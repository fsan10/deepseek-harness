from __future__ import annotations

import unittest

from apps.automation_center.registry import COMPONENT_REGISTRY
from apps.automation_center.service import AutomationService


class FlowValidationTests(unittest.TestCase):
    def test_default_upload_follows_last_archive_and_precedes_stop(self):
        definition = {'nodes':[
            {'id':'first','component_code':'report.archive'},
            {'id':'last','component_code':'report.archive'},
            {'id':'stop','component_code':'cloak.profile.stop'},
        ],'edges':[{'source':'first','target':'last'},{'source':'last','target':'stop'}]}
        normalized = AutomationService._ensure_optional_downstream_nodes(definition)
        validated = AutomationService._validate_flow_definition(normalized, allow_draft_custom=False)
        edges = {(edge['source'],edge['target']) for edge in validated['edges']}
        self.assertEqual({('first','last'),('last','downstream_ingest'),('downstream_ingest','downstream_etl'),('downstream_etl','stop')},edges)
        downstream = [node for node in validated['nodes'] if node['component_code'] in {'ingest.submit','etl.trigger'}]
        self.assertTrue(all(node['enabled'] for node in downstream))
        self.assertEqual([{'source':'first','target':'last'},{'source':'last','target':'stop'}],definition['edges'])

    def test_registered_component_is_publishable(self) -> None:
        definition = AutomationService._validate_flow_definition(
            {
                "nodes": [
                    {
                        "id": "start",
                        "component_code": "jd.ensure_login",
                        "name": "检查登录",
                        "config": {},
                    }
                ],
                "edges": [],
            },
            allow_draft_custom=False,
        )
        self.assertEqual("jd.ensure_login", definition["nodes"][0]["component_code"])

    def test_custom_component_allowed_only_in_draft(self) -> None:
        draft = {
            "nodes": [
                {
                    "id": "custom",
                    "component_code": "custom.business.confirm",
                    "config": {},
                }
            ],
            "edges": [],
        }
        normalized = AutomationService._validate_flow_definition(
            draft, allow_draft_custom=True
        )
        self.assertEqual("custom.business.confirm", normalized["nodes"][0]["component_code"])
        with self.assertRaisesRegex(ValueError, "组件未注册"):
            AutomationService._validate_flow_definition(
                draft, allow_draft_custom=False
            )

    def test_arbitrary_command_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "禁止"):
            AutomationService._validate_flow_definition(
                {
                    "nodes": [
                        {
                            "id": "unsafe",
                            "component_code": "jd.ensure_login",
                            "config": {"command": "powershell.exe -Command whoami"},
                        }
                    ],
                    "edges": [],
                },
                allow_draft_custom=False,
            )

    def test_directional_connection_ports_are_preserved(self) -> None:
        definition = AutomationService._validate_flow_definition(
            {
                "nodes": [
                    {"id": "a", "component_code": "jd.ensure_login", "config": {}},
                    {"id": "b", "component_code": "jd.order.open_export", "config": {}},
                ],
                "edges": [
                    {
                        "source": "a",
                        "target": "b",
                        "source_port": "bottom",
                        "target_port": "top",
                    }
                ],
            },
            allow_draft_custom=False,
        )
        self.assertEqual("bottom", definition["edges"][0]["source_port"])
        self.assertEqual("top", definition["edges"][0]["target_port"])

    def test_invalid_directional_connection_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "端口"):
            AutomationService._validate_flow_definition(
                {
                    "nodes": [
                        {"id": "a", "component_code": "jd.ensure_login", "config": {}},
                        {"id": "b", "component_code": "jd.order.open_export", "config": {}},
                    ],
                    "edges": [
                        {
                            "source": "a",
                            "target": "b",
                            "source_port": "diagonal",
                            "target_port": "left",
                        }
                    ],
                },
                allow_draft_custom=False,
            )

    def test_xiaohongshu_flow_components_are_publishable(self) -> None:
        codes = (
            "xhs.order.open_home",
            "xhs.order.open_management",
            "xhs.order.set_date",
            "xhs.order.query",
            "xhs.order.export",
            "report.validate.schema",
            "report.archive",
            "xhs.report.open",
            "xhs.report.mode.select",
            "xhs.report.latest",
            "xhs.report.download",
        )
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(code, COMPONENT_REGISTRY)
                self.assertTrue(COMPONENT_REGISTRY[code].flow_executable)

    def test_xiaohongshu_fund_flow_definition_is_valid(self) -> None:
        definition = AutomationService._validate_flow_definition(
            {
                "nodes": [
                    {"id": "cloak", "component_code": "cloak.profile.start", "config": {}},
                    {"id": "cdp", "component_code": "browser.connect.cdp", "config": {}},
                    {"id": "open", "component_code": "xhs.report.open", "config": {"report_type": "fund"}},
                    {"id": "mode", "component_code": "xhs.report.mode.select", "config": {"mode": "day"}},
                    {"id": "latest", "component_code": "xhs.report.latest", "config": {}},
                    {"id": "download", "component_code": "xhs.report.download", "config": {}},
                    {"id": "validate", "component_code": "report.validate.schema", "config": {}},
                    {"id": "archive", "component_code": "report.archive", "config": {}},
                    {"id": "stop", "component_code": "cloak.profile.stop", "config": {}},
                ],
                "edges": [
                    {"source": "cloak", "target": "cdp"},
                    {"source": "cdp", "target": "open"},
                    {"source": "open", "target": "mode"},
                    {"source": "mode", "target": "latest"},
                    {"source": "latest", "target": "download"},
                    {"source": "download", "target": "validate"},
                    {"source": "validate", "target": "archive"},
                    {"source": "archive", "target": "stop"},
                ],
            },
            allow_draft_custom=False,
        )
        self.assertEqual(9, len(definition["nodes"]))
        self.assertEqual("fund", definition["nodes"][2]["config"]["report_type"])

    def test_platform_atomic_component_is_publishable(self) -> None:
        definition = AutomationService._validate_flow_definition(
            {
                "nodes": [
                    {"id": "open", "component_code": "douyin.order.open_page", "config": {}},
                    {"id": "query", "component_code": "douyin.order.query", "config": {}},
                    {"id": "export", "component_code": "douyin.order.create_export", "config": {}},
                ],
                "edges": [
                    {"source": "open", "target": "query"},
                    {"source": "query", "target": "export"},
                ],
            },
            allow_draft_custom=False,
        )
        self.assertEqual(3, len(definition["nodes"]))

    def test_invalid_edge_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "连线"):
            AutomationService._validate_flow_definition(
                {
                    "nodes": [
                        {
                            "id": "a",
                            "component_code": "jd.ensure_login",
                            "config": {},
                        }
                    ],
                    "edges": [{"source": "a", "target": "missing"}],
                },
                allow_draft_custom=False,
            )


if __name__ == "__main__":
    unittest.main()
