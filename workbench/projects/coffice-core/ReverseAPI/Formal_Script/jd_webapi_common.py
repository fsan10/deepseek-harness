#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东 WebAPI 下载器共用的 CDP、动态上下文和原始文件能力。

京东商家后台的部分 ``sff.jd.com`` 请求由页面侧安全 SDK 在 XHR 包装器
中补充短效签名。正式模块只复用同一 Target 自然产生的静态业务头，并在
该 Target 内调用页面 XHR；不把 Cookie、h5st、签名地址或 CDP endpoint
写入日志、源码或测试 fixture。
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
JD_HOME_URL = "https://shop.jd.com/jdm/home"
JD_PAGE_HOSTS = frozenset({"shop.jd.com", "jzt.jd.com"})
JD_API_HOSTS = frozenset({"shop.jd.com", "sff.jd.com", "jzt-api.jd.com", "atoms-api.jd.com"})
CN_TZ = timezone(timedelta(hours=8))
MAX_PAGES = 20

# 这些头在真实请求中由页面自然请求提供。h5st 与 dsm-trace-id 必须由京东
# 页面安全 XHR 按当前请求重新生成，绝不能复用抓到的旧值。
STATIC_DYNAMIC_HEADER_NAMES = frozenset(
    {
        "authorization",
        "content-type",
        "dsm-file-path",
        "dsm-lang",
        "dsm-platform",
        "dsm-site",
        "language",
        "loginmode",
        "siteid",
        "x-referer-page",
        "x-requested-with",
        "x-rp-client",
    }
)

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
    """京东 WebAPI 的 HTTP、JSON 结构或业务响应异常。"""

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
    """统一输出，不打印动态请求头、Cookie、签名地址和 endpoint。"""

    print(f"[JD][{report}][{stage}] {message}", flush=True)


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
    """保留可由页面 XHR 设置的静态业务头。

    浏览器会自动处理 Origin/Referer/User-Agent/sec-*；页面安全 XHR
    wrapper 会自行生成 h5st 和 trace id，所以它们被明确排除。
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
    api_name: str | None = None
    # 京东财务/推广微应用可能把安全 XHR 包装器安装在 iframe frame 中。
    # 保留实际发起自然请求的 frame，后续 API 调用必须回到同一 JS 上下文。
    frame: Any | None = None


class NaturalRequestCollector:
    """按同一个浏览器 Target 保存自然 API 请求的动态上下文和模板。"""

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
            if parsed.hostname not in JD_API_HOSTS:
                return
            if str(getattr(request, "resource_type", "")).lower() not in {"xhr", "fetch"}:
                return
            frame = request.frame
            page_url = str(frame.url or "") if frame is not None else ""
            if urlparse(page_url).hostname not in JD_PAGE_HOSTS:
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
                    api_name=(parse_qs(parsed.query).get("api") or [None])[0],
                    frame=frame,
                )
            )
        except Exception:
            # 导航或关闭 Target 时 request.frame 可能暂时不可用；调用侧会
            # 继续等待当前 Target 的后续自然请求。
            return

    def _matching(
        self,
        host: str,
        endpoint_path: str,
        page_route: str,
        page: Any,
        *,
        observed_after: float = 0.0,
        api_name: str | None = None,
    ) -> list[ObservedRequest]:
        return [
            record
            for record in self._records
            if record.page_key == id(page)
            and record.host == host
            and record.path == endpoint_path
            and (api_name is None or record.api_name == api_name)
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
        api_name: str | None = None,
    ) -> dict[str, str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            exact = self._matching(
                host,
                endpoint_path,
                page_route,
                page,
                api_name=api_name,
                observed_after=observed_after,
            )
            if exact:
                return dynamic_fetch_headers(exact[-1].headers)

            # 任务创建、导出和下载地址接口通常不会在页面首次加载时自然
            # 请求，但仍应复用同一 Target 的最新静态业务上下文。
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
            f"京东页面未产生可复用的动态请求上下文：route={page_route} "
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
        api_name: str | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = self._matching(
                host,
                endpoint_path,
                page_route,
                page,
                api_name=api_name,
                observed_after=observed_after,
            )
            for record in reversed(matches):
                if record.post_data is not None:
                    return copy.deepcopy(record.post_data)
            await asyncio.sleep(0.2)
        raise RuntimeError(
            f"京东页面未产生可复用的请求模板：route={page_route} "
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
        api_name: str | None = None,
    ) -> Any | None:
        """返回自然请求所在 frame；无 frame 时由调用方回退到 page。"""

        matches = self._matching(
            host,
            endpoint_path,
            page_route,
            page,
            api_name=api_name,
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
        api_name = (parse_qs(parsed.query).get("api") or [None])[0]
        headers = await self.collector.wait_for_context(
            host,
            path,
            self.page_route,
            self.page,
            api_name=api_name,
            timeout=min(timeout, 30.0),
        )
        target = self.collector.target_for(
            host,
            path,
            self.page_route,
            self.page,
            api_name=api_name,
        ) or self.page
        try:
            body = await browser_post_json(
                target,
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
                host,
                path,
                self.page_route,
                self.page,
                api_name=api_name,
                timeout=min(timeout, 30.0),
                observed_after=observed_after,
            )
            target = self.collector.target_for(
                host,
                path,
                self.page_route,
                self.page,
                api_name=api_name,
                observed_after=observed_after,
            ) or self.page
            try:
                body = await browser_post_json(
                    target,
                    url,
                    payload,
                    headers,
                    timeout=timeout,
                )
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
    """在自然请求所在 page/frame 内用 XHR POST，继承安全 SDK。"""

    script = """
    ({url, payload, headers, timeoutMs}) => new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", url, true);
      request.withCredentials = true;
      request.timeout = timeoutMs;
      for (const [name, value] of Object.entries(headers || {})) {
        request.setRequestHeader(name, value);
      }
      request.onload = () => resolve({status: request.status, text: request.responseText});
      request.onerror = () => reject(new Error("XHR network error"));
      request.ontimeout = () => reject(new Error("XHR timeout"));
      request.send(JSON.stringify(payload));
    })
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
        raise ApiError(f"{urlparse(url).path} 浏览器 XHR 超时") from exc
    except Exception as exc:
        raise ApiError(
            f"{urlparse(url).path} 浏览器 XHR 失败（{type(exc).__name__}）"
        ) from exc

    if not isinstance(value, dict):
        raise ApiError(f"{urlparse(url).path} 浏览器 XHR 返回结构异常")
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
    code = body.get("code")
    success = body.get("success")
    if success is False or code not in (None, 1, "1", 200, "200"):
        message = body.get("msg") or body.get("message") or body.get("subMsg") or "未提供错误信息"
        if is_human_error_message(message):
            raise NeedsHumanError(f"{label}需要恢复登录、权限或安全验证")
        raise ApiError(f"{label}失败：{message}", path=endpoint_path, body=body)


def response_payload(body: dict[str, Any], *, label: str) -> Any:
    if "content" in body and body.get("content") is not None:
        return body.get("content")
    if "data" in body:
        return body.get("data")
    raise ApiError(f"{label}返回缺少 content/data", body=body)


def response_data(body: dict[str, Any], *, label: str) -> dict[str, Any]:
    value = response_payload(body, label=label)
    if not isinstance(value, dict):
        raise ApiError(f"{label}返回的业务 data 不是对象", body=body)
    return value


def extract_download_url(body: dict[str, Any], *, label: str) -> str:
    value = response_payload(body, label=label)
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, dict):
        candidate = value.get("downloadUrl") or value.get("fileUrl") or value.get("url")
    else:
        candidate = None
    if not isinstance(candidate, str) or not candidate.startswith(("http://", "https://")):
        raise ApiError(f"{label}未返回有效下载地址", body=body)
    return candidate


def parse_iso_date(value: str, *, option: str = "日期") -> date:
    try:
        return datetime.strptime(value.strip().replace("/", "-"), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{option}必须使用 YYYY-MM-DD 格式：{value!r}") from exc


def parse_date_range(value: str | None, *, option: str = "--date") -> tuple[date, date] | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    parts = re.split(r"\s*(?:~|至|\.\.|,|，|\s+to\s+)\s*", raw, maxsplit=1, flags=re.IGNORECASE)
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


def recent_30_day_range() -> tuple[date, date]:
    end = datetime.now(CN_TZ).date()
    return end - timedelta(days=29), end


def date_to_ms(value: date, *, end_of_day: bool) -> int:
    clock = dt_time(23, 59, 59, 999000) if end_of_day else dt_time.min
    return int(datetime.combine(value, clock, tzinfo=CN_TZ).timestamp() * 1000)


def sff_utc_bounds(
    start: date,
    end: date,
    *,
    with_milliseconds: bool = False,
) -> list[str]:
    start_dt = datetime.combine(start, dt_time.min, tzinfo=CN_TZ).astimezone(timezone.utc)
    end_dt = datetime.combine(end, dt_time(23, 59, 59, 999000), tzinfo=CN_TZ).astimezone(timezone.utc)
    start_text = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
    if with_milliseconds:
        start_text += ".000"
    return [start_text + "Z", end_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z")]


def clone_payload(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)


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
    referer: str = JD_HOME_URL,
    timeout: tuple[float, float] = (15, 180),
) -> Path:
    """把原始响应写入 ``.part``，校验非空后原子替换正式文件。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("京东接口未返回有效的 HTTP 下载地址")
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
                    f"京东短效文件下载返回 HTTP {response.status_code}，请刷新登录态后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"京东原始文件下载返回 HTTP {response.status_code}")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("京东原始文件下载为空")
        temporary.replace(target)
        return target.resolve()
    except requests.RequestException as exc:
        with suppress(OSError):
            temporary.unlink()
        raise RuntimeError(f"京东原始文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    finally:
        session.close()


async def open_jd_report_page(context: Any, url: str) -> Any:
    """从京东商家后台入口进入报表页，避免沿用未知的当前子域状态。"""

    page = await context.new_page()
    try:
        await page.goto(JD_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await check_human_gate(page)
        if not str(page.url).startswith("https://shop.jd.com/jdm/"):
            raise NeedsHumanError(f"京东 Profile 未处于商家后台：{urlparse(str(page.url)).hostname or 'unknown'}")
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
    if host not in JD_PAGE_HOSTS:
        raise NeedsHumanError(
            f"当前页面未处于京东商家后台（host={host or 'unknown'}），请人工恢复登录"
        )
    lowered_url = str(page.url or "").lower()
    if any(marker in lowered_url for marker in ("login", "passport", "captcha", "verify", "risk")):
        raise NeedsHumanError("京东页面已跳转登录或安全验证，请人工处理")
    try:
        text = await page.locator("body").inner_text(timeout=2_000)
    except Exception:
        return
    if is_human_error_message(text):
        raise NeedsHumanError("京东页面出现登录、人机或安全验证，请人工完成后重试")


async def refresh_jd_page(page: Any, url: str) -> None:
    await page.goto(JD_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await check_human_gate(page)


def bounded_total_pages(data: Any, *, label: str, maximum: int = MAX_PAGES) -> int:
    if not isinstance(data, dict):
        return 1
    raw = data.get("pageTotal") or data.get("totalPage") or data.get("pages") or 1
    try:
        total = max(1, int(raw))
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{label}返回的总页数不是整数") from exc
    if total > maximum:
        raise ApiError(f"{label}总页数 {total} 超过安全上限 {maximum}，已停止")
    return total


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "ApiError",
    "BrowserApiSession",
    "CN_TZ",
    "DEFAULT_OUTPUT_DIR",
    "JD_HOME_URL",
    "NeedsHumanError",
    "NaturalRequestCollector",
    "ObservedRequest",
    "PROJECT_ROOT",
    "as_int",
    "bounded_total_pages",
    "check_human_gate",
    "clone_payload",
    "date_to_ms",
    "default_yesterday",
    "download_original_file",
    "dynamic_fetch_headers",
    "ensure_api_success",
    "extract_download_url",
    "is_human_error_message",
    "log",
    "open_jd_report_page",
    "parse_date_range",
    "parse_iso_date",
    "recent_30_day_range",
    "refresh_jd_page",
    "response_data",
    "response_payload",
    "safe_filename",
    "sff_utc_bounds",
    "unique_path",
]
