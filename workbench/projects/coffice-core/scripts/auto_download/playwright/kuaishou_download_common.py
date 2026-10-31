# -*- coding: utf-8 -*-
"""快手账单下载的会话、文件保存、ZIP 提取与归档能力。"""

from __future__ import annotations

from .component_runtime import automation_component

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from ..extract_report import extract_selected_report, repair_member_name, unique_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@automation_component("kuaishou.session.open", "快手 · 建立业务页面", category="browser")
async def new_page(browser) -> "Page":
    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用上下文")
    return await browser.contexts[0].new_page()


@automation_component("kuaishou.session.ensure_login", "快手 · 检查登录态", category="browser")
def ensure_logged_in(page: "Page") -> None:
    if not page.url.startswith("https://s.kwaixiaodian.com/zone/"):
        raise RuntimeError(f"快手 profile 未登录商家后台，当前页面：{page.url}")


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download, directory: Path, fallback_name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory, download.suggested_filename or fallback_name)
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"快手下载文件为空：{target}")
    return target


def extract_unique_report(
    archive: Path,
    dest: Path,
    allowed_suffixes: tuple[str, ...],
) -> Path:
    """调用 extract_report 提取 ZIP 中唯一允许的报表，并删除 ZIP。"""
    if not zipfile.is_zipfile(archive):
        raise RuntimeError(f"下载文件不是有效 ZIP：{archive}")
    matches: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            repaired = repair_member_name(info.filename, info.flag_bits, "gbk")
            if Path(repaired).suffix.lower() in allowed_suffixes:
                matches.append(repaired)
    if len(matches) != 1:
        raise RuntimeError(f"快手 ZIP 中未找到唯一报表文件：{'、'.join(matches) or '无'}")
    suffix = Path(matches[0]).suffix.lower()
    target = extract_selected_report(
        archive=archive,
        dest=dest,
        include_text=suffix,
        exclude_text="",
        filename_encoding="gbk",
        delete_archive=True,
    )
    if target.stat().st_size == 0:
        raise RuntimeError(f"快手 ZIP 解压得到空文件：{target}")
    return target


@automation_component("file.archive.extract", "解压 / 提取报表文件", category="file")
def prepare_report_file(
    downloaded: Path,
    dest: Path,
    allowed_suffixes: tuple[str, ...],
) -> Path:
    if downloaded.suffix.lower() == ".zip":
        return extract_unique_report(downloaded, dest, allowed_suffixes)
    if downloaded.suffix.lower() not in allowed_suffixes:
        raise RuntimeError(f"快手报表格式不支持：{downloaded.suffix}")
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
