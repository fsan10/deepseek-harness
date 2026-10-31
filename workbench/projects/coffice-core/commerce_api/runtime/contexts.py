"""Endpoint-scoped context identifiers; never share the last header globally."""
from urllib.parse import parse_qs, urlsplit


def context_key(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    suffix = next((f"?{key}={query[key][0]}" for key in ("api", "functionId", "method", "act") if query.get(key)), "")
    return f"{parts.hostname}{parts.path}{suffix}"
