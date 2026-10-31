from __future__ import annotations

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from scripts.auto_download.playwright.tmall_promotion_download_common import (
    is_alimama_report_page,
    is_alimama_target_page,
    month_choices_from_text,
    period_label,
    report_period,
    wanxiangtai_url,
)
from scripts.auto_download.playwright.tmall_taobao_union_promotion_download import (
    confirmed_period_from_overview,
    history_row_matches,
)


class TmallPromotionDownloadTests(unittest.TestCase):
    def test_embedded_form_wait_never_clicks_header_login_popup(self):
        from scripts.auto_download.playwright import tmall_promotion_download_common as common
        page=MagicMock(url=common.ALIMAMA_LOGIN_URL); surface=MagicMock(); container=MagicMock()
        page.get_by_role.return_value.filter.return_value.count=AsyncMock(return_value=0)
        container.get_by_text.return_value.filter.return_value.count=AsyncMock(return_value=0)
        with patch.object(common,'_password_form',new=AsyncMock(side_effect=[None,surface])), \
                patch.object(common,'_alimama_authenticated',new=AsyncMock(return_value=False)), \
                patch.object(common,'_follow_alimama_session_link',new=AsyncMock(return_value=False)), \
                patch.object(common,'_inline_login_container',return_value=container), \
                patch.object(common.asyncio,'sleep',new=AsyncMock()):
            self.assertIs(surface,asyncio.run(common._wait_for_password_form(page)))
        self.assertFalse(any(call.kwargs.get('name')=='立即登录' for call in page.get_by_role.call_args_list))
        page.get_by_text.assert_not_called()

    def test_form_is_bound_to_first_iframe_and_supplied_container_xpath(self):
        from scripts.auto_download.playwright.tmall_promotion_download_common import _inline_login_container
        page=MagicMock()
        _inline_login_container(page)
        page.frame_locator.assert_called_once_with('iframe[src*="login.taobao.com/member/login.jhtml"]')
        page.frame_locator.return_value.first.locator.assert_called_once_with('xpath=//*[@id="container"]')

    def test_quick_enter_is_optional_and_prefers_the_direct_link(self):
        from scripts.auto_download.playwright import tmall_promotion_download_common as common
        for present in (False,True):
            page=MagicMock()
            link=MagicMock(); button=MagicMock()
            link.count=AsyncMock(return_value=int(present)); button.count=AsyncMock(return_value=0)
            link.first.click=AsyncMock()
            page.get_by_role.side_effect=lambda role,**kwargs: MagicMock(filter=lambda **kw: link if role=='link' else button)
            self.assertEqual(present,asyncio.run(common._click_quick_enter_if_present(page)))
            self.assertEqual(int(present),link.first.click.await_count)
            if present:self.assertEqual(1,page.get_by_role.call_count)

    def test_direct_home_does_not_require_quick_enter_or_a_login_form(self):
        from scripts.auto_download.playwright import tmall_promotion_download_common as common
        page=MagicMock()
        with patch.object(common,'_alimama_authenticated',new=AsyncMock(return_value=True)), \
                patch.object(common,'_password_form',new=AsyncMock()) as form, \
                patch.object(common,'_click_quick_enter_if_present',new=AsyncMock()) as quick:
            self.assertIsNone(asyncio.run(common._wait_for_password_form(page)))
        form.assert_not_awaited(); quick.assert_not_awaited()

    def test_history_download_requires_exact_requested_period(self) -> None:
        self.assertTrue(history_row_matches('2026/08/01 至 2026/08/07 下载', '2026-08-01', '2026-08-07'))
        self.assertFalse(history_row_matches('2026-09-01 至 2026-09-07 下载', '2026-08-01', '2026-08-07'))
        self.assertFalse(history_row_matches('2026-08-01 至 2026-08-31 下载', '2026-08-01', '2026-08-07'))
        self.assertFalse(history_row_matches('2026-08-01 创建 下载', '2026-08-01', '2026-08-01'))

    def test_union_daily_overview_may_show_only_the_cutoff_date(self) -> None:
        self.assertEqual(
            ("2026-10-09", "2026-10-09"),
            confirmed_period_from_overview(
                "当前数据统计截止到：2026-10-09", "2026-10-09", "2026-10-09"
            ),
        )

    def test_union_range_overview_must_match_requested_dates(self) -> None:
        self.assertEqual(
            ("2026-10-01", "2026-10-09"),
            confirmed_period_from_overview(
                "2026-10-01 至 2026-10-09", "2026-10-01", "2026-10-09"
            ),
        )
        with self.assertRaises(RuntimeError):
            confirmed_period_from_overview(
                "2026-10-02 至 2026-10-09", "2026-10-01", "2026-10-09"
            )

    def test_day_period_is_previous_day(self) -> None:
        start, end = report_period("day", date(2026, 8, 18))
        self.assertEqual((date(2026, 8, 17), date(2026, 8, 17)), (start, end))
        self.assertEqual("2026-08-17", period_label(start, end, "day"))

    def test_month_period_is_previous_complete_month(self) -> None:
        start, end = report_period("month", date(2026, 8, 18))
        self.assertEqual((date(2026, 7, 1), date(2026, 7, 31)), (start, end))
        self.assertEqual("2026-07", period_label(start, end, "month"))

    def test_wanxiangtai_url_uses_requested_cash_range(self) -> None:
        start, end = date(2026, 8, 17), date(2026, 8, 17)
        parsed = urlparse(wanxiangtai_url(start, end))
        query = parse_qs(parsed.fragment.partition("?")[2])
        self.assertEqual(["2026-08-17"], query["cashStart"])
        self.assertEqual(["2026-08-17"], query["cashEnd"])
        self.assertEqual(["DEDUCT"], query["trade"])
        self.assertEqual(["acount"], query["time"])

    def test_extracts_month_choices_from_union_hover_text(self) -> None:
        self.assertEqual(
            ["2026-07", "2026-06"],
            month_choices_from_text("2026年7月  2026-06"),
        )

    def test_recognizes_union_report_page_after_login_redirect(self) -> None:
        self.assertTrue(
            is_alimama_report_page(
                "https://ad.alimama.com/portal/v2/report/promotionDataPage.htm?spm=example"
            )
        )
        self.assertFalse(is_alimama_report_page("https://ad.alimama.com/index.htm"))

    def test_matches_wanxiangtai_hash_route(self) -> None:
        target = (
            "https://one.alimama.com/index.html#!/account/detail?"
            "cashStart=2026-08-17&cashEnd=2026-08-17"
        )
        self.assertTrue(
            is_alimama_target_page(
                target + "&spm=example",
                target,
            )
        )
        self.assertFalse(is_alimama_target_page("https://ad.alimama.com/index.htm", target))


class AlimamaSessionLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from scripts.auto_download.playwright import tmall_promotion_download_common as common
        self.common = common
        events = patch.object(common, "component_event")
        events.start()
        self.addCleanup(events.stop)
        telemetry = patch.dict(common.os.environ, {"MOCK_AUTOMATION_COMPONENT_TELEMETRY": "0"})
        telemetry.start()
        self.addCleanup(telemetry.stop)

    def browser_with(self, *pages):
        context = SimpleNamespace(pages=list(pages), new_page=AsyncMock())
        for page in pages:
            page.context = context
        return SimpleNamespace(contexts=[context]), context

    async def test_authenticated_session_needs_no_password_or_home_reload(self):
        page = MagicMock(url="https://ad.alimama.com/portal/v2/dashboard.htm")
        browser, _ = self.browser_with(page)
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(return_value=True)), \
                patch.object(self.common, "_open_alimama_target", new=AsyncMock(return_value=page)), \
                patch.object(self.common, "_open_alimama_from_qianniu", new=AsyncMock()) as qianniu, \
                patch.object(self.common.os, "getenv", wraps=self.common.os.getenv) as getenv:
            result = await self.common.open_alimama_page(browser, "https://ad.alimama.com/portal/v2/report/promotionDataPage.htm", "", "TEST_SESSION_PASSWORD")
        self.assertIs(page, result)
        self.assertFalse(any(call.args[0] == "TEST_SESSION_PASSWORD" for call in getenv.call_args_list))
        qianniu.assert_not_awaited()
        page.goto.assert_not_called()

    async def test_existing_quick_entry_is_confirmed_without_refreshing(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        browser, _ = self.browser_with(page)
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(return_value=False)), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(return_value=True)), \
                patch.object(self.common, "_wait_for_alimama_login", new=AsyncMock()) as wait, \
                patch.object(self.common, "_open_alimama_target", new=AsyncMock(return_value=page)), \
                patch.object(self.common, "_open_alimama_from_qianniu", new=AsyncMock()) as qianniu:
            self.assertIs(page, await self.common.open_alimama_page(browser, "target", "", ""))
        wait.assert_awaited_once_with(page, quick_enter_clicked=True)
        qianniu.assert_not_awaited()
        page.goto.assert_not_called()

    async def test_missing_alimama_session_uses_the_same_qianniu_context(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        popup = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        browser, context = self.browser_with(page)
        popup.context = context
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(return_value=False)), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(return_value=False)), \
                patch.object(self.common, "_open_alimama_from_qianniu", new=AsyncMock(return_value=popup)) as qianniu, \
                patch.object(self.common, "_wait_for_password_form", new=AsyncMock(return_value=None)), \
                patch.object(self.common, "_open_alimama_target", new=AsyncMock(return_value=popup)), \
                patch.object(self.common.os, "getenv", wraps=self.common.os.getenv) as getenv:
            self.assertIs(popup, await self.common.open_alimama_page(browser, "target", "", "TEST_SSO_PASSWORD"))
        self.assertFalse(any(call.args[0] == "TEST_SSO_PASSWORD" for call in getenv.call_args_list))
        qianniu.assert_awaited_once_with(context)
        context.new_page.assert_not_awaited()

    async def test_qianniu_menu_captures_new_tab_instead_of_old_alimama_tab(self):
        seller = MagicMock(url=self.common.QIANNIU_HOME_URL + "/QnworkbenchHome/")
        old = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        popup = MagicMock(url="about:blank")
        _, context = self.browser_with(seller, old)
        entry = seller.get_by_role.return_value.filter.return_value.first
        entry.count = AsyncMock(return_value=1)
        entry.wait_for = AsyncMock()
        entry.get_attribute = AsyncMock(return_value=self.common.ALIMAMA_LOGIN_URL)

        async def click(**kwargs):
            popup.context = context
            context.pages.append(popup)

        entry.click = AsyncMock(side_effect=click)
        self.assertIs(popup, await self.common._open_alimama_from_qianniu(context))
        entry.click.assert_awaited_once()
        self.assertIs(popup.context, seller.context)
        seller.goto.assert_not_called()
        context.new_page.assert_not_awaited()

    async def test_qianniu_menu_also_supports_same_tab_navigation(self):
        seller = MagicMock(url=self.common.QIANNIU_HOME_URL)
        _, context = self.browser_with(seller)
        entry = seller.get_by_role.return_value.filter.return_value.first
        entry.count = AsyncMock(return_value=1)
        entry.wait_for = AsyncMock()
        entry.get_attribute = AsyncMock(return_value=self.common.ALIMAMA_LOGIN_URL)

        async def click(**kwargs):
            seller.url = self.common.ALIMAMA_LOGIN_URL

        entry.click = AsyncMock(side_effect=click)
        self.assertIs(seller, await self.common._open_alimama_from_qianniu(context))

    async def test_unexpected_menu_destination_is_not_followed(self):
        seller = MagicMock(url=self.common.QIANNIU_HOME_URL)
        _, context = self.browser_with(seller)
        entry = seller.get_by_role.return_value.filter.return_value.first
        entry.count = AsyncMock(return_value=1)
        entry.wait_for = AsyncMock()
        entry.get_attribute = AsyncMock(return_value="https://example.invalid/")
        entry.click = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "目标地址不符合预期"):
            await self.common._open_alimama_from_qianniu(context)
        entry.click.assert_not_awaited()

    async def test_expired_qianniu_session_preserves_its_login_page(self):
        _, context = self.browser_with()
        seller = MagicMock(url="about:blank")

        async def goto(url, **kwargs):
            seller.url = "https://loginmyseller.taobao.com/"

        seller.goto = AsyncMock(side_effect=goto)
        context.new_page = AsyncMock(return_value=seller)
        self.assertIsNone(await self.common._open_alimama_from_qianniu(context))
        self.assertEqual("https://loginmyseller.taobao.com/", seller.url)
        seller.get_by_role.assert_not_called()

    async def test_quick_entry_requiring_human_does_not_start_another_login(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        browser, _ = self.browser_with(page)
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(return_value=False)), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(return_value=True)), \
                patch.object(self.common, "_wait_for_alimama_login", new=AsyncMock(side_effect=self.common.NeedsHumanError("verification required"))), \
                patch.object(self.common, "_open_alimama_from_qianniu", new=AsyncMock()) as qianniu:
            with self.assertRaises(self.common.NeedsHumanError):
                await self.common.open_alimama_page(browser, "target", "", "")
        qianniu.assert_not_awaited()
        page.goto.assert_not_called()

    async def test_delayed_quick_entry_is_clicked_only_once(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(side_effect=[False, False, True])), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(return_value=True)) as quick, \
                patch.object(self.common, "_password_form", new=AsyncMock(return_value=None)), \
                patch.object(self.common.asyncio, "sleep", new=AsyncMock()):
            await self.common._wait_for_alimama_login(page)
        quick.assert_awaited_once_with(page)
        page.goto.assert_not_called()

    async def test_quick_entry_wait_does_not_fall_back_to_password_during_redirect(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        container = MagicMock()
        container.get_by_text.return_value.filter.return_value.count = AsyncMock(return_value=0)
        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(side_effect=[False, False, True])), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(return_value=True)) as quick, \
                patch.object(self.common, "_password_form", new=AsyncMock(return_value=None)), \
                patch.object(self.common, "_follow_alimama_session_link", new=AsyncMock(return_value=False)), \
                patch.object(self.common, "_inline_login_container", return_value=container), \
                patch.object(self.common.asyncio, "sleep", new=AsyncMock()):
            self.assertIsNone(await self.common._wait_for_password_form(page))
        quick.assert_awaited_once_with(page)

    async def test_normal_sso_link_reuses_the_same_tab_and_saved_session(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        href = (
            "https://login.m.taobao.com/login.htm?redirectURL="
            "https%3A%2F%2Fjump.taobao.com%2Fjump%3Ftarget%3D"
            "https%253A%252F%252Fad.alimama.com%252Findex.htm"
        )
        link = page.get_by_role.return_value.filter.return_value.first
        link.count = AsyncMock(return_value=1)
        link.get_attribute = AsyncMock(return_value=href)
        page.goto = AsyncMock()
        self.assertTrue(await self.common._follow_alimama_session_link(page))
        page.get_by_role.assert_called_once_with("link", name="立即登录", exact=True)
        page.goto.assert_awaited_once_with(href, wait_until="domcontentloaded", timeout=60_000)
        link.click.assert_not_called()

    async def test_sso_link_requires_an_alimama_return_destination(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        link = page.get_by_role.return_value.filter.return_value.first
        link.count = AsyncMock(return_value=1)
        link.get_attribute = AsyncMock(return_value=(
            "https://login.m.taobao.com/login.htm?redirectURL=https%3A%2F%2Fexample.invalid%2F"
        ))
        page.goto = AsyncMock()
        self.assertFalse(await self.common._follow_alimama_session_link(page))
        page.goto.assert_not_awaited()

    async def test_missing_sso_anchor_does_not_click_the_popup_button(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        link = page.get_by_role.return_value.filter.return_value.first
        link.count = AsyncMock(return_value=0)
        page.goto = AsyncMock()
        self.assertFalse(await self.common._follow_alimama_session_link(page))
        page.get_by_role.assert_called_once_with("link", name="立即登录", exact=True)
        page.goto.assert_not_awaited()

    async def test_taobao_and_alimama_confirmation_pages_each_receive_one_click(self):
        page = MagicMock(url=self.common.ALIMAMA_LOGIN_URL)
        mobile_url = "https://login.m.taobao.com/login.htm"
        clicked = []
        redirected = False

        async def follow(current):
            nonlocal redirected
            redirected = True
            current.url = mobile_url
            return True

        async def quick(current):
            if not redirected:
                return False
            clicked.append(current.url)
            if current.url == mobile_url:
                current.url = self.common.ALIMAMA_LOGIN_URL
            else:
                current.url = "https://ad.alimama.com/portal/v2/dashboard.htm"
            return True

        async def authenticated(current):
            return "/portal/" in current.url

        with patch.object(self.common, "_alimama_authenticated", new=AsyncMock(side_effect=authenticated)), \
                patch.object(self.common, "_click_quick_enter_if_present", new=AsyncMock(side_effect=quick)), \
                patch.object(self.common, "_password_form", new=AsyncMock(return_value=None)), \
                patch.object(self.common, "_follow_alimama_session_link", new=AsyncMock(side_effect=follow)) as sso, \
                patch.object(self.common.asyncio, "sleep", new=AsyncMock()):
            self.assertIsNone(await self.common._wait_for_password_form(page))
        sso.assert_awaited_once_with(page)
        self.assertEqual([mobile_url, self.common.ALIMAMA_LOGIN_URL], clicked)

    async def test_wanxiangtai_same_route_still_applies_the_new_business_dates(self):
        old = self.common.wanxiangtai_url(date(2026, 10, 26), date(2026, 10, 26))
        target = self.common.wanxiangtai_url(date(2026, 10, 27), date(2026, 10, 27))
        page = MagicMock(url=old)

        async def goto(url, **kwargs):
            page.url = url

        page.goto = AsyncMock(side_effect=goto)
        with patch.object(self.common, "_password_form", new=AsyncMock(return_value=None)):
            self.assertIs(page, await self.common._open_alimama_target(page, target))
        page.goto.assert_awaited_once_with(target, wait_until="domcontentloaded", timeout=60_000)


if __name__ == "__main__":
    unittest.main()
