#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过拼多多对账中心 Web API 下载结算账单。

这个脚本连接已经登录的拼多多 Chromium profile，复用页面自身产生的
``Anti-Content``、``crawlerInfo`` 等动态上下文，然后按对账中心前端实际
使用的接口完成查询、创建导出任务、轮询导出历史和下载 ZIP。

默认用法（昨天）：

    .venv\\Scripts\\python.exe Formal_Script\\pdd_settlement_webapi_download.py

指定日期：

    .venv\\Scripts\\python.exe Formal_Script\\pdd_settlement_webapi_download.py \
        --start 2026-09-08 --end 2026-09-08

也可显式指定 Profile；wsEndpoint/端口参数仅用于兼容旧调用：

    .venv\\Scripts\\python.exe -m ReverseAPI.Formal_Script.pdd_settlement_webapi_download \
        --profile "PDD-拼多多-养颜轻食"

说明：
- 默认按完整 Profile 名称从 Cloak Login 自动复用或启动当前 Profile；显式
  传入 endpoint/端口仍可用于兼容旧调用。
- 不会关闭浏览器或用户已有的页面，只关闭脚本自己的 CDP 连接。
- 不把临时 ticket、签名下载地址、Anti-Content 或 crawlerInfo 写入日志。
- 导出成功后把 ZIP 保存到输出目录，不检查或解压 ZIP 内部内容。
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import websocket


try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection

try:
    from .pdd_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        download_original_file,
        is_human_error_message,
        log,
    )
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from pdd_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        download_original_file,
        is_human_error_message,
        log,
    )


# 命令行 --ws-endpoint / --cdp / --debug-port 可继续显式指定连接；未传
# endpoint 时按 --profile 从 Cloak Login 自动取得实时 endpoint。
DEFAULT_PROFILE_NAME = "PDD-拼多多-养颜轻食"

MMS_HOST = "mms.pinduoduo.com"
CASHIER_HOST = "cashier.pinduoduo.com"
APP_CODE = "113"
MMS_HOME_URL = "https://mms.pinduoduo.com/home"

BILLS_URL_PART = "/main/bills"
MMS_HOME_URL_PART = "/home"
RECONCILIATION_CENTER_SELECTOR = (
    'li#__msfe__side-nav_item_3475 '
    'a[href^="/cashier/finance/payment-bills"]'
)

QUERY_BILL_LIST_URL = (
    "https://cashier.pinduoduo.com/templar/api/bill/"
    "pagingQueryMallBalanceBillListForMms?__app_code=113"
)
QUERY_BILL_STATISTICS_URL = (
    "https://cashier.pinduoduo.com/templar/api/bill/"
    "queryBillStatistics?__app_code=113"
)
CREATE_DOWNLOAD_TASK_URL = (
    "https://cashier.pinduoduo.com/templar/api/bill/"
    "createBillDownloadTask?__app_code=113"
)
QUERY_DOWNLOAD_TASK_LIST_URL = (
    "https://cashier.pinduoduo.com/templar/api/bill/"
    "queryBillDownloadTaskList?__app_code=113"
)

TZ_CN = timezone(timedelta(hours=8))
ALLOWED_DYNAMIC_HEADERS = {
    "anti-content",
    "etag",
    "accesstoken",
    "access-token",
    "passid",
    "verifyauthtoken",
    "x-fin-sherlock-passid",
    "x-requested-with",
    "x_requested_with",
}


# ---------------------------------------------------------------------------
# 参数和日期
# ---------------------------------------------------------------------------


def default_business_date() -> str:
    return (datetime.now(TZ_CN).date() - timedelta(days=1)).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拼多多结算账单 Web API 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument(
        "--ws-endpoint",
        "--cdp",
        dest="ws_endpoint",
        help="可选：显式传入本次 Profile 的 wsEndpoint；不传则按 --profile 自动获取",
    )
    endpoint.add_argument(
        "--debug-port",
        type=int,
        help="可选：显式传入当前 CDP 端口；不传则按 --profile 自动获取",
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help=f"Cloak Login Profile 完整名称，默认：{DEFAULT_PROFILE_NAME}",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="可选：覆盖 Cloak Login MCP 地址；默认读取 CLOAK_MCP_URL 或本机 19610/mcp",
    )
    parser.add_argument("--start", "--start-date", dest="start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", "--end-date", dest="end", help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="等待导出历史任务完成的最长秒数，默认 120",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="导出历史轮询间隔秒数，默认 2",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="下载 ZIP 时使用的 HTTP 代理，例如 http://127.0.0.1:7897",
    )

    args = parser.parse_args(argv)
    if args.start is None and args.end is None:
        args.start = args.end = default_business_date()
        args.date_source = "默认昨天"
    elif not args.start or not args.end:
        parser.error("--start 与 --end 必须同时提供")
    else:
        args.date_source = "指定日期"

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        parser.error(f"日期必须是 YYYY-MM-DD：{exc}")
    if start > end:
        parser.error("--start 不能晚于 --end")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.poll_interval <= 0:
        parser.error("--poll-interval 必须大于 0")

    return args


def extract_debug_port(ws_endpoint: str) -> int:
    parsed = urlparse(ws_endpoint)
    if not parsed.port:
        raise ValueError(f"无法从 wsEndpoint 解析 CDP 端口：{ws_endpoint}")
    return parsed.port


def date_to_start_ts(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=TZ_CN,
    )
    return int(dt.timestamp())


def date_to_end_ts(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=0,
        tzinfo=TZ_CN,
    )
    return int(dt.timestamp())


def normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


# ---------------------------------------------------------------------------
# 最小 CDP 客户端
# ---------------------------------------------------------------------------


class CDPClient:
    def __init__(self, ws_url: str, event_handler: Callable[[dict[str, Any]], None] | None = None):
        self.ws_url = ws_url
        self.event_handler = event_handler
        self.ws = websocket.create_connection(
            ws_url,
            timeout=5,
            suppress_origin=True,
            enable_multithread=True,
        )
        self.ws.settimeout(None)

        self._id = 0
        self._id_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._closed = threading.Event()
        self._last_error: BaseException | None = None
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _next_id(self) -> int:
        with self._id_lock:
            self._id += 1
            return self._id

    def _reader_loop(self) -> None:
        try:
            while not self._closed.is_set():
                raw = self.ws.recv()
                if not raw:
                    break
                message = json.loads(raw)
                if "id" in message:
                    with self._pending_lock:
                        waiter = self._pending.get(message["id"])
                    if waiter is not None:
                        waiter.put(message)
                        continue
                if "method" in message and self.event_handler:
                    try:
                        self.event_handler(message)
                    except Exception as exc:
                        log(
                            "结算",
                            "上下文",
                            f"CDP 事件处理异常（{type(exc).__name__}）",
                        )
        except Exception as exc:
            # 浏览器关闭或 Target 导航期间断开属于正常清理路径；具体 API
            # 调用失败会由 call() 自己报告。
            if not self._closed.is_set():
                self._last_error = exc
        finally:
            self._closed.set()
            with self._pending_lock:
                pending = list(self._pending.values())
            for waiter in pending:
                try:
                    waiter.put_nowait(
                        {"error": {"message": "CDP Target 连接已断开"}}
                    )
                except queue.Full:
                    pass

    def is_alive(self) -> bool:
        return (
            not self._closed.is_set()
            and self._reader.is_alive()
            and bool(getattr(self.ws, "connected", True))
        )

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 15,
    ) -> dict[str, Any]:
        if not self.is_alive():
            raise ConnectionError("CDP Target 监听连接已断开")
        command_id = self._next_id()
        waiter: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[command_id] = waiter

        try:
            try:
                self.ws.send(
                    json.dumps(
                        {
                            "id": command_id,
                            "method": method,
                            "params": params or {},
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                self._last_error = exc
                self._closed.set()
                raise ConnectionError("CDP Target 命令发送失败") from exc
            try:
                message = waiter.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(f"CDP 命令超时：{method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(command_id, None)

        if "error" in message:
            raise RuntimeError(f"CDP {method} 失败：{message['error']}")
        return message.get("result", {})

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.ws.close()
        except Exception:
            pass


@dataclass
class PageTarget:
    target_id: str
    url: str
    websocket_url: str


# ---------------------------------------------------------------------------
# 页面上下文：采集动态风控字段并在页面内发请求
# ---------------------------------------------------------------------------


class PageSession:
    def __init__(self, manager: "BrowserManager", target: PageTarget):
        self.manager = manager
        self.target_id = target.target_id
        self.url = target.url
        self.websocket_url = target.websocket_url
        self.client = CDPClient(target.websocket_url, self._handle_event)
        self.closed = False
        self.started_at = time.monotonic()
        self.client.call("Page.enable", {})
        self.client.call("Network.enable", {})

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})

        if method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                self.url = frame.get("url") or self.url
                self.manager.touch(self.target_id, self.url)
            return

        if method != "Network.requestWillBeSent":
            return

        request = params.get("request", {})
        url = str(request.get("url") or "")
        parsed = urlparse(url)
        if parsed.hostname not in {MMS_HOST, CASHIER_HOST}:
            return

        headers = normalize_headers(request.get("headers"))
        self.manager.observe_dynamic_headers(url, headers, self.target_id)

        if parsed.hostname == CASHIER_HOST:
            self.manager.touch(self.target_id, self.url)
            post_data = request.get("postData")
            payload = parse_json_value(post_data)
            if isinstance(payload, dict):
                if payload.get("crawlerInfo") is not None:
                    self.manager.update_crawler_info(
                        url, payload["crawlerInfo"], self.target_id
                    )
                self.manager.observe_api_payload(url, payload, headers, self.target_id)

    def evaluate(self, expression: str, timeout: float = 30) -> Any:
        result = self.client.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"页面脚本执行异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def has_text(self, text: str) -> bool:
        text_js = json.dumps(text, ensure_ascii=False)
        script = f"""(() => {{
            const body = document.body;
            return Boolean(body && (body.innerText || '').includes({text_js}));
        }})()"""
        try:
            return bool(self.evaluate(script, timeout=10))
        except Exception:
            return False

    def click_reconciliation_center(self) -> bool:
        selector_js = json.dumps(RECONCILIATION_CENTER_SELECTOR)
        script = f"""(() => {{
            const selector = {selector_js};
            const visible = element => {{
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0;
            }};
            let links = [...document.querySelectorAll(selector)].filter(visible);
            if (!links.length) {{
                links = [...document.querySelectorAll(
                    'a[href^="/cashier/finance/payment-bills"]'
                )].filter(visible);
            }}
            const link = links[0];
            if (!link) return false;
            link.scrollIntoView({{block: 'center', inline: 'center'}});
            link.click();
            return true;
        }})()"""
        return bool(self.evaluate(script, timeout=15))

    def bring_to_front(self) -> None:
        self.client.call("Page.bringToFront", {}, timeout=15)

    def navigate(self, url: str) -> None:
        self.client.call("Page.navigate", {"url": url}, timeout=30)

    def reload(self) -> None:
        self.client.call("Page.reload", {"ignoreCache": True}, timeout=30)

    def browser_fetch_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        crawler_info: Any,
        timeout: float = 40,
    ) -> dict[str, Any]:
        body_payload = dict(payload)
        if crawler_info is not None and "crawlerInfo" not in body_payload:
            body_payload["crawlerInfo"] = crawler_info

        safe_headers = {
            "accept": "*/*",
            "content-type": "application/json",
        }
        for key, value in headers.items():
            if key.lower() in ALLOWED_DYNAMIC_HEADERS and value:
                safe_headers[key] = value

        url_js = json.dumps(url, ensure_ascii=False)
        headers_js = json.dumps(safe_headers, ensure_ascii=False)
        payload_js = json.dumps(body_payload, ensure_ascii=False)
        script = f"""(async () => {{
            const response = await fetch({url_js}, {{
                method: 'POST',
                credentials: 'include',
                headers: {headers_js},
                body: JSON.stringify({payload_js})
            }});
            return {{status: response.status, text: await response.text()}};
        }})()"""

        value = self.evaluate(script, timeout=timeout)
        if not isinstance(value, dict):
            raise RuntimeError(f"浏览器 fetch 返回异常：{value!r}")
        status = int(value.get("status") or 0)
        text = value.get("text") or ""
        try:
            body = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                f"接口返回非 JSON（HTTP {status}）",
                status=status,
                body=None,
            ) from exc
        if status < 200 or status >= 300:
            raise ApiError(f"HTTP {status}", status=status, body=body)
        if not isinstance(body, dict):
            raise ApiError("接口返回不是 JSON 对象", status=status, body=body)
        return body

    def cookies(self) -> list[dict[str, Any]]:
        result = self.client.call("Network.getAllCookies", {}, timeout=15)
        return result.get("cookies", [])

    def user_agent(self) -> str:
        value = self.evaluate("navigator.userAgent", timeout=10)
        return str(value or "Mozilla/5.0")

    def is_alive(self) -> bool:
        return not self.closed and self.client.is_alive()

    def close(self) -> None:
        self.closed = True
        self.client.close()


# ---------------------------------------------------------------------------
# Target 管理和动态上下文
# ---------------------------------------------------------------------------


class BrowserManager:
    def __init__(self, debug_port: int):
        self.debug_port = debug_port
        self.debug_http = f"http://127.0.0.1:{debug_port}"
        self.sessions: dict[str, PageSession] = {}
        self.last_seen: dict[str, float] = {}
        self.sessions_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.discovery_thread: threading.Thread | None = None
        self.dynamic_headers: dict[str, dict[str, dict[str, str]]] = {}
        self.crawler_info: dict[str, dict[str, Any]] = {}
        self.dynamic_context_time: dict[tuple[str, str], float] = {}
        self.dynamic_lock = threading.RLock()
        self.observed_api_payloads: dict[str, dict[str, dict[str, Any]]] = {}
        self.observed_api_headers: dict[str, dict[str, dict[str, str]]] = {}
        self.listener_failures: dict[str, int] = {}
        self.listener_retry_after: dict[str, float] = {}
        self._last_discovery_error_type: str | None = None

    def _fetch_targets(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.debug_http}/json/list", timeout=5)
        response.raise_for_status()
        return response.json()

    def touch(self, target_id: str, url: str | None = None) -> None:
        with self.sessions_lock:
            self.last_seen[target_id] = time.monotonic()
            if url and target_id in self.sessions:
                self.sessions[target_id].url = url

    def observe_dynamic_headers(
        self,
        url: str,
        headers: dict[str, str],
        target_id: str,
    ) -> None:
        endpoint = urlparse(url).path
        selected = {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in ALLOWED_DYNAMIC_HEADERS and value
        }
        if not selected:
            return
        with self.dynamic_lock:
            target_headers = self.dynamic_headers.setdefault(target_id, {})
            target_headers[endpoint] = selected
            self.dynamic_context_time[(target_id, endpoint)] = time.monotonic()

    def update_crawler_info(self, url: str, value: Any, target_id: str) -> None:
        endpoint = urlparse(url).path
        with self.dynamic_lock:
            self.crawler_info.setdefault(target_id, {})[endpoint] = value
            self.dynamic_context_time[(target_id, endpoint)] = time.monotonic()

    def observe_api_payload(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        target_id: str | None = None,
    ) -> None:
        """暂存在内存中记录页面自然请求的账单 Payload。

        仅用于复用当前版本页面的兼容字段；不会写入 JSON、日志或其他
        持久化文件。crawlerInfo 也不单独输出。
        """
        path = urlparse(url).path
        if not path.startswith("/templar/api/bill/"):
            return
        endpoint = path.rsplit("/", 1)[-1]
        if endpoint not in {
            "pagingQueryMallBalanceBillListForMms",
            "queryBillStatistics",
            "queryBillDownloadTaskList",
            "createBillDownloadTask",
        }:
            return
        with self.dynamic_lock:
            if target_id is None:
                return
            target_payloads = self.observed_api_payloads.setdefault(target_id, {})
            target_headers = self.observed_api_headers.setdefault(target_id, {})
            target_payloads[endpoint] = dict(payload)
            if headers:
                target_headers[endpoint] = {
                    key: value
                    for key, value in headers.items()
                    if key in ALLOWED_DYNAMIC_HEADERS and value
                }

    def get_observed_payload(self, url: str, target_id: str) -> dict[str, Any]:
        endpoint = urlparse(url).path.rsplit("/", 1)[-1]
        with self.dynamic_lock:
            return dict(self.observed_api_payloads.get(target_id, {}).get(endpoint, {}))

    def get_observed_headers(self, url: str, target_id: str) -> dict[str, str]:
        endpoint = urlparse(url).path.rsplit("/", 1)[-1]
        with self.dynamic_lock:
            return dict(self.observed_api_headers.get(target_id, {}).get(endpoint, {}))

    def get_dynamic_context(
        self,
        target_id: str,
        url: str | None = None,
    ) -> tuple[dict[str, str], Any, float]:
        endpoint = urlparse(url).path if url else ""
        with self.dynamic_lock:
            target_headers = self.dynamic_headers.get(target_id, {})
            target_crawler = self.crawler_info.get(target_id, {})
            if endpoint and endpoint in target_headers:
                selected_endpoint = endpoint
            elif target_headers:
                selected_endpoint = max(
                    target_headers,
                    key=lambda item: self.dynamic_context_time.get(
                        (target_id, item), 0.0
                    ),
                )
            else:
                selected_endpoint = endpoint
            return (
                dict(target_headers.get(selected_endpoint, {})),
                target_crawler.get(selected_endpoint),
                self.dynamic_context_time.get((target_id, selected_endpoint), 0.0),
            )

    def clear_context(self, target_id: str) -> None:
        with self.dynamic_lock:
            self.dynamic_headers.pop(target_id, None)
            self.crawler_info.pop(target_id, None)
            stale_context = [
                key for key in self.dynamic_context_time if key[0] == target_id
            ]
            for key in stale_context:
                self.dynamic_context_time.pop(key, None)
            self.observed_api_payloads.pop(target_id, None)
            self.observed_api_headers.pop(target_id, None)

    def discover_once(self) -> None:
        try:
            targets = self._fetch_targets()
        except Exception:
            return

        active_ids: set[str] = set()
        for raw in targets:
            if raw.get("type") != "page":
                continue
            url = str(raw.get("url") or "")
            if not (
                MMS_HOST in url
                or CASHIER_HOST in url
                or url.startswith("about:blank")
            ):
                continue
            websocket_url = raw.get("webSocketDebuggerUrl")
            target_id = raw.get("id")
            if not target_id or not websocket_url:
                continue

            active_ids.add(target_id)
            now = time.monotonic()
            self.touch(target_id, url)
            with self.sessions_lock:
                existing = self.sessions.get(target_id)
            if existing is not None:
                existing.url = url
                if (
                    existing.websocket_url == websocket_url
                    and existing.is_alive()
                ):
                    if now - existing.started_at >= 2:
                        self.listener_failures.pop(target_id, None)
                        self.listener_retry_after.pop(target_id, None)
                    continue
                with self.sessions_lock:
                    if self.sessions.get(target_id) is existing:
                        self.sessions.pop(target_id, None)
                existing.close()
                self.clear_context(target_id)
                log("结算", "上下文", "Target 仍存在但监听已断开，准备自动重连")

            if now < self.listener_retry_after.get(target_id, 0.0):
                continue

            try:
                session = PageSession(
                    self,
                    PageTarget(
                        target_id=target_id,
                        url=url,
                        websocket_url=websocket_url,
                    ),
                )
            except Exception as exc:
                failures = self.listener_failures.get(target_id, 0) + 1
                self.listener_failures[target_id] = failures
                delay = min(5.0, 0.25 * (2 ** min(failures - 1, 5)))
                self.listener_retry_after[target_id] = time.monotonic() + delay
                log(
                    "结算",
                    "上下文",
                    f"Target 监听连接失败（{type(exc).__name__}），{delay:g} 秒后重试",
                )
                continue
            with self.sessions_lock:
                self.sessions[target_id] = session
                self.last_seen[target_id] = time.monotonic()
            log("结算", "页面", f"开始监听：{urlparse(url).path or '/'}")

        # 页面切换、认证跳转和新标签页创建期间，Target 可能短暂不出现在
        # /json/list；留出宽限期，避免丢掉刚捕获的 API 事件。
        now = time.monotonic()
        with self.sessions_lock:
            stale_ids = [
                target_id
                for target_id in self.sessions
                if target_id not in active_ids
                and now - self.last_seen.get(target_id, now) > 8
            ]
            stale_sessions = [self.sessions.pop(target_id) for target_id in stale_ids]
            for target_id in stale_ids:
                self.last_seen.pop(target_id, None)
                self.listener_failures.pop(target_id, None)
                self.listener_retry_after.pop(target_id, None)
        for session in stale_sessions:
            session.close()
            self.clear_context(session.target_id)

    def _discovery_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.discover_once()
                self._last_discovery_error_type = None
            except Exception as exc:
                error_type = type(exc).__name__
                if error_type != self._last_discovery_error_type:
                    log("结算", "上下文", f"Target 发现异常（{error_type}），监听继续")
                    self._last_discovery_error_type = error_type
            self.stop_event.wait(0.25)

    def start(self) -> None:
        response = requests.get(f"{self.debug_http}/json/version", timeout=5)
        response.raise_for_status()
        self.discover_once()
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.discovery_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.sessions_lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
            self.last_seen.clear()
            self.listener_failures.clear()
            self.listener_retry_after.clear()
        for session in sessions:
            session.close()

    def list_sessions(self) -> list[PageSession]:
        with self.sessions_lock:
            return [session for session in self.sessions.values() if session.is_alive()]

    def find_bills_page(self, target_ids: set[str] | None = None) -> PageSession | None:
        sessions = [
            session
            for session in self.list_sessions()
            if target_ids is None or session.target_id in target_ids
        ]
        # 正常账单页会自然发出列表/统计请求，是捕获当前版本 Payload 的
        # 首选页面；导出历史页仅作为没有普通账单页时的兼容兜底。
        for session in sessions:
            if (
                CASHIER_HOST in session.url
                and BILLS_URL_PART in session.url
                and "/main/bills/export-history" not in session.url
            ):
                return session
        for session in sessions:
            if CASHIER_HOST in session.url and BILLS_URL_PART in session.url:
                return session
        return None

    def find_home_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if MMS_HOST in session.url and MMS_HOME_URL_PART in session.url:
                return session
        return None

    def find_mms_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if MMS_HOST in session.url:
                return session
        return None

    def find_any_pdd_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if MMS_HOST in session.url or CASHIER_HOST in session.url:
                return session
        return None

    def refresh_context(self, page: PageSession) -> PageSession:
        target_id = page.target_id
        _, _, before_context_time = self.get_dynamic_context(target_id)
        with self.dynamic_lock:
            before_observed = set(self.observed_api_payloads.get(target_id, {}))
        page.reload()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            headers, _, context_time = self.get_dynamic_context(target_id)
            has_anti = bool(headers.get("anti-content"))
            has_new_context = context_time > before_context_time
            # 当前对账中心账单接口的自然请求已验证使用 Anti-Content 和
            # x-fin-sherlock-passid；crawlerInfo 仅在某些接口版本需要时
            # 才会出现，不能把它作为所有版本的硬前置条件。
            if has_anti and has_new_context:
                # 给页面剩余的初始化请求一点时间，避免马上用一组已被下一次
                # 请求刷新前的上下文。
                natural_request_deadline = time.monotonic() + 8
                while time.monotonic() < natural_request_deadline:
                    with self.dynamic_lock:
                        if set(self.observed_api_payloads.get(target_id, {})) - before_observed:
                            break
                    time.sleep(0.25)
                with self.sessions_lock:
                    current = self.sessions.get(target_id)
                return current if current is not None and current.is_alive() else page
            time.sleep(0.25)

        headers, _, _ = self.get_dynamic_context(target_id)
        if not headers.get("anti-content"):
            raise NeedsHumanError(
                "未捕获到对账中心页面的 Anti-Content；请确认 profile 仍处于登录态"
            )
        raise RuntimeError("刷新对账中心后未捕获到新的动态上下文")


# ---------------------------------------------------------------------------
# 对账中心 API
# ---------------------------------------------------------------------------


def api_error_detail(body: Any) -> str:
    if not isinstance(body, dict):
        return "返回体不是对象"
    for key in ("errorMsg", "errorMessage", "message", "msg", "errorCode"):
        value = body.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return "接口返回失败"


def unwrap_api_result(body: dict[str, Any], name: str) -> Any:
    if body.get("success") is False:
        message = body.get("errorMsg") or body.get("errorMessage") or body.get("message") or body.get("msg")
        if is_human_error_message(message):
            raise NeedsHumanError(str(message)[:160])
        raise RuntimeError(f"{name} 失败：{api_error_detail(body)}")
    error_code = body.get("errorCode")
    # cashier 对账接口当前正常响应为 success=true、errorCode=1000000；
    # 这里不能沿用 mms 订单接口只接受 0 的判断方式。只有明确 success
    # 为 false，或没有成功标志却带有错误码时，才判定为业务失败。
    if body.get("success") is not True and error_code not in (None, 0, "0", ""):
        raise RuntimeError(f"{name} 失败：{api_error_detail(body)}")

    # 拼多多页面请求封装通常返回 result；个别版本可能直接返回 data，
    # 兼容两种形态，但不对业务字段做臆测转换。
    if isinstance(body.get("result"), (dict, list)):
        return body["result"]
    if isinstance(body.get("data"), (dict, list)):
        return body["data"]
    return body


def build_filter_payload(start_ts: int, end_ts: int) -> dict[str, Any]:
    # 这些字段对应 bills chunk 中页面状态 g 的默认筛选值。
    return {
        "beginTime": start_ts,
        "endTime": end_ts,
        "groupType": 0,
        "classList": [],
        "minAmount": None,
        "maxAmount": None,
        "orderSn": None,
    }


def build_list_payload(filters: dict[str, Any], page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
    # pagingQueryMallBalanceBillListForMms 当前页面自然请求的字段。
    return {
        "classList": filters["classList"],
        "signTypeList": [],
        "inclusiveBeginTime": filters["beginTime"],
        "exclusiveEndTime": filters["endTime"],
        "inclusiveMinAmount": filters["minAmount"],
        "inclusiveMaxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "pageNum": page_num,
        "pageSize": page_size,
    }


def build_statistics_payload(
    filters: dict[str, Any], page_num: int = 1, page_size: int = 20
) -> dict[str, Any]:
    # queryBillStatistics 当前页面自然请求的字段。
    return {
        "classList": filters["classList"],
        "groupType": filters["groupType"],
        "beginTime": filters["beginTime"],
        "endTime": filters["endTime"],
        "minAmount": filters["minAmount"],
        "maxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "offset": (page_num - 1) * page_size,
        "limit": page_size,
    }


def build_create_task_payload(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "beginTime": filters["beginTime"],
        "endTime": filters["endTime"],
        "groupType": filters["groupType"],
        "classList": filters["classList"],
        "minAmount": filters["minAmount"],
        "maxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "isHistory": True,
    }


def call_api(
    manager: BrowserManager,
    page: PageSession,
    url: str,
    payload: dict[str, Any],
    name: str,
    *,
    retry_context: bool = True,
) -> Any:
    # 以页面刚刚自然发出的同接口 Payload 为模板，再覆盖本次日期/分页
    # 参数。这样即使服务端要求的兼容字段没有出现在旧版静态代码中，
    # 也会随当前页面请求一起带上。
    observed_payload = manager.get_observed_payload(url, page.target_id)
    if observed_payload:
        request_payload = dict(observed_payload)
        request_payload.update(payload)
    else:
        request_payload = payload

    headers, crawler_info, _ = manager.get_dynamic_context(page.target_id, url)
    # crawlerInfo 是按接口版本决定的字段，不能把另一个 cashier 请求的
    # crawlerInfo 跨接口注入。若当前接口自然 Payload 已捕获，则以它是否
    # 自带该字段为准；只有尚未捕获自然 Payload 时才使用全局兜底值。
    if observed_payload and "crawlerInfo" not in observed_payload:
        crawler_info = None
    observed_headers = manager.get_observed_headers(url, page.target_id)
    if observed_headers:
        # Anti-Content 可能按一次页面请求生成；优先使用同一接口自然
        # 请求携带的那一组，而不是另一接口的最后一组值。
        request_headers = dict(headers)
        request_headers.update(observed_headers)
    else:
        request_headers = headers
    if not headers.get("anti-content"):
        page = manager.refresh_context(page)
        headers, crawler_info, _ = manager.get_dynamic_context(page.target_id, url)
        observed_payload = manager.get_observed_payload(url, page.target_id)
        if observed_payload:
            request_payload = dict(observed_payload)
            request_payload.update(payload)
            if "crawlerInfo" not in observed_payload:
                crawler_info = None
        observed_headers = manager.get_observed_headers(url, page.target_id)
        request_headers = dict(headers)
        request_headers.update(observed_headers)

    try:
        body = page.browser_fetch_json(url, request_payload, request_headers, crawler_info)
    except ApiError as exc:
        if exc.status in (401, 403) and retry_context:
            log("结算", "上下文", f"{name} 返回 {exc.status}，刷新后重试一次")
            page = manager.refresh_context(page)
            headers, crawler_info, _ = manager.get_dynamic_context(page.target_id, url)
            observed_headers = manager.get_observed_headers(url, page.target_id)
            request_headers = dict(headers)
            request_headers.update(observed_headers)
            observed_payload = manager.get_observed_payload(url, page.target_id)
            if observed_payload:
                request_payload = dict(observed_payload)
                request_payload.update(payload)
                if "crawlerInfo" not in observed_payload:
                    crawler_info = None
            try:
                body = page.browser_fetch_json(
                    url, request_payload, request_headers, crawler_info
                )
            except ApiError as retry_exc:
                if retry_exc.status in (401, 403):
                    raise NeedsHumanError(
                        f"{name} 刷新动态上下文后仍返回 HTTP {retry_exc.status}，"
                        "请检查登录态或安全验证"
                    ) from retry_exc
                raise
        else:
            if exc.status in (401, 403):
                raise NeedsHumanError(
                    f"{name} 返回 HTTP {exc.status}，请检查登录态或安全验证"
                ) from exc
            raise RuntimeError(f"{name} 请求失败：HTTP {exc.status}") from exc
    return unwrap_api_result(body, name)


def find_rows(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    for key in ("billList", "pageItems", "items", "records", "list", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


def find_task_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if not isinstance(result, dict):
        return []
    for key in ("pageItems", "items", "records", "list", "taskList", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def result_count(result: Any) -> int:
    """取得账单查询条数，用于决定是否创建导出任务。"""
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("total", "totalCount", "count"):
            if key in result:
                value = as_int(result.get(key))
                if value is not None:
                    if value < 0:
                        raise ApiError("账单查询条数不能为负数")
                    return value
        for key in ("billList", "pageItems", "items", "records", "list", "data"):
            if isinstance(result.get(key), list):
                return len(result[key])
    raise ApiError("账单查询结果缺少 total 或明细数组")


def as_epoch_seconds(value: Any) -> int | None:
    number = as_int(value)
    if number is None:
        return None
    if number > 10**12:
        return number // 1000
    if number > 10**10:
        return number // 1000
    return number


def task_query(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("queryJsonString")
    parsed = parse_json_value(raw)
    if isinstance(parsed, str):
        parsed = parse_json_value(parsed)
    return parsed if isinstance(parsed, dict) else {}


def task_range_matches(item: dict[str, Any], start_ts: int, end_ts: int) -> bool:
    query = task_query(item)
    begin = query.get("beginTime", item.get("beginTime"))
    end = query.get("endTime", item.get("endTime"))
    return as_int(begin) == start_ts and as_int(end) == end_ts


def task_created_after(item: dict[str, Any], created_after: float) -> bool:
    for key in ("createdAt", "createdTime", "createTime", "created_at"):
        value = as_epoch_seconds(item.get(key))
        if value is not None:
            return value >= int(created_after) - 20
    # 少数页面版本不返回创建时间；日期范围和列表排序仍可用于匹配。
    return True


def task_status_text(item: dict[str, Any]) -> str:
    return str(
        item.get("statusText")
        or item.get("statusName")
        or item.get("statusStr")
        or item.get("message")
        or ""
    )


def task_download_url(item: dict[str, Any]) -> str | None:
    for key in ("downloadUrl", "downloadURL", "url"):
        value = item.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def find_matching_task(
    result: Any,
    start_ts: int,
    end_ts: int,
    created_after: float,
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in find_task_items(result)
        if task_range_matches(item, start_ts, end_ts)
        and task_created_after(item, created_after)
    ]
    if not candidates:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        created = max(
            as_epoch_seconds(item.get(key)) or 0
            for key in ("createdAt", "createdTime", "createTime", "created_at")
        )
        identifier = as_int(item.get("id")) or as_int(item.get("taskId")) or 0
        return created, identifier

    return max(candidates, key=sort_key)


def is_failed_task(item: dict[str, Any]) -> bool:
    text = task_status_text(item).lower()
    if any(word in text for word in ("失败", "异常", "取消", "fail", "error", "cancel")):
        return True
    status = item.get("status")
    return isinstance(status, str) and status.lower() in {"failed", "error", "cancelled", "canceled"}


def poll_download_task(
    manager: BrowserManager,
    page: PageSession,
    start_ts: int,
    end_ts: int,
    created_after: float,
    timeout: int,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: tuple[Any, ...] | None = None
    while time.monotonic() < deadline:
        result = call_api(
            manager,
            page,
            QUERY_DOWNLOAD_TASK_LIST_URL,
            {"page": 1, "size": 20},
            "queryBillDownloadTaskList",
        )
        task = find_matching_task(result, start_ts, end_ts, created_after)
        if task is None:
            log("结算", "轮询", "历史列表中暂未发现本次任务，继续等待")
            time.sleep(poll_interval)
            continue

        url = task_download_url(task)
        status = task.get("status")
        status_text = task_status_text(task)
        state = (task.get("id") or task.get("taskId"), status, status_text, bool(url))
        if state != last_state:
            log(
                "结算",
                "轮询",
                f"id={state[0]} status={status!r} "
                f"statusText={status_text or '-'} downloadUrl={'yes' if url else 'no'}",
            )
            last_state = state

        if is_failed_task(task):
            raise RuntimeError(f"对账中心导出任务失败：status={status!r} {status_text}")

        # 当前页面把 status=0 视为生成中；下载地址出现且状态非 0 时才点击下载。
        status_zero = status in (0, "0")
        if url and not status_zero:
            return task

        time.sleep(poll_interval)

    raise TimeoutError(f"等待结算导出任务完成超时（{timeout} 秒）")


# ---------------------------------------------------------------------------
# ZIP 下载
# ---------------------------------------------------------------------------


def with_app_code(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "__app_code" for key, _ in query):
        query.append(("__app_code", APP_CODE))
    return urlunparse(parsed._replace(query=urlencode(query)))


def download_zip(
    page: PageSession,
    url: str,
    output_dir: Path,
    start_date: str,
    end_date: str,
    proxy: str | None,
) -> Path:
    log("结算", "下载", "正在保存平台原始 ZIP")
    return download_original_file(
        with_app_code(url),
        output_dir,
        f"PDD_settlement_{start_date}_to_{end_date}.zip",
        headers={
            "Accept": "*/*",
            "Referer": page.url,
            "User-Agent": page.user_agent(),
        },
        cookies=page.cookies(),
        proxy=proxy,
        timeout=(15, 180),
    )


# ---------------------------------------------------------------------------
# 页面准备和主流程
# ---------------------------------------------------------------------------


def wait_until(predicate: Callable[[], Any], timeout: float, interval: float = 0.25) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def ensure_bills_page(manager: BrowserManager) -> PageSession:
    home = manager.find_home_page()
    if home is None:
        home = manager.find_mms_page()
        # 新启动的 profile 偶尔还停留在 mms 的过渡页或其他 PDD 页面。
        # 先把这个页面带回 mms 首页，再通过首页菜单进入对账中心；绝不
        # 直接打开 cashier 深链。
        if home is None:
            home = manager.find_any_pdd_page()
        if home is None:
            raise NeedsHumanError("没有找到已登录的拼多多页面，请先完成商家后台登录")
        log("结算", "页面", "当前没有 mms 首页，先返回商家后台首页")
        if MMS_HOME_URL_PART not in home.url:
            home.navigate(MMS_HOME_URL)
        home = wait_until(manager.find_home_page, timeout=60, interval=0.5)
        if home is None:
            raise NeedsHumanError("导航到拼多多商家后台首页超时，请检查 Profile 登录状态")

    known_target_ids = {session.target_id for session in manager.list_sessions()}
    home_target_id = home.target_id
    manager.clear_context(home_target_id)
    home.bring_to_front()

    log("结算", "页面", "从 mms 首页侧栏点击“对账中心”")
    if not wait_until(
        home.click_reconciliation_center,
        timeout=30,
        interval=0.5,
    ):
        raise RuntimeError("首页未找到可见的“对账中心”导航链接")

    def find_entered_bills_page() -> PageSession | None:
        # 忽略脚本启动前已存在的 cashier 账单页，避免把“直接打开的深链”
        # 当作本次从首页菜单进入的页面。允许首页自身导航或点击后新建的
        # Target，兼容站点使用同页跳转和新标签页两种行为。
        entered_target_ids = {home_target_id}
        for session in manager.list_sessions():
            if session.target_id not in known_target_ids:
                entered_target_ids.add(session.target_id)
        return manager.find_bills_page(entered_target_ids)

    page = wait_until(find_entered_bills_page, timeout=60, interval=0.5)
    if page is None:
        raise RuntimeError("从首页点击“对账中心”后 60 秒内未打开 cashier 账单页")
    page.bring_to_front()
    return page


def print_result_summary(name: str, result: Any) -> None:
    if isinstance(result, dict):
        keys = ", ".join(sorted(str(key) for key in result.keys())[:12])
        rows = find_rows(result)
        total = next(
            (result[key] for key in ("total", "totalCount", "count") if key in result),
            None,
        )
        detail = f"rows={len(rows)}"
        if total is not None:
            detail += f" total={total}"
        log("结算", "查询", f"{name}成功（{detail}，字段：{keys or '-'}）")
    else:
        log("结算", "查询", f"{name}成功")


def run(args: argparse.Namespace) -> Path | None:
    start_ts = date_to_start_ts(args.start)
    end_ts = date_to_end_ts(args.end)
    connection = resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
    )
    # BrowserManager 通过当前 endpoint 的 /json/list 取得页面 Target；只把
    # 端口交给它，实时 wsEndpoint 不写日志、不落盘。
    debug_port = connection.debug_port

    log("结算", "计划", f"Profile={args.profile}")
    log(
        "结算",
        "Profile",
        f"CDP 来源={'本次自动获取' if connection.profile_id else '显式参数'}",
    )
    log(
        "结算",
        "计划",
        f"日期={args.start} 00:00:00 ~ {args.end} 23:59:59，"
        f"来源={getattr(args, 'date_source', '指定日期')}",
    )
    log("结算", "计划", f"输出目录={Path(args.output_dir).expanduser().resolve()}")

    manager = BrowserManager(debug_port)
    try:
        manager.start()
        log("结算", "Profile", "已连接拼多多 Chromium")
        page = ensure_bills_page(manager)

        # 账单页刚刚由首页菜单进入；刷新它只为让本次 CDP 连接捕获一组
        # 新的、由页面自己生成的动态请求上下文。
        log("结算", "上下文", "捕获账单页自己的动态请求字段")
        page = manager.refresh_context(page)
        filters = build_filter_payload(start_ts, end_ts)

        list_result = call_api(
            manager,
            page,
            QUERY_BILL_LIST_URL,
            build_list_payload(filters),
            "pagingQueryMallBalanceBillListForMms",
        )
        print_result_summary("账单查询", list_result)
        bill_count = result_count(list_result)
        if bill_count == 0:
            log("结算", "完成", "查询结果为 0 条，不创建导出任务、不下载文件")
            return None

        statistics_result = call_api(
            manager,
            page,
            QUERY_BILL_STATISTICS_URL,
            build_statistics_payload(filters),
            "queryBillStatistics",
        )
        print_result_summary("账单统计", statistics_result)

        created_after = time.time()
        create_result = call_api(
            manager,
            page,
            CREATE_DOWNLOAD_TASK_URL,
            build_create_task_payload(filters),
            "createBillDownloadTask",
        )
        print_result_summary("创建导出任务", create_result)

        task = poll_download_task(
            manager,
            page,
            start_ts,
            end_ts,
            created_after,
            args.timeout,
            args.poll_interval,
        )
        download_url = task_download_url(task)
        if not download_url:
            raise RuntimeError("导出历史任务已完成，但没有返回 downloadUrl")

        output_dir = Path(args.output_dir).expanduser().resolve()
        zip_path = download_zip(
            page,
            download_url,
            output_dir,
            args.start,
            args.end,
            args.proxy,
        )
        log("结算", "完成", f"原始 ZIP={zip_path}（{zip_path.stat().st_size} bytes）")
        return zip_path
    finally:
        manager.stop()


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr)
        return 2
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[PDD][结算][失败] 用户中断脚本", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[PDD][结算][失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
