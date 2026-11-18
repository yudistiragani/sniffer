from __future__ import annotations

import importlib.resources
from contextlib import AbstractContextManager
from pathlib import Path

from sniffer.capture.writer import append_json
from sniffer.settings import Device, Platform


class Instrumentation(AbstractContextManager):
    def __init__(self, device: Device, platform: Platform, output: Path):
        self.device = device
        self.platform = platform
        self.output = output
        self.session = None
        self.scripts = []

    def __enter__(self):
        try:
            import frida
        except ImportError as error:
            raise RuntimeError("Install Frida support: uv sync --extra frida") from error
        if not self.platform.frida_scripts:
            raise ValueError("Frida enabled but no frida_scripts configured for this platform.")
        manager = frida.get_device_manager()
        if self.device.frida_endpoint:
            target = manager.add_remote_device(self.device.frida_endpoint)
        elif self.device.frida_device_id:
            target = manager.get_device(self.device.frida_device_id, timeout=5)
        else:
            raise ValueError("Set frida_endpoint or frida_device_id explicitly; ADB ID is not assumed.")
        spawned = None
        try:
            apps = target.enumerate_applications()
            pid = next(
                (a.pid for a in apps if a.identifier == self.platform.package and a.pid), None
            )
            if not pid:
                pid = target.spawn([self.platform.package])
                spawned = pid
            self.session = target.attach(pid)
            root = Path(str(importlib.resources.files("sniffer").joinpath("scripts"))).resolve()
            for relative in self.platform.frida_scripts:
                path = (root / relative).resolve()
                if not path.is_relative_to(root) or path.suffix != ".js":
                    raise ValueError("Frida scripts must be .js resources inside sniffer/scripts.")
                script = self.session.create_script(path.read_text(encoding="utf-8"))
                script.on("message", self._message)
                self.scripts.append(script)
                script.load()
            if spawned:
                target.resume(spawned)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            if spawned:
                target.kill(spawned)  # only the process spawned by this failed setup
            raise

    def _message(self, message, data):
        # Binary payloads are deliberately not persisted by default.
        append_json(self.output / "frida.jsonl", {"message": message, "binary_bytes": len(data or b"")})

    def __exit__(self, *_):
        for script in reversed(self.scripts):
            try:
                script.unload()
            except Exception:
                pass
        if self.session:
            self.session.detach()
