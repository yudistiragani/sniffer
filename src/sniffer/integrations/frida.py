from __future__ import annotations

import importlib.resources
import json
import logging
import time
from contextlib import AbstractContextManager
from pathlib import Path

from sniffer.capture.writer import append_json
from sniffer.device import ADB, resolve
from sniffer.runtime import atomic_json, lock
from sniffer.settings import Device, Platform, Settings

logger = logging.getLogger(__name__)
TLS_EVENTS = {
    "tls.runtime", "tls.module", "tls.skipped_machine", "tls.module_unreadable",
    "tls.hook_ready", "tls.hook_error", "tls.module_ready", "tls.call", "tls.limit",
    "tls.export_outside_module", "tls.runtime_probe",
}


class Instrumentation(AbstractContextManager):
    def __init__(
        self, device: Device, platform: Platform, output: Path, *,
        realm: str = "native", allow_spawn: bool = True,
    ):
        if realm not in {"native", "emulated"}:
            raise ValueError("Frida realm must be native or emulated.")
        self.device = device
        self.platform = platform
        self.output = output
        self.session = None
        self.scripts = []
        self.failure = None
        self.closing = False
        self.realm = realm
        self.allow_spawn = allow_spawn

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
            # Match the proven minimal probe: pidof does not require Frida's
            # Android application-enumeration helper or infer an ABI from the APK.
            logger.info("Frida pid_lookup status=START")
            result = ADB(self.device.adb_serial).command(
                "shell", "pidof", self.platform.package, check=False
            )
            if result.returncode not in (0, 1):
                raise RuntimeError("Unable to inspect the application's PID via ADB.")
            pids = result.stdout.split() if result.returncode == 0 else []
            if len(pids) > 1 or any(not p.isdecimal() or int(p) <= 0 for p in pids):
                raise RuntimeError("Application PID is ambiguous; no process was attached.")
            pid = int(pids[0]) if pids else None
            logger.info("Frida pid_lookup status=END running=%s", pid is not None)
            if not pid:
                if not self.allow_spawn:
                    raise RuntimeError("Instagram is not running; open it manually before inspect.")
                pid = target.spawn([self.platform.package])
                spawned = pid
            logger.info("Frida attach status=START realm=%s", self.realm)
            try:
                self.session = (
                    target.attach(pid) if self.realm == "native"
                    else target.attach(pid, realm=self.realm)
                )
            except Exception as error:
                if self.realm == "emulated" and (
                    type(error).__name__ == "NotSupportedError"
                    or "process is not using emulation" in str(error).lower()
                ):
                    raise RuntimeError(
                        "Frida could not expose the emulated realm for this process. "
                        "Stop here; do not change APK, patch memory, or retry automatically."
                    ) from error
                raise
            logger.info("Frida attach status=END realm=%s", self.realm)
            self.session.on("detached", self._detached)
            root = Path(str(importlib.resources.files("sniffer").joinpath("scripts"))).resolve()
            for index, relative in enumerate(self.platform.frida_scripts, start=1):
                path = (root / relative).resolve()
                if not path.is_relative_to(root) or path.suffix != ".js":
                    raise ValueError("Frida scripts must be .js resources inside sniffer/scripts.")
                script = self.session.create_script(path.read_text(encoding="utf-8"))
                script.on("message", self._message)
                self.scripts.append(script)
                logger.info("Frida script_load status=START index=%s", index)
                script.load()
                logger.info("Frida script_load status=END index=%s", index)
            if spawned:
                target.resume(spawned)
            return self
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            if spawned:
                try:
                    target.kill(spawned)  # only the process spawned by this failed setup
                except Exception:
                    logger.warning("Frida failed-setup process cleanup could not be confirmed.")
            raise

    def _message(self, message, data):
        # Binary payloads are deliberately not persisted by default.
        try:
            append_json(
                self.output / "frida.jsonl",
                {"message": message, "binary_bytes": len(data or b"")},
            )
        except Exception:
            self.failure = "Frida diagnostic output could not be saved."
            logger.error("Frida diagnostic output could not be saved.")
            return
        if message.get("type") == "error":
            self.failure = "Frida script error; inspect the session's frida.jsonl."
            logger.error("Frida script error; details saved in %s", self.output / "frida.jsonl")
        payload = message.get("payload")
        event = payload.get("event") if isinstance(payload, dict) else None
        if isinstance(event, str) and event in TLS_EVENTS:
            # Only a known event label reaches the console, never arbitrary payload contents.
            logger.info("Frida TLS observer event=%s", event)

    def _detached(self, reason, crash=None):
        if not self.closing:
            self.failure = "Frida session detached unexpectedly; stop and inspect device logs."
            logger.error("Frida session detached unexpectedly; crash_report_present=%s", bool(crash))

    def check(self):
        if self.failure:
            raise RuntimeError(self.failure)

    def __exit__(self, exc_type, *_):
        self.closing = True
        for script in reversed(self.scripts):
            try:
                script.unload()
            except Exception:
                pass
        if self.session:
            try:
                self.session.detach()
            except Exception as error:
                logger.warning("Frida session cleanup failed; error_type=%s", type(error).__name__)
                if exc_type is None:
                    raise RuntimeError("Frida session cleanup failed.") from error


def inspect_runtime(
    settings: Settings, device_name: str, endpoint: str, realm: str, duration: int = 5,
) -> dict:
    """Attach to an existing app, read metadata, and detach. Never spawn or hook TLS."""
    from sniffer.executor import new_session
    if realm not in {"native", "emulated"} or not 1 <= duration <= 30:
        raise ValueError("Use native/emulated realm and a duration between 1 and 30 seconds.")
    if "instagram" not in settings.platforms:
        raise ValueError("Instagram configuration missing.")
    device = resolve(settings, device_name).model_copy(update={
        "frida_endpoint": endpoint, "frida_device_id": None,
    })
    config = settings.platforms["instagram"].model_copy(update={
        "frida_scripts": ["shared/runtime_probe.js"],
    })
    with lock(settings, f"device-{device_name}"):
        output = new_session(
            settings, "instagram", device_name, purpose="frida_runtime_probe",
            frida_realm=realm, capture=False,
        )
        logger.info("Frida inspect output=%s", output.resolve())
        try:
            with Instrumentation(
                device, config, output, realm=realm, allow_spawn=False,
            ) as instrumentation:
                for _ in range(duration * 5):
                    instrumentation.check()
                    time.sleep(0.2)
                instrumentation.check()
            path = output / "frida.jsonl"
            snapshots = []
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    message = json.loads(line).get("message", {})
                    payload = message.get("payload")
                    if (
                        message.get("type") == "send" and isinstance(payload, dict)
                        and payload.get("event") == "tls.runtime_probe"
                    ):
                        snapshots.append(payload)
            if not snapshots:
                raise RuntimeError("Frida inspect produced no runtime snapshot; inspect session logs.")
            return {
                "realm": realm, "attached_seconds": duration,
                "output": str(output.resolve()), "runtime": snapshots[-1],
                "tls_verification_changed": False,
            }
        except BaseException as error:
            atomic_json(output / "failure.json", {"error_type": type(error).__name__, "realm": realm})
            raise
