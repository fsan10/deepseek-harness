---
name: ecommerce-webapi-builder
description: 在用户只提供电商平台、报表和 Cloak Login Profile 名称时，自动取得 CDP、复用现有 DOM 流程并监听真实接口链，开发或修复遵循统一模块、CLI、返回值、错误、下载和测试契约的混合式 WebAPI 报表下载器。适用于拼多多、抖音、京东、快手、小红书、天猫等平台的新报表 API 化；仅运行成熟下载脚本时不使用。
---

# 电商 WebAPI 下载器开发

## 调用契约

用户只需提供：

```text
使用 $ecommerce-webapi-builder
平台：拼多多
报表：订单
Profile：PDD-拼多多-MOCK饮品旗舰店
开发 WebAPI 下载脚本
```

不要再要求用户提供 CDP、DOM 脚本路径、页面 URL、API、请求头、Payload、Cookie、token、签名或 HAR。只有项目中不存在可识别的 DOM 脚本和入口证据时，才询问一段首页菜单路径或一个 XPath。

## 第一步：自动取得 Profile 和 CDP

用户给出的 Profile 名称即授权本次开发使用并在必要时启动该 Profile。严格执行：

1. 调用 Cloak Login MCP 的 `mcp__cloak_login__list_active`。
2. 在活动项中按完整 `name` 精确匹配。命中时复用其 `id` 和 `wsEndpoint`，不重启。
3. 未命中时调用 `mcp__cloak_login__list_profiles`，按完整 `name` 精确匹配保存的 Profile。
4. 唯一命中后调用 `mcp__cloak_login__start_profile({id})`。优先读取启动结果中的 `wsEndpoint`；若尚未返回，有限次数重新调用 `list_active`，直到同一 `id/name` 出现且带有 endpoint。
5. 零个或多个同名结果、启动失败、或多次查询仍无 endpoint 时停止并明确报告；不得近似选择另一个 Profile。

除非 Cloak Login MCP 不可用或启动失败，不向用户索要 CDP。不要把完整 endpoint 写进源码、捕获 JSON、文档或最终答复；只在当前进程命令中传给监听器/正式脚本。记录本次是否由 AI 启动 Profile，但除非用户明确要求，不停止该 Profile。

## 混合式边界

这个 skill 既不是“全 API”，也不是“完全不要 DOM”：

- 浏览器/CDP 负责：Profile、登录态、从真实首页进入受保护模块、跨域认证跳转、页面会话，以及按需产生新鲜动态风控上下文。
- WebAPI 负责：携带日期和业务筛选查询、判断 0 条、创建导出任务、轮询状态、取得下载地址和保存原始文件。
- DOM 发现脚本只在首次抓包时完整运行一次，用来产生权威请求链。正式脚本只复用其中必要的登录、入口导航和自然请求触发代码，不复刻整套页面下载流程。

日期控件、资金类型/流水类型下拉框只是生成查询 Payload 的 UI。正式 WebAPI 脚本直接替换查询 Payload 字段，不实现日期组件，也不调用字典/选项接口去“设置”筛选，除非抓包证明该接口生成不可替代的动态值或服务端状态。

## 必用资源和快路径

1. 写正式代码前完整读取 [references/implementation-standard.md](references/implementation-standard.md)，并检查共享 `profile_cdp.py`、当前平台 common 模块和统一入口；不得任选一个旧报表脚本整段复制。
2. 用 `rg` 自动定位目标平台/报表现有 DOM 下载脚本，只读入口、CLI 和业务动作顺序。
3. 运行 [scripts/ecommerce_http_capture.py](scripts/ecommerce_http_capture.py)，不要临时编写平台专属监听器。
4. 使用 [scripts/platform_filters.json](scripts/platform_filters.json) 的平台规则；缺域名时扩展规则或传 `--include-domain`。
5. 监听器输出 `[READY]` 后，使用同一 Profile/CDP 运行现有 DOM 脚本一次。
6. 停止监听后只分析捕获 JSON，识别最小链路，再按正式实现规范开发并接入平台统一入口。
7. 按错误层定点修复；只有导航/控件日志明确失败时才分析对应 DOM。

具体执行和验收顺序见 [references/development-workflow.md](references/development-workflow.md)。开始前可运行监听器 `--self-test`，用 `--list-platforms` 查看内置规则。

## Capture 与 Git 隔离

监听器默认把 JSON 保存到 Git 根目录：

```text
.codex_tmp/
└── captures/
    └── pdd_order_20260910.json
```

文件名按平台、报表和本地日期自动生成；同名时追加序号，不覆盖旧捕获。项目已忽略 `.codex_tmp/`。不得把完整 Capture 保存到 `Test_Script`、加入 Git、复制到正式代码目录或在最终答复中展开敏感内容。若永久测试需要 fixture，只提取最小结构并再次脱敏，不提交原始捕获。

从项目根目录运行监听器时无需指定 `--output`：

```powershell
& ".venv\Scripts\python.exe" ".codex\skills\ecommerce-webapi-builder\scripts\ecommerce_http_capture.py" --platform pinduoduo --profile-name "PDD-拼多多-MOCK饮品旗舰店" --ws-endpoint "<由 Cloak Login MCP 取得>" --label "订单"
```

Codex 应保持监听进程会话，在 DOM 脚本完成且最后请求落定后主动发送 `Ctrl+C`；不要让用户管理监听终端。

## 正式脚本要求

- 正式脚本、公共模块、统一入口、返回值、退出码、日志、文件落盘和测试必须满足 [正式实现规范](references/implementation-standard.md)。
- 正式脚本放 `ReverseAPI/Formal_Script`，永久纯逻辑测试放 `ReverseAPI/Test_Script`，下载默认放由模块位置计算出的 `ReverseAPI/downloads`；不得依赖当前工作目录。
- 所有平台复用 `ReverseAPI/Formal_Script/profile_cdp.py`。平台统一入口只解析一次 Profile/CDP，并把同一 endpoint 注入串行执行的子报表。
- 平台已有统一入口时，新报表必须同时加入报表注册、日期计划和统一入口测试；不要只交付一个孤立脚本。
- 浏览器从真实入口建立会话和动态上下文后，查询/导出使用页面内 WebAPI；若 Capture 证明一次性风控请求只能由网页产生，可以拦截并最小修改该自然请求。
- 查询明确为 0 时在创建任务前返回 `None`；没有独立查询接口时，明确的“导出 0 条”任务终态也按成功无数据处理。
- 下载必须使用唯一目标名、同目录 `.part`、HTTP 成功与非空检查、原子替换和失败清理。用户只要求原始 ZIP/XLS/XLSX/CSV 时不擅自解压或表头校验。
- 动态头和 Payload 模板按 Target、endpoint 保存；401/403 只刷新该 endpoint 的自然上下文并重试一次。
- 登录、人机验证、短信验证或权限不足统一返回 `NEEDS_HUMAN:` 和退出码 `2`，不能被平台统一入口降级成普通失败。

## 验收与故障边界

先完成监听器自检、`py_compile`、`--help` 和 [最低测试矩阵](references/implementation-standard.md#11-最低测试矩阵)，再做一次真实 WebAPI 下载。实时 CDP 探针、原始响应和完整 Capture 只能放 `.codex_tmp/`；带真实 endpoint 或导入即联网的文件不得进入永久测试。

- 导航失败：只检查首页入口和对应 DOM。
- JSON 缺请求：检查监听启动时序、线程恢复、平台过滤和 `skipped_hosts`。
- HTTP 400/业务错误：只比较对应 endpoint 的 Payload。
- HTTP 401/403：刷新真实入口、Target 和该 endpoint 的动态上下文。
- 数据范围错误：检查 Payload 日期/筛选/时间单位，不分析日期组件。
- 任务或下载失败：只检查创建、轮询、匹配和下载链。

最终交付正式脚本、平台统一入口、Capture 路径、关键接口链、单行命令、规范合规项和真实测试结果。不要把静态检查、DOM 手工下载或用户操作当成 WebAPI 端到端成功。
