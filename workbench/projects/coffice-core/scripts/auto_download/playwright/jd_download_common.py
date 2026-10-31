# -*- coding: utf-8 -*-
"""京东下载脚本共用的会话、文件保存、递归解压和归档能力。"""

from __future__ import annotations

from .component_runtime import automation_component

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ..extract_report import repair_member_name, unique_path

JD_HOME_URL = "https://shop.jd.com/jdm/home"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOWNLOAD_LOCK_PATH = Path(tempfile.gettempdir()) / "mock_coffice_jd_download.lock"


@automation_component("jd.session.ensure_login", "京东 · 建立已登录页面", category="browser")
async def new_authenticated_page(browser) -> "Page":
    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用上下文")
    page = await browser.contexts[0].new_page()
    await page.goto(JD_HOME_URL, wait_until="domcontentloaded")
    if not page.url.startswith("https://shop.jd.com/jdm/"):
        await page.close()
        raise RuntimeError(f"JD profile 未登录商家后台，当前页面：{page.url}")
    return page


def unique_download_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return unique_path(directory, filename)


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download, directory: Path, fallback_name: str) -> Path:
    target = unique_download_path(directory, download.suggested_filename or fallback_name)
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"京东下载文件为空：{target}")
    return target


def acquire_download_lock(timeout: float = 180.0):
    """同一台 Windows Chrome 的京东自动化需要串行执行。"""
    import msvcrt

    handle = DOWNLOAD_LOCK_PATH.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return handle
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("等待京东浏览器下载锁超时")
            time.sleep(0.2)


def release_download_lock(handle) -> None:
    import msvcrt

    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def _safe_member_basename(info: zipfile.ZipInfo) -> str:
    repaired = repair_member_name(info.filename, info.flag_bits, "gbk")
    basename = PurePosixPath(repaired.replace("\\", "/")).name
    if not basename or basename in {".", ".."}:
        raise RuntimeError(f"ZIP 成员名称不安全：{info.filename!r}")
    return basename


def extract_nested_csv(archive: Path, dest: Path, max_depth: int = 3) -> Path:
    """从日账单或嵌套月账单 ZIP 中提取唯一 CSV，并删除中间压缩包。"""
    if not archive.is_file():
        raise FileNotFoundError(f"压缩包不存在：{archive}")
    dest.mkdir(parents=True, exist_ok=True)
    current = archive
    archives = [archive]
    try:
        for depth in range(max_depth + 1):
            with zipfile.ZipFile(current) as bundle:
                files = [info for info in bundle.infolist() if not info.is_dir()]
                csv_members = [
                    info for info in files if _safe_member_basename(info).lower().endswith(".csv")
                ]
                if csv_members:
                    if len(csv_members) != 1:
                        names = "、".join(_safe_member_basename(info) for info in csv_members)
                        raise RuntimeError(f"ZIP 中匹配到多个 CSV：{names}")
                    info = csv_members[0]
                    target = unique_path(dest, _safe_member_basename(info))
                    with bundle.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    if target.stat().st_size == 0:
                        raise RuntimeError(f"解压得到空 CSV：{target}")
                    return target

                zip_members = [
                    info for info in files if _safe_member_basename(info).lower().endswith(".zip")
                ]
                if len(zip_members) != 1:
                    names = "、".join(_safe_member_basename(info) for info in files)
                    raise RuntimeError(f"第 {depth + 1} 层未找到唯一 CSV 或内层 ZIP：{names}")
                info = zip_members[0]
                nested = unique_path(dest, _safe_member_basename(info))
                with bundle.open(info) as source, nested.open("wb") as output:
                    shutil.copyfileobj(source, output)
                archives.append(nested)
                current = nested
        raise RuntimeError(f"嵌套 ZIP 超过允许深度 {max_depth}")
    finally:
        for item in archives:
            try:
                if item.exists():
                    item.unlink()
            except OSError:
                pass


@automation_component("file.archive.extract", "解压 / 提取报表文件", category="file")
def prepare_report_file(downloaded: Path, dest: Path) -> Path:
    if downloaded.suffix.lower() == ".zip":
        return extract_nested_csv(downloaded, dest)
    return downloaded


def run_project_module(arguments: list[str]) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


@automation_component("report.archive", "归档标准报表", category="file")
def move_report(
    source: Path,
    platform: str,
    company: str,
    shop: str,
    report: str,
    business_date: str,
    dest: Path,
) -> str:
    return run_project_module(
        [
            "scripts.auto_download.move_report",
            "--platform", platform,
            "--company", company,
            "--shop", shop,
            "--report", report,
            "--date", business_date,
            "--src", str(source.parent),
            "--dest", str(dest),
            "--pattern", source.name,
            "--within", "10",
        ]
    )
