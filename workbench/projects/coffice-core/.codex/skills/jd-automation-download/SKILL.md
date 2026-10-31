---
name: jd-automation-download
description: 京东报表自动化下载总流程和路由 skill：按用户请求串行调用订单、资金、结算、京东联盟和京东通推广费子 skill；脚本失败时接管真实 DOM 修复并重跑。
---

# 京东自动化下载总流程

本 skill 是京东报表下载的统一入口；具体页面标准流程仍由下面的子 skill 维护，正式执行必须调用对应 Playwright 脚本。

## 报表路由

- 订单或订单表：使用 `$jd-order-download`，脚本 `scripts.auto_download.playwright.jd_order_download`。
- 资金、资金流水：使用 `$jd-bill-download` 的资金流程，脚本 `scripts.auto_download.playwright.jd_fund_download`。
- 结算、结算单、日/月结算账单：使用 `$jd-bill-download` 的结算流程，脚本 `scripts.auto_download.playwright.jd_settlement_download`。
- 推广费、京东推广费、京东联盟：使用 `$jd-promotion-fee-download` 的联盟流程。
- 京东通、账户中心推广费、京准通消费记录：使用 `$jd-promotion-fee-download` 的京东通流程。
- 用户只说“下载京东报表”或“下载京东所有报表”：依次调用订单、结算、资金、推广费脚本；推广费脚本内部再按联盟、京东通顺序执行。不要并发操作同一个 profile。
- 用户点名某一种报表时只调用对应子 skill/脚本，不额外下载其它报表。

## Profile 和参数契约

1. 用 Cloak Login 精确匹配用户指定的京东 profile，例如 `JD-京东-MOCK饮品旗舰店`。
2. 从 `list_profiles` 的 `note` 解析 `platform=<平台>;company=<公司>;shop=<店铺>`，作为脚本参数唯一来源。
3. profile 未运行才调用 `start_profile`，每次使用本次返回的实时 `wsEndpoint`；已有运行 profile 不重复启动。
4. 记录 profile 是否在本任务开始前已运行。只停止本任务启动的 profile，不关闭用户预先启动的 profile。
5. 所有脚本均在项目根目录用项目虚拟环境执行，例如：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.playwright.<module> `
  --cdp "<本次 wsEndpoint>" --platform "京东" `
  --company "<profile note 中的公司>" --shop "<profile note 中的店铺>"
```

不要把真实密码、令牌或 CDP 之外的敏感认证信息放在命令行、源码、日志或状态文件中。

## 执行和失败接管

- 同一个 profile 的京东脚本依赖共享下载锁；“全部报表”必须完整串行，一个脚本退出后才调用下一个。
- 正常路径每个请求只运行正式脚本一次，不先做浏览器探活、DOM 快照或手工点击。
- 退出码 `0` 后只核对脚本输出的目标文件存在且非空，并按对应子 skill 完成 profile 收尾。
- 只有退出码 `1` 或用户明确要求诊断时，才用同一实时 `wsEndpoint` 读取当前 URL、可见 DOM、任务状态、下载事件和工作目录状态。
- 诊断必须定位到具体阶段，再修改正式脚本；先运行对应测试，随后使用同一 profile、同一工作目录重跑，优先恢复已有任务，不重复提交或下载。
- 失败现场保留给重跑：订单 ZIP/提取码 Challenge、推广费任务状态和临时文件都不能被无故清除。

## 标准验收

- 文件位于 `C:\Users\win\Desktop\data\京东\<标准报表名>`，文件非空，文件名中的公司、店铺、日期和报表名与 profile/请求一致。
- 订单必须完成 ZIP 内加密 XLSX 的提取码、解密和工作簿校验；资金/结算必须完成 ZIP/CSV 结构校验；推广费必须完成两个指定报表的下载与归档。
- `move_report.py` 的注册表名称是唯一报表类型来源，不能把两个推广费报表合并成笼统的“推广费”。
