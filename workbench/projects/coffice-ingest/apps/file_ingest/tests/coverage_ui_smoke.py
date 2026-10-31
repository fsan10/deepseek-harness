"""Real browser UI checks against deterministic HTTP fixtures; no IAM/PG writes."""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from apps.file_ingest.registry import REPORT_BY_TYPE
from apps.file_ingest.tests.finance_ui_preview_server import PreviewHandler


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),PreviewHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    errors=[];writes=[];state={'complete':False,'mode':'fill_gaps'}
    shop=dict(platform_code='douyin',platform_name='抖音',company_code='test',company_name='测试公司',shop_code='one',shop_name='测试店')
    task={'file_task_id':'ui-task','client_file_id':'ui-file','report_type':'douyin_fund','status':'uploaded',**{'resolved_'+k:v for k,v in shop.items()},'source_file_name':'ui.csv','coverage':{}}
    run={'run_id':'ui-run','source':'manual','status':'draft','expected_file_count':1,'import_mode':'fill_gaps','success_file_count':0,'duplicate_file_count':0,'failed_file_count':0}
    etl={'etl_run_id':'ui-etl','status':'failed','trigger_type':'ingest_complete','scope':'affected',
         'requested_etls':['jd_main_business_finance'],'refresh_context':{'mode':'incremental','batch_cutoff':776,
             'source_selection_cutoff':0,'months':{'jd':['2026-10-01']},'shops':{'jd':['one']}}}
    def intercept(route):
        request=route.request;path=urlparse(request.url).path;method=request.method
        body=json.loads(request.post_data) if request.post_data and 'application/json' in request.headers.get('content-type','') else {}
        if method=='POST':writes.append((path,body))
        if path=='/api/ingest/report-types':data={'items':[REPORT_BY_TYPE['douyin_fund'].public_dict()]}
        elif path=='/api/ingest/shops':data={'items':[shop]}
        elif path=='/api/ingest/guess':data={'matched':True,**shop,'report_type':'douyin_fund','report_name':'资金'}
        elif path=='/api/ingest/health':data={'ingest_ready':True,'active_worker_count':1,'ingest_coverage_version':1}
        elif path=='/api/ingest/runs' and method=='POST':run['import_mode']=body.get('import_mode','fill_gaps');data=run
        elif path.endswith('/files'):data=task
        elif path.endswith('/coverage-preflight'):
            state['mode']=body.get('import_mode','fill_gaps');run['import_mode']=state['mode']
            blocked=state['mode']!='replace_range' or not body.get('coverage',{}).get('reason')
            data={'mode':state['mode'],'token':'ui-reviewed-token','blocked':blocked,'summary':{'different':1,'new_only':1},
                  'message':'存在差异，请核对后选择以本次范围为准' if blocked else '预检通过',
                  'items':[{'shop_identity_key':'douyin|one','report_type':'douyin_fund','days':[
                      {'date':'2026-10-01','status':'different','old_rows':2,'new_rows':2,'old_amount':'10','new_amount':'20','blocked':blocked},
                      {'date':'2026-10-02','status':'new_only','old_rows':0,'new_rows':1,'old_amount':'0','new_amount':'5','blocked':False}]}]}
        elif path.endswith('/complete'):
            assert body['preflight_token']=='ui-reviewed-token'
            state['complete']=True;run['status']='success';data={'run':run,'files':[task],'etl_runs':[]}
        elif path=='/api/ingest/runs/ui-run':data={'run':run,'files':[task],'etl_runs':[]}
        elif path=='/api/etl/runs':data={'items':[etl],'operators':[],'pagination':{'total':1,'page':1,'page_size':10}}
        elif path=='/api/etl/runs/ui-etl':data={'run':etl,'tasks':[{'etl_task_id':'ui-etl-task','sequence_no':1,
            'etl_key':'jd_main_business_finance','etl_label':'京东主营财务','status':'failed','error_message':'测试快照差异'}],
            'snapshot_diagnostics':{'snapshot_stale':True,'current_batch_cutoff':779,
                'message':'[STALE_SNAPSHOT] 相关钱包批次777不在快照中；本次仍使用冻结输入'}}
        elif path=='/api/etl/tasks/ui-etl-task/retry':
            assert body=={'snapshot_policy':'latest'}
            data={'etl_run_id':'ui-etl','message':'已创建关联运行，原范围重跑'}
        else:data={'items':[],'operators':[],'pagination':{'total':0,'page':1,'page_size':10},'total':0}
        route.fulfill(status=200,content_type='application/json',body=json.dumps({'code':0,'data':data},ensure_ascii=False))
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1050})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/identity-assets/shell.js',lambda route:route.fulfill(content_type='application/javascript',body="window.appCsrfToken=()=> 'test-only-csrf';"))
            page.route('**/api/**',intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/ingest/#upload')
            page.locator('#fileInput').set_input_files({'name':'ui.csv','mimeType':'text/csv','buffer':b'test fixture'})
            page.locator('[data-file-check]').check()
            page.locator('#submitFiles').click()
            page.locator('#coverageDialog').wait_for(state='visible')
            page.wait_for_function("document.getElementById('coverageSummary').textContent.includes('存在差异')")
            assert page.locator('#coverageApply').is_disabled()
            assert not any(path.endswith('/complete') for path,_ in writes)
            page.locator('#coverageMode').select_option('replace_range')
            page.locator('#coverageStart').fill('2026-10-01');page.locator('#coverageEnd').fill('2026-10-02')
            page.locator('#coverageComplete').check();page.locator('#coverageReason').fill('与财务核对后以本次完整导出为准')
            page.locator('#coverageRecheck').click()
            page.wait_for_function("!document.getElementById('coverageApply').disabled")
            out=Path('.codex_tmp');out.mkdir(exist_ok=True)
            page.screenshot(path=str(out/'ingest-coverage-preview.png'),full_page=True)
            for width in (1100,1920):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.locator('#coverageDialog').bounding_box()['width']<=width
            page.locator('#coverageApply').click()
            page.wait_for_function("!document.getElementById('coverageDialog').open")
            assert state['complete'];assert not errors,errors
            page.goto(f'http://127.0.0.1:{server.server_port}/ingest/#etl')
            page.locator('[data-etl-detail="ui-etl"]').click()
            page.locator('#etlDetailDialog').wait_for(state='visible')
            page.wait_for_function("document.getElementById('etlDetailMeta').textContent.includes('不会扩展到新月份')")
            assert '不会扩展到新月份' in page.locator('#etlDetailMeta').inner_text()
            assert 'STALE_SNAPSHOT' in page.locator('#etlDetailSummary').inner_text()
            assert page.get_by_role('button',name='使用最新数据重跑').count()==1
            assert page.get_by_role('button',name='原快照复现').count()==0
            for width in (1100,1440,1920):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.locator('#etlDetailDialog').bounding_box()['width']<=width
            page.screenshot(path=str(out/'etl-snapshot-review-preview.png'),full_page=True)
            with page.expect_response(lambda response:'/api/etl/tasks/ui-etl-task/retry' in response.url):
                page.get_by_role('button',name='使用最新数据重跑').click()
            page.wait_for_function("document.getElementById('etlDetailDialog').open")
            assert any(path=='/api/etl/tasks/ui-etl-task/retry' and body=={'snapshot_policy':'latest'} for path,body in writes)
            assert not errors,errors
            browser.close()
        print(json.dumps({'browser_errors':errors,'preview_before_complete':True,'replacement_reviewed':True,
                          'latest_retry_and_snapshot_scope':True,'viewport_widths':[1100,1440,1920],'server_stopped_on_exit':True},ensure_ascii=False))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


if __name__=='__main__':main()
