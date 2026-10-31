from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SQL_PATH = ROOT / "sql" / "common" / "430_automation_center_postgres.sql"
REGISTRY_PATH = ROOT / "apps" / "automation_center" / "registry.py"
SERVICE_PATH = ROOT / "apps" / "automation_center" / "service.py"


class AtomicFlowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = SQL_PATH.read_text(encoding="utf-8")
        cls.registry = REGISTRY_PATH.read_text(encoding="utf-8")
        cls.service = SERVICE_PATH.read_text(encoding="utf-8")

    def test_downstream_migration_uses_valid_postgres_do_block(self) -> None:
        marker = "DECLARE\n    rec RECORD;"
        index = self.sql.index(marker)
        prefix = self.sql[max(0, index - 16):index]
        self.assertIn("DO $$", prefix)
        tail = self.sql[index:self.sql.index("COMMENT ON TABLE ops.automation_job", index)]
        self.assertIn("END $$;", tail)
        self.assertNotIn("DO $\nDECLARE", self.sql)
        self.assertNotIn("END $;\n\nCOMMENT ON TABLE ops.automation_job", self.sql)

    def test_every_flow_gets_optional_api_and_etl_nodes(self) -> None:
        # Existing flows are upgraded in-place; new atomic seed flows already
        # include these nodes. Both downstream actions default to enabled.
        self.assertIn("WHERE node->>'component_code'='ingest.submit'", self.sql)
        self.assertIn("WHERE node->>'component_code'='etl.trigger'", self.sql)
        self.assertRegex(
            self.sql,
            r"'component_code',\s*'ingest\.submit'[\s\S]{0,500}'enabled',\s*true",
        )
        self.assertRegex(
            self.sql,
            r"'component_code',\s*'etl\.trigger'[\s\S]{0,500}'enabled',\s*true",
        )
        self.assertIn("'source', ingest_id, 'target', etl_id", self.sql)
        self.assertIn("'source', etl_id, 'target', stop_id", self.sql)

    def test_flow_service_auto_adds_enabled_downstream_nodes(self) -> None:
        self.assertIn("def _ensure_optional_downstream_nodes", self.service)
        self.assertIn('"component_code": "ingest.submit"', self.service)
        self.assertIn('"component_code": "etl.trigger"', self.service)
        self.assertIn('"enabled": True', self.service)
        self.assertIn("self._ensure_optional_downstream_nodes(", self.service)
        self.assertGreaterEqual(
            self.service.count("self._ensure_optional_downstream_nodes("),
            3,
        )

    def test_atomic_seed_flows_do_not_use_monolithic_workflow_nodes(self) -> None:
        component_codes = set(
            re.findall(r'"component_code"\s*:\s*"([^"]+)"', self.sql)
        )
        monolithic = sorted(code for code in component_codes if code.endswith(".workflow"))
        self.assertEqual([], monolithic)

    def test_component_palette_does_not_register_monolithic_workflow_nodes(self) -> None:
        registered = set(
            re.findall(
                r'^\s*"([^"]+)":\s*AutomationComponentSpec\(',
                self.registry,
                flags=re.MULTILINE,
            )
        )
        monolithic = sorted(code for code in registered if code.endswith(".workflow"))
        self.assertEqual([], monolithic)

    def test_atomic_reference_flows_have_enabled_downstream_nodes(self) -> None:
        atomic_defs = re.findall(
            r"'([a-z0-9_.]+\.atomic\.reference)'[\s\S]*?'(\{\"variables\":\{\}[\s\S]*?\})'::jsonb",
            self.sql,
        )
        self.assertGreaterEqual(len(atomic_defs), 17)
        for code, definition in atomic_defs:
            with self.subTest(flow=code):
                self.assertIn(
                    '"component_code":"ingest.submit"',
                    definition,
                )
                self.assertIn(
                    '"component_code":"etl.trigger"',
                    definition,
                )
                ingest = definition.index('"component_code":"ingest.submit"')
                etl = definition.index('"component_code":"etl.trigger"')
                self.assertIn('"enabled":true', definition[ingest:ingest + 260])
                self.assertIn('"enabled":true', definition[etl:etl + 260])


if __name__ == "__main__":
    unittest.main()
