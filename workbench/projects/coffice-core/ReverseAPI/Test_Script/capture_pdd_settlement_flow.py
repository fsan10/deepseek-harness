#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拼多多对账中心结算单导出链路监听器。

本脚本只通过 CDP 读取页面网络事件，不点击页面、不修改请求、不下载文件。
它会自动发现当前 profile 的已有页面及后续打开的新标签页，监听：

* mms.pinduoduo.com、cashier.pinduoduo.com、apm.pinduoduo.com 等拼多多域名
  发出的 XHR / Fetch / Preflight API；
* 对账中心、鉴权页、导出历史页等页面导航；
* 页面网络请求对应的响应状态、响应头和 JSON / 文本响应体；
* Page.downloadWillBegin / Page.downloadProgress 下载事件。

运行到人工下载完成后，在终端按 Ctrl+C，结果会保存为 JSON。

示例（从 ReverseAPI 目录运行，不传参数时直接使用下面的默认常量）：

    & "..\\.venv\\Scripts\\python.exe" "Test_Script\\capture_pdd_settlement_flow.py"

也可以在单行命令中覆盖 wsEndpoint 或只传 CDP 端口：

    & "..\\.venv\\Scripts\\python.exe" "Test_Script\\capture_pdd_settlement_flow.py" --ws-endpoint "ws://127.0.0.1:60120/devtools/browser/<id>"

    & "..\\.venv\\Scripts\\python.exe" "Test_Script\\capture_pdd_settlement_flow.py" --debug-port 60120

默认输出：Test_Script\\pdd_settlement_capture.json
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import websocket


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_DIR / "Test_Script" / "pdd_settlement_capture.json"
# 当前正在使用的 Cloak profile 的 CDP 地址。
# 如果 profile 重启后 wsEndpoint 发生变化，可以直接修改这一行；
# 也可以在命令行通过 --ws-endpoint / --cdp 或 --debug-port 覆盖。
DEFAULT_WS_ENDPOINT = (
    "ws://127.0.0.1:60120/devtools/browser/"
    "b6610eb6-66e5-44aa-a5b6-34ac58d095a9"
)

# 只保存拼多多相关请求；具体是否为 API 请求由 is_capture_request 决定。
PDD_DOMAIN_SUFFIX = ".pinduoduo.com"
PDD_ROOT_DOMAIN = "pinduoduo.com"

API_RESOURCE_TYPES = {"XHR", "Fetch", "Preflight"}
DOCUMENT_RESOURCE_TYPES = {"Document", "SignedExchange"}

# 这些字段只需要知道字段名和结构，不把登录态、票据、风控串写入抓包文件。
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "ticket",
    "signature",
    "signvalue",
    "anti-content",
    "crawlerinfo",
    "verifyauth",
    "passid",
)
SENSITIVE_QUERY_KEYS = {
    "ticket",
    "token",
    "accesstoken",
    "access_token",
    "authorization",
    "signature",
    "sign",
    "password",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("_", "").replace("-", "")
    return any(part.replace("_", "").replace("-", "") in normalized for part in SENSITIVE_KEY_PARTS)


def sanitize_value(value: Any, *, max_string_chars: int | None = None) -> Any:
    """递归脱敏 JSON 兼容值。"""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            result[str(key)] = "***REDACTED***" if is_sensitive_key(key) else sanitize_value(
                item,
                max_string_chars=max_string_chars,
            )
        return result

    if isinstance(value, list):
        return [sanitize_value(item, max_string_chars=max_string_chars) for item in value]

    if isinstance(value, str) and max_string_chars is not None and len(value) > max_string_chars:
        return value[:max_string_chars] + f"\n...[truncated {len(value) - max_string_chars} chars]"

    return value


def sanitize_headers(headers: Any) -> dict[str, Any]:
    if not isinstance(headers, dict):
        return {}

    return {
        str(key): "***REDACTED***" if is_sensitive_key(key) else str(value)
        for key, value in headers.items()
    }


def sanitize_url(url: str) -> str:
    """保留 URL 路径和普通查询参数，隐藏 ticket/token/signature 等值。"""

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    if not parsed.query:
        return url

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower().replace("-", "")
        if key_lower in {item.replace("-", "") for item in SENSITIVE_QUERY_KEYS}:
            value = "***REDACTED***"
        query_items.append((key, value))

    return urlunparse(parsed._replace(query=urlencode(query_items, doseq=True)))


def parse_body_text(text: str, *, max_body_chars: int) -> tuple[Any, bool]:
    """将响应体解析成 JSON；过大文本只保留前缀并标记截断。"""

    truncated = len(text) > max_body_chars
    visible_text = text[:max_body_chars] if truncated else text

    try:
        parsed = json.loads(visible_text)
    except Exception:
        parsed = visible_text

    return sanitize_value(parsed, max_string_chars=max_body_chars), truncated


def parse_post_data(text: str | None, *, max_body_chars: int) -> Any:
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = text

    return sanitize_value(parsed, max_string_chars=max_body_chars)


def is_pdd_host(url: str) -> bool:
    try:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return False

    return hostname == PDD_ROOT_DOMAIN or hostname.endswith(PDD_DOMAIN_SUFFIX)


def is_capture_request(url: str, resource_type: str | None) -> bool:
    """捕获所有 PDD XHR/Fetch，另补充页面导航和可能的导出下载请求。"""

    if not is_pdd_host(url):
        return False

    resource = (resource_type or "").lower()
    path = (urlparse(url).path or "").lower()

    if resource.upper() in API_RESOURCE_TYPES:
        return True

    if resource.upper() in DOCUMENT_RESOURCE_TYPES:
        # 记录用户描述的页面链路，便于确认新标签页和 auth 跳转。
        return any(
            marker in path
            for marker in (
                "/home",
                "/cashier/",
                "/main/auth",
                "/main/bills",
                "/export-history",
            )
        )

    # 某些版本把下载或接口请求标成 Other/None，按路径再补抓一次。
    return any(
        marker in path
        for marker in (
            "/api/",
            "/templar/",
            "/mars/",
            "/export/",
            "/download",
            "/bill/",
        )
    )


class CaptureStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._records]

    def counts(self) -> dict[str, int]:
        with self._lock:
            network = sum(record.get("record_type") == "network" for record in self._records)
            downloads = sum(record.get("record_type") == "download" for record in self._records)
            with_body = sum(
                record.get("record_type") == "network" and "response_body" in record
                for record in self._records
            )
            return {"network": network, "download_events": downloads, "responses_with_body": with_body}


class PageListener:
    """一个 page target 对应一个 CDP WebSocket。"""

    def __init__(
        self,
        target: dict[str, Any],
        store: CaptureStore,
        stop_event: threading.Event,
        max_body_chars: int,
    ) -> None:
        self.target_id = str(target["id"])
        self.page_url = str(target.get("url") or "")
        self.ws_url = str(target["webSocketDebuggerUrl"])
        self.store = store
        self.stop_event = stop_event
        self.max_body_chars = max_body_chars

        self.thread: threading.Thread | None = None
        self.ws: websocket.WebSocket | None = None
        self._command_id = 0
        self._requests: dict[str, dict[str, Any]] = {}
        self._pending_body_commands: dict[int, str] = {}
        self._closed = threading.Event()

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name=f"pdd-cdp-{self.target_id[:8]}",
            daemon=True,
        )
        self.thread.start()

    def update_target(self, target: dict[str, Any]) -> None:
        current_url = str(target.get("url") or "")
        if current_url:
            self.page_url = current_url

    def _next_command_id(self) -> int:
        self._command_id += 1
        return self._command_id

    def _send(self, method: str, params: dict[str, Any] | None = None) -> int:
        if self.ws is None:
            raise RuntimeError("CDP WebSocket 尚未连接")
        command_id = self._next_command_id()
        self.ws.send(
            json.dumps(
                {"id": command_id, "method": method, "params": params or {}},
                ensure_ascii=False,
            )
        )
        return command_id

    def _run(self) -> None:
        print(f"[开始监听页面] target={self.target_id} url={sanitize_url(self.page_url)}")
        try:
            self.ws = websocket.create_connection(
                self.ws_url,
                timeout=5,
                suppress_origin=True,
                enable_multithread=True,
            )
            # 短超时用于让 stop_event 能及时生效；不是网络重试超时。
            self.ws.settimeout(1.0)

            self._send(
                "Network.enable",
                {
                    "maxTotalBufferSize": 100_000_000,
                    "maxResourceBufferSize": 50_000_000,
                },
            )
            self._send("Page.enable")

            while not self.stop_event.is_set():
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                if not raw:
                    break

                try:
                    message = json.loads(raw)
                except Exception as exc:
                    print(f"[CDP 消息解析失败] target={self.target_id}: {exc!r}")
                    continue

                self._handle_message(message)
        except Exception as exc:
            if not self.stop_event.is_set():
                print(f"[页面监听结束] target={self.target_id}: {exc!r}")
        finally:
            self._flush_incomplete_requests()
            self._closed.set()
            if self.ws is not None:
                try:
                    self.ws.close()
                except Exception:
                    pass

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        if isinstance(message_id, int) and message_id in self._pending_body_commands:
            request_id = self._pending_body_commands.pop(message_id)
            self._handle_body_result(request_id, message)
            return

        method = message.get("method")
        params = message.get("params") or {}

        if method == "Network.requestWillBeSent":
            self._on_request(params)
        elif method == "Network.requestWillBeSentExtraInfo":
            self._on_request_extra_info(params)
        elif method == "Network.responseReceived":
            self._on_response(params)
        elif method == "Network.responseReceivedExtraInfo":
            self._on_response_extra_info(params)
        elif method == "Network.loadingFinished":
            self._on_loading_finished(params)
        elif method == "Network.loadingFailed":
            self._on_loading_failed(params)
        elif method == "Page.frameNavigated":
            self._on_frame_navigated(params)
        elif method == "Page.downloadWillBegin":
            self._on_download_will_begin(params)
        elif method == "Page.downloadProgress":
            self._on_download_progress(params)

    def _on_request(self, params: dict[str, Any]) -> None:
        request = params.get("request") or {}
        request_id = str(params.get("requestId") or "")
        url = str(request.get("url") or "")
        resource_type = str(params.get("type") or "")

        if not request_id or not is_capture_request(url, resource_type):
            return

        # requestId 在重定向时可能复用；先保存上一跳，避免被覆盖。
        old_record = self._requests.pop(request_id, None)
        if old_record is not None:
            old_record["redirected"] = True
            old_record["finished_at"] = now_iso()
            self._finalize(old_record)

        record: dict[str, Any] = {
            "record_type": "network",
            "target_id": self.target_id,
            "page_url": sanitize_url(str(params.get("documentURL") or self.page_url)),
            "request_id": request_id,
            "resource_type": resource_type,
            "request_started_at": now_iso(),
            "request": {
                "method": request.get("method"),
                "url": sanitize_url(url),
                "headers": sanitize_headers(request.get("headers")),
                "post_data": parse_post_data(
                    request.get("postData"),
                    max_body_chars=self.max_body_chars,
                ),
                "has_post_data": bool(request.get("postData")),
            },
            "response": None,
            "response_body": None,
            "response_body_available": False,
        }

        if params.get("initiator"):
            record["initiator"] = sanitize_value(params["initiator"])
        if params.get("redirectResponse"):
            record["redirect_response"] = self._response_metadata(params["redirectResponse"])

        self._requests[request_id] = record
        print(
            f"[请求] {resource_type or 'Unknown'} "
            f"{request.get('method', '')} {sanitize_url(url)}"
        )

    def _on_request_extra_info(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None:
            return

        headers = params.get("headers")
        if headers:
            record.setdefault("request", {})["extra_headers"] = sanitize_headers(headers)

    def _response_metadata(self, response: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": sanitize_url(str(response.get("url") or "")),
            "status": response.get("status"),
            "status_text": response.get("statusText"),
            "mime_type": response.get("mimeType"),
            "headers": sanitize_headers(response.get("headers")),
            "protocol": response.get("protocol"),
            "remote_ip_address": response.get("remoteIPAddress"),
            "from_disk_cache": response.get("fromDiskCache"),
            "from_service_worker": response.get("fromServiceWorker"),
        }

    def _on_response(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None:
            return

        response = params.get("response") or {}
        record["response"] = self._response_metadata(response)

    def _on_response_extra_info(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None:
            return

        headers = params.get("headers")
        if headers:
            if not isinstance(record.get("response"), dict):
                record["response"] = {}
            record["response"]["extra_headers"] = sanitize_headers(headers)

    def _should_read_body(self, record: dict[str, Any]) -> bool:
        resource_type = str(record.get("resource_type") or "").upper()
        if resource_type in API_RESOURCE_TYPES:
            return True

        response = record.get("response") or {}
        mime_type = str(response.get("mime_type") or "").lower()
        return "json" in mime_type or "text" in mime_type

    def _on_loading_finished(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None or record.get("finished_at"):
            return

        record["encoded_data_length"] = params.get("encodedDataLength")
        record["finished_at"] = now_iso()

        if self._should_read_body(record) and self.ws is not None:
            command_id = self._send("Network.getResponseBody", {"requestId": request_id})
            self._pending_body_commands[command_id] = request_id
            record["response_body_pending"] = True
            return

        self._finalize(record)

    def _on_loading_failed(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None:
            return

        record["finished_at"] = now_iso()
        record["loading_failed"] = {
            "error_text": params.get("errorText"),
            "canceled": params.get("canceled"),
            "blocked_reason": params.get("blockedReason"),
            "type": params.get("type"),
        }
        self._finalize(record)

    def _handle_body_result(self, request_id: str, message: dict[str, Any]) -> None:
        record = self._requests.get(request_id)
        if record is None:
            return

        record.pop("response_body_pending", None)
        if message.get("error"):
            record["response_body_error"] = sanitize_value(message["error"])
            self._finalize(record)
            return

        result = message.get("result") or {}
        body = result.get("body")
        if body is not None:
            parsed_body, truncated = parse_body_text(
                str(body),
                max_body_chars=self.max_body_chars,
            )
            record["response_body"] = parsed_body
            record["response_body_available"] = True
            record["response_body_truncated"] = truncated
            record["response_body_base64_encoded"] = bool(result.get("base64Encoded"))

        self._finalize(record)

    def _on_frame_navigated(self, params: dict[str, Any]) -> None:
        frame = params.get("frame") or {}
        if not frame.get("parentId") and frame.get("url"):
            self.page_url = str(frame["url"])

    def _on_download_will_begin(self, params: dict[str, Any]) -> None:
        record = {
            "record_type": "download",
            "download_event": "willBegin",
            "target_id": self.target_id,
            "page_url": sanitize_url(self.page_url),
            "event_at": now_iso(),
            "guid": params.get("guid"),
            "url": sanitize_url(str(params.get("url") or "")),
            "suggested_filename": params.get("suggestedFilename"),
        }
        self.store.append(record)
        print(
            f"[下载开始] {record['suggested_filename'] or ''} "
            f"{record['url']}"
        )

    def _on_download_progress(self, params: dict[str, Any]) -> None:
        self.store.append(
            {
                "record_type": "download",
                "download_event": "progress",
                "target_id": self.target_id,
                "page_url": sanitize_url(self.page_url),
                "event_at": now_iso(),
                "guid": params.get("guid"),
                "state": params.get("state"),
                "received_bytes": params.get("receivedBytes"),
                "total_bytes": params.get("totalBytes"),
                "file_path": params.get("filePath"),
            }
        )

    def _finalize(self, record: dict[str, Any]) -> None:
        if record.get("_saved"):
            return
        record["_saved"] = True
        record.pop("response_body_pending", None)
        stored_record = dict(record)
        stored_record.pop("_saved", None)
        self.store.append(stored_record)

        response = record.get("response") or {}
        status = response.get("status") if isinstance(response, dict) else None
        print(
            f"[响应] {status if status is not None else '-'} "
            f"{record.get('request', {}).get('url', '')}"
        )

    def _flush_incomplete_requests(self) -> None:
        for record in list(self._requests.values()):
            if record.get("_saved"):
                continue
            record["capture_incomplete"] = True
            record["finished_at"] = record.get("finished_at") or now_iso()
            self._finalize(record)

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=3)


class CaptureManager:
    def __init__(self, debug_port: int, output_path: Path, max_body_chars: int) -> None:
        self.debug_port = debug_port
        self.debug_http = f"http://127.0.0.1:{debug_port}"
        self.output_path = output_path
        self.max_body_chars = max_body_chars
        self.store = CaptureStore()

        self.stop_event = threading.Event()
        self.discovery_thread: threading.Thread | None = None
        self.sessions: dict[str, PageListener] = {}
        self.sessions_lock = threading.Lock()

    def _fetch_targets(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.debug_http}/json/list", timeout=3)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def discover_once(self) -> None:
        try:
            targets = self._fetch_targets()
        except Exception as exc:
            if not self.stop_event.is_set():
                print(f"[扫描页面失败] {exc!r}")
            return

        active_ids: set[str] = set()
        allowed_target_types = {"page", "iframe", "worker", "service_worker", "shared_worker"}
        for target in targets:
            if target.get("type") not in allowed_target_types:
                continue

            target_url = str(target.get("url") or "")
            if target.get("type") != "worker" and not is_pdd_host(target_url):
                continue

            target_id = str(target.get("id") or "")
            ws_url = target.get("webSocketDebuggerUrl")
            if not target_id or not ws_url:
                continue

            active_ids.add(target_id)
            with self.sessions_lock:
                existing = self.sessions.get(target_id)
            if existing is not None:
                existing.update_target(target)
                continue

            listener = PageListener(
                target=target,
                store=self.store,
                stop_event=self.stop_event,
                max_body_chars=self.max_body_chars,
            )
            with self.sessions_lock:
                # 扫描线程只有一个，但仍防止关闭阶段重复加入。
                if self.stop_event.is_set() or target_id in self.sessions:
                    continue
                self.sessions[target_id] = listener
            listener.start()

        with self.sessions_lock:
            stale_ids = [target_id for target_id in self.sessions if target_id not in active_ids]
            stale = [self.sessions.pop(target_id) for target_id in stale_ids]
        for listener in stale:
            listener.close()

    def _discovery_loop(self) -> None:
        while not self.stop_event.is_set():
            self.discover_once()
            self.stop_event.wait(0.25)

    def start(self) -> None:
        response = requests.get(f"{self.debug_http}/json/version", timeout=3)
        response.raise_for_status()
        version = response.json()
        print(f"[CDP 已连接] port={self.debug_port} browser={version.get('Browser', '')}")
        self.discover_once()
        self.discovery_thread = threading.Thread(
            target=self._discovery_loop,
            name="pdd-cdp-discovery",
            daemon=True,
        )
        self.discovery_thread.start()

    def save(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        records = self.store.snapshot()
        temporary_path = self.output_path.with_name(self.output_path.name + ".tmp")
        temporary_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.output_path)
        return self.output_path.resolve()

    def stop(self) -> None:
        self.stop_event.set()
        with self.sessions_lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()

        for listener in sessions:
            listener.close()

        if self.discovery_thread is not None and self.discovery_thread.is_alive():
            self.discovery_thread.join(timeout=3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="监听拼多多对账中心结算单导出 API 链路")
    endpoint = parser.add_mutually_exclusive_group(required=False)
    endpoint.add_argument(
        "--ws-endpoint",
        "--cdp",
        dest="ws_endpoint",
        default=DEFAULT_WS_ENDPOINT,
        help=f"Cloak 当前 profile 返回的 wsEndpoint，默认使用脚本中的 DEFAULT_WS_ENDPOINT：{DEFAULT_WS_ENDPOINT}",
    )
    endpoint.add_argument(
        "--debug-port",
        type=int,
        help="CDP debug port，例如 60120",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON 输出路径，默认：{DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--max-body-chars",
        type=int,
        default=2_000_000,
        help="每个响应体最多保存的字符数，默认 2000000",
    )
    args = parser.parse_args()

    if args.max_body_chars <= 0:
        parser.error("--max-body-chars 必须大于 0")

    if args.debug_port is not None:
        return args

    if args.ws_endpoint:
        parsed = urlparse(args.ws_endpoint)
        if not parsed.port:
            parser.error(f"无法从 wsEndpoint 解析端口：{args.ws_endpoint}")
        args.debug_port = parsed.port

    return args


def main() -> int:
    args = parse_args()
    manager = CaptureManager(
        debug_port=args.debug_port,
        output_path=args.output if args.output.is_absolute() else PROJECT_DIR / args.output,
        max_body_chars=args.max_body_chars,
    )

    print("=" * 88)
    print("拼多多对账中心结算单导出 API 链路监听")
    print("=" * 88)
    print(f"CDP       : {manager.debug_http}")
    print(f"JSON 输出 : {manager.output_path.resolve()}")
    print()
    print("只监听拼多多域名的 API、页面导航和下载事件，不会自动点击或修改请求。")
    print("请在当前 profile 中依次完成：")
    print("  1. 首页点击【对账中心】，等待进入最终 bills 页面")
    print("  2. 设置目标日期并点击【查询】")
    print("  3. 点击【导出】，在新标签页进入【导出历史】")
    print("  4. 点击目标记录的【下载账单】，等待下载完成")
    print("  5. 回到此终端按 Ctrl+C 保存 JSON")
    print()

    try:
        manager.start()
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[收到 Ctrl+C，正在关闭监听并保存抓包结果]")
    finally:
        manager.stop()
        output_path = manager.save()
        counts = manager.store.counts()
        print(f"[保存完成] {output_path}")
        print(
            f"[统计] network={counts['network']} "
            f"download_events={counts['download_events']} "
            f"responses_with_body={counts['responses_with_body']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
