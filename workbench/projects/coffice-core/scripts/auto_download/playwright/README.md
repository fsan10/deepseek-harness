# Playwright 脚本目录

本目录存放通过 **Playwright** 驱动浏览器自动化的脚本，统一使用 CDP 方式连接 Cloak Login 已启动的 profile（`start_profile` 返回的 `wsEndpoint`），不新建浏览器实例。

所有新报表统一归档到 `C:\Users\win\Desktop\data\平台\标准报表名\YYYY.MM\`，也可通过 `--dest` 指定根目录。月份按报表业务日期确定；自定义区间按结束月份保存。同名文件递增保存，流程编排遵循相同规则。后台批量补跑、旧文件整理和部署说明见 [上级使用说明](../README.md)。

京东结算、快手资金、小红书资金/结算支持 `--mode day --date YYYY-MM-DD` 或 `--mode month --month YYYY-MM` 精确定位历史账单；未指定日期继续获取最新可下载账单。天猫淘宝联盟/万相台支持成对的 `--start-date`、`--end-date`，以及 `--mode month --month YYYY-MM`。历史期间必须真实生效，找不到目标账单会停止，不会下载最新账单作为替代。

天猫支付宝账户资金支持 `--mode day --start-date YYYY-MM-DD --end-date YYYY-MM-DD`：查询整段日期后一次点击「批量下载」，校验每天恰好一份明细，并按各自业务日归档；汇总文件不落盘。范围参数不能与 `--date` 同用，缺少、重复或账户不一致的明细会停止归档。

## 通用前置条件

短信自动接收在后台「AI 管理 → 短信转发机器人」配置：关联现有验证码接收配置，填写同群自定义机器人的 Webhook，完成接收测试后启用。Webhook 与可选签名 Secret 加密保存，不回显；接收测试会向配置的机器人发送一条无真实验证码的消息并确认来源身份。每次 Challenge 总等待 5 分钟，前 2 分钟自动读取短信；未收到有效代码或平台判定代码错误后，通过原飞书应用和群通知人工，人工在剩余时间回复即可继续。人工也可提前回复；错误答案不会自动再次使用，重试不延长原请求截止时间。群历史读取需要接收应用具备相应权限；同一平台、同一短信来源且短信无法区分店铺时，任务必须串行。

自动短信与人工回复接收成功后，群里都会收到“验证码已收到，自动化任务将继续。”、“解压密码已收到，自动化任务将继续。”或“文件提取码已收到，自动化任务将继续。”；回执不包含原始代码。抖音已下载 ZIP 的解压节点恢复时，已收到且仍有效的密码直接继续使用；尚未收到时重新发送带平台、公司、店铺、用途及页面链接的人工提醒。原请求过期后，新建 5 分钟人工等待，请回复该 ZIP 对应的原始密码。

1. 安装 Playwright：`pip install playwright`（无需执行 `playwright install`，因为连接的是 Cloak Login 已启动的 Chrome）。
2. 用 Cloak Login 启动目标 profile（如「DY-抖音-MOCK咖啡旗舰店」），并确保浏览器已登录抖店商家后台。
3. 从 `start_profile` 的返回结果获取 CDP 地址，例如：
   `ws://127.0.0.1:63055/devtools/browser/63a13b44-214b-41d3-adb6-222c6c81cff2`
4. 在仓库根目录执行脚本（模块路径以 `scripts.auto_download.playwright.` 开头）。

## 抖音登录态恢复（订单/资金结算/千川共用）

抖店 profile 默认打开 `https://fxg.jinritemai.com/ffa/mshop/homepage/index`。订单、账单和千川脚本现在统一调用
`douyin_login.py`：目标深链被重定向到登录页时，先检测登录根节点
`//*[@d="root"]/div/div[1]/div/div/div/div`（同时兼容 `#ecomLoginForm` 和邮箱输入框），再点击邮箱登录
`//*[@id="ecomLoginForm"]/section/div[2]/div[2]`，复用 profile 已保存的邮箱/密码，勾选协议
`//*[@id="root"]/div/div[1]/div/div/div/div/div[2]/div[4]/div[1]/label/span/input`，先触发当前 profile 的保存凭据回填，
并仅在登录按钮仍可见时补点“登录”。

登录后的页面可能仍保持 `/login/common` URL，但正文变为“请选择店铺”。脚本通过 profile note 的 `shop` 完整文本精确选择店铺，
不固定点击第一项。若未出现 `//*[@id="captcha_container"]/iframe` 或当前版本的验证码 iframe，直接继续业务流程；若出现真实滑块，
脚本发送飞书人工接手提醒，保留当前 profile 并等待用户完成验证，随后继续进入店铺选择或业务页面，超时才退出码为 1。

### 网易易盾基础滑块示例

`jigsaw_slider_demo.py` 用于 `https://dun.163.com/trial/jigsaw` 的嵌入式模式诊断：它发现 iframe/轨道/手柄并输出坐标；传入人工测得的
`--target-offset` 时只发送一次普通拖拽，不自动识别缺口、不读取令牌、不判断或重试验证码结果。应使用独立测试 profile，不要把抖音登录页或验证 URL 传给该示例。

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.playwright.jigsaw_slider_demo `
  --cdp "<独立测试 profile 的 wsEndpoint>"
```

## Profile 命名与备注规范（参数传递契约）

每个店铺对应一个 Cloak Login profile，`name` 与 `note` 是后续 AI 自动提取
`platform / company / shop` 参数（供下载脚本和 API 使用）的唯一事实来源，
调用方通过 `list_profiles` 获取并按此规范解析，禁止硬编码参数。

- **name（标题，缩写仅供人看）**：`<平台缩写>-<平台中文>-<店铺名>`
  - 示例：`DY-抖音-MOCK咖啡旗舰店`、`KS-快手-MOCK音咖专卖店`、`XHS-小红书-MOCK旗舰店`
  - 平台缩写字典：`DY=抖音`、`KS=快手`、`PDD=拼多多`、`JD=京东`、`TMALL=天猫`、`XHS=小红书`
- **note（备注，供机器解析）**：键值对，参数一律使用中文全称，半角标点，分隔符 `;` 与 `=`
  - 格式：`platform=<平台中文>;company=<公司名>;shop=<店铺名>`
  - 示例：`platform=抖音;company=舟益生物科技(南京)有限公司;shop=MOCK咖啡旗舰店`
- **报表类型（report_type）不写进 profile**：一个表单对应一个下载脚本，在脚本内以常量定义。
- 解析示例（Python）：
  ```python
  import re
  m = re.search(r"platform=([^;]+);company=([^;]+);shop=([^;]+)", note)
  platform, company, shop = m.group(1), m.group(2), m.group(3)
  ```

## 标准报表名称（与数据导入中心一致）

`move_report.py` 不再使用“资金/结算/订单/推广费”四个笼统选项，而是直接校验数据导入中心的 28 类注册表：

| 平台 | 标准报表名称 |
|---|---|
| 抖音 | 订单、资金、结算、千川推广费 |
| 京东 | 订单、资金、结算、京东通推广费、京东联盟推广费 |
| 天猫 | 订单、支付宝账户资金、聚合账户资金、结算收入、结算支出、淘宝联盟推广费、万相台推广费 |
| 快手 | 订单、资金、结算 |
| 拼多多 | 订单、结算、推广费 |
| 视频号 | 订单、结算 |
| 小红书 | 订单、资金、结算|

传给 `--report` 的值必须是对应平台这一列中的标准名称。文件名为
`YYYYMMDD_平台_公司_店铺_报表名称.ext`（日）或
`YYYYMM_平台_公司_店铺_报表名称.ext`（月）；存在同组多文件时追加
`_002`、`_003`。

对配置了表头校验的下载报表，验收按字段名确认必需列，不要求列顺序完全一致，也允许平台新增列；
缺少必需列仍会阻止归档。新增列和当前不会读取的额外工作表会给出提示并继续下载。
下载验收放行不代表新增字段已纳入 ODS，字段是否入库仍由现有导入配置决定。

---

## 六个平台串行总控

总控入口为 `scripts.auto_download.run_all_platform_downloads`，默认读取
`scripts/auto_download/all_platform_downloads.json`。总控每次运行都会先通过 Cloak Login MCP
读取完整 profile 清单，再按 `profile_rules` 和 profile note 为**所有匹配的 profile**生成计划，
串行执行抖音、京东、拼多多、快手、小红书和天猫的正式 Playwright 模块。普通店铺优先按命名
规范匹配，命名不带平台前缀时按 note 中的平台兜底匹配，因此新增店铺 profile 后无需再把店铺名
写入 JSON。

总控启动或复用每个 profile，并从 profile note 取得 `platform/company/shop`；不把公司、店铺或凭据
写入总控配置。抖音普通店铺与千川 profile、天猫商家 profile 与财务账号 profile 使用独立规则，
避免同一个 profile 执行错误的报表集合。

在仓库根目录执行：

```powershell
# 原有行为：一次串行执行全部平台、全部步骤
& ".venv\Scripts\python.exe" -m scripts.auto_download.run_all_platform_downloads

# 凌晨通道：预计无需人工验证码的步骤（包含全部拼多多、天猫步骤）
& ".venv\Scripts\python.exe" -m scripts.auto_download.run_all_platform_downloads `
  --lane overnight

# 上午可交互通道：补齐验证码步骤，并补跑凌晨没有成功的步骤
& ".venv\Scripts\python.exe" -m scripts.auto_download.run_all_platform_downloads `
  --lane interactive --lock-wait-seconds 21600
```

两个定时通道共用同一份 JSON、同一个本地日期检查点和同一套 profile 生命周期。凌晨通道执行
京东结算/资金/推广费、拼多多全部报表、快手资金/结算、小红书全部报表、天猫全部报表；上午通道
覆盖完整计划，但会先跳过凌晨已经成功的步骤，因此正常情况下只需执行抖音/千川、京东订单、
快手订单以及凌晨失败或遇到验证的步骤。若一个 profile 在当前通道的步骤都已有成功检查点，总控
不会重新启动它；若它因上次关闭失败仍在运行，只补偿关闭。共享互斥锁保证凌晨任务尚未结束时，
上午任务不会并发操作 profile 或覆盖检查点。未传 `--lane` 时仍执行 `all`，与拆分前行为一致。

总控默认执行各平台最新日报表/近 30 天订单脚本；每个平台及报表的具体顺序和参数都在
`all_platform_downloads.json` 的 `profile_rules` 中维护。`managed_profile_name_prefixes` 用于
校验传统命名 profile 的管理范围；普通规则启用 `match_all_profiles_with_platform` 后，未带标准
前缀但 note 中平台属于六个平台的 profile 也会兜底纳入。`strict_profile_coverage=true` 时，
管理范围内但未匹配规则的 profile 会在执行下载前直接报错，避免静默漏下载。千川步骤使用
`--aavid auto`，从当前 profile 页面 URL 的 `aavid` 参数读取广告账户 ID。
每个步骤可用 `lanes` 指定 `overnight`、`interactive`；不配置 `lanes` 的旧配置在两个通道和
`all` 模式中都会执行，以保持向后兼容。

店铺是否参与每日下载由 JSON 的 `profile_status` 控制，key 使用 Cloak Login 的完整 profile 名称。
未配置的 profile 默认执行；停业、暂停或关闭的店铺可设置为：

```json
"profile_status": {
  "DY-抖音-MOCK咖啡旗舰店": {
    "enabled": false,
    "status": "停业整顿",
    "reason": "店铺停业整顿，暂不下载报表"
  }
}
```

`enabled=false` 或 `status` 不是 `active`、`正常`、`启用`、`运行` 时，总控会记录为
`disabled`，不启动该 profile、不执行任何下载，也不会由 AI 自动恢复。`strict_profile_status=true`
时，JSON 中写了但 Cloak Login 不存在的 profile 会直接报错，防止店铺改名后状态配置失效而被误执行。

总控按本地日期在 `C:\Users\win\Desktop\data\.automation_logs\all_platform_downloads\checkpoints`
写入 `checkpoint_YYYY-MM-DD.json`。每个 profile 的每个步骤成功后立即原子写入检查点；同一天因
页面、登录或权限问题失败，修复后再次执行同一条总控命令，会跳过已经记录为成功的步骤，只从
第一个未完成步骤继续。检查点同时记录 profile note 指纹；公司、店铺或平台 note 发生变化时，
该 profile 的旧步骤状态会自动失效，避免错复用。
同一天修改 `profile_status`、说明文字或步骤 `lanes` 不会清空已成功步骤；步骤名称、模块或参数
变化后会形成新的步骤键，只重跑变化项。若归档目标目录变化，则创建新的执行上下文状态，避免把
旧目录中的文件误认为新目录已经下载。

每次运行都会在 `C:\Users\win\Desktop\data\.automation_logs\all_platform_downloads`
生成 `.log` 和 `.summary.json`：日志带时间、profile、步骤、模块、子脚本输出、退出码、耗时和
完整异常上下文；汇总文件保存各 profile、各步骤的机器可读结果。

CDP 地址、密码、令牌和授权信息会在日志、汇总和异常文本中脱敏。总控遵循失败即停：某个正式脚本
返回非零退出码时不继续启动后续 profile，保留该脚本的工作目录、检查点和下载现场，退出码为 `1`，
供 Codex 按对应平台 Skill 接管诊断、修复后重新调用总控；总控会依据检查点跳过已经成功的 profile
步骤。所有步骤成功或从检查点全部恢复完成时退出码为 `0`。

---

## douyin_bill_download.py

抖店账单报表下载（结算/资金账单，日汇总/月汇总），自动生成报表、等待可下载、下载并按规则归档到 `C:\Users\win\Desktop\data`。

### 功能

- 账单管理 → 结算账单/资金账单 → 日汇总/月汇总；指定范围时先查询日期范围，再点击「批量下载」→「生成」生成一份区间报表。
- 跳转历史报表页后，**每 30s 刷新页面**轮询第一张报表卡状态（历史报表页不会自动刷新），直至「可下载」。
- 用 Playwright `expect_download` 捕获下载（Playwright 连接会接管下载，文件不落浏览器 Downloads 目录）并 `save_as` 到归档路径。
- 归档规则与 `move_report.py` 一致：`YYYYMMDD_平台_公司_店铺_报表类型.ext`（日）或 `YYYYMM_...`（月），同路径已存在自动递增 `_002`。
- 日汇总支持 `--start-date` / `--end-date`，会查询范围后通过「批量下载」→「生成」归档一份区间报表；文件名日期使用结束日期；不传时仍下载第一行最新日/月汇总。
- 报表类型和目录始终使用数据导入中心注册表中的标准名称“结算/资金”；日/月粒度只由 `YYYYMMDD_` 或 `YYYYMM_` 日期前缀区分，网页导入时忽略该前缀。

### 用法

```
python -m scripts.auto_download.playwright.douyin_bill_download --cdp <wsEndpoint> --platform <平台> --company <公司> --shop <店铺> [--report 结算|资金] [--mode day|month]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | Cloak Login `start_profile` 返回的 wsEndpoint |
| `--platform` | 是 | 平台中文名（取自 profile note） |
| `--company` | 是 | 公司全称，半角括号（取自 profile note） |
| `--shop` | 是 | 店铺名（取自 profile note） |
| `--report` | 否 | 结算 / 资金，默认结算 |
| `--mode` | 否 | day（日汇总）/ month（月汇总），默认 day |
| `--src` | 否 | 浏览器下载目录，默认 `C:\Users\win\Downloads`（仅回退路径用） |
| `--dest` | 否 | 目标根目录，默认 `C:\Users\win\Desktop\data` |
| `--pattern` | 否 | 源文件匹配模式，默认 `DL*` |
| `--start-date` / `--end-date` | 否 | 自定义日汇总日期范围，必须同时提供，格式 `YYYY-MM-DD`；仅支持 `--mode day`，查询后批量生成一份区间报表，文件名日期为结束日期 |

退出码：`0`=成功；`1`=执行失败；`2`=参数错误。

### 示例

```powershell
# 结算账单 · 日汇总（最新一天）
python -m scripts.auto_download.playwright.douyin_bill_download `
  --cdp "ws://127.0.0.1:57925/devtools/browser/5b3bbcf5-6f9d-4c04-8818-10daea1c6fc5" `
  --platform 抖音 --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK官方旗舰店" `
  --report 结算 --mode day

# 结算账单 · 月汇总（最新一月）
python -m scripts.auto_download.playwright.douyin_bill_download `
  --cdp "ws://127.0.0.1:57925/devtools/browser/5b3bbcf5-6f9d-4c04-8818-10daea1c6fc5" `
  --platform 抖音 --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK官方旗舰店" `
  --report 结算 --mode month

# 资金账单 · 指定日期范围（批量生成一份区间报表）
python -m scripts.auto_download.playwright.douyin_bill_download `
  --cdp "ws://127.0.0.1:57925/devtools/browser/5b3bbcf5-6f9d-4c04-8818-10daea1c6fc5" `
  --platform 抖音 --company "津果日记生物科技(南京)有限公司" --shop "MOCK冲饮旗舰店" `
  --report 资金 --mode day --start-date 2026-09-01 --end-date 2026-09-06
```

### 实测记录

| 模式 | 报表 | 结果 |
|---|---|---|
| month | 2026-07 结算月汇总 | 生成→可下载→下载→归档 `202607_抖音_墨客咖时(南京)生物科技有限公司_MOCK官方旗舰店_结算.csv` |

### 依赖与注意事项

- 依赖：`playwright`（Python 包）。
- 历史报表页**不会自动刷新**，脚本内置 30s 间隔 `reload` 轮询「可下载」。
- 下载按钮必须用 JS `evaluate("el => el.click()")` 触发；Playwright 真实 click 可能不触发下载。
- Playwright 连接接管下载：必须用 `page.expect_download()` + `download.save_as()`，不能扫描浏览器 Downloads 目录（会误抓残留旧文件；`--src` 目录扫描仅作为超时回退路径）。
- 月汇总首行操作按钮同样是「下载明细」（没有「生成报表」按钮）。
- tab 用文本精确定位（`exact=True`），避免「日汇总」误匹配「资金流水明细」等。

---

## douyin_date_picker.py

抖店订单管理页（`fxg.jinritemai.com/ffa/morder/order/list`）日期区间自动选择并查询，返回筛选后的订单总条数。

### 功能

- 通过 CDP 附加到已运行的 Cloak Login profile，复用现有登录态。
- 自动打开日期弹层（筛选区展开后优先点击可见的开始范围输入框，旧版回退开始时间；失败时降级为聚焦 + 空格键）。
- 按日期区间类型选择操作面板：
  - **同月区间**：只用左面板切到起始月，在左面板依次点起始日、结束日，绝不操作右面板（避免 auxo 联动把左面板月份带偏）。
  - **跨月区间**：左面板切到起始月点起始日，右面板切到结束月点结束日。
- 点击确定后校验主输入框值（`YYYY/MM/DD 00:00:00 ~ YYYY/MM/DD 23:59:59`），不符即报错。
- 点击查询并等待结果条数文本更新（跳过加载瞬间的旧值），打印「共N条」。

### 用法

```
python -m scripts.auto_download.playwright.douyin_date_picker --cdp <wsEndpoint> --start YYYY-MM-DD --end YYYY-MM-DD [--url <订单管理页地址>]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | Cloak Login `start_profile` 返回的 wsEndpoint |
| `--start` | 是 | 起始日期，格式 `YYYY-MM-DD` |
| `--end` | 是 | 结束日期，格式 `YYYY-MM-DD` |
| `--url` | 否 | 订单管理页地址，默认官方地址 |

退出码：`0`=成功；`1`=执行失败；`2`=参数/连接错误。

### 示例

```powershell
# 同月区间：2026-06-01 ~ 2026-06-02
python -m scripts.auto_download.playwright.douyin_date_picker `
  --cdp "ws://127.0.0.1:63055/devtools/browser/63a13b44-214b-41d3-adb6-222c6c81cff2" `
  --start 2026-06-01 --end 2026-06-02

# 跨月区间：2026-06-30 ~ 2026-07-01
python -m scripts.auto_download.playwright.douyin_date_picker `
  --cdp "ws://127.0.0.1:63055/devtools/browser/63a13b44-214b-41d3-adb6-222c6c81cff2" `
  --start 2026-06-30 --end 2026-07-01
```

### 实测记录

| 日期区间 | 类型 | 结果 |
|---|---|---|
| 2026-06-07 ~ 2026-06-08 | 同月 | 共542条 |
| 2026-06-30 ~ 2026-07-01 | 跨月 | 共224条 |
| 2026-07-01 ~ 2026-07-03 | 同月（需切月） | 共211条 |

### 依赖与注意事项

- 依赖：`playwright`（Python 包）。
- 优先定位可见的「开始范围/结束范围」输入框，旧版回退到「开始时间/结束时间」；页面布局变化时需同步更新选择器。
- 查询结果条数元素 `.index_selectedPrompt__si2uH` 为哈希类名，若页面改版需重新定位。
- 连续快速点面板翻月按钮会因 React 竞态丢步，脚本已内置"每次点击后等待月份文本变化"。

---

## douyin_order_download.py

抖店订单标准报表下载闭环：设置近 30 日或自定义下单时间、查询、创建一次导出任务、等待历史报表可下载，
再处理下载验证、加密 ZIP、解压和归档。适用于 `DY-抖音-MOCK咖啡旗舰店` 等使用相同订单页的店铺。

### 功能

- 兼容订单页 A/B 版本：新页面从首页点击“订单管理”后使用「开始范围/结束范围」，旧页面使用「开始时间/结束时间」；
  有「展开」时先展开。优先使用日期范围右侧的快捷下拉（旧版与日期框同级、约 125px 宽）选择「近30日」，
  也兼容新版日期弹层中的「近一个月/近1个月/最近一个月/近30日/近30天/最近30天」；只有快捷项不可用时才使用日历面板。
  抖店快捷“近30日”按结束日往前 30 天计算（含结束日共 31 个日期），例如 2026-08-25 的范围是 2026-07-26 至 2026-08-25。
- 支持 `--start-date` / `--end-date` 自定义下单日期范围；提供时按日期面板的 `title` 精确选择并校验起止时间，不再使用近30日快捷项。
- 查询完成后读取可见订单总数；指定范围订单数为 0 时输出日志并跳过导出任务，不再打开导出面板。
- 创建任务与下载任务分离。创建成功后会在工作目录保存状态；检测到可见短提示中的“操作过于频繁/重复提交任务/
  5 分钟内不能重复生成”时，将任务视为已存在并复用导出记录，不会重复创建订单报表；不会把整个页面正文或隐藏旧节点
  中的同名文字误判为频控。
- 查询等待有明确上限并使用短随机渲染等待；响应未匹配时只观察页面，不重复点击查询，避免旧版接口差异造成长时间空等或重复提交。
- 历史报表按标准报表类型、目标结束日期和最新生成时间定位，先在当前历史页轮询，约每 30 秒才刷新一次；刷新后若离开历史页，
  会重新进入“导出记录”。只有出现对应记录的「下载报表」才开始下载。
- 标准报表导出后如果出现“请注意”敏感信息提示，会等待弹窗渲染并点击弹窗内的“确认”（兼容旧版“确定”）；兼容
  旧版 `.auxo-modal-confirm` 和新版 `.aurora-modal.aurora-modal-confirm`，仅在弹窗关闭后才记录任务创建成功。
- 下载验证不是必现步骤：点击“下载报表”后若 Playwright 先收到 ZIP 下载事件，直接进入解压密码流程，不创建验证码 Challenge，
  也不寻找验证码输入框。只有检测到包含“下载验证/获取验证码”且有可见输入框的真实弹窗时，才进入自动化验证码转发流程；
  验证码服务探测或创建失败时，会重新点击「获取验证码」后重试，最多重试 3 次；已成功创建 Challenge 时不会重复发送短信。
  验证码挑战与 ZIP 解压密码挑战使用不同类型。页面明确拒绝验证码时，会发送“上一次验证码输入错误，请重新输入”的提醒并重新请求；
  密码错误时同样发送“上一次解压密码输入错误，请重新输入”的提醒。两种重试都不会重新生成或下载订单报表。
- 解压密码接收在触发下载前启动；出现下载验证时，填写验证码后先登记密码接收，再点击“确定”。密码随下载立即发送也能接收，验证码错误时撤销该次未使用的密码请求。
- 使用 Playwright 下载事件保存 ZIP 到工作目录，提取唯一 CSV/XLSX/XLS，并调用 `move_report.py` 归档到
  `C:\Users\win\Desktop\data\抖音\订单`。归档文件名为
  `YYYYMMDD_抖音_公司_店铺_订单.csv`（实际扩展名随下载文件）。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.douyin_order_download `
  --cdp "<wsEndpoint>" --platform "抖音" `
  --company "舟益生物科技(南京)有限公司" --shop "MOCK咖啡旗舰店"
```

自定义日期范围示例：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.douyin_order_download `
  --cdp "<wsEndpoint>" --platform "抖音" `
  --company "津果日记生物科技(南京)有限公司" --shop "MOCK冲饮旗舰店" `
  --start-date 2026-09-01 --end-date 2026-09-06
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 本次启动抖音 profile 返回的 CDP `wsEndpoint`。 |
| `--platform` | 否 | 平台中文名，默认 `抖音`；应与 profile note 一致。 |
| `--company` | 是 | 公司全称，应与 profile note 一致。 |
| `--shop` | 是 | 店铺名，应与 profile note 一致。 |
| `--work-dir` | 否 | 可恢复的 ZIP、解压和状态目录；默认 `C:\Users\win\Desktop\data\\.automation_cache\\douyin_order\\<店铺>`。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |
| `--business-date` | 否 | 文件日期前缀，格式 `YYYY-MM-DD`；默认近 30 日结束日期。 |
| `--start-date` / `--end-date` | 否 | 自定义下单日期范围，必须同时提供，格式 `YYYY-MM-DD`；不提供时使用近 30 日。 |

### 验证码转发配置

服务地址默认为 `http://127.0.0.1:8770`，可通过 `AUTOMATION_RELAY_URL` 覆盖；令牌优先读取
`AUTOMATION_ROBOT_TOKEN`，兼容 `INGEST_ROBOT_TOKEN`。后台验证码转发配置需要启用抖音平台范围。
验证码和解压密码不会写入日志、状态文件或归档文件名。飞书群中回复验证码或密码后，机器人会按当前
Challenge 类型拦截并回复对应的“已收到”提示。脚本在下载验证弹窗出现后先对转发接口做无副作用探测；
若转发服务发生临时网络/服务错误，会重新点击“获取验证码”并重试，最多 3 次；令牌缺失或无权限等配置错误仍会直接退出并保留页面。

登录滑块不创建需要回复的 Challenge；检测到真实登录验证码 iframe 后，脚本会向抖音转发群发送人工接手提醒，
保留当前 profile 并等待负责人完成滑块，随后继续进入店铺选择或业务页面。滑块提醒接口为
`POST /api/automation/verification/notices`，需要重启已运行的统一服务后才会生效。

### 状态恢复与退出码

工作目录的 `douyin_order_task.json` 和 ZIP 是恢复依据。状态为已确认创建导出任务或 ZIP 已下载时，重跑会
直接进入历史报表/解压阶段；旧版本没有确认凭据的状态会先核对目标日期的历史记录，找不到时自动恢复为待创建，
避免因确认弹窗漏点造成“不断打开历史报表但没有新任务”。只有状态不存在或日期任务变化时才会创建新任务。等待验证码或解压密码时同时
保存 Challenge ID，进程重启、网络抖动或 8770 重启会继续原请求，避免重复发群消息或重复触发短信；只有服务明确返回 Challenge
已过期/取消时才清除 ID；临时服务错误会在未持久化 Challenge 前重新点击“获取验证码”并重试，已持久化的 Challenge 仍会复用。
成功归档后状态、ZIP 和解压临时目录会清理。

退出码：`0`=下载、解压、归档成功；`1`=登录、查询、导出、验证、下载、解压或归档失败；`2`=参数错误。

---

## qianchuan_promotion_fee_download.py

千川“财务 → 流水对账 → 日结报表”最新一天或指定日期区间推广费下载。脚本通过已启动的
Cloak Login profile 连接千川登录态；登录态失效时复用 profile 保存的邮箱凭据，登录成功后
新建标签页重新打开升级版工作台 `portal-fallback`，按账户 ID 访问千川，再读取页面当前表头
和有效日期行，不固定字段。写入临时 CSV 后**直接调用** `scripts.auto_download.move_report.py`，
按标准报表名称“千川推广费”增量归档。

### 功能

- 登录恢复后重新打开升级版工作台，按账户卡片内的千川 ID 点击「访问账户」，不按账户列表序号定位。
- 打开给定千川广告账户的财务页面，点击「流水对账」，等待「日结报表」。
- 从包含「日期」表头的实时表格提取首条 `YYYY-MM-DD` 行，自动跳过「总计」。
- 传入 `--start-date` 和 `--end-date` 时，通过页面日期选择器筛选区间，完整读取日结表分页，按日归档；已存在的有效日报跳过，不生成重复文件。
- 强制校验实时表头列数与该行列数一致；千川改表时立即失败，不会写入错列数据。
- CSV 使用实时表头与 UTF-8 BOM；金额千位分隔符由 CSV 标准转义保留。
- 由 `move_report.py` 校验注册表、创建 `data\\抖音\\千川推广费`、生成
  `YYYYMMDD_平台_公司_店铺_千川推广费.csv`；同日期重复执行自动递增 `_002`。
- 千川 profile 登录态失效时，通过 `qianchuan_login.py` 自动回填已保存邮箱凭据并勾选协议；
  出现真实人工验证时只等待用户接管，不识别或绕过验证。

### 用法

```powershell
python -m scripts.auto_download.playwright.qianchuan_promotion_fee_download `
  --cdp "ws://127.0.0.1:63055/devtools/browser/<id>" `
  --aavid "1854896545860682" `
  --platform "抖音" `
  --company "津果日记生物科技(南京)有限公司" `
  --shop "MOCK冲饮旗舰店"

# 下载指定日期范围内的逐日日结记录
python -m scripts.auto_download.playwright.qianchuan_promotion_fee_download `
  --cdp "ws://127.0.0.1:63055/devtools/browser/<id>" `
  --aavid "1854896545860682" `
  --platform "抖音" `
  --company "津果日记生物科技(南京)有限公司" `
  --shop "MOCK冲饮旗舰店" `
  --start-date 2026-09-01 --end-date 2026-09-30
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | `start_profile` 返回的 wsEndpoint。 |
| `--aavid` | 是 | 千川广告账户 ID；传 `auto` 时优先复用当前千川标签，否则按 profile 的公司/店铺备注选择默认账户并从升级版工作台访问；同店铺备用账户请显式传 ID。 |
| `--platform` | 是 | profile note 中的 `platform`。 |
| `--company` | 是 | profile note 中的 `company`，保持半角括号。 |
| `--shop` | 是 | profile note 中的 `shop`。 |
| `--dest` | 否 | 归档根目录，默认 `C:\\Users\\win\\Desktop\\data`。 |
| `--start-date` / `--end-date` | 否 | 日结报表逐日日期范围，格式 `YYYY-MM-DD`；必须同时传入。未传时只下载最新一天。 |

退出码：`0`=成功；`1`=页面、权限、表结构或归档失败；`2`=参数错误。

### 注意事项

- 流水记录每天早上 8 点更新；当天通常只能取到前一天的日结行，这是平台页面规则。
- 不要改写或删除已有归档文件；日期范围模式跳过已有有效日报，其余命名与归档由 `move_report.py` 处理。
- 需先用 Cloak Login 启动目标 profile。脚本只断开 CDP，不关闭用户启动的 profile；
  登录成功后会按固定 `portal-fallback` URL 重新打开升级版工作台，以规避不同浏览器的 AB 页面差异。

---

## tmall_alipay_fund_download.py

使用 `TMALL-天猫-MOCK旗舰店-财务账号` 的登录态进入支付宝商家平台，下载最新
支付宝账户资金日账单或完整自然月账单，选择 ZIP 内的“账务明细”文件并归档。

### 天猫资金与推广费月度标准步骤

当需求为“两个资金单+推广费”时，按以下顺序执行：

1. 使用财务账号下载支付宝账户资金；使用 IT 账号下载聚合账户资金；两份资金单都传 `--mode month`。
2. 使用财务账号串行下载淘宝联盟推广费和万相台推广费，都传 `--mode month`。
3. 淘宝联盟月报必须按自定义日期输入 `YYYY-MM-DD`：悬浮「自定义」→点击「开始日期」并输入起始日后按 Enter→焦点自动跳到「结束日期」并输入结束日后按 Enter→点击「确定」。
4. 校验四个文件都非空，且推广费文件的日期范围为目标完整自然月；结算单不在此组合内，不执行结算下载。
5. 下载完成后关闭本次启动的两个 profile，并清理临时目录。

若需求是历史日期范围的资金单，两个脚本均使用 `--mode day --date YYYY-MM-DD`，按日期升序逐日执行；例如 9 月 1 日至 9 月 6 日需要执行 6 个日期，每个日期分别下载支付宝账户资金和聚合账户资金。

### 自动化流程

1. 调用 `login_extensions/tmall_finance_login.py` 确保千牛商家中心已登录。
2. 悬浮店铺账号菜单，进入「账号信息」，在「绑定支付宝」行点击「查看详情」。
3. 在淘宝支付宝绑定页点击「进入支付宝」，进入支付宝商家平台。
4. 打开「对账中心 → 账单下载」，每次检查并切换为「列表模式」。
5. 根据 `--mode day|month` 选择日账单或月账单，读取第一条一级数据行日期。
6. 用 `page.expect_download()` 捕获 ZIP，并由 `download.save_as()` 保存到系统临时目录。
7. 调用 `scripts.auto_download.extract_report` 修复 GBK 文件名乱码，只提取文件名包含
   `账务明细` 且不包含 `(汇总)` 的明细成员；月账单明细可能带 `_1` 等序号后缀，不能只匹配
   `账务明细.csv`，成功后删除 ZIP。
8. 调用 `move_report.py` 归档为标准报表“支付宝账户资金”。

### 登录扩展

登录验证代码统一位于 `scripts/auto_download/playwright/login_extensions/`。
天猫扩展使用固定账号 `MOCK旗舰店`，从环境变量 `TMALL_LOGIN_PASSWORD` 读取密码，
再用 Playwright 点击账号框/密码框、`Control+A` 后逐字键入，以触发前端 `input/change` 状态。
Windows 下若当前进程尚未继承刚设置的变量，脚本会自动读取当前用户环境变量，无需重启自动化宿主。

```powershell
$env:TMALL_LOGIN_PASSWORD = "<从安全存储读取>"
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.login_extensions.tmall_finance_login `
  --cdp "<wsEndpoint>"
```

登录扩展会自动处理页面出现的滑块验证；验证失败时自动重试，通过后继续登录。

### 下载用法

```powershell
# 最新一天
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_alipay_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode day

# 最新一月
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_alipay_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode month

# 指定历史日
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_alipay_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode day --date 2026-09-01
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | Cloak Login `start_profile` 返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的 `platform`。 |
| `--company` | 是 | profile note 中的 `company`。 |
| `--shop` | 是 | profile note 中的 `shop`。 |
| `--mode` | 否 | `day` 最新一天；`month` 最新一月。默认 `day`。 |
| `--date` | 否 | 指定日账单日期 `YYYY-MM-DD`；仅与 `--mode day` 一起使用，未指定时取页面第一条可下载日账单。 |
| `--work-dir` / `--src` | 否 | ZIP 下载和解压工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |
| `--password-env` | 否 | 密码环境变量名，默认 `TMALL_LOGIN_PASSWORD`。 |

退出码：`0`=成功；`1`=登录/页面/下载/解压/归档失败；`2`=参数错误。

### ZIP 解压工具

`scripts/auto_download/extract_report.py` 是独立工具，可按文件名包含/排除条件选择 ZIP
成员，修复未设置 UTF-8 标志的 GBK 中文文件名，并防止路径穿越和同名覆盖：

```powershell
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.extract_report `
  --archive "<临时工作目录>\20260813_2088841590236985.zip" `
  --include "账务明细" --exclude "(汇总)" `
  --filename-encoding gbk --delete-archive
```

---

## tmall_aggregate_fund_download.py

使用 `TMALL-天猫-MOCK旗舰店` profile 和 IT 账号进入千牛资金管理，在当前标签页下载
聚合账户资金最新日汇总或月汇总明细，并归档为标准报表“聚合账户资金”。

### 自动化流程

1. 复用 `login_extensions/tmall_finance_login.py` 登录天猫。
2. 直接打开聚合账户资金日汇总页面，不新建标签页。
3. `--mode day` 使用日汇总；`--mode month` 点击「月汇总」。
4. 定位第一条可下载数据行，捕获「下载明细」产生的文件。
5. 调用 `move_report.py` 归档到 `C:\Users\win\Desktop\data\天猫\聚合账户资金`。

### 下载用法

```powershell
# 最新一天
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_aggregate_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode day

# 最新一月
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_aggregate_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode month

# 指定历史日
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m scripts.auto_download.playwright.tmall_aggregate_fund_download `
  --cdp "<wsEndpoint>" `
  --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店" `
  --mode day --date 2026-09-01
```

默认账号为 `mock旗舰店:IT`，默认密码环境变量为 `TMALL_IT_LOGIN_PASSWORD`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | `TMALL-天猫-MOCK旗舰店` profile 的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的 `platform`。 |
| `--company` | 是 | profile note 中的 `company`。 |
| `--shop` | 是 | profile note 中的 `shop`。 |
| `--mode` | 否 | `day` 最新一天；`month` 最新一月。默认 `day`。 |
| `--date` | 否 | 指定日汇总日期 `YYYY-MM-DD`；仅与 `--mode day` 一起使用，未指定时取第一条可下载日汇总。 |
| `--work-dir` / `--src` | 否 | 下载临时目录；默认系统临时目录。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |
| `--username` | 否 | 登录账号，默认 `mock旗舰店:IT`。 |
| `--password-env` | 否 | 密码环境变量名，默认 `TMALL_IT_LOGIN_PASSWORD`。 |

退出码：`0`=成功；`1`=登录/页面/下载/归档失败；`2`=参数错误。

---

## tmall_order_download.py

使用 `TMALL-天猫-MOCK旗舰店` profile 进入天猫「已卖出的宝贝」，查询近一个月订单，
导出“宝贝销售明细报表”，保底校验 ODS 合同要求的 13 个自定义字段，并将 XLSX
归档到 `C:\Users\win\Desktop\data\天猫\订单`。脚本复用
`login_extensions/tmall_finance_login.py` 的登录模块。

### 自动化流程

1. 从首页点击左侧「交易」，进入「已卖出的宝贝」。
2. 在指定日期范围弹层输入开始/结束日期；只有两个日期生效且弹层「确定」按钮可用时才提交。
3. 点击「搜索订单」，等待订单列表完成加载。
4. 打开「批量导出」，选择「宝贝销售明细报表」；每次读取真实 checkbox，最终且只能勾选：
   `子订单编号`、`主订单编号`、`商品标题`、`购买数量`、`商品属性`、`订单状态`、`商家编码`、
   `买家应付货款`、`买家实付金额`、`退款状态`、`退款金额`、`订单创建时间`、`订单付款时间`。
5. 点击「生成报表」并确认「请您注意」；若遇到「5分钟内只能导出一次」，转到「查看已生成报表」，不重复创建任务。
6. 在导出历史页按报表申请时间、报表类型和日期范围匹配本次最新任务，直到出现「下载宝贝报表」按钮。
7. 捕获 XLSX 下载，调用 `move_report.py` 以报表名“订单”重命名归档。

### 下载用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.tmall_order_download `
  --cdp "<wsEndpoint>" --profile "TMALL-天猫-MOCK旗舰店" `
  --platform "天猫" --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK旗舰店"
```

默认日期为今天往前 30 天至今天；可用 `--start-date YYYY-MM-DD --end-date YYYY-MM-DD` 指定范围。
默认工作目录为归档根目录下的 `.automation_cache\tmall_order\<店铺>`，失败时保留状态文件供恢复，成功归档后清理本次临时状态。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | `TMALL-天猫-MOCK旗舰店` 本次启动返回的 wsEndpoint。 |
| `--profile` | 否 | profile 名称，仅用于日志；默认 `TMALL-天猫-MOCK旗舰店`。 |
| `--platform` | 否 | 固定为 `天猫`。 |
| `--company` | 是 | profile note 中的公司全称。 |
| `--shop` | 是 | profile note 中的店铺名。 |
| `--start-date` / `--end-date` | 否 | 订单创建日期范围；默认近一个月。 |
| `--work-dir` / `--src` | 否 | 下载和恢复状态目录。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |
| `--history-timeout` | 否 | 导出历史页等待秒数，默认 900。 |

日志统一使用 `[TMALL]` 前缀，并输出 `xlsx_path`、`archive_path` 和退出阶段；退出码：`0`=下载并归档成功；`1`=登录/页面/字段/等待/下载/归档失败；`2`=参数错误。

---

## tmall_taobao_union_promotion_download.py

### 功能

使用 `TMALL-天猫-MOCK旗舰店-财务账号` 下载淘宝联盟推广费。日模式下载昨天；月模式下载
上一个完整自然月。文件归档到 `C:\Users\win\Desktop\data\天猫\淘宝联盟推广费`。

登录优先复用同一 Profile 的联盟会话；需要授权时，从千牛“推广→淘宝联盟”进入并点击“快速进入”，
自动接管菜单打开的新标签页。Cookie 由该浏览器上下文沿用，已有会话不要求密码。
只有现有会话不可用且出现真实密码表单时才使用原有账号密码回退；验证无法完成时保留现场等待人工。

月模式日期选择必须使用自定义范围，不要直接点击「月」使用平台当前月份默认值：

1. 悬浮「自定义」按钮。
2. 点击「开始日期」输入框，输入 `YYYY-MM-DD` 后按 Enter。
3. 指针自动跳到「结束日期」输入框，输入结束日期后按 Enter。
4. 点击「确定」，确认页面统计范围与目标月份一致，再下载报表。

脚本会选择“按店铺整体”。如平台提示“重复提交任务”，自动进入下载记录并下载最新可用任务；
正常新任务则等待平台生成后捕获自动下载。

### 用法

```powershell
# 昨日推广费
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.tmall_taobao_union_promotion_download `
  --cdp "<wsEndpoint>" --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode day

# 上一个完整自然月
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.tmall_taobao_union_promotion_download `
  --cdp "<wsEndpoint>" --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode month
```

密码回退的默认账号为 `MOCK旗舰店`，密码取自项目未提交 `.env` 中的 `TMALL_LOGIN_PASSWORD`；
可继续通过 `--username`、`--password-env` 指定原有配置。

## tmall_wanxiangtai_promotion_download.py

### 功能

使用同一财务账号按记账时间下载万相台现金账户推广费。日模式使用昨天的 `cashStart/cashEnd`，月模式
使用上一个完整自然月；文件归档到 `C:\Users\win\Desktop\data\天猫\万相台推广费`。
与淘宝联盟共用上述千牛会话复用及“快速进入”登录流程。

### 用法

```powershell
# 昨日推广费
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.tmall_wanxiangtai_promotion_download `
  --cdp "<wsEndpoint>" --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode day

# 上一个完整自然月
& "D:\fsan10\mock_coffice\.venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.tmall_wanxiangtai_promotion_download `
  --cdp "<wsEndpoint>" --platform "天猫" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode month
```

两个推广费脚本通用参数：`--mode day|month`、`--work-dir`（兼容别名 `--src`）、`--dest`、
`--username`、`--password-env`。下载均由 Playwright 保存到临时目录后再调用
`move_report.py` 归档；不会依赖浏览器默认下载目录。

---

## jd_settlement_download.py

### 功能

使用已登录的 `JD-京东-MOCK饮品旗舰店` profile 下载最新日账单或月账单。日账单只保留
ZIP 中的 CSV，月账单自动从嵌套 ZIP 中提取 CSV，最后归档为标准报表“结算”。

### 用法

```powershell
python -m scripts.auto_download.playwright.jd_settlement_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--mode day|month] [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | `JD-京东-MOCK饮品旗舰店` profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `京东`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--mode` | 否 | `day` 下载最新日账单；`month` 下载最新月账单。默认 `day`。 |
| `--work-dir` / `--src` | 否 | ZIP 下载和解压工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
# 最新日账单
python -m scripts.auto_download.playwright.jd_settlement_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --mode day

# 最新月账单
python -m scripts.auto_download.playwright.jd_settlement_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --mode month
```

## jd_fund_download.py

### 功能

使用同一 profile 查询资金流水，创建并等待导出任务，下载后归档为标准报表“资金”。未指定日期时查询昨天；可用
`--start-date` 和 `--end-date` 查询自然日期范围。

### 用法

```powershell
python -m scripts.auto_download.playwright.jd_fund_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] `
  [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | `JD-京东-MOCK饮品旗舰店` profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `京东`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--start-date` / `--end-date` | 否 | 同时提供时查询含首尾日期的自然日范围；不提供时查询昨天。 |
| `--work-dir` / `--src` | 否 | 下载工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
python -m scripts.auto_download.playwright.jd_fund_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店"

# 2026 年 8 月资金流水
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_fund_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --start-date 2026-08-01 --end-date 2026-08-31
```

### 并发运行

两个命令可同时启动；连接同一 wsEndpoint 时会自动排队执行，避免京东在并发页面操作期间
返回空下载文件。

两个脚本退出码均为：`0`=成功；`1`=会话/页面/下载/解压/归档失败；`2`=参数错误。

---

## jd_order_download.py

### 功能

使用 `JD-京东-MOCK饮品旗舰店` profile 下载“订单 / 订单明细信息【加密】”报表。默认查询近一个月；也可指定自然日期范围。脚本优先打开京东订单导出深链，
深链会话异常时从“交易 → 订单列表 → 订单导出”进入；在“新建导出任务”中选择“近1个月”和订单状态“全部”，创建一次任务。

京东导出列表不会自动刷新，脚本每 5 秒刷新一次，按完整订单时间范围和任务提交时间匹配最新成功任务；京东“近1个月”快捷项按滚动 30×24 小时计算，起始日比自然日保底范围早一天时仅在结束日相同的情况下视为同一范围。确认操作列同时有“下载文件”和“获取密码”后，
先保存外层 ZIP，再通过自动化 Challenge 获取文件提取码，提取并解密 ZIP 内的 XLSX，最后归档为标准报表“订单”。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.jd_order_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK饮品旗舰店" `
  --start-date 2026-08-01 --end-date 2026-08-31
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 本次京东 profile 启动返回的 CDP `wsEndpoint`。 |
| `--platform` | 否 | profile note 中的平台，默认 `京东`。 |
| `--company` | 是 | profile note 中的公司全称。 |
| `--shop` | 是 | profile note 中的店铺名。 |
| `--work-dir` | 否 | 可恢复状态、ZIP 和解压目录；默认 `C:\Users\win\Desktop\data\.automation_cache\jd_order\<店铺>`。 |
| `--dest` | 否 | 归档根目录；默认 `C:\Users\win\Desktop\data`。 |
| `--business-date` | 否 | 归档日期前缀，默认查询结束日期；不改变查询范围。 |
| `--start-date` / `--end-date` | 否 | 同时提供时查询含首尾日期的自然日范围；不提供时使用“近1个月”。 |

### 依赖、恢复与退出码

除 Playwright 外，ZIP 内受密码保护的 XLSX 需要 `msoffcrypto-tool`，工作簿校验需要 `openpyxl`。状态文件为
`jd_order_task.json`；脚本会保存 `SUBMITTING`、`EXPORT_CREATED`、`ZIP_DOWNLOADED` 和 Challenge ID，重跑时不重复创建任务、
下载 ZIP 或发送“获取密码”。提取码错误最多重新申请三次，归档成功后才清理工作文件。

自动化转发服务默认地址为 `http://127.0.0.1:8770`，令牌读取 `AUTOMATION_ROBOT_TOKEN`（兼容 `INGEST_ROBOT_TOKEN`）。
成功输出文件名形如：

```text
YYYYMMDD_京东_墨客咖时(南京)生物科技有限公司_MOCK饮品旗舰店_订单.xlsx
```

退出码：`0`=下载、提取、解密、校验、归档成功；`1`=登录、页面、导出、等待、下载、Challenge、解密或归档失败；`2`=参数错误。

---

## jd_promotion_fee_download.py

使用同一京东 profile 串行下载京东联盟和账户中心（京东通）推广费报表。联盟页选择“结算时间”，账户中心选择“记账时间”；默认联盟点击“最近30天”，账户中心使用默认最近30天。指定日期时脚本操作双面日历，支持同月、跨月和单日双击。

### 用法

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_promotion_fee_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --report all

# 2026 年 8 月 1 日至 8 月 31 日，只下载京东联盟
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.jd_promotion_fee_download `
  --cdp "<wsEndpoint>" --platform "京东" `
  --company "墨客咖时(南京)生物科技有限公司" `
  --shop "MOCK饮品旗舰店" --report union `
  --start-date 2026-08-01 --end-date 2026-08-31
```

`--report all`（默认）按“京东联盟 → 京东通”顺序执行；`--report union|alliance` 只下载联盟，`--report tong|account` 只下载账户中心。状态文件分别保存在
`C:\Users\win\Desktop\data\.automation_cache\jd_promotion\<店铺>\union` 和 `tong`，页面跳转或下载中断后可恢复已提交任务，不重复生成。成功后调用 `move_report.py`，最终目录分别为
`C:\Users\win\Desktop\data\京东\京东联盟推广费` 和 `C:\Users\win\Desktop\data\京东\京东通推广费`；归档日期默认取自定义范围结束日。退出码 `0`=成功，`1`=页面/任务/下载/归档失败，`2`=参数错误。

---

## kuaishou_order_download.py

### 功能

使用 `KS-快手-MOCK陌时专卖店` profile，从已登录首页点击“订单查询”，按“最近一个月”查询并导出“标准报表”。快手订单导出历史不会自动跳转，脚本会新建历史标签页，选择最新可下载记录，发送文件提取码并下载 XLSX。

快手订单文件通常是文档密码保护的 XLSX，不是 ZIP。脚本通过自动化验证码服务取得文件提取码，使用 `msoffcrypto-tool` 解密为普通 XLSX，用 `openpyxl` 校验后再调用 `move_report.py` 归档到 `快手/订单`。验证码和文件提取码均保存 Challenge ID，进程重启时继续等待，不重复发送请求；同一日期范围已有任务或触发五分钟频控时复用历史记录。

### 依赖

除 Playwright 外，解密受密码保护的 XLSX 需要安装 `msoffcrypto-tool`：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m pip install msoffcrypto-tool
```

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_order_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店"
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 本次启动快手 profile 返回的 CDP wsEndpoint。 |
| `--platform` | 否 | profile note 中的平台；默认 `快手`。 |
| `--company` | 是 | profile note 中的公司全称。 |
| `--shop` | 是 | profile note 中的店铺名，同时用于登录店铺卡片匹配。 |
| `--work-dir` | 否 | 可恢复状态、下载和加密 XLSX 临时目录；默认 `C:\Users\win\Desktop\data\.automation_cache\kuaishou_order\<店铺>`。 |
| `--dest` | 否 | 归档根目录；默认 `C:\Users\win\Desktop\data`。 |
| `--business-date` | 否 | 归档日期前缀，默认查询结束日期。 |
| `--start-date` / `--end-date` | 否 | 同时提供时查询含首尾日期的自定义自然日范围；不提供时使用“最近一个月”。 |
| `--force-new` | 否 | 忽略已有历史任务，重新生成本次日期范围报表，并要求历史记录生成时间晚于本次启动时间；用于确认下载的是本次新报表。 |

### 登录、验证码与提取码

- 登录状态失效时，Playwright 点击“我是员工”“快手商家账号登录”，然后在“选择登录店铺”中点击与 `--shop` 完全匹配的店铺。脚本不读取 Chrome 密码库；只有 profile 保存凭据未触发登录时才读取进程环境变量 `KUAISHOU_LOGIN_USERNAME` / `KUAISHOU_LOGIN_PASSWORD`（兼容 `KS_LOGIN_USERNAME` / `KS_LOGIN_PASSWORD`）。
- 导出短信验证码由 `automation_challenge.py` 创建 `verification_code` Challenge；下载历史页的“发送文件提取码”由同一客户端创建 `archive_password` Challenge。默认转发服务为 `http://127.0.0.1:8770`，令牌优先 `AUTOMATION_ROBOT_TOKEN`，兼容 `INGEST_ROBOT_TOKEN`。答案不会写入日志或源码。
- 点击“导出”后必须等待短信验证码输入框真实出现，再点击“获取验证码”，并等待平台显示已发送/倒计时后才等待人工输入；不会把页面尚未渲染误判为无需验证码。
- 平台确认弹窗必须点击“确定”后才认为提取码已发送。提取码错误会明确提示并最多重试三次，不重复创建报表或下载文件。

### 输出与退出码

成功后输出文件名形如：

```text
YYYYMMDD_快手_南京陌时食品科技有限公司_MOCK陌时专卖店_订单.xlsx
```

退出码：`0`=下载、解密、校验、归档成功；`1`=登录、查询、导出、Challenge、下载、解密或归档失败；`2`=参数错误。

---

## xiaohongshu_order_download.py

### 功能

使用 `XHS-小红书-MOCK旗舰店` profile 打开小红书商家首页，进入订单管理，按默认“近30天”或自定义日期范围设置下单时间，查询后点击“全部导出”，确认提示弹窗并直接接管 XLSX 下载。脚本会复用 `xiaohongshu_download_common.py` 的登录流程和智能广告弹窗关闭模块，校验订单表头后归档为标准报表“订单”。

### 用法

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_order_download `
  --cdp "<wsEndpoint>" --profile "XHS-小红书-MOCK旗舰店" `
  --platform "小红书" --company "<公司>" --shop "<店铺>" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | Cloak Login `start_profile` 返回的实时 `wsEndpoint`。 |
| `--profile` | 否 | profile 名称，仅用于日志，默认 `XHS-小红书-MOCK旗舰店`。 |
| `--platform` | 否 | profile note 中的平台，默认 `小红书`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--work-dir` | 否 | XLSX 下载工作目录；默认 `C:\Users\win\Desktop\data\.automation_cache\xiaohongshu_order\<shop>`。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |
| `--business-date` | 否 | 文件日期前缀，默认查询结束日期或当天。 |
| `--start-date` / `--end-date` | 否 | 自定义下单日期范围，必须同时提供，格式 `YYYY-MM-DD`；不提供时使用“近30天”。 |

### 页面和失败处理

- 当前页面 XPath 以用户确认的订单菜单、下单时间、日期弹层、查询、全部导出和确定按钮为首选；备用定位只接受可见元素。自定义范围优先在“下单时间”输入框直接填写 `YYYY-MM-DD HH:MM:SS` 并回车确认，`--start-date`/`--end-date` 仅在输入框方式不可用时回退到日期弹层。
- 广告弹窗关闭集中在 `xiaohongshu_download_common.dismiss_ad_popups`，只关闭已知广告路径或有广告特征的 portal，不误关日期/导出业务弹窗。
- 正常执行只调用一次脚本；退出码 `1` 时按日志和真实 DOM 修复正式脚本，连续多次修复仍失败才用 Cloak Login MCP 诊断，不能把手工点击代替脚本流程。
- Playwright 下载文件保存在工作目录，校验通过后调用 `move_report.py` 移动到 `C:\Users\win\Desktop\data\小红书\订单`。

成功文件名形如：

```text
YYYYMMDD_小红书_公司_店铺_订单.xlsx
```

例如下载 2026 年 8 月订单：

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_order_download `
  --cdp "<wsEndpoint>" --profile "XHS-小红书-MOCK旗舰店" `
  --platform "小红书" --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" `
  --start-date 2026-08-01 --end-date 2026-08-31
```

退出码：`0`=下载、校验、归档成功；`1`=登录、页面、弹窗、下载、校验或归档失败；`2`=参数错误。

---

## xiaohongshu_settlement_download.py

### 功能

使用 `XHS-小红书-MOCK旗舰店` profile 下载最新日账单或月度汇总单。若登录态失效，脚本会
切换“账号登录”，复用浏览器已保存的账号密码，勾选协议并提交登录。结算 XLSX 同时包含
“订单结算”和“其他服务款”工作表，脚本校验后仅归档一份标准报表“结算”。导入中心上传该
文件一次后，会自动按两个工作表分别导入收入、支出 ODS 原始表。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_settlement_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--mode day|month] [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 小红书 profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `小红书`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--mode` | 否 | `day` 下载最新日账单；`month` 下载最新月度汇总单。默认 `day`。 |
| `--work-dir` / `--src` | 否 | XLSX 下载工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
# 最新日结算账单（生成一个“结算”归档文件）
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_settlement_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode day

# 最新月度汇总单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_settlement_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode month
```

## xiaohongshu_fund_download.py

### 功能

使用同一 profile 下载最新日账单或月度汇总单资金账单，校验“资金账单明细”XLSX 后归档为
标准报表“资金”。登录态失效时自动复用已保存凭据完成账号登录。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_fund_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--mode day|month] [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 小红书 profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `小红书`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--mode` | 否 | `day` 下载最新日账单；`month` 下载最新月度汇总单。默认 `day`。 |
| `--work-dir` / `--src` | 否 | XLSX 下载工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
# 最新日资金账单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_fund_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode day

# 最新月度汇总单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.xiaohongshu_fund_download `
  --cdp "<wsEndpoint>" --platform "小红书" `
  --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK旗舰店" --mode month
```

两个脚本退出码均为：`0`=成功；`1`=登录/页面/下载/校验/归档失败；`2`=参数错误。

---

## 小红书 WebAPI 统一下载

`ReverseAPI/Formal_Script/xiaohongshu_webapi_download.py` 是订单、资金、结算的统一入口。脚本通过
`profile_cdp.py` 按完整名称精确复用或启动 Cloak Login Profile，只需传入 `--profile`；三个报表在同一次运行中
串行复用该 Profile，查询、导出任务、状态轮询和短效文件下载走已经确认的 WebAPI。

### 用法

以下命令均从项目根目录执行，文件默认保存到 `ReverseAPI/downloads`：

```powershell
# 不传日期和报表类型：订单近30天，资金和结算昨天
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.xiaohongshu_webapi_download `
  --profile "XHS-小红书-MOCK旗舰店"

# 指定订单日期范围
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.xiaohongshu_webapi_download `
  --profile "XHS-小红书-MOCK旗舰店" --date 2026-08-01~2026-08-31 --report-type 订单

# 指定资金单日账单；结算使用 --report-type 结算
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.xiaohongshu_webapi_download `
  --profile "XHS-小红书-MOCK旗舰店" --date 2026-09-09 --report-type 资金
```

`--report-type` 支持 `订单/order`、`资金/fund`、`结算/settlement`；省略时下载全部三类。订单日期支持单日或
`YYYY-MM-DD~YYYY-MM-DD` 范围；资金和结算支持单日，传 `YYYY-MM` 时下载对应月度汇总单。运行开始时终端会打印每
个报表的实际时间段，例如“订单：2026-08-12 00:00:00 ~ 2026-09-10 23:59:59（默认近30天）”和“资金：
2026-09-09（默认昨天）”。遇到登录、人机验证或安全验证时以 `NEEDS_HUMAN` 停止，不自动绕过。

---

## 抖音资金/结算 WebAPI

`ReverseAPI/Formal_Script/douyin_webapi_download.py` 是抖音资金单和结算单的统一入口。
脚本通过 `profile_cdp.py` 按完整名称精确复用或启动 Cloak Login Profile，浏览器页面只提供登录态和
安全上下文，查询、创建导出任务、历史任务轮询和短效签名文件下载走已确认的 WebAPI。资金和结算按顺序
复用同一个 Profile，不会停止 Profile。

### 用法

以下命令从项目根目录执行，文件默认保存到 `ReverseAPI/downloads`：

```powershell
# 资金单和结算单，默认昨天
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.douyin_webapi_download `
  --profile "DY-抖音-MOCK禧饮咖啡专卖店"

# 指定单日，或使用 2026-09-01~2026-09-06 指定闭区间
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.douyin_webapi_download `
  --profile "DY-抖音-MOCK禧饮咖啡专卖店" --date 2026-09-10

# 只下载其中一种
& ".venv\Scripts\python.exe" -m `
  ReverseAPI.Formal_Script.douyin_webapi_download `
  --profile "DY-抖音-MOCK禧饮咖啡专卖店" --date 2026-09-10 --report-type 资金
```

`--report-type` 支持 `资金/fund`、`结算/settlement`、`全部/all`；不指定时依次下载资金和结算。
单报表模块也可分别调用 `douyin_fund_webapi_download` 或 `douyin_settlement_webapi_download`。遇到登录、
人机验证或安全验证时以 `NEEDS_HUMAN` 停止，不自动绕过；脚本不会把 Cookie、动态安全字段或签名下载
地址写入日志。

---

## pinduoduo_settlement_download.py

### 功能

使用已登录的 `PDD-拼多多-养颜轻食` profile 查询并下载指定日期范围的拼多多账单，默认昨天。平台的结算单
与资金单为同一个 ZIP；脚本调用 `extract_report.py` 提取其中唯一的 CSV，再调用
`move_report.py` 归档为标准报表“结算”。

### 用法

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_settlement_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--date-only] `
  [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 拼多多 profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `拼多多`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--start-date` / `--end-date` | 否 | 结算发生时间范围，必须同时提供，格式 `YYYY-MM-DD`；不提供时下载昨天。 |
| `--date-only` | 否 | 只设置并校验日期，不查询或创建导出任务；用于先验证日期交互。 |
| `--work-dir` / `--src` | 否 | ZIP 下载和解压工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_settlement_download `
  --cdp "<wsEndpoint>" --platform "拼多多" `
  --company "津果日记生物科技(南京)有限公司" --shop "养颜轻食" `
  --start-date 2026-08-01 --end-date 2026-08-31
```

退出码：`0`=成功；`1`=会话/页面/下载/解压/归档失败；`2`=参数错误。

---

## pinduoduo_order_download.py

### 功能

使用 `PDD-拼多多-养颜轻食` profile 查询指定日期范围的订单，未指定日期时默认通过“订单下单时间”左侧快捷下拉选择“近30日”，
生成“对账报表”，从订单导出记录下载与拼单成功时间范围匹配的最新任务，并归档为标准报表“订单”。登录失效时通过
Playwright 操作账号登录输入框；验证码可接入专用自动化验证码转发服务。

脚本会关闭拼多多导出页可能遮挡下载按钮的“重要提示”浮层（`ImportantList_close`）。
同一店铺 5 分钟内重复生成任务时，平台会返回重复提交/限频提示，脚本进入已有导出记录
复用昨天任务，不会因限频而失败。

### 用法

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_order_download `
  --cdp "<wsEndpoint>" --platform "拼多多" `
  --company "津果日记生物科技(南京)有限公司" --shop "养颜轻食" `
  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--date-only]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 本次启动 profile 返回的 CDP wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，通常为 `拼多多`。 |
| `--company` | 是 | profile note 中的公司全称。 |
| `--shop` | 是 | profile note 中的店铺名。 |
| `--start-date` / `--end-date` | 否 | 拼单成功时间范围，必须同时提供，格式 `YYYY-MM-DD`；不提供时使用左侧快捷项“近30日”。 |
| `--date-only` | 否 | 只设置并校验日期，不查询或创建订单导出任务；用于先验证日期控件。 |
| `--work-dir` / `--src` | 否 | 下载临时目录；默认系统临时目录。 |
| `--dest` | 否 | 归档根目录；默认 `C:\Users\win\Desktop\data`。 |

### 登录与验证码配置

- 优先通过 Playwright 点击账号/密码输入框并用键盘触发 profile 已保存凭据，不读取
  Chrome 密码库；没有保存凭据时才使用 `PDD_LOGIN_USERNAME`、`PDD_LOGIN_PASSWORD`。
- 检测到验证码时，脚本向 `POST $AUTOMATION_RELAY_URL/api/automation/verification/challenges`
  创建请求并轮询答案。默认地址为 `http://127.0.0.1:8770`，令牌优先读取
  `AUTOMATION_ROBOT_TOKEN`，兼容 `INGEST_ROBOT_TOKEN`。验证码不会写入日志。

### 输出与退出码

Playwright 接管下载并保存到临时目录，随后调用 `move_report.py`，输出文件名形如：

```text
YYYYMMDD_拼多多_津果日记生物科技(南京)有限公司_养颜轻食_订单.csv
```

退出码：`0`=下载并归档成功；`1`=登录、查询、导出、下载或归档失败；`2`=参数错误。

---

## pinduoduo_promotion_fee_download.py

使用拼多多推广账户的财务流水页下载推广费明细。脚本先调用公共的
`pinduoduo_login.py` 确认商家后台登录态，再优先直达财务流水页；若直达触发会话异常，
则从商家后台首页点击“推广账户”，进入推广平台后点击“财务流水”兜底。

### 功能

- 可直接填写 `--start-date`/`--end-date` 自定义日期范围；脚本在推广平台日期框输入 `YYYY/MM/DD` 并回车确认。
- 选择 `资金类型=现金`、`流水类型=支出`，点击“查询”并确认页面明细均符合筛选条件。
- 使用 Playwright 捕获“下载明细”文件，不扫描浏览器默认 Downloads 目录。
- 校验默认工作表（优先 `Sheet0`）、ODS 所需七个字段、profile 店铺、有效时间、金额及现金支出行。
- 自定义日期时逐行校验导出明细均落在请求范围内，并用请求结束日期生成归档日期；未指定日期时才使用导出明细的最大“时间”日期。
- 调用 `move_report.py` 归档为“推广费”；同名文件自动递增。

### 用法

```powershell
& ".venv\Scripts\python.exe" -m `
  scripts.auto_download.playwright.pinduoduo_promotion_fee_download `
  --cdp "<wsEndpoint>" --platform "拼多多" `
  --company "津果日记生物科技(南京)有限公司" --shop "养颜轻食" `
  --start-date "2026-08-01" --end-date "2026-08-31"
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 本次启动 profile 返回的 CDP `wsEndpoint`。 |
| `--platform` | 是 | profile note 中的平台，通常为 `拼多多`。 |
| `--company` | 是 | profile note 中的公司全称。 |
| `--shop` | 是 | profile note 中的店铺名。 |
| `--start-date` | 否 | 自定义开始日期，格式 `YYYY-MM-DD` 或 `YYYY/MM/DD`；需与 `--end-date` 同时提供。 |
| `--end-date` | 否 | 自定义结束日期，格式 `YYYY-MM-DD` 或 `YYYY/MM/DD`；需与 `--start-date` 同时提供。 |
| `--work-dir` / `--src` | 否 | 下载临时目录；默认系统临时目录。 |
| `--dest` | 否 | 归档根目录；默认 `C:\Users\win\Desktop\data`。 |

归档文件名形如：

```text
YYYYMMDD_拼多多_津果日记生物科技(南京)有限公司_养颜轻食_推广费.xls
```

平台当前返回 `.xls`；脚本同时兼容 `.xlsx/.xlsm`，并按实际下载扩展名归档。

退出码：`0`=下载、校验并归档成功；`1`=登录、页面、筛选、下载、校验或归档失败；
`2`=参数错误。

---

## kuaishou_settlement_download.py

### 功能

使用已登录的 `KS-快手-MOCK陌时专卖店` profile 下载指定日期范围的快手结算单。默认下载
昨天；平台 ZIP 中的唯一 XLSX/CSV 明细由 `extract_report.py` 提取，最后归档为标准报表“结算”。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_settlement_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--date YYYY-MM-DD | --start-date YYYY-MM-DD --end-date YYYY-MM-DD] `
  [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 快手 profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `快手`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--date` | 否 | 单日结算业务日期，格式 `YYYY-MM-DD`；未提供日期范围时默认昨天。 |
| `--start-date` / `--end-date` | 否 | 同时提供时查询含首尾日期的自然日范围；不能与 `--date` 同时使用。 |
| `--work-dir` / `--src` | 否 | ZIP 下载和解压工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
# 自动下载昨天的结算单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_settlement_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店"

# 下载指定日期
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_settlement_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店" `
  --date 2026-08-16
```

## kuaishou_fund_download.py

### 功能

使用同一 profile 下载最新日资金账单或月资金账单，按目标账单日期匹配导出记录并归档为
标准报表“资金”。

### 用法

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_fund_download `
  --cdp "<wsEndpoint>" --platform "<平台>" `
  --company "<公司>" --shop "<店铺>" `
  [--mode day|month] [--sub-mch-id "<二级商户号>"] `
  [--work-dir "<工作目录>"] [--dest "<归档根目录>"]
```

### 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--cdp` | 是 | 快手 profile 本次启动返回的 wsEndpoint。 |
| `--platform` | 是 | profile note 中的平台，本店为 `快手`。 |
| `--company` | 是 | profile note 中的公司。 |
| `--shop` | 是 | profile note 中的店铺。 |
| `--mode` | 否 | `day` 下载最新日账单；`month` 下载最新月账单。默认 `day`。 |
| `--sub-mch-id` | 否 | 显式指定收支明细二级商户号；不传时使用当前 profile 登录店铺对应的账户。 |
| `--work-dir` / `--src` | 否 | 下载工作目录；默认系统临时目录，`--src` 为兼容别名。 |
| `--dest` | 否 | 归档根目录，默认 `C:\Users\win\Desktop\data`。 |

### 示例

```powershell
# 最新日账单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_fund_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店" `
  --mode day

# 最新月账单
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m `
  scripts.auto_download.playwright.kuaishou_fund_download `
  --cdp "<wsEndpoint>" --platform "快手" `
  --company "南京陌时食品科技有限公司" --shop "MOCK陌时专卖店" `
  --mode month
```

两个脚本退出码均为：`0`=成功；`1`=会话/页面/下载/解压/归档失败；`2`=参数错误。
