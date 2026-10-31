#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天猫订单标准报表 WebAPI 下载。

订单列表查询使用千牛自然请求的完整表单，只在内存中替换日期；订单导出
任务通过历史页使用的接口轮询，成功后根据接口返回的加密文件路径请求
原始 XLSX。页面自动化只用于登录、订单入口和取得动态请求上下文。
"""

from __future__ import annotations

import argparse
import asyncio
import zipfile
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from playwright.async_api import async_playwright

try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
    from .tmall_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        EXPORT_LIST_URL,
        MTOP_HOST,
        NeedsHumanError,
        NaturalRequestCollector,
        ORDER_URL,
        build_mtop_url,
        browser_user_agent,
        download_browser_action,
        ensure_api_success,
        ensure_no_security_challenge,
        ensure_tmall_login,
        form_dict,
        get_browser_cookies,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        parse_json_or_jsonp,
        response_json,
        session_request,
    )
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection
    from tmall_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        EXPORT_LIST_URL,
        MTOP_HOST,
        NeedsHumanError,
        NaturalRequestCollector,
        ORDER_URL,
        build_mtop_url,
        browser_user_agent,
        download_browser_action,
        ensure_api_success,
        ensure_no_security_challenge,
        ensure_tmall_login,
        form_dict,
        get_browser_cookies,
        log,
        make_requests_session,
        page_for,
        parse_date,
        parse_date_range,
        parse_json_or_jsonp,
        response_json,
        session_request,
    )


REGULAR_PROFILE = "TMALL-天猫-MOCK旗舰店"
ORDER_QUERY_PATH = "/trade/itemlist/asyncSold.htm"
ORDER_CREATE_PATH = "/trade/itemlist/list_export_order.htm"
ORDER_EXPORT_PATH = "/trade/itemlist/export_by_tfs.do"
ORDER_SOLD_EXPORT_API = "mtop.com.taobao.order.sold.export"
ORDER_SOLD_EXPORT_PATH = f"/h5/{ORDER_SOLD_EXPORT_API}/1.0/"
ORDER_EXPORT_LIST_API = "mtop.taobao.trade.order.exportlist"
ORDER_EXPORT_LIST_PATH = f"/h5/{ORDER_EXPORT_LIST_API}/1.0/"
TZ_CN = timezone(timedelta(hours=8))
REPORT = "订单"
REQUIRED_FIELD_IDS = "1,2,3,5,7,10,11,17,13,14,15,16,18"


def _timestamp_ms(value: str, *, end_of_day: bool) -> str:
    parsed = parse_date(value, option_name="订单日期")
    moment = datetime.combine(
        parsed,
        dt_time(23, 59, 59) if end_of_day else dt_time(0, 0, 0),
        tzinfo=TZ_CN,
    )
    return str(int(moment.timestamp() * 1000))


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
    url = build_mtop_url(
        template_url,
        data,
        cookies,
        callback=f"mtopjsonp{int(time.time() * 1000) % 100000}",
    )
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


def _fallback_query_form(start_date: str, end_date: str) -> dict[str, str]:
    """自然请求暂未出现时的最小稳定表单；正常运行优先使用自然表单。"""

    return {
        "isQnNew": "true",
        "isHideNick": "true",
        "prePageNo": "1",
        "sifg": "0",
        "action": "itemlist/SoldQueryAction",
        "close": "0",
        "pageNum": "1",
        "tabCode": "latest3Months",
        "useCheckcode": "false",
        "errorCheckcode": "false",
        "payDateBegin": "0",
        "payDateEnd": "0",
        "rateStatus": "ALL",
        "orderStatus": "ALL",
        "pageSize": "15",
        "dateBegin": _timestamp_ms(start_date, end_of_day=False),
        "dateEnd": _timestamp_ms(end_date, end_of_day=True),
        "queryMore": "true",
        "refund": "ALL",
        "queryOrder": "desc",
        "deliveryTimeType": "ALL",
        "payMethodType": "ALL",
        "orderType": "ALL",
        "notifySendGoodsType": "ALL",
        "o2oDeliveryType": "ALL",
        "logisticsService": "ALL",
        "auctionType": "0",
        "holdStatus": "0",
        "tradeTag": "0",
        "unionSearchPageNum": "0",
        "unionSearchTotalNum": "0",
    }


def _with_order_dates(form: dict[str, str], start_date: str, end_date: str) -> dict[str, str]:
    result = dict(form)
    result["dateBegin"] = _timestamp_ms(start_date, end_of_day=False)
    result["dateEnd"] = _timestamp_ms(end_date, end_of_day=True)
    result.setdefault("pageNum", "1")
    result.setdefault("pageSize", "15")
    return result


def order_count(body: Any) -> int:
    if not isinstance(body, dict):
        raise ApiError("订单查询响应结构异常")
    if body.get("error"):
        message = str(body.get("error"))
        if any(x in message for x in ("登录", "验证", "权限")):
            raise NeedsHumanError(message[:160])
        raise ApiError(f"订单查询失败：{message[:160]}")
    page = body.get("page")
    if isinstance(page, dict):
        try:
            count = int(page.get("totalNumber", 0))
        except (TypeError, ValueError) as exc:
            raise ApiError("订单查询 totalNumber 不是整数") from exc
        if count < 0:
            raise ApiError("订单查询 totalNumber 为负数")
        return count
    orders = body.get("mainOrders")
    return len(orders) if isinstance(orders, list) else 0


def _record_range(record: dict[str, Any]) -> tuple[str | None, str | None]:
    return record.get("startTimeStr"), record.get("endTimeStr")


def matching_export_record(
    body: Any,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    data = body.get("data", {}) if isinstance(body, dict) else {}
    records = data.get("detailList", []) if isinstance(data, dict) else []
    expected_start = f"{start_date} 00:00:00"
    expected_end = f"{end_date} 23:59:59"
    for record in records:
        if not isinstance(record, dict):
            continue
        start, end = _record_range(record)
        if start != expected_start or end != expected_end:
            continue
        path = str(record.get("orderEncrypterStr") or "")
        export_type = str(record.get("exportType") or "").lower()
        if export_type:
            # exportType=1 是订单报表；任务处理中可能尚未返回
            # orderEncrypterStr，不能因为文件路径为空而再次创建任务。
            if export_type not in {"1", "order", "orderreport"}:
                continue
        elif not ("/orders" in path or path.endswith("orders")):
            continue
        return record
    return None


def ready_export_record(
    body: Any,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    record = matching_export_record(body, start_date, end_date)
    if record is None:
        return None
    status = str(record.get("exportStatus") or "").lower()
    return record if status in {"exportsuccess", "success", "done", "complete"} else None


def export_download_url(record: dict[str, Any]) -> str:
    encrypted_path = str(record.get("orderEncrypterStr") or "")
    export_id = str(record.get("exportId") or "")
    if not encrypted_path or not export_id:
        raise ApiError("订单导出成功记录缺少文件路径或 exportId")
    params = {
        "f_p": encrypted_path,
        "apply_time": str(record.get("applyTime") or ""),
        "start_time": str(record.get("startTimeStr") or ""),
        "end_time": str(record.get("endTimeStr") or ""),
        "order_status": str(record.get("orderStatus") or "全部"),
        "export_id": export_id,
    }
    return f"https://trade.taobao.com{ORDER_EXPORT_PATH}?{urlencode(params)}"


def history_row_matches(
    text: str,
    start_date: str,
    end_date: str,
    apply_time: str,
) -> bool:
    """判断历史页 DOM 行是否就是 API 返回的本次订单导出记录。"""

    normalized = " ".join(str(text or "").split())
    return all(
        marker in normalized
        for marker in (
            f"报表申请时间：{apply_time}",
            "报表类型：订单报表",
            f"创建时间：{start_date} 00:00:00 到 {end_date} 23:59:59",
            "下载订单报表",
        )
    )


async def _find_history_download_button(
    page: Any,
    *,
    start_date: str,
    end_date: str,
    apply_time: str,
    timeout_seconds: int,
    poll_interval: float,
) -> Any:
    """在导出历史页按 API 记录精确找到真实下载按钮。"""

    deadline = time.monotonic() + timeout_seconds
    last_reload = 0.0
    while time.monotonic() < deadline:
        rows = page.locator('div[class*="order-export_order-block"]')
        for index in range(await rows.count()):
            row = rows.nth(index)
            try:
                text = await row.inner_text(timeout=2_000)
                if not history_row_matches(text, start_date, end_date, apply_time):
                    continue
                button = row.get_by_role("button", name="下载订单报表", exact=True).last
                if await button.count() and await button.is_visible():
                    return button
            except Exception:
                continue

        now = time.monotonic()
        if now - last_reload >= 30:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                if "timeout" not in str(exc).lower() and "abort" not in str(exc).lower():
                    raise
            last_reload = now
        await asyncio.sleep(max(0.2, poll_interval))
    raise ApiError("订单导出历史页未找到本次任务的下载按钮")


async def _download_history_record(
    page: Any,
    record: dict[str, Any],
    output_dir: Path,
    *,
    start_date: str,
    end_date: str,
    timeout_seconds: int,
    poll_interval: float,
) -> Path:
    """点击天猫历史页真实按钮，不能用直接导航替代。"""

    apply_time = str(record.get("applyTime") or "")
    if not apply_time:
        raise ApiError("订单导出成功记录缺少申请时间")
    button = await _find_history_download_button(
        page,
        start_date=start_date,
        end_date=end_date,
        apply_time=apply_time,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
    )
    log(REPORT, "下载", f"点击历史页对应订单报表，申请时间={apply_time}")
    return await download_browser_action(
        page,
        button.click,
        output_dir,
        f"TMALL_order_{start_date}_to_{end_date}.xlsx",
        timeout_ms=max(30_000, min(120_000, timeout_seconds * 1000)),
    )


def _record_submitted_after(record: dict[str, Any], submitted_at: datetime) -> bool:
    value = str(record.get("applyTime") or "")
    try:
        observed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return observed >= submitted_at.replace(tzinfo=None) - timedelta(minutes=2)


async def _create_and_wait_order_export(
    *,
    session: Any,
    cookies: list[dict[str, Any]],
    collector: NaturalRequestCollector,
    page: Any,
    list_template: str,
    query_form: dict[str, str],
    start_date: str,
    end_date: str,
    timeout_seconds: int,
    poll_interval: float,
    user_agent: str,
) -> dict[str, Any]:
    submitted_at = datetime.now(TZ_CN)
    prepare_template = collector.latest(
        path=ORDER_SOLD_EXPORT_PATH,
        host=MTOP_HOST,
        method="GET",
    )
    await _mtop_get(
        session,
        cookies,
        prepare_template.url if prepare_template else _mtop_fallback(ORDER_SOLD_EXPORT_API, ORDER_SOLD_EXPORT_PATH),
        {"type": "online", "operate": "prepare"},
        page_url=page.url,
        user_agent=user_agent,
        label="订单导出字段准备",
    )
    create_form = _with_order_dates(dict(query_form), start_date, end_date)
    create_form.update(
        {
            "action": "itemlist/ExportOrderAction",
            "exportType": "2",
            "fileType": "xlsx",
            "selectFieldIds": REQUIRED_FIELD_IDS,
            "newExportPlatform": "true",
            "event_submit_do_apply_export": "1",
        }
    )
    create_response = await session_request(
        session,
        "POST",
        f"https://trade.taobao.com{ORDER_CREATE_PATH}?_input_charset=utf8",
        label="订单创建导出任务",
        page_url=page.url,
        user_agent=user_agent,
        data=create_form,
    )
    if create_response.status_code in {401, 403}:
        raise NeedsHumanError("订单导出创建接口返回登录或权限状态")
    if create_response.status_code < 200 or create_response.status_code >= 300:
        raise ApiError(f"订单创建导出任务 HTTP {create_response.status_code}")
    text = create_response.text
    if any(x in text for x in ("请先登录", "验证码", "安全验证", "权限不足")):
        raise NeedsHumanError("订单导出创建接口要求人工处理")
    log(REPORT, "导出", "已提交订单导出任务，开始轮询历史记录")

    record: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(max(0.1, poll_interval))
        list_body = await _mtop_get(
            session,
            cookies,
            list_template,
            {"page": 1},
            page_url=page.url,
            user_agent=user_agent,
            label="订单导出历史",
        )
        record = ready_export_record(list_body, start_date, end_date)
        if record is not None and not _record_submitted_after(record, submitted_at):
            record = None
        if record is not None:
            break
    if record is None:
        raise ApiError(f"等待订单导出任务完成超时：{timeout_seconds} 秒")
    return record


async def download_orders(
    browser: Any,
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    timeout_seconds: int = 900,
    poll_interval: float = 3.0,
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> Path | None:
    context = browser.contexts[0]
    collector = NaturalRequestCollector()
    collector.attach(context)
    page = await page_for(browser, lambda url: "myseller.taobao.com" in url or "trade.taobao.com" in url)
    await ensure_tmall_login(page, username=username, password_env=password_env)
    query_after = time.monotonic()
    await page.goto(ORDER_URL, wait_until="domcontentloaded")
    await ensure_no_security_challenge(page)
    try:
        try:
            query_request = await collector.wait_for_path(
                ORDER_QUERY_PATH,
                host="trade.taobao.com",
                method="POST",
                observed_after=query_after,
                timeout=25,
            )
            natural_form = form_dict(query_request.post_data)
        except ApiError:
            natural_form = _fallback_query_form(start_date, end_date)

        query_form = _with_order_dates(natural_form, start_date, end_date)
        cookies = await get_browser_cookies(context)
        session = make_requests_session(cookies)
        user_agent = await browser_user_agent(page)
        try:
            query_response = await session_request(
                session,
                "POST",
                f"https://trade.taobao.com{ORDER_QUERY_PATH}?event_submit_do_query=1&_input_charset=utf8",
                label="订单查询",
                page_url=page.url,
                user_agent=user_agent,
                data=query_form,
            )
            query_body = response_json(query_response, label="订单查询")
            count = order_count(query_body)
            log(REPORT, "查询", f"WebAPI 查询完成，订单数={count}，日期={start_date}..{end_date}")
            if count == 0:
                log(REPORT, "完成", "查询结果为 0 条，不创建订单导出任务")
                return None

            list_after = time.monotonic()
            await page.goto(EXPORT_LIST_URL, wait_until="domcontentloaded")
            try:
                list_request = await collector.wait_for_path(
                    ORDER_EXPORT_LIST_PATH,
                    host=MTOP_HOST,
                    method="GET",
                    observed_after=list_after,
                    timeout=35,
                )
                list_template = list_request.url
            except ApiError:
                list_template = _mtop_fallback(ORDER_EXPORT_LIST_API, ORDER_EXPORT_LIST_PATH)

            list_body = await _mtop_get(
                session,
                cookies,
                list_template,
                {"page": 1},
                page_url=page.url,
                user_agent=user_agent,
                label="订单导出历史",
            )
            record = ready_export_record(list_body, start_date, end_date)
            if record is None:
                pending = matching_export_record(list_body, start_date, end_date)
                if pending is not None:
                    log(REPORT, "导出", "发现同日期进行中的导出任务，继续轮询，不重复创建")
                    deadline = time.monotonic() + timeout_seconds
                    while time.monotonic() < deadline:
                        await asyncio.sleep(max(0.1, poll_interval))
                        list_body = await _mtop_get(
                            session,
                            cookies,
                            list_template,
                            {"page": 1},
                            page_url=page.url,
                            user_agent=user_agent,
                            label="订单导出历史",
                        )
                        record = ready_export_record(list_body, start_date, end_date)
                        if record is not None:
                            break
                    if record is None:
                        raise ApiError(f"等待订单导出任务完成超时：{timeout_seconds} 秒")
                else:
                    record = await _create_and_wait_order_export(
                        session=session,
                        cookies=cookies,
                        collector=collector,
                        page=page,
                        list_template=list_template,
                        query_form=query_form,
                        start_date=start_date,
                        end_date=end_date,
                        timeout_seconds=timeout_seconds,
                        poll_interval=poll_interval,
                        user_agent=user_agent,
                    )
            else:
                log(REPORT, "导出", "复用历史页中已完成的同日期订单报表")

            output = await _download_history_record(
                page,
                record,
                output_dir,
                start_date=start_date,
                end_date=end_date,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
            if not zipfile.is_zipfile(output):
                output.unlink(missing_ok=True)
                raise ApiError("订单下载结果不是有效 XLSX")
            log(REPORT, "完成", f"已保存原始 XLSX：{output}")
            return output
        finally:
            session.close()
    finally:
        collector.detach()


async def run_with_endpoint(
    endpoint: str,
    *,
    start_date: str,
    end_date: str,
    output_dir: Path,
    timeout_seconds: int = 900,
    poll_interval: float = 3.0,
    username: str = "MOCK旗舰店",
    password_env: str = "TMALL_LOGIN_PASSWORD",
) -> Path | None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise ApiError("天猫 Profile 没有可用浏览器上下文")
        return await download_orders(
            browser,
            start_date,
            end_date,
            output_dir,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            username=username,
            password_env=password_env,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="天猫订单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint")
    endpoint.add_argument("--debug-port", type=int)
    parser.add_argument("--profile", default=REGULAR_PROFILE)
    parser.add_argument("--mcp-url", default=None)
    parser.add_argument("--date", help="日期 YYYY-MM-DD 或范围 YYYY-MM-DD~YYYY-MM-DD")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=3.0)
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
    start, end = parse_date_range(
        args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        default="month",
    )
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
        start_date=start,
        end_date=end,
        output_dir=Path(args.output_dir),
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
        username=args.username,
        password_env=args.password_env,
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
