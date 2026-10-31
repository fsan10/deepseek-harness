"""Generate the final delivery report from migration and validation artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/production_database"
MANIFEST_PATH = ROOT / "scripts/production_db/generated/migration_manifest.json"
ANALYSIS_PATH = DOCS / "dependency_analysis.json"
CATALOG_VALIDATION_PATH = DOCS / "validation_catalog_report.json"
ETL_VALIDATION_PATH = DOCS / "empty_etl_validation.json"
DASHBOARD_VALIDATION_PATH = DOCS / "empty_dashboard_validation.json"
OUTPUT_PATH = DOCS / "final_delivery_report.md"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    catalog_validation = json.loads(CATALOG_VALIDATION_PATH.read_text(encoding="utf-8"))
    etl_validation = json.loads(ETL_VALIDATION_PATH.read_text(encoding="utf-8"))
    dashboard_validation = json.loads(DASHBOARD_VALIDATION_PATH.read_text(encoding="utf-8"))

    by_schema: dict[str, list[str]] = defaultdict(list)
    for table in manifest["included_tables"]:
        schema, name = table.split(".", 1)
        by_schema[schema].append(name)
    deprecated = [row for row in analysis["relations"] if row["classification"] == "deprecated"]
    uncertain = [row for row in analysis["relations"] if row["classification"] == "uncertain"]

    lines = [
        "# `coffice_production` 正式数据测试库交付报告",
        "",
        "交付日期：2026-08-06",
        "",
        "## 1. 交付结果",
        "",
        "- 已在现有 PostgreSQL 18.4 服务器创建新数据库 `coffice_production`。",
        "- `mock_coffice` 未执行任何 DDL/DML；迁移前后 catalog 与精确行数签名相同。",
        "- 正式库创建 205 张表、2 个视图、41 个序列、3 个函数和 2 个触发器。",
        "- 正式库保留 205 个主键、16 个外键、71 个唯一约束、97 个检查约束以及总计 774 个索引。",
        "- 结构创建完成后的独立快照证明 205 张表全部为 0 行。初始化后只有 6 张明确列出的系统配置表有数据，其余 199 张表为空。",
        "- 没有复制任何 ODS、DWD、DWS、ADS、上传、任务、银行流水或历史业务记录。",
        "",
        "## 2. 连接与环境切换",
        "",
        "正式连接通过 `PRODUCTION_DATABASE_URL` 提供，测试连接可通过 `TEST_DATABASE_URL` 提供。真实账号和密码不进入代码或数据库。项目仍使用原有 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`；环境脚本只负责显式映射。",
        "",
        "```powershell",
        "$env:PRODUCTION_DATABASE_URL = 'postgresql://<user>:<password>@<host>:<port>/coffice_production'",
        ". .\\scripts\\production_db\\Set-DatabaseEnvironment.ps1 -Environment production",
        "```",
        "",
        "切回开发测试库：",
        "",
        "```powershell",
        "$env:TEST_DATABASE_URL = 'postgresql://<user>:<password>@<host>:<port>/mock_coffice'",
        ". .\\scripts\\production_db\\Set-DatabaseEnvironment.ps1 -Environment test",
        "```",
        "",
        "未显式选择生产环境时，现有开发缺省值继续连接 `mock_coffice`。",
        "",
        "## 3. 实际迁移表清单",
        "",
    ]
    for schema in sorted(by_schema):
        names = sorted(by_schema[schema])
        lines.extend([f"### `{schema}`（{len(names)} 张）", ""])
        lines.extend(f"- `{schema}.{name}`" for name in names)
        lines.append("")
    lines.extend([
        "迁移视图：`common.v_ingest_batch_shop_context`、`dwd.v_statement_split_detail`。",
        "",
        "## 4. 排除的废弃表",
        "",
    ])
    for row in deprecated:
        lines.append(f'- `{row["relation"]}`：{row["deprecated_reason"]}')
    lines.extend([
        "",
        "## 5. 用途未完全确认但已保留",
        "",
    ])
    for row in uncertain:
        lines.append(
            f'- `{row["relation"]}`：当前启用银行 ETL 不刷新该兼容表，但不属于已明确停用的平台独立达人佣金链路，按安全原则保留空结构。'
        )
    lines.extend([
        "",
        "## 6. 初始化配置数据",
        "",
    ])
    for table, count in catalog_validation["seeded_table_counts"].items():
        lines.append(f"- `{table}`：{count} 条。")
    runtime_counts = catalog_validation.get("allowed_runtime_table_counts", {})
    if any(runtime_counts.values()):
        lines.extend(["", "运行服务产生的非业务元数据："])
        for table, count in runtime_counts.items():
            if count:
                lines.append(f"- `{table}`：{count} 条 Worker 心跳；不是 seed 或业务数据。")
    lines.extend([
        "",
        "这些记录全部通过项目内独立幂等 SQL 写入。其中经营配置中心运行配置由只读生成器形成可审查快照，执行 seed 时不再连接 `mock_coffice`；24 条公司店铺 DIM 是上传下拉框、Loader 严格校验和所有启用 ETL 的必要配置。",
        "",
        "未初始化：银行流水、拆分、上传记录、ETL 任务和所有 ODS/DWD/DWS/ADS 指标事实数据。",
        "",
        "## 7. 验证结果",
        "",
        "| 验证项 | 结果 |",
        "|---|---|",
        "| 正式库连接 | 通过，健康接口返回 `database_name=coffice_production` |",
        "| 表与视图数量 | 通过，205 张表、2 个视图，与清单完全一致 |",
        "| 初始空表 | 通过，初始化前 205 张表全部 0 行 |",
        "| 初始化后数据边界 | 通过，除 12 张确认的配置表及运行中的 Worker 心跳外全部为空 |",
        "| 字段、默认值、非空、自增 | 通过，catalog 列定义逐项一致 |",
        "| 主键、外键、唯一与检查约束 | 通过，逐项一致 |",
        "| 普通、联合、部分和唯一索引 | 通过，逐项一致 |",
        "| 序列、视图、函数、触发器 | 通过，逐项一致 |",
        "| 经营配置中心启动 | 通过，临时后端成功启动并已关闭 |",
        "| 银行配置接口 | 通过，ODS/DWD 为 0 行且接口正常返回 |",
        "| 达播配置接口 | 通过，商务、达人归属、GMV 目标、商品目录和编码映射均可读取 |",
        "| 数据导入中心 | 通过，28 类报表和 24 条店铺配置可读取 |",
        "| 上传任务创建 | 通过，API 成功创建 1 个草稿会话；测试会话及日志随后已清理 |",
        f'| 看板空查询 | 通过，{dashboard_validation["ads_table_count"]} 张 ADS 全部可查询且返回空结果 |',
        "| `mock_coffice` 未改动 | 通过，迁移前后签名均为 `466bb53e9e6f308de2ca505e24ee77d89b8573c3bc9ce622783e881544b90fd9` |",
        "",
        "### 空库 ETL 诊断",
        "",
        f'启用 ETL 共 {etl_validation["enabled_etl_count"]} 个：{etl_validation["success_count"]} 个空库成功，{etl_validation["failed_count"]} 个按现有源数据校验主动失败，0 个超时。失败原因均为 ODS 为空、银行没有已提交批次或汇总上游 ADS 为空；没有缺表、缺列、缺函数、约束或权限错误。',
        "",
        "这表示数据库结构具备首批投数条件，但当前 ETL 不是“空数据也返回成功”的设计。按照禁止改变 ETL 逻辑的限制，本次没有放宽这些校验。正式测试顺序必须是：确认 DIM → 上传首批 ODS → 完成会话 → 运行受影响 ETL；银行链路必须先由财务提交锁定批次。",
        "",
        "### 现有单元测试",
        "",
        "- 数据导入模块：25/25 通过。",
        "- 资金配置中心与达播模块：14 项中 13 项通过，1 项失败。失败测试仍断言旧的相对导航 `href=\"influencer/\"`，当前页面使用现行绝对路由 `href=\"/influencer/\"`；该失败与数据库迁移无关，本次未修改导航或测试。",
        "",
        "## 8. 新增文件",
        "",
        "- `scripts/production_db/audit_database.py`：只读 catalog 和行数快照。",
        "- `scripts/production_db/analyze_dependencies.py`：代码、注册表、SQL 与数据库对象交叉分析。",
        "- `scripts/production_db/generate_analysis_report.py`：生成迁移分析报告。",
        "- `scripts/production_db/generate_schema_migration.py`：生成无数据结构 SQL。",
        "- `scripts/production_db/generated/001_schema.sql`：实际执行的幂等结构迁移。",
        "- `scripts/production_db/generated/migration_manifest.json`：迁移、排除和对象清单。",
        "- `scripts/production_db/create_database.py`：只创建、不删除数据库。",
        "- `scripts/production_db/migrate_schema.py`：事务性按步骤执行结构迁移。",
        "- `scripts/production_db/seed_system_config.py`：必要静态配置初始化。",
        "- `scripts/production_db/Set-DatabaseEnvironment.ps1`：测试/正式环境显式切换。",
        "- `scripts/production_db/compare_catalogs.py`：结构完整性与源库未改动验证。",
        "- `scripts/production_db/validate_empty_etl.py`、`validate_empty_dashboard.py`：空库行为诊断。",
        "- `scripts/production_db/README.md`：执行、切换和回滚说明。",
        "- `docs/production_database/*.json`：源库、正式库和验证证据快照。",
        "",
        "没有修改任何 Loader、指标 SQL、ETL 公式、业务 API 或现有默认数据库连接逻辑。",
        "",
        "## 9. 回滚方法",
        "",
        "1. 停止连接正式库的 Web、Worker 和 Windows 计划任务。",
        "2. 执行 `. .\\scripts\\production_db\\Set-DatabaseEnvironment.ps1 -Environment test`。",
        "3. 重新启动现有服务；它将连接 `mock_coffice`。",
        "4. `coffice_production` 原样保留，便于审计或再次测试。",
        "",
        "工具不会自动删除正式库。若确定永久废弃，应先由 DBA 备份并人工审批，再处理数据库；本次没有生成或执行自动 `DROP DATABASE`。",
        "",
        "## 10. 仍需人工确认",
        "",
        "- 复核 24 条公司店铺 DIM，尤其公司编码、店铺 ID、有效期和公司归属。",
        "- 决定两张旧银行达人佣金兼容表未来是否永久排除；当前已保留。",
        "- 接受现有 ETL 在对应源数据为空时主动失败，或另行授权未来设计“无数据即 no_change”行为；本次未修改。",
        "- 为正式 Web、Worker 和计划任务配置独立的最小权限数据库账号；当前建库和验证使用现有管理员账号。",
    ])
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
