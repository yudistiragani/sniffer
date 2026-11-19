"""Read-only mitmweb 11/12 API collector. No proxy restart, replay or mutation."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from sniffer.capture.recorder import Recorder
from sniffer.platforms.instagram.parser import MAX_REQUEST, SEARCH_HOSTS, identify_search
from sniffer.settings import RemoteMitmweb

MAX_LIST = 20 * 1024 * 1024
MAX_FLOWS = 20000
MAX_CONTENT = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def validate_remote(config: RemoteMitmweb) -> str:
    try:
        parts = urlsplit(config.url or "")
        host = parts.hostname or ""
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    try:
        if (
            parts.scheme not in {"http", "https"} or not host or parts.username or parts.password
            or parts.query or parts.fragment or parts.port == 0
            or (parts.scheme == "http" and not loopback)
        ):
            raise ValueError
        ipaddress.ip_address(config.client_ip or "")
    except (ValueError, UnboundLocalError):
        raise ValueError(
            "Set remote_mitmweb.url to HTTPS or a loopback SSH tunnel (no URL credentials), "
            "and client_ip to the Android client's IP as seen by the proxy."
        ) from None
    return (config.url or "").rstrip("/")


class RemoteCapture:
    def __init__(self, config: RemoteMitmweb, context: dict, output):
        self.config = config
        self.origin = validate_remote(config)
        self.recorder = Recorder()
        self.recorder.context = context
        self.recorder.output = output
        from sniffer.platforms.instagram import parser
        self.recorder.parser = parser
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.baseline = set()
        self.seen = set()
        self.last_poll = 0
        self.remote_start = None
        self.session_digest = None
        self.matched = 0
        self.complete = 0
        self.partial = 0
        self.verified = 0

    def _get(self, path: str, limit: int):
        # Secrets are read at use time and never stored in session/config/logs.
        headers = {"Accept-Encoding": "identity", "Accept": "application/json"}
        auth = os.environ.get("SNIFFER_MITMWEB_AUTHORIZATION")
        if auth:
            headers["Authorization"] = auth
        request = Request(self.origin + path, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                body = response.read(limit + 1)
                date = response.headers.get("Date")
                if len(body) > limit:
                    raise RuntimeError("mitmweb response exceeds the collection limit.")
                return body, date
        except HTTPError as error:
            raise RuntimeError(f"mitmweb GET failed (HTTP {error.code}); no proxy settings changed.") from None
        except (URLError, OSError, ValueError):
            raise RuntimeError("mitmweb API unavailable; check its web URL/tunnel/auth locally.") from None

    def _flows(self):
        body, date = self._get("/flows", MAX_LIST)
        try:
            flows = json.loads(body)
            if not isinstance(flows, list) or len(flows) > MAX_FLOWS:
                raise ValueError
            if any(not isinstance(f, dict) or not isinstance(f.get("id"), str) for f in flows):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise RuntimeError("Invalid/oversized mitmweb flow list; no raw metadata was saved.") from None
        return flows, date

    def __enter__(self):
        self.arm()
        return self

    def arm(self):
        flows, date = self._flows()
        try:
            self.remote_start = parsedate_to_datetime(date).timestamp() - 1
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError("mitmweb API must provide a valid Date header for run correlation.") from None
        self.baseline = {flow["id"] for flow in flows}
        self.seen.clear()
        self.session_digest = None
        self.matched = 0
        self.complete = 0
        self.partial = 0
        self.verified = 0

    def __exit__(self, *_):
        return False

    def poll(self, *, force=False):
        if not force and time.monotonic() - self.last_poll < self.config.poll_interval:
            return
        self.last_poll = time.monotonic()
        flows, date = self._flows()
        try:
            upper_time = parsedate_to_datetime(date).timestamp() + 1
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError("mitmweb API Date header disappeared; stopping collection.") from None
        if not self.baseline.issubset({flow["id"] for flow in flows}):
            raise RuntimeError("mitmweb view changed/evicted baseline flows; do not clear or filter it during collection.")
        for flow in flows:
            flow_id = flow["id"]
            if flow_id in self.baseline or flow_id in self.seen:
                continue
            req, res = flow.get("request") or {}, flow.get("response") or {}
            peer = (flow.get("client_conn") or {}).get("peername") or []
            if (
                flow.get("type") != "http" or flow.get("is_replay")
                or req.get("method") != "POST" or req.get("host") not in SEARCH_HOSTS
                or req.get("port") != 443
                or req.get("scheme") != "https" or req.get("path", "").split("?")[0] != "/graphql/query"
                or not peer or peer[0] != self.config.client_ip
            ):
                continue
            started = req.get("timestamp_start")
            if (
                type(started) not in {int, float} or not math.isfinite(started)
                or not self.remote_start <= started <= upper_time
            ):
                continue
            # Wait for the HTTP body to finish, not merely response headers.
            if not res.get("timestamp_end"):
                continue
            if len(self.seen) >= MAX_FLOWS or not re.fullmatch(r"[0-9a-f-]{1,64}", flow_id):
                raise RuntimeError("Remote flow identity/count limit reached.")
            self.seen.add(flow_id)
            req_body, _ = self._get(f"/flows/{flow_id}/request/content.data", MAX_REQUEST)
            headers = {str(k).lower(): str(v) for k, v in req.get("headers", [])}
            url = "https://" + req["host"] + req["path"]
            matched = identify_search("POST", url, headers.get("content-type", ""), req_body)
            if matched is None or matched["keyword"] != self.recorder.context["keyword"]:
                continue
            if type(res.get("status_code")) is not int or not 200 <= res["status_code"] < 300:
                raise RuntimeError("Matching remote search returned non-2xx; nothing will be published.")
            # Detect concurrent search sessions from the same NAT/client; never persist the ID.
            variables = json.loads(parse_qs(req_body.decode())["variables"][0])
            session = variables.get("search_session_id")
            if isinstance(session, str):
                digest = hashlib.sha256(session.encode()).hexdigest()
                if self.session_digest is not None and self.session_digest != digest:
                    raise RuntimeError("Ambiguous remote search sessions; stop other searches on this proxy client.")
                self.session_digest = digest
            if res.get("contentLength", 0) is not None and res["contentLength"] > MAX_CONTENT:
                raise RuntimeError("Remote search response exceeds the encoded body limit.")
            body, _ = self._get(f"/flows/{flow_id}/response/content.data", MAX_CONTENT)
            response_headers = {str(k).lower(): str(v) for k, v in res.get("headers", [])}
            record = self.recorder.response(SimpleNamespace(
                id=flow_id,
                request=SimpleNamespace(
                    host=req["host"], method="POST", pretty_url=url,
                    timestamp_start=started, headers=headers, raw_content=req_body,
                ),
                response=SimpleNamespace(
                    headers=response_headers, status_code=res["status_code"],
                    timestamp_end=res["timestamp_end"], raw_content=body, content=body,
                ),
            ))
            self.matched += 1
            if record.get("stream_complete"):
                self.complete += 1
                self.verified += record.get("post_count", 0) > 0
            else:
                self.partial += 1
