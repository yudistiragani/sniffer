from __future__ import annotations

import logging
import time

import greenstalk
from pydantic import ValidationError

from sniffer.device import resolve
from sniffer.executor import execute
from sniffer.integrations.beanstalk import Heartbeat, LeaseLost, connect
from sniffer.jobs import InvalidJob, KeywordJob, SearchJob
from sniffer.runtime import lock
from sniffer.settings import Settings

logger = logging.getLogger(__name__)


def process_reserved(client, raw, settings, device, lease, *, capture=True, frida=False):
    """Process one reserved job; no payload/exception text is written to worker logs."""
    stats = client.stats_job(raw)
    try:
        job = SearchJob.model_validate_json(raw.body)
        with Heartbeat(client, raw, settings.beanstalk, stats["ttr"]) as heartbeat:
            result = execute(
                settings, device, "instagram", job,
                capture=capture, frida=frida, lease=lease, checkpoint=heartbeat.check,
            )
            heartbeat.check()
        heartbeat.check()
    except (ValidationError, InvalidJob):
        client.bury(raw)
        logger.warning("job=%s status=buried_invalid", raw.id)
        return "buried"
    except LeaseLost:
        # No release/delete: this connection can no longer assert ownership.
        raise
    except (KeyboardInterrupt, SystemExit):
        client.release(raw, delay=settings.beanstalk.retry_delay)
        raise
    except Exception as error:
        if stats["reserves"] >= settings.beanstalk.max_reserves:
            client.bury(raw)
            state = "buried"
        else:
            client.release(raw, delay=settings.beanstalk.retry_delay)
            state = "released"
        logger.warning("job=%s status=%s error=%s", raw.id, state, type(error).__name__)
        return state
    # Completion marker was persisted by execute(). Failed ACK will safely replay that marker.
    client.delete(raw)
    logger.info("job=%s status=completed output=%s", raw.id, result.get("output"))
    return "completed"


def run_worker(
    settings: Settings, device: str, platform: str, *,
    capture: bool = True, frida: bool = False, once: bool = False,
) -> None:
    if platform != "instagram":
        raise ValueError("Only the Instagram worker is implemented.")
    resolve(settings, device)
    with lock(settings, f"device-{device}") as lease:
        while True:
            try:
                with connect(settings.beanstalk) as client:
                    logger.info("watching tube=%s device=%s", settings.beanstalk.instagram_tube, device)
                    while True:
                        try:
                            raw = client.reserve(timeout=settings.beanstalk.reserve_timeout)
                        except greenstalk.TimedOutError:
                            if once:
                                return
                            continue
                        process_reserved(
                            client, raw, settings, device, lease, capture=capture, frida=frida
                        )
                        if once:
                            return
            except (OSError, ConnectionError, greenstalk.Error, LeaseLost) as error:
                if once:
                    raise RuntimeError("Beanstalk connection/reservation failed.") from error
                logger.warning("queue unavailable error=%s; reconnect in 5s", type(error).__name__)
                time.sleep(5)


def process_keyword_reserved(client, raw, settings, device, lease, *, server_id, frida_server=None):
    """Pause on any execution error: no unattended repeat attach after crash/refusal."""
    from sniffer.keyword_executor import execute_keyword, queue_job_id

    stats = client.stats_job(raw)
    try:
        data = KeywordJob.model_validate_json(raw.body)
        job = SearchJob(
            job_id=queue_job_id(server_id, settings.beanstalk.instagram_tube, raw.id),
            keyword=data.keyword, scroll_count=10,
        )
        with Heartbeat(client, raw, settings.beanstalk, stats["ttr"]) as heartbeat:
            kwargs = {"lease": lease, "checkpoint": heartbeat.check}
            if frida_server is not None:
                kwargs["frida_server"] = frida_server
            result = execute_keyword(settings, device, job, **kwargs)
            heartbeat.check()
        heartbeat.check()
    except (ValidationError, InvalidJob):
        client.bury(raw)
        logger.warning("job=%s status=buried_invalid", raw.id)
        return "buried"
    except LeaseLost:
        raise
    except (KeyboardInterrupt, SystemExit):
        client.release(raw, delay=settings.beanstalk.retry_delay)
        raise
    except Exception as error:
        if stats["reserves"] >= settings.beanstalk.max_reserves:
            client.bury(raw)
            state = "buried"
        else:
            client.release(raw, delay=settings.beanstalk.retry_delay)
            state = "released"
        logger.error(
            "job=%s status=%s worker=stopped error_type=%s; inspect before restarting",
            raw.id, state, type(error).__name__,
        )
        return "stopped"
    client.delete(raw)
    logger.info(
        "job=%s status=completed automation_only=true proxy_publish_verified=false output=%s",
        raw.id, result.get("output"),
    )
    return "completed"


def run_keyword_worker(settings: Settings, device: str, *, targeted_trial: bool, once: bool = False):
    """Explicitly opted-in worker: one active Frida trial only while handling a job."""
    from sniffer.keyword_executor import queue_job_id

    if not targeted_trial:
        raise ValueError("Keyword worker requires explicit --targeted-trial.")
    target = resolve(settings, device)
    if not target.frida_endpoint:
        raise ValueError("Configure existing Frida endpoint before starting the worker.")
    if settings.platforms["instagram"].frida_scripts:
        raise ValueError("Keyword worker cannot run alongside configured Frida scripts.")
    with lock(settings, f"device-{device}") as lease:
        from sniffer.integrations.frida_server import WorkerFridaServer

        with WorkerFridaServer(target) as frida_server:
            while True:
                try:
                    with connect(settings.beanstalk) as client:
                        server_id = client.stats().get("id")
                        # Completion markers must not collide between queue server instances.
                        queue_job_id(server_id, settings.beanstalk.instagram_tube, 1)
                        logger.info(
                            "keyword worker watching tube=%s device=%s proxy=external",
                            settings.beanstalk.instagram_tube, device,
                        )
                        while True:
                            try:
                                raw = client.reserve(timeout=settings.beanstalk.reserve_timeout)
                            except greenstalk.TimedOutError:
                                if once:
                                    return
                                continue
                            state = process_keyword_reserved(
                                client, raw, settings, device, lease, server_id=server_id,
                                frida_server=frida_server,
                            )
                            if state == "stopped":
                                raise RuntimeError(
                                    "Keyword worker stopped after job failure; inspect before restarting."
                                )
                            if once:
                                return
                except (OSError, ConnectionError, greenstalk.Error, LeaseLost) as error:
                    if once or isinstance(error, LeaseLost):
                        raise RuntimeError("Beanstalk connection/reservation failed; worker stopped.") from error
                    logger.warning("queue unavailable error=%s; reconnect in 5s", type(error).__name__)
                    time.sleep(5)
