"""Generic failures use existing Feishu transport, never the slider channel.

Configuration is borrowed through read-only transactions. No legacy run, outbox,
audit, or challenge record is created here. Real login challenges stay in the
unchanged legacy login adapter.
"""
from __future__ import annotations

import contextlib
import asyncio
import os

from ...core.errors import redact
from .environment import prepare
from .verification import NAMES


class ReadonlyConfiguration:
    @contextlib.contextmanager
    def transaction(self):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        connection = psycopg2.connect(host=os.getenv("PGHOST", "192.168.77.111"),
            port=int(os.getenv("PGPORT", "5432")), dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"), connect_timeout=5)
        try:
            connection.set_session(readonly=True)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        finally:
            connection.rollback()
            connection.close()


def failure_message(service, relay, profile, purpose):
    return service._automation_run_notification_message(relay, {
        "status": "failed", "job_name": "Commerce API 报表下载",
        "platform_name": NAMES[profile.platform], "shop_name": profile.shop,
        "error_message": redact(purpose),
    })


def _send(profile, purpose):
    prepare()
    from apps.ai_analysis.crypto import SecretCipher
    from apps.feishu_ai.service import FeishuService
    service = FeishuService(ReadonlyConfiguration(), SecretCipher())
    try:
        relay = service._select_verification_relay(NAMES[profile.platform])
        if not relay:
            return False
        app = service._app(relay["feishu_app_id"])
        service._send_post_to_chat(app, relay["chat_id"], failure_message(service, relay, profile, purpose))
        return True
    finally:
        service.close()


async def notify(profile, purpose: str) -> bool:
    try:
        return await asyncio.to_thread(_send, profile, purpose)
    except Exception:
        return False
