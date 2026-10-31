---
name: jd-promotion-fee-download
description: 在京东京准通后台下载并归档京东联盟和账户中心（京东通）推广费报表，支持近30天和自定义日历区间；脚本失败时按真实 DOM 修复并重跑。
---

# 京东推广费报表自动化标准流程

## 适用范围

- 默认 profile 为 `JD-京东-MOCK饮品旗舰店`。必须用 Cloak Login 的 profile `note` 取得
  `platform`、`company`、`shop`，不能根据文件名、店铺名或历史文件推断公司。
- 本 skill 处理两类报表：
  - 京东联盟：标准报表名 `京东联盟推广费`，对应 `ods.ods_jd_union_promotion_expense_raw`；
  - 账户中心（京准通）：标准报表名 `京东通推广费`，对应 `ods.ods_jd_tong_promotion_expense_raw`。
- 页面操作、日期选择、任务等待、下载和归档由正式 Playwright 脚本完成；Cloak Login 只负责 profile 生命周期和提供本次运行的 `wsEndpoint`。

## 正常执行：脚本优先

正式脚本为：

`scripts/auto_download/playwright/jd_promotion_fee_download.py`

用户已启动 profile 时直接使用 `list_active` 返回的实时 `wsEndpoint`；如果 profile 未运行，才启动该 profile 并记录本次是否由当前任务启动。项目根目录执行一次脚本：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_promotion_fee_download `
  --cdp "<本次 profile 的 wsEndpoint>" `
  --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" `
  --report all
```

参数：

- `--report all`：按京东联盟、京东通顺序串行下载；这是默认值。
- `--report union` 或 `--report alliance`：只下载京东联盟。
- `--report tong` 或 `--report account`：只下载账户中心（京东通）。
- 不传 `--start-date/--end-date`：联盟页面点击“最近30天”，京东通使用页面默认最近30天。
- 自定义范围必须同时传 `--start-date` 和 `--end-date`，例如：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_promotion_fee_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK饮品旗舰店" `
  --report all --start-date 2026-08-01 --end-date 2026-08-31
```

`--business-date` 可单独覆盖归档日期，默认使用结束日期；`--work-dir/--src` 可指定可恢复临时目录，默认是
`C:\Users\win\Desktop\data\.automation_cache\jd_promotion\<店铺>`；`--dest` 默认是
`C:\Users\win\Desktop\data`。脚本通过 `jd_download_common.py` 的跨进程锁与京东订单、资金、结算脚本串行。

## 页面标准流程

### 京东联盟

1. 新标签页打开 `https://jzt.jd.com/jtk/#/account-bill`。
2. 点击费用时间下拉框，选择“结算时间”。优先使用已验证 XPath，动态下拉框 ID 变化时用可见的精确文本“结算时间”保底。
3. 默认任务在日期框后点击“最近30天”。自定义任务打开双面日期弹层：先把开始月和结束月都显示在左右面板内，再点击开始日和结束日；同一天使用双击。
4. 点击下载图标，点击“开始生成”，在下载确认弹窗中点击“确定”。5 秒跳转提示不做额外操作，等待进入
   `https://jzt.jd.com/jtk/#/download-report`。
5. 导出历史页面不自动刷新。脚本每 5 秒刷新一次，按本次任务创建时间选择最新行；只有操作列出现可用下载按钮时才下载。
6. 用 Playwright 下载事件保存文件，调用 `move_report.py`，归档为：
   `C:\Users\win\Desktop\data\京东\京东联盟推广费\YYYYMMDD_京东_公司_店铺_京东联盟推广费.xlsx`（实际扩展名以下载文件为准）。

### 账户中心（京东通）

1. 新标签页打开 `https://jzt.jd.com/account/#/financialRecord`，点击“消费记录”。
2. 交易时间下拉框选择“记账时间”。不传自定义日期时保留页面默认最近30天。
3. 自定义任务使用账户中心日期选择框打开同一双面日历：目标月份可以在左边或右边；跨月时必须同时显示开始月和结束月。单日使用目标月份面板上的日期双击。
4. 点击下载图标和“开始生成”。等待自动进入 `https://jzt.jd.com/account/#/downReport`。
5. 每 5 秒刷新下载报表页，核对创建日期最新任务，直到操作列下载按钮可用后用 Playwright 下载。
6. 用 `move_report.py` 归档到：
   `C:\Users\win\Desktop\data\京东\京东通推广费\YYYYMMDD_京东_公司_店铺_京东通推广费.xlsx`（实际扩展名以下载文件为准）。

## 自定义月份规则

- 例如 2026-08-01 至 2026-08-31：日历左右任一面板显示 2026 年 8 月即可，点击 1，再点击 31。
- 例如 2026-08-21 至 2026-09-10：左面板必须是 8 月、右面板必须是 9 月；若当前两个月不合适，使用左右切月按钮调整。
- 例如只下载 2026-08-01：在 8 月面板双击“1”，不要把相邻面板中同名的 1 当作目标日期。
- 结束日期使用页面的自然日选择结果；归档文件日期取 `--end-date`，所以 8 月整月归档前缀是 `20260831`。

## 状态恢复和失败接管

- 每类报表在工作目录中保存独立状态：`jd_union_promotion_task.json` 或 `jd_tong_promotion_task.json`。
- 点击生成前先保存 `SUBMITTING`，确认后保存 `SUBMITTED`；重跑时若状态显示已提交，直接打开下载历史，不再次生成。
- 下载完成后保存 `DOWNLOADED`；归档成功才删除状态文件。归档失败保留原始下载文件，重跑可继续移动。
- 正常路径不要先做浏览器探活、DOM 快照、手工点击或重复创建任务。只有正式脚本退出码为 `1`，或用户明确要求诊断时，才用同一 `wsEndpoint` 检查当前页面、日期弹层、生成弹窗、下载历史行和按钮状态。
- 诊断后只修改正式 `jd_promotion_fee_download.py` 的选择器、等待、日历识别、任务恢复或归档逻辑；先运行对应单元测试，再用同一 profile 和同一工作目录重跑。
- 不要读取、输出或保存登录页中的账号密码；不把密码、令牌或报表内容写入源码、日志或状态文件。

## 退出与验收

- `0`：指定报表均已下载、非空并归档到对应标准目录；脚本输出包含任务创建时间和目标路径。
- `1`：登录、页面、日期、生成、等待、下载或归档失败；保留状态和临时文件供 skill 接管。
- `2`：命令参数错误。
- 完成后核对两个目录和文件大小；同名文件由 `move_report.py` 自动追加 `_002`、`_003`，不覆盖旧文件。
- 只停止本次任务启动的 profile；用户预先启动的 profile 不擅自关闭。
