"""统一指标业务核心；页面、CLI 和 worker 共用，只有认证模块允许浏览器。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .metric_http import MetricHttpSession
from .metric_parsers import (ContractError, NoMetricData, parse_douyin_reception, parse_douyin_score, parse_jd_reception,
                             parse_kuaishou_reception, parse_pdd_reception, parse_pdd_score,
                             parse_tmall_reception, parse_tmall_score, parse_xhs_reception)
from .review_errors import AuthRequired, HumanRequired
from .review_session_store import SessionStore

SOURCE_METRICS = {"douyin": "店铺接待会话量", "jd": "接待量", "kuaishou": "人工会话量",
                  "tmall": "咨询人数", "pinduoduo": "咨询人数(人)", "xiaohongshu": "会话量"}

# 用户确认的同店名称，仅用于本项目身份核对，不改 profile 备注或入库店铺映射。
SHOP_IDENTITY_ALIASES = {("kuaishou", "MOCK禧饮咖啡专卖店"): "MOCK禧饮专卖店"}


def session_store():
    return SessionStore()


def client_for_profile(profile, *, store=None, transport=None):
    store = store or session_store()
    credentials = store.load(profile["profile_id"])
    return MetricHttpSession(profile, credentials, store=store, transport=transport)


async def tmall_account(client):
    token_response = await client.request("https://sycm.taobao.com/csp/api/token/generate.json", codes={200}, label="生意参谋认证")
    token = token_response.get("data")
    if not isinstance(token, dict) or token.get("headerName") != "X-XSRF-TOKEN" or not isinstance(token.get("token"), str):
        raise ContractError("生意参谋认证令牌结构变化")
    headers = {"X-XSRF-TOKEN": token["token"]}
    body = await client.request("https://sycm.taobao.com/csp/api/account/info.json", codes={200}, extra_headers=headers, label="生意参谋店铺身份")
    return body.get("data", {}), headers


async def check_identity(client):
    platform = client.platform
    extra = {}
    if platform == "douyin":
        body = await client.request("https://fxg.jinritemai.com/center/qualification/shop/info", params={"version": 0, "appid": 1, "_bid": "fxg_admin"}, label="抖音店铺身份")
        data = body.get("data", {})
        name, identifier = data.get("shop_name"), data.get("shop_id") or data.get("qual_id")
    elif platform == "pinduoduo":
        body = await client.request("https://mms.pinduoduo.com/janus/api/userinfo", method="POST", payload={}, label="拼多多店铺身份")
        data = body.get("result", {}).get("mall", {})
        name, identifier = data.get("mall_name"), data.get("mall_id")
    elif platform == "jd":
        body = await client.request("https://ddmall.jd.com/user-info.do", label="京东客服登录状态")
        operator = body.get("userName")
        if not isinstance(operator, str) or not operator: raise AuthRequired("京东客服登录失效，请重新登录")
        body = await client.request("https://ddmall.jd.com/mall/api", method="POST", params={"m": "getMallByOperator"},
                                    form={"operator": operator, "m": "getMallByOperator"}, codes={1}, label="京东店铺身份")
        data = body.get("data", {}).get("mall", {})
        name, identifier = data.get("name"), data.get("id")
    elif platform == "kuaishou":
        body = await client.request("https://syt.kwaixiaodian.com/rest/business/analysis/account/info", method="POST", payload={}, label="快手店铺身份")
        data = body.get("data", {}).get("userInfo", {})
        name, identifier = data.get("user_name"), data.get("user_id")
    elif platform == "xiaohongshu":
        body = await client.request("https://ark.xiaohongshu.com/api/edith/seller/info/v2", label="小红书店铺身份")
        data = body.get("data", {})
        name, identifier = data.get("seller_name"), data.get("seller_id")
    elif platform == "tmall":
        body = await client.mtop("mtop.taobao.jdy.resource.shop.info.get", {})
        data = body.get("data", {}).get("result", {})
        name, identifier = data.get("shopName"), data.get("shopId")
        extra = {"account_nick": data.get("nick")}
    else:
        raise ContractError("不支持的平台")
    if not isinstance(name, str) or not name or identifier in (None, ""):
        raise ContractError("平台身份接口缺少店铺名称或稳定标识")
    expected = client.profile.get("expected_shop_name")
    if not expected or SHOP_IDENTITY_ALIASES.get((platform, name), name) != SHOP_IDENTITY_ALIASES.get((platform, expected), expected):
        raise HumanRequired("API 店铺名称与 profile 备注不一致，请在设置中核对店铺身份")
    pinned = client.credentials.get("identity", {})
    if pinned and str(pinned.get("shop_id")) != str(identifier):
        raise HumanRequired("店铺稳定标识已变化，请确认账号后重新登录")
    result = {"profile_id": client.profile["profile_id"], "shop_name": name, "shop_id": str(identifier),
              "state": "valid", "transport": "direct_http", **extra}
    return result


async def fetch_metrics(profile, kind, day=None, *, client=None):
    if client is None:
        async with client_for_profile(profile) as session:
            return await fetch_metrics(profile, kind, day, client=session)
    identity = await check_identity(client)
    platform = profile["platform"]
    if kind == "score":
        if platform == "douyin":
            args = {"params": {"exp_version": "v10"}, "label": "抖音体验分"}
            overview = await client.request("https://fxg.jinritemai.com/governance/shop/experiencescore/getOverviewV10", **args)
            details = await client.request("https://fxg.jinritemai.com/governance/shop/experiencescore/getSubScoreMetricsV10", **args)
            rows = parse_douyin_score(profile, overview, details)
        elif platform == "pinduoduo":
            body = await client.request("https://mms.pinduoduo.com/sydney/api/mallService/getMallServeScoreV2", method="POST", payload={}, label="拼多多体验分")
            rows = parse_pdd_score(profile, body)
        elif platform == "tmall":
            period = await client.mtop("mtop.alibaba.tmall.query.date", {"componentId": "tmallQueryDate", "params": '{"version":"v3"}'})
            dates = period.get("data", {}).get("dataSource", {})
            from .metric_parsers import business_date
            actual_day = business_date(dates.get("endDate"))
            params = json.dumps({"startDate": dates.get("startDate"), "endDate": dates.get("endDate"), "version": "v3"}, separators=(",", ":"))
            overview = await client.mtop("mtop.alibaba.tmall.front.store.index", {"componentId": "tmallStoreIndicators", "gray": True, "params": params})
            details = await client.mtop("mtop.sdx.nps.home.indexsummary", {"updateDate": dates.get("endDate"), "version": "v3"})
            rows = parse_tmall_score(profile, actual_day, overview, details)
        else:
            raise ContractError("该平台没有接入体验分采集，当前支持抖音、天猫、拼多多")
    elif kind == "reception":
        if not isinstance(day, date): raise ContractError("接待量采集需要明确业务日期")
        text = day.isoformat()
        stamp = int(day.strftime("%Y%m%d"))
        if platform == "douyin":
            body = await client.request("https://pigeon.jinritemai.com/backstage/data/shop_data_list_v2", method="POST", params={"_pms": 1},
                                        payload={"is_offline": True, "startDay": stamp, "endDay": stamp, "listType": 0}, label="抖音接待量")
            rows = parse_douyin_reception(profile, body, text)
        elif platform == "pinduoduo":
            body = await client.request("https://mms.pinduoduo.com/desert/stat/mallMonthServiceData", label="拼多多按日咨询人数")
            rows = parse_pdd_reception(profile, body, text)
        elif platform == "jd":
            body = await client.request("https://kf.jd.com/jingmai/T1/queryIndicatorOverview", method="POST", form={"startTime": text, "endTime": text}, label="京东接待量")
            rows = parse_jd_reception(profile, body, text)
        elif platform == "kuaishou":
            previous = (day - timedelta(days=1)).isoformat()
            body = await client.request("https://syt.kwaixiaodian.com/rest/business/gateway/service/data", method="POST",
                payload={"timeRange": "CUSTOMIZED_RANGE", "currentStartDay": text, "currentEndDay": text,
                         "compareStartDay": previous, "compareEndDay": previous, "module": "customerTrend", "selectKeys": ["manualAskSessionCnt"]}, label="快手人工会话量")
            rows = parse_kuaishou_reception(profile, body, text)
        elif platform == "xiaohongshu":
            # 官方日期枚举：1=单日，2=近7日。近7日模式会忽略 date 并返回汇总值。
            body = await client.request("https://ark.xiaohongshu.com/api/edith/butterfly/data", method="POST", params={"type": "sellerCSOverall"},
                payload={"requestBody": {"blockElements": [{"blockKey": "sellerCSOverall", "filterMap": {"dateSelectType": "day", "dateType": 1, "date": text}}]}}, label="小红书会话量")
            rows = parse_xhs_reception(profile, body, text)
        elif platform == "tmall":
            account, headers = await tmall_account(client)
            # 淘宝两端可能将子账号后缀 IT 显示为 it。按精确主账号核对所属店铺，
            # 不对 shopName 做大小写转换，不按相似名称匹配店铺。
            owner = str(identity.get("account_nick") or "").partition(":")[0]
            actual_owner = str(account.get("accountNick") or "").partition(":")[0]
            if not owner or actual_owner != owner:
                raise HumanRequired("千牛与生意参谋当前账号不一致，请重新登录确认")
            body = await client.request("https://sycm.taobao.com/csp/api/core/monitor/overview/list", codes={200}, extra_headers=headers,
                params={"dateType": "day", "dateRange": "1d", "startDate": str(stamp), "endDate": str(stamp)}, label="天猫咨询人数")
            rows = parse_tmall_reception(profile, body, text)
        else: raise ContractError("不支持的平台")
    else: raise ContractError("不支持的采集类型")
    if not rows: raise NoMetricData("平台未提供可入库指标")
    return {"identity": identity, "records": rows, "report_date": rows[0]["reportDate"],
            "source_metric": SOURCE_METRICS[platform] if kind == "reception" else "店铺体验分及分项",
            "transport": "direct_http"}
