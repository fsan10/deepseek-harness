from __future__ import annotations

from .authorization import FINANCE_PAGE_PERMISSIONS


STATIC_GROUPS = (
    ("ai", "AI 管理", "ai", (
        ("ai.analysis.view", "AI 数据分析", "/ai/"),
        ("ai.model.manage", "模型配置", "/ai-admin/#models"),
        ("ai.datasource.manage", "数据源管理", "/ai-admin/#sources"),
        ("ai.prompt.manage", "提示词模板", "/ai-admin/#prompts"),
        ("ai.feishu_app.manage", "飞书应用配置", "/ai-admin/#feishuApps"),
        ("ai.feishu_app.manage", "验证码转发机器人", "/ai-admin/#verificationRelays"),
        ("ai.feishu_app.manage", "短信转发机器人", "/ai-admin/#smsForwarders"),
        ("ai.audit.view", "AI 会话与审计", "/ai-admin/#audit"),
    )),
    ("bank", "银行资金", "wallet", (
        ("bank.statement.view", "主编辑表", "/#statement"),
        ("bank.types.view", "类型管理", "/#types"),
        ("bank.accounts.view", "入账管理", "/#accounts"),
        ("bank.imports.view", "导入记录", "/#imports"),
        ("bank.logs.view", "操作日志", "/#logs"),
    )),
    ("influencer", "达播运营", "users", (
        ("influencer.assignments.view", "达人商务归属", "/influencer/#assignmentPanel"),
        ("influencer.targets.view", "商务月度目标", "/influencer/#targetPanel"),
        ("influencer.products.view", "商品品类配置", "/influencer/#productCategoryPanel"),
        ("influencer.products.view", "商品编码映射", "/influencer/#productMappingPanel"),
    )),
    ("ingest", "数据导入", "upload", (
        ("ingest.upload.view", "数据上传", "/ingest/#upload"),
        ("ingest.runs.view", "导入记录", "/ingest/#runs"),
        ("ingest.etl.view", "ETL任务", "/ingest/#etl"),
        ("ingest.logs.view", "操作日志", "/ingest/#logs"),
    )),
    ("platform_fee", "经营收支管理", "tags", (
        ("platform_fee.categories.view", "一级分类管理", "/ingest/#feeCategories"),
        ("platform_fee.mappings.view", "平台收支配置", "/ingest/#feeMappings"),
        ("platform_fee.mappings.view", "收支场景清洗规则", "/ingest/#sceneRules"),
        ("platform_fee.raw.view", "全部收支类型", "/ingest/#rawFees"),
    )),
    ("operating_config", "经营配置", "target", (
        (FINANCE_PAGE_PERMISSIONS["overview"], "经营指标总览", "/ingest/#financeOverview"),
        (FINANCE_PAGE_PERMISSIONS["gsv"], "GSV目标管理", "/ingest/#financeGsv"),
        (FINANCE_PAGE_PERMISSIONS["promotion"], "推广预算管理", "/ingest/#financePromotion"),
        (FINANCE_PAGE_PERMISSIONS["adjustment"], "预算调整记录", "/ingest/#financeAdjustments"),
        (FINANCE_PAGE_PERMISSIONS["recharge"], "充值流水", "/ingest/#financeRecharges"),
        (FINANCE_PAGE_PERMISSIONS["spend"], "推广消耗", "/ingest/#financeSpend"),
        (FINANCE_PAGE_PERMISSIONS["marketing"], "营销预算管理", "/ingest/#financeMarketing"),
        (FINANCE_PAGE_PERMISSIONS["expense_type"], "营销费用类型管理", "/ingest/#financeExpenseTypes"),
    )),
    ("automation", "自动化工作台", "automation", (
        ("automation.results.view", "报表任务", "/automation/#reports"),
        ("automation.runs.view", "运行中心", "/automation/#runs"),
        ("automation.jobs.view", "任务调度", "/automation/#schedules"),
        ("automation.flows.view", "流程编排", "/automation/#flow-studio"),
        ("automation.workbench.view", "系统运行", "/automation/#runtime"),
    )),
    ("system", "系统管理", "settings", (
        ("system.platform_shop_company.view", "平台店铺公司映射", "/system/#platformShopCompany"),
        ("system.dashboard.manage", "看板管理", "/system/#dashboards"),
        ("system.user.manage", "用户管理", "/system/#users"),
        ("system.department.manage", "部门管理", "/system/#departments"),
        ("system.role.manage", "角色管理", "/system/#roles"),
        ("system.permission.manage", "权限管理", "/system/#permissions"),
        ("system.audit.view", "审计日志", "/system/#audit"),
    )),
)


def build_navigation(context, dashboard_service) -> dict:
    groups: list[dict] = []
    dashboards = dashboard_service.permitted(context)["items"]
    if dashboards:
        groups.append({
            "code": "dashboard", "name": "经营仪表盘", "icon": "dashboard",
            "items": [{"permission": f"dashboard.view.{item['dashboard_code']}", "name": item["dashboard_name"],
                       "href": f"/dashboards/?code={item['dashboard_code']}"} for item in dashboards],
        })
    for code, name, icon, definitions in STATIC_GROUPS:
        items = [{"permission": permission, "name": label, "href": href}
                 for permission, label, href in definitions if context.can(permission)]
        if items:
            groups.append({"code": code, "name": name, "icon": icon, "items": items})
    return {"user": context.public_user(), "permissions": sorted(context.permissions), "groups": groups}
