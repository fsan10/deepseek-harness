"""Cross-reference PostgreSQL catalog objects with active project code and SQL.

This is a static, read-only analyzer.  It deliberately separates runtime code
references from table-definition SQL so that a table is not considered active
merely because an old CREATE TABLE file still exists on disk.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DEFAULT = PROJECT_ROOT / "docs/production_database/mock_coffice_catalog.json"
OUTPUT_DEFAULT = PROJECT_ROOT / "docs/production_database/dependency_analysis.json"
TEXT_SUFFIXES = {".py", ".js", ".html", ".sql", ".ps1", ".md"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="交叉分析代码、SQL 与数据库对象引用")
    parser.add_argument("--catalog", type=Path, default=CATALOG_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    return parser


def load_registry():
    path = PROJECT_ROOT / "apps/file_ingest/registry.py"
    spec = importlib.util.spec_from_file_location("production_audit_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载注册表：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def iter_project_text_files() -> Iterable[Path]:
    for base_name in ("apps", "etl", "sql", "scripts", "docs"):
        base = PROJECT_ROOT / base_name
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def path_key(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def python_sql_literals(path: Path) -> set[Path]:
    result: set[Path] = set()
    try:
        tree = ast.parse(read_text(path), filename=str(path))
    except SyntaxError:
        return result
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.replace("\\", "/")
        if not value.lower().endswith(".sql"):
            continue
        candidates = [PROJECT_ROOT / value, PROJECT_ROOT / "sql" / value, path.parent / value]
        parts = Path(value).parts
        if "sql" in parts:
            candidates.append(PROJECT_ROOT / Path(*parts[parts.index("sql") :]))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file() and PROJECT_ROOT in resolved.parents:
                result.add(resolved)
                break
    return result


QUALIFIED_OBJECT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(ods|dwd|dws|dim|ads|ops|fund|common|iam|config|ai|public)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def main() -> None:
    args = build_parser().parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    registry = load_registry()

    relations = {
        f'{item["schema_name"]}.{item["relation_name"]}': item
        for item in catalog["relations"]
        if item["relation_type"] in {"table", "partitioned_table", "view", "materialized_view"}
    }

    active_runtime_files: set[Path] = set()
    for item in registry.ACTIVE_REPORTS:
        active_runtime_files.add((PROJECT_ROOT / item.loader).resolve())
    for item in registry.ETL_SPECS.values():
        if item.enabled:
            active_runtime_files.add((PROJECT_ROOT / item.script).resolve())

    # Web/API/config-center runtime. Tests, vendored wheels and frontend build
    # dependencies are kept out of active Python evidence.
    for path in (PROJECT_ROOT / "apps").rglob("*.py"):
        if (
            "tests" not in path.parts
            and ".vendor" not in path.parts
            and "node_modules" not in path.parts
            and not path.name.startswith("test_")
        ):
            active_runtime_files.add(path.resolve())
    for path in (PROJECT_ROOT / "etl/common").rglob("*.py"):
        active_runtime_files.add(path.resolve())

    active_sql_files: set[Path] = set()
    for path in active_runtime_files:
        if path.is_file() and path.suffix.lower() == ".py":
            active_sql_files.update(python_sql_literals(path))

    all_files = list(iter_project_text_files())
    runtime_references: dict[str, list[str]] = defaultdict(list)
    active_sql_references: dict[str, list[str]] = defaultdict(list)
    test_references: dict[str, list[str]] = defaultdict(list)
    other_sql_references: dict[str, list[str]] = defaultdict(list)
    documentation_references: dict[str, list[str]] = defaultdict(list)

    active_runtime_keys = {path_key(p) for p in active_runtime_files if p.is_file()}
    active_sql_keys = {path_key(p) for p in active_sql_files if p.is_file()}

    for path in all_files:
        key = path_key(path)
        if key.startswith("docs/production_database/"):
            continue
        text = read_text(path)
        is_test = "tests" in path.parts or path.name.startswith("test_") or "smoke_test" in path.name
        referenced_names = {
            f"{match.group(1).lower()}.{match.group(2).lower()}"
            for match in QUALIFIED_OBJECT_PATTERN.finditer(text)
        }.intersection(relations)
        for relation_name in referenced_names:
            if key in active_runtime_keys:
                runtime_references[relation_name].append(key)
            elif key in active_sql_keys:
                active_sql_references[relation_name].append(key)
            elif is_test:
                test_references[relation_name].append(key)
            elif path.suffix.lower() == ".sql":
                other_sql_references[relation_name].append(key)
            elif path.suffix.lower() == ".md":
                documentation_references[relation_name].append(key)

    active_targets = {item.target_table for item in registry.ACTIVE_REPORTS}
    explicitly_deprecated = {
        "ods.ods_tmall_fund_raw": "注册表明确停用的旧天猫通用资金 Loader；现用支付宝和聚合账户资金。",
        "ods.ods_tmall_order_raw_legacy_20260728_164401": "天猫订单粒度迁移时生成的带时间戳历史备份表。",
        "ads.ads_influencer_commission_company_platform_daily": "旧版独立达人佣金 ADS；注册表 ETL 已 enabled=False。",
    }
    for name in relations:
        if name.startswith("dwd.dwd_") and "influencer_commission" in name and "bank_" not in name:
            explicitly_deprecated[name] = "旧版独立达人佣金 DWD；当前看板改用统一平台费用 ADS。"
        if name.startswith("dws.dws_") and "influencer_commission" in name and "bank_" not in name:
            explicitly_deprecated[name] = "旧版独立达人佣金 DWS；当前看板改用统一平台费用 ADS。"

    view_dependencies = defaultdict(list)
    for item in catalog.get("view_dependencies", []):
        view_name = f'{item["view_schema"]}.{item["view_name"]}'
        ref_name = f'{item["referenced_schema"]}.{item["referenced_relation"]}'
        view_dependencies[view_name].append(ref_name)

    fk_dependencies = defaultdict(list)
    for item in catalog.get("constraints", []):
        if item["constraint_type"] != "f" or not item.get("referenced_relation"):
            continue
        source = f'{item["schema_name"]}.{item["relation_name"]}'
        target = f'{item["referenced_schema"]}.{item["referenced_relation"]}'
        fk_dependencies[source].append(target)

    rows = []
    for name, relation in sorted(relations.items()):
        active_evidence = sorted(
            set(runtime_references[name])
            | set(active_sql_references[name])
            | ({"apps/file_ingest/registry.py:target_table"} if name in active_targets else set())
        )
        deprecated_reason = explicitly_deprecated.get(name)
        if active_evidence:
            classification = "required"
            # Conflicts must be reviewed instead of silently excluding an actively referenced object.
            if deprecated_reason:
                classification = "review_conflict"
        elif deprecated_reason:
            classification = "deprecated"
        else:
            classification = "uncertain"
        rows.append(
            {
                "relation": name,
                "relation_type": relation["relation_type"],
                "estimated_rows": relation.get("estimated_rows"),
                "exact_rows": catalog.get("exact_row_counts", {}).get(name),
                "classification": classification,
                "active_evidence": active_evidence,
                "runtime_references": sorted(set(runtime_references[name])),
                "active_sql_references": sorted(set(active_sql_references[name])),
                "test_references": sorted(set(test_references[name])),
                "other_sql_references": sorted(set(other_sql_references[name])),
                "documentation_references": sorted(set(documentation_references[name])),
                "deprecated_reason": deprecated_reason,
                "foreign_key_dependencies": sorted(set(fk_dependencies[name])),
                "view_dependencies": sorted(set(view_dependencies[name])),
            }
        )

    output = {
        "source_database": catalog.get("server", {}).get("database_name"),
        "source_catalog_sha256": catalog.get("catalog_sha256"),
        "active_report_count": len(registry.ACTIVE_REPORTS),
        "active_etl_keys": sorted(key for key, item in registry.ETL_SPECS.items() if item.enabled),
        "disabled_etl_keys": sorted(key for key, item in registry.ETL_SPECS.items() if not item.enabled),
        "deprecated_loaders": registry.DEPRECATED_LOADERS,
        "active_runtime_files": sorted(active_runtime_keys),
        "active_sql_files": sorted(active_sql_keys),
        "relations": rows,
        "foreign_key_dependencies": dict(sorted(fk_dependencies.items())),
        "view_dependencies": dict(sorted(view_dependencies.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = defaultdict(int)
    for row in rows:
        counts[row["classification"]] += 1
    print(json.dumps({"classification_counts": dict(counts), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
