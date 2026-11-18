"""IG416 TopSerp shape observed by the operator; never treat all GraphQL as search."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit, urlunsplit

from sniffer.capture.decoding import decode_documents

MAX_REQUEST = 256 * 1024
MAX_ITEMS = 2000
SEARCH_HOSTS = {"i.instagram.com", "i-fallback.instagram.com"}
CONNECTION = "manual_pagination_query"


def parse_json(body) -> dict:
    """Unknown endpoints retain the existing redacted, non-semantic boundary."""
    return {"kind": "unmapped_json", "data": body}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def identify_search(method: str, url: str, content_type: str, body: bytes) -> dict | None:
    """Read only the operation, keyword and pagination boolean; discard tokens."""
    try:
        parts = urlsplit(url)
        if (
            method.upper() != "POST" or parts.scheme != "https"
            or parts.hostname not in SEARCH_HOSTS or parts.port not in {None, 443}
            or parts.username is not None or parts.password is not None
            or parts.path != "/graphql/query"
            or content_type.split(";", 1)[0].strip().lower()
            != "application/x-www-form-urlencoded"
            or len(body) > MAX_REQUEST
        ):
            return None
        form = parse_qs(
            body.decode("utf-8"), keep_blank_values=True, max_num_fields=100,
            encoding="utf-8", errors="strict",
        )
        if form.get("fb_api_req_friendly_name") != ["TopSerpQuery"]:
            return None
        encoded = form.get("variables", [])
        if len(encoded) != 1:
            return None
        variables = json.loads(encoded[0], object_pairs_hook=_unique_object)
        if not isinstance(variables, dict):
            return None
        keyword = variables.get("query")
        if not isinstance(keyword, str) or not keyword.strip() or not 1 <= len(keyword) <= 200:
            return None
        pagination = variables.get("is_pagination_request")
        return {
            "operation": "TopSerpQuery",
            "keyword": keyword,
            "is_pagination_request": pagination if type(pagination) is bool else None,
        }
    except (ValueError, UnicodeError, RecursionError):
        return None


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _merge(left: dict, right: dict, *, preserve_known=False) -> dict:
    # GraphQL deferred data extends an object at path; do not replace its base fields.
    result = deepcopy(left)
    for key, value in right.items():
        if preserve_known and value is None and key in result:
            continue
        result[key] = (
            _merge(result[key], value, preserve_known=preserve_known)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else deepcopy(value)
        )
    return result


def _string(value, limit=500):
    return value if isinstance(value, str) and len(value) <= limit else None


def _number(value):
    if type(value) is int:
        return value if 0 <= value <= 2**63 - 1 else None
    return value if type(value) is float and math.isfinite(value) and value >= 0 else None


def _identifier(item: dict):
    value = item.get("id")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:_[0-9]+)?", value) else None


def _media_url(value):
    """References only: drop ALL signed/tracking queries, not just known token names."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (
            parts.scheme != "https" or parts.username is not None
            or parts.password is not None or parts.port not in {None, 443}
            or not any(host == d or host.endswith("." + d) for d in (
                "fbcdn.net", "cdninstagram.com",
            ))
        ):
            return None
        return urlunsplit(("https", host, parts.path, "", ""))
    except ValueError:
        return None


def _versions(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    result = []
    for entry in values[:10]:
        entry = _object(entry)
        url = _media_url(entry.get("url"))
        if url:
            result.append({
                "url": url, "width": _number(entry.get("width")),
                "height": _number(entry.get("height")),
            })
    return result


def normalize_post(item: dict, *, child=False) -> dict:
    user = _object(item.get("user"))
    caption = _object(item.get("caption"))
    code = _string(item.get("code"), 100)
    permalink = None
    if code and re.fullmatch(r"[A-Za-z0-9_-]+", code):
        category = "reel" if item.get("product_type") == "clips" else "p"
        permalink = f"https://www.instagram.com/{category}/{code}/"
    result = {
        "id": _identifier(item),
        "shortcode": code,
        "permalink": permalink,
        "media_type": item.get("media_type") if type(item.get("media_type")) is int else None,
        "product_type": _string(item.get("product_type"), 100),
        "taken_at": _number(item.get("taken_at")),
        "caption": _string(caption.get("text"), 20000),
        "like_count": _number(item.get("like_count")),
        "comment_count": _number(item.get("comment_count")),
        "play_count": _number(item.get("play_count")),
        "view_count": _number(item.get("view_count")),
        "reshare_count": _number(item.get("reshare_count")),
        "user": {
            "id": _identifier(user),
            "username": _string(user.get("username")),
            "full_name": _string(user.get("full_name")),
            "is_verified": user.get("is_verified") if type(user.get("is_verified")) is bool else None,
            "follower_count": _number(user.get("follower_count")),
        },
        "images": _versions(_object(item.get("image_versions2")).get("candidates")),
        "videos": _versions(item.get("video_versions")),
        "video_duration": _number(item.get("video_duration")),
    }
    if not child:
        children = {}
        # Lightweight data may contain the only thumbnail; the later full fragment enriches it.
        for field in ("lightweight_carousel", "carousel_media"):
            values = item.get(field)
            if isinstance(values, list):
                for value in values[:100]:
                    value = _object(value)
                    key = _identifier(value)
                    if key:
                        children[key] = _merge(children.get(key, {}), value)
        result["carousel"] = [normalize_post(value, child=True) for value in children.values()]
    return result


def parse_search(body: bytes, request: dict, *, expected_keyword: str | None = None) -> dict:
    """Merge the observed base + deferred paths in one bounded HTTP response."""
    matched = expected_keyword is not None and request["keyword"] == expected_keyword
    result = {
        "kind": "instagram_search", **request,
        "keyword_matched": matched,
        "parse_status": "invalid", "stream_complete": False,
        "has_next_page": None, "has_end_cursor": False,
        "posts": [], "post_count": 0, "issues": [],
    }
    if expected_keyword is not None and not matched:
        return {**result, "kind": "search_keyword_mismatch", "issues": ["keyword_mismatch"]}
    decoded = decode_documents(body)
    issues = set()
    if decoded.error:
        issues.add(decoded.error)
    slots = {}
    base_seen = False
    page_info = {}
    patches = []
    final_seen = False
    for doc in decoded.values:
        if final_seen:
            issues.add("document_after_final")
        if doc.get("errors"):
            issues.add("graphql_errors")
        extensions = _object(doc.get("extensions"))
        final_seen = extensions.get("is_final") is True
        if "path" in doc:
            patches.append(doc)
            continue
        connection = _object(_object(doc.get("data")).get(CONNECTION))
        edges = connection.get("edges")
        if not isinstance(edges, list) or base_seen:
            # A final metadata-only marker is allowed, not a second base response.
            if not (extensions.get("is_final") is True and "data" not in doc):
                issues.add("unsupported_document")
            continue
        base_seen = True
        page_info = _object(connection.get("page_info"))
        for edge_index, edge in enumerate(edges[:MAX_ITEMS]):
            node = _object(_object(edge).get("node"))
            if node.get("__typename") != "XDTTopSerpMediaGridUnit" or node.get("unit_type") != "MEDIA_GRID":
                issues.add("unsupported_unit")
                continue
            items = node.get("items")
            if not isinstance(items, list):
                issues.add("invalid_items")
                continue
            for item_index, item in enumerate(items):
                if len(slots) >= MAX_ITEMS:
                    issues.add("item_limit")
                    break
                item = _object(item)
                if item.get("__typename") != "XDTMediaDict" or not _identifier(item):
                    issues.add("invalid_media")
                    continue
                slots[(edge_index, item_index)] = item
        if len(edges) > MAX_ITEMS:
            issues.add("item_limit")
    for patch in patches:
        path = patch.get("path")
        data = _object(patch.get("data"))
        if path == [CONNECTION] and patch.get("label") == "TopSerpPagingInfo__force_flush":
            page_info = _merge(page_info, _object(data.get("page_info")))
        elif (
            isinstance(path, list) and len(path) == 6
            and path[:2] == [CONNECTION, "edges"] and path[3:5] == ["node", "items"]
            and type(path[2]) is int and type(path[5]) is int
            and patch.get("label") == "SerpClipsViewerFragment"
        ):
            key = (path[2], path[5])
            original = slots.get(key)
            if (
                original is None or _identifier(data) != _identifier(original)
                or data.get("__typename") != "XDTMediaDict"
            ):
                issues.add("patch_identity_mismatch")
            else:
                slots[key] = _merge(original, data)
        else:
            issues.add("unsupported_patch")
    if not base_seen:
        issues.add("missing_search_base")
    # One plain JSON document can be complete; explicit is_final=false cannot.
    plain = (
        len(decoded.values) == 1
        and "is_final" not in _object(decoded.values[0].get("extensions"))
        and not patches
    )
    complete = base_seen and not issues and (final_seen or plain)
    if base_seen and not (final_seen or plain):
        issues.add("missing_final_marker")
    unique = {}
    for item in slots.values():
        key = _identifier(item)
        unique[key] = _merge(unique.get(key, {}), item, preserve_known=True)
    posts = [normalize_post(item) for item in unique.values()]
    next_page = page_info.get("has_next_page")
    result.update(
        parse_status="complete" if complete else "partial" if base_seen else "invalid",
        stream_complete=complete,
        has_next_page=next_page if type(next_page) is bool else None,
        has_end_cursor=isinstance(page_info.get("end_cursor"), str)
        and bool(page_info["end_cursor"]),
        posts=posts, post_count=len(posts), issues=sorted(issues),
    )
    return result
