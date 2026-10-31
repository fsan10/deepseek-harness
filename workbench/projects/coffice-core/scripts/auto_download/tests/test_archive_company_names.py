from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from apps.file_ingest.naming import guess_filename
from scripts.auto_download.archive_company_names import plan_company_rename, validate_dim
from scripts.auto_download.archive_months import apply_archive
from scripts.auto_download.move_report import file_digest

OLD = '南京南京宁盏食品科技有限公司'
COMPANY = '南京宁盏食品科技有限公司'
SHOP = 'MOCK宁盏冲饮专卖店'


class ArchiveCompanyTests(unittest.TestCase):
    def test_renames_exact_identity_preserving_data_dates_sequences_and_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for report in ('订单','资金','结算'):
                folder=root/'抖音'/report/'2026.10';folder.mkdir(parents=True)
                (folder/f'20261009_抖音_{OLD}_{SHOP}_{report}_002.csv').write_bytes(b'original-data')
            other=root/'抖音/订单/2026.10'/f'20261009_抖音_{OLD}_其他店铺_订单.csv'
            other.write_bytes(b'other-data')
            plan=plan_company_rename(root,'抖音',OLD,COMPANY,SHOP)
            self.assertEqual(3,len(plan['moves']))
            item=plan['moves'][0]
            receipt=root/'.automation_logs/report_receipts/test.json';receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'relative_path':item['source'],'file_name':Path(item['source']).name}),encoding='utf-8')
            cursor=Mock();cursor.fetchone.return_value={'count':0}
            @contextmanager
            def transaction(): yield cursor
            apply_archive(plan,Mock(transaction=transaction))
            for move in plan['moves']:
                target=root/move['target']
                self.assertEqual(move['sha256'],file_digest(target))
                self.assertTrue(target.name.endswith('_002.csv'))
                self.assertTrue(guess_filename(target.name,[{'platform_code':'douyin','company_name':COMPANY,
                                                            'shop_name':SHOP,'shop_code':'219888797'}])['matched'])
            self.assertTrue(other.exists())
            self.assertEqual({'relative_path':item['target'],'file_name':Path(item['target']).name},json.loads(receipt.read_text()))
            cursor.execute.assert_any_call('UPDATE ops.automation_artifact SET relative_path=%s,file_name=%s WHERE relative_path=%s',
                                           (item['target'],Path(item['target']).name,item['source']))
            self.assertEqual([],plan_company_rename(root,'抖音',OLD,COMPANY,SHOP)['moves'])

    def test_conflict_refuses_overwrite_without_moving_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'抖音/资金';folder.mkdir(parents=True)
            for company in (OLD,COMPANY):
                (folder/f'20261009_抖音_{company}_{SHOP}_资金.csv').write_bytes(company.encode())
            with self.assertRaisesRegex(ValueError,'拒绝覆盖'):
                plan_company_rename(root,'抖音',OLD,COMPANY,SHOP)
            self.assertEqual(2,len(list(folder.iterdir())))

    def test_dim_requires_the_complete_unique_current_identity(self):
        service=Mock()
        service.file_ingest.list_shops.return_value=[{'platform_name':'抖音','company_name':COMPANY,'shop_name':SHOP}]
        validate_dim(service,'抖音',COMPANY,SHOP)
        with self.assertRaisesRegex(ValueError,'无唯一有效映射'):
            validate_dim(service,'抖音',OLD,SHOP)
        service.file_ingest.list_shops.return_value *= 2
        with self.assertRaises(ValueError):validate_dim(service,'抖音',COMPANY,SHOP)
