"""Bounded decoding of JSON or whitespace-separated JSON documents (not MIME)."""

from __future__ import annotations

import json
from dataclasses import dataclass

MAX_BODY = 2 * 1024 * 1024
MAX_DOCUMENTS = 512


@dataclass
class Documents:
    values: list[dict]
    error: str | None = None


def decode_documents(body: bytes) -> Documents:
    if len(body) > MAX_BODY:
        return Documents([], "body_limit")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError:
        return Documents([], "invalid_utf8")
    decoder = json.JSONDecoder()
    values = []
    offset = 0
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset == len(text):
            break
        if len(values) >= MAX_DOCUMENTS:
            return Documents(values, "document_limit")
        try:
            value, offset = decoder.raw_decode(text, offset)
        except (ValueError, RecursionError):
            return Documents(values, "invalid_json_sequence")
        if not isinstance(value, dict):
            return Documents(values, "non_object_document")
        values.append(value)
    return Documents(values, None if values else "empty_body")
