"""Probe only allowlisted read endpoints independently of the browser."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re

from ..core.registry import Registry
from ..runtime.http import HttpSession
from ..runtime.sessions import protect

READ_ONLY = re.compile(r"queryExportTaskInfo|qualification/shop/info|janus/api/userinfo|queryCapitalFlowPage|queryDailyBillByPage|query_period_|get_bill_download_url|account/info|queryBillDownloadTaskList|/export/task/list|/fundDailyStat|listAccountJournal|/exportHistory$|/query_item")


async def run(args):
    from pathlib import Path
    from urllib.parse import urlsplit
    capture = json.loads(protect((Path(args.directory) / "context.enc").read_bytes(), decrypt=True))
    matches = [r for r in capture["records"] if re.search(args.match, r["url"])]
    if not matches:
        raise ValueError("No matching captured request")
    record = matches[-1]
    from ..runtime.contexts import context_key
    if not READ_ONLY.search(context_key(record["url"])):
        raise ValueError("Endpoint is not explicitly read-allowlisted")
    spec = Registry().backend(capture["platform"], capture["backend"])
    headers = {k: v for k, v in record["headers"].items() if not k.startswith(":")
        and k.lower() not in {"cookie", "host", "content-length", "accept-encoding", "connection"}}
    if args.omit_signatures:
        headers = {k: v for k, v in headers.items() if k.lower() not in {"h5st", "dsm-trace-id", "a-bogus", "anti-content"}}
    credential = {"platform": capture["platform"], "backend": capture["backend"],
        "user_agent": capture["user_agent"], "cookies": capture["cookies"]}
    payload = json.loads(record["post_data"]) if record["post_data"] else None
    if args.mutate and payload and "exportParam" in payload:
        payload["exportParam"]["pageSize"] = 1
    async with HttpSession(spec, credential) as session:
        body = await session.json(record["method"], record["url"], payload=payload, headers=headers)
        from ..core.errors import redact
        print(json.dumps({"code": body.get("code", body.get("error_code")), "keys": list(body),
            "message": redact(body.get("msg", body.get("message", ""))),
            "data_keys": list(body.get("data", {})) if isinstance(body.get("data"), dict) else type(body.get("data")).__name__}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--match", required=True)
    parser.add_argument("--omit-signatures", action="store_true")
    parser.add_argument("--mutate", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        from ..core.errors import redact
        print(json.dumps({"error": type(exc).__name__, "message": redact(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
