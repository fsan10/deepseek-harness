# 达播运营配置台性能与接口问题分析报告

- 日期：2026-08-10
- 范围：商品品类操作 5 秒+ 根因量化、达播商务归属"接口不存在"根因、全项目同类问题排查
- 结论先行：**商品品类每次写操作都在事务内同步执行整条指标链路的全量重算（实测 6.34s），是 5s+ 的唯一主因**；"接口不存在"是聚合服务适配层缺失路由（非进程问题）；全项目共 21 处"写后同步刷新"调用点，其中商品品类 14 处为严重等级。

---

## 一、商品品类操作 5 秒+（严重）

### 1.1 根因链

```
用户点击停用/新增/修改/删除
  └─ PUT/POST /api/... （进入 ProductCategoryService 写方法）
       └─ with self.transaction():                 # 写事务内
            ├─ UPDATE/DELETE dim 表               # 毫秒级
            └─ _refresh_dashboard(cursor)          # ★ 整条指标链路全量重算
                 ├─ 9 个 CREATE SQL（DROP+CREATE 表，含 7 平台 DWS + helper + ADS）
                 ├─ 7 个平台 REFRESH SQL（TRUNCATE+INSERT 全量重算 DWS）
                 └─ 1 个 FINAL REFRESH SQL（全量重算 ADS 公司店铺日汇总）
       └─ commit（6.3s 内一直持锁）
  └─ 前端 reload()：串行 renderSummary → loadActiveView → 最后才 toast
```

调用点：`apps/influencer_config/product_category.py` 中 **14 处**写操作（创建/更新/删除分类、产品、目录行，以及全部状态切换）每次都会触发。

### 1.2 实测数据（事务内执行 + 回滚，无副作用，2026-08-10）

| 阶段 | 文件 | 耗时 |
|---|---|---|
| CREATE ×9 | 201/248/251/254/257/260/300/276/160 | 0.05s |
| REFRESH douyin | 202 | **1.72s** |
| REFRESH wechat_channels | 263 | 1.08s |
| REFRESH jd | 266 | 0.07s |
| REFRESH ks | 269 | 1.17s |
| REFRESH xhs | 272 | 0.01s |
| REFRESH pdd | 275 | 1.09s |
| REFRESH tmall | 303 | 1.03s |
| FINAL ADS | 165 | 0.12s |
| **合计** | **17 个文件串行** | **6.34s** |

数据量仅：douyin DWD 19,469 行 / DWS 13,643 行，其余平台 <2,000 行，ADS 509 行。**小数据量仍然慢**，热点在 douyin 202 的链式 CTE：`REGEXP_SPLIT_TO_TABLE` 拆码 + 每组件 `LATERAL` 子查询在 `dim_company_product_code_mapping` 上做正则匹配并 `ORDER BY ... LIMIT 1`（202 文件第 130-171 行），映射候选逐行匹配是主要成本。

### 1.3 连带问题

- **长事务持锁**：6.3s 的写事务内包含 `TRUNCATE`（ACCESS EXCLUSIVE），期间所有读 DWS/ADS 的请求被阻塞或读到旧快照；频繁小操作还会放大事务膨胀。
- **每次点击都在 DROP/CREATE 表**：9 个 CREATE 文件虽只占 0.05s，但每次写操作都重建表结构，存在锁竞争与依赖风险。
- **前端叠加**：`reload()`（product-category.js）串行执行 `refreshMetadata()` → `loadActiveView()` → `toast()`，写操作返回后还要等 2 个串行请求才给用户反馈。
- **放大效应**：若用户连续操作（改映射→看效果→再改），每次都是 6.3s 全量重算。

---

## 二、达播商务归属"停用"提示"接口不存在"

### 2.1 结论

**不是运行进程过期，是聚合服务适配层缺少路由**。重启/进程清理均无法解决。

- 前端请求：`POST /api/influencer/influencers/toggle-status`（`apiPrefix = /api/influencer` + `/influencers/toggle-status`）
- 聚合服务 `apps/fund_split_adjust/server.py`（8770）把 `/api/influencer/*` 交给 `apps/fund_split_adjust/influencer_module.py` 的 `dispatch()`（第 50 行）
- `dispatch()` 中 **没有** `/influencers/toggle-status` 路由（POST 仅有 businesses/assignments/targets/product-*，达人状态只有 `DELETE /influencers`）→ 返回 None → 落入聚合服务兜底分支返回 `接口不存在`
- 独立版 `apps/influencer_config/server.py` 的 do_POST 有该分支（提交 66846da8），但聚合服务不走这条路径

### 2.2 已执行

- 关闭了双进程（PID 460 用户重启的 8770/8101 实例、PID 23040 codex 环境 8771 旧实例），端口已释放，由用户自行重启。
- 注意：补上路由后，`toggle_influencer_status` 会触发 `ASSIGNMENT_REFRESH_FILES`（tmall 282 + 174/175/176 三个 ADS 刷新，实测 ~0.1s），属于可接受范围，但应按本报告第三节方案统一治理。

---

## 三、全项目同类问题排查

扫描所有 `apps/**/*.py` 中 `execute(read_text(...))` 及写后刷新模式：

| 位置 | 触发 | 实测耗时 | 严重度 |
|---|---|---|---|
| `influencer_config/product_category.py` **14 处**（分类/产品/目录的增删改与状态切换） | 每次 HTTP 写操作，事务内全链路重算（17 个 SQL） | **6.34s** | 🔴 严重 |
| `influencer_config/server.py` **7 处**（create/update/delete_business、save_assignment、delete_influencer、toggle_influencer_status、save_target） | 每次 HTTP 写操作，事务内执行 174/175/176（+tmall 282）ADS 刷新 | ~0.1s | 🟡 中等（模式相同，数据量小暂不痛，随数据增长恶化） |
| `fund_split_adjust/database.py:104` `migrate()` | 仅启动一次性 | — | 🟢 无 |
| `file_ingest/service.py:155` `migrate()` | 仅启动一次性 | — | 🟢 无 |
| `identity_access/module.py:46`、`dashboard_center/module.py:33` | 仅启动一次性 | — | 🟢 无 |
| `dashboard_center/proxy.py` | DataEase 嵌入代理，ADS 只读 | — | 🟢 架构正确 |

**共性模式**：业务配置表（dim）写操作与"指标表全量重算"（DWS/ADS 层）在同一 HTTP 请求、同一事务内同步完成。指标全量重算是分钟级批处理任务，被错误地放进了秒级交互路径。

---

## 四、优化方案与处理意见

### 4.1 短期（半天内，收益最大，风险低）

1. **把刷新移出写事务**：业务写先 commit，刷新在独立连接/独立事务中执行。响应立刻返回（<100ms），ADS 在后台几秒后一致。
   - 实现：`_refresh_dashboard` 改为在事务提交后调用，或在服务内维护单线程后台队列（配置变更频率极低，单线程足够）。
2. **7 平台刷新并行化**：`ThreadPoolExecutor(max_workers=7)` 并行执行 7 个平台 REFRESH，6.3s → ~1.8s；再叠加异步化则完全脱离用户链路。
3. **前端优化**：`reload()` 改为 `Promise.all([refreshMetadata(), loadActiveView()])` 并行，且 toast 先于列表刷新显示；连续操作期间用 loading 态。

### 4.2 中期（1-2 天）

4. **去抖合并**：后台刷新队列按"距上次刷新 >10s 或队列积压"合并，连续小操作只触发一次全量重算。
5. **只刷受影响平台**：映射/产品变更只影响发生变更的平台（如改 douyin 映射只跑 202），其余平台 DWS 不动；ADS 从 DWS 全量重算（0.12s）成本可接受。
6. **SQL 热点优化**：douyin 202 的 LATERAL 映射匹配（第 130-171 行）加 `UPPER(code_pattern)` 表达式索引 + 候选集预过滤；`source_component_count` 等窗口可下推。目标 douyin 1.72s → <0.3s。

### 4.3 长期（架构）

7. **配置变更 → 事件 → 异步重算**：统一提供"指标重算服务"（复用现有 SQL 文件，幂等全量刷新），所有配置写操作只发事件；DataEase 侧保持只读 ADS。
8. **达播模块同治理**：`influencer_module.py` 补 `POST /influencers/toggle-status` 路由（同时提交），`server.py` 的 7 处刷新按同样异步化改造。
9. **可观测性**：刷新任务加日志（各层行数、耗时、汇总值），与 AGENTS.md 测试规范一致。

### 4.4 处理优先级

| 优先级 | 事项 | 预期效果 |
|---|---|---|
| P0 | 补 `influencer_module.py` toggle-status 路由 | 解决"接口不存在" |
| P0 | 商品品类刷新移出事务 + 后台队列 | 5s+ → <200ms |
| P1 | 7 平台并行 + 前端 Promise.all | 进一步降延迟、反馈即时 |
| P1 | 达人模块 7 处刷新异步化 | 消除同类隐患 |
| P2 | SQL 热点优化、去抖、受影响平台精准刷新 | 后端负载与延迟最优 |

---

## 五、验证方式（对齐 AGENTS.md 测试规范）

- 每次优化后：`pytest` 全量回归（现有 32 passed / 9 skipped 基线）。
- 写操作响应时间：curl 计时 ≤300ms；后台刷新任务日志输出 DWS/ADS 行数与汇总值。
- ADS 一致性：后台刷新完成后 `ads` 汇总与 DataEase 指标卡一致（既有断言逻辑复用）。
- 事务边界验证：写事务内无 `TRUNCATE`/长时间 DML（通过日志或 `pg_stat_activity` 检查）。
