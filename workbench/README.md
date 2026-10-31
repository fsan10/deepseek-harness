# 全能工作台 v1.1（联邦式 · dsh 原生 · 可操作）

> 六个独立项目 + 一个 dsh 原生工作台。
> **能看，也能干**：文件接入、自动化流程、达人主数据、资金拆分调整都在页面里操作，
> 同一批动作同时注册成 AI 工具；客服、直播两个原系统的完整界面直接嵌在工作台里。
> coffice 的业务数据只写本地 SQLite（`var/workbench.db`），生产库一行不动。

## 一、结论先说

| 问题 | 这一版的答案 |
|---|---|
| 大一统还是联邦 | **联邦**：6 个项目各自独立，工作台只做登记、投影、入口、治理 |
| 原功能还在吗 | **在**：客服 / 直播以原生界面嵌进工作台（`kind: app`），所有原有菜单可点可操作 |
| 人怎么操作 | 文件接入、自动化、达人、资金四个页面有**表单与行内动作**，写入本地业务库 |
| AI 怎么操作 | 每条动作都是 `workbench_action` 的一个 action，等级 L1/L2/L3 与页面完全一致 |
| 数据从哪来 | kefu / liveops 读它们自己的 SQLite；coffice 的数据落工作台本地 SQLite，**不碰生产 PG** |
| 状态可信吗 | 端口 + 健康检查 + 运行记录三条证据；没有证据的指标一律「未接入」 |

## 二、这一版能干什么（已实测）

**原系统，原样可用**
- 「客服中心（原系统）」页内嵌 kefu 本体：经营总览、接待量分析、店铺体验分、差评分析、评价采集、数据接入……全部可点。
- 「直播运营（原系统）」页内嵌 liveops 本体：数据总览、排班管理、数据明细、采集记录、采集脚本、系统配置。
- 顶部只加一条 KPI（店铺 / 差评 / 采集成功率），不改原系统任何一个页面。

**新增的四个操作页**
| 页面 | 能做什么 | 落到哪 |
|---|---|---|
| 文件接入 | 扫描 `coffice-core/data` 的 59 个真实文件；逐条「登记 / 标记入库」 | `ingest_batches` |
| 自动化流程 | 新建流程、立即运行、看最近 12 次记录；三条内置同步真跑 | `flows` / `flow_runs` |
| 达人主数据 | 新增达人、补佣金率、停用 | `influencers` |
| 资金拆分 | 新建调整单 → 待复核 → 复核 / 驳回 | `fund_adjustments` |
| 公司与店铺 | 给 56 家店铺补公司归属（当前只有 7 家已归属） | `dim_shop_company` |

**公司整体分析**
「公司总览」页直接从本地镜像聚合：直播成交额 ¥84.7 万、23 家店有指标、5 家公司有归属、16 家店未归属（会显式标黄）。
每一行都能追到 `metrics_daily` 的具体来源（kefu 15148 行 / liveops 32 行）。

## 三、一条动作，两条通道

页面按钮和 AI 工具调的是**同一个 `runAction`**，不存在两套实现：

```js
// plugin/lib/index.js
const ACTIONS = {
  'ingest.register':   { level: 'L1', ... },
  'flow.run':          { level: 'L2', ... },
  'influencer.upsert': { level: 'L2', ... },
  'fund.adjust':       { level: 'L2', ... },
  'fund.approve':      { level: 'L3', ... },  // 只允许人工在页面确认
  ...
}
```

| 通道 | 调用 | 等级行为 |
|---|---|---|
| 人 | 页面按钮 → `POST /api/workbench/action` | L1 直接执行；L2/L3 弹确认卡，写着影响面 |
| AI | `workbench_action` 工具 | L1 直接执行；L2 必须 `confirm=true`；**L3 永远返回 blocked** |

实测：`flow.run` 不带 confirm 返回 `428 + 影响面`；带上后真跑并写 15163 行；
`fund.approve` 以 `actor=agent` 调用返回 `L3-human-only`，审计留痕。

七个工具：`workbench_projects` / `workbench_project` / `workbench_view` / `workbench_control` / `workbench_query`（只读 SQL，表白名单）/ `workbench_analysis`（公司级聚合）/ `workbench_action`。

## 四、目录结构

```
workbench/
├─ plugin/                    dsh bundle（Host + Client）
│  ├─ lib/index.js            注册表 / 状态机 / 执行器 / 审计 / HTTP / 7 个 tool / 11 个 action
│  ├─ lib/store.js            本地业务库（var/workbench.db）：7 张表 + 播种 + 同步 + 写动作
│  ├─ lib/views.js            18 个视图包的数据解析
│  ├─ lib/client.js           侧边栏入口 + 面板 + 5 种渲染器（含 app 内嵌、ops 表单）
│  └─ lib/{registry,status,runner,audit,db,yaml}.js
├─ projects/                  6 个项目（物理克隆 / 从一体式平台拆出）
├─ views/                     18 个 *.view.json
├─ policies/                  角色与 L3 红线
├─ runtime/unit_app.py        联邦单元的零依赖 HTTP 外壳
├─ scripts/                   clone-projects.sh / bootstrap.ps1
├─ docs/screenshots/          实拍验证图
└─ var/                       workbench.db · audit.jsonl · runs.jsonl · pids.json · logs/
```

## 五、18 个页面

| 域 | 页面 |
|---|---|
| 今日 | 今日工作台（待办 + 3 个 KPI） |
| 经营 | 公司总览 · 店铺全景 · 资金与结算（未接入）· 门店与人效（未接入） |
| 业务 | 客服中心（原系统）· 直播运营（原系统）· 文件接入 · 自动化流程 · 达人主数据 · 资金拆分 · 商品中心 · 履约与售后 |
| 平台 | 项目矩阵 · 数据与连接 · 调度运行 |
| 治理 | 公司与店铺 · 人员与权限 |

`views/*.view.json` 只声明标题 / 问题 / 排序；渲染类型由数据决定：
`overview` `control` `table` `matrix` `governance` `unavailable` **`app`** **`ops`**。

## 六、数据边界（重要）

- **生产的 mock_coffice 库一行不动**。coffice 相关数据只写 `var/workbench.db`（SQLite，已在 `.gitignore`）。
- **kefu / liveops 的库只读**：通过 `ATTACH ... AS ext` 读取，读完立即 DETACH，不写回。
- **原始项目代码不动**：三个源目录保持原样；`projects/` 下是物理副本，可以改的是副本。
- **密钥不入库**：`.env`、`var/master.key` 都在 gitignore 里；liveops 需要 `master.key` 才能解密已有设置。

## 七、怎么跑

```powershell
# 1. 克隆（只需一次）
bash workbench/scripts/clone-projects.sh

# 2. 装依赖（liveops 用 Python 3.12，含 playwright；kefu 用 npm ci）
.\workbench\scripts\bootstrap.ps1

# 3. 装进 dsh profile（装过可跳过）
pnpm dsh plugin --profile web add "link:D:/fsan10/deepseek-harness/workbench/plugin"

# 4. 启动（默认 3080）
pnpm dsh web
```

终端会打印带 `?token=…` 的地址，**必须用它打开**；token 每次启动都变。
左侧边栏「插件」下面点 **「全能工作台」**（底部第三方 worktable 的「工作台」是另一个东西）。

## 八、还没做的

1. **资金与结算、门店与人效**仍无数据源，页面写明需要什么契约；资金**调整**可以在「资金拆分」里做。
2. **coffice 三个拆分单元**只有边界 + 自检，业务 API 还没包；文件接入目前是「登记批次」，真正的 ETL 解析（xlsx 读表）还没接。
3. **xlsx 行数不解析**（只对 CSV 实数），避免引入第三方解析库。
4. **公司归属**只有 7/56 家（从差评反推），其余要在「公司与店铺」里人工补或接 DIM。
5. **工具已注册但未做模型侧实跑**：仓库根没有 `DEEPSEEK_API_KEY`，需要在有 key 的会话里验一次。
6. L3 只覆盖 `fund.approve`；新增动作必须自己声明等级，否则默认按 L2。

## 九、验证截图

`docs/screenshots/`（2026-10-31 无头 Chrome 实拍，1440×900）：

| 文件 | 看点 |
|---|---|
| `01-company-overview.png` | 公司总览：¥84.7 万成交、23 家店、5 家公司、16 家未归属 |
| `02-ingest.png` | 59 个真实文件、CSV 行数、登记/标记入库按钮 |
| `03-confirm.png` | L2 确认卡：影响面写在按钮上面 |
| `04-automation.png` | 流程表 + 真实运行记录（15163 行） |
| `05-influencers.png` | 达人表 + 新增表单 |
| `06-kefu-embedded.png` | kefu 原系统嵌在工作台里，菜单齐全 |
| `07-liveops-embedded.png` | liveops 原系统嵌在工作台里 |
| `08-project-matrix.png` | 四形态矩阵与健康分构成 |
