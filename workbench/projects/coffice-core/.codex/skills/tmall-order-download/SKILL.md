---
name: tmall-order-download
description: 在天猫千牛商家中心使用指定 profile 下载近一个月的“宝贝销售明细报表”订单明细，校验 13 个字段，处理导出限频和导出历史页，下载 XLSX 后按标准名称归档；脚本失败时按真实 DOM 接管、修复并重跑。
---

# 天猫订单报表自动化标准流程

## 适用范围

- 只处理天猫订单标准报表“订单”，实际导出类型必须是“宝贝销售明细报表”。资金、结算和推广费使用其他天猫 skill。
- 默认 profile 为 `TMALL-天猫-MOCK旗舰店`。从 profile note 解析 `platform`、`company`、`shop`，不得用文件名或默认店铺猜测归属。
- 页面操作、日期筛选、字段校验、导出历史轮询、下载和归档由正式脚本完成；Cloak Login 只负责选择/启动 profile、提供本次 `wsEndpoint`，以及失败后的 DOM 接管。

## 正常执行：脚本优先

1. 用 Cloak Login `list_profiles` 精确选择 `TMALL-天猫-MOCK旗舰店`；确认 note 通常为：
   - `platform=天猫`
   - `company=墨客咖时(南京)生物科技有限公司`
   - `shop=MOCK旗舰店`
2. profile 未运行时调用 `start_profile`，只使用本次返回的实时 `wsEndpoint`。
3. 在项目根目录只调用一次正式脚本：

   ```powershell
   & "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
     scripts.auto_download.playwright.tmall_order_download `
     --cdp "<本次 start_profile 返回的 wsEndpoint>" `
     --profile "TMALL-天猫-MOCK旗舰店" `
     --platform "天猫" `
     --company "墨客咖时(南京)生物科技有限公司" `
     --shop "MOCK旗舰店"
   ```

   默认范围为今天往前 30 天至今天；例如 2026-08-27 会输入 `2026-07-28` 至 `2026-08-27`。需要固定范围时传 `--start-date` 和 `--end-date`。
4. 检查退出码和脚本输出的 `archive_path`；成功后调用 `stop_profile` 关闭本次启动的 profile。

正常路径不要另行手工点击、重复创建导出任务或重复下载。退出码 `0` 时只需验证最终 XLSX 非空且能被 `openpyxl` 打开。

## 页面与字段标准

脚本复用 `scripts/auto_download/playwright/login_extensions/tmall_finance_login.py` 的登录逻辑，使用账号 `mock旗舰店:IT` 和密码环境变量 `TMALL_IT_LOGIN_PASSWORD`。登录页出现时由该模块完成登录和滑块处理，不在日志中输出密码。

登录后脚本从首页点击左侧「交易」，进入 `/home.htm/trade-platform/tp/sold` 的「已卖出的宝贝」页面；点击用户提供的日期范围控件，分别填写开始/结束 `YYYY-MM-DD`，按 Tab，确认日期弹层的「确定」按钮已启用后点击；再点击「搜索订单」并等待列表恢复。

导出弹窗中必须选择「宝贝销售明细报表」。自定义导出字段最终必须且只能勾选以下 13 个字段（脚本每次都读取真实 checkbox property，默认状态不可信）：

```text
子订单编号、主订单编号、商品标题、购买数量、商品属性、订单状态、商家编码、
买家应付货款、买家实付金额、退款状态、退款金额、订单创建时间、订单付款时间
```

字段多选或缺失时立即失败并保留状态文件，不生成不符合 ODS 合同的报表。确认「请您注意」弹窗后进入订单导出报表页：`https://myseller.taobao.com/home.htm/trade-platform/tp/export-list`。按「报表申请时间」选择本次最新的「宝贝销售明细报表」，只有同一日期范围且出现「下载宝贝报表」按钮后才下载。

## 五分钟限频与恢复

- 如果生成按钮显示「5分钟内只能导出一次」，不得再次点击生成；点击「查看已生成报表」进入历史页并复用匹配任务。若按钮不可用，也可直接打开上述导出历史 URL。
- 日期历史记录允许平台把起始日显示为输入日前一天的兼容差异，但结束日和报表类型必须匹配；脚本会在日志中记录实际历史范围。
- 脚本在工作目录保存 `tmall_order_download_state.json`：点击生成前为 `SUBMITTING`，确认后为 `EXPORT_CREATED`，下载后为 `DOWNLOADED`。中断重跑时先核对历史任务，不得盲目再次创建；临时文件和状态只在归档成功后清理。

## 下载与归档

- 通过 Playwright `expect_download()` 捕获 XLSX，保存到工作目录，不依赖浏览器默认下载目录。
- 调用 `scripts.auto_download.move_report`，报表名固定为 `订单`，归档目录为 `C:\Users\win\Desktop\data\天猫\订单`；文件名形如：

  ```text
  YYYYMMDD_天猫_墨客咖时(南京)生物科技有限公司_MOCK旗舰店_订单.xlsx
  ```

- 归档成功必须核对文件存在、大小大于 0、XLSX 工作簿可读取，并核对首行包含上述 13 个字段。失败时保留状态和现场，不能声称已完成。

## 日志与退出码

脚本阶段日志统一使用 `[TMALL]` 前缀，至少应覆盖 profile、日期范围、打开订单管理、登录复用、字段校验、查询完成、创建/限频、报表生成、请求下载、`xlsx_path`、文件移动、`archive_path` 和任务完成；不输出账号密码、令牌或任何验证码内容。退出码：`0`=下载并归档成功；`1`=登录、页面、字段、等待、下载或归档失败；`2`=参数错误。

## 失败接管

只有正式脚本退出码为 `1`，或用户明确要求诊断时，才用 Cloak Login 的浏览器工具连接同一 profile 的同一 `wsEndpoint`：先 `browser_snapshot`，再按真实可见 DOM 检查当前 URL、日期输入值、导出类型、13 个 checkbox、限频/注意弹窗、导出历史行和下载按钮；需要脚本外补救时使用 `browser_click`、`browser_type` 或 `browser_evaluate`，不猜测隐藏节点。

定位原因后只修改 `scripts/auto_download/playwright/tmall_order_download.py` 的选择器、等待或状态恢复逻辑，先运行天猫订单单元测试，再用同一 profile 单次重跑并验证实际归档。若状态为 `SUBMITTING` 或 `EXPORT_CREATED`，优先复用已有历史任务，禁止创建重复任务。失败现场和状态文件不得在未解决前删除。
