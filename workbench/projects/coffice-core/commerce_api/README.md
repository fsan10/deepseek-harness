# Commerce API CLI

一套 CLI 控制抖音、京东、拼多多、快手、小红书、天猫，并提供千川快捷入口。平台接口按“平台 → 后台 → 业务功能”分类；千川、支付宝、阿里妈妈等后台保存独立会话并单独验证授权。

这是独立开发目录。现有 DOM 下载器、工作台、调度、入库和财务计算继续使用原来的路径。本项目下载到自己的 `.runtime/downloads/`，通过 CLI 显式执行，不注册定时任务、不自动启动轮询、不执行入库。

## 开始使用

当前工作区可以直接使用 PowerShell 入口，无需修改原项目依赖：

```powershell
# 在 commerce_api 目录中
.\commerce.ps1 --help
.\commerce.ps1 platforms
.\commerce.ps1 doctor
.\commerce.ps1 schema pinduoduo
.\commerce.ps1 profiles sync
```

入口优先使用本目录 `.venv\Scripts\python.exe`，其次复用父项目解释器。所有 Python 命令使用 Python 3.12，通过 `-B -m` 运行。独立环境的依赖和 `commerce` 命令入口声明在 `pyproject.toml`，可以在本项目虚拟环境中安装本目录；开发期间没有更改父项目依赖。

`doctor` 检查本地依赖和处理模块的载入情况。实际平台下载验收记录见 [验收说明](docs/ACCEPTANCE.md)。

默认复用父项目未提交的 `.env`，只在当前进程加载登录、Cloak、验证码转发及通知所需配置。也可显式指定配置文件和登录适配器目录：

```powershell
.\commerce.ps1 --env-file .\.env --legacy-root D:\fsan10\mock_coffice doctor
```

密码、令牌、Cookie 和短信答案不作为 CLI 参数，不写入使用示例。无需设置 Windows 用户或系统环境变量。

## 登录和子后台

首次认证使用现有 DOM 登录函数、同一个 Profile 和原有验证通知。认证完成后保存加密 Cookie、浏览器身份及必要的接口上下文，再通过独立 HTTP 验证实际店铺和目标后台权限。

```powershell
.\commerce.ps1 douyin auth login --profile '完整抖音 Profile 名称'
.\commerce.ps1 douyin auth status --profile '完整抖音 Profile 名称'
.\commerce.ps1 qianchuan auth login --profile '完整千川或抖音 Profile 名称'
.\commerce.ps1 pinduoduo auth login --profile '完整拼多多 Profile 名称' --backend cashier
.\commerce.ps1 tmall auth login --profile '完整天猫财务 Profile 名称' --backend alipay
```

`auth status` 通过 HTTP 检查，不自动登录。`auth logout` 删除指定后台的本地加密会话。一个子后台的认证成功只更新这个子后台的状态；原有停用店铺限制继续生效。

新项目的单次登录等待有五分钟保护上限。需要人工处理时保留 Profile 页面并返回状态，处理后继续原任务。

## 下载

```powershell
.\commerce.ps1 xiaohongshu report download --profile '完整 Profile 名称' --kind order --date 2026-10-28
.\commerce.ps1 jd report download --profile '完整 Profile 名称' --kind settlement --month 2026-09
.\commerce.ps1 pinduoduo report download --profile '完整 Profile 名称' --kind promotion --backend promotion --from 2026-10-01 --to 2026-10-28
.\commerce.ps1 qianchuan report download --profile '完整 Profile 名称' --date 2026-10-28
.\commerce.ps1 tmall report download --profile '完整 Profile 名称' --kind fund --backend aggregate --date 2026-10-28
```

`--date`、`--month`、`--from/--to` 三选一。日期按上海时区解释。订单默认近 30 日，资金、结算及推广费默认昨天。`--timeout` 控制导出任务轮询等待；`--poll-interval` 控制轮询间隔。需要验证独立 HTTP 链路时，追加 `--no-login-recovery`，认证失效会直接返回状态。

`--human-timeout` 控制本次等待群回复的时间，默认 300 秒，可设为 1 到 300 秒。提前返回等待状态后，原 Challenge 继续接收，使用 `run resume` 继续等待；这不会改变原服务的五分钟有效期。请求已过期时，沿用原服务的新建接收请求和单次发码规则。

| 平台入口 | 报表 `--kind` | 后台 `--backend` |
|---|---|---|
| `douyin` | `order`、`fund`、`settlement` | `merchant` |
| `douyin` / `qianchuan` | `promotion` / 快捷入口固定推广费 | `qianchuan` |
| `jd` | `order`、`fund`、`settlement` | `merchant` |
| `jd` | `promotion`，同时取得联盟与京东通文件 | `promotion` |
| `pinduoduo` | `order` | `merchant` |
| `pinduoduo` | `settlement` | `cashier` |
| `pinduoduo` | `promotion` | `promotion` |
| `kuaishou` | `order` | `merchant` |
| `kuaishou` | `fund`、`settlement` | `finance` |
| `xiaohongshu` | `order`、`fund`、`settlement` | `merchant` |
| `tmall` | `order`，宝贝销售明细 | `qianniu` |
| `tmall` | `fund` | `aggregate` 或 `alipay` |
| `tmall` | `promotion` | `alimama` 或 `wanxiangtai` |

后台能够唯一确定时可以省略 `--backend`。天猫资金和推广费需要明确后台。视频号暂不实现。

范围资金账单按平台原生账期下载，结果可以包含多份文件。支付宝的范围及月份请求逐日取得明细；聚合资金、京东结算、小红书和快手资金使用相应月账期接口。平台尚未生成目标账期时返回 `NOT_READY`，保留原任务，不用其他日期代替。

## 验证码、文件密码和续跑

下载验证码、文件密码发送均由平台 Web API 触发，接收继续使用现有群通知、短信转发和群回复服务。发送前先登记 Challenge；京东文件密码绑定真实导出 taskId。滑块和登录异常继续交给原登录适配器，普通下载失败使用普通失败通知。

批量任务依次等待回复。同一个群内有多条未完成请求时，需要对机器人对应通知使用“回复”功能后发送提取码，原服务才会唯一匹配；单条请求可直接回复。接收窗口仍为原服务的五分钟，使用 `--human-timeout` 提前返回后继续下一平台时尤其需要注意。

```powershell
.\commerce.ps1 run status --id '返回的 run_id'
.\commerce.ps1 run resume --id '返回的 run_id'
```

Run 保存原请求日期、Profile、后台、已提交任务、Challenge 和文件校验值。重复执行相同请求会复用已有任务及有效文件；网络中断导致提交结果不明时，优先查询原任务，返回 `OUTCOME_UNKNOWN` 的操作不会自动再次提交。续跑会核验原店铺及业务账户。

所有业务命令输出统一 JSON：`ok / data / error / meta`。错误会附带 `code`、阶段、可恢复标志和可用的 `run_id`。验证码、文件密码、签名地址和 Cookie 不写入 Run JSON。成功文件含路径、大小和 SHA-256。

`row_count` 是对应平台查询的记录数；天猫订单查询按主订单统计，下载明细按子订单展开，两者可以不同。资金汇总查询使用 `query_summary_count` 单独注明汇总数量。实际文件内容的验收统计见验收说明。

## 默认关闭的每日登录检查

全局和单个 Profile/后台均需显式开启；默认间隔 1440 分钟。关闭时不会访问平台或浏览器。检查先走 HTTP，确认登录失效后调用原 DOM 登录。需要人工处理的后台暂停自动恢复，等待显式认证。

```powershell
.\commerce.ps1 health policy
.\commerce.ps1 health configure --profile '完整 Profile 名称' --platform pinduoduo --backend promotion --enabled true
.\commerce.ps1 health configure --interval-minutes 1440 --enabled true
.\commerce.ps1 health run --due
# 显式在前台运行周期检查；关闭开关后退出
.\commerce.ps1 health watch
# 关闭全部自动检查
.\commerce.ps1 health configure --enabled false
```

本项目不会安装或修改 Windows 计划任务。若以后接入调度器，调用 `health run --due` 即可沿用同一开关与到期判断。

## 批量任务与扩展

`batch run --plan <JSON文件>` 串行执行计划，`batch resume --id <batch_id>` 继续未完成项。计划只接受登记的报表字段，不执行任意脚本。示例见 [batch.example.json](config/batch.example.json)。日期在创建批量任务时冻结。

代码职责、后续商品操作的接入方式及迁移步骤见 [架构说明](docs/ARCHITECTURE.md)。

开发测试在父目录执行：

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s commerce_api\tests -t . -v
& .\.venv\Scripts\python.exe -B -m commerce_api.tools.check_symbols
& .\.venv\Scripts\python.exe -B -m commerce_api.tools.isolation verify
```

真实接口发现工具位于 `tools/`，仅供开发监听，生产调度不会导入它们。会话及原始捕获使用当前 Windows 用户的 DPAPI 加密；`.runtime/`、`.env`、虚拟环境及构建产物均不进入版本管理。
