"""多平台店铺发现；只接受业务账号，保留 profile 与入库店铺的明确映射。"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from .douyin_reviews import shared_modules
from .review_errors import ContractError

PLATFORMS = {
    "douyin": {"name": "抖音", "prefix": "DY-抖音-", "home": "https://fxg.jinritemai.com/ffa/mshop/homepage/index", "domains": ("jinritemai.com",), "score": True},
    "jd": {"name": "京东", "prefix": "JD-京东-", "home": "https://shop.jd.com/jdm/home", "domains": ("jd.com",), "score": False},
    "kuaishou": {"name": "快手", "prefix": "KS-快手-", "home": "https://s.kwaixiaodian.com/zone/home", "domains": ("kwaixiaodian.com", "kuaishou.com",), "score": False},
    "tmall": {"name": "天猫", "exact": "TMALL-天猫-MOCK旗舰店", "home": "https://myseller.taobao.com/home.htm", "domains": ("taobao.com", "tmall.com"), "score": True},
    "pinduoduo": {"name": "拼多多", "prefix": "PDD-拼多多-", "home": "https://mms.pinduoduo.com/home", "domains": ("pinduoduo.com",), "score": True},
    "xiaohongshu": {"name": "小红书", "exact": "XHS-小红书-MOCK旗舰店", "home": "https://ark.xiaohongshu.com/app-system/home", "domains": ("xiaohongshu.com",), "score": False},
}


def platform_key(value: str) -> str:
    for key, spec in PLATFORMS.items():
        if value in (key, spec["name"]):
            return key
    raise ContractError("不支持的平台；当前范围为抖音、京东、快手、天猫、拼多多、小红书")


def discover(raw: list[dict]) -> list[dict]:
    profiles = []
    for item in raw:
        name = str(item.get("name") or "")
        found = [(key, spec) for key, spec in PLATFORMS.items()
                 if name == spec.get("exact") or spec.get("prefix") and name.startswith(spec["prefix"])]
        if not found:
            continue
        key, spec = found[0]
        note = str(item.get("note") or "")
        fields = dict(re.findall(r"(?:^|[;；\n])\s*(platform|company|shop)\s*=\s*([^;；\n]*)", note))
        shop = fields.get("shop", "").strip()
        closed = name == "DY-抖音-MOCK吉饮咖啡专卖店" or bool(re.search(r"已关店|已闭店|已停业", note))
        mismatch = fields.get("platform", "").strip() not in ("", spec["name"])
        profiles.append({"profile_id": str(item["id"]), "profile_name": name, "platform": key,
                         "company": fields.get("company", "").strip(), "expected_shop_name": shop,
                         "excluded": int(closed or mismatch), "exclusion_reason": "备注平台与账号类型不一致" if mismatch else "已关店" if closed else ""})
    if len({p["profile_name"] for p in profiles}) != len(profiles) or len({p["profile_id"] for p in profiles}) != len(profiles):
        raise ContractError("Cloak Login 存在重复 profile，请先核对账号")
    return sorted(profiles, key=lambda p: (p["platform"], p["profile_name"]))


def list_profiles() -> list[dict]:
    Client, *_ = shared_modules()
    client = Client(os.environ.get("CLOAK_MCP_URL", "http://127.0.0.1:19610/mcp"), 25)
    client.initialize()
    data = client.call("list_profiles", {})
    if isinstance(data, dict):
        data = data.get("profiles", data.get("items", data.get("result")))
    if not isinstance(data, list):
        raise ContractError("Cloak Login 店铺清单结构异常")
    return discover(data)


def sync_profiles(db, profiles: list[dict], shops: list[dict], *, preserve_mapping=False):
    from .collection_accounts import initialize_accounts
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_schema'").fetchone():
        initialize_accounts(db)
    allowed = {(s["platform"], s["name"]): s for s in shops}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db:
        # 同步中消失的账号停止采集，历史任务和指标仍保留。
        db.execute("UPDATE metric_profiles SET excluded=1,exclusion_reason='本次同步未发现 profile'")
        for p in profiles:
            previous = db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (p["profile_id"],)).fetchone()
            mapped = previous["shop_name"] if previous else p["expected_shop_name"]
            spec = allowed.get((PLATFORMS[p["platform"]]["name"], mapped), {})
            if preserve_mapping and previous:
                spec = {"score": previous["score_enabled"], "reception": previous["reception_enabled"]}
            if not spec:
                mapped = ""
            closed = p["exclusion_reason"] == "已关店"
            disabled = previous["disabled"] if previous and previous["availability_configured"] else int(closed)
            configured = int(closed or bool(previous and previous["availability_configured"]))
            db.execute("""INSERT INTO metric_profiles(profile_id,profile_name,platform,company,expected_shop_name,shop_name,
                score_enabled,reception_enabled,excluded,exclusion_reason,last_seen_at,review_enabled,disabled,availability_configured) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET profile_name=excluded.profile_name,platform=excluded.platform,
                company=excluded.company,expected_shop_name=excluded.expected_shop_name,shop_name=excluded.shop_name,
                score_enabled=excluded.score_enabled,reception_enabled=excluded.reception_enabled,
                excluded=excluded.excluded,exclusion_reason=excluded.exclusion_reason,last_seen_at=excluded.last_seen_at,
                review_enabled=excluded.review_enabled,disabled=excluded.disabled,availability_configured=excluded.availability_configured""",
                (p["profile_id"], p["profile_name"], p["platform"], p["company"], p["expected_shop_name"], mapped,
                 int(bool(spec.get("score"))), int(bool(spec.get("reception"))), int(bool(p["excluded"]) and not closed), "" if closed else p["exclusion_reason"], stamp,
                 int(p["platform"] == "douyin" and p["profile_name"].startswith("DY-抖音")), disabled, configured))
        duplicate = db.execute("SELECT 1 FROM metric_profiles WHERE excluded=0 AND disabled=0 AND shop_name<>'' GROUP BY platform,shop_name HAVING COUNT(*)>1 LIMIT 1").fetchone()
        if duplicate:
            raise ContractError("多个业务 profile 指向同一入库店铺，请先核对备注，未更新原有配置")


def choose_profile(db, identifier: str) -> dict:
    rows = db.execute("SELECT * FROM metric_profiles WHERE profile_id=? OR profile_name=?", (identifier, identifier)).fetchall()
    if len(rows) != 1 or rows[0]["excluded"] or rows[0]["disabled"]:
        raise ContractError("店铺不存在、已停用、已关店或已移除，请先核对店铺")
    return dict(rows[0])
