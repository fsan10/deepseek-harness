---
name: xiaohongshu-order-download
description: 使用指定小红书商家 profile 下载近30天或指定日期范围的订单 XLSX 标准报表并归档；脚本失败时按真实报错和 DOM 修复，连续修复仍失败时再用 Cloak Login MCP 接管页面诊断。
---

# 小红书订单报表下载

## 适用范围

- 只处理小红书订单标准报表“订单”，不混用资金、结算或推广费流程。
- 默认使用 `XHS-小红书-MOCK旗舰店`；测试必须使用该 profile。
- 从 profile note 读取 `platform`、`company`、`shop`，不要根据文件名或店铺名猜测公司。
- Cloak Login 负责 profile 生命周期和提供本次启动的 `wsEndpoint`；页面操作、下载、校验和归档由正式 Playwright 脚本完成。

## 正常路径：脚本优先

启动 profile 后只使用本次 `start_profile` 返回的实时 `wsEndpoint`，从项目根目录调用一次正式脚本：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_order_download `
  --cdp "<本次 start_profile 返回的 wsEndpoint>" `
  --profile "XHS-小红书-MOCK旗舰店" `
  --platform "小红书" `
  --company "<profile note 中的公司>" `
  --shop "<profile note 中的店铺>" `
  [--start-date "YYYY-MM-DD" --end-date "YYYY-MM-DD"]
```

未提供日期参数时使用“近30天”。用户指定自然月或其他精确范围时，必须同时提供
`--start-date` 和 `--end-date`，脚本在订单页日期弹层中选择该范围，并默认用结束日期生成归档文件日期前缀。

默认工作目录为 `C:\Users\win\Desktop\data\.automation_cache\xiaohongshu_order\<shop>`，归档根目录为
`C:\Users\win\Desktop\data`。可用 `--work-dir`、`--dest` 和 `--business-date` 覆盖。

正常路径不要另行打开页面、执行 DOM 探活或手工重复点击。脚本退出码为 `0` 时，只核对输出的非空归档文件，然后停止本次启动的 profile。

## 页面标准流程

脚本必须按以下顺序完成，绝对 XPath 是当前页面的首选，备用定位必须限定为可见元素：

1. 打开 `https://ark.xiaohongshu.com/app-system/home`。若跳转到 `customer.xiaohongshu.com/login`，复用 `xiaohongshu_download_common.py` 的登录流程：点击“账号登录”、使用 profile 自动填充的账号密码、勾选协议并点击登录。不得读取、打印或写入凭据。
2. 进入订单管理：点击 `//*[@id="root-menu-wrapper"]/div[3]/div[6]/div[2]/div[1]/span`。
3. 订单页加载后定位下单时间组件 `//*[@id="fulfillmentorderark-mount-container"]/div[2]/div/div[2]/div[2]/div/div[7]/div/div`，点击开始输入框 `.../div[2]/div[1]/input`。
4. 未提供自定义范围时，在日期弹层 `/html/body/div[38]` 点击“近30天” `/html/body/div[38]/div[3]/div/button[5]/div/span`，确认日期范围已生效；提供自定义范围时，直接在“下单时间”的开始、结束输入框分别输入 `YYYY-MM-DD HH:MM:SS`（开始为 `00:00:00`、结束为 `23:59:59`），每个输入框回车确认，并确认两个页面值均已提交。
5. 点击查询 `//*[@id="fulfillmentorderark-mount-container"]/div[2]/div/div[2]/div[2]/div/div[8]/button[3]`，等待查询完成。
6. 点击全部导出 `//*[@id="new_order_manage_step_second"]/div[1]/button[3]`，等待提示弹窗 `/html/body/div[16]/div`，只点击该弹窗的确定按钮 `/html/body/div[16]/div/div[3]/div/button[2]`。
7. 用 Playwright 下载事件捕获直接生成的 XLSX，校验工作簿可读且首个工作表表头与 `etl/xhs/load_xhs_order_ods.py` 的 `EXPECTED_COLUMNS` 一致。
8. 调用 `move_report.py --report 订单` 归档到 `小红书/订单`；只有移动成功后才视为完成。

## 广告弹窗

广告弹窗是随机出现的 portal，不能把它与日期面板或导出提示混淆。公共模块
`scripts.auto_download.playwright.xiaohongshu_download_common.dismiss_ad_popups` 必须在首页、订单页和关键点击前后调用：

- 首先检查当前已知路径 `/html/body/div[3]/div/div[1]/span/svg`，必要时点击其父级 `span`。
- 动态备用定位只允许处理可见、具有广告/活动特征且包含关闭控件的 portal。
- 含“订单、日期、查询、导出、确定、取消、登录”等业务文本的弹窗必须跳过。
- 关闭失败要保留当前 URL、阶段和页面摘要，交给失败接管流程；不得盲目点击所有 SVG 或所有关闭按钮。

## 日志和验收

每个阶段都要输出带 `[XHS]` 前缀的可检索日志，至少包括 profile、登录状态、广告关闭、订单管理、日期范围、查询、导出提示、导出成功、下载文件路径、XLSX 校验、归档和任务完成。凭据、验证码、令牌不得出现在日志中。成功日志应类似：

```text
[XHS] profile=XHS-小红书-MOCK旗舰店
[XHS] 正在打开订单管理
[XHS] 已选择近30天：...（或 `[XHS] 已选择自定义日期范围：...`）
[XHS] 查询完成
[XHS] 正在创建订单导出任务
[XHS] 导出任务创建成功
[XHS] xlsx_path=...
[XHS] XLSX 校验成功
[XHS] 文件移动成功
[XHS] 任务完成
```

成功文件名形如：

```text
YYYYMMDD_小红书_公司_店铺_订单.xlsx
```

退出码：`0`=下载、校验、归档成功；`1`=登录、页面、弹窗、下载、校验或归档失败；`2`=命令参数错误。失败时保留工作目录中的下载现场，不宣称已归档。

## 失败修复与 Cloak Login 接管

1. 正式脚本退出 `1` 后，先根据日志确定失败阶段；用同一个 profile 和 `wsEndpoint` 检查错误上下文，只修改正式 `xiaohongshu_order_download.py` 或公共弹窗模块，先运行小红书订单单元测试，再用同一命令重跑。
2. 诊断优先检查当前 URL、登录页、订单根节点、日期输入实际值、近30天按钮或自定义日期输入框、查询按钮、全部导出按钮、可见提示弹窗和下载文件大小。不要凭静态 XPath 猜测页面已完成。
3. 连续多轮（至少两轮）按脚本报错修复并重跑仍不成功时，才根据本 skill 调用 Cloak Login MCP：先 `browser_get_info`，再 `browser_snapshot` 或 `browser_read`，需要读取隐藏属性时使用 `browser_evaluate`；任何点击或输入前必须重新 snapshot，使用最新可见元素，不得猜测凭据。
4. Cloak Login MCP 仅用于确认实时页面状态、完成必要的登录/页面恢复和获取真实 DOM 证据；拿到证据后必须回写正式 Playwright 脚本并重跑，不能把一次手工点击当成自动化完成。
5. 若 profile 登录态、商家权限或订单导出能力本身缺失，停止并报告，不使用其他店铺、账号或伪造凭据。完成后关闭本次启动的 profile，并用 `list_active` 确认没有遗留 profile。
