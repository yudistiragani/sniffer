import json
from types import SimpleNamespace

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
