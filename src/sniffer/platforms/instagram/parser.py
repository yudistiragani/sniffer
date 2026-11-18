def parse_json(body) -> dict:
    """Preserve decoded JSON; semantic search extraction needs real response fixtures."""
    return {"kind": "unmapped_json", "data": body}
