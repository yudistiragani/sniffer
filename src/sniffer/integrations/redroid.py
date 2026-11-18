from __future__ import annotations

import json
import platform

from sniffer.device import register, registry
from sniffer.runtime import lock, require_free_port, run
from sniffer.settings import Device, Settings, safe_name

LABEL = "io.media-sniffer.managed"


def inspect_container(name: str) -> dict | None:
    result = run(["docker", "container", "inspect", name], check=False)
    if result.returncode:
        # Distinguish missing container from an unreachable Docker daemon.
        run(["docker", "info", "--format", "{{.ServerVersion}}"])
        return None
    return json.loads(result.stdout)[0]


def create(
    settings: Settings, name: str, image: str, adb_port: int, system_port: int, proxy_port: int
) -> dict:
    safe_name(name)
    if platform.system() != "Linux":
        raise RuntimeError("Redroid creation is supported on the Linux Docker host, not Windows.")
    device = Device(
        adb_serial=f"127.0.0.1:{adb_port}", container=name,
        system_port=system_port, proxy_port=proxy_port,
    )
    if not 1024 <= adb_port <= 65535:
        raise ValueError("ADB port must be between 1024 and 65535.")
    if len({adb_port, system_port, proxy_port}) != 3:
        raise ValueError("ADB, system, and proxy ports must be distinct.")
    with lock(settings, "inventory-create"), lock(settings, f"device-{name}"):
        if name in settings.devices or name in registry(settings) or inspect_container(name):
            raise ValueError(f"Refusing to replace existing device/container: {name}")
        for other in [
            *settings.devices.values(),
            *(Device.model_validate(e["device"]) for e in registry(settings).values()),
        ]:
            if any(
                getattr(other, field) == getattr(device, field)
                for field in ("adb_serial", "system_port", "proxy_port")
            ):
                raise ValueError("ADB endpoint, Appium system port, or proxy port already registered.")
        for port in (adb_port, system_port, proxy_port):
            require_free_port("127.0.0.1", port)
        # Only use an explicitly selected local image. Never pull a guessed Magisk tag.
        run(["docker", "image", "inspect", image])
        data = (settings.redroid.data_dir / name).resolve()
        if data.exists():
            raise ValueError(f"Refusing to reuse existing data directory: {data}")
        data.mkdir(parents=True)
        result = run([
            "docker", "create", "--name", name, "--privileged",
            "--label", f"{LABEL}=true",
            "--label", f"io.media-sniffer.data={data}",
            "--publish", f"127.0.0.1:{adb_port}:5555",
            "--mount", f"type=bind,src={data},dst=/data",
            image, *settings.redroid.boot_args,
        ])
        container_id = result.stdout.strip()
        # If registration fails, leave the stopped container/data intact for inspection.
        register(settings, name, device, ownership="managed", container_id=container_id, image=image)
        return {"name": name, "container_id": container_id, "data_dir": str(data), "started": False}


def lifecycle(settings: Settings, name: str, operation: str) -> None:
    if operation not in {"start", "stop", "destroy"}:
        raise ValueError("Unsupported lifecycle operation.")
    safe_name(name)
    with lock(settings, f"device-{name}"):
        entry = registry(settings).get(name)
        if not entry or entry.get("ownership") != "managed" or name in settings.devices:
            raise ValueError("Lifecycle changes are restricted to devices created by this project.")
        actual = inspect_container(entry["container_id"])
        if (
            not actual
            or actual["Id"] != entry["container_id"]
            or (actual["Config"].get("Labels") or {}).get(LABEL) != "true"
            or actual["Name"].lstrip("/") != name
        ):
            raise ValueError("Container identity/ownership could not be verified.")
        if operation == "destroy":
            if actual["State"]["Running"]:
                raise ValueError("Stop the device explicitly before destroy.")
            run(["docker", "rm", entry["container_id"]])  # no --force and no --volumes
            with lock(settings, "inventory"):
                entries = registry(settings)
                entries.pop(name)
                from sniffer.runtime import atomic_json
                atomic_json(settings.state_dir / "devices.json", entries)
        else:
            run(["docker", operation, entry["container_id"]])


def stf_containers(settings: Settings) -> list[dict]:
    result = run([
        "docker", "ps", "-a", "--filter",
        f"label=com.docker.compose.project={settings.stf.compose_project}",
        "--format", "{{json .}}",
    ])
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def start_stf(settings: Settings) -> int:
    with lock(settings, "stf"):
        containers = stf_containers(settings)
        if not containers:
            raise ValueError("No existing STF containers match the configured Compose project.")
        # Start existing resources only, never compose up/recreate, remove, or modify volumes.
        stopped = [c["ID"] for c in containers if c.get("State") in {"exited", "created"}]
        for container in stopped:
            run(["docker", "start", container])
        return len(stopped)
