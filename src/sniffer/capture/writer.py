from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WRITE_LOCK = threading.Lock()
_SENSITIVE = re.compile(
    r"(authorization|cookie|password|passwd|secret|token|sessionid|csrf|api[_-]?key)", re.I
)


def redact(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    # Drop userinfo as well as sensitive query values.
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    query = [
        (key, "[REDACTED]" if _SENSITIVE.search(key) else val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))


def append_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(redact(value), ensure_ascii=False, default=str)
    with _WRITE_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
