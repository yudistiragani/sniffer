def parse_json(body) -> dict:
    """Capture boundary only; no TikTok semantic extraction implemented."""
    return {"kind": "unmapped_json", "data": body}
