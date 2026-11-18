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
