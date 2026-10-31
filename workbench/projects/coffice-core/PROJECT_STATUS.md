# PROJECT STATUS

> 更新时间：2026-09-10T17:21:31+08:00
> Git：main @ 32d086e8（与 origin/main 同步；工作区 dirty）

## 项目概况

本项目用于快速验证财务经营指标，主链路为 PostgreSQL ODS -> DWD -> DWS -> ADS -> DataEase，公司/店铺归属统一由 DIM 维护。仓库同时包含经营配置、文件导入、IAM、Dashboard、生产库配置同步和多平台报表下载能力。当前阶段重点是把拼多多/小红书订单、推广费、资金和结算下载收敛为“浏览器负责真实登录与动态上下文、WebAPI 负责查询和下载”的混合流程，并完善登录失效通知。

## 当前状态

- 已完成：HEAD 32d086e8 已加入登录态失效通知并优化千川/抖音登录处理；前序提交已落地 PDD WebAPI/抓包基础、平台店铺公司映射管理、全平台下载计划/执行车道、月度结算净额与多平台财务 ETL 能力。
- 进行中：快照写入前工作区有 23 个未提交路径（9 个修改、3 个删除、11 个新增）。改动集中在 ecommerce-webapi-builder 技能及抓包脚本、PDD 订单/推广费/结算 WebAPI 脚本、统一 profile-CDP 解析、新增 XHS 订单/资金/结算 WebAPI 脚本和测试；另有 2 个 PDD XLS/ZIP 下载产物未跟踪。
- 当前阻塞：无。WebAPI 当前改动尚未在真实 Cloak Login profile 和完整下载归档链路完成本阶段验收。

## 关键实现与约定

- ODS 是字段分析与指标计算的唯一事实来源；一个指标独立维护 DWD、DWS、ADS 和刷新 SQL。DWD 只清洗字段，不提前筛选订单/售后状态；平台口径在对应 DWS 完成，ADS 只服务指定图表。
- 公司/店铺关系只维护在 dim.dim_platform_shop_company；ODS 明细通过 batch_id 关联批次店铺上下文，不得按文件名或默认店铺兜底。指标 SQL 不得硬编码公司店铺。
- WebAPI 混合流程必须先复用指定 Cloak Login profile 的真实页面/会话，让浏览器自然产生 Cookie、Origin、Referer、User-Agent 和动态业务头，再由浏览器上下文或 API session 查询/下载；不得把 Cookie、令牌或真实 endpoint 固化到源码、抓包或文档。
- profile 解析应按完整 profile 名称唯一匹配，优先复用同一活动实例的实时 CDP endpoint；profile 重启后 endpoint 可能变化，命令行显式 endpoint 仅作为覆盖。登录态失效、验证码/安全门和店铺选择必须明确报告，不得伪造成功。
- PDD WebAPI 覆盖订单导出、推广费和结算；XHS WebAPI 覆盖订单、资金日/月账单和结算日/月账单。日期范围、业务筛选、报表类型、非空文件、文件格式和归档结果都要分别校验。
- 抓包工具必须按平台规则过滤域名/请求、脱敏 URL/请求体/响应体和敏感头；只保留可复现业务 API 所需上下文。删除或替换抓包样本前先确认没有测试依赖。
- 自动下载以 Cloak Login profile 的 name/note 作为平台、公司、店铺事实来源；用户可见的正式脚本仍遵循共享登录、归档、profile 清理和失败交接流程。
- SQL 按职责放在 sql/<platform>/、sql/ads/、sql/dim/、sql/common/，建表及字段需要完整注释；金额使用 NUMERIC(18,2)，日期使用 DATE。Python 执行统一使用项目 .venv\\Scripts\\python.exe -m ... 并加载项目 .env。

## 关键位置

- ReverseAPI/Formal_Script/profile_cdp.py、xhs_webapi_common.py：统一 Cloak profile/CDP 解析、动态浏览器 API session、XHS 请求头/日期/下载公共逻辑。
- ReverseAPI/Formal_Script/pdd_order_export_download.py、pdd_promotion_fee_webapi_download.py、pdd_settlement_webapi_download.py：PDD 订单导出、推广费和结算 WebAPI 正式脚本。
- ReverseAPI/Formal_Script/xiaohongshu_webapi_download.py 及 xiaohongshu_*_webapi_download.py：XHS 三类报表计划、API 查询、账单选择和文件下载。
- ReverseAPI/Test_Script/：PDD/XHS WebAPI、profile-CDP 和推广费脚本测试；当前包含被标记删除的旧抓包 JSON。
- .codex/skills/ecommerce-webapi-builder/：抓包、脱敏、平台过滤、输入模板和开发流程技能；当前本身有未提交修改。
- scripts/auto_download/playwright/、scripts/auto_download/run_all_platform_downloads.py：原有 DOM/Playwright 正式下载链路、统一计划和失败处理。
- apps/identity_access/、sql/common/420_platform_shop_company_admin_postgres.sql：平台店铺公司映射管理。
- etl/、sql/ads/、sql/xhs/：多平台财务指标、结算净额和费用 ADS 链路。

## 最近变更

- 32d086e8：增加登录态失效通知，优化千川和抖音登录处理。
- 777b2b4f：加入 ecommerce-webapi-builder 技能、PDD WebAPI/抓包基础和测试素材整理。
- d650cc72：增加平台店铺公司映射管理功能。
- 5e5f72e5：重构下载链接识别和执行车道，完善统一下载计划。
- 7a372d7e、1a3d30c5、57daf729：PDD 订单导出、profile 管理/检查点和六平台动态下载配置。
- f97b2651、34d624fd：月度结算净额及多平台财务/自动化流程调整。
- 未提交：23 个路径（9 个修改、3 个删除、11 个新增），另含 2 个未跟踪 PDD 下载文件；本快照文件本身也未提交。

## 下一步

1. 先执行纯逻辑/单元测试与脱敏抓包样本检查，覆盖 profile endpoint 唯一匹配、日期/报表计划、API 错误、安全门、PDD/XHS 文件解析和删除抓包样本的依赖关系；本次 handoff 不代替这些验证。
2. 使用当前有效 Cloak Login profile 做 PDD 订单/推广费/结算和 XHS 订单/资金/结算真实 CDP/API 验收，检查动态请求上下文、业务筛选、日期范围、非空文件、文件格式和归档命名。
3. 核对 ReverseAPI/downloads 下的 PDD XLS/ZIP 是否为测试产物，确认 3 个抓包 JSON 的删除是否有意；不在未确认前删除、覆盖或提交这些文件。
4. 通过正式脚本/技能接入统一下载计划，完成失败交接与登录态失效通知闭环；再按当前改动边界提交，保留其他用户修改。

## 已知问题

- 本次 handoff 只进行了快照、Git 状态/日志和 diff 统计及必要的代码入口检查，未运行测试、构建、服务或真实浏览器下载；当前 WebAPI 改动仍属待验收状态。
- 当前有 3 个已跟踪 PDD 抓包 JSON 被删除，11 个新增路径未跟踪，且包含 2 个二进制下载结果；提交前必须确认样本保留策略、测试依赖和归档策略。
- WebAPI 脚本内的动态 endpoint、登录态、安全门和平台响应字段依赖运行时页面；静态测试或历史抓包不能证明当前 profile、日期和下载接口仍可用。
- 现有正式 Playwright 链路与 ReverseAPI 混合链路尚需明确分工和统一入口，避免重复导出、绕过业务页面入口或在失败时错误报告成功。
