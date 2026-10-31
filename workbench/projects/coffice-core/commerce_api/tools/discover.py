"""Development-only request discovery around unchanged, isolated DOM flows.

The shared skill capture tool records a redacted diagnostic capture. Request
contexts needed to implement independent HTTP are separately DPAPI-encrypted.
Neither this module nor any DOM download is imported by production dispatch.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import importlib
import importlib.util
import io
import json
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from ..core.errors import redact
from ..integrations.legacy.environment import prepare
from ..integrations.legacy.locking import legacy_browser_lock
from ..integrations.legacy.profiles import resolve_connection, select_profile
from ..runtime.sessions import protect
from ..runtime.storage import Paths, atomic_json

MODULES = {
    ("douyin", "order", "merchant"): "douyin_order_download",
    ("douyin", "fund", "merchant"): "douyin_bill_download",
    ("douyin", "settlement", "merchant"): "douyin_bill_download",
    ("douyin", "promotion", "qianchuan"): "qianchuan_promotion_fee_download",
    ("jd", "order", "merchant"): "jd_order_download",
    ("jd", "fund", "merchant"): "jd_fund_download",
    ("jd", "settlement", "merchant"): "jd_settlement_download",
    ("jd", "promotion", "promotion"): "jd_promotion_fee_download",
    ("pinduoduo", "order", "merchant"): "pinduoduo_order_download",
    ("pinduoduo", "settlement", "cashier"): "pinduoduo_settlement_download",
    ("pinduoduo", "promotion", "promotion"): "pinduoduo_promotion_fee_download",
    ("kuaishou", "order", "merchant"): "kuaishou_order_download",
    ("kuaishou", "fund", "finance"): "kuaishou_fund_download",
    ("kuaishou", "settlement", "finance"): "kuaishou_settlement_download",
    ("xiaohongshu", "order", "merchant"): "xiaohongshu_order_download",
    ("xiaohongshu", "fund", "merchant"): "xiaohongshu_fund_download",
    ("xiaohongshu", "settlement", "merchant"): "xiaohongshu_settlement_download",
    ("tmall", "order", "qianniu"): "tmall_order_download",
    ("tmall", "fund", "aggregate"): "tmall_aggregate_fund_download",
    ("tmall", "fund", "alipay"): "tmall_alipay_fund_download",
    ("tmall", "promotion", "alimama"): "tmall_taobao_union_promotion_download",
    ("tmall", "promotion", "wanxiangtai"): "tmall_wanxiangtai_promotion_download",
}


def load_capture(root):
    path = root / ".codex/skills/ecommerce-webapi-builder/scripts/ecommerce_http_capture.py"
    spec = importlib.util.spec_from_file_location("commerce_development_capture", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, path.with_name("platform_filters.json")


async def run(args):
    root = prepare()
    profile = select_profile(args.profile, args.platform)
    name = MODULES.get((args.platform, args.kind, args.backend))
    if not name:
        raise ValueError("没有已登记的 DOM 发现流程")
    paths = Paths()
    identifier = f"{args.platform}_{args.backend}_{args.kind}_{uuid.uuid4().hex[:10]}"
    directory = paths.root / "discovery" / identifier
    directory.mkdir(parents=True)
    capture, filters = load_capture(root)
    capture.log = lambda stage, message: print(f"[capture:{stage}] {redact(message)}", flush=True) if stage in {"READY", "WARN", "RESTART"} else None
    rules = capture.PlatformCatalog(filters).build_rules("qianchuan" if args.backend == "qianchuan" else args.platform,
        include_domains=[], exclude_domains=[], exclude_url_regex=[], capture_all_http=False)
    with legacy_browser_lock():
        connection = await asyncio.to_thread(resolve_connection, profile)
    manager = capture.CaptureManager(debug_port=urlsplit(connection.endpoint).port,
        output_path=directory / "capture.redacted.json", rules=rules, profile_name=profile.name,
        label=args.kind, max_body_chars=500000, scan_interval_seconds=.2, stale_target_seconds=8)
    records = []
    probe_results = []
    history_probe_started = False
    pending = set()
    snapshot = {"cookies": [], "user_agent": "", "at": 0}
    from playwright.async_api import async_playwright, Browser
    original_close = Browser.close

    async def preserve_borrowed_browser(*unused, **kwargs):
        return None

    async def capture_response(response):
        nonlocal history_probe_started
        try:
            request = response.request
            if (request.resource_type not in {"xhr", "fetch", "document", "other"}
                and not (request.resource_type == "script" and "/h5/" in request.url)) or not rules.url_in_scope(request.url):
                return
            if len(records) >= 3000:
                return
            headers = request.headers
            with contextlib.suppress(Exception):
                headers = await request.all_headers()
            if time.time() - snapshot["at"] > 5:
                with contextlib.suppress(Exception):
                    snapshot.update(cookies=await request.frame.page.context.cookies(),
                                    user_agent=headers.get("user-agent", ""), at=time.time())
            wire_headers = dict(headers)
            headers = {k: v for k, v in headers.items() if k.lower() not in {"cookie", "host", "content-length"}}
            body = None
            with contextlib.suppress(Exception):
                text = await response.text()
                if len(text) < 2000000:
                    with contextlib.suppress(ValueError):
                        body = json.loads(text)
                    if body is None:
                        match = re.fullmatch(r"[A-Za-z_$][\w$]*\((.*)\);?", text.strip(), re.S)
                        if match:
                            with contextlib.suppress(ValueError):
                                body = json.loads(match[1])
            records.append({"url": request.url, "method": request.method, "headers": headers,
                "post_data": request.post_data, "status": response.status, "response": body, "captured_at": time.time()})
            if (args.probe_history_http and not history_probe_started
                    and urlsplit(request.url).path == "/order/torder/exportHistory"
                    and isinstance(body, dict) and body.get("code") == 0):
                history_probe_started = True
                from ..core.registry import Registry
                from ..runtime.http import HttpSession
                from ..runtime.sessions import SessionStore, session_key
                from ..runtime.contexts import context_key
                from urllib.parse import parse_qsl
                cookies = await request.frame.page.context.cookies()
                credential = {"platform": args.platform, "backend": args.backend, "cookies": cookies,
                    "user_agent": wire_headers.get("user-agent") or snapshot["user_agent"]}
                natural_headers = {k: v for k, v in wire_headers.items() if not k.startswith(":")
                    and k.lower() not in {"host", "content-length", "accept-encoding", "connection"}}
                spec = Registry().backend(args.platform, args.backend)
                async with HttpSession(spec, credential) as http:
                    info = {"browser_code": body["code"], "browser_total": body.get("total")}
                    try:
                        previous = SessionStore(paths).load(session_key(profile.id, args.platform, args.backend))
                        saved = previous.get("contexts", {}).get(context_key(request.url), {})
                        old_query = dict(parse_qsl(urlsplit(saved.get("url", "")).query, keep_blank_values=True))
                        fresh_query = dict(parse_qsl(urlsplit(request.url).query, keep_blank_values=True))
                        info["session_fields_changed"] = [key for key in ("appid", "__token", "_bid", "aid", "_lid", "verifyFp", "fp", "msToken")
                            if old_query.get(key) != fresh_query.get(key)]
                        info["user_agent_changed"] = previous.get("user_agent") != credential["user_agent"]
                    except Exception:
                        info["previous_context_available"] = False
                    try:
                        # Development-only, exact natural read. Cookie stays in
                        # memory; no signed URL or response body is logged.
                        probe = await http.client.get(request.url, headers=natural_headers)
                        info.update(http_status=probe.status_code, body_bytes=len(probe.content),
                            content_type=probe.headers.get("content-type", "").split(";")[0],
                            content_encoding=probe.headers.get("content-encoding", "identity"))
                        try:
                            result = json.loads(probe.text.lstrip("\ufeff"))
                            info.update(code=result.get("code"), response_keys=list(result), total=result.get("total"))
                        except (ValueError, AttributeError):
                            info["json"] = False
                        if info.get("code") == 0:
                            context_credential = {**credential, "contexts": {context_key(request.url): {
                                "url": request.url, "headers": headers}}}
                            async with HttpSession(spec, context_credential) as runtime_http:
                                built = runtime_http.client.build_request("GET", request.url,
                                    headers=runtime_http.headers(request.url))
                                original_cookie = next((v for k, v in natural_headers.items() if k.lower() == "cookie"), "")
                                built_cookie = built.headers.get("cookie", "")
                                def cookie_pairs(raw):
                                    return sorted(tuple(part.strip().partition("=")[::2]) for part in raw.split(";") if "=" in part)
                                info["cookie_header_matches"] = original_cookie == built_cookie
                                info["cookie_pairs_match"] = cookie_pairs(original_cookie) == cookie_pairs(built_cookie)
                                full = await runtime_http.request("GET", request.url)
                                try:
                                    full_body = json.loads(full.text.lstrip("\ufeff"))
                                    info["runtime_full_signature_code"] = full_body.get("code")
                                except ValueError:
                                    info["runtime_full_signature_json"] = False
                                if info.get("runtime_full_signature_code") == 0:
                                    from urllib.parse import urlencode, urlunsplit
                                    parts = urlsplit(request.url)
                                    unsigned_url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                                        urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                                            if key != "a_bogus"]), ""))
                                    unsigned = await runtime_http.request("GET", unsigned_url)
                                    try:
                                        info["runtime_without_a_bogus_code"] = json.loads(unsigned.text.lstrip("\ufeff")).get("code")
                                    except ValueError:
                                        info["runtime_without_a_bogus_json"] = False
                    except Exception as exc:
                        info["error_type"] = type(exc).__name__
                    probe_results.append(info)
        except Exception:
            pass

    def observe(response):
        task = asyncio.create_task(capture_response(response))
        pending.add(task)
        task.add_done_callback(pending.discard)

    with legacy_browser_lock():
        manager.start()
        print("[READY] Shared capture listener started; legacy production checkpoints are not used", flush=True)
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(connection.endpoint)
                context = browser.contexts[0]
                context.on("response", observe)
                module = importlib.import_module("scripts.auto_download.playwright." + name)
                if name == "douyin_order_download" and args.history_readonly:
                    async def observe_douyin_history():
                        async with async_playwright() as auth_playwright:
                            current_browser = await auth_playwright.chromium.connect_over_cdp(connection.endpoint)
                            current_context = current_browser.contexts[0]
                            current_page, _ = await module.open_order_page(current_context, profile.shop,
                                platform="抖音", company=profile.company)
                            await module.open_export_history(current_page)
                            await asyncio.sleep(3)
                            return 0 if any("/order/torder/exportHistory" in item["url"]
                                and isinstance(item.get("response"), dict) for item in records) else 1
                    def history_readonly_main():
                        try:
                            return asyncio.run(asyncio.wait_for(observe_douyin_history(), timeout=120))
                        except Exception as exc:
                            print(json.dumps({"history_discovery_failed": type(exc).__name__}))
                            return 1
                    module.main = history_readonly_main
                if args.auth_only:
                    from ..runtime.auth import AuthManager
                    from ..core.registry import Registry
                    from ..core.errors import CommerceError
                    def auth_main():
                        manager = AuthManager(paths, Registry(), login_timeout=180)
                        backend = manager.registry.backend(args.platform, args.backend)
                        try:
                            asyncio.run(manager.login(profile, backend, already_locked=True))
                            return 0
                        except CommerceError as exc:
                            print(json.dumps(exc.public(), ensure_ascii=False))
                            return exc.exit_code
                    module.main = auth_main
                if name == "tmall_alipay_fund_download" and not args.auth_only:
                    original_account_info, original_alipay_page = module.open_account_info, module.open_alipay_page
                    async def existing_alipay_account(page, shop):
                        if any(urlsplit(p.url).hostname == "b.alipay.com" for p in page.context.pages):
                            return
                        return await original_account_info(page, shop)
                    async def existing_alipay_page(page):
                        found = next((p for p in reversed(page.context.pages) if urlsplit(p.url).hostname == "b.alipay.com"), None)
                        return (found, False) if found else await original_alipay_page(page)
                    module.open_account_info, module.open_alipay_page = existing_alipay_account, existing_alipay_page
                if name == "tmall_order_download" and args.reuse_export_only:
                    async def existing_order_export(page, state_path, state, start_date, end_date):
                        module.update_state(state_path, state, "EXPORT_CREATED", creation_mode="recovered", submitted_at="")
                        return await module.open_export_history(page)
                    module.create_export_task = existing_order_export
                if name == "tmall_taobao_union_promotion_download" and not args.auth_only:
                    from ..integrations.legacy.login import _open_tmall_marketing
                    from ..runtime.sessions import SessionStore, session_key
                    from ..core.registry import Registry
                    from ..core.errors import AuthRequired
                    async def current_marketing_entry(browser, target, username, password_env):
                        backend = Registry().backend("tmall", "alimama")
                        try:
                            previous = SessionStore(paths).load(session_key(profile.id, "tmall", "alimama"))
                        except AuthRequired:
                            previous = {}
                        current = next((p for p in reversed(browser.contexts[0].pages)
                            if urlsplit(p.url).hostname == "myseller.taobao.com"), browser.contexts[0].pages[0])
                        return await _open_tmall_marketing(browser, current, browser.contexts[0], profile, backend, None, previous, {})
                    module.open_alimama_page = current_marketing_entry
                if name == "pinduoduo_promotion_fee_download":
                    async def api_guarded_promotion_query(page, *unused, **kwargs):
                        from decimal import Decimal
                        before_count = len(records)
                        await (await module._query_button(page)).click()
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            for item in reversed(records[before_count:]):
                                if "/invoice/getDailyInvoice" not in item["url"] or not item["response"]:
                                    continue
                                payload = json.loads(item["post_data"] or "{}")
                                if payload.get("fundType") != 1 or payload.get("flowType") != 2:
                                    continue
                                for field, argument in (("startDate", "start_date"), ("endDate", "end_date")):
                                    if kwargs.get(argument) and payload.get(field) != str(kwargs[argument]):
                                        raise ValueError("开发发现的推广费 API 日期与请求不一致")
                                result = item["response"]["result"]
                                total = int(result["total"])
                                amount = (result.get("summary") or {}).get("spendAmount") or {}
                                if "value" not in amount:
                                    raise ValueError("开发发现缺少现金支出合计")
                                return total, abs(Decimal(str(amount["value"])))
                            await asyncio.sleep(.1)
                        raise TimeoutError("开发发现未收到已验证现金支出查询响应")
                    module.query_filtered_rows = api_guarded_promotion_query
                # Development-only compatibility for the legacy monthly locator:
                # its daily [col-id=setDate] selector cannot read monthly rows.
                # Use the same visible monthly row/button; never edit old files.
                if name == "jd_settlement_download" and args.mode == "month":
                    original_latest_row = module.latest_row
                    async def monthly_row(page, mode, target_date=None):
                        if mode != "month":
                            return await original_latest_row(page, mode, target_date)
                        row = page.locator(".ag-row.ag-row-level-0:visible").filter(has_text=args.date[:7]).first
                        await row.wait_for(state="visible", timeout=30000)
                        return row, args.date[:7]
                    module.latest_row = monthly_row
                source = (root / "scripts/auto_download/playwright" / (name + ".py")).read_text(encoding="utf-8-sig")
                declared_flags = {argument.value for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                    for argument in node.args if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and argument.value.startswith("--")}
                arguments = [name]

                def add(flag, value):
                    if flag in declared_flags and value is not None:
                        arguments.extend([flag, str(value)])

                add("--cdp", connection.endpoint)
                add("--platform", {"douyin": "抖音", "jd": "京东", "pinduoduo": "拼多多", "kuaishou": "快手", "xiaohongshu": "小红书", "tmall": "天猫"}[profile.platform])
                add("--company", profile.company)
                add("--shop", profile.shop)
                add("--profile", profile.name)
                add("--dest", directory / "downloads")
                add("--work-dir", directory / "work")
                add("--src", directory / "source")
                add("--mode", args.mode)
                add("--history-timeout", args.history_timeout)
                if args.force_new and "--force-new" in declared_flags:
                    arguments.append("--force-new")
                if not args.default_period:
                    if args.mode == "month" and "--month" in declared_flags:
                        add("--month", args.date[:7])
                    elif args.mode == "day":
                        add("--date", args.date)
                        if args.mode == "day":
                            add("--start-date", args.date)
                            add("--end-date", args.date)
                # Some legacy parsers make --date exclusive with range arguments.
                if "--date" in arguments and "--start-date" in arguments:
                    pos = arguments.index("--date")
                    del arguments[pos:pos + 2]
                if name == "douyin_bill_download":
                    add("--report", "资金" if args.kind == "fund" else "结算")
                elif name == "jd_promotion_fee_download":
                    add("--report", "all")
                add("--aavid", "auto")
                previous = sys.argv
                Browser.close = preserve_borrowed_browser
                output = io.StringIO()
                result = 1
                try:
                    sys.argv = arguments
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        try:
                            result = await asyncio.to_thread(module.main)
                        except SystemExit as exc:
                            result = exc.code
                finally:
                    sys.argv = previous
                    Browser.close = original_close
                    context.remove_listener("response", observe)
                    if pending:
                        await asyncio.gather(*list(pending), return_exceptions=True)
                    with contextlib.suppress(Exception):
                        snapshot["cookies"] = await context.cookies()
                        if context.pages:
                            snapshot["user_agent"] = await context.pages[0].evaluate("navigator.userAgent")
                    secured = {"profile": profile.__dict__, "platform": args.platform, "backend": args.backend,
                        "kind": args.kind, "cookies": snapshot["cookies"], "user_agent": snapshot["user_agent"], "records": records}
                    (directory / "context.enc").write_bytes(protect(json.dumps(secured, ensure_ascii=False).encode()))
                    # The old scripts may report helpful labels, but raw stdout is
                    # not persisted because it can include temporary signed links.
                    tail = redact(output.getvalue()[-800:])
                    atomic_json(directory / "summary.json", {"id": identifier, "return_code": result,
                        "request_count": len(records), "platform": args.platform, "backend": args.backend,
                        "kind": args.kind, "date": args.date, "diagnostic_tail": tail, "http_probes": probe_results})
                print(json.dumps({"id": identifier, "return_code": result, "requests": len(records),
                    "summary": str(directory / "summary.json")}, ensure_ascii=False), flush=True)
        finally:
            manager.stop()
            manager.save(capture_complete=True)
            from .secure_captures import secure
            secure(directory / "capture.redacted.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--backend", default="merchant")
    parser.add_argument("--date", required=True)
    parser.add_argument("--mode", choices=("day", "month"), default="day")
    parser.add_argument("--default-period", action="store_true", help="开发发现使用旧流程的默认日期，不用于正式 API 日期选择")
    parser.add_argument("--history-timeout", type=int, default=180)
    parser.add_argument("--force-new", action="store_true", help="仅显式开发发现时创建一次新导出，用于监听未捕获的创建与验证码接口")
    parser.add_argument("--auth-only", action="store_true", help="只监听目标后台认证，不执行报表业务流程")
    parser.add_argument("--reuse-export-only", action="store_true", help="天猫订单发现仅读取原导出，不创建任务")
    parser.add_argument("--history-readonly", action="store_true", help="抖店订单仅监听打开导出历史，不创建或下载报表")
    parser.add_argument("--probe-history-http", action="store_true", help="开发监听时立即独立 HTTP 复核一次自然历史查询")
    args = parser.parse_args()
    if args.history_readonly or args.probe_history_http:
        if (args.platform, args.backend, args.kind) != ("douyin", "merchant", "order"):
            parser.error("历史只读监听仅适用于抖店订单")
        if args.auth_only or args.force_new or args.reuse_export_only or not args.history_readonly:
            parser.error("HTTP 历史探针必须搭配 --history-readonly，不能与认证或导出动作混用")
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"ok": False, "type": type(exc).__name__, "message": redact(str(exc))}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
