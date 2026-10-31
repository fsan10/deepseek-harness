"""Windows 当前用户 DPAPI 加密会话；磁盘上不出现明文 Cookie。"""
from __future__ import annotations

import ctypes
import contextlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from .review_config import PROJECT
from .review_errors import AuthRequired, AuthStoreError


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise AuthStoreError("会话存储目前需要 Windows DPAPI；不允许降级为明文保存")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), "kefu-review-session", None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise AuthStoreError("无法读取或保护登录会话，请使用同一 Windows 用户重新登录")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


class SessionStore:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or os.environ.get("COLLECTION_AUTH_DIR") or PROJECT / "data" / "collection-auth")
        self.legacy_directories = [] if directory is not None else [
            Path(os.environ.get("REVIEWS_AUTH_DIR") or PROJECT / "data" / "review-auth"),
            Path(os.environ.get("METRICS_AUTH_DIR") or PROJECT / "data" / "metric-auth")]

    def _path(self, profile_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", profile_id):
            raise AuthStoreError("profile 标识无效")
        return self.directory / f"{profile_id}.enc"

    def load(self, profile_id: str) -> dict:
        path = self._path(profile_id)
        if not path.exists():
            with self._locked(profile_id):
                if not path.exists():
                    candidates = [directory / path.name for directory in self.legacy_directories if (directory / path.name).is_file()]
                    if not candidates:
                        raise AuthRequired("该店铺尚未保存登录会话，请先执行登录操作")
                    # 仅迁移当前 profile 最近保存的加密会话；不读取其他账号，不降级为明文。
                    value = self._read(max(candidates, key=lambda item: item.stat().st_mtime), profile_id)
                    self._write(profile_id, value)
        return self._read(path, profile_id)

    def _read(self, path: Path, profile_id: str) -> dict:
        try:
            value = json.loads(_dpapi(path.read_bytes(), decrypt=True))
            if value.get("version") != 1 or value.get("profile_id") != profile_id or not value.get("cookies") or not value.get("user_agent"):
                raise ValueError("invalid session")
            return value
        except AuthStoreError:
            raise
        except Exception:
            raise AuthStoreError("登录会话文件损坏，请重新登录") from None

    def save(self, profile_id: str, value: dict):
        with self._locked(profile_id):
            self._write(profile_id, value)

    def refresh(self, profile_id: str, value: dict) -> bool:
        """只更新同一代会话；并行重新登录或注销后，旧请求不得覆盖新凭据。"""
        with self._locked(profile_id):
            try:
                path = self._path(profile_id)
                if not path.exists(): return False
                current = self._read(path, profile_id)
            except AuthRequired:
                return False
            if not value.get("session_id") or current.get("session_id") != value["session_id"]:
                return False
            self._write(profile_id, value)
            return True

    @contextlib.contextmanager
    def _locked(self, profile_id: str):
        if os.name != "nt":
            raise AuthStoreError("会话存储目前需要 Windows DPAPI")
        import msvcrt
        lock_path = self._path(profile_id).with_suffix(".lock")
        self.directory.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if lock_path.stat().st_size == 0:
                handle.write(b" "); handle.flush()
            for attempt in range(100):
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 99: raise AuthStoreError("登录会话正在更新，请稍后重试") from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _write(self, profile_id: str, value: dict):
        path = self._path(profile_id)
        encrypted = _dpapi(json.dumps({**value, "version": 1, "profile_id": profile_id}, ensure_ascii=False).encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{profile_id}-{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as target:
                target.write(encrypted); target.flush(); os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self, profile_id: str):
        with self._locked(profile_id):
            path = self._path(profile_id)
            path.unlink(missing_ok=True)
            for directory in self.legacy_directories:
                (directory / path.name).unlink(missing_ok=True)
