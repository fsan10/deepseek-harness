#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天猫 WebAPI 下载器共用能力。

天猫后台的业务请求分布在千牛、支付宝和阿里妈妈多个 Target。这里把
登录/入口导航、自然请求上下文、MTop 签名、API 响应判定和原始文件保存
集中起来，报表模块只保留各自的业务口径。

动态 Cookie、token、签名和短效下载地址只存在当前进程内，不写日志、源
码或捕获文件。遇到验证码、风险控制、短信或二次验证时统一抛出
``NeedsHumanError``，不自动绕过。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "downloads"
TZ_CN = timezone(timedelta(hours=8))

SELLER_HOME_URL = "https://myseller.taobao.com/home.htm"
ORDER_URL = "https://myseller.taobao.com/home.htm/trade-platform/tp/sold"
EXPORT_LIST_URL = "https://myseller.taobao.com/home.htm/trade-platform/tp/export-list"
AGGREGATE_FUND_URL = (
    "https://myseller.taobao.com/home.htm/whale-accountant/pay/capital/home?active=fund_day"
)
ALIPAY_FUND_URL = "https://b.alipay.com/page/mbillexprod/bill/download/fundBill"
UNION_PROMOTION_URL = "https://ad.alimama.com/portal/v2/report/promotionDataPage.htm"
WANXIANGTAI_URL = "https://one.alimama.com/index.html"

MTOP_HOST = "h5api.m.taobao.com"
MTOP_APP_KEY = "12574478"
MTOP_TTID = "11320@taobao_WEB_9.9.99"

DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})$")
HUMAN_MARKERS = (
    "验证码",
    "滑块验证",
    "安全验证",
    "风险验证",
    "二次验证",
    "短信验证",
    "身份验证",
    "请先登录",
    "登录失效",
    "未登录",
    "权限不足",
    "无权限",
    "安全风控",
)


class NeedsHumanError(RuntimeError):
    """登录、权限或安全验证需要人工处理。"""


class ApiError(RuntimeError):
    """天猫 WebAPI HTTP、JSON 结构或业务响应异常。"""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        path: str = "",
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.path = path
        self.body = body


def log(report: str, stage: str, message: str) -> None:
    """输出不含动态凭据的三段式日志。"""

    print(f"[TMALL][{report}][{stage}] {message}", flush=True)


def parse_date(value: str, *, option_name: str = "日期") -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError(f"{option_name} 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{option_name} 不是有效日期：{value}") from exc


def default_business_date(today: date | None = None) -> str:
    current = today or datetime.now(TZ_CN).date()
    return (current - timedelta(days=1)).isoformat()


def recent_month_range(today: date | None = None) -> tuple[str, str]:
    end = today or datetime.now(TZ_CN).date()
    return ((end - timedelta(days=29)).isoformat(), end.isoformat())


def parse_date_range(
    value: str | None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    default: str = "yesterday",
    today: date | None = None,
) -> tuple[str, str]:
    if value and (start_date or end_date):
        raise ValueError("--date 不能和 --start-date/--end-date 同时使用")
    if value:
        parts = value.split("~")
        if len(parts) == 1:
            start, end = parts[0], parts[0]
        elif len(parts) == 2:
            start, end = parts
        else:
            raise ValueError("--date 必须是 YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD")
    elif start_date or end_date:
        if not start_date or not end_date:
            raise ValueError("--start-date 和 --end-date 必须同时提供")
        start, end = start_date, end_date
    elif default == "month":
        return recent_month_range(today)
    else:
        start = end = default_business_date(today)
    start_obj = parse_date(start, option_name="开始日期")
    end_obj = parse_date(end, option_name="结束日期")
    if start_obj > end_obj:
        raise ValueError(f"开始日期晚于结束日期：{start} > {end}")
    return start_obj.isoformat(), end_obj.isoformat()


def is_human_error_message(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in HUMAN_MARKERS)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"输出目录中同名文件过多：{path.name}")


def _add_cookies(
    session: requests.Session,
    cookies: Iterable[Mapping[str, Any]] | None,
) -> None:
    for cookie in cookies or ():
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        kwargs: dict[str, str] = {"path": str(cookie.get("path") or "/")}
        domain = cookie.get("domain")
        if domain:
            kwargs["domain"] = str(domain)
        try:
            session.cookies.set(str(name), str(value), **kwargs)
        except (TypeError, ValueError):
            session.cookies.set(str(name), str(value))


def make_requests_session(cookies: Iterable[Mapping[str, Any]]) -> requests.Session:
    session = requests.Session()
    _add_cookies(session, cookies)
    return session


def download_original_file(
    url: str,
    output_dir: Path,
    filename: str,
    *,
    headers: Mapping[str, str] | None = None,
    cookies: Iterable[Mapping[str, Any]] | None = None,
    session: requests.Session | None = None,
    timeout: tuple[float, float] = (15, 180),
) -> Path:
    """将原始文件写入同目录 ``.part``，成功后原子落盘。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError("接口未返回有效的 HTTP 下载地址")
    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(resolved_dir / filename)
    temporary = target.with_name(target.name + ".part")
    own_session = session is None
    client = session or make_requests_session(cookies or ())
    try:
        with client.get(url, headers=dict(headers or {}), stream=True, timeout=timeout) as response:
            if response.status_code in {401, 403}:
                raise NeedsHumanError(
                    f"短效文件下载返回 HTTP {response.status_code}，请刷新登录态后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise ApiError(f"原始文件下载返回 HTTP {response.status_code}", status=response.status_code)
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ApiError("原始文件下载为空")
        temporary.replace(target)
        return target.resolve()
    except requests.RequestException as exc:
        with suppress(OSError):
            temporary.unlink()
        raise ApiError(f"原始文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    finally:
        if own_session:
            client.close()


async def download_browser_file(
    page: Any,
    url: str,
    output_dir: Path,
    filename: str,
    *,
    timeout_ms: int = 120_000,
) -> Path:
    """在同一 CDP Target 内下载需要 Profile 代理/会话的短效文件。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError("接口未返回有效的浏览器下载地址")
    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    return await download_browser_action(
        page,
        lambda: page.goto(url, wait_until="commit", timeout=timeout_ms),
        resolved_dir,
        filename,
        timeout_ms=timeout_ms,
    )


async def download_browser_action(
    page: Any,
    action: Callable[[], Awaitable[Any]],
    output_dir: Path,
    filename: str,
    *,
    timeout_ms: int = 120_000,
) -> Path:
    """执行页面内下载动作并以同目录 ``.part`` 原子保存。"""

    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(resolved_dir / filename)
    temporary = target.with_name(target.name + ".part")
    try:
        async with page.expect_download(timeout=timeout_ms) as download_info:
            try:
                await action()
            except Exception as exc:
                # 下载响应接管页面动作时 Playwright 可能抛 ERR_ABORTED；只要
                # 同一个上下文已经产生下载事件，仍以下载事件为事实。
                if "abort" not in str(exc).lower() and "download" not in str(exc).lower():
                    raise
        download = await download_info.value
        await download.save_as(str(temporary))
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ApiError("浏览器下载文件为空")
        temporary.replace(target)
        return target.resolve()
    except Exception as exc:
        with suppress(OSError):
            temporary.unlink()
        if type(exc).__name__ == "TimeoutError":
            raise ApiError("浏览器等待文件下载超时") from exc
        raise


@dataclass(frozen=True)
class ObservedRequest:
    method: str
    url: str
    headers: dict[str, str]
    post_data: str | None
    page_url: str
    resource_type: str
    observed_at: float


def normalize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {
        str(key).lower(): str(value)
        for key, value in (headers or {}).items()
        if value is not None and str(value) != ""
    }


class NaturalRequestCollector:
    """只在内存记录当前 CDP 上下文产生的自然请求。"""

    def __init__(self) -> None:
        self.records: list[ObservedRequest] = []
        self._context: Any | None = None

    def attach(self, context: Any) -> None:
        if self._context is not None:
            return
        self._context = context
        context.on("request", self._on_request)

    def detach(self) -> None:
        if self._context is None:
            return
        with suppress(Exception):
            self._context.remove_listener("request", self._on_request)
        self._context = None

    def _on_request(self, request: Any) -> None:
        try:
            resource = str(request.resource_type or "")
            if resource not in {"document", "xhr", "fetch", "script"}:
                return
            frame = request.frame
            page_url = str(frame.url or "") if frame is not None else ""
            self.records.append(
                ObservedRequest(
                    method=str(request.method or "GET"),
                    url=str(request.url or ""),
                    headers=normalize_headers(request.headers),
                    post_data=request.post_data,
                    page_url=page_url,
                    resource_type=resource,
                    observed_at=time.monotonic(),
                )
            )
        except Exception:
            # 页面关闭或跨 Target 导航期间 request.frame 可能失效。
            return

    def latest(
        self,
        *,
        path: str | None = None,
        host: str | None = None,
        method: str | None = None,
        observed_after: float = 0.0,
    ) -> ObservedRequest | None:
        for record in reversed(self.records):
            parsed = urlparse(record.url)
            if record.observed_at <= observed_after:
                continue
            if path and parsed.path != path:
                continue
            if host and parsed.hostname != host:
                continue
            if method and record.method.upper() != method.upper():
                continue
            return record
        return None

    async def wait_for(
        self,
        predicate: Callable[[ObservedRequest], bool],
        *,
        timeout: float = 30.0,
        observed_after: float = 0.0,
    ) -> ObservedRequest:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for record in reversed(self.records):
                if record.observed_at > observed_after and predicate(record):
                    return record
            await asyncio.sleep(0.2)
        raise ApiError("页面没有产生所需的自然业务请求")

    async def wait_for_path(
        self,
        path: str,
        *,
        host: str | None = None,
        method: str | None = None,
        timeout: float = 30.0,
        observed_after: float = 0.0,
    ) -> ObservedRequest:
        return await self.wait_for(
            lambda item: (
                urlparse(item.url).path == path
                and (host is None or urlparse(item.url).hostname == host)
                and (method is None or item.method.upper() == method.upper())
            ),
            timeout=timeout,
            observed_after=observed_after,
        )


def parse_form_post_data(post_data: str | None) -> list[tuple[str, str]]:
    if not post_data:
        return []
    return [(key, value) for key, value in parse_qsl(post_data, keep_blank_values=True)]


def form_dict(post_data: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in parse_form_post_data(post_data):
        result[key] = value
    return result


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def mtop_token(cookies: Iterable[Mapping[str, Any]]) -> str:
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        if name in {"_m_h5_tk", "_m_h5_tk_"}:
            value = str(cookie.get("value") or "")
            if value:
                return value.split("_", 1)[0]
    raise NeedsHumanError("当前 Profile 缺少天猫 MTop 登录令牌，请刷新登录态")


def build_mtop_url(
    template_url: str,
    data: Mapping[str, Any],
    cookies: Iterable[Mapping[str, Any]],
    *,
    callback: str | None = None,
    timestamp_ms: int | None = None,
) -> str:
    """按当前 Cookie 令牌生成一次性 MTop URL。"""

    parsed = urlsplit(template_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.setdefault("jsv", "2.6.1")
    params.setdefault("appKey", MTOP_APP_KEY)
    params.setdefault("api", params.get("api", ""))
    params.setdefault("v", "1.0")
    params.setdefault("ttid", MTOP_TTID)
    params["t"] = str(timestamp_ms or int(time.time() * 1000))
    data_text = _json_text(dict(data))
    token = mtop_token(cookies)
    params["sign"] = hashlib.md5(
        f"{token}&{params['t']}&{params['appKey']}&{data_text}".encode("utf-8")
    ).hexdigest()
    params["data"] = data_text
    if callback is not None:
        params["callback"] = callback
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))


def parse_json_or_jsonp(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        raise ApiError("接口返回空响应")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        left = raw.find("(")
        right = raw.rfind(")")
        if left < 0 or right <= left:
            raise ApiError("接口响应不是合法 JSON/JSONP")
        try:
            return json.loads(raw[left + 1 : right])
        except json.JSONDecodeError as exc:
            raise ApiError("接口响应不是合法 JSONP") from exc


def ensure_api_success(body: Any, *, label: str) -> Any:
    if not isinstance(body, dict):
        raise ApiError(f"{label}接口响应结构异常")
    ret = body.get("ret")
    if isinstance(ret, list):
        text = " ".join(str(item) for item in ret)
        if any(marker in text for marker in HUMAN_MARKERS) or any(
            marker in text for marker in ("SESSION_EXPIRED", "USER_VALIDATE", "NO_PERMISSION")
        ):
            raise NeedsHumanError(f"{label}返回登录或安全验证状态")
        if ret and not any("SUCCESS" in str(item) for item in ret):
            raise ApiError(f"{label}接口业务失败")
    if body.get("success") is False:
        message = body.get("bizErrorDesc") or body.get("message") or body.get("msg")
        if is_human_error_message(message):
            raise NeedsHumanError(str(message)[:160])
        raise ApiError(f"{label}接口业务失败：{str(message or '未知错误')[:160]}")
    info = body.get("info")
    if isinstance(info, dict) and info.get("ok") is False:
        message = info.get("message") or info.get("errorCode")
        if is_human_error_message(message):
            raise NeedsHumanError(str(message)[:160])
        raise ApiError(f"{label}接口业务失败：{str(message or '未知错误')[:160]}")
    return body


def extract_first_url(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and urlparse(item).scheme in {"http", "https"}:
                return item
    if isinstance(value, str) and urlparse(value).scheme in {"http", "https"}:
        return value
    raise ApiError("接口响应缺少有效原始文件地址")


async def browser_user_agent(page: Any) -> str:
    with suppress(Exception):
        value = await page.evaluate("navigator.userAgent")
        if value:
            return str(value)
    return "Mozilla/5.0"


async def browser_body_text(page: Any) -> str:
    with suppress(Exception):
        return str(await page.locator("body").inner_text(timeout=2_000) or "")
    return ""


async def ensure_no_security_challenge(page: Any) -> None:
    text = await browser_body_text(page)
    frame_urls = [str(frame.url or "") for frame in getattr(page, "frames", [])]
    if any(marker in text for marker in HUMAN_MARKERS) or any(
        "punish" in url or "captcha" in url for url in frame_urls
    ):
        raise NeedsHumanError("天猫页面出现登录、安全验证或人工验证，请先在 Profile 中处理")


async def _visible_text_locator(page: Any, text: str) -> Any | None:
    locator = page.get_by_text(text, exact=True)
    for index in range(await locator.count()):
        item = locator.nth(index)
        with suppress(Exception):
            if await item.is_visible():
                return item
    return None


async def ensure_tmall_login(
    page: Any,
    *,
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> None:
    """用 DOM 完成普通登录表单；验证码/风险控制只交给人工。"""

    await page.goto(SELLER_HOME_URL, wait_until="domcontentloaded")
    if "loginmyseller" not in str(page.url) and "login" not in str(page.url).lower():
        await ensure_no_security_challenge(page)
        return
    await ensure_no_security_challenge(page)
    password = os.environ.get(password_env, "")
    if not password and os.name == "nt":
        with suppress(FileNotFoundError, OSError, TypeError):
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                password = str(winreg.QueryValueEx(key, password_env)[0])
    if not password:
        raise NeedsHumanError(f"未读取到登录密码环境变量 {password_env}，请先完成登录")

    surface: Any = page
    iframe = page.locator("iframe#alibaba-login-box")
    if await iframe.count() and await iframe.first.is_visible():
        surface = page.frame_locator("iframe#alibaba-login-box")
    account = surface.locator("#fm-login-id")
    secret = surface.locator("#fm-login-password")
    await account.wait_for(state="visible", timeout=30_000)
    await account.fill(username)
    await secret.fill(password)
    button = surface.locator("button.fm-submit").first
    await button.click()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        await ensure_no_security_challenge(page)
        if "loginmyseller" not in str(page.url) and "login" not in str(page.url).lower():
            return
        await asyncio.sleep(0.5)
    raise NeedsHumanError("天猫登录后未进入商家中心，请人工确认登录状态")


async def handle_alimama_login(page: Any, target_url: str) -> None:
    """进入阿里妈妈页面并点击页面提供的登录入口。"""

    await page.goto(target_url, wait_until="domcontentloaded")
    for _ in range(12):
        await ensure_no_security_challenge(page)
        clicked = False
        for label in ("快速进入", "立即登录"):
            locator = await _visible_text_locator(page, label)
            if locator is not None:
                await locator.click()
                clicked = True
                await page.wait_for_timeout(800)
                break
        body = await browser_body_text(page)
        url = str(page.url)
        if not clicked and "login.m.taobao.com" not in url and "立即登录" not in body:
            return
        await asyncio.sleep(0.5)
    raise NeedsHumanError("阿里妈妈页面仍停留在登录入口，请人工完成登录")


def replace_query(url: str, updates: Mapping[str, Any]) -> str:
    parsed = urlsplit(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in updates.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = str(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(values), ""))


def response_json(response: requests.Response, *, label: str) -> Any:
    try:
        body = response.json()
    except ValueError:
        body = parse_json_or_jsonp(response.text)
    if response.status_code in {401, 403}:
        raise ApiError(f"{label}接口 HTTP {response.status_code}", status=response.status_code, body=body)
    if response.status_code < 200 or response.status_code >= 300:
        raise ApiError(f"{label}接口 HTTP {response.status_code}", status=response.status_code, body=body)
    return body


async def session_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    label: str,
    page_url: str = "",
    user_agent: str = "Mozilla/5.0",
    data: Any = None,
    params: Any = None,
    allow_redirects: bool = True,
    timeout: tuple[float, float] = (15, 60),
) -> requests.Response:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": page_url,
        "User-Agent": user_agent,
    }

    def request() -> requests.Response:
        return session.request(
            method,
            url,
            headers=headers,
            data=data,
            params=params,
            allow_redirects=allow_redirects,
            timeout=timeout,
        )

    try:
        return await asyncio.to_thread(request)
    except requests.RequestException as exc:
        raise ApiError(f"{label}请求失败：{type(exc).__name__}") from exc


async def page_for(browser: Any, predicate: Callable[[str], bool]) -> Any:
    for context in browser.contexts:
        for page in context.pages:
            if predicate(str(page.url)):
                return page
    if not browser.contexts:
        raise ApiError("CDP 浏览器没有可用上下文")
    return await browser.contexts[0].new_page()


async def get_browser_cookies(context: Any) -> list[dict[str, Any]]:
    return list(await context.cookies())


def query_value(url: str, key: str) -> str | None:
    values = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return values.get(key)


def body_value(body: Any, *keys: str) -> Any:
    current = body
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


__all__ = [
    "AGGREGATE_FUND_URL",
    "ALIPAY_FUND_URL",
    "ApiError",
    "DEFAULT_OUTPUT_DIR",
    "EXPORT_LIST_URL",
    "MTOP_APP_KEY",
    "MTOP_HOST",
    "MTOP_TTID",
    "NeedsHumanError",
    "NaturalRequestCollector",
    "ObservedRequest",
    "ORDER_URL",
    "PROJECT_ROOT",
    "SELLER_HOME_URL",
    "TZ_CN",
    "UNION_PROMOTION_URL",
    "WANXIANGTAI_URL",
    "body_value",
    "browser_body_text",
    "browser_user_agent",
    "build_mtop_url",
    "default_business_date",
    "download_browser_action",
    "download_original_file",
    "download_browser_file",
    "ensure_api_success",
    "ensure_no_security_challenge",
    "ensure_tmall_login",
    "extract_first_url",
    "form_dict",
    "get_browser_cookies",
    "handle_alimama_login",
    "is_human_error_message",
    "log",
    "make_requests_session",
    "parse_date",
    "parse_date_range",
    "parse_form_post_data",
    "parse_json_or_jsonp",
    "page_for",
    "query_value",
    "recent_month_range",
    "replace_query",
    "response_json",
    "session_request",
    "unique_path",
]
