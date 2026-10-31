"""Generate the human-reviewable production database migration analysis report."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "docs/production_database/mock_coffice_catalog.json"
ANALYSIS_PATH = ROOT / "docs/production_database/dependency_analysis.json"
REPORT_PATH = ROOT / "docs/production_database/migration_analysis_report.md"


def bullets(values: list[str]) -> list[str]:
    return [f"- `{value}`" for value in values]


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    relations = analysis["relations"]
    required = [row for row in relations if row["classification"] == "required"]
    uncertain = [row for row in relations if row["classification"] == "uncertain"]
    deprecated = [row for row in relations if row["classification"] == "deprecated"]
    migration = required + uncertain

    migration_tables = sorted(row["relation"] for row in migration if row["relation_type"] in {"table", "partitioned_table"})
    migration_views = sorted(row["relation"] for row in migration if row["relation_type"] in {"view", "materialized_view"})
    deprecated_tables = sorted(row["relation"] for row in deprecated)
    required_tables = {row["relation"] for row in required if row["relation_type"] == "table"}

    config_metadata = sorted(
        name for name in migration_tables
        if name.startswith(("dim.", "ops.", "fund.")) or name == "ods.ods_file_ingest_log"
    )
    business_tables = sorted(
        name for name in migration_tables
        if (name.startswith("ods.") and name != "ods.ods_file_ingest_log")
        or name == "dwd.dwd_statement_split"
    )
    etl_tables = sorted(
        name for name in migration_tables
        if name in required_tables
        and name.startswith(("dwd.", "dws.", "ads."))
        and name != "dwd.dwd_statement_split"
    )

    constraints = Counter(item["constraint_type"] for item in catalog["constraints"])
    indexes_by_schema = Counter(item["schema_name"] for item in catalog["indexes"])
    relation_counts = Counter(
        (item["schema_name"], item["relation_type"])
        for item in catalog["relations"]
    )

    fk_lines: list[str] = []
    for item in catalog["constraints"]:
        if item["constraint_type"] != "f" or not item.get("referenced_relation"):
            continue
        source = f'{item["schema_name"]}.{item["relation_name"]}'
        target = f'{item["referenced_schema"]}.{item["referenced_relation"]}'
        if source not in migration_tables or target not in migration_tables:
            continue
        fk_lines.append(f'- `{source}` → `{target}`（`{item["constraint_name"]}`）')

    lines = [
        "# 正式数据测试库迁移分析报告",
        "",
        "> 状态：分析完成，尚未创建正式数据库。本报告由数据库只读目录快照、运行时代码引用、ETL 注册表和 SQL 上下游依赖交叉生成。",
        "",
        "## 1. 结论摘要",
        "",
        f'- 数据库类型：PostgreSQL `{catalog["server"]["server_version"]}`。',
        "- 当前开发测试库：`mock_coffice`，默认地址 `192.168.77.111:5432`，默认用户 `postgres`。",
        "- 建议正式数据测试库名称：`coffice_production`。项目不存在其他生产库命名规范。",
        f"- 当前库实际包含 {sum(1 for r in relations if r['relation_type'] == 'table')} 张表、{sum(1 for r in relations if r['relation_type'] == 'view')} 个视图。",
        f"- 建议迁移 {len(migration_tables)} 张空表和 {len(migration_views)} 个视图：其中 {len(uncertain)} 张用途未完全确认的表按安全原则保留。",
        f"- 明确排除 {len(deprecated_tables)} 张历史表；没有发现任何启用中的 Loader、ETL 注册项、网页 API 或运行时 SQL 仍引用这些排除表。",
        f'- 本次分析前 `mock_coffice` 目录签名：`{catalog["catalog_sha256"]}`；已保存所有表精确行数，供迁移完成后复核。',
        "",
        "## 2. 连接配置与代码现状",
        "",
        "项目没有 ORM Model、Alembic/Django migration 或统一 Repository 层；数据库结构由 `sql/**` 和 Python ETL 显式 SQL 驱动。连接参数分散在后端与 ETL 的命令行解析中，但共同遵循：",
        "",
        "- `PGHOST`，缺省 `192.168.77.111`",
        "- `PGPORT`，缺省 `5432`",
        "- `PGDATABASE`，缺省 `mock_coffice`",
        "- `PGUSER`，缺省 `postgres`",
        "- `PGPASSWORD`，无代码默认值",
        "",
        "主要配置入口包括 `apps/file_ingest/worker.py`、`apps/fund_split_adjust/server.py`、`apps/influencer_config/server.py` 以及全部 `etl/**/run_*_etl.py` 和 `load_*_ods.py`。因此不能修改代码缺省数据库名；正式环境必须通过显式环境选择脚本设置连接变量。",
        "",
        "## 3. 分类方法",
        "",
        "对象被判定为仍在使用，至少满足一项：启用的 28 类报表 Loader 目标；启用 ETL 脚本或其 SQL 文件引用；经营配置中心、数据导入中心或资金拆分服务运行时代码引用；启用链路的外键、视图或函数依赖。仅存在建表 SQL、测试或文档引用不能单独证明仍在使用。",
        "",
        "## 4. 正式环境必须保留的业务表",
        "",
        f"共 {len(business_tables)} 张，包含 28 类电商 ODS、银行 ODS 及银行拆分明细：",
        "",
        *bullets(business_tables),
        "",
        "## 5. 当前仍在使用的 ETL 链路表",
        "",
        f"共 {len(etl_tables)} 张 DWD/DWS/ADS 表。它们由启用的 ETL 注册表或当前 DataEase 指标链路引用：",
        "",
        *bullets(etl_tables),
        "",
        "## 6. 系统配置、任务与元数据表",
        "",
        f"共 {len(config_metadata)} 张：",
        "",
        *bullets(config_metadata),
        "",
        "此外保留以下视图：",
        "",
        *bullets(migration_views),
        "",
        "## 7. 明确不迁移的废弃表",
        "",
    ]
    for row in deprecated:
        lines.append(f'- `{row["relation"]}`：{row["deprecated_reason"]}')
    lines.extend([
        "",
        "排除安全检查：以上对象均没有 `active_evidence`。旧达人佣金代码和 SQL 文件仍保留在磁盘用于审计，但注册表 `influencer_commission.enabled=False`；天猫旧通用资金 Loader 位于 `DEPRECATED_LOADERS`；带时间戳天猫订单表只属于粒度迁移备份。",
        "",
        "## 8. 无法完全确认用途但默认保留的表",
        "",
    ])
    for row in uncertain:
        lines.append(
            f'- `{row["relation"]}`：当前启用的银行经营指标脚本不再刷新该旧银行达人佣金兼容表，但名称不属于已停用的平台独立达人佣金链路，且历史文档仍存在引用；按要求保留空结构，等待人工确认。'
        )
    lines.extend([
        "",
        "## 9. 外键、视图与对象依赖",
        "",
        "主要数据流为：`DIM + ODS/批次上下文 → DWD → 平台 DWS → ADS → DataEase`；数据导入任务为 `ops.ingest_run → ops.ingest_file_task / ops.etl_run → ops.etl_task`；银行拆分为 `fund.import_record + ods.ods_bank_statement → dwd.dwd_statement_split`。",
        "",
        "数据库中需要保留的外键如下：",
        "",
        *sorted(fk_lines),
        "",
        "视图依赖：",
        "",
    ])
    for item in catalog["view_dependencies"]:
        view_name = f'{item["view_schema"]}.{item["view_name"]}'
        ref_name = f'{item["referenced_schema"]}.{item["referenced_relation"]}'
        if view_name in migration_views:
            lines.append(f'- `{view_name}` → `{ref_name}`')
    lines.extend([
        "",
        "## 10. 其他数据库对象",
        "",
        f'- 约束：主键 {constraints["p"]}、外键 {constraints["f"]}、唯一约束 {constraints["u"]}、检查约束 {constraints["c"]}、PostgreSQL 18 独立非空约束 {constraints["n"]}。迁移脚本会按保留表过滤。',
        f'- 索引：当前共 {len(catalog["indexes"])} 个，按 schema 分布为 `{dict(sorted(indexes_by_schema.items()))}`；迁移会保留保留表上的普通、部分、联合及唯一索引。',
        f'- 序列：当前目录共 {relation_counts[("ods", "sequence")] + relation_counts[("dim", "sequence")] + relation_counts[("dwd", "sequence")] + relation_counts[("fund", "sequence")] + relation_counts[("ops", "sequence")]} 个业务序列；只迁移保留表默认值或 identity 所依赖的序列。',
        "- 函数：`dim.set_platform_fee_mapping_updated_at()`、`dim.set_platform_fee_primary_category_updated_at()`、`dws.refresh_operating_sales_product_allocation(...)`。",
        "- 触发器：费用映射表和一级分类表各 1 个 `updated_at` 触发器。",
        "- 扩展：仅 PostgreSQL 内置 `plpgsql`，不需要额外安装第三方扩展。",
        "- 物化视图和枚举类型：未发现。",
        "",
        "## 11. 初始化配置数据建议",
        "",
        "允许迁移的初始化数据必须来自项目内可审查、幂等的 seed SQL，而不是从 `mock_coffice` 复制：",
        "",
        "- 公司店铺映射：`sql/dim/32_dim_platform_shop_company_postgres.sql` 中的 24 条严格 DIM 配置。所有启用 ETL 都执行该文件，上传下拉框和 Loader 校验也依赖这些记录。",
        "- 银行费用类型、入账科目及允许关系：`sql/dim/181_seed_bank_fund_classification_postgres.sql`。",
        "- 七个平台费用映射模板：`306`、`313`、`318`、`331`、`340` 五个 seed SQL。",
        "- 平台费用一级分类：在映射模板写入后，由 `369_dim_platform_fee_primary_category_postgres.sql` 幂等生成。",
        "- 经营配置中心运行配置：用户确认商务人员、达人归属、0 元 GMV 目标、商品目录和商家编码映射属于正式库必需初始化数据；由只读生成器生成 `scripts/production_db/generated/002_runtime_config_seed.sql`，重复执行不覆盖网页维护结果。",
        "",
        "不进入自动初始化的数据仍包括银行流水拆分、上传记录、任务历史以及全部 ODS/DWD/DWS/ADS 事实数据。正式投数前仍应由业务方复核 24 条公司店铺映射和上述经营配置快照。",
        "",
        "## 12. 创建正式库可能影响的代码与配置",
        "",
        "不会修改指标公式、ETL SQL、Loader 或业务接口。新增内容仅限正式库迁移、初始化、环境选择和验证脚本。Windows 任务计划程序、Web 服务和 Worker 在正式测试时必须显式选择生产环境；现有未设置环境的开发运行仍连接 `mock_coffice`。",
        "",
        "## 13. 完整迁移清单",
        "",
        f"以下 {len(migration_tables)} 张表将创建为空表：",
        "",
        *bullets(migration_tables),
        "",
        "## 14. 分析阶段待人工确认",
        "",
        "- 是否最终永久移除两张旧银行达人佣金兼容表；当前迁移按安全原则保留。",
        "- 24 条代码内置公司店铺 DIM 的业务复核人；它们按系统必需初始化配置写入，但不是从 `mock_coffice` 复制。",
        "- 数据库服务器当前用户是否具备 `CREATE DATABASE` 权限；创建阶段会先检查，不会删除同名数据库。",
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(REPORT_PATH)


if __name__ == "__main__":
    main()
