# -*- coding: utf-8 -*-
"""六个平台报表自动化下载总控。

正常路径只负责编排：通过 Cloak Login MCP 读取 profile、按 profile note
取得平台/公司/店铺，按配置顺序调用已有 Playwright 下载模块。页面操作、
导出轮询、验证码/提取码等待、文件校验和归档仍由各平台正式脚本负责。

本模块不读取或保存密码、令牌或 CDP 地址。CDP 地址只存在于当前子进程
参数中，并在总控日志、汇总 JSON 和异常信息中统一脱敏。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from apps.file_ingest.naming import comparison_key
from scripts.auto_download.business_time import CHINA_TIME_ZONE, china_localtime, china_now


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("all_platform_downloads.json")
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")
DEFAULT_LOG_DIR = DEFAULT_DEST / ".automation_logs" / "all_platform_downloads"
DEFAULT_MCP_URL = "http://127.0.0.1:19610/mcp"

PROFILE_ARGUMENT_MODULES = {
    "tmall_order_download",
    "xiaohongshu_order_download",
}

SUPPORTED_MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NOTE_PATTERN = re.compile(
    r"^platform=(?P<platform>[^;]+);company=(?P<company>[^;]+);shop=(?P<shop>[^;]+)$"
)
SUPPORTED_PLATFORMS = frozenset({"抖音", "京东", "拼多多", "快手", "小红书", "天猫"})
ACTIVE_PROFILE_STATUS_VALUES = frozenset({"active", "enabled", "正常", "启用", "运行"})
EXECUTION_LANE_ALL = "all"
SUPPORTED_EXECUTION_LANES = frozenset({"overnight", "interactive"})

_CDP_PATTERN = re.compile(r"(?i)\b(?:wss?|ws)://[^\s\"']+")
_CDP_FLAG_PATTERN = re.compile(
    r"(?i)(--cdp(?:=|\s+))(?:wss?|ws)://[^\s\"']+"
)
_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|authorization)\b\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


class ControllerError(RuntimeError):
    """总控编排或运行时失败。"""


class DownloadStepError(ControllerError):
    """下载子步骤失败，并保留机器可判定的退出码。"""

    def __init__(self, message: str, *, return_code: int, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.return_code = return_code
        self.result = result


class OptionalProfileMissing(ControllerError):
    """可选 profile 不存在时的可控跳过。"""


def step_execution_lanes(
    step: dict[str, Any],
    *,
    label: str,
) -> tuple[str, ...] | None:
    """读取并校验步骤通道；未配置时保持旧版行为，在所有通道执行。"""

    raw_lanes = step.get("lanes")
    if raw_lanes is None:
        return None
    if not isinstance(raw_lanes, list) or not raw_lanes:
        raise ControllerError(f"{label}.lanes 必须是非空字符串数组")
    if any(not isinstance(lane, str) or not lane.strip() for lane in raw_lanes):
        raise ControllerError(f"{label}.lanes 必须是非空字符串数组")
    lanes = tuple(lane.strip() for lane in raw_lanes)
    if len(set(lanes)) != len(lanes):
        raise ControllerError(f"{label}.lanes 不得包含重复通道")
    unknown = sorted(set(lanes) - SUPPORTED_EXECUTION_LANES)
    if unknown:
        raise ControllerError(
            f"{label}.lanes 包含未知通道：{', '.join(unknown)}；"
            f"允许值={', '.join(sorted(SUPPORTED_EXECUTION_LANES))}"
        )
    return lanes


def local_timestamp() -> str:
    return china_now().isoformat(timespec="seconds")


def redact(value: Any) -> str:
    """脱敏日志和异常文本中的 CDP、密码、令牌等值。"""

    text = str(value)
    text = _CDP_FLAG_PATTERN.sub(r"\1<CDP_REDACTED>", text)
    text = _CDP_PATTERN.sub("<CDP_REDACTED>", text)
    text = _SECRET_PATTERN.sub(r"\1<REDACTED>", text)
    return text


class RedactingFormatter(logging.Formatter):
    converter = staticmethod(china_localtime)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("all_platform_downloads")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = RedactingFormatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def resolve_path(raw: str | Path, *, base: Path = PROJECT_ROOT) -> Path:
    path = Path(os.path.expandvars(str(raw))).expanduser()
    return path if path.is_absolute() else base / path


def load_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            config = json.load(stream)
    except FileNotFoundError as exc:
        raise ControllerError(f"总控配置文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ControllerError(f"总控配置不是有效 JSON：{path}；{exc}") from exc
    if not isinstance(config, dict):
        raise ControllerError("总控配置顶层必须是 JSON 对象")
    profiles = config.get("profiles")
    profile_rules = config.get("profile_rules")
    has_profiles = isinstance(profiles, list) and bool(profiles)
    has_profile_rules = isinstance(profile_rules, list) and bool(profile_rules)
    if has_profiles and has_profile_rules:
        raise ControllerError("总控配置不能同时包含 profiles 和 profile_rules")
    if not has_profiles and not has_profile_rules:
        raise ControllerError("总控配置必须包含非空 profiles 或 profile_rules 数组")
    profile_status = config.get("profile_status", {})
    if not isinstance(profile_status, dict):
        raise ControllerError("总控配置 profile_status 必须是 JSON 对象")
    for profile_name, status_config in profile_status.items():
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ControllerError("总控配置 profile_status 的 key 必须是非空 profile 名称")
        if not isinstance(status_config, dict):
            raise ControllerError(
                f"总控配置 profile_status[{profile_name}] 必须是 JSON 对象"
            )
        status = status_config.get("status", "active")
        if not isinstance(status, str):
            raise ControllerError(
                f"总控配置 profile_status[{profile_name}].status 必须是字符串"
            )
        enabled = status_config.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ControllerError(
                f"总控配置 profile_status[{profile_name}].enabled 必须是布尔值"
            )
    plan_label = "profiles" if has_profiles else "profile_rules"
    plans = profiles if has_profiles else profile_rules
    assert isinstance(plans, list)
    for plan_index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            continue
        steps = plan.get("steps")
        if not isinstance(steps, list):
            continue
        for step_index, step in enumerate(steps):
            if isinstance(step, dict):
                step_execution_lanes(
                    step,
                    label=f"{plan_label}[{plan_index}].steps[{step_index}]",
                )
    return config


def parse_profile_note(note: Any, profile_name: str) -> dict[str, str]:
    if not isinstance(note, str) or not note.strip():
        raise ControllerError(
            f"profile note 缺失，无法取得 platform/company/shop：{profile_name}"
        )
    match = NOTE_PATTERN.fullmatch(note.strip())
    if not match:
        raise ControllerError(
            f"profile note 格式不符合 platform=<平台>;company=<公司>;shop=<店铺>："
            f"{profile_name}"
        )
    metadata = {key: value.strip() for key, value in match.groupdict().items()}
    if not all(metadata.values()):
        raise ControllerError(f"profile note 存在空的业务参数：{profile_name}")
    return metadata


def validate_profile_companies(plans: Iterable[dict[str, Any]]) -> None:
    """Reject conflicting notes for one platform/shop before starting downloads."""
    identities: dict[tuple[str, str], tuple[str, str]] = {}
    for plan in plans:
        metadata = plan["_metadata"]
        key = (comparison_key(metadata["platform"]), comparison_key(metadata["shop"]))
        company = comparison_key(metadata["company"])
        name = plan["profile_name"]
        previous = identities.get(key)
        if previous and previous[0] != company:
            raise ControllerError(
                f"同一平台店铺的 profile 公司名不一致：{metadata['platform']}/{metadata['shop']}；"
                f"{previous[1]}={previous[0]}，{name}={company}；"
                "请按 DIM 核对这些 profile note 的 company 后重试"
            )
        identities[key] = (company, name)


def first_value(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def as_list(value: Any, *, label: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("profiles", "items", "data", "value", "result"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
    raise ControllerError(f"Cloak Login {label} 返回的数据不是数组")


def unwrap_rpc_result(response: Any) -> Any:
    if not isinstance(response, dict):
        raise ControllerError("Cloak Login MCP 返回了非 JSON-RPC 对象")
    error = response.get("error")
    if isinstance(error, dict):
        message = error.get("message") or json.dumps(error, ensure_ascii=False)
        raise ControllerError(f"Cloak Login MCP 请求失败：{redact(message)}")
    return response.get("result", response)


def unwrap_tool_result(response: Any) -> Any:
    result = unwrap_rpc_result(response)
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        texts = [
            block.get("text", "")
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        raise ControllerError(f"Cloak Login 工具执行失败：{redact(' '.join(texts))}")

    structured = result.get("structuredContent")
    if structured is not None:
        if isinstance(structured, dict) and structured.get("result") is not None:
            return structured["result"]
        return structured

    content = result.get("content")
    if isinstance(content, list):
        text_blocks = [
            block.get("text")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        for text in text_blocks:
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and parsed.get("result") is not None:
                    return parsed["result"]
                return parsed
            except json.JSONDecodeError:
                continue
        if text_blocks:
            return "\n".join(str(text) for text in text_blocks)
    # Cloak Login returns a few profile-management tool payloads wrapped in a
    # vendor-level ``result`` object instead of MCP content blocks.  Unwrap it
    # here so callers can consistently read fields such as ``wsEndpoint``.
    nested_result = result.get("result")
    if nested_result is not None:
        return nested_result
    return result


class CloakMcpClient:
    """通过 Cloak Login 的本机 Streamable HTTP MCP 端点管理 profile。"""

    def __init__(self, url: str, logger: logging.Logger) -> None:
        self.url = url
        self.logger = logger
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
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                status = getattr(response, "status", response.getcode())
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ControllerError(
                f"Cloak Login MCP HTTP {exc.code}：{redact(raw[:1000])}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ControllerError(
                f"无法访问 Cloak Login MCP {self.url}：{redact(exc)}；"
                "请确认 Cloak Login 已启动并启用 MCP"
            ) from exc

        if status == 202:
            return {"jsonrpc": "2.0", "result": None}
        if not raw.strip():
            raise ControllerError(f"Cloak Login MCP 返回空响应：HTTP {status}")
        return self._decode_response(raw)

    @staticmethod
    def _decode_response(raw: str) -> Any:
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
        raise ControllerError("Cloak Login MCP 返回了无法解析的 JSON/SSE 响应")

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mock-coffice-all-platform-downloads", "version": "1.0"},
            },
        )
        self._request("notifications/initialized", {}, include_id=False)
        self.logger.info("Cloak Login MCP 初始化完成：url=%s", self.url)

    def load_tools(self) -> None:
        result = unwrap_rpc_result(self._request("tools/list", {}))
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise ControllerError("Cloak Login MCP tools/list 没有返回 tools 数组")
        self.tool_names = {
            str(item.get("name"))
            for item in tools
            if isinstance(item, dict) and item.get("name")
        }
        required = {"list_profiles", "get_profile", "list_active", "start_profile", "stop_profile"}
        missing = sorted(required - self.tool_names)
        if missing:
            raise ControllerError(f"Cloak Login MCP 缺少 profile 管理工具：{', '.join(missing)}")
        self.logger.info("Cloak Login MCP 工具发现完成：profile 管理工具可用")

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tool_names:
            raise ControllerError(f"Cloak Login MCP 工具不可用：{name}")
        response = self._request("tools/call", {"name": name, "arguments": arguments})
        return unwrap_tool_result(response)


class ResumeCheckpoint:
    """按本地日期和配置版本保存 profile/步骤级可恢复状态。"""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        path: Path,
        scope: str,
        config_fingerprint: str,
        logger: logging.Logger,
        execution_context_fingerprint: str | None = None,
        require_scope_match: bool = False,
    ) -> None:
        self.path = path
        self.scope = scope
        self.config_fingerprint = config_fingerprint
        self.execution_context_fingerprint = str(
            execution_context_fingerprint or ""
        ).strip()
        self.logger = logger
        self.require_scope_match = require_scope_match
        self.data = self._load()

    @staticmethod
    def step_key(step: dict[str, Any]) -> str:
        name = str(step.get("name", "")).strip()
        module = str(step.get("module", "")).strip()
        args = step.get("args", [])
        normalized_args = [str(item) for item in args] if isinstance(args, list) else [str(args)]
        return f"{name}|{module}|{json.dumps(normalized_args, ensure_ascii=False, separators=(',', ':'))}"

    @staticmethod
    def profile_signature(metadata: dict[str, str]) -> str:
        canonical = json.dumps(
            {
                "platform": metadata.get("platform", ""),
                "company": metadata.get("company", ""),
                "shop": metadata.get("shop", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _new_data(self) -> dict[str, Any]:
        now = local_timestamp()
        data = {
            "schema_version": self.SCHEMA_VERSION,
            "scope": self.scope,
            "config_fingerprint": self.config_fingerprint,
            "created_at": now,
            "updated_at": now,
            "profiles": {},
        }
        if self.execution_context_fingerprint:
            data["execution_context_fingerprint"] = self.execution_context_fingerprint
        return data

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            self.logger.info("未发现本日检查点，将从第一个步骤开始：%s", self.path)
            return self._new_data()
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ControllerError(f"检查点文件无法读取或不是有效 JSON：{self.path}；{exc}") from exc
        if not isinstance(data, dict):
            raise ControllerError(f"检查点顶层必须是 JSON 对象：{self.path}")
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ControllerError(
                f"检查点版本不兼容：{self.path}；当前={self.SCHEMA_VERSION}，"
                f"文件={data.get('schema_version')}"
            )
        if data.get("scope") != self.scope:
            if self.require_scope_match:
                raise ControllerError(
                    f"每日检查点日期不一致，保留原文件并停止：path={self.path}；"
                    f"file_scope={data.get('scope')}；business_date={self.scope}"
                )
            self.logger.info(
                "检查点 scope 不同，忽略旧状态并创建新状态：path=%s file_scope=%s current_scope=%s",
                self.path,
                data.get("scope"),
                self.scope,
            )
            return self._new_data()
        stored_context_fingerprint = str(
            data.get("execution_context_fingerprint") or ""
        ).strip()
        if (
            self.execution_context_fingerprint
            and stored_context_fingerprint
            and stored_context_fingerprint != self.execution_context_fingerprint
        ):
            self.logger.warning(
                "检查点执行上下文已变化，创建新状态：path=%s file=%s current=%s",
                self.path,
                stored_context_fingerprint,
                self.execution_context_fingerprint,
            )
            return self._new_data()
        stored_fingerprint = str(data.get("config_fingerprint") or "").strip()
        if stored_fingerprint and stored_fingerprint != self.config_fingerprint:
            self.logger.warning(
                "检查点配置指纹已变化，保留步骤级成功状态并按步骤键兼容续跑："
                "path=%s file=%s current=%s",
                self.path,
                stored_fingerprint,
                self.config_fingerprint,
            )
            data["previous_config_fingerprint"] = stored_fingerprint
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            raise ControllerError(f"检查点 profiles 必须是 JSON 对象：{self.path}")
        data["config_fingerprint"] = self.config_fingerprint
        if self.execution_context_fingerprint:
            data["execution_context_fingerprint"] = self.execution_context_fingerprint
        self.logger.info(
            "已加载可恢复检查点：path=%s profile_count=%s",
            self.path,
            len(profiles),
        )
        return data

    def _profile_entry(
        self,
        profile_name: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        profiles = self.data.setdefault("profiles", {})
        entry = profiles.get(profile_name)
        signature = self.profile_signature(metadata)
        if not isinstance(entry, dict):
            entry = {
                "platform": metadata["platform"],
                "company": metadata["company"],
                "shop": metadata["shop"],
                "profile_signature": signature,
                "steps": {},
            }
            profiles[profile_name] = entry
            return entry
        old_signature = str(entry.get("profile_signature") or "").strip()
        if old_signature and old_signature != signature:
            self.logger.warning(
                "profile note 已变化，清除该 profile 的旧步骤检查点：profile=%s",
                profile_name,
            )
            entry = {
                "platform": metadata["platform"],
                "company": metadata["company"],
                "shop": metadata["shop"],
                "profile_signature": signature,
                "steps": {},
            }
            profiles[profile_name] = entry
            return entry
        entry["platform"] = metadata["platform"]
        entry["company"] = metadata["company"]
        entry["shop"] = metadata["shop"]
        entry["profile_signature"] = signature
        if not isinstance(entry.get("steps"), dict):
            entry["steps"] = {}
        return entry

    def prepare_profile(self, profile_name: str, metadata: dict[str, str]) -> None:
        self._profile_entry(profile_name, metadata)
        self._persist()

    def successful_step(
        self,
        profile_name: str,
        metadata: dict[str, str],
        step: dict[str, Any],
    ) -> dict[str, Any] | None:
        entry = self._profile_entry(profile_name, metadata)
        record = entry["steps"].get(self.step_key(step))
        if isinstance(record, dict) and record.get("status") == "success":
            return record
        return None

    def record_success(
        self,
        profile_name: str,
        metadata: dict[str, str],
        step: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        entry = self._profile_entry(profile_name, metadata)
        entry["steps"][self.step_key(step)] = {
            "name": str(step.get("name", "")).strip(),
            "module": str(step.get("module", "")).strip(),
            "args": [str(item) for item in step.get("args", [])],
            "status": "success",
            "execution_lane": result.get("execution_lane"),
            "return_code": result.get("return_code", 0),
            "started_at": result.get("started_at"),
            "finished_at": result.get("finished_at") or local_timestamp(),
            "duration_seconds": result.get("duration_seconds"),
            "recorded_at": local_timestamp(),
        }
        entry["last_success_at"] = local_timestamp()
        self._persist()

    def record_failure(
        self,
        profile_name: str,
        metadata: dict[str, str],
        step: dict[str, Any],
        error: Any,
        *,
        execution_lane: str | None = None,
    ) -> None:
        entry = self._profile_entry(profile_name, metadata)
        entry["last_failure"] = {
            "name": str(step.get("name", "")).strip(),
            "module": str(step.get("module", "")).strip(),
            "args": [str(item) for item in step.get("args", [])],
            "status": "failed",
            "execution_lane": execution_lane,
            "error": redact(error),
            "recorded_at": local_timestamp(),
        }
        self._persist()

    def _persist(self) -> None:
        self.data["updated_at"] = local_timestamp()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(
            f"{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            temporary_path.replace(self.path)
        except OSError as exc:
            raise ControllerError(f"检查点写入失败：{self.path}；{exc}") from exc
        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


class ControllerRunLock:
    """跨进程互斥锁，防止凌晨与上午总控同时改写同一检查点。"""

    def __init__(
        self,
        *,
        path: Path,
        wait_seconds: int,
        run_id: str,
        execution_lane: str,
        logger: logging.Logger,
    ) -> None:
        if wait_seconds < 0:
            raise ControllerError("总控互斥锁等待秒数不能小于 0")
        self.path = path
        self.wait_seconds = wait_seconds
        self.run_id = run_id
        self.execution_lane = execution_lane
        self.logger = logger
        self.handle: Any = None
        self.acquired = False

    def _try_lock(self) -> None:
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl

        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)

    def _owner_text(self) -> str:
        try:
            self.handle.seek(0)
            return redact(self.handle.read(2000).strip()) or "<unknown>"
        except OSError:
            return "<locked>"

    def acquire(self) -> None:
        if self.acquired:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor: int | None = None
        try:
            file_descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT)
            self.handle = os.fdopen(file_descriptor, "r+", encoding="utf-8")
            file_descriptor = None
            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(" ")
                self.handle.flush()
        except OSError as exc:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            elif file_descriptor is not None:
                os.close(file_descriptor)
            raise ControllerError(f"总控互斥锁文件无法打开：{self.path}；{exc}") from exc

        deadline = time.monotonic() + self.wait_seconds
        next_wait_log_at = 0.0
        while True:
            try:
                self._try_lock()
                break
            except OSError as exc:
                now = time.monotonic()
                if now >= deadline:
                    owner = self._owner_text()
                    self.handle.close()
                    self.handle = None
                    raise ControllerError(
                        f"已有另一个总控实例正在运行，未获取互斥锁：{self.path}；"
                        f"wait_seconds={self.wait_seconds}；owner={owner}"
                    ) from exc
                if now >= next_wait_log_at:
                    self.logger.info(
                        "等待另一个总控实例结束：lane=%s remaining_seconds=%s lock=%s",
                        self.execution_lane,
                        max(0, round(deadline - now)),
                        self.path,
                    )
                    next_wait_log_at = now + 30
                time.sleep(min(5.0, max(0.1, deadline - now)))

        self.acquired = True
        owner = json.dumps(
            {
                "pid": os.getpid(),
                "run_id": self.run_id,
                "execution_lane": self.execution_lane,
                "acquired_at": local_timestamp(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.handle.seek(0)
        self.handle.write(owner)
        self.handle.truncate()
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.logger.info(
            "已获取总控互斥锁：lane=%s lock=%s",
            self.execution_lane,
            self.path,
        )

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if self.acquired:
                self._unlock()
                self.logger.info(
                    "已释放总控互斥锁：lane=%s lock=%s",
                    self.execution_lane,
                    self.path,
                )
        except OSError as exc:
            self.logger.error("释放总控互斥锁失败：lock=%s error=%s", self.path, exc)
        finally:
            self.acquired = False
            self.handle.close()
            self.handle = None


class DownloadController:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        config_path: Path,
        destination: Path,
        logger: logging.Logger,
        run_id: str,
        summary_path: Path,
        mcp_url: str,
        checkpoint_scope: str | None = None,
        execution_lane: str = EXECUTION_LANE_ALL,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
        business_date: date | None = None,
        require_daily_checkpoint: bool = False,
        trigger_type: str = "manual",
        exclude_platform: str | None = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.destination = destination
        self.logger = logger
        self.run_id = run_id
        self.summary_path = summary_path
        self.execution_lane = str(execution_lane).strip().lower() or EXECUTION_LANE_ALL
        self.event_sink = event_sink
        self.trigger_type = trigger_type
        self.exclude_platform = exclude_platform
        from scripts.auto_download.ledger import RunJournal
        self.journal = RunJournal(destination, run_id, self.execution_lane,
                                  external=event_sink is None, trigger_type=trigger_type)
        self.receipt_file = None
        if self.execution_lane not in SUPPORTED_EXECUTION_LANES | {EXECUTION_LANE_ALL}:
            raise ControllerError(
                f"未知执行通道：{self.execution_lane}；允许值="
                f"{EXECUTION_LANE_ALL}, {', '.join(sorted(SUPPORTED_EXECUTION_LANES))}"
            )
        self.client = CloakMcpClient(mcp_url, logger)
        self.python_executable = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        self.started_profile_ids: list[tuple[str, str]] = []
        # 只记录“该 profile 的全部步骤已成功完成、允许关闭”的 profile。
        # 总控中断时不得根据 started_profile_ids 关闭未完成的 profile。
        self.profiles_ready_to_close: list[tuple[str, str]] = []
        self.business_date = business_date or china_now().date()
        daily_scope = self.business_date.isoformat()
        self.checkpoint_scope = (
            str(checkpoint_scope or daily_scope).strip() or daily_scope
        )
        if require_daily_checkpoint and self.checkpoint_scope != daily_scope:
            raise ControllerError(
                f"每日任务检查点日期与业务日期不一致："
                f"checkpoint_scope={self.checkpoint_scope}；business_date={daily_scope}"
            )
        checkpoint_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.checkpoint_scope)
        raw_checkpoint_file = config.get("checkpoint_file")
        if raw_checkpoint_file:
            checkpoint_path = resolve_path(str(raw_checkpoint_file), base=PROJECT_ROOT)
        else:
            raw_checkpoint_directory = config.get("checkpoint_directory")
            checkpoint_directory = (
                resolve_path(str(raw_checkpoint_directory), base=PROJECT_ROOT)
                if raw_checkpoint_directory
                else summary_path.parent / "checkpoints"
            )
            checkpoint_path = checkpoint_directory / f"checkpoint_{checkpoint_slug}.json"
        if require_daily_checkpoint:
            named_date = re.fullmatch(r"checkpoint_(\d{4}-\d{2}-\d{2})\.json", checkpoint_path.name)
            if named_date and named_date.group(1) != daily_scope:
                raise ControllerError(
                    f"每日任务检查点路径日期不一致：path={checkpoint_path}；"
                    f"business_date={daily_scope}"
                )
        config_fingerprint = hashlib.sha256(
            json.dumps(
                config,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        execution_context_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "project_root": str(PROJECT_ROOT.resolve()),
                    "destination": str(destination.resolve()),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.checkpoint = ResumeCheckpoint(
            path=checkpoint_path,
            scope=self.checkpoint_scope,
            config_fingerprint=config_fingerprint,
            logger=logger,
            execution_context_fingerprint=execution_context_fingerprint,
            require_scope_match=require_daily_checkpoint,
        )
        self.summary: dict[str, Any] = {
            "run_id": run_id,
            "status": "running",
            "started_at": local_timestamp(),
            "business_date": daily_scope,
            "business_timezone": CHINA_TIME_ZONE,
            "trigger_type": trigger_type,
            "config": str(config_path),
            "destination": str(destination),
            "execution_lane": self.execution_lane,
            "platform_filter": {"exclude_platform": self.exclude_platform},
            "profiles": [],
            "warnings": [],
            "cleanup_errors": [],
            "checkpoint": {
                "path": str(checkpoint_path),
                "scope": self.checkpoint_scope,
                "config_fingerprint": config_fingerprint,
                "execution_context_fingerprint": execution_context_fingerprint,
                "resumed_profile_count": len(self.checkpoint.data.get("profiles", {})),
            },
        }

    def _emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        journal = getattr(self, "journal", None)
        if journal is not None:
            journal.emit(event, dict(payload or {}))
            if journal.data['external'] and event in {
                'step_started', 'step_downloaded', 'step_succeeded', 'step_failed', 'completed',
            }:
                self._sync_external_journal()
        event_sink = getattr(self, "event_sink", None)
        if event_sink is None:
            return
        event_sink(event, dict(payload or {}))

    def _sync_external_journal(self) -> None:
        """Best-effort live projection; the durable journal also supports catch-up."""
        if time.monotonic() < getattr(self, '_journal_retry_at', 0):
            return
        try:
            from scripts.auto_download.report_calendar_admin import service_from_env
            service = service_from_env(self.destination)
            # Bound a disconnected database; never delay each subsequent event.
            service.file_ingest.connect_kwargs['connect_timeout'] = 3
            service.sync_report_journals(journal_key=self.run_id)
        except Exception:
            self._journal_retry_at = time.monotonic() + 30
            self.logger.warning('执行台账暂未同步；本地事件已保存，后续自动补同步')

    def _artifact_snapshot(self) -> dict[str, tuple[int, int]]:
        if not self.destination.exists():
            return {}
        snapshot: dict[str, tuple[int, int]] = {}
        ignored_suffixes = {".crdownload", ".part", ".tmp", ".download"}
        artifact_suffixes = {".csv", ".xls", ".xlsx", ".xlsm", ".zip"}
        for path in self.destination.rglob("*"):
            if (
                not path.is_file()
                or any(part.startswith(".automation_") for part in path.parts)
                or path.suffix.lower() in ignored_suffixes
                or path.suffix.lower() not in artifact_suffixes
            ):
                continue
            try:
                stat = path.stat()
                relative = path.relative_to(self.destination).as_posix()
            except OSError:
                continue
            snapshot[relative] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    def _collect_artifacts(self, before: dict[str, tuple[int, int]]) -> list[dict[str, Any]]:
        from scripts.auto_download.ledger import read_receipts
        receipt = getattr(self, "receipt_file", None)
        if receipt is not None and receipt.is_file():
            return read_receipts(receipt)
        after = self._artifact_snapshot()
        artifacts: list[dict[str, Any]] = []
        for relative, state in after.items():
            if before.get(relative) == state:
                continue
            path = self.destination / Path(relative)
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            artifacts.append({
                "artifact_type": "archive" if path.suffix.lower() == ".zip" else "report_file",
                "file_name": path.name,
                "relative_path": relative,
                "file_size_bytes": state[0],
                "file_hash": digest.hexdigest(),
            })
        return artifacts

    def run(self) -> int:
        if self.event_sink is None:
            from scripts.auto_download.ingest_api import validate_ingest_credentials
            validate_ingest_credentials('manual' if self.trigger_type == 'manual' else 'api')
        self._emit("run_started", {"run_id": self.run_id, "execution_lane": self.execution_lane})
        self.logger.info(
            "总控启动：run_id=%s lane=%s project_root=%s config=%s destination=%s",
            self.run_id,
            self.execution_lane,
            PROJECT_ROOT,
            self.config_path,
            self.destination,
        )
        if not self.python_executable.is_file():
            raise ControllerError(f"项目虚拟环境解释器不存在：{self.python_executable}")

        self.client.initialize()
        self.client.load_tools()
        all_profiles = as_list(self.client.call("list_profiles", {}), label="list_profiles")
        self.logger.info("Cloak Login profile 清单读取完成：数量=%s", len(all_profiles))

        try:
            if isinstance(self.config.get("profile_rules"), list):
                plans = self._materialize_profile_plans(all_profiles)
                self.logger.info(
                    "动态 profile 计划生成完成：纳入=%s，执行顺序=规则顺序内按 profile 名称排序",
                    len(plans),
                )
            else:
                plans = self.config["profiles"]

            self.summary["plan_count"] = len(plans)
            from scripts.auto_download.ledger import atomic_json
            inventory = [{"profile_name": plan.get("profile_name"),
                          "profile_id": plan.get("_profile_id"),
                          "metadata": plan.get("_metadata") or {}, "steps": plan.get("steps") or []}
                         for plan in plans if plan.get("enabled", True)]
            if isinstance(self.config.get("profile_rules"), list):
                atomic_json(self.destination / ".automation_logs" / "report_ledger" / "inventory.json",
                            {"targets": inventory, "updated_at": local_timestamp(),
                             "disabled": (self.summary.get("profile_inventory") or {}).get("disabled_profiles", [])})
            self._emit("plan", {"targets": inventory})
            lane_plan_count = 0
            for index, plan in enumerate(plans, start=1):
                if not isinstance(plan, dict):
                    raise ControllerError(f"profiles[{index - 1}] 必须是 JSON 对象")
                if plan.get("enabled", True) is False:
                    self.logger.info("跳过禁用的 profile 计划：index=%s", index)
                    continue
                selected_plan = self._select_plan_for_lane(index, plan)
                if selected_plan is None:
                    metadata = plan.get("_metadata")
                    skipped_record: dict[str, Any] = {
                        "profile": str(plan.get("profile_name", "")).strip(),
                        "platform": str(plan.get("platform", "")).strip(),
                        "status": "skipped_lane",
                        "execution_lane": self.execution_lane,
                        "reason": "当前执行通道或平台筛选没有匹配步骤",
                    }
                    if isinstance(metadata, dict):
                        skipped_record.update(
                            {
                                key: metadata.get(key)
                                for key in ("company", "shop")
                                if metadata.get(key)
                            }
                        )
                    self.summary["profiles"].append(skipped_record)
                    continue
                lane_plan_count += 1
                self._run_profile_plan(index, selected_plan, all_profiles)
            self.summary["lane_plan_count"] = lane_plan_count
        finally:
            # 这里只补偿重试已经完成、但首次关闭失败的 profile。
            # 未完成 profile 保留现场，供人工接管或下一次任务继续。
            self._cleanup_completed_profiles()

        if self.summary["cleanup_errors"]:
            self.summary["status"] = "failed"
            self._emit("run_finished", {"status": "failed", "summary": self.summary})
            return 1
        if self.summary["warnings"]:
            self.summary["status"] = "success_with_warnings"
        else:
            self.summary["status"] = "success"
        self._emit("run_finished", {"status": self.summary["status"], "summary": self.summary})
        return 0

    def _select_plan_for_lane(
        self,
        index: int,
        plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        """先筛选平台，再返回当前通道应执行的步骤。"""

        metadata = plan.get("_metadata") or {}
        platform = metadata.get("platform") or plan.get("platform")
        excluded = getattr(self, "exclude_platform", None)
        if excluded and platform == excluded:
            self.logger.info(
                "平台筛选跳过且不启动 profile：platform=%s profile=%s",
                platform, plan.get("profile_name"),
            )
            return None

        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ControllerError(f"profiles[{index - 1}] 的 steps 必须是非空数组")
        selected_steps: list[dict[str, Any]] = []
        omitted_names: list[str] = []
        for step_index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ControllerError(
                    f"profiles[{index - 1}].steps[{step_index - 1}] 必须是 JSON 对象"
                )
            lanes = step_execution_lanes(
                step,
                label=f"profiles[{index - 1}].steps[{step_index - 1}]",
            )
            if (
                self.execution_lane == EXECUTION_LANE_ALL
                or lanes is None
                or self.execution_lane in lanes
            ):
                selected_step = dict(step)
                selected_step["_source_step_index"] = step_index
                selected_steps.append(selected_step)
            else:
                omitted_names.append(
                    str(step.get("name", "")).strip() or f"step-{step_index}"
                )

        profile_name = str(plan.get("profile_name", "")).strip() or f"index-{index}"
        if not selected_steps:
            self.logger.info(
                "当前通道无步骤，跳过且不启动 profile：lane=%s profile=%s omitted=%s",
                self.execution_lane,
                profile_name,
                ", ".join(omitted_names) or "<none>",
            )
            return None
        selected_plan = dict(plan)
        selected_plan["steps"] = selected_steps
        if omitted_names:
            self.logger.info(
                "已按执行通道筛选步骤：lane=%s profile=%s selected=%s omitted=%s",
                self.execution_lane,
                profile_name,
                len(selected_steps),
                ", ".join(omitted_names),
            )
        return selected_plan

    def _materialize_profile_plans(self, all_profiles: list[Any]) -> list[dict[str, Any]]:
        """按命名规则盘点所有 profile，并为每个 profile 生成一份下载计划。

        配置只描述平台级报表步骤，店铺数量和 profile 名称全部来自
        Cloak Login 的实时清单。这样同一平台新增店铺后无需再改总控 JSON。
        """

        raw_rules = self.config.get("profile_rules")
        if not isinstance(raw_rules, list) or not raw_rules:
            raise ControllerError("profile_rules 必须是非空数组")

        compiled_rules: list[dict[str, Any]] = []
        derived_managed_prefixes: set[str] = set()
        for rule_index, rule in enumerate(raw_rules, start=1):
            if not isinstance(rule, dict):
                raise ControllerError(f"profile_rules[{rule_index - 1}] 必须是 JSON 对象")
            rule_name = str(rule.get("name", "")).strip() or f"rule-{rule_index}"
            platform = str(rule.get("platform", "")).strip()
            if platform not in SUPPORTED_PLATFORMS:
                raise ControllerError(
                    f"profile_rules[{rule_index - 1}] 平台无效：{platform or '<empty>'}"
                )
            steps = rule.get("steps")
            if not isinstance(steps, list) or not steps:
                raise ControllerError(f"profile_rules[{rule_index - 1}] 的 steps 必须是非空数组")

            prefixes = rule.get("profile_name_prefixes", [])
            if not isinstance(prefixes, list) or any(
                not isinstance(prefix, str) or not prefix.strip() for prefix in prefixes
            ):
                raise ControllerError(
                    f"profile_rules[{rule_index - 1}].profile_name_prefixes 必须是非空字符串数组"
                )
            prefixes = [prefix.strip() for prefix in prefixes]

            regex_text = str(rule.get("profile_name_regex", "")).strip()
            if not prefixes and not regex_text:
                raise ControllerError(
                    f"profile_rules[{rule_index - 1}] 必须配置 profile_name_prefixes 或 "
                    "profile_name_regex"
                )
            try:
                name_regex = re.compile(regex_text) if regex_text else None
            except re.error as exc:
                raise ControllerError(
                    f"profile_rules[{rule_index - 1}].profile_name_regex 无效：{exc}"
                ) from exc

            excluded_suffixes = rule.get("exclude_profile_name_suffixes", [])
            if not isinstance(excluded_suffixes, list) or any(
                not isinstance(suffix, str) or not suffix.strip()
                for suffix in excluded_suffixes
            ):
                raise ControllerError(
                    f"profile_rules[{rule_index - 1}].exclude_profile_name_suffixes "
                    "必须是字符串数组"
                )
            excluded_suffixes = [suffix.strip() for suffix in excluded_suffixes]
            derived_managed_prefixes.update(prefixes)
            compiled_rules.append(
                {
                    "index": rule_index,
                    "name": rule_name,
                    "platform": platform,
                    "steps": steps,
                    "prefixes": prefixes,
                    "regex": name_regex,
                    "excluded_suffixes": excluded_suffixes,
                    "fallback_for_platform": bool(
                        rule.get("match_all_profiles_with_platform", False)
                    ),
                    "rule": rule,
                }
            )

        managed_prefixes = self.config.get("managed_profile_name_prefixes")
        if managed_prefixes is None:
            managed_prefixes = sorted(derived_managed_prefixes)
        if not isinstance(managed_prefixes, list) or any(
            not isinstance(prefix, str) or not prefix.strip() for prefix in managed_prefixes
        ):
            raise ControllerError("managed_profile_name_prefixes 必须是字符串数组")
        managed_prefixes = [prefix.strip() for prefix in managed_prefixes]
        strict_coverage = bool(self.config.get("strict_profile_coverage", True))
        profile_status = self.config.get("profile_status", {})
        if not isinstance(profile_status, dict):
            raise ControllerError("总控配置 profile_status 必须是 JSON 对象")
        strict_profile_status = bool(self.config.get("strict_profile_status", True))

        plans: list[dict[str, Any]] = []
        assigned_names: set[str] = set()
        seen_status_names: set[str] = set()
        unmatched_managed: list[str] = []
        unmanaged_names: list[str] = []
        disabled_profiles: list[dict[str, str]] = []
        rule_counts = {rule["index"]: 0 for rule in compiled_rules}

        for inventory_index, profile in enumerate(all_profiles, start=1):
            if not isinstance(profile, dict):
                raise ControllerError(f"list_profiles[{inventory_index - 1}] 不是 JSON 对象")
            profile_name = str(first_value(profile, "name", "profileName") or "").strip()
            if not profile_name:
                raise ControllerError(f"list_profiles[{inventory_index - 1}] 缺少 profile 名称")
            if profile_name in assigned_names:
                raise ControllerError(f"Cloak Login 返回重复的 profile 名称：{profile_name}")
            assigned_names.add(profile_name)

            status_config = profile_status.get(profile_name)
            if status_config is not None:
                seen_status_names.add(profile_name)
                status = str(status_config.get("status", "active")).strip() or "active"
                enabled = bool(status_config.get("enabled", True))
                normalized_status = status.casefold()
                is_enabled = enabled and normalized_status in {
                    value.casefold() for value in ACTIVE_PROFILE_STATUS_VALUES
                }
                if not is_enabled:
                    reason = str(status_config.get("reason", "")).strip()
                    disabled_record = {
                        "profile": profile_name,
                        "status": "disabled",
                        "profile_status": status,
                        "reason": reason or "profile_status 未启用",
                    }
                    disabled_profiles.append(disabled_record)
                    self.summary["profiles"].append(disabled_record)
                    self.logger.info(
                        "按 profile_status 跳过，不启动、不执行任何下载：profile=%s "
                        "status=%s enabled=%s reason=%s",
                        profile_name,
                        status,
                        enabled,
                        reason or "profile_status 未启用",
                    )
                    continue

            matching_rules = [
                rule
                for rule in compiled_rules
                if self._profile_name_matches_rule(profile_name, rule)
            ]
            if len(matching_rules) > 1:
                names = ", ".join(rule["name"] for rule in matching_rules)
                raise ControllerError(f"profile 同时匹配多个总控规则：{profile_name} -> {names}")
            profile_id = str(first_value(profile, "id", "profileId") or "").strip()
            if not profile_id:
                if matching_rules or any(
                    profile_name.startswith(prefix) for prefix in managed_prefixes
                ):
                    raise ControllerError(f"profile 缺少 id：{profile_name}")
                unmanaged_names.append(profile_name)
                continue

            details = self.client.call("get_profile", {"id": profile_id})
            details = details if isinstance(details, dict) else {}
            note = first_value(details, "note") or first_value(profile, "note")
            try:
                metadata = parse_profile_note(note, profile_name)
            except ControllerError:
                if matching_rules or any(
                    profile_name.startswith(prefix) for prefix in managed_prefixes
                ):
                    raise
                self.logger.info(
                    "profile 没有可解析的业务 note，作为非报表 profile 忽略：%s",
                    profile_name,
                )
                unmanaged_names.append(profile_name)
                continue

            selection_mode = "profile_name"
            if not matching_rules:
                fallback_rules = [
                    rule
                    for rule in compiled_rules
                    if rule["fallback_for_platform"]
                    and rule["platform"] == metadata["platform"]
                    and not any(
                        profile_name.endswith(suffix)
                        for suffix in rule["excluded_suffixes"]
                    )
                ]
                if len(fallback_rules) > 1:
                    names = ", ".join(rule["name"] for rule in fallback_rules)
                    raise ControllerError(
                        f"profile note 平台匹配多个兜底规则：{profile_name} -> {names}"
                    )
                if not fallback_rules:
                    if any(
                        profile_name.startswith(prefix) for prefix in managed_prefixes
                    ):
                        unmatched_managed.append(profile_name)
                    else:
                        unmanaged_names.append(profile_name)
                    continue
                matching_rules = fallback_rules
                selection_mode = "profile_note"

            rule = matching_rules[0]
            if metadata["platform"] != rule["platform"]:
                raise ControllerError(
                    f"profile note 平台与总控规则不一致：profile={profile_name}，"
                    f"规则={rule['name']}({rule['platform']})，note={metadata['platform']}"
                )

            rule_counts[rule["index"]] += 1
            plans.append(
                {
                    "platform": rule["platform"],
                    "profile_name": profile_name,
                    "required": True,
                    "steps": rule["steps"],
                    "_profile": profile,
                    "_profile_id": profile_id,
                    "_metadata": metadata,
                    "_rule_index": rule["index"],
                    "_selection_mode": selection_mode,
                }
            )

        if unmatched_managed:
            names = ", ".join(sorted(unmatched_managed))
            message = f"总控管理范围内 profile 未匹配任何规则：{names}"
            if strict_coverage:
                raise ControllerError(message)
            self.logger.warning(message)
            self.summary["warnings"].append(message)

        unknown_status_names = sorted(set(profile_status) - seen_status_names)
        if unknown_status_names:
            message = (
                "profile_status 中的 profile 不存在于 Cloak Login 清单："
                + ", ".join(unknown_status_names)
            )
            if strict_profile_status:
                raise ControllerError(message)
            self.logger.warning(message)
            self.summary["warnings"].append(message)

        validate_profile_companies(plans)
        plans.sort(key=lambda plan: (plan["_rule_index"], plan["profile_name"]))
        self.summary["profile_inventory"] = {
            "total_profiles": len(all_profiles),
            "selected_profiles": len(plans),
            "disabled_profiles": disabled_profiles,
            "unmanaged_profiles": sorted(unmanaged_names),
            "unmatched_managed_profiles": sorted(unmatched_managed),
            "rule_counts": {
                next(rule["name"] for rule in compiled_rules if rule["index"] == index): count
                for index, count in rule_counts.items()
            },
        }
        if unmanaged_names:
            self.logger.info(
                "发现未纳入报表总控命名范围的 profile（不执行下载）：数量=%s names=%s",
                len(unmanaged_names),
                ", ".join(sorted(unmanaged_names)),
            )
        for rule in compiled_rules:
            if rule_counts[rule["index"]] == 0:
                self.logger.info("规则当前没有匹配 profile：%s", rule["name"])
        if not plans and not disabled_profiles:
            raise ControllerError("Cloak Login 清单中没有匹配总控规则的 profile")
        self.logger.info(
            "所有纳入总控范围的 profile 均已生成计划：数量=%s names=%s",
            len(plans),
            ", ".join(plan["profile_name"] for plan in plans),
        )
        return plans

    @staticmethod
    def _profile_name_matches_rule(profile_name: str, rule: dict[str, Any]) -> bool:
        regex = rule["regex"]
        prefix_match = any(profile_name.startswith(prefix) for prefix in rule["prefixes"])
        regex_match = bool(regex and regex.fullmatch(profile_name))
        if not (prefix_match or regex_match):
            return False
        return not any(
            profile_name.endswith(suffix) for suffix in rule["excluded_suffixes"]
        )

    def _checkpoint_step_result(
        self,
        *,
        step_index: int,
        step: dict[str, Any],
        checkpoint_record: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "name": str(step.get("name", "")).strip() or f"step-{step_index}",
            "module": str(step.get("module", "")).strip(),
            "status": "skipped_checkpoint",
            "execution_lane": self.execution_lane,
            "completed_in_lane": checkpoint_record.get("execution_lane"),
            "return_code": 0,
            "started_at": checkpoint_record.get("started_at"),
            "finished_at": checkpoint_record.get("finished_at"),
            "duration_seconds": checkpoint_record.get("duration_seconds"),
            "checkpoint_recorded_at": checkpoint_record.get("recorded_at"),
        }

    def _emit_checkpoint_step(
        self,
        *,
        profile_name: str,
        metadata: dict[str, str],
        step_index: int,
        step: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        payload = {
            "profile_name": profile_name,
            "metadata": dict(metadata),
            "step_index": step_index,
            "step_name": result["name"],
            "module_name": result["module"],
            "args": list(step.get("args") or []),
            "execution_lane": self.execution_lane,
            "started_at": result.get("started_at"),
            "checkpoint_reused": True,
        }
        self._emit("step_started", payload)
        self._emit("step_succeeded", {**payload, **result, "status": "skipped", "artifacts": []})

    def _close_profile_if_active(self, profile_id: str, profile_name: str) -> None:
        """检查点已全完成时只关闭残留实例，不为跳过步骤重新启动 profile。"""

        active = as_list(self.client.call("list_active", {}), label="list_active")
        is_active = any(
            isinstance(item, dict)
            and str(first_value(item, "id", "profileId") or "") == profile_id
            for item in active
        )
        if not is_active:
            self.logger.info(
                "检查点已覆盖当前通道全部步骤，profile 未运行，无需启动：profile=%s lane=%s",
                profile_name,
                self.execution_lane,
            )
            return
        self.logger.info(
            "检查点已覆盖当前通道全部步骤，关闭残留运行实例：profile=%s lane=%s",
            profile_name,
            self.execution_lane,
        )
        self._queue_profile_for_close(profile_id, profile_name)
        self._stop_profile(profile_id, profile_name)

    def _run_profile_plan(
        self,
        index: int,
        plan: dict[str, Any],
        all_profiles: list[Any],
    ) -> None:
        profile_name = str(plan.get("profile_name", "")).strip()
        if not profile_name:
            raise ControllerError(f"profiles[{index - 1}].profile_name 不能为空")
        required = bool(plan.get("required", True))
        expected_platform = str(plan.get("platform", "")).strip()
        internal_profile = plan.get("_profile")
        if isinstance(internal_profile, dict):
            match = [internal_profile]
        else:
            match = [
                profile
                for profile in all_profiles
                if isinstance(profile, dict)
                and str(first_value(profile, "name", "profileName") or "") == profile_name
            ]
        if not match:
            message = f"未找到 profile：{profile_name}"
            if not required:
                self.logger.warning("可选 profile 不存在，跳过：%s", profile_name)
                self.summary["warnings"].append(message)
                self.summary["profiles"].append(
                    {"profile": profile_name, "status": "skipped", "reason": message}
                )
                return
            raise ControllerError(message)
        if len(match) > 1:
            raise ControllerError(f"profile 名称不唯一：{profile_name}")

        profile = match[0]
        if plan.get("expected_profile_id") and str(first_value(profile, "id", "profileId") or "") != plan["expected_profile_id"]:
            raise ControllerError(f"补跑Profile标识已改变：{profile_name}；请重新选择店铺创建计划")
        profile_id = str(
            plan.get("_profile_id") or first_value(profile, "id", "profileId") or ""
        ).strip()
        if not profile_id:
            raise ControllerError(f"profile 缺少 id：{profile_name}")
        internal_metadata = plan.get("_metadata")
        if isinstance(internal_metadata, dict) and all(
            isinstance(internal_metadata.get(key), str)
            for key in ("platform", "company", "shop")
        ):
            metadata = dict(internal_metadata)
        else:
            details = self.client.call("get_profile", {"id": profile_id})
            details = details if isinstance(details, dict) else {}
            note = first_value(details, "note") or first_value(profile, "note")
            metadata = parse_profile_note(note, profile_name)
        if plan.get("expected_metadata") and metadata != plan["expected_metadata"]:
            raise ControllerError(f"补跑Profile业务归属已改变：{profile_name}；请核对标准店铺后重新创建计划")
        if expected_platform and metadata["platform"] != expected_platform:
            raise ControllerError(
                f"profile note 平台与配置不一致：profile={profile_name}，"
                f"配置={expected_platform}，note={metadata['platform']}"
            )
        self.checkpoint.prepare_profile(profile_name, metadata)

        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ControllerError(f"profile {profile_name} 的 steps 必须是非空数组")
        step_states: list[tuple[int, dict[str, Any], dict[str, Any] | None]] = []
        for selected_step_index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ControllerError(
                    f"profile {profile_name} 的 steps[{selected_step_index - 1}] "
                    "必须是 JSON 对象"
                )
            source_step_index = int(step.get("_source_step_index", selected_step_index))
            if step.get("enabled", True) is False:
                self.logger.info(
                    "跳过禁用步骤：profile=%s step=%s",
                    profile_name,
                    source_step_index,
                )
                continue
            checkpoint_record = self.checkpoint.successful_step(
                profile_name,
                metadata,
                step,
            )
            step_states.append((source_step_index, step, checkpoint_record))

        profile_summary: dict[str, Any] = {
            "profile": profile_name,
            "platform": metadata["platform"],
            "company": metadata["company"],
            "shop": metadata["shop"],
            "selection_mode": plan.get("_selection_mode", "profile_name"),
            "execution_lane": self.execution_lane,
            "status": "running",
            "steps": [],
        }
        self.summary["profiles"].append(profile_summary)
        self._emit("profile_started", {
            "profile_name": profile_name,
            "metadata": metadata,
            "execution_lane": self.execution_lane,
        })
        self.logger.info(
            "profile[%s] 元数据确认：profile=%s platform=%s company=%s shop=%s status=%s",
            index,
            profile_name,
            metadata["platform"],
            metadata["company"],
            metadata["shop"],
            first_value(profile, "status") or "unknown",
        )

        if step_states and all(record is not None for _, _, record in step_states):
            for step_index, step, checkpoint_record in step_states:
                assert checkpoint_record is not None
                checkpoint_step_result = self._checkpoint_step_result(
                    step_index=step_index,
                    step=step,
                    checkpoint_record=checkpoint_record,
                )
                profile_summary["steps"].append(checkpoint_step_result)
                self._emit_checkpoint_step(
                    profile_name=profile_name, metadata=metadata, step_index=step_index,
                    step=step, result=checkpoint_step_result,
                )
                self.logger.info(
                    "跳过已成功检查点：profile=%s step=%s name=%s module=%s "
                    "recorded_at=%s completed_in_lane=%s",
                    profile_name,
                    step_index,
                    checkpoint_step_result["name"],
                    checkpoint_step_result["module"],
                    checkpoint_record.get("recorded_at"),
                    checkpoint_record.get("execution_lane") or "legacy",
                )
            profile_summary["checkpoint_only"] = True
            try:
                self._close_profile_if_active(profile_id, profile_name)
            except Exception:
                profile_summary["status"] = "failed"
                raise
            profile_summary["status"] = "success"
            self._emit("profile_finished", {
                "profile_name": profile_name, "metadata": metadata,
                "status": "success", "execution_lane": self.execution_lane,
            })
            self.logger.info(
                "profile 当前通道已由检查点完成：profile=%s lane=%s",
                profile_name,
                self.execution_lane,
            )
            return

        cdp_url, _started_by_controller = self._ensure_profile_running(profile_id, profile_name)
        try:
            for step_index, step, checkpoint_record in step_states:
                if checkpoint_record is not None:
                    checkpoint_step_result = self._checkpoint_step_result(
                        step_index=step_index,
                        step=step,
                        checkpoint_record=checkpoint_record,
                    )
                    profile_summary["steps"].append(checkpoint_step_result)
                    self._emit_checkpoint_step(
                        profile_name=profile_name, metadata=metadata, step_index=step_index,
                        step=step, result=checkpoint_step_result,
                    )
                    self.logger.info(
                        "跳过已成功检查点：profile=%s step=%s name=%s module=%s "
                        "recorded_at=%s completed_in_lane=%s",
                        profile_name,
                        step_index,
                        checkpoint_step_result["name"],
                        checkpoint_step_result["module"],
                        checkpoint_record.get("recorded_at"),
                        checkpoint_record.get("execution_lane") or "legacy",
                    )
                    continue
                try:
                    step_result = self._run_step(
                        profile_name=profile_name,
                        profile_id=profile_id,
                        cdp_url=cdp_url,
                        metadata=metadata,
                        step_index=step_index,
                        step=step,
                    )
                except Exception as exc:
                    try:
                        self.checkpoint.record_failure(
                            profile_name,
                            metadata,
                            step,
                            exc,
                            execution_lane=self.execution_lane,
                        )
                    except Exception as checkpoint_exc:
                        self.logger.exception(
                            "失败步骤检查点写入异常：profile=%s step=%s；%s",
                            profile_name,
                            step_index,
                            redact(checkpoint_exc),
                        )
                    profile_summary["steps"].append(
                        {
                            "name": str(step.get("name", "")).strip() or f"step-{step_index}",
                            "module": str(step.get("module", "")).strip(),
                            "status": "failed",
                            "finished_at": local_timestamp(),
                            "error": redact(exc),
                        }
                    )
                    raise
                else:
                    step_result["status"] = "success"
                    step_result["execution_lane"] = self.execution_lane
                    try:
                        self.checkpoint.record_success(
                            profile_name,
                            metadata,
                            step,
                            step_result,
                        )
                    except Exception as checkpoint_exc:
                        checkpoint_error = ControllerError(
                            f"步骤已完成但检查点写入失败：profile={profile_name} "
                            f"step={step_index}；{redact(checkpoint_exc)}"
                        )
                        profile_summary["steps"].append(
                            {
                                "name": str(step.get("name", "")).strip()
                                or f"step-{step_index}",
                                "module": str(step.get("module", "")).strip(),
                                "status": "failed",
                                "finished_at": local_timestamp(),
                                "error": redact(checkpoint_error),
                            }
                        )
                        self.logger.error(
                            "步骤成功后的检查点写入失败：profile=%s step=%s",
                            profile_name,
                            step_index,
                        )
                        raise checkpoint_error from checkpoint_exc
                    profile_summary["steps"].append(step_result)
            profile_summary["status"] = "success"
            self._emit("profile_finished", {
                "profile_name": profile_name, "metadata": metadata,
                "status": "success", "execution_lane": self.execution_lane,
            })
            self.logger.info(
                "profile 当前通道完成：profile=%s lane=%s",
                profile_name,
                self.execution_lane,
            )
        except Exception:
            profile_summary["status"] = "failed"
            self._emit("profile_finished", {
                "profile_name": profile_name, "metadata": metadata,
                "status": "failed", "execution_lane": self.execution_lane,
            })
            raise
        finally:
            if profile_summary["status"] == "success":
                # 无论 profile 是总控启动还是复用已运行实例，只要本 profile
                # 的全部步骤成功，就必须关闭它。
                self._queue_profile_for_close(profile_id, profile_name)
                self._stop_profile(profile_id, profile_name)
            else:
                # 失败、中断或异常时保留现场；同时从历史启动记录中移除，
                # 防止外层清理逻辑误把未完成 profile 关闭。
                self.started_profile_ids = [
                    item for item in self.started_profile_ids if item[0] != profile_id
                ]
                self.logger.info(
                    "profile 未成功完成，保留失败现场：%s",
                    profile_name,
                )

    def _ensure_profile_running(self, profile_id: str, profile_name: str) -> tuple[str, bool]:
        active = as_list(self.client.call("list_active", {}), label="list_active")
        for item in active:
            if not isinstance(item, dict):
                continue
            item_id = str(first_value(item, "id", "profileId") or "")
            if item_id != profile_id:
                continue
            endpoint = first_value(item, "wsEndpoint", "ws_endpoint")
            if not endpoint:
                endpoint = first_value(
                    self.client.call("get_cdp_endpoint", {"id": profile_id}),
                    "wsEndpoint",
                    "ws_endpoint",
                )
            if not isinstance(endpoint, str) or not endpoint.startswith(("ws://", "wss://")):
                raise ControllerError(f"运行中的 profile 没有有效 CDP 地址：{profile_name}")
            self.logger.info("复用已经运行的 profile：%s，CDP=%s", profile_name, endpoint)
            return endpoint, False

        started = self.client.call("start_profile", {"id": profile_id})
        endpoint = first_value(started, "wsEndpoint", "ws_endpoint")
        if not isinstance(endpoint, str) or not endpoint.startswith(("ws://", "wss://")):
            endpoint = first_value(
                self.client.call("get_cdp_endpoint", {"id": profile_id}),
                "wsEndpoint",
                "ws_endpoint",
            )
        if not isinstance(endpoint, str) or not endpoint.startswith(("ws://", "wss://")):
            raise ControllerError(f"start_profile 未返回有效 CDP 地址：{profile_name}")
        self.started_profile_ids.append((profile_id, profile_name))
        self.logger.info("已启动本次任务需要的 profile：%s，CDP=%s", profile_name, endpoint)
        return endpoint, True

    def _run_step(
        self,
        *,
        profile_name: str,
        profile_id: str,
        cdp_url: str,
        metadata: dict[str, str],
        step_index: int,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        name = str(step.get("name", "")).strip() or f"step-{step_index}"
        module = str(step.get("module", "")).strip()
        if not module or not SUPPORTED_MODULE_PATTERN.fullmatch(module):
            raise ControllerError(f"步骤模块名无效：profile={profile_name} step={name}")
        args = step.get("args", [])
        if not isinstance(args, list) or any(not isinstance(item, (str, int, float)) for item in args):
            raise ControllerError(f"步骤 args 必须是字符串/数字数组：profile={profile_name} step={name}")
        args = [str(item) for item in args]
        reserved = {"--cdp", "--platform", "--company", "--shop", "--dest", "--profile"}
        if reserved.intersection(args):
            raise ControllerError(
                f"步骤不得自行覆盖总控参数 {sorted(reserved)}：profile={profile_name} step={name}"
            )

        command = [
            str(self.python_executable),
            "-m",
            f"scripts.auto_download.playwright.{module}",
            "--cdp",
            cdp_url,
            "--platform",
            metadata["platform"],
            "--company",
            metadata["company"],
            "--shop",
            metadata["shop"],
        ]
        if module in PROFILE_ARGUMENT_MODULES:
            command.extend(["--profile", profile_name])
        command.extend(args)
        if "--dest" not in args:
            command.extend(["--dest", str(self.destination)])

        start = time.perf_counter()
        started_at = local_timestamp()
        before_artifacts = self._artifact_snapshot()
        event_payload = {
            "profile_name": profile_name,
            "metadata": dict(metadata),
            "step_index": step_index,
            "step_name": name,
            "module_name": module,
            "args": list(args),
            "execution_lane": self.execution_lane,
            "started_at": started_at,
        }
        from apps.automation_center.registry import business_period
        from apps.automation_center.report_plan import china_today
        event_payload["business_period"] = business_period(module, args, china_today())
        self._emit("step_started", event_payload)
        display_command = redact(" ".join(command))
        self.logger.info(
            "步骤开始：profile=%s profile_id=%s step=%s name=%s module=%s command=%s",
            profile_name,
            profile_id,
            step_index,
            name,
            module,
            display_command,
        )
        child_env = os.environ.copy()
        child_env["PYTHONUNBUFFERED"] = "1"
        self.receipt_file = self.destination / ".automation_logs" / "report_receipts" / f"{self.run_id}_{step_index}_{uuid.uuid4().hex}.json"
        child_env["AUTOMATION_ARTIFACT_MANIFEST"] = str(self.receipt_file)
        for key in ("AUTOMATION_REPORT_START", "AUTOMATION_REPORT_END"):
            child_env.pop(key, None)
        if "--start-date" in args and "--end-date" in args and module != "qianchuan_promotion_fee_download":
            child_env["AUTOMATION_REPORT_START"] = str(args[args.index("--start-date") + 1])
            child_env["AUTOMATION_REPORT_END"] = str(args[args.index("--end-date") + 1])
        try:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise ControllerError(
                f"无法启动下载子脚本：profile={profile_name} step={name}；{exc}"
            ) from exc

        output_lines: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                line = line.rstrip("\r\n")
                if line:
                    if line.startswith("__MOCK_AUTOMATION_COMPONENT__:"):
                        try:
                            component_payload = json.loads(line.split(":", 1)[1])
                        except json.JSONDecodeError:
                            self.logger.warning("忽略无法解析的组件事件：profile=%s step=%s", profile_name, name)
                        else:
                            self._emit("component_event", {**event_payload, "component": component_payload})
                            self.logger.info(
                                "原子组件事件：profile=%s step=%s component=%s event=%s",
                                profile_name, name, component_payload.get("component_code"), component_payload.get("event"),
                            )
                        continue
                    output_lines.append(redact(line))
                    if len(output_lines) > 200:
                        output_lines.pop(0)
                    self.logger.info("子脚本输出：profile=%s step=%s %s", profile_name, name, line)
        return_code = process.wait()
        duration = round(time.perf_counter() - start, 3)
        result = {
            "name": name,
            "module": module,
            "started_at": started_at,
            "finished_at": local_timestamp(),
            "duration_seconds": duration,
            "return_code": return_code,
            "output_summary": "\n".join(output_lines)[-20_000:] or None,
            "artifacts": self._collect_artifacts(before_artifacts),
        }
        if return_code != 0:
            self.logger.error(
                "步骤失败：profile=%s step=%s module=%s return_code=%s duration_seconds=%s；"
                "已停止后续平台，保留失败现场供 AI 接管",
                profile_name,
                name,
                module,
                return_code,
                duration,
            )
            result["status"] = "needs_human" if return_code == 2 else "cancelled" if return_code == 130 else "failed"
            if any("REPORT_NOT_READY" in line for line in output_lines):
                result["reason"] = "report_not_ready"
            result["error_message"] = (
                f"下载步骤失败：profile={profile_name} step={name} module={module} return_code={return_code}"
            )
            self._emit("step_failed", {**event_payload, **result})
            raise DownloadStepError(result["error_message"], return_code=return_code, result=result)
        # A zero exit code without a receipt proves execution, not empty data.
        from scripts.auto_download.ledger import confirmed_no_data
        result["status"] = 'no_data' if not result['artifacts'] and confirmed_no_data(module, result['output_summary'] or '') else 'success'
        self._emit("step_downloaded", {**event_payload, **result, "status": "running"})
        if self.event_sink is None:
            from scripts.auto_download.ingest_api import IngestAPIError, submit_archived_reports
            try:
                from apps.automation_center.report_plan import step_reports
                result["ingest"] = submit_archived_reports(self.destination,result["artifacts"],metadata=metadata,
                    report_types=[spec.report_type for spec in step_reports(metadata['platform'],step)],
                    source='manual' if getattr(self,'trigger_type','manual')=='manual' else 'api',
                    period=event_payload['business_period'])
            except IngestAPIError as exc:
                result["status"] = "failed"
                result["reason"] = "ingest_failed"
                result["error_message"] = str(exc)
                self._emit("step_failed", {**event_payload, **result})
                raise DownloadStepError(str(exc), return_code=1, result=result) from exc
        self._emit("step_succeeded", {**event_payload, **result})
        self.logger.info(
            "步骤成功：profile=%s step=%s module=%s return_code=0 duration_seconds=%s",
            profile_name,
            name,
            module,
            duration,
        )
        return result

    def _queue_profile_for_close(self, profile_id: str, profile_name: str) -> None:
        if not any(item[0] == profile_id for item in self.profiles_ready_to_close):
            self.profiles_ready_to_close.append((profile_id, profile_name))

    def _cleanup_completed_profiles(self) -> None:
        if not self.profiles_ready_to_close:
            return
        self.logger.info(
            "开始补偿清理已完成但尚未关闭的 profile：数量=%s",
            len(self.profiles_ready_to_close),
        )
        for profile_id, profile_name in reversed(self.profiles_ready_to_close.copy()):
            self._stop_profile(profile_id, profile_name)

    def _stop_profile(self, profile_id: str, profile_name: str) -> None:
        try:
            result = self.client.call("stop_profile", {"id": profile_id})
            if isinstance(result, dict) and result.get("ok") is False:
                raise ControllerError("stop_profile 返回 ok=false")
            self.started_profile_ids = [
                item for item in self.started_profile_ids if item[0] != profile_id
            ]
            self.profiles_ready_to_close = [
                item for item in self.profiles_ready_to_close if item[0] != profile_id
            ]
            self.logger.info("已关闭已完成的 profile：%s", profile_name)
        except Exception as exc:
            message = f"停止 profile 失败：{profile_name}；{redact(exc)}"
            self.summary["cleanup_errors"].append(message)
            self.logger.exception(message)

    def write_summary(self) -> None:
        self.summary["finished_at"] = local_timestamp()
        self._emit("completed", {key: self.summary.get(key) for key in ("status", "finished_at")})
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        with self.summary_path.open("w", encoding="utf-8") as stream:
            json.dump(self.summary, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        self.logger.info(
            "总控结束：status=%s summary=%s",
            self.summary.get("status"),
            self.summary_path,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="串行执行抖音、京东、拼多多、快手、小红书、天猫报表自动化下载"
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="总控 JSON 配置；默认 scripts/auto_download/all_platform_downloads.json",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="覆盖配置中的归档根目录；默认 C:\\Users\\win\\Desktop\\data",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="覆盖日志目录；默认归档根目录/.automation_logs/all_platform_downloads",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="覆盖 Cloak Login MCP 地址；默认读取 CLOAK_MCP_URL 或本机 19610 端口",
    )
    parser.add_argument(
        "--checkpoint-scope",
        default=None,
        help="覆盖可恢复检查点 scope；默认使用本地日期，同一天重跑会续接上次进度",
    )
    parser.add_argument(
        "--lane",
        choices=[EXECUTION_LANE_ALL, *sorted(SUPPORTED_EXECUTION_LANES)],
        default=EXECUTION_LANE_ALL,
        help=(
            "执行通道：all=原有全量流程，overnight=凌晨任务，"
            "interactive=可交互及补跑任务"
        ),
    )
    parser.add_argument(
        "--lock-wait-seconds",
        type=int,
        default=0,
        help="等待其他总控实例释放共享互斥锁的秒数；默认 0（立即报错）",
    )
    parser.add_argument(
        "--exclude-platform", choices=sorted(SUPPORTED_PLATFORMS),
        help="跳过指定平台，用于把该平台拆到其他时段执行",
    )
    parser.add_argument(
        "--trigger-type",
        choices=["manual", "schedule"],
        default="manual",
        help="运行来源：manual=手动（默认），schedule=每日定时执行并校验当天检查点",
    )
    return parser


def main(argv: Iterable[str] | None = None, *, business_date: date | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    from apps.fund_split_adjust.server import load_project_env
    load_project_env()
    config_path = resolve_path(args.config)
    run_started_at = china_now()
    run_business_date = business_date or run_started_at.date()
    run_id = f"{run_started_at.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    bootstrap_log_dir = resolve_path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    logger = configure_logger(bootstrap_log_dir / f"{run_id}.log")
    summary_path = bootstrap_log_dir / f"{run_id}.summary.json"
    controller: DownloadController | None = None
    run_lock: ControllerRunLock | None = None

    try:
        config = load_config(config_path)
        destination = resolve_path(
            args.dest or config.get("destination") or str(DEFAULT_DEST), base=PROJECT_ROOT
        )
        log_dir = resolve_path(
            args.log_dir
            or config.get("log_directory")
            or str(destination / ".automation_logs" / "all_platform_downloads"),
            base=PROJECT_ROOT,
        )
        if log_dir != bootstrap_log_dir:
            logger = configure_logger(log_dir / f"{run_id}.log")
            summary_path = log_dir / f"{run_id}.summary.json"
        run_lock = ControllerRunLock(
            path=log_dir / "controller.lock",
            wait_seconds=args.lock_wait_seconds,
            run_id=run_id,
            execution_lane=args.lane,
            logger=logger,
        )
        run_lock.acquire()
        mcp_url = args.mcp_url or os.getenv("CLOAK_MCP_URL") or config.get("mcp_url") or DEFAULT_MCP_URL
        controller = DownloadController(
            config=config,
            config_path=config_path,
            destination=destination,
            logger=logger,
            run_id=run_id,
            summary_path=summary_path,
            mcp_url=str(mcp_url),
            checkpoint_scope=args.checkpoint_scope or config.get("checkpoint_scope"),
            execution_lane=args.lane,
            business_date=run_business_date,
            require_daily_checkpoint=args.trigger_type == "schedule" or business_date is not None,
            trigger_type=args.trigger_type,
            exclude_platform=args.exclude_platform,
        )
        logger.info(
            "业务日期确认：business_date=%s timezone=%s checkpoint_scope=%s checkpoint=%s",
            controller.business_date.isoformat(), CHINA_TIME_ZONE,
            controller.checkpoint_scope, controller.checkpoint.path,
        )
        exit_code = controller.run()
    except (Exception, KeyboardInterrupt) as exc:
        logger.exception("总控失败：%s", redact(exc))
        if controller is not None:
            controller.summary["status"] = "cancelled" if isinstance(exc, KeyboardInterrupt) else "needs_human" if isinstance(exc, DownloadStepError) and exc.return_code == 2 else "failed"
            controller.summary["error"] = redact(exc)
            controller.summary["traceback"] = redact(traceback.format_exc())
            try:
                controller.write_summary()
            except Exception as summary_error:
                logger.exception("写入总控汇总失败：%s", redact(summary_error))
        else:
            logger.error("总控在初始化阶段失败，详细异常：%s", redact(traceback.format_exc()))
        return 1
    else:
        if controller is not None:
            try:
                controller.write_summary()
            except Exception as summary_error:
                logger.exception("写入总控汇总失败：%s", redact(summary_error))
                return 1
        return exit_code
    finally:
        if run_lock is not None:
            run_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
