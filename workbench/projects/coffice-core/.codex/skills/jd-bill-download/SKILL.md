---
name: jd-bill-download
description: 在京东商家后台下载并归档最新日/月结算账单或指定日期范围的资金流水账单。用户要求下载京东资金单、日账单、月账单、结算单，处理日账单 ZIP 或月账单嵌套 ZIP，测试同一京东 profile 的两类下载，或相关 Playwright 自动化报错需要接管分析、修复和重跑时使用。
---

# 京东资金与结算账单下载

优先运行项目正式脚本；失败时按本 Skill 的页面标准流程用 Playwright 接管、修复正式脚本并真实重跑。Cloak Login 只负责 profile 生命周期和提供 `wsEndpoint`，页面操作与下载必须由 Playwright 完成。

## 启动与参数

1. 用 Cloak Login 精确选择 `JD-京东-MOCK饮品旗舰店` profile。
2. 从 profile `note` 获取标准元数据：
   - `platform=京东`
   - `company=墨客咖时(南京)生物科技有限公司`
   - `shop=MOCK饮品旗舰店`
3. 若 profile 未运行则调用 `start_profile`，使用本次返回的实时 `wsEndpoint`，不得复用历史端口。
4. 已登录入口为 `https://shop.jd.com/jdm/home`。若跳转到登录页，先确认 profile 是否选错或登录态是否失效；不得臆造账号密码。

## 结算单标准流程

正式脚本：`scripts/auto_download/playwright/jd_settlement_download.py`。

1. 直接打开 `https://shop.jd.com/jdm/fin/billManage/DailyBill`，无需依赖悬浮菜单。
2. `--mode day` 使用默认「日账单」；`--mode month` 点击精确文本「月账单」，并等待 URL 进入 `MonthlyBill`。
3. 等待可见一级数据行 `.ag-row.ag-row-level-0`，按页面顺序选择第一个包含「下载明细」的可下载行；该行就是当前模式的最新账单。
4. 从目标行读取业务日期：日账单为 `YYYY-MM-DD`，月账单为 `YYYY-MM`。不要使用下载文件内部日期替换页面业务日期。
5. 用 `page.expect_download()` 包裹目标行内「下载明细」，并用 `download.save_as()` 保存到工作目录。
6. 日账单 ZIP 内包含 CSV 和 TXT，只保留唯一 CSV；月账单为外层 ZIP → 内层 ZIP → 唯一 CSV，递归解压到 CSV。若同一层出现多个 CSV 或多个候选内层 ZIP，停止并检查平台结构变化，不得任选其一。
7. 调用 `scripts.auto_download.move_report`，报表名固定为 `结算`；成功后外层和中间 ZIP 不得残留。

执行命令：

```powershell
python -m scripts.auto_download.playwright.jd_settlement_download `
  --cdp <wsEndpoint> --platform 京东 `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --mode day
```

用户明确要求月账单时改为 `--mode month`。

## 资金单标准流程

正式脚本：`scripts/auto_download/playwright/jd_fund_download.py`。

1. 直接打开 `https://shop.jd.com/jdm/finance/billManage/foundFlow?formCeconciiFlag=true`；该页对应「对账中心 → 资金流水账单」。
2. 未指定日期范围时点击 `input[placeholder="开始时间"]`，在时间面板点击精确按钮「昨天」。指定范围时分别填写开始和结束日期时间。核对输入值后再点击「查询」；日期范围覆盖首尾自然日的 `00:00:00` 至 `23:59:59`。
3. 点击可见的 `span.actions-down`「导出」。若京东悬浮助手拦截普通点击，可使用 Playwright `force=True`，不要改用 Cloak Login 代点。
4. 导出抽屉出现后，在点击「确认导出」前记录当前第一条「账单查询-资金流水账单」任务文本；确认后等待第一行文本发生变化且任务时间为本次提交时间，不能误用旧的成功任务。
5. 新任务状态为「待生成」或「处理中」时，点击行内「刷新」；若只有「刷新列表」，使用该按钮。定时重读第一行，直到出现「下载」。
6. 等全屏加载层消失后，用 `page.expect_download()` 捕获第一行「下载」产生的文件，并用 `download.save_as()` 保存。
7. 调用 `scripts.auto_download.move_report`，报表名固定为 `资金`，业务日期使用时间选择器中的昨天日期。

执行命令：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.playwright.jd_fund_download `
  --cdp <wsEndpoint> --platform 京东 `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店"
```

指定自然日期范围时，同时传入：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.playwright.jd_fund_download `
  --cdp <wsEndpoint> --platform 京东 `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --start-date 2026-08-01 --end-date 2026-08-31
```

## 并发约束

- 京东在同一 Chrome profile 存在并发页面操作时可能让两个下载事件都返回 0 字节文件。
- 两个正式脚本使用同一跨进程锁；命令可以同时启动，但连接同一 `wsEndpoint` 时必须自动排队完整流程。不要删除锁或只锁 `save_as()` 阶段。
- 若出现空文件，先确认是否有旧版本脚本、调试器或人工标签页正在同一 profile 查询、刷新或下载；停止并发操作后重新执行正式脚本。

## 归档与验收

- 默认根目录：`C:\Users\win\Desktop\data`。
- 结算目录：`C:\Users\win\Desktop\data\京东\结算`。
- 资金目录：`C:\Users\win\Desktop\data\京东\资金`。
- 文件名：日级使用 `YYYYMMDD_京东_公司_店铺_报表类型.csv`，月级使用 `YYYYMM_京东_公司_店铺_报表类型.csv`；同名文件由 `move_report.py` 递增编号。
- 成功必须同时满足：退出码为 `0`、目标文件存在且非空、扩展名为 CSV、临时 ZIP 已清理、日志中的业务日期和目标目录正确。
- 保持京东源 CSV 的原始编码和内容，不为解决终端乱码而重新编码或改写源数据。
- 完成后关闭本次启动的 profile。

## 失败接管

1. 退出码 `1` 时，用 Playwright 连接同一实时 `wsEndpoint`，读取当前 URL、可见 DOM、任务首行文本、下载事件和相关请求响应，先定位失败阶段。
2. 结算页没有行时，检查是否仍在日/月正确 URL、微前端是否加载完成以及 `.ag-row.ag-row-level-0:visible` 是否变化；不要立即改成固定等待。
3. 资金任务卡住时，区分「旧任务被误选」「新任务仍生成中」「刷新按钮没有作用」「加载层未消失」四类情况，并核对任务提交时间。
4. 下载事件触发但文件为 0 字节时，按并发约束排查同 profile 的其它操作；不得归档空文件。
5. ZIP 解压失败时列出安全化后的成员名和层级，确认平台是否增加文件或改变嵌套结构；保持唯一候选校验，不能静默选第一个。
6. 修复正式脚本后运行对应单元测试，再使用真实 profile 完整重跑并核对最终文件；不能只用临时调试脚本完成下载，也不能只报告失败原因。
