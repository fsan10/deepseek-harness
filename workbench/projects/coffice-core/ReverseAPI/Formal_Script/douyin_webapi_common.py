#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖店资金/结算 WebAPI 共用能力。

抖音账单接口依赖当前商家页面的登录 Cookie、Origin 和安全 SDK 上下文。
因此正式下载器只把请求放在已登录的浏览器页面内执行，Python 进程只负责
解析业务响应、轮询导出任务和下载接口返回的短效签名文件地址。

本模块不记录 Cookie、动态安全头、download_id 或签名 URL；下载文件使用
``.part`` 临时文件，只有收到非空响应后才原子改名。
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import urlencode, urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ReverseAPI" / "downloads"

DOUYIN_HOST = "fxg.jinritemai.com"
DOUYIN_ORIGIN = f"https://{DOUYIN_HOST}"
FUND_URL = f"{DOUYIN_ORIGIN}/ffa/fxg-bill/fund-detail-bill"
SETTLEMENT_URL = f"{DOUYIN_ORIGIN}/ffa/fxg-bill/settlement-detail-bill"
HISTORY_URL = f"{DOUYIN_ORIGIN}/ffa/fxg-bill/history-report"

QUERY_ITEM_PATH = "/bill_center/domestic/shop/query_item"
CREATE_DOWNLOAD_PATH = "/bill_center/domestic/shop/download_item"
HISTORY_PATH = "/settlement/settlement/downloadItemList"
DOWNLOAD_URL_PATH = "/settlement/settlement/downloadFileFromId"
SHOP_CONFIG_PATH = "/settle/shop/getShopSettleDayConfig"

CN_TZ = timezone(timedelta(hours=8))
MAX_HISTORY_PAGES = 100
HISTORY_PAGE_SIZE = 20

HUMAN_ERROR_MARKERS = (
    "登录失效",
    "登录异常",
    "请先登录",
    "未登录",
    "权限不足",
    "无权限",
    "验证码",
    "人机验证",
    "安全验证",
    "风险验证",
    "身份验证",
    "短信验证",
    "二次验证",
)


class NeedsHumanError(RuntimeError):
    """登录、店铺选择、权限或安全验证需要人工处理。"""


class ApiError(RuntimeError):
    """抖音 WebAPI 的 HTTP、JSON 结构或业务响应异常。"""

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
    """输出不含动态凭据的统一日志。"""

    print(f"[DY][{report}][{stage}] {message}", flush=True)


def is_human_error_message(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in HUMAN_ERROR_MARKERS)


def parse_iso_date(value: str, *, option: str = "日期") -> date:
    normalized = str(value or "").strip().replace("/", "-")
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{option} 必须使用 YYYY-MM-DD 格式：{value!r}") from exc


DATE_RANGE_SEPARATOR = re.compile(r"\s*(?:~|至|\.\.|,|，|\s+to\s+)\s*", re.I)


def parse_date_range(value: str | None) -> tuple[date, date]:
    """解析单日或闭区间日期，返回真实业务起止日。"""

    raw = str(value or "").strip()
    if not raw:
        yesterday = datetime.now(CN_TZ).date() - timedelta(days=1)
        return yesterday, yesterday
    parts = DATE_RANGE_SEPARATOR.split(raw, maxsplit=1)
    if len(parts) == 1:
        parsed = parse_iso_date(parts[0], option="--date")
        return parsed, parsed
    if any(not part.strip() for part in parts):
        raise ValueError(
            "--date 日期范围必须使用 YYYY-MM-DD~YYYY-MM-DD（或至、..、逗号、to）"
        )
    start = parse_iso_date(parts[0], option="--date 开始日期")
    end = parse_iso_date(parts[1], option="--date 结束日期")
    if start > end:
        raise ValueError("--date 开始日期不能晚于结束日期")
    return start, end


def resolve_date_range(args: Any) -> tuple[date, date]:
    """同时兼容统一入口的 start/end 和单报表入口的 --date。"""

    start_value = getattr(args, "start", None)
    end_value = getattr(args, "end", None)
    date_value = getattr(args, "date", None)
    if date_value and (start_value or end_value):
        raise ValueError("--date 不能与 --start/--end 同时使用")
    if start_value or end_value:
        if not start_value or not end_value:
            raise ValueError("--start 与 --end 必须同时提供")
        start = parse_iso_date(start_value, option="--start")
        end = parse_iso_date(end_value, option="--end")
        if start > end:
            raise ValueError("--start 不能晚于 --end")
        return start, end
    return parse_date_range(date_value)


def format_api_time(value: date, *, end_of_day: bool) -> str:
    return f"{value.isoformat()} {'23:59:59' if end_of_day else '00:00:00'}"


def period_text(start: date, end: date) -> str:
    return f"{start.isoformat()} 00:00:00 ~ {end.isoformat()} 23:59:59"


def safe_filename(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value)).strip("._") or "report"


def unique_path(path: Path) -> Path:
    """不覆盖历史报表，为本次下载分配稳定的唯一名称。"""

    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"输出目录中同名文件过多：{path.name}")


def download_file(
    url: str,
    output_dir: Path,
    filename: str,
    *,
    referer: str = HISTORY_URL,
) -> Path:
    """下载签名 CSV，成功后才将 ``.part`` 原子改名为正式文件。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("抖音接口未返回有效的 HTTP 下载地址")

    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(resolved_dir / safe_filename(filename))
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
                    f"抖音短效文件下载返回 HTTP {response.status_code}，请刷新登录态后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(
                    f"抖音短效文件下载返回 HTTP {response.status_code}"
                )
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)

        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("抖音下载文件为空")
        temporary.replace(target)
        return target.resolve()
    except requests.RequestException as exc:
        with suppress(OSError):
            temporary.unlink()
        raise RuntimeError(f"抖音短效文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    finally:
        session.close()


async def browser_fetch_json(
    page: Any,
    method: str,
    path: str,
    *,
    payload: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """在当前抖音页面的 Cookie/Origin 上下文内执行 JSON fetch。"""

    method = method.upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"不支持的抖音 WebAPI 方法：{method}")
    url = f"{DOUYIN_ORIGIN}{path}"
    if query:
        query_items = [(str(key), str(value)) for key, value in query.items() if value is not None]
        if query_items:
            url = f"{url}?{urlencode(query_items)}"

    script = """
    async ({url, method, payload}) => {
      const options = {method, credentials: "include", headers: {
        "Accept": "application/json, text/plain, */*"
      }};
      if (method === "POST") {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(payload || {});
      }
      const response = await fetch(url, options);
      return {status: response.status, text: await response.text()};
    }
    """
    try:
        value = await asyncio.wait_for(
            page.evaluate(
                script,
                {"url": url, "method": method, "payload": dict(payload or {})},
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ApiError(f"{path} 浏览器 fetch 超时", path=path) from exc
    except Exception as exc:
        raise ApiError(
            f"{path} 浏览器 fetch 失败（{type(exc).__name__}）", path=path
        ) from exc

    if not isinstance(value, dict):
        raise ApiError(f"{path} 浏览器 fetch 返回结构异常", path=path)
    try:
        status = int(value.get("status") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{path} 返回 HTTP 状态异常", path=path) from exc
    text = str(value.get("text") or "")
    try:
        body = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{path} 返回非 JSON（HTTP {status}）", status=status, path=path) from exc
    if not isinstance(body, dict):
        raise ApiError(f"{path} 返回不是 JSON 对象", status=status, path=path, body=body)
    if status < 200 or status >= 300:
        raise ApiError(f"{path} HTTP {status}", status=status, path=path, body=body)
    return body


def ensure_success(
    body: dict[str, Any],
    *,
    label: str,
    path: str,
    expected_codes: set[int | str],
) -> None:
    """严格校验抖音接口业务 code，不以空 data 误判成功。"""

    code = body.get("code")
    normalized = {str(item) for item in expected_codes}
    if str(code) in normalized:
        return
    message = body.get("msg") or body.get("message") or "未提供错误信息"
    if is_human_error_message(message):
        raise NeedsHumanError(f"{label}需要恢复登录、权限或安全验证")
    raise ApiError(f"{label}失败：{message}", path=path, body=body)


class BrowserApiSession:
    """页面内 API 会话，401/403 只允许刷新当前页面并重试一次。"""

    def __init__(self, page: Any, *, refresh: Callable[[], Awaitable[None]]) -> None:
        self.page = page
        self.refresh = refresh

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        label: str,
        expected_codes: set[int | str],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        refreshed = False
        while True:
            try:
                body = await browser_fetch_json(
                    self.page,
                    method,
                    path,
                    payload=payload,
                    query=query,
                    timeout=timeout,
                )
            except ApiError as exc:
                if exc.status not in {401, 403}:
                    raise
                if refreshed:
                    raise NeedsHumanError(
                        f"{label}刷新登录态后仍返回 HTTP {exc.status}，请人工检查登录、权限或安全验证"
                    ) from exc
                log("公共", "上下文", f"{label}返回 {exc.status}，刷新后仅重试一次")
                await self.refresh()
                refreshed = True
                continue
            ensure_success(
                body,
                label=label,
                path=path,
                expected_codes=expected_codes,
            )
            return body

    async def get_json(
        self,
        path: str,
        query: Mapping[str, Any] | None = None,
        *,
        label: str,
        expected_codes: set[int | str] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return await self.request_json(
            "GET",
            path,
            query=query,
            label=label,
            expected_codes=expected_codes or {0, "0"},
            timeout=timeout,
        )

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        label: str,
        expected_codes: set[int | str] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return await self.request_json(
            "POST",
            path,
            payload=payload,
            label=label,
            expected_codes=expected_codes or {"100000"},
            timeout=timeout,
        )


def parse_data_rows(body: Mapping[str, Any], *, label: str) -> list[dict[str, Any]]:
    """解析账单查询的对象数组；平台把行编码成 JSON 字符串。"""

    data = body.get("data")
    if not isinstance(data, list):
        raise ApiError(f"{label}返回缺少 data 数组", body=body)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(data):
        value: Any = raw
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except (TypeError, ValueError) as exc:
                raise ApiError(f"{label}第 {index + 1} 行不是有效 JSON", body=body) from exc
        if not isinstance(value, dict):
            raise ApiError(f"{label}第 {index + 1} 行不是对象", body=body)
        rows.append(value)
    return rows


def read_total(body: Mapping[str, Any], *, label: str) -> int:
    raw = body.get("total")
    try:
        total = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{label}返回的 total 不是整数", body=body) from exc
    if total < 0:
        raise ApiError(f"{label}返回了负数 total", body=body)
    return total


def extract_shop_id(body: Any) -> str | None:
    """从店铺配置响应中读取当前店铺 ShopID，用于历史任务消歧。"""

    keys = {"ShopID", "shop_id", "shopId", "shopID"}

    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and item not in (None, ""):
                    text = str(item).strip()
                    if text.isdigit():
                        return text
            for item in value.values():
                result = walk(item)
                if result:
                    return result
        elif isinstance(value, list):
            for item in value:
                result = walk(item)
                if result:
                    return result
        return None

    return walk(body)


def extract_download_id(body: Mapping[str, Any], *, label: str) -> str:
    value: Any = body.get("download_id")
    if value in (None, "") and isinstance(body.get("data"), dict):
        value = body["data"].get("download_id")
    if not isinstance(value, str) or not value.strip():
        raise ApiError(f"{label}未返回 download_id", body=body)
    return value.strip()


def extract_signed_url(body: Mapping[str, Any], *, label: str) -> str:
    data = body.get("data")
    value = data.get("url") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ApiError(f"{label}未返回有效签名下载地址", body=body)
    return value


def _parse_server_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CN_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})",
        text,
    )
    if not match:
        return None
    parts = [int(part) for part in match.groups()]
    return datetime(*parts, tzinfo=CN_TZ)


def normalize_api_datetime(value: Any) -> str:
    parsed = _parse_server_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


SUCCESS_STATUSES = {"SUCCESS", "SUCCEED", "FINISH", "FINISHED"}
FAIL_STATUSES = {"FAIL", "FAILED", "ERROR", "INVALID"}


def history_record_matches(
    record: Mapping[str, Any],
    *,
    start_time: str,
    end_time: str,
    download_type: str,
    time_type: str,
    download_id: str | None = None,
    shop_id: str | None = None,
    created_after: datetime | None = None,
    status: set[str] | None = None,
) -> bool:
    """严格按日期、类型、时间类型、任务 ID、店铺和创建时间匹配任务。"""

    if normalize_api_datetime(record.get("start_time")) != normalize_api_datetime(start_time):
        return False
    if normalize_api_datetime(record.get("end_time")) != normalize_api_datetime(end_time):
        return False
    if str(record.get("download_type") or "").upper() != download_type.upper():
        return False
    if str(record.get("time_type") or "").upper() != time_type.upper():
        return False
    if download_id is not None and str(record.get("download_id") or "") != download_id:
        return False
    if shop_id is not None and str(record.get("shop_id") or "") != str(shop_id):
        return False
    if created_after is not None:
        created = _parse_server_datetime(record.get("create_time"))
        if created is None or created < created_after:
            return False
    if status is not None and str(record.get("status") or "").upper() not in status:
        return False
    return True


async def fetch_history_records(
    api: BrowserApiSession,
    *,
    label: str,
    timeout: float = 60.0,
) -> tuple[list[dict[str, Any]], int]:
    """读取全部必要历史页，禁止超过安全上限后静默截断。"""

    first = await api.get_json(
        HISTORY_PATH,
        {"page": 0, "size": HISTORY_PAGE_SIZE},
        label=label,
        timeout=timeout,
    )
    rows = parse_data_rows(first, label=label)
    total = read_total(first, label=label)
    try:
        page_size = int(first.get("size") or HISTORY_PAGE_SIZE)
    except (TypeError, ValueError):
        page_size = HISTORY_PAGE_SIZE
    page_size = max(1, page_size)
    pages = max(1, math.ceil(total / page_size))
    if pages > MAX_HISTORY_PAGES:
        raise ApiError(f"{label}总页数 {pages} 超过安全上限 {MAX_HISTORY_PAGES}")

    for page in range(1, pages):
        body = await api.get_json(
            HISTORY_PATH,
            {"page": page, "size": HISTORY_PAGE_SIZE},
            label=label,
            timeout=timeout,
        )
        rows.extend(parse_data_rows(body, label=label))

    # 后端偶尔在不同分页参数下返回重复行；按任务 ID 去重但不丢弃没有 ID
    # 的异常行，后续结构校验仍会让任务明确失败。
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        identity = str(row.get("download_id") or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        deduped.append(row)
    return deduped, total


async def wait_for_history_task(
    api: BrowserApiSession,
    *,
    label: str,
    start_time: str,
    end_time: str,
    download_type: str,
    time_type: str,
    download_id: str,
    shop_id: str | None,
    created_after: datetime,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    """轮询并返回刚创建的成功任务；不接受旧账期或旧任务。"""

    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("导出 timeout 和 poll_interval 必须大于 0")
    deadline = time.monotonic() + timeout
    last_marker: tuple[int, str] | None = None
    while True:
        rows, total = await fetch_history_records(api, label=f"{label}历史任务")
        candidates = [
            row
            for row in rows
            if history_record_matches(
                row,
                start_time=start_time,
                end_time=end_time,
                download_type=download_type,
                time_type=time_type,
                download_id=download_id,
                shop_id=shop_id,
                created_after=created_after,
            )
        ]
        failure = next(
            (
                row
                for row in candidates
                if str(row.get("status") or "").upper() in FAIL_STATUSES
            ),
            None,
        )
        if failure is not None:
            raise ApiError(f"{label}导出任务失败")
        success = [
            row
            for row in candidates
            if str(row.get("status") or "").upper() in SUCCESS_STATUSES
        ]
        if success:
            selected = max(
                success,
                key=lambda row: _parse_server_datetime(row.get("create_time"))
                or datetime.min.replace(tzinfo=CN_TZ),
            )
            return selected

        pending_status = ",".join(
            sorted({str(row.get("status") or "PROCESSING").upper() for row in candidates})
        ) or "未出现"
        marker = (total, pending_status)
        if marker != last_marker:
            log("公共", "轮询", f"{label}历史任务数量={total}，目标状态={pending_status}")
            last_marker = marker
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{label}导出任务在 {timeout:g} 秒内未变为可下载")
        await asyncio.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


__all__ = [
    "ApiError",
    "BrowserApiSession",
    "CN_TZ",
    "CREATE_DOWNLOAD_PATH",
    "DEFAULT_OUTPUT_DIR",
    "DOUYIN_HOST",
    "DOUYIN_ORIGIN",
    "DOWNLOAD_URL_PATH",
    "FUND_URL",
    "HISTORY_PATH",
    "HISTORY_URL",
    "NeedsHumanError",
    "QUERY_ITEM_PATH",
    "SETTLEMENT_URL",
    "SHOP_CONFIG_PATH",
    "download_file",
    "ensure_success",
    "extract_download_id",
    "extract_shop_id",
    "extract_signed_url",
    "fetch_history_records",
    "format_api_time",
    "history_record_matches",
    "is_human_error_message",
    "log",
    "normalize_api_datetime",
    "parse_data_rows",
    "parse_date_range",
    "parse_iso_date",
    "period_text",
    "read_total",
    "resolve_date_range",
    "safe_filename",
    "unique_path",
    "wait_for_history_task",
]
