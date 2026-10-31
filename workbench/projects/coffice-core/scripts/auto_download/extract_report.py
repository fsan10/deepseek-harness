# -*- coding: utf-8 -*-
"""从 ZIP 报表中安全提取指定明细文件，可修复 GBK 文件名乱码。"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath


def repair_member_name(name: str, flag_bits: int, filename_encoding: str) -> str:
    """修复 ZIP 未设置 UTF-8 标志时被 zipfile 按 CP437 解码的中文文件名。"""
    if flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode(filename_encoding)
    except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
        return name


def select_member(
    members: list[zipfile.ZipInfo],
    include_text: str,
    exclude_text: str,
    filename_encoding: str,
) -> tuple[zipfile.ZipInfo, str]:
    candidates: list[tuple[zipfile.ZipInfo, str]] = []
    for info in members:
        if info.is_dir():
            continue
        repaired = repair_member_name(info.filename, info.flag_bits, filename_encoding)
        basename = PurePosixPath(repaired.replace("\\", "/")).name
        if include_text in basename and (not exclude_text or exclude_text not in basename):
            candidates.append((info, basename))
    if not candidates:
        raise RuntimeError(
            f"压缩包中未找到包含 {include_text!r} 且不包含 {exclude_text!r} 的文件"
        )
    if len(candidates) != 1:
        names = "、".join(name for _, name in candidates)
        raise RuntimeError(f"压缩包中匹配到多个明细文件：{names}")
    return candidates[0]


def unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    source = Path(filename)
    for sequence in range(2, 1000):
        candidate = directory / f"{source.stem}_{sequence:03d}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"{directory} 下同名文件过多，无法生成解压文件名")


def extract_selected_report(
    archive: Path,
    dest: Path,
    include_text: str = "账务明细.csv",
    exclude_text: str = "(汇总)",
    filename_encoding: str = "gbk",
    delete_archive: bool = False,
) -> Path:
    if not archive.is_file():
        raise FileNotFoundError(f"压缩包不存在：{archive}")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        info, basename = select_member(
            bundle.infolist(), include_text, exclude_text, filename_encoding
        )
        if info.flag_bits & 0x1:
            raise RuntimeError("压缩包成员已加密，无法自动解压")
        target = unique_path(dest, basename)
        with bundle.open(info) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    if delete_archive:
        archive.unlink()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="安全解压报表 ZIP 并选择业务明细文件")
    parser.add_argument("--archive", required=True, help="ZIP 压缩包路径")
    parser.add_argument("--dest", help="解压目录，默认压缩包所在目录")
    parser.add_argument("--include", default="账务明细.csv", help="目标文件名必须包含的文本")
    parser.add_argument("--exclude", default="(汇总)", help="目标文件名不得包含的文本")
    parser.add_argument("--filename-encoding", default="gbk", help="非 UTF-8 ZIP 文件名编码")
    parser.add_argument("--delete-archive", action="store_true", help="成功提取后删除压缩包")
    args = parser.parse_args()

    archive = Path(args.archive)
    try:
        target = extract_selected_report(
            archive=archive,
            dest=Path(args.dest) if args.dest else archive.parent,
            include_text=args.include,
            exclude_text=args.exclude,
            filename_encoding=args.filename_encoding,
            delete_archive=args.delete_archive,
        )
    except (FileNotFoundError, FileExistsError, RuntimeError, OSError, zipfile.BadZipFile) as exc:
        print(f"解压失败：{exc}", file=sys.stderr)
        return 1
    print(f"已提取：{target}")
    if args.delete_archive:
        print(f"已删除压缩包：{archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
