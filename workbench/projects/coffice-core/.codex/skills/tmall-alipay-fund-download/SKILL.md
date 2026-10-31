---
name: tmall-alipay-fund-download
description: 登录天猫并下载支付宝账户资金或聚合账户资金的最新日/月明细，支持指定历史日，按对应标准报表增量归档。用户要求下载天猫支付宝账单、聚合账户资金、日/月资金明细，测试两类资金单并行下载，或相关 Playwright 自动化失败需要接管修复时使用。
---

# 天猫账户资金下载

根据报表运行 `tmall_alipay_fund_download.py` 或 `tmall_aggregate_fund_download.py`。两者复用同一 Playwright 登录扩展；Cloak Login 仅用于选择/启动 profile 和取得 `wsEndpoint`。

## 执行

1. 用 Cloak Login `list_profiles` 精确选择 profile：
   - 支付宝账户资金：`TMALL-天猫-MOCK旗舰店-财务账号`
   - 聚合账户资金：`TMALL-天猫-MOCK旗舰店`
2. 从 profile `note` 解析：
   - `platform=天猫`
   - `company=墨客咖时(南京)生物科技有限公司`
   - `shop=MOCK旗舰店`
3. 若 profile 未运行则调用 `start_profile`，取得实时 `wsEndpoint`。
4. 按用户要求执行日账单、指定历史日或完整自然月账单：

   ```powershell
   & 'D:\fsan10\mock_coffice\.venv\Scripts\python.exe' -m scripts.auto_download.playwright.tmall_alipay_fund_download `
     --cdp <wsEndpoint> `
     --platform 天猫 `
     --company "墨客咖时(南京)生物科技有限公司" `
     --shop "MOCK旗舰店" `
     --mode month
   ```

   聚合账户资金改用：

   ```powershell
   & 'D:\fsan10\mock_coffice\.venv\Scripts\python.exe' -m scripts.auto_download.playwright.tmall_aggregate_fund_download `
     --cdp <wsEndpoint> `
     --platform 天猫 `
     --company "墨客咖时(南京)生物科技有限公司" `
     --shop "MOCK旗舰店" `
     --mode month
   ```

   最新日账单时将两个命令的 `--mode month` 改为 `--mode day`；指定历史日时保留 `--mode day` 并增加 `--date YYYY-MM-DD`。日期范围必须逐日执行，每个账户都要覆盖范围内的每一天；完整自然月才使用 `--mode month`。

5. 检查退出码和输出路径；成功文件必须非空，并进入 `C:\Users\win\Desktop\data\天猫\支付宝账户资金` 或 `聚合账户资金` 子目录。支付宝流程还必须确认 ZIP 已删除且汇总文件未保留。
6. 下载完成后调用 `stop_profile` 关闭浏览器进程，避免占用端口。

## 登录约束

- 登录扩展：`scripts/auto_download/playwright/login_extensions/tmall_finance_login.py`。
- 支付宝账户使用账号 `MOCK旗舰店` 和环境变量 `TMALL_LOGIN_PASSWORD`；聚合账户使用账号 `mock旗舰店:IT` 和环境变量 `TMALL_IT_LOGIN_PASSWORD`。Windows 下进程未继承新值时，自动读取当前用户环境变量。
- 登录表单通常位于 `iframe#alibaba-login-box`；直接登录页则在主文档。
- 点击密码框后若出现滑块验证，使用 Playwright 自动完成；验证失败时自动重试，通过后继续登录，无需通知用户或附加参数。

## 支付宝账户资金流程

1. 千牛首页：`https://myseller.taobao.com/home.htm`。
2. 悬浮 `div[class*="shopName--"]` 的账号容器，点击精确文本「账号信息」；失败时直达 `/home.htm/merchant-user-info`。
3. 在 `div.info-item` 且包含「绑定支付宝」的行内点击「查看详情」，接管新标签页。
4. 淘宝绑定页：`https://passport.taobao.com/ac/alipay_management.htm?fromSite=0&bizcode=taobao`；点击精确文本「进入支付宝」。
5. 支付宝点击「对账中心」和左侧「账单下载」；最终 URL 为 `/page/mbillexprod/bill/download/fundBill`。
6. 若 `div[class*="currentBtn"]` 未包含「列表模式」，点击 `div[class*="defaultBtn"]` 中的「列表模式」。每次都检查，不能依赖上次状态。
7. 日/月单选用 `input[type=radio][value=day|month]`。
8. 按页面顺序遍历 `tr.ant-table-row.ant-table-row-level-0`，跳过显示「账单未生成」或没有「账单下载」的行；指定 `--date` 时只选择日期完全匹配的可下载行，否则选择第一条可下载账单。日日期格式为 `YYYY-MM-DD（周X）`，月日期格式为 `YYYY-MM`。

## 聚合账户资金流程

1. 登录成功后在当前标签页打开 `/home.htm/whale-accountant/pay/capital/home?active=fund_day`。
2. 日汇总保持默认页面；月汇总点击「月汇总」。
3. 读取第一条可下载数据行的日期并点击行内「下载明细」。
4. 捕获平台文件并调用 `move_report.py`，报表名使用 `聚合账户资金`；日汇总用 `YYYYMMDD`，月汇总用 `YYYYMM`。

## 下载与归档

- 下载用 `page.expect_download()` 捕获，并用 `download.save_as()` 保存到系统临时目录，不经过浏览器默认下载目录。
- ZIP 未设置 UTF-8 标志，`zipfile` 会按 CP437 显示乱码。调用 `scripts.auto_download.extract_report`，把原始文件名字节按 GBK 修复。
- 只提取文件名包含 `账务明细` 且不包含 `(汇总)` 的唯一成员；月账单明细可能带 `_1` 等序号后缀，不能只匹配完整文件名 `账务明细.csv`。内容保持平台原始 GBK 编码。
- 提取成功后删除 ZIP；汇总成员不落盘。
- 调用 `scripts.auto_download.move_report`，报表名必须为 `支付宝账户资金`。日账单用 `YYYYMMDD`，月账单用 `YYYYMM`，同名文件自动递增。
- 聚合账户文件无需解压，下载后直接按 `聚合账户资金` 归档；同名文件同样自动递增。
- 两个脚本的 `--date` 只支持与 `--mode day` 一起使用；指定范围下载时复用同一个已启动 profile，按日期升序逐日执行，不能用最新日账单代替历史日期。

## 失败接管

1. 退出码 `1`：AI 用 Playwright 连接同一 `wsEndpoint`，读取当前 URL、frame 树、错误和可见 DOM，分析失败原因并继续完成任务。
2. 登录失败时先检查输入长度、按钮状态、滑块 frame 与真实边界框；不得根据隐藏旧滑块推测密码错误，也不得改用 Cloak Login 点击表单。
3. 修复脚本后再次运行并验证实际下载；不能只报告脚本失败。
4. 接管流程仍须使用 Playwright，并核对最新可下载业务日期、ZIP 成员唯一性、最终文件存在且非空。
