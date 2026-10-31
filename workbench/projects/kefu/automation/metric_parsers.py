"""确定性的 JSON → /api/import 记录适配器；不读取 HTML。"""
from __future__ import annotations

import math
import re
from datetime import date

from .metric_profiles import PLATFORMS
from .review_errors import ContractError, ReviewError


class DataNotReady(ReviewError):
    code = "DATA_NOT_READY"
    recoverable = True
    recovery_action = "等待平台更新后重试该日期"


class NoMetricData(ReviewError):
    code = "NO_DATA"


def business_date(value) -> str:
    text = str(value or "")
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text): raise ValueError()
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ContractError("平台未返回有效业务日期，禁止用采集时间替代") from None


def number(value, *, integer=False):
    if isinstance(value, bool) or value is None or not isinstance(value, (str, int, float)):
        raise ContractError("平台指标缺失或类型异常，不能写入为 0")
    raw = str(value).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", raw):
        raise ContractError("平台指标不是有效数值")
    value = float(raw)
    if not math.isfinite(value) or value < 0 or integer and not value.is_integer():
        raise ContractError("平台指标超出有效范围")
    return int(value) if integer else value


def record(profile, day, name, category, value, unit="分", note=""):
    if not profile.get("shop_name"):
        raise ContractError("该 profile 尚未映射到数据台店铺，请先设置明确映射")
    return {"reportDate": business_date(day), "platform": PLATFORMS[profile["platform"]]["name"],
            "shopName": profile["shop_name"], "shopKind": "own", "metricName": name, "metricCategory": category,
            "unit": unit, "value": value, "source": "商家WebAPI", "note": note}


def reception(profile, day, value, source_metric):
    return [record(profile, day, "接待量", "运营", number(value, integer=True), "单", "来源口径：" + source_metric)]


def dated_row(rows, day, field):
    if not isinstance(rows, list): raise ContractError("平台按日列表结构变化")
    matches = [r for r in rows if isinstance(r, dict) and business_date(r.get(field)) == day]
    if not matches: raise DataNotReady("平台未返回该日期的数据，保留未完成状态")
    if len(matches) != 1: raise ContractError("平台同一业务日期返回重复记录")
    return matches[0]


def parse_douyin_reception(profile, body, day):
    data = body.get("data")
    if not isinstance(data, dict): raise ContractError("抖音接待量结构变化")
    row = dated_row(data.get("list"), day, "date")
    value = row.get("shop_serv_conv_cnt")
    if not isinstance(value, dict): raise ContractError("抖音缺少店铺接待会话量")
    return reception(profile, day, value.get("value"), "店铺接待会话量")


def parse_jd_reception(profile, body, day):
    row = dated_row(body.get("trend"), day, "sdate")
    return reception(profile, day, row.get("receiveNum"), "接待量")


def parse_kuaishou_reception(profile, body, day):
    rows = body.get("data")
    if not isinstance(rows, list): raise ContractError("快手趋势数据结构变化")
    metric_rows = [r for r in rows if isinstance(r, dict) and r.get("category") == "人工会话量"]
    row = dated_row(metric_rows, day, "sourceDate")
    value = row.get("value")
    if not isinstance(value, dict): raise ContractError("快手缺少人工会话量")
    return reception(profile, day, value.get("sourceValue"), "人工会话量")


def parse_pdd_reception(profile, body, day):
    # 月度接口提供逐日日期证据，不能把聚合或实时接口的值冒充指定日期。
    row = dated_row(body.get("result"), day, "statDate")
    return reception(profile, day, row.get("consultUserCnt"), "咨询人数(人)")


def parse_xhs_reception(profile, body, day):
    blocks = body.get("data")
    if not isinstance(blocks, list): raise ContractError("小红书统计块结构变化")
    blocks = [b for b in blocks if isinstance(b, dict) and b.get("blockKey") == "sellerCSOverall"]
    if len(blocks) != 1: raise ContractError("小红书客服统计块缺失或重复")
    block = blocks[0]
    actual = business_date(block.get("statisticsDate"))
    if actual != day: raise ContractError(f"小红书接口返回日期与请求不一致（请求 {day}，返回 {actual}）")
    rows = block.get("data")
    if not isinstance(rows, list) or len(rows) != 1: raise ContractError("小红书客服统计行缺失或重复")
    row = rows[0]
    if business_date(row.get("dtm", {}).get("value")) != day: raise ContractError("小红书指标日期不一致")
    value = row.get("caseCnt", {}).get("value")
    if value is None: raise DataNotReady("小红书尚未提供该日期的会话量")
    return reception(profile, day, value, "会话量")


def parse_tmall_reception(profile, body, day):
    rows = body.get("data", {}).get("data")
    if not isinstance(rows, list): raise ContractError("天猫咨询人数结构变化")
    matches = [r for r in rows if isinstance(r, dict) and r.get("key") == "cstUv1d" and r.get("name") == "咨询人数"]
    if len(matches) != 1: raise ContractError("天猫咨询人数指标缺失或重复")
    metric = matches[0]
    if metric.get("delay") is not False: raise DataNotReady("生意参谋咨询人数尚未更新")
    # 此接口不回显业务日期，由已验证的 startDate=endDate 请求与来源审计共同记录。
    return reception(profile, day, metric.get("value"), "咨询人数")


def parse_douyin_score(profile, overview, details):
    data = overview.get("data", {})
    detail = details.get("data", {})
    if not isinstance(data, dict) or not isinstance(detail, dict): raise ContractError("抖音体验分结构变化")
    if data.get("has_data") is False or detail.get("has_data") is False: raise NoMetricData("平台明确返回暂无体验分")
    day = business_date(data.get("done_info", {}).get("done_date"))
    if day != business_date(detail.get("done_info", {}).get("done_date")): raise ContractError("抖音总分和分项的业务日期不一致")
    if detail.get("shop_name") != profile["expected_shop_name"]: raise ContractError("抖音体验分所属店铺与认证店铺不一致")
    scores = data.get("formal_score_info", {})
    rows = [record(profile, day, name, "总览", number(scores.get(key, {}).get("score"))) for key, name in (
        ("experience_score", "店铺体验分"), ("goods_score", "商品体验分"), ("logistics_score", "物流体验分"), ("service_score", "服务体验分"))]
    rows.append(record(profile, day, "近30天有效订单", "总览", number(detail.get("shop_order_latest_30_cnt"), integer=True), "单"))
    info = detail.get("formal_score_metric_info", {})
    groups = {g["sub_score_node"]: g["sub_score_name"] for g in info.get("shop_sub_score", []) if isinstance(g, dict) and "sub_score_node" in g and "sub_score_name" in g}
    metrics = info.get("metrics")
    if not isinstance(metrics, list) or not metrics: raise ContractError("抖音分项指标列表缺失")
    seen = set()
    for m in metrics:
        node = m.get("node_id")
        name = m.get("title")
        value = m.get("value", {})
        if not isinstance(node, int) or not isinstance(name, str) or not name or node // 100 not in groups:
            raise ContractError("抖音分项所属分组或指标名称异常")
        if node in seen: raise ContractError("抖音分项指标重复")
        seen.add(node)
        figure = value.get("value_figure")
        # 抖音 V10 用 -9999 表示分项暂无数据（页面显示“—”），不能当成 0 或真实负数。
        if figure is None or figure in (-9999, "-9999"): continue
        units = {0: "项", 2: "%", 3: "小时", 4: "分", 6: "秒", 7: "单", 9: "单", 10: "次"}
        kind = value.get("value_type")
        if kind not in units: raise ContractError("抖音新增了未知指标单位，请核对后接入")
        try:
            numeric = number(figure)
        except ContractError as exc:
            raise ContractError(f"抖音分项指标「{name}」数值异常：{exc}") from None
        actual = f"{numeric * 100:.10g}%" if kind == 2 else numeric
        rows.append(record(profile, day, name, groups[node // 100], actual, units[kind]))
    return rows


def parse_pdd_score(profile, body):
    data = body.get("result")
    if not isinstance(data, dict): raise ContractError("拼多多体验分结构变化")
    day = business_date(data.get("readyDate"))
    rows = [record(profile, day, name, "总览", number(data.get(key))) for key, name in (
        ("cstmrServScore", "消费者服务体验分"), ("attiLmScore", "服务态度体验分"), ("jcfwLmScore", "基础服务体验分"),
        ("spLmScore", "商品服务体验分"), ("fhLmScore", "发货服务体验分"), ("wlLmScore", "物流服务体验分"))]
    rank = number(data.get("cstmrServRank"))
    if rank > 1: raise ContractError("拼多多同行排名超出有效范围")
    # 与平台 10% 档位一致；整档边界属于前一档，首尾档保留完整区间。
    upper = max(10, min(100, math.ceil(rank * 10) * 10))
    rows.append(record(profile, day, "本店铺体验分在同行排名", "总览", f"{upper - 10}%-{upper}%", "区间"))
    return rows


def parse_tmall_score(profile, day, overview, details):
    day = business_date(day)
    data = overview.get("data", {})
    if data.get("resSuccess") is not True: raise ContractError("天猫体验分总览失败")
    source = data.get("dataSource", {})
    cards = source.get("list")
    if not isinstance(cards, list): raise ContractError("天猫体验分卡片结构变化")
    labels = {"nps": "店铺体验分", "newGoods": "宝贝质量分", "newLogistics": "物流速度分", "newServices": "服务体验分"}
    rows = []
    for key, name in labels.items():
        matching = [m for m in cards if isinstance(m, dict) and m.get("code") == key]
        if len(matching) != 1: raise ContractError("天猫体验分卡片缺失或重复")
        rows.append(record(profile, day, name, "总览", number(matching[0].get("score"))))
    rows.append(record(profile, day, "近30天有效订单", "总览", number(source.get("validOrderCount"), integer=True), "单"))
    groups = details.get("data", {}).get("data", {}).get("mainIndexInfoList")
    if not isinstance(groups, list) or not groups: raise ContractError("天猫体验分明细结构变化")
    for group in groups:
        category = {"newGoods": "宝贝质量", "newLogistics": "物流速度", "newServices": "服务体验"}.get(group.get("code"))
        if not category: continue
        metrics = group.get("subIndexInfoList")
        if not isinstance(metrics, list) or not metrics: raise ContractError("天猫体验分明细组缺失")
        for m in metrics:
            if not isinstance(m.get("name"), str) or not m["name"]: raise ContractError("天猫明细指标缺少名称")
            if m.get("value") in (None, "", "-", "--"): continue
            raw = number(m["value"])
            show = str(m.get("showValue", ""))
            unit = m.get("unit") or ("%" if "%" in show else "小时" if "小时" in show else "秒" if "秒" in show else "")
            if not unit: raise ContractError("天猫明细指标单位缺失，需要核对接口")
            value = f"{raw * 100:.10g}%" if unit == "%" else raw
            rows.append(record(profile, day, m["name"], category, value, unit))
    return rows
