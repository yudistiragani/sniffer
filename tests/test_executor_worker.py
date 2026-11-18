import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sniffer import executor, worker
from sniffer.integrations.beanstalk import Heartbeat, LeaseLost
from sniffer.jobs import InvalidJob, JobConflict, SearchJob
from sniffer.runtime import atomic_json, lock


def test_dry_run_has_no_side_effects(settings, monkeypatch):
    monkeypatch.setattr(executor, "ADB", lambda *_: pytest.fail("no ADB"))
    result = executor.execute(
        settings, "android01", "instagram", SearchJob(job_id="j1", keyword="coffee"), dry_run=True
    )
    assert result["dry_run"] is True
    assert not settings.state_dir.exists() and not settings.output_dir.exists()


def test_completed_job_replayed_without_device_connection(settings, monkeypatch):
    job = SearchJob(job_id="j1", keyword="coffee")
    marker = settings.state_dir / "completed" / "instagram" / "j1.json"
    atomic_json(marker, {
        "fingerprint": executor.job_fingerprint(job, capture=True, frida=False),
        "result": {"job_id": "j1", "output": "old-output"},
    })
    monkeypatch.setattr(executor, "ADB", lambda *_: pytest.fail("no repeated ADB"))
    assert executor.execute(settings, "android01", "instagram", job)["already_completed"]
    with pytest.raises(JobConflict):
        executor.execute(settings, "android01", "instagram", job.model_copy(update={"keyword": "tea"}))


def test_job_fingerprint_changes_with_frida_script_selection():
    job = SearchJob(job_id="frida-options", keyword="coffee")
    first = executor.job_fingerprint(
        job, capture=False, frida=True, frida_options={"scripts": ["shared/observe.js"]}
    )
    second = executor.job_fingerprint(
        job, capture=False, frida=True, frida_options={"scripts": ["shared/tls_observer.js"]}
    )
    assert first != second


def raw_job(body=None):
    return SimpleNamespace(id=42, body=body or '{"job_id":"j1","keyword":"coffee"}')


def test_worker_ack_after_success(settings, monkeypatch):
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": 1}
    def fake(*args, **kwargs):
        kwargs["checkpoint"]()
        assert not client.delete.called
        return {"output": "saved"}
    monkeypatch.setattr(worker, "execute", fake)
    with lock(settings, "device-android01") as lease:
        assert worker.process_reserved(client, raw_job(), settings, "android01", lease) == "completed"
    client.touch.assert_called()
    client.delete.assert_called_once()
    client.release.assert_not_called()


@pytest.mark.parametrize("body", ['not-json', '{"job_id":"x","keyword":"a","shell":"oops"}'])
def test_worker_buries_invalid(settings, body):
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": 1}
    assert worker.process_reserved(client, raw_job(body), settings, "android01", None) == "buried"
    client.bury.assert_called_once()
    client.delete.assert_not_called()


@pytest.mark.parametrize("reserves,expected", [(1, "released"), (3, "buried")])
def test_worker_bounded_retry(settings, monkeypatch, reserves, expected):
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": reserves}
    monkeypatch.setattr(worker, "execute", MagicMock(side_effect=RuntimeError("transient")))
    assert worker.process_reserved(client, raw_job(), settings, "android01", None) == expected
    client.delete.assert_not_called()
    if expected == "released":
        client.release.assert_called_once()
    else:
        client.bury.assert_called_once()


def test_worker_shutdown_releases_job(settings, monkeypatch):
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": 1}
    monkeypatch.setattr(worker, "execute", MagicMock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        worker.process_reserved(client, raw_job(), settings, "android01", None)
    client.release.assert_called_once()
    client.delete.assert_not_called()


def test_short_ttr_is_invalid(settings):
    with pytest.raises(InvalidJob):
        Heartbeat(MagicMock(), raw_job(), settings.beanstalk, 5)


def test_heartbeat_uses_same_connection_and_reports_loss(settings):
    client = MagicMock()
    with Heartbeat(client, raw_job(), settings.beanstalk, 120) as heartbeat:
        heartbeat.lost.set()
        with pytest.raises(LeaseLost):
            heartbeat.check()
    client.touch.assert_called_once()
    assert not heartbeat.thread.is_alive()


def test_lost_lease_never_acknowledges(settings, monkeypatch):
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": 1}
    monkeypatch.setattr(worker, "execute", MagicMock(side_effect=LeaseLost("gone")))
    with pytest.raises(LeaseLost):
        worker.process_reserved(client, raw_job(), settings, "android01", None)
    client.delete.assert_not_called()
    client.release.assert_not_called()
    client.bury.assert_not_called()


def test_executor_ui_only_cleanup_and_completion(settings, monkeypatch):
    driver = MagicMock()
    adb = MagicMock()
    monkeypatch.setattr(executor, "ADB", lambda *_: adb)
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    monkeypatch.setattr(
        "sniffer.platforms.instagram.executor.search",
        lambda *_: {"scrolls": 1},
    )
    job = SearchJob(job_id="ui-only", keyword="coffee")
    result = executor.execute(settings, "android01", "instagram", job, capture=False)
    assert result["captured_responses"] == 0
    assert not result["semantic_search_results_verified"]
    driver.quit.assert_called_once()
    assert (settings.state_dir / "completed/instagram/ui-only.json").exists()


def test_executor_failure_cleans_session_without_success_marker(settings, monkeypatch):
    driver = MagicMock()
    monkeypatch.setattr(executor, "ADB", lambda *_: MagicMock())
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    monkeypatch.setattr(
        "sniffer.platforms.instagram.executor.search", MagicMock(side_effect=RuntimeError("UI failed"))
    )
    with pytest.raises(RuntimeError, match="UI failed"):
        executor.execute(
            settings, "android01", "instagram", SearchJob(job_id="failed", keyword="coffee"),
            capture=False,
        )
    driver.quit.assert_called_once()
    assert list(settings.output_dir.glob("*/failure.json"))
    assert not (settings.state_dir / "completed/instagram/failed.json").exists()


def test_empty_capture_is_not_acknowledged_as_success(settings, monkeypatch):
    driver = MagicMock()
    monkeypatch.setattr(executor, "ADB", lambda *_: MagicMock())
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    monkeypatch.setattr("sniffer.integrations.mitmproxy.ProxyCapture", MagicMock())
    monkeypatch.setattr("sniffer.platforms.instagram.executor.search", lambda *_: {"scrolls": 0})
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="No matching HTTP"):
        executor.execute(
            settings, "android01", "instagram", SearchJob(job_id="empty", keyword="coffee")
        )
    assert not (settings.state_dir / "completed/instagram/empty.json").exists()
    driver.quit.assert_called_once()


@pytest.mark.parametrize("foreground", [True, False])
def test_attach_only_never_activates_or_spawns_app(settings, monkeypatch, foreground):
    driver = MagicMock()
    driver.current_package = "com.instagram.android" if foreground else "com.android.launcher3"
    monkeypatch.setattr(executor, "ADB", lambda *_: MagicMock())
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    instrumentation = MagicMock()
    monkeypatch.setattr("sniffer.integrations.frida.Instrumentation", instrumentation)
    search = MagicMock(return_value={"scrolls": 0})
    monkeypatch.setattr("sniffer.platforms.instagram.executor.search", search)
    job = SearchJob(job_id="attach-only", keyword="coffee", scroll_count=0)
    if foreground:
        executor.execute(
            settings, "android01", "instagram", job,
            capture=False, frida=True, frida_spawn=False,
        )
        search.assert_called_once()
    else:
        with pytest.raises(RuntimeError, match="already open in the foreground"):
            executor.execute(
                settings, "android01", "instagram", job,
                capture=False, frida=True, frida_spawn=False,
            )
        search.assert_not_called()
    assert instrumentation.call_args.kwargs["allow_spawn"] is False
    driver.activate_app.assert_not_called()
    driver.quit.assert_called_once()


@pytest.mark.parametrize("mode,verified", [
    ("complete", True), ("partial", False), ("mismatch", False),
    ("empty", False), ("http_error", False), ("unmapped", False),
])
def test_executor_semantic_acceptance_is_keyword_and_completion_scoped(
    settings, monkeypatch, mode, verified,
):
    driver = MagicMock()
    monkeypatch.setattr(executor, "ADB", lambda *_: MagicMock())
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    def proxy(_settings, _device, output):
        record = {
            "kind": "instagram_search" if mode != "unmapped" else "unmapped_json",
            "keyword": "coffee" if mode != "mismatch" else "tea",
            "keyword_matched": mode != "mismatch",
            "stream_complete": mode != "partial",
            "post_count": 0 if mode == "empty" else 3,
            "status_code": 500 if mode == "http_error" else 200,
        }
        (output / "requests.jsonl").write_text(json.dumps(record) + "\n")
        return MagicMock()
    monkeypatch.setattr("sniffer.integrations.mitmproxy.ProxyCapture", proxy)
    monkeypatch.setattr("sniffer.platforms.instagram.executor.search", lambda *_: {"scrolls": 0})
    monkeypatch.setattr(executor.time, "sleep", lambda _: None)
    result = executor.execute(
        settings, "android01", "instagram", SearchJob(job_id=f"parse-{mode}", keyword="coffee"),
    )
    assert result["semantic_search_results_verified"] is verified
    assert result["verified_search_responses"] == int(verified)
