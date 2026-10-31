#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拼多多商家后台订单导出下载（Cloak Login + 原生 CDP）

流程：
1. 连接 Cloak Login 当前已打开的拼多多 Chromium（通过 CDP debug port）。
2. 监听并拦截网页自己发出的 task/add 请求。
3. 保留网页生成的 anti-content / crawlerInfo，只替换导出日期。
4. 自动创建导出任务。
5. 轮询 task/list，找到本次任务并等待完成。
6. 调用 getUrl 获取短效签名下载地址。
7. 立即下载 CSV 到本地。

依赖：
    python -m pip install requests websocket-client

示例：
    .venv\\Scripts\\python.exe -m ReverseAPI.Formal_Script.pdd_order_export_download \
        --profile "PDD-拼多多-养颜轻食" \
        --start 2026-09-07 \
        --end 2026-09-08 \
        --output-dir ./downloads

也可继续显式传入 wsEndpoint 或 debug port；不传时按完整 Profile 名称自动获取。

说明：
- 默认会尝试自动点击【批量导出】和【生成报表】。
- 如果页面结构变化导致自动点击失败，脚本会自动进入人工触发兜底：
  你只需要在 Cloak 浏览器里点击【批量导出】→【生成报表】，其余流程仍由脚本完成。
- 不会关闭 Cloak 浏览器。
"""

from __future__ import annotations

import argparse
import base64
import json
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

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


try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass


MMS_HOST = "mms.pinduoduo.com"
CASHIER_HOST = "cashier.pinduoduo.com"
PROMOTION_HOST = "yingxiao.pinduoduo.com"
MMS_HOME_URL = "https://mms.pinduoduo.com/home"
ORDERS_URL = "https://mms.pinduoduo.com/orders/list?tab=0"
DEFAULT_PROFILE_NAME = "PDD-拼多多-养颜轻食"
TASK_ADD_URL = "https://mms.pinduoduo.com/mars/shop/recentOrders/export/task/add"
TASK_LIST_URL = "https://mms.pinduoduo.com/mars/shop/orders/export/task/list"
TASK_GET_URL = "https://mms.pinduoduo.com/mars/shop/orders/export/task/getUrl"

TZ_CN = timezone(timedelta(hours=8))
ALLOWED_DYNAMIC_HEADERS = {
    "anti-content",
    "etag",
    "accesstoken",
    "access-token",
    "passid",
    "verifyauthtoken",
    "x-requested-with",
    "x_requested_with",
}


# -----------------------------------------------------------------------------
# 通用工具
# -----------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拼多多订单导出下载")

    endpoint = parser.add_mutually_exclusive_group(required=False)
    endpoint.add_argument(
        "--ws-endpoint",
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
    parser.add_argument("--start", help="开始日期，YYYY-MM-DD；不传则使用默认近30天")
    parser.add_argument("--end", help="结束日期，YYYY-MM-DD；不传则使用默认近30天")
    parser.add_argument("--template", default="对账报表", help="导出模板，默认：对账报表")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--timeout", type=int, default=240, help="等待导出完成的最长秒数，默认 240")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="任务轮询间隔秒数，默认 2")
    parser.add_argument(
        "--manual-trigger",
        action="store_true",
        help="不自动点击页面按钮，手动点击【批量导出】→【生成报表】来触发真实 task/add",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="仅最终下载文件时使用的 HTTP 代理，例如 http://127.0.0.1:7897",
    )

    args = parser.parse_args(argv)
    if args.start is None and args.end is None:
        today = datetime.now(TZ_CN).date()
        args.start = (today - timedelta(days=29)).isoformat()
        args.end = today.isoformat()
        args.date_source = "默认近30天"
    elif not args.start or not args.end:
        parser.error("--start 与 --end 必须同时提供")
    else:
        args.date_source = "指定日期"

    return args


def extract_debug_port(ws_endpoint: str) -> int:
    parsed = urlparse(ws_endpoint)
    if not parsed.port:
        raise ValueError("无法从 wsEndpoint 解析 CDP 端口")
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


def validate_date_range(start: str, end: str) -> tuple[int, int]:
    start_ts = date_to_start_ts(start)
    end_ts = date_to_end_ts(end)
    if start_ts > end_ts:
        raise ValueError("开始日期不能晚于结束日期")
    return start_ts, end_ts


def normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def safe_json_loads(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


# -----------------------------------------------------------------------------
# 简单 CDP Client：单个 Page Target 一个 WebSocket
# -----------------------------------------------------------------------------


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
                msg = json.loads(raw)

                if "id" in msg:
                    msg_id = msg["id"]
                    with self._pending_lock:
                        waiter = self._pending.get(msg_id)
                    if waiter is not None:
                        waiter.put(msg)
                        continue

                if "method" in msg and self.event_handler:
                    try:
                        self.event_handler(msg)
                    except Exception as exc:
                        log(
                            "订单",
                            "上下文",
                            f"CDP 事件处理异常（{type(exc).__name__}）",
                        )
        except Exception as exc:
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

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 15) -> dict[str, Any]:
        if not self.is_alive():
            raise ConnectionError("CDP Target 监听连接已断开")
        cmd_id = self._next_id()
        waiter: queue.Queue = queue.Queue(maxsize=1)

        with self._pending_lock:
            self._pending[cmd_id] = waiter

        try:
            try:
                self.ws.send(
                    json.dumps(
                        {
                            "id": cmd_id,
                            "method": method,
                            "params": params or {},
                        }
                    )
                )
            except Exception as exc:
                self._last_error = exc
                self._closed.set()
                raise ConnectionError("CDP Target 命令发送失败") from exc
            msg = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"CDP命令超时：{method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(cmd_id, None)

        if "error" in msg:
            raise RuntimeError(f"CDP {method} 失败：{msg['error']}")

        return msg.get("result", {})

    def send_no_wait(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.is_alive():
            raise ConnectionError("CDP Target 监听连接已断开")
        cmd_id = self._next_id()
        try:
            self.ws.send(
                json.dumps(
                    {
                        "id": cmd_id,
                        "method": method,
                        "params": params or {},
                    }
                )
            )
        except Exception as exc:
            self._last_error = exc
            self._closed.set()
            raise ConnectionError("CDP Target 命令发送失败") from exc

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self.ws.close()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Page Session
# -----------------------------------------------------------------------------


@dataclass
class InterceptedExportRequest:
    target_id: str
    page_url: str
    headers: dict[str, str]
    original_payload: dict[str, Any]
    modified_payload: dict[str, Any]


class NoDataExport(RuntimeError):
    """订单导出任务已完成，但指定范围没有可导出数据。"""


class PageSession:
    def __init__(self, manager: "BrowserManager", target: dict[str, Any]):
        self.manager = manager
        self.target_id = target["id"]
        self.url = target.get("url", "")
        self.ws_url = target["webSocketDebuggerUrl"]
        self.client = CDPClient(self.ws_url, self._handle_event)
        self.closed = False
        self.started_at = time.monotonic()

        self.client.call("Network.enable", {})
        self.client.call(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*mms.pinduoduo.com/mars/shop/recentOrders/export/task/add*",
                        "requestStage": "Request",
                    }
                ]
            },
        )

    def _handle_event(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            url = request.get("url", "")
            headers = normalize_headers(request.get("headers"))
            self.manager.observe_dynamic_headers(url, headers, self.target_id)

            if MMS_HOST in url:
                self.manager.last_mms_page = self

        elif method == "Fetch.requestPaused":
            request = params.get("request", {})
            url = request.get("url", "")
            request_id = params.get("requestId")

            if url != TASK_ADD_URL:
                self.client.send_no_wait("Fetch.continueRequest", {"requestId": request_id})
                return

            # 只修改第一次由本脚本触发的 task/add；后续同接口直接放行。
            if self.manager.export_intercepted.is_set():
                self.client.send_no_wait("Fetch.continueRequest", {"requestId": request_id})
                return

            try:
                payload = json.loads(request.get("postData") or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("task/add 的 Payload 不是 JSON 对象")

                headers = normalize_headers(request.get("headers"))

                modified = dict(payload)
                modified["groupStartTime"] = self.manager.start_ts
                modified["groupEndTime"] = self.manager.end_ts
                modified["templateName"] = self.manager.template_name

                post_data = json.dumps(
                    modified,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")

                # Fetch.continueRequest 的 postData 要 base64。
                self.client.send_no_wait(
                    "Fetch.continueRequest",
                    {
                        "requestId": request_id,
                        "postData": base64.b64encode(post_data).decode("ascii"),
                    },
                )

                self.manager.observe_dynamic_headers(url, headers, self.target_id)

                self.manager.intercepted_request = InterceptedExportRequest(
                    target_id=self.target_id,
                    page_url=self.url,
                    headers=headers,
                    original_payload=payload,
                    modified_payload=modified,
                )
                self.manager.export_intercepted.set()

                log(
                    "订单",
                    "导出",
                    "已拦截首条 task/add；"
                    f"日期 {payload.get('groupStartTime')}~{payload.get('groupEndTime')} "
                    f"替换为 {self.manager.start_ts}~{self.manager.end_ts}，"
                    f"模板={modified.get('templateName')}",
                )

            except Exception as exc:
                log("订单", "失败", f"修改 task/add 失败（{type(exc).__name__}）")
                self.client.send_no_wait("Fetch.continueRequest", {"requestId": request_id})
                self.manager.intercept_error = exc
                self.manager.export_intercepted.set()

    def evaluate(self, expression: str, timeout: float = 15) -> Any:
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
            raise RuntimeError(f"Runtime.evaluate 异常：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    def click_text(self, text: str) -> bool:
        text_js = json.dumps(text, ensure_ascii=False)
        script = f"""
(() => {{
  const targetText = {text_js};
  const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], span, div'));
  const visible = el => {{
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
  }};
  const exact = candidates.find(el => visible(el) && (el.innerText || '').trim() === targetText);
  const fuzzy = candidates.find(el => visible(el) && (el.innerText || '').trim().includes(targetText));
  const el = exact || fuzzy;
  if (!el) return false;
  const clickable = el.closest('button, a, [role="button"]') || el;
  clickable.scrollIntoView({{block:'center', inline:'center'}});
  clickable.click();
  return true;
}})()
"""
        try:
            return bool(self.evaluate(script))
        except Exception:
            return False

    def has_text(self, text: str) -> bool:
        text_js = json.dumps(text, ensure_ascii=False)
        script = f"""
(() => {{
  const t = {text_js};
  return (document.body && document.body.innerText || '').includes(t);
}})()
"""
        try:
            return bool(self.evaluate(script))
        except Exception:
            return False

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
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        # 浏览器侧 fetch：自动继承当前 Cloak 的 Cookie / 指纹 / Origin / UA。
        safe_headers = {
            "content-type": "application/json",
            "accept": "*/*",
        }
        for key, value in (headers or {}).items():
            key_lower = key.lower()
            # 这些允许作为自定义请求头；Cookie/Origin/Referer/UA 不手工设。
            if key_lower in {
                "anti-content",
                "etag",
                "accesstoken",
                "access-token",
                "passid",
                "verifyauthtoken",
                "x-requested-with",
                "x_requested_with",
            }:
                safe_headers[key] = value

        url_js = json.dumps(url)
        headers_js = json.dumps(safe_headers, ensure_ascii=False)
        payload_js = json.dumps(payload, ensure_ascii=False)

        script = f"""
(async () => {{
  const resp = await fetch({url_js}, {{
    method: 'POST',
    headers: {headers_js},
    credentials: 'include',
    body: JSON.stringify({payload_js})
  }});
  const text = await resp.text();
  return {{status: resp.status, text}};
}})()
"""

        value = self.evaluate(script, timeout=timeout)
        if not isinstance(value, dict):
            raise RuntimeError(f"浏览器 fetch 返回异常：{value!r}")

        try:
            status = int(value.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        text = value.get("text", "")

        try:
            body = json.loads(text)
        except Exception as exc:
            raise ApiError(
                f"{urlparse(url).path} 返回非 JSON（HTTP {status}）",
                status=status,
                path=urlparse(url).path,
            ) from exc

        if status < 200 or status >= 300:
            raise ApiError(
                f"{urlparse(url).path} 返回 HTTP {status}",
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

    def is_alive(self) -> bool:
        return not self.closed and self.client.is_alive()

    def close(self) -> None:
        self.closed = True
        self.client.close()


# -----------------------------------------------------------------------------
# Browser Manager
# -----------------------------------------------------------------------------


class BrowserManager:
    def __init__(self, debug_port: int, start_ts: int, end_ts: int, template_name: str):
        self.debug_port = debug_port
        self.debug_http = f"http://127.0.0.1:{debug_port}"
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.template_name = template_name

        self.sessions: dict[str, PageSession] = {}
        self.last_seen: dict[str, float] = {}
        self.sessions_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.discovery_thread: threading.Thread | None = None

        self.dynamic_headers: dict[str, dict[str, dict[str, str]]] = {}
        self.dynamic_context_time: dict[tuple[str, str], float] = {}
        self.dynamic_headers_lock = threading.RLock()
        self.last_mms_page: PageSession | None = None
        self.listener_failures: dict[str, int] = {}
        self.listener_retry_after: dict[str, float] = {}
        self._last_discovery_error_type: str | None = None

        self.export_intercepted = threading.Event()
        self.intercepted_request: InterceptedExportRequest | None = None
        self.intercept_error: Exception | None = None

    def observe_dynamic_headers(
        self,
        url: str,
        headers: dict[str, str],
        target_id: str,
    ) -> None:
        path = urlparse(url).path
        selected = {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in ALLOWED_DYNAMIC_HEADERS and value
        }
        if not selected:
            return
        with self.dynamic_headers_lock:
            target_headers = self.dynamic_headers.setdefault(target_id, {})
            target_headers[path] = selected
            self.dynamic_context_time[(target_id, path)] = time.monotonic()

    def get_dynamic_headers(
        self,
        url: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, str]:
        if target_id is None and self.intercepted_request is not None:
            target_id = self.intercepted_request.target_id
        if target_id is None and self.last_mms_page is not None:
            target_id = self.last_mms_page.target_id
        path = urlparse(url).path if url else ""
        with self.dynamic_headers_lock:
            endpoint_headers = self.dynamic_headers.get(target_id or "", {})
            if path and path in endpoint_headers:
                result = dict(endpoint_headers[path])
            elif endpoint_headers:
                latest_path = max(
                    endpoint_headers,
                    key=lambda item: self.dynamic_context_time.get(
                        (target_id or "", item), 0.0
                    ),
                )
                result = dict(endpoint_headers[latest_path])
            else:
                result = {}

        if (
            self.intercepted_request
            and self.intercepted_request.target_id == target_id
        ):
            for key in ALLOWED_DYNAMIC_HEADERS:
                if key in self.intercepted_request.headers:
                    result.setdefault(key, self.intercepted_request.headers[key])
        return result

    def clear_context(self, target_id: str) -> None:
        with self.dynamic_headers_lock:
            self.dynamic_headers.pop(target_id, None)
            stale_keys = [
                key for key in self.dynamic_context_time if key[0] == target_id
            ]
            for key in stale_keys:
                self.dynamic_context_time.pop(key, None)

    def refresh_context(self, page: PageSession) -> PageSession:
        """刷新当前 Target，并等待同一 Target 产生新的动态请求头。"""

        target_id = page.target_id
        with self.dynamic_headers_lock:
            before = max(
                (
                    observed_at
                    for (observed_target, _), observed_at in self.dynamic_context_time.items()
                    if observed_target == target_id
                ),
                default=0.0,
            )
        page.reload()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with self.sessions_lock:
                current = self.sessions.get(target_id)
            if current is not None and current.is_alive():
                headers = self.get_dynamic_headers(target_id=target_id)
                with self.dynamic_headers_lock:
                    observed_at = max(
                        (
                            value
                            for (observed_target, _), value in self.dynamic_context_time.items()
                            if observed_target == target_id
                        ),
                        default=0.0,
                    )
                if headers.get("anti-content") and observed_at > before:
                    return current
            time.sleep(0.25)
        raise NeedsHumanError(
            "刷新订单页面后未取得新的 Anti-Content，请检查登录态或安全验证"
        )

    def _fetch_targets(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.debug_http}/json/list", timeout=3)
        response.raise_for_status()
        return response.json()

    def discover_once(self) -> None:
        try:
            targets = self._fetch_targets()
        except Exception:
            return

        active_ids: set[str] = set()
        for target in targets:
            if target.get("type") != "page":
                continue
            url = target.get("url", "")
            parsed = urlparse(url)
            if (
                parsed.hostname not in {MMS_HOST, CASHIER_HOST, PROMOTION_HOST}
                and not url.startswith("about:blank")
            ):
                continue
            if not target.get("webSocketDebuggerUrl"):
                continue

            target_id = target["id"]
            active_ids.add(target_id)
            now = time.monotonic()
            self.last_seen[target_id] = now

            with self.sessions_lock:
                existing = self.sessions.get(target_id)
            if existing is not None:
                existing.url = url
                if (
                    existing.ws_url == target["webSocketDebuggerUrl"]
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
                log("订单", "上下文", "Target 仍存在但监听已断开，准备自动重连")

            if now < self.listener_retry_after.get(target_id, 0.0):
                continue

            try:
                session = PageSession(self, target)
            except Exception as exc:
                failures = self.listener_failures.get(target_id, 0) + 1
                self.listener_failures[target_id] = failures
                delay = min(5.0, 0.25 * (2 ** min(failures - 1, 5)))
                self.listener_retry_after[target_id] = time.monotonic() + delay
                log(
                    "订单",
                    "上下文",
                    f"Target 监听连接失败（{type(exc).__name__}），{delay:g} 秒后重试",
                )
                continue

            with self.sessions_lock:
                self.sessions[target_id] = session

            log("订单", "页面", f"开始监听：{urlparse(url).path or '/'}")

        # Target 认证跳转时可能短暂从 /json/list 消失，保留短宽限期。
        now = time.monotonic()
        with self.sessions_lock:
            stale = [
                tid
                for tid in self.sessions
                if tid not in active_ids
                and now - self.last_seen.get(tid, now) > 8
            ]
            stale_sessions = [self.sessions.pop(tid) for tid in stale]
            for tid in stale:
                self.last_seen.pop(tid, None)
                self.listener_failures.pop(tid, None)
                self.listener_retry_after.pop(tid, None)
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
                    log("订单", "上下文", f"Target 发现异常（{error_type}），监听继续")
                    self._last_discovery_error_type = error_type
            self.stop_event.wait(0.25)

    def start(self) -> None:
        # 先验证端口。
        response = requests.get(f"{self.debug_http}/json/version", timeout=3)
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

    def find_order_page(self) -> PageSession | None:
        sessions = self.list_sessions()
        for session in sessions:
            if "/orders/list" in session.url:
                return session
        return None

    def find_home_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if MMS_HOST in session.url and "/home" in session.url:
                return session
        return None

    def find_mms_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if MMS_HOST in session.url:
                return session
        return None

    def find_any_pdd_page(self) -> PageSession | None:
        for session in self.list_sessions():
            if urlparse(session.url).hostname in {
                MMS_HOST,
                CASHIER_HOST,
                PROMOTION_HOST,
            }:
                return session
        return None

    def best_api_page(self) -> PageSession:
        sessions = self.list_sessions()
        for session in sessions:
            if "/orders/exportExcel" in session.url:
                return session
        for session in sessions:
            if "/orders/list" in session.url:
                return session
        if self.last_mms_page and self.last_mms_page.is_alive():
            return self.last_mms_page
        if sessions:
            return sessions[0]
        raise RuntimeError("没有可用的拼多多页面")

    def find_page_with_text(self, text: str) -> PageSession | None:
        for session in self.list_sessions():
            if session.has_text(text):
                return session
        return None


# -----------------------------------------------------------------------------
# 自动触发真实 task/add
# -----------------------------------------------------------------------------


def wait_until(predicate: Callable[[], Any], timeout: float, interval: float = 0.25) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def ensure_order_page(manager: BrowserManager) -> PageSession:
    """从当前已登录的 mms 页面进入订单列表，准备真实导出上下文。"""

    order_page = manager.find_order_page()
    if order_page is not None:
        order_page.bring_to_front()
        return order_page

    source = (
        manager.find_home_page()
        or manager.find_mms_page()
        or manager.find_any_pdd_page()
    )
    if source is None:
        raise NeedsHumanError("没有找到已登录的拼多多页面，请先完成商家后台登录")

    source.bring_to_front()
    if "/home" not in source.url:
        log("订单", "页面", "当前不是 mms 首页，先返回商家后台首页")
        source.navigate(MMS_HOME_URL)
        source = wait_until(manager.find_home_page, timeout=60, interval=0.5)
        if source is None:
            raise NeedsHumanError("导航到拼多多商家后台首页超时，请检查 Profile 登录状态")

    log("订单", "页面", "从 mms 首页进入订单列表")
    if not source.click_text("订单查询"):
        # 首页菜单可能被折叠或延迟渲染；用同一登录页面打开官方订单路由，
        # 仍由页面自然请求产生 anti-content/crawlerInfo。
        source.navigate(ORDERS_URL)

    order_page = wait_until(manager.find_order_page, timeout=60, interval=0.5)
    if order_page is None:
        raise RuntimeError("从拼多多首页进入订单列表超时")
    order_page.bring_to_front()
    return order_page


def trigger_export(manager: BrowserManager, manual_trigger: bool) -> bool:
    """触发自然导出；返回是否正在等待用户手工完成固定点击。"""

    if manual_trigger:
        log("订单", "页面", "请手动点击【批量导出】→【生成报表】")
        log("订单", "上下文", "脚本将拦截首条 task/add 并只替换日期和模板")
        return True

    def find_ready_order_page() -> PageSession | None:
        page = manager.find_order_page()
        if page is None or not page.has_text("批量导出"):
            return None
        return page

    order_page = wait_until(find_ready_order_page, timeout=60)
    if not order_page:
        log("订单", "页面", "自动触发未找到【批量导出】，等待手工点击")
        return True

    known_target_ids = {session.target_id for session in manager.list_sessions()}
    log("订单", "页面", "自动点击【批量导出】")
    if not order_page.click_text("批量导出"):
        log("订单", "页面", "自动点击【批量导出】失败，等待手工点击")
        return True

    def find_new_report_page() -> PageSession | None:
        # 已存在的 orders/exportExcel 历史页也包含“生成报表”文案，不能把
        # 它当作本次批量导出弹窗；只接受当前订单页或本次新建的 Target。
        if order_page.has_text("生成报表"):
            return order_page
        for page in manager.list_sessions():
            if page.target_id in known_target_ids:
                continue
            if page.has_text("生成报表"):
                return page
        return None

    # 等待“生成报表”出现，可能在当前页，也可能新开/切换到别的页。
    report_page = wait_until(find_new_report_page, timeout=30)
    if not report_page:
        log("订单", "页面", "自动触发未找到【生成报表】，等待手工点击")
        return True

    log("订单", "页面", "自动点击【生成报表】")
    if not report_page.click_text("生成报表"):
        log("订单", "页面", "自动点击【生成报表】失败，等待手工点击")
        return True
    return False


# -----------------------------------------------------------------------------
# API：任务列表、getUrl
# -----------------------------------------------------------------------------


def ensure_api_success(body: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ApiError(f"{name} 返回不是 JSON 对象")
    if body.get("success") is not True or body.get("errorCode") not in (0, None):
        error_code = body.get("errorCode")
        message = body.get("errorMsg") or body.get("message") or body.get("msg")
        if is_human_error_message(message):
            raise NeedsHumanError(str(message)[:160])
        detail = f"errorCode={error_code!r}"
        if message:
            detail += f"，message={str(message)[:160]}"
        raise ApiError(f"{name} 失败：{detail}", body=body)
    return body


def call_api(
    manager: BrowserManager,
    page: PageSession,
    url: str,
    payload: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """按同一 Target/endpoint 上下文调用只读 API，401/403 只刷新一次。"""

    def request(current: PageSession) -> dict[str, Any]:
        return current.browser_fetch_json(
            url,
            payload,
            headers=manager.get_dynamic_headers(url, current.target_id),
            timeout=30,
        )

    try:
        return request(page)
    except ApiError as exc:
        if exc.status not in (401, 403):
            raise
        log("订单", "上下文", f"{label} 返回 {exc.status}，刷新后重试一次")
        refreshed = manager.refresh_context(page)
        try:
            return request(refreshed)
        except ApiError as retry_exc:
            if retry_exc.status in (401, 403):
                raise NeedsHumanError(
                    f"{label} 刷新动态上下文后仍返回 HTTP {retry_exc.status}，"
                    "请检查登录态或安全验证"
                ) from retry_exc
            raise


def find_matching_task(
    body: dict[str, Any],
    start_ts: int,
    end_ts: int,
    created_after: int,
) -> dict[str, Any] | None:
    result = body.get("result") or {}
    items = result.get("pageItems") or []

    candidates = []
    for item in items:
        if item.get("groupStartTime") != start_ts:
            continue
        if item.get("groupEndTime") != end_ts:
            continue
        # 给服务器/客户端时钟差留 10 秒余量。
        if int(item.get("createdTime") or 0) < created_after - 10:
            continue
        candidates.append(item)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda x: (int(x.get("createdTime") or 0), int(x.get("id") or 0)),
    )


def poll_export_task(
    manager: BrowserManager,
    timeout: int,
    poll_interval: float,
    created_after: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status = None

    while time.monotonic() < deadline:
        page = manager.best_api_page()

        body = call_api(
            manager,
            page,
            TASK_LIST_URL,
            {
                "pageNumber": 1,
                "pageSize": 40,
                "exportType": "0",
            },
            "task/list",
        )
        ensure_api_success(body, "task/list")

        task = find_matching_task(body, manager.start_ts, manager.end_ts, created_after)

        if not task:
            log("订单", "轮询", "暂未在任务列表中发现本次导出")
            time.sleep(poll_interval)
            continue

        status = task.get("status")
        status_str = task.get("statusStr")
        progress = task.get("progressRate")

        current_status = (task.get("id"), status, status_str, progress)
        if current_status != last_status:
            log(
                "订单",
                "轮询",
                f"id={task.get('id')} status={status} "
                f"statusText={status_str!s} progress={progress}%",
            )
            last_status = current_status

        if status == 1 or status_str == "完成" or progress == 100:
            return task

        if status == 4 and (
            "0条" in str(status_str)
            or "没有数据" in str(status_str)
            or "无数据" in str(status_str)
        ):
            raise NoDataExport(str(status_str))

        if status_str and any(word in str(status_str) for word in ("失败", "取消", "异常")):
            raise RuntimeError(
                f"导出任务失败：id={task.get('id')} status={status!r} "
                f"statusText={str(status_str)[:160]}"
            )

        time.sleep(poll_interval)

    raise TimeoutError(f"等待导出任务完成超时（{timeout} 秒）")


def get_download_url(manager: BrowserManager, job_id: int) -> str:
    page = manager.best_api_page()
    body = call_api(
        manager,
        page,
        TASK_GET_URL,
        {"jobId": job_id},
        "task/getUrl",
    )
    ensure_api_success(body, "task/getUrl")

    url = body.get("result")
    if not isinstance(url, str) or not url.startswith("http"):
        raise RuntimeError("getUrl 未返回有效下载地址")
    return url


# -----------------------------------------------------------------------------
# 下载文件
# -----------------------------------------------------------------------------


def download_file(
    url: str,
    output_dir: Path,
    start_date: str,
    end_date: str,
    proxy: str | None,
) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".csv", ".zip", ".xls", ".xlsx"}:
        suffix = ".csv"
    log("订单", "下载", "正在保存平台原始文件")
    return download_original_file(
        url,
        output_dir,
        f"PDD_order_{start_date}_to_{end_date}{suffix}",
        proxy=proxy,
        timeout=(10, 90),
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def run(args: argparse.Namespace) -> Path | None:
    start_ts, end_ts = validate_date_range(args.start, args.end)
    connection = resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
    )
    debug_port = connection.debug_port

    log("订单", "计划", f"Profile={args.profile}")
    log(
        "订单",
        "Profile",
        f"CDP 来源={'本次自动获取' if connection.profile_id else '显式参数'}",
    )
    log(
        "订单",
        "计划",
        f"日期={args.start} 00:00:00 ~ {args.end} 23:59:59，"
        f"来源={getattr(args, 'date_source', '指定日期')}，模板={args.template}",
    )
    log("订单", "计划", f"输出目录={Path(args.output_dir).expanduser().resolve()}")

    manager = BrowserManager(
        debug_port=debug_port,
        start_ts=start_ts,
        end_ts=end_ts,
        template_name=args.template,
    )

    try:
        manager.start()
        log("订单", "Profile", "已连接拼多多 Chromium")

        ensure_order_page(manager)

        # 记录创建任务前的时间，用于从 task/list 精确识别本次任务。
        created_after = int(time.time())

        waiting_for_human = trigger_export(manager, args.manual_trigger)

        log("订单", "上下文", "等待网页生成真实 task/add 请求")
        if not manager.export_intercepted.wait(timeout=120):
            message = (
                "120 秒内没有捕获到 task/add；请在订单页完成"
                "【批量导出】→【生成报表】后重试"
            )
            if waiting_for_human:
                raise NeedsHumanError(message)
            raise TimeoutError(message)

        if manager.intercept_error:
            raise manager.intercept_error

        intercepted = manager.intercepted_request
        if not intercepted:
            raise RuntimeError("未取得 task/add 请求信息")

        if "crawlerInfo" not in intercepted.modified_payload:
            log("订单", "上下文", "task/add 未包含 crawlerInfo，按页面原请求继续")

        log("订单", "导出", "task/add 已由浏览器继续发送")

        # 给 task/add 一点入库时间。
        time.sleep(1.0)

        task = poll_export_task(
            manager,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
            created_after=created_after,
        )

        job_id = int(task["id"])
        log("订单", "轮询", f"导出完成，jobId={job_id}")

        download_url = get_download_url(manager, job_id)
        log("订单", "下载", "已取得短效地址，立即下载")

        output_path = download_file(
            download_url,
            Path(args.output_dir),
            args.start,
            args.end,
            args.proxy,
        )

        log(
            "订单",
            "完成",
            f"原始文件={output_path}（{output_path.stat().st_size} bytes）",
        )
        return output_path

    except NoDataExport as exc:
        log("订单", "完成", f"{exc}，不下载文件")
        return None
    finally:
        manager.stop()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr)
        return 2
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[PDD][订单][失败] 用户中断脚本", file=sys.stderr)
        return 130
    except (RuntimeError, TimeoutError, ValueError, OSError, requests.RequestException) as exc:
        print(f"[PDD][订单][失败] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
