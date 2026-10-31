# -*- coding: utf-8 -*-
"""网易易盾嵌入式滑块的诊断与人工拖拽基础示例。

这个示例用于验证 Playwright 的 iframe/坐标处理，不自动识别缺口、不读取
验证码令牌，也不尝试绕过第三方人机校验。默认只打开网易易盾体验页并打印
可见轨道与手柄的边界框；传入 ``--target-offset`` 时，才按人工提供的相对
偏移量发送一次普通鼠标拖拽，结果仍由页面自行判定。

抖音登录页的验证码由 ``douyin_login.py`` 检测并交给人工完成，不应把本示例
直接用于生产验证码或把目标站点的挑战数据写入日志。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

YIDUN_JIGSAW_URL = "https://dun.163.com/trial/jigsaw"
EMBED_TAB_SELECTOR = '.tcapt-tabs__tab[captcha-mode="embed"]'
EMBED_CAPTCHA_SELECTOR = ".tcapt-type__item.active .j-captcha"


async def _visible_count(locator: Any) -> int:
    count = await locator.count()
    visible = 0
    for index in range(count):
        try:
            if await locator.nth(index).is_visible():
                visible += 1
        except Exception:
            continue
    return visible


async def activate_embedded_mode(page: Any) -> None:
    tab = page.locator(EMBED_TAB_SELECTOR).filter(visible=True)
    if not await _visible_count(tab):
        raise RuntimeError("网易易盾体验页未找到“嵌入式”标签")
    await tab.last.click(timeout=10_000)
    await page.locator(EMBED_CAPTCHA_SELECTOR).filter(visible=True).first.wait_for(
        state="visible", timeout=20_000
    )


async def find_visible_slider(page: Any) -> tuple[Any | None, Any | None, Any | None]:
    """Return (surface, track, handle) for a visible demo slider, if present."""

    selector_pairs = (
        ("#nc_1_n1t", "#nc_1_n1z"),
        ('[id$="_n1t"]', '[id$="_n1z"]'),
    )
    surfaces = [page, *page.frames]
    for surface in surfaces:
        for track_selector, handle_selector in selector_pairs:
            tracks = surface.locator(track_selector)
            handles = surface.locator(handle_selector)
            count = min(await tracks.count(), await handles.count())
            for index in range(count - 1, -1, -1):
                track = tracks.nth(index)
                handle = handles.nth(index)
                try:
                    if await track.bounding_box() is not None and await handle.bounding_box() is not None:
                        return surface, track, handle
                except Exception:
                    continue
    return None, None, None


async def inspect_embedded_slider(page: Any) -> dict[str, Any]:
    await activate_embedded_mode(page)
    surface, track, handle = await find_visible_slider(page)
    result: dict[str, Any] = {
        "url_host": page.url.split("/", 3)[2] if "/" in page.url else page.url,
        "captcha_container_count": await _visible_count(
            page.locator(EMBED_CAPTCHA_SELECTOR)
        ),
        "frame_count": len(page.frames),
        "slider_found": surface is not None,
    }
    if track is not None and handle is not None:
        result["track_box"] = await track.bounding_box()
        result["handle_box"] = await handle.bounding_box()
    return result


async def manual_drag_by_offset(page: Any, handle: Any, offset: float, *, steps: int = 36) -> float:
    """Drag by an operator-supplied offset and return the observed x movement."""

    if steps < 2:
        raise ValueError("steps 必须至少为 2")
    before = await handle.bounding_box()
    if before is None:
        raise RuntimeError("滑块手柄不可见")
    start_x = before["x"] + before["width"] / 2
    start_y = before["y"] + before["height"] / 2
    await handle.hover()
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    try:
        for step in range(1, steps + 1):
            progress = step / steps
            # A short deterministic easing curve is enough for UI testing;
            # this is intentionally not a CAPTCHA-evasion trajectory.
            eased = progress * progress * (3 - 2 * progress)
            await page.mouse.move(start_x + offset * eased, start_y, steps=1)
            await asyncio.sleep(0.02)
    finally:
        await page.mouse.up()
    await asyncio.sleep(0.5)
    after = await handle.bounding_box()
    return (after["x"] - before["x"]) if after is not None else offset


async def run(cdp_url: str, url: str, target_offset: float | None) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器没有可用上下文")
        context = browser.contexts[0]
        page = next(
            (candidate for candidate in context.pages if "dun.163.com" in candidate.url),
            None,
        )
        created = page is None
        if page is None:
            page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                info = await inspect_embedded_slider(page)
            except PlaywrightTimeout as exc:
                raise RuntimeError("网易易盾嵌入式验证码未在限定时间内渲染") from exc
            print(f"网易易盾滑块诊断：{info}")

            if not info["slider_found"]:
                print("未找到可见滑块，本轮跳过；没有发送拖拽事件")
                return 0
            if target_offset is None:
                print("仅完成坐标诊断；请人工确认偏移量后再传入 --target-offset")
                return 0

            _, _, handle = await find_visible_slider(page)
            if handle is None:
                raise RuntimeError("坐标诊断后滑块手柄已消失")
            moved = await manual_drag_by_offset(page, handle, target_offset)
            print(f"已发送人工指定偏移量：{target_offset:.1f}px；页面观察到手柄位移：{moved:.1f}px")
            print("示例不判断或重试验证码结果，请人工查看体验页")
            return 0
        finally:
            if created and not page.is_closed():
                await page.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="网易易盾嵌入式滑块诊断/人工拖拽示例")
    parser.add_argument("--cdp", required=True, help="单独测试 profile 的 wsEndpoint")
    parser.add_argument("--url", default=YIDUN_JIGSAW_URL)
    parser.add_argument(
        "--target-offset", type=float, default=None,
        help="人工测得的相对 x 偏移量；不传则只诊断坐标",
    )
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(args.cdp, args.url, args.target_offset))
    except Exception as exc:
        print(f"滑块示例失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
