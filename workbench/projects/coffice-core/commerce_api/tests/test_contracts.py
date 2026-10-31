import ast
import unittest
from datetime import date

from commerce_api.core.contracts import Period
from commerce_api.core.errors import ContractError, UsageError
from commerce_api.core.registry import Registry, load_symbol
from commerce_api.cli.help import build_parser
from commerce_api.runtime.storage import PROJECT
from commerce_api.platforms.jd.backends.merchant.api.reports.settlements import row_business_date
from commerce_api.platforms.pinduoduo.backends.promotion.api.reports.promotion import payload
from commerce_api.platforms.kuaishou.backends.merchant.api.reports.orders import filters
from commerce_api.platforms.tmall.backends.qianniu.api.reports.orders import order_count


class ContractTests(unittest.TestCase):
    def test_douyin_order_search_uses_query_sort_fields_without_export_options(self):
        from commerce_api.platforms.douyin.backends.merchant.api.reports.orders import query_params
        query = query_params(Period.parse(day="2026-10-28"))
        self.assertEqual((query["order_by"], query["order"]), ("create_time", "desc"))
        self.assertEqual(query["source"], "shop_order_view_upgrade")
        self.assertNotIn("file_type", query)
        self.assertNotIn("report_type", query)

    def test_jd_settlement_uses_settlement_day_not_following_accounting_day(self):
        self.assertEqual(row_business_date({"setDate": "20261028", "accDate": "20261029"}), "2026-10-28")
        self.assertEqual(row_business_date({"setDate": "2026-10-28 00:00:00", "accDate": "20261029"}), "2026-10-28")

    def test_closed_day_boundaries_and_leap_month(self):
        period = Period.parse(day="2026-10-28")
        self.assertEqual(period.timestamp(end=True) - period.timestamp(), 86399)
        self.assertEqual(Period.parse(month="2024-02").end, date(2024, 2, 29))
        with self.assertRaises(UsageError):
            Period.parse(start="2026-10-28")

    def test_pdd_promotion_keeps_cash_expense_filters(self):
        period = Period.parse(day="2026-10-28")
        result = payload({"flowType": 3, "fundType": 9}, period)
        self.assertEqual((result["fundType"], result["flowType"]), (1, 2))
        self.assertEqual(result["startDate"], "2026-10-28")

    def test_kuaishou_hidden_and_visible_date_fields_cannot_diverge(self):
        period = Period.parse(day="2026-10-28")
        result = filters({"startTime": 0, "endTime": 1, "timeValue": [4, 5]}, period)
        self.assertEqual(result["time"], result["timeValue"])
        self.assertEqual(result["time"], [result["startTime"], result["endTime"]])
        self.assertEqual(result["endTime"] % 1000, 999)

    def test_tmall_missing_total_is_an_error_not_zero_orders(self):
        with self.assertRaises(ContractError):
            order_count({"page": {}})

    def test_every_declared_report_handler_loads(self):
        registry = Registry()
        reports = [r for p in registry.platforms.values() for r in p.reports]
        self.assertEqual(len(reports), 22)
        self.assertTrue(all(callable(load_symbol(r.handler)) for r in reports))

    def test_qianchuan_is_a_dispatch_alias_of_the_same_cli(self):
        args = build_parser(Registry()).parse_args(["qianchuan", "report", "download", "--profile", "Example"])
        self.assertEqual((args.platform_id, args.backend, args.kind), ("douyin", "qianchuan", "promotion"))

    def test_business_modules_cannot_import_browser_or_legacy_dom_downloaders(self):
        errors = []
        for path in (PROJECT / "platforms").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
                for name in names:
                    if name.startswith(("playwright", "selenium", "scripts.auto_download.playwright", "ReverseAPI")):
                        errors.append(str(path.relative_to(PROJECT)))
        self.assertEqual(errors, [])
