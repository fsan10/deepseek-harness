"""Isolated browser QA; fixture HTTP server never connects to IAM or PG."""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

from apps.file_ingest.tests.finance_ui_preview_server import PreviewHandler


def main():
    output=Path('.codex_tmp')
    output.mkdir(exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),PreviewHandler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    fees=[dict(mapping_id=i,platform_code='pdd',platform_name='拼多多',source_document_type='settlement',
        secondary_category_name=name,secondary_category_code='scene_'+str(i),primary_category_code=cat,
        primary_category_name=label,operating_treatment=treatment,is_active=True,
        mapping_status='mapped' if cat!='unmapped' else 'unmapped') for i,name,cat,label,treatment in (
            (719,'交易收入 + 订单收入','sales_income','商品销售收入','income'),
            (722,'退款 + 订单退款','sales_refund','销售退款','income'),
            (725,'技术服务费 + 基础技术服务费','unmapped','未映射','expense'),
            (723,'提现 + 提现申请','excluded','不计平台费用','excluded'))]
    details=[dict(stat_date='2026-09-30',platform_name='拼多多',shop_name='养颜轻食',source_document_type='settlement',
        secondary_category_name='提现 + 提现申请',primary_category_name='不计平台费用',operating_treatment='excluded',
        source_signed_amount='-165000.00',income_amount='0.00',expense_amount='0.00',mapping_status='mapped',
        exclusion_reason='账户提现属于资金转出。'),
        dict(stat_date='2026-09-30',platform_name='拼多多',shop_name='养颜轻食',source_document_type='settlement',
        secondary_category_name='技术服务费 + 基础技术服务费',primary_category_name='未映射',operating_treatment='expense',
        source_signed_amount='-1437.22',income_amount='0.00',expense_amount='1437.22',mapping_status='unmapped',exclusion_reason='')]
    errors=[]
    capabilities={'version':2}
    writes=[]
    reads=[]
    scene_writes=[]
    scene_rules=[dict(rule_id=1,rule_name='资金场景去除订单单号尾缀',platform_code='ks',source_document_type='fund',
        source_business_type=None,pattern='-订单号[：:]?.*$',replacement='',priority=30,is_active=True,note='',configuration_etl_status='queued',updated_at='2026-10-17T00:00:00+00:00')]
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/identity-assets/shell.js',lambda route:route.fulfill(
                body='window.currentUser={is_super_admin:true};',content_type='application/javascript'))
            def respond(route):
                url=route.request.url
                if '/fee-mappings/scene-rules/preview' in url:
                    data={'preview_token':'scene-preview-token','changed_names':1780,'source_names_before':1832,'source_names_after':34,
                        'examples':[{'before':'货款结算 + 快手小店交易结算-订单号：123456','after':'货款结算 + 快手小店交易结算'}],
                        'conflicts':[],'can_save':True,'scope_note':'只清洗名称，金额与经营归属不变。'}
                elif '/fee-mappings/scene-rules' in url:
                    if route.request.method=='POST':
                        scene_writes.append(route.request.post_data_json)
                        data={'rule':route.request.post_data_json,'etl_run':None}
                    else:data={'items':scene_rules}
                elif route.request.method=='POST' and '/fee-mappings/preview' in url:
                    payload=route.request.post_data_json
                    data={'items':[{'stat_month':'2026-09-01','shop_name':'预览店铺','income_delta':'1','expense_delta':'-1'}],
                        'source_rows':12,'rule_count':len(payload['items']),'income_delta':'1','expense_delta':'-1','scope_note':'全部匹配店铺和历史月份'}
                elif route.request.method=='POST' and '/fee-mappings/assign' in url:
                    payload=route.request.post_data_json
                    writes.append(payload)
                    changed=[]
                    for selected in payload['items']:
                        row=next(row for row in fees if row['mapping_id']==selected['mapping_id'])
                        for key in ('operating_treatment','primary_category_code','primary_category_name'):
                            if key in payload:
                                row[key]=payload[key]
                        changed.append(row)
                    data={'items':changed}
                elif '/source' in url:
                    data={'rule':{**fees[0],'source_usage_label':'可配置的独立金额','source_usage_note':'可由财务确认归属','treatment_editable':True},
                        'evidence':{'source_rows':12,'matched_rows':0,'missing_identity_rows':0,'samples':[],'correction_available':False}}
                elif '/ingest/health' in url:
                    data={'ready':True,'operating_treatment_version':capabilities['version'],'scene_normalization_version':1}
                elif '/fee-mappings' in url:
                    data={'items':fees,'pagination':{'total':4,'unmapped_total':1,'page':1,'page_size':10}}
                elif '/operating-details' in url:
                    reads.append(url)
                    data={'items':details,'summary':{'income_amount':'233496.90','expense_amount':'5302.45','scene_total':2},
                        'pagination':{'total':2,'unmapped_total':1,'page':1,'page_size':10}}
                elif '/fee-categories' in url:
                    data={'items':[{'primary_category_code':'sales_income','primary_category_name':'商品销售收入'},
                        {'primary_category_code':'sales_refund','primary_category_name':'销售退款'}]}
                elif '/report-types' in url:
                    data={'items':[{'platform_code':'pdd','platform_name':'拼多多'},{'platform_code':'ks','platform_name':'快手'}]}
                else:
                    data={'items':[],'ready':True}
                route.fulfill(content_type='application/json',body=json.dumps({'code':0,'data':data},ensure_ascii=False))
            page.route('**/api/**',respond)
            page.goto(f'http://127.0.0.1:{server.server_port}/ingest/#feeMappings')
            page.locator('#feeBody tr').first.wait_for()
            page.set_viewport_size({'width':1920,'height':1000})
            assert '原始业务类型' not in page.locator('#feeMappingTable thead').inner_text()
            assert 'scene_' not in page.locator('#feeBody').inner_text()
            assert '可配置的独立金额' not in page.locator('#feeBody').inner_text()
            positions=page.locator('#feeBody tr').first.locator('.row-actions button').evaluate_all('(buttons)=>buttons.map(b=>b.getBoundingClientRect().top)')
            assert max(positions)-min(positions)<2,positions
            assert page.locator('.fee-table-wrap').evaluate('(e)=>e.scrollWidth<=e.clientWidth'), 'full screen must fit the table'
            page.screenshot(path=str(output/'operating-config-wide.png'),full_page=True)
            page.locator('[data-page="sceneRules"]').click();page.locator('#sceneRulesPage').wait_for(state='visible')
            assert page.url.endswith('#sceneRules')
            assert page.locator('#sceneRuleRows tr').count()==1
            assert page.locator('[data-page="sceneRules"]').get_attribute('aria-current')=='page'
            assert page.locator('[data-page="feeMappings"]').get_attribute('aria-current') is None
            assert '等待重算' in page.locator('#sceneRuleRows').inner_text()
            page.locator('#sceneRuleKeyword').fill('不存在的清洗规则');page.locator('#searchSceneRules').click()
            assert '共 0 条规则' in page.locator('#sceneRuleTotal').inner_text()
            page.locator('#resetSceneRules').click()
            assert '共 1 条规则' in page.locator('#sceneRuleTotal').inner_text()
            page.screenshot(path=str(output/'scene-rules-list.png'),full_page=True)
            page.locator('[data-edit-scene-rule="0"]').click()
            assert page.locator('#saveSceneRule').is_disabled()
            page.locator('#previewSceneRule').click();page.locator('#saveSceneRule').wait_for(state='visible')
            page.wait_for_function("!document.getElementById('saveSceneRule').disabled")
            assert '快手小店交易结算' in page.locator('#sceneRuleExamples').inner_text()
            assert not scene_writes
            page.screenshot(path=str(output/'scene-rules-preview.png'),full_page=True)
            page.locator('#sceneRuleReplacement').fill('修改后须重新预览')
            assert page.locator('#saveSceneRule').is_disabled()
            page.locator('[data-close-dialog="sceneRuleEditor"]').last.click();assert not scene_writes
            page.locator('[data-edit-scene-rule="0"]').click();page.locator('#previewSceneRule').click()
            page.wait_for_function("!document.getElementById('saveSceneRule').disabled")
            page.locator('#saveSceneRule').click();page.locator('#sceneRuleEditor').wait_for(state='hidden')
            assert scene_writes[-1]['preview_token']=='scene-preview-token'
            page.locator('[data-page="feeMappings"]').click()
            page.set_viewport_size({'width':1440,'height':1000})
            assert '归属待确认' in page.locator('#feeTreatment option').all_text_contents()
            page.locator('[data-source-fee="0"]').click()
            page.locator('#feeSourceDialog').wait_for(state='visible')
            assert '可配置的独立金额' in page.locator('#feeSourceContent').inner_text()
            page.locator('[data-close-dialog="feeSourceDialog"]').last.click()
            page.screenshot(path=str(output/'operating-config.png'),full_page=True)
            page.locator('[data-edit-fee="0"]').click()
            assert page.locator('#feeMappingInclude').input_value()=='income'
            assert page.locator('#feeMappingInclude option').all_text_contents()==[
                '归属待确认','收入（含冲减）','支出（含冲减）','不计入']
            page.screenshot(path=str(output/'operating-editor.png'),full_page=True)
            page.locator('[data-close-dialog="feeMappingDialog"]').last.click()
            with page.expect_request(lambda request:request.method=='POST' and '/fee-mappings/assign' in request.url) as submitted:
                page.evaluate("assignResolved(document.querySelector('[data-assign-trigger=\"0\"]'),'sales_refund','销售退款')")
            submitted.value.response()
            assert 'operating_treatment' not in writes[0]
            assert 'include_in_platform_expense' not in writes[0]
            capabilities['version']=0
            page.evaluate("assignResolved(document.querySelector('[data-assign-trigger=\"0\"]'),'sales_refund','销售退款')")
            page.locator('#toast').filter(has_text='请先重启后台服务').wait_for()
            assert len(writes)==1
            capabilities['version']=2
            treatment_selector='[data-assign-trigger="0"][data-assign-kind="treatment"]'
            page.locator(treatment_selector).click()
            assert page.locator('#assignOptions button').all_text_contents()==['收入','支出','不计入','归属待确认']
            page.locator('#assignOptions [data-assign-code="expense"]').click()
            page.locator('#operatingPreviewDialog').wait_for(state='visible')
            page.locator('#applyOperatingPreview').click()
            page.locator(treatment_selector).filter(has_text='支出').wait_for()
            assert writes[-1]['operating_treatment']=='expense'
            assert len(writes[-1]['items'])==1
            assert 'primary_category_code' not in writes[-1]
            assert fees[0]['primary_category_code']=='sales_refund'
            page.locator('#batchMapFees').click()
            page.locator('input[data-fee-index="0"]').check()
            page.locator('input[data-fee-index="2"]').check()
            page.locator(treatment_selector).click()
            page.locator('#assignOptions [data-assign-code="excluded"]').click()
            page.locator('#operatingPreviewDialog').wait_for(state='visible')
            assert '2 条规则' in page.locator('#operatingPreviewTotals').inner_text()
            before_cancel=len(writes)
            page.locator('[data-close-dialog="operatingPreviewDialog"]').last.click()
            assert len(writes)==before_cancel
            assert page.locator('input[data-fee-index="0"]').is_checked()
            page.locator(treatment_selector).click()
            page.locator('#assignOptions [data-assign-code="excluded"]').click()
            page.locator('#applyOperatingPreview').click()
            page.locator(treatment_selector).filter(has_text='不计入').wait_for()
            assert writes[-1]['operating_treatment']=='excluded'
            assert [row['mapping_id'] for row in writes[-1]['items']]==[719,725]
            assert fees[0]['primary_category_code']=='sales_refund'
            assert fees[2]['primary_category_code']=='unmapped'
            assert fees[1]['operating_treatment']=='income'
            assert not page.locator('#feeMappingDialog').is_visible()
            page.evaluate("switchPage('rawFees')")
            page.locator('#rawFeeBody tr').first.wait_for()
            assert '165,000.00' in page.locator('#rawFeeBody').inner_text()
            assert '未映射' in page.locator('#rawFeeBody').inner_text()
            for width in (1920,1440,1100):
                page.set_viewport_size({'width':width,'height':1000})
                positions=page.locator('#rawFeesPage .toolbar').evaluate('''toolbar => {
                    const controls=[...toolbar.querySelectorAll('.inline-field,.search-field,.button')];
                    return controls.map(control=>{const r=control.getBoundingClientRect();return {top:r.top,right:r.right,bottom:r.bottom}});
                }''')
                row_span=max(r['top'] for r in positions)-min(r['top'] for r in positions)
                assert (row_span<2 if width==1920 else row_span>2), positions
                assert max(r['right'] for r in positions)<=width, positions
                assert page.locator('#rawKeyword').bounding_box()['width']==240
                for selector in ('#rawDocument','#rawTreatment','#rawStatus'):
                    assert page.locator(selector).bounding_box()['width']==120
            page.set_viewport_size({'width':1920,'height':1000})
            raw_date=page.locator('[data-date-range="rawDateFrom,rawDateTo"]')
            raw_date.locator('button').click()
            page.locator('#dateRangeDropdown [data-date-days="30"]').click()
            start=page.locator('#rawDateFrom').input_value()
            end=page.locator('#rawDateTo').input_value()
            assert start and end
            assert raw_date.locator('.date-start').inner_text()==start
            assert raw_date.locator('.date-end').inner_text()==end
            with page.expect_request('**/api/ingest/operating-details?*') as queried:
                page.locator('#searchRawFees').click()
            assert f'date_from={start}' in queried.value.url and f'date_to={end}' in queried.value.url
            with page.expect_download():
                page.locator('#exportRawFees').click()
            assert f'date_from={start}' in reads[-1] and f'date_to={end}' in reads[-1]
            raw_date.locator('button').click()
            with page.expect_request('**/api/ingest/operating-details?*') as reset:
                page.locator('#resetRawFees').click()
            assert 'date_from=' not in reset.value.url and 'date_to=' not in reset.value.url
            assert raw_date.locator('.date-start').inner_text()=='开始日期'
            assert raw_date.locator('.date-end').inner_text()=='结束日期'
            assert not page.locator('#dateRangeDropdown').is_visible()
            page.screenshot(path=str(output/'operating-details.png'),full_page=True)
            headers=page.locator('.raw-fee-table-wrap th').all_text_contents()
            assert headers[headers.index('经营归属')+1]=='不计入原因'
            assert '日汇总' in page.locator('#rawFeeTotal').inner_text()
            # Release two queries in reverse order: the newest filter must win.
            held=[]
            page.route('**/api/ingest/fee-mappings?*',lambda route:held.append(route))
            page.evaluate('window.savedAbort=AbortController.prototype.abort;AbortController.prototype.abort=()=>{}')
            page.locator('[data-page="feeMappings"]').click()
            page.wait_for_timeout(100)
            assert len(held)==1
            assert page.locator('#feeMappingTable').get_attribute('aria-busy')=='true'
            assert page.locator('#feeTotal').inner_text()=='正在加载…'
            page.locator('#feeKeyword').fill('较新的筛选')
            page.locator('#searchFees').click()
            page.wait_for_timeout(100)
            assert len(held)==2
            def fee_result(label):
                return json.dumps({'code':0,'data':{'items':[{**fees[0],'secondary_category_name':label}],
                    'pagination':{'total':1,'unmapped_total':0,'page':1,'page_size':10}}},ensure_ascii=False)
            held[1].fulfill(content_type='application/json',body=fee_result('较新的查询结果'))
            page.wait_for_function("document.getElementById('feeBody').textContent.includes('较新的查询结果')")
            held[0].fulfill(content_type='application/json',body=fee_result('过期的查询结果'))
            page.wait_for_timeout(100)
            assert '较新的查询结果' in page.locator('#feeBody').inner_text()
            assert '过期的查询结果' not in page.locator('#feeBody').inner_text()
            page.evaluate('() => { AbortController.prototype.abort=window.savedAbort; }')
            browser.close()
            if errors:
                raise AssertionError(errors)
            print('经营归属直接修改、批量确认及取消、分类保留、日期查询及导出、布局、加载反馈及查询乱序验收通过，无页面错误')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__=='__main__':
    main()
