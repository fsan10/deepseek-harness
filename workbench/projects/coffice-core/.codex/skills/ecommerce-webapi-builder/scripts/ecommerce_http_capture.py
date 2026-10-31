#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""通过 CDP 旁路监听电商后台的 HTTP/API/下载链路。

监听器不点击页面、不修改请求，也不下载文件。它持续发现同一浏览器中的
page/iframe/worker Target，过滤图片、视频、字体、图标、样式、脚本和已知
埋点，保存查询、导出、轮询、下载相关请求的 Payload、响应状态和响应体。

推荐从项目根目录运行：

    & ".venv\Scripts\python.exe" ".codex\skills\ecommerce-webapi-builder\scripts\ecommerce_http_capture.py" --platform pinduoduo --profile-name "PDD-拼多多-店铺名" --ws-endpoint "<由 Cloak Login MCP 取得>" --label "订单"

看到 [READY] 后再运行现有 DOM 下载脚本。DOM 脚本完成后按 Ctrl+C，监听器
会写入最终 JSON。运行期间也会周期性写入 capture_complete=false 的检查点。
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import websocket


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_FILE = SCRIPT_DIR / "platform_filters.json"
DEFAULT_CAPTURE_DIR = Path(".codex_tmp") / "captures"

# Profile 重启后 endpoint 通常会变化。可以直接修改此常量，也可以在命令行
# 使用 --ws-endpoint / --cdp / --debug-port 覆盖。不要在这里保存账号或令牌。
DEFAULT_WS_ENDPOINT = ""

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
    "sessionid",
    "csrf",
)
SENSITIVE_QUERY_KEYS = {
    "authorization",
    "access_token",
    "accesstoken",
    "csrf",
    "password",
    "passid",
    "sessionid",
    "sign",
    "signature",
    "ticket",
    "token",
}
ALLOWED_TARGET_TYPES = {"page", "iframe", "worker", "service_worker", "shared_worker"}
PLATFORM_FILE_PREFIXES = {
    "generic": "ecommerce",
    "pinduoduo": "pdd",
    "douyin": "douyin",
    "qianchuan": "qianchuan",
    "jd": "jd",
    "kuaishou": "kuaishou",
    "xiaohongshu": "xhs",
    "tmall": "tmall",
}
REPORT_FILE_ALIASES = (
    ("推广费用", "promotion_fee"),
    ("推广费", "promotion_fee"),
    ("推广", "promotion_fee"),
    ("结算账单", "settlement"),
    ("结算单", "settlement"),
    ("结算", "settlement"),
    ("资金账单", "fund"),
    ("资金单", "fund"),
    ("资金", "fund"),
    ("订单", "order"),
    ("账单", "bill"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(stage: str, message: str) -> None:
    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{stage}] {message}", flush=True)


def find_git_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def safe_file_slug(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^\w]+", "_", value.strip().lower(), flags=re.UNICODE)
    normalized = normalized.strip("_")
    return normalized or fallback


def report_file_slug(label: str) -> str:
    normalized = label.strip().lower()
    for marker, slug in REPORT_FILE_ALIASES:
        if marker in normalized:
            return slug
    return safe_file_slug(normalized, fallback="capture")


def unique_capture_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成唯一 Capture 路径：{path}")


def default_capture_path(platform: str, label: str) -> Path:
    root = find_git_root(Path.cwd())
    platform_slug = PLATFORM_FILE_PREFIXES.get(
        platform,
        safe_file_slug(platform, fallback="ecommerce"),
    )
    report_slug = report_file_slug(label)
    local_date = datetime.now().astimezone().strftime("%Y%m%d")
    return unique_capture_path(
        root
        / DEFAULT_CAPTURE_DIR
        / f"{platform_slug}_{report_slug}_{local_date}.json"
    )


def listener_restart_delay(attempt: int) -> float:
    exponent = min(max(attempt - 1, 0), 5)
    return min(5.0, 0.25 * (2**exponent))


def normalize_domain(value: str) -> str:
    return value.strip().lower().lstrip(".").rstrip(".")


def hostname_from_url(url: str) -> str:
    try:
        return normalize_domain(urlparse(url).hostname or "")
    except Exception:
        return ""


def domain_matches(hostname: str, domains: tuple[str, ...] | list[str]) -> bool:
    hostname = normalize_domain(hostname)
    if not hostname:
        return False
    return any(hostname == item or hostname.endswith("." + item) for item in domains)


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("_", "").replace("-", "")
    return any(
        part.replace("_", "").replace("-", "") in normalized
        for part in SENSITIVE_KEY_PARTS
    )


def sanitize_url(url: str) -> str:
    """保留 host/path/普通业务参数，隐藏登录、签名和风控查询值。"""

    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.query:
        return url

    items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower().replace("-", "").replace("_", "")
        sensitive = normalized in {
            item.replace("-", "").replace("_", "") for item in SENSITIVE_QUERY_KEYS
        } or is_sensitive_key(key)
        items.append((key, "***REDACTED***" if sensitive else value))
    return urlunparse(parsed._replace(query=urlencode(items, doseq=True)))


def sanitize_raw_text(value: str, *, max_string_chars: int | None = None) -> str:
    text = re.sub(
        r"(?i)\bws://[^/\s\"']+/devtools/(?:browser|page)/[^\s\"']+",
        "ws://***REDACTED***",
        value,
    )
    secret_names = (
        "authorization",
        "password",
        "passwd",
        "token",
        "ticket",
        "signature",
        "sign",
        "anti-content",
        "crawlerinfo",
        "passid",
        "sessionid",
        "csrf",
    )
    for name in secret_names:
        pattern = re.compile(
            rf"(?i)({re.escape(name)}\s*[\"']?\s*[:=]\s*[\"']?)([^&\s,\"';}}]+)"
        )
        text = pattern.sub(r"\1***REDACTED***", text)
    if max_string_chars is not None and len(text) > max_string_chars:
        omitted = len(text) - max_string_chars
        text = text[:max_string_chars] + f"\n...[truncated {omitted} chars]"
    return text


def sanitize_value(value: Any, *, max_string_chars: int | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            result[str(key)] = (
                "***REDACTED***"
                if is_sensitive_key(key)
                else sanitize_value(item, max_string_chars=max_string_chars)
            )
        return result
    if isinstance(value, list):
        return [
            sanitize_value(item, max_string_chars=max_string_chars) for item in value
        ]
    if isinstance(value, tuple):
        return [
            sanitize_value(item, max_string_chars=max_string_chars) for item in value
        ]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("http://", "https://", "ws://", "wss://")):
            value = sanitize_url(value)
        return sanitize_raw_text(value, max_string_chars=max_string_chars)
    return value


def sanitize_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in headers.items():
        key_text = str(key)
        if is_sensitive_key(key_text):
            result[key_text] = "***REDACTED***"
            continue
        value_text = str(value)
        if value_text.strip().startswith(("http://", "https://")):
            value_text = sanitize_url(value_text)
        result[key_text] = sanitize_raw_text(value_text, max_string_chars=20_000)
    return result


def sanitized_query_items(url: str) -> list[dict[str, str]]:
    try:
        pairs = parse_qsl(urlparse(url).query, keep_blank_values=True)
    except Exception:
        return []
    result: list[dict[str, str]] = []
    for key, value in pairs:
        result.append(
            {
                "name": key,
                "value": "***REDACTED***"
                if is_sensitive_key(key)
                or key.lower().replace("-", "").replace("_", "")
                in {
                    item.replace("-", "").replace("_", "")
                    for item in SENSITIVE_QUERY_KEYS
                }
                else sanitize_raw_text(value, max_string_chars=20_000),
            }
        )
    return result


def parse_post_data(text: str | None, *, max_body_chars: int) -> Any:
    if not text:
        return None
    try:
        return sanitize_value(json.loads(text), max_string_chars=max_body_chars)
    except Exception:
        pass

    if "=" in text and "\n" not in text:
        try:
            pairs = parse_qsl(text, keep_blank_values=True)
        except Exception:
            pairs = []
        if pairs:
            return {
                "_encoding": "form",
                "fields": [
                    {
                        "name": key,
                        "value": "***REDACTED***"
                        if is_sensitive_key(key)
                        else sanitize_raw_text(value, max_string_chars=max_body_chars),
                    }
                    for key, value in pairs
                ],
            }
    return sanitize_raw_text(text, max_string_chars=max_body_chars)


def parse_response_body(
    body: str,
    *,
    max_body_chars: int,
    base64_encoded: bool,
) -> tuple[Any, bool]:
    if base64_encoded:
        return {
            "_omitted": "base64-encoded response body",
            "encoded_chars": len(body),
        }, False

    truncated = len(body) > max_body_chars
    if truncated:
        return sanitize_raw_text(
            body[:max_body_chars],
            max_string_chars=max_body_chars,
        ), True
    try:
        return sanitize_value(json.loads(body), max_string_chars=max_body_chars), False
    except Exception:
        return sanitize_raw_text(body, max_string_chars=max_body_chars), False


def unique_strings(values: list[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class CaptureRules:
    platform: str
    description: str
    include_domains: tuple[str, ...]
    exclude_domains: tuple[str, ...]
    exclude_url_patterns: tuple[str, ...]
    exclude_url_regexes: tuple[re.Pattern[str], ...]
    capture_resource_types: tuple[str, ...]
    ignore_resource_types: tuple[str, ...]
    ignore_extensions: tuple[str, ...]

    def url_in_scope(self, url: str) -> bool:
        host = hostname_from_url(url)
        if not host:
            return False
        if domain_matches(host, self.exclude_domains):
            return False
        if not self.include_domains:
            return True
        return domain_matches(host, self.include_domains)

    def evaluate(
        self,
        *,
        url: str,
        resource_type: str | None,
        source_url: str,
        target_in_scope: bool,
    ) -> tuple[bool, str]:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
            return False, "non_http"

        resource = str(resource_type or "Other")
        if resource in self.ignore_resource_types:
            return False, "ignored_resource_type"
        if resource not in self.capture_resource_types:
            return False, "uncaptured_resource_type"

        suffix = Path(parsed.path).suffix.lower()
        if suffix and suffix in self.ignore_extensions:
            return False, "ignored_extension"

        host = normalize_domain(parsed.hostname or "")
        if domain_matches(host, self.exclude_domains):
            return False, "excluded_domain"

        sanitized = sanitize_url(url)
        if any(pattern.search(sanitized) for pattern in self.exclude_url_regexes):
            return False, "excluded_pattern"

        source_in_scope = self.url_in_scope(source_url)
        request_in_scope = self.url_in_scope(url)
        if self.include_domains and not (
            target_in_scope or source_in_scope or request_in_scope
        ):
            return False, "outside_platform_scope"
        return True, "captured"

    def public_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "description": self.description,
            "include_domains": list(self.include_domains),
            "exclude_domains": list(self.exclude_domains),
            "exclude_url_regex": list(self.exclude_url_patterns),
            "capture_resource_types": list(self.capture_resource_types),
            "ignore_resource_types": list(self.ignore_resource_types),
            "ignore_extensions": list(self.ignore_extensions),
        }


class PlatformCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("platforms"), dict):
            raise ValueError(f"平台规则格式无效：{path}")
        self.common = payload.get("common") or {}
        self.platforms: dict[str, dict[str, Any]] = payload["platforms"]
        self.aliases: dict[str, str] = {}
        for name, config in self.platforms.items():
            self.aliases[name.casefold()] = name
            for alias in config.get("aliases") or []:
                self.aliases[str(alias).casefold()] = name

    def canonical_name(self, name: str) -> str:
        key = name.strip().casefold()
        if key not in self.aliases:
            available = ", ".join(sorted(self.platforms))
            raise ValueError(
                f"未知平台规则：{name}。可用：{available}；未知平台可使用 generic"
            )
        return self.aliases[key]

    def build_rules(
        self,
        platform: str,
        *,
        include_domains: list[str],
        exclude_domains: list[str],
        exclude_url_regex: list[str],
        capture_all_http: bool,
    ) -> CaptureRules:
        canonical = self.canonical_name(platform)
        config = self.platforms[canonical]

        platform_domains = [] if capture_all_http else list(
            config.get("include_domains") or []
        )
        if not capture_all_http:
            platform_domains.extend(include_domains)
        included = unique_strings(
            [normalize_domain(item) for item in platform_domains if normalize_domain(item)]
        )
        excluded = unique_strings(
            [
                normalize_domain(item)
                for item in list(self.common.get("exclude_domains") or [])
                + list(config.get("exclude_domains") or [])
                + exclude_domains
                if normalize_domain(item)
            ]
        )
        pattern_texts = unique_strings(
            list(self.common.get("exclude_url_regex") or [])
            + list(config.get("exclude_url_regex") or [])
            + exclude_url_regex
        )
        try:
            patterns = tuple(re.compile(item) for item in pattern_texts)
        except re.error as exc:
            raise ValueError(f"过滤正则无效：{exc}") from exc

        return CaptureRules(
            platform=canonical,
            description=str(config.get("description") or ""),
            include_domains=included,
            exclude_domains=excluded,
            exclude_url_patterns=pattern_texts,
            exclude_url_regexes=patterns,
            capture_resource_types=unique_strings(
                list(self.common.get("capture_resource_types") or [])
            ),
            ignore_resource_types=unique_strings(
                list(self.common.get("ignore_resource_types") or [])
            ),
            ignore_extensions=unique_strings(
                [str(item).lower() for item in self.common.get("ignore_extensions") or []]
            ),
        )

    def print_platforms(self) -> None:
        for name in sorted(self.platforms):
            config = self.platforms[name]
            aliases = ", ".join(str(item) for item in config.get("aliases") or [])
            suffix = f"（别名：{aliases}）" if aliases else ""
            print(f"{name}: {config.get('description', '')}{suffix}")


class CaptureStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_capture_id = 0
        self._records: list[dict[str, Any]] = []
        self._target_events: list[dict[str, Any]] = []
        self._skipped: Counter[tuple[str, str]] = Counter()

    def next_capture_id(self) -> int:
        with self._lock:
            self._next_capture_id += 1
            return self._next_capture_id

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)

    def append_target_event(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._target_events.append(record)

    def note_skipped(self, url: str, reason: str) -> None:
        host = hostname_from_url(url) or "(no-host)"
        with self._lock:
            self._skipped[(host, reason)] += 1

    def snapshot(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[tuple[str, str]]]:
        with self._lock:
            return list(self._records), list(self._target_events), self._skipped.copy()

    def summary(self) -> dict[str, Any]:
        records, target_events, skipped = self.snapshot()
        network = [
            item for item in records if item.get("record_type") == "network"
        ]
        downloads = [
            item for item in records if item.get("record_type") == "download"
        ]
        response_bodies = sum(
            bool(item.get("response_body_available")) for item in network
        )

        endpoints: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in network:
            request = item.get("request") or {}
            method = str(request.get("method") or "")
            url = str(request.get("url") or "")
            parsed = urlparse(url)
            key = (method, parsed.hostname or "", parsed.path or "/")
            endpoint = endpoints.setdefault(
                key,
                {
                    "method": method,
                    "host": parsed.hostname or "",
                    "path": parsed.path or "/",
                    "count": 0,
                    "capture_ids": [],
                    "resource_types": Counter(),
                    "statuses": Counter(),
                    "response_mime_types": Counter(),
                    "has_post_data": False,
                    "query_key_sets": [],
                    "request_payload_key_sets": [],
                    "response_top_level_key_sets": [],
                },
            )
            endpoint["count"] += 1
            endpoint["capture_ids"].append(item.get("capture_id"))
            endpoint["resource_types"][str(item.get("resource_type") or "")] += 1
            endpoint["has_post_data"] = endpoint["has_post_data"] or bool(
                request.get("has_post_data")
            )
            query_keys = tuple(
                sorted(
                    {
                        str(item.get("name"))
                        for item in request.get("query") or []
                        if isinstance(item, dict) and item.get("name")
                    }
                )
            )
            if query_keys and list(query_keys) not in endpoint["query_key_sets"]:
                endpoint["query_key_sets"].append(list(query_keys))
            payload_keys = self._payload_keys(request.get("post_data"))
            if (
                payload_keys
                and list(payload_keys) not in endpoint["request_payload_key_sets"]
            ):
                endpoint["request_payload_key_sets"].append(list(payload_keys))
            response = item.get("response") or {}
            if response.get("status") is not None:
                endpoint["statuses"][str(response["status"])] += 1
            if response.get("mime_type"):
                endpoint["response_mime_types"][str(response["mime_type"])] += 1
            response_keys = self._payload_keys(item.get("response_body"))
            if (
                response_keys
                and list(response_keys) not in endpoint["response_top_level_key_sets"]
            ):
                endpoint["response_top_level_key_sets"].append(list(response_keys))

        endpoint_rows: list[dict[str, Any]] = []
        for endpoint in endpoints.values():
            endpoint["resource_types"] = dict(endpoint["resource_types"])
            endpoint["statuses"] = dict(endpoint["statuses"])
            endpoint["response_mime_types"] = dict(endpoint["response_mime_types"])
            endpoint_rows.append(endpoint)
        endpoint_rows.sort(
            key=lambda item: min(
                [value for value in item["capture_ids"] if isinstance(value, int)]
                or [10**12]
            )
        )

        skipped_rows = [
            {"host": host, "reason": reason, "count": count}
            for (host, reason), count in skipped.most_common()
        ]
        return {
            "network_records": len(network),
            "responses_with_body": response_bodies,
            "download_events": len(downloads),
            "target_events": len(target_events),
            "endpoints": endpoint_rows,
            "skipped_hosts": skipped_rows,
        }

    @staticmethod
    def _payload_keys(value: Any) -> tuple[str, ...]:
        if not isinstance(value, dict):
            return ()
        if value.get("_encoding") == "form" and isinstance(value.get("fields"), list):
            return tuple(
                sorted(
                    {
                        str(item.get("name"))
                        for item in value["fields"]
                        if isinstance(item, dict) and item.get("name")
                    }
                )
            )
        return tuple(sorted(str(key) for key in value))

    def build_document(
        self,
        *,
        rules: CaptureRules,
        debug_port: int,
        profile_name: str,
        label: str,
        started_at: str,
        capture_complete: bool,
    ) -> dict[str, Any]:
        records, target_events, _ = self.snapshot()
        return {
            "schema_version": 1,
            "capture": {
                "platform": rules.platform,
                "profile_name": profile_name,
                "label": label,
                "debug_port": debug_port,
                "started_at": started_at,
                "saved_at": now_iso(),
                "capture_complete": capture_complete,
                "filter_rules": rules.public_dict(),
            },
            "summary": self.summary(),
            "targets": target_events,
            "records": records,
        }


class PageListener:
    def __init__(
        self,
        *,
        target: dict[str, Any],
        inherited_scope: bool,
        store: CaptureStore,
        rules: CaptureRules,
        stop_event: threading.Event,
        max_body_chars: int,
    ) -> None:
        self.target_id = str(target["id"])
        self.target_type = str(target.get("type") or "")
        self.title = str(target.get("title") or "")
        self.page_url = str(target.get("url") or "")
        self.ws_url = str(target["webSocketDebuggerUrl"])
        self.in_scope = inherited_scope or rules.url_in_scope(self.page_url)
        self.store = store
        self.rules = rules
        self.stop_event = stop_event
        self.max_body_chars = max_body_chars

        self.thread: threading.Thread | None = None
        self.ws: websocket.WebSocket | None = None
        self._command_id = 0
        self._requests: dict[str, dict[str, Any]] = {}
        self._pending_body_commands: dict[int, str] = {}
        self._closed = threading.Event()
        self.started_monotonic: float | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self.in_scope:
            self.store.append_target_event(
                {
                    "event": "attached",
                    "event_at": now_iso(),
                    "target_id": self.target_id,
                    "target_type": self.target_type,
                    "title": self.title,
                    "url": sanitize_url(self.page_url),
                    "in_scope": True,
                }
            )
            log(
                "TARGET",
                f"attach id={self.target_id[:8]} type={self.target_type} "
                f"scope=yes url={sanitize_url(self.page_url)}",
            )
        else:
            # 仍连接该 Target，以便它随后导航到目标平台；不记录无关标签页
            # 的标题和 URL。
            log(
                "TARGET",
                f"attach id={self.target_id[:8]} type={self.target_type} scope=watch",
            )
        self.thread = threading.Thread(
            target=self._run,
            name=f"ecommerce-cdp-{self.target_id[:8]}",
            daemon=True,
        )
        self.started_monotonic = time.monotonic()
        self.thread.start()

    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def uptime_seconds(self) -> float:
        if self.started_monotonic is None:
            return 0.0
        return max(0.0, time.monotonic() - self.started_monotonic)

    def update_target(self, target: dict[str, Any]) -> None:
        current_url = str(target.get("url") or "")
        if not current_url:
            return
        changed = current_url != self.page_url
        previous_scope = self.in_scope
        self.page_url = current_url
        if self.rules.url_in_scope(current_url):
            self.in_scope = True
        if changed and (previous_scope or self.in_scope):
            self.store.append_target_event(
                {
                    "event": "target_url_changed",
                    "event_at": now_iso(),
                    "target_id": self.target_id,
                    "target_type": self.target_type,
                    "url": sanitize_url(current_url),
                    "in_scope": self.in_scope,
                }
            )

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
        try:
            self.ws = websocket.create_connection(
                self.ws_url,
                timeout=5,
                suppress_origin=True,
                enable_multithread=True,
            )
            self.ws.settimeout(1.0)
            self._send(
                "Network.enable",
                {
                    "maxTotalBufferSize": 100_000_000,
                    "maxResourceBufferSize": 50_000_000,
                    "maxPostDataSize": self.max_body_chars,
                },
            )
            self._send("Page.enable")

            while not self.stop_event.is_set():
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    self.last_error = "WebSocket 已关闭"
                    break
                try:
                    message = json.loads(raw)
                except Exception as exc:
                    log("WARN", f"target={self.target_id[:8]} CDP 消息解析失败：{exc!r}")
                    continue
                self._handle_message(message)
        except Exception as exc:
            self.last_error = sanitize_raw_text(repr(exc), max_string_chars=1_000)
            if not self.stop_event.is_set():
                log(
                    "WARN",
                    f"target={self.target_id[:8]} 监听结束：{self.last_error}",
                )
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
        resource_type = str(params.get("type") or "Other")
        source_url = str(params.get("documentURL") or self.page_url)

        capture, reason = self.rules.evaluate(
            url=url,
            resource_type=resource_type,
            source_url=source_url,
            target_in_scope=self.in_scope,
        )
        if not request_id or not capture:
            if url and (
                self.in_scope
                or self.rules.url_in_scope(source_url)
                or self.rules.url_in_scope(url)
            ):
                self.store.note_skipped(url, reason)
            return
        if self.rules.url_in_scope(url) or self.rules.url_in_scope(source_url):
            self.in_scope = True

        old_record = self._requests.pop(request_id, None)
        if old_record is not None:
            redirect_response = params.get("redirectResponse")
            if isinstance(redirect_response, dict):
                old_record["response"] = self._response_metadata(redirect_response)
            old_record["redirected_to"] = sanitize_url(url)
            old_record["finished_at"] = now_iso()
            self._finalize(old_record)

        capture_id = self.store.next_capture_id()
        record: dict[str, Any] = {
            "record_type": "network",
            "capture_id": capture_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "page_url": sanitize_url(source_url),
            "request_id": request_id,
            "resource_type": resource_type,
            "request_started_at": now_iso(),
            "_started_monotonic": time.monotonic(),
            "request": {
                "method": request.get("method"),
                "url": sanitize_url(url),
                "query": sanitized_query_items(url),
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
            record["initiator"] = sanitize_value(
                params["initiator"],
                max_string_chars=20_000,
            )
        self._requests[request_id] = record
        log(
            f"REQ {capture_id:04d}",
            f"{resource_type} {request.get('method', '')} {sanitize_url(url)}",
        )

    def _on_request_extra_info(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is not None and params.get("headers"):
            record.setdefault("request", {})["extra_headers"] = sanitize_headers(
                params["headers"]
            )

    @staticmethod
    def _response_metadata(response: dict[str, Any]) -> dict[str, Any]:
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
        if record is not None:
            record["response"] = self._response_metadata(params.get("response") or {})

    def _on_response_extra_info(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None or not params.get("headers"):
            return
        if not isinstance(record.get("response"), dict):
            record["response"] = {}
        record["response"]["extra_headers"] = sanitize_headers(params["headers"])

    @staticmethod
    def _should_read_body(record: dict[str, Any]) -> bool:
        resource_type = str(record.get("resource_type") or "")
        if resource_type in {"XHR", "Fetch", "EventSource", "Other"}:
            return True
        response = record.get("response") or {}
        mime_type = str(response.get("mime_type") or "").lower()
        return any(
            marker in mime_type
            for marker in ("json", "text", "xml", "graphql", "javascript")
        )

    def _on_loading_finished(self, params: dict[str, Any]) -> None:
        request_id = str(params.get("requestId") or "")
        record = self._requests.get(request_id)
        if record is None or record.get("_saved"):
            return
        record["encoded_data_length"] = params.get("encodedDataLength")
        record["finished_at"] = now_iso()
        if self._should_read_body(record) and self.ws is not None:
            try:
                command_id = self._send(
                    "Network.getResponseBody",
                    {"requestId": request_id},
                )
            except Exception as exc:
                record["response_body_error"] = sanitize_raw_text(repr(exc))
                self._finalize(record)
                return
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
        record["loading_failed"] = sanitize_value(
            {
                "error_text": params.get("errorText"),
                "canceled": params.get("canceled"),
                "blocked_reason": params.get("blockedReason"),
                "type": params.get("type"),
            }
        )
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
            parsed, truncated = parse_response_body(
                str(body),
                max_body_chars=self.max_body_chars,
                base64_encoded=bool(result.get("base64Encoded")),
            )
            record["response_body"] = parsed
            record["response_body_available"] = True
            record["response_body_truncated"] = truncated
            record["response_body_base64_encoded"] = bool(result.get("base64Encoded"))
        self._finalize(record)

    def _on_frame_navigated(self, params: dict[str, Any]) -> None:
        frame = params.get("frame") or {}
        if frame.get("parentId") or not frame.get("url"):
            return
        previous_scope = self.in_scope
        self.page_url = str(frame["url"])
        if self.rules.url_in_scope(self.page_url):
            self.in_scope = True
        if previous_scope or self.in_scope:
            self.store.append_target_event(
                {
                    "event": "navigation",
                    "event_at": now_iso(),
                    "target_id": self.target_id,
                    "target_type": self.target_type,
                    "url": sanitize_url(self.page_url),
                    "in_scope": self.in_scope,
                }
            )
            log(
                "NAV",
                f"target={self.target_id[:8]} {sanitize_url(self.page_url)}",
            )

    def _on_download_will_begin(self, params: dict[str, Any]) -> None:
        url = str(params.get("url") or "")
        if not (self.in_scope or self.rules.url_in_scope(url)):
            return
        record = {
            "record_type": "download",
            "download_event": "willBegin",
            "target_id": self.target_id,
            "target_type": self.target_type,
            "page_url": sanitize_url(self.page_url),
            "event_at": now_iso(),
            "guid": params.get("guid"),
            "url": sanitize_url(url),
            "suggested_filename": params.get("suggestedFilename"),
        }
        self.store.append(record)
        log(
            "DOWNLOAD",
            f"start file={record['suggested_filename'] or '-'} url={record['url']}",
        )

    def _on_download_progress(self, params: dict[str, Any]) -> None:
        if not self.in_scope:
            return
        record = {
            "record_type": "download",
            "download_event": "progress",
            "target_id": self.target_id,
            "target_type": self.target_type,
            "page_url": sanitize_url(self.page_url),
            "event_at": now_iso(),
            "guid": params.get("guid"),
            "state": params.get("state"),
            "received_bytes": params.get("receivedBytes"),
            "total_bytes": params.get("totalBytes"),
            "file_path": params.get("filePath"),
        }
        self.store.append(record)
        if params.get("state") in {"completed", "canceled"}:
            log(
                "DOWNLOAD",
                f"state={params.get('state')} bytes={params.get('receivedBytes')}",
            )

    def _finalize(self, record: dict[str, Any]) -> None:
        if record.get("_saved"):
            return
        record["_saved"] = True
        record.pop("response_body_pending", None)
        started = record.pop("_started_monotonic", None)
        if isinstance(started, (int, float)):
            record["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        stored = dict(record)
        stored.pop("_saved", None)
        self.store.append(stored)

        response = record.get("response") or {}
        status = response.get("status") if isinstance(response, dict) else None
        size = record.get("encoded_data_length")
        duration = record.get("duration_ms")
        log(
            f"RES {int(record.get('capture_id') or 0):04d}",
            f"HTTP {status if status is not None else '-'} "
            f"{duration if duration is not None else '-'}ms "
            f"{size if size is not None else '-'}B",
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
    def __init__(
        self,
        *,
        debug_port: int,
        output_path: Path,
        rules: CaptureRules,
        profile_name: str,
        label: str,
        max_body_chars: int,
        scan_interval_seconds: float,
        stale_target_seconds: float,
    ) -> None:
        self.debug_port = debug_port
        self.debug_http = f"http://127.0.0.1:{debug_port}"
        self.output_path = output_path
        self.rules = rules
        self.profile_name = profile_name
        self.label = label
        self.max_body_chars = max_body_chars
        self.scan_interval_seconds = scan_interval_seconds
        self.stale_target_seconds = stale_target_seconds
        self.started_at = now_iso()
        self.store = CaptureStore()

        self.stop_event = threading.Event()
        self.discovery_thread: threading.Thread | None = None
        self.sessions: dict[str, PageListener] = {}
        self.last_seen: dict[str, float] = {}
        self.listener_restart_counts: dict[str, int] = {}
        self.listener_restart_not_before: dict[str, float] = {}
        self.sessions_lock = threading.Lock()

    def _fetch_targets(self) -> list[dict[str, Any]]:
        response = requests.get(f"{self.debug_http}/json/list", timeout=3)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def _create_listener(
        self,
        target: dict[str, Any],
        inherited_scope: bool,
    ) -> PageListener:
        return PageListener(
            target=target,
            inherited_scope=inherited_scope,
            store=self.store,
            rules=self.rules,
            stop_event=self.stop_event,
            max_body_chars=self.max_body_chars,
        )

    def discover_once(self) -> None:
        try:
            targets = self._fetch_targets()
        except Exception as exc:
            if not self.stop_event.is_set():
                log("WARN", f"扫描 Target 失败：{exc!r}")
            return

        now = time.monotonic()
        active_ids: set[str] = set()
        for target in targets:
            if str(target.get("type") or "") not in ALLOWED_TARGET_TYPES:
                continue
            target_id = str(target.get("id") or "")
            ws_url = str(target.get("webSocketDebuggerUrl") or "")
            if not target_id or not ws_url:
                continue
            active_ids.add(target_id)

            with self.sessions_lock:
                existing = self.sessions.get(target_id)
                opener = self.sessions.get(str(target.get("openerId") or ""))
            self.last_seen[target_id] = now
            inherited_scope = bool(opener and opener.in_scope)
            if existing is not None:
                existing.update_target(target)
                inherited_scope = inherited_scope or existing.in_scope
                if existing.is_alive():
                    if existing.uptime_seconds() >= 5:
                        self.listener_restart_counts.pop(target_id, None)
                        self.listener_restart_not_before.pop(target_id, None)
                    continue

                not_before = self.listener_restart_not_before.get(target_id, 0.0)
                if now < not_before:
                    continue
                with self.sessions_lock:
                    if self.sessions.get(target_id) is not existing:
                        continue
                    self.sessions.pop(target_id, None)
                existing.close()

                attempt = self.listener_restart_counts.get(target_id, 0) + 1
                delay = listener_restart_delay(attempt)
                self.listener_restart_counts[target_id] = attempt
                self.listener_restart_not_before[target_id] = now + delay
                reason = sanitize_raw_text(
                    existing.last_error or "监听线程已退出",
                    max_string_chars=1_000,
                )
                restart_event: dict[str, Any] = {
                    "event": "listener_restart",
                    "event_at": now_iso(),
                    "target_id": target_id,
                    "target_type": str(target.get("type") or ""),
                    "attempt": attempt,
                    "backoff_seconds": delay,
                    "reason": reason,
                    "in_scope": inherited_scope,
                }
                if inherited_scope:
                    restart_event["url"] = sanitize_url(
                        str(target.get("url") or "")
                    )
                self.store.append_target_event(restart_event)
                log(
                    "RESTART",
                    f"target={target_id[:8]} attempt={attempt} "
                    f"backoff={delay:.2f}s reason={reason}",
                )

            if existing is None and now < self.listener_restart_not_before.get(
                target_id, 0.0
            ):
                continue

            listener = self._create_listener(target, inherited_scope)
            with self.sessions_lock:
                if self.stop_event.is_set() or target_id in self.sessions:
                    continue
                self.sessions[target_id] = listener
            try:
                listener.start()
            except Exception as exc:
                reason = sanitize_raw_text(repr(exc), max_string_chars=1_000)
                listener.last_error = reason
                with self.sessions_lock:
                    if self.sessions.get(target_id) is listener:
                        self.sessions.pop(target_id, None)
                attempt = self.listener_restart_counts.get(target_id, 0) + 1
                delay = listener_restart_delay(attempt)
                self.listener_restart_counts[target_id] = attempt
                self.listener_restart_not_before[target_id] = now + delay
                start_error_event: dict[str, Any] = {
                    "event": "listener_start_failed",
                    "event_at": now_iso(),
                    "target_id": target_id,
                    "target_type": str(target.get("type") or ""),
                    "attempt": attempt,
                    "backoff_seconds": delay,
                    "reason": reason,
                    "in_scope": listener.in_scope,
                }
                if listener.in_scope:
                    start_error_event["url"] = sanitize_url(
                        str(target.get("url") or "")
                    )
                self.store.append_target_event(start_error_event)
                log(
                    "WARN",
                    f"target={target_id[:8]} 监听启动失败；"
                    f"retry_after={delay:.2f}s reason={reason}",
                )

        with self.sessions_lock:
            stale_ids = [
                target_id
                for target_id in self.sessions
                if target_id not in active_ids
                and now - self.last_seen.get(target_id, now)
                >= self.stale_target_seconds
            ]
            stale = [self.sessions.pop(target_id) for target_id in stale_ids]
            for target_id in stale_ids:
                self.last_seen.pop(target_id, None)
                self.listener_restart_counts.pop(target_id, None)
                self.listener_restart_not_before.pop(target_id, None)
        for listener in stale:
            listener.close()

    def _discovery_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.discover_once()
            except Exception as exc:
                reason = sanitize_raw_text(repr(exc), max_string_chars=1_000)
                log("WARN", f"Target 发现循环异常，将继续重试：{reason}")
            self.stop_event.wait(self.scan_interval_seconds)

    def start(self) -> None:
        response = requests.get(f"{self.debug_http}/json/version", timeout=3)
        response.raise_for_status()
        version = response.json()
        log(
            "CDP",
            f"connected port={self.debug_port} browser={version.get('Browser', '')}",
        )
        self.discover_once()
        self.discovery_thread = threading.Thread(
            target=self._discovery_loop,
            name="ecommerce-cdp-discovery",
            daemon=True,
        )
        self.discovery_thread.start()
        log(
            "READY",
            f"platform={self.rules.platform} targets={len(self.sessions)} "
            f"output={self.output_path.resolve()}",
        )

    def save(self, *, capture_complete: bool, checkpoint: bool = False) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        document = self.store.build_document(
            rules=self.rules,
            debug_port=self.debug_port,
            profile_name=self.profile_name,
            label=self.label,
            started_at=self.started_at,
            capture_complete=capture_complete,
        )
        temporary = self.output_path.with_name(self.output_path.name + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.output_path)
        if checkpoint:
            log(
                "CHECKPOINT",
                f"records={document['summary']['network_records']} "
                f"path={self.output_path.resolve()}",
            )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通用电商 WebAPI HTTP 监听器：旁路捕获请求、响应、导航和下载事件"
    )
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument(
        "--ws-endpoint",
        "--cdp",
        dest="ws_endpoint",
        default=DEFAULT_WS_ENDPOINT,
        help="当前 Profile 的 browser CDP wsEndpoint；可修改脚本顶部默认常量",
    )
    endpoint.add_argument("--debug-port", type=int, help="CDP debug port")
    parser.add_argument(
        "--platform",
        default="generic",
        help="平台规则名或别名；使用 --list-platforms 查看，默认 generic",
    )
    parser.add_argument("--profile-name", default="", help="仅写入元数据的 Profile 名称")
    parser.add_argument("--label", default="", help="报表/本次捕获标签")
    parser.add_argument(
        "--rules-file",
        type=Path,
        default=DEFAULT_RULES_FILE,
        help=f"平台过滤规则 JSON，默认 {DEFAULT_RULES_FILE}",
    )
    parser.add_argument(
        "--include-domain",
        action="append",
        default=[],
        help="追加需要捕获的域名后缀，可重复使用",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="追加忽略的域名后缀，可重复使用",
    )
    parser.add_argument(
        "--exclude-url-regex",
        action="append",
        default=[],
        help="追加忽略 URL 的正则，可重复使用",
    )
    parser.add_argument(
        "--capture-all-http",
        action="store_true",
        help="忽略平台 include_domains，捕获所有 Target 的非静态 HTTP 请求",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "JSON 输出路径；默认自动写入 Git 根目录下 "
            ".codex_tmp/captures/<platform>_<report>_YYYYMMDD.json"
        ),
    )
    parser.add_argument(
        "--max-body-chars",
        type=int,
        default=1_000_000,
        help="每个文本响应体最多保存字符数，默认 1000000",
    )
    parser.add_argument(
        "--checkpoint-seconds",
        type=float,
        default=5.0,
        help="检查点写入间隔；0 表示关闭，默认 5 秒",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0.0,
        help="自动停止秒数；0 表示等 Ctrl+C，默认 0",
    )
    parser.add_argument(
        "--scan-interval-ms",
        type=float,
        default=100.0,
        help="发现新 Target 的间隔毫秒，默认 100",
    )
    parser.add_argument(
        "--stale-target-seconds",
        type=float,
        default=8.0,
        help="Target 暂时消失后的保留时间，默认 8 秒",
    )
    parser.add_argument(
        "--list-platforms",
        action="store_true",
        help="列出平台规则后退出，不连接 CDP",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行过滤和脱敏自检后退出，不连接 CDP",
    )
    return parser


def resolve_debug_port(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.debug_port is not None:
        if not 1 <= args.debug_port <= 65535:
            parser.error("--debug-port 必须在 1..65535")
        return args.debug_port
    if not args.ws_endpoint:
        parser.error("必须提供 --ws-endpoint/--cdp 或 --debug-port")
    parsed = urlparse(args.ws_endpoint)
    if not parsed.port:
        parser.error(f"无法从 wsEndpoint 解析端口：{args.ws_endpoint}")
    return parsed.port


def run_self_test(catalog: PlatformCatalog) -> None:
    rules = catalog.build_rules(
        "pinduoduo",
        include_domains=[],
        exclude_domains=[],
        exclude_url_regex=[],
        capture_all_http=False,
    )
    captured, _ = rules.evaluate(
        url="https://cashier.pinduoduo.com/templar/api/bill/query?date=2026-09-09",
        resource_type="XHR",
        source_url="https://cashier.pinduoduo.com/main/bills",
        target_in_scope=True,
    )
    assert captured
    captured, reason = rules.evaluate(
        url="https://img.pinduoduo.com/a/logo.png",
        resource_type="Image",
        source_url="https://mms.pinduoduo.com/home",
        target_in_scope=True,
    )
    assert not captured and reason == "ignored_resource_type"
    captured, reason = rules.evaluate(
        url="https://apm.pinduoduo.com/api/pmm/defined",
        resource_type="Fetch",
        source_url="https://mms.pinduoduo.com/home",
        target_in_scope=True,
    )
    assert not captured and reason in {"excluded_domain", "excluded_pattern"}
    captured, _ = rules.evaluate(
        url="https://unknown-api.example.com/export/create",
        resource_type="Fetch",
        source_url="https://yingxiao.pinduoduo.com/mains/account/report",
        target_in_scope=True,
    )
    assert captured

    tmall_rules = catalog.build_rules(
        "tmall",
        include_domains=[],
        exclude_domains=[],
        exclude_url_regex=[],
        capture_all_http=False,
    )
    captured, _ = tmall_rules.evaluate(
        url="https://h5api.m.taobao.com/h5/mtop.trade.query/1.0/?type=jsonp",
        resource_type="Script",
        source_url="https://myseller.taobao.com/home.htm",
        target_in_scope=True,
    )
    assert captured
    captured, reason = tmall_rules.evaluate(
        url="https://g.alicdn.com/app/static/main.js",
        resource_type="Script",
        source_url="https://myseller.taobao.com/home.htm",
        target_in_scope=True,
    )
    assert not captured and reason == "ignored_extension"

    safe_url = sanitize_url(
        "https://example.com/download?date=2026-09-09&ticket=abc&sign=xyz"
    )
    assert "date=2026-09-09" in safe_url
    assert "abc" not in safe_url and "xyz" not in safe_url
    safe_payload = sanitize_value(
        {
            "startDate": "2026-09-09",
            "token": "secret-token",
            "downloadUrl": "https://example.com/a.xls?sign=secret-sign",
        }
    )
    assert safe_payload["startDate"] == "2026-09-09"
    assert safe_payload["token"] == "***REDACTED***"
    assert "secret-sign" not in safe_payload["downloadUrl"]
    safe_error = sanitize_raw_text(
        "disconnect ws://127.0.0.1:60120/devtools/browser/secret-browser-id"
    )
    assert "secret-browser-id" not in safe_error
    assert "ws://***REDACTED***" in safe_error

    store = CaptureStore()
    store.append(
        {
            "record_type": "network",
            "capture_id": 1,
            "resource_type": "Fetch",
            "request": {
                "method": "POST",
                "url": "https://example.com/api/export",
                "has_post_data": True,
            },
            "response": {"status": 200, "mime_type": "application/json"},
            "response_body_available": True,
        }
    )
    summary = store.summary()
    assert summary["network_records"] == 1
    assert summary["responses_with_body"] == 1
    assert summary["endpoints"][0]["path"] == "/api/export"
    assert listener_restart_delay(1) == 0.25
    assert listener_restart_delay(2) == 0.5
    assert listener_restart_delay(99) == 5.0
    sample_capture = default_capture_path("pinduoduo", "订单")
    assert sample_capture.parent.name == "captures"
    assert sample_capture.parent.parent.name == ".codex_tmp"
    assert sample_capture.name.startswith("pdd_order_")

    class FakeListener:
        def __init__(
            self,
            *,
            alive: bool,
            in_scope: bool,
            start_error: bool = False,
        ) -> None:
            self.alive = alive
            self.in_scope = in_scope
            self.start_error = start_error
            self.last_error = "simulated disconnect"
            self.closed = False
            self.started = False
            self.start_calls = 0

        def update_target(self, target: dict[str, Any]) -> None:
            del target

        def is_alive(self) -> bool:
            return self.alive

        def uptime_seconds(self) -> float:
            return 0.0

        def close(self) -> None:
            self.closed = True

        def start(self) -> None:
            self.start_calls += 1
            if self.start_error:
                raise RuntimeError("simulated start failure")
            self.started = True
            self.alive = True

    test_manager = CaptureManager(
        debug_port=1,
        output_path=sample_capture,
        rules=rules,
        profile_name="self-test",
        label="订单",
        max_body_chars=1_000,
        scan_interval_seconds=0.1,
        stale_target_seconds=8.0,
    )
    target = {
        "id": "target-self-test",
        "type": "page",
        "url": "https://mms.pinduoduo.com/home",
        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/fake",
    }
    dead_listener = FakeListener(alive=False, in_scope=True)
    replacement_listener = FakeListener(alive=False, in_scope=True)
    test_manager.sessions[target["id"]] = dead_listener  # type: ignore[assignment]
    test_manager._fetch_targets = lambda: [target]  # type: ignore[method-assign]
    test_manager._create_listener = (  # type: ignore[method-assign]
        lambda current_target, inherited_scope: replacement_listener
    )
    test_manager.discover_once()
    assert dead_listener.closed
    assert replacement_listener.started
    assert test_manager.sessions[target["id"]] is replacement_listener
    _, target_events, _ = test_manager.store.snapshot()
    assert any(item.get("event") == "listener_restart" for item in target_events)

    start_failure_manager = CaptureManager(
        debug_port=1,
        output_path=sample_capture,
        rules=rules,
        profile_name="self-test",
        label="订单",
        max_body_chars=1_000,
        scan_interval_seconds=0.1,
        stale_target_seconds=8.0,
    )
    failing_listener = FakeListener(
        alive=False,
        in_scope=True,
        start_error=True,
    )
    start_failure_manager._fetch_targets = lambda: [target]  # type: ignore[method-assign]
    start_failure_manager._create_listener = (  # type: ignore[method-assign]
        lambda current_target, inherited_scope: failing_listener
    )
    start_failure_manager.discover_once()
    start_failure_manager.discover_once()
    assert failing_listener.start_calls == 1
    assert target["id"] not in start_failure_manager.sessions
    _, start_error_events, _ = start_failure_manager.store.snapshot()
    assert any(
        item.get("event") == "listener_start_failed"
        for item in start_error_events
    )

    json.dumps(
        store.build_document(
            rules=rules,
            debug_port=60120,
            profile_name="self-test",
            label="self-test",
            started_at=now_iso(),
            capture_complete=True,
        ),
        ensure_ascii=False,
    )
    log("SELF-TEST", "过滤、脱敏、默认 Capture 路径和重启退避通过")


def print_final_summary(summary: dict[str, Any]) -> None:
    log(
        "SUMMARY",
        f"network={summary['network_records']} "
        f"bodies={summary['responses_with_body']} "
        f"downloads={summary['download_events']} "
        f"targets={summary['target_events']}",
    )
    for endpoint in summary["endpoints"][:30]:
        statuses = ",".join(
            f"{key}:{value}" for key, value in endpoint["statuses"].items()
        ) or "-"
        log(
            "ENDPOINT",
            f"{endpoint['method']} {endpoint['host']}{endpoint['path']} "
            f"count={endpoint['count']} statuses={statuses} "
            f"ids={endpoint['capture_ids'][:8]}",
        )
    for skipped in summary["skipped_hosts"][:10]:
        log(
            "SKIPPED",
            f"{skipped['host']} reason={skipped['reason']} count={skipped['count']}",
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_body_chars <= 0:
        parser.error("--max-body-chars 必须大于 0")
    if args.checkpoint_seconds < 0:
        parser.error("--checkpoint-seconds 不能小于 0")
    if args.duration_seconds < 0:
        parser.error("--duration-seconds 不能小于 0")
    if args.scan_interval_ms <= 0:
        parser.error("--scan-interval-ms 必须大于 0")
    if args.stale_target_seconds < 0:
        parser.error("--stale-target-seconds 不能小于 0")

    try:
        catalog = PlatformCatalog(args.rules_file.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    if args.list_platforms:
        catalog.print_platforms()
        return 0
    if args.self_test:
        run_self_test(catalog)
        return 0

    try:
        rules = catalog.build_rules(
            args.platform,
            include_domains=args.include_domain,
            exclude_domains=args.exclude_domain,
            exclude_url_regex=args.exclude_url_regex,
            capture_all_http=args.capture_all_http,
        )
    except ValueError as exc:
        parser.error(str(exc))

    debug_port = resolve_debug_port(parser, args)
    if args.output is None:
        output_path = default_capture_path(rules.platform, args.label)
    else:
        output_path = (
            args.output if args.output.is_absolute() else Path.cwd() / args.output
        )
    manager = CaptureManager(
        debug_port=debug_port,
        output_path=output_path,
        rules=rules,
        profile_name=args.profile_name,
        label=args.label,
        max_body_chars=args.max_body_chars,
        scan_interval_seconds=args.scan_interval_ms / 1000,
        stale_target_seconds=args.stale_target_seconds,
    )

    log("START", f"platform={rules.platform} label={args.label or '-'}")
    log(
        "FILTER",
        "include="
        + (",".join(rules.include_domains) if rules.include_domains else "ALL_HTTP")
        + " exclude="
        + (",".join(rules.exclude_domains) if rules.exclude_domains else "-"),
    )
    try:
        manager.start()
    except (OSError, requests.RequestException, ValueError) as exc:
        log("FAILED", f"CDP 连接失败：{exc}")
        return 1

    capture_complete = False
    started_monotonic = time.monotonic()
    next_checkpoint = (
        started_monotonic + args.checkpoint_seconds
        if args.checkpoint_seconds > 0
        else float("inf")
    )
    try:
        while True:
            time.sleep(0.25)
            now = time.monotonic()
            if args.duration_seconds > 0 and (
                now - started_monotonic >= args.duration_seconds
            ):
                log("STOP", f"达到 --duration-seconds={args.duration_seconds}")
                capture_complete = True
                break
            if now >= next_checkpoint:
                try:
                    manager.save(capture_complete=False, checkpoint=True)
                except OSError as exc:
                    log("WARN", f"检查点写入失败：{exc}")
                next_checkpoint = now + args.checkpoint_seconds
    except KeyboardInterrupt:
        log("STOP", "收到 Ctrl+C，正在完成未决请求并写入最终 JSON")
        capture_complete = True
    except Exception as exc:
        log("FAILED", f"监听主循环异常：{exc!r}")
    finally:
        manager.stop()
        try:
            saved = manager.save(capture_complete=capture_complete)
        except OSError as exc:
            log("FAILED", f"最终 JSON 写入失败：{exc}")
            return 1
        summary = manager.store.summary()
        log("SAVED", str(saved))
        print_final_summary(summary)

    return 0 if capture_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
