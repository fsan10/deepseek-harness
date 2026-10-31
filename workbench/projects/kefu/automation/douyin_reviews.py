"""抖店中差评 WebAPI 采集。业务数据只从 JSON 响应读取，不解析评价或订单 DOM。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

CN = timezone(timedelta(hours=8))
ROOT = Path(os.environ.get("MOCK_COFFICE_ROOT", r"D:\fsan10\mock_coffice"))
PREFIX = "DY-抖音"
CLOSED_PROFILE = "DY-抖音-MOCK吉饮咖啡专卖店"
OVERVIEW = "https://fxg.jinritemai.com/ffa/maftersale/comment/review-overview"
DETAILS = "https://fxg.jinritemai.com/ffa/maftersale/comment/review-details"
COMMENT_PATH = "/product/tcomment/commentList"
ORDER_PATH = "/api/order/orderDetail"
SHOP_PATH = "/center/qualification/shop/info"


from .review_errors import ContractError, HumanRequired


def prepare_shared_imports():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # 本项目也有 scripts 包。保留已加载的本地工具，同时开放共享登录模块所在路径。
    import scripts
    shared_path = str(ROOT / "scripts")
    if shared_path not in scripts.__path__:
        scripts.__path__.append(shared_path)


def shared_modules():
    prepare_shared_imports()
    from ReverseAPI.Formal_Script.profile_cdp import CloakMcpClient, resolve_profile_connection
    from scripts.auto_download.playwright.douyin_login import goto_with_douyin_login, DOUYIN_HOME_URL
    return CloakMcpClient, resolve_profile_connection, goto_with_douyin_login, DOUYIN_HOME_URL


def profile_identity(profile: dict) -> dict:
    from .metric_profiles import discover
    profiles = discover([profile])
    if not profiles or profiles[0]["platform"] != "douyin":
        raise ContractError("只允许抖音店铺 profile")
    p = profiles[0]
    return {**p, "platform": "抖音", "shop_name": p["expected_shop_name"]}


def list_profiles() -> list[dict]:
    from .metric_profiles import list_profiles as list_accounts
    return [{**p, "platform": "抖音", "shop_name": p["expected_shop_name"]} for p in list_accounts() if p["platform"] == "douyin"]


def api_query(start: date, end: date, level: str, page: int = 0) -> dict:
    if level not in ("中评", "差评") or start > end:
        raise ContractError("评价等级或时间范围无效")
    return {"status_filter": 0, "content_search": 1, "reply_search": 0, "appeal_search": 0,
            "rank": 2 if level == "中评" else 1, "count_ecology_score_filter": 0,
            "comment_time_from": int(datetime.combine(start, time.min, CN).timestamp()),
            "comment_time_to": int(datetime.combine(end, time(23, 59, 59), CN).timestamp()),
            "page": page, "pageSize": 20, "appid": 1}


def day_windows(start: date, end: date):
    # 小范围查询避免平台隐藏的跨度限制；大范围按不重叠自然月内的 30 天拆分。
    current = start
    while current <= end:
        finish = min(current + timedelta(days=29), end)
        yield current, finish
        current = finish + timedelta(days=1)


KEYWORDS = {
    "口感": ("味道", "口感", "难喝", "不好喝", "太甜", "齁", "很淡", "中药味", "油油"),
    "宣传不符": ("直播", "宣传", "描述", "说的", "欺骗", "效果", "减肥"),
    "赠品": ("赠品", "送", "漏发", "少发"),
    "客服服务": ("客服", "服务", "态度", "欺负"),
    "退款售后": ("退款", "退货", "售后", "退回"),
    "物流发货": ("物流", "快递", "发货", "配送"),
    "包装品质": ("包装", "破损", "质量", "变质", "漏粉", "结块", "过期"),
    "价格": ("价格", "贵", "便宜", "划算", "不值"),
    "回购意愿": ("回购", "再买", "老顾客", "老客户", "不来了"),
}


def normalize_comment(raw: dict, profile: dict, level: str, start: date, end: date) -> dict:
    required = ("id", "order_id", "product_id", "comment_time")
    if any(not raw.get(k) for k in required):
        raise ContractError("评价接口缺少评价ID、订单号、产品ID或时间")
    reviewed = datetime.fromtimestamp(int(raw["comment_time"]), CN)
    actual_level = ((raw.get("tags") or {}).get("rank_info") or {}).get("name")
    if actual_level != level:
        raise ContractError("评价接口返回的等级与请求不一致")
    if not start <= reviewed.date() <= end:
        raise ContractError("评价接口返回了请求范围以外的数据")
    content = str(raw.get("content") or raw.get("orig_content") or "").strip()
    if not content:
        raise ContractError("有内容筛选返回空评价，请检查平台接口契约")
    product = raw.get("product") or {}
    code = str(raw.get("merchant_sku_code") or raw.get("out_sku_id") or product.get("merchant_sku_code") or "").strip()
    tags = (raw.get("tags") or {}).get("negative_tags") or []
    names = [str(t.get("name") or t.get("tag_name") or "") for t in tags if isinstance(t, dict)]
    names += [label for label, words in KEYWORDS.items() if any(word in content for word in words)]
    return {"profile_id": profile["profile_id"], "company": profile["company"], "shop_name": profile["shop_name"],
            "comment_id": str(raw["id"]), "order_id": str(raw["order_id"]), "shop_order_id": str(raw.get("shop_order_id") or raw["order_id"]),
            "reviewed_at": reviewed.strftime("%Y-%m-%d %H:%M:%S"), "review_date": reviewed.date().isoformat(),
            "review_level": level, "content": content, "product_id": str(raw["product_id"]),
            "product_name": str(product.get("name") or ""), "sku_id": str(raw.get("sku_id") or ""),
            "sku_name": str(raw.get("sku") or ""), "product_code": code,
            "code_source": "评价接口" if code else "", "enrichment_status": "complete" if code else "pending",
            "keywords": "、".join(dict.fromkeys(n for n in names if n)),
            "source_status": str((raw.get("status_info") or {}).get("comment_status", raw.get("status", "")))}


def enrich_order(row: dict, body: dict) -> None:
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance((data.get("product") or {}).get("sku"), list):
        raise ContractError("订单详情接口商品结构异常")
    items = data["product"]["sku"]
    # 一个订单可包含赠品；先按商品单ID，再按产品ID与规格匹配，绝不取第一项。
    matched = [item for item in items if str(item.get("sku_order_id")) == row["order_id"] and str(item.get("product_id")) == row["product_id"]]
    if not matched:
        matched = [item for item in items if str(item.get("product_id")) == row["product_id"]]
        if len(matched) > 1:
            matched = [item for item in matched if any(p.get("key") == "sku_spec" and row["sku_name"] and str(p.get("text", "")).startswith(row["sku_name"]) for p in item.get("properties", []))]
    if len(matched) != 1:
        row["enrichment_status"] = "unmatched"
        return
    item = matched[0]
    code = str(item.get("merchant_sku_code") or "").strip()
    for prop in item.get("properties") or []:
        if prop.get("key") == "merchant_sku_code":
            code = re.sub(r"^商家编码\s*[:：]\s*", "", str(prop.get("text") or "")).strip()
    row["product_code"] = "" if code in ("-", "—", "未设置") else code
    row["product_name"] = str(item.get("product_name") or row["product_name"])
    row["code_source"] = "订单详情接口"
    row["enrichment_status"] = "complete" if row["product_code"] else "not_set"


async def collect_window(session, profile: dict, start: date, end: date, level: str, progress: Callable[[str], None]) -> list[dict]:
    rows = []; page_no = 0; total = None; seen = set()
    while True:
        progress(f"{profile['shop_name']} · {level} · {start} 至 {end} · 第 {page_no + 1} 页")
        body = await session.get_json(COMMENT_PATH, api_query(start, end, level, page_no), label="评价明细", expected_codes={0})
        data = body.get("data")
        if not isinstance(data, list) or not isinstance(body.get("total"), int) or body["total"] < 0:
            raise ContractError("评价接口分页结构异常，不能按无数据处理")
        if total is None:
            total = body["total"]
        elif total != body["total"]:
            raise ContractError("采集中评价总数发生变化，请重试该店铺")
        if int(body.get("page", -1)) != page_no:
            raise ContractError("评价接口页码与请求不一致")
        if not data:
            if len(rows) != total:
                raise ContractError("评价接口提前返回空页，采集未完成")
            break
        for raw in data:
            row = normalize_comment(raw, profile, level, start, end)
            if row["comment_id"] in seen:
                raise ContractError("评价接口出现重复分页，停止以免漏采")
            seen.add(row["comment_id"]); rows.append(row)
        if len(rows) >= total:
            if len(rows) != total:
                raise ContractError("评价接口数量与总数不一致")
            break
        page_no += 1
        if page_no >= 1000:
            raise ContractError("单个窗口超过 1000 页，请缩小时间范围")
        await asyncio.sleep(0.35)
    return rows


async def collect_shop(profile: dict, start: date, end: date, progress: Callable[[str], None]) -> list[dict]:
    """独立 HTTP 采集：只读取已保存会话，不连接或启动任何浏览器。"""
    from .review_auth import client_for_profile
    if profile["excluded"]:
        raise ContractError("已关店，禁止采集该 profile")
    if start > end or end >= datetime.now(CN).date():
        raise ContractError("请选择截至昨天的有效日期范围")
    progress(f"{profile['shop_name']} · 正在通过店铺 API 核验登录")
    async with client_for_profile(profile) as session:
        identity = await session.check_identity()
        profile["shop_name"] = identity["shop_name"]
        rows_by_id = {}
        for window_start, window_end in day_windows(start, end):
            for level in ("中评", "差评"):
                for row in await collect_window(session, profile, window_start, window_end, level, progress):
                    rows_by_id[row["comment_id"]] = row
        rows = list(rows_by_id.values())
        order_cache = {}
        for index, row in enumerate(rows):
            if row["product_code"]:
                continue
            progress(f"{profile['shop_name']} · HTTP 补全商品编码 {index + 1}/{len(rows)}")
            order_id = row["shop_order_id"]
            if order_id not in order_cache:
                order_cache[order_id] = await session.get_json(ORDER_PATH, {"order_id": order_id}, label="订单商品信息", expected_codes={0})
            enrich_order(row, order_cache[order_id])
            await asyncio.sleep(0.15)
        return rows
