"""Correct an explicitly selected archive company name without changing data."""
from __future__ import annotations

import argparse
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from apps.file_ingest.naming import comparison_key, safe_component
from apps.file_ingest.registry import ACTIVE_REPORTS
from scripts.auto_download.archive_months import apply_archive
from scripts.auto_download.ledger import atomic_json
from scripts.auto_download.move_report import archive_filename, file_digest
from scripts.auto_download.report_calendar_admin import service_from_env
from scripts.auto_download.run_all_platform_downloads import ControllerRunLock, DEFAULT_CONFIG, load_config, resolve_path


def plan_company_rename(root: Path, platform: str, old_company: str, company: str, shop: str) -> dict:
    root = root.resolve()
    moves, reserved = [], set()
    for spec in ACTIVE_REPORTS:
        if spec.platform_name != platform:
            continue
        folder = root / platform / spec.report_name
        old_stem = '_'.join(safe_component(v) for v in (platform, old_company, shop, spec.report_name))
        pattern = re.compile(r'^(\d{8}|\d{6})_' + re.escape(old_stem) + r'(?:_(\d{3}))?$')
        for source in sorted(folder.rglob('*')):
            if not source.is_file() or source.suffix.lower() not in {'.csv', '.xlsx', '.xls', '.xlsm', '.zip', '.txt'}:
                continue
            match = pattern.fullmatch(source.stem)
            if not match:
                continue
            target = source.with_name(archive_filename(platform, company, shop, spec.report_name,
                                                      match[1], source.suffix, int(match[2]) if match[2] else None))
            source.relative_to(root); target.relative_to(root)
            if source == target:
                continue
            if target.exists() or target in reserved:
                raise ValueError(f'目标文件已存在，拒绝覆盖：{target}')
            reserved.add(target)
            moves.append({'source':source.relative_to(root).as_posix(), 'target':target.relative_to(root).as_posix(),
                          'size':source.stat().st_size, 'sha256':file_digest(source)})
    return {'version':1, 'archive_root':str(root), 'created_at':datetime.now().astimezone().isoformat(),
            'platform':platform, 'old_company':old_company, 'company':company, 'shop':shop,
            'moves':moves, 'skipped':[], 'status':'planned'}


def validate_dim(service, platform: str, company: str, shop: str) -> dict:
    expected = tuple(comparison_key(v) for v in (platform, company, shop))
    rows = [row for row in service.file_ingest.list_shops()
            if tuple(comparison_key(row[k]) for k in ('platform_name','company_name','shop_name')) == expected]
    if len(rows) != 1:
        raise ValueError('目标平台、公司、店铺在当前 DIM 中无唯一有效映射，停止改名')
    return rows[0]


def main() -> None:
    parser = argparse.ArgumentParser(description='修正指定公司店铺的已有归档文件名，默认预览；不修改文件内容或ODS')
    parser.add_argument('--dest')
    parser.add_argument('--platform', required=True)
    parser.add_argument('--old-company', required=True)
    parser.add_argument('--company', required=True)
    parser.add_argument('--shop', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = resolve_path(args.dest or load_config(DEFAULT_CONFIG)['destination'])
    service = service_from_env(root)
    dim = validate_dim(service, args.platform, args.company, args.shop)
    lock = ControllerRunLock(path=root/'.automation_logs/all_platform_downloads/controller.lock',
                             wait_seconds=0, run_id='archive-company-'+uuid.uuid4().hex[:8], execution_lane='all',
                             logger=logging.getLogger('archive-company'))
    lock.acquire()
    try:
        plan = plan_company_rename(root, dim['platform_name'], args.old_company, dim['company_name'], dim['shop_name'])
        manifest = root/'.automation_logs/archive_migrations'/f'company_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.json'
        atomic_json(manifest, plan)
        if args.apply:
            apply_archive(plan, service)
            atomic_json(manifest, plan)
        print(f"{'已修正' if args.apply else '待修正'} {len(plan['moves'])} 个文件；文件内容不变")
        print(f'迁移清单：{manifest}')
    finally:
        lock.release()


if __name__ == '__main__':
    main()
