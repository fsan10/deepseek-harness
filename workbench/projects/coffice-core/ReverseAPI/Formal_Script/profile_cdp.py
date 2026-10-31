#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 Profile 名称从 Cloak Login 精确取得当前 CDP endpoint。

该模块是下载脚本的本地运行时适配层：

* 明确传入 ``--ws-endpoint`` 或 ``--debug-port`` 时，保持旧调用方式；
* 未传 endpoint 时，通过 Cloak Login 本机 MCP 精确匹配完整 Profile 名称；
* 活动 Profile 直接复用，未运行时启动唯一匹配的 Profile；
* ``start_profile`` 没有立即返回 endpoint 时，有限次数查询活动 Profile 或
  ``get_cdp_endpoint``；
* endpoint 只在当前进程内返回，不写日志、不写捕获 JSON、不持久化。

默认 MCP 地址为本机 Cloak Login 的 ``19610/mcp``，可用
``CLOAK_MCP_URL`` 或调用方的 ``mcp_url`` 覆盖。脚本不会在成功或失败时
自动停止 Profile，避免误关用户已有的浏览器现场。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse


DEFAULT_MCP_URL = "http://127.0.0.1:19610/mcp"
VALID_ENDPOINT_SCHEMES = {"ws", "wss", "http", "https"}
DEFAULT_DISCOVERY_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 0.5


class ProfileResolutionError(RuntimeError):
    """Profile 不唯一、无法启动或没有实时 CDP endpoint。"""


@dataclass(frozen=True)
class ProfileConnection:
    profile_name: str
    profile_id: str | None
    endpoint: str
    started_by_this_run: bool

    @property
    def debug_port(self) -> int:
        parsed = urlparse(self.endpoint)
        if parsed.port is None:
            raise ProfileResolutionError("CDP endpoint 缺少 debug port")
        return parsed.port


def validate_endpoint(endpoint: Any) -> str:
    value = str(endpoint or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in VALID_ENDPOINT_SCHEMES or parsed.port is None:
        raise ProfileResolutionError("CDP endpoint 不是有效的 ws/http 地址")
    return value


def endpoint_from_debug_port(debug_port: int) -> str:
    if not 1 <= int(debug_port) <= 65535:
        raise ProfileResolutionError("CDP debug port 必须在 1 到 65535 之间")
    return f"http://127.0.0.1:{int(debug_port)}"


def _first_value(value: Any, *names: str) -> Any:
    """在 MCP 工具常见的浅层嵌套结果中读取字段。"""

    if isinstance(value, dict):
        for name in names:
            if name in value and value[name] not in (None, ""):
                return value[name]
        for nested_key in ("data", "result", "profile", "item"):
            if nested_key in value:
                nested = _first_value(value[nested_key], *names)
                if nested not in (None, ""):
                    return nested
    return None


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("profiles", "items", "active", "running", "data", "result"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        if _first_value(value, "id", "profileId") is not None:
            return [value]
    return []


def _unwrap_rpc_response(response: Any) -> Any:
    if not isinstance(response, dict):
        return response
    if response.get("error"):
        error = response.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        raise ProfileResolutionError(f"Cloak Login MCP JSON-RPC 失败：{code or 'unknown'}")
    return response.get("result", response)


def _decode_json_or_sse(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        data_lines = [
            line[5:].strip()
            for line in raw.splitlines()
            if line.startswith("data:")
        ]
        for data in reversed(data_lines):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                continue
    raise ProfileResolutionError("Cloak Login MCP 返回了无法解析的 JSON/SSE")


def _unwrap_tool_result(response: Any) -> Any:
    result = _unwrap_rpc_response(response)
    if not isinstance(result, dict):
        return result

    structured = result.get("structuredContent")
    if structured is not None:
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured

    content = result.get("content")
    if isinstance(content, list):
        text_blocks = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        for text in reversed(text_blocks):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        if text_blocks:
            return "\n".join(text_blocks)

    nested = result.get("result")
    if nested is not None:
        return nested
    return result


class CloakMcpClient:
    """Cloak Login 本机 Streamable HTTP MCP 的最小 profile 客户端。"""

    def __init__(self, url: str, timeout: float) -> None:
        self.url = url
        self.timeout = timeout
        self.request_id = 0
        self.session_id: str | None = None
        self.tool_names: set[str] = set()

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        include_id: bool = True,
    ) -> Any:
        self.request_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if include_id:
            payload["id"] = self.request_id
        if params is not None:
            payload["params"] = params
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                status = getattr(response, "status", response.getcode())
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise ProfileResolutionError(f"Cloak Login MCP HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProfileResolutionError(
                "无法访问 Cloak Login MCP，请确认 Cloak Login 已启动并启用 MCP"
            ) from exc
        if status == 202:
            return {"jsonrpc": "2.0", "result": None}
        if not raw.strip():
            raise ProfileResolutionError(f"Cloak Login MCP 返回空响应：HTTP {status}")
        return _decode_json_or_sse(raw)

    def initialize(self) -> None:
        _unwrap_rpc_response(
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "mock-coffice-reverseapi",
                        "version": "1.0",
                    },
                },
            )
        )
        self._request("notifications/initialized", {}, include_id=False)
        tool_result = _unwrap_rpc_response(self._request("tools/list", {}))
        tools = tool_result.get("tools") if isinstance(tool_result, dict) else None
        if not isinstance(tools, list):
            raise ProfileResolutionError("Cloak Login MCP tools/list 没有返回工具列表")
        self.tool_names = {
            str(item.get("name"))
            for item in tools
            if isinstance(item, dict) and item.get("name")
        }
        required = {"list_profiles", "list_active", "start_profile"}
        missing = sorted(required - self.tool_names)
        if missing:
            raise ProfileResolutionError(
                f"Cloak Login MCP 缺少 profile 工具：{', '.join(missing)}"
            )

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tool_names:
            raise ProfileResolutionError(f"Cloak Login MCP 工具不可用：{name}")
        return _unwrap_tool_result(
            self._request("tools/call", {"name": name, "arguments": arguments})
        )


def _profile_id(item: dict[str, Any]) -> str:
    value = _first_value(item, "id", "profileId", "profile_id")
    return str(value or "").strip()


def _profile_name(item: dict[str, Any]) -> str:
    value = _first_value(item, "name", "profileName", "profile_name")
    return str(value or "").strip()


def _profile_endpoint(item: Any) -> str | None:
    value = _first_value(
        item,
        "wsEndpoint",
        "ws_endpoint",
        "webSocketDebuggerUrl",
        "websocketDebuggerUrl",
        "endpoint",
    )
    if value is None and isinstance(item, str):
        value = item
    if value is None:
        return None
    try:
        return validate_endpoint(value)
    except ProfileResolutionError:
        return None


def _exact_profile(profiles: list[dict[str, Any]], profile_name: str) -> dict[str, Any]:
    matches = [item for item in profiles if _profile_name(item) == profile_name]
    if len(matches) == 0:
        raise ProfileResolutionError(f"Cloak Login 中不存在 Profile：{profile_name}")
    if len(matches) > 1:
        raise ProfileResolutionError(f"Cloak Login 中存在多个同名 Profile：{profile_name}")
    if not _profile_id(matches[0]):
        raise ProfileResolutionError(f"Profile 缺少 id：{profile_name}")
    return matches[0]


def _active_for_id(active: list[dict[str, Any]], profile_id: str) -> dict[str, Any] | None:
    matches = [item for item in active if _profile_id(item) == profile_id]
    if len(matches) > 1:
        raise ProfileResolutionError(f"运行中的 Profile 实例不唯一：{profile_id}")
    return matches[0] if matches else None


def _get_endpoint(client: CloakMcpClient, profile_id: str) -> str | None:
    if "get_cdp_endpoint" not in client.tool_names:
        return None
    try:
        value = client.call("get_cdp_endpoint", {"id": profile_id})
    except ProfileResolutionError:
        return None
    return _profile_endpoint(value)


def _resolve_from_mcp(
    profile_name: str,
    *,
    mcp_url: str,
    timeout: float,
    poll_interval: float,
    client_factory: Callable[[str, float], CloakMcpClient] = CloakMcpClient,
) -> ProfileConnection:
    if not profile_name.strip():
        raise ProfileResolutionError("自动取得 CDP 时必须提供完整 Profile 名称")
    client = client_factory(mcp_url, timeout)
    client.initialize()

    requested_name = profile_name.strip()
    # 先看活动实例：同名活动项必须唯一，命中后直接复用实时 endpoint。
    active = _records(client.call("list_active", {}))
    named_active = [item for item in active if _profile_name(item) == requested_name]
    if len(named_active) > 1:
        raise ProfileResolutionError(f"运行中的同名 Profile 不唯一：{requested_name}")
    if len(named_active) == 1:
        active_item = named_active[0]
        profile_id = _profile_id(active_item)
        if not profile_id:
            raise ProfileResolutionError(f"运行中的 Profile 缺少 id：{requested_name}")
        endpoint = _profile_endpoint(active_item) or _get_endpoint(client, profile_id)
        if endpoint is None:
            raise ProfileResolutionError(
                f"运行中的 Profile 没有实时 CDP endpoint：{requested_name}"
            )
        return ProfileConnection(requested_name, profile_id, endpoint, False)

    # 活动清单有时只返回 id/endpoint，没有 name；此时再从保存清单按完整
    # 名称唯一匹配，随后仍只接受同一 profile id 的活动实例。
    profiles = _records(client.call("list_profiles", {}))
    profile = _exact_profile(profiles, requested_name)
    profile_id = _profile_id(profile)
    active_item = _active_for_id(active, profile_id)

    if active_item is not None:
        endpoint = _profile_endpoint(active_item) or _get_endpoint(client, profile_id)
        if endpoint is None:
            raise ProfileResolutionError(
                f"运行中的 Profile 没有实时 CDP endpoint：{profile_name}"
            )
        return ProfileConnection(profile_name, profile_id, endpoint, False)

    started = client.call("start_profile", {"id": profile_id})
    endpoint = _profile_endpoint(started)
    if endpoint is not None:
        return ProfileConnection(profile_name, profile_id, endpoint, True)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = _records(client.call("list_active", {}))
        active_item = _active_for_id(active, profile_id)
        if active_item is not None:
            endpoint = _profile_endpoint(active_item) or _get_endpoint(client, profile_id)
            if endpoint is not None:
                return ProfileConnection(profile_name, profile_id, endpoint, True)
        time.sleep(poll_interval)
    raise ProfileResolutionError(
        f"Profile 已启动但在 {timeout:g} 秒内未取得实时 CDP endpoint：{profile_name}"
    )


def resolve_profile_connection(
    *,
    profile_name: str,
    ws_endpoint: str | None = None,
    debug_port: int | None = None,
    mcp_url: str | None = None,
    timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    client_factory: Callable[[str, float], CloakMcpClient] | None = None,
) -> ProfileConnection:
    """优先使用显式 endpoint，否则自动精确获取当前 Profile 的 CDP。"""

    if ws_endpoint and debug_port is not None:
        raise ProfileResolutionError("--ws-endpoint/--cdp 与 --debug-port 只能传一个")
    if timeout <= 0 or poll_interval <= 0:
        raise ProfileResolutionError("Profile/CDP 自动获取 timeout 和 poll_interval 必须大于 0")
    if ws_endpoint:
        return ProfileConnection(
            profile_name=profile_name,
            profile_id=None,
            endpoint=validate_endpoint(ws_endpoint),
            started_by_this_run=False,
        )
    if debug_port is not None:
        return ProfileConnection(
            profile_name=profile_name,
            profile_id=None,
            endpoint=endpoint_from_debug_port(debug_port),
            started_by_this_run=False,
        )

    actual_mcp_url = (mcp_url or os.environ.get("CLOAK_MCP_URL") or DEFAULT_MCP_URL).strip()
    if not actual_mcp_url.startswith(("http://", "https://")):
        raise ProfileResolutionError("CLOAK_MCP_URL 必须是 http/https MCP 地址")
    return _resolve_from_mcp(
        profile_name,
        mcp_url=actual_mcp_url,
        timeout=timeout,
        poll_interval=poll_interval,
        client_factory=client_factory or CloakMcpClient,
    )


__all__ = [
    "DEFAULT_MCP_URL",
    "ProfileConnection",
    "ProfileResolutionError",
    "endpoint_from_debug_port",
    "resolve_profile_connection",
    "validate_endpoint",
]
