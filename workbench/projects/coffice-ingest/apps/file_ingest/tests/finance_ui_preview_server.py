from __future__ import annotations

import json
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "file_ingest" / "static"
ASSETS = {
    "/ingest/": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/ingest/ingest.css": (STATIC / "ingest.css", "text/css; charset=utf-8"),
    "/ingest/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
    "/styles.css": (ROOT / "apps" / "fund_split_adjust" / "static" / "styles.css", "text/css; charset=utf-8"),
    "/identity-assets/shell.css": (ROOT / "apps" / "identity_access" / "static" / "shell.css", "text/css; charset=utf-8"),
    "/identity-assets/shell.js": (ROOT / "apps" / "identity_access" / "static" / "shell.js", "text/javascript; charset=utf-8"),
}

SHOPS = [
    {"platform_code": "douyin", "platform_name": "抖音", "company_code": "zhouyi", "company_name": "舟益生物科技（南京）有限公司", "shop_code": "dy-coffee", "shop_name": "MOCK咖啡旗舰店"},
    {"platform_code": "tmall", "platform_name": "天猫", "company_code": "moka", "company_name": "墨客咖啡生物科技有限公司", "shop_code": "tmall-flag", "shop_name": "MOCK旗舰店"},
    {"platform_code": "jd", "platform_name": "京东", "company_code": "moka", "company_name": "墨客咖啡生物科技有限公司", "shop_code": "jd-drink", "shop_name": "MOCK饮品旗舰店"},
    {"platform_code": "pdd", "platform_name": "拼多多", "company_code": "jinguo", "company_name": "津果日记生物科技有限公司", "shop_code": "pdd-light", "shop_name": "养颜轻食"},
]

FINANCE_EXPENSE_TYPES = [
    {"expense_type_id": 1, "expense_type_code": "celebrity_cooperation", "expense_type_name": "明星合作", "remark": "明星或达人合作费用", "is_active": True, "created_by": "系统", "updated_by": "系统", "created_at": "2026-08-01T09:00:00+08:00", "updated_at": "2026-08-01T09:00:00+08:00"},
    {"expense_type_id": 2, "expense_type_code": "talent_cooperation", "expense_type_name": "达人合作", "remark": "达人、主播或内容创作者合作费用", "is_active": True, "created_by": "系统", "updated_by": "系统", "created_at": "2026-08-01T09:00:00+08:00", "updated_at": "2026-08-01T09:00:00+08:00"},
    {"expense_type_id": 3, "expense_type_code": "advertising_cooperation", "expense_type_name": "广告合作", "remark": "广告投放及内容合作费用", "is_active": True, "created_by": "系统", "updated_by": "系统", "created_at": "2026-08-01T09:00:00+08:00", "updated_at": "2026-08-01T09:00:00+08:00"},
    {"expense_type_id": 4, "expense_type_code": "event_sponsorship", "expense_type_name": "活动赞助", "remark": "活动赞助、展位及物料费用", "is_active": True, "created_by": "系统", "updated_by": "系统", "created_at": "2026-08-01T09:00:00+08:00", "updated_at": "2026-08-01T09:00:00+08:00"},
]

RESOURCE_ITEMS = {
    "budgets": [{"budget_month": "2026-08-01", "gsv_target_amount": 6_700_000, "promotion_budget_amount": 1_200_000, "marketing_budget_amount": 500_000, "remark": "8月经营预算", "updated_by": "财务专员", "updated_at": "2026-08-18T10:00:00+08:00"}],
    "shop-plans": [
        {"shop_plan_id": 1, "budget_month": "2026-08-01", **SHOPS[0], "promotion_budget_amount": 350_000, "gsv_target_amount": 2_500_000, "updated_at": "2026-08-18T10:00:00+08:00"},
        {"shop_plan_id": 2, "budget_month": "2026-08-01", **SHOPS[1], "promotion_budget_amount": 270_000, "gsv_target_amount": 2_200_000, "updated_at": "2026-08-18T10:00:00+08:00"},
        {"shop_plan_id": 3, "budget_month": "2026-08-01", **SHOPS[2], "promotion_budget_amount": 120_000, "gsv_target_amount": 1_200_000, "updated_at": "2026-08-18T10:00:00+08:00"},
        {"shop_plan_id": 4, "budget_month": "2026-08-01", **SHOPS[3], "promotion_budget_amount": 50_000, "gsv_target_amount": 800_000, "updated_at": "2026-08-18T10:00:00+08:00"},
    ],
    "recharges": [
        {"recharge_id": 1, "recharge_date": "2026-08-05", **SHOPS[0], "recharge_amount": 400_000, "document_no": "CZ-2026-0801", "remark": "月初充值", "updated_at": "2026-08-05T09:00:00+08:00"},
        {"recharge_id": 2, "recharge_date": "2026-08-08", **SHOPS[1], "recharge_amount": 290_000, "document_no": "CZ-2026-0802", "remark": "追加充值", "updated_at": "2026-08-08T09:00:00+08:00"},
    ],
    "adjustments": [
        {"adjustment_id": 1, "budget_month": "2026-08-01", "adjustment_date": "2026-08-06", "adjustment_amount": 250_000, "approval_status": "approved", "approval_no": "YS-2026-0801", "reason": "销售增长追加投放", "updated_at": "2026-08-06T12:00:00+08:00"},
        {"adjustment_id": 2, "budget_month": "2026-08-01", "adjustment_date": "2026-08-12", "adjustment_amount": -50_000, "approval_status": "approved", "approval_no": "YS-2026-0802", "reason": "调整低效渠道", "updated_at": "2026-08-12T12:00:00+08:00"},
    ],
    "marketing-expenses": [
        {"marketing_expense_id": 1, "expense_date": "2026-08-05", "expense_type": "明星合作", "expense_amount": 150_000, "counterparty": "XX明星工作室", "document_no": "YX-2026-0801", "remark": "品牌代言合作首付款", "updated_at": "2026-08-05T12:00:00+08:00"},
        {"marketing_expense_id": 2, "expense_date": "2026-08-10", "expense_type": "广告合作", "expense_amount": 50_000, "counterparty": "XX综艺植入", "document_no": "YX-2026-0805", "remark": "热门综艺产品植入", "updated_at": "2026-08-10T12:00:00+08:00"},
        {"marketing_expense_id": 3, "expense_date": "2026-08-15", "expense_type": "活动赞助", "expense_amount": 26_000, "counterparty": "上海咖啡文化节", "document_no": "YX-2026-0812", "remark": "展位与物料制作", "updated_at": "2026-08-15T12:00:00+08:00"},
    ],
    "expense-types": FINANCE_EXPENSE_TYPES,
}

RESOURCE_PK = {
    "budgets": "budget_month",
    "shop-plans": "shop_plan_id",
    "recharges": "recharge_id",
    "adjustments": "adjustment_id",
    "marketing-expenses": "marketing_expense_id",
    "expense-types": "expense_type_id",
}

SUMMARY_SHOPS = [
    {**item, "recharge_amount": recharge, "pending_recharge_amount": pending, "over_recharge_amount": over, "actual_gsv_amount": actual, "gsv_completion_rate": rate, "promotion_expense_amount": spend, "promotion_execution_rate": spend / item["promotion_budget_amount"] * 100, "theoretical_account_balance": recharge - spend}
    for item, recharge, pending, over, actual, rate, spend in (
        (RESOURCE_ITEMS["shop-plans"][0], 400_000, 0, 50_000, 3_150_000, 126, 320_000),
        (RESOURCE_ITEMS["shop-plans"][1], 290_000, 0, 20_000, 2_310_000, 105, 230_000),
        (RESOURCE_ITEMS["shop-plans"][2], 100_000, 20_000, 0, 1_140_000, 95, 78_000),
        (RESOURCE_ITEMS["shop-plans"][3], 10_000, 40_000, 0, 600_000, 75, 6_200),
    )
]

SUMMARY = {
    "global": {
        "budget_month": "2026-08-01", "gsv_target_amount": 6_700_000,
        "initial_promotion_budget_amount": 1_000_000,
        "approved_adjustment_amount": 200_000, "effective_promotion_budget_amount": 1_200_000,
        "allocated_promotion_budget_amount": 790_000, "unallocated_promotion_budget_amount": 410_000,
        "recharge_amount": 950_000, "pending_recharge_amount": 250_000,
        "marketing_budget_amount": 500_000, "marketing_expense_amount": 226_000,
        "marketing_remaining_amount": 274_000,
    },
    "shops": SUMMARY_SHOPS,
    "actuals": {
        "gsv_target_amount": 6_700_000, "shop_gsv_target_amount": 6_700_000,
        "actual_gsv_amount": 7_200_000, "gsv_completion_rate": 107.46,
        "promotion_expense_amount": 822_000, "promotion_execution_rate": 68.5,
        "marketing_execution_rate": 45.2, "theoretical_account_balance": 128_000,
        "approved_increase_amount": 250_000, "approved_decrease_amount": 50_000,
        "shop_count": 4, "pending_recharge_shop_count": 2, "alert_count": 3,
    },
    "alerts": [
        {"level": "danger", "resource": "recharges", "title": "抖音 · MOCK咖啡旗舰店 超预算充值", "description": "已充值超过店铺预算 50,000.00 元"},
        {"level": "warning", "resource": "recharges", "title": "京东 · MOCK饮品旗舰店 待充值", "description": "当前待充值额度 20,000.00 元"},
        {"level": "info", "resource": "shop-plans", "title": "拼多多 · 养颜轻食 目标进度待关注", "description": "当前 GSV 目标完成率 75.0%"},
    ],
}


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps({"code": 0, "data": data}, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    @staticmethod
    def finance_target(path: str) -> tuple[str, str]:
        prefix = "/api/ingest/finance-config/"
        value = path[len(prefix):] if path.startswith(prefix) else ""
        resource, _, record_id = value.partition("/")
        return resource, record_id

    @staticmethod
    def enrich_shop(item: dict) -> dict:
        shop = next((row for row in SHOPS if row["shop_code"] == item.get("shop_code")), None)
        return {**item, **(shop or {})}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ASSETS:
            path, content_type = ASSETS[parsed.path]
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/ingest/report-types":
            self.send_json({"items": [{"platform_code": shop["platform_code"], "platform_name": shop["platform_name"]} for shop in SHOPS]})
            return
        if parsed.path == "/api/ingest/shops":
            self.send_json({"items": SHOPS})
            return
        if parsed.path == "/api/ingest/fee-categories":
            self.send_json({"items": []})
            return
        if parsed.path in {"/api/health", "/api/ingest/health"}:
            self.send_json({"ready": True, "failed": [], "modules": {"ingest": {"ingest_ready": True}, "worker": {"active_worker_count": 1}}})
            return
        if parsed.path == "/api/ingest/finance-config/summary":
            self.send_json(SUMMARY)
            return
        prefix = "/api/ingest/finance-config/"
        if parsed.path.startswith(prefix):
            resource = parsed.path[len(prefix):]
            if resource in RESOURCE_ITEMS:
                query = parse_qs(parsed.query)
                items = list(RESOURCE_ITEMS[resource])
                month = query.get("budget_month", [""])[0]
                platform = query.get("platform_code", [""])[0]
                company = query.get("company_code", [""])[0]
                shop_code = query.get("shop_code", [""])[0]
                keyword = query.get("keyword", [""])[0].lower()
                status = query.get("approval_status", [""])[0]
                expense_type = query.get("expense_type", [""])[0]
                if month:
                    date_field = {
                        "budgets": "budget_month",
                        "shop-plans": "budget_month",
                        "recharges": "recharge_date",
                        "adjustments": "budget_month",
                        "marketing-expenses": "expense_date",
                    }[resource]
                    items = [item for item in items if str(item.get(date_field, ""))[:7] == month[:7]]
                if platform:
                    items = [item for item in items if item.get("platform_code") == platform]
                if company:
                    items = [item for item in items if item.get("company_code") == company]
                if shop_code:
                    items = [item for item in items if item.get("shop_code") == shop_code]
                if status:
                    items = [item for item in items if item.get("approval_status") == status]
                if expense_type:
                    items = [item for item in items if item.get("expense_type") == expense_type]
                if keyword:
                    items = [item for item in items if keyword in json.dumps(item, ensure_ascii=False).lower()]
                page = int(query.get("page", [1])[0])
                page_size = int(query.get("page_size", [10])[0])
                start = (page - 1) * page_size
                self.send_json({"items": items[start:start + page_size], "pagination": {"total": len(items), "page": page, "page_size": page_size}})
                return
        self.send_json({}, 404)

    def do_POST(self) -> None:
        resource, _ = self.finance_target(urlparse(self.path).path)
        if resource not in RESOURCE_ITEMS:
            self.send_json({}, 404)
            return
        item = self.read_json()
        pk = RESOURCE_PK[resource]
        if resource == "budgets":
            item[pk] = item.get("budget_month")
        else:
            item[pk] = max((int(row.get(pk, 0)) for row in RESOURCE_ITEMS[resource]), default=0) + 1
        if resource == "expense-types":
            item.setdefault("expense_type_code", f"custom_type_{item[pk]}")
            item.setdefault("created_by", "网页用户")
            item.setdefault("updated_by", "网页用户")
            item.setdefault("created_at", datetime.now().astimezone().isoformat())
        item["updated_at"] = datetime.now().astimezone().isoformat()
        item = self.enrich_shop(item)
        RESOURCE_ITEMS[resource].append(item)
        self.send_json(item)

    def do_PUT(self) -> None:
        resource, record_id = self.finance_target(urlparse(self.path).path)
        if resource not in RESOURCE_ITEMS:
            self.send_json({}, 404)
            return
        pk = RESOURCE_PK[resource]
        item = next((row for row in RESOURCE_ITEMS[resource] if str(row.get(pk)) == record_id), None)
        if item is None:
            self.send_json({}, 404)
            return
        item.update(self.read_json())
        item[pk] = record_id if resource == "budgets" else int(record_id)
        item["updated_at"] = datetime.now().astimezone().isoformat()
        item.update(self.enrich_shop(item))
        self.send_json(item)

    def do_DELETE(self) -> None:
        resource, record_id = self.finance_target(urlparse(self.path).path)
        if resource not in RESOURCE_ITEMS:
            self.send_json({}, 404)
            return
        pk = RESOURCE_PK[resource]
        before = len(RESOURCE_ITEMS[resource])
        RESOURCE_ITEMS[resource][:] = [row for row in RESOURCE_ITEMS[resource] if str(row.get(pk)) != record_id]
        self.send_json({"deleted": len(RESOURCE_ITEMS[resource]) < before})


if __name__ == "__main__":
    try:
        ThreadingHTTPServer(("127.0.0.1", 8792), PreviewHandler).serve_forever()
    except KeyboardInterrupt:
        pass
