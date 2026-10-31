#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快手商家后台 WebAPI 下载器共用能力。

快手商家后台的业务接口由页面侧发起。正式下载器先进入同一 Profile 的
商家页面，监听当前 Target 的自然 XHR/fetch 请求，再在该 Target 内复用
稳定业务头调用接口。Cookie、短效 trace/session 头和带签名下载地址只在
进程内使用，绝不写入源码、测试 fixture 或日志。
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping
from urllib.parse import parse_qs, urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ReverseAPI" / "downloads"
KUAISHOU_HOME_URL = "https://s.kwaixiaodian.com/zone/home"
KUAISHOU_PAGE_HOSTS = frozenset({"s.kwaixiaodian.com"})
KUAISHOU_API_HOSTS = frozenset({"s.kwaixiaodian.com"})
KUAISHOU_DOWNLOAD_HOSTS = frozenset({"s.kwaixiaodian.com", "www.kuaishoupay.com"})
CN_TZ = timezone(timedelta(hours=8))

# 当前抓包中还出现 ktrace-str、merchantSessionKey、Trace-Id 等短效值。
# 它们由页面/服务端按请求生成，不能从一次抓包复制到下一次请求。
STATIC_DYNAMIC_HEADER_NAMES = frozenset({"kpf", "kpn"})

HUMAN_ERROR_MARKERS = (
    "登录失效",
    "请先登录",
    "未登录",
    "权限不足",
    "无权限",
    "验证码",
    "滑块验证",
    "人机验证",
    "安全验证",
    "风险验证",
    "短信验证码",
    "二次验证",
    "请完成验证",
)


class NeedsHumanError(RuntimeError):
    """登录、权限或安全验证需要人工处理。"""


class ApiError(RuntimeError):
    """快手 WebAPI 的 HTTP、JSON 结构或业务响应异常。"""

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
    """统一输出；消息中不包含 Cookie、动态头、签名地址或 endpoint。"""

    print(f"[快手][{report}][{stage}] {message}", flush=True)


def is_human_error_message(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in HUMAN_ERROR_MARKERS)


def normalize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    return {
        str(key).lower(): str(value)
        for key, value in (headers or {}).items()
        if value is not None and str(value) != ""
    }


def dynamic_fetch_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """提取可安全复用的页面业务头。

    浏览器自动发送 Origin/Referer/User-Agent/sec-*；快手当前业务接口只
    需要页面请求中的 kpf/kpn 和 JSON 内容头。短效 trace/session/Cookie
    明确不复制。
    """

    normalized = normalize_headers(headers)
    result = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
    }
    for name in STATIC_DYNAMIC_HEADER_NAMES:
        value = normalized.get(name)
        if value:
            result[name] = value
    return result


def _parse_post_data(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return copy.deepcopy(parsed) if isinstance(parsed, dict) else None


@dataclass(frozen=True)
class ObservedRequest:
    host: str
    path: str
    page_url: str
    page_key: int
    headers: dict[str, str]
    post_data: dict[str, Any] | None
    observed_at: float
    frame: Any | None = None


class NaturalRequestCollector:
    """按同一个浏览器 Target 保存自然请求模板和页面上下文。"""

    def __init__(self) -> None:
        self._records: list[ObservedRequest] = []
        self._attached_context: Any | None = None

    def attach(self, context: Any) -> None:
        if self._attached_context is not None:
            return
        self._attached_context = context
        context.on("request", self._on_request)

    def detach(self) -> None:
        if self._attached_context is None:
            return
        with suppress(Exception):
            self._attached_context.remove_listener("request", self._on_request)
        self._attached_context = None

    def _on_request(self, request: Any) -> None:
        try:
            parsed = urlparse(str(request.url or ""))
            if parsed.hostname not in KUAISHOU_API_HOSTS:
                return
            if str(getattr(request, "resource_type", "")).lower() not in {"xhr", "fetch"}:
                return
            frame = request.frame
            page_url = str(frame.url or "") if frame is not None else ""
            if urlparse(page_url).hostname not in KUAISHOU_PAGE_HOSTS:
                return
            page = frame.page if frame is not None else None
            if page is None:
                return
            self._records.append(
                ObservedRequest(
                    host=str(parsed.hostname),
                    path=parsed.path,
                    page_url=page_url,
                    page_key=id(page),
                    headers=normalize_headers(getattr(request, "headers", None)),
                    post_data=_parse_post_data(getattr(request, "post_data", None)),
                    observed_at=time.monotonic(),
                    frame=frame,
                )
            )
        except Exception:
            # 导航或关闭 Target 时 frame 可能暂时不可用；调用方会继续等待
            # 当前 Target 的后续自然请求。
            return

    def _matching(
        self,
        host: str,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        observed_after: float = 0.0,
    ) -> list[ObservedRequest]:
        return [
            record
            for record in self._records
            if record.page_key == id(page)
            and record.host == host
            and record.path == endpoint_path
            and page_route in record.page_url
            and record.observed_at > observed_after
        ]

    async def wait_for_context(
        self,
        host: str,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        timeout: float = 30.0,
        observed_after: float = 0.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            exact = self._matching(
                host,
                endpoint_path,
                page_route,
                page,
                observed_after=observed_after,
            )
            if exact:
                return dynamic_fetch_headers(exact[-1].headers)

            # 创建任务和轮询接口通常不会在首次加载时自然调用；在同一个
            # Target 已有页面 API 请求时，仍可安全复用稳定业务头。
            same_target = [
                record
                for record in self._records
                if record.page_key == id(page)
                and record.host == host
                and page_route in record.page_url
                and record.observed_at > observed_after
            ]
            if same_target:
                return dynamic_fetch_headers(same_target[-1].headers)
            await asyncio.sleep(0.2)
        raise RuntimeError(
            f"快手页面未产生可复用的动态请求上下文：route={page_route} "
            f"host={host} endpoint={endpoint_path}"
        )

    async def wait_for_payload(
        self,
        host: str,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        timeout: float = 30.0,
        observed_after: float = 0.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = self._matching(
                host,
                endpoint_path,
                page_route,
                page,
                observed_after=observed_after,
            )
            for record in reversed(matches):
                if record.post_data is not None:
                    return copy.deepcopy(record.post_data)
            await asyncio.sleep(0.2)
        raise RuntimeError(
            f"快手页面未产生可复用的请求模板：route={page_route} "
            f"host={host} endpoint={endpoint_path}"
        )

    def target_for(
        self,
        host: str,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        observed_after: float = 0.0,
    ) -> Any | None:
        matches = self._matching(
            host,
            endpoint_path,
            page_route,
            page,
            observed_after=observed_after,
        )
        if matches:
            return matches[-1].frame
        same_target = [
            record
            for record in self._records
            if record.page_key == id(page)
            and record.host == host
            and page_route in record.page_url
            and record.observed_at > observed_after
        ]
        return same_target[-1].frame if same_target else None


class BrowserApiSession:
    """在当前页面 Target 内调用 JSON API，401/403 时刷新一次。"""

    def __init__(
        self,
        page: Any,
        collector: NaturalRequestCollector,
        *,
        page_route: str,
        refresh: Callable[[], Awaitable[None]],
    ) -> None:
        self.page = page
        self.collector = collector
        self.page_route = page_route
        self.refresh = refresh

    async def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        label: str,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        host = str(parsed.hostname or "")
        path = parsed.path
        headers = await self.collector.wait_for_context(
            host,
            path,
            self.page_route,
            self.page,
            timeout=min(timeout, 30.0),
        )
        target = self.collector.target_for(
            host,
            path,
            self.page_route,
            self.page,
        ) or self.page
        try:
            body = await browser_post_json(target, url, payload, headers, timeout=timeout)
        except ApiError as exc:
            if exc.status not in {401, 403}:
                raise
            log("公共", "上下文", f"{label} 返回 {exc.status}，刷新后重试一次")
            observed_after = time.monotonic()
            await self.refresh()
            headers = await self.collector.wait_for_context(
                host,
                path,
                self.page_route,
                self.page,
                timeout=min(timeout, 30.0),
                observed_after=observed_after,
            )
            target = self.collector.target_for(
                host,
                path,
                self.page_route,
                self.page,
                observed_after=observed_after,
            ) or self.page
            try:
                body = await browser_post_json(target, url, payload, headers, timeout=timeout)
            except ApiError as retry_exc:
                if retry_exc.status in {401, 403}:
                    raise NeedsHumanError(
                        f"{label}刷新动态上下文后仍返回 HTTP {retry_exc.status}，"
                        "请检查登录态、权限或安全验证"
                    ) from retry_exc
                raise

        ensure_api_success(body, label=label, endpoint_path=path)
        return body


async def browser_post_json(
    page_or_frame: Any,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """在自然请求所在 page/frame 内使用 fetch，继承浏览器登录态。"""

    script = """
    async ({url, payload, headers, timeoutMs}) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: headers || {},
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        return {status: response.status, text: await response.text()};
      } finally {
        clearTimeout(timer);
      }
    }
    """
    try:
        value = await asyncio.wait_for(
            page_or_frame.evaluate(
                script,
                {
                    "url": url,
                    "payload": payload,
                    "headers": headers,
                    "timeoutMs": max(1_000, int(timeout * 1_000)),
                },
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ApiError(f"{urlparse(url).path} 浏览器请求超时") from exc
    except Exception as exc:
        raise ApiError(f"{urlparse(url).path} 浏览器请求失败（{type(exc).__name__}）") from exc

    if not isinstance(value, dict):
        raise ApiError(f"{urlparse(url).path} 浏览器请求返回结构异常")
    status = int(value.get("status") or 0)
    text = str(value.get("text") or "")
    try:
        body = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            f"{urlparse(url).path} 返回非 JSON（HTTP {status}）",
            status=status,
            path=urlparse(url).path,
        ) from exc
    if status < 200 or status >= 300:
        raise ApiError(
            f"{urlparse(url).path} HTTP {status}",
            status=status,
            path=urlparse(url).path,
            body=body,
        )
    if not isinstance(body, dict):
        raise ApiError(
            f"{urlparse(url).path} 返回不是 JSON 对象",
            status=status,
            path=urlparse(url).path,
            body=body,
        )
    return body


def ensure_api_success(body: dict[str, Any], *, label: str, endpoint_path: str = "") -> None:
    """快手业务成功标记是 ``result=1``，不能只看 code。"""

    result = body.get("result")
    if result in (1, "1", True):
        return
    message = (
        body.get("error_msg")
        or body.get("msg")
        or body.get("message")
        or body.get("code")
        or "未提供错误信息"
    )
    if is_human_error_message(message):
        raise NeedsHumanError(f"{label}需要恢复登录、权限或安全验证")
    raise ApiError(f"{label}失败：{message}", path=endpoint_path, body=body)


def response_payload(body: dict[str, Any], *, label: str) -> Any:
    if "data" in body:
        return body.get("data")
    raise ApiError(f"{label}返回缺少 data", body=body)


def clone_payload(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)


def parse_iso_date(value: str, *, option: str = "日期") -> date:
    try:
        return datetime.strptime(value.strip().replace("/", "-"), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{option}必须使用 YYYY-MM-DD 格式：{value!r}") from exc


def parse_date_range(value: str | None, *, option: str = "--date") -> tuple[date, date] | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    parts = re.split(
        r"\s*(?:~|至|\.\.|,|，|\s+to\s+)\s*",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    if len(parts) == 1:
        parsed = parse_iso_date(parts[0], option=option)
        return parsed, parsed
    if any(not item.strip() for item in parts):
        raise ValueError(f"{option}日期范围不完整：{value!r}")
    start = parse_iso_date(parts[0], option=f"{option}开始日期")
    end = parse_iso_date(parts[1], option=f"{option}结束日期")
    if start > end:
        raise ValueError(f"{option}开始日期不能晚于结束日期")
    return start, end


def default_yesterday() -> date:
    return datetime.now(CN_TZ).date() - timedelta(days=1)


def date_to_ms(
    value: date,
    *,
    end_of_day: bool,
    end_millisecond: int = 999,
) -> int:
    if not 0 <= int(end_millisecond) <= 999:
        raise ValueError("end_millisecond 必须在 0 到 999 之间")
    clock = (
        dt_time(23, 59, 59, int(end_millisecond) * 1000)
        if end_of_day
        else dt_time.min
    )
    return int(datetime.combine(value, clock, tzinfo=CN_TZ).timestamp() * 1000)


def safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("._") or "report"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"输出目录中同名文件过多：{path.name}")


def _add_cookies(session: requests.Session, cookies: Iterable[Mapping[str, Any]] | None) -> None:
    for cookie in cookies or ():
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        try:
            session.cookies.set(str(name), str(value), path=str(cookie.get("path") or "/"))
        except (TypeError, ValueError):
            session.cookies.set(str(name), str(value))


def download_original_file(
    url: str,
    output_dir: Path,
    filename: str,
    *,
    headers: Mapping[str, str] | None = None,
    cookies: Iterable[Mapping[str, Any]] | None = None,
    referer: str = KUAISHOU_HOME_URL,
    timeout: tuple[float, float] = (15, 180),
) -> Path:
    """把原始文件写入 ``.part``，校验非空后原子替换正式文件。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("快手接口未返回有效的 HTTP 下载地址")
    if parsed.hostname not in KUAISHOU_DOWNLOAD_HOSTS:
        raise RuntimeError("快手接口返回了非官方下载地址")
    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(resolved_dir / safe_filename(filename))
    temporary = target.with_name(target.name + ".part")
    session = requests.Session()
    _add_cookies(session, cookies)
    request_headers = {"Accept": "*/*", "Referer": referer}
    request_headers.update(dict(headers or {}))
    try:
        with session.get(url, headers=request_headers, stream=True, timeout=timeout) as response:
            if response.status_code in {401, 403}:
                raise NeedsHumanError(
                    f"快手短效文件下载返回 HTTP {response.status_code}，请人工刷新登录态后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"快手原始文件下载返回 HTTP {response.status_code}")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("快手原始文件下载为空")
        temporary.replace(target)
        return target.resolve()
    except requests.RequestException as exc:
        with suppress(OSError):
            temporary.unlink()
        raise RuntimeError(f"快手原始文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    finally:
        session.close()


async def save_playwright_download(download: Any, output_dir: Path, filename: str) -> Path:
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    suggested = str(getattr(download, "suggested_filename", "") or "")
    # 调用方传入的名称带有平台、报表和账期，优先保持该稳定契约；只有
    # 调用方未提供扩展名时才借用浏览器建议扩展名。
    chosen = safe_filename(filename)
    if not Path(filename).suffix and suggested:
        chosen = safe_filename(suggested)
    target = unique_path(output_dir / chosen)
    temporary = target.with_name(target.name + ".part")
    try:
        failure = await download.failure()
        if failure:
            raise RuntimeError(f"快手浏览器下载失败：{failure}")
        await download.save_as(str(temporary))
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("快手浏览器下载文件为空")
        temporary.replace(target)
        return target.resolve()
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise


async def download_browser_url(page: Any, url: str, output_dir: Path, filename: str) -> Path:
    """使用当前已认证浏览器打开官方直链并接收下载事件。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in KUAISHOU_DOWNLOAD_HOSTS:
        raise RuntimeError("快手接口未返回有效的官方下载地址")
    download = None
    try:
        async with page.expect_download(timeout=180_000) as info:
            try:
                await page.goto(url, wait_until="commit", timeout=180_000)
            except Exception as exc:
                # 文件响应常使 page.goto 报 ERR_ABORTED；只要下载事件已经
                # 完成，仍以真实文件为准。
                lowered = str(exc).lower()
                if "abort" not in lowered and "download is starting" not in lowered:
                    raise
        download = await info.value
    except Exception:
        if download is None:
            raise
    return await save_playwright_download(download, output_dir, filename)


async def open_kuaishou_report_page(context: Any, url: str) -> Any:
    """从快手商家后台入口进入报表页，避免沿用未知子页面状态。"""

    page = await context.new_page()
    try:
        await page.goto(KUAISHOU_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await check_human_gate(page)
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await check_human_gate(page)
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=8_000)
        await check_human_gate(page)
        return page
    except Exception:
        with suppress(Exception):
            await page.close()
        raise


async def check_human_gate(page: Any) -> None:
    host = urlparse(str(page.url or "")).hostname
    if host not in KUAISHOU_PAGE_HOSTS:
        raise NeedsHumanError(
            f"当前页面未处于快手商家后台（host={host or 'unknown'}），请人工恢复登录"
        )
    lowered_url = str(page.url or "").lower()
    if any(marker in lowered_url for marker in ("login", "passport", "captcha", "verify", "risk")):
        raise NeedsHumanError("快手页面已跳转登录或安全验证，请人工处理")
    try:
        text = await page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return
    if is_human_error_message(text):
        raise NeedsHumanError("快手页面出现登录、人机或安全验证，请人工完成后重试")


async def refresh_kuaishou_page(page: Any, url: str) -> None:
    await page.goto(KUAISHOU_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await check_human_gate(page)


def as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


__all__ = [
    "ApiError",
    "BrowserApiSession",
    "CN_TZ",
    "DEFAULT_OUTPUT_DIR",
    "KUAISHOU_API_HOSTS",
    "KUAISHOU_DOWNLOAD_HOSTS",
    "KUAISHOU_HOME_URL",
    "KUAISHOU_PAGE_HOSTS",
    "NeedsHumanError",
    "NaturalRequestCollector",
    "ObservedRequest",
    "as_int",
    "browser_post_json",
    "check_human_gate",
    "clone_payload",
    "date_to_ms",
    "default_yesterday",
    "download_browser_url",
    "download_original_file",
    "dynamic_fetch_headers",
    "ensure_api_success",
    "is_human_error_message",
    "log",
    "normalize_headers",
    "open_kuaishou_report_page",
    "parse_date_range",
    "parse_iso_date",
    "refresh_kuaishou_page",
    "response_payload",
    "safe_filename",
    "save_playwright_download",
    "unique_path",
]
