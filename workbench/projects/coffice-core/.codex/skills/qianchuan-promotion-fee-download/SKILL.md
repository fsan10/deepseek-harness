---
name: qianchuan-promotion-fee-download
description: 在巨量千川财务页下载“流水对账”日结报表的最新一天推广费，并按项目标准增量归档为 CSV。用户要求下载千川推广费、流水对账、日结报表、指定千川店铺或广告账户推广消耗，或需要修复该自动化脚本时使用。
---

# 千川推广费下载

使用 `scripts/auto_download/playwright/qianchuan_promotion_fee_download.py`。脚本通过 Playwright 连接用户已经启动的 Cloak Login profile，不新建浏览器，也不关闭该 profile。

登录态恢复：先按 `$douyin-login-recovery` 检查抖店统一登录页。若千川深链回到
`fxg.jinritemai.com/login/common`，复用 profile 已保存的邮箱凭据、协议和 profile note
中的目标店铺；只有检测到真实滑块 iframe 才等待人工完成，没有滑块直接继续。

## 执行流程

1. 用 `list_profiles` 找到目标 `DY-千川-<店铺>` profile；从 `note` 读取 `platform`、`company`、`shop`，不得硬编码。
2. 确认 profile 已运行；若未运行再 `start_profile`，取得 `wsEndpoint`。
3. 从目标千川财务 URL 读取 `aavid`，执行：

   ```powershell
   python -m scripts.auto_download.playwright.qianchuan_promotion_fee_download `
     --cdp <wsEndpoint> --aavid <aavid> `
     --platform <platform> --company <company> --shop <shop>
   ```

4. 读取脚本输出的目标日期和归档路径，确认退出码为 0。

## 页面和数据约束

- 页面路径：`https://qianchuan.jinritemai.com/finance?aavid=<aavid>`；点击「流水对账」，读取「日结报表」。
- 只取实时表格中第一个 `YYYY-MM-DD` 行，跳过「总计」。平台每天早上 8 点更新，最新记录通常是前一天。
- 表头必须从页面读取；脚本校验表头和数据行列数，变更时停止而非错列写入。
- CSV 必须由脚本调用 `scripts.auto_download.move_report.py` 归档。标准报表名称固定为“千川推广费”，最终目录为 `C:\Users\win\Desktop\data\抖音\千川推广费`。
- 同一天重复运行允许 `move_report.py` 生成 `_002` 等后缀；不得覆盖旧文件。

## 故障处理

- iframe 未出现或找不到「流水对账」：先确认千川已登录、广告账户 ID 有财务权限。
- 无有效日期行：当天数据尚未更新或筛选范围为空，停止并报告页面日期范围。
- 列数不一致：不要手动补齐列，记录实时表头后修复脚本。
