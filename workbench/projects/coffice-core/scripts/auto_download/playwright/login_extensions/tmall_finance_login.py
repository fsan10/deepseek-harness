# -*- coding: utf-8 -*-
"""天猫财务账号登录扩展（Playwright + Cloak Login CDP）。

使用固定账号及进程环境或 Windows 当前用户环境变量中的密码，通过 Playwright
键盘事件输入登录表单。检测到可见滑块后自动完成拖动。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import re
import sys
from typing import Any

from playwright.async_api import Page, async_playwright

SELLER_HOME_URL = "https://myseller.taobao.com/home.htm"
DEFAULT_USERNAME = "MOCK旗舰店"
DEFAULT_PASSWORD_ENV = "TMALL_LOGIN_PASSWORD"
HOME_URL_RE = re.compile(r"^https://myseller\.taobao\.com/home\.htm(?:[/?#]|$)")
MAX_SLIDER_ROUNDS = 6


def _read_environment_value(name: str) -> str:
    """读取环境变量；Windows 进程环境过期时回退到当前用户环境配置。"""
    value = os.environ.get(name, "")
    if value:
        return value
    if os.name != "nt":
        return ""

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            raw_value, _ = winreg.QueryValueEx(key, name)
        return str(raw_value)
    except (FileNotFoundError, OSError, TypeError):
        return ""


async def _login_surface(page: Page) -> Any:
    iframe = page.locator("iframe#alibaba-login-box")
    if await iframe.count() and await iframe.first.is_visible():
        return page.frame_locator("iframe#alibaba-login-box")
    return page


async def _visible_slider_locators(page: Page, surface: Any) -> tuple[Any | None, Any | None]:
    """遍历 frame 树选择有真实边界框的挑战，避开登录 frame 内尺寸为 0 的旧节点。"""
    candidates = [surface, *page.frames]
    for candidate in candidates:
        for track_selector, handle_selector in (
            ("#nc_1_n1t", "#nc_1_n1z"),
            ('[id$="_n1t"]', '[id$="_n1z"]'),
        ):
            tracks = candidate.locator(track_selector)
            handles = candidate.locator(handle_selector)
            count = min(await tracks.count(), await handles.count())
            for index in range(count - 1, -1, -1):
                track = tracks.nth(index)
                handle = handles.nth(index)
                if await track.bounding_box() is not None and await handle.bounding_box() is not None:
                    return track, handle
    return None, None


async def _slider_visible(page: Page, surface: Any) -> bool:
    try:
        track, handle = await _visible_slider_locators(page, surface)
        if track is None or handle is None:
            return False
        return await track.bounding_box() is not None and await handle.bounding_box() is not None
    except Exception:
        return False


async def _find_challenge_frame(page: Page) -> Any | None:
    for frame in page.frames:
        if "punish" in frame.url:
            return frame
    return None


async def _challenge_text(page: Page) -> str:
    frame = await _find_challenge_frame(page)
    if frame is None:
        return ""
    try:
        return (await frame.locator("body").inner_text()).strip()
    except Exception:
        return ""


def _judge_slider_text(text: str) -> str:
    """按成功、失败、未知的优先级判定挑战文本。"""
    if any(word in text for word in ("验证通过", "验证成功")):
        return "pass"
    if any(
        word in text
        for word in ("验证失败", "点击框体重试", "请点我重试", "请重试", "再试一次")
    ):
        return "fail"
    return "unknown"


async def _click_retry_box(page: Page) -> bool:
    """点击失败态 #nc_1_nocaptcha，使挑战恢复为滑动型。"""
    frame = await _find_challenge_frame(page)
    if frame is None:
        return False
    retry_box = frame.locator("#nc_1_nocaptcha")
    if not await retry_box.count() or await retry_box.bounding_box() is None:
        return False
    await retry_box.click()
    await asyncio.sleep(1.5)
    return True


async def _slider_challenge_present(page: Page, surface: Any) -> bool:
    if await _slider_visible(page, surface):
        return True
    text = await _challenge_text(page)
    return "向右滑动" in text or _judge_slider_text(text) == "fail"


async def _human_drag_slider(page: Page, frame: Any) -> None:
    """使用已实测通过的慢速拟人轨迹拖动，并在终点超程保持。"""
    track = frame.locator("#nc_1_n1t")
    handle = frame.locator("#nc_1_n1z")
    track_box = await track.bounding_box()
    handle_box = await handle.bounding_box()
    if track_box is None or handle_box is None:
        raise RuntimeError("滑块轨道或手柄不可见")

    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2
    end_x = track_box["x"] + track_box["width"] - handle_box["width"] / 2 + 10
    await handle.hover()
    await asyncio.sleep(0.6 + random.uniform(0, 0.3))
    await page.mouse.move(start_x, start_y)
    await asyncio.sleep(0.5 + random.uniform(0, 0.2))
    await page.mouse.down()
    await asyncio.sleep(0.5 + random.uniform(0, 0.2))
    steps = 130
    for step in range(1, steps + 1):
        progress = step / steps
        x = start_x + (end_x - start_x) * (1 - math.cos(progress * math.pi)) / 2
        y = start_y + math.sin(progress * math.pi) * 2.5 + random.uniform(-1.0, 1.0)
        await page.mouse.move(x, y)
        velocity = math.sin(progress * math.pi)
        delay = random.uniform(0.022, 0.048) / (0.35 + 0.65 * velocity)
        await asyncio.sleep(delay)
    await page.mouse.move(end_x + 10, start_y + random.uniform(-2, 2))
    await asyncio.sleep(1.0)
    await page.mouse.up()
    await asyncio.sleep(3.0)


async def _smooth_drag_slider(page: Page, surface: Any) -> None:
    """最多六轮处理滑动型和点击重试型挑战，直至验证通过。"""
    for round_no in range(1, MAX_SLIDER_ROUNDS + 1):
        text = await _challenge_text(page)
        judgement = _judge_slider_text(text)
        if judgement == "pass":
            return
        if judgement == "fail":
            if await _click_retry_box(page):
                continue
            await asyncio.sleep(1.5)
            continue

        frame = await _find_challenge_frame(page)
        track, handle = await _visible_slider_locators(page, surface)
        if frame is None or track is None or handle is None:
            if not await _slider_challenge_present(page, surface):
                return
            await asyncio.sleep(1.5)
            continue

        handle_before = await handle.bounding_box()
        await _human_drag_slider(page, frame)
        try:
            handle_after = await handle.bounding_box()
        except Exception:
            handle_after = None
        if handle_before is not None and handle_after is not None:
            moved = handle_after["x"] - handle_before["x"]
            if moved < 100:
                await asyncio.sleep(1)
                continue

        result = await _challenge_text(page)
        judgement = _judge_slider_text(result)
        if judgement == "pass":
            return
        if judgement == "fail":
            continue
        slider_gone = not await _slider_visible(page, await _login_surface(page))
        if slider_gone and "向右滑动" not in result:
            return
        await asyncio.sleep(1)

    raise RuntimeError(f"连续 {MAX_SLIDER_ROUNDS} 轮自动滑块验证仍未通过")


async def _fill_login_form(
    page: Page,
    username: str,
    password_env: str,
) -> tuple[Any, Any, str, str]:
    surface = await _login_surface(page)
    account = surface.locator("#fm-login-id")
    password = surface.locator("#fm-login-password")
    await account.wait_for(state="visible", timeout=30000)

    typed_username = username
    typed_password = _read_environment_value(password_env)
    if not typed_password:
        raise RuntimeError(
            f"未读取到登录密码；请设置当前用户环境变量 {password_env}"
        )

    await _type_credentials(account, password, typed_username, typed_password)
    return surface, surface.locator("button.fm-submit"), typed_username, typed_password


async def _type_credentials(
    account: Any,
    password: Any,
    username: str,
    password_value: str,
) -> None:
    """通过键盘事件输入凭据，确保前端组件收到 input/change 事件。"""
    await account.click()
    await account.press("Control+A")
    await account.type(username, delay=50)
    await password.click()
    await password.press("Control+A")
    await password.type(password_value, delay=50)


async def _resubmit_after_slider(
    page: Page,
    username: str,
    password_value: str,
) -> Any:
    """滑块通过后确认表单值完整，并点击登录按钮。"""
    deadline = asyncio.get_running_loop().time() + 4
    last_surface = await _login_surface(page)
    while asyncio.get_running_loop().time() < deadline:
        if HOME_URL_RE.match(page.url) and "loginmyseller" not in page.url:
            return await _login_surface(page)
        surface = await _login_surface(page)
        last_surface = surface
        account = surface.locator("#fm-login-id")
        password = surface.locator("#fm-login-password")
        if await account.count() and await password.count():
            try:
                if await account.first.is_visible() and await password.first.is_visible():
                    current_account = (await account.input_value()).strip()
                    current_password = await password.input_value()
                    if current_account != username or current_password != password_value:
                        await _type_credentials(account, password, username, password_value)
                    button = surface.locator("button.fm-submit").first
                    await button.click()
                    return surface
            except Exception:
                pass
        await asyncio.sleep(0.25)
    return last_surface


async def _login_diagnostics(page: Page, surface: Any) -> str:
    """返回不包含账号、密码内容的登录现场信息。"""
    account = surface.locator("#fm-login-id")
    password = surface.locator("#fm-login-password")
    button = surface.locator("button.fm-submit").first
    wrapper = surface.locator('[id$="_wrapper"]:visible').last
    track, handle = await _visible_slider_locators(page, surface)

    async def count(locator: Any) -> int:
        return await locator.count()

    account_length = len(await account.input_value()) if await count(account) else 0
    password_length = len(await password.input_value()) if await count(password) else 0
    button_enabled = await button.is_enabled() if await count(button) else False
    wrapper_visible = await wrapper.is_visible() if await count(wrapper) else False
    track_box = await track.bounding_box() if track is not None else None
    handle_box = await handle.bounding_box() if handle is not None else None
    return (
        f"账号长度={account_length}，密码长度={password_length}，登录按钮可用={button_enabled}，"
        f"滑块容器可见={wrapper_visible}，轨道边界={track_box}，手柄边界={handle_box}"
    )


async def ensure_tmall_login(
    page: Page,
    username: str = DEFAULT_USERNAME,
    password_env: str = DEFAULT_PASSWORD_ENV,
    _refresh_retry: bool = True,
    _credentials: tuple[str, str] | None = None,
) -> None:
    """确保已登录千牛商家中心，并自动处理当前可见滑块。"""
    if HOME_URL_RE.match(page.url) and "loginmyseller" not in page.url:
        await page.wait_for_load_state("domcontentloaded")
        return
    if "loginmyseller.taobao.com" not in page.url:
        await page.goto(SELLER_HOME_URL, wait_until="domcontentloaded")
        if HOME_URL_RE.match(page.url) and "loginmyseller" not in page.url:
            return

    if _credentials is None:
        surface, login_button, typed_username, typed_password = await _fill_login_form(
            page, username, password_env
        )
    else:
        typed_username, typed_password = _credentials
        surface = await _login_surface(page)
        account = surface.locator("#fm-login-id")
        password = surface.locator("#fm-login-password")
        await account.wait_for(state="visible", timeout=10000)
        await _type_credentials(account, password, typed_username, typed_password)
        login_button = surface.locator("button.fm-submit")
    deadline = asyncio.get_running_loop().time() + 12
    slider_attempts = 0
    if await _slider_challenge_present(page, surface):
        slider_attempts += 1
        try:
            await _smooth_drag_slider(page, surface)
        except RuntimeError:
            if _refresh_retry:
                await page.reload(wait_until="domcontentloaded")
                return await ensure_tmall_login(
                    page, username, password_env, False, (typed_username, typed_password)
                )
            raise
        surface = await _resubmit_after_slider(page, typed_username, typed_password)
    else:
        await login_button.click()

    while asyncio.get_running_loop().time() < deadline:
        if HOME_URL_RE.match(page.url) and "loginmyseller" not in page.url:
            return
        if await _slider_challenge_present(page, surface):
            if slider_attempts >= 2:
                if _refresh_retry:
                    await page.reload(wait_until="domcontentloaded")
                    return await ensure_tmall_login(
                        page, username, password_env, False, (typed_username, typed_password)
                    )
                raise RuntimeError("连续两次自动滑块后仍要求验证")
            slider_attempts += 1
            try:
                await _smooth_drag_slider(page, surface)
            except RuntimeError:
                if _refresh_retry:
                    await page.reload(wait_until="domcontentloaded")
                    return await ensure_tmall_login(
                        page, username, password_env, False, (typed_username, typed_password)
                    )
                raise
            surface = await _resubmit_after_slider(page, typed_username, typed_password)
        await asyncio.sleep(0.5)

    if _refresh_retry:
        await page.reload(wait_until="domcontentloaded")
        return await ensure_tmall_login(
            page, username, password_env, False, (typed_username, typed_password)
        )

    login_surface = await _login_surface(page)
    slider_state = "可见" if await _slider_visible(page, login_surface) else "隐藏"
    diagnostics = await _login_diagnostics(page, login_surface)
    raise RuntimeError(
        f"天猫登录后未进入商家中心，当前页面：{page.url}；滑块：{slider_state}；{diagnostics}"
    )


async def _find_page(browser) -> Page:
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith(("https://myseller.taobao.com", "https://loginmyseller.taobao.com")):
                return page
    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用的浏览器上下文")
    return await browser.contexts[0].new_page()


async def run(cdp_url: str, username: str, password_env: str) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        page = await _find_page(browser)
        await ensure_tmall_login(page, username, password_env)
        print(f"天猫登录成功：{page.url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫财务账号登录扩展")
    parser.add_argument("--cdp", required=True, help="Cloak Login profile 的 wsEndpoint")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="登录账号，默认 MOCK旗舰店")
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV, help="密码环境变量名")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(args.cdp, args.username, args.password_env))
    except Exception as exc:
        print(f"登录失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
