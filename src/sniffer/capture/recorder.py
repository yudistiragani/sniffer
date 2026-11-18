"""mitmdump addon entrypoint; also importable without mitmproxy for offline tests."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from sniffer.capture.writer import append_json, safe_url
from sniffer.runtime import atomic_json

MAX_BODY = 2 * 1024 * 1024


def matches_domain(host: str, domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in domains)


class Recorder:
    def load(self, loader):
        loader.add_option("sniffer_context", str, "", "Path to this capture session's metadata.")

    def configure(self, updated):
        from mitmproxy import ctx
        path = ctx.options.sniffer_context
        if not path:
            return
        self.context = json.loads(Path(path).read_text(encoding="utf-8"))
        self.output = Path(path).resolve().parent
        platform = self.context["platform"]
        if platform not in {"instagram", "tiktok"}:
            raise ValueError("Unsupported capture platform.")
        self.parser = importlib.import_module(f"sniffer.platforms.{platform}.parser")

    def running(self):
        if not hasattr(self, "context"):
            raise RuntimeError("Missing sniffer_context.")
        atomic_json(self.output / "capture.ready.json", {"pid": os.getpid()})

    def response(self, flow):
        try:
            self._response(flow)
        except Exception as error:
            atomic_json(self.output / "capture.failed.json", {"error_type": type(error).__name__})
            raise

    def _response(self, flow):
        if not matches_domain(flow.request.host, self.context["domains"]):
            return
        response = flow.response
        content_type = response.headers.get("content-type", "")
        record = {
            "job_id": self.context.get("job_id"),
            "platform": self.context["platform"],
            "flow_id": flow.id,
            "started_at": flow.request.timestamp_start,
            "finished_at": response.timestamp_end,
            "method": flow.request.method,
            "url": safe_url(flow.request.pretty_url),
            "status_code": response.status_code,
            "content_type": content_type,
        }
        # No request bodies, headers, binary bodies, or unbounded response decoding by default.
        if len(response.raw_content or b"") > MAX_BODY:
            record.update(kind="body_skipped", reason="encoded body exceeds limit")
        elif "json" in content_type.lower():
            try:
                body = response.content
                if len(body or b"") > MAX_BODY:
                    record.update(kind="body_skipped", reason="decoded body exceeds limit")
                else:
                    record.update(self.parser.parse_json(json.loads(body)))
            except (ValueError, UnicodeError):
                record.update(kind="unparsed", reason="invalid JSON")
        else:
            record.update(kind="metadata_only")
        append_json(self.output / "requests.jsonl", record)

    def error(self, flow):
        try:
            if matches_domain(flow.request.host, self.context["domains"]):
                append_json(self.output / "requests.jsonl", {
                    "job_id": self.context.get("job_id"),
                    "platform": self.context["platform"],
                    "url": safe_url(flow.request.pretty_url),
                    "kind": "transport_error",
                    "host": urlsplit(flow.request.pretty_url).hostname,
                })
        except Exception as error:
            atomic_json(self.output / "capture.failed.json", {"error_type": type(error).__name__})
            raise


addons = [Recorder()]
