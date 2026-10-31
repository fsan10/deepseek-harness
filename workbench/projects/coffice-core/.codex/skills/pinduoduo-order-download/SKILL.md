---
name: pinduoduo-order-download
description: 在拼多多商家后台按指定日期范围下载并归档订单对账报表，默认昨天。用户要求下载拼多多订单、批量导出订单、处理订单导出记录或修复对应 Playwright 自动化时使用。
---

# 拼多多订单报表下载

## 适用范围

使用指定拼多多店铺 profile 的登录态，查询指定日期范围订单，生成“对账报表”，从导出记录下载最新匹配任务，并按项目规则归档为“订单”。不提供日期时默认在“订单下单时间”左侧快捷下拉选择“近30日”；不要把本流程与拼多多对账中心的结算 ZIP 流程混用。

## 前置条件

- 使用 `PDD-拼多多-养颜轻食` profile；平台、公司、店铺必须从 profile note 的 `platform/company/shop` 读取。
- 每次启动 profile 后使用本次返回的 `wsEndpoint`，不要复用旧 CDP 地址。
- 登录失效时进入“账号登录”，通过 Playwright 点击输入框并用键盘触发 profile 中保存的凭据；不得读取 Chrome 密码库。没有可用保存凭据时才使用 `PDD_LOGIN_USERNAME`/`PDD_LOGIN_PASSWORD` 环境变量。
- 验证码出现时调用专用验证码转发服务（`AUTOMATION_RELAY_URL` + `AUTOMATION_ROBOT_TOKEN`，兼容 `INGEST_ROBOT_TOKEN`），等待负责人回复后填写验证码；不要把验证码写入日志。

## 标准流程

1. 启动 profile，记录本次 `wsEndpoint`。
2. 运行 `scripts.auto_download.playwright.pinduoduo_order_download`，传入 `--cdp`、`--platform`、`--company`、`--shop`；未指定日期时默认在“订单下单时间”左侧快捷下拉选择“近30日”，自定义区间时同时传 `--start-date YYYY-MM-DD --end-date YYYY-MM-DD` 才打开右侧日期范围框。首次修复或验证日期控件时追加 `--date-only`，它只设置并校验日期，不创建导出任务。
3. 登录成功后复用当前可用的拼多多商家 tab；仅在没有可复用页面时才打开 `https://mms.pinduoduo.com/orders/list?tab=0`。若深链再次跳转登录页，回首页完成登录后重试。
4. 在“订单下单时间”选择器中设置日期范围。始终从当前可见的 `data-testid="beast-core-rangePicker-dropdown-contentRoot"` 重新解析弹层；月份切换限定在左侧第一个 `section[data-testid="beast-core-monthRangePicker-year-header"]` 内的 `svg[data-testid="beast-core-icon-left/right"]`，日期使用第一个 `data-testid="beast-core-rangePicker-table"` 内的 `role="date-cell"`。时间控件按“开始→结束”分别设置为 `00:00:00` 和 `23:59:59`，优先使用 `data-testid="beast-core-rangePicker-timePicker-htmlInput-begin/end"`；如果组件版本把两个输入标成同一个 `beast-core-timePicker-html-input`，则在当前弹层内按 DOM 顺序区分开始和结束。点击“确认”后核对范围值，再点击“查询”，等待 `/mangkhut/mms/recentOrderList` 返回 HTTP 200。日期弹层或时间 portal 每次打开只点击一次；日期、月份或时间选择后组件可能重绘，下一步必须重新解析当前 portal，不能复用旧节点。
   你提供的绝对 XPath 仅作为快速定位和 DOM 调试线索，不视为稳定选择器；不得把它写成业务定位器，也不得只设置日期而跳过时间。
5. 点击“批量导出”，确认“对账报表”处于选中状态，点击“生成报表”。
6. 拼多多同一店铺 5 分钟内只能生成一次任务。遇到“重复提交/5 分钟内只能生成一次”等提示时，不重试生成；直接进入导出记录复用当天已有任务。
7. 导出记录页若出现 `i.ImportantList_close__d0eKb`（或同前缀类名）的“重要提示”浮层，先点击关闭，再按“拼单成功时间”匹配目标日期范围的任务卡，点击“下载报表”。不能只按页面第一个按钮猜日期。
8. 使用 Playwright `expect_download()` 捕获文件并保存到临时工作目录，再调用 `move_report.py`，归档到 `C:\Users\win\Desktop\data\拼多多\订单`。
9. 校验归档文件存在且非空；只关闭脚本自己创建的标签页，保留复用的用户页面，最后停止本次启动的 profile。

## 执行命令

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_order_download `
  --cdp "<wsEndpoint>" --platform "拼多多" `
  --company "津果日记生物科技(南京)有限公司" --shop "养颜轻食" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--date-only]
```

可选参数：`--start-date` 与 `--end-date` 必须同时提供，指定拼单成功时间范围；不提供时默认选择“近30日”快捷项。`--date-only` 只执行日期设置和完整时间校验，成功后不查询、不生成导出任务。`--work-dir/--src` 指定临时下载目录，`--dest` 指定归档根目录；默认分别为系统临时目录和 `C:\Users\win\Desktop\data`。

## 验收标准

- 退出码为 `0`。
- 归档目录存在本次下载的非空 CSV，文件名形如 `YYYYMMDD_拼多多_公司_店铺_订单.csv`。
- 页面查询接口返回 200，任务卡的拼单成功时间确实覆盖目标日期范围。
- 下载通过 Playwright 接管，不扫描浏览器默认 Downloads 目录，也不把旧文件误当新下载。

## 失败接管

- 先检查当前 URL、可见弹窗和导出任务卡，不要因为按钮被遮挡就重复生成任务。
- 若下载按钮点击被拦截，重新执行关闭 `ImportantList_close` 浮层，再用同一任务卡的按钮重试。
- 若 5 分钟限频或重复提交，直接刷新导出记录并复用昨天已有任务；只有没有目标日期任务时才重新生成。
- 若验证码服务不可用，检查后台验证码转发配置、令牌和飞书群；不要在日志或回复中输出账号、密码或验证码。
- 页面结构变化时修复 Playwright 选择器并重新执行完整下载，不能只手工点击完成一次。
