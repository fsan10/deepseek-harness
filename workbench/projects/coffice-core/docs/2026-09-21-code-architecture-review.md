# mock_coffice 代码与架构审查报告

> 审查日期：2026-09-21  
> 审查对象：`D:\fsan10\mock_coffice`（HEAD 附近工作区，含未提交改动）  
> 审查方式：**全程只读**，未修改、移动或删除任何文件  
> 覆盖范围：`sql/`（431 个 .sql）、`etl/`（80 个 .py / 22,603 行）、`scripts/`（83 个 .py）、`ReverseAPI/`（49 个 .py）、`apps/`（12 个目录）、`deploy/production/`、根级配置与 Git 状态

---

## 0. 执行摘要

### 0.1 体检结论

| 维度      | 评级      | 一句话判断                                                                    |
| ------- | ------- | ------------------------------------------------------------------------ |
| 整体架构与分层 | **中**   | 方向正确（ODS→DWD→DWS→ADS→DataEase 纪律执行得好），但存在 2 处越层、1 处部署态断裂、1 个 6.9 万行的巨石应用 |
| 数据库设计   | **中上**  | 注释规范 100% 达标、金额类型纪律良好；真正的债在**迁移治理**与**刷新架构**，不在建模                        |
| 代码冗余    | **差**   | 跨文件重复行占 18.9%；连接/事务/校验骨架被复制 30+ 次                                        |
| 废弃代码与依赖 | **差**   | 无根级依赖清单；19,959 个 `node_modules` 文件被 Git 跟踪；确认可删 ~2,493 行死代码              |
| 性能      | **中**   | 无连接池是首要瓶颈；全量 TRUNCATE 刷新 + 7 路 UNION 重复扫描是结构性成本                          |
| 安全      | **中偏上** | 认证/会话/CSRF/注入防护做得扎实（超出同规模项目平均水平）；**但 .env 存在弱口令与令牌复用，且用户密码被可逆存储**        |

### 0.2 必须立刻处理的 5 件事（P0）

| # | 问题                                                                                                                                                               | 影响                              | 证据                                                                                                                                    |
| - | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | **生产容器可能启动即崩溃**：`apps/automation_center/service.py` 顶层 `import scripts.auto_download.run_all_platform_downloads`，而 `.dockerignore` 排除了 `scripts/auto_download`   | 生产 web 服务 `ImportError`，整站不可用   | `.dockerignore`、`apps/automation_center/service.py:19`、`apps/automation_center/worker.py:14`、`apps/fund_split_adjust/server.py:36/56` |
| 2 | **`.env` 弱口令 + 令牌复用**：`PGPASSWORD` 长度仅 **4**；`INGEST_ROBOT_TOKEN` 与 `AUTOMATION_ROBOT_TOKEN` **完全相同**；`INITIAL_ADMIN_PASSWORD` 与 `HTTP_TEST_PASSWORD` 是**同一个口令** | 数据库、机器人网关、管理员三处可被横向攻破           | `.env`（未入库）实测复核                                                                                                                       |
| 3 | **用户密码可逆存储与"查看密码"功能**                                                                                                                                            | 主密钥泄露 = 全量用户口令明文泄露，违反口令不可恢复原则   | `sql/common/424_iam_user_password_view_postgres.sql`、`apps/identity_access/password_cipher.py`、`user_service.view_password`           |
| 4 | **19,959 个 `node_modules` 文件被 Git 跟踪**（占全部跟踪文件的 **91.6%**），`.gitignore` 无 `node_modules` 规则，`.git` 已达 **294MB**                                                  | clone/切分支/CI 全面变慢，diff 噪音淹没真实改动 | 实测：`git ls-files \| wc -l` = 21800，`grep -c node_modules` = 19959                                                                     |
| 5 | **真实业务与个人数据入库**：`data/`（59 个）、`ReverseAPI/downloads/`（22 个）、`outputs/`（2 个，含员工姓名与绩效）                                                                             | 违反 AGENTS.md 数据边界，存在合规风险        | 实测 `git ls-files`                                                                                                                     |

### 0.3 一句话总结

> 这是一个**业务价值跑在工程治理前面**的项目：指标链路的分层纪律和字段规范执行得相当好（表/列注释 100%，金额无浮点滥用），但**迁移治理、代码去重、依赖与资产治理、密钥管理四条工程线明显滞后**；同时 `apps/fund_split_adjust` 已膨胀为单文件体系（107 个 py / 68,897 行），成为最大的维护风险点。  
> **建议路线：先用 1~~2 周清掉 P0（部署断裂、密钥、版本库瘦身），再用 3~~4 周做 P1 结构性去重，之后才谈新增功能。**



---

## 1. 整体架构与分层设计的合理性

### 1.1 实际形态（三层聚合）

系统实际由三条链路组成，不是微服务，也不是标准数仓平台：

```
┌── 取数层 ─────────────────────────────────────────────┐
│ Playwright DOM 链路：scripts/auto_download/playwright/ │
│ WebAPI 混合链路：ReverseAPI/Formal_Script/             │
│         （Cloak Login profile → CDP → 浏览器上下文）    │
└────────────────────┬──────────────────────────────────┘
                     │ 报表文件（xlsx/csv/zip）
┌── 数据层 ──────────▼──────────────────────────────────┐
│ etl/<platform>/load_*_ods.py → ODS                    │
│ etl/<platform|cross>/run_*_etl.py → DWD → DWS → ADS   │
│ sql/ 168 个 refresh SQL（TRUNCATE + INSERT 全量刷新）  │
└────────────────────┬──────────────────────────────────┘
                     │ ADS / dim
┌── 服务层 ──────────▼──────────────────────────────────┐
│ 单进程聚合服务 apps/fund_split_adjust/server.py :8770  │
│  └ 11 个模块（identity_access / file_ingest /          │
│     influencer_config / dashboard_center / ai_* /      │
│     automation_center / fund_split_adjust）            │
│ 独立进程：file_ingest.worker、nightly_scheduler        │
└────────────────────┬──────────────────────────────────┘
                     │ 只读
                DataEase（外部，:8101 代理嵌入）
```

### 1.2 分层合理之处（应当保持）

1. **指标链路的纪律性执行到位**：DWD 只清洗字段、不提前筛选订单/售后状态；平台口径下沉到 DWS；ADS 只服务指定图表；公司归属统一走 `dim.dim_platform_shop_company`，指标 SQL 不硬编码公司店铺。这是同规模项目里少见的自律。
2. **ODS 批次店铺上下文机制设计正确**：`common.v_ingest_batch_shop_context` 把"文件批次 → 店铺"事实从明细里剥离，导入侧显式报错而非静默 `default` 兜底（`etl/common/ods_file_loader.py:533`）。这是整个项目里最值得保留的设计。
3. **应用层不自己算指标**：`file_ingest` 通过 subprocess 调 ETL，前端明确注释"实际达成来自 ADS，不在前端自行计算"。
4. **AI 只读分析有 AST 级安全边界**：`apps/ai_analysis/sql_safety.py` 用 sqlglot 做白名单校验（禁 DML/DDL/危险函数/系统 schema，强制显式 schema，禁 `SELECT *`）+ 只读会话 + `statement_timeout`。**这一层的严谨程度高于项目其余部分。**
5. **认证与权限已收敛**：`apps/identity_access` 统一提供 cookie 会话、CSRF、RBAC 与导航构建，9 个页面复用同一 `shell.js`，没有出现"每个应用一套登录"的常见退化。

### 1.3 架构问题诊断

| ID      | 问题                                                                                                                                                                                      | 严重度   | 证据                                                                                                                                                                    |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A1**  | **部署态导入链断裂**：`automation_center` 顶层依赖被 `.dockerignore` 排除的 `scripts/auto_download`；静态推断生产 `web` 容器会在启动时 `ImportError`（需实机 `docker build` 验证）                                            | 🔴 P0 | `.dockerignore:scripts/auto_download`；`compose.yml:35-52` CMD 为 `apps.fund_split_adjust.server`；`server.py:36/56` → `automation_center/module.py:9` → `service.py:19` |
| **A2**  | **巨石应用**：`apps/fund_split_adjust` 占应用层代码的 **83.7%**（68,897 / 82,314 行，107 个 py），同时承担银行资金台、主服务宿主、路由分派、静态资源、DataEase 代理编排                                                                 | 🔴 P1 | 实测目录统计                                                                                                                                                                |
| **A3**  | **越层写 ODS/DWD**：`apps/fund_split_adjust/database.py` 在应用层直接 `INSERT INTO ods.ods_bank_statement`、`INSERT/UPDATE/DELETE dwd.dwd_statement_split`（13 处），违反 AGENTS.md「禁止修改、删除或覆盖 ODS 原始数据」 | 🟠 P1 | `database.py:284,303,535,542,582,585,629,637,684,745,808,917,960,981,1002`                                                                                            |
| **A4**  | **越层触发指标刷新**：`apps/influencer_config/product_category.py` 在应用层事务内直接执行 DWS/ADS 刷新 SQL，绕过 `etl/` 编排与校验                                                                                    | 🟠 P1 | `product_category.py:36-80`、`server.py:47-56`                                                                                                                         |
| **A5**  | **两条下载链路分工未定**：Playwright DOM 链路与 ReverseAPI WebAPI 链路并存、无统一入口，存在重复导出与"失败误报成功"风险（PROJECT_STATUS.md 已自认）                                                                                 | 🟠 P1 | `PROJECT_STATUS.md:60`；两套脚本各自实现归档/状态/登录处理                                                                                                                             |
| **A6**  | **无路由表**：`server.py:406-813` 按前缀顺序 `try` 各模块 `dispatch()`，"抢占式分派"使路由归属不可枚举、难测试                                                                                                          | 🟡 P2 | `server.py:406-813`                                                                                                                                                   |
| **A7**  | **自动化 Worker 未纳入编排**：`compose.yml` 只有 `file_ingest.worker` 与 `nightly_scheduler`，无 automation worker → 生产环境自动化任务**只入队不执行**                                                              | 🟠 P1 | `compose.yml:64-81`；`worker.py` 仅出现在 `docs/automation_api.md:25`                                                                                                      |
| **A8**  | **硬编码 Windows 宿主路径**：`ARCHIVE_ROOT = Path(r"C:\Users\win\Desktop\data")`，Linux 容器内必然失效                                                                                                  | 🟠 P1 | `apps/automation_center/registry.py:13`                                                                                                                               |
| **A9**  | **健康检查过于表面**：`scripts/deployment/healthcheck.py` 只做 TCP 连通性，不校验应用/DB 就绪；`/api/health` 未鉴权且暴露版本、特性清单与异常类型名                                                                               | 🟡 P2 | `compose.yml:56-61`、`apps/common/health.py:131-143`                                                                                                                   |
| **A10** | **无可观测性**：无结构化日志、无指标采集、无告警；Web 服务日志写 stdout，自动化日志用无轮转的 `FileHandler`                                                                                                                    | 🟡 P2 | `compose.yml` 无 logging 配置；`run_all_platform_downloads.py:137`                                                                                                        |

### 1.4 架构层建议

- **保留**：三层职责划分、DIM 单一归属、批次上下文机制、AI SQL 白名单、统一 IAM。
- **收敛**：把 A3/A4 两类越层显式化为"运营编辑层"（独立 schema 或独立 ETL 入口），要么改造、要么在 AGENTS.md 中登记为受控例外——**当前状态最危险的是"没人知道这是例外"**。
- **拆分**：`fund_split_adjust` 的 `server.py` 只保留宿主与路由表；银行资金台业务下沉为独立模块包，为后续引入真正的路由注册表做准备。
- **补齐**：A1 与 A7 是一对——先把 `scripts.auto_download` 的公共部分（`redact`、常量、`DownloadController`）下沉到 `apps/automation_center/` 内部或独立 `core/`，再决定自动化 Worker 的部署归属。

---

## 2. 数据库设计（表结构、索引、字段规范、关系与性能）

### 2.1 实测概览

| 指标                  | 实测值                                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `sql/` 文件           | 431（ads 19 / ai 10 / bank 8 / common 30 / dim 27 / douyin 11 / jd 11 / ks 10 / pdd 10 / tmall 12 / wechat_channels 9 / xhs 9，含嵌套子目录） |
| `CREATE TABLE`      | 280（唯一表名 280，**无一张表被重复 CREATE**）                                                                                                     |
| 表按 schema           | dws 85、dwd 71、ods 33、ads 24、dim 16、ai 15、ops 14、iam 11、config 9、fund 2                                                               |
| `COMMENT ON TABLE`  | **280 / 280（100%）**                                                                                                                  |
| `COMMENT ON COLUMN` | 5,202 条，覆盖全部 4,922 个表内列（**0 缺口**）                                                                                                    |
| 主键 / 唯一约束 / 索引      | PK 264、UNIQUE 110、`CREATE INDEX` 536                                                                                                 |
| 真实外键                | 90 处，**全部在 dim/common/ai/iam/ops/bank**，数仓层 0 外键                                                                                     |
| 刷新 SQL              | 168 个（161 个含 TRUNCATE），**58 个无任何 WHERE**（纯全量）                                                                                        |
| 文件序号                | 唯一序号 421 个；**重复序号 ≥5 组**、断裂序号 10 个                                                                                                   |

### 2.2 亮点（先说做对的）

1. **注释规范 100% 达标**——这是最容易被忽视却最难做到的项，本项目做到了，且字段注释普遍包含业务含义、来源、单位与枚举口径。
2. **金额类型纪律良好**：`FLOAT/DOUBLE/REAL` 命中 **0** 处；`NUMERIC(18,2)` 出现 466 次；少数 `NUMERIC(18,6)`（比率/权重）属合理例外。
3. **ODS 索引覆盖完整**：33 张 ODS 表 100% 有 `batch_id` 索引；ADS 普遍有 `company/platform/shop + 日期` 复合索引。
4. **SCD2 建模规范**：`dim.dim_platform_shop_company` 提供 `uq_dim_platform_shop_company_version / _current`，支持历史归属回溯——这是处理"店铺换主体"这类真实业务变化的正确做法。

### 2.3 表结构与字段规范

| ID     | 问题                                                                                                                      | 严重度   | 证据                                                                                                |
| ------ | ----------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------- |
| **D1** | **ODS 中文引号列名 802 个**（31 个文件）：`"APP渠道"`、`"SKU商家改价(元)"`、`"余额总消耗(元)"`，且大小写混用（`SKU`/`sku`）。虽属 ODS 保留源字段名的豁免范围，但严重影响可移植性与工具链 | 🟡 P2 | `sql/douyin/ods/11_...`、`sql/jd/ods/14_...`、`sql/xhs/ods/19_...`、`sql/wechat_channels/ods/17_...` |
| **D2** | **ODS 金额以文本存储**：237 个金额类中文列定义为 `TEXT/VARCHAR`（`"买家实付金额"`、`"订单实付(元)"`…），每次聚合都要 `::numeric` 转换                            | 🟠 P1 | `sql/tmall/ods/18_...`、`sql/ks/ods/04_...`                                                        |
| **D3** | **ODS 业务日期以文本存储**，DWD 刷新时做 `::timestamp` 转换                                                                             | 🟡 P2 | 同上                                                                                                |
| **D4** | **业务时间戳用裸 `TIMESTAMP`**：185 处 vs `TIMESTAMPTZ` 689 处，约定未覆盖"业务时间"场景，跨时区结算存在歧义                                            | 🟡 P2 | `sql/douyin/settlement_income/66_...:12`、`sql/douyin/gsv/26_...:14-15`                            |
| **D5** | **字段宽度漂移**：`shop_name` 有 255/200/128 三种；`platform_code` 有 32/64 两种                                                      | 🟡 P2 | `sql/common/430_automation_center_postgres.sql` vs 主流程                                            |
| **D6** | **规范例外未登记**：`sql/common/384`、`385` 在 DWD/DWS 层直接带 `company_code`，与"公司归属只在 ADS 关联 DIM"的约定冲突                              | 🟡 P2 | `sql/common/384_...`、`sql/common/385_...`                                                         |

### 2.4 关系与一致性

**做对的**：`shop_code`(1169) / `company_code`(263) / `batch_id`(691) / `stat_date`(1228) 命名全局一致；店铺-公司关系仅存在于 `dim.dim_platform_shop_company`（被 31 个文件引用），无第二张关系表。

| ID      | 问题                                                                                                                                                                                                          | 严重度          | 证据                                                                              |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------- |
| **D7**  | **`batch_id` 类型分裂**：全局 34 处 `BIGINT` vs 3 处 `VARCHAR(32)`。银行链路自成一套批次号，**无法与 `ods.ods_file_ingest_log.batch_id` 直接关联**                                                                                       | 🟠 P1        | `sql/bank/ods/177_...:5`、`sql/bank/fund_split/179_...:6`、`sql/common/180_...:5` |
| **D8**  | **同义台账重复**：文件导入台账两套（`ods.ods_file_ingest_log` vs `fund.import_record`）；运行台账三套（`ops.ingest_run` / `ops.ingest_file_task` / `ops.ingest_file_task_batch`）；操作审计两套（`fund.operation_log` vs `ops.operation_log`） | 🟡 P2        | `sql/common/00_...`、`180_...`、`368_...`                                         |
| **D9**  | **达人业绩 DWS 命名/粒度混乱**：`..._sales_order_item` / `..._sales_order` / `..._sales_shop_daily_zero` 三种后缀混用，部分是订单行粒度、部分是补零占位粒度，被同一视图 UNION 消费                                                                      | 🟡 P2        | `sql/common/396_dws_influencer_identity_resolved_view_postgres.sql`             |
| **D10** | **天猫结算双实现**：`dws_tmall_settlement_*` 与 `dws_tmall_settlement_fund_*` 两套，由 410/411/412 联合刷新合并                                                                                                                | 🟡 P2        | `sql/tmall/settlement_income/133...143` vs `sql/tmall/settlement_fund/403-405`  |
| **D11** | **数仓层零外键**：`batch_id`、`shop_code` 引用完整性仅靠应用层保证，无数据库级兜底                                                                                                                                                      | 🟢 可接受（数仓惯例） | —                                                                               |

### 2.5 迁移与编号治理（最需要治理的一块）

| ID      | 问题                                                                                                                                                                                                                                                  | 严重度   | 证据                                                                                                   |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ---------------------------------------------------------------------------------------------------- |
| **D12** | **双源头 DDL**：仓库无 `schema_migration` 台账；生产由 `scripts/production_db/bootstrap_database.py` 执行 `generated/001_schema.sql` + 54 个精选文件 + `apps/file_ingest/service.py` 的 20 条 `MIGRATION_FILES`。而 `sql/` 有 280 张表，**约 338 个编号文件未被任何运行器执行**——它们是被快照吸收的开发历史 | 🔴 P0 | `scripts/production_db/generated/001_schema.sql`（205 表 / 仅 2 视图）、`generated/migration_manifest.json` |
| **D13** | **重复序号 ≥5 组（同一目录层）**：305、306、370、382、383 各有两个不同内容的文件（跨目录统计达 10 组，另含 399/400/401/402/403）。序号已无法唯一标识文件                                                                                                                                                | 🟠 P1 | 实测 `ls sql/*/*.sql \| cut -d_ -f1 \| uniq -c`                                                        |
| **D14** | **同对象被多文件反复 ALTER**：`dim.dim_company_product_code_mapping` 被 **22 次** ALTER/改名（200→203→393→427→429），最终形态依赖执行顺序；该表是达人/产品/运营多条 ADS 链路的枢纽，**顺序错乱直接算错金额**                                                                                               | 🔴 P0 | `sql/dim/200,203,393,427,429`                                                                        |
| **D15** | **同一张表被两套刷新技术覆盖（6 组）**：`135/410`、`139/411`、`143/412`、`174/399`、`175/400`、`176/401`，同一 TRUNCATE 目标可能被两个任务按不同顺序覆盖                                                                                                                                     | 🟠 P1 | 对应 refresh 文件                                                                                        |
| **D16** | **同视图重复定义**：`common.v_ingest_batch_shop_context`（52 vs 421）、`dwd.v_statement_split_detail`（179 vs 182），后者覆盖前者                                                                                                                                       | 🟠 P1 | `sql/common/52_...:3`、`421_...:2`、`sql/bank/fund_split/179_...:26`、`182_...:1`                       |
| **D17** | **索引非幂等**：37 条 `CREATE INDEX` 缺 `IF NOT EXISTS`，重放必失败                                                                                                                                                                                               | 🟡 P2 | `sql/tmall/gsv/40_...:67-73` 等                                                                       |


### 2.6 历史包袱（由 manifest 直接坐实）

| ID      | 问题                                                                                                                                                     | 证据                                                               |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| **D18** | **17 张表定义完整却不上线**：整套达人佣金指标表（真实表 + 补零表，`sql/*/influencer_commission/228-245`、`289-296`）被 `migration_manifest.json` 的 `excluded_tables` 排除               | `scripts/production_db/generated/migration_manifest.json`        |
| **D19** | **已被 DROP 的死表定义**：`ai.catalog_column`/`ai.data_catalog`（374 建、379 删）；`ai.access_policy`/`skill_version`/`skill`/`feishu_identity_binding`（378 删）       | `sql/ai/374,378,379`                                             |
| **D20** | **改名残留与回退痕迹**：`ads_gsv_platform_daily`→`ads_gsv_company_daily`；7 平台 `*_operating_sales_product_allocation` 被整体 DROP 后在 248/251/254/257/260/300 重建      | `sql/ads/gsv/28_...:3`、`sql/douyin/operating_sales/201_...:4-10` |
| **D21** | **可能从未部署的视图**：`sql/ads/settlement_net/418_view_settlement_net_company_shop_monthly_metric_postgres.sql` 既不在 `001_schema.sql`，也不在 `COMPATIBILITY_FILES` | 交叉比对                                                             |
| **D22** | **列级 legacy 残留**：`dim_company_product_code_mapping.legacy_large_product_category / legacy_product_category_l2 / legacy_product_name`                   | `sql/dim/203_...:202-204`                                        |

### 2.7 数据库性能

| ID      | 问题                                                                                                                                                                                                                                                                                       | 严重度   | 证据                                                                                         |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------ |
| **D23** | **全量刷新无增量**：168 个 refresh 中 **58 个完全无 WHERE**，DWD 每次全表重扫 ODS                                                                                                                                                                                                                             | 🟠 P1 | 如 `sql/douyin/settlement_income/69_refresh_...`                                            |
| **D24** | **7 平台 UNION ALL 重复大查询**：30 个文件含 126 次 `UNION ALL`，ADS 层 17 个文件是"7 路 DWS 联合 + SCD2 区间 JOIN + GROUP BY"，最重的有 **13 个 UNION ALL**                                                                                                                                                           | 🟠 P1 | `sql/ads/settlement_income/71_refresh_...`、`sql/ads/influencer_commission/245_refresh_...` |
| **D25** | **非 SARGable 谓词导致索引失效**：刷新 SQL 普遍对 ODS 列做 `NULLIF(BTRIM(col),'')` 后再判断，已建索引完全用不上 → 全表扫描                                                                                                                                                                                                  | 🟠 P1 | `sql/douyin/influencer_performance/172_...:45`                                             |
| **D26** | **无分区**：`PARTITION BY RANGE/LIST/HASH` 出现 **0** 次。ODS 订单明细为纯追加表，无限增长                                                                                                                                                                                                                     | 🟡 P2 | 全库扫描                                                                                       |
| **D27** | **热路径缺索引**：`dws.dws_{jd,pdd,xhs}_influencer_sales_shop_daily_zero` 被视图按 `(platform_code, influencer_id)` 关联，但 PK 前缀是 `(stat_date, ...)`，**无法命中**；`dwd_finance_operating_configuration_detail` 按 `budget_month` 过滤无索引；`ads_operating_sales_product_company_shop_daily` 缺 `shop_code+date` | 🟡 P2 | 对应建表文件                                                                                     |
| **D28** | **重量级过程**：`sql/common/276_...`（10 层 CTE + `CROSS JOIN LATERAL REGEXP_SPLIT_TO_TABLE` + 逐行 `LEFT JOIN LATERAL ... LIMIT 1`）                                                                                                                                                               | 🟡 P2 | `sql/common/276_operating_sales_product_allocation_refresh_helper_postgres.sql`            |

> **澄清**：刷新 SQL 文件内 `BEGIN/COMMIT` 出现 0 次，但执行器（`etl/operating_sales/run_operating_sales_etl.py:284` 等）是"整文件 execute + 一次 commit，异常 rollback"，因此"事务内 TRUNCATE+INSERT"在**客户端层成立**。风险在于**任何绕过执行器的直接 psql 调用会失去原子性**。

### 2.8 数据库层优化建议（按优先级）

| 优先级    | 建议                                                                                                                              | 影响面   | 成本 |
| ------ | ------------------------------------------------------------------------------------------------------------------------------- | ----- | -- |
| **P0** | **分离"开发历史"与"可部署 DDL"**：把被快照吸收的 ~338 个文件归档到 `sql/archive/`，只保留生成 schema + 精选迁移；17 张 excluded 表对应文件加 `-- DEPRECATED` 头并移出主目录      | ★★★★★ | 中  |
| **P0** | **消除 `dim_company_product_code_mapping` 的顺序依赖**：把 200→203→393→427→429 的 22 次 ALTER 合并为一份"当前形态" `CREATE TABLE`（含清理 `legacy_*` 列） | ★★★★★ | 中  |
| **P1** | **统一批次台账与 `batch_id` 类型**：银行链路 `VARCHAR(32)` → `BIGINT` 并弱关联 `ods_file_ingest_log`，或显式建立映射                                      | ★★★★  | 高  |
| **P1** | **补热路径索引**（D27 三处，均为低风险高收益）                                                                                                     | ★★★★  | 低  |
| **P1** | **物化中间层**，把 17 个 ADS 刷新里的"7 路 UNION + DIM JOIN + GROUP BY"降为单层聚合                                                                | ★★★★  | 高  |
| **P1** | **解决 6 组双刷新技术覆盖**：明确唯一权威，删除另一套                                                                                                  | ★★★★  | 中  |
| **P2** | **引入增量与分区**：ODS 按 `ingest_time`/`batch_id` RANGE 分区；DWD 只处理新增 batch；把 `NULLIF(BTRIM())` 改为落库时预清洗                                | ★★★★★ | 高  |
| **P2** | **统一 ODS 类型策略**：落库即转 `NUMERIC(18,2)`/`DATE`，原始值留存 `raw_data JSONB`（参考 `ods.ods_bank_statement` 已有做法）                            | ★★★   | 中  |
| **P2** | **幂等性补齐**：37 条缺 `IF NOT EXISTS` 的索引统一加固                                                                                         | ★★★   | 低  |
| **P3** | **编号治理**：修复重复/断裂序号，或放弃序号语义，改为 `版本_时间戳_描述` + 轻量迁移台账表                                                                             | ★★★   | 中  |
| **P3** | **合并同义台账**（D8）、统一达人 DWS 命名（D9）                                                                                                  | ★★    | 中  |

---

## 3. 代码冗余与重复逻辑

### 3.1 量化结论

在 `etl + scripts + ReverseAPI` 合计 **58,764 非空代码行**中，**11,109 行（18.9%）被至少另一个文件以 ≥6 行块重复**。

单文件重复率 Top：

| 文件                                                                   | 重复占比      | 重复行       |
| -------------------------------------------------------------------- | --------- | --------- |
| `ReverseAPI/Formal_Script/xiaohongshu_settlement_webapi_download.py` | **81.2%** | 224 / 276 |
| `ReverseAPI/Formal_Script/xiaohongshu_fund_webapi_download.py`       | **79.4%** | 224 / 282 |
| `ReverseAPI/Formal_Script/douyin_settlement_webapi_download.py`      | 67.1%     | 206 / 307 |
| `ReverseAPI/Formal_Script/douyin_fund_webapi_download.py`            | 64.4%     | 206 / 320 |
| `ReverseAPI/Formal_Script/kuaishou_webapi_common.py`                 | 62.2%     | 404 / 650 |
| `ReverseAPI/Formal_Script/jd_webapi_common.py`                       | 59.9%     | 400 / 668 |
| `scripts/auto_download/playwright/pinduoduo_order_download.py`       | 57.3%     | 401 / 700 |
| `etl/ks/run_ks_platform_expense_etl.py`                              | 57.1%     | 393 / 688 |

### 3.2 重复模式清单

| ID      | 模式                                                                                                                                                                                                                                                                                                           | 副本数      | 证据                                                                                                                    | 可削减            |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | --------------------------------------------------------------------------------------------------------------------- | -------------- |
| **C1**  | `build_parser()` 的 PostgreSQL 连接参数块逐字复制（仅 `description` 文案不同，30 个变体）                                                                                                                                                                                                                                         | 37 文件    | `etl/douyin/run_douyin_gsv_etl.py:56-63`、`etl/pdd/run_pdd_gsv_etl.py:54-61`、`etl/common/ods_file_loader.py:406-410`   | ~200 行         |
| **C2**  | `connect + try/except rollback/finally close` 事务骨架逐字副本（14 份精确匹配 + 21 份仅变量名不同）                                                                                                                                                                                                                                | 35 文件    | `etl/douyin/run_douyin_gsv_etl.py:92-128`、`etl/pdd/run_pdd_gsv_etl.py:158-310`                                        | ~350 行         |
| **C3**  | 依赖缺失守卫（`raise SystemExit("缺少依赖：psycopg2…")`，其中 20 份字符串完全相同）                                                                                                                                                                                                                                                  | 30 文件    | 各 `run_*_etl.py` 头部                                                                                                   | ~150 行         |
| **C4**  | `sys.path` 注入 + 路径常量（`ETL_ROOT` 32 / `PROJECT_ROOT` 39 / `SQL_DIR` 30）                                                                                                                                                                                                                                       | 30-39 文件 | `etl/tmall/load_tmall_fund_ods.py:10-12`                                                                              | ~120 行         |
| **C5**  | ODS 表/字段校验三件套（`to_regclass` 35 次 / `information_schema.columns` 38 次），逻辑等价但实现各异                                                                                                                                                                                                                              | 30-32 文件 | `etl/douyin/run_douyin_gsv_etl.py:66-88`、`etl/platform_bank_summary/run_...:89-102`                                   | ~400 行         |
| **C6**  | `def execute_files` + `cursor.execute((SQL_DIR / f).read_text())` 逐字相同（32 处 / 27 文件）                                                                                                                                                                                                                         | 23 份     | `etl/douyin/run_douyin_gsv_etl.py:102-104`                                                                            | ~180 行         |
| **C7**  | **`*_webapi_common.py` 整份复制**：`NeedsHumanError`/`ApiError` 6 份、`log()` 7 份、`is_human_error_message()` 5 份、`ObservedRequest` 4 份、`NaturalRequestCollector` 4 份（jd vs kuaishou 约 178 行**仅 29 行有差异**）、`BrowserApiSession` 4 份、`safe_filename`/`unique_path` 4/6 份、`_add_cookies`/`download_original_file` 4/4 份 | 4-7 份    | `ReverseAPI/Formal_Script/{douyin,jd,kuaishou,pdd,tmall,xhs}_webapi_common.py`                                        | ~1,800-2,100 行 |
| **C8**  | 同平台"资金/结算"脚本互为 80% 复制                                                                                                                                                                                                                                                                                        | 2 对      | `xiaohongshu_fund/settlement_webapi_download.py`（81%/79%）、douyin 对应（64%/67%）                                          | ~400 行         |
| **C9**  | ETL 校验巨函数逐平台重写（**157 个函数 >80 行**，最大 510 行），内部结构高度雷同（粒度唯校 → DWS 重算一致 → ADS↔DWS 对账 → unmapped=0 → 主键唯一）                                                                                                                                                                                                        | 30+      | `etl/douyin/run_douyin_operating_sales_etl.py:291`(510 行)、`etl/operating_sales/run_operating_sales_etl.py:747`(360 行) | ~1,500 行       |
| **C10** | Playwright 状态/归档/子进程 helper 重复：`_state_path/_read_state/_write_state` 4 组（jd↔kuaishou 逐字等价）、`run_project_module` 4 份、`move_report` 3 份；`pinduoduo_order/settlement` 相似度 **61.5%（共同 359 行）**                                                                                                                  | 3-4      | `jd_order_download.py:95/99/107`、`kuaishou_order_download.py:84/88/96`                                                | ~400 行         |
| **C11** | 收尾摘要块与 SQL 清单重复：`print(f"数据库：{args.dbname}")` 精确出现在 23 文件；同一批刷新 SQL 被 7-9 份 ETL 重复列出                                                                                                                                                                                                                         | 7-23     | 各 `run_*_etl.py`                                                                                                      | ~200 行         |

### 3.3 连接与事务封装现状

| 项目                      | 实测                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `import psycopg2`       | etl **36 文件**，全仓 61 文件                                                                                                   |
| `psycopg2.connect(` 调用点 | etl **37 次**；scripts 12 文件                                                                                               |
| 使用连接上下文管理器              | **仅 2 文件**（`etl/xhs/run_xhs_settlement_metrics_etl.py`、`load_xhs_settlement_ods.py:88`）                                  |
| 已有封装但未被复用               | `scripts/production_db/db_connection.py`（57 行，含参数注入 + URL 解析 + 安全校验）**只有 `scripts/production_db/` 内 11 个文件用**，etl 层 0 复用 |

### 3.4 代码层优化建议

| 优先级    | 建议                                                                                                                                | 量化收益                               |
| ------ | --------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| **P0** | 抽取 `etl/common/db.py`（`add_pg_arguments()` + `@contextmanager pg_connection()` + `run_sql_files()`），直接复用 `db_connection.py` 的安全校验 | **-350 行**，30 个参数变体 → 1            |
| **P0** | 删除确认废弃的 8 个脚本（见 §4.1）                                                                                                             | **-2,493 行 / 8 文件**，消除"哪个是正式入口"的歧义 |
| **P0** | 补齐根级依赖声明（见 §4.3）                                                                                                                  | 消除 5 个未声明依赖                        |
| **P1** | 抽取 `ReverseAPI/common/webapi_common_base.py`（C7 全部公共类与函数）                                                                         | **-1,800~2,100 行**                 |
| **P1** | 抽取 `etl/common/pipeline.py` 校验原语（表存在性 / 粒度唯校 / 重算一致 / 对账 / unmapped 硬失败）                                                          | **-1,500 行**，并统一 unmapped 语义       |
| **P1** | 抽取 `playwright_common.py`（状态、归档、子进程、日历/弹层公共交互）                                                                                    | **-400 行**                         |
| **P2** | 基线快照外置：`EXPECTED`/`CURRENT_BASELINE`/内联 `DATE '2026-05-01'` → `data/baselines/*.json`                                             | 消除 8+ 处"数据一变 ETL 就红"               |
| **P2** | ETL 引入 `logging` 替换 447 处 `print`（层名/行数/日期范围/指标值/耗时/batch_id）                                                                     | 满足 AGENTS.md 可审计要求                 |
| **P2** | 一致性修复：移除 2 处 BOM（`scripts/auto_download/__init__.py` 等）、补 `__init__.py`、统一导入风格                                                    | 消除 `python -m` 下偶发失败               |

> **合计可削减约 6,500~6,900 行**（占 `etl+scripts+ReverseAPI` 的 ~10%），跨文件重复率从 18.9% 降至 10% 以下。

---

## 4. 未使用或废弃的代码与依赖

### 4.1 确认可删除的脚本（全仓引用检索确认）

| 文件                                                       | 行数        | 判定依据                                                                                       |
| -------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------ |
| `etl/douyin/run_douyin_operating_sales_etl.py`           | **887**   | 已被多平台版 `etl/operating_sales/run_operating_sales_etl.py`（含 `PLATFORMS["douyin"]`）取代；全仓 0 引用 |
| `ReverseAPI/capture_pdd_export_flow.py`                  | **588**   | 0 引用                                                                                       |
| `ReverseAPI/Test_Script/pdd_cdp_probe.py`                | 380       | 0 引用                                                                                       |
| `scripts/auto_download/playwright/tmall_slider_debug.py` | 206       | 0 引用；`_wait_login_or_timeout` 定义即死代码                                                       |
| `ReverseAPI/Test_Script/pdd_promotion_export_probe.py`   | 197       | 0 引用                                                                                       |
| `ReverseAPI/Test_Script/pdd_direct_query_probe.py`       | 153       | 0 引用                                                                                       |
| `ReverseAPI/Test_Script/pdd_playwright_query_probe.py`   | 64        | 0 引用                                                                                       |
| `etl/douyin/run_douyin_influencer_performance_etl.py`    | 18        | `runpy` 兼容壳，0 引用                                                                           |
| **合计**                                                   | **2,493** |                                                                                            |

另有 16 个"定义了但从未被调用"的函数（AST + 全文引用双重判定），如 `pdd_order_export_download.py:172 extract_debug_port`、`:215 safe_json_loads`、`kuaishou_settlement_webapi_download.py:125 has_settlement_rows` 等。

### 4.2 未使用/废弃资产

| ID      | 资产                                                                                                          | 规模                          | 状态                                                                                                                       | 建议                                                       |
| ------- | ----------------------------------------------------------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| **U1**  | `apps/shared_navigation/`                                                                                   | **183MB / 19,959 个跟踪文件**    | 死资产：只有 `dist/`、`node_modules/`、`package-lock.json`，**连 `package.json` 都没有**；`dist/semi-sidebar.{js,css}` 与另两处字节级相同；全仓零引用 | 移出版本库并评估整体删除                                             |
| **U2**  | `graphify-out/`                                                                                             | 69MB / **732 个文件已跟踪**       | 自动生成代码图谱，仅自引用，`.gitignore` 未覆盖                                                                                           | `git rm -r --cached` + 加忽略                               |
| **U3**  | 死前端资源 `semi-sidebar.js/css`                                                                                 | 306KB + 703KB × **3 份完全相同** | `apps/{shared_navigation/dist,fund_split_adjust/static,influencer_config/static}/`，无任何 HTML 引用                           | 删除                                                       |
| **U4**  | 根目录 4 个设计稿目录：`fund-split-adjust/`、`influencer-ops-design/`、`finance-budget-ops/`、`platform-income-expense/` | 1.35MB                      | Trae `solo-design` 技能产出的画布工程（含 `canvasData`/`validation-report.json`），对应功能均已实现于 `apps/`                                  | 归档或删除；`platform-income-expense/test.txt`（内容仅 "test"）一并清理 |
| **U5**  | `mock_coffice_architecture.html` + `.visual-check.json`                                                     | 730KB + 16KB                | 一次性渲染产物，已跟踪                                                                                                              | 移除跟踪                                                     |
| **U6**  | `outputs/` 中被跟踪的 2 个文件                                                                                      | 含员工姓名与绩效的 xlsx              | 目录已被 `.gitignore` 忽略但文件已入库（忽略规则对已跟踪文件无效）                                                                                 | `git rm --cached`                                        |
| **U7**  | `ReverseAPI/downloads/`（22 个 CSV/XLS/ZIP）、`data/`（59 个 xlsx/csv）                                            | 真实业务数据                      | 均**未**被 `.gitignore` 覆盖                                                                                                  | 取消跟踪 + 补忽略规则 + 清理历史                                      |
| **U8**  | `ops.etl_nightly_schedule` 之外的深链：`compose.yml` 无 automation 服务                                              | —                           | 见 A7                                                                                                                     | 补编排或明确仅运维机运行                                             |
| **U9**  | `.codex_tmp/`（381MB / 4,725 文件）、`.uploads/`（215MB）、`tmp/`、`.tmp*`、`ReverseAPI/__pycache__`                  | ~600MB                      | 已被 gitignore，仍在磁盘                                                                                                        | 确认后物理清理                                                  |
| **U10** | `apps/dashboard_center/frontend/` 仅剩空壳 `node_modules/.vite-temp`                                            | 8KB                         | Vite 前端遗留                                                                                                                | 删除                                                       |


### 4.3 依赖管理

**现状：根级无 `requirements.txt` / `pyproject.toml` / `uv.lock` / `setup.py` / `Pipfile`。** 唯一清单是 `apps/fund_split_adjust/requirements.txt`，却混装了全项目乃至 ETL 的依赖。

实际 import 与声明比对：

| 库                                                | 使用文件数                 | 是否声明                                                                             |
| ------------------------------------------------ | --------------------- | -------------------------------------------------------------------------------- |
| `psycopg2`                                       | 61                    | ✅                                                                                |
| **`playwright`**                                 | **48**                | ❌ **未声明**                                                                        |
| `openpyxl`                                       | 17                    | ✅                                                                                |
| **`requests`**                                   | **13**                | ❌ **未声明**                                                                        |
| **`websocket-client`**                           | **5**                 | ❌ **未声明**                                                                        |
| **`msoffcrypto-tool`**                           | 2                     | ❌ **未声明**                                                                        |
| **`pytest`**                                     | 运行器（72 个文件用 unittest） | ❌ **未声明**                                                                        |
| `cryptography` / `bcrypt` / `lark-oapi` / `xlrd` | 1-2 各                 | ✅                                                                                |
| `sqlglot`                                        | 1                     | ✅ **但三重提供**（已安装 + `apps/fund_split_adjust/.vendor/sqlglot`(13MB) + requirements） |

其他：全部为区间约束（`>=x,<y`）、无锁文件、无 hash 校验；`.venv` 内还装着 `graphifyy` + 30 个 `tree-sitter-*` + `networkx`/`RapidFuzz`/`PyYAML` 等项目代码 0 引用的开发工具链。

**建议（P0）**：新建根级 `requirements.txt`（或 `pyproject.toml`）+ 锁文件，补入 5 个未声明依赖，把 `apps/fund_split_adjust/requirements.txt` 收回为子应用专属，删除 `.vendor/sqlglot`。

### 4.4 测试覆盖现状

| 区域                             | 文件数   | 测试函数数 | 覆盖对象                                  |
| ------------------------------ | ----- | ----- | ------------------------------------- |
| `apps/**/tests/`               | 38    | 260   | Web 应用（IAM、file_ingest、dashboard、AI…） |
| `scripts/auto_download/tests/` | 20    | 119   | Playwright 下载脚本的解析/计划/参数逻辑            |
| `ReverseAPI/Test_Script/`      | 17    | —     | WebAPI/抓包**探针**（非标准单测）                |
| **`etl/`**                     | **0** | **0** | ——                                    |

**完全无测试的关键链路**：161 个含 TRUNCATE 的刷新 SQL（可重复执行/原子性/回滚）、38 个 `run_*_etl.py` 中的 35 个、`common.v_ingest_batch_shop_context`（55 个 DWD refresh 依赖的核心契约）、`etl/common/ods_file_loader.py`（618 行主流程）、全部回滚路径。

**当前健康信号**：`scripts/auto_download/.pytest_cache/v/cache/lastfailed` 记录 **10 个测试文件失败**，下载脚本测试处于红/不稳定状态。

---

## 5. 潜在的性能与安全隐患

### 5.1 性能

| ID     | 问题                                                                                                                                        | 严重度    | 证据                                                                                                                      |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------- |
| **P1** | **无数据库连接池**：每次事务 `psycopg2.connect()` 新建连接、用完 `close()`；无 `SimpleConnectionPool`/pgbouncer                                                | 🔴 高   | `apps/fund_split_adjust/database.py:82-98`、`apps/file_ingest/service.py:252-256`、`apps/influencer_config/server.py:118` |
| **P2** | **并发无上限**：`ThreadingHTTPServer` 每请求一线程，线程数与 DB 连接数均无限制，高并发下易耗尽 PostgreSQL 连接                                                              | 🔴 高   | `server.py:20,106,903`、`influencer_config/server.py:1295`                                                               |
| **P3** | **AI 只读查询无行数上限**：`cursor.fetchall()` 全量取回，validator 仅**记录** LIMIT 而不强制追加；`statement_timeout` 限时不限内存                                       | 🟠 中   | `apps/ai_analysis/query_executor.py:88-89`、`sql_safety.py:105-111`                                                      |
| **P4** | **夜间调度 TOCTOU**：先 `already_created()` 再 `create_nightly_etl()`，`ops.etl_run` 无 `(trigger_type, 日期)` 唯一约束；多实例可能重复入队（当前 compose 单实例运行，风险受控） | 🟠 中   | `nightly_scheduler.py:37-47/68-91`、`sql/common/390_...`                                                                 |
| **P5** | **上传文件 SHA-256 在内存中计算**（200MB 上限时整块驻留）                                                                                                    | 🟡 低-中 | `apps/file_ingest/service.py:469`、`etl/common/ods_file_loader.py:536`                                                   |
| **P6** | **日志无轮转**：`logging.FileHandler` 追加写；Web 服务日志直接 stdout                                                                                     | 🟠 中   | `run_all_platform_downloads.py:137`                                                                                     |
| **P7** | **Playwright 可能关闭共享浏览器**：个别脚本调 `browser.close()`，而浏览器是 Cloak 共享实例，会连带影响其他并发任务                                                             | 🟠 中   | `douyin_bill_download.py:331`                                                                                           |
| **P8** | **ETL 全量刷新 + 非 SARGable 谓词 + 无分区**                                                                                                        | 🟠 中   | 见 §2.7 D23/D25/D26                                                                                                      |

**做对的**：全仓 `read_sql`/`pandas` 命中 0，无整表读入内存；ETL worker 用 `pg_try_advisory_lock` + `FOR UPDATE SKIP LOCKED` 防并发重复消费；下载脚本普遍设置了操作/下载超时并 `try/finally` 关闭 page。

### 5.2 安全

| ID      | 问题                                                                                                                                                                   | 严重度   | 证据                                                                                         |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------ |
| **S1**  | **`.env` 弱口令 + 令牌复用**（实测复核）：`PGPASSWORD` 长度 **4**；`INGEST_ROBOT_TOKEN` 与 `AUTOMATION_ROBOT_TOKEN` **完全相同**；`INITIAL_ADMIN_PASSWORD` 与 `HTTP_TEST_PASSWORD` 为**同一口令** | 🔴 P0 | `.env`（未入库，Git 历史干净✅）                                                                      |
| **S2**  | **用户密码可逆存储并可前端查看**：AES-GCM 密文 + `view_password()` + 前端弹窗；登录仍用 bcrypt，但主密钥即可批量还原全部用户口令                                                                                | 🔴 P0 | `sql/common/424_...`、`password_cipher.py`、`user_service.py:155-184`、`static/system-iam.js` |
| **S3**  | **单一主密钥复用**：同一 `AI_CONFIG_ENCRYPTION_KEY` 同时保护 AI `api_key`、数据源密码、飞书 `app_secret/verification_token/encrypt_key` 与用户口令密文；无轮换/KMS                                     | 🟡 P2 | `apps/ai_analysis/crypto.py:13-58`                                                         |
| **S4**  | **共享默认初始口令**：新建用户不填密码时用 `DEFAULT_INITIAL_PASSWORD`                                                                                                                   | 🟠 P1 | `user_service.py:17,29-36,85`                                                              |
| **S5**  | **无任何安全响应头**：CSP / X-Frame-Options / X-Content-Type-Options / HSTS / Referrer-Policy 全仓 0 命中                                                                         | 🟠 P1 | 全仓 grep                                                                                    |
| **S6**  | **`X-Forwarded-For` 可伪造**：直接取首值，未限定可信代理，影响限流与审计真实性                                                                                                                   | 🟠 P1 | `server.py:192-195`                                                                        |
| **S7**  | **部署暴露面**：`8770`/`8101` 发布到宿主机（Docker 默认 `0.0.0.0`）；`DATAEASE_PROXY_BIND=0.0.0.0`；`AUTH_COOKIE_SECURE=false`；镜像 tag `APP_IMAGE_TAG=latest`                           | 🟠 P1 | `compose.yml:50-52`、`.env:29,33,59`                                                        |
| **S8**  | **真实业务与个人数据入库**                                                                                                                                                      | 🟠 P1 | 见 U7                                                                                       |
| **S9**  | **健康接口信息暴露**：`/api/health` 未鉴权且暴露版本、特性清单、模块就绪与异常类型名                                                                                                                  | 🟡 P2 | `apps/common/health.py:131-143`                                                            |
| **S10** | **标识符未统一 quote**：动态表名/列名走白名单但未用 `psycopg2.sql.Identifier` 包裹，缺防御纵深                                                                                                   | 🟡 P2 | 见下                                                                                         |
| **S11** | **子进程透传 `PGPASSWORD`**                                                                                                                                               | 🟡 P2 | `apps/file_ingest/service.py:3399-3410`                                                    |
| **S12** | **AI 工具沙箱全开**：`.codex/config.toml` 为 `danger-full-access` + `network_access = true`                                                                                  | 🟡 P2 | `.codex/config.toml:1,4`                                                                   |
| **S13** | **本地残留抓包**：`.codex_tmp/captures/*.json`（约 140MB，已 gitignore）含抖音/京东/快手/天猫/小红书真实账单与订单响应                                                                                | 🟡 P2 | `.codex_tmp/captures/`                                                                     |

**做对的（应当保持）**：`.env` 未被跟踪且**全历史干净**（`git log --all --full-history -- .env` 无命中，关键密钥字面量的 `git log -S` 检索为空）；**无 SQL 注入**（`.format`→`execute` 命中 0，值全部 `%s` 参数化，动态标识符均来自白名单；仅标识符未 quote，属纵深问题）；bcrypt（rounds 12）、`HttpOnly`+`SameSite=Strict` Cookie、CSRF 双提交、登录锁定 + 双维度限流 + dummy hash 防枚举；路径穿越防护（basename + `resolve()` 根校验）；无 `shell=True`；DataEase 代理无 SSRF（目标 host 固定）；无 CORS 全开、无 `debug=True`；容器非 root（uid 10001）、未挂载敏感目录、无 DB 端口发布。

### 5.3 性能与安全整改清单

**P0**

1. 轮换 `.env` 全部凭证：更换 4 位 DB 口令；拆分并分别随机化两个 robot token；更换管理员/默认/测试口令与电商登录口令；确认新值不进任何文件、不进命令历史。
2. 下线"密码可逆存储/查看"（424 视图 + `password_cipher.py` + `view_password` + 前端入口），仅保留 bcrypt 单向哈希；确有业务需要则强制最小权限 + 双人复核 + 审计告警。
3. 引入数据库连接池（`psycopg2.pool` 或 pgbouncer），并给 `ThreadingHTTPServer` 设并发上限。
4. 修复 A1 部署态导入链断裂；从 Git 移除 `data/`、`ReverseAPI/downloads/`、`outputs/` 已跟踪文件并清理历史，补全 `.gitignore`。
5. 移除 `node_modules` 跟踪（19,959 文件），`.gitignore` 增加 `node_modules/`。

**P1**  
6\. AI 只读查询强制服务端行数上限（统一包裹 LIMIT 或游标分页）。  
7\. 夜间调度加 `(trigger_type, 日期)` 唯一约束或用 `pg_advisory_xact_lock` 包裹"检查+插入"。  
8\. 收敛部署面：宿主端口绑 `127.0.0.1` + 前置反代、`DATAEASE_PROXY_BIND=127.0.0.1`、镜像 tag 固定版本号、对外启用 HTTPS 并置 `AUTH_COOKIE_SECURE=true`。  
9\. 增加安全响应头；仅在可信代理后信任 `X-Forwarded-For`。  
10\. 依赖固定精确版本 + 锁文件；补声明 `playwright/requests/websocket-client/msoffcrypto-tool`。  
11\. 日志启用 `RotatingFileHandler`，限制 `captures`/`outputs` 保留周期。

**P2**  
12\. 动态标识符统一 `psycopg2.sql.Identifier` 包裹；收敛健康接口信息暴露；不向子进程透传 `PGPASSWORD`（改 `.pgpass`/服务文件）。  
13\. 主密钥引入 KMS/轮换与备份恢复方案。  
14\. 收敛 `.codex/config.toml` 的 `danger-full-access`；清理本地抓包样本。

---

## 6. 建议新增的功能（作用、价值与优先级）

> 说明：以下均为**审查后基于现有能力缺口**提出的建议，不是已存在的功能。优先级综合"业务价值 / 实施成本 / 依赖前置"三项判断。P0 建议在完成 §0.2 的四个 P0 之后再启动。

### 6.1 P0 级（建议 1~2 个月内落地）

#### F1 数据质量闸门（Data Quality Gate）

- **作用**：把散落在 30+ 个 `validate_*` 巨函数里的校验规则，收敛为一张**可配置规则表**（`ops.data_quality_rule`）+ 统一执行器，覆盖"批次映射完整性、粒度唯一、金额勾稽、unmapped=0、跨层对账差异阈值"。规则命中即**阻断 ADS 刷新**并留痕。
- **预期价值**：直接根治 §2 与 §3 里最危险的一类问题——**部分脚本校验 unmapped=0 会 raise，部分只统计不拦截**（`etl/bank/run_bank_management_metrics_etl.py:418-465`），口径全靠人记。按当前 168 个刷新任务计算，一次脏数据进 ADS 的返工成本远高于建立规则中心的成本。
- **依赖**：无（可先用现有 `validate_*` 逻辑反推规则表）
- **成本**：中

#### F2 取数链路统一入口与健康巡检（Download Orchestrator Health）

- **作用**：为 Playwright DOM 链路与 ReverseAPI WebAPI 链路提供**统一入口 + 统一状态机**，并为 Cloak Login profile 增加"有效性/剩余登录态/店铺可访问性"巡检；下载失败自动重试、登录失效自动通知、产物完整性校验（非空、格式、行数、与预期报表类型匹配）。
- **预期价值**：直接消灭 PROJECT_STATUS.md 自认的两个未闭环项——"两条链路分工未定"与"登录态失效通知闭环"。这是当前唯一影响**每日数据是否到手**的功能，业务价值最高。
- **依赖**：A5/A7 先定分工；A8 硬编码路径先参数化
- **成本**：中高

#### F3 ETL 契约测试基线（Contract Test Baseline）

- **作用**：新建 `etl/tests/`，用参数化测试 + mock cursor 覆盖 4 条核心契约：`ods_file_loader` 主流程、`v_ingest_batch_shop_context` 解析、`pg_connection` 回滚路径（故障注入）、刷新 SQL 幂等性（临时库上跑两遍比对行数与指标值）。把"基线快照"从源码硬编码迁到 `data/baselines/*.json` 供测试读取。
- **预期价值**：`etl/` 当前测试数为 **0**，而 §3 建议的所有结构性重构（-6,500 行）在无测试保护下都无法安全实施。**这是所有后续优化的前置条件**，收益是"让其他优化变得可能"。
- **依赖**：无
- **成本**：中

### 6.2 P1 级（2~4 个月）

#### F4 指标对账与行级下钻（Reconciliation & Drill-down）

- **作用**：任一 ADS 指标值可一路下钻到 ODS 原始行与原始文件（ADS → DWS → DWD → ODS → `ods_file_ingest_log` 批次 → 文件），并展示每层金额的加总过程与差异项。
- **预期价值**：财务最高频的问题是"这个数字怎么算出来的"。当前虽有 ADS 与 DWS 的自动对账，但**人工解释一次差异要翻 SQL 与批次日志**。这是把"可审计"从口号变成可交付能力。
- **依赖**：批次上下文机制（已有）、血缘元数据（见 F7）
- **成本**：中高

#### F5 指标波动预警与归因（Anomaly Alert）

- **作用**：对 ADS 指标做日/月环比的阈值与统计双策略检测，异常时自动按"平台 × 店铺 × 费用类型 × 商品"分解贡献度，推送到飞书（项目已有 `apps/feishu_ai` 通道）。
- **预期价值**：把系统从"事后看板"升级为"主动告警"。例如推广费单日暴涨、某店铺结算净额为负，可在财务发现前触达。
- **依赖**：F1（需先保证数据质量，否则告警噪音淹没信号）
- **成本**：中

#### F6 上传自助预校验与错误行回吐（Ingest Preflight）

- **作用**：文件上传后、入库前先跑预校验（表头别名匹配、必填列、金额格式、日期范围、与已入库文件的重复检测），不合格直接拒绝并**回吐带行号的错误清单**（xlsx）。
- **预期价值**：`etl/common/ods_file_loader.py` 已具备表头别名与重复文件拒绝能力，但错误只以异常输出。把错误结构化回吐，可把"运营上传失败 → 找开发查日志 → 返工"的循环砍掉大半。
- **依赖**：无
- **成本**：低-中

#### F7 指标字典与血缘图谱（Metric Catalog & Lineage）

- **作用**：从 `sql/` 与 ETL 配置中**自动解析**出 ODS → DWD → DWS → ADS → 图表 的血缘，生成可检索的指标字典（口径、公式、负责人、刷新频率、依赖批次），并输出可交互图谱。
- **预期价值**：项目有 280 张表、168 个刷新任务、37 份 docs 说明，口径知识目前只存在于人脑与文档里。仓库里 `graphify-out/` 说明团队已有此需求，但那是代码级图谱且是死产物——**需要的是业务口径级血缘**。同时它是 F4 的前置元数据。
- **依赖**：D12（先理清"哪些 SQL 才是权威"）
- **成本**：中高

### 6.3 P2 级（半年内，按需启动）

#### F8 月度结账编排（Close-the-Books Orchestration）

- **作用**：把"月度结算净额 + 各平台费用 + 资金账户"打包为一个**带闸门的编排任务**，按依赖顺序执行、逐节点阻断、生成结账报告与差异说明。
- **预期价值**：当前刷新由 `nightly_scheduler` 按日触发，月度结账靠人工按序点。编排化可消除"顺序错导致的金额错误"（与 D14 同源风险）。
- **依赖**：F1、F3
- **成本**：中

#### F9 行级/字段级权限与金额脱敏

- **作用**：把现有 RBAC 扩展为**按公司/店铺的数据范围授权**，并对敏感金额字段做掩码；配套操作审计可视化。
- **预期价值**：项目已支持多公司主体（`dim_platform_shop_company` SCD2），但权限止于页面级——相同角色可见全部公司数据。多主体场景下这是合规硬需求。
- **依赖**：无
- **成本**：中

#### F10 预算达成与滚动预测（Budget vs Actual）

- **作用**：在已有 `finance_operating_configuration` 与 `dim_business_gmv_target_monthly` 基础上，提供预算 vs 实际达成、差异分解与滚动预测。
- **预期价值**：当前配置能力已存在但只做静态对照；把"目标 - 达成 - 差异归因 - 剩余期间预测"闭环，是财务经营分析的直接增值点。
- **依赖**：F5（归因能力复用）
- **成本**：中

#### F11 前端工程化与统一设计系统

- **作用**：为 `apps/` 引入最小编译（esbuild）与共享组件壳，拆分巨石脚本（`file_ingest/static/app.js` 169KB、`influencer_config/static/master-config.js` 68KB、`fund_split_adjust/static/app.js` 65KB），统一 `styles.css` 单一来源（当前 3 份内容不同且被跨目录歧义引用）。
- **预期价值**：降低前端改动风险与重复劳动；是 A2 巨石应用拆分的配套。
- **依赖**：无
- **成本**：高（但可增量进行）

#### F12 AI 问数增强（Conversational Analytics）

- **作用**：在现有只读 AI 分析（sqlglot 白名单 + 只读会话）基础上，扩展多轮会话式的指标追问、自动选择图表形态、对异常值给出口径级解释。
- **预期价值**：`apps/ai_analysis` 的安全底座已经打好（这部分比项目其他代码更严谨），是**边际成本最低的扩展**——把已有能力从"能问一句"提升为"能追着问"。
- **依赖**：F1（数据质量）、F7（口径字典）
- **成本**：中

### 6.4 功能优先级汇总

| 优先级    | 功能               | 核心价值               | 成本  | 依赖       |
| ------ | ---------------- | ------------------ | --- | -------- |
| **P0** | F1 数据质量闸门        | 防脏数据进 ADS，统一校验口径   | 中   | —        |
| **P0** | F2 取数链路统一入口与健康巡检 | 保障每日数据到手，闭环两个已知未决项 | 中高  | A5/A7/A8 |
| **P0** | F3 ETL 契约测试基线    | 让后续所有重构变得安全        | 中   | —        |
| **P1** | F4 对账与行级下钻       | 让"可审计"可交付          | 中高  | F7       |
| **P1** | F5 波动预警与归因       | 从事后看板到主动告警         | 中   | F1       |
| **P1** | F6 上传预校验与错误回吐    | 砍掉导入返工循环           | 低-中 | —        |
| **P1** | F7 指标字典与血缘       | 口径知识资产化，F4 的前置     | 中高  | D12      |
| **P2** | F8 月度结账编排        | 消除人工按序点单           | 中   | F1/F3    |
| **P2** | F9 行级权限与脱敏       | 多主体合规硬需求           | 中   | —        |
| **P2** | F10 预算达成与滚动预测    | 财务经营决策增值           | 中   | F5       |
| **P2** | F11 前端工程化        | 降低前端维护成本           | 高   | —        |
| **P2** | F12 AI 问数增强      | 边际成本最低的能力扩展        | 中   | F1/F7    |

---

## 7. 整改路线图

### 阶段一（1~2 周）：止血 —— 只做 P0，不做重构

1. 修复 A1 部署导入链断裂（先在本地 `docker build` 复现确认，再决定是下沉 `redact`/常量还是改为受保护导入）。
2. 轮换 `.env` 全部凭证（S1），下线密码可逆查看（S2）。
3. 版本库瘦身：移除 `node_modules`（U1）、`graphify-out`（U2）、`graphify-out`、`data/`、`ReverseAPI/downloads/`、`outputs/` 的跟踪（U6/U7）并补全 `.gitignore`。
4. 补齐根级依赖声明 + 锁文件（§4.3）。

### 阶段二（3~4 周）：去重与治理

1. 抽取 `etl/common/db.py`、`pipeline.py`、`webapi_common_base.py`、`playwright_common.py`（C1-C11），删除 8 个废弃脚本（-2,493 行）。
2. 建立 `etl/tests/` 契约基线（F3）——**必须在步骤 5 的每个抽取动作前后各跑一遍**。
3. 数据库层：分离可部署 DDL 与开发历史（D12）、合并 `dim_company_product_code_mapping` 的 22 次 ALTER（D14）、补热路径索引（D27）。
4. 引入连接池（P1）与并发上限（P2）。

### 阶段三（1~2 个月）：能力补齐

1. F1 数据质量闸门 → F2 取数链路统一入口 → F6 上传预校验。
2. 数据库：解决 6 组双刷新技术覆盖（D15）、统一批次类型（D7）、引入增量与分区（D26）。

### 阶段四（按需）：业务增值

1. F4 / F5 / F7 → F8 / F9 / F10 → F11 / F12。

---

## 附录 A：审查方法与置信度

| 方法                                                                   | 用途                                                                 |
| -------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 全仓 AST 解析（212 个 py 文件）                                               | 函数长度、未引用函数、第三方 import 清单                                           |
| 6 行滑窗 + MD5 跨文件克隆检测                                                  | 重复行占比 18.9%                                                        |
| `difflib.SequenceMatcher`                                            | 指定文件对相似度（如 xhs 资金/结算 81%）                                          |
| SQL 正则结构化统计                                                          | 表/视图/注释/约束/索引/序号/UNION/分区 计数                                       |
| `git ls-files` / `git log --all --full-history` / `git check-ignore` | 资产是否入库、密钥是否曾提交                                                     |
| 定向复现                                                                 | §0.2 五个 P0 已逐项复核（node_modules 计数、序号冲突、导入链、`.env` 变量强度与复用、敏感数据入库计数） |

**置信度说明**

- **高**：所有计数类结论、导入链断裂、序号冲突、`.env` 强度与令牌复用、版本库资产统计——均已直接复现。
- **中**：依赖 CVE 情况（本次未联网核对，仅记录版本策略现状）；`apps/shared_navigation` 的完整历史成因（仅确认当前零引用）。
- **需实机验证**：A1 生产容器是否真的启动失败（静态依赖链完整，但未经 `docker build` + 起容器确认）；`sql/ads/settlement_net/418_...` 是否真的从未部署。

## 附录 B：未纳入本次审查的范围

- DataEase 侧看板配置与数据集定义（仅审查了代理与配置表）
- Cloak Login 浏览器 profile 的实际内容与登录态
- PostgreSQL 实例侧的运行时状态（连接数、慢查询、表膨胀、`pg_stat_statements`）——**建议补一次数据库运行时体检**，它能把 §2.7 的性能推断从静态升级为实测
- 依赖 CVE 比对（需联网）
