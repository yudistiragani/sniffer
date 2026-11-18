"""Parse operator-exported bodies without contacting a device, proxy or Instagram."""

from __future__ import annotations

import json
from pathlib import Path

from sniffer.capture.decoding import MAX_BODY
from sniffer.capture.writer import SearchPostWriter, append_json
from sniffer.platforms.instagram.parser import MAX_REQUEST, identify_search, parse_search
from sniffer.runtime import atomic_json


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        body = handle.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Offline input exceeds the parsing limit.")
    return body


def parse_instagram_search(
    request_path: Path, response_path: Path, keyword: str, output: Path,
) -> dict:
    try:
        metadata = json.loads(_read(request_path, MAX_REQUEST))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("body"), str):
            raise ValueError
        request = identify_search(
            metadata.get("method", ""), metadata.get("url", ""),
            metadata.get("content_type", ""), metadata["body"].encode("utf-8"),
        )
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise ValueError("Invalid request metadata; expected a form-encoded TopSerpQuery.") from None
    if request is None:
        raise ValueError("Request is not a supported Instagram TopSerpQuery.")
    if not keyword.strip() or len(keyword) > 200:
        raise ValueError("Expected keyword must contain 1 to 200 characters.")
    record = parse_search(
        _read(response_path, MAX_BODY), request, expected_keyword=keyword,
    )
    if record["kind"] == "search_keyword_mismatch":
        raise ValueError("Request keyword does not match the expected keyword.")
    # HTTP status is optional operator-supplied metadata; never invent 200.
    status = metadata.get("status_code")
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("Invalid HTTP status metadata.")
    record.update(status_code=status, source="offline_export")
    if status is not None and not 200 <= status < 300:
        record.update(stream_complete=False, parse_status="partial" if record["posts"] else "invalid")
        record["issues"].append("http_error")
    # Never overwrite existing captures/user files, and keep inputs outside this new directory.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    append_json(output / "requests.jsonl", record)
    SearchPostWriter(output).write(record)
    summary = {key: record[key] for key in (
        "parse_status", "stream_complete", "post_count", "has_next_page",
        "has_end_cursor", "issues", "status_code",
    )}
    summary.update(output=str(output.resolve()), source="offline_export")
    atomic_json(output / "parse-summary.json", summary)
    return summary
