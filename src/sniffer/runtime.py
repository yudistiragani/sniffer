from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

from filelock import FileLock

from sniffer.settings import Settings, safe_name


def run(args: list[str], *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    executable = shutil.which(args[0])
    if executable is None:
        raise RuntimeError(f"Executable not found: {args[0]}")
    result = subprocess.run(
        [executable, *args[1:]], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and result.returncode:
        # Do not echo arbitrary command output: it may contain credentials.
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); inspect the service locally.")
    return result


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def lock(settings: Settings, resource: str) -> FileLock:
    safe_name(resource)
    directory = settings.state_dir / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    return FileLock(directory / f"{resource}.lock", timeout=0)


def require_free_port(host: str, port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, port))
    except OSError as error:
        raise RuntimeError(f"Port unavailable: {host}:{port}") from error


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False
