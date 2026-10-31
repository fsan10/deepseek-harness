from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

from .registry import ACTIVE_REPORTS, ReportSpec


WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SEQUENCE_SUFFIX = re.compile(r"_(\d{3})$")
# 自动下载归档文件的日期前缀：YYYYMMDD_ 或 YYYYMM_。
# 部分 Windows/Excel 流程会带 BOM 或全角下划线，均按同一规则兼容。
DATE_PREFIX = re.compile(r"^\ufeff?(?:\d{8}|\d{6})[_＿]")


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def comparison_key(value: str) -> str:
    """Normalize visually equivalent filename and DIM punctuation for matching only."""
    return unicodedata.normalize("NFKC", normalize_name(value))


def safe_component(value: str) -> str:
    normalized = normalize_name(value)
    if not normalized:
        raise ValueError("文件名组成部分不能为空")
    normalized = WINDOWS_INVALID.sub("-", normalized).rstrip(" .")
    if not normalized:
        raise ValueError("文件名组成部分清洗后为空")
    return normalized


def build_filename(
    *,
    extension: str,
    platform_name: str,
    company_name: str,
    shop_name: str,
    report_name: str,
    sequence: int | None = None,
) -> str:
    suffix = extension.lower()
    if not suffix.startswith("."):
        suffix = "." + suffix
    if sequence is not None and not 1 <= int(sequence) <= 999:
        raise ValueError("流水序号必须在1到999之间")
    stem = "_".join(safe_component(item) for item in (platform_name, company_name, shop_name, report_name))
    if sequence is not None:
        stem += f"_{int(sequence):03d}"
    return stem + suffix


def strip_sequence(stem: str) -> tuple[str, int | None]:
    match = SEQUENCE_SUFFIX.search(stem)
    if not match:
        return stem, None
    return stem[: match.start()], int(match.group(1))


def strip_date_prefix(stem: str) -> str:
    """Ignore the optional automation date prefix without using it as metadata."""
    return DATE_PREFIX.sub("", normalize_name(stem), count=1)


def guess_filename(filename: str, shops: Iterable[dict], reports: Iterable[ReportSpec] = ACTIVE_REPORTS) -> dict:
    path = Path(filename)
    actual_stem, sequence = strip_sequence(normalize_name(path.stem))
    actual_stem = strip_date_prefix(actual_stem)
    matches: list[dict] = []
    for shop in shops:
        for spec in reports:
            if spec.platform_code != shop.get("platform_code"):
                continue
            expected = "_".join(
                safe_component(item)
                for item in (spec.platform_name, shop.get("company_name", ""), shop.get("shop_name", ""), spec.report_name)
            )
            if comparison_key(expected) == comparison_key(actual_stem):
                matches.append({
                    "report_type": spec.report_type,
                    "report_name": spec.report_name,
                    "platform_code": spec.platform_code,
                    "platform_name": spec.platform_name,
                    "shop_code": shop.get("shop_code"),
                    "shop_name": shop.get("shop_name"),
                    "company_code": shop.get("company_code"),
                    "company_name": shop.get("company_name"),
                    "shop_identity_key": shop.get("shop_identity_key"),
                    "target_table": spec.target_table,
                    "extensions": list(spec.extensions),
                    "etl_keys": list(spec.etl_keys),
                    "sequence": sequence,
                })
    if len(matches) == 1:
        return {"filename": path.name, "matched": True, "ambiguous": False, **matches[0]}
    return {
        "filename": path.name,
        "matched": False,
        "ambiguous": len(matches) > 1,
        "sequence": sequence,
        "alternatives": matches,
        "message": "文件名匹配到多个候选" if matches else "文件名不符合标准命名或DIM中无唯一店铺",
    }
