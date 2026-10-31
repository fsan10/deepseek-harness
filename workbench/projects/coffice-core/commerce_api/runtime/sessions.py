"""DPAPI-protected, backend-scoped sessions with generation-fenced refresh."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import uuid

from ..core.contracts import now_iso
from ..core.errors import AuthRequired, SessionStoreError
from .storage import Paths, file_lock


def protect(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise SessionStoreError("会话存储要求 Windows DPAPI，不允许降级为明文")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if decrypt:
        success = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        success = crypt.CryptProtectData(ctypes.byref(source), "commerce-api-session-v1", None, None, None, 1, ctypes.byref(result))
    if not success:
        raise SessionStoreError("无法保护或读取会话，请使用同一 Windows 用户")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def session_key(profile_id: str, platform: str, backend: str) -> str:
    return hashlib.sha256(f"{profile_id}\0{platform}\0{backend}".encode()).hexdigest()


class SessionStore:
    def __init__(self, paths: Paths, *, codec=protect):
        self.paths = paths
        self.codec = codec

    def load(self, key: str) -> dict:
        path = self.paths.file("sessions", key, ".enc")
        if not path.is_file():
            raise AuthRequired("尚无该后台的加密会话，请先登录", stage="auth")
        try:
            result = json.loads(self.codec(path.read_bytes(), decrypt=True))
            if result.get("key") != key or result.get("version") != 1 or not result.get("generation"):
                raise ValueError()
            return result
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("加密会话损坏，禁止使用或明文回退") from None

    def _write(self, key: str, value: dict) -> None:
        path = self.paths.file("sessions", key, ".enc")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{key}.{uuid.uuid4().hex}.tmp")
        try:
            content = self.codec(json.dumps({**value, "version": 1, "key": key}, ensure_ascii=False).encode())
            with temporary.open("xb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, key: str, value: dict) -> dict:
        with file_lock(self.paths.file("locks", "session_" + key, ".lock"), timeout=5):
            result = {**value, "generation": uuid.uuid4().hex, "captured_at": now_iso()}
            self._write(key, result)
            return result

    def refresh(self, key: str, value: dict) -> bool:
        with file_lock(self.paths.file("locks", "session_" + key, ".lock"), timeout=5):
            try:
                current = self.load(key)
            except AuthRequired:
                return False
            if value.get("generation") != current["generation"]:
                return False
            self._write(key, {**value, "updated_at": now_iso()})
            return True

    def delete(self, key: str) -> None:
        with file_lock(self.paths.file("locks", "session_" + key, ".lock"), timeout=5):
            self.paths.file("sessions", key, ".enc").unlink(missing_ok=True)
