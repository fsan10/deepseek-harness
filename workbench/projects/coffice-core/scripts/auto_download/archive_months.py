"""Move legacy flat archives into business-month folders with reversible audit."""
from __future__ import annotations

import argparse
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from apps.file_ingest.registry import ACTIVE_REPORTS
from scripts.auto_download.ledger import atomic_json
from scripts.auto_download.move_report import file_digest, parse_date, report_directory
from scripts.auto_download.report_calendar_admin import service_from_env
from scripts.auto_download.run_all_platform_downloads import ControllerRunLock, DEFAULT_CONFIG, load_config, resolve_path


def plan_archive(root: Path) -> dict:
    root = root.resolve()
    moves, skipped, reserved = [], [], set()
    for spec in ACTIVE_REPORTS:
        folder = root/spec.platform_name/spec.report_name
        for source in sorted(folder.glob('*')):
            if not source.is_file() or source.suffix.lower() not in {'.csv','.xlsx','.xls','.xlsm','.zip','.txt'}:
                continue
            match = re.match(r'^(\d{8}|\d{4}-\d{2}-\d{2}|\d{6}|\d{4}-\d{2})_', source.name)
            try:
                compact = parse_date(match[1]) if match else None
            except ValueError:
                compact = None
            if not compact:
                skipped.append(source.relative_to(root).as_posix()); continue
            target = report_directory(root, spec.platform_name, spec.report_name, compact)/source.name
            sequence = 2
            while target.exists() or target in reserved:
                target = target.with_name(f'{source.stem}_m{sequence:03d}{source.suffix}');sequence += 1
            reserved.add(target)
            moves.append({'source':source.relative_to(root).as_posix(), 'target':target.relative_to(root).as_posix(),
                          'size':source.stat().st_size, 'sha256':file_digest(source)})
    return {'version':1,'archive_root':str(root),'created_at':datetime.now().astimezone().isoformat(),
            'moves':moves,'skipped':skipped,'status':'planned'}


def rewrite_paths(value, mapping):
    if isinstance(value, dict):
        return {k: rewrite_paths(v, mapping) for k,v in value.items()}
    if isinstance(value, list):
        return [rewrite_paths(v, mapping) for v in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def apply_archive(plan: dict, service) -> None:
    root = Path(plan['archive_root']).resolve()
    moved, rewritten = [], []
    mapping = {item['source']:item['target'] for item in plan['moves']}
    mapping.update({str(root/item['source']):str(root/item['target']) for item in plan['moves']})
    # Identity corrections may also change the basename; keep receipts and
    # checkpoint artifact names consistent with their rewritten paths.
    mapping.update({Path(item['source']).name:Path(item['target']).name for item in plan['moves']})
    try:
        with service.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('automation-archive-migration'))")
            cursor.execute("SELECT COUNT(*) AS count FROM ops.automation_run WHERE execution_lane <> 'etl' AND status='running'")
            if cursor.fetchone()['count']:
                raise ValueError('有自动化任务正在执行，请完成后再迁移旧文件')
            for item in plan['moves']:
                source, target = (root/item['source']).resolve(), (root/item['target']).resolve()
                source.relative_to(root);target.relative_to(root)
                if target.exists() or not source.is_file() or file_digest(source) != item['sha256']:
                    raise ValueError('归档文件与预览不一致，请重新预览')
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target);moved.append((source,target))
                if file_digest(target) != item['sha256']:
                    raise ValueError('迁移后文件校验失败')
                cursor.execute('UPDATE ops.automation_artifact SET relative_path=%s,file_name=%s WHERE relative_path=%s',
                               (item['target'],target.name,item['source']))
            log_root = root/'.automation_logs'
            for directory in ('report_ledger','report_receipts','all_platform_downloads'):
                for path in (log_root/directory).rglob('*.json'):
                    original = path.read_bytes()
                    try:
                        value = json.loads(original)
                    except json.JSONDecodeError:
                        continue
                    updated = rewrite_paths(value,mapping)
                    if updated != value:
                        rewritten.append((path,original));atomic_json(path,updated)
    except BaseException:
        for path, original in reversed(rewritten):
            path.write_bytes(original)
        for source, target in reversed(moved):
            target.rename(source)
        raise
    plan['status'] = 'completed'


def main():
    parser = argparse.ArgumentParser(description='旧报表按业务月份整理，默认只预览；不会导入或刷新ODS')
    parser.add_argument('--dest')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = resolve_path(args.dest or load_config(DEFAULT_CONFIG)['destination'])
    lock = ControllerRunLock(path=root/'.automation_logs/all_platform_downloads/controller.lock',
                             wait_seconds=0,run_id='archive-months-'+uuid.uuid4().hex[:8],execution_lane='all',
                             logger=logging.getLogger('archive-months'))
    # Protect preview hashing and apply from a concurrent downloader.
    lock.acquire()
    try:
        plan = plan_archive(root)
        manifest = root/'.automation_logs/archive_migrations'/f'{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.json'
        atomic_json(manifest,plan)
        if args.apply:
            apply_archive(plan,service_from_env(root));atomic_json(manifest,plan)
        print(f"{'已整理' if args.apply else '待整理'} {len(plan['moves'])} 个旧文件；无法识别日期 {len(plan['skipped'])} 个")
        print(f'迁移清单：{manifest}')
    finally:
        lock.release()


if __name__ == '__main__':
    main()
