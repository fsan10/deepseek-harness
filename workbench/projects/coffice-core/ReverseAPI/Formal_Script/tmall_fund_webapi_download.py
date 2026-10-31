#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天猫聚合账户资金与支付宝账户资金 WebAPI 下载。

页面只负责登录、入口和取得当前 Target 的自然业务上下文；查询、目标日
判断、短效地址获取和文件落盘均通过 WebAPI 完成。默认下载昨天，输出为
天猫后台返回的原始 XLSX/ZIP，不在本模块改写财务明细。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import zipfile
from contextlib import suppress
from datetime import date, datetime, time as day_time, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright

from scripts.auto_download.playwright.tmall_alipay_fund_download import (
    ensure_list_mode as _ensure_alipay_list_mode,
    open_account_info as _open_account_info,
    open_alipay_page as _open_alipay_page,
    open_bill_download as _open_bill_download,
    select_bill_mode as _select_alipay_mode,
)

try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
    from .tmall_webapi_common import (
        AGGREGATE_FUND_URL,
        ALIPAY_FUND_URL,
        ApiError,
        DEFAULT_OUTPUT_DIR,
        EXPORT_LIST_URL,
        MTOP_HOST,
        TZ_CN,
        NeedsHumanError,
        NaturalRequestCollector,
        build_mtop_url,
        browser_user_agent,
        download_browser_file,
        download_original_file,
        ensure_api_success,
        ensure_no_security_challenge,
        ensure_tmall_login,
        extract_first_url,
        form_dict,
        get_browser_cookies,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        parse_json_or_jsonp,
        replace_query,
        response_json,
        session_request,
    )
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection
    from tmall_webapi_common import (  # type: ignore[no-redef]
        AGGREGATE_FUND_URL,
        ALIPAY_FUND_URL,
        ApiError,
        DEFAULT_OUTPUT_DIR,
        EXPORT_LIST_URL,
        MTOP_HOST,
        TZ_CN,
        NeedsHumanError,
        NaturalRequestCollector,
        build_mtop_url,
        browser_user_agent,
        download_browser_file,
        download_original_file,
        ensure_api_success,
        ensure_no_security_challenge,
        ensure_tmall_login,
        extract_first_url,
        form_dict,
        get_browser_cookies,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        parse_json_or_jsonp,
        replace_query,
        response_json,
        session_request,
    )


REGULAR_PROFILE = "TMALL-天猫-MOCK旗舰店"
FINANCE_PROFILE = "TMALL-天猫-MOCK旗舰店-财务账号"
ALIPAY_STAT_PATH = "/enterprise/fundDailyStat.json"
ALIPAY_DAILY_PATH = "/enterprise/dailyBillQuery.resource"
ALIPAY_SECURITY_PATH = "/enterprise/entAsyncSecurityCheck.json"
ALIPAY_SECURITY_BIZ_TYPE = "SECURITY_PRODUCT_BILL_DOWNLOAD"
AGG_QUERY_API = "mtop.taobao.finance.fund.bill.query"
AGG_FILE_API = "mtop.taobao.finance.fund.bill.detail.file.get"
AGG_QUERY_PATH = f"/h5/{AGG_QUERY_API}/1.0/"
AGG_FILE_PATH = f"/h5/{AGG_FILE_API}/1.0/"
ALIPAY_REPORT = "支付宝账户资金"
AGG_REPORT = "聚合账户资金"


def _alipay_success(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ApiError("支付宝资金查询响应结构异常")
    if str(body.get("success", "")).lower() != "true" or body.get("status") != "succeed":
        message = body.get("message") or body.get("outputMsg") or "未知错误"
        if any(x in str(message) for x in ("登录", "验证", "权限")):
            raise NeedsHumanError(f"支付宝资金接口返回人工处理状态：{str(message)[:120]}")
        raise ApiError(f"支付宝资金查询失败：{str(message)[:160]}")
    return body


def _mtop_fallback(api: str, path: str) -> str:
    return (
        f"https://{MTOP_HOST}{path}?jsv=2.6.1&appKey=12574478&api={api}"
        "&v=1.0&ttid=11320%40taobao_WEB_9.9.99&dataType=originaljsonp"
        "&type=originaljsonp&callback=mtopjsonp1&data=%7B%7D"
    )


async def _mtop_get(
    session: Any,
    cookies: list[dict[str, Any]],
    template_url: str,
    data: dict[str, Any],
    *,
    page_url: str,
    user_agent: str,
    label: str,
) -> dict[str, Any]:
    callback = f"mtopjsonp{int(time.time() * 1000) % 100000}"
    url = build_mtop_url(template_url, data, cookies, callback=callback)
    response = await session_request(
        session,
        "GET",
        url,
        label=label,
        page_url=page_url,
        user_agent=user_agent,
    )
    body = response_json(response, label=label)
    if isinstance(body, str):
        body = parse_json_or_jsonp(body)
    ensure_api_success(body, label=label)
    return body


def alipay_day_times(target_date: str) -> tuple[str, str]:
    """页面以 GMT 字符串传输中国自然日的闭区间。"""
    target = parse_date(target_date, option_name="支付宝目标日期")
    start = datetime.combine(target, day_time.min, tzinfo=TZ_CN)
    end = start + timedelta(days=1, seconds=-1)
    return tuple(format_datetime(value.astimezone(timezone.utc), usegmt=True) for value in (start, end))


def alipay_query_form(template: dict[str, str], target_date: str) -> dict[str, str]:
    parse_date(target_date, option_name="支付宝目标日期")
    if not template.get("billUserId"):
        raise ApiError("支付宝资金自然请求缺少 billUserId")
    result = dict(template)
    result.update(startDate=target_date, endDate=target_date, pageNum="1")
    return result


def alipay_security_request(template_url: str, target_date: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(template_url)
    csrf = dict(parse_qsl(parsed.query)).get("ctoken")
    if parsed.scheme != "https" or parsed.hostname != "mbillexprod.alipay.com" or not csrf:
        raise ApiError("支付宝当前 Target 缺少安全校验请求上下文")
    start, end = alipay_day_times(target_date)
    url = urlunsplit((parsed.scheme, parsed.netloc, ALIPAY_SECURITY_PATH,
                      urlencode({"ctoken": csrf, "_output_charset": "utf-8"}), ""))
    return url, {"securityBizType": ALIPAY_SECURITY_BIZ_TYPE, "beginDate": start,
                 "endDate": end, "_input_charset": "gbk"}


def alipay_security_id(body: Any) -> str:
    if not isinstance(body, dict):
        raise ApiError("支付宝安全校验响应结构异常")
    if body.get("securityStatus") != "succeed":
        raise NeedsHumanError("支付宝安全校验未通过，请在当前 Profile 完成人工验证")
    value = body.get("securityId")
    if not isinstance(value, str) or not value:
        raise ApiError("支付宝安全校验成功但未返回下载上下文")
    return value


def alipay_download_url(template_url: str, form: dict[str, str], target_date: str,
                        security_id: str, *, timestamp_ms: int | None = None) -> str:
    parsed = urlsplit(template_url)
    if parsed.scheme != "https" or parsed.hostname != "mbillexprod.alipay.com":
        raise ApiError("支付宝下载请求来源异常")
    if not form.get("billUserId") or not security_id:
        raise ApiError("支付宝下载请求缺少账户或安全上下文")
    start, end = alipay_day_times(target_date)
    query = {"_t": str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)),
             "billTypeList": "signcustomer", "billUserId": form["billUserId"],
             "bizDate": target_date, "endTime": end, "forceAync": "0",
             "querySettleAccount": form.get("querySettleAccount", "false"),
             "securityBizType": ALIPAY_SECURITY_BIZ_TYPE, "securityId": security_id,
             "startTime": start}
    return urlunsplit((parsed.scheme, parsed.netloc, ALIPAY_DAILY_PATH, urlencode(query), ""))


def _alipay_true(value: Any) -> bool:
    return str(value).lower() in {"true", "1"}


def alipay_target_row(body: Any, target_date: str) -> dict[str, Any] | None:
    result = _alipay_success(body).get("result")
    rows = result.get("dateDtls") if isinstance(result, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ApiError("支付宝资金查询缺少账期列表")
    matches = [row for row in rows if row.get("bizDate") == target_date]
    if len(matches) > 1:
        raise ApiError("支付宝资金查询返回重复目标账期")
    if not matches or any(_alipay_true(matches[0].get(key)) for key in ("noData", "emptyData")):
        return None
    row = matches[0]
    if not _alipay_true(row.get("downloadable")) or _alipay_true(row.get("processing")):
        raise ApiError(f"支付宝目标日尚未生成可下载账单：{target_date}")
    return row


async def _alipay_page_post(page: Any, url: str, fields: dict[str, str], *, label: str) -> Any:
    """由当前页面携带 Cookie/Origin 等浏览器上下文发送已捕获的 API。"""
    try:
        response = await page.evaluate("""async ({url, fields}) => {
            const response = await fetch(url, {method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
                body: new URLSearchParams(fields).toString()});
            return {status: response.status, text: await response.text()};
        }""", {"url": url, "fields": fields})
    except Exception as exc:
        raise ApiError(f"{label}浏览器请求失败：{type(exc).__name__}", path=urlsplit(url).path) from exc
    if not isinstance(response, dict) or not isinstance(response.get("status"), int):
        raise ApiError(f"{label}浏览器响应结构异常", path=urlsplit(url).path)
    status = response["status"]
    if status < 200 or status >= 300:
        raise ApiError(f"{label} HTTP {status}", status=status, path=urlsplit(url).path)
    try:
        return json.loads(response.get("text"))
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{label}未返回 JSON", status=status, path=urlsplit(url).path) from exc


async def _open_alipay_bill_page(browser: Any, username: str, password_env: str) -> Any:
    for context in reversed(browser.contexts):
        for page in reversed(context.pages):
            parsed = urlsplit(page.url)
            if (not page.is_closed() and parsed.hostname == "b.alipay.com"
                    and parsed.path == urlsplit(ALIPAY_FUND_URL).path):
                await ensure_no_security_challenge(page)
                return page
    page = await page_for(browser, lambda url: "myseller.taobao.com" in url)
    await ensure_tmall_login(page, username=username, password_env=password_env)
    await _open_account_info(page, username)
    alipay_page, _ = await _open_alipay_page(page)
    await _open_bill_download(alipay_page)
    return alipay_page


async def _alipay_natural_context(page: Any) -> Any:
    collector = NaturalRequestCollector()
    collector.attach(page)  # Page 而非 BrowserContext：动态值只属于当前 Target。
    observed_after = time.monotonic()
    try:
        await page.reload(wait_until="domcontentloaded")
        await ensure_no_security_challenge(page)
        await _ensure_alipay_list_mode(page)
        await _select_alipay_mode(page, "day")
        return await collector.wait_for_path(ALIPAY_STAT_PATH, host="mbillexprod.alipay.com",
                                             method="POST", observed_after=observed_after, timeout=30)
    finally:
        collector.detach()


async def download_alipay(
    browser: Any,
    target_date: str,
    output_dir: Path,
    *,
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> Path | None:
    report = ALIPAY_REPORT
    parse_date(target_date, option_name="支付宝目标日期")
    existing_pages = {page for context in browser.contexts for page in context.pages}
    preserve_pages = False
    try:
        page = await _open_alipay_bill_page(browser, username, password_env)
        for attempt in range(2):
            natural = await _alipay_natural_context(page)
            form = alipay_query_form(form_dict(natural.post_data), target_date)
            try:
                body = await _alipay_page_post(page, natural.url, form, label="支付宝资金查询")
                if alipay_target_row(body, target_date) is None:
                    log(report, "查询", f"{target_date} 无可下载数据")
                    return None
                log(report, "查询", f"已确认目标日可下载：{target_date}")
                security_url, security_form = alipay_security_request(natural.url, target_date)
                security_body = await _alipay_page_post(page, security_url, security_form,
                                                        label="支付宝下载安全校验")
                ticket = alipay_security_id(security_body)
                break
            except ApiError as exc:
                if exc.status not in {401, 403}:
                    raise
                if attempt:
                    raise NeedsHumanError("支付宝接口刷新当前页面会话后仍无权限") from exc
                log(report, "上下文", "当前接口会话失效，刷新同一 Target 后重试一次")
        daily_url = alipay_download_url(natural.url, form, target_date, ticket)
        log(report, "下载", "使用本次安全校验上下文请求原始账单")
        # dailyBillQuery 会消耗本次 securityId，并直接 302 到 ZIP；不能先请求
        # 一次再重放、也不能重新消费短效下载链接。
        try:
            output = await download_browser_file(
                page, daily_url, output_dir, f"TMALL_alipay_fund_{target_date}.zip",
            )
        except (ApiError, NeedsHumanError):
            raise
        except Exception as exc:
            # Playwright 错误可能包含带安全上下文的导航 URL，不能直接回显。
            raise ApiError(f"支付宝账单下载失败：{type(exc).__name__}") from exc
        if not zipfile.is_zipfile(output):
            output.unlink(missing_ok=True)
            raise ApiError("支付宝资金下载结果不是有效 ZIP")
        log(report, "完成", f"已保存原始 ZIP：{output}")
        return output
    except NeedsHumanError:
        preserve_pages = True
        raise
    finally:
        if not preserve_pages:
            for context in browser.contexts:
                for owned_page in list(context.pages):
                    if owned_page not in existing_pages:
                        with suppress(Exception):
                            await owned_page.close()


async def download_aggregate(
    browser: Any,
    target_date: str,
    output_dir: Path,
    *,
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> Path | None:
    report = AGG_REPORT
    context = browser.contexts[0]
    collector = NaturalRequestCollector()
    collector.attach(context)
    page = await page_for(browser, lambda url: "myseller.taobao.com" in url)
    await ensure_tmall_login(page, username=username, password_env=password_env)
    observed_after = time.monotonic()
    await page.goto(AGGREGATE_FUND_URL, wait_until="domcontentloaded")
    await ensure_no_security_challenge(page)
    query_request = await collector.wait_for_path(
        AGG_QUERY_PATH,
        host=MTOP_HOST,
        method="GET",
        observed_after=observed_after,
        timeout=40,
    )
    file_request = collector.latest(path=AGG_FILE_PATH, host=MTOP_HOST, method="GET")
    target = parse_date(target_date, option_name="聚合资金目标日期")
    start = (target - timedelta(days=30)).isoformat()
    end = target.isoformat()
    cookies = await get_browser_cookies(context)
    session = make_requests_session(cookies)
    user_agent = await browser_user_agent(page)
    try:
        all_rows: list[dict[str, Any]] = []
        for page_no in range(1, 8):
            body = await _mtop_get(
                session,
                cookies,
                query_request.url,
                {
                    "pageNo": page_no,
                    "pageSize": 50,
                    "billCycleFrom": start,
                    "billCycleTo": end,
                    "billCode": "BILL_DAY_AGG",
                },
                page_url=page.url,
                user_agent=user_agent,
                label="聚合资金查询",
            )
            data = body.get("data", {})
            table = data.get("tableValues", {}) if isinstance(data, dict) else {}
            rows = table.get("data", []) if isinstance(table, dict) else []
            all_rows.extend(item for item in rows if isinstance(item, dict))
            if not table.get("hasNext") or rows:
                # 日期范围已收窄到目标日前，首个有数据的页即可覆盖目标日；
                # 若目标不在本页且有下一页，继续读取。
                if any(item.get("ds") == target.strftime("%Y%m%d") for item in all_rows):
                    break
            if not table.get("hasNext"):
                break
        target_row = next(
            (item for item in all_rows if item.get("ds") == target.strftime("%Y%m%d")),
            None,
        )
        if target_row is None:
            log(report, "查询", f"{target_date} 无聚合资金明细")
            return None
        template = file_request.url if file_request is not None else _mtop_fallback(AGG_FILE_API, AGG_FILE_PATH)
        body = await _mtop_get(
            session,
            cookies,
            template,
            {"period": target.strftime("%Y%m%d")},
            page_url=page.url,
            user_agent=user_agent,
            label="聚合资金文件地址",
        )
        file_url = extract_first_url(body.get("data", {}).get("fileUrl"))
        output = download_original_file(
            file_url,
            output_dir,
            f"TMALL_aggregate_fund_{target_date}.xlsx",
            headers={"Referer": page.url, "User-Agent": user_agent},
            session=session,
        )
        log(report, "完成", f"已保存原始 XLSX：{output}")
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
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> Path | None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise ApiError("天猫 Profile 没有可用浏览器上下文")
        if kind == "聚合账户资金":
            return await download_aggregate(
                browser,
                target_date,
                output_dir,
                username=username,
                password_env=password_env,
            )
        if kind == "支付宝账户资金":
            return await download_alipay(
                browser,
                target_date,
                output_dir,
                username=username,
                password_env=password_env,
            )
        raise ValueError(f"不支持的资金报表：{kind}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="天猫资金单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint")
    endpoint.add_argument("--debug-port", type=int)
    parser.add_argument("--profile", default=FINANCE_PROFILE)
    parser.add_argument("--mcp-url", default=None)
    parser.add_argument("--kind", choices=("支付宝账户资金", "聚合账户资金"), default="支付宝账户资金")
    parser.add_argument("--date", help="目标日 YYYY-MM-DD，默认昨天")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--username", default="MOCK旗舰店")
    parser.add_argument("--password-env", default="TMALL_LOGIN_PASSWORD")
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
        username=args.username,
        password_env=args.password_env,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        output = asyncio.run(run_async(parse_args(argv)))
        if output is None:
            return 0
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
