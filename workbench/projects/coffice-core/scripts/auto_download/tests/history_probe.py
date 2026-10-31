"""Opt-in live DOM checks; exports only with explicit --download-jd."""
from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright
from apps.fund_split_adjust.server import load_project_env
from scripts.auto_download.run_all_platform_downloads import CloakMcpClient, DEFAULT_MCP_URL, as_list, parse_profile_note


async def probe(options, endpoint, metadata):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            if options.kind == 'jd':
                from scripts.auto_download.playwright.jd_settlement_download import select_mode, latest_row, run
                await select_mode(page, 'day')
                _, value = await latest_row(page, 'day', options.date)
                if options.download_jd:
                    await page.close()
                    with tempfile.TemporaryDirectory(prefix='calendar-live-jd-') as directory:
                        root=Path(directory)
                        await run(endpoint,metadata['platform'],metadata['company'],metadata['shop'],
                                  'day',root/'work',root/'archive',options.date)
                        files=list((root/'archive').rglob('*.csv'))
                        assert len(files)==1 and files[0].stat().st_size>0
                        assert files[0].parent.name==options.date[:7].replace('-','.')
                        print('DOWNLOAD_VERIFIED',files[0].stat().st_size,'bytes; temporary files cleaned')
            elif options.kind == 'xhs':
                from scripts.auto_download.playwright.xiaohongshu_fund_download import FUND_URL
                from scripts.auto_download.playwright.xiaohongshu_download_common import open_report_page, select_bill_mode, latest_bill_row
                await page.close(); page=await open_report_page(context,FUND_URL)
                await select_bill_mode(page,'day')
                _, value=await latest_bill_row(page,'day',options.date)
            elif options.kind == 'ks':
                from scripts.auto_download.playwright.kuaishou_fund_download import FUND_BASE_URL, QUERY_RE, latest_bill_row, infer_sub_mch_id
                sub_mch=infer_sub_mch_id(browser)
                url=FUND_BASE_URL+('?' + urlencode({'subMchId':sub_mch}) if sub_mch else '')
                await page.goto(url,wait_until='domcontentloaded')
                await page.get_by_role('button',name=QUERY_RE).click()
                _, value=await latest_bill_row(page,'day',options.date)
            else:
                from scripts.auto_download.playwright.tmall_taobao_union_promotion_download import PROMOTION_REPORT_URL, select_period
                from scripts.auto_download.playwright.tmall_promotion_download_common import open_alimama_page, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV
                await page.close();page=await open_alimama_page(browser,PROMOTION_REPORT_URL,DEFAULT_USERNAME,DEFAULT_PASSWORD_ENV)
                value=await select_period(page,'day',options.date,options.end_date or options.date)
            print('EXACT_DATE',value)
        finally:
            if not page.is_closed():await page.close()


def main():
    load_project_env()
    parser=argparse.ArgumentParser(description='真实历史查询验收；默认不导出')
    parser.add_argument('kind',choices=('jd','xhs','ks','union'))
    parser.add_argument('--date',default='2026-08-01')
    parser.add_argument('--end-date')
    parser.add_argument('--download-jd',action='store_true')
    options=parser.parse_args()
    if options.download_jd and options.kind!='jd':parser.error('--download-jd仅用于京东临时下载验收')
    names={'jd':'JD-京东-MOCK饮品旗舰店','xhs':'XHS-小红书-MOCK旗舰店','ks':'KS-快手-MOCK禧饮专卖店','union':'TMALL-天猫-MOCK旗舰店-财务账号'}
    client=CloakMcpClient(DEFAULT_MCP_URL,logging.getLogger('probe'));client.initialize();client.load_tools()
    profiles=as_list(client.call('list_profiles',{}),label='profiles')
    profile=next(p for p in profiles if p['name']==names[options.kind])
    metadata=parse_profile_note(profile['note'],profile['name'])
    active=as_list(client.call('list_active',{}),label='active')
    existing=next((p for p in active if p['id']==profile['id']),None)
    result=existing or client.call('start_profile',{'id':profile['id']})
    try:asyncio.run(probe(options,result['wsEndpoint'],metadata))
    finally:
        if not existing:client.call('stop_profile',{'id':profile['id']})


if __name__=='__main__':main()