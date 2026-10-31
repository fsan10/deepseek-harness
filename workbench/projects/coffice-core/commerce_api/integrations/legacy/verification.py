"""Keep the existing group notification, reply, expiry and resume service."""
from __future__ import annotations

import asyncio
import contextlib
import io

from ...core.errors import ChallengeExpired, ContractError, NeedsHuman, NetworkError, redact
from .environment import prepare

NAMES = {"douyin": "抖音", "jd": "京东", "pinduoduo": "拼多多", "kuaishou": "快手", "xiaohongshu": "小红书", "tmall": "天猫"}


def relay():
    prepare()
    from scripts.auto_download.playwright import automation_challenge
    return automation_challenge


async def create(profile, *, purpose: str, kind="verification_code", reference="", defer_human_notice=False, force_human=False) -> dict:
    try:
        service = relay()
        phase = "probe"
        await asyncio.to_thread(service.probe_relay)
        phase = "create_challenge"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return await service.create_challenge(challenge_type=kind, platform=NAMES[profile.platform],
                company=profile.company, shop=profile.shop, purpose=purpose, business_reference=reference,
                defer_human_notice=defer_human_notice, force_human=force_human)
    except Exception as exc:
        import traceback
        import json
        reason = str(exc)
        if "{" in reason:
            try:
                reason = str(json.loads(reason[reason.index("{"):]).get("message") or "转发服务返回错误")
            except ValueError:
                reason = "转发服务返回错误"
        status = getattr(exc.__cause__, "code", None)
        error = ContractError if status == 400 else NetworkError
        message = "原有验证码服务拒绝本次请求，未触发平台发送" if status == 400 else "现有验证码服务不可用，未触发平台发送"
        raise error(message, stage="verification",
            details={"phase": locals().get("phase", "configuration"), "cause": type(exc).__name__,
                     "reason": redact(reason)[:160], "http_status": status,
                     "steps": [f.name for f in traceback.extract_tb(exc.__traceback__)[-4:]]}) from None


async def answer(challenge_id: str, *, timeout_seconds=300) -> str:
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return await relay().wait_answer(challenge_id=challenge_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if "过期" in str(exc) or "取消" in str(exc):
            raise ChallengeExpired("原有接收请求已失效，保留原平台任务", stage="verification") from None
        raise NeedsHuman("原有群回复流程尚未提供有效答案，已保留 Challenge 和导出任务", stage="verification") from None


async def reject(challenge_id):
    try:
        await relay().reject_answer(challenge_id)
    except Exception:
        raise NeedsHuman("需要在原群中更正验证码或文件密码，已保留原任务", stage="verification") from None


async def cancel(challenge_id):
    try:
        await relay().cancel_challenge(challenge_id)
    except Exception:
        raise NeedsHuman("旧密码接收通道尚未取消，保留现场以避免验证码与密码串线", stage="verification") from None
