# -*- coding: utf-8 -*-
"""Shared, forward-compatible schema checks for downloaded merchant reports."""

from __future__ import annotations

from collections.abc import Iterable


def validate_report_columns(
    actual_columns: Iterable[object],
    expected_columns: Iterable[str],
    *,
    report_name: str,
    optional_columns: Iterable[str] = (),
    missing_error_prefix: str | None = None,
) -> None:
    """Require configured columns while tolerating platform-added or reordered columns."""

    actual = tuple(
        str(value).replace("\ufeff", "").strip()
        for value in actual_columns
        if value is not None
    )
    expected = tuple(str(column).replace("\ufeff", "").strip() for column in expected_columns)
    optional = {str(column).replace("\ufeff", "").strip() for column in optional_columns}
    actual_set = set(actual)

    missing = [column for column in expected if column not in optional and column not in actual_set]
    if missing:
        prefix = missing_error_prefix or f"{report_name}表头缺少必需字段："
        raise RuntimeError(f"{prefix}{'、'.join(missing)}")

    missing_optional = [column for column in expected if column in optional and column not in actual_set]
    if missing_optional:
        print(
            f"提示：{report_name}缺少可选字段，仍继续下载：{'、'.join(missing_optional)}",
            flush=True,
        )

    expected_set = set(expected)
    unregistered = tuple(
        dict.fromkeys(column for column in actual if column and column not in expected_set)
    )
    if unregistered:
        print(
            f"警告：{report_name}包含未登记字段，仍继续下载；是否导入这些字段取决于现有导入配置："
            f"{'、'.join(unregistered)}",
            flush=True,
        )


def warn_unread_sheets(
    report_name: str,
    actual_sheet_names: Iterable[str],
    consumed_sheet_names: Iterable[str],
) -> None:
    consumed = set(consumed_sheet_names)
    unread = tuple(name for name in actual_sheet_names if name not in consumed)
    if unread:
        print(
            f"警告：{report_name}包含当前下载校验/导入不会读取的工作表，仍继续下载："
            f"{'、'.join(unread)}",
            flush=True,
        )
