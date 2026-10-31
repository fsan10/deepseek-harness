# 旧逻辑与失效代码审计报告

> 审计时间：2026-10-17
> 审计范围：`D:\fsan10\mock_coffice` 全仓库（排除 `.venv`、`.vendor`、`__pycache__`、`tmp/`、`.codex_tmp/`、`outputs/`）
> 扫描规模：392 个 Python 文件、53 个前端资源、468 个 SQL 文件
> 方法：AST 导入图 + ETL registry 路径比对 + 前端资源引用链 + 全仓 token 提及统计（脚本见 `.workbuddy/audit_scan.py`、`.workbuddy/audit_scan2.py`，均为只读）
> 本报告只做判定，**未修改、删除任何业务文件**

---

## 0. 结论摘要

### 0.1 一句话结论

项目**没有大面积腐烂**：ETL 注册表与磁盘脚本 100% 对齐（0 缺失），27 个活跃 loader 与 `ACTIVE_REPORTS` 完全匹配，`apps/` 下 58 个生产模块**全部至少被引用一次**。真正的问题集中在**三类**：

1. **配置/测试/文档指向已删除或已停用的对象**（4 处，会直接导致 CI 失败或误导维护者）；
2. **重构后被遗忘的旧实现**（`product-category.js` 759 行是最大一块）；
3. **两条并行下载链路**（Playwright 与 ReverseAPI WebAPI）职责重叠，且旧版兼容 ETL 是**完整实现复制**而非薄壳。

### 0.2 量化结果

| 指标 | 数量 | 说明 |
|---|---:|---|
| Python 文件（有效范围） | 392 | 含 apps / etl / scripts / ReverseAPI |
| 静态零 import 的 Python 文件 | 92 | **其中 87 个是"零 import 但活着"**：ETL 进程入口、运维脚本、探针 |
| 经人工验证的真死代码文件 | **4** | 合计 1,040 行 |
| 已停用但按设计保留 | 7 项 | 合计 2,555 行（含 2 个完整重复实现的旧兼容 ETL） |
| 一次性迁移/验收脚本 | 9 个 + 1 个 SQL | 合计约 1,977 行 |
| 配置/文档不一致点 | 4 处 | 含 1 处 CI 必失败 |
| 零引用 SQL | 26 | 均为 ODS 建表/一次性 DDL，**不建议删除** |

### 0.3 必须先知道的三个"别删"

| 对象 | 为什么不能按"零引用"删 |
|---|---|
| `sql/tmall/settlement_income/135_*`、`settlement_expense/139_*`、`settlement_net/143_*` | 仍被 `run_tmall_settlement_from_funds_etl.py:47-51` 引用，是 `legacy_available()` 分支的**受控旧结算路径**，删了会破坏"同月资金覆盖、无资金月份保留旧结算"的机制 |
| `influencer_commission` 这个词 | ETL key 已停用，但 `primary_category_code='influencer_commission'` 仍是**活跃的费用分类代码**（`run_douyin_platform_expense_etl.py:109,618`、`category_catalog` 测试），删分类会改变经营归属 |
| `scripts/production_db/*` 15 个"零 import"脚本 | 是正式库交付/清理/校验工具链，`scripts/production_db/README.md` 有完整可重复执行流程，**全部是活的** |

---

## 1. 判定标准（避免误读）

| 判定 | 含义 | 处置基调 |
|---|---|---|
| **D 死代码** | 无运行时引用、无业务价值、无文档依赖 | 可删 |
| **L 停用保留** | 被新实现取代，但通过 registry / 测试 / 文档刻意保留 | 需产品决策，不擅自删 |
| **H 历史资产** | 一次性迁移/验收脚本，已完成使命 | 归档，不删 |
| **A 活工具** | 零 import，但由命令行/运维流程/人工使用 | 保留，禁止按引用数判死 |
| **R 风险点** | 配置、测试、文档指向已不存在或已停用对象 | **必须修** |

> **关键方法论**：本项目的 ETL 不是 `import` 调用，而是 registry 里的**路径字符串 + subprocess**；loader 也是按路径约定执行。因此"零 import"在本项目里**默认不等于死代码**。92 个零 import 文件中只有 4 个经交叉验证确认为死。

---

## 2. 分析表 A：配置 / 测试 / 文档与实际架构脱节（P0，必须修）

| 编号 | 对象 | 位置 | 问题 | 证据 | 建议动作 | 优先级 |
|---|---|---|---|---|---|---|
| **R1** | CI 校验已删除文件 | `.github/workflows/automation-component-static.yml:27` | `node --check apps/automation_center/static/ops-center.js`，但该文件在 2026-10-17 五菜单重构中已删除 | `ls apps/automation_center/static/` 只有 app/common/flow-studio/reports/runtime 五个 JS，无 `ops-center.js` | 改为校验 `common.js`、`reports.js`、`runtime.js`；补上 `node --check` 对全部 5 个 JS | **P0** |
| **R2** | 测试仍在保护死文件 | `apps/common/tests/test_frontend_contracts.py:103-107` | `test_product_configuration_reports_before_background_refresh` 读取并断言 `product-category.js` 内容，制造"该文件仍有用"的假象 | 该测试只读文件文本，不验证页面加载；页面 `index.html:189-191` 只加载 `app.js` + `master-config.js` | 删除该测试方法，或改为断言 `master-config.js` 的等价逻辑 | **P0** |
| **R3** | 前端死调用 | `apps/influencer_config/static/app.js:475, 526` | `window.productCategoryModule?.activate()` —— 该全局对象由 `product-category.js` 定义，但页面从未加载它，可选链使调用**静默跳过** | `index.html` 无 `product-category.js` 的 `<script>`；全仓无动态 `import()` / `createElement('script')` | 删除这两处调用；确认品类面板由 `master-config.js`（`:220` 的 `productCategoryApp`）独立渲染 | **P0** |
| **R4** | 文档教人用旧的无认证入口 | `docs/ods_to_dws_to_ads_standard_flow.md:1304` | 仍写 `python apps/influencer_config/server.py --bind 127.0.0.1 --port 8765`，但生产已统一到 `apps/fund_split_adjust/server.py`（带 IAM/CSRF/审计） | 统一入口 `server.py:42` 挂载 `IdentityAccessModule`；旧入口的 `main()` 无任何认证 | 文档改为统一服务启动方式；旧 `main()` 见 B4 | **P1** |

> **补充**：`PROJECT_STATUS.md` 头部停在 `2026-09-10 / 32d086e8`，当前 HEAD 是 `68b3a95c`（2026-10-17 自动化工作台重构）。这份交接文档已整体过期，建议重新生成而非局部修补。

---

## 3. 分析表 B：确认可删除的死代码（P1）

| 编号 | 文件 | 行数 | 原用途 | 判定依据 | 建议 | 风险 |
|---|---|---:|---|---|---|---|
| **B1** | `apps/influencer_config/static/product-category.js` | **759** | 旧版"商品品类配置"页面脚本，定义 `window.productCategoryModule` | 页面未加载（见 R3）；唯一提及是测试文件（见 R2）；无动态加载；功能已由 `master-config.js` 覆盖 | **删除**（连同 R2/R3 一起改） | 低。删前用 `master-config.js` 跑一遍品类增删改冒烟 |
| **B2** | `etl/tmall/run_tmall_order_metrics_etl.py` | **102** | 天猫订单 ODS 变更后的"一键刷新"聚合入口 | 不在 `ETL_SPECS`；全仓仅 `docs/tmall_order_item_migration_implementation.md` 提及；内部 import 并执行**已停用**的 `influencer_commission` 链路（`:19-21`） | **删除**，或改造为只调用当前 4 个活跃 ETL 的薄壳 | 中。若保留，必须移除对 `influencer_commission` 的依赖，否则会跑停用链路 |
| **B3** | `scripts/auto_download/playwright/jigsaw_slider_demo.py` | **179** | 网易易盾滑块 iframe 坐标处理的**诊断示例** | 文件自述"基础示例，不自动识别缺口"；全仓零引用；无 CLI 入口被脚本调用 | **移到 `docs/` 或 `scripts/diagnostics/`**，不留在正式下载目录 | 低。纯示例，无生产依赖 |
| **B4** | `apps/influencer_config/server.py` 的 `build_parser()` + `main()` | 约 **50** | 达播配置页的**独立启动入口**（端口 8765） | 文件主体（`Database`、`parse_month`）被 `influencer_module.py:16-17` 复用，**不能删文件**；但 `main()` 无认证、与统一服务重复、仅旧文档引用（见 R4） | **删除 `main()`/`build_parser()` 与 `if __name__` 块**，保留服务类 | 低。删前确认无人用 `--port 8765` 独立启动 |
| **B5** | `apps/influencer_config/company_master_smoke_test.py`<br>`crud_smoke_test.py`<br>`product_catalog_crud_smoke_test.py` | 373<br>123<br>155 | 真实测试库上的手工冒烟验收 | 均不在 `tests/` 目录、不被 unittest 发现、全仓零引用 | **移入 `apps/influencer_config/tests/` 并改名为 `test_*`**，或删除 | 中。内含真实库写入与 `finally` 硬删逻辑，移动前确认清理边界 |

**B 类合计：约 1,741 行**（不含 B5 则为 1,090 行）

---

## 4. 分析表 C：已停用但按设计保留（需决策，不要擅自删）

| 编号 | 对象 | 规模 | 停用方式 | 证据 | 现状评估 | 建议 |
|---|---|---:|---|---|---|---|
| **C1** | `etl/influencer_commission/run_influencer_commission_etl.py` | **1,025 行** | `ETL_SPECS['influencer_commission'].enabled=False` | `registry.py:183-190`；`test_registry.py:152-159` 专门测试"停用但保留"；`plan_etls({'influencer_commission'})` 返回 `[]` | 完全无法被调度触发，但文件与 SQL 保留。看板已改用"统一平台费用 ADS 按一级分类汇总" | **保留**。若要删，先移除 `test_registry.py` 的契约测试，并确认历史月份不需要重算 |
| **C2** | `etl/platform_finance/run_douyin_ks_main_business_income_etl.py` | **754 行** | `enabled=True`，但列入 `FULL_REFRESH_EXCLUDED_ETLS` | `registry.py:172-180, 204`；note 写"保留旧脚本供历史任务兼容" | ⚠️ **不是薄壳**：内部有自己的 `PREPARE_SQL_FILES`/`CREATE_SQL_FILES` 和完整刷新逻辑，与新拆分的 3 个 ETL **并行维护**。新 ETL 修 bug 时旧入口不会同步 | 二选一：<br>① 改造成调用 3 个新 ETL 的薄壳（推荐，消除重复）<br>② 直接 `enabled=False` 并删除文件 |
| **C3** | `etl/platform_finance/run_pdd_wechat_xhs_main_business_finance_etl.py` | **601 行** | 同上 | `registry.py:161-168, 205` | 同上，完整重复实现 | 同上 |
| **C4** | `etl/tmall/load_tmall_fund_ods.py` | 40 | `DEPRECATED_LOADERS` | `registry.py:131`；`test_registry.py:20-37` 强制"磁盘 loader = ACTIVE + DEPRECATED" | 已不参与导入，保留仅为通过"loader 不得成为孤儿"的契约测试 | **保留**。这是有意识的归档，不是遗漏 |
| **C5** | `etl/xhs/load_xhs_fund_ods.py` | 40 | 同上 | `registry.py:132` | 旧"货款明细"格式，已切"资金账单明细" | 同上 |
| **C6** | `etl/xhs/load_xhs_settlement_income_ods.py` | 52 | 同上 | `registry.py:133` | 已切单文件多工作表分流 | 同上 |
| **C7** | `etl/xhs/load_xhs_settlement_expense_ods.py` | 43 | 同上 | `registry.py:134` | 同上 | 同上 |
| **C8** | `tmall_settlement_income` / `tmall_settlement_expense` 两个 ODS 导入 | — | 仍注册在 `ACTIVE_REPORTS`，但 note 标明"历史结算单已不再新增导入" | `registry.py:99-100` | **半活**：补导历史文件时仍需要，不能删 | 保留，但 UI 上可考虑标注"仅历史" |

**C 类合计：2,555 行**

### C 类的额外风险提示

`run_douyin_ks_main_business_income_etl.py` 与 `run_pdd_wechat_xhs_main_business_finance_etl.py` 这两个"旧兼容入口"虽然不在全量刷新里，但：

- 它们在 `ETL_SPECS` 里 `enabled=True`；
- 上传对应报表时，`etl_keys` 已改为指向新拆分 ETL（`test_registry.py:212-245` 有断言），所以**正常上传不会触发旧入口**；
- 但**手工按 key 触发**（运维脚本/API）仍会执行完整旧逻辑。

→ 这是当前项目里**最容易产生"两套口径"**的地方，建议优先处理。

---

## 5. 分析表 D：一次性迁移 / 验收脚本（历史资产，建议归档）

这些脚本的共同特征：`--apply` 前默认回滚预览、有 SHA256/manifest 校验、有详细 docstring，属于**一次性实施工具**。执行完即完成使命，但保留是有价值的审计证据。

| 编号 | 文件 | 行数 | 用途 | 引用情况 | 建议 |
|---|---|---:|---|---|---|
| **D1** | `etl/platform_finance/run_operating_policy_migration.py` | 61 | 经营归属策略迁移 | 零引用 | 归入 `etl/_migrations/`，或在 `docs/` 索引中标注"已执行" |
| **D2** | `etl/platform_finance/run_scene_normalization_migration.py` | 125 | 收支场景清洗规则迁移 | 零引用 | 同上 |
| **D3** | `etl/platform_finance/run_operating_treatment_migration.py` | 124 | 经营收支归属迁移 | 零引用 | 同上 |
| **D4** | `etl/platform_finance/rebuild_operating_categories.py` | 145 | 重建七平台经营分类（双次刷新校验） | 零引用 | 同上 |
| **D5** | `etl/platform_finance/reconcile_operating_sources.py` | 225 | 经营来源对账（回滚预览） | 零引用 | 同上 |
| **D6** | `etl/platform_finance/reconcile_settlement.py` | 325 | 结算文件 SHA256 manifest 对账 | 零引用 | 同上 |
| **D7** | `etl/operating_sales/validate_product_identity.py` | 389 | 只读验收公司商品识别/GMV 分摊 | 零引用 | 保留为验收工具，移入 `etl/_acceptance/` |
| **D8** | `etl/operating_sales/refresh_product_mapping_workbench.py` | 42 | 商品映射工作台刷新触发 | 零引用 | 可能仍被外部调度调用，**先确认再动** |
| **D9** | `etl/tmall/migrate_tmall_order_source.py` | 541 | 天猫主订单 ODS → 宝贝销售子订单 ODS 原子迁移 | 仅被自身 docstring/测试提及 | 保留为迁移证据，移入 `etl/_migrations/` |
| **D10** | `sql/dim/465_douyin_yinka_shop_postgres.sql` | — | 一次性 DIM 店铺补丁（音咖） | 零引用，`DO $$` 幂等 + 冲突即 `RAISE EXCEPTION` | 保留。这是"已执行的变更记录"，删了会丢失数据沿革 |

**D 类合计：约 1,977 行 + 1 个 SQL**

> **不建议删除 D 类的理由**：这些脚本记录了口径变更的**可复现过程**（双次刷新一致才算通过）。删掉后如果生产库出现口径争议，无法回放验证。归档成本几乎为零。

---

## 6. 分析表 E：零引用但仍是活工具（**禁止按引用数判死**）

这一组是本次审计最重要的"防误删清单"。

| 编号 | 对象 | 数量 | 零引用原因 | 实际使用方式 | 判定 |
|---|---|---:|---|---|---|
| **E1** | `scripts/production_db/*.py` | 15 | 运维脚本，不被业务代码 import | `python -m scripts.production_db.<name>`，`README.md` 有完整流程（audit / generate / bootstrap / cleanup / sync / validate） | **活** |
| **E2** | `scripts/deployment/healthcheck.py`、`init_admin.py` | 2 | 部署期一次性调用 | 容器 healthcheck / 初始化管理员 | **活** |
| **E3** | `scripts/ai_config/inspect_encrypted_config.py` | 1 | 运维排查工具 | 手工执行查看加密配置 | **活** |
| **E4** | `scripts/auto_download/playwright/douyin_date_picker.py` | 1 | 手工调试工具 | 文件头有完整 `--cdp` 用法示例 | **活**（工具） |
| **E5** | `ReverseAPI/Formal_Script/*.py` | 30 | 独立命令行链路，不被 `apps/` import | 各平台 WebAPI 下载脚本，`python <script> ...` | **活**（但与 E6 重叠，见 §8） |
| **E6** | `ReverseAPI/Test_Script/*.py` | 14 | 探针测试，非 unittest | 手工运行验证 WebAPI/抓包 | **活**（探针） |
| **E7** | `apps/fund_split_adjust/tests/verify_*.py` | 10 | 文件名不是 `test_*`，不被 unittest 发现 | 手工验收脚本（分账/金额恢复/层级归属/对账搜索） | **活**（手工验收） |
| **E8** | `apps/file_ingest/tests/finance_ui_preview_server.py`<br>`operating_ui_smoke.py` | 2 | 测试夹具 | 隔离的浏览器 QA，不连 IAM/PG | **活**（测试辅助） |
| **E9** | `apps/ai_analysis/tests/*.py` | 2 | 测试 | 安全与集成测试 | **活**（测试） |
| **E10** | `sql/**/ods/*.sql`（26 个零引用） | 26 | 建表脚本，已固化进 `scripts/production_db/generated/001_schema.sql` | 新环境重建/审计时作为源定义 | **归档保留** |
| **E11** | `scripts/production_db/generate_analysis_report.py`<br>`generate_final_delivery_report.py` | 2 | 一次性交付报告生成 | 已在交付阶段执行完 | **H 类**：可归档，不必删 |

> **E10 的准确性说明**：`001_schema.sql` 已包含 `ods.ods_douyin_order_raw` 等表（146 处匹配）。这些零引用 SQL 是"被快照覆盖的源定义"，不是死代码，但也不再参与自动部署。**建议保留**，仅在文档里注明"以 generated/001_schema.sql 为准"。

---

## 7. 分析表 F：仓库卫生与资产（P2）

| 编号 | 对象 | 规模 | 状态 | 风险 | 建议 |
|---|---|---:|---|---|---|
| **F1** | `apps/fund_split_adjust/.vendor/sqlglot` | **13 MB** | 三重提供（已安装 + vendor + requirements） | 版本漂移时不知用哪份 | 删除 `.vendor/sqlglot`，统一用已安装包 |
| **F2** | `.codex_tmp/` | **382 MB** | 已 gitignore，仍在磁盘 | 占空间；含 31 个一次性诊断脚本 | 确认后物理清理 |
| **F3** | `.uploads/` | **575 MB** | 已 gitignore | 上传临时文件 | 确认后物理清理 |
| **F4** | `.tmp/` | **598 MB** | 已 gitignore | 临时产物 | 确认后物理清理 |
| **F5** | `tmp/` | 4.4 MB | 已 gitignore | 79 个探针脚本（`probe_xhs_202609_*`、`overlap_audit_*`） | 保留到对账结论归档后清理 |
| **F6** | `data/`（59 个 xlsx/csv） | 60 MB | **已被 git 跟踪**，`.gitignore` 未覆盖 | 真实业务数据入库 | `git rm --cached` + 补忽略规则 |
| **F7** | `ReverseAPI/downloads/`（22 个） | 387 KB | **已被 git 跟踪** | 下载产物入库 | 同上 |
| **F8** | `outputs/`（2 个） | 8.1 MB | 目录已忽略但 2 个文件已跟踪 | 含员工姓名与绩效的 xlsx | `git rm --cached` |
| **F9** | `mock_coffice_architecture.html` + `.visual-check.json` | 746 KB | 已写入 `.gitignore` 但**仍被跟踪**（忽略规则对已跟踪文件无效） | 一次性渲染产物 | `git rm --cached` |
| **F10** | `design-qa.md` | — | 仍被跟踪 | 一次性设计 QA 记录，引用临时截图路径 `C:\Users\...\Temp\...` | 删除或移入 `docs/` |
| **F11** | 根级无 `requirements.txt` / `pyproject.toml` | — | 依赖仍未声明（`playwright`、`requests`、`websocket-client`、`msoffcrypto-tool`、`pytest`） | 新环境无法复现 | 建根级清单 + 锁文件 |

---

## 8. 独立议题：两条下载链路的重叠（架构级，非"死代码"但属"旧逻辑未退役"）

| 维度 | `scripts/auto_download/playwright/` | `ReverseAPI/Formal_Script/` |
|---|---|---|
| 方式 | Playwright 驱动 DOM 点击/导出 | 浏览器上下文内发 WebAPI 请求 |
| 规模 | 38 个脚本 + 28 个测试 | 30 个正式脚本 + 14 个探针 |
| 被谁调用 | `run_all_platform_downloads.py` / automation 组件 | **无人调用**，纯命令行 |
| 覆盖平台 | 7 平台全量 | 抖音/京东/快手/拼多多/天猫/小红书 |
| 当前定位 | 正式主线 | 混合链路（PROJECT_STATUS 称"尚需明确分工"） |

**判定**：两者都活着，但**同一报表存在两套实现**。这不是"死代码"，而是"旧逻辑没有退役"的典型形态 —— 风险在于口径不一致、修复只改一边。

**建议（P1）**：给 `ReverseAPI/Formal_Script` 明确角色定位，二选一：

1. **定为正式主线**：把 `run_all_platform_downloads.py` 的对应平台切到 WebAPI 脚本，Playwright 版降级为回退方案；
2. **定为实验链路**：整体移入 `ReverseAPI/experimental/`，并在 README 声明"不参与生产调度"，避免被误用。

不要维持"两套都叫正式"的现状。

---

## 9. 优先级处置清单

### P0（本周，纯配置/调用层修改，零业务风险）

| # | 动作 | 涉及文件 | 验证方式 |
|---|---|---|---|
| 1 | 修正 CI 的 `ops-center.js` 引用，补齐 5 个 JS 校验 | `.github/workflows/automation-component-static.yml:26-29` | `node --check` 全部通过 |
| 2 | 删除对 `product-category.js` 的死测试 | `apps/common/tests/test_frontend_contracts.py:102-107` | `python -m unittest apps.common.tests.test_frontend_contracts` |
| 3 | 删除 `app.js` 两处 `productCategoryModule` 死调用 | `apps/influencer_config/static/app.js:475,526` | 打开 `/influencer/#productCategoryPanel` 确认品类面板仍由 `master-config.js` 渲染 |
| 4 | 修正文档里的旧启动入口 | `docs/ods_to_dws_to_ads_standard_flow.md:1304` | 全文检索 `port 8765` 无残留 |

### P1（两周内，需小范围回归）

| # | 动作 | 涉及文件 |
|---|---|---|
| 5 | 删除 `product-category.js`（759 行） | 与 P0-2/3 同批提交 |
| 6 | 删除 `influencer_config/server.py` 的 `main()`/`build_parser()`（约 50 行） | 保留 `Database`/`parse_month` |
| 7 | 处理旧版兼容 ETL：改薄壳或停用 | `run_douyin_ks_main_business_income_etl.py`(754)、`run_pdd_wechat_xhs_main_business_finance_etl.py`(601) |
| 8 | 删除/改造 `run_tmall_order_metrics_etl.py`（含停用链路） | `etl/tmall/run_tmall_order_metrics_etl.py` |
| 9 | 明确 ReverseAPI 与 Playwright 的分工 | 见 §8 |

### P2（按节奏，低风险）

| # | 动作 |
|---|---|
| 10 | 3 个 smoke_test 移入 `tests/` 并改名 |
| 11 | 迁移/验收脚本归入 `etl/_migrations/`、`etl/_acceptance/` |
| 12 | 删除 `.vendor/sqlglot`（13 MB） |
| 13 | 清理已跟踪的构建产物与业务数据（F6-F10，`git rm --cached`） |
| 14 | 物理清理 `.codex_tmp` / `.uploads` / `.tmp`（约 1.55 GB，需确认） |
| 15 | 补根级依赖清单与锁文件 |

---

## 10. 审计可信度与局限

**已交叉验证的部分**

- ETL registry → 磁盘脚本：`etl_registered_missing = 0`（registry 中无指向不存在文件的条目）；
- `ACTIVE_REPORTS`(27) 与磁盘 `load_*_ods.py`：由 `test_registry.py:31-37` 强制相等，当前通过；
- `apps/` 生产模块：58 个全部至少被 import 一次，无孤儿服务模块；
- 前端资源：5 个页面加载的 14 个 JS/CSS 全部存在；仅 `product-category.js` 未被加载。

**局限（需人工确认的部分）**

1. **动态调用**：本项目大量使用路径字符串 + subprocess，静态分析无法覆盖运行时拼接的路径（已用"文件名全仓提及"二次校验，但仍可能漏）；
2. **业务语义**：`influencer_commission` 这类"ETL 停用但分类代码仍活"的同名不同义，只能靠人工判定，已在本报告 §0.3 标出；
3. **数据库侧**：未连接生产库核对 `ops.etl_task` 历史任务是否仍引用旧 ETL key，也未核对 `dim`/`ods` 表是否被外部系统直接查询；
4. **SQL 层**：26 个零引用 SQL 只做了"被 .py 提及"检查，未验证是否被 DataEase 数据集或人工脚本引用。

**建议的下一步验证**（不改代码）

```bash
# 1. 确认旧 ETL key 是否还有历史任务在跑
SELECT etl_key, status, COUNT(*) FROM ops.etl_task
WHERE created_at > NOW() - INTERVAL '90 days'
GROUP BY 1,2 ORDER BY 3 DESC;

# 2. 确认 influencer_commission 分类是否仍被经营归属使用
SELECT primary_category_code, COUNT(*), SUM(amount)
FROM dws.dws_platform_expense_shop_daily
WHERE primary_category_code = 'influencer_commission'
GROUP BY 1;

# 3. 确认 8765 端口旧服务是否还在运行
netstat -ano | findstr :8765
```

---

## 附录：扫描脚本

| 脚本 | 作用 |
|---|---|
| `.workbuddy/audit_scan.py` | AST 导入图、ETL registry 差集、SQL/前端零引用清单 |
| `.workbuddy/audit_scan2.py` | 全仓 token 索引，统计每个文件的"文件名提及次数" |
| `.workbuddy/audit_scan.json` / `audit_scan2.json` | 原始扫描结果（只读产物，可复跑） |

两个脚本均为纯标准库、只读，不修改业务文件；`.workbuddy/` 已在 `.gitignore` 中。
