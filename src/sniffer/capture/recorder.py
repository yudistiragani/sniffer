"""mitmdump addon entrypoint; also importable without mitmproxy for offline tests."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from sniffer.capture.decoding import MAX_BODY
from sniffer.capture.writer import SearchPostWriter, append_json, safe_url
from sniffer.runtime import atomic_json


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
            return self._response(flow)
        except Exception as error:
            atomic_json(self.output / "capture.failed.json", {"error_type": type(error).__name__})
            raise

    def _response(self, flow):
        if not matches_domain(flow.request.host, self.context["domains"]):
            return
        response = flow.response
        content_type = response.headers.get("content-type", "")
        search_request = None
        if self.context["platform"] == "instagram":
            search_request = self.parser.identify_search(
                flow.request.method, flow.request.pretty_url,
                getattr(flow.request, "headers", {}).get("content-type", ""),
                getattr(flow.request, "raw_content", b"") or b"",
            )
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
        if search_request is not None:
            # A POST URL can still carry query metadata; never export it for search.
            record["url"] = urlsplit(record["url"])._replace(query="", fragment="").geturl()
        # Only allowlisted search request metadata survives; never export its raw body.
        if len(response.raw_content or b"") > MAX_BODY:
            record.update(kind="body_skipped", reason="encoded body exceeds limit")
        elif search_request is not None or "json" in content_type.lower():
            try:
                body = response.content
                if len(body or b"") > MAX_BODY:
                    record.update(kind="body_skipped", reason="decoded body exceeds limit")
                elif search_request is not None:
                    record.update(self.parser.parse_search(
                        body or b"", search_request, expected_keyword=self.context.get("keyword"),
                    ))
                    if not 200 <= response.status_code < 300:
                        record["stream_complete"] = False
                        record["parse_status"] = "partial" if record["posts"] else "invalid"
                        record["issues"].append("http_error")
                else:
                    record.update(self.parser.parse_json(json.loads(body)))
            except (ValueError, UnicodeError, RecursionError):
                record.update(kind="unparsed", reason="invalid JSON")
        else:
            record.update(kind="metadata_only")
        # Collect publishes posts via an outbox, not a separate JSONL snapshot or log.
        metadata_only = self.context.get("post_output") == "memory"
        append_json(
            self.output / "requests.jsonl",
            {k: v for k, v in record.items() if k != "posts"} if metadata_only else record,
        )
        if record["kind"] == "instagram_search" and record["posts"]:
            if not hasattr(self, "post_writer"):
                self.post_writer = SearchPostWriter(self.output, persist=not metadata_only)
            self.post_writer.write(record)
        return record

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
