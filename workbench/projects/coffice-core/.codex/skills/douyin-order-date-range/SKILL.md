---
name: douyin-order-date-range
description: 在抖店商家后台（fxg.jinritemai.com）订单管理页（/ffa/morder/order/list）为 auxo 范围日期选择器填写自定义日期区间、快捷近30日并提交查询。当页面上出现 placeholder 为"开始范围/结束范围"（旧版为"开始时间/结束时间"）的 readonly 输入框、需要按指定起止日期（如 2026-06-01 ~ 2026-06-02，或跨月的 2026-06-30 ~ 2026-07-01）筛选订单时使用。包含打开日期弹层、快捷项、同月/跨月两种选择策略、确定、查询的完整流程与踩坑规避。
---

# 抖店订单管理 日期区间填写

适用页面：`https://fxg.jinritemai.com/ffa/morder/order/list`（抖店订单管理）。新页面通常从首页点击“订单管理”后进入，
组件：auxo RangePicker，弹层 `.auxo-picker-dropdown`，左右两个 `.auxo-picker-panel`；新页面输入框可能标为
`开始范围/结束范围`，旧页面标为 `开始时间/结束时间`。Playwright 实现位于
`scripts/auto_download/playwright/douyin_order_common.py`，订单下载和独立日期测试共用这里的日期操作。

## 快捷近30日

订单报表下载需要近 30 日时，先检查日期范围右侧的独立快捷下拉框。旧版结构是“下单时间”日期范围 wrapper
的同级 `.auxo-label-wrapper.auxo-label-wrapper-small`（通常宽度约 125px），打开后精确选择可见的「近30日」；
新版或其他版本也可能在日期弹层中提供「近一个月」「近1个月」「近30日」「近30天」等快捷项。快捷下拉优先于
日期弹层，只有两者都不存在时才回退到下面的同月/跨月 `title` 日期单元格策略。

页面快捷项由平台定义实际起止日，当前“近30日”是结束日往前 30 天（含结束日共 31 个日期），例如
2026-08-25 对应 2026-07-26 ~ 2026-08-25。操作后必须读取两个主输入框确认非空并核对日期，不要假设页面一定展示
按本地 `timedelta(days=29)` 计算的起始日。

## 核心策略（先判断，再操作，一次成功）

- **同月区间**（如 2026-06-01 ~ 2026-06-02）：**只用左面板**。左面板切到起始月后，起始日期和结束日期都在左面板内点击，**绝不操作右面板**（auxo 左右联动会把左面板月份带偏，导致区间被重置）。
- **跨月区间**（如 2026-06-30 ~ 2026-07-01）：左面板显示起始月、右面板显示结束月；左面板点起始日期，右面板点结束日期。

## 关键选择器

| 目标 | 选择器 |
|---|---|
| 主输入框（打开弹层） | `input[placeholder="开始时间"], input[placeholder="开始范围"]`（readonly） |
| 弹层面板 | `.auxo-picker-dropdown .auxo-picker-panel`（可见的两个，index 0=左、1=右） |
| 面板当前月份 | `.auxo-picker-header-view`（文本如 "2026年8月"） |
| 上一月 / 下一月 | `.auxo-picker-header-prev-btn` / `.auxo-picker-header-next-btn` |
| 上一年 / 下一年 | `.auxo-picker-header-super-prev-btn` / `.auxo-picker-header-super-next-btn` |
| 日期单元格 | `td.auxo-picker-cell[title="YYYY-MM-DD"]`（**必须用 title 精确定位**） |
| 确定按钮 | `button.sp-picker-range-ok-btn`（文本"确定"） |
| 查询按钮 | `#order-list-submit-btn` |
| 结果条数 | `.index_selectedPrompt__si2uH`（文本如 "共3120条"） |

## 执行步骤

1. **准备日期**：先点击「展开」（若筛选区已展开则跳过）。优先点击日期范围右侧的快捷下拉框并选择「近30日」；
   选择成功后读取两个主输入框即可结束日期步骤。若快捷下拉不存在或没有匹配项，再点击当前可见的
   `input[placeholder="开始范围"]`；旧版没有该节点时回退到 `input[placeholder="开始时间"]`。不要只点击「下单时间」标签或外层文字，必须点击这个 readonly 输入框本身。
   - 若点击工具在该输入框上超时（MCP timeout 且弹层未开），改用：JS `el.focus()` 聚焦后按空格键（`browser_press_key` Space）打开。
2. **读取左右面板月份**：两个 panel 的 `.auxo-picker-header-view`（如 "2026年8月" / "2026年9月"），并判断起始/结束日期是否同月。
3. **同月区间（只用左面板）**：
   a. 左面板用 prev/next 切到起始月（每次点一次，点完读 header 确认，避免连续点击竞态）；
   b. 在左面板点 `td.auxo-picker-cell[title="<起始日期>"]`；
   c. 仍在左面板点 `td.auxo-picker-cell[title="<结束日期>"]`；
   d. **不碰右面板**，直接进入步骤 6。
4. **跨月区间（左起始 + 右结束）**：
   a. 左面板切到起始月，点 `td.auxo-picker-cell[title="<起始日期>"]`；
   b. 检查右面板月份：通常点完起始日后右面板已联动到结束月；若未联动，用 prev/next 把右面板切到结束月；
   c. 在右面板点 `td.auxo-picker-cell[title="<结束日期>"]`。
5. **验证选择**（一次即可，不要反复核对）：`.auxo-picker-cell-range-start` 与 `.auxo-picker-cell-range-end` 的 `title` 分别等于起始/结束日期；若不一致，重新点一次起始日期即可恢复区间。
6. **点确定**：`button.sp-picker-range-ok-btn`（用快照中带"确定"文本的 ref 真实点击；无 ref 时用 JS `click()`）。
7. **验证提交**：主输入框值应为 `YYYY/MM/DD 00:00:00`（开始）与 `YYYY/MM/DD 23:59:59`（结束）。
8. **点查询**：`#order-list-submit-btn`，等待列表加载后从 `.index_selectedPrompt__si2uH` 读"共N条"。

## 注意事项（踩坑记录）

- **同月区间绝不操作右面板**。在左面板点完起始日期后去切右面板，auxo 联动会把左面板月份带偏（如 6月变5月），区间会错乱或重置，必须避免。
- **确定按钮只能点 `.sp-picker-range-ok-btn`**。弹层内其旁边有未命名兄弟按钮（`data-cloak-ref` 相邻、无文本），点错会导致值不提交（表单仍按默认 -6M 查询）。
- **时间输入框无需填写**：平台固定 00:00:00 / 23:59:59，只有筛选特殊时段（如 00:00:00-10:00:00）才需在弹层时间输入框填写。
- 日期单元格必须用 `title` 属性定位，不要按文本（如 "1"、"31"）选择，会跨月误选。
- 面板切换用头部 prev/next 按钮（`element.click()` 即可），不要展开月份选择视图；**一次点一个按钮，点完读 header 确认月份**，连续点击会因 React 竞态丢步。
- 区间被重置的兜底：重新点一次起始日期即可恢复（如 6/1~6/2 点成 6/2~6/2 后，再点 6/1 恢复）。
- 查询后如要确认区间真正生效，捕获 `searchConfig` 请求体，检查 `compact_time.range` 是否为目标区间。
- 快照 ref（如 e101）在页面变化后失效，点击前先重新快照。
