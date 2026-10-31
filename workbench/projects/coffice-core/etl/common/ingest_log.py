#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reusable PostgreSQL ingest log helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def calculate_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def split_table_name(table_name: str) -> tuple[str | None, str]:
    if "." not in table_name:
        return None, table_name
    schema, table = table_name.split(".", 1)
    return schema.strip('"'), table.strip('"')


def create_file_ingest_log(
    conn,
    *,
    source_system: str = "file",
    platform_code: str,
    platform_name: str | None = None,
    shop_code: str | None = None,
    shop_name: str | None = None,
    shop_identity_key: str | None = None,
    shop_mapping_status: str | None = None,
    shop_mapping_source: str | None = None,
    shop_mapping_message: str | None = None,
    data_domain: str,
    source_file_path: str,
    source_file_name: str,
    file_hash: str | None = None,
    file_size_bytes: int | None = None,
    file_encoding: str | None = None,
    source_sheet_name: str | None = None,
    header_row_no: int = 1,
    data_start_row_no: int = 3,
    total_rows: int = 0,
    parsed_rows: int = 0,
    target_schema: str | None = None,
    target_table: str | None = None,
    commit: bool = True,
) -> int:
    sheet_name = source_sheet_name or "CSV"
    sql = """
        INSERT INTO ods.ods_file_ingest_log (
            source_system,
            platform_code,
            platform_name,
            shop_code,
            shop_name,
            shop_identity_key,
            shop_mapping_status,
            shop_mapping_source,
            shop_mapping_message,
            data_domain,
            source_file_path,
            source_file_name,
            file_hash,
            file_size_bytes,
            file_encoding,
            source_sheet_name,
            header_row_no,
            data_start_row_no,
            total_rows,
            parsed_rows,
            target_schema,
            target_table,
            ingest_status,
            started_at
        )
        VALUES (
            %(source_system)s,
            %(platform_code)s,
            %(platform_name)s,
            %(shop_code)s,
            %(shop_name)s,
            %(shop_identity_key)s,
            %(shop_mapping_status)s,
            %(shop_mapping_source)s,
            %(shop_mapping_message)s,
            %(data_domain)s,
            %(source_file_path)s,
            %(source_file_name)s,
            %(file_hash)s,
            %(file_size_bytes)s,
            %(file_encoding)s,
            %(source_sheet_name)s,
            %(header_row_no)s,
            %(data_start_row_no)s,
            %(total_rows)s,
            %(parsed_rows)s,
            %(target_schema)s,
            %(target_table)s,
            'running',
            NOW()
        )
        RETURNING batch_id
    """
    params = {
        "source_system": source_system,
        "platform_code": platform_code,
        "platform_name": platform_name,
        "shop_code": shop_code,
        "shop_name": shop_name,
        "shop_identity_key": shop_identity_key,
        "shop_mapping_status": shop_mapping_status,
        "shop_mapping_source": shop_mapping_source,
        "shop_mapping_message": shop_mapping_message,
        "data_domain": data_domain,
        "source_file_path": source_file_path,
        "source_file_name": source_file_name,
        "file_hash": file_hash,
        "file_size_bytes": file_size_bytes,
        "file_encoding": file_encoding,
        "source_sheet_name": sheet_name,
        "header_row_no": header_row_no,
        "data_start_row_no": data_start_row_no,
        "total_rows": total_rows,
        "parsed_rows": parsed_rows,
        "target_schema": target_schema,
        "target_table": target_table,
    }
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        batch_id = cursor.fetchone()[0]
    if commit:
        conn.commit()
    return int(batch_id)


def finish_file_ingest_log(
    conn,
    *,
    batch_id: int,
    ingest_status: str,
    parsed_rows: int | None = None,
    success_rows: int = 0,
    duplicate_rows: int = 0,
    failed_rows: int = 0,
    error_message: str | None = None,
    commit: bool = True,
) -> None:
    sql = """
        UPDATE ods.ods_file_ingest_log
        SET
            ingest_status = %(ingest_status)s,
            parsed_rows = COALESCE(%(parsed_rows)s, parsed_rows),
            success_rows = %(success_rows)s,
            duplicate_rows = %(duplicate_rows)s,
            failed_rows = %(failed_rows)s,
            error_message = %(error_message)s,
            finished_at = NOW(),
            duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
            updated_at = NOW()
        WHERE batch_id = %(batch_id)s
    """
    params = {
        "batch_id": batch_id,
        "ingest_status": ingest_status,
        "parsed_rows": parsed_rows,
        "success_rows": success_rows,
        "duplicate_rows": duplicate_rows,
        "failed_rows": failed_rows,
        "error_message": error_message,
    }
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
    if commit:
        conn.commit()
