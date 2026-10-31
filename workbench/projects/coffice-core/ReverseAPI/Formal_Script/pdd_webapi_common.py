#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼多多 WebAPI 下载器共享的异常、日志和原始文件落盘能力。"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "downloads"
HUMAN_ERROR_MARKERS = (
    "登录失效",
    "登录异常",
    "请先登录",
    "未登录",
    "权限不足",
    "无权限",
    "验证码",
    "安全验证",
    "风险验证",
    "身份验证",
)


class NeedsHumanError(RuntimeError):
    """登录、权限或安全验证需要用户处理。"""


class ApiError(RuntimeError):
    """拼多多 WebAPI 的 HTTP、JSON 结构或业务响应异常。"""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        path: str = "",
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.path = path
        self.body = body


def log(report: str, stage: str, message: str) -> None:
    """输出不含动态凭据的统一三段式日志。"""

    print(f"[PDD][{report}][{stage}] {message}", flush=True)


def is_human_error_message(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in HUMAN_ERROR_MARKERS)


def unique_path(path: Path) -> Path:
    """保留历史文件，为本次下载分配唯一文件名。"""

    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"输出目录中同名文件过多：{path.name}")


def _add_cookies(
    session: requests.Session,
    cookies: Iterable[Mapping[str, Any]] | None,
) -> None:
    for cookie in cookies or ():
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        kwargs: dict[str, str] = {"path": str(cookie.get("path") or "/")}
        domain = cookie.get("domain")
        if domain:
            kwargs["domain"] = str(domain)
        try:
            session.cookies.set(str(name), str(value), **kwargs)
        except (TypeError, ValueError):
            session.cookies.set(str(name), str(value))


def download_original_file(
    url: str,
    output_dir: Path,
    filename: str,
    *,
    headers: Mapping[str, str] | None = None,
    cookies: Iterable[Mapping[str, Any]] | None = None,
    proxy: str | None = None,
    timeout: tuple[float, float] = (15, 180),
) -> Path:
    """将平台原始文件写入同目录 ``.part``，成功后原子落盘。"""

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("接口未返回有效的 HTTP 下载地址")

    resolved_dir = Path(output_dir).expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(resolved_dir / filename)
    temporary = target.with_name(target.name + ".part")
    session = requests.Session()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    _add_cookies(session, cookies)

    try:
        with session.get(
            url,
            headers=dict(headers or {}),
            stream=True,
            timeout=timeout,
        ) as response:
            if response.status_code in {401, 403}:
                raise NeedsHumanError(
                    f"短效文件下载返回 HTTP {response.status_code}，请刷新登录态后重试"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"原始文件下载返回 HTTP {response.status_code}")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        stream.write(chunk)

        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("原始文件下载为空")
        temporary.replace(target)
        return target.resolve()
    except requests.RequestException as exc:
        with suppress(OSError):
            temporary.unlink()
        raise RuntimeError(f"原始文件下载失败：{type(exc).__name__}") from exc
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    finally:
        session.close()


__all__ = [
    "ApiError",
    "DEFAULT_OUTPUT_DIR",
    "NeedsHumanError",
    "PROJECT_ROOT",
    "download_original_file",
    "is_human_error_message",
    "log",
    "unique_path",
]
