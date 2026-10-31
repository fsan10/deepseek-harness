"""Read/write the master download config that Codex executes every morning.

The JSON file (``scripts/auto_download/all_platform_downloads.json``) is the single
source of truth for *which profiles run*: Codex reads ``profile_status`` before it
starts the controller, so the console must write the same file instead of keeping a
parallel copy in PostgreSQL.

Layout added by the console (ignored by the controller, which only validates
``enabled`` / ``status`` / ``reason``)::

    "profile_status": {
      "DY-抖音-MOCK冲饮旗舰店": {
        "enabled": true,
        "status": "active",
        "reason": "",
        "reports": {"douyin_qianchuan": false}
      }
    }

``reports`` narrows the console's target set (completion stats and manual backfill).
The nightly controller still walks its full step list; the switch is a target/statistics
scope, not a change to the download script.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .registry import DOWNLOAD_CONFIG

_LOCK = threading.Lock()
DISABLED_STATUS = "disabled"
ENABLED_STATUS = "active"
_ACTIVE_CACHE: frozenset[str] | None = None


def config_path(path: Path | str | None = None) -> Path:
    return Path(path or os.getenv("AUTOMATION_DOWNLOAD_CONFIG") or DOWNLOAD_CONFIG)


def load_settings(path: Path | str | None = None) -> dict:
    target = config_path(path)
    try:
        with target.open("r", encoding="utf-8") as stream:
            config = json.load(stream)
    except FileNotFoundError as exc:
        raise ValueError(f"总控配置文件不存在：{target}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"总控配置不是有效 JSON：{target}；{exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("总控配置顶层必须是 JSON 对象")
    statuses = config.get("profile_status")
    if statuses is None:
        config["profile_status"] = {}
    elif not isinstance(statuses, dict):
        raise ValueError("总控配置 profile_status 必须是 JSON 对象")
    return config


def active_status_values() -> frozenset[str]:
    global _ACTIVE_CACHE
    if _ACTIVE_CACHE is None:
        from scripts.auto_download.run_all_platform_downloads import ACTIVE_PROFILE_STATUS_VALUES

        _ACTIVE_CACHE = frozenset(item.casefold() for item in ACTIVE_PROFILE_STATUS_VALUES)
    return _ACTIVE_CACHE


def profile_entry(config: dict, profile_name: str) -> dict:
    entry = (config.get("profile_status") or {}).get(profile_name) or {}
    return entry if isinstance(entry, dict) else {}


def profile_enabled(config: dict, profile_name: str) -> bool:
    entry = profile_entry(config, profile_name)
    enabled = entry.get("enabled", True)
    status = str(entry.get("status") or "active")
    return bool(enabled) and status.casefold() in active_status_values()


def profile_reason(config: dict, profile_name: str) -> str | None:
    entry = profile_entry(config, profile_name)
    if profile_enabled(config, profile_name):
        return None
    reason = entry.get("reason")
    return str(reason) if reason else "该店铺已在报表任务中停用"


def report_enabled(config: dict, profile_name: str, report_type: str) -> bool:
    entry = profile_entry(config, profile_name)
    reports = entry.get("reports")
    if not isinstance(reports, dict):
        return True
    return bool(reports.get(report_type, True))


def disabled_reports(config: dict, profile_name: str) -> set[str]:
    entry = profile_entry(config, profile_name)
    reports = entry.get("reports")
    if not isinstance(reports, dict):
        return set()
    return {str(key) for key, value in reports.items() if value is False}


def _validate(profile_name: str, reports: dict | None) -> dict[str, bool]:
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("profile_name 必须是非空字符串")
    cleaned: dict[str, bool] = {}
    for key, value in (reports or {}).items():
        if not isinstance(key, str) or not key.strip() or len(key) > 64:
            raise ValueError("报表类型必须是非空字符串（≤64 字符）")
        if not isinstance(value, bool):
            raise ValueError("报表启停值必须是布尔值")
        cleaned[key.strip()] = value
    return cleaned


def _write(config: dict, path: Path) -> None:
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def update_profile_settings(
    profile_name: str,
    *,
    enabled: bool | None = None,
    reports: dict | None = None,
    reason: str = "",
    path: Path | str | None = None,
) -> dict:
    """Patch ``profile_status[profile_name]`` and return the reloaded config."""

    cleaned = _validate(profile_name, reports)
    if enabled is None and not cleaned:
        raise ValueError("没有需要保存的设置")
    target = config_path(path)
    with _LOCK:
        config = load_settings(target)
        statuses = config.setdefault("profile_status", {})
        entry = dict(statuses.get(profile_name) or {})
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("enabled 必须是布尔值")
            entry["enabled"] = enabled
            entry["status"] = ENABLED_STATUS if enabled else DISABLED_STATUS
            entry["reason"] = (reason or "") if enabled else (reason or "报表任务页停用每日下载")
        if cleaned:
            merged = dict(entry.get("reports") or {})
            merged.update(cleaned)
            entry["reports"] = merged
        if not entry:
            raise ValueError("没有需要保存的设置")
        statuses[profile_name] = entry
        _write(config, target)
    return load_settings(target)
