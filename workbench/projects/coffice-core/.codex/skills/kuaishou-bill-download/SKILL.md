---
name: kuaishou-bill-download
description: 在快手小店商家后台下载并归档指定日期的结算单或最新日/月资金账单。用户要求下载快手结算账单、日资金账单、月资金账单，处理结算 ZIP，指定快手 profile 或二级商户号，或相关 Playwright 自动化报错需要接管分析、修复和真实重跑时使用。
---

# 快手资金与结算账单下载

优先运行项目正式脚本。脚本失败时，用 Playwright 连接同一实时 `wsEndpoint`，按本流程定位原因、修复正式脚本并完整重跑。Cloak Login 只负责选择、启动、停止 profile 和提供 CDP 地址，不用于代替 Playwright 操作页面。

## 启动与元数据

1. 精确选择 `KS-快手-MOCK陌时专卖店` profile。
2. 从 profile `note` 读取：
   - `platform=快手`
   - `company=南京陌时食品科技有限公司`
   - `shop=MOCK陌时专卖店`
3. 若 profile 未运行，调用 `start_profile` 并使用本次返回的 `wsEndpoint`；不得复用历史端口。
4. 页面应位于 `https://s.kwaixiaodian.com/zone/`。若跳转到登录页，先检查 profile 和登录态，不得臆造账号密码。
5. 所有 Python 命令使用 `C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe -m`。

## 结算单标准流程

正式脚本：`scripts/auto_download/playwright/kuaishou_settlement_download.py`。

1. 直接打开 `https://s.kwaixiaodian.com/zone/fund/accounting/payment-bill`。
2. 默认业务日期为昨天；用户指定日期时传 `--date YYYY-MM-DD`。
3. 点击 `input[placeholder="开始日期"]`。该输入框初始为 `readonly`，必须先点击打开日期组件，再填入 `YYYY-MM-DD 00:00:00` 并按 Enter。
4. 在 `input[placeholder="结束日期"]` 填入同日 `23:59:59` 并按 Enter。读取两个输入值确认完整时间范围后再继续。
5. 点击精确文本「查询」，再点击精确文本「导出」。定位必须首尾精确，不能让「导出」误匹配「查看导出记录」。
6. 等待“导出成功，请至「查看导出记录」中下载账单”提示；可关闭提示，然后直接打开 `https://s.kwaixiaodian.com/zone/fund/accounting/export-list?type=SELLER_SETTLED_ORDER_V2`。
7. 在 `div.zone-fund-accounting-descriptions` 中按完整结算时间范围匹配目标记录，不能只依赖第一条。列表异步加载时，每次进入页面至少等待目标记录 15 秒；确认未出现后才 reload，禁止短间隔刷新打断接口加载。
8. 用 `page.expect_download()` 捕获目标卡片内「下载」，并用 `download.save_as()` 保存到工作目录。
9. 下载结果为 ZIP。调用 `scripts.auto_download.extract_report`，只允许唯一 XLSX 或 CSV 明细；实际结算 ZIP 通常包含一个名称类似 `订单流水导出.xlsx_...xlsx` 的 XLSX。提取成功后删除 ZIP。
10. 调用 `scripts.auto_download.move_report`，标准报表名使用 `结算`，业务日期使用 `YYYYMMDD`。

执行示例：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_settlement_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店"
```

## 资金单标准流程

正式脚本：`scripts/auto_download/playwright/kuaishou_fund_download.py`。

1. 本店二级商户号为 `5504000424907185`。直接打开 `https://s.kwaixiaodian.com/zone/fund/accounting/account-bill?subMchId=5504000424907185`；其它店铺必须传正确的 `--sub-mch-id`，不得沿用本店编号。
2. `--mode day` 保持默认「日账单」；`--mode month` 点击精确 tab「月账单」。
3. 点击精确文本「查询」，等待 `tr.zone-fund-accounting-table-row` 数据行，选择页面顺序中第一个包含「导出账单」的行。
4. 从目标行首列读取业务日期：日账单为 `YYYYMMDD`，月账单为 `YYYYMM`。点击行内精确文本「导出账单」。
5. 等待“账单导出成功”提示，点击精确按钮「导出记录」，并等待进入 `/zone/fund/accounting/export-list`。
6. 导出记录为 `div.container___mBlUU`。按 `账单日期：<目标日期>` 匹配记录；平台可能对重复导出做去重，因此不能假设刚点击后记录一定移动到第一条。
7. 列表异步加载时按结算单相同的等待策略处理。目标卡片出现后，用 `page.expect_download()` 捕获「下载」。资金日/月账单通常直接得到 CSV。
8. 调用 `scripts.auto_download.move_report`，标准报表名使用 `资金`；日账单文件名前缀为 `YYYYMMDD`，月账单为 `YYYYMM`。

执行示例：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_fund_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店" `
  --mode day
```

## 归档与验收

- 默认根目录为 `C:\Users\win\Desktop\data`。
- 结算单进入 `C:\Users\win\Desktop\data\快手\结算`；资金单进入 `C:\Users\win\Desktop\data\快手\资金`。
- 成功必须满足：退出码为 `0`、目标文件存在且非空、结算临时 ZIP 已删除、文件名中的日期/平台/公司/店铺/报表类型正确。
- 保持平台源文件内容和编码，不为消除终端乱码而改写源数据。
- 完成后关闭本次启动的 profile。

## 失败接管

1. 退出码 `1` 时，连接同一 `wsEndpoint`，依次核对当前 URL、输入框值、可见按钮、目标记录文本、下载事件和实际文件大小。
2. 日期无法输入时，确认先点击只读输入框再 fill/Enter；不要用 JavaScript 强改 value 绕过日期组件状态。
3. 点击导出时报 strict mode violation 时，改用首尾精确名称，区分「导出」「导出账单」「查看导出记录」「导出记录」。
4. 导出记录超时时，先确认数据接口是否被频繁 reload 打断，再检查是否按目标日期或完整时间范围匹配；不要盲目增加固定 sleep。
5. 下载了旧文件时，检查是否错误地永远取第一条。结算按完整时间范围匹配，资金按 `账单日期` 匹配。
6. ZIP 处理失败时列出成员名、大小和编码标志，保持唯一报表约束；不得静默选择多个候选中的第一个。
7. 修复后运行 `scripts.auto_download.tests.test_kuaishou_downloads`，再用真实 profile 完整执行对应正式脚本并核对归档结果；不能只运行临时调试器或只报告失败原因。
