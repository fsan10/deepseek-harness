"""Inspect order verification protocol shapes, never answers or signed URLs."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from commerce_api.runtime.private import load
from commerce_api.runtime.sessions import protect
from commerce_api.runtime.storage import Paths


def shape(value):
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--run")
    args = parser.parse_args()
    if args.run:
        value = load(Paths(), args.run).get("download_verification", {})
        data = value.get("data") or {}
        print(json.dumps({"private_download_verification_shape": shape(value),
            "verify_required": bool(data.get("verify_type")), "file_name_present": bool(data.get("file_name")),
            "need_popup": data.get("need_popup")}, ensure_ascii=False))
    if args.directory:
        value = json.loads(protect((args.directory / "context.enc").read_bytes(), decrypt=True))
        records = value["records"]
        indices = [i for i, record in enumerate(records) if "/order/torder/exportHistory/downloadfile" in record["url"]]
        if not indices:
            return
        for record in records[min(indices):max(indices) + 1]:
            parts = urlsplit(record["url"])
            if parts.hostname != "fxg.jinritemai.com":
                continue
            raw = record.get("post_data") or ""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = dict(parse_qsl(raw))
            response = record.get("response")
            print(json.dumps({"host": parts.hostname, "path": parts.path,
                "method": record["method"], "query_keys": [key for key, _ in parse_qsl(parts.query)],
                "request_shape": shape(body), "response_shape": shape(response)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
