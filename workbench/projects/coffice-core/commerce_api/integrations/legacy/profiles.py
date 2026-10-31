"""Exact Profile discovery; preserve legacy disabled-shop policy."""
from __future__ import annotations

import json
import re

from ...core.contracts import Profile
from ...core.errors import ContractError, IntegrationUnavailable, UsageError, redact
from .environment import prepare

PLATFORM_IDS = {"抖音": "douyin", "京东": "jd", "拼多多": "pinduoduo", "快手": "kuaishou", "小红书": "xiaohongshu", "天猫": "tmall"}


def client():
    prepare()
    import os
    from ReverseAPI.Formal_Script.profile_cdp import CloakMcpClient, ProfileResolutionError
    instance = CloakMcpClient(os.environ.get("CLOAK_MCP_URL", "http://127.0.0.1:19610/mcp"), 20)
    try:
        instance.initialize()
    except ProfileResolutionError as exc:
        raise IntegrationUnavailable("Cloak Login 连接尚未就绪", stage="profile",
            hint="请打开 Cloak Login 并启用原 MCP 后重试",
            details={"reason": redact(exc)}) from None
    return instance


def list_profiles() -> list[Profile]:
    root = prepare()
    records = client().call("list_profiles", {})
    if isinstance(records, dict):
        records = records.get("profiles", records.get("data", []))
    if not isinstance(records, list):
        raise ContractError("Cloak Profile 清单结构异常")
    settings = json.loads((root / "scripts/auto_download/all_platform_downloads.json").read_text(encoding="utf-8"))
    statuses = settings.get("profile_status", {})
    result = []
    for record in records:
        if not isinstance(record, dict):
            continue
        note = str(record.get("note") or record.get("notes") or "")
        match = re.fullmatch(r"platform=([^;]+);company=([^;]+);shop=([^;]+)", note)
        if not match or match[1] not in PLATFORM_IDS:
            continue
        name = str(record.get("name") or "")
        policy = statuses.get(name, {})
        enabled = policy.get("enabled", True) is not False and str(policy.get("status", "active")).casefold() in {"active", "enabled", "正常", "启用", "运行"}
        result.append(Profile(str(record.get("id") or record.get("profileId") or ""), name,
                              PLATFORM_IDS[match[1]], match[2], match[3], enabled))
    return result


def select_profile(name: str, platform: str, *, records=None) -> Profile:
    candidates = [p for p in (records if records is not None else list_profiles()) if p.name == name]
    if len(candidates) != 1:
        raise UsageError("Profile 名称必须完整且唯一匹配")
    result = candidates[0]
    if result.platform != platform:
        raise UsageError("Profile 备注中的平台与命令平台不一致")
    if not result.enabled:
        raise UsageError("该 Profile 已在现有配置中停用，禁止自动恢复启用")
    return result


def resolve_connection(profile: Profile):
    prepare()
    from ReverseAPI.Formal_Script.profile_cdp import ProfileResolutionError, resolve_profile_connection
    try:
        return resolve_profile_connection(profile_name=profile.name)
    except ProfileResolutionError as exc:
        raise IntegrationUnavailable("无法取得指定 Profile 的登录连接", stage="profile",
            hint="请检查 Cloak Login、MCP 和原 Profile；处理后续跑原任务",
            details={"reason": redact(exc)}) from None
