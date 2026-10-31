from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
import calendar
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOWNLOAD_CONFIG = PROJECT_ROOT / "scripts/auto_download/all_platform_downloads.json"
ARCHIVE_ROOT = Path(r"C:\Users\win\Desktop\data")


@dataclass(frozen=True, slots=True)
class AutomationJobSpec:
    code: str
    job_type: str
    execution_lane: str
    label: str


@dataclass(frozen=True, slots=True)
class AutomationComponentSpec:
    code: str
    name: str
    category: str
    description: str
    timeout_seconds: int = 60
    retryable: bool = True
    config_schema: tuple[dict[str, Any], ...] = ()
    flow_executable: bool = False


def _field(key: str, label: str, field_type: str = "text", default: Any = None, options: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"key": key, "label": label, "type": field_type, "default": default, "options": list(options)}


COMPONENT_REGISTRY: dict[str, AutomationComponentSpec] = {
    "cloak.profile.start": AutomationComponentSpec("cloak.profile.start", "启动 / 复用 Cloak Profile", "system", "启动或复用浏览器 Profile，会话生命周期由总控统一管理。", 60, flow_executable=True),
    "cloak.profile.stop": AutomationComponentSpec("cloak.profile.stop", "关闭 Cloak Profile", "system", "流程成功完成后关闭当前 Profile；失败时默认保留现场。", 30, flow_executable=True),
    "browser.connect.cdp": AutomationComponentSpec("browser.connect.cdp", "连接 CDP Browser", "browser", "连接 Cloak 返回的 CDP endpoint。", 30, flow_executable=True),
    "human.verification.wait": AutomationComponentSpec("human.verification.wait", "等待飞书验证码 / 密码", "human", "创建 Challenge 并等待飞书负责人回复；答案永不写入运行日志。", 300, True, (_field("challenge_type", "类型", "select", "verification_code", ("verification_code", "archive_password")),), flow_executable=True),
    "human.handoff.notice": AutomationComponentSpec("human.handoff.notice", "发送人工接管通知", "human", "用于扫码、滑块等必须由人工完成的页面动作。", 30),
    "report.date_range.set": AutomationComponentSpec("report.date_range.set", "设置业务日期范围", "report", "设置滚动 30 日、业务日或自定义日期范围。", 30, flow_executable=True),
    "report.wait_export_ready": AutomationComponentSpec("report.wait_export_ready", "等待导出任务就绪", "report", "轮询平台导出历史直到目标任务可下载。", 900, flow_executable=True),
    "file.download": AutomationComponentSpec("file.download", "下载报表文件", "file", "捕获浏览器下载事件并保存到工作目录。", 180, flow_executable=True),
    "file.archive.extract": AutomationComponentSpec("file.archive.extract", "解压 / 解密归档", "file", "处理 ZIP、嵌套压缩包和受密码保护文件。", 180, flow_executable=True),
    "report.validate.schema": AutomationComponentSpec(
        "report.validate.schema", "标准报表校验", "file",
        "统一校验入口：根据上游待处理报表声明的 validator 选择对应业务校验规则。",
        60, flow_executable=True,
    ),
    "report.archive": AutomationComponentSpec(
        "report.archive", "标准归档", "file",
        "统一归档组件：消费上游待归档文件，按业务日期、平台、公司、店铺和标准报表名重命名并移动到目标目录。",
        60, True, (_field("report_name", "标准报表名（留空自动取上游）", "text", ""),),
        flow_executable=True,
    ),
    "ingest.submit": AutomationComponentSpec(
        "ingest.submit", "API 上传 / FileIngest", "data",
        "显式把本次 Flow 生成的标准报表提交到 FileIngest 并等待 ODS 导入完成；不会自动触发 ETL。",
        1800, flow_executable=True,
    ),
    "etl.trigger": AutomationComponentSpec(
        "etl.trigger", "触发受影响 ETL", "data",
        "基于上游 FileIngest 的报表类型计算受影响 ETL，并等待本次 ETL 执行完成。",
        3600, flow_executable=True,
    ),
    "jd.ensure_login": AutomationComponentSpec("jd.ensure_login", "京东 · 检查登录态", "report", "确认京东商家后台可用并识别登录失效。", 60, flow_executable=True),
    "jd.order.open_export": AutomationComponentSpec("jd.order.open_export", "京东订单 · 打开导出页", "report", "进入京东订单导出中心。", 60, flow_executable=True),
    "jd.order.create_export": AutomationComponentSpec("jd.order.create_export", "京东订单 · 创建导出", "report", "创建或幂等复用京东订单导出任务。", 90, flow_executable=True),
    "douyin.order.open_page": AutomationComponentSpec("douyin.order.open_page", "抖音订单 · 打开页面", "report", "进入抖店订单管理页。", 60, flow_executable=True),
    "douyin.order.prepare_filters": AutomationComponentSpec("douyin.order.prepare_filters", "抖音订单 · 设置筛选", "report", "准备订单查询筛选条件。", 45, flow_executable=True),
    "douyin.order.query": AutomationComponentSpec("douyin.order.query", "抖音订单 · 查询", "report", "提交订单查询并等待结果。", 60, flow_executable=True),
    "douyin.order.create_export": AutomationComponentSpec("douyin.order.create_export", "抖音订单 · 创建导出", "report", "创建订单导出任务。", 90, flow_executable=True),
    "kuaishou.ensure_login": AutomationComponentSpec("kuaishou.ensure_login", "快手 · 检查登录态", "report", "确认快手小店登录并切换目标店铺。", 120),
    "kuaishou.order.open_page": AutomationComponentSpec("kuaishou.order.open_page", "快手订单 · 打开页面", "report", "进入快手订单管理页。", 60, flow_executable=True),
    "kuaishou.order.query": AutomationComponentSpec("kuaishou.order.query", "快手订单 · 查询", "report", "执行订单查询。", 45, flow_executable=True),
    "kuaishou.order.create_export": AutomationComponentSpec("kuaishou.order.create_export", "快手订单 · 创建导出", "report", "创建快手订单导出任务。", 90, flow_executable=True),
    "tmall.order.open_page": AutomationComponentSpec("tmall.order.open_page", "天猫订单 · 打开页面", "report", "进入天猫订单页面。", 60, flow_executable=True),
    "tmall.order.set_date": AutomationComponentSpec("tmall.order.set_date", "天猫订单 · 设置日期", "report", "设置订单查询日期范围。", 45, flow_executable=True),
    "tmall.order.search": AutomationComponentSpec("tmall.order.search", "天猫订单 · 查询", "report", "提交订单查询。", 60, flow_executable=True),
    "tmall.order.create_export": AutomationComponentSpec("tmall.order.create_export", "天猫订单 · 创建导出", "report", "创建天猫订单导出任务。", 90, flow_executable=True),
    "xhs.order.open_home": AutomationComponentSpec("xhs.order.open_home", "小红书 · 打开工作台", "report", "进入小红书商家工作台并确认登录态。", 60, flow_executable=True),
    "xhs.order.open_management": AutomationComponentSpec("xhs.order.open_management", "小红书订单 · 打开管理页", "report", "进入订单管理页面。", 60, flow_executable=True),
    "xhs.order.set_date": AutomationComponentSpec("xhs.order.set_date", "小红书订单 · 设置日期", "report", "设置近 30 日或使用运行参数中的自定义日期。", 45, flow_executable=True),
    "xhs.order.query": AutomationComponentSpec("xhs.order.query", "小红书订单 · 查询", "report", "执行订单查询。", 60, flow_executable=True),
    "xhs.order.export": AutomationComponentSpec("xhs.order.export", "小红书订单 · 导出", "report", "确认导出提示并直接下载小红书订单 XLSX。", 180, flow_executable=True),
    "pinduoduo.ensure_login": AutomationComponentSpec("pinduoduo.ensure_login", "拼多多 · 检查登录态", "report", "使用保存凭据并通过统一 Challenge 服务处理验证码。", 180),
    "jd.session.ensure_login": AutomationComponentSpec("jd.session.ensure_login", "京东 · 建立登录页面", "browser", "建立已认证京东页面，供资金、结算等报表复用。", 60, flow_executable=True),
    "kuaishou.session.open": AutomationComponentSpec("kuaishou.session.open", "快手 · 建立业务页面", "browser", "在当前 CDP 会话创建快手业务页。", 60),
    "kuaishou.session.ensure_login": AutomationComponentSpec("kuaishou.session.ensure_login", "快手 · 检查登录态", "browser", "检查快手业务页面登录态。", 60),
    "xhs.session.ensure_login": AutomationComponentSpec("xhs.session.ensure_login", "小红书 · 检查登录态", "browser", "检查小红书商家后台登录态。", 60),
    "xhs.report.open": AutomationComponentSpec("xhs.report.open", "小红书 · 打开报表页", "report", "打开资金或结算报表页面并恢复会话。", 60, True, (_field("report_type", "报表类型", "select", "fund", ("fund", "settlement")),), flow_executable=True),
    "xhs.report.mode.select": AutomationComponentSpec("xhs.report.mode.select", "小红书账单 · 选择日/月", "report", "选择日账单或月度汇总单。", 30, True, (_field("mode", "账单周期", "select", "day", ("day", "month")),), flow_executable=True),
    "xhs.report.latest": AutomationComponentSpec("xhs.report.latest", "小红书账单 · 定位最新报表", "report", "定位最新可下载的资金或结算账单。", 60, flow_executable=True),
    "xhs.report.download": AutomationComponentSpec("xhs.report.download", "小红书账单 · 下载", "report", "下载当前定位的资金或结算 XLSX。", 180, flow_executable=True),
    "report.mode.select": AutomationComponentSpec("report.mode.select", "选择日 / 月报表模式", "report", "切换报表日汇总或月汇总模式。", 30),
    "report.latest.locate": AutomationComponentSpec("report.latest.locate", "定位最新可下载报表", "report", "定位最新业务日期对应的可下载行。", 60),
    "tmall.promotion.open": AutomationComponentSpec("tmall.promotion.open", "天猫推广 · 打开阿里妈妈报表", "report", "打开淘宝联盟或万相台推广报表页面。", 120),
    "tmall.promotion.capture_download": AutomationComponentSpec("tmall.promotion.capture_download", "天猫推广 · 触发并捕获下载", "report", "触发推广报表下载并处理下载事件。", 180),
    "douyin.bill.set_date": AutomationComponentSpec("douyin.bill.set_date", "抖音账单 · 设置日期范围", "report", "设置资金/结算账单业务日期范围。", 45, flow_executable=True),
    "douyin.bill.generate": AutomationComponentSpec("douyin.bill.generate", "抖音账单 · 生成批量报表", "report", "提交抖音账单报表生成任务。", 90, flow_executable=True),
    "douyin.bill.wait_ready": AutomationComponentSpec("douyin.bill.wait_ready", "抖音账单 · 等待报表就绪", "report", "轮询历史报表直到可下载。", 900, flow_executable=True),
    "douyin.bill.download": AutomationComponentSpec("douyin.bill.download", "抖音账单 · 下载报表", "report", "下载指定资金或结算账单。", 180, flow_executable=True),
    "qianchuan.finance.open": AutomationComponentSpec("qianchuan.finance.open", "千川 · 打开财务页面", "report", "打开千川财务流水对账页面。", 90, flow_executable=True),
    "qianchuan.daily.open": AutomationComponentSpec("qianchuan.daily.open", "千川 · 打开日结报表", "report", "切换到千川日结报表。", 60, flow_executable=True),
    "qianchuan.daily.wait": AutomationComponentSpec("qianchuan.daily.wait", "千川 · 等待最新日结", "report", "等待最新日结数据出现。", 300, flow_executable=True),
    "jd.settlement.select_mode": AutomationComponentSpec("jd.settlement.select_mode", "京东结算 · 选择日月模式", "report", "选择京东结算日账单或月账单。", 30, flow_executable=True),
    "jd.settlement.locate": AutomationComponentSpec("jd.settlement.locate", "京东结算 · 定位最新账单", "report", "定位最新可下载结算账单。", 60, flow_executable=True),
    "jd.fund.set_date": AutomationComponentSpec("jd.fund.set_date", "京东资金 · 设置日期", "report", "设置京东资金流水查询日期。", 45, flow_executable=True),
    "jd.fund.create_export": AutomationComponentSpec("jd.fund.create_export", "京东资金 · 创建导出任务", "report", "创建京东资金流水导出任务。", 90, flow_executable=True),
    "jd.fund.wait_download": AutomationComponentSpec("jd.fund.wait_download", "京东资金 · 等待并下载", "report", "等待资金导出完成并触发下载。", 900, flow_executable=True),
    "jd.promotion.set_date": AutomationComponentSpec("jd.promotion.set_date", "京东推广费 · 设置日期", "report", "设置京东联盟/京准通推广费日期。", 60, flow_executable=True),
    "jd.promotion.create_export": AutomationComponentSpec("jd.promotion.create_export", "京东推广费 · 创建报表", "report", "创建推广费生成任务。", 90, flow_executable=True),
    "jd.promotion.wait_ready": AutomationComponentSpec("jd.promotion.wait_ready", "京东推广费 · 等待报表", "report", "等待推广费报表生成完成。", 900, flow_executable=True),
    "pinduoduo.session.ensure_login": AutomationComponentSpec("pinduoduo.session.ensure_login", "拼多多 · 检查登录态", "browser", "检查拼多多财务页面登录态。", 60),
    "pinduoduo.order.open": AutomationComponentSpec("pinduoduo.order.open", "拼多多订单 · 打开页面", "report", "进入拼多多订单管理页面。", 60, flow_executable=True),
    "pinduoduo.order.set_date": AutomationComponentSpec("pinduoduo.order.set_date", "拼多多订单 · 设置日期", "report", "设置订单近30日或自定义日期。", 45, flow_executable=True),
    "pinduoduo.order.query": AutomationComponentSpec("pinduoduo.order.query", "拼多多订单 · 查询", "report", "查询订单列表。", 60, flow_executable=True),
    "pinduoduo.order.create_export": AutomationComponentSpec("pinduoduo.order.create_export", "拼多多订单 · 创建导出", "report", "创建订单导出任务。", 90, flow_executable=True),
    "pinduoduo.order.wait_ready": AutomationComponentSpec("pinduoduo.order.wait_ready", "拼多多订单 · 等待导出就绪", "report", "等待匹配日期的订单导出可下载。", 900, flow_executable=True),
    "pinduoduo.settlement.open": AutomationComponentSpec("pinduoduo.settlement.open", "拼多多结算 · 打开对账中心", "report", "进入拼多多结算对账中心。", 60, flow_executable=True),
    "pinduoduo.settlement.set_date": AutomationComponentSpec("pinduoduo.settlement.set_date", "拼多多结算 · 设置日期", "report", "设置结算查询日期范围。", 45, flow_executable=True),
    "pinduoduo.settlement.create_export": AutomationComponentSpec("pinduoduo.settlement.create_export", "拼多多结算 · 创建导出", "report", "创建结算导出任务。", 90, flow_executable=True),
    "pinduoduo.settlement.wait_ready": AutomationComponentSpec("pinduoduo.settlement.wait_ready", "拼多多结算 · 等待导出就绪", "report", "等待结算导出历史卡片可下载。", 900, flow_executable=True),
    "pinduoduo.promotion.open": AutomationComponentSpec("pinduoduo.promotion.open", "拼多多推广费 · 打开报表页", "report", "进入推广账户现金支出明细页面。", 90, flow_executable=True),
    "pinduoduo.promotion.set_date": AutomationComponentSpec("pinduoduo.promotion.set_date", "拼多多推广费 · 设置日期", "report", "设置推广费查询日期范围。", 45, flow_executable=True),
    "pinduoduo.promotion.apply_filters": AutomationComponentSpec("pinduoduo.promotion.apply_filters", "拼多多推广费 · 设置筛选", "report", "设置资金类型、流水类型等筛选。", 45, flow_executable=True),
    "pinduoduo.promotion.query": AutomationComponentSpec("pinduoduo.promotion.query", "拼多多推广费 · 查询", "report", "查询推广账户支出记录。", 90, flow_executable=True),
    "kuaishou.fund.locate_bill": AutomationComponentSpec("kuaishou.fund.locate_bill", "快手资金 · 定位最新账单", "report", "定位最新日/月资金账单。", 60, flow_executable=True),
    "kuaishou.fund.wait_ready": AutomationComponentSpec("kuaishou.fund.wait_ready", "快手资金 · 等待导出记录", "report", "在导出记录中等待资金账单。", 900, flow_executable=True),
    "kuaishou.settlement.set_date": AutomationComponentSpec("kuaishou.settlement.set_date", "快手结算 · 设置日期", "report", "设置结算查询日期范围。", 45, flow_executable=True),
    "kuaishou.settlement.create_export": AutomationComponentSpec("kuaishou.settlement.create_export", "快手结算 · 创建导出", "report", "创建快手结算导出任务。", 90, flow_executable=True),
    "kuaishou.settlement.wait_ready": AutomationComponentSpec("kuaishou.settlement.wait_ready", "快手结算 · 等待导出记录", "report", "等待结算导出记录可下载。", 900, flow_executable=True),
    "tmall.aggregate_fund.select_mode": AutomationComponentSpec("tmall.aggregate_fund.select_mode", "天猫聚合资金 · 选择日月模式", "report", "切换聚合账户资金日/月汇总。", 30, flow_executable=True),
    "tmall.aggregate_fund.locate": AutomationComponentSpec("tmall.aggregate_fund.locate", "天猫聚合资金 · 定位最新账单", "report", "定位最新可下载聚合资金报表。", 60, flow_executable=True),
    "tmall.session.open": AutomationComponentSpec("tmall.session.open", "天猫 · 获取业务页面", "browser", "从当前 CDP 会话获取天猫业务页。", 60, flow_executable=True),
    "tmall.alipay.open_account": AutomationComponentSpec("tmall.alipay.open_account", "天猫支付宝资金 · 打开账户信息", "report", "进入店铺账户信息。", 60, flow_executable=True),
    "tmall.alipay.open_page": AutomationComponentSpec("tmall.alipay.open_page", "天猫支付宝资金 · 打开支付宝", "report", "跳转已绑定支付宝账户。", 90, flow_executable=True),
    "tmall.alipay.open_bill": AutomationComponentSpec("tmall.alipay.open_bill", "天猫支付宝资金 · 打开账单下载", "report", "进入支付宝资金账单下载页面。", 90, flow_executable=True),
    "tmall.alipay.select_mode": AutomationComponentSpec("tmall.alipay.select_mode", "天猫支付宝资金 · 选择日月模式", "report", "选择日账单或月账单。", 30, flow_executable=True),
    "tmall.alipay.wait_ready": AutomationComponentSpec("tmall.alipay.wait_ready", "天猫支付宝资金 · 等待账单", "report", "等待第一条可下载资金账单。", 300, flow_executable=True),
    "tmall.union.select_period": AutomationComponentSpec("tmall.union.select_period", "淘宝联盟推广费 · 选择周期", "report", "选择昨日或月度推广费周期。", 45, flow_executable=True),
    "tmall.union.download": AutomationComponentSpec("tmall.union.download", "淘宝联盟推广费 · 下载报表", "report", "生成或复用历史任务并下载联盟推广费。", 300, flow_executable=True),
    "tmall.wanxiangtai.download": AutomationComponentSpec("tmall.wanxiangtai.download", "万相台推广费 · 下载报表", "report", "下载万相台推广费明细。", 180, flow_executable=True),

    # 平台原子适配节点：直接调用现有 Playwright 函数，不复制浏览器业务逻辑。
    "douyin.order.wait_ready": AutomationComponentSpec("douyin.order.wait_ready", "抖音订单 · 等待导出就绪", "report", "进入导出记录并等待当前日期范围报表可下载。", 900, flow_executable=True),
    "douyin.order.download_verify": AutomationComponentSpec("douyin.order.download_verify", "抖音订单 · 下载 / 验证码", "human", "触发订单 ZIP 下载；平台要求时通过统一 Challenge 完成短信验证码。", 900, flow_executable=True),
    "douyin.order.extract": AutomationComponentSpec("douyin.order.extract", "抖音订单 · 解压 / 文件密码", "file", "解压订单 ZIP；加密时通过统一 Challenge 获取解压密码。", 300, flow_executable=True),
    "douyin.bill.open": AutomationComponentSpec("douyin.bill.open", "抖音账单 · 打开报表页", "report", "打开资金或结算日/月账单页面。", 90, True, (_field("report", "报表类型", "select", "资金", ("资金", "结算")), _field("mode", "周期", "select", "day", ("day", "month"))), flow_executable=True),
    "qianchuan.daily.materialize": AutomationComponentSpec("qianchuan.daily.materialize", "千川 · 生成 CSV 文件", "file", "把网页实时日结表头和最新记录写成标准 CSV 临时文件。", 30, flow_executable=True),
    "jd.settlement.download": AutomationComponentSpec("jd.settlement.download", "京东结算 · 下载明细", "file", "下载当前定位的结算账单 ZIP/文件。", 180, flow_executable=True),
    "jd.settlement.extract": AutomationComponentSpec("jd.settlement.extract", "京东结算 · 提取报表", "file", "从结算下载文件中提取标准 CSV。", 120, flow_executable=True),
    "jd.fund.extract": AutomationComponentSpec("jd.fund.extract", "京东资金 · 提取报表", "file", "处理资金下载文件并得到标准明细文件。", 120, flow_executable=True),
    "jd.promotion.open": AutomationComponentSpec("jd.promotion.open", "京东推广费 · 打开报表", "report", "打开京东联盟或京准通推广费页面。", 90, True, (_field("report_key", "报表", "select", "union", ("union", "tong")),), flow_executable=True),
    "jd.promotion.download": AutomationComponentSpec("jd.promotion.download", "京东推广费 · 下载报表", "file", "下载当前推广费生成任务。", 180, flow_executable=True),
    "pinduoduo.order.download": AutomationComponentSpec("pinduoduo.order.download", "拼多多订单 · 下载报表", "file", "下载当前日期范围的订单报表。", 180, flow_executable=True),
    "pinduoduo.settlement.download": AutomationComponentSpec("pinduoduo.settlement.download", "拼多多结算 · 下载账单", "file", "下载当前结算导出记录。", 180, flow_executable=True),
    "pinduoduo.settlement.extract": AutomationComponentSpec("pinduoduo.settlement.extract", "拼多多结算 · 提取 CSV", "file", "从结算 ZIP 中提取唯一 CSV 并准备校验。", 120, flow_executable=True),
    "pinduoduo.promotion.download": AutomationComponentSpec("pinduoduo.promotion.download", "拼多多推广费 · 下载明细", "file", "下载筛选后的现金支出明细。", 180, flow_executable=True),
    "kuaishou.order.set_date": AutomationComponentSpec("kuaishou.order.set_date", "快手订单 · 设置日期", "report", "设置最近一个月或运行参数指定日期范围。", 60, flow_executable=True),
    "kuaishou.order.wait_ready": AutomationComponentSpec("kuaishou.order.wait_ready", "快手订单 · 等待导出就绪", "report", "等待匹配日期范围的订单导出记录。", 900, flow_executable=True),
    "kuaishou.order.download_password": AutomationComponentSpec("kuaishou.order.download_password", "快手订单 · 提取码 / 下载", "human", "获取订单文件提取码并下载加密 XLSX。", 600, flow_executable=True),
    "kuaishou.order.decrypt": AutomationComponentSpec("kuaishou.order.decrypt", "快手订单 · 解密 / 校验", "file", "使用提取码解密 XLSX 并校验表结构。", 180, flow_executable=True),
    "kuaishou.fund.open": AutomationComponentSpec("kuaishou.fund.open", "快手资金 · 打开账单页", "report", "打开资金账单页、确认登录并执行查询。", 90, True, (_field("mode", "周期", "select", "day", ("day", "month")),), flow_executable=True),
    "kuaishou.fund.create_export": AutomationComponentSpec("kuaishou.fund.create_export", "快手资金 · 导出账单", "report", "对当前资金账单发起导出。", 90, flow_executable=True),
    "kuaishou.fund.download": AutomationComponentSpec("kuaishou.fund.download", "快手资金 · 下载账单", "file", "下载已就绪的资金导出记录。", 180, flow_executable=True),
    "kuaishou.fund.extract": AutomationComponentSpec("kuaishou.fund.extract", "快手资金 · 提取报表", "file", "提取资金 CSV/XLSX 标准文件。", 120, flow_executable=True),
    "kuaishou.settlement.open": AutomationComponentSpec("kuaishou.settlement.open", "快手结算 · 打开账单页", "report", "打开结算账单页面并确认登录。", 90, flow_executable=True),
    "kuaishou.settlement.download": AutomationComponentSpec("kuaishou.settlement.download", "快手结算 · 下载账单", "file", "下载当前结算导出记录。", 180, flow_executable=True),
    "kuaishou.settlement.extract": AutomationComponentSpec("kuaishou.settlement.extract", "快手结算 · 提取报表", "file", "从结算下载文件中提取 XLSX/CSV。", 120, flow_executable=True),
    "tmall.order.wait_ready": AutomationComponentSpec("tmall.order.wait_ready", "天猫订单 · 等待导出就绪", "report", "等待宝贝销售明细生成可下载。", 900, flow_executable=True),
    "tmall.order.download": AutomationComponentSpec("tmall.order.download", "天猫订单 · 下载报表", "file", "下载宝贝销售明细 Excel。", 180, flow_executable=True),
    "tmall.aggregate_fund.open": AutomationComponentSpec("tmall.aggregate_fund.open", "天猫聚合资金 · 打开页面", "report", "确认天猫登录并打开聚合账户资金页。", 90, True, (_field("mode", "周期", "select", "day", ("day", "month")),), flow_executable=True),
    "tmall.aggregate_fund.download": AutomationComponentSpec("tmall.aggregate_fund.download", "天猫聚合资金 · 下载明细", "file", "下载当前聚合资金明细。", 180, flow_executable=True),
    "tmall.alipay.download": AutomationComponentSpec("tmall.alipay.download", "天猫支付宝资金 · 下载 ZIP", "file", "下载当前支付宝资金账单 ZIP。", 180, flow_executable=True),
    "tmall.alipay.extract": AutomationComponentSpec("tmall.alipay.extract", "天猫支付宝资金 · 提取明细", "file", "从支付宝 ZIP 中提取账务明细文件。", 120, flow_executable=True),
    "tmall.union.open": AutomationComponentSpec("tmall.union.open", "淘宝联盟推广费 · 打开报表", "report", "打开阿里妈妈淘宝联盟推广报表。", 120, True, (_field("mode", "周期", "select", "day", ("day", "month")),), flow_executable=True),
    "tmall.wanxiangtai.open": AutomationComponentSpec("tmall.wanxiangtai.open", "万相台推广费 · 打开报表", "report", "按日/月周期打开万相台现金明细。", 120, True, (_field("mode", "周期", "select", "day", ("day", "month")),), flow_executable=True),


}


def component_registry_payload() -> list[dict[str, Any]]:
    return [
        {
            "code": spec.code,
            "name": spec.name,
            "category": spec.category,
            "description": spec.description,
            "timeout_seconds": spec.timeout_seconds,
            "retryable": spec.retryable,
            "config_schema": list(spec.config_schema),
            "flow_executable": spec.flow_executable,
        }
        for spec in COMPONENT_REGISTRY.values()
        if spec.flow_executable
    ]


JOB_REGISTRY = {
    "platform_download_backfill": AutomationJobSpec("platform_download_backfill", "platform_download", "interactive", "历史报表补跑"),
    "platform_download_overnight": AutomationJobSpec(
        "platform_download_overnight", "platform_download", "overnight", "平台报表下载 / overnight"
    ),
    "platform_download_interactive": AutomationJobSpec(
        "platform_download_interactive", "platform_download", "interactive", "平台报表下载 / interactive"
    ),
    "full_etl": AutomationJobSpec("full_etl", "full_etl", "etl", "全量 ETL 刷新"),
    "flow_overnight": AutomationJobSpec("flow_overnight", "flow", "overnight", "自定义组件 Flow / overnight"),
    "flow_interactive": AutomationJobSpec("flow_interactive", "flow", "interactive", "自定义组件 Flow / interactive"),
    "flow_etl": AutomationJobSpec("flow_etl", "flow", "etl", "自定义组件 Flow / etl"),
}


def require_job_spec(job_code: str) -> AutomationJobSpec:
    try:
        return JOB_REGISTRY[job_code]
    except KeyError as exc:
        raise ValueError("任务不在 Automation registry 白名单中") from exc


def _arg_value(args: list[str], name: str) -> str | None:
    try:
        index = args.index(name)
    except ValueError:
        return None
    return args[index + 1] if index + 1 < len(args) else None


def business_period(module_name: str, raw_args: list[Any], business_date: date) -> dict[str, str]:
    """Return the explicit business period kept separately from execution timestamps.

    Explicit CLI dates win. Defaults mirror the current controller modules at a
    useful control-plane granularity; the downloaded filename remains the final
    audit source and may later refine these fields.
    """

    args = [str(value) for value in raw_args]
    start = _arg_value(args, "--start-date")
    end = _arg_value(args, "--end-date")
    exact = _arg_value(args, "--date")
    mode = _arg_value(args, "--mode") or ""
    month = _arg_value(args, "--month")
    if month:
        first = date.fromisoformat(month + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        return {"business_date_start": first.isoformat(), "business_date_end": last.isoformat(), "period_type": "month"}
    if start and end:
        return {"business_date_start": start, "business_date_end": end, "period_type": "date_range"}
    if exact:
        return {"business_date_start": exact, "business_date_end": exact, "period_type": "day"}
    if mode == "month":
        first = business_date.replace(day=1)
        previous_end = first - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        return {
            "business_date_start": previous_start.isoformat(),
            "business_date_end": previous_end.isoformat(),
            "period_type": "month",
        }
    if ("order" in module_name and not module_name.startswith("pinduoduo_")) or module_name == "jd_promotion_fee_download":
        days = 30 if module_name != "tmall_order_download" else 31
        return {
            "business_date_start": (business_date - timedelta(days=days - 1)).isoformat(),
            "business_date_end": business_date.isoformat(),
            "period_type": "rolling_30_days",
        }
    yesterday = business_date - timedelta(days=1)
    return {
        "business_date_start": yesterday.isoformat(),
        "business_date_end": yesterday.isoformat(),
        "period_type": "day",
    }


def refine_business_period(artifacts: list[dict[str, Any]], fallback: dict[str, str]) -> dict[str, str]:
    """Prefer the actual archive filename date emitted by formal download scripts."""

    receipts = [a for a in artifacts if a.get("coverage_verified") and a.get("business_date_start") and a.get("business_date_end")]
    if receipts:
        types = {a.get("period_type") for a in receipts}
        return {"business_date_start": min(str(a["business_date_start"]) for a in receipts),
                "business_date_end": max(str(a["business_date_end"]) for a in receipts),
                "period_type": next(iter(types)) if len(types) == 1 else "date_range"}
    days: list[date] = []
    months: list[tuple[int, int]] = []
    for artifact in artifacts:
        name = str(artifact.get("file_name") or "")
        day_match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:_|$)", name)
        if day_match:
            try:
                days.append(date.fromisoformat(day_match.group(1)))
            except ValueError:
                pass
            continue
        month_match = re.match(r"^(\d{4})-(\d{2})(?:_|$)", name)
        if month_match:
            year, month = int(month_match.group(1)), int(month_match.group(2))
            if 1 <= month <= 12:
                months.append((year, month))
    if days:
        return {
            "business_date_start": min(days).isoformat(),
            "business_date_end": max(days).isoformat(),
            "period_type": "day" if len(set(days)) == 1 else "date_range",
        }
    if months:
        starts = [date(year, month, 1) for year, month in months]
        ends = [date(year, month, calendar.monthrange(year, month)[1]) for year, month in months]
        return {"business_date_start": min(starts).isoformat(), "business_date_end": max(ends).isoformat(), "period_type": "month"}
    return dict(fallback)
