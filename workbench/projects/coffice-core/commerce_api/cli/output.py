"""Stable machine-readable output; operational logs belong on stderr."""
from __future__ import annotations

import json


def envelope(data=None, *, error=None, meta=None):
    return {"ok": error is None, "data": data, "error": error, "meta": meta or {}}


def write(value, stream):
    stream.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
    stream.flush()
