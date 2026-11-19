"""Explicit bounded search -> remote mitmweb GET -> posts -> outgoing Beanstalk."""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import ExitStack

from sniffer.device import ADB, resolve
from sniffer.executor import new_session
from sniffer.integrations.mitmweb import RemoteCapture, validate_remote
from sniffer.jobs import SearchJob
from sniffer.results import connect_results, message_limit, prepare_outbox, publish_outbox
from sniffer.runtime import atomic_json, lock

logger = logging.getLogger(__name__)


def collect(settings, device_name: str, job: SearchJob, *, trial: bool, publish: bool, dry_run=False):
    if not trial:
        raise ValueError("This collect mode requires explicit --targeted-trial consent (max120s).")
    if job.scroll_count != 10:
        raise ValueError("This controlled collect mode performs exactly10 scrolls.")
    device = resolve(settings, device_name)
    origin = validate_remote(settings.remote_mitmweb)
    if settings.results.tube == settings.beanstalk.instagram_tube:
        raise ValueError("Results tube must differ from the input job tube.")
    if not device.frida_endpoint:
        raise ValueError("Set the existing loopback-forwarded Frida endpoint explicitly.")
    if settings.platforms["instagram"].frida_scripts:
        raise ValueError("Collect trial must not be combined with configured observer/other scripts.")
    if dry_run:
        return {
            "dry_run": True, "device": device_name, "job": job.model_dump(),
            "capture": "remote_mitmweb_readonly", "trial_max_seconds": 120,
            "publish": publish, "results": settings.results.model_dump(),
            "proxy_settings_changed": False,
        }
    resource = hashlib.sha256(
        (origin + "|" + settings.remote_mitmweb.client_ip).encode()
    ).hexdigest()[:24]
    with lock(settings, f"device-{device_name}"), lock(settings, f"remote-capture-{resource}"):
        # Check the destination before spending the trial window. No test messages are put.
        if publish:
            try:
                with connect_results(settings.results) as client:
                    message_limit(client, settings.results)
            except Exception:
                raise RuntimeError("Results queue preflight failed; automation was not started.") from None
        adb = ADB(device.adb_serial)
        adb.ready(connect=True)
        adb.require_package("com.instagram.android")
        output = new_session(
            settings, "instagram", device_name, job_id=job.job_id, keyword=job.keyword,
            capture="remote_mitmweb_readonly", targeted_trial_seconds=120,
            requested_scrolls=10, publish_requested=publish,
        )
        logger.info("Collect output=%s", output.resolve())
        try:
            from sniffer.integrations.appium import session
            from sniffer.integrations.trial_repl import TrialREPL
            from sniffer.platforms.instagram.executor import search
            with ExitStack() as stack:
                driver = stack.enter_context(session(device, settings.platforms["instagram"]))
                if driver.current_package != "com.instagram.android":
                    raise RuntimeError("Open Instagram in foreground manually; collect never activates/restarts it.")
                capture = stack.enter_context(RemoteCapture(
                    settings.remote_mitmweb,
                    {
                        "platform": "instagram", "domains": ["instagram.com"],
                        "job_id": job.job_id, "keyword": job.keyword, "post_output": "memory",
                    },
                    output,
                ))
                instrumentation = stack.enter_context(TrialREPL(device, output))
                capture.arm()  # Exclude setup/prefetch flows before the actual controlled search.

                def health():
                    instrumentation.check()
                    if driver.current_package != "com.instagram.android":
                        raise RuntimeError("Instagram left foreground; stop the collect run.")
                    capture.poll()
                    instrumentation.check()

                # No activate_app, second hook, local mitmdump or proxy provisioning.
                result = search(driver, settings.platforms["instagram"], job, health)
                deadline = time.monotonic() + settings.remote_mitmweb.settle_seconds
                while time.monotonic() < deadline:
                    health()
                    time.sleep(0.2)
                capture.poll(force=True)
                instrumentation.check()
                if result.get("scrolls") != 10 or capture.matched == 0:
                    raise RuntimeError("Ten scrolls and matching remote search responses were not confirmed.")
            writer = getattr(capture.recorder, "post_writer", None)
            if writer is None or not writer.posts:
                raise RuntimeError("No parsed search posts; nothing was published.")
            result.update(
                job_id=job.job_id, output=str(output.resolve()),
                capture="remote_mitmweb_readonly", matched_search_responses=capture.matched,
                complete_search_responses=capture.complete,
                partial_search_responses=capture.partial,
                semantic_search_results_verified=capture.verified > 0,
                search_results_exhaustive=False, publish_requested=publish,
            )
            # Persist outbox before any put, including capture-only runs.
            prepare_outbox(
                output, settings.results, job_id=job.job_id, device=device_name, keyword=job.keyword,
                posts=writer.posts.values(),
            )
            atomic_json(output / "capture-result.json", result)
            if publish:
                result.update(publish_outbox(output))
            atomic_json(output / "result.json", result)
            return result
        except BaseException as error:
            atomic_json(output / "failure.json", {"error_type": type(error).__name__})
            raise
