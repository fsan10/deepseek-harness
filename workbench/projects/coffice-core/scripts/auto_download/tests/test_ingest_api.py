from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from scripts.auto_download.ingest_api import IngestAPIError, _request, submit_archived_reports


class IngestAPIRequestTests(unittest.TestCase):
    def test_http_preflight_error_keeps_safe_category_without_response_secrets(self):
        from urllib.error import HTTPError
        payload = {'message':'文件业务日期超出完整查询范围：token=never-echo password=never-echo'}
        error = HTTPError('http://ingest.test',400,'bad request',{},io.BytesIO(json.dumps(payload).encode()))
        with patch('scripts.auto_download.ingest_api.urlopen',side_effect=error):
            with self.assertRaises(IngestAPIError) as raised:
                _request('http://ingest.test','test-token','/api/ingest/runs/id/coverage-preflight',b'{}','application/json','key')
        self.assertIn('阶段=覆盖预检', str(raised.exception))
        self.assertIn('覆盖范围校验未通过', str(raised.exception))
        self.assertNotIn('never-echo', str(raised.exception))

    def test_jd_bill_date_uses_actual_receipt_instead_of_requested_day(self):
        calls=[]
        def request(base,token,path,body,content_type,key,**kwargs):
            calls.append((path,body))
            if path.endswith('/shops'): return {'items':[{'platform_code':'jd','platform_name':'京东',
                'company_name':'测试公司','shop_name':'测试店','shop_code':'one'}]}
            if path=='/api/ingest/runs': return {'run_id':'test-run','status':'draft'}
            if path.endswith('/coverage-preflight'): return {'blocked':False,'token':'reviewed','summary':{}}
            return {}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'INGEST_ROBOT_TOKEN':'test-only'}), \
                patch('scripts.auto_download.ingest_api._request',side_effect=request):
            path=Path(directory)/'bill.csv'; path.write_text('fixture',encoding='utf-8')
            submit_archived_reports(Path(directory),[{'relative_path':path.name,'report_type':'jd_settlement',
                'shop_code':'one','platform_code':'jd','coverage_verified':True,
                'business_date_start':'2026-10-19','business_date_end':'2026-10-19'}],
                period={'start':'2026-10-20','end':'2026-10-20'})
        body=next(body for path,body in calls if path.endswith('/files')).decode()
        self.assertIn('"bill_date": "2026-10-19"', body)
        self.assertNotIn('2026-10-20', body)

    def test_archive_upload_supplies_dim_shop_report_and_query_range_before_complete(self):
        calls=[]
        def request(base,token,path,body,content_type,key,**kwargs):
            calls.append((path,body,kwargs))
            if path.endswith('/shops'):return {'items':[{'platform_code':'douyin','platform_name':'抖音',
                'company_name':'测试公司','shop_name':'测试店','shop_code':'standard-one'}]}
            if path=='/api/ingest/runs':
                self.assertEqual(json.loads(body)['source'],'api');return {'run_id':'test-run','status':'draft'}
            if path.endswith('/coverage-preflight'):return {'blocked':False,'token':'reviewed','summary':{'new_only':1}}
            return {}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'INGEST_ROBOT_TOKEN':'test-only-token'}),patch('scripts.auto_download.ingest_api._request',side_effect=request):
            path=Path(directory)/'arbitrary-name.csv';path.write_text('test fixture',encoding='utf-8')
            submit_archived_reports(Path(directory),[{'relative_path':path.name,'report_type':'douyin_fund',
                'coverage_verified':True,'business_date_start':'2026-10-01','business_date_end':'2026-10-18'}],
                metadata={'platform':'抖音','company':'测试公司','shop':'测试店'})
        upload=next(body for path,body,_ in calls if path.endswith('/files')).decode()
        self.assertIn('standard-one',upload);self.assertIn('douyin_fund',upload);self.assertIn('2026-10-18',upload)
        self.assertEqual(json.loads(calls[-1][1])['preflight_token'],'reviewed')

    def test_manual_archive_cannot_fall_back_to_the_robot_credential(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'INGEST_USERNAME':'','INGEST_PASSWORD':'','INGEST_ROBOT_TOKEN':'test-only-token'}):
            path=Path(directory)/'file.csv';path.write_text('test fixture',encoding='utf-8')
            with self.assertRaisesRegex(IngestAPIError,'人工终端上传需要用户登录'):
                submit_archived_reports(Path(directory),[{'relative_path':path.name}],source='manual')

    @patch("scripts.auto_download.ingest_api.time.sleep")
    @patch("scripts.auto_download.ingest_api.urlopen")
    def test_transient_error_retries_same_idempotent_request(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            URLError("temporary connection failure"),
            io.BytesIO(json.dumps({"data": {"run_id": "safe-test-id"}}).encode()),
        ]

        result = _request(
            "http://ingest.test",
            "test-token",
            "/api/ingest/runs",
            b'{"source":"api"}',
            "application/json",
            "stable-idempotency-key",
        )

        self.assertEqual(result, {"run_id": "safe-test-id"})
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)
        first_request = mock_urlopen.call_args_list[0].args[0]
        second_request = mock_urlopen.call_args_list[1].args[0]
        self.assertEqual(first_request.data, second_request.data)
        self.assertEqual(
            first_request.get_header("Idempotency-key"),
            second_request.get_header("Idempotency-key"),
        )

    @patch("scripts.auto_download.ingest_api.time.sleep")
    @patch("scripts.auto_download.ingest_api.urlopen")
    def test_http_error_is_not_retried(self, mock_urlopen, mock_sleep):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "http://ingest.test", 400, "bad request", {}, io.BytesIO(b"ignored")
        )

        with self.assertRaisesRegex(IngestAPIError, "HTTP 400"):
            _request(
                "http://ingest.test",
                "test-token",
                "/api/ingest/runs",
                b'{"source":"api"}',
                "application/json",
                "stable-idempotency-key",
            )

        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
