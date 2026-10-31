#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天猫淘宝联盟与万相台推广费 WebAPI 下载。"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright

try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
    from .tmall_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        MTOP_HOST,
        NeedsHumanError,
        NaturalRequestCollector,
        UNION_PROMOTION_URL,
        WANXIANGTAI_URL,
        browser_user_agent,
        download_original_file,
        ensure_api_success,
        ensure_no_security_challenge,
        extract_first_url,
        get_browser_cookies,
        handle_alimama_login,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        query_value,
        response_json,
        session_request,
    )
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection
    from tmall_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        MTOP_HOST,
        NeedsHumanError,
        NaturalRequestCollector,
        UNION_PROMOTION_URL,
        WANXIANGTAI_URL,
        browser_user_agent,
        download_original_file,
        ensure_api_success,
        ensure_no_security_challenge,
        extract_first_url,
        get_browser_cookies,
        handle_alimama_login,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        query_value,
        response_json,
        session_request,
    )


FINANCE_PROFILE = "TMALL-天猫-MOCK旗舰店-财务账号"
UNION_HOST = "ad.alimama.com"
UNION_LIST_PATH = "/openapi/param2/1/gateway.unionadv/shopkeeper.rpt.process.list.json"
UNION_START_PATH = "/openapi/param2/1/gateway.unionadv/shopkeeper.rpt.taskstart.json"
UNION_FILE_PATH = "/openapi/param2/1/gateway.unionadv/shopkeeper.rpt.filelink.json"
WANXIANG_HOST = "stlacct.alimama.com"
WANXIANG_LIST_PATH = "/settleAccount/account/listAccountJournalWithTrans.json"
WANXIANG_COST_PATH = "/settleAccount/account/getHisCost.json"
WANXIANG_EXPORT_PATH = "/settleAccount/account/exportAccountJournalWithTrans.action"
UNION_REPORT = "淘宝联盟推广费"
WANXIANG_REPORT = "万相台推广费"
UNION_BIZ_TYPE = "96"
UNION_EXT = (
    '{"type":"cps","split":1,"period":"1d","level4Type":"day_level3",'
    '"headerKeys":"theDateTime,dimField,alipayAmt,alipayNum,preCommissionFee,'
    'preTotalFee,preCommissionRate,preServiceRate,enterShopPvTk,cartAddItmCnt,'
    'cltAddItmCnt,cmCommissionFee,cmServiceFee,cmTotalFee,cmCommissionRate,'
    'cmServiceRate,cpsSettleAmt,cpsSettleNum,preCommissionFee,preServiceFee,'
    'preTotalFee,preCommissionRate,preServiceRate,preGPP,cmCommissionFee,'
    'cmServiceFee,cmTotalFee,cmCommissionRate,cmServiceRate,depPreCommissionFee,'
    'depPreCommissionRate,enterShopPvTk,enterShopUvTk,tkPvItemCnt,cartAddItmCnt,'
    'cltAddItmCnt,alipayNumDepositPresale,alipayAmtDepositPresale,depPreRestAmt,'
    'depPreAlipayAmt,tkCouponGetCnt,alipayByrCnt,alipayAmt,alipayNum,alipayQuantity,'
    'cvr,tkSuccByrCnt,tkSuccAmt,tkSuccCnt,cpsSettleByrCnt,cpsSettleAmt,cpsSettleNum"}'
)


def _with_query(url: str, updates: dict[str, Any]) -> str:
    parsed = urlsplit(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in updates.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = str(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(values), ""))


def _cookie_value(cookies: list[dict[str, Any]], name: str) -> str | None:
    for cookie in cookies:
        if cookie.get("name") == name and cookie.get("value"):
            return str(cookie["value"])
    return None


def _union_token(template_url: str, cookies: list[dict[str, Any]]) -> str:
    token = query_value(template_url, "_tb_token_") or _cookie_value(cookies, "_tb_token_")
    if not token:
        raise NeedsHumanError("阿里妈妈页面没有产生动态登录令牌，请刷新 Profile")
    return token


async def _union_list(
    session: Any,
    template_url: str,
    token: str,
    *,
    start_date: str | None = None,
    page_url: str,
    user_agent: str,
) -> dict[str, Any]:
    url = _with_query(
        template_url,
        {
            "t": int(time.time() * 1000),
            "_tb_token_": token,
            "pageNo": 1,
            "pageSize": 20,
            "bizTypeList": "105,96",
            "timer": int(time.time() * 1000) if start_date else None,
        },
    )
    response = await session_request(
        session,
        "GET",
        url,
        label="淘宝联盟推广费导出历史",
        page_url=page_url,
        user_agent=user_agent,
    )
    body = response_json(response, label="淘宝联盟推广费导出历史")
    ensure_api_success(body, label="淘宝联盟推广费导出历史")
    return body


def union_record(body: Any, target_date: str) -> dict[str, Any] | None:
    data = body.get("data", {}) if isinstance(body, dict) else {}
    rows = data.get("result", []) if isinstance(data, dict) else []
    prefix = f"{target_date} 00:00:00~{target_date} 23:59:59"
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("bizType", 0) or 0) != int(UNION_BIZ_TYPE):
            continue
        if str(row.get("fileName") or "").startswith(prefix) and int(row.get("status", 0) or 0) == 1:
            return row
    return None


async def _union_file_url(
    session: Any,
    template_url: str,
    token: str,
    row_id: Any,
    *,
    page_url: str,
    user_agent: str,
) -> str:
    url = _with_query(
        template_url,
        {
            "t": int(time.time() * 1000),
            "_tb_token_": token,
            "idList": str(row_id),
            "bizType": UNION_BIZ_TYPE,
        },
    )
    response = await session_request(
        session,
        "GET",
        url,
        label="淘宝联盟推广费文件地址",
        page_url=page_url,
        user_agent=user_agent,
    )
    body = response_json(response, label="淘宝联盟推广费文件地址")
    ensure_api_success(body, label="淘宝联盟推广费文件地址")
    urls = body.get("data", {}).get("urlList", [])
    if not isinstance(urls, list) or not urls:
        raise ApiError("淘宝联盟推广费文件地址为空")
    value = urls[0].get("url") if isinstance(urls[0], dict) else None
    return extract_first_url(value)


async def download_union(
    browser: Any,
    target_date: str,
    output_dir: Path,
    *,
    timeout_seconds: int = 300,
    poll_interval: float = 3.0,
) -> Path | None:
    context = browser.contexts[0]
    collector = NaturalRequestCollector()
    collector.attach(context)
    page = await page_for(browser, lambda url: "alimama.com" in url)
    observed_after = time.monotonic()
    await handle_alimama_login(page, UNION_PROMOTION_URL)
    await ensure_no_security_challenge(page)
    try:
        list_request = await collector.wait_for_path(
            UNION_LIST_PATH,
            host=UNION_HOST,
            method="GET",
            observed_after=observed_after,
            timeout=35,
        )
    except ApiError:
        # 页面可能复用旧 Target，重新加载只获取自然列表请求，不操作日期控件。
        observed_after = time.monotonic()
        await page.reload(wait_until="domcontentloaded")
        list_request = await collector.wait_for_path(
            UNION_LIST_PATH,
            host=UNION_HOST,
            method="GET",
            observed_after=observed_after,
            timeout=35,
        )

    cookies = await get_browser_cookies(context)
    token = _union_token(list_request.url, cookies)
    session = make_requests_session(cookies)
    user_agent = await browser_user_agent(page)
    try:
        list_body = await _union_list(
            session,
            list_request.url,
            token,
            page_url=page.url,
            user_agent=user_agent,
        )
        row = union_record(list_body, target_date)
        if row is None:
            start = f"{target_date} 00:00:00"
            end = f"{target_date} 23:59:59"
            start_request = collector.latest(path=UNION_START_PATH, host=UNION_HOST, method="POST")
            start_url = start_request.url if start_request else f"https://{UNION_HOST}{UNION_START_PATH}"
            form = {
                "t": int(time.time() * 1000),
                "_tb_token_": token,
                "startTime": start,
                "endTime": end,
                "bizType": UNION_BIZ_TYPE,
                "ext": UNION_EXT,
            }
            response = await session_request(
                session,
                "POST",
                start_url,
                label="淘宝联盟推广费创建导出任务",
                page_url=page.url,
                user_agent=user_agent,
                data=form,
            )
            start_body = response_json(response, label="淘宝联盟推广费创建导出任务")
            if start_body.get("success") is False and "重复提交" not in str(start_body.get("bizErrorDesc") or ""):
                ensure_api_success(start_body, label="淘宝联盟推广费创建导出任务")
            log(UNION_REPORT, "导出", "已提交导出任务，开始轮询历史记录")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(max(0.1, poll_interval))
                list_body = await _union_list(
                    session,
                    list_request.url,
                    token,
                    start_date=target_date,
                    page_url=page.url,
                    user_agent=user_agent,
                )
                row = union_record(list_body, target_date)
                if row is not None:
                    break
            if row is None:
                raise ApiError(f"等待淘宝联盟推广费导出超时：{timeout_seconds} 秒")
        else:
            log(UNION_REPORT, "导出", "复用历史页中已完成的同日期报表")

        file_request = collector.latest(path=UNION_FILE_PATH, host=UNION_HOST, method="GET")
        file_url = await _union_file_url(
            session,
            file_request.url if file_request else f"https://{UNION_HOST}{UNION_FILE_PATH}",
            token,
            row.get("id"),
            page_url=page.url,
            user_agent=user_agent,
        )
        output = download_original_file(
            file_url,
            output_dir,
            f"TMALL_taobao_union_promotion_{target_date}.csv",
            headers={"Referer": page.url, "User-Agent": user_agent},
            session=session,
        )
        log(UNION_REPORT, "完成", f"已保存原始 CSV：{output}")
        return output
    finally:
        session.close()
        collector.detach()


def _wanxiang_params(template_url: str, target_date: str) -> dict[str, str]:
    values = dict(parse_qsl(urlsplit(template_url).query, keep_blank_values=True))
    values.update(
        {
            "beginTime": target_date,
            "endTime": target_date,
            "offset": "0",
            "limit": "20",
            "timeType": "acount",
            "tradeType": "DEDUCT",
        }
    )
    return values


def _wanxiang_target_url(target_date: str) -> str:
    target = parse_date(target_date, option_name="万相台目标日期")
    query = urlencode(
        {
            "spm": "",
            "costStartTime": target.replace(day=1).isoformat(),
            "costEndTime": target.isoformat(),
            "detailTab": "cash",
            "time": "acount",
            "currentPage": "1",
            "trade": "DEDUCT",
            "cashStart": target.isoformat(),
            "cashEnd": target.isoformat(),
        }
    )
    return f"https://one.alimama.com/index.html#!/account/detail?{query}"


async def download_wanxiangtai(
    browser: Any,
    target_date: str,
    output_dir: Path,
) -> Path | None:
    context = browser.contexts[0]
    collector = NaturalRequestCollector()
    collector.attach(context)
    page = await page_for(browser, lambda url: "alimama.com" in url)
    observed_after = time.monotonic()
    await handle_alimama_login(page, _wanxiang_target_url(target_date))
    await ensure_no_security_challenge(page)
    list_request = await collector.wait_for_path(
        WANXIANG_LIST_PATH,
        host=WANXIANG_HOST,
        method="GET",
        observed_after=observed_after,
        timeout=40,
    )
    cookies = await get_browser_cookies(context)
    session = make_requests_session(cookies)
    user_agent = await browser_user_agent(page)
    try:
        params = _wanxiang_params(list_request.url, target_date)
        response = await session_request(
            session,
            "GET",
            list_request.url.split("?", 1)[0],
            label="万相台推广费查询",
            page_url=page.url,
            user_agent=user_agent,
            params=params,
        )
        body = response_json(response, label="万相台推广费查询")
        ensure_api_success(body, label="万相台推广费查询")
        data = body.get("data", {})
        total = int(data.get("total", 0) or 0) if isinstance(data, dict) else 0
        log(WANXIANG_REPORT, "查询", f"WebAPI 查询完成，现金支出={total}条，日期={target_date}")
        if total == 0:
            log(WANXIANG_REPORT, "完成", "查询结果为 0 条，不创建导出任务")
            return None

        export_request = collector.latest(path=WANXIANG_EXPORT_PATH, host=WANXIANG_HOST, method="POST")
        export_url = export_request.url if export_request else f"https://{WANXIANG_HOST}{WANXIANG_EXPORT_PATH}"
        export_response = await session_request(
            session,
            "POST",
            export_url,
            label="万相台推广费创建导出",
            page_url=page.url,
            user_agent=user_agent,
            data={
                "csrfId": params.get("csrfId", ""),
                "bizCode": params.get("bizCode", "universalBP"),
                "beginTime": target_date,
                "endTime": target_date,
                "timeType": "acount",
                "tradeType": "DEDUCT",
                "loginPointId": params.get("loginPointId", ""),
            },
        )
        export_body = response_json(export_response, label="万相台推广费创建导出")
        ensure_api_success(export_body, label="万相台推广费创建导出")
        link = export_body.get("data", {}).get("downloadLink")
        file_url = extract_first_url(f"https:{link}" if isinstance(link, str) and link.startswith("//") else link)
        output = download_original_file(
            file_url,
            output_dir,
            f"TMALL_wanxiangtai_promotion_{target_date}.csv",
            headers={"Referer": page.url, "User-Agent": user_agent},
            session=session,
        )
        log(WANXIANG_REPORT, "完成", f"已保存原始 CSV：{output}")
        return output
    finally:
        session.close()
        collector.detach()


async def run_with_endpoint(
    endpoint: str,
    *,
    kind: str,
    target_date: str,
    output_dir: Path,
    timeout_seconds: int = 300,
    poll_interval: float = 3.0,
) -> Path | None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise ApiError("天猫 Profile 没有可用浏览器上下文")
        if kind == "淘宝联盟推广费":
            return await download_union(
                browser,
                target_date,
                output_dir,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
        if kind == "万相台推广费":
            return await download_wanxiangtai(browser, target_date, output_dir)
        raise ValueError(f"不支持的推广费报表：{kind}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="天猫推广费 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint")
    endpoint.add_argument("--debug-port", type=int)
    parser.add_argument("--profile", default=FINANCE_PROFILE)
    parser.add_argument("--mcp-url", default=None)
    parser.add_argument("--kind", choices=("淘宝联盟推广费", "万相台推广费"), default="淘宝联盟推广费")
    parser.add_argument("--date", help="目标日 YYYY-MM-DD，默认昨天")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--profile-timeout", type=float, default=30.0)
    parser.add_argument("--profile-poll-interval", type=float, default=0.5)
    return parser.parse_args(argv)


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., Any] = resolve_profile_connection,
) -> Path | None:
    target, _ = parse_date_range(args.date, default="yesterday")
    connection = resolver(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
        timeout=args.profile_timeout,
        poll_interval=args.profile_poll_interval,
    )
    return await run_with_endpoint(
        connection.endpoint,
        kind=args.kind,
        target_date=target,
        output_dir=Path(args.output_dir),
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        output = asyncio.run(run_async(parse_args(argv)))
        if output is not None:
            print(f"output={output}")
        return 0
    except (NeedsHumanError, ProfileResolutionError) as exc:
        print(f"NEEDS_HUMAN: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
    except (ApiError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
