# 电商 WebAPI 正式实现规范

本规范约束 `ReverseAPI/Formal_Script` 中新建或修改的电商 WebAPI 下载器。平台接口形态可以不同，但 Profile、模块边界、返回值、错误、日志、下载和测试必须统一。

## 1. 先复用现有基线

开始编码前依次检查：

1. `ReverseAPI/Formal_Script/profile_cdp.py`：所有平台统一复用，不复制 MCP 客户端或 Profile 查找逻辑。
2. `ReverseAPI/Formal_Script/<platform>_webapi_common.py`：存在时优先扩展。一个平台出现第二个需要相同会话、请求或下载逻辑的报表时，才提取平台公共模块。
3. `ReverseAPI/Formal_Script/<platform>_webapi_download.py`：平台已有统一入口时，新报表必须加入其报表注册、日期计划和测试。
4. 同平台现有报表模块：只复用已验证的局部能力，不整文件复制另一套 CDP Client、Target Manager、下载函数和异常体系。

当前项目中可借鉴的组合是：

- 小红书：`profile_cdp.py` + `xhs_webapi_common.py` + 各报表模块 + 统一入口。
- 拼多多对账：真实首页入口、按 Target/endpoint 保存自然 Payload 和动态头、401/403 只刷新一次。
- 拼多多订单：当一次性风控字段不适合重放时，可拦截并只修改网页自然导出请求，而不是强求纯 HTTP。

不要继承旧探针中的硬编码 endpoint、相对当前目录的 `./downloads`、直接写最终文件、完整响应打印或“Target 在 sessions 中就永远继续复用”等行为。

## 2. 文件和模块契约

新平台或新报表使用以下职责，不为形式统一而重命名已经稳定运行的旧模块：

```text
ReverseAPI/Formal_Script/profile_cdp.py
ReverseAPI/Formal_Script/<platform>_webapi_common.py          # 有真实共享逻辑时
ReverseAPI/Formal_Script/<platform>_<report>_webapi_download.py
ReverseAPI/Formal_Script/<platform>_webapi_download.py         # 平台统一入口
ReverseAPI/Test_Script/test_<platform>_<report>_webapi.py
ReverseAPI/Test_Script/test_<platform>_webapi.py                # 统一入口测试
```

报表模块必须暴露：

- `run_async(args) -> Path | None`，Playwright/CDP 异步实现优先使用它；
- 或在原生同步 CDP 确有必要时暴露 `run(args) -> Path | None`；
- `main(argv: list[str] | None = None) -> int`，便于纯逻辑测试；旧模块暂时不能接收 `argv` 时不为此单独重构。

返回值固定为：

- `Path`：原始文件已完整落盘；
- `None`：权威查询明确为零数据或指定账期不存在，这是成功终态；
- 异常：流程未完成，不能用 `None` 掩盖 API、权限、任务或文件错误。

## 3. 统一入口和 CLI

面向用户的命令优先使用平台统一入口：

```powershell
& ".venv\Scripts\python.exe" -m ReverseAPI.Formal_Script.<platform>_webapi_download --profile "<完整 Profile>" --report-type "<中文报表名>" --date "<业务日期>"
```

统一入口的公共参数：

- `--profile`：必填，完整名称，不在新代码里固化具体店铺作为正常调用默认值。
- `--report-type`：使用项目约定的中文标准报表名；省略时是否运行全部由该平台现有入口约定决定。
- `--date`：统一的用户日期入口；解析后再转换为报表模块需要的起止日期、日/月模式。
- `--output-dir`：默认是由模块位置计算出的 `ReverseAPI/downloads` 绝对路径，不依赖当前工作目录。
- `--timeout`、`--poll-interval`：任务型导出需要，必须校验为正数。
- `--mcp-url`：仅作本机 MCP 覆盖，正常命令不要求用户传。
- `--ws-endpoint/--cdp`、`--debug-port`：只能作为诊断兼容参数且互斥，正常命令只给 Profile。

同一平台一次下载多个报表时：

1. 统一入口只调用一次 `resolve_profile_connection()`。
2. 把同一 `ProfileConnection.endpoint` 注入各子模块，子模块不得再次调用 MCP。
3. 报表按计划串行执行；一个报表完成后再进入下一个，避免同一 Profile 的页面和动态上下文互相覆盖。
4. 日志保留已完成文件；任一失败后停止后续任务，不把部分成功汇报成全部成功。
5. 前一个报表可能停在同平台的业务子域、深层页面或导出历史页。后一个子模块必须把经白名单确认的同平台页面视为“返回官方首页”的启动载体，再从首页真实菜单进入目标模块；不得因此误判 Profile 未登录，也不得直接复用旧报表留下的受保护深链。

## 4. Profile、浏览器和页面所有权

- 精确复用 `profile_cdp.py` 的活动 Profile → 保存 Profile → 按需启动流程。
- 不记录完整 endpoint；只可记录“自动取得/显式参数”和必要的非敏感来源说明。
- 默认不停止 Profile。只有用户明确要求停止时才停止，并且只能停止本次目标 Profile。
- 不关闭用户原有页面、BrowserContext 或浏览器。只关闭脚本自己新建的页面、事件监听器、WebSocket、HTTP Session 和临时文件。
- 对借用的 `connect_over_cdp()` 浏览器，禁止调用会终止远端 Profile 的关闭操作。只有当前适配器已确认 `browser.close()` 是断开连接而非关闭远端浏览器时才可使用，否则依靠连接生命周期退出。
- 事件监听必须在进入目标页面之前注册，并在 `finally` 中移除。

如果正式脚本自行维护 CDP Target 会话，必须满足：

1. 会话提供可验证的 `is_alive()`/关闭状态。
2. `discover_once()` 发现同一 Target ID 已存在时，先检查监听线程；线程死亡必须移除旧会话并重连。
3. 重连有短退避并记录不含 endpoint 的状态；健康运行一段时间后清零连续失败计数。
4. Target 短暂消失使用宽限期，真正 stale 后关闭会话并清除该 Target 的动态上下文。
5. discovery loop 捕获单次异常后继续，不能因一个 WebSocket 异常永久停止发现。

## 5. 浏览器与 WebAPI 的两种合法组合

根据 Capture 证据选择一种，不按个人偏好强求纯 HTTP。

### A. 页面内 WebAPI

适合小红书订单/账单、拼多多结算/推广费这类可在登录页面内 `fetch` 的接口：

```text
真实首页/菜单入口
  → 注册自然请求监听
  → 页面产生该 endpoint 的动态上下文
  → page.evaluate(fetch, credentials=include)
  → 查询/导出/轮询
```

### B. 拦截并最小修改自然请求

适合网页必须亲自生成一次性 `Anti-Content`、`crawlerInfo` 或单次导出请求的接口：

```text
真实页面触发一次导出
  → 拦截目标 endpoint 的第一条请求
  → 只修改已确认的日期/筛选字段
  → 继续原请求
  → WebAPI 轮询和下载
```

拦截模式必须防止同一次运行修改第二条同接口请求。自动 DOM 触发失败且确实需要人工操作时返回 `NEEDS_HUMAN`；正式脚本不能无限等待一个未明确提示的手工点击。

DOM 只允许承担真实入口、认证跳转、生成动态上下文，以及 Capture 已证明必需的固定业务筛选。日期始终从 Payload 替换；不得重新实现日期组件，也不得调用字典/选项接口来“设置”下拉值。

## 6. 动态上下文与请求构造

- 动态头、自然 Payload 和采集时间按 `(Target, endpoint path)` 保存；精确 endpoint 优先。
- 只有 Capture 证明多个接口共享同一上下文时，才允许回退到同一 Target 最近的业务请求；禁止跨 Target、跨页面、跨平台使用“最后一组头”。
- 只复制 allowlist 中经 Capture 证明确实需要的动态头。Cookie、Origin、Host、Content-Length、`sec-*` 等交给浏览器。
- 动态值只留在内存，不写源码、日志、fixture 或 Capture 之外的文件。
- 以自然 Payload 为模板时，复制后只覆盖日期、分页和用户指定的业务筛选，不修改原对象。
- 静态构造 Payload 仅在 Capture 和回归 fixture 已证明字段稳定时使用；查询 Payload 和导出 Payload 字段名不同则分别建纯函数。
- 日期转换显式使用中国时区，保留自然请求的字符串/秒/毫秒类型及 inclusive/exclusive 语义。不要使用未带时区的 `datetime.now()` 推导默认业务日。

401/403 的恢复固定为一次：重新走必要入口或触发当前 endpoint 的自然请求，重新取得同 Target/endpoint 上下文，只重试当前 API。第二次仍失败则报错。创建导出任务不能因普通超时或 5xx 自动重发，除非接口有已验证的幂等键或先查询确认未创建。

## 7. 查询、成功码和零数据

- 每个 endpoint 单独定义成功条件。不得假设所有平台都使用 `code=0` 或 `errorCode=0`；例如明确的 `success=true` 可以与平台特有成功码并存。
- HTTP 非 2xx、非 JSON、结构缺失和业务失败分别报错。异常至少保留 `status`、`path` 和经过裁剪/脱敏的业务消息，不能直接打印完整响应体。
- 查询条数优先使用权威 `total/totalCount/count`；不存在时才使用已确认的 rows 数组。未知结构不是零数据，应报错。
- 查询明确为 0 时，在创建导出任务之前返回 `None`。
- 没有独立查询接口时，可把导出任务明确返回的“0 条/无数据”终态转换为 `None`。
- 账期列表型接口必须精确匹配请求日期、日/月类型和成功状态；“列表非空”不等于目标账期存在。
- 分页读取服务端返回的总页数。若设置安全上限，超过上限必须报错，不能静默截断后选择错误账期。

## 8. 创建任务和轮询

- 优先使用创建响应返回的 `task_id/job_id` 轮询。
- 创建响应没有 ID 时，按“日期/筛选 + 创建时间下界 + 当前 Profile/店铺可用标识”匹配，并选择最新候选；不能只拿列表第一行。
- 创建前记录时间，给客户端/服务端时钟差留有界余量。
- 轮询使用 `time.monotonic()` 截止时间和正数间隔，只在状态变化时打印日志。
- 明确列出成功、失败、取消和零数据终态；未知状态持续到超时，不擅自当成功。
- 下载地址出现仍需满足 Capture 确认的完成条件；短效地址取得后立即下载，不写日志。

## 9. 文件落盘

默认只保存平台返回的原始 ZIP/XLS/XLSX/CSV，不解压、不改写、不做业务表头校验，除非用户明确要求。

下载函数必须：

1. 验证 URL 为 `http/https`，不打印带签名的完整地址。
2. 输出目录使用 `expanduser().resolve()` 并创建。
3. 文件名包含稳定的平台码、报表码和请求账期；扩展名来自已验证的接口/URL/响应。
4. 已有同名文件时生成唯一名称，不覆盖历史文件。
5. 在同目录写 `<目标名>.part`，HTTP 2xx 且文件大小大于 0 后原子替换为最终文件。
6. 任意失败删除本次 `.part`，保留已有正式文件。
7. 只有 Capture 证明下载需要时才复制 Cookie、Referer、User-Agent；使用独立 `requests.Session` 并在 `finally` 关闭。

推荐新文件名：

```text
<PLATFORM>_<report>_<start>_to_<end>.<ext>
<PLATFORM>_<report>_day_<YYYY-MM-DD>.<ext>
<PLATFORM>_<report>_month_<YYYY-MM>.<ext>
```

报表码使用 `order`、`fund`、`settlement`、`promotion_fee` 等单数英文标识。

## 10. 异常、退出码和日志

同一平台共享一套异常类型，子模块不要重复定义含义相同但无法被统一入口识别的 `NeedsHumanError`。

退出码：

- `0`：下载成功，或权威判断无数据；
- `1`：导航、API、任务、超时或文件失败；
- `2`：Profile/CDP 无法取得、登录失效、验证码、短信/二次验证或权限不足；输出以 `NEEDS_HUMAN:` 开头；
- `130`：用户中断。

日志统一为：

```text
[<平台码>][<报表>][计划|Profile|页面|上下文|查询|导出|轮询|下载|完成|失败] 消息
```

可以打印日期、行数、分页、任务 ID、状态、文件路径和大小。不得打印完整 endpoint、Cookie、动态头值、Payload、响应体、ticket、签名 URL 或本地凭据。字段排查只打印脱敏后的字段名和有限业务错误。

## 11. 最低测试矩阵

永久测试使用 `unittest` 和虚构 fixture，放在 `ReverseAPI/Test_Script`。测试模块导入时不得连接浏览器、访问网络、启动 Profile 或写文件；所有可执行逻辑必须在测试方法或 `if __name__ == "__main__"` 后。

每个新报表至少覆盖：

1. 默认日期与显式日期、时区、起止边界和自然字段类型。
2. 查询/导出 Payload 形状；确认只替换目标字段且不修改模板。
3. 平台特有成功码、HTTP 错误、非 JSON 和结构缺失。
4. 0 条时未调用创建任务或下载。
5. 任务 ID 优先；无 ID 时排除旧任务、错日期、失败任务和重复候选。
6. 失败/取消/零数据终态与轮询超时。
7. 401/403 只刷新并重试一次，第二次失败透出。
8. 下载使用 `.part`、非空检查、唯一命名、原子替换和失败清理。
9. `Path`/`None` 返回契约以及 `0/1/2/130` 退出码。
10. 统一入口只解析一次 Profile、按计划串行运行并传递同一 endpoint。
11. 若使用自建 Target Manager，覆盖“Target 仍存在但监听线程死亡”的自动重连。
12. 多报表统一入口覆盖“前一报表停在同平台其他子域/深层页面，下一报表仍能返回官方首页并重新走真实入口”。

真实 CDP 探针、原始响应和完整 Capture 只放 `.codex_tmp/`，不得命名为 `test_*.py` 或加入测试发现。任何测试/示例都不得硬编码真实 `wsEndpoint`。

## 12. 交付前合规检查

交付前逐项给出通过证据：

- 使用共享 `profile_cdp.py`，平台统一入口已接入；
- 浏览器职责和 WebAPI 职责已明确；
- 动态上下文绑定 Target/endpoint，401/403 只重试一次；
- 零数据、任务匹配和原子下载满足本规范；
- 日志和 fixture 不含真实 endpoint/凭据/签名；
- `py_compile`、`--help`、最低测试矩阵和一次真实端到端下载通过；
- 真实文件非空且账期正确；未要求时没有解压或业务表头校验。

若某项因平台接口形态不适用，必须用 Capture 证据说明替代方案；不能静默省略。
