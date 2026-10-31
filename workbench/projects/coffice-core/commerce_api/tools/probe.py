"""Read-only independent HTTP identity probe using an owned encrypted session."""
from __future__ import annotations

import argparse
import asyncio
import json

from ..core.registry import Registry
from ..runtime.http import HttpSession
from ..runtime.sessions import SessionStore, session_key
from ..runtime.storage import Paths, read_json


async def run(args):
    paths = Paths()
    profile = read_json(paths.file("config", "profiles"), {})[args.profile]
    spec = Registry().backend(args.platform, args.backend)
    store = SessionStore(paths)
    credential = store.load(session_key(profile["id"], args.platform, args.backend))
    url = args.url
    if args.captured_query:
        from ..runtime.contexts import context_key
        url = credential.get("contexts", {}).get(context_key(url), {}).get("url", url)
    if args.without_signature:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        parts = urlsplit(url)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([(k, v) for k, v in parse_qsl(parts.query) if k not in {"a_bogus", "msToken", "verifyFp", "fp"}]), ""))
    if args.drop_query_key:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        parts = urlsplit(url)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path,
            urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key not in args.drop_query_key]), ""))
    async with HttpSession(spec, credential, store=store) as http:
        body = await http.json("GET", url)
        if isinstance(body, dict):
            data = body.get("data") or {}
            actual = data.get("shop_name") if isinstance(data, dict) else None
            print(json.dumps({"code": body.get("code", body.get("error_code")), "keys": list(body),
                "data_keys": list(data) if isinstance(data, dict) else type(data).__name__,
                "expected_shop_matches": actual == profile["shop"] if actual else None,
                "error_message": __import__("commerce_api.core.errors", fromlist=["redact"]).redact(body.get("msg", "")) if body.get("code") else None}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--captured-query", action="store_true")
    parser.add_argument("--without-signature", action="store_true")
    parser.add_argument("--drop-query-key", action="append", default=[], help="开发对比时仅移除指定查询键，不回显其值")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        from ..core.errors import redact
        print(json.dumps({"type": type(exc).__name__, "message": redact(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
