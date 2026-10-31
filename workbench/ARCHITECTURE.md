# 工作台架构（v1）

> 每个模块带 A/B/C/D 编号，下面文件表里每个路径标同一个编号，可以逐条核对。
> 这份文件回答一个问题：**改一个东西，应该改哪个文件**。

## 一、四层结构

```
┌──────────────────────────────────────────────────────────────────────┐
│ A 视图层（只读投影，不执行业务）                                      │
│   A1 main 面板 + 14 个视图包      A2 项目详情抽屉（健康分/运行/启停）  │
└───────────────▲──────────────────────────────────────────────────────┘
                │ fetch /api/workbench/*
┌───────────────┴──────────────────────────────────────────────────────┐
│ B 管理平面（唯一真源 + 状态投影）                                     │
│   B1 registry（project.yaml）   B2 runner（启停/pid/日志）             │
│   B3 status（探测/状态机/健康分）                                     │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│ C 能力与治理                                                          │
│   C1 tools（L0-L3）   C2 policies（角色/红线）   C3 audit（JSONL）     │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│ D dsh 运行时                                                          │
│   D1 session / tool registry / permission   D2 var（runs/logs/pids）   │
│   D3 webServer 路由注册表                                             │
└──────────────────────────────────────────────────────────────────────┘
```

数据流只有两条，且不交叉：

- **看**：浏览器 → `A1` → `GET /api/workbench/views/:id` → `B1/B3` → `computeView()` → 项目本地库/文件系统。
- **做**：浏览器点击 或 模型调 `workbench_control` → `C1` 校验等级 → `C2` 查红线 → `B2` 拉起子进程 → `C3` 落审计 → `B3` 重新探测 → `A2` 刷新。

## 二、编号 ↔ 文件

| 编号 | 路径 | 职责 | 改动影响 |
|---|---|---|---|
| A1 | `views/*.view.json` | 页面声明：标题/问题/渲染类型/顺序 | 只影响导航与页面标题 |
| A1 | `plugin/lib/client.js` | 侧边栏入口、main 面板、5 种渲染器、抽屉 | 视觉与交互 |
| A2 | `plugin/lib/client.js`（Drawer） | 健康分构成、最近运行、启停确认、日志 | 启停手感 |
| B1 | `projects/*/project.yaml` | **唯一真源**：形态/端口/命令/健康/依赖/等级 | 控制室与工具同时变化 |
| B1 | `plugin/lib/registry.js` | 扫描 + 校验 + 生成只读索引 | 加字段在这里加 |
| B1 | `plugin/lib/yaml.js` | 极简 YAML 子集解析（不引第三方包） | 需要新语法时改这里 |
| B2 | `plugin/lib/runner.js` | spawn/pid/日志/taskkill | 启动语义 |
| B2 | `projects/*/runtime/start.ps1` | 人工启动入口（与 command/args 等价） | 仅影响手动启动 |
| B3 | `plugin/lib/status.js` | TCP/HTTP 探测、状态机、健康分 | 可信度来源 |
| C1 | `plugin/lib/index.js`（tools 段） | 4 个 tool 的 schema 与执行 | 模型能看到什么 |
| C2 | `policies/roles.yaml` | 角色 × 范围 × 最高等级 | 治理页 |
| C2 | `policies/redlines.md` | L3 红线清单 | 只读文档；代码里另有硬判 |
| C3 | `plugin/lib/audit.js` + `var/audit.jsonl` | 一次调用一行，不改写历史 | 事后回放 |
| D1 | dsh `tool-*` / profile | tool 注册与权限 | 由 dsh 决定 |
| D2 | `var/{runs.jsonl,pids.json,logs/}` | 运行事实，可删可重建 | 不影响代码 |
| D3 | `plugin/lib/index.js`（register 段） | `/api/workbench/*` 路由 | 前端契约 |

## 三、状态机

```
idle ──start──▶ starting ──健康通过──▶ running ──连续3次失败──▶ degraded
                   │                      │                        │
                   └──30s 未起来──▶ failed  └──stop──▶ stopped ◀────┘
```

| 状态 | 判定依据 |
|---|---|
| starting | 刚调用 start，端口还没通 |
| running | TCP 通，且声明了 `health.path` 时 HTTP < 400 |
| degraded | 端口通但健康检查失败，且连续 ≥3 次 |
| stopped | 端口不通，且不是 starting |
| failed | starting 超过 30 秒仍未通，或 job 上次运行失败 |
| idle | job 形态还没跑过 |

健康分（40/30/20/10）的每一分都能在界面上展开看构成；成功率来自 `var/runs.jsonl`，没有记录时按「未知」给分并在界面标注。

## 四、四种形态的语义差异

| 形态 | 「启动」是什么意思 | 状态从哪来 | 典型操作 |
|---|---|---|---|
| service | 拉起常驻进程，占端口 | 端口 + 健康检查 | 启动 / 停止 / 看日志 |
| job | 跑一次，看上次结果 | `var/runs.jsonl` 最近一条 | 看上次、看失败原因 |
| mcp | 连接外部服务，看会话是否在 | 连接态（本版占位） | 重连、看调用量 |
| view | 没有进程，打开就能看 | 恒为可读 | 打开 |

把四种混在一行里，操作栏一定会乱——这是按形态分组、不按业务域分组的唯一理由。

## 五、拆分策略：绞杀者，不是重写

```
coffice-core（完整、可运行）
   ├─ apps/file_ingest      ──副本──▶ coffice-ingest
   ├─ apps/automation_center──副本──▶ coffice-ingest
   ├─ apps/ai_*             ──副本──▶ coffice-insight
   ├─ apps/dashboard_center ──副本──▶ coffice-insight
   ├─ apps/identity_access  ──副本──▶ coffice-master
   └─ apps/influencer_config──副本──▶ coffice-master
```

- 每个单元拿到**源码副本**（不是符号链接、不是 import 原目录），可以独立打包部署。
- core 保持完整：拆分过程中任何一处没搬干净，core 仍然跑得起来——这是回退路径。
- 单元外壳 `runtime/unit_app.py` 只用标准库，保证「拷走就能跑」，不引入新的依赖地狱。
- 外壳只回答两个问题：这个单元**活着吗**、它**手里有什么**。业务 API 是下一步的事。

## 六、安全与权限（写死在代码里的部分）

| 约束 | 位置 | 绕过方式 |
|---|---|---|
| L3 永不执行 | `index.js` 的 `level === 'L3'` 分支 | 无（返回 403 + 审计） |
| L2 必须确认 | `body.confirm !== true → 428` | 无 |
| 前置未装不许启动 | `readiness()` 检查 `requires` | 无（返回 409 + bootstrap 提示） |
| 只能启停登记过的项目 | `getProjects().find(...)` | 无 |
| 审计必留 intent | `workbench_control` 的 `intent` 必填 | 无 |

界面上还有一条：**外部进程标记**。端口通但没有工作台 pid 时标「外部进程」——避免把别人正在跑的生产实例算成自己的工作台启动的。

## 七、扩展一个页面 / 一个工具

**加页面**（不改主程序）：

1. 新建 `views/xxx.view.json`：`{id, domain, title, question, kind, order}`。
2. 在 `plugin/lib/views.js` 的 `resolvers` 里加同名函数，返回 `{kind, ...}`。
3. 若 `kind` 是新的，在 `client.js` 的 `Body` 里加一个分支。

**加工具**：

1. 在 `index.js` 里 `tools.register({...})`，显式写 `output.schema`（标准 JSON Schema：`required` 是数组，不是属性上的布尔值）。
2. 危险等级通过 `project.levels` 或代码内判定，默认按 L2 处理。
3. 审计里必须带 `intent`；失败要返回可读原因，不要吞异常。
