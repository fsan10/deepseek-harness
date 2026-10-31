"""Generate an idempotent, data-free PostgreSQL schema migration from catalog JSON."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "docs/production_database/mock_coffice_catalog.json"
ANALYSIS_PATH = ROOT / "docs/production_database/dependency_analysis.json"
OUTPUT_PATH = ROOT / "scripts/production_db/generated/001_schema.sql"
MANIFEST_PATH = ROOT / "scripts/production_db/generated/migration_manifest.json"
TMALL_ORDER_TABLE = "ods.ods_tmall_order_raw"
TMALL_ORDER_STAGE_TABLE = "ods.ods_tmall_order_raw_next"
WECHAT_CHANNELS_ORDER_TABLE = "ods.ods_wechat_channels_order_raw"
SUPERSEDED_INDEXES = {
    # 393 replaces the historical global product-id uniqueness rule with
    # platform/shop/source-code scoped indexes.  Re-emitting this old unique
    # index makes a second bootstrap fail after the approved seed contains
    # multiple platform codes for one company product.
    "dim.uq_company_product_mapping_product_id",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从只读 catalog 和依赖分析生成无业务数据结构迁移")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--analysis", type=Path, default=ANALYSIS_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    return parser


def qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def ql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def qualified(schema: str, name: str) -> str:
    return f"{qi(schema)}.{qi(name)}"


def step(step_id: str, sql: str) -> str:
    return f"-- migration-step: {step_id}\n{sql.rstrip()}\n"


def create_index_if_not_exists(definition: str) -> str:
    if definition.startswith("CREATE UNIQUE INDEX "):
        return definition.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1) + ";"
    if definition.startswith("CREATE INDEX "):
        return definition.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1) + ";"
    raise ValueError(f"无法处理索引定义：{definition}")


def normalize_known_catalog_metadata(catalog: dict, included_tables: set[str]) -> list[str]:
    """Repair metadata left behind by the one-time Tmall table cutover.

    The test database currently contains the new item-grain table under the
    canonical relation name, but PostgreSQL object names were not renamed when
    the temporary ``*_next`` table was cut over.  The catalog is deliberately
    kept as a read-only source snapshot; this function only normalizes the
    deployment SQL generated from that snapshot.  The temporary table itself
    remains an explicit, opt-in migration (297) and is not part of the normal
    empty production bootstrap.
    """
    if TMALL_ORDER_TABLE not in included_tables:
        return []

    notes: list[str] = []

    # Point the canonical table at its canonical sequence.  The source
    # sequence is present in the catalog but still owned by the archived
    # legacy table; ownership is corrected below so the generated schema can
    # create and own the sequence without copying the archive.
    for column in catalog["columns"]:
        if (
            f'{column["schema_name"]}.{column["relation_name"]}' == TMALL_ORDER_TABLE
            and column["column_name"] == "id"
        ):
            column["column_default"] = (
                "nextval('ods.ods_tmall_order_raw_id_seq'::regclass)"
            )
            notes.append("canonicalized ods.ods_tmall_order_raw.id sequence")
            break

    for sequence in catalog["sequences"]:
        qualified_name = f'{sequence["schema_name"]}.{sequence["sequence_name"]}'
        if qualified_name == "ods.ods_tmall_order_raw_id_seq":
            sequence["owned_by_schema"] = "ods"
            sequence["owned_by_relation"] = "ods_tmall_order_raw"
            sequence["owned_by_column"] = "id"
            sequence["ownership_type"] = "a"
        elif (
            qualified_name == "ods.ods_tmall_order_raw_next_id_seq"
            and TMALL_ORDER_STAGE_TABLE not in included_tables
        ):
            # This sequence belongs only to the opt-in temporary stage table.
            # Leaving it in a canonical empty bootstrap would make the main
            # table depend on an object that should not exist there.
            sequence["_exclude_from_deploy"] = True
            notes.append("excluded temporary ods_tmall_order_raw_next sequence")

    constraint_names = {
        "ods_tmall_order_raw_next_pkey": "ods_tmall_order_raw_pkey",
        "uk_ods_tmall_order_raw_next_row_hash": "uk_ods_tmall_order_row_hash",
    }
    for constraint in catalog["constraints"]:
        table_name = f'{constraint["schema_name"]}.{constraint["relation_name"]}'
        if table_name == TMALL_ORDER_TABLE:
            old_name = constraint["constraint_name"]
            if old_name in constraint_names:
                constraint["constraint_name"] = constraint_names[old_name]
                notes.append(f"renamed canonical Tmall constraint {old_name}")

    # Normalize ordinary indexes and drop duplicate *_next metadata.  The
    # source catalog has canonical main/sub-order indexes plus stale *_next
    # copies; batch/source-file indexes exist only under the stale names.
    index_names = {
        "idx_ods_tmall_order_raw_next_batch_id": "idx_ods_tmall_order_batch_id",
        "idx_ods_tmall_order_raw_next_main_order_no": "idx_ods_tmall_order_main_order_no",
        "idx_ods_tmall_order_raw_next_source_file": "idx_ods_tmall_order_source_file",
        "idx_ods_tmall_order_raw_next_sub_order_no": "idx_ods_tmall_order_sub_order_no",
        "ods_tmall_order_raw_next_pkey": "ods_tmall_order_raw_pkey",
        "uk_ods_tmall_order_raw_next_row_hash": "uk_ods_tmall_order_row_hash",
    }
    normalized_indexes: list[dict] = []
    seen_tmall_index_names: set[str] = set()
    for index in catalog["indexes"]:
        table_name = f'{index["schema_name"]}.{index["relation_name"]}'
        if f'{index["schema_name"]}.{index["index_name"]}' in SUPERSEDED_INDEXES:
            continue
        if table_name != TMALL_ORDER_TABLE:
            normalized_indexes.append(index)
            continue
        old_name = index["index_name"]
        new_name = index_names.get(old_name, old_name)
        index = {**index, "index_name": new_name}
        if index.get("backing_constraint_name"):
            index["backing_constraint_name"] = constraint_names.get(
                index["backing_constraint_name"], index["backing_constraint_name"]
            )
        definition = index.get("definition") or ""
        if old_name != new_name:
            definition = re.sub(
                rf"(?i)(CREATE(?: UNIQUE)? INDEX ){re.escape(old_name)}( ON )",
                rf"\g<1>{new_name}\g<2>",
                definition,
            )
        index["definition"] = definition
        if new_name in seen_tmall_index_names:
            continue
        seen_tmall_index_names.add(new_name)
        normalized_indexes.append(index)
    catalog["indexes"] = normalized_indexes
    notes.append("normalized canonical Tmall order index names and duplicates")
    return notes


def normalize_wechat_channels_order_discount_columns(
    catalog: dict, included_tables: set[str]
) -> list[str]:
    """Keep the generated bootstrap aligned with the current Video Account export.

    The read-only catalog predates the platform's split of the old ``商品优惠``
    source header into ``商家优惠`` and ``平台优惠``.  Normalize only the
    generated deployment artifact; the source catalog remains unchanged.
    """
    if WECHAT_CHANNELS_ORDER_TABLE not in included_tables:
        return []

    table_columns = [
        column
        for column in catalog["columns"]
        if f'{column["schema_name"]}.{column["relation_name"]}' == WECHAT_CHANNELS_ORDER_TABLE
    ]
    legacy = next(
        (column for column in table_columns if column["column_name"] == "商品优惠"),
        None,
    )
    merchant = next(
        (column for column in table_columns if column["column_name"] == "商家优惠"),
        None,
    )
    platform = next(
        (column for column in table_columns if column["column_name"] == "平台优惠"),
        None,
    )
    if legacy is not None and merchant is not None:
        raise RuntimeError(
            "视频号订单ODS结构快照同时包含旧字段“商品优惠”和新字段“商家优惠”"
        )
    if legacy is None and merchant is None:
        raise RuntimeError("视频号订单ODS结构快照缺少“商品优惠”或“商家优惠”字段")

    notes: list[str] = []
    merchant_comment = (
        "来源文件字段“商家优惠”，保留平台导出的原始值；"
        "旧版“商品优惠”表头由Loader兼容映射到本列。"
    )
    platform_comment = (
        "来源文件字段“平台优惠”，保留平台导出的原始值；"
        "旧版未拆分文件为空。"
    )
    if legacy is not None:
        legacy["column_name"] = "商家优惠"
        legacy["comment"] = merchant_comment
        merchant = legacy
        notes.append("renamed Video Account ODS 商品优惠 to 商家优惠")
    else:
        merchant["comment"] = merchant_comment

    if platform is None:
        merchant_position = merchant["ordinal_position"]
        for column in table_columns:
            if (
                column is not merchant
                and column["ordinal_position"] > merchant_position
            ):
                column["ordinal_position"] += 1
        platform = {
            **merchant,
            "ordinal_position": merchant_position + 1,
            "column_name": "平台优惠",
            "comment": platform_comment,
        }
        insert_at = catalog["columns"].index(merchant) + 1
        catalog["columns"].insert(insert_at, platform)
        notes.append("added Video Account ODS 平台优惠 column")
    else:
        platform["comment"] = platform_comment
    return notes


def main() -> None:
    args = build_parser().parse_args()
    args.catalog = args.catalog.resolve()
    args.analysis = args.analysis.resolve()
    args.output = args.output.resolve()
    args.manifest = args.manifest.resolve()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    included_rows = [row for row in analysis["relations"] if row["classification"] in {"required", "uncertain"}]
    included_tables = {
        row["relation"] for row in included_rows
        if row["relation_type"] in {"table", "partitioned_table"}
    }
    included_views = {
        row["relation"] for row in included_rows
        if row["relation_type"] in {"view", "materialized_view"}
    }
    excluded_tables = {
        row["relation"] for row in analysis["relations"]
        if row["classification"] == "deprecated"
    }
    normalization_notes = normalize_known_catalog_metadata(catalog, included_tables)
    normalization_notes.extend(
        normalize_wechat_channels_order_discount_columns(catalog, included_tables)
    )

    columns_by_table: dict[str, list[dict]] = defaultdict(list)
    for column in catalog["columns"]:
        name = f'{column["schema_name"]}.{column["relation_name"]}'
        if name in included_tables | included_views:
            columns_by_table[name].append(column)

    constraints_by_table: dict[str, list[dict]] = defaultdict(list)
    foreign_keys: list[dict] = []
    for constraint in catalog["constraints"]:
        source = f'{constraint["schema_name"]}.{constraint["relation_name"]}'
        if source not in included_tables:
            continue
        if constraint["constraint_type"] == "f":
            target = f'{constraint["referenced_schema"]}.{constraint["referenced_relation"]}'
            if target not in included_tables:
                raise RuntimeError(f"保留表外键指向被排除表：{source} -> {target}")
            foreign_keys.append(constraint)
        elif constraint["constraint_type"] in {"p", "u", "c", "x"}:
            constraints_by_table[source].append(constraint)
        # PostgreSQL 18 contype=n is represented by each column's NOT NULL flag.

    identity_columns = {
        (item["schema_name"], item["relation_name"], item["column_name"])
        for item in catalog["columns"] if item.get("identity_kind")
    }
    default_text = "\n".join(
        item.get("column_default") or ""
        for item in catalog["columns"]
        if f'{item["schema_name"]}.{item["relation_name"]}' in included_tables
    )
    selected_sequences = []
    for sequence in catalog["sequences"]:
        if sequence.get("_exclude_from_deploy"):
            continue
        owner = None
        if sequence.get("owned_by_relation"):
            owner = f'{sequence["owned_by_schema"]}.{sequence["owned_by_relation"]}'
        referenced = re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(sequence['schema_name'])}\.{re.escape(sequence['sequence_name'])}(?![A-Za-z0-9_])",
            default_text,
        ) is not None
        if owner not in included_tables and not referenced:
            continue
        identity_owned = (
            sequence.get("owned_by_schema"),
            sequence.get("owned_by_relation"),
            sequence.get("owned_by_column"),
        ) in identity_columns
        selected_sequences.append({**sequence, "identity_owned": identity_owned})

    relations_by_name = {
        f'{item["schema_name"]}.{item["relation_name"]}': item
        for item in catalog["relations"]
    }

    chunks: list[str] = [
        "-- Generated from a read-only mock_coffice catalog snapshot.\n"
        "-- Contains structure only: no source rows, sequence values or business data.\n"
        "-- The runner refuses to execute this file against mock_coffice.\n"
    ]
    schemas = sorted({name.split(".", 1)[0] for name in included_tables | included_views})
    for schema in schemas:
        chunks.append(step(f"schema:{schema}", f"CREATE SCHEMA IF NOT EXISTS {qi(schema)};"))

    for sequence in sorted(selected_sequences, key=lambda item: (item["schema_name"], item["sequence_name"])):
        if sequence["identity_owned"]:
            continue
        sql = (
            f"CREATE SEQUENCE IF NOT EXISTS {qualified(sequence['schema_name'], sequence['sequence_name'])}\n"
            f"    AS {sequence['data_type']}\n"
            f"    INCREMENT BY {sequence['increment_by']}\n"
            f"    MINVALUE {sequence['min_value']}\n"
            f"    MAXVALUE {sequence['max_value']}\n"
            f"    START WITH {sequence['start_value']}\n"
            f"    CACHE {sequence['cache_size']}\n"
            f"    {'CYCLE' if sequence['cycle'] else 'NO CYCLE'};"
        )
        chunks.append(step(f"sequence:{sequence['schema_name']}.{sequence['sequence_name']}", sql))

    for table_name in sorted(included_tables):
        schema, name = table_name.split(".", 1)
        definitions: list[str] = []
        for column in columns_by_table[table_name]:
            column_sql = f"{qi(column['column_name'])} {column['data_type']}"
            if column.get("generated_kind"):
                column_sql += f" GENERATED ALWAYS AS ({column['column_default']}) STORED"
            elif column.get("identity_kind"):
                generation = "ALWAYS" if column["identity_kind"] == "a" else "BY DEFAULT"
                column_sql += f" GENERATED {generation} AS IDENTITY"
            elif column.get("column_default") is not None:
                column_sql += f" DEFAULT {column['column_default']}"
            if column["not_null"]:
                column_sql += " NOT NULL"
            definitions.append(column_sql)
        for constraint in sorted(constraints_by_table[table_name], key=lambda item: item["constraint_name"]):
            definitions.append(
                f"CONSTRAINT {qi(constraint['constraint_name'])} {constraint['definition']}"
            )
        table_sql = (
            f"CREATE TABLE IF NOT EXISTS {qualified(schema, name)} (\n    "
            + ",\n    ".join(definitions)
            + "\n);"
        )
        chunks.append(step(f"table:{table_name}", table_sql))

    for sequence in sorted(selected_sequences, key=lambda item: (item["schema_name"], item["sequence_name"])):
        if sequence["identity_owned"] or not sequence.get("owned_by_relation"):
            continue
        sql = (
            f"ALTER SEQUENCE {qualified(sequence['schema_name'], sequence['sequence_name'])}\n"
            f"    OWNED BY {qualified(sequence['owned_by_schema'], sequence['owned_by_relation'])}.{qi(sequence['owned_by_column'])};"
        )
        chunks.append(step(f"sequence-owner:{sequence['schema_name']}.{sequence['sequence_name']}", sql))

    for constraint in sorted(
        foreign_keys,
        key=lambda item: (item["schema_name"], item["relation_name"], item["constraint_name"]),
    ):
        schema = constraint["schema_name"]
        table = constraint["relation_name"]
        name = constraint["constraint_name"]
        sql = f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE ns.nspname = {ql(schema)}
          AND cls.relname = {ql(table)}
          AND con.conname = {ql(name)}
    ) THEN
        ALTER TABLE {qualified(schema, table)}
            ADD CONSTRAINT {qi(name)} {constraint['definition']};
    END IF;
END
$$;"""
        chunks.append(step(f"foreign-key:{schema}.{table}.{name}", sql))

    for index in catalog["indexes"]:
        table_name = f'{index["schema_name"]}.{index["relation_name"]}'
        if table_name not in included_tables or index.get("backing_constraint_name"):
            continue
        chunks.append(
            step(
                f'index:{index["schema_name"]}.{index["index_name"]}',
                create_index_if_not_exists(index["definition"]),
            )
        )

    for function in catalog["functions"]:
        chunks.append(
            step(
                f'function:{function["schema_name"]}.{function["function_name"]}({function["identity_arguments"]})',
                function["definition"],
            )
        )

    for view in catalog["views"]:
        view_name = f'{view["schema_name"]}.{view["relation_name"]}'
        if view_name not in included_views:
            continue
        if view["relation_kind"] == "m":
            raise RuntimeError(f"暂不支持物化视图：{view_name}")
        sql = f"CREATE OR REPLACE VIEW {qualified(view['schema_name'], view['relation_name'])} AS\n{view['definition']};"
        chunks.append(step(f"view:{view_name}", sql))

    for trigger in catalog["triggers"]:
        table_name = f'{trigger["schema_name"]}.{trigger["relation_name"]}'
        if table_name not in included_tables:
            continue
        sql = (
            f"DROP TRIGGER IF EXISTS {qi(trigger['trigger_name'])} ON {qualified(trigger['schema_name'], trigger['relation_name'])};\n"
            f"{trigger['definition']};"
        )
        chunks.append(step(f"trigger:{table_name}.{trigger['trigger_name']}", sql))

    for table_name in sorted(included_tables):
        relation = relations_by_name[table_name]
        schema, name = table_name.split(".", 1)
        if relation.get("comment") is not None:
            chunks.append(
                step(f"table-comment:{table_name}", f"COMMENT ON TABLE {qualified(schema, name)} IS {ql(relation['comment'])};")
            )
        for column in columns_by_table[table_name]:
            if column.get("comment") is None:
                continue
            chunks.append(
                step(
                    f"column-comment:{table_name}.{column['column_name']}",
                    f"COMMENT ON COLUMN {qualified(schema, name)}.{qi(column['column_name'])} IS {ql(column['comment'])};",
                )
            )
    for view_name in sorted(included_views):
        relation = relations_by_name[view_name]
        schema, name = view_name.split(".", 1)
        if relation.get("comment") is not None:
            chunks.append(
                step(f"view-comment:{view_name}", f"COMMENT ON VIEW {qualified(schema, name)} IS {ql(relation['comment'])};")
            )
        for column in columns_by_table[view_name]:
            if column.get("comment") is None:
                continue
            chunks.append(
                step(
                    f"view-column-comment:{view_name}.{column['column_name']}",
                    f"COMMENT ON COLUMN {qualified(schema, name)}.{qi(column['column_name'])} IS {ql(column['comment'])};",
                )
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(chunks), encoding="utf-8")
    manifest = {
        "source_database": analysis.get("source_database", catalog["server"]["database_name"]),
        "source_catalog_sha256": analysis.get("source_catalog_sha256"),
        "structure_catalog_database": catalog["server"]["database_name"],
        "structure_catalog_sha256": catalog["catalog_sha256"],
        "target_database": "coffice_production",
        "included_tables": sorted(included_tables),
        "included_views": sorted(included_views),
        "excluded_tables": sorted(excluded_tables),
        "included_sequences": sorted(
            f'{item["schema_name"]}.{item["sequence_name"]}' for item in selected_sequences
        ),
        "included_functions": sorted(
            f'{item["schema_name"]}.{item["function_name"]}({item["identity_arguments"]})'
            for item in catalog["functions"]
        ),
        "included_triggers": sorted(
            f'{item["schema_name"]}.{item["relation_name"]}.{item["trigger_name"]}'
            for item in catalog["triggers"]
            if f'{item["schema_name"]}.{item["relation_name"]}' in included_tables
        ),
        "catalog_normalizations": normalization_notes,
        "superseded_indexes": sorted(SUPERSEDED_INDEXES),
        "schema_file": str(args.output.relative_to(ROOT)).replace("\\", "/"),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tables": len(included_tables), "views": len(included_views), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
