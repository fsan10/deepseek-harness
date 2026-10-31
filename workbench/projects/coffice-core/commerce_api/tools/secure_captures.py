"""Encrypt shared-tool captures; publish only a credential-free schema index."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from commerce_api.runtime.sessions import protect
from commerce_api.runtime.storage import atomic_json


def secure(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    if value.get("commerce_schema_index"):
        return
    target = path.with_name("capture.enc")
    temporary = target.with_suffix(".enc.tmp")
    try:
        temporary.write_bytes(protect(raw))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    endpoints = set()

    def visit(node):
        if isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                parsed = urlsplit(url)
                endpoints.add((parsed.hostname, parsed.path, tuple(sorted(parse_qs(parsed.query)))))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    atomic_json(path, {"commerce_schema_index": 1, "encrypted_capture": "capture.enc",
        "endpoints": [{"host": host, "path": endpoint, "query_keys": keys}
                      for host, endpoint, keys in sorted(endpoints)]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    files = list(args.directory.rglob("capture.redacted.json"))
    for path in files:
        secure(path)
    print(json.dumps({"secured_captures": len(files)}))


if __name__ == "__main__":
    main()
