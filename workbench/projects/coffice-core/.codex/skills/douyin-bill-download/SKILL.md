---
name: douyin-bill-download
description: 在抖店商家后台（fxg.jinritemai.com）下载资金/结算账单报表并重命名归档。流程：账单管理→结算账单/资金账单→日汇总/月汇总→第一行下载明细→弹窗生成→历史报表刷新等待可下载→下载→按「日期_平台_公司_店铺_报表类型」剪切归档到 C:\Users\win\Desktop\data。支持日汇总（最新一天）与月汇总（最新一月）两种模式。当自动下载脚本报错需要按此流程手动修复/重跑时使用。
---

# 抖店账单报表下载

适用：抖店商家后台账单管理页（`fxg.jinritemai.com/ffa/fxg-bill/*`），下载资金单/结算单。
自动化载体：`scripts/auto_download/playwright/douyin_bill_download.py`（Playwright + Cloak Login CDP）。
本 skill 记录完整手动流程与踩坑，脚本异常时按此人工/修复后重跑。

登录态恢复：先按 `$douyin-login-recovery` 执行共享登录检查。目标页重定向到登录页时，脚本会复用 profile 已保存的邮箱凭据并勾选协议，再按 profile note 的 `shop` 精确选择店铺；仅在出现 `//*[@id="captcha_container"]/iframe` 时等待人工完成滑块，没有滑块直接继续。

## 核心概念

- 第一行 = 最新（日汇总=最新一天；月汇总=最新一月）。
- 生成报表：点「下载明细」→ 弹窗点「生成」→ 自动跳转历史报表页（历史报表不会自动刷新，需间隔刷新）。
- 历史报表页：第一张卡 = 最近一次生成的报表；状态「生成中」→ 等待 →「可下载」。
- 归档：`data\<平台>\<报表类型目录>\YYYYMMDD_平台_公司_店铺_报表类型.ext`，同天同店同表单递增 `_002`。

## 关键选择器

| 目标 | 选择器 |
|---|---|
| 结算账单 tab | `[role=tab]` 文本「结算账单」（一级） |
| 资金账单 tab | `[role=tab]` 文本「资金账单」（一级） |
| 日汇总 / 月汇总 tab | `[role=tab]` 文本「日汇总」/「月汇总」（二级） |
| 汇总表第一行 | 可见的第一个 `.aurora-table-row` |
| 第一行操作按钮 | 行内文本「下载明细」（月汇总同样如此，无「生成报表」按钮） |
| 弹窗生成 | `.aurora-popconfirm` 内文本「生成」按钮 |
| 报表卡 | `.reportCard-GbHGPv`（第一个可见） |
| 卡状态标签 | 卡内 `.aurora-tag`（「生成中」/「可下载」） |
| 卡下载按钮 | 卡内文本「下载」按钮 |
| 结算时间 | 卡内 `.value-wTAaor`（如 2026/07/01 00:00:00 - 2026/07/31 23:59:59） |

## 执行步骤

1. 打开账单管理：`https://fxg.jinritemai.com/ffa/fxg-bill/fund-detail-bill`（此时默认在资金账单页）。
2. 点一级 tab「结算账单」（或按需「资金账单」），等待 URL 变为 `/ffa/fxg-bill/settlement-detail-bill`。
3. 点二级 tab「日汇总」（最新一天）或「月汇总」（最新一月）。
4. 等待第一行出现，读第一行首列日期（日汇总如 `2026-08-12`；月汇总如 `2026-07`）。
5. 点第一行的「下载明细」按钮（月汇总行操作也是「下载明细」）。
6. 弹窗「生成报表」出现，点「生成」。
7. 等待跳转 `https://fxg.jinritemai.com/ffa/fxg-bill/history-report`（最多等 30s，未跳则手动 goto）。
8. 读第一张卡的 `.aurora-tag`：
   - 「可下载」→ 继续步骤 9。
   - 「生成中」→ **每 30s 刷新一次页面**（reload），重新读第一张卡状态，直到「可下载」（最长等待 15 分钟）。历史报表页不会自动刷新，必须手动 reload。
9. 点第一张卡内「下载」按钮，等待下载完成。
10. 归档重命名（见下）。

## 归档重命名

报表类型目录映射：结算日=结算、资金日=资金、结算月=结算月汇总、资金月=资金月汇总。
文件名：
- 日汇总：`YYYYMMDD_平台_公司_店铺_结算|资金.ext`
- 月汇总：`YYYYMM_平台_公司_店铺_结算月汇总|资金月汇总.ext`
公司/店铺/平台取自 profile note 键值对（半角括号）。同路径同名已存在则递增 `_002`、`_003`。

示例：
```
20260812_抖音_墨客咖时(南京)生物科技有限公司_MOCK官方旗舰店_结算.csv
202607_抖音_墨客咖时(南京)生物科技有限公司_MOCK官方旗舰店_结算月汇总.csv
```

## Playwright 脚本用法

```powershell
python -m scripts.auto_download.playwright.douyin_bill_download --cdp <wsEndpoint> `
  --platform 抖音 --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK官方旗舰店" `
  --report 结算 --mode month
```
参数：`--cdp`(必填) `--platform/--company/--shop`(取自 note) `--report`(结算/资金, 默认结算) `--mode`(day/month, 默认 day) `--src`(默认 C:\Users\win\Downloads) `--dest`(默认 C:\Users\win\Desktop\data) `--pattern`(默认 DL*)。
退出码：0=成功；1=执行失败；2=参数错误。

## 踩坑记录（脚本异常时按此修复）

- **历史报表不会自动刷新**：`wait_report_ready` 必须周期 `page.reload()`（默认 30s 间隔），直到首卡 tag=「可下载」，否则永远等不到。
- **Playwright 连接会接管下载**：`dl_btn.click()` 后文件不会进浏览器 Downloads 目录（download 事件被 Playwright 截获，文件存到临时目录）。必须用 `page.expect_download()` 捕获 Download 对象并 `download.save_as(target)`；此时不能依赖扫描 `C:\Users\win\Downloads\DL*`（会误抓残留旧文件）。
- **下载按钮必须用 JS evaluate 点击**：`dl_btn.evaluate("el => el.click()")` 可靠；Playwright 真实 `click()` 在此站点可能不触发下载。
- **切月/生成等其它按钮**：tab、下载明细、生成按钮用 `get_by_role("button", name=..., exact=True)` 正常。
- **月汇总首行也是「下载明细」**：无「生成报表」按钮，别找错。
- **重复测试会产生多份同月报表**：历史报表页会有多张相同时间范围的卡，取第一张（最新）；归档自动递增 `_002`，可清理多余测试文件。
- tab 文本定位用 `exact=True`，避免「日汇总」误匹配「资金流水明细」等。
