from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


CENT = Decimal("0.01")
REQUIRED_SOURCE_HEADERS = {
    "账号",
    "账号名称",
    "币种",
    "交易日",
    "交易时间",
    "起息日",
    "交易类型",
    "借方金额",
    "贷方金额",
    "余额",
    "摘要",
    "流水号",
}


def money(value: Any, *, allow_none: bool = True) -> Decimal | None:
    if value in (None, ""):
        if allow_none:
            return None
        raise ValueError("金额不能为空")
    if isinstance(value, Decimal):
        number = value
    else:
        text = str(value).replace(",", "").replace("¥", "").strip()
        if not text:
            return None if allow_none else Decimal("0.00")
        number = Decimal(text)
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def amount_abs(debit: Any, credit: Any) -> Decimal:
    debit_value = money(debit)
    credit_value = money(credit)
    if debit_value is None and credit_value is None:
        raise ValueError("借方金额和贷方金额不能同时为空")
    if debit_value not in (None, Decimal("0.00")) and credit_value not in (None, Decimal("0.00")):
        raise ValueError("同一行借方金额和贷方金额不能同时有值")
    return abs(debit_value if debit_value is not None else credit_value).quantize(CENT)


def parse_date(value: Any, epoch: datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return from_excel(value, epoch).date()
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"无法识别日期：{value}")


def parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if isinstance(value, (int, float)):
        seconds = round(float(value) * 24 * 60 * 60) % (24 * 60 * 60)
        return (datetime.min + timedelta(seconds=seconds)).time()
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"无法识别时间：{value}")


def text_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass(frozen=True)
class SourceRow:
    row_order: int
    account_no: str | None
    account_name: str | None
    currency: str | None
    transaction_date: date
    transaction_time: time | None
    value_date: date | None
    transaction_type: str | None
    debit_amount: Decimal | None
    credit_amount: Decimal | None
    balance: Decimal | None
    summary: str | None
    transaction_no: str | None
    raw_data: dict[str, Any]

    @property
    def source_amount(self) -> Decimal:
        return amount_abs(self.debit_amount, self.credit_amount)


@dataclass(frozen=True)
class SplitSpec:
    source_row_order: int
    split_index: int
    split_amount: Decimal
    expense_type_name: str | None
    account_entry_name: str | None
    remark: str
    is_adjusted: bool
    original_amount: Decimal
    adjusted_diff: Decimal

    @property
    def adjusted_amount(self) -> Decimal:
        return (self.original_amount + self.adjusted_diff).quantize(CENT)


@dataclass(frozen=True)
class ParsedWorkbook:
    source_sheet: str
    organized_sheet: str | None
    source_rows: list[SourceRow]
    split_specs: list[SplitSpec]
    expense_types: list[str]
    account_pairs: list[tuple[str, str]]

    @property
    def total_debit(self) -> Decimal:
        return sum((row.debit_amount or Decimal("0")) for row in self.source_rows).quantize(CENT)

    @property
    def total_credit(self) -> Decimal:
        return sum((row.credit_amount or Decimal("0")) for row in self.source_rows).quantize(CENT)

    @property
    def date_from(self) -> date:
        return min(row.transaction_date for row in self.source_rows)

    @property
    def date_to(self) -> date:
        return max(row.transaction_date for row in self.source_rows)

    @property
    def adjustment_balance(self) -> Decimal:
        return sum((row.adjusted_diff for row in self.split_specs), Decimal("0")).quantize(CENT)


def rows_as_dicts(sheet) -> tuple[list[str], list[dict[str, Any]]]:
    row_iterator = sheet.iter_rows(
        min_row=1,
        max_row=min(sheet.max_row, 200_000),
        max_col=min(sheet.max_column, 256),
        values_only=True,
    )
    try:
        header_values = next(row_iterator)
    except StopIteration:
        raise ValueError(f"工作表“{sheet.title}”为空")
    last_header = max((index for index, value in enumerate(header_values) if value not in (None, "")), default=-1)
    if last_header < 0:
        raise ValueError(f"工作表“{sheet.title}”没有表头")
    headers = [str(value).strip() if value is not None else "" for value in header_values[: last_header + 1]]
    named_headers = [header for header in headers if header]
    if len(named_headers) != len(set(named_headers)):
        raise ValueError(f"工作表“{sheet.title}”存在重复表头")
    rows: list[dict[str, Any]] = []
    blank_streak = 0
    for values_row in row_iterator:
        values_row = values_row[: len(headers)]
        if all(value in (None, "") for value in values_row):
            blank_streak += 1
            if blank_streak >= 50:
                break
            continue
        blank_streak = 0
        rows.append({header: value for header, value in zip(headers, values_row) if header})
    return headers, rows


def parse_workbook(path: str | Path) -> ParsedWorkbook:
    workbook = load_workbook(filename=Path(path), data_only=True, read_only=True)
    try:
        source_sheet = workbook["原数据"] if "原数据" in workbook.sheetnames else workbook[workbook.sheetnames[0]]
        source_headers, source_dicts = rows_as_dicts(source_sheet)
        missing = sorted(REQUIRED_SOURCE_HEADERS - set(source_headers))
        if missing:
            raise ValueError("原数据缺少必需列：" + "、".join(missing))
        if not source_dicts:
            raise ValueError("原数据没有可导入的数据行")

        source_rows: list[SourceRow] = []
        transaction_lookup: dict[str, SourceRow] = {}
        for row_order, raw in enumerate(source_dicts, start=1):
            transaction_no = text_value(raw.get("流水号"))
            source = SourceRow(
                row_order=row_order,
                account_no=text_value(raw.get("账号")),
                account_name=text_value(raw.get("账号名称")),
                currency=text_value(raw.get("币种")),
                transaction_date=parse_date(raw.get("交易日"), workbook.epoch),
                transaction_time=parse_time(raw.get("交易时间")),
                value_date=parse_date(raw.get("起息日"), workbook.epoch) if raw.get("起息日") not in (None, "") else None,
                transaction_type=text_value(raw.get("交易类型")),
                debit_amount=money(raw.get("借方金额")),
                credit_amount=money(raw.get("贷方金额")),
                balance=money(raw.get("余额")),
                summary=text_value(raw.get("摘要")),
                transaction_no=transaction_no,
                raw_data={key: json_value(value) for key, value in raw.items()},
            )
            _ = source.source_amount
            source_rows.append(source)
            if transaction_no:
                if transaction_no in transaction_lookup:
                    raise ValueError(f"原数据流水号重复：{transaction_no}")
                transaction_lookup[transaction_no] = source

        if "整理后" not in workbook.sheetnames:
            splits = [
                SplitSpec(row.row_order, 1, row.source_amount, None, None, "", False, row.source_amount, Decimal("0.00"))
                for row in source_rows
            ]
            return ParsedWorkbook(source_sheet.title, None, source_rows, splits, [], [])

        organized = workbook["整理后"]
        organized_headers, organized_rows = rows_as_dicts(organized)
        required_organized = REQUIRED_SOURCE_HEADERS | {"费用类型", "入账"}
        missing = sorted(required_organized - set(organized_headers))
        if missing:
            raise ValueError("整理后缺少必需列：" + "、".join(missing))

        grouped: dict[int, list[dict[str, Any]]] = {}
        current_source: SourceRow | None = None
        for excel_row, raw in enumerate(organized_rows, start=2):
            transaction_no = text_value(raw.get("流水号"))
            if transaction_no:
                current_source = transaction_lookup.get(transaction_no)
                if current_source is None:
                    raise ValueError(f"整理后第{excel_row}行流水号在原数据中不存在：{transaction_no}")
            elif current_source is None:
                raise ValueError(f"整理后第{excel_row}行缺少流水号，且无法识别所属母行")
            grouped.setdefault(current_source.row_order, []).append(raw)

        split_specs: list[SplitSpec] = []
        expense_types: set[str] = set()
        account_pairs: set[tuple[str, str]] = set()
        for source in source_rows:
            organized_group = grouped.get(source.row_order)
            if not organized_group:
                split_specs.append(
                    SplitSpec(source.row_order, 1, source.source_amount, None, None, "", False, source.source_amount, Decimal("0.00"))
                )
                continue
            organized_amounts = [amount_abs(row.get("借方金额"), row.get("贷方金额")) for row in organized_group]
            group_total = sum(organized_amounts, Decimal("0")).quantize(CENT)
            is_true_split = len(organized_group) > 1
            if is_true_split and group_total != source.source_amount:
                raise ValueError(
                    f"流水{source.transaction_no or source.row_order}拆分合计{group_total}与原金额{source.source_amount}不一致"
                )
            for index, (raw, organized_amount) in enumerate(zip(organized_group, organized_amounts), start=1):
                expense_name = text_value(raw.get("费用类型"))
                account_name = text_value(raw.get("入账"))
                if expense_name:
                    expense_types.add(expense_name)
                if expense_name and account_name:
                    account_pairs.add((account_name, expense_name))
                original_amount = organized_amount if is_true_split else source.source_amount
                adjusted_diff = Decimal("0.00") if is_true_split else (organized_amount - source.source_amount).quantize(CENT)
                child_remark = text_value(raw.get("摘要")) if not text_value(raw.get("流水号")) else None
                split_specs.append(
                    SplitSpec(
                        source_row_order=source.row_order,
                        split_index=index,
                        split_amount=original_amount,
                        expense_type_name=expense_name,
                        account_entry_name=account_name,
                        remark=child_remark or "",
                        is_adjusted=adjusted_diff != 0,
                        original_amount=original_amount,
                        adjusted_diff=adjusted_diff,
                    )
                )

        return ParsedWorkbook(
            source_sheet=source_sheet.title,
            organized_sheet=organized.title,
            source_rows=source_rows,
            split_specs=split_specs,
            expense_types=sorted(expense_types),
            account_pairs=sorted(account_pairs),
        )
    finally:
        workbook.close()


def allocate_split_amounts(total: Decimal, amounts: Iterable[Any]) -> list[Decimal]:
    target = money(total, allow_none=False)
    parsed = [money(value) for value in amounts]
    missing = [index for index, value in enumerate(parsed) if value is None]
    fixed_total = sum((value or Decimal("0")) for value in parsed).quantize(CENT)
    if not missing:
        if fixed_total != target:
            raise ValueError(f"拆分金额合计{fixed_total}必须等于母行金额{target}")
        if any(value <= 0 for value in parsed if value is not None):
            raise ValueError("拆分金额必须大于0")
        return [value for value in parsed if value is not None]
    remaining = (target - fixed_total).quantize(CENT)
    if remaining <= 0:
        raise ValueError("已填写金额不得大于或等于母行金额")
    average = (remaining / len(missing)).quantize(CENT, rounding=ROUND_HALF_UP)
    allocated = list(parsed)
    running = Decimal("0")
    for position, index in enumerate(missing):
        value = (remaining - running).quantize(CENT) if position == len(missing) - 1 else average
        if value <= 0:
            raise ValueError("自动分配后的子行金额必须大于0")
        allocated[index] = value
        running += value
    result = [value for value in allocated if value is not None]
    if sum(result).quantize(CENT) != target:
        raise ValueError("自动分配金额未能与母行金额一致")
    return result


def allocate_adjustment_diffs(total: Any, count: int) -> list[Decimal]:
    """将母行调账差额等分到子行，最后一行承接分差。"""
    if count < 1:
        raise ValueError("调账差额至少需要分配到1行")
    target = money(total, allow_none=False)
    average = (target / Decimal(count)).quantize(CENT, rounding=ROUND_HALF_UP)
    allocated = [average for _ in range(count - 1)]
    allocated.append((target - sum(allocated, Decimal("0.00"))).quantize(CENT))
    return allocated


def pending_amount(adjusted_diffs: Iterable[Any]) -> Decimal:
    """待调配额 = 银行固定总额 - 调账后总额。

    增加某行金额会产生负待调配额，需要从其他行扣减；
    减少某行金额会产生正待调配额，需要加到其他行。
    """
    total = sum((money(value, allow_none=False) for value in adjusted_diffs), Decimal("0"))
    return (-total).quantize(CENT)
