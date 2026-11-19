import socketserver
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import greenstalk
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sniffer import keyword_executor, worker
from sniffer.cli import app
from sniffer.integrations.beanstalk import LeaseLost
from sniffer.jobs import JobConflict, KeywordJob, SearchJob
from sniffer.runtime import lock


def raw(body='{"keyword":"prabowo"}', job_id=42):
    return SimpleNamespace(id=job_id, body=body)


def queue():
    client = MagicMock()
    client.stats_job.return_value = {"ttr": 120, "reserves": 1}
    return client


def job():
    return SearchJob(job_id=keyword_executor.queue_job_id("server-instance", "jobs", 42),
                     keyword="prabowo", scroll_count=119)


@pytest.mark.parametrize("body", [
    "not-json", "{}", '{"keyword":""}', '{"keyword":"   "}', '{"keyword":2}',
    '{"keyword":"x","scroll_count":500}', '{"keyword":"x","script":"bad"}',
])
def test_keyword_payload_rejects_invalid_or_extra_fields(settings, body, monkeypatch):
    client = queue()
    fake = MagicMock()
    monkeypatch.setattr(keyword_executor, "execute_keyword", fake)
    assert worker.process_keyword_reserved(
        client, raw(body), settings, "android01", None, server_id="server-instance",
    ) == "buried"
    client.bury.assert_called_once()
    client.delete.assert_not_called()
    fake.assert_not_called()


def test_minimal_job_exact_ten_scrolls_and_ack_after_cleanup(settings, monkeypatch):
    client = queue()
    def execute(_settings, _device, value, *, lease, checkpoint):
        assert value.keyword == "prabowo" and value.scroll_count == 119
        checkpoint()
        client.delete.assert_not_called()
        return {"output": "synthetic"}
    monkeypatch.setattr(keyword_executor, "execute_keyword", execute)
    assert worker.process_keyword_reserved(
        client, raw(), settings, "android01", None, server_id="server-instance",
    ) == "completed"
    client.touch.assert_called()
    client.delete.assert_called_once()
    client.release.assert_not_called()


@pytest.mark.parametrize("reserves,action", [(1, "release"), (3, "bury")])
def test_trial_failure_pauses_worker_without_automatic_retry(settings, monkeypatch, reserves, action):
    client = queue()
    client.stats_job.return_value["reserves"] = reserves
    monkeypatch.setattr(keyword_executor, "execute_keyword", MagicMock(side_effect=RuntimeError("failed")))
    assert worker.process_keyword_reserved(
        client, raw(), settings, "android01", None, server_id="server-instance",
    ) == "stopped"
    getattr(client, action).assert_called_once()
    client.delete.assert_not_called()


@pytest.mark.parametrize("error", [LeaseLost("lost"), KeyboardInterrupt()])
def test_lease_loss_and_shutdown_never_ack(settings, monkeypatch, error):
    client = queue()
    monkeypatch.setattr(keyword_executor, "execute_keyword", MagicMock(side_effect=error))
    with pytest.raises(type(error)):
        worker.process_keyword_reserved(
            client, raw(), settings, "android01", None, server_id="server-instance",
        )
    client.delete.assert_not_called()
    if isinstance(error, LeaseLost):
        client.release.assert_not_called()
    else:
        client.release.assert_called_once()


def test_ids_include_server_instance_tube_and_queue_id():
    first = keyword_executor.queue_job_id("server-one", "tube", 1)
    assert first == keyword_executor.queue_job_id("server-one", "tube", 1)
    assert first != keyword_executor.queue_job_id("server-two", "tube", 1)
    assert first != keyword_executor.queue_job_id("server-one", "other", 1)
    assert first != keyword_executor.queue_job_id("server-one", "tube", 2)
    with pytest.raises(ValueError):
        keyword_executor.queue_job_id("", "tube", 1)


@pytest.mark.parametrize("failure", [None, "foreground", "trial", "search", "scrolls", "cleanup", "lease"])
def test_keyword_executor_scopes_trial_to_job_and_no_capture(settings, monkeypatch, failure):
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    driver = MagicMock(current_package="other" if failure == "foreground" else "com.instagram.android")
    events = []
    adb = MagicMock()
    monkeypatch.setattr(keyword_executor, "ADB", lambda *_: adb)
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    def ready(*_args):
        if failure == "foreground":
            raise RuntimeError("foreground timeout")
    monkeypatch.setattr(keyword_executor, "ensure_instagram_ready", ready)
    @contextmanager
    def trial(*_, **kwargs):
        assert kwargs == {"duration_seconds": 300}
        events.append("attach")
        if failure == "trial":
            raise RuntimeError("refused")
        instance = MagicMock()
        try:
            yield instance
        finally:
            events.append("detach")
            if failure == "cleanup":
                raise RuntimeError("cleanup failed")
    monkeypatch.setattr("sniffer.integrations.trial_repl.TrialREPL", trial)
    def search(_driver, _platform, value, health):
        assert value.scroll_count == 119
        health()
        if failure == "search":
            raise RuntimeError("search failed")
        return {
            "scrolls": 118 if failure == "scrolls" else 119,
            "first_result_tapped": True,
        }
    monkeypatch.setattr(
        "sniffer.platforms.instagram.automation.search_open_first_post_and_scroll", search,
    )
    class Clock:
        now = 0
        def monotonic(self):
            self.now += 1
            return self.now
        def sleep(self, _):
            pass
    monkeypatch.setattr(keyword_executor, "time", Clock())
    monkeypatch.setattr("sniffer.integrations.mitmproxy.ProxyCapture", lambda *_: pytest.fail("no local proxy"))
    def checkpoint():
        if failure == "lease" and events:
            raise LeaseLost("lease lost")
    with lock(settings, "device-android01") as lease:
        if failure:
            with pytest.raises((RuntimeError, LeaseLost)):
                keyword_executor.execute_keyword(
                    settings, "android01", job(), lease=lease, checkpoint=checkpoint,
                )
        else:
            result = keyword_executor.execute_keyword(
                settings, "android01", job(), lease=lease, checkpoint=checkpoint,
            )
            assert result["scrolls"] == 119
            assert not result["proxy_capture_verified"] and not result["proxy_publish_verified"]
            assert events == ["attach", "detach"]
            assert not list(settings.output_dir.glob("*/posts.jsonl"))
            assert not list(settings.output_dir.glob("*/result-outbox.json"))
            monkeypatch.setattr(keyword_executor, "ADB", lambda *_: pytest.fail("no replay device"))
            assert keyword_executor.execute_keyword(
                settings, "android01", job(), lease=lease, checkpoint=checkpoint,
            )["already_completed"]
        driver.activate_app.assert_not_called()
        driver.quit.assert_called_once()
        if failure != "foreground":
            assert events[0] == "attach"
        if failure in {"search", "scrolls", "cleanup", "lease"}:
            assert events[-1] == "detach"
        marker = settings.state_dir / "completed" / "instagram-keyword" / f"{job().job_id}.json"
        assert marker.exists() is (failure is None)


def test_auto_launch_once_then_wait_for_one_pid_and_foreground():
    driver = MagicMock()
    type(driver).current_package = property(
        lambda self: next(self._foreground, "com.instagram.android")
    )
    driver._foreground = iter(["launcher", "launcher", "com.instagram.android"])
    adb = MagicMock()
    adb.command.side_effect = [
        SimpleNamespace(returncode=0, stdout=(
            "priority=0 preferredOrder=0 match=0x108000\n"
            "com.instagram.android/.activity.MainTabActivity\n"
        )),
        SimpleNamespace(returncode=0, stdout="Starting: Intent"),
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout="1234\n"),
    ]
    checkpoint = MagicMock()
    keyword_executor.ensure_instagram_ready(
        driver, adb, "com.instagram.android", checkpoint, timeout=3,
    )
    assert adb.command.call_args_list[0].args == (
        "shell", "cmd", "package", "resolve-activity", "--brief",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
        "com.instagram.android",
    )
    assert adb.command.call_args_list[1].args == (
        "shell", "am", "start", "-n", "com.instagram.android/.activity.MainTabActivity",
        "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
    )
    assert sum(call.args[:3] == ("shell", "am", "start") for call in adb.command.call_args_list) == 1
    assert checkpoint.call_count >= 4
    assert all(not any(x in {"clear", "force-stop", "kill"} for x in call.args)
               for call in adb.command.call_args_list)


def test_already_foreground_does_not_launch_or_reset():
    driver = MagicMock(current_package="com.instagram.android")
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(returncode=0, stdout="1234\n")
    keyword_executor.ensure_instagram_ready(driver, adb, "com.instagram.android", lambda: None)
    adb.command.assert_called_once_with(
        "shell", "pidof", "com.instagram.android", check=False,
    )
    driver.activate_app.assert_not_called()


@pytest.mark.parametrize("mode", [
    "timeout", "ambiguous", "pid_error", "launch_error", "launch_stdout_error", "lease_lost",
    "resolve_missing", "resolve_other", "resolve_injection", "resolve_ambiguous",
])
def test_auto_launch_failure_never_attaches_or_retries(mode):
    driver = MagicMock(current_package="launcher")
    adb = MagicMock()
    resolved = "com.instagram.android/.activity.MainTabActivity"
    responses = [
        SimpleNamespace(returncode=0, stdout=resolved),
        SimpleNamespace(returncode=0, stdout="Starting: Intent"),
        SimpleNamespace(returncode=1, stdout=""),
    ]
    if mode == "ambiguous":
        driver.current_package = "com.instagram.android"
        responses = [SimpleNamespace(returncode=0, stdout="12 34")]
    elif mode == "pid_error":
        driver.current_package = "com.instagram.android"
        responses = [SimpleNamespace(returncode=2, stdout="")]
    elif mode == "launch_error":
        responses[1].returncode = 1
    elif mode == "launch_stdout_error":
        responses[1].stdout = "Error: Activity not started"
    elif mode == "resolve_missing":
        responses[0].stdout = "No activity found"
    elif mode == "resolve_other":
        responses[0].stdout = "com.other/.Main"
    elif mode == "resolve_injection":
        responses[0].stdout = resolved + ";clear data"
    elif mode == "resolve_ambiguous":
        responses[0].stdout = resolved + "\n" + resolved
    adb.command.side_effect = responses
    def checkpoint():
        if mode == "lease_lost":
            raise LeaseLost("lost")
    with pytest.raises((RuntimeError, LeaseLost)):
        keyword_executor.ensure_instagram_ready(
            driver, adb, "com.instagram.android", checkpoint, timeout=0,
        )
    launches = [call for call in adb.command.call_args_list if call.args[:3] == ("shell", "am", "start")]
    assert len(launches) <= 1
    if mode.startswith("resolve_") or mode == "lease_lost":
        assert not launches
    assert all(not any(arg in {"-S", "force-stop", "clear", "kill"} for arg in call.args)
               for call in adb.command.call_args_list)
    driver.activate_app.assert_not_called()


def test_keyword_replay_conflict_stops_without_device(settings, monkeypatch):
    from sniffer.runtime import atomic_json
    first = job()
    marker = settings.state_dir / "completed" / "instagram-keyword" / f"{first.job_id}.json"
    atomic_json(marker, {"fingerprint": "different", "result": {}})
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    monkeypatch.setattr(keyword_executor, "ADB", lambda *_: pytest.fail("no device"))
    with pytest.raises(JobConflict, match="identity"):
        keyword_executor.execute_keyword(settings, "android01", first, lease=None, checkpoint=lambda: None)


def test_keyword_worker_does_not_attach_while_waiting(settings, monkeypatch):
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"id": "server-instance"}
    client.reserve.side_effect = greenstalk.TimedOutError()
    monkeypatch.setattr(worker, "connect", lambda _: client)
    monkeypatch.setattr(keyword_executor, "execute_keyword", lambda *_args, **_kwargs: pytest.fail("no attach"))
    worker.run_keyword_worker(settings, "android01", targeted_trial=True, once=True)
    client.delete.assert_not_called()


def test_worker_stops_on_execution_failure_instead_of_reserving_again(settings, monkeypatch):
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    client = queue()
    client.__enter__.return_value = client
    client.stats.return_value = {"id": "server-instance"}
    client.reserve.return_value = raw()
    monkeypatch.setattr(worker, "connect", lambda _: client)
    monkeypatch.setattr(keyword_executor, "execute_keyword", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="worker stopped"):
        worker.run_keyword_worker(settings, "android01", targeted_trial=True)
    client.reserve.assert_called_once()


def test_cli_requires_explicit_opt_in(settings, monkeypatch):
    monkeypatch.setattr("sniffer.cli.load_settings", lambda _: settings)
    result = CliRunner().invoke(app, ["worker-keywords", "--device", "android01"])
    assert result.exit_code == 1 and "requires explicit --targeted-trial" in result.output


def test_cli_passes_opt_in_and_once(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(worker, "run_keyword_worker", fake)
    result = CliRunner().invoke(app, [
        "worker-keywords", "--device", "android01", "--targeted-trial", "--once",
    ])
    assert result.exit_code == 0, result.output
    assert fake.call_args.kwargs == {"targeted_trial": True, "once": True}


def test_keyword_job_model_is_strict():
    assert KeywordJob.model_validate_json('{"keyword":" prabowo "}').keyword == "prabowo"
    with pytest.raises(ValidationError):
        KeywordJob.model_validate_json('{"keyword":7}')


def test_real_queue_protocol_keyword_worker_heartbeat_then_ack(settings, monkeypatch):
    commands = []
    body = b'{"keyword":"prabowo"}'
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while line := self.rfile.readline():
                command = line.decode().strip()
                commands.append(command)
                action = command.split()[0]
                if action == "use":
                    response = b"USING sniffer.instagram\r\n"
                elif action == "watch":
                    response = b"WATCHING 2\r\n"
                elif action == "ignore":
                    response = b"WATCHING 1\r\n"
                elif action == "stats":
                    stats = b"---\nid: synthetic-server-instance\n"
                    response = f"OK {len(stats)}\r\n".encode() + stats + b"\r\n"
                elif action == "reserve-with-timeout":
                    response = f"RESERVED 42 {len(body)}\r\n".encode() + body + b"\r\n"
                elif action == "stats-job":
                    stats = b"---\nttr: 120\nreserves: 1\n"
                    response = f"OK {len(stats)}\r\n".encode() + stats + b"\r\n"
                elif action == "touch":
                    response = b"TOUCHED\r\n"
                elif action == "delete":
                    response = b"DELETED\r\n"
                else:
                    response = b"UNKNOWN_COMMAND\r\n"
                self.wfile.write(response)
                self.wfile.flush()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.beanstalk.port = server.server_address[1]
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    def fake(_settings, _device, item, *, lease, checkpoint, frida_server):
        assert item.keyword == "prabowo" and item.scroll_count == 119
        assert frida_server is not None
        assert "delete 42" not in commands
        checkpoint()
        return {"output": "synthetic"}
    monkeypatch.setattr(keyword_executor, "execute_keyword", fake)
    try:
        worker.run_keyword_worker(settings, "android01", targeted_trial=True, once=True)
        assert "ignore default" in commands
        assert "touch 42" in commands and commands[-1] == "delete 42"
        assert all(not command.startswith("put ") for command in commands)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
