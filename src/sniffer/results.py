"""Durable outgoing post outbox, separate from the incoming automation job queue."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import greenstalk
from filelock import FileLock

from sniffer.capture.writer import redact
from sniffer.runtime import atomic_json
from sniffer.settings import ResultsQueue, safe_name

MAX_OUTBOX = 64 * 1024 * 1024
POST_FIELDS = {
    "id", "shortcode", "permalink", "media_type", "product_type", "taken_at", "caption",
    "like_count", "comment_count", "play_count", "view_count", "reshare_count", "user",
    "images", "videos", "video_duration", "carousel",
}


def connect_results(config: ResultsQueue):
    sock = socket.create_connection((config.host, config.port), timeout=config.timeout)
    try:
        # No reserve/watch/delete/ack of jobs in any tube.
        return greenstalk.Client(sock, use=config.tube)
    except BaseException:
        sock.close()
        raise


def message_limit(client, config: ResultsQueue) -> int:
    limit = client.stats().get("max-job-size")
    if type(limit) is not int or limit <= 0:
        raise RuntimeError("Beanstalk did not report max-job-size; refusing unbounded result puts.")
    return min(config.max_message_bytes, limit)


def prepare_outbox(output: Path, config: ResultsQueue, *, job_id: str, device: str, keyword: str):
    safe_name(job_id)
    safe_name(device)
    path = output / "result-outbox.json"
    if path.exists():
        raise ValueError("Result outbox already exists; use results publish to resume it.")
    posts_path = output / "posts.jsonl"
    if not posts_path.exists() or posts_path.stat().st_size > 32 * 1024 * 1024:
        raise RuntimeError("Missing/oversized posts.jsonl; nothing was published.")
    messages, seen = [], set()
    with posts_path.open(encoding="utf-8") as handle:
        for line in handle:
            if len(messages) >= 10000:
                raise RuntimeError("Result post count limit reached; nothing was published.")
            post = json.loads(line)
            if post.get("kind") != "instagram_search_post" or post.get("keyword") != keyword:
                raise ValueError("Unexpected post record/keyword; nothing was published.")
            post_id = post.get("id")
            if not isinstance(post_id, str) or not post_id or post_id in seen:
                raise ValueError("Missing/duplicate post ID; nothing was published.")
            seen.add(post_id)
            # Snapshot files are produced by the allowlisted parser, not raw capture.
            data = redact({key: value for key, value in post.items() if key in POST_FIELDS})
            event_id = hashlib.sha256(
                json.dumps([1, job_id, keyword, post_id], ensure_ascii=False).encode()
            ).hexdigest()
            payload = {
                "schema_version": 1, "event": "instagram.search.post", "event_id": event_id,
                "job_id": job_id, "device": device, "keyword": keyword,
                "complete_response_observed": post.get("complete_response_observed") is True,
                "post": data,
            }
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > config.max_message_bytes:
                raise RuntimeError("A result exceeds the message size limit; no posts were published.")
            messages.append({"payload": encoded, "beanstalk_id": None})
    if not messages:
        raise RuntimeError("No search posts to publish; empty runs are not success.")
    state = {"schema_version": 1, "destination": config.model_dump(), "messages": messages}
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_OUTBOX:
        raise RuntimeError("Result outbox size limit reached.")
    atomic_json(path, state)
    return path


def prepare_saved_outbox(output: Path, config: ResultsQueue):
    """Explicit recovery after completed capture; no device/network operations."""
    with FileLock(str(output / ".result-publish.lock"), timeout=0):
        metadata = json.loads((output / "session.json").read_text(encoding="utf-8"))
        result = json.loads((output / "capture-result.json").read_text(encoding="utf-8"))
        if (
            metadata.get("capture") != "remote_mitmweb_readonly"
            or result.get("scrolls") != 10 or result.get("job_id") != metadata.get("job_id")
        ):
            raise ValueError("Expected a completed, matching ten-scroll collect capture.")
        path = prepare_outbox(
            output, config, job_id=metadata["job_id"], device=metadata["device"],
            keyword=metadata["keyword"],
        )
        return {"outbox": str(path.resolve()), "published_posts": 0}


def publish_outbox(output: Path) -> dict:
    path = output / "result-outbox.json"
    with FileLock(str(output / ".result-publish.lock"), timeout=0):
        if path.stat().st_size > MAX_OUTBOX:
            raise ValueError("Result outbox exceeds limit.")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise ValueError("Unsupported result outbox schema.")
        config = ResultsQueue.model_validate(state["destination"])
        messages = state["messages"]
        if not isinstance(messages, list) or not 1 <= len(messages) <= 10000:
            raise ValueError("Invalid result outbox.")
        for item in messages:
            if (
                not isinstance(item, dict) or not isinstance(item.get("payload"), str)
                or "beanstalk_id" not in item
                or (item["beanstalk_id"] is not None and (
                    type(item["beanstalk_id"]) is not int or item["beanstalk_id"] <= 0
                ))
            ):
                raise ValueError("Invalid result outbox receipt/payload.")
        pending = [item for item in messages if item["beanstalk_id"] is None]
        if pending:
            try:
                with connect_results(config) as client:
                    limit = message_limit(client, config)
                    if any(len(item["payload"].encode()) > limit for item in pending):
                        raise RuntimeError("A result exceeds server max-job-size; no pending posts were published.")
                    for item in pending:
                        inserted = client.put(item["payload"], ttr=120)
                        if type(inserted) is not int or inserted <= 0:
                            raise RuntimeError("Invalid Beanstalk insertion acknowledgment.")
                        # A lost reply or crash before this durable receipt can duplicate delivery.
                        item["beanstalk_id"] = inserted
                        atomic_json(path, state)
            except Exception:
                raise RuntimeError(
                    "Result publish incomplete; durable outbox retained. "
                    "Use results publish on this output, not a new automation run."
                ) from None
        result = {
            "published_posts": sum(item["beanstalk_id"] is not None for item in messages),
            "total_posts": len(messages), "delivery": "at-least-once",
            "results_tube": config.tube,
        }
        atomic_json(output / "publish-summary.json", result)
        return result
