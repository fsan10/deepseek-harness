# Automation Component Workbench

本目录的自动化控制面采用三层运行模型：

- Automation Run：一次任务或 Flow 的运行。
- Step Run：平台 / 店铺 / 报表级步骤，兼容既有 DownloadController。
- Component Run：Step 内部可独立观测、重试设计和 AI 修复的业务原子动作。

## 组件边界

组件应对应稳定的业务动作，例如启动/复用 Cloak Profile、连接 CDP、检查登录态、打开报表页、设置业务日期、创建导出任务、等待导出、人工 Challenge、下载、解压、校验和归档。不要把每一次 Playwright click/fill/wait 拆成画布节点；一个组件内部可以包含多次浏览器操作。

## Runtime telemetry

scripts/auto_download/playwright/component_runtime.py 提供 automation_component 装饰器、component_event、父子组件上下文、stdout JSON 事件协议、in-process event sink、错误分类和秘密值脱敏。

all_platform_downloads.json 当前引用的所有活跃报表模块均有 workflow 边界，主要日期、导出、等待、下载、解压、校验、归档逻辑继续拆为子组件。没有迁移的内部函数仍会归责到父 workflow 组件。

## 数据模型

- ops.automation_flow：Flow Studio 草稿 / 发布版本。
- ops.automation_component_run：原子组件运行，支持 parent_component_run_id。
- ops.automation_component_event：组件内部 action / observation / waiting_human 等事件。
- ops.automation_artifact：最终文件成果。

验证码、密码、Cookie、Token 不允许进入 Flow definition、input_context、component event 或运行日志。

## Flow Studio

路由：/automation/#flow-studio

支持组件搜索拖拽、节点移动和连线、复制/禁用/删除、超时/重试/失败策略、条件表达式、配置 JSON、Flow 变量、JSON 导入导出、草稿保存/发布以及发布 Flow 入队运行。

custom.* 节点可以保存在草稿中，但没有后端 Registry + Handler 时不能发布。

## Flow execution safety

Flow 定义不能指定 Python 模块、Shell 命令或可执行文件。发布和运行只接受 COMPONENT_REGISTRY 白名单组件，并要求 flow_executable=True。

当前 V1 提供完整可执行参考 Flow：jd.order.reference。它验证 Cloak → CDP → 京东登录 → 订单导出页 → 日期 → 创建导出 → 等待 → 下载 → 飞书文件密码 → 解压/校验/归档 → 关闭 Profile → Artifact/FileIngest。

其他平台的现有生产脚本已经接入组件级观测；在为原子组件补齐专用 Flow Handler 前，组件库会明确显示“仅组件观测”，不会伪装成可执行节点。

## AI repair context

失败组件可通过 GET /api/automation/components/runs/{component_run_id}/repair-context 获取 component_code/version、error_type/error_message、page_url、screenshot_path/trace_path、最近 component events、Flow/平台/店铺/Profile 上下文、source_hint 以及默认 component_only 修复提示词。

Workbench 执行详情提供“复制 AI 修复上下文”，默认要求 Codex 只修改对应组件和测试，不扩大到无关 Flow。

## 新组件迁移规范

1. 优先给现有稳定函数加 automation_component，不复制业务实现。
2. 在 apps/automation_center/registry.py 注册 ComponentSpec。
3. 只做运行观测时保持 flow_executable=False。
4. 支持画布执行后，在 FlowRunner.handlers 增加固定 Handler，再打开 flow_executable=True。
5. Handler 不得从数据库读取 module/script/command 后动态 import/exec。
6. 人工 Challenge 必须复用 automation_challenge.py，不要在平台脚本重复实现 HTTP 轮询。
7. 失败尽量留下标准 error_type、page_url、截图和非敏感事件。
8. 新增或修改组件后补测试，并通过 .github/workflows/automation-component-static.yml。

## Component Library 边界

Flow Studio 组件库只展示 `flow_executable=True` 的独立编排能力。仅用于旧脚本内部遥测的函数可以继续通过 `@automation_component` 产生运行树事件，但不要为了展示它们而注册成可拖拽节点，也不要在前端增加“仅观测”兼容分支。

文件处理采用统一管线：

- `report.validate.schema`：统一画布校验节点。上游通过 `pending_artifact.validator` 声明具体业务校验器；平台差异留在校验实现内部。
- `report.archive`：唯一标准归档节点。消费 `pending_artifact.source_path/report_name/business_date`，平台、公司、店铺从当前 Profile 读取。
- `scripts.auto_download.move_report.archive_report`：归档的唯一 Python 实现；CLI 与 Flow 均复用它。

不要新增 `<platform>.*.archive` 或 `<platform>.*.validate` 画布组件。确有平台差异时，新增 validator 实现或上游业务组件，并通过统一文件管线调用。

## Flow Studio 测试运行与正式运行

Flow Studio 是流程设计和 Playwright 调试工作台。已保存的 draft Flow 可以通过 `test-run` 执行，不要求发布。测试运行复用真实 AutomationWorker / FlowRunner，但使用 `trigger_type=test`，不进入正式“执行记录”、任务最近状态、工作台统计或每日成果。

自动化任务页面只运行已发布 Flow，并使用正式 `manual/schedule` 运行记录。不要把 Flow Studio 的测试按钮改回“必须发布”，也不要把 test run 混入生产执行历史。

画布运行状态只展示当前测试 run；结束后的节点/连线状态保留用于检查，用户点击“清除运行状态”后恢复设计态。

## 下游数据处理必须显式

FlowRunner 不允许在流程结束时隐式调用 FileIngest 或 ETL。

- `ingest.submit`：显式 API/FileIngest 节点。只提交本次新增标准 Artifact 并等待 ODS 导入完成，`auto_refresh=false`。
- `etl.trigger`：显式下游刷新节点。依赖上游 `ingest.submit` 的 ingest_run_id，按报表类型计算受影响 ETL。
- 未放置上述节点时，Flow 只负责浏览器自动化、下载、校验与归档。

这样同一份下载流程可以按场景选择“只下载”“下载+API上传”“下载+API上传+ETL”，不要重新引入隐式副作用。

