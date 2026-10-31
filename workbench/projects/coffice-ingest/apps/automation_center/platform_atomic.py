from __future__ import annotations

import asyncio
import re
import zipfile
from contextlib import suppress
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


PLATFORM_ATOMIC_CODES = frozenset({
    "douyin.order.open_page",
    "douyin.order.prepare_filters",
    "douyin.order.query",
    "douyin.order.create_export",
    "douyin.order.wait_ready",
    "douyin.order.download_verify",
    "douyin.order.extract",
    "douyin.bill.open",
    "douyin.bill.set_date",
    "douyin.bill.generate",
    "douyin.bill.wait_ready",
    "douyin.bill.download",
    "qianchuan.finance.open",
    "qianchuan.daily.open",
    "qianchuan.daily.wait",
    "qianchuan.daily.materialize",
    "jd.session.ensure_login",
    "jd.settlement.select_mode",
    "jd.settlement.locate",
    "jd.settlement.download",
    "jd.settlement.extract",
    "jd.fund.set_date",
    "jd.fund.create_export",
    "jd.fund.wait_download",
    "jd.fund.extract",
    "jd.promotion.open",
    "jd.promotion.set_date",
    "jd.promotion.create_export",
    "jd.promotion.wait_ready",
    "jd.promotion.download",
    "pinduoduo.order.open",
    "pinduoduo.order.set_date",
    "pinduoduo.order.query",
    "pinduoduo.order.create_export",
    "pinduoduo.order.wait_ready",
    "pinduoduo.order.download",
    "pinduoduo.settlement.open",
    "pinduoduo.settlement.set_date",
    "pinduoduo.settlement.create_export",
    "pinduoduo.settlement.wait_ready",
    "pinduoduo.settlement.download",
    "pinduoduo.settlement.extract",
    "pinduoduo.promotion.open",
    "pinduoduo.promotion.set_date",
    "pinduoduo.promotion.apply_filters",
    "pinduoduo.promotion.query",
    "pinduoduo.promotion.download",
    "kuaishou.order.open_page",
    "kuaishou.order.set_date",
    "kuaishou.order.query",
    "kuaishou.order.create_export",
    "kuaishou.order.wait_ready",
    "kuaishou.order.download_password",
    "kuaishou.order.decrypt",
    "kuaishou.fund.open",
    "kuaishou.fund.locate_bill",
    "kuaishou.fund.create_export",
    "kuaishou.fund.wait_ready",
    "kuaishou.fund.download",
    "kuaishou.fund.extract",
    "kuaishou.settlement.open",
    "kuaishou.settlement.set_date",
    "kuaishou.settlement.create_export",
    "kuaishou.settlement.wait_ready",
    "kuaishou.settlement.download",
    "kuaishou.settlement.extract",
    "tmall.order.open_page",
    "tmall.order.set_date",
    "tmall.order.search",
    "tmall.order.create_export",
    "tmall.order.wait_ready",
    "tmall.order.download",
    "tmall.aggregate_fund.open",
    "tmall.aggregate_fund.select_mode",
    "tmall.aggregate_fund.locate",
    "tmall.aggregate_fund.download",
    "tmall.session.open",
    "tmall.alipay.open_account",
    "tmall.alipay.open_page",
    "tmall.alipay.open_bill",
    "tmall.alipay.select_mode",
    "tmall.alipay.wait_ready",
    "tmall.alipay.download",
    "tmall.alipay.extract",
    "tmall.union.open",
    "tmall.union.select_period",
    "tmall.union.download",
    "tmall.wanxiangtai.open",
    "tmall.wanxiangtai.download",
})


def _context(runner: Any):
    if runner.browser is None or not runner.browser.contexts:
        raise RuntimeError("浏览器尚未连接，请先执行 browser.connect.cdp")
    return runner.browser.contexts[0]


def _profile(runner: Any) -> dict[str, Any]:
    profile = runner.runtime.get("profile")
    if not isinstance(profile, dict):
        raise RuntimeError("缺少 Cloak Profile 业务元数据")
    return profile


def _work_dir(runner: Any, key: str) -> Path:
    profile = _profile(runner)
    shop = re.sub(r'[<>:"/\\|?*]+', "_", str(profile.get("shop") or runner.profile_name))
    path = runner.destination / ".automation_cache" / key / shop
    path.mkdir(parents=True, exist_ok=True)
    return path


def _input_range(runner: Any) -> tuple[str | None, str | None]:
    start = str(runner.input_context.get("start_date") or "").strip() or None
    end = str(runner.input_context.get("end_date") or "").strip() or None
    if bool(start) != bool(end):
        raise ValueError("start_date 和 end_date 必须同时提供")
    return start, end


def _historical_bill_target(runner, mode: str) -> str | None:
    start, end = _input_range(runner)
    if not start:
        return None
    if mode == "day":
        if start != end:
            raise ValueError("日账单Flow一次获取一个业务日；多日请使用报表日历批量补跑")
        return start
    import calendar
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.day != 1 or last != first.replace(day=calendar.monthrange(first.year, first.month)[1]):
        raise ValueError("月账单Flow必须选择完整自然月")
    return start[:7]


def _set_pending(
    runner: Any,
    source: Path,
    report_name: str,
    business_date: str,
    *,
    validator: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "source_path": Path(source),
        "report_name": report_name,
        "business_date": business_date,
    }
    if validator:
        payload["validator"] = validator
    runner.runtime["pending_artifact"] = payload


async def execute_platform_atomic(runner: Any, node: dict[str, Any]) -> None:
    code = str(node["component_code"])
    config = runner._node_config(node)
    profile = _profile(runner)
    platform = str(profile.get("platform") or "")
    company = str(profile.get("company") or "")
    shop = str(profile.get("shop") or "")

    # ------------------------------------------------------------------
    # 抖音订单
    # ------------------------------------------------------------------
    if code == "douyin.order.open_page":
        from scripts.auto_download.playwright.douyin_order_download import (
            _read_state,
            _same_task,
            _state_path,
            _write_state,
            near_thirty_days,
            open_order_page,
        )

        start_date, end_date = _input_range(runner)
        custom_range = bool(start_date)
        if not custom_range:
            start_date, end_date = near_thirty_days()
        assert start_date and end_date
        work_dir = _work_dir(runner, "douyin_order")
        state_path = _state_path(work_dir)
        state = _read_state(state_path)
        if not _same_task(state, start_date, end_date) or state.get("stage") == "COMPLETED":
            state = {
                "platform": platform,
                "company": company,
                "shop": shop,
                "start_date": start_date,
                "end_date": end_date,
                "stage": "EXPORT_NOT_CREATED",
            }
            _write_state(state_path, state)
        page, created = await open_order_page(
            _context(runner), shop, platform=platform, company=company
        )
        runner.page = page
        runner.runtime.update({
            "douyin_order_created_page": created,
            "douyin_order_start": start_date,
            "douyin_order_end": end_date,
            "douyin_order_custom_range": custom_range,
            "douyin_order_work_dir": work_dir,
            "douyin_order_state_path": state_path,
            "douyin_order_state": state,
            "douyin_order_has_data": True,
        })
        return

    if code == "douyin.order.prepare_filters":
        from scripts.auto_download.playwright.douyin_order_download import prepare_order_filters
        await prepare_order_filters(runner.page)
        return

    if code == "douyin.order.query":
        from scripts.auto_download.playwright.douyin_order_download import query_orders
        total = await query_orders(
            runner.page,
            runner.runtime["douyin_order_start"],
            runner.runtime["douyin_order_end"],
            custom_range=bool(runner.runtime.get("douyin_order_custom_range")),
        )
        runner.runtime["douyin_order_has_data"] = total != 0
        runner.runtime["douyin_order_count"] = total
        return

    if code == "douyin.order.create_export":
        if not runner.runtime.get("douyin_order_has_data", True):
            return
        from scripts.auto_download.playwright.douyin_order_download import create_export_once
        await create_export_once(
            runner.page,
            runner.runtime["douyin_order_state_path"],
            runner.runtime["douyin_order_state"],
        )
        return

    if code == "douyin.order.wait_ready":
        if not runner.runtime.get("douyin_order_has_data", True):
            return
        from scripts.auto_download.playwright.douyin_order_download import (
            open_export_history,
            wait_latest_report,
        )
        runner.page = await open_export_history(runner.page)
        runner.runtime["douyin_order_download_button"] = await wait_latest_report(
            runner.page,
            runner.runtime["douyin_order_start"],
            runner.runtime["douyin_order_end"],
        )
        return

    if code == "douyin.order.download_verify":
        if not runner.runtime.get("douyin_order_has_data", True):
            return
        from scripts.auto_download.playwright.douyin_order_download import download_zip_with_challenges
        archive = await download_zip_with_challenges(
            runner.page,
            runner.runtime["douyin_order_download_button"],
            platform=platform,
            company=company,
            shop=shop,
            state_path=runner.runtime["douyin_order_state_path"],
            state=runner.runtime["douyin_order_state"],
        )
        runner.runtime["douyin_order_archive"] = archive
        return

    if code == "douyin.order.extract":
        if not runner.runtime.get("douyin_order_has_data", True):
            return
        from scripts.auto_download.playwright.douyin_order_download import (
            REPORT_NAME,
            _archive_requires_password,
            _cancel_password_listener,
            _request_stateful_answer,
            _write_state,
            extract_zip,
            select_report_file,
        )
        archive = Path(runner.runtime["douyin_order_archive"])
        state_path = runner.runtime["douyin_order_state_path"]
        state = runner.runtime["douyin_order_state"]
        extract_dir = archive.parent / "extracted"
        password = ""
        needs_password = await asyncio.to_thread(_archive_requires_password, archive)
        if not needs_password:
            await _cancel_password_listener(state_path, state)
        files: list[Path] = []
        for attempt in range(3 if needs_password else 1):
            if needs_password:
                state["stage"] = "PASSWORD_REQUIRED"
                _write_state(state_path, state)
                password = await _request_stateful_answer(
                    challenge_key="archive_password_challenge_id",
                    challenge_type="archive_password",
                    platform=platform,
                    company=company,
                    shop=shop,
                    purpose=(
                        f"订单报表 ZIP 解压（{archive.name}）"
                        if attempt == 0
                        else f"上一次解压密码错误，请重新输入。订单报表 ZIP 解压（{archive.name}）"
                    ),
                    page_url=runner.page.url,
                    state_path=state_path,
                    state=state,
                    resume_human=attempt == 0 and bool(runner.claim.get("resume_count")),
                )
            try:
                files = await asyncio.to_thread(extract_zip, archive, extract_dir, password)
                break
            except ValueError:
                if attempt >= 2:
                    raise RuntimeError("连续三次抖音订单 ZIP 解压密码错误")
        report_file = select_report_file(files)
        _set_pending(
            runner,
            report_file,
            REPORT_NAME,
            str(runner.business_date.isoformat()),
        )
        return

    # ------------------------------------------------------------------
    # 抖音资金 / 结算账单
    # ------------------------------------------------------------------
    if code == "douyin.bill.open":
        from scripts.auto_download.playwright.douyin_bill_download import BILL_URL, click_tab
        from scripts.auto_download.playwright.douyin_login import (
            find_or_create_douyin_page,
            goto_with_douyin_login,
        )
        report = str(config.get("report") or "资金")
        mode = str(config.get("mode") or "day")
        page, _ = await find_or_create_douyin_page(runner.browser)
        await goto_with_douyin_login(
            page, BILL_URL, shop, platform=platform, company=company
        )
        await page.wait_for_selector(".auxo-tabs-nav", timeout=30_000)
        report_tab = "结算账单" if report == "结算" else "资金账单"
        bill_path = (
            "/ffa/fxg-bill/settlement-detail-bill"
            if report == "结算"
            else "/ffa/fxg-bill/fund-detail-bill"
        )
        if bill_path not in page.url.split("?", 1)[0]:
            await click_tab(page, report_tab)
        await click_tab(page, "月汇总" if mode == "month" else "日汇总")
        runner.page = page
        runner.runtime.update({
            "douyin_bill_report": report,
            "douyin_bill_mode": mode,
            "douyin_bill_work_dir": _work_dir(runner, f"douyin_bill_{report}_{mode}"),
        })
        return

    if code == "douyin.bill.set_date":
        from scripts.auto_download.playwright.douyin_bill_download import set_report_date_range
        mode = runner.runtime.get("douyin_bill_mode") or "day"
        start_date, end_date = _input_range(runner)
        if mode == "day":
            start_date = start_date or runner.business_date.isoformat()
            end_date = end_date or runner.business_date.isoformat()
            await set_report_date_range(runner.page, start_date, end_date)
            runner.runtime["douyin_bill_start"] = start_date
            runner.runtime["douyin_bill_end"] = end_date
        return

    if code == "douyin.bill.generate":
        from scripts.auto_download.playwright.douyin_bill_download import (
            click_batch_download_and_generate,
            click_row_download,
            first_row_date,
            wait_first_row,
        )
        mode = runner.runtime.get("douyin_bill_mode") or "day"
        if mode == "day":
            await click_batch_download_and_generate(runner.page)
            runner.runtime["douyin_bill_business_date"] = runner.runtime.get(
                "douyin_bill_end", runner.business_date.isoformat()
            )
        else:
            await wait_first_row(runner.page)
            row = runner.page.locator(".aurora-table-row:visible").first
            date_text = await first_row_date(runner.page)
            await click_row_download(row)
            generate = runner.page.get_by_role("button", name="生成", exact=True)
            await generate.wait_for(state="visible", timeout=10_000)
            await generate.click()
            runner.runtime["douyin_bill_business_date"] = date_text
        return

    if code == "douyin.bill.wait_ready":
        from scripts.auto_download.playwright.douyin_bill_download import HISTORY_URL, wait_report_ready
        try:
            await runner.page.wait_for_url("**/ffa/fxg-bill/history-report", timeout=30_000)
        except Exception:
            if "history-report" not in runner.page.url:
                await runner.page.goto(HISTORY_URL, wait_until="domcontentloaded")
        await wait_report_ready(runner.page)
        return

    if code == "douyin.bill.download":
        card = runner.page.locator(".reportCard-GbHGPv:visible").first
        button = card.get_by_role("button", name="下载", exact=True).first
        async with runner.page.expect_download(timeout=180_000) as info:
            await button.evaluate("el => el.click()")
        download = await info.value
        work_dir = runner.runtime["douyin_bill_work_dir"]
        filename = download.suggested_filename or "douyin_bill.csv"
        source = work_dir / filename
        await download.save_as(str(source))
        if not source.is_file() or source.stat().st_size <= 0:
            raise RuntimeError(f"抖音账单下载文件为空：{source}")
        _set_pending(
            runner,
            source,
            str(runner.runtime["douyin_bill_report"]),
            str(runner.runtime["douyin_bill_business_date"]),
        )
        return

    # ------------------------------------------------------------------
    # 千川推广费
    # ------------------------------------------------------------------
    if code == "qianchuan.finance.open":
        from scripts.auto_download.playwright.qianchuan_promotion_fee_download import (
            finance_frame,
            open_qianchuan_finance_page,
        )
        page, account = await open_qianchuan_finance_page(
            runner.browser,
            "auto",
            platform=platform,
            company=company,
            shop=shop,
        )
        runner.page = page
        runner.runtime["qianchuan_frame"] = await finance_frame(
            page,
            account.aavid,
            shop,
            platform=platform,
            company=company,
        )
        return

    if code == "qianchuan.daily.open":
        from scripts.auto_download.playwright.qianchuan_promotion_fee_download import open_daily_report
        await open_daily_report(runner.runtime["qianchuan_frame"])
        return

    if code == "qianchuan.daily.wait":
        from scripts.auto_download.playwright.qianchuan_promotion_fee_download import (
            wait_latest_daily_record, set_daily_date_range, read_daily_range_records,
        )
        start, end = _input_range(runner)
        if start:
            await set_daily_date_range(runner.runtime["qianchuan_frame"], start, end)
            headers, rows = await read_daily_range_records(runner.runtime["qianchuan_frame"], start, end)
            runner.runtime["qianchuan_rows"] = rows
            if not rows:
                raise RuntimeError("REPORT_NOT_READY：千川目标区间未返回逐日日结记录")
            row = rows[0]
        else:
            headers, row = await wait_latest_daily_record(runner.runtime["qianchuan_frame"])
        runner.runtime["qianchuan_headers"] = headers
        runner.runtime["qianchuan_row"] = row
        return

    if code == "qianchuan.daily.materialize":
        from scripts.auto_download.playwright.qianchuan_promotion_fee_download import (
            REPORT_NAME,
            TEMP_FILE_NAME,
            write_csv,
        )
        work_dir = _work_dir(runner, "qianchuan_promotion")
        if runner.runtime.get("qianchuan_rows"):
            pending = []
            for row in runner.runtime["qianchuan_rows"]:
                source = work_dir / (str(row[0]).replace("/", "-") + ".csv")
                await asyncio.to_thread(write_csv, source, runner.runtime["qianchuan_headers"], row)
                pending.append({"source_path": source, "report_name": REPORT_NAME, "business_date": str(row[0])})
            runner.runtime["pending_artifacts"] = pending
            runner.runtime["pending_artifact"] = pending[0]
            return
        source = work_dir / TEMP_FILE_NAME
        await asyncio.to_thread(
            write_csv,
            source,
            runner.runtime["qianchuan_headers"],
            runner.runtime["qianchuan_row"],
        )
        business_date = str(runner.runtime["qianchuan_row"][0])
        _set_pending(runner, source, REPORT_NAME, business_date)
        return

    # ------------------------------------------------------------------
    # 京东结算 / 资金 / 推广费
    # ------------------------------------------------------------------
    if code == "jd.session.ensure_login":
        from scripts.auto_download.playwright.jd_download_common import (
            acquire_download_lock,
            new_authenticated_page,
        )
        if runner.download_lock is None:
            runner.download_lock = await asyncio.to_thread(acquire_download_lock)
        runner.page = await new_authenticated_page(runner.browser)
        return

    if code == "jd.settlement.select_mode":
        from scripts.auto_download.playwright.jd_settlement_download import select_mode
        mode = str(config.get("mode") or "day")
        runner.runtime["jd_settlement_mode"] = mode
        await select_mode(runner.page, mode)
        return

    if code == "jd.settlement.locate":
        from scripts.auto_download.playwright.jd_settlement_download import latest_row
        row, business_date = await latest_row(
            runner.page, str(runner.runtime.get("jd_settlement_mode") or "day"),
            _historical_bill_target(runner, str(runner.runtime.get("jd_settlement_mode") or "day")),
        )
        runner.runtime["jd_settlement_row"] = row
        runner.runtime["jd_settlement_business_date"] = business_date
        return

    if code == "jd.settlement.download":
        from scripts.auto_download.playwright.jd_download_common import save_download
        row = runner.runtime["jd_settlement_row"]
        button = row.locator("button:visible").filter(has_text="下载明细").first
        async with runner.page.expect_download(timeout=120_000) as info:
            await button.evaluate("element => element.click()")
        downloaded = await save_download(
            await info.value, _work_dir(runner, "jd_settlement"), "jd_settlement.zip"
        )
        runner.runtime["jd_settlement_download"] = downloaded
        return

    if code == "jd.settlement.extract":
        from scripts.auto_download.playwright.jd_download_common import prepare_report_file
        from scripts.auto_download.playwright.jd_settlement_download import REPORT_NAME
        work_dir = _work_dir(runner, "jd_settlement")
        source = await asyncio.to_thread(
            prepare_report_file,
            Path(runner.runtime["jd_settlement_download"]),
            work_dir,
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["jd_settlement_business_date"]),
        )
        return

    if code == "jd.fund.set_date":
        from scripts.auto_download.playwright.jd_fund_download import select_date_range
        start_date, end_date = _input_range(runner)
        business_date = await select_date_range(runner.page, start_date, end_date)
        runner.runtime["jd_fund_business_date"] = business_date
        return

    if code == "jd.fund.create_export":
        from scripts.auto_download.playwright.jd_fund_download import create_export_task
        runner.runtime["jd_fund_row"] = await create_export_task(runner.page)
        return

    if code == "jd.fund.wait_download":
        from scripts.auto_download.playwright.jd_fund_download import wait_and_download
        runner.runtime["jd_fund_download"] = await wait_and_download(
            runner.page,
            runner.runtime["jd_fund_row"],
            _work_dir(runner, "jd_fund"),
        )
        return

    if code == "jd.fund.extract":
        from scripts.auto_download.playwright.jd_download_common import prepare_report_file
        from scripts.auto_download.playwright.jd_fund_download import REPORT_NAME
        work_dir = _work_dir(runner, "jd_fund")
        source = await asyncio.to_thread(
            prepare_report_file,
            Path(runner.runtime["jd_fund_download"]),
            work_dir,
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["jd_fund_business_date"]),
        )
        return

    if code == "jd.promotion.open":
        from scripts.auto_download.playwright import jd_promotion_fee_download as mod
        report_key = str(config.get("report_key") or "union")
        start_date, end_date = _input_range(runner)
        date_range = mod.requested_range(start_date, end_date, today=runner.business_date)
        page = runner.page or await _context(runner).new_page()
        runner.page = page
        if report_key == "union":
            await page.goto(mod.ALLIANCE_URL, wait_until="domcontentloaded", timeout=60_000)
            await mod._handle_login_redirect(page)
            await mod._wait_page_marker(page, mod.ALLIANCE_FEE_TIME_XPATH, "费用时间")
            await mod._select_option(
                page,
                mod.ALLIANCE_FEE_TIME_XPATH,
                mod.ALLIANCE_SETTLEMENT_OPTION_XPATH,
                "结算时间",
            )
        elif report_key == "tong":
            await page.goto(mod.TONG_URL, wait_until="domcontentloaded", timeout=60_000)
            await mod._handle_login_redirect(page)
            await mod._wait_page_marker(page, mod.TONG_CONSUMPTION_XPATH, "消费记录")
            await mod._click_xpath(page, mod.TONG_CONSUMPTION_XPATH, fallback_text="消费记录")
            await mod._select_option(
                page, mod.TONG_TIME_XPATH, mod.TONG_BOOKING_OPTION_XPATH, "记账时间"
            )
        else:
            raise ValueError(f"不支持的京东推广费报表：{report_key}")
        runner.runtime["jd_promotion_key"] = report_key
        runner.runtime["jd_promotion_range"] = date_range
        return

    if code == "jd.promotion.set_date":
        from scripts.auto_download.playwright import jd_promotion_fee_download as mod
        report_key = str(runner.runtime["jd_promotion_key"])
        date_range = runner.runtime["jd_promotion_range"]
        if report_key == "union":
            await mod.select_alliance_date(runner.page, date_range)
        else:
            await mod.select_tong_date(runner.page, date_range)
        return

    if code == "jd.promotion.create_export":
        from scripts.auto_download.playwright import jd_promotion_fee_download as mod
        report_key = str(runner.runtime["jd_promotion_key"])
        if report_key == "union":
            await mod._click_xpath(
                runner.page, mod.ALLIANCE_DOWNLOAD_ICON_XPATH, fallback_text=re.compile(r"下载")
            )
            submitted = await mod._start_generation(runner.page, report_label="京东联盟")
            await mod._wait_hash(runner.page, "#/download-report")
        else:
            await mod._click_xpath(
                runner.page, mod.TONG_DOWNLOAD_ICON_XPATH, fallback_text=re.compile(r"下载")
            )
            submitted = await mod._start_generation(runner.page, report_label="京东通")
            await mod._wait_hash(runner.page, "#/downReport")
        runner.runtime["jd_promotion_submitted"] = submitted
        return

    if code == "jd.promotion.wait_ready":
        from scripts.auto_download.playwright import jd_promotion_fee_download as mod
        report_key = str(runner.runtime["jd_promotion_key"])
        date_range = runner.runtime["jd_promotion_range"]
        row = await mod.wait_report_ready(
            runner.page,
            date_range=date_range,
            report_name=(
                mod.ALLIANCE_HISTORY_NAME if report_key == "union" else mod.TONG_HISTORY_NAME
            ),
            require_range=report_key != "union" and not date_range.from_shortcut,
            action_column=4 if report_key == "union" else 5,
            submitted_after=runner.runtime.get("jd_promotion_submitted"),
            timeout_seconds=float(node.get("timeout_seconds") or 900),
            report_label="京东联盟" if report_key == "union" else "京东通",
        )
        runner.runtime["jd_promotion_row"] = row
        return

    if code == "jd.promotion.download":
        from scripts.auto_download.playwright import jd_promotion_fee_download as mod
        report_key = str(runner.runtime["jd_promotion_key"])
        date_range = runner.runtime["jd_promotion_range"]
        report_label = mod._report_definition(report_key)[2]
        source = await mod._download_report_file(
            runner.page,
            runner.runtime["jd_promotion_row"],
            action_column=4 if report_key == "union" else 5,
            work_dir=_work_dir(runner, f"jd_promotion_{report_key}"),
            fallback=f"jd_{report_key}_promotion.xlsx",
        )
        end_value = getattr(date_range.end, "isoformat", lambda: str(date_range.end))()
        _set_pending(runner, source, report_label, str(end_value))
        return

    # ------------------------------------------------------------------
    # 拼多多订单 / 结算 / 推广费
    # ------------------------------------------------------------------
    if code == "pinduoduo.order.open":
        from scripts.auto_download.playwright.pinduoduo_order_download import open_order_page
        page, created = await open_order_page(
            _context(runner), platform=platform, company=company, shop=shop
        )
        runner.page = page
        runner.runtime["pdd_order_created"] = created
        return

    if code == "pinduoduo.order.set_date":
        from scripts.auto_download.playwright.pinduoduo_order_download import (
            choose_date_range,
            choose_recent_30_days,
            resolve_date_range,
        )
        start_date, end_date = _input_range(runner)
        if start_date is None:
            start_date, end_date = await choose_recent_30_days(runner.page)
        else:
            start_date, end_date = resolve_date_range(start_date, end_date)
            await choose_date_range(runner.page, start_date, end_date)
        runner.runtime["pdd_order_start"] = start_date
        runner.runtime["pdd_order_end"] = end_date
        return

    if code == "pinduoduo.order.query":
        from scripts.auto_download.playwright.pinduoduo_order_download import query_orders
        await query_orders(runner.page)
        return

    if code == "pinduoduo.order.create_export":
        from scripts.auto_download.playwright.pinduoduo_order_download import create_export
        runner.page = await create_export(runner.page)
        return

    if code == "pinduoduo.order.wait_ready":
        from scripts.auto_download.playwright.pinduoduo_order_download import newest_download_button
        runner.runtime["pdd_order_download_button"] = await newest_download_button(
            runner.page,
            runner.runtime["pdd_order_start"],
            runner.runtime["pdd_order_end"],
        )
        return

    if code == "pinduoduo.order.download":
        from scripts.auto_download.playwright.pinduoduo_order_download import (
            click_compat,
            close_important_popup,
            save_download,
        )
        async with runner.page.expect_download(timeout=120_000) as info:
            await close_important_popup(runner.page)
            await click_compat(runner.runtime["pdd_order_download_button"])
        source = await save_download(await info.value, _work_dir(runner, "pinduoduo_order"))
        _set_pending(runner, source, "订单", str(runner.runtime["pdd_order_end"]))
        return

    if code == "pinduoduo.settlement.open":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import open_reconciliation_center
        page, created = await open_reconciliation_center(_context(runner))
        runner.page = page
        runner.runtime["pdd_settlement_created"] = created
        return

    if code == "pinduoduo.settlement.set_date":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import (
            choose_date_range,
            resolve_date_range,
        )
        start_date, end_date = _input_range(runner)
        start_date, end_date = resolve_date_range(start_date, end_date)
        await choose_date_range(runner.page, start_date, end_date)
        runner.runtime["pdd_settlement_start"] = start_date
        runner.runtime["pdd_settlement_end"] = end_date
        return

    if code == "pinduoduo.settlement.create_export":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import create_export
        runner.page = await create_export(runner.page)
        return

    if code == "pinduoduo.settlement.wait_ready":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import (
            EXPORT_HISTORY_URL,
            find_export_card,
        )
        if "/main/bills/export-history" not in runner.page.url:
            await runner.page.goto(
                EXPORT_HISTORY_URL, wait_until="domcontentloaded", timeout=60_000
            )
        runner.runtime["pdd_settlement_card"] = await find_export_card(
            runner.page,
            runner.runtime["pdd_settlement_start"],
            runner.runtime["pdd_settlement_end"],
        )
        return

    if code == "pinduoduo.settlement.download":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import save_download
        card = runner.runtime["pdd_settlement_card"]
        async with runner.page.expect_download(timeout=120_000) as info:
            await card.get_by_role("button", name="下载账单", exact=True).click()
        source = await save_download(
            await info.value, _work_dir(runner, "pinduoduo_settlement")
        )
        runner.runtime["pdd_settlement_download"] = source
        return

    if code == "pinduoduo.settlement.extract":
        from scripts.auto_download.playwright.pinduoduo_settlement_download import (
            REPORT_NAME,
            extract_pdd_report,
        )
        work_dir = _work_dir(runner, "pinduoduo_settlement")
        source = await asyncio.to_thread(
            extract_pdd_report,
            Path(runner.runtime["pdd_settlement_download"]),
            work_dir,
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["pdd_settlement_end"]),
            validator="pdd.settlement",
        )
        return

    if code == "pinduoduo.promotion.open":
        from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import open_promotion_page
        page, opened = await open_promotion_page(
            _context(runner), platform=platform, company=company, shop=shop
        )
        runner.page = page
        runner.runtime["pdd_promotion_opened_pages"] = opened
        return

    if code == "pinduoduo.promotion.set_date":
        from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import set_promotion_date_range
        start_date, end_date = _input_range(runner)
        if start_date and end_date:
            start_value = date.fromisoformat(start_date)
            end_value = date.fromisoformat(end_date)
            await set_promotion_date_range(runner.page, start_value, end_value)
            runner.runtime["pdd_promotion_start"] = start_value
            runner.runtime["pdd_promotion_end"] = end_value
        else:
            runner.runtime["pdd_promotion_start"] = None
            runner.runtime["pdd_promotion_end"] = None
        return

    if code == "pinduoduo.promotion.apply_filters":
        from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import apply_filters
        await apply_filters(runner.page)
        return

    if code == "pinduoduo.promotion.query":
        from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import query_filtered_rows
        rows, amount = await query_filtered_rows(
            runner.page,
            start_date=runner.runtime.get("pdd_promotion_start"),
            end_date=runner.runtime.get("pdd_promotion_end"),
        )
        runner.runtime["pdd_promotion_rows"] = rows
        runner.runtime["pdd_promotion_amount"] = amount
        return

    if code == "pinduoduo.promotion.download":
        from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import (
            REPORT_NAME,
            _download_button,
            click_compat,
            save_download,
        )
        button = await _download_button(runner.page)
        async with runner.page.expect_download(timeout=120_000) as info:
            await click_compat(button)
        source = await save_download(
            await info.value, _work_dir(runner, "pinduoduo_promotion")
        )
        business_date = (
            runner.runtime["pdd_promotion_end"].isoformat()
            if runner.runtime.get("pdd_promotion_end")
            else runner.business_date.isoformat()
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            business_date,
            validator="pdd.promotion",
        )
        return

    # ------------------------------------------------------------------
    # 快手订单 / 资金 / 结算
    # ------------------------------------------------------------------
    if code == "kuaishou.order.open_page":
        from scripts.auto_download.playwright.kuaishou_order_download import (
            _read_state,
            _state_path,
            _write_state,
            open_order_page,
            recent_month_range,
        )
        start_date, end_date = _input_range(runner)
        custom_range = bool(start_date)
        if not custom_range:
            start_date, end_date = recent_month_range(today=runner.business_date)
        assert start_date and end_date
        work_dir = _work_dir(runner, "kuaishou_order")
        state_path = _state_path(work_dir)
        state = _read_state(state_path)
        if (
            state.get("start_date") != start_date
            or state.get("end_date") != end_date
            or state.get("stage") == "COMPLETED"
        ):
            state = {
                "platform": platform,
                "company": company,
                "shop": shop,
                "start_date": start_date,
                "end_date": end_date,
                "stage": "EXPORT_NOT_CREATED",
            }
            _write_state(state_path, state)
        page, created = await open_order_page(_context(runner), shop)
        runner.page = page
        runner.runtime.update({
            "ks_order_created": created,
            "ks_order_start": start_date,
            "ks_order_end": end_date,
            "ks_order_custom": custom_range,
            "ks_order_state": state,
            "ks_order_state_path": state_path,
            "ks_order_work_dir": work_dir,
            "ks_order_has_data": True,
        })
        return

    if code == "kuaishou.order.set_date":
        from scripts.auto_download.playwright.kuaishou_order_download import choose_recent_month
        await choose_recent_month(
            runner.page,
            runner.runtime["ks_order_start"],
            runner.runtime["ks_order_end"],
            use_preset=not bool(runner.runtime.get("ks_order_custom")),
        )
        return

    if code == "kuaishou.order.query":
        from scripts.auto_download.playwright.kuaishou_order_download import (
            click_query_and_wait,
            read_order_record_count,
        )
        await click_query_and_wait(runner.page)
        count = await read_order_record_count(runner.page)
        runner.runtime["ks_order_count"] = count
        runner.runtime["ks_order_has_data"] = count != 0
        return

    if code == "kuaishou.order.create_export":
        if not runner.runtime.get("ks_order_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_order_download import create_export_once
        await create_export_once(
            runner.page,
            platform=platform,
            company=company,
            shop=shop,
            state_path=runner.runtime["ks_order_state_path"],
            state=runner.runtime["ks_order_state"],
        )
        return

    if code == "kuaishou.order.wait_ready":
        if not runner.runtime.get("ks_order_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_order_download import (
            open_export_history,
            wait_latest_report,
        )
        history = await open_export_history(_context(runner))
        runner.page = history
        runner.runtime["ks_order_row"] = await wait_latest_report(
            history,
            runner.runtime["ks_order_start"],
            runner.runtime["ks_order_end"],
        )
        return

    if code == "kuaishou.order.download_password":
        if not runner.runtime.get("ks_order_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_order_download import send_file_code_and_download
        downloaded, password = await send_file_code_and_download(
            runner.page,
            runner.runtime["ks_order_row"],
            platform=platform,
            company=company,
            shop=shop,
            state_path=runner.runtime["ks_order_state_path"],
            state=runner.runtime["ks_order_state"],
            work_dir=runner.runtime["ks_order_work_dir"],
        )
        runner.runtime["ks_order_download"] = downloaded
        runner.runtime["ks_order_password"] = password
        return

    if code == "kuaishou.order.decrypt":
        if not runner.runtime.get("ks_order_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_order_download import (
            REPORT_NAME,
            _request_stateful_answer,
            _write_state,
            decrypt_xlsx,
        )
        downloaded = Path(runner.runtime["ks_order_download"])
        password = str(runner.runtime.get("ks_order_password") or "")
        target = downloaded.with_name(f"{downloaded.stem}_decrypted.xlsx")
        state = runner.runtime["ks_order_state"]
        state_path = runner.runtime["ks_order_state_path"]
        for attempt in range(3):
            with suppress(OSError):
                target.unlink(missing_ok=True)
            try:
                await asyncio.to_thread(decrypt_xlsx, downloaded, password, target)
                break
            except ValueError:
                if attempt >= 2:
                    raise RuntimeError("连续三次快手订单文件提取码错误")
                state["stage"] = "PASSWORD_REQUIRED"
                _write_state(state_path, state)
                password = await _request_stateful_answer(
                    challenge_key="file_password_challenge_id",
                    challenge_type="archive_password",
                    platform=platform,
                    company=company,
                    shop=shop,
                    purpose=f"上一次文件提取码错误，请重新输入。订单报表文件提取码（{downloaded.name}）",
                    page_url=runner.page.url,
                    state_path=state_path,
                    state=state,
                )
        _set_pending(
            runner,
            target,
            REPORT_NAME,
            runner.business_date.isoformat(),
            validator="ks.order",
        )
        return

    if code == "kuaishou.fund.open":
        from scripts.auto_download.playwright.kuaishou_download_common import ensure_logged_in, new_page
        from scripts.auto_download.playwright.kuaishou_fund_download import (
            FUND_BASE_URL,
            QUERY_RE,
            find_page_for_sub_mch_id,
            infer_sub_mch_id,
        )
        from urllib.parse import urlencode
        mode = str(config.get("mode") or "day")
        sub_mch_id = infer_sub_mch_id(runner.browser) or ""
        page = await find_page_for_sub_mch_id(runner.browser, sub_mch_id) if sub_mch_id else None
        if page is None:
            page = await new_page(runner.browser)
        url = FUND_BASE_URL + (f"?{urlencode({'subMchId': sub_mch_id})}" if sub_mch_id else "")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        ensure_logged_in(page)
        if mode == "month":
            await page.get_by_role("tab", name="月账单", exact=True).click()
        await page.get_by_role("button", name=QUERY_RE).click()
        runner.page = page
        runner.runtime["ks_fund_mode"] = mode
        return

    if code == "kuaishou.fund.locate_bill":
        from scripts.auto_download.playwright.kuaishou_fund_download import latest_bill_row
        row, business_date = await latest_bill_row(
            runner.page, str(runner.runtime.get("ks_fund_mode") or "day"),
            _historical_bill_target(runner, str(runner.runtime.get("ks_fund_mode") or "day")),
        )
        runner.runtime["ks_fund_row"] = row
        runner.runtime["ks_fund_business_date"] = business_date
        return

    if code == "kuaishou.fund.create_export":
        from scripts.auto_download.playwright.kuaishou_fund_download import EXPORT_BILL_RE
        row = runner.runtime["ks_fund_row"]
        await row.get_by_role("button", name=EXPORT_BILL_RE).click()
        with suppress(Exception):
            await runner.page.get_by_text("账单导出成功", exact=True).wait_for(
                state="visible", timeout=10_000
            )
        await runner.page.get_by_role("button", name="导出记录", exact=True).click()
        await runner.page.wait_for_url("**/zone/fund/accounting/export-list**", timeout=30_000)
        return

    if code == "kuaishou.fund.wait_ready":
        from scripts.auto_download.playwright.kuaishou_fund_download import find_export_record
        page, card = await find_export_record(
            runner.browser,
            runner.page,
            str(runner.runtime["ks_fund_business_date"]),
        )
        runner.page = page
        runner.runtime["ks_fund_card"] = card
        return

    if code == "kuaishou.fund.download":
        from scripts.auto_download.playwright.kuaishou_download_common import save_download
        from scripts.auto_download.playwright.kuaishou_fund_download import DOWNLOAD_RE
        card = runner.runtime["ks_fund_card"]
        async with runner.page.expect_download(timeout=120_000) as info:
            await card.get_by_role("button", name=DOWNLOAD_RE).click()
        runner.runtime["ks_fund_download"] = await save_download(
            await info.value, _work_dir(runner, "kuaishou_fund"), "kuaishou_fund.csv"
        )
        return

    if code == "kuaishou.fund.extract":
        from scripts.auto_download.playwright.kuaishou_download_common import prepare_report_file
        from scripts.auto_download.playwright.kuaishou_fund_download import REPORT_NAME
        work_dir = _work_dir(runner, "kuaishou_fund")
        source = await asyncio.to_thread(
            prepare_report_file,
            Path(runner.runtime["ks_fund_download"]),
            work_dir,
            (".csv", ".xlsx"),
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["ks_fund_business_date"]),
        )
        return

    if code == "kuaishou.settlement.open":
        from scripts.auto_download.playwright.kuaishou_download_common import ensure_logged_in, new_page
        from scripts.auto_download.playwright.kuaishou_settlement_download import SETTLEMENT_URL
        page = await new_page(runner.browser)
        await page.goto(SETTLEMENT_URL, wait_until="domcontentloaded", timeout=60_000)
        ensure_logged_in(page)
        runner.page = page
        return

    if code == "kuaishou.settlement.set_date":
        from scripts.auto_download.playwright.kuaishou_settlement_download import choose_range
        start_date, end_date = _input_range(runner)
        start_date = start_date or runner.business_date.isoformat()
        end_date = end_date or runner.business_date.isoformat()
        start_value, end_value = await choose_range(runner.page, start_date, end_date)
        runner.runtime.update({
            "ks_settlement_start": start_date,
            "ks_settlement_end": end_date,
            "ks_settlement_start_value": start_value,
            "ks_settlement_end_value": end_value,
        })
        return

    if code == "kuaishou.settlement.create_export":
        from scripts.auto_download.playwright.kuaishou_settlement_download import create_export
        runner.runtime["ks_settlement_has_data"] = await create_export(runner.page)
        return

    if code == "kuaishou.settlement.wait_ready":
        if not runner.runtime.get("ks_settlement_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_settlement_download import (
            EXPORT_URL,
            find_export_record,
        )
        await runner.page.goto(EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
        runner.runtime["ks_settlement_card"] = await find_export_record(
            runner.page,
            runner.runtime["ks_settlement_start_value"],
            runner.runtime["ks_settlement_end_value"],
        )
        return

    if code == "kuaishou.settlement.download":
        if not runner.runtime.get("ks_settlement_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_download_common import save_download
        from scripts.auto_download.playwright.kuaishou_settlement_download import DOWNLOAD_RE
        card = runner.runtime["ks_settlement_card"]
        async with runner.page.expect_download(timeout=120_000) as info:
            await card.get_by_role("button", name=DOWNLOAD_RE).click()
        runner.runtime["ks_settlement_download"] = await save_download(
            await info.value,
            _work_dir(runner, "kuaishou_settlement"),
            "kuaishou_settlement.zip",
        )
        return

    if code == "kuaishou.settlement.extract":
        if not runner.runtime.get("ks_settlement_has_data", True):
            return
        from scripts.auto_download.playwright.kuaishou_download_common import prepare_report_file
        from scripts.auto_download.playwright.kuaishou_settlement_download import REPORT_NAME
        work_dir = _work_dir(runner, "kuaishou_settlement")
        source = await asyncio.to_thread(
            prepare_report_file,
            Path(runner.runtime["ks_settlement_download"]),
            work_dir,
            (".xlsx", ".csv"),
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["ks_settlement_end"]),
        )
        return

    # ------------------------------------------------------------------
    # 天猫订单 / 资金 / 推广费
    # ------------------------------------------------------------------
    if code == "tmall.order.open_page":
        from scripts.auto_download.playwright import tmall_order_download as mod
        start_date, end_date = _input_range(runner)
        start_date, end_date = mod.resolve_date_range(start_date, end_date)
        page, created_pages = await mod.open_order_page(
            runner.browser, mod.DEFAULT_USERNAME, mod.DEFAULT_PASSWORD_ENV
        )
        runner.page = page
        work_dir = _work_dir(runner, "tmall_order")
        state_path = work_dir / mod.STATE_FILENAME
        request = mod.state_request(start_date, end_date, company, shop)
        state = mod.read_state(state_path)
        if state is None or state.get("request") != request or state.get("stage") == "COMPLETED":
            state = mod.new_state(request)
            mod.write_state(state_path, state)
        runner.runtime.update({
            "tmall_order_start": start_date,
            "tmall_order_end": end_date,
            "tmall_order_created_pages": created_pages,
            "tmall_order_work_dir": work_dir,
            "tmall_order_state_path": state_path,
            "tmall_order_state": state,
        })
        return

    if code == "tmall.order.set_date":
        from scripts.auto_download.playwright.tmall_order_download import set_order_date_range
        await set_order_date_range(
            runner.page,
            runner.runtime["tmall_order_start"],
            runner.runtime["tmall_order_end"],
        )
        return

    if code == "tmall.order.search":
        from scripts.auto_download.playwright.tmall_order_download import search_orders
        await search_orders(
            runner.page,
            runner.runtime["tmall_order_start"],
            runner.runtime["tmall_order_end"],
        )
        return

    if code == "tmall.order.create_export":
        from scripts.auto_download.playwright.tmall_order_download import create_export_task
        history, pages = await create_export_task(
            runner.page,
            runner.runtime["tmall_order_state_path"],
            runner.runtime["tmall_order_state"],
            runner.runtime["tmall_order_start"],
            runner.runtime["tmall_order_end"],
        )
        runner.page = history
        runner.runtime["tmall_order_created_pages"].extend(pages)
        return

    if code == "tmall.order.wait_ready":
        from scripts.auto_download.playwright.tmall_order_download import (
            parse_history_datetime,
            wait_for_ready_history_record,
        )
        state = runner.runtime["tmall_order_state"]
        submitted = parse_history_datetime(str(state.get("submitted_at", "")))
        runner.runtime["tmall_order_record"] = await wait_for_ready_history_record(
            runner.page,
            runner.runtime["tmall_order_start"],
            runner.runtime["tmall_order_end"],
            submitted,
            state.get("creation_mode") == "rate_limited",
            int(node.get("timeout_seconds") or 900),
        )
        return

    if code == "tmall.order.download":
        from scripts.auto_download.playwright.tmall_order_download import (
            REPORT_NAME,
            download_history_record,
        )
        row = runner.runtime["tmall_order_record"][0]
        source = await download_history_record(
            runner.page, row, runner.runtime["tmall_order_work_dir"]
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["tmall_order_end"]),
        )
        return

    if code == "tmall.aggregate_fund.open":
        from scripts.auto_download.playwright.login_extensions.tmall_finance_login import ensure_tmall_login
        from scripts.auto_download.playwright.tmall_aggregate_fund_download import (
            AGGREGATE_FUND_URL,
            DEFAULT_PASSWORD_ENV,
            DEFAULT_USERNAME,
        )
        from scripts.auto_download.playwright.tmall_alipay_fund_download import find_work_page
        mode = str(config.get("mode") or "day")
        page = await find_work_page(runner.browser)
        await ensure_tmall_login(page, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV)
        await page.goto(AGGREGATE_FUND_URL, wait_until="domcontentloaded")
        runner.page = page
        runner.runtime["tmall_aggregate_mode"] = mode
        return

    if code == "tmall.aggregate_fund.select_mode":
        from scripts.auto_download.playwright.tmall_aggregate_fund_download import select_mode
        await select_mode(runner.page, str(runner.runtime.get("tmall_aggregate_mode") or "day"))
        return

    if code == "tmall.aggregate_fund.locate":
        from scripts.auto_download.playwright.tmall_aggregate_fund_download import latest_downloadable_row
        mode = str(runner.runtime.get("tmall_aggregate_mode") or "day")
        target_date = runner.business_date.isoformat() if mode == "day" else None
        row, business_date = await latest_downloadable_row(runner.page, mode, target_date)
        runner.runtime["tmall_aggregate_row"] = row
        runner.runtime["tmall_aggregate_business_date"] = business_date
        return

    if code == "tmall.aggregate_fund.download":
        from scripts.auto_download.playwright.tmall_aggregate_fund_download import (
            REPORT_NAME,
            download_report,
        )
        source = await download_report(
            runner.page,
            runner.runtime["tmall_aggregate_row"],
            _work_dir(runner, "tmall_aggregate_fund"),
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["tmall_aggregate_business_date"]),
        )
        return

    if code == "tmall.session.open":
        from scripts.auto_download.playwright.login_extensions.tmall_finance_login import (
            DEFAULT_PASSWORD_ENV,
            DEFAULT_USERNAME,
            ensure_tmall_login,
        )
        from scripts.auto_download.playwright.tmall_alipay_fund_download import find_work_page
        page = await find_work_page(runner.browser)
        await ensure_tmall_login(page, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV)
        runner.page = page
        return

    if code == "tmall.alipay.open_account":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import open_account_info
        await open_account_info(runner.page, shop)
        return

    if code == "tmall.alipay.open_page":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import open_alipay_page
        page, created = await open_alipay_page(runner.page)
        runner.page = page
        runner.runtime["tmall_alipay_created"] = created
        return

    if code == "tmall.alipay.open_bill":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import (
            ensure_list_mode,
            open_bill_download,
        )
        await open_bill_download(runner.page)
        await ensure_list_mode(runner.page)
        return

    if code == "tmall.alipay.select_mode":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import select_bill_mode
        mode = str(config.get("mode") or "day")
        runner.runtime["tmall_alipay_mode"] = mode
        await select_bill_mode(runner.page, mode)
        return

    if code == "tmall.alipay.wait_ready":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import wait_first_downloadable_bill_row
        mode = str(runner.runtime.get("tmall_alipay_mode") or "day")
        target_date = runner.business_date.isoformat() if mode == "day" else None
        row, business_date = await wait_first_downloadable_bill_row(
            runner.page, mode, target_date
        )
        runner.runtime["tmall_alipay_row"] = row
        runner.runtime["tmall_alipay_business_date"] = business_date
        return

    if code == "tmall.alipay.download":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import download_zip
        archive = await download_zip(
            runner.page,
            runner.runtime["tmall_alipay_row"],
            _work_dir(runner, "tmall_alipay"),
        )
        runner.runtime["tmall_alipay_archive"] = archive
        return

    if code == "tmall.alipay.extract":
        from scripts.auto_download.playwright.tmall_alipay_fund_download import (
            REPORT_NAME,
            extracted_path_from_log,
            run_project_module,
        )
        work_dir = _work_dir(runner, "tmall_alipay")
        log = await asyncio.to_thread(
            run_project_module,
            [
                "scripts.auto_download.extract_report",
                "--archive", str(runner.runtime["tmall_alipay_archive"]),
                "--dest", str(work_dir),
                "--include", "账务明细",
                "--exclude", "(汇总)",
                "--filename-encoding", "gbk",
                "--delete-archive",
            ],
        )
        source = extracted_path_from_log(log)
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["tmall_alipay_business_date"]),
        )
        return

    if code == "tmall.union.open":
        from scripts.auto_download.playwright.tmall_promotion_download_common import (
            DEFAULT_PASSWORD_ENV,
            DEFAULT_USERNAME,
            open_alimama_page,
        )
        from scripts.auto_download.playwright.tmall_taobao_union_promotion_download import PROMOTION_REPORT_URL
        mode = str(config.get("mode") or "day")
        runner.page = await open_alimama_page(
            runner.browser, PROMOTION_REPORT_URL, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV
        )
        runner.runtime["tmall_union_mode"] = mode
        return

    if code == "tmall.union.select_period":
        from scripts.auto_download.playwright.tmall_taobao_union_promotion_download import select_period
        runner.runtime["tmall_union_business_date"] = await select_period(
            runner.page, str(runner.runtime.get("tmall_union_mode") or "day"),
            *_input_range(runner),
        )
        return

    if code == "tmall.union.download":
        from scripts.auto_download.playwright.tmall_taobao_union_promotion_download import (
            REPORT_NAME,
            download_report,
        )
        source = await download_report(runner.page, _work_dir(runner, "tmall_union"))
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["tmall_union_business_date"]),
        )
        return

    if code == "tmall.wanxiangtai.open":
        from scripts.auto_download.playwright.tmall_promotion_download_common import (
            DEFAULT_PASSWORD_ENV,
            DEFAULT_USERNAME,
            open_alimama_page,
            period_label,
            report_period,
            wanxiangtai_url,
        )
        mode = str(config.get("mode") or "day")
        start_value, end_value = _input_range(runner)
        start, end = report_period(mode, today=runner.business_date, start_date=start_value, end_date=end_value)
        runner.page = await open_alimama_page(
            runner.browser,
            wanxiangtai_url(start, end),
            DEFAULT_USERNAME,
            DEFAULT_PASSWORD_ENV,
        )
        runner.runtime["tmall_wxt_business_date"] = period_label(start, end, mode)
        return

    if code == "tmall.wanxiangtai.download":
        from scripts.auto_download.playwright.tmall_wanxiangtai_promotion_download import (
            REPORT_NAME,
            download_report,
        )
        source = await download_report(
            runner.page, _work_dir(runner, "tmall_wanxiangtai")
        )
        _set_pending(
            runner,
            source,
            REPORT_NAME,
            str(runner.runtime["tmall_wxt_business_date"]),
        )
        return

    raise RuntimeError(f"未实现平台原子组件：{code}")
