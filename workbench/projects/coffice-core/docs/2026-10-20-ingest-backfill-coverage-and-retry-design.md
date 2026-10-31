# 补跑、覆盖声明与重试机制：问题分析与落地方案

> 编写日期：2026-10-20
> 范围：文件导入（`apps/file_ingest`）、增量刷新快照（`etl/common/refresh_runtime.py`、`apps/file_ingest/refresh_scope.py`）、结算来源选择（`etl/common/settlement_sources.py`、`sql/common/436_*`）、京东钱包对账（`etl/jd/run_jd_main_business_finance_etl.py`）、自动化补跑（`apps/automation_center/report_center.py`）。
> 本轮仅输出方案，不修改任何代码、数据与任务。

---

## 0 结论摘要

四个问题不是四个独立缺陷，而是同一套机制里三个层次混淆的结果：

| 层次 | 是什么 | 现状 |
|---|---|---|
| **事实层** | ODS 原始流水 | 设计正确：只追加、按 SHA256 防重、永不改动 |
| **声明层** | "这份文件完整覆盖了哪几天" | **缺位**。只有 CLI 能登记，网页/API 无法表达，且登记只校验"明细不越界"，不校验"区间被填满" |
| **选择层** | "某个店铺某一天，以哪份事实为准" | 规则存在但只有"阻断"一种出口，没有"人工裁决"出口 |
| **快照层** | "这次刷新能看到哪些批次" | 冻结过头：重试复用旧快照、上游不级联，导致数据到了也读不到 |

由此推出的四条主结论：

1. **补跑缺口可以精确计算，但"整月重传"缺少表达渠道。** 补跑日历已能算出缺失日（`report_center.preview_report_batch`），真正缺的是"我这份文件覆盖 10-01~10-18"这一句声明，以及声明前的**影响预检**。
2. **"以最新整月为准"应实现为"切换权威版本"，而不是"复制一份数据"。** 现有 decision 视图已支持"宽范围胜窄范围、同范围取最新"，只要补上声明与冲突裁决入口，语义立刻成立；不需要动 ODS。
3. **京东重试必然失败，是三个叠加原因，不是资金没到。** 主因是 `retry_etl_task()` 不复位 `ops.etl_run.refresh_context`，次因是上游 DWD 节点不级联、对账只取"最新单批次"。
4. **三个上传入口共用同一个落库函数，但校验强度、幂等要求、错误反馈完全不同。** 收敛为一个契约、三种投递方式即可；差异只允许出现在认证与默认值来源。

另外发现一个**未被讨论但风险更高**的漏洞，建议优先修复：

> `register_source()` 只校验"明细日期落在声明区间内"，**不校验声明区间内每一天都有明细**。因此可以声明"覆盖 10-01~10-18"、实际上传的却是只有 10-01 一天的文件；系统会接受，并让这份文件在该区间内**覆盖掉 17 天的旧来源**（decision 视图按声明区间判胜），最终这些日期的数据静默变成空。当前抖音 11 个批次正走在这条路径的入口上。

---

## 1 现状机制：事实链与证据索引

### 1.1 一次上传到指标刷新的完整链路

```
网页/API/CLI
  └─ POST /api/ingest/runs                     创建会话（idempotency_key 必填）
  └─ POST /api/ingest/runs/{id}/files          逐文件上传 → ops.ingest_file_task
       ├─ SHA256 与 ods.ods_file_ingest_log 比对 → status=duplicate / uploaded
       └─ DIM 解析店铺公司 → resolved_* / shop_identity_key
  └─ POST /api/ingest/runs/{id}/complete       文件数齐备 → status=ready
        └─ Worker 领取 → 逐个 loader 写 ODS → 记 ods_file_ingest_log(batch_id)
        └─ 汇总本次成功文件的 report_type → create_etl_run(trigger_type='ingest_complete')
              └─ build_refresh_context() 冻结 batch_cutoff / months / shops
                    └─ 每个 etl_task 子进程继承 MOCK_COFFICE_REFRESH_CONTEXT
                          └─ ODS 读取被替换为 pg_temp 视图 WHERE batch_id<=cutoff
```

### 1.2 关键代码位置（实施时逐条核对）

| 能力 | 位置 | 现状要点 |
|---|---|---|
| 结算覆盖登记 | `etl/common/settlement_sources.py:42-74` | 仅 CLI；校验文件存在+哈希、行数完整、明细不越界；**不校验区间填满** |
| 覆盖前置校验 | `etl/common/settlement_sources.py:112-172` | 冲突即 `RuntimeError('结算来源覆盖不明或范围交叉…')`，无消解出口 |
| 有效来源判定 | `sql/common/436_*:69-102` | 宽范围胜窄范围；同范围取 `(started_at,batch_id)` 最新；两来源均未声明时互不覆盖→同时生效→冲突 |
| 快照冻结 | `apps/file_ingest/refresh_scope.py:31-38` | `MAX(batch_id) WHERE success` 作为上界，失败批次进排除表 |
| 快照复用 | `apps/file_ingest/refresh_scope.py:149-158` | `refresh_context` 非空直接返回，**永不重算** |
| 快照生效 | `etl/common/refresh_runtime.py:227-234` | ODS 全部替换为 `WHERE batch_id<=cutoff AND NOT excluded` |
| 手工全量旁路 | `etl/common/refresh_runtime.py:127-140` | `mode='full'`（仅 manual）→ 谓词 `TRUE`，**不加批次过滤** |
| 节点重试 | `apps/file_ingest/service.py:1118-1133` | 只把 task/run 置 queued，**不动 refresh_context、不动上游** |
| 上游 DWD 重建 | `sql/jd/platform_expense/321_*:1` | `TRUNCATE` 全量重建，源表被临时视图限制在 cutoff 内 |
| 京东钱包对账 | `etl/jd/run_jd_main_business_finance_etl.py:500-560` | `latest_settlement_batch` 用 `MAX(ingest_time)` 取**单一批次** |
| 上传落库 | `apps/file_ingest/service.py:442-560` | hash 去重；同 run 内 hash 去重；无声明字段 |
| 全重复收口 | `apps/file_ingest/service.py:3242-3248` | success 数为 0 → `no_change`，`keys` 为空 → 不刷新任何指标 |
| 三入口鉴权 | `apps/file_ingest/module.py:52-61,108-125` | 仅 `source∈{api,robot}` 校验 Bearer；`manual` 不校验 |
| 补跑缺口计算 | `apps/automation_center/report_center.py:610-668` | 按日历缺失日生成计划，支持"按执行日期还原实际请求期间" |
| 表头范围解析范例 | `etl/common/report_sources.py:53-101` | 拼多多 CSV 头 `起始时间/终止时间`+全量落在区间+必须整日 → 可复用范式 |

### 1.3 与既有分析的对照

Codex 给出的定位方向是正确的，本方案在此基础上补足代码级事实：

| 既有结论 | 核对结果 | 本方案的补充 |
|---|---|---|
| 抖音：11 个批次缺覆盖登记，与旧日批次重叠触发保护 | 成立 | 补充"登记通道只有 CLI"与"登记不校验区间填满"两个缺口；后者风险更高 |
| 抖音：不能据文件名或末笔日期推断范围 | 成立，且必须坚持 | 补充"可验证的替代证据"：逐日行数/金额与旧来源交叉比对，不依赖文件名 |
| 京东：失败会话来源上限固定为批次 776，读不到 777 | 成立 | 指出**为什么重试也不会变**：`retry_etl_task` 不复位 context；即便复位，scope 仍绑定旧会话；即便 scope 变了，上游 DWD 也不会重建 |
| 京东：后续会话已成功，旧会话保留失败记录 | 成立 | 补充"对账只取最新单批次"这一独立缺陷，会影响分批上传场景 |
| 两批文件均已成功入库 | 成立 | 补充"全重复文件不触发任何刷新"的第三种无效路径 |

### 1.4 现有设计里值得保留的部分

- ODS 不可变、同 hash 不重复写入 —— 不能为了"覆盖"去删数据。
- `period_start/period_end` 由"声明+证据"给出，禁止用文件名或末笔日期推断 —— 这条红线必须保留。
- `refresh_context` 冻结可避免"运行中途混入新批次"导致指标前后不一致 —— 语义正确，问题在"重试也沿用"。
- 冲突时阻断而不是静默取一 —— 方向正确，问题在"阻断后无路可走"。

---

## 2 问题一：补跑与重叠处理

### 2.1 问题分析

现象：自动化失败若干天，无法确定具体缺哪几天，于是手动下载 10-01~10-18 整段上传，刷新被"结算来源覆盖不明或范围交叉"拦下。

事实链：

1. 手动上传的文件是**结算明细**，进入 `ods.ods_douyin_settlement_raw`，写入 `ods_file_ingest_log` 得到批次 789~799。
2. 这些批次**没有** `common.settlement_source_registry` 记录，`period_start/period_end` 为 NULL。
3. 10-12 等日期上已存在旧的日结算批次（如 188）。此时有两种情况，结果相同：
   - 旧批次由自动化回执登记过范围 → 它带 `period_start=period_end=10-12`，新批次无区间，二者互不覆盖；
   - 旧批次同样未登记 → 两个 NULL 之间也无法互相判胜（`BETWEEN NULL AND NULL` 恒为 NULL）。
4. `v_settlement_source_decision` 判定：新批次区间未知，无法覆盖旧批次；旧批次也无法覆盖新批次（新版无区间，无法被判"更宽"）。两者同日同时 `is_effective`。
5. `prepare_settlement_sources` 的最终检查（`settlement_sources.py:161-166`）按 `(shop, table, stat_date)` 统计 `COUNT(DISTINCT source_group_key)>1` 命中 → 抛错。
6. 三个任务（结算指标、平台支出、主营收入）都调用同一 gate（`etl/common/finance_sources.py:147-153`），第一个失败，其余因依赖未成功被 `skipped`。

**结论**：拦截是正确行为，缺的是"如何把这份文件的覆盖范围合法地告诉系统"。这个缺口在 2026-10-20 快手验收里已经原样出现过一次（`docs/etl_incremental_refresh_acceptance_20261020.md`：739/740/741 三个批次人工登记范围后重试通过），说明它是**机制性缺失，不是偶发**。

同时必须指出反向风险：一旦放开了"随便登记区间"，就会出现第 0 节所述漏洞 —— 声明 18 天、实际只有 1 天，17 天旧数据被静默覆盖。**所以"允许声明"必须与"声明可验证"同时上线，不能只做一半。**

### 2.2 设计原则

| 编号 | 原则 | 含义 |
|---|---|---|
| P1-1 | 补跑优先于重传 | 能算出缺口就用补跑；只有"缺口无法定位"或"平台侧只有整段导出"时才走整段上传 |
| P1-2 | 声明与事实分离 | 声明只改变"哪份事实被采信"，绝不改动 ODS 行 |
| P1-3 | 声明必须先预检后生效 | 任何声明都要先算出"会覆盖谁、会空掉哪几天、差多少钱"，再允许提交 |
| P1-4 | 空日零容忍 | 声明区间内"新文件无数据、旧来源有数据"的日期默认阻断，除非逐日确认 |
| P1-5 | 宽范围不等于免检 | 宽范围只解决"包含关系"，不解决"内容完整性" |
| P1-6 | 证据强度可达可降 | 自动化回执 > 文件内声明 > 人工确认；强度影响同范围裁决，不影响包含裁决 |

### 2.3 处理流程

#### 流程 A：先判断"该补跑还是该整段上传"

```
入口：报表日历 / 上传页
  │
  ├─ 步骤1 计算缺口
  │    GET /api/automation/report-calendar?month=2026-10&date_basis=business
  │    对每个 (profile, report_type)：列出 status ∈ {missing, failed, stale} 的业务日期
  │    ├─ 缺口可枚举（≤N 天，且任务可单日重跑）→ 走【流程 B 补跑】
  │    └─ 缺口不可枚举（平台只提供区间导出 / 缺口>阈值 / 报表无单日粒度）→ 走【流程 C 整段上传】
  │
  └─ 步骤2 记录选择理由（写入 run.intent 与 note，供审计）
```

判定阈值建议：缺口 ≤ 7 天且报表 `module` 不在 `SINGLE_DAY` 例外清单 → 补跑；否则整段上传。阈值放配置，不硬编码。

#### 流程 B：补跑（保持现状，仅补可见性）

```
POST /api/automation/report-batches/preview   → 计划、跳过的日期、预计文件数
POST /api/automation/report-batches           → 建批次，逐 profile 建 run
     每个 run 的 step 只针对缺口日期，business_date_start/end 由 business_period() 给出
     下载成功 → artifact(coverage_verified=true, business_date_start/end)
     → 导入 → ingest_run → etl_run(cutoff=当时水位)
```

需要补的两点（不是重写，是补字段）：

- 预览结果里增加 `coverage_plan`：每个 profile 将请求的区间、预计覆盖天数、与既有来源是否重叠。
- 补跑产生的新批次自动带 `automation_receipt` 证据，无需人工登记 —— 这条现有代码已经能做（`backfill_receipts`，`settlement_sources.py:77-109`），只要回执的 `business_date_start/end` 完整。

#### 流程 C：整段上传（新增能力）

```
① 建会话：intent = incremental | supersede
   POST /api/ingest/runs {source, expected_file_count, intent, idempotency_key}

② 上传文件（三入口共用同一契约，见第 5 节）
   —— 此时只落 ops.ingest_file_task，不写 ODS

③ 提交前预检（新增，只读）
   POST /api/ingest/runs/{id}/coverage-preflight
   body: {items:[{file_task_id, coverage_start, coverage_end, evidence_type, empty_days[]}]}
   → 返回 PreflightReport（见 2.4）

④ 依据预检结果分三种出口
   PASS      → 允许 complete，自动登记声明（registry, evidence_type=user_confirmed）
   REVIEW    → 前端展示逐日差异，要求选择 keep_old / take_new / 逐日裁决
   BLOCK     → 禁止 complete，提示补齐文件或逐日确认空日

⑤ complete → loader 写 ODS → create_etl_run
       若 intent=supersede，刷新上下文额外携带 supersede_batches 列表，
       使本次运行的来源选择无视旧版本（仍需通过空日校验）
```

### 2.4 预检报告结构（PreflightReport）

```jsonc
{
  "run_id": "...",
  "verdict": "PASS | REVIEW | BLOCK",
  "items": [{
    "file_task_id": "...", "shop_identity_key": "...", "target_table": "ods_douyin_settlement_raw",
    "claimed": {"start": "2026-10-01", "end": "2026-10-18", "evidence_type": "user_confirmed"},
    "actual":  {"min_date": "2026-10-01", "max_date": "2026-10-18", "rows": 33767},
    "days": {
      "matched":   ["2026-10-01", "..."],          // 新=旧（行数与主金额一致）
      "new_only":  ["2026-10-02"],                  // 纯补齐，最理想
      "diff":      [{"date":"2026-10-12","new_rows":412,"old_rows":398,
                     "new_amount":"18204.11","old_amount":"17905.20",
                     "doc_no_only_new":14,"doc_no_only_old":0}],
      "empty_new": ["2026-10-15"],                  // 新无、旧有 → 高危
      "empty_both":["2026-10-16"]                   // 两边都无 → 不影响
    },
    "covered_batches": [{"batch_id":188,"period":["2026-10-12","2026-10-12"],
                         "evidence":"automation_receipt","rows":398}],
    "impact": {"months":["2026-10"],"etls":["douyin_settlement",
               "douyin_platform_expense","douyin_main_business_income"],
               "affected_rows_estimate": 33767}
  }]
}
```

判定规则：

| 条件 | verdict | 处理 |
|---|---|---|
| 存在 `empty_new` 且未在 `empty_days` 中确认 | `BLOCK` | 拒绝提交，提示"10-15 旧来源有 398 行，本次文件无数据，疑似漏导" |
| 存在 `diff` 且未指定裁决 | `REVIEW` | 要求选 keep_old / take_new / 逐日 |
| 仅 `matched` + `new_only` + `empty_both` | `PASS` | 可直接提交 |
| `actual` 超出 `claimed` | `BLOCK` | 与 `register_source` 现有校验一致 |

`empty_both` 单独列出，是为了让用户看到"这段区间平台确实没有交易"，而不是被静默跳过。

### 2.5 边界情况

| 场景 | 处理 |
|---|---|
| 声明区间内首/末日本身无交易（如 10-01 是节假日） | 允许，但需在 `empty_days` 显式记录，并在后续复核时保留 |
| 同一会话内同一店铺同报表传了两份不同内容（如 10-01~10-10 与 10-01~10-18） | 预检按"并集"计算，宽者覆盖窄者的重叠日；若两份内容在同一天不一致 → `REVIEW` |
| 同一会话内重复上传同一文件（hash 相同） | 现有行为保持：`duplicate`，不写 ODS；但预检仍把它计入声明（见问题二） |
| 声明跨月（10-25~11-05） | 允许，`months` 取两月；预检按自然月分段展示 |
| 声明含未来日期 | `BLOCK`：`coverage_end > 平台数据可得日（今日-1）` |
| 声明区间与明细倒挂（`start > min_date`） | `BLOCK`：说明文件含声明外数据，声明不成立 |
| 文件在登记后被移动/删除 | 现有 `register_source` 会因文件不存在而拒绝；新增声明改为"登记时立即计算并持久化 `file_hash`+`row_digest`"，后续复核只依赖哈希不依赖路径 |
| 旧来源本身也是人工声明且无回执 | 降级为 `user_confirmed`，同范围时按版本新旧裁决 |
| 平台事后补结算（同一结算日后续新增行） | 属正常业务变更，走 `supersede`（问题二），不走 `incremental` |
| 空文件中含表头但 0 行 | 视为 `empty_new`（全部日期），必须逐日确认或拒绝 |

### 2.6 本节用户可见结果

上传提交后固定返回三段：

```
覆盖声明：2026-10-01 ~ 2026-10-18（人工确认）
  ✅ 完全一致 12 天
  ➕ 新增补齐  2 天（10-02、10-03 此前无来源）
  ⚠️ 存在差异  1 天（10-12：本次 412 行/¥18,204.11，既有 398 行/¥17,905.20）
  ⛔ 疑似漏导  0 天
影响范围：抖音 3 店 · 2026-10 · 3 个指标任务 · 预计 33,767 行
将覆盖既有批次：188、201、…（共 11 个，均为自动化回执）
```

---

## 3 问题二：整月数据冲突与"以最新为准"

### 3.1 问题分析

用户描述有两个不同现象，必须分开处理：

**现象 A：上传后发现全部是重复数据。**
`save_upload` 以 `SHA256 + platform_code + shop_identity_key + target_table` 判定重复（`service.py:493-504`）。全部重复时 `success_count=0` → `final_status='no_change'`，且 `keys` 为空 → `create_etl_run` 不产生任何指标任务（`service.py:3243-3248`）。用户看到"上传成功/无变化"，但系统什么都没做，也**没有任何入口表达"我就是要以这份为准"**。

**现象 B：每天上传的数据与财务数据对不上，想以整月为准。**
这不是"重复"，而是"同一业务日存在两个内容不同的事实版本"。当前 decision 视图能裁决（宽范围胜窄范围、同范围取最新），但前提是**两份都有声明**；只要有一份没声明，就会落到"冲突阻断"。

两者的共同缺口是：**系统没有"权威版本切换"这一动作**。现有模型只有"新增一份事实"，没有"让某份事实成为该区间唯一权威"。

### 3.2 设计原则

| 编号 | 原则 | 含义 |
|---|---|---|
| P2-1 | 切换权威，不复制事实 | `supersede` 只改声明状态与选择结果，ODS 行数不变 |
| P2-2 | 覆盖必须有清单 | 提交前必须列出将被覆盖的批次、日期、行数、金额差异 |
| P2-3 | 覆盖可回滚 | 每次 supersede 产生一个 revision，可一键回到上一 revision |
| P2-4 | 差异必须归因 | 差异日要给出"可能原因"提示（导出时点早于补结算 / 文件截断 / 币种与含税口径） |
| P2-5 | 默认保守 | 未明确选择时一律 `keep_old`，绝不默认覆盖 |
| P2-6 | 全部重复 ≠ 无事发生 | 内容相同但用户声明了范围时，仍应更新声明与优先级并重算 |

### 3.3 冲突判定标准（唯一口径）

对同一 `(shop_identity_key, target_table, stat_date)` 的候选来源集合 `S`：

```
若存在 selection 记录            → 按 selection（最高优先级，人工裁决）
否则若 S 中恰有一个来源         → 该来源生效
否则若存在 c∈S 使 c.period 严格包含 S 中其它所有来源的 period
      → c 生效（宽者胜）
否则若 S 中多个来源 period 完全相同
      → evidence_strength 高者胜；同强度取 (started_at, batch_id) 最大者
否则若存在交叉但不包含
      → 冲突（阻断），进入裁决
否则（全部 period 为 NULL）
      → 若 |S|=1 生效；否则冲突（阻断）
```

`evidence_strength`：`automation_receipt=3`、`report_header=2`、`user_confirmed=1`。

补充约束（防止宽范围滥用）：

```
c 生效的前提是 c 通过完整性校验：
  - c.actual_min <= c.period_start 且 c.actual_max >= c.period_end 且 empty_new 为空
    → 即"区间被填满"
  - 若 c 有 empty_days 声明，则 empty_days 内不得出现旧来源有数据的情况
未通过完整性校验的来源，其 period 视为 NULL（不参与"宽者胜"）
```

这一条是第 0 节漏洞的补丁，也是 supersede 的安全前提。

### 3.4 处理流程

#### 流程 A：内容全重复，但要求以本次为准

```
上传 11 个文件 → 全部 duplicate（hash 命中批次 789~799）
  │
  ├─ 若 run.intent=incremental
  │     → 结果：no_change，提示
  │       "11 个文件与既有批次 789~799 内容完全一致，未写入新数据，也未触发刷新。
  │        如需以这批文件为准重算，请选择【以本批为准】（会更新覆盖声明并重算 10 月）。"
  │
  └─ 若 run.intent=supersede
        → 不新增 ODS 行
        → 为既有批次创建新的 coverage claim revision（revision+1，claimed_by=本次 operator，
          evidence=user_confirmed，note='整月重传以最新为准'）
        → 预检照常执行（因为内容相同，empty_new 必为空，diff 必为空 → PASS）
        → 触发一次 affected 刷新：months=声明区间覆盖的月份，shops=本批店铺
        → 结果："已切换权威版本（revision 2），重算 3 个指标，0 行数据变化，金额无差异"
```

关键点：**内容相同不等于不用重算**。用户可能就是因为"上游指标算错了"才重传，所以 supersede 必须触发重算，且必须告诉用户"数据没变、只是重算"。

#### 流程 B：内容不同，需要裁决

```
预检返回 REVIEW（diff 日 N 天）
  │
  ├─ 用户选【以本次为准】
  │     → 新批次登记 supersede claim（revision+1）
  │     → 旧批次标记 claim_status='superseded'，superseded_by=新批次
  │     → 重算受影响月份
  │     → 结果需列出：被替代批次、替代前后金额差（按店铺/按日）、重算指标清单
  │
  ├─ 用户选【保留旧来源】
  │     → 新批次的 claim 裁剪为"仅缺口日"（period 变为离散日期集合）
  │     → 只补 new_only 的日期，diff 日保持旧来源
  │     → 结果："本次仅在 2 天生效，1 天差异日保留旧来源"
  │
  └─ 用户选【逐日】
        → 生成 selection 记录，按日指定
        → 结果需列出每一天的选择
```

裁剪为"离散日期集合"意味着 registry 的 `period_start/period_end` 不够用，需要支持多段。两种实现：

- **方案一（推荐）**：新增 `common.settlement_coverage_range(batch_id, range_start, range_end)` 子表，一个批次可有多段；`period_start/period_end` 保留为"最外层包络"，用于快速过滤。decision 视图改为按 range 判定。
- 方案二：为每个缺口段生成一条"虚拟 claim"，需要伪造 batch。不可取。

方案一改动集中在视图与登记，ODS 与 loader 不动。

#### 流程 C：回滚

```
POST /api/ingest/coverage-claims/{claim_id}/revert
  → claim_status='revoked'，上一 revision 恢复 active
  → 触发受影响月份重算
  → 结果："已回退到 revision 1（批次 188/201/… 生效），10 月重算完成，金额回到 ¥X"
```

回滚必须重算，否则 ADS 与来源不符。

### 3.5 边界情况

| 场景 | 处理 |
|---|---|
| supersede 的目标区间与另一个 supersede 区间重叠 | 冲突，需先回滚其中一个；不允许两个 active supersede 覆盖同一天 |
| supersede 后新批次被判定 empty_new | `BLOCK`，不允许用不完整文件替代完整来源 |
| 旧来源是自动化回执、新来源是人工确认 | 允许 supersede，但结果提示必须写明"人工确认替代了自动化回执，证据强度下降" |
| 财务口径与平台口径系统性差异（如退款时点） | 不属 supersede 范畴，应走"口径说明"字段，禁止用覆盖来掩盖口径差异 |
| 重传文件只覆盖部分店铺 | 按店铺分别处理，未涉及的店铺不受影响 |
| 同一店铺两个账户（如抖音结算与资金） | 按 `target_table` 隔离，互不 supersede |
| 用户在 supersede 预览页停留过久，期间又有新导入 | 提交时校验 `preflight_id` 是否仍与当前来源集合一致，不一致则重算预检并提示 |

### 3.6 本节用户可见结果

```
本次上传与既有来源在 1 天存在差异。
  2026-10-12  本次 412 行 / ¥18,204.11   既有 398 行 / ¥17,905.20   差 +14 行 / +¥298.91
  常见原因：旧文件在当日 10:30 导出，平台在 14:00 后补结算；或旧文件被截断。
选择：
  ● 以本次为准（推荐）  覆盖 11 个旧批次 / 重算 3 个指标 / 预计影响 10 月 ¥298.91
  ○ 保留旧来源          仅补齐 10-02、10-03 两天
  ○ 逐日选择
[查看被覆盖批次清单]  [导出差异明细]
```

---

## 4 问题三：京东结算单重试仍失败

### 4.1 问题分析：四个代码级原因 + 一个入口错位

按"是否足以单独导致重试失败"排序：

#### 原因 1（决定性）：`refresh_context` 冻结且重试不复位

```python
# apps/file_ingest/service.py:1118-1133
def retry_etl_task(self, task_id, operator, ip_address):
    ...
    cursor.execute("UPDATE ops.etl_task SET status='queued',... WHERE etl_task_id=%s ...")
    cursor.execute("UPDATE ops.etl_run SET status='queued',... WHERE etl_run_id=%s")
    # ↑ 没有清 ops.etl_run.refresh_context
```

```python
# apps/file_ingest/refresh_scope.py:149-155
if run.get('refresh_context') is not None:
    return run['refresh_context']      # ← 命中缓存，永不重算
```

于是重试时 `batch_cutoff` 仍是失败会话的 776；`refresh_runtime.source()` 把 ODS 包成 `WHERE batch_id<=776` 的临时视图；批次 777 的资金流水**在物理上存在、在本次运行中不可见**。资金就绪与重试成功之间没有因果关系。

#### 原因 2（范围不足）：只清缓存也不完整，scope 的月份与店铺仍锚定在旧会话

`build_refresh_context` 在 `ingest_run_id` 存在时：

```sql
WHERE t.run_id = %s AND t.status='success'   -- 只取本次导入会话的文件
```

清掉 `refresh_context` 确实能让 `batch_cutoff` 重新取到 779，从而让 ODS 读取看到 777；但 `months` / `shops` 仍只由 `9750b31c` 这批文件推导。一旦后续补齐的数据落在旧会话未覆盖的月份（例如补了 9 月结算），那部分月份不会进入刷新范围，指标仍是旧值。

所以"重试"要真正等价于"按当前数据重跑"，必须**同时**做三件事：换 cutoff、并集 months/shops、级联失效上游。仅改其中一项都会留下不一致。

#### 原因 3（掩盖问题）：上游 DWD 节点不级联

`sql/jd/platform_expense/321_refresh_*` 的第一句是 `TRUNCATE TABLE dwd.dwd_jd_platform_expense_source_detail`，然后从 `ods.ods_jd_settlement_raw` 全量重建。对账 SQL 读的是这张 DWD。

- 失败会话里该 DWD 已由上一个成功节点重建（只含 ≤776 的结算与资金），状态 `success`。
- 重试"结算指标"节点时，DWD 节点处于 success，不会重跑；即便 context 更新，DWD 也不会重新包含 777。
- 结果：`fund` CTE 里依然没有 777 的 `merchant_order_no` → `MISSING_WALLET` 原样复现。

#### 原因 4（长期缺陷）：对账只取"最新一个结算批次"

```sql
latest_settlement_batch AS (
  SELECT batch_id FROM ods.ods_jd_settlement_raw
  GROUP BY batch_id ORDER BY MAX(ingest_time) DESC, batch_id DESC LIMIT 1
)
...
INNER JOIN latest_settlement_batch b ON b.batch_id = d.source_batch_id
```

这意味着：分批上传（10-01~10-10 一个文件、10-11~10-18 另一个文件）时，**只有最后一批参与对账**，前一批的结算单被整体忽略。`settlement_batch_count`、`matched/pending/missing` 全部只反映最后一批。既可能漏报缺失，也可能因为最后一批里恰好有未到账单据而误报。

#### 原因 5（入口错位）：报表侧"重试"与 ETL 侧"重试"是两条链路

- 报表日历的"重试"走 `AutomationService.retry_run`（`service.py:664-690`）：新建一个 `automation_run`，重跑下载步骤。
- ETL 页面的"重试"走 `retry_etl_task`：只重置 `ops.etl_task`。
- 如果用户在报表侧点重试，而重下载的文件全部 hash 相同 → 导入会话 `no_change` → `create_etl_run(keys=∅)` → 不产生任何 ETL 任务。用户看到"下载成功"，指标却没动。

因此"我在结算单任务里点了重试还是失败"这一现象，取决于点的是哪一个按钮；但无论走哪条，结果都是失败或无效，**不可能因为"资金已经上传"而自动变好**。

### 4.2 设计原则

| 编号 | 原则 | 含义 |
|---|---|---|
| P3-1 | 重试必须声明快照策略 | "沿用原快照"与"按当前数据重跑"是两个动作，不能同名 |
| P3-2 | 快照策略必须在 UI 可见 | 按钮旁显示"快照 ≤ 批次 776"，用户能判断该不该点 |
| P3-3 | 上游按依赖级联失效 | 重跑下游前，所有"读 ODS 且产物被下游读"的祖先必须重建 |
| P3-4 | 启动时做新鲜度守卫 | 检测到 cutoff 之后有成功批次，必须警告并记录，不得静默 |
| P3-5 | 对账对象是"有效来源集合" | 不是"最新单批次" |
| P3-6 | 不允许隐式全量 | "按当前数据重跑"仍按月份+店铺，不得退化为 full |

### 4.3 处理流程

#### 4.3.1 三个动作，三种语义

| 动作 | 触发 | 快照 | 适用 |
|---|---|---|---|
| **继续**（resume） | 运行未终结（needs_human/paused） | 原快照 | 人工介入后继续 |
| **重试本节点**（replay） | 节点 failed/skipped/deferred | **原快照** | 复现问题、外部依赖瞬断 |
| **按最新数据重跑**（resnapshot） | 任何已终结运行 | **新快照** | 数据已补齐、上游已修正 |

`resnapshot` 的关键实现：

```
1. 新建 ops.etl_run：
   trigger_type='resnapshot'
   ingest_run_id=NULL            ← 关键：不再绑定旧会话
   scope='affected'
   requested_etls = 原 run 的 requested_etls（或用户勾选）
   parent_etl_run_id = 原 etl_run_id

2. build_refresh_context 走新分支：
   months = 原 context.months
          ∪ 区间内新导入批次覆盖的月份（同平台）
   shops  = 原 context.shops ∪ 新批次 shops
   batch_cutoff = 当前 MAX(batch_id) WHERE success
   excluded_batch_ids = 当前失败批次

3. 若 months 或 shops 无法确定（原 context 为空 / 新批次跨多个平台）→ 拒绝，
   提示"无法确定受影响范围，请使用手工全量刷新"（仍然可选，但不默认）

4. 依赖失效：把原 run 中所有"ODS→DWD"节点标记 stale（见 4.3.2），
   在新的 run 里全部重建，再跑目标节点
```

#### 4.3.2 依赖级联失效

`ops.etl_task.dependencies` 已经记录了节点间依赖。新增反向遍历：

```
targets = 用户要重跑的节点
ancestors = 沿 dependencies 反向闭包
stale = { n ∈ ancestors | n 读取 ods.* 或 n 的输出被 targets 读取 }
```

判定"读取 ods"不必解析 SQL，可复用现有登记：`ETL_SPECS[key].source_tables`（若不存在则用"凡 DWD 重建类节点一律 stale"的白名单兜底）。

`stale` 节点在 UI 上显示为"上游已过期"，并在 `resnapshot` 时自动加入执行计划。

#### 4.3.3 启动时新鲜度守卫

在 `_run_etl_task` 注入 context 之前：

```
if context.batch_cutoff:
    newer = SELECT platform_code, COUNT(*) FROM ods.ods_file_ingest_log
            WHERE batch_id > cutoff AND ingest_status='success'
            GROUP BY platform_code
    if newer:
        log.warning("[STALE_SNAPSHOT] 快照上界=%s，当前已导入 %s；本次运行不会读取这些批次",
                    cutoff, newer)
        UPDATE ops.etl_run SET snapshot_stale=TRUE, snapshot_note=...
```

失败信息里也带上这一行，避免用户拿着 `MISSING_WALLET` 去查资金文件。

#### 4.3.4 京东对账改为"有效来源集合"

```sql
settlement AS (
  SELECT merchant_order_no,
         ROUND(SUM(signed_amount), 2) AS settlement_amount,
         MIN(stat_date) AS first_date, MAX(stat_date) AS last_date,
         ARRAY_AGG(DISTINCT source_batch_id) AS batches
  FROM (
    SELECT DISTINCT ON (shop_identity_key, source_event_key) *
    FROM dwd.dwd_jd_platform_expense_source_detail
    WHERE source_document_type='settlement' AND merchant_order_no IS NOT NULL
    ORDER BY shop_identity_key, source_event_key, event_at DESC, id DESC
  ) d
  GROUP BY merchant_order_no
)
```

要点：

- 去重键是 `(shop_identity_key, source_event_key)`（`source_event_key` 即清洗后的单据编号），与 `321_refresh_*` 里 `latest` CTE 的口径一致，天然支持多批次。
- `settlement_batch_count` 改为 `COUNT(DISTINCT batch)`，并在输出里列出批次清单与各自日期范围。
- `fund_window.fund_extract_to` 仍用全表最大事件日，但增加"资金文件覆盖起点"，用于区分"未到账"与"资金文件本身没导到那段"。

```sql
fund_coverage AS (SELECT MIN(event_at::date) low, MAX(event_at::date) high
                  FROM dwd.dwd_jd_platform_expense_source_detail
                  WHERE source_document_type='fund')
-- expected_wallet_date < fund_coverage.low  →  数据缺口，不是 PENDING_NOT_YET_ARRIVED
```

#### 4.3.5 报表侧重试与 ETL 侧重试打通

- 报表侧 `retry_run` 成功后，若导入会话 `no_change`，必须**显式提示**"文件未变化，未触发指标刷新"，并提供"按最新数据重算"按钮（跳 `resnapshot`）。
- 若导入会话有新增批次，正常触发 `ingest_complete`，并在结果里给出 `etl_run_id`。

### 4.4 边界情况

| 场景 | 处理 |
|---|---|
| `resnapshot` 期间又有新批次导入 | 新批次不进入本次快照（context 已冻结），运行结束后标记 `snapshot_stale`，提示再次重跑 |
| 原 run 的 `requested_etls` 含已下线节点 | 沿用现有收口：未登记 key 按无操作成功，不阻断 |
| 重试的是 `deferred` 节点（来源未就绪） | 先校验来源是否已就绪，再决定 replay 还是 resnapshot |
| 上游节点重跑失败 | 下游保持 `skipped`，不产生半套结果 |
| 多平台混合运行（shared_ads） | `resnapshot` 需保留 `--allow-partial` 语义，否则共享 ADS 会因缺平台而失败 |
| 重跑与定时任务并发 | 沿用 `MOCK_COFFICE_ETL_LOCK_HELD` 与控制器锁，不新增并发路径 |
| 用户连续点两次"按最新数据重跑" | `etl_run` 级幂等键（parent + cutoff + requested_etls 哈希），重复请求返回同一 run |
| 京东分批上传后对账结果与财务月报不一致 | 先看 `settlement_batches` 是否覆盖全月；若覆盖仍不一致，属口径问题，不进本机制 |

### 4.5 本节用户可见结果

运行详情页固定展示：

```
快照：批次 ≤ 776（2026-10-20 14:22 冻结）
      ⚠️ 此后已导入 1 个批次（777 · jd_fund · 10-11 到账 909.72 元），本次运行不读取
失败节点：京东结算指标
原因：结算单据 MO20261010001（10-10 净额 909.72）在资金流水中未找到
      —— 该单据的到账日 10-11 位于批次 777，超出本次快照
可选：
  [重试本节点]  沿用快照 ≤776，结果不会改变
  [按最新数据重跑]  快照 ≤779，重建 DWD 明细，重算 3 个节点
```

---

## 5 问题四：上传入口完整性

### 5.1 问题分析

三个入口（网页人工、自动化 API、终端调用 API）在代码上共用 `save_upload`，但外围差异很大：

| 维度 | 网页人工（source=manual） | 自动化 API（source=api/robot） | 终端调用 API |
|---|---|---|---|
| 鉴权 | 会话登录态，`require_robot_token` 直接放行 | `INGEST_ROBOT_TOKEN` + `Authorization: Bearer` | 取决于 `source` 取值，**填 manual 即可绕过 token** |
| 幂等 | 表单 `client_file_id` | `Idempotency-Key` 必须等于 `client_file_id` | 同 API，自行保证 |
| 报表识别 | 可下拉选择，也可文件名 guess | 参数模式必填 `report_name` 等 | 通常只给文件，靠 guess |
| 覆盖声明 | 无 | 无（回执在 artifact 上，未下发到上传） | 无 |
| 结果反馈 | 页面状态、toast、运行详情 | JSON `data`，错误只有 HTTP 码 | 需自行解析 JSON，无 exit code 约定 |
| 异常处理 | 前端重试按钮 | 客户端重试 2 次（同幂等键） | 无统一约定 |
| 失败可见性 | 文件任务级错误摘要 | `IngestAPIError` 文案极简（"API上传失败（HTTP 4xx）"） | 同 API |

三个具体缺陷：

1. **`source=manual` 是免检后门。** `require_robot_token` 只在 `source ∈ {api, robot}` 时校验；任何终端脚本只要写 `"source":"manual"` 就能免 token 上传，且 `shop_mapping_source` 会被记成 `manual_selected`，审计上无法与真人区分。
2. **覆盖声明完全没有入口。** 自动化下载明明有 `artifacts.business_date_start/end`（且 `coverage_verified`），但上传时没有把这份证据带进来，导致 `backfill_receipts` 只能事后回填；人工上传则连事后回填的依据都没有。
3. **错误语义丢失。** `IngestAPIError("API上传失败（HTTP 400）")` 把后端的中文业务原因（如"company_name与DIM不一致"）吞掉了，终端用户无从修正。

### 5.2 设计原则

| 编号 | 原则 | 含义 |
|---|---|---|
| P4-1 | 一个契约，三种投递 | 业务校验只有一份实现，入口只决定认证方式与默认值来源 |
| P4-2 | 显式优于推断 | 报表类型与店铺在 API/CLI 必填；文件名识别只用于网页预填，不作为最终依据 |
| P4-3 | 声明随文件走 | 自动化入口的范围来自服务端回执，人工入口的范围来自显式输入，均落同一字段 |
| P4-4 | 幂等键不可省 | 三个入口都必须有 run 级与 file 级幂等键，且语义一致 |
| P4-5 | 错误可行动 | 每个失败必须给出"哪一项、期望什么、实际什么、怎么改" |
| P4-6 | 人机可区分且不可伪造 | `source` 由认证方式决定，不由请求体声明 |
| P4-7 | 预检前置 | 三入口都必须能"先看影响、再提交"（CLI 用 `--dry-run`） |

### 5.3 统一上传契约

#### 5.3.1 会话级字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `source` | 是 | **由服务端依据认证方式赋值**，请求体同名字段忽略 |
| `idempotency_key` | 是 | run 级幂等；网页自动生成 UUID，API/CLI 由调用方提供 |
| `expected_file_count` | 是 | 用于"文件数不齐不允许提交"的硬校验 |
| `intent` | 是 | `incremental` / `refresh_only` / `supersede`，默认 `incremental` |
| `operator` | 是 | 网页取登录用户；API/CLI 取 `X-Operator`，并校验非空、长度、字符集 |
| `note` | 否 | 补跑/整段上传的理由，进审计 |

#### 5.3.2 文件级字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 单文件；扩展名受报表 spec 限制 |
| `client_file_id` | 是 | 文件级幂等，重试保持不变 |
| `report_type` | API/CLI 必填 | 网页可留空，由文件名预填后**由用户确认** |
| `platform_name` / `company_name` / `shop_code` / `shop_name` | 参数模式必填 | 与 DIM 严格一致；`shop_code` 优先 |
| `coverage_start` / `coverage_end` | 条件必填 | `intent=supersede` 必填；`incremental` 可空（空则按"未声明"处理） |
| `coverage_evidence_type` | 条件必填 | `user_confirmed` / `automation_receipt`；`report_header` 由系统解析后赋值，不接受客户端传入 |
| `empty_days` | 否 | 声明区间内已确认无交易的日期，逗号分隔 |

#### 5.3.3 统一响应

```jsonc
{
  "code": "OK | NEEDS_DECISION | VALIDATION_FAILED | AUTH_FAILED | CONFLICT",
  "message": "人类可读中文摘要",
  "data": { "run_id": "...", "file_task_id": "...", "status": "uploaded|duplicate" },
  "issues": [
    {"field":"company_name","expected":"墨客咖时(南京)生物科技有限公司",
     "actual":"墨客咖时（南京）生物科技有限公司","hint":"全角括号与DIM不一致，系统已按NFKC等价处理，无需修改"}
  ],
  "preflight": { /* 见 2.4，仅在 dry_run 或提交前返回 */ }
}
```

HTTP 码与 `code` 的映射固定：400→`VALIDATION_FAILED`、401/403→`AUTH_FAILED`、409→`CONFLICT` 或 `NEEDS_DECISION`、201/200→`OK`。

### 5.4 三个入口的差异化要求

#### A. 网页人工上传

| 项 | 要求 |
|---|---|
| 输入来源 | 拖拽/选择文件；报表类型与店铺下拉（默认由文件名预填，必须用户确认）；覆盖范围选择器（"整月"/"自定义"/"不声明"），默认从文件解析，解析不到则要求显式选择 |
| 校验 | 前端：扩展名、大小、必填项、日期先后、跨月提示；后端：与其它入口完全相同的 `save_upload` + 预检 |
| 结果反馈 | 逐文件状态（识别/重复/待确认/失败）+ 会话级三段式（见 2.6）+ 影响预览面板 |
| 异常处理 | 失败文件可单独修正参数后重试（现有 `retry_file`）；预检 `BLOCK` 时不允许提交，给出具体日期与行数 |
| 特殊 | 提交前必须展示"将覆盖哪些批次"，并提供"导出差异明细" |

#### B. 自动化 API（robot/api）

| 项 | 要求 |
|---|---|
| 输入来源 | 下载脚本产出的归档 + `ops.automation_artifact` 回执；**覆盖范围由服务端从回执注入**（`business_date_start/end` + `coverage_verified`），不接受客户端自述区间 |
| 校验 | `Bearer` + `Idempotency-Key` 必填；`report_type` 必填；店铺三要素与 DIM 严格一致；回执哈希与文件哈希必须一致（防"回执配错文件"） |
| 结果反馈 | 结构化 `code/message/issues`；`Issues[].field` 供脚本自动修正；HTTP 码稳定 |
| 异常处理 | 网络不确定时同幂等键重试（现有 2 次）；`NEEDS_DECISION` 时**不重试**，直接上抛给人，避免自动化反复制造冲突 |
| 特殊 | 若回执缺失或 `coverage_verified=false`，**不阻断上传**，但声明为空，进入"未声明"分支；同时给出 warning 让自动化侧补齐回执 |

#### C. 终端调用（归人工）

| 项 | 要求 |
|---|---|
| 输入来源 | 本地目录 + 显式参数；支持 manifest 文件（一批文件各自的报表、店铺、范围） |
| 校验 | 与网页一致；`--dry-run` 只跑预检不落库；`source` 固定为 `manual` 且必须携带本机凭据（见下） |
| 结果反馈 | 默认人类可读表格；`--json` 输出与 API 同构；**定义 exit code**：`0` 成功 / `2` 需人工决策 / `3` 校验失败 / `4` 认证失败 / `5` 部分成功 |
| 异常处理 | 失败文件保留在暂存目录，支持 `--resume <run_id>` 续传；不在失败时自动删除本地文件 |
| 特殊 | 禁止用 `source=manual` 绕过鉴权：CLI 必须走"本机凭据"（登录后签发的短期 token，或 `.env` 中的 `INGEST_ROBOT_TOKEN` 并显式声明 `--as automation`），服务端据凭据而非请求体判定 `source` |

CLI 形态建议：

```bash
.venv/Scripts/python.exe -m apps.file_ingest.cli upload \
  --platform douyin --shop-code DY001 --report-type douyin_settlement \
  --coverage 2026-10-01:2026-10-18 --evidence user-confirmed \
  --intent incremental --dir ./exports/20261018 \
  --dry-run --json
```

### 5.5 三者一致性要求（可验收）

| 一致性维度 | 要求 | 验收方式 |
|---|---|---|
| 业务校验 | 同一输入必须产生同一 `code` 与同一 `issues` | 三入口跑同一 fixture，比对响应体（忽略 run_id/时间） |
| 幂等 | 同一 `idempotency_key` 重复提交返回同一 run，不产生第二个会话 | 三入口各重放 2 次，校验 `COUNT(DISTINCT run_id)=1` |
| 声明落库 | 同一范围内三种入口写入的 claim 字段完全一致 | 查询 registry，比对 `period_start/end/evidence_type/empty_days` |
| 重复判定 | 同一文件在三入口均判 `duplicate` 且指向同一历史批次 | 比对 `ingest_file_task.batch_id` |
| 刷新触发 | 同一批新增文件产生等价 `requested_etls` 集合 | 比对 `ops.etl_run.requested_etls` |
| 审计 | `ops.operation_log` 均记录 `source`、`operator`、`intent`、`coverage` | 查询日志核对 |
| 错误文案 | 同一错误的 `message` 主体一致（仅前缀可不同） | 文案快照测试 |

### 5.6 边界情况

| 场景 | 处理 |
|---|---|
| 自动化回执的范围与文件实际内容不符（回执配错文件） | 预检 `actual` 超出 `claimed` → `BLOCK`，并告警自动化侧 |
| 同一 run 内混入不同报表类型 | 允许，但预检按报表分别出报告；刷新触发取并集 |
| 终端脚本重复上传（网络重试） | 幂等键相同 → 返回同一 file_task；不同 → 进入 duplicate 判定 |
| 网页上传中断（关页面） | 现有 `_mark_stale_drafts` 超时收口；新增"草稿续传"提示，避免用户重开新会话 |
| API 客户端不读 `issues` 直接重试 | 服务端对同一 `idempotency_key` 的重复失败请求返回相同 `code`，不累积副作用 |
| CLI 在 CI 中无人值守 | `NEEDS_DECISION` 必须非 0 退出，禁止静默按默认值提交 |
| 文件超过 200MB（`MAX_UPLOAD_BYTES`） | 三入口统一在 `read_multipart` 前拒绝，返回 `VALIDATION_FAILED` 并给出实际大小 |

---

## 6 统一判定标准（供实现与测试共用）

### 6.1 数据来源优先级

裁决按顺序短路，命中即停：

```
1. 人工裁决记录（common.settlement_source_selection）
2. 完整性达标且严格包含其它来源的声明（宽者胜）
3. 声明区间完全相同 → evidence_strength 高者胜
4. 声明区间完全相同且强度相同 → (version_started_at, batch_id) 最大者胜
5. 区间交叉但不包含 → 冲突
6. 全部未声明 → 唯一来源生效，否则冲突
```

`evidence_strength` 仅在第 3 步起作用；**不能**用它推翻"包含关系"，否则会出现"窄的自动化回执压掉宽的完整导出"的反直觉结果。

### 6.2 重复与冲突判定

| 判定 | 口径 | 触发后行为 |
|---|---|---|
| 文件重复 `duplicate` | `SHA256 + platform + shop_identity_key + target_table` 已有成功批次 | 不写 ODS；`intent=supersede` 时仍更新声明并重算 |
| 会话内重复 | 同 run 内 `file_hash` 相同 | 同上 |
| 日期重叠（可接受） | 新声明区间与旧来源有交集，但新来源完整包含旧来源且通过完整性校验 | 旧来源被覆盖，记录 `covered_by_batch_id` |
| 日期交叉（不可接受） | 交集存在但互不包含 | 冲突，阻断，进入裁决 |
| 声明不完整 | 声明区间内 `empty_new` 非空且未确认 | 阻断 |
| 内容差异 | 同日行数或主金额不一致 | `REVIEW`，需显式裁决 |
| 全量重复 | 会话内 `success_count=0` | `no_change` + 明确提示，不产生 ETL |

### 6.3 关键不变量（实现时作为断言）

```
I1  ODS 行集合在任何声明/裁决/supersede 操作前后完全不变。
I2  任一 (shop, table, date) 在任一时刻至多有一个 effective 来源，或处于显式冲突状态。
I3  任一 effective 来源的 period 必须被自身明细填满（或空日已确认）。
I4  任一 etl_run 的所有节点使用同一个 refresh_context 修订号。
I5  任一 supersede 必须有可回滚的上一 revision。
I6  三入口对同一输入产出同一判定结果。
```

---

## 7 用户可见提示规范

### 7.1 状态与文案

| 状态 | 展示位置 | 文案要点 |
|---|---|---|
| 待声明 | 上传行 | "未声明覆盖范围；仅在该日期无其它来源时生效" |
| 声明已通过 | 上传行 | "覆盖 10-01~10-18 已核验（12 天一致 / 2 天补齐）" |
| 待裁决 | 会话顶部 | "1 天存在差异，需选择以哪份为准" |
| 已阻断 | 会话顶部 + 文件行 | "10-15 疑似漏导：既有 398 行，本次无数据" |
| 已覆盖 | 运行详情 | "本批次 1 天被批次 188 覆盖（自动化回执）" |
| 快照过期 | 运行详情 | "快照 ≤776，此后已导入批次 777，本次不读取" |
| 无变化 | 会话顶部 | "11 个文件内容与既有批次一致，未写入数据；如需重算请选择【以本批为准】" |
| 已切换权威 | 会话顶部 | "已切换至 revision 2，重算 3 个指标，金额差 ¥298.91" |
| 已回退 | 会话顶部 | "已回退到 revision 1，10 月重算完成" |

### 7.2 禁止出现的提示

- "结算来源覆盖不明或范围交叉，请登记完整查询参数后重试" —— 把内部规则直接抛给用户，且不告知"登记"在哪做。
- "API上传失败（HTTP 400）" —— 丢失业务原因。
- "无变化" 而不说明"未触发刷新"。

替代写法："本次 11 个文件与既有批次 789~799 内容一致，未写入新数据，也未刷新指标。如需以本批为准重算，请点击【以本批为准】。"

---

## 8 实施方案

### 8.1 分期

#### P0：止血（1~2 天，不改业务口径）

| # | 改动 | 文件 |
|---|---|---|
| 1 | `retry_etl_task` 增加 `snapshot_policy` 参数；`replay` 保留 context，`refresh` 走 resnapshot | `apps/file_ingest/service.py:1118` |
| 2 | 新增 `trigger_type='resnapshot'` 分支：`ingest_run_id=NULL`，months/shops 继承原 context 并并集新批次。**必须是独立分支**，不能落进现有"无 ingest_run_id"分支（`refresh_scope.py:39-53` 会按 DWS 边界推导月份，导致全历史重算） | `apps/file_ingest/refresh_scope.py:23` |
| 3 | 启动前新鲜度守卫 + `[STALE_SNAPSHOT]` 日志 + `ops.etl_run.snapshot_stale` | `apps/file_ingest/service.py:3650` |
| 4 | 失败信息附"快照上界与后续批次"摘要 | 同上 |
| 5 | `register_source` 增加空日校验（`empty_days` 参数 + 逐日比对），默认拒绝未确认空日；CLI 增加 `--allow-empty-days yyyy-mm-dd,...` 显式放行 | `etl/common/settlement_sources.py:42` |
| 6 | 京东对账改多批次去重（按单据编号） | `etl/jd/run_jd_main_business_finance_etl.py:500` |

P0 验收：

```sql
-- 6 项断言
-- a) 重试后 cutoff 变化
SELECT refresh_context->>'batch_cutoff' FROM ops.etl_run WHERE etl_run_id = :new_id;  -- > 776
-- b) 快照过期标记
SELECT snapshot_stale FROM ops.etl_run WHERE etl_run_id = :old_id;                   -- t
-- c) 空日被拒
--    构造"声明 18 天、只传 1 天"的上传，期望 register_source 抛错且不写 registry
SELECT COUNT(*) FROM common.settlement_source_registry WHERE batch_id = :bt;         -- 0
-- d) 京东对账覆盖多批次
--    run_jd_main_business_finance_etl 输出中 settlement_batches 长度 > 1
-- e) ODS 不变
SELECT COUNT(*), MD5(STRING_AGG(id::text, ',' ORDER BY id)) FROM ods.ods_douyin_settlement_raw;
-- f) 下游一致：同一快照下重算两次，DWS/ADS 逐行 EXCEPT ALL 为空
```

#### P1：声明与预检（3~5 天）

| # | 改动 | 位置 |
|---|---|---|
| 7 | `coverage-preflight` 只读 API + `PreflightReport` | `apps/file_ingest/service.py` 新增 |
| 8 | 上传契约扩展（`intent`、`coverage_*`、`empty_days`） | `module.py:108`、`service.py:442` |
| 9 | registry 增加 `revision/claim_status/declared_by/empty_days/preflight_id` | 新迁移 `sql/common/4xx_*` |
| 10 | 新增 `common.settlement_coverage_range` 支持多段区间 | 同上 |
| 11 | decision 视图改为按 range 判定 + 过滤 `claim_status='active'` | `sql/common/436_*` 重写 |
| 12 | 网页上传页：范围选择器 + 影响预览 + 待裁决交互 | `apps/file_ingest/static/*` |
| 13 | CLI：`--dry-run/--json/--resume` + exit code | 新增 `apps/file_ingest/cli.py` |
| 14 | 三入口一致性测试 | `apps/file_ingest/tests/test_ingest_contract.py` |

#### P2：权威切换与长期治理（1~2 周）

| # | 改动 |
|---|---|
| 15 | `intent=supersede` 全链路：预检、revision、重算、回执、回滚 |
| 16 | `common.settlement_source_selection` + 逐日裁决 API/UI |
| 17 | 依赖级联失效（`stale` 标注 + 自动纳入执行计划） |
| 18 | `refresh_only` 意图（内容不变但强制重算） |
| 19 | 审计报表：覆盖率、空日率、supersede 次数、快照过期次数 |
| 20 | 文档：`docs/ingest-coverage-contract.md`（对外契约，含三入口示例） |

### 8.2 迁移与兼容

- 所有 `ALTER TABLE ... ADD COLUMN` 带默认值，旧数据自动落在"未声明/active/strength=1"。
- decision 视图重写时保留原视图名，先建 `v_settlement_source_decision_v2` 并行验证，再切换。
- `settlement_source_registry` 现有 3 种 `evidence_type` 保持不变；新增字段不进入 CHECK 约束。
- CLI 的 `--manifest` 旧格式继续可用（视为 `user_confirmed` + 单段区间）。

### 8.3 回滚

| 改动 | 回滚方式 |
|---|---|
| 视图切换 | 视图名切回 v1，无需数据变更 |
| 新列 | 保留不用（向后兼容）；不 DROP |
| `resnapshot` | 停用入口，历史 run 仍可查询 |
| supersede | 每条 claim 可 revert；批量回滚按 revision 逆序 |

---

## 9 当前事故的立即恢复路径（不改代码）

### 9.1 抖音

**第一步：先算缺口，不要直接登记整月。**

```bash
GET /api/automation/report-calendar?month=2026-10&date_basis=business&platform=douyin
```

对该月每个 `profile` 的结算类报表，导出 `status ∈ {missing, failed}` 的日期集合 `G`。

**第二步：核对 11 个批次的真实覆盖边界（只读）。**

```sql
-- 逐批次的实际首末日期与行数；只作为"候选区间"，不构成声明
SELECT l.batch_id, l.source_file_name, l.parsed_rows, l.failed_rows,
       MIN((NULLIF(NULLIF(BTRIM(r."结算时间"),''),'-')::timestamp)::date) AS actual_min,
       MAX((NULLIF(NULLIF(BTRIM(r."结算时间"),''),'-')::timestamp)::date) AS actual_max
FROM ods.ods_file_ingest_log l
JOIN ods.ods_douyin_settlement_raw r USING (batch_id)
WHERE l.batch_id BETWEEN 789 AND 799
GROUP BY 1,2,3,4 ORDER BY 1;
```

**第三步：按店铺判断"整月是否真的完整"。**

如果某店铺的 `actual_min=10-01`、`actual_max=10-18`，且该店铺历史日批次在 10-01~10-18 每天都有数据，则整月导出很可能完整；此时登记 `2026-10-01~2026-10-18` 是安全的。

如果某个店铺 `actual_max=10-10`，**不能**登记到 10-18——那会覆盖掉 10-11~10-18 的旧来源（第 0 节漏洞）。

**第四步：登记并重跑（现有 CLI）。**

```json
// docs/manifests/douyin-20261018.json
[
  {"batch_id":789,"start":"2026-10-01","end":"2026-10-18",
   "evidence":{"source":"douyin_compass_export","operator":"<you>",
               "note":"10月自动化失败后手工整段导出，已核对首末日期与逐日行数"}},
  {"batch_id":790,"start":"2026-10-01","end":"2026-10-18","evidence":{"...":"..."}}
]
```

```bash
.venv/Scripts/python.exe -m etl.common.settlement_sources \
  --manifest docs/manifests/douyin-20261018.json --env-file .env
```

**第五步：不要点"重试本节点"，改用"手工选择刷新"。**

原因（重要）：`trigger_type='manual'` 的 context 是 `mode='full'`，`RefreshScope.predicate()` 直接返回 `TRUE`，**不加 batch 过滤**（`refresh_runtime.py:139-140`）。因此它能读到刚登记的来源，也不会被旧 `refresh_context` 卡住。

```bash
POST /api/etl/runs
{"scope":"selected","etls":[
  "douyin_settlement",
  "douyin_platform_expense",
  "douyin_main_business_income"
]}
```

`plan_etls()`（`apps/file_ingest/registry.py:288-304`）会自动补上下游与汇总：`douyin_settlement → settlement_shared_ads`、`douyin_main_business_income → platform_main_business_income_shared_ads`，以及 `douyin_platform_expense` 触发的 `platform_bank_summary`。**不需要手工列出共享 ADS**。

**第六步：核对。**

```sql
-- 覆盖是否按预期生效，且没有意外空日
SELECT shop_identity_key,
       COUNT(DISTINCT stat_date) FILTER (WHERE is_effective) days_effective,
       COUNT(DISTINCT stat_date) days_total
FROM common.v_settlement_source_decision
WHERE platform_code='douyin'
  AND stat_date BETWEEN '2026-10-01' AND '2026-10-18'
GROUP BY 1;
```

`days_effective` 应等于 18（或该店铺实际的营业天数），且不出现日期缺口。

### 9.2 京东

京东已由会话 `3fb3a418` 成功刷新，**不需要再操作**。旧会话 `9750b31c` 保留失败记录是正确的审计行为。

若要验证"重试为何无效"这一结论，可在测试库上：对旧 run 执行 `retry_etl_task`，观察 `ops.etl_run.refresh_context->>'batch_cutoff'` 仍为 776，且失败信息不变。这正好作为 P0 第 1 项的回归用例。

---

## 10 假设与未决项

| # | 假设/未决 | 影响 | 建议 |
|---|---|---|---|
| A1 | 抖音/京东结算导出文件**不含**查询起止时间表头（已抽样确认：抖音 CSV 首行为列名+说明，京东 CSV 首行为列名） | `report_header` 证据对这两平台不可用，只能靠回执或人工声明 | 若平台后续提供带区间的导出，优先接 `report_header`（可复用 `report_sources.py` 的解析范式） |
| A2 | 主金额列用于预检比对 | 不同报表列名不同 | 建 `common.report_amount_column(report_type, column)` 映射，缺失时只比行数并降级提示 |
| A3 | 补跑阈值（≤7 天走补跑） | 影响用户默认路径 | 放 `dim.dim_ingest_policy` 或配置表，可由财务调整 |
| A4 | 是否需要"跨平台统一 supersede" | 当前按 `target_table` 隔离，抖音结算与资金不互相覆盖 | 保持隔离；若出现"结算+资金必须同版本"的需求，再引入 `source_group_key` 级别的成组声明 |
| A5 | 京东对账改为多批次后，历史 `settlement_batch_count` 口径变化 | 报表数字会跳变 | 在输出中显式给出 `rule_version`，历史运行按旧版本解读 |
| A6 | CLI 的本机凭据形态 | 影响 P1 工作量 | 优先复用现有登录态签发的短期 token；不新建账号体系 |
| A7 | 空日确认的责任人 | 涉及财务判断 | 必须记录 `operator + 时间 + 理由`，并纳入审计报表；不允许脚本自动确认 |

---

## 附录 A 三个入口的现状差异（改造前基线）

| 能力 | 网页 | 自动化 API | 终端 |
|---|---|---|---|
| 免 token 后门 | 设计如此 | 有校验 | **有**（填 manual 即可绕过） |
| 报表类型必填 | 否（可 guess） | 是 | 否 |
| 覆盖声明 | 无 | 无（回执未下发） | 无 |
| 预检 | 无 | 无 | 无 |
| 结构化错误 | 弱（toast） | 弱（HTTP 码） | 无 |
| 幂等 | 表单字段 | Header 强校验 | 取决于调用方 |
| 续传 | 草稿 | 同幂等键 | 无 |

## 附录 B 需要新增/修改的对象清单

**表/视图**

- `common.settlement_source_registry`：+`revision`,`claim_status`,`declared_by`,`evidence_strength`,`empty_days`,`preflight_id`
- `common.settlement_coverage_range`（新）
- `common.settlement_source_selection`（新）
- `common.v_settlement_source_decision`（重写，按 range + claim_status）
- `ops.ingest_run`：+`intent`,`note`,`preflight_id`
- `ops.ingest_file_task`：+`coverage_start`,`coverage_end`,`coverage_evidence_type`,`empty_days`
- `ops.etl_run`：+`refresh_context_revision`,`snapshot_stale`,`snapshot_note`,`parent_etl_run_id`
- `ops.etl_task`：+`stale_reason`

**接口**

- `POST /api/ingest/runs/{id}/coverage-preflight`
- `POST /api/ingest/coverage-claims/{id}/revert`
- `POST /api/ingest/source-conflicts/{id}/decide`
- `POST /api/etl/runs/{id}/resnapshot`
- `POST /api/etl/tasks/{id}/retry`（+`snapshot_policy`）

**CLI**

- `python -m apps.file_ingest.cli upload|preflight|resume`

**测试**

- 三入口一致性（同一 fixture 比对响应与落库）
- 空日阻断（声明 18 天只传 1 天）
- supersede + revert
- resnapshot 后 cutoff 变化与上游级联
- 京东多批次对账
- ODS 不变性（每类操作前后行数与摘要比对）
