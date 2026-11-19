"""Per-job UI automation against an externally managed proxy; no result publishing."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import ExitStack

from sniffer.device import ADB, resolve
from sniffer.executor import new_session
from sniffer.jobs import JobConflict, SearchJob
from sniffer.runtime import atomic_json, lock

logger = logging.getLogger(__name__)


def queue_job_id(server_id: str, tube: str, job_id: int) -> str:
    if not isinstance(server_id, str) or not server_id or len(server_id) > 256:
        raise ValueError("Beanstalk server identity is required.")
    if type(job_id) is not int or job_id <= 0:
        raise ValueError("Invalid Beanstalk job ID.")
    identity = json.dumps([server_id, tube, job_id], ensure_ascii=True).encode()
    return "queue-" + hashlib.sha256(identity).hexdigest()


def execute_keyword(settings, device_name, job: SearchJob, *, lease, checkpoint):
    """One accepted reservation; caller owns the device lease and queue heartbeat."""
    device = resolve(settings, device_name)
    if not device.frida_endpoint:
        raise RuntimeError("Configure the existing Frida endpoint; no server will be started.")
    if settings.platforms["instagram"].frida_scripts:
        raise RuntimeError("Remove configured Frida scripts; targeted job trial cannot share hooks.")
    if job.scroll_count != 10:
        raise ValueError("Keyword worker requires exactly10 scroll gestures.")
    fingerprint = hashlib.sha256(
        json.dumps({"job": job.model_dump(), "mode": "external-proxy-targeted-v1"}, sort_keys=True).encode()
    ).hexdigest()
    completion = settings.state_dir / "completed" / "instagram-keyword" / f"{job.job_id}.json"
    with lock(settings, f"job-{job.job_id}"):
        if completion.exists():
            previous = json.loads(completion.read_text(encoding="utf-8"))
            if previous.get("fingerprint") != fingerprint:
                raise JobConflict("Queue job identity reused with different keyword/options.")
            checkpoint()
            return {**previous["result"], "already_completed": True}
        checkpoint()
        adb = ADB(device.adb_serial)
        adb.ready(connect=True)
        adb.require_package(settings.platforms["instagram"].package)
        output = new_session(
            settings, "instagram", device_name, job_id=job.job_id, keyword=job.keyword,
            capture="external_proxy_unverified", targeted_trial_seconds=120,
            requested_scrolls=10,
        )
        logger.info("Keyword job session output=%s", output.resolve())
        try:
            from sniffer.integrations.appium import session
            from sniffer.integrations.trial_repl import TrialREPL
            from sniffer.platforms.instagram.executor import search

            with ExitStack() as stack:
                driver = stack.enter_context(session(device, settings.platforms["instagram"]))
                checkpoint()
                if driver.current_package != settings.platforms["instagram"].package:
                    raise RuntimeError("Instagram must already be open in foreground.")
                trial = stack.enter_context(TrialREPL(device, output))

                def health():
                    checkpoint()
                    trial.check()
                    if driver.current_package != settings.platforms["instagram"].package:
                        raise RuntimeError("Instagram left foreground; job stopped.")
                    trial.check()
                    checkpoint()

                health()
                result = search(driver, settings.platforms["instagram"], job, health)
                if result.get("scrolls") != 10:
                    raise RuntimeError("The ten requested scroll gestures were not completed.")
                # Give final proxied requests a bounded window before detaching the hook.
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    health()
                    time.sleep(min(0.2, max(0, until - time.monotonic())))
                health()
            # Trial and Appium cleanup must have succeeded before marking/ACK.
            checkpoint()
            result.update(
                job_id=job.job_id, output=str(output.resolve()),
                capture="external_proxy_unverified",
                proxy_capture_verified=False, proxy_publish_verified=False,
                semantic_search_results_verified=False,
            )
            atomic_json(output / "result.json", result)
            atomic_json(completion, {"fingerprint": fingerprint, "result": result})
            return result
        except BaseException as error:
            atomic_json(output / "failure.json", {"error_type": type(error).__name__})
            raise
