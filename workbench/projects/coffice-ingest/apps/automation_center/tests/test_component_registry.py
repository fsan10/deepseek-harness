from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry.py"
SPEC = importlib.util.spec_from_file_location("automation_component_registry_standalone", REGISTRY_PATH)
assert SPEC is not None and SPEC.loader is not None
REGISTRY_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REGISTRY_MODULE
SPEC.loader.exec_module(REGISTRY_MODULE)
COMPONENT_REGISTRY = REGISTRY_MODULE.COMPONENT_REGISTRY


MONOLITHIC_FLOW_CODES = {
    "douyin.order.workflow",
    "douyin.bill.workflow",
    "qianchuan.promotion.workflow",
    "jd.order.workflow",
    "jd.settlement.workflow",
    "jd.fund.workflow",
    "jd.promotion.workflow",
    "pinduoduo.order.workflow",
    "pinduoduo.settlement.workflow",
    "pinduoduo.promotion.workflow",
    "kuaishou.order.workflow",
    "kuaishou.fund.workflow",
    "kuaishou.settlement.workflow",
    "tmall.order.workflow",
    "tmall.aggregate_fund.workflow",
    "tmall.alipay.workflow",
    "tmall.union.workflow",
    "tmall.wanxiangtai.workflow",
}


ATOMIC_PLATFORM_CODES = {
    # Douyin / Qianchuan
    "douyin.order.open_page",
    "douyin.order.prepare_filters",
    "douyin.order.query",
    "douyin.order.create_export",
    "douyin.order.wait_ready",
    "douyin.order.download_verify",
    "douyin.order.extract",
    "douyin.bill.open",
    "douyin.bill.generate",
    "douyin.bill.wait_ready",
    "douyin.bill.download",
    "qianchuan.finance.open",
    "qianchuan.daily.open",
    "qianchuan.daily.wait",
    "qianchuan.daily.materialize",
    # JD
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
    # PDD
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
    "pinduoduo.promotion.apply_filters",
    "pinduoduo.promotion.query",
    "pinduoduo.promotion.download",
    # Kuaishou
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
    # Tmall
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
}


class ComponentRegistryTests(unittest.TestCase):
    def test_component_palette_contains_only_executable_components(self) -> None:
        palette = REGISTRY_MODULE.component_registry_payload()
        self.assertTrue(palette)
        self.assertTrue(all(item["flow_executable"] for item in palette))

    def test_component_palette_has_one_standard_archive_and_validation(self) -> None:
        codes = [item["code"] for item in REGISTRY_MODULE.component_registry_payload()]
        archive_codes = [code for code in codes if code.endswith(".archive") or code == "report.archive"]
        validation_codes = [code for code in codes if code.endswith(".validate") or code == "report.validate.schema"]
        self.assertEqual(["report.archive"], archive_codes)
        self.assertEqual(["report.validate.schema"], validation_codes)

    def test_downstream_actions_are_explicit_executable_nodes(self) -> None:
        for code in ("ingest.submit", "etl.trigger"):
            with self.subTest(code=code):
                self.assertIn(code, COMPONENT_REGISTRY)
                self.assertTrue(COMPONENT_REGISTRY[code].flow_executable)

    def test_monolithic_workflow_nodes_are_not_registered(self) -> None:
        self.assertFalse(MONOLITHIC_FLOW_CODES.intersection(COMPONENT_REGISTRY))

    def test_all_platform_atomic_components_are_executable(self) -> None:
        missing = sorted(ATOMIC_PLATFORM_CODES.difference(COMPONENT_REGISTRY))
        self.assertEqual([], missing)
        non_executable = sorted(
            code for code in ATOMIC_PLATFORM_CODES
            if not COMPONENT_REGISTRY[code].flow_executable
        )
        self.assertEqual([], non_executable)

    def test_xiaohongshu_atomic_components_remain_executable(self) -> None:
        for code in (
            "xhs.order.open_home",
            "xhs.order.open_management",
            "xhs.order.set_date",
            "xhs.order.query",
            "xhs.order.export",
            "xhs.report.open",
            "xhs.report.mode.select",
            "xhs.report.latest",
            "xhs.report.download",
        ):
            with self.subTest(code=code):
                self.assertTrue(COMPONENT_REGISTRY[code].flow_executable)


if __name__ == "__main__":
    unittest.main()
