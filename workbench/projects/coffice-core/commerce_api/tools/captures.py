"""Inspect encrypted discovery schemas or seed an owned encrypted HTTP session."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..core.registry import Registry
from ..runtime.sessions import SessionStore, protect, session_key
from ..runtime.storage import Paths, atomic_json


def shape(value, depth=0, field=""):
    if depth >= 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: shape(v, depth + 1, k) for k, v in list(value.items())[:70]}
    if isinstance(value, list):
        return {"count": len(value), "item": shape(value[0], depth + 1, field) if value else None}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if field in {"templateName", "reportName", "exportType", "templateType", "fileType", "statusStr",
                 "start_day", "end_day", "from_app", "date", "timeType", "dateType", "timeFilterType",
                 "bizCode", "loginPointId", "timeValue", "reportType", "tradeType"} and isinstance(value, str):
        return value[:100]
    if field in {"pageTotal", "pageNo", "exportCount"} and isinstance(value, str) and value.isdigit():
        return value
    if isinstance(value, str) and value[:1] in {"{", "["}:
        try:
            return {"json_string": shape(json.loads(value), depth + 1)}
        except ValueError:
            pass
    if isinstance(value, str) and value.startswith(("https://", "http://", "//")):
        parsed = urlsplit("https:" + value if value.startswith("//") else value)
        return {"url_host": parsed.hostname, "query_keys": list(parse_qs(parsed.query))}
    if isinstance(value, str) and (re.fullmatch(r"[A-Z_]{2,70}", value) or re.fullmatch(r"20\d\d-\d\d-\d\d(?:[ T]\d\d:\d\d:\d\d)?", value)):
        return value
    return "str"


def key(url):
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    discriminator = next((f"?{k}={query[k][0]}" for k in ("api", "functionId", "method", "act") if query.get(k)), "")
    return f"{parts.hostname}{parts.path}{discriminator}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--match", default="order|export|download|sms|verify|encrypt|code|password|shop/info")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--shared", action="store_true", help="检查加密的共享 CDP 捕获，不用于会话初始化")
    parser.add_argument("--last", action="store_true", help="优先查看每个接口的最后一次请求")
    args = parser.parse_args()
    value = json.loads(protect((args.directory / "context.enc").read_bytes(), decrypt=True))
    if args.shared:
        if args.seed:
            parser.error("共享捕获已脱敏，不可用于初始化认证上下文")
        raw = json.loads(protect((args.directory / "capture.enc").read_bytes(), decrypt=True))
        value["records"] = [{"url": r.get("request", {}).get("url", ""),
            "method": r.get("request", {}).get("method"), "headers": r.get("request", {}).get("headers", {}),
            "post_data": r.get("request", {}).get("post_data"), "response": r.get("response_body")}
            for r in raw.get("records", []) if r.get("record_type") == "network"]
    if args.seed:
        paths = Paths()
        backend = Registry().backend(value["platform"], value["backend"])
        contexts = {}
        for record in value["records"]:
            host = urlsplit(record["url"]).hostname or ""
            if host not in backend.domains:
                continue
            contexts[key(record["url"])] = {"url": record["url"], "method": record["method"],
                "headers": record["headers"], "post_data": record["post_data"],
                "captured_at": record["captured_at"]}
        profile = value["profile"]
        identifier = session_key(profile["id"], value["platform"], value["backend"])
        store = SessionStore(paths)
        try:
            previous = store.load(identifier)
        except __import__("commerce_api.core.errors", fromlist=["AuthRequired"]).AuthRequired:
            previous = {}
        contexts = {**previous.get("contexts", {}), **contexts}
        retained = {key: previous[key] for key in ("mtop_signer_domains", "proxy", "account_id") if key in previous}
        store.save(identifier, {**retained, "profile": profile, "platform": value["platform"],
            "backend": value["backend"], "cookies": value["cookies"], "user_agent": value["user_agent"],
            "contexts": contexts, "identity": previous.get("identity", {})})
        atomic_json(paths.file("config", "profiles"), {**__import__("commerce_api.runtime.storage", fromlist=["read_json"]).read_json(paths.file("config", "profiles"), {}), profile["name"]: profile})
        print(json.dumps({"session_saved": True, "contexts": len(contexts)}))
    seen = set()
    if args.last:
        value["records"].reverse()
    for record in value["records"]:
        if isinstance(record.get("response"), str):
            matched = re.fullmatch(r"[A-Za-z_$][\w$]*\((.*)\);?", record["response"].strip(), re.S)
            if matched:
                try:
                    record["response"] = json.loads(matched[1])
                except ValueError:
                    pass
        identifier = key(record["url"])
        if not re.search(args.match, identifier, re.I) or (identifier, record["method"]) in seen:
            continue
        seen.add((identifier, record["method"]))
        if args.index:
            print(json.dumps({"endpoint": identifier, "method": record["method"]}, ensure_ascii=False))
            continue
        body = record["post_data"]
        try:
            body = json.loads(body) if isinstance(body, str) and body else body
        except (ValueError, TypeError):
            body = {k: v[0] for k, v in parse_qs(body or "").items()}
        print(json.dumps({"endpoint": identifier, "method": record["method"],
            "query_keys": list(parse_qs(urlsplit(record["url"]).query)),
            "query": shape(parse_qs(urlsplit(record["url"]).query)),
            "header_keys": list(record["headers"]), "payload": shape(body),
            "response": shape(record["response"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
