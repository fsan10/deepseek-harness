# -*- coding: utf-8 -*-
"""下载报表移动重命名脚本。

将浏览器默认下载目录（C:\\Users\\win\\Downloads）中刚下载的报表文件
剪切到 C:\\Users\\win\\Desktop\\data\\<平台>\\<报表类型>\\YYYY.MM\\ 并按
`YYYYMMDD_平台_公司_店铺_报表类型[.ext]` 规则重命名；同一天同店铺同报表
类型已存在时自动递增 _002、_003。原下载位置不保留源文件。

参数（platform/company/shop 取自 profile note 的键值对）：
    --platform 平台中文名（如 抖音）
    --company  公司全称（半角括号，与 note 一致）
    --shop     店铺名
    --report   数据导入中心登记的标准报表名称，同时作为目标子目录名
    --date     账单日期，支持 2026-08-12 或 20260812
    --src      源目录，默认 C:\\Users\\win\\Downloads
    --dest     目标根目录，默认 C:\\Users\\win\\Desktop\\data
    --pattern  源文件匹配模式，默认 DL*（抖店下载报表前缀）
    --within   只匹配最近 N 分钟内修改的源文件，默认 10 分钟

示例：
    python -m scripts.auto_download.move_report --platform 抖音 --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK官方旗舰店" --report 结算 --date 2026-08-12

退出码：0=成功；1=执行失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.file_ingest.registry import ACTIVE_REPORTS, find_report
from apps.file_ingest.naming import build_filename

DEFAULT_SRC = Path(r"C:\Users\win\Downloads")
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")

REPORTS_BY_PLATFORM: dict[str, tuple[str, ...]] = {}
for _spec in ACTIVE_REPORTS:
    REPORTS_BY_PLATFORM.setdefault(_spec.platform_name, tuple())
    REPORTS_BY_PLATFORM[_spec.platform_name] += (_spec.report_name,)


def parse_date(text: str) -> str:
    m = re.match(r"^(\d{4})[-\/]?(\d{2})[-\/]?(\d{2})$", text)
    if m:
        datetime.date(int(m[1]), int(m[2]), int(m[3]))
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = re.match(r"^(\d{4})[-\/]?(\d{2})$", text)
    if m:
        datetime.date(int(m[1]), int(m[2]), 1)
        return f"{m.group(1)}{m.group(2)}"
    raise ValueError(f"日期格式错误：{text}（支持 YYYY-MM-DD、YYYYMMDD、YYYY-MM、YYYYMM）")


def find_latest(src: Path, pattern: str, within_minutes: int) -> Path:
    cutoff = datetime.datetime.now() - datetime.timedelta(minutes=within_minutes)
    candidates = []
    for f in src.glob(pattern):
        try:
            if f.is_file() and f.stat().st_mtime >= cutoff.timestamp():
                candidates.append(f)
        except OSError:
            continue
    if not candidates:
        raise FileNotFoundError(
            f"在 {src} 中未找到最近 {within_minutes} 分钟内匹配 {pattern!r} 的下载文件"
        )
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def report_directory(dest: Path, platform: str, report: str, business_date: str) -> Path:
    compact = parse_date(business_date)
    return Path(dest) / platform / report / f"{compact[:4]}.{compact[4:6]}"


def archive_filename(platform: str, company: str, shop: str, report: str,
                     business_date: str, ext: str, sequence: int | None = None) -> str:
    """Use the ingest naming contract without inventing company/shop aliases."""
    return f"{parse_date(business_date)}_" + build_filename(
        extension=ext, platform_name=platform, company_name=company,
        shop_name=shop, report_name=report, sequence=sequence,
    )


def target_path(dest: Path, platform: str, company: str, shop: str, report: str,
                date_compact: str, ext: str) -> Path:
    try:
        spec = find_report(platform_name=platform, report_name=report)
    except ValueError as exc:
        available = "、".join(REPORTS_BY_PLATFORM.get(platform, ())) or "无"
        raise ValueError(
            f"平台“{platform}”不支持报表“{report}”；可选标准报表：{available}"
        ) from exc
    platform = spec.platform_name
    report = spec.report_name
    date_compact = parse_date(date_compact)
    filename = archive_filename(platform, company, shop, report, date_compact, ext)
    base_dir = report_directory(dest, platform, report, date_compact)
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / filename
    if not candidate.exists():
        return candidate
    for seq in range(2, 1000):
        candidate = base_dir / archive_filename(platform, company, shop, report, date_compact, ext, seq)
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"{base_dir} 下同名文件过多，无法生成新文件名")


def archive_report(
    source: Path,
    platform: str,
    company: str,
    shop: str,
    report: str,
    business_date: str,
    dest: Path,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
    receipt_path: Path | None = None,
) -> Path:
    """Rename and move one downloaded report into the standard archive tree."""

    source = Path(source)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"待归档文件不存在：{source}")
    if not source.stat().st_size:
        raise ValueError("待归档文件为空，不能认定报表获取成功")
    date_compact = parse_date(business_date)
    # These variables are scoped to the downloader subprocess, never persisted
    # as Windows user/system environment settings.
    period_start = period_start or os.getenv("AUTOMATION_REPORT_START")
    period_end = period_end or os.getenv("AUTOMATION_REPORT_END")
    if bool(period_start) != bool(period_end):
        raise ValueError("归档业务开始/结束日期必须同时提供")
    if len(date_compact) == 6:
        start = datetime.date(int(date_compact[:4]), int(date_compact[4:6]), 1)
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        if period_start and (datetime.date.fromisoformat(period_start) != start or datetime.date.fromisoformat(period_end) != end):
            raise ValueError("月报请求必须覆盖归档月份的完整自然月")
        period_type = "month"
    elif period_start and period_end:
        start = datetime.date.fromisoformat(period_start)
        end = datetime.date.fromisoformat(period_end)
        if start > end or (len(date_compact) == 8 and end.strftime("%Y%m%d") != date_compact):
            raise ValueError("归档业务日期与请求期间不一致")
        period_type = "day" if start == end else "date_range"
    else:
        start = end = datetime.datetime.strptime(date_compact, "%Y%m%d").date()
        period_type = "day"
    target = target_path(
        Path(dest),
        platform,
        company,
        shop,
        report,
        date_compact,
        source.suffix,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    manifest = receipt_path or (Path(os.environ["AUTOMATION_ARTIFACT_MANIFEST"]) if os.getenv("AUTOMATION_ARTIFACT_MANIFEST") else None)
    if manifest:
        spec = find_report(platform_name=platform, report_name=report)
        item = {
            "artifact_type": "report_file", "file_name": target.name,
            "relative_path": target.relative_to(Path(dest)).as_posix(),
            "file_size_bytes": target.stat().st_size,
            "file_hash": file_digest(target),
            "report_type": spec.report_type, "business_date_start": start.isoformat(),
            "business_date_end": end.isoformat(), "period_type": period_type,
            "coverage_verified": True,
        }
        manifest.parent.mkdir(parents=True, exist_ok=True)
        items = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else []
        items.append(item)
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        temporary.replace(manifest)
    return target


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="下载报表移动重命名脚本")
    parser.add_argument("--platform", required=True, help="平台中文名")
    parser.add_argument("--company", required=True, help="公司全称")
    parser.add_argument("--shop", required=True, help="店铺名")
    parser.add_argument("--report", required=True, help="当前28类注册表中的标准报表名称")
    parser.add_argument("--date", required=True, help="账单日期 YYYY-MM-DD/YYYYMMDD 或 YYYY-MM/YYYYMM")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="源目录")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="目标根目录")
    parser.add_argument("--pattern", default="DL*", help="源文件匹配模式")
    parser.add_argument("--within", type=int, default=10, help="匹配最近 N 分钟内的文件")
    args = parser.parse_args()

    try:
        src = Path(args.src)
        dest = Path(args.dest)
        source = find_latest(src, args.pattern, args.within)
        target = archive_report(
            source,
            args.platform,
            args.company,
            args.shop,
            args.report,
            args.date,
            dest,
        )
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"移动失败：{exc}", file=sys.stderr)
        return 1

    print(f"已移动：{source.name}")
    print(f"  -> {target}")
    print(f"报表类型目录：{target.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
