#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书 WebAPI 下载脚本共用的 CDP、动态上下文和文件能力。

小红书接口依赖登录页面自然产生的 Authorization、X-S-Common 等动态请求
头。本模块只在内存中保留当前 Target 的请求头，并通过页面内 fetch 调用
业务 API；真实的短效文件地址只用于当前进程的下载，不写入日志或文件。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ReverseAPI" / "downloads"
XHS_HOST = "ark.xiaohongshu.com"
XHS_ORIGIN = f"https://{XHS_HOST}"
XHS_HOME_URL = f"{XHS_ORIGIN}/app-system/home"
CN_TZ = timezone(timedelta(hours=8))
MAX_PERIOD_PAGES = 20

# 只复制经抓包确认会随当前 Cloak Target 产生的动态业务头。Cookie、Origin、
# Referer、User-Agent、sec-* 和 Content-Length 由浏览器自动处理或禁止脚本设置。
DYNAMIC_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-s-common",
        "x-s",
        "x-t",
        "x-b3-traceid",
        "bill-type",
        "sub-system",
    }
)


class NeedsHumanError(RuntimeError):
    """登录、人机验证、短信验证或权限状态需要人工处理。"""


class ApiError(RuntimeError):
    """小红书 WebAPI HTTP 或业务响应异常。"""

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
    """输出不含动态凭据的小红书统一日志。"""

    print(f"[XHS][{report}][{stage}] {message}", flush=True)


@dataclass(frozen=True)
class ObservedRequest:
    path: str
    page_url: str
    page_key: int
    headers: dict[str, str]
    observed_at: float


def normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    return {
        str(key).lower(): str(value)
        for key, value in (headers or {}).items()
        if value is not None and str(value) != ""
    }


def dynamic_fetch_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """构造页面 fetch 可设置的最小请求头集合。"""

    normalized = normalize_headers(headers)
    result = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
    }
    for name in DYNAMIC_HEADER_NAMES:
        value = normalized.get(name)
        if value:
            result[name] = value
    return result


class NaturalRequestCollector:
    """按页面路由记录同一 Target 的自然 API 请求头。

    监听器不落盘；正式脚本也不把这些值写入日志。精确 endpoint 优先，
    找不到时只回退到同一小红书页面 Target 最近的一次业务请求。
    """

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
        with _suppress(Exception):
            self._attached_context.remove_listener("request", self._on_request)
        self._attached_context = None

    def _on_request(self, request: Any) -> None:
        try:
            parsed = urlparse(str(request.url or ""))
            if parsed.hostname != XHS_HOST:
                return
            if request.resource_type not in {"xhr", "fetch"}:
                return
            frame = request.frame
            page_url = str(frame.url or "") if frame is not None else ""
            if urlparse(page_url).hostname != XHS_HOST:
                return
            page = frame.page if frame is not None else None
            if page is None:
                return
            self._records.append(
                ObservedRequest(
                    path=parsed.path,
                    page_url=page_url,
                    page_key=id(page),
                    headers=normalize_headers(request.headers),
                    observed_at=time.monotonic(),
                )
            )
        except Exception:
            # Target 在导航/关闭期间可能让 Playwright 的 request.frame 失效；
            # 这不应遮蔽后续正式 API 调用，调用侧会继续等待下一条请求。
            return

    def _matching(
        self,
        endpoint_path: str,
        page_route: str,
        page: Any,
        observed_after: float = 0.0,
    ) -> list[ObservedRequest]:
        return [
            record
            for record in self._records
            if record.page_key == id(page)
            and page_route in record.page_url
            and record.page_url.startswith(XHS_ORIGIN)
            and (not endpoint_path or record.path == endpoint_path)
            and record.observed_at > observed_after
        ]

    def headers_for(
        self,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        observed_after: float = 0.0,
    ) -> dict[str, str]:
        exact = self._matching(
            endpoint_path,
            page_route,
            page,
            observed_after=observed_after,
        )
        if exact:
            return dynamic_fetch_headers(exact[-1].headers)

        same_target = [
            record
            for record in self._records
            if record.page_key == id(page)
            and page_route in record.page_url
            and record.page_url.startswith(XHS_ORIGIN)
            and record.observed_at > observed_after
        ]
        if same_target:
            return dynamic_fetch_headers(same_target[-1].headers)
        raise RuntimeError(
            f"小红书页面未产生可复用的动态请求头：route={page_route} endpoint={endpoint_path}"
        )

    async def wait_for_context(
        self,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        timeout: float = 30.0,
        observed_after: float = 0.0,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.headers_for(
                    endpoint_path,
                    page_route,
                    page,
                    observed_after=observed_after,
                )
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(0.2)
        if last_error is not None:
            raise last_error
        raise RuntimeError("小红书页面未产生动态请求头")


class BrowserApiSession:
    """在当前页面 Target 内调用小红书 JSON API，401/403 时刷新一次。"""

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
        endpoint_path: str,
        payload: dict[str, Any],
        *,
        label: str,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        url = f"{XHS_ORIGIN}{endpoint_path}"
        headers = await self.collector.wait_for_context(
            endpoint_path, self.page_route, self.page, timeout=min(timeout, 30.0)
        )
        try:
            response = await browser_post_json(
                self.page,
                url,
                payload,
                headers,
                timeout=timeout,
            )
        except ApiError as exc:
            if exc.status not in {401, 403}:
                raise
            log("公共", "上下文", f"{label} 返回 {exc.status}，刷新后重试一次")
            observed_after = time.monotonic()
            await self.refresh()
            headers = await self.collector.wait_for_context(
                endpoint_path,
                self.page_route,
                self.page,
                timeout=min(timeout, 30.0),
                observed_after=observed_after,
            )
            try:
                response = await browser_post_json(
                    self.page,
                    url,
                    payload,
                    headers,
                    timeout=timeout,
                )
            except ApiError as retry_exc:
                if retry_exc.status in {401, 403}:
                    raise NeedsHumanError(
                        f"{label} 刷新动态上下文后仍返回 HTTP {retry_exc.status}，"
                        "请检查登录态、权限或安全验证"
                    ) from retry_exc
                raise

        ensure_api_success(response, label=label, endpoint_path=endpoint_path)
        return response


async def browser_post_json(
    page: Any,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """在浏览器页面上下文执行 POST，继承当前 Profile 的 Cookie/Origin。"""

    script = """
    async ({url, payload, headers}) => {
      const response = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers,
        body: JSON.stringify(payload),
      });
      const text = await response.text();
      return {status: response.status, text};
    }
    """
    try:
        value = await asyncio.wait_for(
            page.evaluate(
                script,
                {"url": url, "payload": payload, "headers": headers},
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ApiError(f"{urlparse(url).path} 浏览器 fetch 超时") from exc
    except Exception as exc:
        raise ApiError(
            f"{urlparse(url).path} 浏览器 fetch 失败（{type(exc).__name__}）"
        ) from exc

    if not isinstance(value, dict):
        raise ApiError(f"{urlparse(url).path} 浏览器 fetch 返回结构异常")
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


def ensure_api_success(
    body: dict[str, Any], *, label: str, endpoint_path: str = ""
) -> None:
    code = body.get("code")
    success = body.get("success")
    if (success is False) or (code not in (None, 0, "0")):
        message = body.get("msg") or body.get("message") or "未提供错误信息"
        if is_security_gate_text(str(message)) or any(
            marker in str(message)
            for marker in ("登录失效", "请先登录", "未登录", "权限不足", "无权限")
        ):
            raise NeedsHumanError(f"{label}需要恢复登录、权限或安全验证")
        raise ApiError(
            f"{label}失败：{message}",
            path=endpoint_path,
            body=body,
        )


def response_data(body: dict[str, Any], *, label: str) -> dict[str, Any]:
    value = body.get("data")
    if not isinstance(value, dict):
        raise ApiError(f"{label}返回缺少 data 对象", body=body)
    return value


def parse_iso_date(value: str, *, option: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{option} 必须使用 YYYY-MM-DD 格式：{value!r}") from exc


def date_to_ms(value: date, *, end_of_day: bool) -> int:
    clock = dt_time(23, 59, 59) if end_of_day else dt_time.min
    return int(datetime.combine(value, clock, tzinfo=CN_TZ).timestamp() * 1000)


def recent_order_range() -> tuple[date, date]:
    end = datetime.now(CN_TZ).date()
    return end - timedelta(days=29), end


def period_text(value: date, *, end_of_day: bool = False) -> str:
    return f"{value.isoformat()} {'23:59:59' if end_of_day else '00:00:00'}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10_000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复的下载文件名：{path}")


def download_file(
    url: str,
    output_dir: Path,
    filename: str,
    *,
    referer: str = XHS_ORIGIN + "/",
) -> Path:
    """使用刚取得的短效地址流式保存原始 XLSX，不打印地址。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("小红书接口未返回有效下载地址")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir / filename)
    temporary = target.with_name(target.name + ".part")
    session = requests.Session()
    try:
        with session.get(
            url,
            headers={"Accept": "*/*", "Referer": referer},
            stream=True,
            timeout=(10, 180),
        ) as response:
            if response.status_code in {401, 403}:
                raise NeedsHumanError(
                    f"小红书短效下载地址返回 HTTP {response.status_code}，请刷新页面后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"小红书短效文件下载返回 HTTP {response.status_code}")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("小红书下载文件为空")
        temporary.replace(target)
    except requests.RequestException as exc:
        with _suppress(OSError):
            temporary.unlink()
        raise RuntimeError(f"小红书短效文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with _suppress(OSError):
            temporary.unlink()
        raise
    finally:
        session.close()
    return target.resolve()


def extract_download_url(body: dict[str, Any], *, label: str) -> str:
    data = response_data(body, label=label)
    value = data.get("downloadUrl") or data.get("fileUrl") or data.get("file_url")
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ApiError(f"{label}未返回下载地址", body=body)
    return value


def period_rows(body: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
    data = response_data(body, label=label)
    rows = data.get("list")
    if not isinstance(rows, list):
        raise ApiError(f"{label}返回缺少 list", body=body)
    return [row for row in rows if isinstance(row, dict)]


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def bounded_total_pages(
    data: Any,
    *,
    label: str,
    maximum: int = MAX_PERIOD_PAGES,
) -> int:
    """校验服务端总页数；超过安全上限时明确失败，绝不静默截断。"""

    if not isinstance(data, dict):
        raise ApiError(f"{label}返回缺少分页 data 对象")
    raw = data.get("totalPage", 1)
    try:
        total_pages = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{label}返回的 totalPage 不是整数") from exc
    total_pages = max(1, total_pages)
    if total_pages > maximum:
        raise ApiError(
            f"{label}总页数 {total_pages} 超过安全上限 {maximum}，已停止以避免选错账期"
        )
    return total_pages


def is_security_gate_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return bool(
        re.search(
            r"滑块验证|人机验证|安全验证|短信验证码|二次验证|风险验证|请完成验证",
            compact,
        )
    )


async def check_human_gate(page: Any) -> None:
    """把登录/安全验证停在 NEEDS_HUMAN，不尝试绕过。"""

    host = urlparse(str(page.url or "")).hostname
    if host != XHS_HOST:
        raise NeedsHumanError(
            f"当前页面未处于小红书商家后台（host={host or 'unknown'}）"
        )
    try:
        text = await page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return
    if is_security_gate_text(text):
        raise NeedsHumanError("小红书页面出现人机/安全验证，请人工完成后重试")


async def reload_target_page(page: Any) -> None:
    await page.reload(wait_until="domcontentloaded", timeout=60_000)
    await check_human_gate(page)


def parse_period_key(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
    if not match:
        return ""
    year, month, day = match.groups()
    if day is None:
        return f"{int(year):04d}-{int(month):02d}"
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("._") or "report"


class _suppress:
    """局部 suppress，避免在类型检查和延迟依赖路径中引入额外上下文。"""

    def __init__(self, *exceptions: type[BaseException]) -> None:
        self.exceptions = exceptions or (Exception,)

    def __enter__(self) -> "_suppress":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, self.exceptions)


__all__ = [
    "ApiError",
    "BrowserApiSession",
    "CN_TZ",
    "DEFAULT_OUTPUT_DIR",
    "MAX_PERIOD_PAGES",
    "NeedsHumanError",
    "NaturalRequestCollector",
    "PROJECT_ROOT",
    "XHS_HOST",
    "XHS_HOME_URL",
    "XHS_ORIGIN",
    "as_int",
    "bounded_total_pages",
    "check_human_gate",
    "date_to_ms",
    "download_file",
    "ensure_api_success",
    "extract_download_url",
    "log",
    "parse_iso_date",
    "parse_period_key",
    "period_rows",
    "period_text",
    "recent_order_range",
    "response_data",
    "reload_target_page",
    "safe_filename",
]
