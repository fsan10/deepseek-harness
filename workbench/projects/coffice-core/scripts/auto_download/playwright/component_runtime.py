# -*- coding: utf-8 -*-
"""Structured component telemetry for Playwright automation scripts.

Component events are emitted as a single JSON line on stdout. DownloadController
recognises the prefix and forwards the payload to AutomationWorker, so legacy
scripts remain compatible while migrated functions gain component-level
observability without opening a second network channel.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
import functools
import inspect
import json
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Callable, TypeVar


COMPONENT_EVENT_PREFIX = "__MOCK_AUTOMATION_COMPONENT__:"
_CURRENT_COMPONENT_KEY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "automation_component_key", default=None
)
_CURRENT_COMPONENT_CODE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "automation_component_code", default=None
)
_EVENT_SINK: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    "automation_component_event_sink", default=None
)
_SUPPRESS_STDOUT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "automation_component_suppress_stdout", default=False
)

F = TypeVar("F", bound=Callable[..., Any])
_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|secret|authorization|cookie|验证码|密码)\s*[:=]\s*([^\s,;]+)"
)


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _redact(value: Any) -> str:
    text = str(value or "")
    return _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}=<redacted>", text)[:4000]


def _page_url(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    for value in [*args, *kwargs.values()]:
        try:
            url = getattr(value, "url", None)
        except Exception:
            url = None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url[:2000]
    explicit = kwargs.get("page_url")
    return str(explicit)[:2000] if explicit else None


def classify_error(exc: BaseException) -> str:
    if getattr(exc, 'requires_human', False):
        return "NEEDS_HUMAN"
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    text = str(exc).lower()
    if "selector" in text or "locator" in text or "not visible" in text or "未找到" in text:
        return "SELECTOR_NOT_FOUND"
    if "login" in text or "登录" in text:
        return "LOGIN_EXPIRED"
    if "challenge" in text or "验证码" in text or "人工" in text:
        return "HUMAN_INTERACTION_FAILED"
    if "download" in text or "下载" in text:
        return "DOWNLOAD_FAILED"
    if "schema" in text or "表头" in text or "字段" in text:
        return "REPORT_SCHEMA_CHANGED"
    if "network" in text or "http " in text:
        return "NETWORK_ERROR"
    return type(exc).__name__.upper()[:80] or "COMPONENT_ERROR"


@contextmanager
def component_event_sink(
    sink: Callable[[dict[str, Any]], None],
    *,
    suppress_stdout: bool = True,
):
    """Route component telemetry to an in-process consumer.

    Legacy subprocess execution still writes JSON lines to stdout. FlowRunner
    uses this bridge so the same decorators/events can be persisted directly
    without parsing its own stdout or duplicating Challenge instrumentation.
    """

    token_sink = _EVENT_SINK.set(sink)
    token_stdout = _SUPPRESS_STDOUT.set(bool(suppress_stdout))
    try:
        yield
    finally:
        _SUPPRESS_STDOUT.reset(token_stdout)
        _EVENT_SINK.reset(token_sink)


@contextmanager
def component_parent_context(run_key: str, component_code: str | None = None):
    """Expose an externally-created component as parent of decorated calls."""

    token_key = _CURRENT_COMPONENT_KEY.set(run_key)
    token_code = _CURRENT_COMPONENT_CODE.set(component_code)
    try:
        yield
    finally:
        _CURRENT_COMPONENT_CODE.reset(token_code)
        _CURRENT_COMPONENT_KEY.reset(token_key)


def emit_component_event(event: str, **payload: Any) -> None:
    if os.getenv("MOCK_AUTOMATION_COMPONENT_TELEMETRY", "1").strip().lower() in {"0", "false", "off", "no"}:
        return
    body = {
        "event": event,
        "emitted_at": _timestamp(),
        "component_run_key": payload.pop("component_run_key", None) or _CURRENT_COMPONENT_KEY.get(),
        "component_code": payload.pop("component_code", None) or _CURRENT_COMPONENT_CODE.get(),
        **payload,
    }
    sink = _EVENT_SINK.get()
    if sink is not None:
        sink(dict(body))
    if _SUPPRESS_STDOUT.get():
        return
    print(
        COMPONENT_EVENT_PREFIX + json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str),
        flush=True,
    )


def component_event(action: str, message: str = "", *, detail: dict[str, Any] | None = None) -> None:
    """Emit a safe internal event for the currently executing component.

    Never put passwords, verification answers, cookies or tokens in detail.
    """

    emit_component_event(
        "component_event",
        action=str(action or "observation")[:80],
        message=_redact(message),
        detail=detail or {},
    )


def automation_component(
    code: str,
    name: str,
    *,
    category: str = "business",
    version: str = "1.0.0",
) -> Callable[[F], F]:
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,119}", code):
        raise ValueError(f"invalid automation component code: {code}")

    def decorator(func: F) -> F:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any):
                run_key = str(uuid.uuid4())
                parent_run_key = _CURRENT_COMPONENT_KEY.get()
                token_key = _CURRENT_COMPONENT_KEY.set(run_key)
                token_code = _CURRENT_COMPONENT_CODE.set(code)
                started = time.perf_counter()
                emit_component_event(
                    "component_started",
                    component_run_key=run_key,
                    parent_component_run_key=parent_run_key,
                    component_code=code,
                    component_name=name,
                    component_version=version,
                    category=category,
                    page_url=_page_url(args, kwargs),
                )
                try:
                    result = await func(*args, **kwargs)
                except BaseException as exc:
                    emit_component_event(
                        "component_failed",
                        component_run_key=run_key,
                        component_code=code,
                        component_name=name,
                        component_version=version,
                        category=category,
                        duration_seconds=round(time.perf_counter() - started, 3),
                        error_type=classify_error(exc),
                        error_message=_redact(exc),
                        page_url=_page_url(args, kwargs),
                    )
                    raise
                else:
                    emit_component_event(
                        "component_succeeded",
                        component_run_key=run_key,
                        component_code=code,
                        component_name=name,
                        component_version=version,
                        category=category,
                        duration_seconds=round(time.perf_counter() - started, 3),
                        page_url=_page_url(args, kwargs),
                    )
                    return result
                finally:
                    _CURRENT_COMPONENT_CODE.reset(token_code)
                    _CURRENT_COMPONENT_KEY.reset(token_key)
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any):
            run_key = str(uuid.uuid4())
            parent_run_key = _CURRENT_COMPONENT_KEY.get()
            token_key = _CURRENT_COMPONENT_KEY.set(run_key)
            token_code = _CURRENT_COMPONENT_CODE.set(code)
            started = time.perf_counter()
            emit_component_event(
                "component_started",
                component_run_key=run_key,
                parent_component_run_key=parent_run_key,
                component_code=code,
                component_name=name,
                component_version=version,
                category=category,
                page_url=_page_url(args, kwargs),
            )
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                emit_component_event(
                    "component_failed",
                    component_run_key=run_key,
                    parent_component_run_key=parent_run_key,
                    component_code=code,
                    component_name=name,
                    component_version=version,
                    category=category,
                    duration_seconds=round(time.perf_counter() - started, 3),
                    error_type=classify_error(exc),
                    error_message=_redact(exc),
                    page_url=_page_url(args, kwargs),
                )
                raise
            else:
                emit_component_event(
                    "component_succeeded",
                    component_run_key=run_key,
                    parent_component_run_key=parent_run_key,
                    component_code=code,
                    component_name=name,
                    component_version=version,
                    category=category,
                    duration_seconds=round(time.perf_counter() - started, 3),
                    page_url=_page_url(args, kwargs),
                )
                return result
            finally:
                _CURRENT_COMPONENT_CODE.reset(token_code)
                _CURRENT_COMPONENT_KEY.reset(token_key)
        return sync_wrapper  # type: ignore[return-value]

    return decorator
