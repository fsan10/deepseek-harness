# -*- coding: utf-8 -*-
"""自动化任务与飞书验证码转发服务之间的最小客户端。

服务端只返回已加密存储后解密的临时答案；本模块不记录令牌、验证码或密码。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any
from .component_runtime import automation_component, component_event
from .outcomes import NeedsHumanError, NeedsHumanTimeout

DEFAULT_RELAY_URL = "http://127.0.0.1:8770"
DEFAULT_TOKEN_ENV = "AUTOMATION_ROBOT_TOKEN"


def json_request(url: str, *, method: str = "GET", token: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"自动化验证码服务 HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"自动化验证码服务不可用：{exc}") from exc
    if int(data.get("code", 0)) != 0:
        raise RuntimeError(str(data.get("message") or "自动化验证码服务请求失败"))
    return data.get("data") or {}


def relay_settings() -> tuple[str, str]:
    base_url = os.getenv("AUTOMATION_RELAY_URL", DEFAULT_RELAY_URL).rstrip("/")
    token_env = os.getenv("AUTOMATION_RELAY_TOKEN_ENV", DEFAULT_TOKEN_ENV)
    token = os.getenv(token_env, "") or os.getenv("INGEST_ROBOT_TOKEN", "")
    if not token:
        raise RuntimeError(f"未设置自动化验证码转发令牌（{token_env}）")
    return base_url, token


def probe_relay() -> None:
    """确认转发服务和令牌可用，但不创建 Challenge 或发送群消息。

    自动化接口没有单独的匿名健康检查接口；对 Challenge 集合发 GET 会经过
    同样的 Bearer 鉴权并返回 404（该路径只支持 POST）。404 在这里代表服务
    已连通，其他 HTTP 错误则按真实前置依赖失败处理。
    """

    base_url, token = relay_settings()
    request = urllib.request.Request(
        f"{base_url}/api/automation/verification/challenges",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 405}:
            return
        if exc.code in {401, 403}:
            raise RuntimeError("自动化验证码服务令牌无效或无权访问") from exc
        raise RuntimeError(f"自动化验证码服务 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"自动化验证码服务不可用：{exc}") from exc


async def create_challenge(
    *,
    challenge_type: str,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
    page_url: str = "",
    timeout_seconds: int | None = None,
    business_reference: str = "",
    force_human: bool = False,
    defer_human_notice: bool = False,
) -> dict[str, Any]:
    """创建一个有类型的 Challenge，返回短期 challenge_id 和等待时长。"""

    if challenge_type not in {"verification_code", "archive_password"}:
        raise ValueError(f"不支持的 Challenge 类型：{challenge_type}")
    base_url, token = relay_settings()
    payload: dict[str, Any] = {
        "challenge_type": challenge_type,
        "platform": platform,
        "company": company,
        "shop": shop,
        "purpose": purpose,
        "page_url": page_url,
        "business_reference": business_reference,
        "force_human": force_human,
        "defer_human_notice": defer_human_notice,
    }
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    return await asyncio.to_thread(json_request,
        f"{base_url}/api/automation/verification/challenges",
        method="POST",
        token=token,
        payload=payload,
    )


async def reject_answer(challenge_id: str) -> dict[str, Any]:
    """Keep the original five-minute deadline and request a human replacement."""
    base_url, token = relay_settings()
    return await asyncio.to_thread(json_request,
        f"{base_url}/api/automation/verification/challenges/{challenge_id}/reject",
        method="POST", token=token, payload={},
    )


async def reopen_for_human(state: dict[str, Any], challenge_key: str) -> None:
    challenge_id = str(state.get(challenge_key + "_last_answered") or state.get(challenge_key) or "")
    if challenge_id:
        await reject_answer(challenge_id)
        state[challenge_key] = challenge_id
        state.pop(challenge_key + "_last_answered", None)


async def resume_challenge(challenge_id: str) -> dict[str, Any]:
    """Explicit recovery asks for a fresh human notice without losing an answer."""
    base_url, token = relay_settings()
    return await asyncio.to_thread(json_request,
        f"{base_url}/api/automation/verification/challenges/{challenge_id}/resume",
        method="POST", token=token, payload={},
    )


async def cancel_challenge(challenge_id: str) -> None:
    base_url, token = relay_settings()
    await asyncio.to_thread(json_request,
        f"{base_url}/api/automation/verification/challenges/{challenge_id}/cancel",
        method="POST", token=token, payload={},
    )


async def notify_human_handoff(
    *,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
) -> None:
    """Send a human-handoff notice without creating an answer challenge."""

    base_url, token = relay_settings()
    await asyncio.to_thread(
        json_request,
        f"{base_url}/api/automation/verification/notices",
        method="POST",
        token=token,
        payload={
            "platform": platform,
            "company": company,
            "shop": shop,
            "purpose": purpose,
        },
    )


async def wait_answer(
    *,
    challenge_id: str,
    timeout_seconds: int | None = None,
) -> str:
    """轮询已有 Challenge；用于进程重启后复用未完成请求。"""

    if not challenge_id:
        raise ValueError("challenge_id 不能为空")
    base_url, token = relay_settings()
    timeout = max(1, min(300, int(timeout_seconds or 300)))
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        state = await asyncio.to_thread(json_request,
            f"{base_url}/api/automation/verification/challenges/{challenge_id}",
            token=token,
        )
        status = state.get("status")
        if status == "answered":
            answer = str(state.get("answer") or "").strip()
            if not answer:
                raise RuntimeError("自动化验证码服务返回空答案")
            return answer
        if status in {"expired", "cancelled"}:
            raise NeedsHumanError("自动化 Challenge 已过期或被取消；保留原任务和文件供恢复")
        await asyncio.sleep(2)
    raise NeedsHumanTimeout(f"等待自动化 Challenge 超过 {timeout} 秒；保留原任务和文件供恢复")


@automation_component("human.verification.wait", "等待飞书验证码 / 密码", category="human")
async def request_answer(
    *,
    challenge_type: str,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
    page_url: str = "",
    timeout_seconds: int | None = None,
    challenge_id: str | None = None,
) -> str:
    """创建并等待有类型的 Challenge；传入 challenge_id 时复用已有请求。"""

    if challenge_id:
        component_event("waiting_human", "复用已有 Challenge，等待自动接收或人工回复", detail={"challenge_id": challenge_id, "challenge_type": challenge_type})
        answer = await wait_answer(challenge_id=challenge_id, timeout_seconds=timeout_seconds)
        component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
        return answer
    challenge = await create_challenge(
        challenge_type=challenge_type, platform=platform, company=company, shop=shop,
        purpose=purpose, page_url=page_url, timeout_seconds=timeout_seconds,
    )
    challenge_id = str(challenge.get("challenge_id") or "")
    if not challenge_id:
        raise RuntimeError("自动化验证码服务未返回 challenge_id")
    component_event("waiting_human", "Challenge 已创建，等待自动接收或人工回复", detail={"challenge_id": challenge_id, "challenge_type": challenge_type})
    answer = await wait_answer(
        challenge_id=challenge_id,
        timeout_seconds=int(challenge.get("timeout_seconds") or timeout_seconds or 300),
    )
    component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
    return answer
