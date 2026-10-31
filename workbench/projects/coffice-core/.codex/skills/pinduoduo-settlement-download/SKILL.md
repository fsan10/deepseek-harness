---
name: pinduoduo-settlement-download
description: 在拼多多对账中心按指定日期范围下载并归档结算账单，默认昨天。用户要求下载拼多多结算单、资金单、对账中心账单，指定 PDD profile，或相关 Playwright 自动化报错需要接管分析、修复和真实重跑时使用。
---

# 拼多多结算账单下载

## 目标

使用指定拼多多 profile 下载指定日期范围的对账中心账单；不提供日期时默认昨天。拼多多结算单与资金单是同一个文件；将 ZIP 中唯一的 CSV 明细解压后，按项目标准归档为“结算”。

## 前置条件

- 使用 profile `PDD-拼多多-养颜轻食`。
- 从 profile note 读取标准元数据：`platform=拼多多`、`company=津果日记生物科技(南京)有限公司`、`shop=养颜轻食`。
- 每次启动 profile 后使用本次返回的 `wsEndpoint`，不要复用旧端点。
- 统一使用项目 `.venv\Scripts\python.exe -m` 运行模块。

## 标准流程

1. 启动指定 profile，记录 `wsEndpoint`。
2. 运行 `scripts.auto_download.playwright.pinduoduo_settlement_download`，传入 `--cdp`、`--platform`、`--company`、`--shop`；自定义区间时同时传 `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`。首次修复或验证日期控件时追加 `--date-only`，它只设置并校验日期，不创建导出任务。
3. 如果当前 tab 已在对账中心账单页则直接复用；否则复用已有商家后台 tab，处理遮挡导航的首页运营弹层后，点击 `a[href="/cashier/finance/payment-bills"]` 进入“对账中心”。不要依赖侧边栏动态 `li` ID。仅在没有可复用页面时才打开新 tab；不要直接访问旧的对账中心深链，以免次日触发登录异常。
4. 点击“开始日期-结束日期”设置日期范围。始终从当前可见的 `data-testid="beast-core-rangePicker-dropdown-contentRoot"` 重新解析弹层；月份切换使用弹层内月份 header 的 `data-testid` 控件，日期使用 `data-testid="beast-core-rangePicker-table"` 内的 `role="date-cell"`。时间控件按“开始→结束”分别设置为 `00:00:00` 和 `23:59:59`：优先使用带 `-begin/-end` 的时间 testid；结算中心当前版本若使用两个同名的 `data-testid="beast-core-timePicker-html-input"`，则在当前弹层内按 DOM 顺序区分开始和结束。点击“确认”后核对范围值。你提供的绝对 XPath 仅作为快速定位和 DOM 调试线索，不视为稳定选择器；日期或时间选择后组件可能重绘，下一步必须重新解析当前 portal，弹层每次打开只点击一次，禁止用重试点击把弹层再次关闭。
5. 点击“查询”，等待结果稳定后点击“导出”。
6. 在导出历史页按目标日期范围的入账时间匹配最新记录，点击“下载账单”。不要仅按页面上第一个可下载按钮判断日期。
7. 使用 Playwright 捕获下载并保存到临时工作目录；不依赖 Chrome 默认下载目录。
8. 调用 `extract_report.py` 从 ZIP 中提取唯一 CSV，并校验文件非空及拼多多结算字段。
9. 调用 `move_report.py`，以平台“拼多多”、报表“结算”和目标区间结束日期移动并重命名到 `C:\Users\win\Desktop\data\拼多多\结算`。
10. 验证归档文件存在且非空；只关闭脚本自己创建的页面，保留复用的用户页面，然后关闭本次启动的 profile。

## 执行命令

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_settlement_download `
  --cdp "<wsEndpoint>" --platform "拼多多" `
  --company "津果日记生物科技(南京)有限公司" --shop "养颜轻食" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--date-only]
```

成功文件名形如：

```text
YYYYMMDD_拼多多_津果日记生物科技(南京)有限公司_养颜轻食_结算.csv
```

## 验收标准

- 脚本退出码为 `0`。
- 归档目录中存在本次生成的非空 CSV。
- CSV 业务日期覆盖目标日期范围，表头至少包含商户订单号、发生时间、收入金额、支出金额、账务类型、备注和业务描述。
- ZIP 已在成功解压后删除，临时目录中没有被误当作正式报表的压缩包。

## 失败接管

- 如果被重定向到登录页，确认使用了正确 profile；不要绕过登录态下载。
- 首页运营弹层可能使用 `div[class*="newCloseBtn"]`，也可能使用 `data-testid="beast-core-modal-icon-close"`；先检查当前可见弹层，再关闭遮挡导航的关闭控件。
- 如果日期或时间未变为目标范围，重新打开日期弹层，按“开始日期、结束日期、开始时间、结束时间、确认”的顺序设置并核对输入框值后继续。
- 如果导出历史暂时没有目标记录，刷新导出历史页并继续按目标日期范围匹配，最长等待 90 秒。
- 如果页面控件、URL 或导出记录结构变化，检查真实页面，修复对应 Playwright 脚本并重跑完整流程；不要只手工完成一次下载。
- 如果 ZIP 内没有唯一 CSV 或表头不匹配，停止归档，检查平台导出结构后调整提取规则，避免把错误文件导入 ODS。
- 自动化失败时由 AI 分析当前页面、下载文件和异常原因，在安全范围内修复并重跑；仅在确需用户登录或外部状态变化时请求用户处理。
