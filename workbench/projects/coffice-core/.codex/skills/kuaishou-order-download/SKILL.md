---
name: kuaishou-order-download
description: 在快手小店商家后台通过“订单查询”下载最近一个月的标准订单报表，处理员工登录、导出短信验证码、历史报表文件提取码、受密码保护的 XLSX 解密并归档。用户要求下载快手订单、处理快手订单导出验证或修复对应 Playwright 自动化时使用。
---

# 快手订单报表自动化标准流程

## 适用范围

- 目标 profile 由用户指定；测试 profile 为 `KS-快手-MOCK陌时专卖店`。
- profile note 必须提供 `platform=快手`、公司和店铺；店铺名必须与登录后的“选择登录店铺”卡片一致。
- 只处理订单标准报表，归档标准报表名为 `订单`。资金/结算账单使用 `$kuaishou-bill-download`。
- 页面操作、下载、解密和归档由 Playwright 正式脚本完成；Cloak Login 只负责 profile 生命周期和提供本次 `wsEndpoint`。

## 正式脚本

从项目根目录运行：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_order_download `
  --cdp "<本次 start_profile 返回的 wsEndpoint>" `
  --platform "快手" --company "南京陌时食品科技有限公司" `
  --shop "MOCK陌时专卖店"
```

脚本默认使用 `C:\Users\win\Desktop\data\\.automation_cache\\kuaishou_order\\<店铺>` 保存状态和临时下载，归档根目录默认是 `C:\Users\win\Desktop\data`。可用 `--work-dir`、`--dest` 和 `--business-date` 覆盖。

## 调用编排约束

- 用户要求正常下载时，启动指定 profile、取得本次 `wsEndpoint` 后只调用上面的 Playwright 模块一次；不要额外执行 `rg`、缓存目录检查、单独的中转服务探活、`browser_snapshot`/`browser_read`/`browser_evaluate` 或手工点击命令。
- 中转服务探活、页面等待、短信验证码/文件提取码等待、下载、解密和归档都由脚本在同一进程内完成；脚本等待 Challenge 答案时保持等待，不由大模型代替脚本轮询或操作页面。
- 只有脚本退出码为 `1`（或用户明确要求诊断）时，才进入下方“失败接管规则”：使用同一 profile 的实时 `wsEndpoint` 分析 DOM、网络和状态文件，定位原因，修改正式脚本后重新以单次命令运行。
- 退出码为 `0` 时直接核对脚本输出的归档文件并结束本次 profile；不要为了“确认成功”再开新的历史页或重复运行导出。

## 登录与店铺选择

1. 启动指定 profile 并使用本次实时 `wsEndpoint`，不要复用旧端口。
2. profile 首页若跳转到 `login.kwaixiaodian.com`，点击“我是员工”和“快手商家账号登录”。账号密码由 profile 保存，脚本不读取 Chrome 密码库；只有页面保存凭据未触发登录时才读取进程环境变量 `KUAISHOU_LOGIN_USERNAME`、`KUAISHOU_LOGIN_PASSWORD`（兼容 `KS_LOGIN_USERNAME`、`KS_LOGIN_PASSWORD`）。
3. 出现“选择登录店铺”后，只点击与 profile note 店铺完全匹配的卡片，等待回到 `s.kwaixiaodian.com/zone/`。
4. 如果登录表单为空且没有环境变量，立即报告前置条件缺失；不得猜测或输出密码。

## 页面标准流程

1. 在已登录首页点击“订单查询”，不要把登录前的深链接当作登录凭据；正常路由为 `/zone/order/list`。
2. 等待“开始时间”“结束时间”输入框可见；若查询条件被折叠、暂时看不到开始时间，先点击可见的“展开全部”，再继续定位输入框。在 Ant Design 日期弹层选择“最近一个月”，等待两个输入框均有值；当前版本的快捷项实际位于 `.ant-picker-dropdown li.ant-picker-preset`。只有快捷项不可用时，才回退为开始日 `结束日-29` 的 `00:00:00` 和结束日 `23:59:59`，并按 Enter 提交。
3. 点击“查询”，监听订单查询响应或页面重绘，使用短的动态等待，不固定长时间空等。
4. 点击“导出数据”。侧栏中检查“标准报表”的 active 状态，未选中时才点击；然后点击侧栏内“导出”。
5. 若出现短信验证码弹窗，先探活自动化验证码服务，再创建 `verification_code` Challenge，点击“获取验证码”，等待负责人回复后填写并点击“生成报表”。验证码错误时只重试挑战，不重复创建订单导出任务。
6. 没有验证码时，确认侧栏关闭或出现成功/频控提示后再记录任务已提交。出现 5 分钟频控时不要再次点击导出，改用历史记录复用。

## 历史记录、提取码和文件处理

1. 快手不会自动跳转导出历史；脚本新建标签页打开 `https://s.kwaixiaodian.com/zone/order/exportList`，轮询 `li.ant-list-item`，按“标准报表”、结束日期和生成时间选择最新任务。每 30 秒才刷新一次页面，避免破坏 SPA 上下文。
2. 若行内有“发送文件提取码”，先创建 `archive_password` Challenge，再点击该按钮；出现确认弹窗时必须点击“确定”，否则不能认为提取码已发送。进程重启时复用状态文件中的 Challenge ID，不重复点击发送。
3. 点击“下载报表”并用 `page.expect_download()` 保存到工作目录。快手订单通常是受密码保护的 XLSX，不是 ZIP。
4. 使用 `msoffcrypto-tool` 以负责人回复的原始文件提取码解密为普通 XLSX，再用 `openpyxl` 校验至少存在一个工作表，最后调用 `move_report.py` 归档到 `快手/订单`。解密失败时明确提醒“文件提取码错误”，最多重新申请 3 次，不重复下载。
5. 下载文件、解密中间文件和状态文件只有在归档成功后才清理；失败时保留现场供同一 profile 重跑。

## 失败接管规则

- 退出码 `1` 时，用同一 `wsEndpoint` 的 Playwright 读取当前 URL、可见登录/店铺卡片、日期输入值、导出侧栏、验证码弹窗、历史行、下载事件和文件大小，先定位失败阶段再修复正式脚本。
- 不把隐藏旧节点、静态帮助文案或历史无关行当作当前挑战/频控；所有候选均要求可见并尽量限定在当前抽屉或 `ant-list-item`。
- 验证码与文件提取码均通过 `automation_challenge.py` 的类型化 Challenge 转发；不要把答案写入源码、日志或状态文件。
- 修复后运行 `scripts.auto_download.tests.test_kuaishou_order_download` 和既有 `test_kuaishou_downloads`，再使用真实 profile 完整重跑并核对归档路径、文件大小和 XLSX 可读性。

## 输出约定

最终文件名由 `move_report.py` 生成：

```text
YYYYMMDD_快手_公司_店铺_订单.xlsx
```

退出码：`0`=下载、解密、校验、归档成功；`1`=登录、页面、Challenge、下载、解密或归档失败；`2`=命令参数错误。
