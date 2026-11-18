"""Local HTTP integration only. No Instagram, device, or external endpoint is contacted."""

import http.client
import json
import shutil
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sniffer.executor import new_session
from sniffer.integrations.mitmproxy import ProxyCapture


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(shutil.which("mitmdump") is None, reason="Install capture extra for local proxy test")
def test_real_proxy_records_local_response_and_cleans_up(settings):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"items":[{"id":"synthetic-1"}],"access_token":"must-not-leak"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.devices["android01"].proxy_port = available_port()
    settings.platforms["instagram"].domains = ["127.0.0.1"]
    output = new_session(settings, "instagram", "android01", job_id="local-proxy-test")
    try:
        with ProxyCapture(settings, settings.devices["android01"], output) as capture:
            # Explicit HTTP proxy request, bypassing urllib's localhost no_proxy behavior.
            connection = http.client.HTTPConnection(
                "127.0.0.1", settings.devices["android01"].proxy_port, timeout=10
            )
            try:
                connection.request("GET", f"http://127.0.0.1:{server.server_port}/search?token=hidden")
                response = connection.getresponse()
                assert response.status == 200
                response.read()
            finally:
                connection.close()
            deadline = time.monotonic() + 3
            path = output / "requests.jsonl"
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            capture.require_alive()
            record = json.loads(path.read_text())
            assert record["data"]["items"][0]["id"] == "synthetic-1"
            assert record["data"]["access_token"] == "[REDACTED]"
            assert "must-not-leak" not in path.read_text()
            assert "hidden" not in record["url"]
        assert capture.process.poll() is not None
        assert not (output / "traffic.mitm").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
