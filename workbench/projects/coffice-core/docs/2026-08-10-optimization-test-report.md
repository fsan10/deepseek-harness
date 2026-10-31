# 达播运营配置台优化验证测试报告

- 日期：2026-08-10
- 被测对象：用户按 `docs/2026-08-10-performance-analysis.md` 建议实施的改动
- 测试方式：黑盒 API 测试（登录态会话 + CSRF）+ 数据库一致性校验 + 全量 pytest + 前端语法检查
- 测试期间未修改任何项目代码

## 1. 被测改动范围（git status 确认）

| 文件 | 改动 |
|---|---|
| `apps/influencer_config/refresh_queue.py`（新增） | `CoalescingRefreshWorker`：单线程后台刷新、去抖 0.2~0.25s、revision 计数、失败保留可观测 |
| `apps/influencer_config/product_category.py` | 14 处写操作由事务内同步全量刷新改为提交后入队后台刷新 |
| `apps/influencer_config/server.py` | 达人商务 7 处写操作同样异步化；新增 `refresh_status()`/`wait_for_refresh()`/`close(drain)` |
| `apps/fund_split_adjust/influencer_module.py` | 补齐 `POST /influencers/toggle-status` 路由；新增 `GET /refresh-status` |
| `apps/fund_split_adjust/server.py` | 启动/退出时对刷新队列 drain 关闭；版本 r21 |
| `apps/influencer_config/static/product-category.js` | reload 改为 `Promise.all` 并行 + 先反馈 toast |
| `apps/influencer_config/tests/`（新增） | refresh_queue 单元测试（3 项） |

## 2. 测试结果总览

- **pytest：61 passed / 9 skipped**（基线 32 passed / 9 skipped，新增 29 项全过）
- **前端语法：node --check 通过**
- **运行时 API 测试：14/14 通过**

## 3. 关键性能对比（实测）

| 操作 | 优化前 | 优化后 | 提升 |
|---|---|---|---|
| 商品品类停用/恢复（PUT status） | 6.34s（事务内全量重算） | **62~82ms**（提交后入队） | ~100x |
| 达播商务归属停用（toggle-status） | 404 接口不存在 | **60~80ms**，200 | 修复 |
| 达人指标后台刷新（174/175/176+tmall282） | 同步 ~0.1s | 后台 0.11~0.14s | 移出请求链路 |
| 商品看板后台刷新（17 个 SQL） | — | 后台 6.1~6.3s 完成 | 用户无感知 |

后台刷新完成时 `last_result` 确认 7 平台全部刷新（douyin/wechat_channels/jd/ks/xhs/pdd/tmall），ADS 行数 325/89/21。

## 4. 功能验证明细

1. **toggle-status 路由**（原"接口不存在"）：`POST /api/influencer/influencers/toggle-status` 停用 → 200，状态 True→False 生效；恢复 → 200，状态还原 ✓
2. **商品品类停用**：PUT `/product-catalog/34/status` → 200，`dashboard_refresh` 返回队列快照（queued）；`row_active` True→False 生效；恢复后还原 ✓
3. **数据一致性**：刷新完成后 7 平台 DWS 分配金额合计与 `ads.ads_operating_sales_product_company_shop_daily` 的 gmv_amount 合计**逐平台完全一致**（douyin 1,567,842.00 等全部相等）✓
4. **去抖合并**：3 次并发变更（burst 0.08s）→ 后台排空 13.1s（约 2 次运行；3 次独立运行需 ~19.5s），`requested_revision == completed_revision == 22`（**无请求丢失**），3 请求均 200 ✓
5. **可观测性**：`GET /refresh-status` 暴露两队列状态/rev/耗时/错误；health 接口含队列状态 ✓
6. **刷新期间不阻塞**：后台刷新 running 期间，其他写请求 64~82ms 正常完成 ✓

## 5. 数据现场与测试痕迹清理

- 测试用临时超管账号（`perf_*`）已全部删除（含崩溃残留 7 个，审计/登录记录同步清理，剩余 0）
- 数据状态已还原：tmall/3333333 `is_active=True`、mapping 34 与 product 均 `is_active=True`
- 未启动任何服务进程（被测服务为用户自行启动的 PID 22268，保持运行）

## 6. 发现的问题与备注

1. **无功能性缺陷**。唯一注意点：并发变更若发生在一次 6.2s 刷新进行中，会触发一次"跟进刷新"（与 `test_refresh_queue.py` 语义一致），连续快速操作仍可能产生串行多次后台重算——当前去抖只合并空闲窗口内的请求。属设计取舍，非 bug；如需更强合并可后续把"刷新中到达"改为 mark-dirty 合并（超出本次范围）。
2. 商品品类后台全量刷新本身仍需 6.2s（受 douyin 202 的 LATERAL 正则映射匹配限制），报告中的 P2 优化（表达式索引、受影响平台精准刷新）尚未实施，可作为后续项。
3. `completed_revision` 语义为"已完成的最高请求号"，与运行次数不等价（测试中以排空耗时判定合并效果）。

## 7. 结论

**全部优化目标达成，14/14 运行时测试通过：**
- "接口不存在"已修复（路由补齐，60~80ms）
- 商品品类操作由 5s+ 降至 ~70ms，全量重算转入后台并保持 ADS 一致性
- 刷新去抖合并有效、无请求丢失、状态可观测
- 单元测试与前端语法全部通过，无回归
