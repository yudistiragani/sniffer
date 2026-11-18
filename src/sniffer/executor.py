from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from sniffer.capture.writer import append_json
from sniffer.device import ADB, resolve
from sniffer.jobs import JobConflict, SearchJob
from sniffer.runtime import atomic_json, lock
from sniffer.settings import Settings

logger = logging.getLogger(__name__)


def job_fingerprint(
    job: SearchJob, *, capture: bool, frida: bool, frida_options: dict | None = None,
) -> str:
    payload = {**job.model_dump(), "capture": capture, "frida": frida}
    if frida_options is not None:
        payload["frida_options"] = frida_options
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def new_session(settings: Settings, platform: str, device: str, **metadata) -> Path:
    from sniffer.settings import safe_name
    safe_name(platform)
    safe_name(device)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = settings.output_dir / f"{stamp}_{platform}_{device}_{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(output / "session.json", {
        "platform": platform, "device": device,
        "domains": settings.platforms[platform].domains,
        "started_at": datetime.now(UTC).isoformat(), **metadata,
    })
    return output


def execute(
    settings: Settings,
    device_name: str,
    platform: str,
    job: SearchJob,
    *,
    capture: bool = True,
    frida: bool = False,
    frida_spawn: bool = True,
    dry_run: bool = False,
    lease: FileLock | None = None,
    checkpoint: Callable[[], None] = lambda: None,
) -> dict:
    if platform != "instagram":
        raise ValueError("Only Instagram search automation is implemented.")
    if platform not in settings.platforms:
        raise ValueError("Platform configuration missing.")
    if not frida_spawn and not frida:
        raise ValueError("--no-frida-spawn requires --frida.")
    device = resolve(settings, device_name)
    if dry_run:
        return {
            "dry_run": True, "platform": platform, "device": device_name,
            "adb_serial": device.adb_serial, "job": job.model_dump(),
            "capture": capture, "frida": frida,
            "frida_spawn": frida_spawn if frida else False,
        }
    fingerprint = job_fingerprint(
        job, capture=capture, frida=frida,
        frida_options={
            "endpoint": device.frida_endpoint, "device_id": device.frida_device_id,
            "scripts": settings.platforms[platform].frida_scripts,
            "allow_spawn": frida_spawn,
        } if frida else None,
    )
    completion = settings.state_dir / "completed" / platform / f"{job.job_id}.json"
    with lock(settings, f"job-{platform}-{job.job_id}"), (
        lease if lease is not None else lock(settings, f"device-{device_name}")
    ):
        if completion.exists():
            previous = json.loads(completion.read_text(encoding="utf-8"))
            if previous["fingerprint"] != fingerprint:
                raise JobConflict("Job ID reused with different payload/options; refusing ambiguous replay.")
            checkpoint()
            return {**previous["result"], "already_completed": True}
        checkpoint()
        adb = ADB(device.adb_serial)
        adb.ready(connect=True)
        adb.require_package(settings.platforms[platform].package)
        output = new_session(
            settings, platform, device_name, job_id=job.job_id,
            keyword=job.keyword, capture=capture, frida=frida,
            frida_scripts=settings.platforms[platform].frida_scripts if frida else [],
            frida_spawn=frida_spawn if frida else False,
        )
        logger.info("Session output=%s", output.resolve())
        def event(phase):
            append_json(output / "events.jsonl", {
                "job_id": job.job_id, "phase": phase, "at": datetime.now(UTC).isoformat(),
            })

        try:
            event("session_started")
            with ExitStack() as stack:
                proxy = None
                if capture:
                    from sniffer.integrations.mitmproxy import ProxyCapture
                    proxy = stack.enter_context(ProxyCapture(settings, device, output))
                    event("capture_ready")
                from sniffer.integrations.appium import session
                driver = stack.enter_context(session(device, settings.platforms[platform]))
                instrumentation = None
                if frida:
                    from sniffer.integrations.frida import Instrumentation
                    instrumentation = stack.enter_context(
                        Instrumentation(
                            device, settings.platforms[platform], output, allow_spawn=frida_spawn,
                        )
                    )
                    instrumentation.check()
                if frida and not frida_spawn:
                    if driver.current_package != settings.platforms[platform].package:
                        raise RuntimeError(
                            "Attach-only mode requires Instagram already open in the foreground; "
                            "no app was activated."
                        )
                    instrumentation.check()
                    event("application_foreground_verified")
                else:
                    driver.activate_app(settings.platforms[platform].package)
                    event("application_activated")

                def health():
                    checkpoint()
                    if proxy:
                        proxy.require_alive()
                    if instrumentation:
                        instrumentation.check()

                from sniffer.platforms.instagram.executor import search
                event("search_started")
                result = search(driver, settings.platforms[platform], job, health)
                event("search_finished")
                # Allow responses triggered by the last action to arrive.
                if proxy:
                    for _ in range(5):
                        health()
                        time.sleep(0.2)
                health()
            checkpoint()
            traffic_file = output / "requests.jsonl"
            count = 0
            verified_search_responses = 0
            partial_search_responses = 0
            if traffic_file.exists():
                with traffic_file.open(encoding="utf-8") as handle:
                    for line in handle:
                        record = json.loads(line)
                        count += record["kind"] != "transport_error"
                        if record["kind"] == "instagram_search" and record.get("keyword") == job.keyword:
                            verified = (
                                record.get("keyword_matched") is True
                                and record.get("stream_complete") is True
                                and record.get("post_count", 0) > 0
                                and 200 <= record.get("status_code", 0) < 300
                            )
                            verified_search_responses += verified
                            partial_search_responses += not verified
            if capture and count == 0:
                raise RuntimeError(
                    "No matching HTTP responses captured. Check proxy, trust, domains, and app transport."
                )
            result.update(job_id=job.job_id, output=str(output.resolve()))
            result["captured_responses"] = count
            result["semantic_search_results_verified"] = verified_search_responses > 0
            result["verified_search_responses"] = verified_search_responses
            result["partial_search_responses"] = partial_search_responses
            event("completed")
            atomic_json(output / "result.json", result)
            atomic_json(completion, {"fingerprint": fingerprint, "result": result})
            return result
        except BaseException as error:
            event("failed")
            atomic_json(output / "failure.json", {
                "job_id": job.job_id, "error_type": type(error).__name__,
                "finished_at": datetime.now(UTC).isoformat(),
            })
            raise
