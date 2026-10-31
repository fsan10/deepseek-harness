"""Development inventory of page hosts/paths; excludes queries and credentials."""
import argparse
import asyncio
import json
import re
from urllib.parse import urlsplit

from commerce_api.integrations.legacy.environment import prepare
from commerce_api.integrations.legacy.profiles import select_profile, resolve_connection
from commerce_api.integrations.legacy.locking import legacy_browser_lock


async def run(args):
    prepare()
    from playwright.async_api import async_playwright
    profile = select_profile(args.profile, args.platform)
    with legacy_browser_lock():
        connection = await asyncio.to_thread(resolve_connection, profile)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(connection.endpoint)
            pages = []
            for context in browser.contexts:
                for page in context.pages:
                    url = urlsplit(page.url)
                    entry = {"host": url.hostname, "path": url.path, "title": await page.title()}
                    if args.auth_controls:
                        controls = []
                        for locator in await page.locator("a,button,[role=button]").all():
                            if not await locator.is_visible():
                                continue
                            label = (await locator.inner_text()).strip()
                            if len(label) < 35 and not re.search(r"\d", label) and re.search("推广|万相|淘宝联盟|支付宝|快速进入|立即登录|账号密码登录|资金|财务", label):
                                controls.append({"label": label, "tag": await locator.evaluate("e => e.tagName")})
                        entry["auth_controls"] = controls[:50]
                    pages.append(entry)
            print(json.dumps(pages, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--auth-controls", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
