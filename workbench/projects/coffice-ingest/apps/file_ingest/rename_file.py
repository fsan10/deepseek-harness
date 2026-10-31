from __future__ import annotations

import argparse
import json
from pathlib import Path

from .naming import build_filename
from .registry import find_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按数据导入中心规范重命名影刀下载文件。")
    parser.add_argument("--file", required=True, help="待改名文件完整路径。")
    parser.add_argument("--platform-name", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--report-name", required=True)
    parser.add_argument("--sequence", type=int, default=None, help="同组多文件流水序号1-999；单文件不传。")
    return parser


def rename_file(args: argparse.Namespace) -> dict:
    source = Path(args.file).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"文件不存在：{source}")
    spec = find_report(platform_name=args.platform_name, report_name=args.report_name)
    target_name = build_filename(
        extension=source.suffix,
        platform_name=spec.platform_name,
        company_name=args.company_name,
        shop_name=args.shop_name,
        report_name=spec.report_name,
        sequence=args.sequence,
    )
    target = source.with_name(target_name)
    if target == source:
        return {"success": True, "path": str(target), "filename": target.name, "renamed": False}
    if target.exists():
        raise FileExistsError(f"目标文件已存在，拒绝覆盖：{target}")
    source.rename(target)
    return {"success": True, "path": str(target), "filename": target.name, "renamed": True}


def main() -> int:
    try:
        result = rename_file(build_parser().parse_args())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
