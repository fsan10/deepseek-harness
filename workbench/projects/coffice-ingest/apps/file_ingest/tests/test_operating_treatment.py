from __future__ import annotations

import unittest

from apps.file_ingest.service import FileIngestService
from apps.identity_access.authorization import required_permission


class OperatingRuleTests(unittest.TestCase):
    def test_description_match_does_not_hide_a_new_scene_with_same_business_type(self):
        rule = dict(platform_code='ks',source_document_type='fund',source_business_type='资金扣减',
                    source_description_match_type='exact',source_description_match_value='已配置服务费')
        candidate = dict(source_document_type='fund',source_business_type='资金扣减',
                         source_description='另一项服务费',secondary_category_name='资金扣减 + 另一项服务费')
        self.assertFalse(FileIngestService._fee_rule_matches(rule,'ks',candidate))
        rule['source_description_match_type']='prefix'
        rule['source_description_match_value']='另一项'
        self.assertTrue(FileIngestService._fee_rule_matches(rule,'ks',candidate))

    def test_inactive_classification_still_retains_source_rule(self):
        rule = dict(platform_code='pdd',source_document_type='settlement',is_active=False,
                    secondary_category_name='提现',source_description_match_type='none')
        candidate = dict(source_document_type='settlement',secondary_category_name='提现')
        self.assertTrue(FileIngestService._fee_rule_matches(rule,'pdd',candidate))

    def test_detail_requires_its_own_read_permission(self):
        self.assertEqual('platform_fee.raw.view',required_permission('GET','/api/ingest/operating-details'))


if __name__ == '__main__':
    unittest.main()
