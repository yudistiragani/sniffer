import json
import socketserver
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest
from typer.testing import CliRunner

from sniffer import collect as collect_module
from sniffer.cli import app
from sniffer.integrations.mitmweb import RemoteCapture, validate_remote
from sniffer.integrations.trial_repl import TrialREPL
from sniffer.jobs import SearchJob
from sniffer.results import prepare_outbox, prepare_saved_outbox, publish_outbox
from sniffer.settings import RemoteMitmweb, ResultsQueue

FIXTURE = Path(__file__).parent / "fixtures/top_serp_synthetic.jsonseq"
CLIENT = "192.0.2.10"
FLOW_ID = "00000000-0000-0000-0000-000000000001"
OLD_ID = "00000000-0000-0000-0000-000000000000"


def metadata(flow_id=FLOW_ID):
    return {
        "id": flow_id, "type": "http", "is_replay": None,
        "client_conn": {"peername": [CLIENT, 12345]},
        "request": {
            "method": "POST", "scheme": "https", "host": "i.instagram.com",
            "port": 443, "path": "/graphql/query",
            "headers": [["Content-Type", "application/x-www-form-urlencoded"], ["Cookie", "PRIVATE_COOKIE"]],
            "timestamp_start": time.time(),
        },
        "response": {
            "status_code": 200, "timestamp_end": time.time(), "contentLength": 500,
            "headers": [["Content-Type", "application/x-fb-response"]],
        },
    }


def form(keyword="coffee test", session="PRIVATE_SESSION"):
    return urlencode({
        "fb_api_req_friendly_name": "TopSerpQuery",
        "variables": json.dumps({"query": keyword, "search_session_id": session}),
    }).encode()


@contextmanager
def api_server():
    state = {
        "flows": [metadata(OLD_ID)], "body": FIXTURE.read_bytes(), "request": form(),
        "calls": [], "error": None, "redirect": False, "auth": None,
    }
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["calls"].append(("GET", self.path))
            state["auth"] = self.headers.get("Authorization")
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://must-not-contact.invalid/")
                self.end_headers()
                return
            if state["error"]:
                self.send_response(state["error"])
                self.end_headers()
                return
            body = (
                json.dumps(state["flows"]).encode() if self.path == "/flows"
                else state["request"] if self.path.endswith("/request/content.data")
                else state["body"]
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def context():
    return {
        "platform": "instagram", "domains": ["instagram.com"],
        "job_id": "synthetic-run", "keyword": "coffee test",
    }


@pytest.mark.parametrize("url", [
    "http://203.0.113.5:8081", "https://user:secret@example.test",
    "https://example.test/?token=secret", "file:///tmp/data", "https://example.test/#secret",
    "https://example.test:0",
])
def test_remote_url_requires_safe_transport(url):
    with pytest.raises(ValueError):
        validate_remote(RemoteMitmweb(url=url, client_ip=CLIENT))


def test_remote_api_read_only_capture_baseline_matching_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("SNIFFER_MITMWEB_AUTHORIZATION", "Bearer PRIVATE_API_TOKEN")
    with api_server() as (state, url):
        with RemoteCapture(RemoteMitmweb(url=url, client_ip=CLIENT), context(), tmp_path) as capture:
            state["flows"].append(metadata())
            capture.poll(force=True)
            capture.poll(force=True)
            assert capture.matched == 1
        assert state["auth"] == "Bearer PRIVATE_API_TOKEN"
        assert all(method == "GET" for method, _ in state["calls"])
        assert not any(OLD_ID + "/" in path for _, path in state["calls"])
    posts = (tmp_path / "posts.jsonl").read_text()
    assert len(posts.splitlines()) == 3 and "PRIVATE" not in posts
    assert "PRIVATE" not in (tmp_path / "requests.jsonl").read_text()


@pytest.mark.parametrize("mutation", ["client", "replay", "time", "path", "port", "method"])
def test_remote_unrelated_flows_not_retrieved(tmp_path, mutation):
    with api_server() as (state, url):
        with RemoteCapture(RemoteMitmweb(url=url, client_ip=CLIENT), context(), tmp_path) as capture:
            flow = metadata()
            if mutation == "client":
                flow["client_conn"]["peername"][0] = "192.0.2.99"
            elif mutation == "replay":
                flow["is_replay"] = "request"
            elif mutation == "time":
                flow["request"]["timestamp_start"] = 0
            elif mutation == "path":
                flow["request"]["path"] = "/api/v1/discover/topical_explore/"
            elif mutation == "port":
                flow["request"]["port"] = 8443
            else:
                flow["request"]["method"] = "GET"
            state["flows"].append(flow)
            capture.poll(force=True)
            assert capture.matched == 0
        assert all(path == "/flows" for _, path in state["calls"])
    assert not (tmp_path / "posts.jsonl").exists()


def test_remote_waits_for_body_and_rejects_wrong_keyword(tmp_path):
    with api_server() as (state, url):
        with RemoteCapture(RemoteMitmweb(url=url, client_ip=CLIENT), context(), tmp_path) as capture:
            flow = metadata()
            flow["response"]["timestamp_end"] = None
            state["flows"].append(flow)
            capture.poll(force=True)
            assert capture.matched == 0
            flow["response"]["timestamp_end"] = time.time()
            state["request"] = form("other")
            capture.poll(force=True)
            assert capture.matched == 0
        assert not any("/response/" in path for _, path in state["calls"])


@pytest.mark.parametrize("mode", ["error", "redirect", "eviction", "http_error", "oversized"])
def test_remote_api_fail_closed(tmp_path, mode):
    with api_server() as (state, url):
        with RemoteCapture(RemoteMitmweb(url=url, client_ip=CLIENT), context(), tmp_path) as capture:
            if mode == "error":
                state["error"] = 403
            elif mode == "redirect":
                state["redirect"] = True
            elif mode == "eviction":
                state["flows"] = []
            else:
                flow = metadata()
                if mode == "http_error":
                    flow["response"]["status_code"] = 500
                else:
                    flow["response"]["contentLength"] = 3 * 1024 * 1024
                state["flows"].append(flow)
            with pytest.raises(RuntimeError):
                capture.poll(force=True)
    assert not (tmp_path / "posts.jsonl").exists()


def test_remote_refuses_ambiguous_search_sessions(tmp_path):
    with api_server() as (state, url):
        with RemoteCapture(RemoteMitmweb(url=url, client_ip=CLIENT), context(), tmp_path) as capture:
            state["flows"].append(metadata())
            capture.poll(force=True)
            other = metadata("00000000-0000-0000-0000-000000000002")
            state["flows"].append(other)
            state["request"] = form(session="PRIVATE_OTHER_SESSION")
            with pytest.raises(RuntimeError, match="Ambiguous"):
                capture.poll(force=True)


def snapshot(output, *, huge=False):
    output.mkdir(exist_ok=True)
    (output / "posts.jsonl").write_text(json.dumps({
        "kind": "instagram_search_post", "keyword": "coffee test", "id": "1001_2001",
        "caption": "x" * 70000 if huge else "synthetic caption",
        "user": {"id": "2001", "username": "synthetic_user"},
        "complete_response_observed": False,
    }) + "\n", encoding="utf-8")


def test_results_outbox_separate_schema_receipt_and_idempotent_resume(tmp_path, monkeypatch):
    snapshot(tmp_path)
    config = ResultsQueue()
    prepare_outbox(tmp_path, config, job_id="synthetic-run", device="android01", keyword="coffee test")
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"max-job-size": 65535}
    client.put.return_value = 123
    monkeypatch.setattr("sniffer.results.connect_results", lambda _: client)
    first = publish_outbox(tmp_path)
    assert first["published_posts"] == 1
    payload = json.loads(client.put.call_args.args[0])
    assert payload["event"] == "instagram.search.post" and len(payload["event_id"]) == 64
    assert not payload["complete_response_observed"]
    assert payload["post"]["id"] == "1001_2001"
    assert "keyword" not in payload["post"]
    publish_outbox(tmp_path)
    client.put.assert_called_once()
    client.reserve.assert_not_called()
    client.delete.assert_not_called()


def test_results_put_failure_keeps_pending_outbox_for_retry(tmp_path, monkeypatch):
    snapshot(tmp_path)
    prepare_outbox(
        tmp_path, ResultsQueue(), job_id="synthetic-run", device="android01", keyword="coffee test",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"max-job-size": 65535}
    client.put.side_effect = OSError("PRIVATE_SERVER_ERROR")
    monkeypatch.setattr("sniffer.results.connect_results", lambda _: client)
    with pytest.raises(RuntimeError) as error:
        publish_outbox(tmp_path)
    assert "PRIVATE" not in str(error.value)
    assert json.loads((tmp_path / "result-outbox.json").read_text())["messages"][0]["beanstalk_id"] is None
    client.put.side_effect = None
    client.put.return_value = 124
    assert publish_outbox(tmp_path)["published_posts"] == 1


def test_results_resume_does_not_repeat_already_acknowledged_posts(tmp_path, monkeypatch):
    snapshot(tmp_path)
    path = tmp_path / "posts.jsonl"
    post = json.loads(path.read_text())
    post["id"] = "1002_2002"
    with path.open("a") as handle:
        handle.write(json.dumps(post) + "\n")
    prepare_outbox(
        tmp_path, ResultsQueue(), job_id="synthetic-run", device="android01", keyword="coffee test",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"max-job-size": 65535}
    client.put.side_effect = [901, OSError("lost connection")]
    monkeypatch.setattr("sniffer.results.connect_results", lambda _: client)
    with pytest.raises(RuntimeError):
        publish_outbox(tmp_path)
    state = json.loads((tmp_path / "result-outbox.json").read_text())
    assert [m["beanstalk_id"] for m in state["messages"]] == [901, None]
    client.put.side_effect = None
    client.put.return_value = 902
    assert publish_outbox(tmp_path)["published_posts"] == 2
    assert client.put.call_count == 3
    sent = [json.loads(call.args[0])["post"]["id"] for call in client.put.call_args_list]
    assert sent == ["1001_2001", "1002_2002", "1002_2002"]


@pytest.mark.parametrize("limit", [1, None])
def test_server_message_limit_checked_before_any_put(tmp_path, monkeypatch, limit):
    snapshot(tmp_path)
    prepare_outbox(
        tmp_path, ResultsQueue(), job_id="synthetic-run", device="android01", keyword="coffee test",
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"max-job-size": limit}
    monkeypatch.setattr("sniffer.results.connect_results", lambda _: client)
    with pytest.raises(RuntimeError):
        publish_outbox(tmp_path)
    client.put.assert_not_called()


def test_oversized_post_not_silently_dropped(tmp_path):
    snapshot(tmp_path, huge=True)
    with pytest.raises(RuntimeError, match="size limit"):
        prepare_outbox(
            tmp_path, ResultsQueue(), job_id="synthetic-run", device="android01", keyword="coffee test",
        )
    assert not (tmp_path / "result-outbox.json").exists()


def test_prepare_saved_capture_never_reruns_ui_or_sends(tmp_path, monkeypatch):
    snapshot(tmp_path)
    (tmp_path / "session.json").write_text(json.dumps({
        "capture": "remote_mitmweb_readonly", "job_id": "synthetic-run",
        "device": "android01", "keyword": "coffee test",
    }))
    result_file = tmp_path / "capture-result.json"
    result_file.write_text(json.dumps({"scrolls": 9, "job_id": "synthetic-run"}))
    monkeypatch.setattr("sniffer.results.connect_results", lambda *_: pytest.fail("No network"))
    with pytest.raises(ValueError, match="completed"):
        prepare_saved_outbox(tmp_path, ResultsQueue())
    result_file.write_text(json.dumps({"scrolls": 10, "job_id": "synthetic-run"}))
    assert prepare_saved_outbox(tmp_path, ResultsQueue())["published_posts"] == 0
    assert (tmp_path / "result-outbox.json").exists()


def configure_collect(settings):
    settings.remote_mitmweb = RemoteMitmweb(url="http://127.0.0.1:19001", client_ip=CLIENT, settle_seconds=1)
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    return SearchJob(job_id="synthetic-run", keyword="coffee test", scroll_count=10)


def test_collect_dry_run_has_no_network_or_state(settings, monkeypatch):
    job = configure_collect(settings)
    monkeypatch.setattr(collect_module, "ADB", lambda *_: pytest.fail("No device access"))
    monkeypatch.setattr(collect_module, "connect_results", lambda *_: pytest.fail("No queue access"))
    result = collect_module.collect(
        settings, "android01", job, trial=True, publish=True, dry_run=True,
    )
    assert result["job"]["scroll_count"] == 10 and result["trial_max_seconds"] == 120
    assert not settings.state_dir.exists() and not settings.output_dir.exists()


def test_collect_requires_opt_in_and_separate_results_tube(settings):
    job = configure_collect(settings)
    with pytest.raises(ValueError, match="consent"):
        collect_module.collect(settings, "android01", job, trial=False, publish=True)
    settings.results.tube = settings.beanstalk.instagram_tube
    with pytest.raises(ValueError, match="differ"):
        collect_module.collect(settings, "android01", job, trial=True, publish=True, dry_run=True)


@pytest.mark.parametrize("failure", [None, "ui", "trial", "empty"])
def test_collect_lifecycle_publishes_only_after_successful_capture(settings, monkeypatch, failure):
    job = configure_collect(settings)
    driver = MagicMock(current_package="com.instagram.android")
    monkeypatch.setattr(collect_module, "ADB", lambda *_: MagicMock())
    monkeypatch.setattr("sniffer.integrations.appium.connect", lambda *_: driver)
    trial = MagicMock()
    trial.__enter__.return_value = trial
    if failure == "trial":
        trial.check.side_effect = RuntimeError("trial expired")
    monkeypatch.setattr("sniffer.integrations.trial_repl.TrialREPL", lambda *_: trial)
    class Capture:
        matched = 1
        complete = 0
        partial = 1
        verified = 0
        def __init__(self, config, context, output):
            self.output = output
            self.matched = 0 if failure == "empty" else 1
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def arm(self):
            pass
        def poll(self, **_):
            if failure != "empty":
                snapshot(self.output)
    monkeypatch.setattr(collect_module, "RemoteCapture", Capture)
    def search(driver, platform, job, health):
        health()
        if failure == "ui":
            raise RuntimeError("UI failed")
        return {"scrolls": 10}
    monkeypatch.setattr("sniffer.platforms.instagram.executor.search", search)
    publisher = MagicMock(return_value={"published_posts": 1})
    monkeypatch.setattr(collect_module, "publish_outbox", publisher)
    client = MagicMock()
    client.__enter__.return_value = client
    client.stats.return_value = {"max-job-size": 65535}
    monkeypatch.setattr(collect_module, "connect_results", lambda _: client)
    if failure:
        with pytest.raises(RuntimeError):
            collect_module.collect(settings, "android01", job, trial=True, publish=True)
        publisher.assert_not_called()
    else:
        result = collect_module.collect(settings, "android01", job, trial=True, publish=True)
        assert result["scrolls"] == 10 and result["published_posts"] == 1
        publisher.assert_called_once()
    driver.activate_app.assert_not_called()
    driver.quit.assert_called_once()
    trial.__exit__.assert_called_once()


def test_repl_event_reader_accepts_only_fixed_safe_events(tmp_path):
    trial = TrialREPL(SimpleNamespace(), tmp_path)
    trial._line("message: " + repr({
        "type": "send", "payload": {
            "event": "fb_trial.ready", "durationMs": 120000, "secret": "PRIVATE_CERT",
        },
    }) + " data: None\n")
    assert trial.ready.is_set()
    assert "PRIVATE" not in (tmp_path / "frida.jsonl").read_text()
    trial._line("Failed to attach: PRIVATE_ATTACH_ERROR\n")
    assert "PRIVATE" not in (tmp_path / "frida.jsonl").read_text()
    trial._line("message: " + repr({
        "type": "send", "payload": {"event": "fb_trial.refused", "reason": "PRIVATE_REASON"},
    }) + " data: None\n")
    assert trial.failure == "trial_refused"


def test_repl_expiry_and_exit_are_not_retried(tmp_path):
    trial = TrialREPL(SimpleNamespace(), tmp_path)
    trial.process = MagicMock()
    trial.process.poll.return_value = None
    trial.deadline = time.monotonic() - 1
    with pytest.raises(RuntimeError, match="expired"):
        trial.check()
    trial.process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="exited"):
        trial.check()


def test_repl_owns_only_child_and_uses_official_pinned_native_cli(tmp_path, monkeypatch):
    device = SimpleNamespace(adb_serial="synthetic", frida_endpoint="127.0.0.1:27052")
    monkeypatch.setattr(
        "sniffer.integrations.trial_repl.importlib.metadata.version",
        lambda package: "17.27.0" if package == "frida" else "14.13.2",
    )
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(stdout="12345\n", returncode=0)
    monkeypatch.setattr("sniffer.integrations.trial_repl.ADB", lambda _: adb)
    trial = TrialREPL(device, tmp_path)
    process = MagicMock()
    process.poll.return_value = None
    process.stdout.readline.side_effect = [
        "message: " + repr({"type": "send", "payload": {
            "event": "fb_trial.ready", "durationMs": 120000,
        }}) + " data: None\n", "",
    ]
    popen = MagicMock(return_value=process)
    monkeypatch.setattr("sniffer.integrations.trial_repl.subprocess.Popen", popen)
    with trial:
        trial.check()
    args = popen.call_args.args[0]
    assert "frida_tools.repl" in args and "--no-auto-reload" in args
    assert args[args.index("--realm") + 1] == "native"
    assert args[args.index("-p") + 1] == "12345"
    assert "-f" not in args and "--eternalize" not in args
    assert "__snifferTrialDurationMs = 120000" in (tmp_path / "collect-trial.js").read_text()
    process.terminate.assert_called_once()


def test_collect_queue_preflight_failure_never_opens_device(settings, monkeypatch):
    job = configure_collect(settings)
    monkeypatch.setattr(
        collect_module, "connect_results", MagicMock(side_effect=OSError("PRIVATE_DEST")),
    )
    monkeypatch.setattr(collect_module, "ADB", lambda *_: pytest.fail("No device access"))
    with pytest.raises(RuntimeError, match="preflight"):
        collect_module.collect(settings, "android01", job, trial=True, publish=True)
    assert not settings.output_dir.exists()


def test_real_outgoing_beanstalk_protocol_only_uses_stats_and_put(tmp_path):
    commands, payloads = [], []
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while line := self.rfile.readline():
                command = line.decode().strip()
                commands.append(command.split()[0])
                if command.startswith("use "):
                    response = b"USING sniffer_instagram_result\r\n"
                elif command == "stats":
                    stats = b"---\nmax-job-size: 65535\n"
                    response = f"OK {len(stats)}\r\n".encode() + stats + b"\r\n"
                elif command.startswith("put "):
                    size = int(command.split()[-1])
                    payloads.append(json.loads(self.rfile.read(size)))
                    assert self.rfile.read(2) == b"\r\n"
                    response = b"INSERTED 901\r\n"
                else:
                    response = b"UNKNOWN_COMMAND\r\n"
                self.wfile.write(response)
                self.wfile.flush()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        snapshot(tmp_path)
        prepare_outbox(
            tmp_path, ResultsQueue(port=server.server_address[1]),
            job_id="protocol-output", device="android01", keyword="coffee test",
        )
        assert publish_outbox(tmp_path)["published_posts"] == 1
        assert commands == ["use", "stats", "put"]
        assert payloads[0]["post"]["id"] == "1001_2001"
        assert json.loads((tmp_path / "result-outbox.json").read_text())["messages"][0]["beanstalk_id"] == 901
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_collect_cli_and_publish_cli_forward_explicit_options(settings, monkeypatch):
    configure_collect(settings)
    monkeypatch.setattr("sniffer.cli.load_settings", lambda _: settings)
    fake = MagicMock(return_value={"dry_run": True})
    monkeypatch.setattr(collect_module, "collect", fake)
    result = CliRunner().invoke(app, [
        "automation", "instagram", "collect", "--device", "android01", "--keyword", "prabowo",
        "--targeted-trial", "--publish", "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert fake.call_args.args[2].scroll_count == 10
    assert fake.call_args.args[2].keyword == "prabowo"
    assert fake.call_args.kwargs == {"trial": True, "publish": True, "dry_run": True}
