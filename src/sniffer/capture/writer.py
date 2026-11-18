from __future__ import annotations

import json
import os
import re
import threading
import uuid
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


class SearchPostWriter:
    """Bounded per-session snapshot: one row per (keyword, post ID), enriched on repeat."""

    def __init__(
        self, output: Path, *, max_posts: int = 10000, max_bytes: int = 32 * 1024 * 1024,
    ):
        self.output = output
        self.max_posts = max_posts
        self.max_bytes = max_bytes
        self.posts = {}

    def write(self, record: dict) -> None:
        def enrich(old, new):
            result = dict(old)
            for key, value in new.items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key] = enrich(result[key], value)
                elif value is not None and value != []:
                    result[key] = value
                elif key not in result:
                    result[key] = value
            return result

        for post in record["posts"]:
            key = (record["keyword"], post["id"])
            previous = self.posts.get(key, {})
            if not previous and len(self.posts) >= self.max_posts:
                raise RuntimeError("Search post limit reached; stop this capture session.")
            self.posts[key] = {
                **enrich(previous, post),
                "kind": "instagram_search_post",
                "keyword": record["keyword"],
                "job_id": record.get("job_id"),
                "source_flow_id": record.get("flow_id"),
                "complete_response_observed": (
                    previous.get("complete_response_observed", False)
                    or record["stream_complete"]
                ),
            }
        if not self.posts:
            return
        path = self.output / "posts.jsonl"
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                size = 0
                for post in self.posts.values():
                    line = json.dumps(redact(post), ensure_ascii=False, allow_nan=False) + "\n"
                    size += len(line.encode("utf-8"))
                    if size > self.max_bytes:
                        raise RuntimeError("Search output size limit reached; stop this capture session.")
                    handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
