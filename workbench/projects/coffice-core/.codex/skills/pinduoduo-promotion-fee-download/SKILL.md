---
name: pinduoduo-promotion-fee-download
description: 在拼多多推广平台财务流水页按默认或指定日期范围筛选现金支出、下载推广费明细并按项目标准归档。用户要求下载拼多多推广费、推广账户流水或修复对应 Playwright 自动化时使用。
---

# 拼多多推广费下载

使用 `scripts/auto_download/playwright/pinduoduo_promotion_fee_download.py`。脚本通过 Playwright 连接已经启动的 Cloak Login profile，并复用
`scripts/auto_download/playwright/pinduoduo_login.py` 的拼多多商家后台登录流程；脚本不会创建浏览器或关闭 profile。

## 前置条件

- 使用 `PDD-拼多多-养颜轻食` profile。平台、公司、店铺从 profile note 的 `platform/company/shop` 读取，不从文件名猜测。
- 每次启动 profile 都使用本次 `start_profile` 返回的 `wsEndpoint`；已经运行的 profile 直接复用当前端点。
- 优先复用当前已经打开的 `https://yingxiao.pinduoduo.com/mains/account/report`；没有可用推广页时才由公共登录脚本确认商家后台并从“推广账户”入口兜底，不为直达报表额外创建标签页。

## 标准流程

1. 启动目标 profile，读取并保存本次 `wsEndpoint`。
2. 在仓库根目录执行：

   ```powershell
   & ".venv\Scripts\python.exe" -m scripts.auto_download.playwright.pinduoduo_promotion_fee_download `
     --cdp "<wsEndpoint>" --platform "<profile note platform>" `
     --company "<profile note company>" --shop "<profile note shop>" `
     --start-date "2026-08-01" --end-date "2026-08-31"
   ```

   `--start-date` 与 `--end-date` 必须成对提供，接受 `YYYY-MM-DD` 或 `YYYY/MM/DD`；不提供时保留页面默认日期范围。

3. 指定日期时，脚本点击日期框后直接填写 `YYYY/MM/DD` 并按 Enter 确认开始、结束日期。日期控件使用 `input[placeholder="开始日期"]`、`input[placeholder="结束日期"]` 和可见 `.anq-picker-dropdown`，不依赖浏览器复制出的绝对 XPath；随后选择 `资金类型=现金`、`流水类型=支出`，点击“查询”。
4. 下载由 Playwright 捕获到临时目录；脚本校验工作表、必需表头、店铺、现金/支出行、有效时间和金额，再调用 `move_report.py`。
5. 归档目录为 `C:\Users\win\Desktop\data\拼多多\推广费`。指定日期时逐行确认导出日期均在请求范围内，并以请求结束日期作为文件日期前缀；默认日期范围才取导出明细中最大的“时间”日期。若筛选结果出现范围外日期，停止归档。
   同名文件由 `move_report.py` 递增 `_002`、`_003`，不覆盖旧文件。
6. 退出码为 0 且归档文件存在、非空、可读、表头和行校验通过后，再停止本次启动的 profile；脚本自身只断开 CDP 并关闭自己创建的标签页。

## 验收与故障处理

- 日志必须能看到登录、导航、筛选、查询、下载、验收和归档阶段；不得输出账号、密码、验证码或令牌。
- 归档文件必须可以被 `etl/pdd/load_pdd_promotion_expense_ods.py` 按默认工作表读取；平台当前返回 `.xls`，脚本也兼容 `.xlsx/.xlsm`，且至少包含：`时间`、`资金类型`、`流水类型`、`店铺名称`、`交易金额`、`余额`、`交易摘要`。
- 下载空文件、表头变化、日期无法解析、现金/支出过滤失效或店铺不匹配时停止归档，不手工改文件。
- 若脚本退出码为 1，先依据日志和当前真实 DOM 检查登录态、页面路由、选择框和下载按钮；修复正式脚本后只重跑一次。验证码或权限缺失需要用户处理时停止，不尝试其他账号。
- 不要把推广平台报表深链作为未登录状态的第一步；这会触发平台的会话异常。
