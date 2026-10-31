---
name: xiaohongshu-bill-download
description: 登录小红书千帆商家后台并下载、校验、归档最新日账单或月度汇总单。用户要求下载小红书资金单、结算单、日账单、月度汇总单，指定 XHS profile，登录态失效，或相关 Playwright 自动化报错需要接管修复和真实重跑时使用。
---

# 小红书资金结算账单下载

## 前置条件

- 使用 profile `XHS-小红书-MOCK旗舰店`。
- 从 profile note 读取 `platform=小红书`、`company=墨客咖时(南京)生物科技有限公司`、`shop=MOCK旗舰店`。
- 每次启动 profile 后使用本次返回的 `wsEndpoint`。
- 统一使用 `C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe -m` 运行模块。

## 登录

1. 启动 profile；其默认页为 `https://ark.xiaohongshu.com/app-system/home`。
2. 只有在页面被重定向到 `customer.xiaohongshu.com/login` 时才登录。
3. 点击“账号登录”，等待邮箱和密码输入框可见。不要输入、读取或打印凭据；必须由 profile 已保存的凭据自动填充。
4. 勾选协议复选框，点击“登录”，等待返回 `ark.xiaohongshu.com`。
5. 自动填充缺失或登录后仍未返回商家后台时停止并报告登录态问题。

## 资金账单

1. 打开 `https://ark.xiaohongshu.com/app-finance/bill/fund`。
2. 明确点击“日账单”或“月度汇总单”；该页面默认可能停留在“资金明细”。
3. 等待表格加载，取第一行并点击其“下载账单”链接。
4. 日账单使用首行日期归档；月度汇总单使用日期范围起始月份归档。
5. 校验 XLSX 仅含“资金账单明细”工作表和资金账单表头，再用 `move_report.py` 归档为“资金”。

## 结算账单

1. 打开 `https://ark.xiaohongshu.com/app-finance/bill/settle/daily`。
2. 明确点击“日账单”或“月度汇总单”，等待第一行后点击“下载账单”链接。
3. 校验 XLSX 至少含“订单结算”和“其他服务款”工作表及对应表头。
4. 用 `move_report.py` 仅归档一份为“结算”。导入中心上传该文件时选择“结算”，一次上传必须同时完成“订单结算”和“其他服务款”两个工作表的导入；任一工作表失败时停止后续刷新并修复。

## 执行命令

```powershell
# 资金日/月账单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_fund_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode day

# 结算日/月账单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_settlement_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode month
```

## 验收与接管

- 资金文件归档到 `C:\Users\win\Desktop\data\小红书\资金`；结算文件归档到 `C:\Users\win\Desktop\data\小红书\结算`。
- 下载由 Playwright 捕获并保存到临时目录，不依赖浏览器默认下载目录。
- 若首行未出现、月度标签未切换或下载链接失效，检查真实页面和第一行内容后修复脚本并完整重跑。
- 若 XLSX 工作表或表头变化，停止归档，先核对现有 ODS 注册表与 Loader，再调整下载校验或导入映射，避免错误文件入库。
- 完成验收后关闭本次启动的 profile。
