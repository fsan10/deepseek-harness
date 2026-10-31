"""Execute a registry-approved ETL in an isolated scoped database runtime."""
from __future__ import annotations

import argparse
import json
import os
import runpy
import sys

import psycopg2

from apps.file_ingest.registry import ETL_SPECS, PROJECT_ROOT
from etl.common.refresh_runtime import RefreshScope, connection_factory
from etl.common.errors import SourceNotReady


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--etl-key', required=True, choices=sorted(ETL_SPECS))
    args, extra = parser.parse_known_args()
    context = json.loads(os.environ['MOCK_COFFICE_REFRESH_CONTEXT'])
    scope = RefreshScope(context)
    if not scope.full and not scope.platforms:
        print('刷新范围为空：重复文件或没有业务数据变化，无需执行ETL')
        return
    if scope.full:
        print('刷新模式：人工全量', flush=True)
    else:
        print('刷新模式：增量；业务月份：' + json.dumps(context['months'], ensure_ascii=False)
              + '；标准店铺：' + json.dumps(context.get('shops', {}), ensure_ascii=False), flush=True)
    spec = ETL_SPECS[args.etl_key]
    if not spec.enabled:
        raise ValueError('ETL已停用')
    connect = psycopg2.connect
    factory = connection_factory(context)

    def scoped_connect(*arguments, **keywords):
        if 'connection_factory' in keywords:
            raise ValueError('注册ETL不允许绕过增量数据库运行时')
        keywords['connection_factory'] = factory
        return connect(*arguments, **keywords)

    # Manual full refresh retains the original installation and rebuild path.
    # Only an incremental child installs the scoped connection; other processes
    # retain their own connections and the metric modules own transactions.
    if not scope.full:
        psycopg2.connect = scoped_connect
    sys.argv = [str(spec.command_path), *spec.args, *extra]
    module = '.'.join(spec.command_path.relative_to(PROJECT_ROOT).with_suffix('').parts)
    try:
        runpy.run_module(module, run_name='__main__')
    except SourceNotReady as exc:
        print('[SOURCE_NOT_READY] ' + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(3) from None
    finally:
        psycopg2.connect = connect


if __name__ == '__main__':
    main()
