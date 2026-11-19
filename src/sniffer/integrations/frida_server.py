"""Conservative, per-worker lifecycle for an explicitly provisioned Frida server."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlsplit

from sniffer.device import ADB

logger = logging.getLogger(__name__)


class WorkerFridaServer:
    """Start only a configured server when absent; stop only the PID we started."""

    def __init__(self, device):
        self.device = device
        self.adb = ADB(device.adb_serial)
        self.owned_pid: int | None = None
        self.started = False

    def _endpoint_port(self) -> int:
        endpoint = self.device.frida_endpoint
        if not endpoint:
            raise ValueError("Configure an explicit Frida endpoint.")
        parsed = urlsplit("//" + endpoint)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise RuntimeError(
                "Automatic Frida startup requires a loopback endpoint with an explicit port."
            )
        return parsed.port

    def _reachable(self) -> bool:
        try:
            import frida

            target = frida.get_device_manager().add_remote_device(self.device.frida_endpoint)
            target.enumerate_processes()
            return True
        except Exception:
            return False

    def ensure_ready(self, checkpoint=lambda: None) -> None:
        """Check existing server first; provision/start only if no server process exists."""
        checkpoint()
        port = self._endpoint_port()
        if self._reachable():
            logger.info("Frida server status=EXISTING endpoint_ready=true")
            return

        listed = self.adb.command("shell", "pidof", "frida-server", check=False)
        if listed.returncode == 0:
            pids = listed.stdout.split()
            if pids:
                # Never replace/restart an existing server, even if its endpoint is bad.
                raise RuntimeError(
                    "Frida server process exists but the configured endpoint is unavailable; "
                    "no existing process or forward was changed."
                )
        elif listed.returncode != 1:
            raise RuntimeError("Could not safely inspect existing Frida server processes.")

        path = self.device.frida_server_path
        if not path:
            raise RuntimeError(
                "Frida server is unavailable and no verified frida_server_path is configured."
            )
        if not re.fullmatch(r"/[A-Za-z0-9._/-]+", path) or ".." in path.split("/"):
            raise RuntimeError("Configured Frida server path is not a safe absolute path.")
        executable = self.adb.command("shell", "test", "-x", path, check=False)
        if executable.returncode != 0:
            raise RuntimeError("Configured Frida server binary is missing or not executable.")
        checkpoint()
        logger.info("Frida server status=START path_configured=true")
        # The path is restricted to shell-safe characters. Capture the PID from this
        # exact background launch; the existing ADB forward is deliberately untouched.
        # Keep the full script as one `adb shell` argument. Passing it as
        # `shell sh -c <script>` is split by some platform-tools versions, making
        # the listen flag become sh's $0 instead of an argument to frida-server.
        launch = (
            f"'{path}' --listen=127.0.0.1:{port} "
            ">/dev/null 2>&1 </dev/null & echo $!"
        )
        started = self.adb.command("shell", launch, check=False)
        fields = started.stdout.split()
        if started.returncode != 0 or not fields or not fields[-1].isdecimal():
            raise RuntimeError("Could not confirm the PID of the newly started Frida server.")
        self.owned_pid = int(fields[-1])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            checkpoint()
            if self._reachable():
                self.started = True
                logger.info("Frida server status=READY owned=true endpoint_ready=true")
                return
            process = self.adb.command(
                "shell", "kill", "-0", str(self.owned_pid), check=False,
            )
            if process.returncode != 0:
                self.owned_pid = None
                raise RuntimeError("New Frida server exited before the endpoint became ready.")
            time.sleep(0.25)
        raise RuntimeError("New Frida server did not become reachable before timeout.")

    def close(self) -> None:
        """Stop only the recorded PID after verifying its command line is our binary."""
        pid, self.owned_pid = self.owned_pid, None
        if pid is None:
            return
        path = self.device.frida_server_path
        cmdline = self.adb.command(
            "shell", "cat", f"/proc/{pid}/cmdline", check=False,
        )
        command = cmdline.stdout.replace("\x00", " ").strip()
        if cmdline.returncode != 0 or not (
            command == path or command.startswith(f"{path} ")
        ):
            logger.warning("Frida server cleanup skipped; owned PID identity no longer matches.")
            return
        logger.info("Frida server status=STOP_OWNED pid=%s", pid)
        self.adb.command("shell", "kill", str(pid), check=False)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            alive = self.adb.command("shell", "kill", "-0", str(pid), check=False)
            if alive.returncode != 0:
                logger.info("Frida server status=STOPPED_OWNED")
                return
            time.sleep(0.1)
        logger.warning("Frida server owned PID did not exit after SIGTERM; left untouched.")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
