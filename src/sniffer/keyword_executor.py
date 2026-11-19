"""Per-job UI automation against an externally managed proxy; no result publishing."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import ExitStack

from sniffer.device import ADB, resolve
from sniffer.executor import new_session
from sniffer.jobs import JobConflict, SearchJob
from sniffer.runtime import atomic_json, lock

logger = logging.getLogger(__name__)


def ensure_instagram_ready(driver, adb, package, checkpoint, *, timeout=20):
    """Launch once only if needed, then wait for foreground + one existing main PID."""
    checkpoint()
    if package != "com.instagram.android":
        raise RuntimeError("Keyword worker can only open the configured Instagram package.")
    if driver.current_package != package:
        logger.info("IG foreground status=LAUNCH_START mode=android_launcher")
        # Resolve dynamically; accept only a single shell-safe component in IG.
        resolved = adb.command(
            "shell", "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
            package, check=False,
        )
        checkpoint()
        components = [
            line.strip() for line in resolved.stdout.splitlines()
            if re.fullmatch(
                r"com\.instagram\.android/(?:\.[A-Za-z_][A-Za-z0-9_.]*"
                r"|com\.instagram\.android\.[A-Za-z_][A-Za-z0-9_.]*)",
                line.strip(),
            )
        ]
        if resolved.returncode != 0 or len(components) != 1:
            raise RuntimeError("Instagram launcher activity could not be resolved uniquely.")
        logger.info("IG foreground status=LAUNCHER_RESOLVED")
        # am start without -S; no force-stop, clear/reset, Frida spawn or kill.
        result = adb.command(
            "shell", "am", "start", "-n", components[0],
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
            check=False,
        )
        if result.returncode != 0 or re.search(r"(?im)^\s*(?:error|exception):", result.stdout):
            raise RuntimeError("Instagram launcher failed; no further launch attempt was made.")
        checkpoint()
        logger.info("IG foreground status=LAUNCH_SENT")
    else:
        logger.info("IG foreground status=ALREADY_OPEN")
    deadline = time.monotonic() + timeout
    while True:
        checkpoint()
        foreground = driver.current_package == package
        result = adb.command("shell", "pidof", package, check=False)
        pids = result.stdout.split() if result.returncode == 0 else []
        if result.returncode not in (0, 1):
            raise RuntimeError("Cannot inspect Instagram PID; no retry or process restart.")
        if len(pids) > 1 or any(not pid.isdecimal() or int(pid) <= 0 for pid in pids):
            raise RuntimeError("Instagram main PID is ambiguous; no Frida attach was attempted.")
        if foreground and len(pids) == 1:
            checkpoint()
            logger.info("IG foreground status=READY pid=%s", pids[0])
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Instagram foreground/main PID not ready before timeout; job stopped.")
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


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
        phase = "appium_setup"
        try:
            from sniffer.integrations.appium import session
            from sniffer.integrations.trial_repl import TrialREPL
            from sniffer.platforms.instagram.executor import search

            with ExitStack() as stack:
                driver = stack.enter_context(session(device, settings.platforms["instagram"]))
                checkpoint()
                phase = "foreground_and_pid"
                ensure_instagram_ready(driver, adb, settings.platforms["instagram"].package, checkpoint)
                phase = "frida_attach"
                trial = stack.enter_context(TrialREPL(device, output))
                logger.info("IG targeted_trial status=READY duration_ms=120000")

                def health():
                    checkpoint()
                    trial.check()
                    if driver.current_package != settings.platforms["instagram"].package:
                        raise RuntimeError("Instagram left foreground; job stopped.")
                    trial.check()
                    checkpoint()

                health()
                phase = "search_and_scroll"
                result = search(driver, settings.platforms["instagram"], job, health)
                if result.get("scrolls") != 10:
                    raise RuntimeError("The ten requested scroll gestures were not completed.")
                # Give final proxied requests a bounded window before detaching the hook.
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    health()
                    time.sleep(min(0.2, max(0, until - time.monotonic())))
                health()
                phase = "owned_cleanup"
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
            logger.error("IG job status=FAILED phase=%s error_type=%s", phase, type(error).__name__)
            atomic_json(output / "failure.json", {"phase": phase, "error_type": type(error).__name__})
            raise
