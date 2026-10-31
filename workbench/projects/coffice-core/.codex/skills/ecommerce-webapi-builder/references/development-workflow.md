# 电商 WebAPI 下载器开发流程

## 0. 解析 Profile，不向用户索要 CDP

收到平台、报表和 Profile 名称后：

1. 调用 `mcp__cloak_login__list_active({})`。
2. 在结果数组中按完整 `name` 精确匹配；命中时取得该项的 `id` 与 `wsEndpoint`。
3. 未命中时调用 `mcp__cloak_login__list_profiles({})`，按完整 `name` 精确匹配。
4. 唯一命中后调用 `mcp__cloak_login__start_profile({id})`。
5. 若启动结果没有 endpoint，间隔短暂等待后最多重新查询 `list_active` 三次，并同时核对 `id` 和 `name`。

不得模糊匹配、用另一个店铺替代、重复启动已运行 Profile，或把完整 endpoint 写入日志和交付文本。记录 `profile_started_by_this_run`，但没有用户明确要求时不调用 `stop_profile`。

只有 MCP 不可用、Profile 不存在/重名、启动失败或三次仍无 endpoint 时，才报告阻塞。

## 1. 锁定现有代码基线和 DOM 流程

先完整读取 [implementation-standard.md](implementation-standard.md)，再检查：

- `ReverseAPI/Formal_Script/profile_cdp.py`，必须复用现有 Profile/CDP 解析。
- 当前平台的 `<platform>_webapi_common.py` 和 `<platform>_webapi_download.py`。
- 同平台现有报表模块的返回值、异常、日志和测试，但不能默认整段复制其旧实现。

使用 `rg --files` 和 `rg` 自动找到目标平台/报表的现有 DOM 下载脚本。只提取：

- 入口模块及 CLI 参数。
- 登录、首页和受保护页面导航函数。
- 查询、导出、导出历史和下载的动作顺序。
- 当前业务默认日期、筛选和输出约束。

不要先分析日期选择器、下拉框、整页 DOM 或前端源码。首次发现阶段直接运行现有脚本一次，让它产生完整真实网络链。只有脚本实际报错指向某个入口或控件时，才检查该节点。

项目确实没有脚本时，才根据已有代码查找入口；仍无法确定时，只向用户询问一段首页菜单路径或一个 XPath。

## 2. 启动通用监听器

从 Git 根目录运行技能自带监听器：

```powershell
& ".venv\Scripts\python.exe" ".codex\skills\ecommerce-webapi-builder\scripts\ecommerce_http_capture.py" --platform <platform> --profile-name "<profile>" --ws-endpoint "<本轮从 Cloak Login 取得>" --label "<report>"
```

默认 Capture 位于：

```text
.codex_tmp/captures/<platform>_<report>_YYYYMMDD.json
```

监听器会从当前目录向上查找 `.git`，因此从子目录启动时也写入同一 Git 根目录下的 `.codex_tmp/captures`。同名文件自动加序号。不得改回 `Test_Script`，不得 `git add -f`，不得把原始 JSON 移入仓库文件。

必须等待 `[READY]`，再在另一个进程用同一 endpoint 运行现有 DOM 脚本一次。监听器只读，不修改请求。

## 3. 完成一次发现捕获

DOM 脚本负责首次发现时的整条页面操作：真实入口、会话、日期/筛选、查询、导出、历史和下载。监听器负责旁路记录：

- page、iframe、worker 等 Target 及导航。
- XHR、Fetch、Preflight、Document、Other、EventSource、WebSocket 握手及 JSONP。
- 请求方法、查询参数、Payload、响应状态、文本/JSON 响应体。
- 下载事件和建议文件名。
- endpoint 汇总、Payload 字段集合、响应字段集合和跳过域名。

DOM 脚本完成并等待最后请求结束后，Codex 主动向监听进程发送 `Ctrl+C`。确认 `capture_complete=true`，且关键请求和响应体存在。

若缺少请求，先检查：

1. 监听器是否在 DOM 脚本前出现 `[READY]`。
2. 监听线程是否记录 `listener_restart`。
3. 平台规则和 `summary.skipped_hosts`。
4. 必要时传 `--include-domain`。

不要因此重写监听器或重新扫描整个 DOM。

## 4. 从 Capture 识别最小接口链

先读 `summary.endpoints`，再按候选 `capture_ids` 定点读取完整记录。按时间顺序确认：

1. 查询 API：其 Payload 是日期、店铺、状态、资金类型、流水类型等最终业务值的权威来源。
2. 创建导出任务 API：比较它与查询 Payload 的字段关系。
3. 任务列表/状态 API：确认 ID、状态枚举和本次任务匹配条件。
4. 下载地址产生位置：确认短效签名、Cookie、Referer 或浏览器上下文要求。

剔除页面初始化、字典/选项、配置、埋点、推荐和静态资源。只有抓包证明初始化接口生成后续请求不可替代的动态 ID 或服务端状态时，才纳入正式链路。

## 5. 生成混合式正式脚本

代码结构、CLI、Profile 所有权、动态上下文、任务轮询、文件落盘、异常和日志以 [implementation-standard.md](implementation-standard.md) 为唯一正式契约。现有脚本与规范冲突时，新代码遵循规范，并只在本任务范围内修复直接复用的公共能力；不要顺手重构所有旧报表。

正式结构应是：

```text
Cloak Profile/CDP
  → 浏览器从真实入口建立登录、认证和页面会话
  → 浏览器自然请求提供该 endpoint 的新鲜动态上下文
  → WebAPI 查询（Payload 直接带日期与业务筛选）
  → 0 条则结束
  → WebAPI 创建一次导出任务
  → WebAPI 精确轮询本次任务
  → 下载原始文件
```

浏览器不是只在失败时使用；它是登录、真实入口和动态上下文的一部分。反过来，查询、导出、轮询和下载不应继续依赖整套 DOM 流程。

日期只做 Payload 字段替换，保留自然请求的字符串/秒/毫秒类型和时区。筛选直接写入 Payload。不得实现日期弹窗或调用选项接口；如果首次产生权威自然请求必须处于某个固定筛选状态，只复用现有 DOM 脚本已经验证的最少筛选动作，不重新分析控件。

动态请求头和 Payload 模板按 Target、endpoint 保存。401/403 时只重新走真实入口或触发该 endpoint 的自然请求一次，不把另一个接口最后出现的 token/风控字段注入当前请求。

## 6. Capture 数据与测试 fixture

完整 Capture 只留在 `.codex_tmp/captures`。代码和测试需要 fixture 时：

- 只提取当前解析逻辑所需的最小字段。
- 使用明显虚构的 ID、URL、金额和业务值。
- 再次移除 Cookie、endpoint、token、ticket、签名和风控值。
- 不提交原始响应明细或商户数据。

开发完成前用 `git check-ignore -v .codex_tmp/captures/<file>` 确认忽略规则生效。

## 7. 分层测试与定点诊断

依次验证：

1. 监听器 `--self-test`、`py_compile`、`--help`。
2. [正式实现规范的最低测试矩阵](implementation-standard.md#11-最低测试矩阵)，特别是 0 条短路、任务精确匹配、401/403 单次刷新、原子下载和统一退出码。
3. 平台统一入口只解析一次 Profile，并把同一 endpoint 串行传给所有选中报表的测试。
4. 平台支持多个报表时，测试前一报表停留在同平台其他子域或深层页面后，下一报表仍从官方首页重新走真实菜单入口。
5. fresh Profile/CDP 上的一次真实混合式 WebAPI 下载。

永久测试只能使用虚构 fixture。导入即连接浏览器、硬编码真实 endpoint、写原始响应或依赖当前在线页面的探针移到 `.codex_tmp/`，不得让 `unittest`/pytest 自动发现。

| 现象 | 只处理这一层 |
| --- | --- |
| Profile 未运行/无 endpoint | Cloak Login 精确匹配与启动 |
| 找不到首页或目标页 | 现有导航函数和入口 DOM |
| JSON 没有关键请求 | 启动时序、监听线程恢复、平台过滤 |
| HTTP 400/业务错误 | 对应 endpoint 的 Payload |
| HTTP 401/403 | 真实入口、Target、该 endpoint 动态上下文 |
| 日期/筛选错误 | Payload 字段、单位和时区 |
| 导出重复/旧任务 | 创建幂等和任务匹配 |
| 下载失败 | 短效 URL、Cookie/Referer 和文件写入 |

禁止因为单个 API 失败就重扫整页 DOM、重写监听器或重跑完整发现流程。

## 8. 交付

交付正式脚本、平台统一入口、Capture 的本地路径、最小接口链、单行运行命令、[合规检查](implementation-standard.md#12-交付前合规检查)和真实测试结果。最终答复只说明 CDP 已自动取得，不回显完整 endpoint。

一次 Capture 已完整时不重复运行 DOM 脚本；一次正式下载成功后不继续制造额外导出任务。
