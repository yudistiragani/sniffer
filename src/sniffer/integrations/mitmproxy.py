from __future__ import annotations

import shutil
import subprocess
import time
from contextlib import AbstractContextManager
from pathlib import Path

from sniffer.runtime import lock, require_free_port
from sniffer.settings import Device, Settings


class ProxyCapture(AbstractContextManager):
    def __init__(self, settings: Settings, device: Device, output: Path, *, raw: bool = False):
        self.settings = settings
        self.device = device
        self.output = output
        self.raw = raw
        self.process = None
        self.log = None
        self.lease = lock(settings, f"proxy-{device.proxy_port}")
        self.ca_lease = lock(settings, "mitm-bootstrap")

    def __enter__(self):
        self.lease.acquire()
        try:
            # Two devices may share the CA directory; serialize first-time CA initialization.
            self.ca_lease.acquire(timeout=25)
            executable = shutil.which("mitmdump")
            if not executable:
                raise RuntimeError("Install capture support: uv sync --extra capture")
            require_free_port(self.device.proxy_host, self.device.proxy_port)
            self.output.mkdir(parents=True, exist_ok=True)
            (self.output / "capture.ready.json").unlink(missing_ok=True)
            (self.output / "capture.failed.json").unlink(missing_ok=True)
            addon = Path(__file__).parents[1] / "capture" / "recorder.py"
            args = [
                executable, "-q", "--listen-host", self.device.proxy_host,
                "--listen-port", str(self.device.proxy_port),
                "-s", str(addon),
                "--set", f"confdir={self.settings.mitm_confdir.resolve()}",
                "--set", f"sniffer_context={(self.output / 'session.json').resolve()}",
            ]
            if self.raw:
                args += ["-w", str(self.output / "traffic.mitm")]
            self.log = (self.output / "proxy.log").open("w", encoding="utf-8")
            self.process = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("mitmdump failed; inspect the session's restricted proxy.log.")
                if (self.output / "capture.ready.json").exists():
                    self.ca_lease.release()
                    return self
                time.sleep(0.1)
            raise RuntimeError("mitmdump recorder readiness timed out.")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def require_alive(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("Capture process exited before job completion.")
        if (self.output / "capture.failed.json").exists():
            raise RuntimeError("Recorder failed to persist a response; inspect restricted proxy.log.")

    def __exit__(self, *_):
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.log:
                self.log.close()
            self.ca_lease.release()
            self.lease.release()
