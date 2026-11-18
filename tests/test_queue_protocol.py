"""Exercise greenstalk against a tiny local protocol fixture, not the user's queue."""

import json
import socketserver
import threading
from types import SimpleNamespace

from sniffer import worker
from sniffer.integrations.beanstalk import connect


def test_reserve_touch_ack_share_owner_connection(settings, monkeypatch):
    commands = []
    body = json.dumps({"job_id": "protocol-1", "keyword": "coffee"}).encode()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while line := self.rfile.readline():
                command = line.decode().strip()
                commands.append((id(self), command))
                action = command.split()[0]
                if action == "use":
                    response = b"USING sniffer.instagram\r\n"
                elif action == "watch":
                    response = b"WATCHING 2\r\n"
                elif action == "ignore":
                    response = b"WATCHING 1\r\n"
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
    settings.beanstalk.touch_interval = 1

    def fake_execute(*_, **kwargs):
        # Wait for at least one periodic heartbeat during simulated blocking UI work.
        threading.Event().wait(1.2)
        kwargs["checkpoint"]()
        return {"output": "synthetic-local-output"}

    monkeypatch.setattr(worker, "execute", fake_execute)
    try:
        with connect(settings.beanstalk) as client:
            raw = client.reserve(timeout=1)
            assert worker.process_reserved(
                client, raw, settings, "android01", SimpleNamespace()
            ) == "completed"
        texts = [text for _, text in commands]
        assert "ignore default" in texts
        assert texts.count("touch 42") >= 2
        assert texts[-1] == "delete 42"
        assert len({owner for owner, _ in commands}) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
