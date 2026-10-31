# 客服部数据台（本地局域网版）

这是由每日客服 Excel 报表转换而来的网页 + SQLite 数据库系统。它支持按日期、平台、店铺和指标查看数据，也提供批量导入 API，供 Python、影刀 RPA 等自动化工具使用。

系统完全在本地运行，不依赖 Sites 或其他云端服务。首次启动会自动用 `drizzle/0000_kefu_initial.sql` 创建 `data/kefu.sqlite`，其中包含原 Excel 导入的历史数据。

“差评汇总分析”入口为左侧导航或 `/reviews`。支持抖音中评/差评采集、店铺和评价日期筛选、商品名称/编码/评价内容/订单号/关键词/产品ID搜索，以及按当前筛选条件导出完整 Excel。采集与定时设置、店铺同步和任务进度均在页面内操作。

## 页面

- 分析：经营总览 `/overview`、接待量分析 `/reception`、店铺体验分 `/scores`、差评分析 `/reviews`
- 运营：评价采集 `/reviews/collection`、接待量采集 `/reception/collection`、店铺体验分采集 `/scores/collection`、数据维护 `/data`
- 配置：统一采集设置 `/collection/settings`、店铺配置 `/collection/settings/shops`、数据接入 `/data/import`

分析页以「数据日」为口径，采集页日期不得晚于昨天；日期统一按北京时间解释。总览、筛选与分页状态写入 URL，刷新或分享链接可复现。

首次同步店铺、登录或重新登录时需要 Cloak Login 及本机 `mock_coffice` 的共享登录模块。保存加密会话后，店铺状态检查、评价采集和商品编码补全均通过独立 HTTP WebAPI 完成，可关闭店铺浏览器。登录失效会在页面提示重新登录。默认采集昨天，支持配置采集频率、回溯天数和登录检查间隔。

接待量支持抖音、京东、快手、天猫、拼多多、小红书；体验分支持抖音、天猫、拼多多的总分和分项。正式取数均为独立 HTTP WebAPI，浏览器只用于显式登录与会话提取。采集设置分为四个分区：店铺与范围（登录、启停、逐店与批量设置采集范围）、采集计划（三类采集共用一张计划表）、运行与环境（服务心跳、登录检查间隔、服务日志与运行日志）、通知与异常（统一异常记录与飞书提醒）；体验分使用平台返回的业务日期。

网页与 `scripts/commerce.ps1` 共用采集、认证及任务队列核心。操作说明见 [多平台指标采集](docs/多平台指标采集.md) 和 [差评采集说明](docs/差评汇总分析.md)。

## 快速开始

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1
```

服务器本机打开 `http://localhost:3000`，局域网电脑打开 `http://服务器IP:3000`。

完整说明见 [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md)，自动化导入见 [API_IMPORT.md](API_IMPORT.md)。

首次部署需安装 Python 3.12。一键安装会创建 `.venv` 并安装 `requirements-reviews.txt`。已有 Node 环境只需补装采集器依赖时，可执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-reviews.ps1
```

## 主要目录

- `app/`：页面路由（`app/(console)/`）和 API
- `components/`：共享外壳、UI 组件与图表
- `lib/`：日期、格式化、评价与采集运行逻辑
- `design/`：前端重构原型与日期规范（不参与运行）
- `data/kefu.sqlite`：运行时数据库（首次访问自动生成）
- `drizzle/0000_kefu_initial.sql`：历史数据初始化脚本
- `automation/import_client.py`：Python 批量导入客户端
- `automation/import_template.csv`：导入 CSV 模板
- `scripts/`：Windows 安装和启动脚本
