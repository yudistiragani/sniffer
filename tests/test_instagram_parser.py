import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode

import pytest

from sniffer.capture.decoding import MAX_BODY, MAX_DOCUMENTS, decode_documents
from sniffer.capture.offline import parse_instagram_search
from sniffer.capture.writer import SearchPostWriter
from sniffer.platforms.instagram import parser

FIXTURE = Path(__file__).parent / "fixtures/top_serp_synthetic.jsonseq"
URL = "https://i.instagram.com/graphql/query"
CONTENT_TYPE = "application/x-www-form-urlencoded"


def request_body(keyword="coffee test", **variables):
    return urlencode({
        "fb_api_req_friendly_name": "TopSerpQuery",
        "client_doc_id": "synthetic-build-specific-id",
        "variables": json.dumps({
            "query": keyword, "is_pagination_request": True,
            "after": "PRIVATE_CURSOR", "search_session_id": "PRIVATE_SESSION", **variables,
        }),
    }).encode()


def request():
    return parser.identify_search("POST", URL, CONTENT_TYPE, request_body())


def docs():
    return decode_documents(FIXTURE.read_bytes()).values


def parse(values=None, **kwargs):
    body = (
        FIXTURE.read_bytes() if values is None
        else "\n  ".join(json.dumps(value) for value in values).encode()
    )
    return parser.parse_search(body, request(), expected_keyword="coffee test", **kwargs)


def test_request_identification_does_not_export_session_or_cursor():
    assert request() == {
        "operation": "TopSerpQuery", "keyword": "coffee test", "is_pagination_request": True,
    }
    assert "PRIVATE" not in json.dumps(request())


@pytest.mark.parametrize("method,url,content_type", [
    ("GET", URL, CONTENT_TYPE),
    ("POST", "https://i.instagram.com.evil.test/graphql/query", CONTENT_TYPE),
    ("POST", "https://i.instagram.com/api/v1/feed/timeline/", CONTENT_TYPE),
    ("POST", "https://i.instagram.com/api/v1/discover/topical_explore/", CONTENT_TYPE),
    ("POST", "http://i.instagram.com/graphql/query", CONTENT_TYPE),
    ("POST", "https://user:pass@i.instagram.com/graphql/query", CONTENT_TYPE),
    ("POST", "https://i.instagram.com:444/graphql/query", CONTENT_TYPE),
    ("POST", URL, "application/json"),
])
def test_unrelated_request_not_search(method, url, content_type):
    assert parser.identify_search(method, url, content_type, request_body()) is None


@pytest.mark.parametrize("body", [
    b"variables={}",
    request_body().replace(b"TopSerpQuery", b"AnotherQuery"),
    request_body() + b"&variables={}",
    request_body() + b"&fb_api_req_friendly_name=TopSerpQuery",
    request_body(keyword=""),
    request_body(keyword=None),
    request_body(keyword="x" * 201),
    request_body(keyword=" " * 201 + "coffee"),
    b"x" * (parser.MAX_REQUEST + 1),
    b"fb_api_req_friendly_name=TopSerpQuery&variables=%FF",
    urlencode({
        "fb_api_req_friendly_name": "TopSerpQuery",
        "variables": '{"query":"coffee test","query":"other"}',
    }).encode(),
])
def test_invalid_or_ambiguous_request(body):
    assert parser.identify_search("POST", URL, CONTENT_TYPE, body) is None


def test_encoded_keyword_and_form_charset():
    result = parser.identify_search(
        "POST", URL, CONTENT_TYPE + "; charset=UTF-8", request_body("kopi + 日本"),
    )
    assert result["keyword"] == "kopi + 日本"


def test_base_and_out_of_order_patches_are_merged_and_deduplicated():
    result = parse()
    assert result["parse_status"] == "complete"
    assert result["stream_complete"] and result["keyword_matched"]
    assert result["post_count"] == 3
    photo, video, carousel = result["posts"]
    assert photo["caption"] == "Synthetic coffee photo"
    assert photo["user"]["username"] == "synthetic_cafe"
    assert photo["user"]["follower_count"] == 10
    assert photo["like_count"] == 7 and photo["comment_count"] == 2
    assert video["permalink"] == "https://www.instagram.com/reel/SYNTHETIC_B/"
    assert video["like_count"] == 0 and video["comment_count"] is None
    assert video["view_count"] is None and video["play_count"] == 100
    assert len(carousel["carousel"]) == 2
    assert all(child["images"] for child in carousel["carousel"])
    assert result["has_next_page"] is True and result["has_end_cursor"] is True
    # Never emit signed media queries, manifests, tracking tokens, sessions or cursors.
    assert "PRIVATE" not in json.dumps(result)
    assert "?" not in photo["images"][0]["url"]


def test_patch_arriving_before_base_uses_path_not_arrival_order():
    values = docs()
    values[0], values[1] = values[1], values[0]
    assert parse(values)["posts"] == parse()["posts"]


def test_duplicate_base_with_null_metadata_does_not_erase_deferred_fields():
    values = docs()
    duplicate = values[0]["data"][parser.CONNECTION]["edges"][1]["node"]["items"][1]
    duplicate.update(caption=None, like_count=None, image_versions2=None)
    duplicate["user"]["follower_count"] = None
    photo = parse(values)["posts"][0]
    assert photo["caption"] == "Synthetic coffee photo" and photo["like_count"] == 7
    assert photo["user"]["follower_count"] == 10 and photo["images"]


def test_keyword_mismatch_never_emits_posts():
    result = parser.parse_search(FIXTURE.read_bytes(), request(), expected_keyword="other")
    assert result["kind"] == "search_keyword_mismatch"
    assert result["post_count"] == 0 and not result["stream_complete"]


@pytest.mark.parametrize("mutation,issue", [
    ("missing_final", "missing_final_marker"),
    ("graphql_error", "graphql_errors"),
    ("wrong_id", "patch_identity_mismatch"),
    ("out_of_range", "patch_identity_mismatch"),
    ("wrong_type", "patch_identity_mismatch"),
    ("boolean_index", "unsupported_patch"),
    ("wrong_label", "unsupported_patch"),
    ("wrong_path", "unsupported_patch"),
    ("unknown_unit", "unsupported_unit"),
    ("invalid_media", "invalid_media"),
    ("after_final", "document_after_final"),
])
def test_incomplete_or_unsupported_stream_is_never_complete(mutation, issue):
    values = docs()
    if mutation == "missing_final":
        values.pop()
    elif mutation == "graphql_error":
        values[1]["errors"] = [{"message": "PRIVATE_ERROR"}]
    elif mutation == "wrong_id":
        values[1]["data"]["id"] = "9999_2002"
    elif mutation == "out_of_range":
        values[1]["path"][2] = 999
    elif mutation == "wrong_type":
        values[1]["data"]["__typename"] = "Other"
    elif mutation == "boolean_index":
        values[1]["path"][2] = True
    elif mutation == "wrong_label":
        values[1]["label"] = "AnotherFragment"
    elif mutation == "wrong_path":
        values[1]["path"].append("caption")
    elif mutation == "unknown_unit":
        values[0]["data"][parser.CONNECTION]["edges"][0]["node"]["__typename"] = "Unknown"
    elif mutation == "invalid_media":
        values[0]["data"][parser.CONNECTION]["edges"][0]["node"]["items"][1]["id"] = "invalid"
    elif mutation == "after_final":
        values.append(deepcopy(values[1]))
    result = parse(values)
    assert not result["stream_complete"]
    assert issue in result["issues"]
    assert "PRIVATE" not in json.dumps(result)


def test_plain_json_and_empty_results():
    base = docs()[0]
    base.pop("extensions")
    result = parse([base])
    assert result["stream_complete"] and result["post_count"] == 3
    base["data"][parser.CONNECTION]["edges"] = []
    result = parse([base])
    assert result["stream_complete"] and result["posts"] == []


@pytest.mark.parametrize("body,issue", [
    (b"", "empty_body"),
    (b"\xff", "invalid_utf8"),
    (b"[]", "non_object_document"),
    (b'{"data":', "invalid_json_sequence"),
    (b"{}" * (MAX_DOCUMENTS + 1), "document_limit"),
    (b"x" * (MAX_BODY + 1), "body_limit"),
    (b"[" * 2000, "invalid_json_sequence"),
    (b'--boundary\r\nContent-Type: application/json\r\n{}', "invalid_json_sequence"),
])
def test_bounded_decoder_errors_are_static(body, issue):
    assert decode_documents(body).error == issue
    result = parser.parse_search(body, request())
    assert not result["stream_complete"] and result["post_count"] == 0


def test_trailing_truncation_keeps_partial_posts_not_success():
    result = parser.parse_search(
        FIXTURE.read_bytes().rsplit(b'{"extensions"', 1)[0] + b'{"extensions":',
        request(), expected_keyword="coffee test",
    )
    assert result["post_count"] == 3 and result["parse_status"] == "partial"
    assert "invalid_json_sequence" in result["issues"]


def test_no_base_never_accepts_fragment_as_a_post():
    assert parse(docs()[1:])["post_count"] == 0
    assert "missing_search_base" in parse(docs()[1:])["issues"]


def test_numeric_null_and_untrusted_urls():
    result = parser.normalize_post({
        "id": "1_2", "code": "../../evil", "media_type": True, "like_count": float("nan"),
        "comment_count": -1, "play_count": True, "view_count": float("inf"),
        "image_versions2": {"candidates": [
            {"url": "https://media.fbcdn.net.evil.test/a.jpg"},
            {"url": "https://user:pass@media.fbcdn.net/a.jpg"},
            {"url": "javascript:alert(1)"},
            {"url": "https://media.fbcdn.net/a.jpg?sig=PRIVATE#PRIVATE"},
        ]},
    })
    assert result["like_count"] is None and result["view_count"] is None
    assert result["comment_count"] is None and result["play_count"] is None
    assert result["permalink"] is None and result["media_type"] is None
    assert [image["url"] for image in result["images"]] == ["https://media.fbcdn.net/a.jpg"]
    assert parser.normalize_post({"id": "1", "like_count": 10**400})["like_count"] is None


def test_item_limit_is_explicit_not_silent_success(monkeypatch):
    monkeypatch.setattr(parser, "MAX_ITEMS", 1)
    result = parse()
    assert "item_limit" in result["issues"] and not result["stream_complete"]
    assert result["post_count"] == 1


@pytest.mark.parametrize("metadata", [
    {"method": 42}, {"content_type": {}}, {"status_code": "200"},
    {"status_code": True}, {"status_code": 999},
])
def test_invalid_offline_metadata_is_rejected_without_output(tmp_path, metadata):
    output = tmp_path / "parsed"
    with pytest.raises(ValueError):
        parse_instagram_search(
            offline_request(tmp_path, **metadata), FIXTURE, "coffee test", output,
        )
    assert not output.exists()


def test_post_snapshot_deduplicates_pages_and_preserves_enrichment(tmp_path):
    writer = SearchPostWriter(tmp_path)
    full = {**parse(), "job_id": "synthetic-job", "flow_id": "synthetic-flow"}
    writer.write(full)
    partial = parse(docs()[:1])
    writer.write(partial)
    posts = [json.loads(line) for line in (tmp_path / "posts.jsonl").read_text().splitlines()]
    assert len(posts) == 3 and posts[0]["caption"] == "Synthetic coffee photo"
    assert posts[0]["complete_response_observed"] is True
    assert "PRIVATE" not in (tmp_path / "posts.jsonl").read_text()
    writer.write({**full, "keyword": "different keyword"})
    assert len((tmp_path / "posts.jsonl").read_text().splitlines()) == 6


def test_output_limits_do_not_replace_previous_snapshot(tmp_path):
    writer = SearchPostWriter(tmp_path, max_posts=3)
    writer.write(parse())
    before = (tmp_path / "posts.jsonl").read_bytes()
    with pytest.raises(RuntimeError, match="post limit"):
        writer.write({**parse(), "keyword": "different"})
    assert (tmp_path / "posts.jsonl").read_bytes() == before
    writer.max_bytes = 1
    with pytest.raises(RuntimeError, match="size limit"):
        writer.write(parse())
    assert (tmp_path / "posts.jsonl").read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def offline_request(tmp_path, **metadata):
    path = tmp_path / "request.json"
    path.write_text(json.dumps({
        "method": "POST", "url": URL, "content_type": CONTENT_TYPE,
        "body": request_body().decode(), **metadata,
    }))
    return path


def test_offline_export_without_http_status_does_not_invent_one(tmp_path):
    output = tmp_path / "parsed"
    result = parse_instagram_search(
        offline_request(tmp_path), FIXTURE, "coffee test", output,
    )
    assert result["post_count"] == 3 and result["status_code"] is None
    assert (output / "posts.jsonl").exists()
    assert "PRIVATE" not in (output / "requests.jsonl").read_text()
    with pytest.raises(FileExistsError):
        parse_instagram_search(offline_request(tmp_path), FIXTURE, "coffee test", output)


def test_offline_mismatched_keyword_has_no_output(tmp_path):
    output = tmp_path / "parsed"
    with pytest.raises(ValueError, match="keyword"):
        parse_instagram_search(offline_request(tmp_path), FIXTURE, "other", output)
    assert not output.exists()


def test_offline_http_error_preserves_partial_not_complete(tmp_path):
    result = parse_instagram_search(
        offline_request(tmp_path, status_code=500), FIXTURE, "coffee test", tmp_path / "parsed",
    )
    assert not result["stream_complete"] and "http_error" in result["issues"]
