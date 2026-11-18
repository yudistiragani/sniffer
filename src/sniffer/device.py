from __future__ import annotations

import json

from sniffer.runtime import atomic_json, lock, run
from sniffer.settings import Device, Settings, safe_name


def registry(settings: Settings) -> dict:
    path = settings.state_dir / "devices.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(settings: Settings, name: str) -> Device:
    safe_name(name)
    if name in settings.devices:
        return settings.devices[name]
    entry = registry(settings).get(name)
    if entry:
        return Device.model_validate(entry["device"])
    raise ValueError(f"Unknown device: {name}. Register it with device adopt or device create.")


def register(settings: Settings, name: str, device: Device, **metadata) -> None:
    safe_name(name)
    with lock(settings, "inventory"):
        entries = registry(settings)
        if name in entries or name in settings.devices:
            raise ValueError(f"Device already registered: {name}")
        all_devices = [*settings.devices.values()]
        all_devices += [Device.model_validate(e["device"]) for e in entries.values()]
        for field in ("adb_serial", "system_port", "proxy_port"):
            if any(getattr(d, field) == getattr(device, field) for d in all_devices):
                raise ValueError(f"Device {field} already registered.")
        entries[name] = {"device": device.model_dump(), **metadata}
        atomic_json(settings.state_dir / "devices.json", entries)


def configure(settings: Settings, name: str, changes: dict) -> Device:
    """Update connection metadata without changing runtime or managed ownership."""
    safe_name(name)
    allowed = {
        "appium_url", "system_port", "proxy_host", "proxy_port",
        "frida_endpoint", "frida_device_id",
    }
    if not changes or not set(changes).issubset(allowed):
        raise ValueError("Provide connection settings; immutable device identity cannot be changed.")
    with lock(settings, f"device-{name}"), lock(settings, "inventory"):
        if name in settings.devices:
            raise ValueError("Device is defined in YAML; edit config/local.yaml instead.")
        entries = registry(settings)
        if name not in entries:
            raise ValueError(f"Unknown registered device: {name}")
        updated = Device.model_validate({**entries[name]["device"], **changes})
        others = [*settings.devices.values()]
        others += [
            Device.model_validate(entry["device"]) for key, entry in entries.items() if key != name
        ]
        for field in ("system_port", "proxy_port"):
            if any(getattr(other, field) == getattr(updated, field) for other in others):
                raise ValueError(f"Device {field} already registered.")
        entries[name]["device"] = updated.model_dump()
        atomic_json(settings.state_dir / "devices.json", entries)
        return updated


class ADB:
    def __init__(self, serial: str):
        self.serial = serial

    def command(self, *args: str, check: bool = True):
        return run(["adb", "-s", self.serial, *args], check=check)

    def ready(self, *, connect: bool = False) -> None:
        if connect and ":" in self.serial:
            run(["adb", "connect", self.serial])
        result = self.command("get-state")
        if result.stdout.strip() != "device":
            raise RuntimeError(f"Device is not ready: {self.serial}")
        if self.command("shell", "getprop", "sys.boot_completed").stdout.strip() != "1":
            raise RuntimeError(f"Android has not finished booting: {self.serial}")

    def require_package(self, package: str) -> None:
        if "package:" not in self.command("shell", "pm", "path", package).stdout:
            raise RuntimeError(f"Application is not installed: {package}")

    def info(self) -> dict:
        self.ready()
        values = {}
        for name, prop in (
            ("android", "ro.build.version.release"),
            ("sdk", "ro.build.version.sdk"),
            ("abi", "ro.product.cpu.abi"),
            ("abi_list", "ro.product.cpu.abilist"),
        ):
            values[name] = self.command("shell", "getprop", prop).stdout.strip()
        result = self.command("shell", "magisk", "-v", check=False)
        values["magisk"] = (
            result.stdout.strip() if result.returncode == 0 else "not verified (may need root)"
        )
        return values
