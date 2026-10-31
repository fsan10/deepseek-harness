# Codex 实现评审：覆盖预检、逐日采信与重试修复

评审对象：`175956ce`（2026-10-21 00:25）、`c1da9433`（2026-10-21 09:07）
对照基准：`docs/2026-10-20-ingest-backfill-coverage-and-retry-design.md`
评审方式：逐文件读 diff + 跑测试（47 项全通过）+ 核对 SQL 依赖链

## 结论

**可以合并，且质量高于方案本身。** 四个问题的主干都已落地，比较口径、并发复核、快照一致性三处比原方案更严谨；抖音事故已用真实数据恢复并做了只读核验。

但有两处**必须补**：`settlement_sources --manifest` 仍是绕过全部新校验的旁路；快照新鲜度没有运行时守卫。两者都属于"下次事故还会咬人"的类型。

## 一、超出方案的部分（值得保留）

| # | 实现 | 为什么比方案好 |
|---|---|---|
| 1 | `fingerprint_rows` 用全业务字段多重集哈希 | 方案只要求"行数 + 主金额"，那会漏掉"行数金额相同但单据不同"。测试 `test_same_counts_and_total_do_not_prove_equality` 直接锁住这一点 |
| 2 | `preflight_token` + `activate` 双重复核（`old_digest`/`new_digest` + `selection_id`） | 方案只写了"校验预检是否过期"；这里把"预检→提交→激活"三段之间的来源变化全部拦住，且用内容哈希而非时间戳 |
| 3 | `own_batches` / `baseline_excluded_batches` | 新批次已写进 ODS 后再比"旧来源"，若不排除自己会把自己当基线。这个坑方案没写到，实现处理了 |
| 4 | `source_selection_cutoff` + `set_config` 事务级快照 | 方案 P2 才提到"逐日裁决要进快照"，实现连"commit 后复用同一 cursor 要重新 SET LOCAL"都测了 |
| 5 | `reuse_run_files` | 方案没有。历史文件已在 ODS，重新核对采信不必重传，直接解决 789–799 的死局 |
| 6 | `recover_legacy_ingest` 的"全等才自动、有差异则整体回滚" | 方案只给了人工路径；这里给了一条零风险自动路径，且失败时不产生半套结果 |
| 7 | 鉴权白名单（路径 + token 双重限制） | 方案只要求"source 由认证方式决定"，实现还额外限制了 Bearer 可访问的路径集合 |

实库验收（`docs/2026-10-21-douyin-legacy-retry-repair.md`）：355 条采信、173 个店铺日 0 差异、ODS/DWD/ADS 结算净额均为 1,663,321.02 元、ODS 摘要不变。这是"改完还验了"的完整闭环。

## 二、必须补（P1）

### 1. `settlement_sources --manifest` 仍是全量旁路

`etl/common/settlement_sources.py` 本轮只加了 `ensure_schema` 一行（接入 468 视图），`register_source()` 本身**没有改**：

- 仍不校验"声明区间是否被填满"；
- 仍不要求 preflight / `import_mode` / 操作人；
- 仍可被任何能跑 Python 的人调用。

后果：`replace_range` 的"仅人工 + 预检令牌 + 空日确认"在页面和 API 上是闭环的，但用这个 CLI 直接写 `settlement_source_registry` 可以完全绕过——声明 18 天、实际 3 天，decision 视图照旧按声明区间判宽者胜。

建议改法（任选其一，推荐 A）：

**A. 收敛为回执专用**：`register_source` 只接受 `evidence_type='automation_receipt'` 且必须能关联到 `ops.automation_artifact`；`user_confirmed` 一律走新的页面/API 采信链路。CLI 的 `--manifest` 保留但拒绝 `user_confirmed`。

**B. 在 CLI 内部补齐同样的校验**：调 `coverage.preview()` 再 `activate()`，不直接写 registry。

无论选哪个，都要加一条断言：`registry` 中每条 `user_confirmed` 记录必须存在对应的 `ingest_source_day_selection`。

### 2. 没有快照新鲜度守卫

`wallet_reconciliation.validate` 的报错里带了 `batch_cutoff`，但**没有带当前最大批次**，也没有 `snapshot_stale` 标记。用户看到 `missing=1` 仍然无法判断"是数据没到"还是"快照没打开"。

建议：`_run_etl_task` 注入 context 前查一次

```sql
SELECT platform_code,COUNT(*) FROM ods.ods_file_ingest_log
WHERE batch_id > %s AND ingest_status='success' GROUP BY 1
```

命中则打 `[STALE_SNAPSHOT]` 并在失败信息末尾追加"快照上界 776，此后已成功导入 jd 1 个批次（779）"。这是纯观测改动，风险为零。

## 三、建议补（P2）

| # | 问题 | 建议 |
|---|---|---|
| 3 | 前端 `retryEtlTask` 固定 `snapshot_policy:'latest'`，后端支持的 `replay` 无入口 | 详情页给两个按钮，并在按钮旁显示"快照 ≤ 776 / 当前 779"；否则"重试"与"按最新重跑"在用户视角仍是同一个动作 |
| 4 | `wallet_reconciliation` 的 `settlement_batch_count` 实际是**结算单据组数** | 改名 `settlement_group_count`，另输出 `settlement_batches`（distinct batch_id + 日期范围），否则和文档里的"批次清单"对不上 |
| 5 | 资金只有 `fund_extract_to`（最大日），没有覆盖起点 | 增加 `fund_coverage.low`：`expected_wallet_date < low` 应报"资金文件未覆盖该段"，而不是 `missing` |
| 6 | `expected_wallet_date` 从 SQL 改为 Python 解析，丢掉了 `^20[0-9]{6}$` 前缀约束 | 加一条 `merchant[:4]=='20'` 守卫，避免 `1999…` 被判成日期 |
| 7 | `_resolve_shop` 不再允许文件名识别店铺，无过渡期 | 发布说明里点名"未传 `shop_code` 的旧客户端会 400"；错误文案已足够清楚，建议再加一个 `code=SHOP_CODE_REQUIRED` 便于脚本识别 |
| 8 | `retry_refresh_context` 只保留原 months/shops，不做并集 | 语义是安全的（只重算原范围），但要在 UI 上写明"不会扩展到新月份"；否则补了 9 月数据的用户会以为重试能覆盖 |

## 四、验证记录（本轮实跑）

```
apps.file_ingest.tests.test_coverage_workflow.ContentComparisonTests   5 passed
apps.file_ingest.tests.test_coverage_workflow.CoverageDatabaseTests   25 passed (14.2s)
scripts.auto_download.tests.test_ingest_api                            4 passed
etl.common.tests.test_finance_sources                                 13 passed
```

`test_etl_recovery` 的 15 项 DB 用例因"disposable PostgreSQL database required"跳过（需显式环境变量），未计入。

覆盖到的关键场景与测试名一致：空日不得静默清除旧行、同额同单不等于同一笔、令牌不能授权变更后的来源、旧快照执行 replay 不改来源、复用草稿不删原文件、资金基线先排除新批次再选旧版本。

## 五、运维状态（本次已核实，无需用户再查）

| 检查项 | 结果 |
|---|---|
| `common.ingest_source_day_selection` | 存在 |
| `common.v_ingest_source_day_selection` | 存在 |
| `common.v_selected_douyin_fund_raw` / `v_selected_jd_settlement_raw` | 均存在 |
| `ops.ingest_run.coverage_result` / `ops.etl_run.parent_etl_run_id` | 均存在 |
| 后端进程 | PID 22212，启动于 **2026-10-21 09:09:09**，晚于 `c1da9433`（09:07:54），已加载全部新代码 |
| 监听端口 | 8770（控制台）、8101（DataEase 代理） |

生产库已有采信记录 **369 条**：

| 平台 | 表 | 记录数 | 最晚业务日 |
|---|---|---:|---|
| douyin | `ods_douyin_fund_raw` | 188 | 2026-10-20 |
| douyin | `ods_douyin_settlement_raw` | 179 | 2026-10-20 |
| jd | `ods_jd_fund_raw` | 1 | 2026-10-20 |
| jd | `ods_jd_settlement_raw` | 1 | 2026-10-19 |

同时 `common.settlement_source_registry` 里仍有 **20 条 `user_confirmed`**（快手 739–741 那次及更早的抖音手工登记）。它们没有对应的 `ingest_source_day_selection` 记录，靠 436 的 `winner` 分支兜底生效。这正是 P1 第 1 项指出的"两套并存"现实：新链路已经跑起来，但老的口子还开着。
