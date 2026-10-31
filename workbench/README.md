# 全能工作台 v1（联邦式 · dsh 原生）

> 把「一个公司的全部业务」拆成若干独立项目，用 dsh 做运行时，用一个控制室统一范围、状态、入口和权限。
> 这一版是可运行的第 1 版：不是原型图，也不是 mock 界面——页面上每个数字都能追到某个项目自己的文件或本地库。

## 一、结论先说

| 问题 | 这一版的答案 |
|---|---|
| 大一统还是联邦 | **联邦**：6 个项目各自独立，工作台只做登记、投影、入口、治理 |
| 项目怎么接进来 | 物理克隆到 `projects/`，每个项目一份 `project.yaml`；**不改原项目一行代码** |
| 谁是真源 | `project.yaml` 是唯一真源；`projects/registry.json` 只是扫描产物，任何进程都不写它 |
| AI 怎么操作业务 | 页面上的每个动作都是一个 **tool**，人和 AI 走同一条通道；启停是 L2，必须确认 + 留审计 |
| 状态可信吗 | 端口探测 + 健康检查 + 运行记录三条证据；没有证据的指标一律显示「未接入」 |

## 二、这一版能跑什么（已实测）

- dsh 侧边栏出现「工作台」入口，点开是 **项目控制室**；14 个页面全部可切换。
- 三个 coffice 拆分单元可**一键启动/停止**（L2 确认卡 + 审计），健康分 95/100、时延 2–3ms 为真实探测值。
- 客服中心显示 56 家店铺、76 条差评、15398 行日指标——来自 `kefu/data/kefu.sqlite`。
- 直播运营显示 262 条排班、128 份场次报表、5 个采集模块——来自 `var/liveops.sqlite3`，并把当天的采集失败如实列进「需要你处理」。
- 店铺全景 56 行 × 5 项能力，圆点全部由 `kefu.shops` 与 `liveops.shift_reports` 算出；「结算」列因为没有来源，整列显示为未接入。
- 启停链路实测：无 `confirm` 返回 `428 confirm-required`，带确认后 `ok=true, pid=…`，5 秒内状态从「启动中」转「运行中」，审计落 `var/audit.jsonl`。

## 三、目录结构

```
workbench/
├─ plugin/                    ← dsh bundle（Host + Client），通过 link 安装进 profile
│  ├─ lib/index.js            Host：注册表 / 状态机 / 执行器 / 审计 / HTTP / 4 个 tool
│  ├─ lib/client.js           Client：侧边栏入口 + main 全局面板 + 14 页渲染器
│  ├─ lib/{registry,status,runner,audit,views,db,yaml}.js
│  └─ cordis.patch.yml        只 insert 一行，不覆盖任何官方插件
├─ projects/                  ← 六个项目，全部物理克隆/派生，无任何引用
│  ├─ coffice-core/           原一体式平台（2183 文件），保持完整可运行
│  ├─ coffice-ingest/         拆分：文件接入 + 自动化流程 + 公共健康
│  ├─ coffice-insight/        拆分：AI 管理 + 自然语言分析 + 看板代理 + 飞书
│  ├─ coffice-master/         拆分：身份权限 + 达人主数据 + 资金拆分
│  ├─ liveops/                直播运营（72 文件 + 真实 SQLite）
│  └─ kefu/                   客服中心（1292 文件 + 真实 SQLite）
├─ views/                     14 个 *.view.json（视图包：标题 / 问题 / 渲染类型 / 顺序）
├─ policies/roles.yaml        角色 × 范围 × 最高等级
├─ policies/redlines.md       L3 红线（写死在代码里，不可配置绕过）
├─ runtime/unit_app.py        联邦单元的零依赖 HTTP 外壳（标准库，无第三方包）
├─ scripts/clone-projects.sh  从 D:\fsan10 物理克隆三个源项目（排除 .git/.venv/node_modules/.env）
├─ scripts/bootstrap.ps1      给副本装依赖（liveops 的 .venv / kefu 的 node_modules）
└─ var/                       audit.jsonl / runs.jsonl / pids.json / logs/（不入库）
```

## 四、六个项目与四种形态

| 项目 | 形态 | 端口 | 启动方式 | 说明 |
|---|---|---|---|---|
| coffice-core | job | — | 由部署侧调度器触发 | 原一体式平台整包克隆，作为拆分参照系 |
| coffice-ingest | service | 8791 | `python service/app.py --port 8791` | 从 core 拆出的接入与自动化单元 |
| coffice-insight | service | 8792 | 同上 | 分析、看板、飞书 |
| coffice-master | service | 8793 | 同上 | 主数据、权限、资金拆分 |
| kefu | service | 3100 | `node next dev -p 3100` | 3000 常被生产实例占用，副本错开到 3100 |
| liveops | service | 8865 | `.venv python -m uvicorn liveops.app:app` | 副本独立端口，避免和线上冲突 |

四种形态的「启动」语义完全不同，这是控制室按形态分组、而不是按业务域分组的原因：
`service` 启停重启 · `job` 跑一次看上次 · `mcp` 重连看调用量 · `view` 打开即可。

## 五、14 个视图包

| 域 | 页面 | 主导区域 | 数据来源 |
|---|---|---|---|
| 今日 | 今日工作台 | 待办清单 + 3 个 KPI | 运行时状态 + 两库异常 |
| 经营 | 经营总览 / 店铺全景 / 资金与结算 / 门店与人效 | 指标覆盖 · 店铺×能力矩阵 · 未接入 · 未接入 | kefu 库；后两者显式未接入 |
| 业务 | 商品中心 / 履约与售后 / 客服中心 / 内容与达人 | 差评商品 · 物流指标 · 店铺表 · 主播表 | kefu + liveops 库 |
| 平台 | 项目矩阵 / 数据与连接 / 调度运行 | 四形态矩阵 · 连接器清单 · 运行时间线 | registry + 文件系统 + 三库运行记录 |
| 治理 | 公司与店铺 / 人员与权限 | 公司→店铺结构 · 角色×等级 | kefu 差评反推 + policies/roles.yaml |

`views/*.view.json` 只声明「标题 / 这页回答什么问题 / 用哪种渲染器 / 排序」；数据由 Host 的
`computeView(id)` 给出。加一页 = 加一个 json + 一个 resolver，不改主程序、不动导航。

## 六、和 dsh 的关系：页面是视图，操作是工具

```yaml
# 页面 = 视图包    views/kefu.view.json     → main 面板按 kind 渲染
# 操作 = 工具      workbench_projects / workbench_project / workbench_view / workbench_control
# 流程 = 技能      交给 skill 层组合，本轮不预置
```

四个 tool 的等级与边界：

| 工具 | 等级 | 说明 |
|---|---|---|
| `workbench_projects` | L0 | 列项目、状态、健康分 |
| `workbench_project` | L0 | 单项目详情、健康分构成、最近运行 |
| `workbench_view` | L0 | 读任意视图的数据 |
| `workbench_control` | **L2** | 启停；必须 `confirm=true` + `intent`，缺前置返回 `not-ready` |

三层校验落在代码里：

1. **身份范围**：会话继承发起人范围（本版先由 `policies/roles.yaml` 声明，网关按 profile 注入）。
2. **工具等级**：`project.levels` 声明每个动作的等级；L3 直接返回 `l3-redline`，只留审计工单。
3. **会话预算**：审计里按 actor 统计 L2 写入，超阈值拒绝（`audit.writesWithin`）。

再配三件事：pid 幂等（重复启动返回同一 pid）、审计含自然语言 `intent`、`var/logs/<id>.log` 保存子进程输出。

## 七、怎么跑

```powershell
# 1. 克隆源项目（只需一次；源目录只读）
bash workbench/scripts/clone-projects.sh

# 2. 给副本装依赖（coffice 三个单元是标准库，无需安装）
.\workbench\scripts\bootstrap.ps1

# 3. 把工作台装进 dsh 的 web profile（已装过可跳过）
pnpm dsh plugin --profile web add "link:D:/fsan10/deepseek-harness/workbench/plugin"

# 4. 启动
pnpm dsh web --port 4599
```

打开后左侧点「工作台」。控制室每 20 秒静默刷新一次状态（不产生模型调用）。

接口自检：

```bash
curl http://127.0.0.1:4599/api/workbench/health
curl http://127.0.0.1:4599/api/workbench/bootstrap
curl http://127.0.0.1:4599/api/workbench/views/projects
```

## 八、和三个原项目的关系（重要）

- **源目录一行未改**：`D:\fsan10\mock_coffice`、`D:\fsan10\直播运营`、`D:\fsan10\kefu` 保持原样，仍可独立运行。
- **副本是物理拷贝，不是引用**：`projects/` 下是真实文件树，剪掉任何一个源目录都不影响工作台。
- **密钥不进副本**：克隆时排除 `.env` / `.env.local` / `.env.bak*`；副本自己的运行时密钥由 bootstrap 或用户自行提供。
- **端口错开**：3000/8765 上可能有生产实例在跑，副本改用 3100/8865；`project.yaml` 里可改。
- **子进程随宿主生命周期结束**：dsh 停止后由它拉起的服务会一起退出（pid 文件在下次启动时清理）。需要长期驻留的服务请交给系统服务托管——工作台只做控制面，不做「进程的爹」。

## 九、诚实清单：这一版没做的

1. **资金与结算、门店与人效**两页没有数据源，页面显示「未接入」+ 需要什么契约，不填假数字。
2. **coffice 三个拆分单元只做到「边界 + 自检」**：模块源码原样搬过去，但还没为每个域包出真正的业务 API；这是下一步的主要工作量。
3. **范围选择器**（集团→公司→平台→店铺→账号）尚未做成可交互控件，当前按全量展示；数据层已经按 `project.yaml` 的 `owner/domain` 预留。
4. **「进入项目」= 打开项目自己的界面**（新标签页），还不是方案里的「新建 scoped session」；tool 白名单隔离留到 v2。
5. **身份范围**取自 `policies/roles.yaml`，还没有和 dsh 的会话身份打通。
6. **L3 红线**只覆盖 `workbench_control`；新增工具必须自己声明等级，否则默认按 L2 处理。

## 十、下一步建议（按优先级）

1. 把 coffice-ingest 的「批量补采/重跑」包成第一个**真业务 tool**（保留批次号、幂等键），验证 L2 确认卡在真实写操作上的手感。
2. 给 kefu 的差评派单做 L1 工具（自动 + 留痕），跑通「一句话 → 工具 → 页面刷新」闭环。
3. 补 DIM：把 56 家店铺的公司归属从差评明细反推，改为读 `dim.dim_platform_shop_company`。
4. 做 scoped session：进入项目时新建会话并只挂该项目的 tool 白名单。

## 附：验证截图

`docs/screenshots/` 下四张是 2026-10-31 用无头 Chrome 实拍（1440×900，`pnpm dsh web --port 4599`）：

| 文件 | 页面 | 看点 |
|---|---|---|
| `01-project-matrix.png` | 项目矩阵 | 四形态分组、健康分构成彩条、运行中/已停止的真实差异 |
| `02-project-drawer.png` | 项目详情抽屉 | 健康分拆到 40/30/20/10、前置检查、L2 确认入口 |
| `03-shop-panorama.png` | 店铺全景 | 56 店 × 5 能力，结算列整列「未接入」 |
| `04-kefu.png` | 客服中心 | 真实店铺/差评/采集成功率 |
