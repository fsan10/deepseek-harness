"""Read owned report contents without printing business rows or personal data."""
from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

from commerce_api.runtime.files import content_extension, valid_receipt
from commerce_api.runtime.storage import Paths, atomic_json, read_json

DATE_LABEL = re.compile(r"(?:日期|时间|账期)$")
DATE_VALUE = re.compile(r"^(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日|\b)")
MAX_BYTES = 100 * 1024 * 1024


def parse_day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value or "").strip().lstrip("\ufeff'\t=").strip('"')
    match = DATE_VALUE.match(raw)
    if not match and re.fullmatch(r"20\d{6}", raw):
        raw = raw[:4] + "-" + raw[4:6] + "-" + raw[6:]
        match = DATE_VALUE.match(raw)
    if match:
        try:
            return date(*(int(part) for part in match.groups())).isoformat()
        except ValueError:
            pass
    return None


def summarize_rows(rows):
    rows = iter(rows)
    beginning = list(itertools.islice(rows, 30))
    if not beginning:
        return {"rows_after_header": 0, "columns": 0, "date_columns": {}}
    def score(row):
        labels = [str(value or "").strip() for value in row]
        dates = sum(bool(DATE_LABEL.search(label)) and len(label) < 25 for label in labels)
        return dates * 1000 + sum(bool(label) for label in labels)
    header_index = max(range(len(beginning)), key=lambda i: score(beginning[i]))
    headers = [str(value or "").strip().lstrip("\ufeff") for value in beginning[header_index]]
    columns = {i: label for i, label in enumerate(headers) if len(label) < 25 and DATE_LABEL.search(label)}
    identifiers = {i: label for i, label in enumerate(headers) if label in {
        "主订单编号", "子订单编号", "订单编号", "主订单号", "子订单号", "订单号"}}
    distinct = {label: set() for label in identifiers.values()}
    statistics = {label: {"parsed": 0, "minimum": None, "maximum": None} for label in columns.values()}
    count = 0
    for row in itertools.chain(beginning[header_index + 1:], rows):
        if not any(value not in (None, "") for value in row):
            continue
        if [str(value or "").strip() for value in row] == headers:
            continue
        count += 1
        for i, label in identifiers.items():
            value = str(row[i] or "").strip().lstrip("\ufeff'\t=").strip('"') if i < len(row) else ""
            if value:
                distinct[label].add(value)
        for i, label in columns.items():
            parsed = parse_day(row[i]) if i < len(row) else None
            if parsed:
                item = statistics[label]
                item["parsed"] += 1
                item["minimum"] = min(item["minimum"] or parsed, parsed)
                item["maximum"] = max(item["maximum"] or parsed, parsed)
    return {"rows_after_header": count, "columns": len(headers), "header_row": header_index + 1,
        "date_columns": statistics, "distinct_order_keys": {label: len(values) for label, values in distinct.items()}}


def inspect_content(content, suffix, *, depth=0):
    if len(content) > MAX_BYTES or depth > 3:
        return {"inspected": False, "reason": "bounded_inspection_limit"}
    if suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(content)) as bundle:
            members = [item for item in bundle.infolist() if not item.is_dir()]
            if any(item.flag_bits & 1 for item in members):
                return {"inspected": False, "encrypted": True}
            if sum(item.file_size for item in members) > MAX_BYTES:
                return {"inspected": False, "reason": "bounded_archive_limit"}
            reports = []
            for member in members:
                extension = Path(member.filename).suffix.lower()
                if extension in {".zip", ".csv", ".xlsx", ".xls"}:
                    reports.append({"format": extension,
                        **inspect_content(bundle.read(member), extension, depth=depth + 1)})
            return {"inspected": bool(reports), "archive_members": len(members), "reports": reports}
    if suffix == ".xlsx":
        if content.startswith(b"\xd0\xcf\x11\xe0"):
            import olefile
            with olefile.OleFileIO(io.BytesIO(content)) as document:
                if document.exists("EncryptedPackage"):
                    return {"inspected": False, "encrypted": True}
                if document.exists("Workbook") or document.exists("Book"):
                    return {"actual_format": ".xls", **inspect_content(content, ".xls", depth=depth)}
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            for sheet in book:
                sheet.reset_dimensions()
            return {"inspected": True, "sheets": [summarize_rows(sheet.iter_rows(values_only=True)) for sheet in book]}
        finally:
            book.close()
    if suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(file_contents=content)
        try:
            return {"inspected": True, "sheets": [summarize_rows(sheet.row_values(i) for i in range(sheet.nrows))
                for sheet in book.sheets()]}
        finally:
            book.release_resources()
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return {"inspected": False, "reason": "unsupported_text_encoding"}
        try:
            dialect = csv.Sniffer().sniff(text[:65536], delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel_tab if text.count("\t") > text.count(",") else csv.excel
        return {"inspected": True, "encoding": encoding, **summarize_rows(csv.reader(io.StringIO(text), dialect))}
    return {"inspected": False, "reason": "unsupported_format"}


def audit(paths, run_id=None):
    result = []
    files = [paths.file("runs", run_id)] if run_id else sorted((paths.root / "runs").glob("*.json"))
    for file in files:
        state = read_json(file, {})
        if not state.get("files"):
            continue
        request = state["request"]
        item = {"run_id": state["id"], "platform": request["platform"], "backend": request["backend"],
            "kind": request["kind"], "status": state["status"], "period": request["period"], "files": []}
        for receipt in state["files"]:
            path = Path(receipt["path"]).resolve()
            if not path.is_relative_to(paths.root / "downloads"):
                raise ValueError("Refusing to inspect a file outside owned downloads")
            entry = {"format": path.suffix.lower(), "role": receipt.get("role"), "receipt_valid": valid_receipt(receipt)}
            if entry["receipt_valid"]:
                try:
                    entry.update(inspect_content(path.read_bytes(), path.suffix.lower()))
                except Exception as exc:
                    entry.update(inspected=False, error_type=type(exc).__name__)
            item["files"].append(entry)
        result.append(item)
    return {"runs": result, "run_count": len(result), "business_rows_printed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    paths = Paths()
    result = audit(paths, args.run)
    if args.write:
        atomic_json(paths.file("acceptance", "content-audit"), result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
