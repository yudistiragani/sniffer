import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from sniffer.capture.recorder import MAX_BODY, Recorder, matches_domain
from sniffer.capture.writer import append_json, redact, safe_url
from sniffer.platforms.instagram import parser


def test_domain_boundaries():
    assert matches_domain("i.instagram.com", ["instagram.com"])
    assert matches_domain("INSTAGRAM.COM.", ["instagram.com"])
    assert not matches_domain("evilinstagram.com", ["instagram.com"])
    assert not matches_domain("instagram.com.evil.test", ["instagram.com"])


def test_redaction(tmp_path):
    payload = {"users": [{"username": "demo", "access_token": "secret"}], "Cookie": "secret"}
    assert redact(payload)["users"][0]["access_token"] == "[REDACTED]"
    path = tmp_path / "response.jsonl"
    append_json(path, payload)
    assert "secret" not in path.read_text()
    assert "demo" in path.read_text()
    url = safe_url("https://user:pass@i.instagram.com/api?q=coffee&token=secret#fragment")
    assert "user:pass" not in url and "secret" not in url and "coffee" in url


def flow(body=b'{"username":"demo","sessionid":"hidden"}', content_type="application/json"):
    return SimpleNamespace(
        id="flow-1",
        request=SimpleNamespace(
            host="i.instagram.com", method="GET", timestamp_start=1,
            pretty_url="https://i.instagram.com/api?token=hidden",
        ),
        response=SimpleNamespace(
            status_code=200, timestamp_end=2, headers={"content-type": content_type},
            raw_content=body, content=body,
        ),
    )


@pytest.fixture
def recorder(tmp_path):
    addon = Recorder()
    addon.context = {"platform": "instagram", "domains": ["instagram.com"], "job_id": "job-1"}
    addon.output = tmp_path
    addon.parser = parser
    return addon


def test_recorder_json_is_not_claimed_as_search_result(recorder):
    recorder.response(flow())
    record = json.loads((recorder.output / "requests.jsonl").read_text())
    assert record["kind"] == "unmapped_json"
    assert record["data"]["sessionid"] == "[REDACTED]"
    assert "hidden" not in json.dumps(record)


def test_binary_metadata_only(recorder):
    recorder.response(flow(b"\x00\x01", "application/octet-stream"))
    record = json.loads((recorder.output / "requests.jsonl").read_text())
    assert record["kind"] == "metadata_only" and "data" not in record


def test_invalid_and_oversized_json(recorder):
    recorder.response(flow(b"not-json"))
    recorder.response(flow(b"x" * (MAX_BODY + 1)))
    records = [json.loads(line) for line in (recorder.output / "requests.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in records] == ["unparsed", "body_skipped"]


def test_unrelated_domain_is_not_saved(recorder):
    sample = flow()
    sample.request.host = "example.org"
    recorder.response(sample)
    assert not (recorder.output / "requests.jsonl").exists()


def test_recorder_failure_is_signalled(recorder, monkeypatch):
    def broken(*_):
        raise OSError("disk unavailable")
    monkeypatch.setattr("sniffer.capture.recorder.append_json", broken)
    with pytest.raises(OSError):
        recorder.response(flow())
    assert (recorder.output / "capture.failed.json").exists()


def search_flow(*, keyword="coffee test", status=200):
    sample = flow(
        (Path(__file__).parent / "fixtures/top_serp_synthetic.jsonseq").read_bytes(),
        "application/x-fb-response",
    )
    sample.request.method = "POST"
    sample.request.pretty_url = "https://i.instagram.com/graphql/query"
    sample.request.headers = {"content-type": "application/x-www-form-urlencoded"}
    sample.request.raw_content = urlencode({
        "fb_api_req_friendly_name": "TopSerpQuery",
        "variables": json.dumps({"query": keyword, "is_pagination_request": True}),
        "access_token": "PRIVATE_REQUEST",
    }).encode()
    sample.response.status_code = status
    return sample


def test_recorder_top_serp_sequence_outputs_normalized_posts(recorder):
    recorder.context["keyword"] = "coffee test"
    recorder.response(search_flow())
    recorder.response(search_flow())  # repeated page, not six new posts
    records = [
        json.loads(line) for line in (recorder.output / "requests.jsonl").read_text().splitlines()
    ]
    assert all(r["stream_complete"] and r["keyword_matched"] for r in records)
    assert len((recorder.output / "posts.jsonl").read_text().splitlines()) == 3
    for file in recorder.output.glob("*.jsonl"):
        assert "PRIVATE" not in file.read_text()


def test_recorder_mismatched_keyword_does_not_export_posts(recorder):
    recorder.context["keyword"] = "different"
    recorder.response(search_flow())
    record = json.loads((recorder.output / "requests.jsonl").read_text())
    assert record["kind"] == "search_keyword_mismatch"
    assert not (recorder.output / "posts.jsonl").exists()


def test_search_post_url_query_metadata_is_never_exported(recorder):
    sample = search_flow()
    sample.request.pretty_url += "?variables=PRIVATE_SESSION"
    recorder.response(sample)
    record = json.loads((recorder.output / "requests.jsonl").read_text())
    assert record["url"] == "https://i.instagram.com/graphql/query"
    assert "PRIVATE" not in json.dumps(record)


@pytest.mark.parametrize("mode", ["partial", "http_error", "oversized", "decoded_oversized"])
def test_recorder_search_limits_and_partial_flags(recorder, mode):
    sample = search_flow(status=500 if mode == "http_error" else 200)
    if mode == "partial":
        sample.response.raw_content = sample.response.content = (
            sample.response.content.rsplit(b'{"extensions"', 1)[0]
        )
    elif mode == "oversized":
        sample.response.raw_content = b"x" * (MAX_BODY + 1)
    elif mode == "decoded_oversized":
        sample.response.content = b"x" * (MAX_BODY + 1)
    recorder.response(sample)
    record = json.loads((recorder.output / "requests.jsonl").read_text())
    assert not record.get("stream_complete")
    if "oversized" in mode:
        assert record["kind"] == "body_skipped"
        assert not (recorder.output / "posts.jsonl").exists()
    else:
        assert record["parse_status"] == "partial"
        assert all(not json.loads(line)["complete_response_observed"] for line in (
            recorder.output / "posts.jsonl"
        ).read_text().splitlines())


def test_post_snapshot_write_failure_fails_capture(recorder, monkeypatch):
    monkeypatch.setattr(
        "sniffer.capture.recorder.SearchPostWriter.write",
        lambda *_: (_ for _ in ()).throw(OSError("PRIVATE_DISK_ERROR")),
    )
    with pytest.raises(OSError):
        recorder.response(search_flow())
    failure = json.loads((recorder.output / "capture.failed.json").read_text())
    assert failure == {"error_type": "OSError"}
