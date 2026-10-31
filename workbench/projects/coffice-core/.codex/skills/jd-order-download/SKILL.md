---
name: jd-order-download
description: 在京麦商家后台使用指定京东 profile 下载近一个月或指定日期范围的订单明细信息【加密】标准报表，处理登录失效、订单导出任务轮询、ZIP 内加密 XLSX 的文件提取码和归档；脚本失败时用于按真实 DOM 修复并重跑京东订单自动化。
---

# 京东订单报表自动化标准流程

## 适用范围

- 默认 profile 为 `JD-京东-MOCK饮品旗舰店`；使用用户指定的京东 profile 时，以该 profile note 中的 `platform`、`company`、`shop` 为脚本参数，不凭文件名或店铺名推断公司。
- 只处理京东订单标准报表“订单”。京东资金、结算和推广费使用对应的京东账单流程，不要在本 skill 中混用。
- 页面操作、任务轮询、下载、ZIP 提取、XLSX 解密和归档由正式 Playwright 脚本完成；Cloak Login 只负责启动/停止 profile 和提供本次运行的 `wsEndpoint`。

## 正常执行：脚本优先

启动 `JD-京东-MOCK饮品旗舰店` 后，从本次 `start_profile` 返回值取得实时 `wsEndpoint`，在项目根目录只调用一次正式脚本：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_order_download `
  --cdp "<本次 start_profile 返回的 wsEndpoint>" `
  --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店"
```

指定自然日期范围时，同时传入 `--start-date` 和 `--end-date`；例如 2026 年 8 月：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_order_download `
  --cdp "<本次 start_profile 返回的 wsEndpoint>" `
  --platform "京东" --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --start-date 2026-08-01 --end-date 2026-08-31
```

默认可恢复工作目录为 `C:\Users\win\Desktop\data\.automation_cache\jd_order\<店铺>`，归档根目录为
`C:\Users\win\Desktop\data`。可用 `--work-dir`、`--dest` 和 `--business-date` 覆盖；`--business-date`
只控制归档文件日期前缀，不改变订单查询范围；默认使用查询结束日期。

指定范围时，`--start-date` / `--end-date` 必须同时提供，查询含首尾日期的自然日范围；不提供时使用“近1个月”快捷项。

正常路径不要另行执行浏览器探活、DOM 快照、历史页探查或手工点击，也不要为了确认成功重复创建任务。
脚本退出码为 `0` 时，核对脚本输出的非空归档文件后停止本次启动的 profile 即可。

## 京东页面标准流程

脚本必须遵循以下业务顺序：

1. 打开 `https://shop.jd.com/jdm/home`。若跳转到京麦登录页，账号密码由 profile 持久化保存，只点击“立即登录”；不得读取或输出密码，也不得把密码写入源码、命令行、状态文件或日志。
2. 优先打开订单导出深链：
   `https://shop.jd.com/jdm/trade/tools/export/ExprotList?exportTaskType=0`。
   如果深链出现会话异常、被带回不完整页面或找不到“新建导出任务”，回到首页，从左侧“交易”下的“订单列表”进入，再点击“订单导出”。
3. 点击“新建导出任务”，等待可见的居中弹窗 `.el-dialog.add-new-dialog[role="dialog"]`。导出类型应为
   `订单 / 订单明细信息【加密】`；如果不是该类型，打开导出类型下拉框并选择“订单明细信息【加密】”。
4. 点击下单时间的开始框。未指定日期时优先点击日期面板的“近1个月”快捷项（当前页面实际为 Element Plus 的 `近1个月`；旧版本也可能使用 `.jd-picker-panel__shortcut`）。指定日期时跳过快捷项，分别填写开始时间 `YYYY-MM-DD 00:00:00` 和结束时间 `YYYY-MM-DD 23:59:59`，并核对两个输入框。京东不会像快手一样在开始框 Enter 后自动跳到结束框。京东快捷项按滚动的 30×24 小时计算，展示的起始日可能比自然日保底范围早一天；仅近一个月模式允许这一偏差，显式日期范围必须精确匹配。
5. 在订单状态中勾选“全部”（当前自定义 checkbox 的值为 `-1`），确认勾选状态后点击弹窗内的“确 认”。点击前后都不得点击页面上其他同名按钮。
6. 确认后列表会先新增“导出中”任务，页面不会自动刷新。每 5 秒刷新一次页面，按“订单明细信息”、完整订单时间范围（含上述快捷项的一天起始日偏差）和任务提交时间选择本次最新任务；不能只按第一行或只按“成功”文字判断。只有状态为“成功”且操作列同时出现“下载文件”和“获取密码”才可继续。
7. 先点击该任务的“下载文件”并用 Playwright 下载事件保存外层 ZIP；下载完成后再点击“获取密码”。通过自动化 Challenge/飞书机器人请求 `archive_password`，等待负责人回复文件提取码。
8. 安全提取 ZIP 中唯一的 XLSX 文件，使用 `msoffcrypto-tool` 解密，使用 `openpyxl` 确认工作簿可读取且存在工作表；最后调用 `move_report.py` 归档到 `京东/订单`。

## 状态恢复与提取码

- 状态文件为工作目录中的 `jd_order_task.json`。点击确认前先写入 `SUBMITTING`，确认后写入 `EXPORT_CREATED`；进程中断后必须先查找匹配的历史任务，不能盲目再次点击“新建导出任务”。
- 已存在 `SUBMITTING` 状态但列表暂时没有对应任务时，保留状态并报告未能核验，不自动制造重复任务。已存在 ZIP 时直接从 ZIP/解密阶段恢复，不重复下载。
- “获取密码”只允许触发一次，`file_password_challenge_id` 保存未完成 Challenge ID；重跑优先等待同一个 Challenge，不重复发送短信/提取码请求。提取码和密码不会写入状态文件。
- ZIP 内 XLSX 解密失败时，最多重新申请两次 `archive_password` Challenge；不重新创建订单任务、不重新下载 ZIP。三次错误后保留原始 ZIP 和状态文件供人工恢复。
- 只有归档成功后才清理 ZIP、解密文件、解压目录和状态文件；失败时保留工作现场。

## 自动化转发服务

脚本通过 `scripts.auto_download.playwright.automation_challenge` 调用本机自动化转发服务，默认地址为
`http://127.0.0.1:8770`，可用 `AUTOMATION_RELAY_URL` 覆盖；令牌从 `AUTOMATION_ROBOT_TOKEN` 读取，兼容
`INGEST_ROBOT_TOKEN`。在点击“获取密码”前先探活服务，服务不可达或令牌无效时不触发京东短信。不要把令牌、
文件提取码或解密密码写入日志、聊天、源码或状态文件。

## 失败接管规则

只有正式脚本退出码为 `1`，或用户明确要求诊断时，才进入失败接管：

1. 使用同一 profile 的实时 `wsEndpoint` 检查当前 URL、登录页按钮、订单导出弹窗、日期输入值、`全部` checkbox、确认后的可见提示和 AG Grid 行。
2. 对历史任务同时检查中心行 `.ag-center-cols-container .ag-row` 与右侧钉住操作行 `.ag-pinned-right-cols-container .ag-row`，通过相同 `row-id` 对应；核对 `taskData` 的订单时间、`createDate` 的提交时间和 `taskStatus`，不要用静态帮助文字或未匹配的第一行。
3. 定位失败阶段后只修改正式 `jd_order_download.py` 的选择器、等待、状态恢复或解密逻辑，先运行京东订单单元测试，再用同一 profile 以单次命令重跑。修复重跑仍不得重新创建已有任务或重新下载已保存 ZIP。
4. 退出码 `1` 时保留现场并报告阶段、当前 URL、可见状态和工作目录；退出码 `0` 时报告最终归档路径、文件大小和 XLSX 校验结果。

## 输出与验收

成功文件名形如：

```text
YYYYMMDD_京东_墨客咖时(南京)生物科技有限公司_MOCK饮品旗舰店_订单.xlsx
```

验收必须同时满足：归档文件非空且 `openpyxl` 可读取；导出历史中的订单时间范围与本次查询一致；任务提交时间是本次匹配到的最新任务；没有因重跑产生重复任务；本次启动的 profile 已停止。

退出码：`0`=下载、提取、解密、校验、归档成功；`1`=登录、页面、导出、等待、下载、Challenge、提取、解密或归档失败；`2`=命令参数错误。
