"""Development-only read probe: compare one real query with direct HTTP.

No export, login, send-code, cookie value or response body is printed.
"""
import argparse
import asyncio
import contextlib
import json

from commerce_api.integrations.legacy.environment import prepare
from commerce_api.integrations.legacy.locking import legacy_browser_lock
from commerce_api.integrations.legacy.profiles import select_profile, resolve_connection


async def run(name, seed=False):
    prepare()
    import httpx
    from playwright.async_api import async_playwright
    from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import _query_button, open_promotion_page
    profile = select_profile(name, "pinduoduo")
    with legacy_browser_lock():
        connection = await asyncio.to_thread(resolve_connection, profile)
        async with async_playwright() as engine:
            browser = await engine.chromium.connect_over_cdp(connection.endpoint)
            context = browser.contexts[0]
            before = set(context.pages)
            try:
                result = await open_promotion_page(context, platform="拼多多", company=profile.company, shop=profile.shop)
                page = result[0] if isinstance(result, tuple) else result
                async with page.expect_response(lambda r: "/invoice/getDailyInvoice" in r.url and r.request.method == "POST", timeout=30000) as info:
                    await (await _query_button(page)).click()
                response = await info.value
                request = response.request
                observed = await response.json()
                headers = {k: v for k, v in (await request.all_headers()).items()
                    if not k.startswith(":") and k.lower() not in {"host", "content-length", "accept-encoding", "connection"}}
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=20) as client:
                    copied = await client.post(request.url, content=(request.post_data or "").encode(), headers=headers)
                    body = copied.json()
                from commerce_api.runtime.http import HttpSession
                from commerce_api.core.registry import Registry
                from commerce_api.runtime.contexts import context_key
                credential = {"platform": "pinduoduo", "backend": "promotion", "cookies": await context.cookies(),
                    "user_agent": headers["user-agent"], "contexts": {context_key(request.url): {
                        "url": request.url, "headers": {k: v for k, v in headers.items() if k != "cookie"}}}}
                async with HttpSession(Registry().backend("pinduoduo", "promotion"), credential) as session:
                    assembled = session.client.build_request("POST", request.url,
                        json=json.loads(request.post_data or "{}"), headers=session.headers(request.url))
                    def cookies(value):
                        return dict(pair.strip().split("=", 1) for pair in value.split(";") if "=" in pair)
                    actual_cookies = cookies(headers.get("cookie", ""))
                    jar_cookies = cookies(assembled.headers.get("cookie", ""))
                    differences = [k for k in set(actual_cookies) | set(jar_cookies)
                        if actual_cookies.get(k) != jar_cookies.get(k)]
                    rebuilt = await session.client.send(assembled)
                    rebuilt_body = rebuilt.json()
                    altered_payload = json.loads(request.post_data or "{}")
                    altered_payload["pageSize"] = 1
                    altered = await session.client.post(request.url, json=altered_payload, headers=session.headers(request.url))
                    altered_body = altered.json()
                    from commerce_api.platforms.pinduoduo.backends.promotion.client import Client
                    scoped = Client(Registry().backend("pinduoduo", "promotion"), credential, profile)
                    try:
                        merchant = await scoped.post("https://mms.pinduoduo.com/janus/api/userinfo", {})
                        after_merchant = await scoped.http.client.post(request.url, content=(request.post_data or "").encode(), headers=scoped.http.headers(request.url))
                        after_merchant_body = after_merchant.json()
                    finally:
                        await scoped.close()
                    minimal_payload = json.loads(request.post_data or "{}")
                    minimal_payload.pop("crawlerInfo", None)
                    minimal = await session.client.post(request.url, json=minimal_payload,
                        headers={"origin": "https://yingxiao.pinduoduo.com", "referer": "https://yingxiao.pinduoduo.com/mains/account/report"})
                    minimal_body = minimal.json()
                    from commerce_api.runtime.sessions import SessionStore, session_key
                    from commerce_api.runtime.storage import Paths
                    saved = SessionStore(Paths()).load(session_key(profile.id, "pinduoduo", "promotion"))
                    previous_cookies = { (c["name"], c["domain"], c.get("path", "/")): c["value"] for c in saved["cookies"] }
                    fresh_cookies = { (c["name"], c["domain"], c.get("path", "/")): c["value"] for c in credential["cookies"] }
                    changed_names = sorted({k[0] for k in set(previous_cookies) | set(fresh_cookies)
                        if previous_cookies.get(k) != fresh_cookies.get(k)})
                    from commerce_api.runtime.backend import BackendClient
                    saved_session = HttpSession(Registry().backend("pinduoduo", "promotion"), saved)
                    try:
                        restored = await saved_session.client.post(request.url, content=(request.post_data or "").encode(), headers={k: v for k, v in headers.items() if k != "cookie"})
                        restored_body = restored.json()
                    finally:
                        await saved_session.close()
                    # Persist current browser context only when explicitly asked;
                    # production collection never imports this discovery tool.
                    if seed:
                        from commerce_api.runtime.contexts import context_key
                        saved.update(cookies=credential["cookies"], user_agent=credential["user_agent"])
                        saved["contexts"][context_key(request.url)] = {"url": request.url,
                            "headers": {k: v for k, v in headers.items() if k != "cookie"}, "post_data": request.post_data}
                        SessionStore(Paths()).save(session_key(profile.id, "pinduoduo", "promotion"), saved)
                print(json.dumps({"browser_success": observed.get("success"), "http_status": copied.status_code,
                    "direct_success": body.get("success"), "direct_code": body.get("errorCode"),
                    "header_count": len(headers), "cookie_present": "cookie" in headers,
                    "jar_success": rebuilt_body.get("success"), "cookie_mismatch_names": differences,
                    "body_bytes_equal": assembled.content == (request.post_data or "").encode(),
                    "minimal_success": minimal_body.get("success"), "minimal_code": minimal_body.get("errorCode"),
                    "saved_cookie_changed_names": changed_names, "saved_cookie_fresh_headers_success": restored_body.get("success"),
                    "altered_page_size_success": altered_body.get("success"), "after_merchant_success": after_merchant_body.get("success")}, ensure_ascii=False))
            finally:
                for page in list(context.pages):
                    if page not in before and len(context.pages) > 1:
                        with contextlib.suppress(Exception):
                            await page.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.profile, seed=args.seed))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
