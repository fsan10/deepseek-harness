"""Validate target catalog fidelity, emptiness and source non-mutation."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE_BEFORE = ROOT / "docs/production_database/mock_coffice_catalog.json"
SOURCE_AFTER = ROOT / "docs/production_database/mock_coffice_catalog_after.json"
TARGET = ROOT / "docs/production_database/coffice_production_catalog.json"
MANIFEST = ROOT / "scripts/production_db/generated/migration_manifest.json"
OUTPUT = ROOT / "docs/production_database/validation_catalog_report.json"

SEEDED_TABLES = {
    "dim.dim_platform_shop_company",
    "dim.dim_expense_type",
    "dim.dim_account_entry",
    "dim.dim_account_entry_expense_type",
    "dim.dim_platform_fee_mapping",
    "dim.dim_platform_fee_primary_category",
    "dim.dim_business_owner",
    "dim.dim_influencer_business_assignment_monthly",
    "dim.dim_business_gmv_target_monthly",
    "dim.dim_influencer_product_category",
    "dim.dim_influencer_product",
    "dim.dim_company_product_code_mapping",
}

# A running production worker legitimately maintains these rows after the
# initial empty-database verification.  They are reported separately and are
# never treated as seed or business data.
ALLOWED_RUNTIME_TABLES = {
    "ops.worker_heartbeat",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="比较源库快照、目标库结构和空表状态")
    parser.add_argument("--source-before", type=Path, default=SOURCE_BEFORE)
    parser.add_argument("--source-after", type=Path, default=SOURCE_AFTER)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser


def relation_names(catalog: dict[str, Any], kinds: set[str]) -> set[str]:
    return {
        f'{item["schema_name"]}.{item["relation_name"]}'
        for item in catalog["relations"] if item["relation_type"] in kinds
    }


def filtered(items: list[dict[str, Any]], included: set[str]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        relation = f'{item["schema_name"]}.{item["relation_name"]}'
        if relation in included:
            result.append(item)
    return result


def canonical_columns(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in filtered(catalog["columns"], included):
        grouped[f'{item["schema_name"]}.{item["relation_name"]}'].append(item)
    result = []
    for relation_name, items in grouped.items():
        schema, relation = relation_name.split(".", 1)
        for visible_position, item in enumerate(sorted(items, key=lambda row: row["ordinal_position"]), 1):
            result.append(
                (
                    schema, relation, visible_position, item["column_name"], item["data_type"],
                    item["not_null"], item.get("column_default"), item.get("identity_kind"),
                    item.get("generated_kind"), item.get("comment"),
                )
            )
    return sorted(result)


def normalize_constraint_definition(value: str) -> str:
    # PostgreSQL 18 reparses varchar ANY-array checks into an equivalent form
    # with per-element ::text casts. Compare the logical expression instead of
    # pg_get_constraintdef's formatting choice.
    value = value.replace("::character varying::text", "::character varying")
    value = value.replace("::text[]", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def canonical_constraints(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["relation_name"], item["constraint_name"],
            item["constraint_type"], normalize_constraint_definition(item["definition"]), item.get("referenced_schema"),
            item.get("referenced_relation"), item["deferrable"], item["initially_deferred"],
            item["validated"],
        )
        for item in filtered(catalog["constraints"], included)
        if item["constraint_type"] != "n"
    )


def canonical_indexes(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["relation_name"], item["index_name"],
            item["definition"], item.get("backing_constraint_name"),
        )
        for item in filtered(catalog["indexes"], included)
    )


def canonical_views(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["relation_name"], item["relation_kind"],
            re.sub(r"\s+", " ", item["definition"]).strip(),
        )
        for item in catalog["views"]
        if f'{item["schema_name"]}.{item["relation_name"]}' in included
    )


def canonical_functions(catalog: dict[str, Any]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["function_name"], item["identity_arguments"],
            item["language"], item["result_type"], re.sub(r"\s+", " ", item["definition"]).strip(),
        )
        for item in catalog["functions"]
    )


def canonical_triggers(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["relation_name"], item["trigger_name"],
            re.sub(r"\s+", " ", item["definition"]).strip(), item["enabled"],
        )
        for item in catalog["triggers"]
        if f'{item["schema_name"]}.{item["relation_name"]}' in included
    )


def canonical_sequences(catalog: dict[str, Any], included: set[str]) -> list[tuple]:
    return sorted(
        (
            item["schema_name"], item["sequence_name"], item["data_type"],
            item["start_value"], item["min_value"], item["max_value"],
            item["increment_by"], item["cache_size"], item["cycle"],
            item.get("owned_by_schema"), item.get("owned_by_relation"),
            item.get("owned_by_column"), item.get("ownership_type"),
        )
        for item in catalog["sequences"]
        if f'{item["schema_name"]}.{item["sequence_name"]}' in included
    )


def main() -> None:
    args = build_parser().parse_args()
    source_before = json.loads(args.source_before.read_text(encoding="utf-8"))
    source_after = json.loads(args.source_after.read_text(encoding="utf-8"))
    target = json.loads(args.target.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    included_tables = set(manifest["included_tables"])
    included_views = set(manifest["included_views"])
    included_relations = included_tables | included_views
    included_sequences = set(manifest["included_sequences"])

    target_tables = relation_names(target, {"table", "partitioned_table"})
    target_views = relation_names(target, {"view", "materialized_view"})
    unexpected_nonempty = {
        name: count for name, count in target["exact_row_counts"].items()
        if name not in SEEDED_TABLES
        and name not in ALLOWED_RUNTIME_TABLES
        and count != 0
    }
    seeded_counts = {
        name: target["exact_row_counts"].get(name, 0) for name in sorted(SEEDED_TABLES)
    }
    runtime_counts = {
        name: target["exact_row_counts"].get(name, 0)
        for name in sorted(ALLOWED_RUNTIME_TABLES)
    }
    checks = {
        "source_catalog_unchanged": source_before["catalog_sha256"] == source_after["catalog_sha256"],
        "table_set_matches": target_tables == included_tables,
        "view_set_matches": target_views == included_views,
        "excluded_tables_absent": not set(manifest["excluded_tables"]).intersection(target_tables),
        "non_config_tables_empty": not unexpected_nonempty,
        "seed_tables_initialized": all(count > 0 for count in seeded_counts.values()),
        "columns_match": canonical_columns(source_before, included_relations) == canonical_columns(target, included_relations),
        "constraints_match": canonical_constraints(source_before, included_tables) == canonical_constraints(target, included_tables),
        "indexes_match": canonical_indexes(source_before, included_tables) == canonical_indexes(target, included_tables),
        "views_match": canonical_views(source_before, included_views) == canonical_views(target, included_views),
        "functions_match": canonical_functions(source_before) == canonical_functions(target),
        "triggers_match": canonical_triggers(source_before, included_tables) == canonical_triggers(target, included_tables),
        "sequences_match": canonical_sequences(source_before, included_sequences) == canonical_sequences(target, included_sequences),
    }
    report = {
        "status": "success" if all(checks.values()) else "failed",
        "checks": checks,
        "expected_table_count": len(included_tables),
        "actual_table_count": len(target_tables),
        "expected_view_count": len(included_views),
        "actual_view_count": len(target_views),
        "seeded_table_counts": seeded_counts,
        "allowed_runtime_table_counts": runtime_counts,
        "unexpected_nonempty_tables": unexpected_nonempty,
        "missing_tables": sorted(included_tables - target_tables),
        "extra_tables": sorted(target_tables - included_tables),
        "missing_views": sorted(included_views - target_views),
        "extra_views": sorted(target_views - included_views),
        "source_before_sha256": source_before["catalog_sha256"],
        "source_after_sha256": source_after["catalog_sha256"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
