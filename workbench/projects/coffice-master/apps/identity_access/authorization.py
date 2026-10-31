from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class AuthenticationError(PermissionError):
    http_status = 401


class RateLimitError(AuthenticationError):
    http_status = 429

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class AuthorizationError(PermissionError):
    http_status = 403


FINANCE_PAGE_PERMISSIONS = {
    "overview": "finance_budget.overview.view",
    "gsv": "finance_budget.gsv.view",
    "promotion": "finance_budget.promotion.view",
    "adjustment": "finance_budget.adjustment.view",
    "recharge": "finance_budget.recharge.view",
    "spend": "finance_budget.spend.view",
    "marketing": "finance_budget.marketing.view",
    "expense_type": "finance_budget.expense_type.view",
}
FINANCE_PAGE_PERMISSION_CODES = tuple(FINANCE_PAGE_PERMISSIONS.values())
FINANCE_ACTION_PERMISSIONS = {
    "gsv_total": "finance_budget.gsv_total.manage",
    "gsv_detail": "finance_budget.gsv_detail.manage",
    "promotion_total": "finance_budget.promotion_total.manage",
    "shop_budget": "finance_budget.shop_budget.manage",
    "promotion_recharge": "finance_budget.promotion_recharge.manage",
    "marketing_budget": "finance_budget.marketing_budget.manage",
    "marketing_expense": "finance_budget.marketing_expense.manage",
    "expense_type": "finance_budget.expense_type.manage",
}
FINANCE_ACTION_PAGE_PERMISSIONS = {
    "gsv_total": "gsv",
    "gsv_detail": "gsv",
    "promotion_total": "promotion",
    "shop_budget": "promotion",
    "promotion_recharge": "recharge",
    "marketing_budget": "marketing",
    "marketing_expense": "marketing",
    "expense_type": "expense_type",
}
FINANCE_READ_PERMISSIONS = {
    "summary": FINANCE_PAGE_PERMISSION_CODES,
    "budgets": (FINANCE_PAGE_PERMISSIONS["overview"], FINANCE_PAGE_PERMISSIONS["gsv"], FINANCE_PAGE_PERMISSIONS["promotion"], FINANCE_PAGE_PERMISSIONS["marketing"]),
    "shop-plans": (FINANCE_PAGE_PERMISSIONS["gsv"], FINANCE_PAGE_PERMISSIONS["promotion"]),
    "gsv-targets": (FINANCE_PAGE_PERMISSIONS["gsv"],),
    "shop-budgets": (FINANCE_PAGE_PERMISSIONS["promotion"],),
    "recharges": (FINANCE_PAGE_PERMISSIONS["recharge"],),
    "adjustments": (FINANCE_PAGE_PERMISSIONS["adjustment"],),
    "promotion-spend": (FINANCE_PAGE_PERMISSIONS["spend"],),
    "marketing-expenses": (FINANCE_PAGE_PERMISSIONS["marketing"],),
    "marketing-budget-history": (FINANCE_PAGE_PERMISSIONS["adjustment"],),
    "expense-types": (FINANCE_PAGE_PERMISSIONS["expense_type"], FINANCE_PAGE_PERMISSIONS["marketing"]),
}
FINANCE_RESOURCE_ACTIONS = {
    "budgets": ("gsv_total", "promotion_total", "marketing_budget"),
    "shop-plans": ("gsv_detail", "shop_budget"),
    "gsv-targets": ("gsv_detail",),
    "shop-budgets": ("shop_budget",),
    "recharges": ("promotion_recharge",),
    "marketing-expenses": ("marketing_expense",),
    "expense-types": ("expense_type",),
}


@dataclass(slots=True)
class AuthContext:
    user_id: int
    username: str
    display_name: str
    department_id: int | None
    department_name: str | None
    is_super_admin: bool
    session_token_hash: str
    csrf_token_hash: str
    permissions: set[str] = field(default_factory=set)
    permission_sources: dict[str, str] = field(default_factory=dict)

    def can(self, code: str | None) -> bool:
        return code is None or self.is_super_admin or code in self.permissions

    def public_user(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "department_id": self.department_id,
            "department_name": self.department_name,
            "is_super_admin": self.is_super_admin,
        }


def required_permission(method: str, path: str) -> str | tuple[str, ...] | None:
    """集中维护业务接口权限，避免授权判断散落在各服务实现中。"""
    method = method.upper()
    if path in {"/api/health", "/api/navigation", "/api/auth/me"}:
        return None
    if path.startswith("/api/auth/"):
        return None
    if path.startswith("/api/automation/verification/"):
        return None
    if path.startswith("/api/automation/"):
        if path in {"/api/automation/report-targets", "/api/automation/report-calendar",
                    "/api/automation/report-day"} or re.fullmatch(r"/api/automation/report-batches/[0-9a-fA-F-]{36}", path):
            return "automation.results.view"
        if path == "/api/automation/report-settings":
            return "automation.results.view" if method == "GET" else "automation.jobs.manage"
        if path in {"/api/automation/report-batches", "/api/automation/report-batches/preview"}:
            return "automation.runs.execute"
        if path in {"/api/automation/workbench", "/api/automation/health", "/api/automation/runtime-resources"}:
            return "automation.workbench.view"
        if path == "/api/automation/daily-results":
            return "automation.results.view"
        if path == "/api/automation/faults":
            return "automation.runs.view"
        if path == "/api/automation/notification-policy":
            return "automation.jobs.view" if method == "GET" else "automation.jobs.manage"
        if path == "/api/automation/components":
            return "automation.flows.view"
        if re.fullmatch(r"/api/automation/components/runs/[0-9a-fA-F-]{36}/repair-context", path):
            return "automation.runs.view"
        if path == "/api/automation/flows":
            return "automation.flows.view" if method == "GET" else "automation.flows.manage"
        if re.fullmatch(r"/api/automation/flows/[0-9a-fA-F-]{36}", path):
            return "automation.flows.view" if method == "GET" else "automation.flows.manage"
        if re.fullmatch(r"/api/automation/flows/[0-9a-fA-F-]{36}/versions", path):
            return "automation.flows.view"
        if re.fullmatch(r"/api/automation/flows/[0-9a-fA-F-]{36}/versions/\d+/rollback", path):
            return "automation.flows.manage"
        if re.fullmatch(r"/api/automation/flows/[0-9a-fA-F-]{36}/(publish|enabled)", path):
            return "automation.flows.manage"
        if re.fullmatch(r"/api/automation/flows/[0-9a-fA-F-]{36}/(run|test-run)", path):
            return "automation.flows.execute"
        if re.fullmatch(r"/api/automation/jobs/\d+/run", path):
            return "automation.runs.execute"
        if re.fullmatch(r"/api/automation/runs/[0-9a-fA-F-]{36}/acknowledge", path):
            return "automation.runs.retry"
        if re.fullmatch(r"/api/automation/runs/[0-9a-fA-F-]{36}/(retry|resume)", path):
            return "automation.runs.retry"
        if re.fullmatch(r"/api/automation/runs/[0-9a-fA-F-]{36}/cancel", path):
            return "automation.runs.execute"
        if path == "/api/automation/jobs" or re.fullmatch(r"/api/automation/jobs/\d+", path):
            return "automation.jobs.view" if method == "GET" else "automation.jobs.manage"
        if path == "/api/automation/runs" or re.fullmatch(r"/api/automation/runs/[0-9a-fA-F-]{36}", path):
            return "automation.runs.view"
        return "automation.workbench.view"
    if path.startswith("/api/ai/admin/"):
        return None  # AI管理模块按具体配置对象集中校验管理权限
    if path.startswith("/api/ai/"):
        if path == "/api/ai/chat/stream":
            return "ai.analysis.query"
        return "ai.analysis.view"
    if path.startswith("/api/system/") or path.startswith("/api/dashboards/admin"):
        return None  # 模块内部按管理页面和具体操作再次判断
    if path.startswith("/api/dashboards"):
        return None  # 动态看板权限由dashboard_code对应资源判断

    if path.startswith("/api/influencer/"):
        route = path.removeprefix("/api/influencer")
        if method == "GET" and route in {"/health", "/refresh-status"}:
            return ("influencer.assignments.view", "influencer.targets.view", "influencer.products.view")
        if route.startswith(("/product",)):
            return "influencer.products.view" if method == "GET" else "influencer.products.manage"
        if method == "GET" and route.startswith("/businesses"):
            return ("influencer.assignments.view", "influencer.targets.view")
        if route.startswith("/targets") or route.startswith("/businesses"):
            return "influencer.targets.view" if method == "GET" else "influencer.targets.manage"
        return "influencer.assignments.view" if method == "GET" else "influencer.assignments.manage"

    if path.startswith(("/api/ingest/", "/api/etl/")):
        if path.startswith('/api/ingest/fee-mappings/scene-rules'):
            return 'platform_fee.mappings.view' if method=='GET' else 'platform_fee.mappings.manage'
        if path == "/api/ingest/operating-details":
            return "platform_fee.raw.view"
        if path.startswith("/api/ingest/finance-config/"):
            if method == "GET":
                resource = path.removeprefix("/api/ingest/finance-config/").split("/", 1)[0]
                if resource == "summary":
                    return FINANCE_READ_PERMISSIONS["summary"]
                return FINANCE_READ_PERMISSIONS.get(resource, FINANCE_PAGE_PERMISSION_CODES)
            resource = path.removeprefix("/api/ingest/finance-config/").split("/", 1)[0]
            actions = FINANCE_RESOURCE_ACTIONS.get(resource)
            return tuple(FINANCE_ACTION_PERMISSIONS[action] for action in actions) if actions else FINANCE_PAGE_PERMISSION_CODES
        if "/fee-" in path or "/raw-fees" in path or "/platform-fee" in path:
            if "mapping" in path:
                page = "platform_fee.mappings"
            elif "raw" in path:
                page = "platform_fee.raw"
            else:
                page = "platform_fee.categories"
            if method == "GET" and "fee-mappings" in path:
                return ("platform_fee.mappings.view", "platform_fee.raw.view")
            return f"{page}.view" if method == "GET" else f"{page}.manage"
        if method == "GET" and path in {"/api/ingest/health", "/api/ingest/report-types", "/api/ingest/shops"}:
            return ("ingest.upload.view", "ingest.runs.view", "ingest.etl.view", "ingest.logs.view",
                    "platform_fee.categories.view", "platform_fee.mappings.view", "platform_fee.raw.view",
                    *FINANCE_PAGE_PERMISSION_CODES)
        if path.startswith("/api/etl/"):
            return "ingest.etl.view" if method == "GET" else "ingest.etl.manage"
        if "/logs" in path:
            return "ingest.logs.view"
        if "/runs" in path and method == "GET":
            return "ingest.runs.view"
        return "ingest.upload.view" if method == "GET" else "ingest.upload.manage"

    if path.startswith("/api/import"):
        return ("bank.imports.view", "bank.statement.view") if method == "GET" else "bank.statement.import"
    if path.startswith("/api/operation-logs"):
        return "bank.logs.view"
    if path.startswith("/api/expense-types"):
        return ("bank.types.view", "bank.statement.view") if method == "GET" else "bank.types.manage"
    if path.startswith("/api/account-entries"):
        return ("bank.accounts.view", "bank.statement.view") if method == "GET" else "bank.accounts.manage"
    if path.startswith("/api/statement/"):
        if method == "GET":
            return "bank.statement.view"
        suffix_permissions = (
            (r"/(split|split/cancel|split/add-row|add-split-row)$", "bank.statement.split"),
            (r"/(adjust|adjust-parent|adjust-child|restore|allocate-one-click)$", "bank.statement.adjust"),
            (r"/(batch-assign|remark|summary)$", "bank.statement.assign"),
            (r"/withdraw-submit$", "bank.statement.withdraw"),
            (r"/submit$", "bank.statement.submit"),
        )
        for pattern, permission in suffix_permissions:
            if re.search(pattern, path):
                return permission
        return "bank.statement.view"
    return None
