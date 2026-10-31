"""Atomic owned downloads and file receipts; never upload or run ETL."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..core.errors import AuthRequired, ContractError, NeedsHuman, NetworkError


def safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:180]


def receipt(path: Path, *, period: dict | None = None) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "size": path.stat().st_size,
            "sha256": digest.hexdigest(), "actual_period": period}


def valid_receipt(value: dict) -> bool:
    path = Path(value.get("path", ""))
    return path.is_file() and path.stat().st_size == value.get("size") and receipt(path)["sha256"] == value.get("sha256")


def content_extension(path: Path, proposed: str) -> str:
    """Some gateways label an Excel 97 workbook as xlsx; keep its real format.

    Encrypted OOXML also uses OLE, so the magic bytes alone are insufficient.
    """
    with path.open("rb") as source:
        magic = source.read(8)
    if magic == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        import olefile
        with olefile.OleFileIO(path) as document:
            if document.exists("EncryptedPackage"):
                return ".xlsx"
            if document.exists("Workbook") or document.exists("Book"):
                return ".xls"
    return proposed


def save_response(response, directory, name, *, period=None):
    """Save an already-consumed one-time response without requesting it again."""
    content = response.content
    content_type = response.headers.get("content-type", "").lower()
    if not content or "text/html" in content_type or "application/json" in content_type:
        raise ContractError("一次性下载没有返回有效报表内容")
    destination = directory / safe_filename(name)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        temporary.write_bytes(content)
        destination = destination.with_suffix(content_extension(temporary, destination.suffix))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return receipt(destination, period=period)


async def download(url: str, directory: Path, name: str, *, client: httpx.AsyncClient | None = None,
                   headers: dict | None = None, allowed_hosts=(), period: dict | None = None) -> dict:
    from .http import domain_matches
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ContractError("平台下载地址不是合法 HTTPS 地址", stage="download")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ContractError("拒绝 IP 下载地址", stage="download")
    if allowed_hosts and not domain_matches(parsed.hostname, allowed_hosts):
        raise ContractError("下载地址不属于已登记的文件域名", stage="download")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / safe_filename(name)
    if destination.exists():
        destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:10]}{destination.suffix}")
    temporary = destination.with_name(destination.name + ".part")
    owned_client = client is None
    client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=90)
    try:
        # Redirects are handled explicitly so a platform response cannot send cookies
        # to an unvalidated host or make the CLI fetch a local network service.
        for redirect in range(5):
            async with client.stream("GET", url, headers=headers) as response:
                if response.is_redirect:
                    target = response.url.join(response.headers.get("location", ""))
                    target_parsed = urlsplit(str(target))
                    if target_parsed.scheme != "https" or not target_parsed.hostname or not domain_matches(target_parsed.hostname, allowed_hosts):
                        raise ContractError("拒绝未登记的文件下载重定向", stage="download")
                    if target_parsed.hostname != urlsplit(url).hostname:
                        headers = {k: v for k, v in (headers or {}).items() if k.lower() in {"user-agent", "accept", "referer"}}
                        referer = next((k for k in headers if k.lower() == "referer"), None)
                        if referer:
                            ref = urlsplit(headers[referer])
                            headers[referer] = f"{ref.scheme}://{ref.netloc}/"
                    url = str(target)
                    continue
                if response.status_code == 401:
                    raise AuthRequired("文件下载授权已失效，保留原导出任务", stage="download")
                if response.status_code in {403, 412, 418, 429}:
                    raise NeedsHuman("文件接口要求检查权限、下载上下文或频率，保留原任务", stage="download")
                if not response.is_success:
                    raise ContractError(f"文件下载 HTTP {response.status_code}", stage="download")
                content_type = response.headers.get("content-type", "").lower()
                disposition = response.headers.get("content-disposition", "")
                extension = re.search(r"\.(xlsx|xls|csv|zip)(?:[\"';\s]|$)", disposition, re.I)
                if extension and destination.suffix.lower() != "." + extension[1].lower():
                    destination = destination.with_suffix("." + extension[1].lower())
                if any(marker in content_type for marker in ("text/html", "application/json")):
                    raise ContractError("文件接口返回页面或错误数据，未保存为报表", stage="download")
                with temporary.open("xb") as output:
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)
                expected = response.headers.get("content-length")
                if not temporary.stat().st_size:
                    raise ContractError("下载文件为空", stage="download")
                if expected and response.headers.get("content-encoding", "identity") == "identity" and int(expected) != temporary.stat().st_size:
                    raise ContractError("文件长度不完整", stage="download")
                prefix = temporary.open("rb")
                try:
                    start = prefix.read(100).lstrip().lower()
                finally:
                    prefix.close()
                if start.startswith((b"<!doctype html", b"<html", b'{"code"', b'{"error"')):
                    raise ContractError("文件内容为错误响应", stage="download")
                destination = destination.with_suffix(content_extension(temporary, destination.suffix))
                if destination.exists():
                    destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:10]}{destination.suffix}")
                temporary.replace(destination)
                return receipt(destination, period=period)
        raise ContractError("文件下载重定向次数超限", stage="download")
    except httpx.RequestError:
        raise NetworkError("文件传输中断，保留平台导出任务以便续跑", stage="download") from None
    finally:
        temporary.unlink(missing_ok=True)
        if owned_client:
            await client.aclose()
