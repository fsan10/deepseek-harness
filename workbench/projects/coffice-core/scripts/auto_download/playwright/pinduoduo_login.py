# -*- coding: utf-8 -*-
"""拼多多商家后台登录与验证码转发公共模块。"""

from __future__ import annotations

import asyncio
import os
import re
from typing import TYPE_CHECKING
from .automation_challenge import request_answer
from .component_runtime import automation_component

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Locator, Page


MMS_HOME_URL = "https://mms.pinduoduo.com/home"
LOGIN_PATH = "/login/"

def _is_login_url(url: str) -> bool:
    return "mms.pinduoduo.com/login" in (url or "")


async def _visible(locator: "Locator") -> bool:
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def _first_visible(locator: "Locator") -> "Locator | None":
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def _switch_to_account_login(page: "Page") -> None:
    username = page.locator(
        '#usernameId, input[placeholder="请输入账号名/手机号"]'
    ).filter(visible=True)
    if await _visible(username):
        return
    candidates = [
        page.locator('[data-tracking-click-viewid="password_log"]'),
        page.get_by_text("账号登录", exact=True),
    ]
    for candidate in candidates:
        target = await _first_visible(candidate)
        if target is not None:
            await target.click()
            break
    await username.first.wait_for(state="visible", timeout=20_000)


async def _autofill_saved_credentials(page: "Page") -> None:
    """通过网页输入框的键盘操作触发浏览器已保存凭据自动填充。

    不访问 Chrome 密码数据库，也不读取或记录凭据值；仅检查输入框是否已填充。
    """

    username = page.locator(
        '#usernameId, input[placeholder="请输入账号名/手机号"]'
    ).filter(visible=True).first
    password = page.locator(
        '#passwordId, input[placeholder="请输入密码"]'
    ).filter(visible=True).first
    await username.wait_for(state="visible", timeout=20_000)
    await password.wait_for(state="visible", timeout=20_000)

    for target in (username, password, username):
        await target.click()
        await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.4)
        if await username.input_value() and await password.input_value():
            return

    env_username = os.getenv("PDD_LOGIN_USERNAME", "").strip()
    env_password = os.getenv("PDD_LOGIN_PASSWORD", "")
    if env_username:
        await username.fill(env_username)
    if env_password:
        await password.fill(env_password)
    if not await username.input_value() or not await password.input_value():
        raise RuntimeError(
            "拼多多登录表单未完整填充；请在 profile 中选择已保存凭据，"
            "或设置 PDD_LOGIN_USERNAME/PDD_LOGIN_PASSWORD 环境变量"
        )


def _captcha_input(page: "Page") -> "Locator | None":
    # 保持候选范围窄，避免把普通搜索框误判为验证码框。
    return page.locator(
        'input[placeholder*="验证码"], input[aria-label*="验证码"], '
        'input[name*="captcha" i], input[id*="captcha" i], '
        'input[name*="verify" i], input[id*="verify" i]'
    ).first


async def _captcha_visible(page: "Page") -> bool:
    locator = _captcha_input(page)
    return locator is not None and await _visible(locator)


async def relay_captcha_and_fill(
    page: "Page",
    *,
    platform: str,
    company: str,
    shop: str,
    purpose: str = "登录验证码",
) -> None:
    """通过统一 automation_challenge 组件等待验证码并填写当前页面。"""

    input_locator = _captcha_input(page)
    if input_locator is None or not await _visible(input_locator):
        raise RuntimeError("检测到验证码状态，但未找到可填写的验证码输入框")
    answer = await request_answer(
        challenge_type="verification_code",
        platform=platform,
        company=company,
        shop=shop,
        purpose=purpose,
        page_url=page.url,
        timeout_seconds=300,
    )
    await input_locator.fill(answer)


@automation_component("pinduoduo.ensure_login", "拼多多 · 检查登录态", category="report")
async def ensure_pinduoduo_login(
    context: "BrowserContext",
    *,
    platform: str,
    company: str,
    shop: str,
    login_timeout_ms: int = 120_000,
) -> "Page":
    """确认拼多多登录态；失效时通过保存凭据和验证码转发完成登录。"""

    page = next(
        (
            candidate
            for candidate in context.pages
            if not candidate.is_closed() and "mms.pinduoduo.com" in candidate.url
        ),
        None,
    )
    if page is None:
        page = await context.new_page()
        await page.goto(MMS_HOME_URL, wait_until="domcontentloaded", timeout=60_000)

    if not _is_login_url(page.url):
        try:
            await page.locator("text=订单查询").first.wait_for(
                state="visible", timeout=8_000
            )
            return page
        except Exception:
            await page.goto(MMS_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            if not _is_login_url(page.url):
                return page

    await _switch_to_account_login(page)
    await _autofill_saved_credentials(page)
    login_button = page.get_by_role("button", name="登录", exact=True)
    login_button = login_button.filter(visible=True).first
    await login_button.click()
    deadline = asyncio.get_running_loop().time() + login_timeout_ms / 1000
    captcha_sent = False
    while asyncio.get_running_loop().time() < deadline:
        if "/home" in page.url and not _is_login_url(page.url):
            return page
        if await _captcha_visible(page):
            if not captcha_sent:
                await relay_captcha_and_fill(
                    page,
                    platform=platform,
                    company=company,
                    shop=shop,
                )
                captcha_sent = True
            await login_button.click()
        await asyncio.sleep(1)
    raise TimeoutError(f"拼多多登录超过 {login_timeout_ms // 1000} 秒")

