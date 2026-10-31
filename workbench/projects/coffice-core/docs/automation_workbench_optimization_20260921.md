# 自动化工作台：报错修复 + 工具栏统一 + 整体优化方案

- 基线提交：`4311c419 Add automation center worker and job management functionality`（分支 `codex/automation-workbench`）
- 范围：`apps/automation_center/`（新增于该提交），只读调研 + 复现，本方案未改动任何代码
- 关联文档：`docs/automation_plan.md`、`docs/automation_api.md`

---

## 0. 结论摘要

| 优先级 | 问题                                                    | 根因                                                                                                                      | 处理                        |
| --- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| P0  | 控制台报错 `invalid literal for int() with base 10: 'NaN'` | 侧边栏导航 `data-page` 与自动化分页按钮 `data-page` 同名，全局点击委托把页面 key（`runs`）当页码 → `Number('runs')` = `NaN` → `page=NaN` 送到后端 `int()` | 已定位并复现，见 §1               |
| P1  | 执行记录 / 每日成果工具栏风格不统一                                   | 自动化页自绘 toolbar、原生 `<input type=date>`、自绘分页、图标 sprite 缺 4 个符号、状态标签自有一套 class                                             | 对齐 `数据上传分类 / 导入记录` 页，见 §2 |
| P2  | 工作台能力缺口（轮询、导出、批量处理、告警等）                               | 新模块只做了最小可用集                                                                                                             | 见 §3                      |

---

## 1. P0：`int() with base 10: 'NaN'` 根因与修复

### 1.1 复现证据（本机真实库）

直接调用 `AutomationService.list_runs({'page': 'NaN'})`：

```
FAIL list_runs(page=NaN) ValueError invalid literal for int() with base 10: 'NaN'
  File "apps/automation_center/service.py", line 320, in list_runs
    page = max(1, int(query.get("page") or 1))
```

报错文本与用户看到的一致；`ops.automation_job`（3 条）、`ops.automation_run`（0 条）数据正常，说明**不是数据问题**，而是入参没有校验。

### 1.2 根因链路（`data-page` 命名冲突）

1. `apps/identity_access/static/shell.js:90`：在 `/automation/*` 下侧边栏项渲染为  
   `<button class="nav-item" data-page="runs" data-href="/automation/#runs">`，`data-page` 的值是**页面 key**（`workbench` / `jobs` / `runs` / `results`）。
2. `apps/automation_center/static/app.js:30`：页面在 `document` 上做全局点击委托  
   `if(button.dataset.page){state.runPage=Number(button.dataset.page);await loadRuns()}`  
   —— 它假设 `data-page` 一定是**页码**。
3. 点侧边栏任意一项（工作台 / 自动化任务 / 执行记录 / 每日成果）→ `Number('runs')` = `NaN` → `state.runPage = NaN`。
4. `app.js:23` `runQuery()` 用 `String(state.runPage)` 拼查询串 → `page=NaN`。
5. `service.py:320` `int('NaN')` → `ValueError`，server 按 `ValueError → 400`（`server.py:205`）原样回传异常文本 → 前端 toast 弹出该报错。

**连带影响**：`state.runPage` 被污染后不会自愈，「执行记录」页随后的查询、翻页、重置全部继续报同一错误，直到刷新页面（刷新后只要再点一次侧边栏就复发）。

**同一处还有第二个隐患**：`app.js:24` 的分页按钮也写 `data-page="${data.page-1}"`，与侧边栏语义重叠；点击侧边栏时还会顺带触发一次多余的 `loadRuns()` 请求。

### 1.3 修复方案

**A. 前端（`apps/automation_center/static/app.js`）**

1. 分页按钮改名，语义隔离：`data-page` → `data-run-page`（上一页 / 下一页两处）。
2. 点击委托收敛：只在 `main` 区域内响应，彻底不接管侧边栏  
   `const button=event.target.closest('main button'); if(!button)return;`
3. 页码读取加守卫：`const target=Number(button.dataset.runPage); if(Number.isFinite(target)&&target>0){state.runPage=target; await loadRuns()}`
4. `runQuery()` 输出兜底：`page` 恒为正整数（`Number.isFinite(state.runPage)&&state.runPage>0 ? state.runPage : 1`）。
5. `state.runPage` 只在「查询 / 重置」时归 1，翻页只由 `data-run-page` 驱动。

**B. 后端（`apps/automation_center/service.py`）**

1. 抽一个入参解析辅助函数（模块内私有），`list_runs` 不再裸调 `int()`：

```python
def _positive_int(value, *, default, minimum=1, maximum=None, field="参数"):
    if value in (None, ""):
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是整数") from exc      # → 400，不再是 500
    return max(minimum, min(number, maximum) if maximum else number)
```

- `page = _positive_int(query.get("page"), default=1, field="page")`
- `page_size = _positive_int(query.get("page_size") or query.get("limit"), default=20, maximum=100, field="page_size")`

1. 同类加固（同一类隐患，建议顺手一起）：`apps/fund_split_adjust/server.py:551 / 563-569` 的  
   `int(query.get("page", 1))`、`int(query["expense_type_id"])` 等，前端一旦传出 `NaN`/空串会出现同样文本的 500。

**C. 测试（防回归）**

1. `apps/automation_center/tests/test_frontend_contract.py` 增加断言：脚本内不得出现 `dataset.page`、必须出现 `data-run-page`；`test_frontend_contract` 中 `queryRuns` / `queryResults` 既有断言保留。
2. `apps/automation_center/tests/` 增加 service 层用例：`list_runs({'page': 'NaN'})`、`{'page': '-1'}`、`{'page_size': 'abc'}` 抛 `ValueError`（中文提示），`{}` / `{'page': '2'}` 正常。

### 1.4 验收清单

- [ ] 在自动化工作台依次点击侧边栏 4 个菜单项，均无报错提示，页面正常切换
- [ ] 执行记录：查询 / 重置 / 上一页 / 下一页 / 页码跳转全部正常，`state.runPage` 不再被污染
- [ ] 直接请求 `GET /api/automation/runs?page=NaN` 返回 400 且提示「page 必须是整数」（HTTP 状态不再是 500）
- [ ] `python -m unittest discover -s apps/automation_center/tests -v` 全绿
- [ ] `node --check apps/automation_center/static/app.js` 通过

---

## 2. P1：执行记录 / 每日成果工具栏与「导入记录」统一

### 2.1 参考实现的构成（`apps/file_ingest/static/index.html:118-138`）

| 元素   | 参考实现                                                                                                                                                                     | 说明                                                                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 容器   | `<div class="toolbar ingest-filter-toolbar"><div class="toolbar-group">`                                                                                                 | `.toolbar` 基础样式在 `/styles.css`                                                                                                                     |
| 字段   | `<label class="inline-field"><span>标签</span><select>`                                                                                                                    | 标签文字左置、控件 120px、统一高度                                                                                                                               |
| 日期   | `<div class="date-range" data-date-range="fromId,toId">` + `trigger(#i-calendar + date-start → date-end + #i-down)` + 2 个 hidden input                                   | 共享组件 `/identity-assets/date-range.js` 自初始化，弹层自建 `#dateRangeDropdown`，样式来自 `/styles.css`（含 `.date-range-dropdown/.calendar-day/.date-shortcut`，已具备） |
| 搜索   | `<label class="search-field grow"><svg #i-search><input type="search">`                                                                                                  | 图标绝对定位，输入框 340px                                                                                                                                   |
| 按钮   | `button.button.primary.query-button`（#i-search + 查询）、`button.button.reset-button`（#i-refresh + 重置）                                                                       | reset 必须带刷新图标                                                                                                                                      |
| 分页   | `.pagination-bar` = `.pagination-summary`(共 N 条) + `.pagination-controls`(每页条数 select + `.pagination-nav` 上一页/下一页 + `.pagination-pages` 页码 + `.pagination-page` 第 x/y 页) | 由 `renderPagination()` 驱动（`ingest/app.js:878`）                                                                                                     |
| 状态标签 | `<span class="status-tag success/failed/...">`（`ingest.css:102-112`）                                                                                                     | 有 `success / failed / no_change / partial_failed / success_with_warnings / queued / running` 等语义色                                                  |
| 轮询   | `ingest/app.js:954` 每 5s 刷新当前页                                                                                                                                           | 自动化页没有                                                                                                                                             |

### 2.2 现状差距

| 项         | 自动化现状                                                | 目标                                                                                  |            |                                                                                  |
| --------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------- |
| 工具栏容器     | `div.toolbar.filters` / `div.toolbar.result-toolbar` | `div.toolbar` + `div.toolbar-group`                                                 |            |                                                                                  |
| 字段标签      | 无 `.inline-field`、无左侧文字标签（只有 input 上的小字）             | `label.inline-field > span`                                                         |            |                                                                                  |
| 日期筛选      | 两个原生 `<input type="date">`（开始/结束各一个）                 | 共享 date-range 单控件（区间语义一致、含快捷「近7/30/90天」）                                            |            |                                                                                  |
| 搜索        | 无                                                    | 平台/店铺可改为 `.search-field`（若保留下拉则套 `.inline-field`）                                   |            |                                                                                  |
| 按钮图标      | 查询有 #i-search，重置无图标                                  | 查询 + 重置都带图标，类名 `query-button` / `reset-button`                                      |            |                                                                                  |
| 分页        | 自绘「上一页 / 下一页」文本按钮，无页码、无每页条数，且 `data-page` 与侧边栏冲突     | `.pagination-bar` 全套组件                                                              |            |                                                                                  |
| 图标 sprite | 仅 5 个（`i-grid/i-refresh/i-play/i-search/i-calendar`） | 补 `i-left/i-right/i-down/i-chevron-down/i-plus/i-check-square` 等（与 ingest 同名同 path） |            |                                                                                  |
| 状态标签      | 自绘 `.status-badge`（`automation/styles.css`）          | 统一为 `.status-tag`（与导入记录同色同形状）                                                       |            |                                                                                  |
| 文案        | 触发类型显示原始值 `manual/schedule/retry`；表头「步骤 / 文件」含混      | 中文标签：手工 / 计划 / 重试；表头「步骤数 / 文件数」                                                     |            |                                                                                  |
| 交互        | 结果页只能点按钮查询，无回车提交；toast 有 \`                          |                                                                                     | alert\` 兜底 | 回车提交、`DateRange.clear()` 联动重置、toast 统一走 `window.showAppToast`（`shell.js:20` 已提供） |

### 2.3 统一方案

1. **执行记录页**：改为  
   `toolbar > toolbar-group`：时间字段（开始/完成时间）→ 共享 `date-range` → 状态 / 任务 / 触发 / 平台 / 店铺（`.inline-field` 下拉）→ `query-button` 查询 + `reset-button` 重置。  
   `runDateFrom/runDateTo` 保留为 hidden input（`data-date-range="runDateFrom,runDateTo"`），这样 `runQuery()` 的取参逻辑不用改写。
2. **每日成果页**：日期是**单日**语义，不建议硬套区间组件。保留 `<input type="date" id="resultDate">`，但用 `label.inline-field` 包裹、统一控件高度/字号，「查询」套 `query-button`（带图标），并补回车提交。
3. **分页组件**：`renderPagination()` 逻辑复制进 `/automation/app.js`（或抽公共模块，见第 5 条），DOM 换成 `.pagination-bar` 结构，新增 `runPageSize`（10/20/50/100），页码按钮用 `data-run-page`（呼应 §1 的修复）。
4. **图标**：在 `automation/static/index.html` 的 sprite 中补齐所需 symbol，**直接复制 ingest 页同名 symbol 的 path**，保证图标形状完全一致。
5. **样式归属**（两选一）：
   - 方案 A（推荐，零回归）：把 `ingest.css` 的 `.pagination-*`（312-328）、`.select-chevron`、`.status-tag` 等组件规则补充进 `automation/static/styles.css`，状态标签改用 `.status-tag` 并删除 `.status-badge`。
   - 方案 B（单一来源，改动更大）：新建 `/identity-assets/components.css`（分页 + 状态标签 + 筛选器抽取），ingest / automation（可选 system）同时引用；需注意 `system.css` 已有同名 `.pagination-*` 规则的层叠顺序。
   - 不要整份引入 `/ingest/ingest.css`（含大量导入页专属规则，会污染自动化页布局）。
6. **文案与术语统一**：顶部标题/副标题、状态中文名、触发类型中文名、日期占位「开始日期 → 结束日期」、按钮「查询 / 重置 / 刷新 / 上一页 / 下一页」，以及「执行日期（automation_run.business_date）」与「业务日期区间（step.business_date_start → end）」的表述澄清（避免两个"日期"混用）。

### 2.4 改动文件清单（预计）

| 文件                                                       | 改动                                                                                       |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `apps/automation_center/static/index.html`               | 两个工具栏重写、分页条重写、sprite 补图标、引入 `/identity-assets/date-range.js`                             |
| `apps/automation_center/static/app.js`                   | 分页渲染改为 `renderPagination` 风格、`runQuery` 适配、`data-run-page`、回车提交、重置联动 `DateRange.clear()` |
| `apps/automation_center/static/styles.css`               | 分页/选择器/状态标签组件样式（方案 A）                                                                    |
| `apps/automation_center/tests/test_frontend_contract.py` | 新增工具栏/分页/图标契约断言                                                                          |

---

## 3. P2：工作台整体优化思路

### P0（正确性与可用性）

1. §1 的 NaN 修复 + 全站查询入参校验（`int/Number` 边界）。
2. 「每日成果」执行日期加合法性校验（非法值 → 400 中文提示，不要 500），并支持回车查询。
3. 轮询：工作台（当前运行/等待人工）与执行记录（有 `queued/running` 时）每 5s 自动刷新，切页即停 —— 对齐导入记录页。
4. 长时间运行保护：详情弹窗自动刷新运行中状态；`queued/running` 行的取消按钮加二次确认。

### P1（一致性与可维护性）

1. §2 的工具栏/分页/状态标签/图标/文案统一。
2. 抽公共前端小组件（分页、`statusTag`、`toast`、`date-range` 已有），供 `/ingest`、`/automation`、`/system` 复用，避免第 2~3 份副本。
3. 表格体验：长 ID 复制按钮、列宽与换行、按开始时间排序、每页条数记忆（localStorage）、空状态区分「暂无记录 / 当前筛选无匹配」。
4. 运行详情弹窗与其它模块的详情呈现（抽屉/弹窗）视觉统一；错误/输出文本支持折叠与复制。
5. 「立即运行」入口增加业务基准日选择与二次确认（当前固定 `today()`）。

### P2（能力完善）

1. 任务编辑：执行时间输入校验 + 保存后展示「下次运行时间」变化；支持多个时间点。ETL 调度已统一到 Automation Job，不再需要与旧 ETL 调度互斥。
2. 批量处理与提醒：批量重跑 / 批量取消筛选结果；`needs_human` 与 `failed` 走现有飞书通道推送卡片（复用 `ai.feishu` 能力，不新增依赖）。
3. 导出：执行记录 / 每日成果导出 CSV/XLSX（复用现有导入导出风格）。
4. 指标化：运行成功率、平均耗时、`needs_human` 次数落 ADS，供 DataEase 看板（沿 `ODS → DWD → DWS → ADS` 分层，不跨指标复用）。
5. 运维入口：Worker 心跳过期告警 + 页面内「回收异常运行」（`recover_stale`）按钮，走 `automation.runs.execute` 权限。
6. 全链路自测：`--once` 跑通一次真实 run，覆盖 artifact → FileIngest → ETL → 每日成果页显示。

---

## 4. 不做的事与边界

- ~~不改 ODS/DWD/DWS/ADS 口径，不动 `sql/` 下指标链路。~~
- ~~不引入新依赖（复用 `/styles.css`、`date-range.js`、`shell.js`、`ingest.css` 既有能力）。~~
- ~~不改变既有 API 路径与权限码（`automation.*` 已由 `sql/common/430_automation_center_postgres.sql:157-174` 种子化）。~~
- ~~界面改动限定在 `apps/automation_center/static/`；后端只做入参校验加固，不改调度/执行语义。~~
- 测试后按 `AGENTS.md` 关闭本次启动的服务、清理测试数据。

## 5. 建议实施顺序

| 步 | 内容                       | 产出                       |
| - | ------------------------ | ------------------------ |
| 1 | §1 修复（纯 bugfix，独立可回滚）    | 报错消失 + 单元/契约测试           |
| 2 | §2 工具栏与分页统一（含图标、状态标签、文案） | 三页视觉一致，`node --check` 通过 |
| 3 | §3 P0 剩余项（校验、轮询、确认）      | 行为一致性                    |
| 4 | §3 P1/P2 按需排期            | 逐个特性提交                   |

每步单独提交，便于按步验收与回滚。

---

## 6. 实施记录（2026-09-21）

已按第 1、2 步落地，第 3、4 步（轮询、导出、批量处理、告警、指标化）待排期。

### 已完成

| # | 文件 | 改动 |
| --- | --- | --- |
| 1 | `apps/automation_center/static/app.js` | 分页按钮改 `data-run-page`；点击委托限定 `main button`，不再读取侧边栏 `data-page`；`state.runPage` 加 `Number.isFinite` 守卫；`runQuery()` 恒发正整数页码；状态标签改 `.status-tag`；触发类型中文化；新增 `renderRunPagination()`（页码 + 每页条数 10/20/50/100）；重置联动 `DateRange.clear()`；两个工具栏支持回车查询 |
| 2 | `apps/automation_center/static/index.html` | 执行记录 / 每日成果工具栏改为 `toolbar + toolbar-group + inline-field`；日期改用共享 `data-date-range` 组件；分页改为 `.pagination-bar` 组件；补齐 `i-left/i-right/i-down` 图标；引入 `/identity-assets/date-range.js` |
| 3 | `apps/automation_center/static/styles.css` | 补充分页组件、`select-chevron`、`.status-tag` 样式（与导入记录页同源）；移除 `.status-badge`、`.filters`、`.result-toolbar` 旧样式 |
| 4 | `apps/automation_center/service.py` | 新增 `bounded_int()`（非法整数 → 中文 `ValueError` → 400）；`list_runs` 支持 `date_field`（业务基准日 / 开始时间 / 完成时间，后者按 `Asia/Shanghai` 取日期）；日期参数改用中文错误提示 |
| 5 | `apps/fund_split_adjust/server.py` | 新增 `query_int()`，替换 `/api/import/records`、`/api/expense-types`、`/api/account-entries` 的裸 `int(query.get(...))`，同类 500 一并消除 |
| 6 | `apps/automation_center/tests/test_query_validation.py`（新增） | `bounded_int` 边界、`list_runs` 非法入参、模块层 `page=NaN` 查询串共 8 个用例 |
| 7 | `apps/automation_center/tests/test_frontend_contract.py` | 新增 5 个契约：分页不得复用 `data-page`、导航点击不得被当作翻页、工具栏结构、分页组件、状态标签同源 |
| 8 | `apps/common/tests/test_health.py` | 修复基线提交遗留失败：`modules` 期望集合补 `automation` |
| 9 | `docs/automation_api.md` | 补全 `GET /api/automation/runs` 的查询参数与校验说明 |

### 验证证据

- 真实库复现 → 修复后：`GET /api/automation/runs?page=NaN` 返回 **400 `page必须是整数`**（原为 500 + Python 异常文本）；
  `page_size=NaN` → 400；`date_field=created_at` → 400；`date_from=2026-13-01` → 400；合法组合 → 200。
- 无头浏览器（Chromium）登录后依次点击侧边栏「自动化任务 / 执行记录 / 每日成果 / 工作台」：
  不再出现 `NaN` 报错 toast，无 console error；执行记录工具栏 7 个字段、分页组件与每页条数（20）正常，
  共享日期弹层可打开，查询与重置均正常。截图：`tmp/automation_runs_after_fix.png`、`tmp/automation_results_after_fix.png`。
- 测试：`apps/automation_center` 35 passed / 1 skipped；`apps/common` 12 passed；`apps/fund_split_adjust` 21 passed；
  `apps/file_ingest` 通过（5 skipped）；`apps/identity_access` 22 passed / 11 skipped；`node --check` 通过。
- 冒烟产生的登录会话与审计记录已硬删除，备用端口 8795 服务已关闭。

### 未做（下一步候选）

- 工作台 / 执行记录轮询自动刷新；取消操作二次确认；运行详情弹窗自动刷新。
- 运行指标、导出、批量重试、心跳告警、飞书推送（原方案 §3 P1/P2）。

