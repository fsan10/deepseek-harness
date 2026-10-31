import unittest
import uuid

from apps.file_ingest.service import FEE_ODS_CANDIDATE_QUERIES
from apps.file_ingest.service import FileIngestService
from unittest.mock import Mock
from apps.fund_split_adjust.server import json_default


class FeeCandidateTests(unittest.TestCase):
    def test_description_sensitive_platforms_expose_real_match_inputs(self):
        self.assertIn('BTRIM("资金动账备注")',FEE_ODS_CANDIDATE_QUERIES['jd'])
        self.assertIn('BTRIM("描述")',FEE_ODS_CANDIDATE_QUERIES['ks'])
        self.assertIn(" || ' + ' || ",FEE_ODS_CANDIDATE_QUERIES['ks'])

    def test_pdd_candidates_match_the_finance_scene_grain(self):
        query = FEE_ODS_CANDIDATE_QUERIES["pdd"]
        self.assertIn('BTRIM("账务类型") || \' + \' || BTRIM("业务描述")', query)
        self.assertNotIn('"备注"', query)

    def test_new_pdd_scene_is_visible_even_when_deduction_type_is_configured(self):
        cursor = Mock()
        configured = dict(platform_code='pdd',source_document_type='settlement',
                          secondary_category_name='扣款 + 已配置场景',
                          source_business_type='扣款',is_active=True)
        candidate = dict(source_document_type='settlement',source_business_type='扣款',
                         source_description='0040006|售后费用-缺货',
                         secondary_category_name='扣款 + 0040006|售后费用-缺货')
        def execute(query,params=None):
            cursor.fetchall.return_value = ([configured] if 'SELECT * FROM dim.' in query
                                           else [candidate] if 'ods_pdd_settlement_raw' in query else [])
        cursor.execute.side_effect = execute
        result = FileIngestService._fee_candidates(object.__new__(FileIngestService),cursor)
        shortage = [r for r in result if r['secondary_category_name']==candidate['secondary_category_name']]
        self.assertEqual(len(shortage),1)
        self.assertEqual(shortage[0]['mapping_status'],'unmapped')

    def test_tmall_candidates_use_the_dwd_standardized_scene(self):
        query = FEE_ODS_CANDIDATE_QUERIES["tmall"]
        self.assertIn('"备注"', query)
        self.assertIn("REGEXP_REPLACE", query)
        self.assertIn("source_business_type || ' + ' || standardized_note", query)

    def test_all_fee_platforms_have_stable_ods_candidate_queries(self):
        self.assertEqual(
            {"douyin", "jd", "tmall", "ks", "pdd", "wechat_channels", "xhs"},
            set(FEE_ODS_CANDIDATE_QUERIES),
        )

    def test_integrated_api_can_serialize_uuid_results(self):
        value = uuid.uuid4()
        self.assertEqual(str(value), json_default(value))


if __name__ == "__main__":
    unittest.main()
