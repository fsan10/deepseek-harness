from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from scripts.auto_download.archive_months import apply_archive, plan_archive
from scripts.auto_download.move_report import file_digest


class ArchiveMigrationTests(unittest.TestCase):
    def test_preserves_content_and_unknown_names_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'京东/结算';folder.mkdir(parents=True)
            source=folder/'20260801_京东_公司_店铺_结算.csv';source.write_bytes(b'original-data')
            (folder/'unknown.csv').write_bytes(b'unknown')
            existing=folder/'2026.08'/source.name;existing.parent.mkdir();existing.write_bytes(b'existing-data')
            plan=plan_archive(root)
            cursor=Mock();cursor.fetchone.return_value={'count':0}
            @contextmanager
            def transaction(): yield cursor
            apply_archive(plan,Mock(transaction=transaction))
            self.assertEqual(b'existing-data',existing.read_bytes())
            target=root/plan['moves'][0]['target'];self.assertEqual(b'original-data',target.read_bytes())
            self.assertEqual(plan['moves'][0]['sha256'],file_digest(target))
            self.assertEqual(1,len(plan['skipped']));self.assertFalse(source.exists())

    def test_database_failure_restores_the_moved_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'京东/结算';folder.mkdir(parents=True)
            source=folder/'20260801_京东_公司_店铺_结算.csv';source.write_bytes(b'original')
            cursor=Mock();cursor.fetchone.return_value={'count':0}
            def execute(sql,*_):
                if sql.startswith('UPDATE'):raise RuntimeError('simulated DB failure')
            cursor.execute.side_effect=execute
            @contextmanager
            def transaction(): yield cursor
            with self.assertRaises(RuntimeError):apply_archive(plan_archive(root),Mock(transaction=transaction))
            self.assertEqual(b'original',source.read_bytes())

