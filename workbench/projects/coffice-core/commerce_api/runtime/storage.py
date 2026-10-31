"""Owned project paths, atomic state writes and cross-process file locks."""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from ..core.errors import LockBusy, UsageError

PROJECT = Path(__file__).resolve().parents[1]


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", value):
        raise UsageError("本地标识仅允许字母、数字、下划线和连字符")
    return value


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class Paths:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or PROJECT / ".runtime").resolve()

    def file(self, area: str, identifier: str, suffix: str = ".json") -> Path:
        return self.root / area / (safe_id(identifier) + suffix)


@contextlib.contextmanager
def file_lock(path: Path, *, timeout: float = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b" ")
            handle.flush()
        deadline = time.monotonic() + timeout
        acquired = False
        try:
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise LockBusy("相同账户的任务正在执行，请等待后续跑") from None
                    time.sleep(.1)
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_UN)
