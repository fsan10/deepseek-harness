"""Project-local 影刀 shop-score/reception parser and API payload builder.

Uses only the Python standard library and supports Python 3.7+.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union


class ShopScoreError(ValueError):
    pass


RECEPTION_PLATFORMS = {"抖音", "天猫", "拼多多", "京东", "微信小店", "小红书", "快手"}
REFUND_PLATFORMS = {"抖音"}


@dataclass
class Element:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List[Union["Element", str]] = field(default_factory=list)
    parent: Optional["Element"] = field(default=None, repr=False, compare=False)

    @property
    def class_tokens(self) -> List[str]:
        return self.attrs.get("class", "").split()

    def has_class_prefix(self, prefix: str) -> bool:
        return any(token.startswith(prefix) for token in self.class_tokens)

    def has_class(self, name: str) -> bool:
        return name in self.class_tokens

    def text_content(self) -> str:
        parts: List[str] = []

        def collect(node: Union["Element", str]) -> None:
            if isinstance(node, str):
                parts.append(node)
            else:
                for child in node.children:
                    collect(child)

        collect(self)
        return clean_text("".join(parts))

    def descendants(self, include_self: bool = False) -> Iterable["Element"]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class TolerantDomParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("__root__")
        self.stack: List[Element] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        element = Element(
            tag.lower(),
            {key: (value or "") for key, value in attrs},
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(element)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: List[tuple]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u3000", " ")).strip()


def parse_dom(html: str) -> Element:
    if not isinstance(html, str) or not html.strip():
        raise ShopScoreError("传入的网页元素源代码为空")
    parser = TolerantDomParser()
    parser.feed(html)
    parser.close()
    return parser.root


def find_first(root: Element, class_prefix: str) -> Optional[Element]:
    return next(
        (node for node in root.descendants(include_self=True) if node.has_class_prefix(class_prefix)),
        None,
    )


def find_all(root: Element, class_prefix: str) -> List[Element]:
    return [
        node for node in root.descendants(include_self=True)
        if node.has_class_prefix(class_prefix)
    ]


def direct_child_elements(root: Element, tag: str = "") -> List[Element]:
    return [
        child for child in root.children
        if isinstance(child, Element) and (not tag or child.tag == tag)
    ]


def find_all_by_attr_prefix(root: Element, attr: str, prefix: str) -> List[Element]:
    return [
        node for node in root.descendants(include_self=True)
        if node.attrs.get(attr, "").startswith(prefix)
    ]


def find_exact_text_elements(root: Element, expected: str) -> List[Element]:
    """Return the smallest elements whose visible text exactly matches expected."""

    matches: List[Element] = []
    for node in root.descendants(include_self=True):
        if node.text_content() != expected:
            continue
        if any(child.text_content() == expected for child in direct_child_elements(node)):
            continue
        matches.append(node)
    return matches


TMALL_GROUPS: Sequence[str] = ("宝贝质量", "物流速度", "服务保障")
TMALL_PRIMARY_SCORES: Sequence[str] = ("真实体验分",) + TMALL_GROUPS
TMALL_SECTION_IDS = {
    "newGoods": "宝贝质量",
    "newLogistics": "物流速度",
    "newServices": "服务保障",
}
TMALL_DETAIL_ROW_ID_PREFIX = "metricsNameContainer-"
TMALL_SCORE_PATTERN = re.compile(r"^([0-5](?:\.\d+)?)(?:分)?$")
TMALL_DISPLAY_VALUE_PATTERN = re.compile(
    r"^[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|小时|秒)?$"
)


def recognize_tmall_group(section: Element) -> Optional[str]:
    for node in section.descendants(include_self=True):
        section_id = node.attrs.get("id", "")
        for marker, group_name in TMALL_SECTION_IDS.items():
            if marker in section_id:
                return group_name

    name_node = find_first(section, "PerformanceMetricsTable--name--")
    if not name_node:
        name_node = find_first(section, "name--")
    visible_name = name_node.text_content() if name_node else ""
    if visible_name in TMALL_GROUPS:
        return visible_name
    list_name = find_first(section, "PerformanceMetricsTable--listName--")
    section_id = list_name.attrs.get("id", "") if list_name else ""
    for marker, group_name in TMALL_SECTION_IDS.items():
        if marker in section_id:
            return group_name
    return None


def find_tmall_primary_score(root: Element, metric_name: str) -> str:
    """Pair a primary label with its score inside the nearest local container."""

    for label_node in find_exact_text_elements(root, metric_name):
        current = label_node.parent
        while current is not None:
            other_labels = [
                name for name in TMALL_PRIMARY_SCORES
                if name != metric_name and find_exact_text_elements(current, name)
            ]
            if other_labels:
                break
            for node in current.descendants(include_self=True):
                value = node.text_content()
                match = TMALL_SCORE_PATTERN.fullmatch(value)
                if not match:
                    continue
                if any(
                    child.text_content() == value
                    for child in direct_child_elements(node)
                ):
                    continue
                return match.group(1)
            current = current.parent
    return ""


def nearest_tmall_detail_section(marker: Element) -> Optional[Element]:
    current = marker.parent
    while current is not None:
        if find_all_by_attr_prefix(current, "id", TMALL_DETAIL_ROW_ID_PREFIX):
            return current
        current = current.parent
    return None


def find_tmall_display_value(scope: Element) -> str:
    """Read the displayed value in a semantic row before scales and targets."""

    for node in scope.descendants(include_self=True):
        value = node.text_content()
        if not TMALL_DISPLAY_VALUE_PATTERN.fullmatch(value):
            continue
        if any(
            child.text_content() == value
            for child in direct_child_elements(node)
        ):
            continue
        return value.replace(",", "")
    return ""


def tmall_semantic_sections(root: Element) -> List[tuple]:
    sections: List[tuple] = []
    seen = set()
    for node in root.descendants(include_self=True):
        section_id = node.attrs.get("id", "")
        group_name = next(
            (
                group for marker, group in TMALL_SECTION_IDS.items()
                if marker in section_id
            ),
            None,
        )
        if not group_name:
            continue
        section = nearest_tmall_detail_section(node)
        if section is not None and group_name not in seen:
            sections.append((group_name, section))
            seen.add(group_name)
    return sections


def tmall_detail_rows(section: Element) -> List[tuple]:
    """Return semantic name/value pairs, then fall back to old/new classes."""

    semantic_rows: List[tuple] = []
    for row in find_all_by_attr_prefix(section, "id", TMALL_DETAIL_ROW_ID_PREFIX):
        name = clean_text(row.attrs.get("id", "")[len(TMALL_DETAIL_ROW_ID_PREFIX):])
        row_children = direct_child_elements(row)
        value = find_tmall_display_value(row_children[0] if row_children else row)
        if name and value:
            semantic_rows.append((name, value))
    if semantic_rows:
        return semantic_rows

    rows = find_all(section, "PerformanceMetricsTableList--listItem--")
    if not rows:
        rows = find_all(section, "listItem--")
    class_rows: List[tuple] = []
    for row in rows:
        name_node = find_first(row, "PerformanceMetricsTableList--metricsName--")
        if not name_node:
            name_node = find_first(row, "metricsName--")
        value_node = find_first(row, "RankContainer--rankValue--")
        if not value_node:
            value_node = find_first(row, "rankValue--")
        if name_node and value_node:
            class_rows.append((name_node.text_content(), value_node.text_content()))
    return class_rows


def metric_unit(name: str, value: str, default: str = "分") -> str:
    if value.endswith("小时"):
        return "小时"
    if value.endswith("秒"):
        return "秒"
    if value.endswith("%") or name.endswith("率") or "比例" in name:
        return "%"
    if value.endswith("单") or any(marker in name for marker in ("订单", "数量", "人数", "接待", "咨询")):
        return "单"
    return default


def parse_tmall(source_block1: str, source_block2: str = "") -> Dict[str, object]:
    performance_root = parse_dom(source_block1)
    score_root = parse_dom(source_block2)
    metrics: List[Dict[str, str]] = []

    score_values = {
        name: find_tmall_primary_score(score_root, name)
        for name in TMALL_PRIMARY_SCORES
    }
    first_name = (
        find_first(score_root, "ScoreDetails--firstItemName--")
        or find_first(score_root, "firstItemName--")
    )
    first_score = (
        find_first(score_root, "ScoreDetails--firstItemScore--")
        or find_first(score_root, "firstItemScore--")
    )
    if first_name and first_score and first_name.text_content() in TMALL_PRIMARY_SCORES:
        score_values[first_name.text_content()] = first_score.text_content()
    score_rows = find_all(score_root, "ScoreDetails--item--")
    if not score_rows:
        score_rows = find_all(score_root, "item--")
    for row in score_rows:
        name_node = (
            find_first(row, "ScoreDetails--itemName--")
            or find_first(row, "itemName--")
        )
        score_node = (
            find_first(row, "ScoreDetails--itemScore--")
            or find_first(row, "itemScore--")
        )
        if name_node and score_node and name_node.text_content() in TMALL_PRIMARY_SCORES:
            score_values[name_node.text_content()] = score_node.text_content()

    missing_scores = [name for name in TMALL_PRIMARY_SCORES if not score_values.get(name)]
    if missing_scores:
        raise ShopScoreError("天猫一级指标缺失：" + "、".join(missing_scores))
    for name in TMALL_PRIMARY_SCORES:
        metrics.append({
            "metricName": name,
            "metricCategory": "体验分",
            "unit": "分",
            "value": score_values[name],
        })

    found_groups = set()
    metric_identities = set()
    sections = tmall_semantic_sections(performance_root)
    if len(sections) < len(TMALL_GROUPS):
        fallback_sections = (
            find_all(performance_root, "PerformanceMetricsTable--container--")
            + find_all(performance_root, "listItemContainer--")
        )
        existing_groups = {group for group, _section in sections}
        for section in fallback_sections:
            group_name = recognize_tmall_group(section)
            if group_name and group_name not in existing_groups:
                sections.append((group_name, section))
                existing_groups.add(group_name)

    for group_name, section in sections:
        found_groups.add(group_name)
        for name, value in tmall_detail_rows(section):
            if name and value and value not in {"—", "-", "/"}:
                identity = (group_name, name)
                if identity in metric_identities:
                    continue
                metric_identities.add(identity)
                metrics.append({
                    "metricName": name,
                    "metricCategory": group_name,
                    "unit": metric_unit(name, value),
                    "value": value,
                })

    missing_groups = [name for name in TMALL_GROUPS if name not in found_groups]
    if missing_groups:
        raise ShopScoreError("天猫指标明细分组缺失：" + "、".join(missing_groups))

    date_match = re.search(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", performance_root.text_content())
    if not date_match:
        raise ShopScoreError("天猫源码中未找到 YYYY-MM-DD 数据日期")
    return {"platform": "天猫", "reportDate": date_match.group(0), "metrics": metrics}


def parse_tmall_reception(source_block: str) -> Dict[str, str]:
    root = parse_dom(source_block)
    for group in find_all(root, "index-group-level-1"):
        labels = [node.text_content() for node in find_all(group, "index-label")]
        if "咨询人数" not in labels:
            continue
        for value_container in find_all(group, "index-value"):
            if not value_container.has_class("level-1"):
                continue
            value_node = find_first(value_container, "numbervalue")
            if not value_node:
                continue
            value = value_node.text_content().replace(",", "")
            if re.fullmatch(r"\+?\d+(?:\.\d+)?", value):
                return {
                    "metricName": "咨询人数",
                    "metricCategory": "接待量",
                    "unit": "单",
                    "value": value.lstrip("+"),
                }
    raise ShopScoreError("天猫接待量源码中未找到一级指标“咨询人数”及其数值")


DOUYIN_PRIMARY_SCORES: Sequence[str] = (
    "我的体验分",
    "商品体验得分",
    "物流体验得分",
    "服务体验得分",
)
# Douyin has changed the visible labels on the score overview more than once.
# Keep the old names as the parser's required identities, but accept the labels
# currently rendered by the page and retain the label that was actually found
# in the returned metric.  The API layer maps all of these to its canonical
# dashboard names.
DOUYIN_PRIMARY_SCORE_ALIASES: Dict[str, Sequence[str]] = {
    "我的体验分": ("我的体验分", "我的总分", "店铺体验分"),
    "商品体验得分": ("商品体验得分", "商品体验", "商品体验分"),
    "物流体验得分": ("物流体验得分", "物流体验", "物流体验分"),
    "服务体验得分": ("服务体验得分", "服务体验", "服务体验分"),
}
DOUYIN_DETAIL_GROUPS = {
    "product": "商品体验",
    "logistics": "物流体验",
    "service": "服务体验",
}
DOUYIN_NEW_DETAIL_GROUPS = {
    "formal-score-detail-group-goods": "商品体验",
    "formal-score-detail-group-logistics": "物流体验",
    "formal-score-detail-group-service": "服务体验",
}
DOUYIN_DETAIL_METRIC_ID_PREFIX = "formal-score-detail-metric-"
DOUYIN_SCORE_VALUE_PATTERN = re.compile(r"^[+-]?\d+(?:,\d{3})*(?:\.\d+)?$")
DOUYIN_DETAIL_VALUE_PATTERN = re.compile(
    r"^[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:%|小时|秒|分)?$"
)


def douyin_primary_canonical_name(name: str) -> Optional[str]:
    for canonical, aliases in DOUYIN_PRIMARY_SCORE_ALIASES.items():
        if name in aliases:
            return canonical
    return None


def find_douyin_score_value(scope: Element) -> str:
    """Find a score paired with a visible ``分`` unit in one local card."""

    for node in scope.descendants(include_self=True):
        value = clean_text(node.text_content()).replace(",", "")
        if not DOUYIN_SCORE_VALUE_PATTERN.fullmatch(value):
            continue
        if any(child.text_content() == value for child in direct_child_elements(node)):
            continue
        parent = node.parent
        if parent is None:
            continue
        parent_text = clean_text(parent.text_content()).replace(",", "")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*分", parent_text):
            return value.lstrip("+")
    return ""


def find_douyin_primary_semantic(root: Element, aliases: Sequence[str]) -> tuple:
    """Pair a primary label with the score in its nearest semantic card."""

    all_aliases = {
        alias
        for primary_aliases in DOUYIN_PRIMARY_SCORE_ALIASES.values()
        for alias in primary_aliases
    }
    label_nodes = [
        node for node in root.descendants(include_self=True)
        if node.attrs.get("data-title") == "true"
        and node.text_content() in aliases
    ]
    if not label_nodes:
        for alias in aliases:
            label_nodes.extend(find_exact_text_elements(root, alias))

    for label_node in label_nodes:
        current = label_node.parent
        while current is not None:
            # Once an ancestor contains more than one primary card, do not let
            # a missing value in this card accidentally consume a neighbour's.
            local_labels = [
                node for node in current.descendants(include_self=True)
                if node.text_content() in all_aliases
                and not any(child.text_content() == node.text_content() for child in direct_child_elements(node))
            ]
            if len(local_labels) > 1:
                break
            value = find_douyin_score_value(current)
            if value:
                return label_node.text_content(), value
            current = current.parent
    return "", ""


def douyin_new_detail_group(node: Element) -> Optional[str]:
    group_id = node.attrs.get("id", "")
    if group_id in DOUYIN_NEW_DETAIL_GROUPS:
        return DOUYIN_NEW_DETAIL_GROUPS[group_id]
    group_key = node.attrs.get("data-group-key", "")
    return {
        "goods": "商品体验",
        "logistics": "物流体验",
        "service": "服务体验",
    }.get(group_key)


def douyin_metric_body(article: Element) -> Element:
    """Return the text body of a new metric article, excluding its overlay."""

    # Resolve the body from the semantic metric-name button first.  This avoids
    # relying on the current number/order of wrapper elements in the article.
    for node in article.descendants(include_self=True):
        aria_label = node.attrs.get("aria-label", "")
        if not aria_label.startswith("查看") or "指标说明" not in aria_label:
            continue
        current = node
        while current.parent is not None and current.parent is not article:
            current = current.parent
        if current.parent is article and current.tag != "button":
            return current

    children = direct_child_elements(article)
    non_buttons = [child for child in children if child.tag != "button"]
    return non_buttons[0] if non_buttons else article


def douyin_new_detail_name(article: Element) -> str:
    for node in article.descendants(include_self=True):
        aria_label = node.attrs.get("aria-label", "")
        if not aria_label.startswith("查看") or "指标说明" not in aria_label:
            continue
        visible_name = node.text_content()
        if visible_name:
            return visible_name
    body = douyin_metric_body(article)
    first = direct_child_elements(body)
    return first[0].text_content() if first else ""


def douyin_new_detail_value(article: Element) -> str:
    body = douyin_metric_body(article)
    for node in body.descendants(include_self=True):
        value = clean_text(node.text_content()).replace(",", "")
        if not DOUYIN_DETAIL_VALUE_PATTERN.fullmatch(value):
            continue
        if any(child.text_content() == value for child in direct_child_elements(node)):
            continue
        return value
    return ""


def douyin_new_detail_rows(section: Element) -> List[tuple]:
    rows: List[tuple] = []
    for article in section.descendants(include_self=True):
        metric_id = article.attrs.get("id", "")
        if article.tag != "article" or not metric_id.startswith(DOUYIN_DETAIL_METRIC_ID_PREFIX):
            continue
        name = douyin_new_detail_name(article)
        value = douyin_new_detail_value(article)
        if name and value and value not in {"—", "-", "/"}:
            rows.append((name, value))
    return rows


def parse_douyin(source_block1: str, source_block2: str = "") -> Dict[str, object]:
    score_root = parse_dom(source_block1)
    detail_root = parse_dom(source_block2)
    metrics: List[Dict[str, object]] = []

    score_values: Dict[str, tuple] = {}
    # New overview cards expose ``data-title=true`` and keep the score/unit in
    # the same card.  This path does not depend on Tailwind class names.
    for canonical, aliases in DOUYIN_PRIMARY_SCORE_ALIASES.items():
        name, value = find_douyin_primary_semantic(score_root, aliases)
        if name and value:
            score_values[canonical] = (name, value)

    # Backward-compatible fallback for the previous score-view markup.
    for card in find_all(score_root, "child-score-"):
        name_node = find_first(card, "child-score-title-name-")
        value_node = find_first(card, "child-score-value-text-")
        if not name_node or not value_node:
            continue
        name = name_node.text_content()
        value = value_node.text_content()
        canonical = douyin_primary_canonical_name(name)
        if canonical and value and canonical not in score_values:
            score_values[canonical] = (name, value)

    missing_scores = [name for name in DOUYIN_PRIMARY_SCORES if name not in score_values]
    if missing_scores:
        raise ShopScoreError("抖音一级指标缺失：" + "、".join(missing_scores))
    for canonical in DOUYIN_PRIMARY_SCORES:
        name, value = score_values[canonical]
        metrics.append({
            "metricName": name,
            "metricCategory": "体验分",
            "unit": "分",
            "value": value,
        })

    found_groups = set()
    metric_identities = set()

    # Current detail cards use stable semantic group/metric IDs.  The first
    # numeric value in each article body is the store performance; comparison,
    # diagnosis, target and trend text are outside that local value node.
    new_sections = []
    for section in detail_root.descendants(include_self=True):
        group_name = douyin_new_detail_group(section)
        if group_name:
            new_sections.append((group_name, section))
    for group_name, section in new_sections:
        found_groups.add(group_name)
        for name, value in douyin_new_detail_rows(section):
            identity = (group_name, name)
            if identity in metric_identities:
                continue
            metric_identities.add(identity)
            metrics.append({
                "metricName": name,
                "metricCategory": group_name,
                "unit": metric_unit(name, value),
                "value": value,
            })

    # Keep the old table adapter as a fallback, and allow a mixed capture to
    # fill any group not present in the new markup.
    for section in detail_root.descendants(include_self=True):
        section_id = section.attrs.get("data-experience-score-card-id", "")
        group_name = DOUYIN_DETAIL_GROUPS.get(section_id)
        if not group_name or group_name in found_groups:
            continue
        found_groups.add(group_name)
        for row in find_all(section, "tableRow-"):
            cells = direct_child_elements(row, "td")
            if len(cells) < 3:
                continue
            name_node = find_first(cells[0], "title-")
            value_node = find_first(cells[2], "scoreValue-")
            if not name_node or not value_node:
                continue
            name = name_node.text_content()
            value = value_node.text_content()
            identity = (group_name, name)
            if name and value and value not in {"—", "-", "/"} and identity not in metric_identities:
                metric_identities.add(identity)
                metrics.append({
                    "metricName": name,
                    "metricCategory": group_name,
                    "unit": metric_unit(name, value),
                    "value": value,
                })

    missing_groups = [name for name in DOUYIN_DETAIL_GROUPS.values() if name not in found_groups]
    if missing_groups:
        raise ShopScoreError("抖音指标明细分组缺失：" + "、".join(missing_groups))

    combined_text = "{} {}".format(score_root.text_content(), detail_root.text_content())
    date_match = re.search(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", combined_text)
    return {
        "platform": "抖音",
        "reportDate": date_match.group(0) if date_match else "",
        "metrics": metrics,
    }


PINDUODUO_RANK_NAME = "本店铺体验分在同行排名"
PINDUODUO_SCORE_NAMES: Sequence[str] = (
    "消费者服务体验分",
    "服务态度体验分",
    "基础服务体验分",
    "商品服务体验分",
    "发货服务体验分",
    "物流服务体验分",
)


def parse_pinduoduo(source_block1: str, source_block2: str = "") -> Dict[str, object]:
    root = parse_dom(source_block1)
    score_values: Dict[str, str] = {}

    title_node = find_first(root, "score_title__")
    value_node = find_first(root, "score_scoreVal__")
    if title_node and value_node:
        name = title_node.text_content()
        if name in PINDUODUO_SCORE_NAMES:
            score_values[name] = value_node.text_content()

    for container in find_all(root, "score_attitudeScoreBox__"):
        name_node = find_first(container, "score_scoreDetail__")
        value_node = find_first(container, "score_scoreItemVal__")
        if name_node and value_node and name_node.text_content() in PINDUODUO_SCORE_NAMES:
            score_values[name_node.text_content()] = value_node.text_content()

    for container in find_all(root, "score_scoreItem__"):
        name_node = find_first(container, "score_detail__")
        value_node = find_first(container, "score_scoreItemVal__")
        if name_node and value_node and name_node.text_content() in PINDUODUO_SCORE_NAMES:
            score_values[name_node.text_content()] = value_node.text_content()

    missing_scores = [name for name in PINDUODUO_SCORE_NAMES if not score_values.get(name)]
    if missing_scores:
        raise ShopScoreError("拼多多一级指标缺失：" + "、".join(missing_scores))

    rank_value = ""
    rank_pattern = re.compile(
        r"本店铺体验分在同行排名\s*(\d+(?:\.\d+)?)%\s*(?:-|~|～|—|至)\s*(\d+(?:\.\d+)?)%"
    )
    for node in find_all(root, "score_main__"):
        match = rank_pattern.search(node.text_content())
        if match:
            rank_value = "{}%-{}%".format(match.group(1), match.group(2))
            break
    if not rank_value:
        raise ShopScoreError("拼多多一级指标缺失：{}".format(PINDUODUO_RANK_NAME))

    metrics: List[Dict[str, object]] = [{
        "metricName": PINDUODUO_RANK_NAME,
        "metricCategory": "总览",
        "unit": "区间",
        "value": rank_value,
    }]
    metrics.extend({
        "metricName": name,
        "metricCategory": "总览",
        "unit": "分",
        "value": score_values[name],
    } for name in PINDUODUO_SCORE_NAMES)
    return {"platform": "拼多多", "reportDate": "", "metrics": metrics}


Adapter = Callable[[str, str], Dict[str, object]]
ADAPTERS: Dict[str, Adapter] = {}
ReceptionAdapter = Callable[[str], Dict[str, str]]
RECEPTION_ADAPTERS: Dict[str, ReceptionAdapter] = {}


def register_adapter(platform: str, parser: Adapter) -> None:
    ADAPTERS[clean_text(platform)] = parser


def register_reception_adapter(platform: str, parser: ReceptionAdapter) -> None:
    RECEPTION_ADAPTERS[clean_text(platform)] = parser


register_adapter("天猫", parse_tmall)
register_adapter("抖音", parse_douyin)
register_adapter("拼多多", parse_pinduoduo)
register_reception_adapter("天猫", parse_tmall_reception)


def parse_reception_metric(platform: str, source_block: str) -> Dict[str, str]:
    parser = RECEPTION_ADAPTERS.get(clean_text(platform))
    if not parser:
        raise ShopScoreError(
            "尚未适配平台接待量：{}。请按 references/platform-adapters.md 添加解析器。".format(platform)
        )
    return parser(source_block)


VALID_ORDER_NAMES = {"近30天有效订单", "近30单有效订单"}


def parse_scaled_integer(raw_value: object, label: str) -> Optional[int]:
    if raw_value is None:
        return None
    text = clean_text(str(raw_value)).replace(",", "")
    if not text:
        return None
    if text.endswith("单"):
        text = text[:-1].strip()
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1].strip()
    elif text.endswith("千"):
        multiplier = 1000
        text = text[:-1].strip()
    if not re.fullmatch(r"\+?\d+(?:\.\d+)?", text):
        raise ShopScoreError("{}不是有效数字：{}".format(label, raw_value))
    value = float(text.lstrip("+")) * multiplier
    rounded = round(value)
    if abs(value - rounded) > 1e-9:
        raise ShopScoreError("{}必须换算为整数：{}".format(label, raw_value))
    return int(rounded)


def parse_valid_order_count(raw_value: object) -> Optional[int]:
    """Normalize a directly captured order count, including values such as 1.23万."""
    return parse_scaled_integer(raw_value, "近30天有效订单")


def parse_reception_count(raw_value: object) -> Optional[int]:
    return parse_scaled_integer(raw_value, "接待量")


def parse_refund_rate(raw_value: object) -> Optional[str]:
    if raw_value is None:
        return None
    text = clean_text(str(raw_value)).replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    if not re.fullmatch(r"\+?\d+(?:\.\d+)?", text):
        raise ShopScoreError("退款率不是有效百分比：{}".format(raw_value))
    value = float(text.lstrip("+"))
    if value < 0 or value > 100:
        raise ShopScoreError("退款率必须在 0% 到 100% 之间：{}".format(raw_value))
    return "{}%".format(text.lstrip("+"))


def attach_valid_order_count(result: Dict[str, object], raw_value: object) -> Dict[str, object]:
    value = parse_valid_order_count(raw_value)
    if value is None:
        return result
    updated = dict(result)
    metrics = [dict(metric) for metric in result.get("metrics", [])]
    for metric in metrics:
        if clean_text(str(metric.get("metricName", ""))) in VALID_ORDER_NAMES:
            metric.update({
                "metricName": "近30天有效订单",
                "metricCategory": "总览",
                "unit": "单",
                "value": value,
            })
            updated["metrics"] = metrics
            return updated
    metrics.append({
        "metricName": "近30天有效订单",
        "metricCategory": "总览",
        "unit": "单",
        "value": value,
    })
    updated["metrics"] = metrics
    return updated


def parse_shop_score(
    platform: str,
    source_block1: str,
    source_block2: str = "",
    reception_source: str = "",
    valid_order_count: object = "",
    report_date: str = "",
) -> Dict[str, object]:
    platform = clean_text(platform)
    parser = ADAPTERS.get(platform)
    if not parser:
        raise ShopScoreError(
            "尚未适配平台：{}。请按 references/platform-adapters.md 添加解析器。".format(platform)
        )
    result = parser(source_block1, source_block2)
    if result.get("platform") != platform:
        raise ShopScoreError("解析器返回的平台与请求平台不一致")
    source_date = clean_text(str(result.get("reportDate", "")))
    supplied_date = clean_text(str(report_date))
    if supplied_date and not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", supplied_date):
        raise ShopScoreError("report_date 必须为 YYYY-MM-DD")
    if source_date and supplied_date and source_date != supplied_date:
        raise ShopScoreError(
            "源码日期 {} 与传入日期 {} 不一致".format(source_date, supplied_date)
        )
    result = dict(result)
    result["reportDate"] = source_date or supplied_date
    if not result.get("reportDate"):
        raise ShopScoreError("源码中没有数据日期，请通过 report_date 显式传入")
    if not result.get("metrics"):
        raise ShopScoreError("解析器未返回指标")
    if reception_source and reception_source.strip():
        result = dict(result)
        result["metrics"] = list(result["metrics"]) + [
            parse_reception_metric(platform, reception_source)
        ]
    return attach_valid_order_count(result, valid_order_count)


def parse_reception_only(platform: str, source_block: str, report_date: str) -> Dict[str, object]:
    platform = clean_text(platform)
    report_date = clean_text(report_date)
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", report_date):
        raise ShopScoreError("接待量单独导入时 report_date 必须为 YYYY-MM-DD")
    return {
        "platform": platform,
        "reportDate": report_date,
        "metrics": [parse_reception_metric(platform, source_block)],
    }


def coerce_dict(value: object) -> Dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = ast.literal_eval(value)
        if isinstance(parsed, dict):
            return parsed
    raise ShopScoreError("解析结果必须是字典或字典字符串")


def upsert_metric(metrics: List[Dict[str, object]], metric: Dict[str, object]) -> None:
    identity = (metric["metricCategory"], metric["metricName"])
    for index, current in enumerate(metrics):
        if (current.get("metricCategory"), current.get("metricName")) == identity:
            metrics[index] = metric
            return
    metrics.append(metric)


def add_direct_metrics(parsed_result: object, reception_count: object = "", refund_rate: object = "") -> Dict[str, object]:
    parsed = dict(coerce_dict(parsed_result))
    platform = clean_text(str(parsed.get("platform", "")))
    metrics = [dict(metric) for metric in parsed.get("metrics", [])]
    reception_value = parse_reception_count(reception_count)
    if reception_value is not None:
        if platform not in RECEPTION_PLATFORMS:
            raise ShopScoreError("{}不允许导入接待量".format(platform or "当前平台"))
        upsert_metric(metrics, {
            "metricName": "接待量",
            "metricCategory": "运营",
            "unit": "单",
            "value": reception_value,
        })
    refund_value = parse_refund_rate(refund_rate)
    if refund_value is not None:
        if platform not in REFUND_PLATFORMS:
            raise ShopScoreError("{}不允许导入退款率；目前只有抖音支持".format(platform or "当前平台"))
        upsert_metric(metrics, {
            "metricName": "退款率",
            "metricCategory": "退款统计",
            "unit": "%",
            "value": refund_value,
        })
    if not metrics:
        raise ShopScoreError("没有可导入的直接指标")
    parsed["metrics"] = metrics
    return parsed


def create_direct_result(platform: str, report_date: str, reception_count: object = "") -> Dict[str, object]:
    platform = clean_text(platform)
    report_date = clean_text(report_date)
    if not platform:
        raise ShopScoreError("平台不能为空")
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", report_date):
        raise ShopScoreError("report_date 必须为 YYYY-MM-DD")
    return add_direct_metrics(
        {"platform": platform, "reportDate": report_date, "metrics": []},
        reception_count,
    )


def api_value(raw_value: object, unit: str) -> object:
    text = clean_text(str(raw_value))
    if unit == "区间":
        return text
    if unit == "%":
        return text if text.endswith("%") else "{}%".format(text)
    for suffix in ("小时", "秒", "分", "单"):
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
            break
    try:
        return float(text.replace(",", ""))
    except ValueError as error:
        raise ShopScoreError("指标值不是有效数值：{}".format(raw_value)) from error


def build_import_payload(
    parsed_result: object,
    shop_name: str,
    dry_run: bool = True,
    shop_kind: str = "own",
) -> Dict[str, object]:
    parsed = coerce_dict(parsed_result)
    platform = clean_text(str(parsed.get("platform", "")))
    report_date = clean_text(str(parsed.get("reportDate", "")))
    shop_name = clean_text(shop_name)
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", report_date):
        raise ShopScoreError("reportDate 必须为 YYYY-MM-DD")
    if not platform or not shop_name:
        raise ShopScoreError("平台和店铺名称不能为空")
    if shop_kind not in {"own", "competitor"}:
        raise ShopScoreError("shop_kind 只能是 own 或 competitor")

    records: List[Dict[str, object]] = []
    for metric in parsed.get("metrics", []):
        name = clean_text(str(metric.get("metricName", "")))
        category = clean_text(str(metric.get("metricCategory", "")))
        unit = clean_text(str(metric.get("unit", "")))
        if not name or not category or not unit:
            raise ShopScoreError("指标缺少 metricName、metricCategory 或 unit")
        records.append({
            "reportDate": report_date,
            "platform": platform,
            "shopName": shop_name,
            "shopKind": shop_kind,
            "metricName": name,
            "metricCategory": category,
            "unit": unit,
            "value": api_value(metric.get("value"), unit),
            "note": (
                "接待量每日自动采集" if category in {"接待量", "运营"}
                else "退款率每日自动采集" if category == "退款统计"
                else "店铺分每日自动采集"
            ),
            "source": "影刀RPA",
        })
    if not records:
        raise ShopScoreError("没有可导入指标")
    request_id = "{}-{}-{}".format(platform, report_date.replace("-", ""), shop_name)[:100]
    return {"requestId": request_id, "dryRun": bool(dry_run), "records": records}


def yingdao_parse(platform, source_block1, source_block2="", reception_source="", valid_order_count="", report_date=""):
    """影刀入口保持单行且无尾随逗号，避免影刀生成空参数。"""
    return parse_shop_score(platform, source_block1, source_block2, reception_source, valid_order_count, report_date)


def yingdao_parse_reception(platform, reception_source, report_date):
    """接待量单独导入入口；签名格式兼容影刀模块解析器。"""
    return parse_reception_only(platform, reception_source, report_date)


def yingdao_add_direct_metrics(parsed_result, reception_count="", refund_rate=""):
    """Backward-compatible generic entry point; prefer the platform-specific wrappers."""
    return add_direct_metrics(parsed_result, reception_count, refund_rate)


def yingdao_add_reception(parsed_result, reception_count):
    """Add a directly captured reception count to Tmall or Pinduoduo score results."""
    return add_direct_metrics(parsed_result, reception_count, "")


def yingdao_add_douyin_metrics(parsed_result, reception_count="", refund_rate=""):
    """Add directly captured reception and refund values to a Douyin score result."""
    parsed = coerce_dict(parsed_result)
    if clean_text(str(parsed.get("platform", ""))) != "抖音":
        raise ShopScoreError("yingdao_add_douyin_metrics 只允许用于抖音")
    return add_direct_metrics(parsed, reception_count, refund_rate)


def yingdao_create_direct_result(platform, report_date, reception_count=""):
    """Create a reception-only result; Douyin refund is added after yingdao_parse."""
    return create_direct_result(platform, report_date, reception_count)


def yingdao_build_api_body(parsed_result, shop_name, dry_run=True):
    """API 组包入口；签名格式兼容影刀模块解析器。"""
    return json.dumps(
        build_import_payload(parsed_result, shop_name, dry_run=dry_run),
        ensure_ascii=False,
    )


def self_test() -> None:
    performance = """
    <div class="PerformanceMetrics--container--random"><span>更新时间：2026-07-14</span>
      <div class="PerformanceMetricsTable--container--a"><div class="PerformanceMetricsTable--listName--a" id="voc-shop-performance-newGoods-v2025"><span class="PerformanceMetricsTable--name--a">宝贝质量</span></div><div class="PerformanceMetricsTableList--listItem--a"><span class="PerformanceMetricsTableList--metricsName--a">商品负反馈率</span><span class="RankContainer--rankValue--a">0.1124%</span></div></div>
      <div class="PerformanceMetricsTable--container--b"><div class="PerformanceMetricsTable--listName--b" id="voc-shop-performance-newLogistics-v2025"><span class="PerformanceMetricsTable--name--b">物流速度</span></div><div class="PerformanceMetricsTableList--listItem--b"><span class="PerformanceMetricsTableList--metricsName--b">物流到货时长</span><span class="RankContainer--rankValue--b">47.09<span>小时</span></span></div></div>
      <div class="PerformanceMetricsTable--container--c"><div class="PerformanceMetricsTable--listName--c" id="voc-shop-performance-newServices-v2025"><span class="PerformanceMetricsTable--name--c">服务保障</span></div><div class="PerformanceMetricsTableList--listItem--c"><span class="PerformanceMetricsTableList--metricsName--c">平台求助率</span><span class="RankContainer--rankValue--c">0.0000%</span></div></div>
    </div>"""
    scores = """
    <div class="ScoreDetails--container--x"><span class="ScoreDetails--firstItemName--x">真实体验分</span><span class="ScoreDetails--firstItemScore--x">5.00</span>
      <div class="ScoreDetails--item--x"><span class="ScoreDetails--itemName--x">宝贝质量</span><span class="ScoreDetails--itemScore--x">4.97</span></div>
      <div class="ScoreDetails--item--y"><span class="ScoreDetails--itemName--x">物流速度</span><span class="ScoreDetails--itemScore--x">4.96</span></div>
      <div class="ScoreDetails--item--z"><span class="ScoreDetails--itemName--x">服务保障</span><span class="ScoreDetails--itemScore--x">5.00</span></div>
    </div>"""
    reception = """
    <div class="index-group-level-1 consult-monitor-overview-index">
      <div class="index-line level-1"><span class="index-label level-1"><span class="text">咨询人数</span></span></div>
      <div class="index-line level-1"><div class="index-value level-1"><span class="numbervalue" data-onetrace-index-id="random"><span class="number-prefix"></span>34</span></div></div>
      <div class="index-group-level-2"><div class="index-value level-2"><span class="numbervalue">17.24%</span></div></div>
    </div>"""
    result = parse_shop_score("天猫", performance, scores, reception, "1.23万")
    assert result["reportDate"] == "2026-07-14"
    assert len(result["metrics"]) == 9
    assert result["metrics"][-2] == {
        "metricName": "咨询人数",
        "metricCategory": "接待量",
        "unit": "单",
        "value": "34",
    }
    assert result["metrics"][-1] == {
        "metricName": "近30天有效订单",
        "metricCategory": "总览",
        "unit": "单",
        "value": 12300,
    }
    payload = build_import_payload(result, "mock天猫旗舰店", dry_run=True)
    assert len(payload["records"]) == 9
    assert payload["records"][5]["unit"] == "小时"
    assert payload["records"][5]["value"] == 47.09
    assert payload["records"][-2]["value"] == 34.0
    assert payload["records"][-2]["note"] == "接待量每日自动采集"
    assert payload["records"][-1]["value"] == 12300.0

    # Current Tmall DOM: prove that primary extraction and the three semantic
    # detail groups keep working even when every CSS class is renamed.
    current_tmall_performance = """
    <div class="renamed-root"><span>更新时间：2026-08-06</span>
      <div class="renamed-group"><div id="voc-shop-performance-newGoods-v2025">宝贝质量</div>
        <div id="metricsNameContainer-商品负反馈率"><div><span>商品负反馈率</span><span>0.0674%</span></div></div>
      </div>
      <div class="renamed-group"><div id="voc-shop-performance-newLogistics-v2025">物流速度</div>
        <div id="metricsNameContainer-物流到货时长"><div><span>物流到货时长</span><span>47.51<span>小时</span></span></div></div>
      </div>
      <div class="renamed-group"><div id="voc-shop-performance-newServices-v2025">服务保障</div>
        <div id="metricsNameContainer-平台求助率"><div><span>平台求助率</span><span>0.0000%</span></div></div>
      </div>
      <div><div id="voc-shop-performance-additionalPoints-v2025">附加分</div>
        <div id="metricsNameContainer-特色服务达标占比"><div><span>特色服务达标占比</span><span>67.14%</span></div></div>
      </div>
    </div>"""
    current_tmall_scores = """
    <div class="renamed-scores">
      <div><span>真实体验分</span><span>5.00</span><span>超过99%同行</span></div>
      <div><span><span>宝贝质量</span><span>（权重30%）</span></span><span>4.94</span></div>
      <div><span><span>物流速度</span><span>（权重30%）</span></span><span>4.96</span></div>
      <div><span><span>服务保障</span><span>（权重40%）</span></span><span>5.00</span></div>
    </div>"""
    current_tmall_result = parse_shop_score(
        "天猫", current_tmall_performance, current_tmall_scores
    )
    assert current_tmall_result["reportDate"] == "2026-08-06"
    assert len(current_tmall_result["metrics"]) == 7
    current_tmall_values = {
        (metric["metricCategory"], metric["metricName"]): metric["value"]
        for metric in current_tmall_result["metrics"]
    }
    assert current_tmall_values[("体验分", "宝贝质量")] == "4.94"
    assert current_tmall_values[("物流速度", "物流到货时长")] == "47.51小时"
    assert ("附加分", "特色服务达标占比") not in current_tmall_values

    douyin_scores = """
    <div class="score-view-random">
      <div class="child-score-a"><div class="child-score-title-name-a">我的体验分</div><div class="child-score-value-a"><span class="child-score-value-text-a">98</span><span>分</span></div></div>
      <div class="child-score-b"><div class="child-score-title-name-b">商品体验得分</div><div class="child-score-value-b"><span class="child-score-value-text-b">100</span></div></div>
      <div class="child-score-c"><div class="child-score-title-name-c">物流体验得分</div><div class="child-score-value-c"><span class="child-score-value-text-c">100</span></div></div>
      <div class="child-score-d"><div class="child-score-title-name-d">服务体验得分</div><div class="child-score-value-d"><span class="child-score-value-text-d">95</span></div></div>
      <div class="child-score-e"><div class="child-score-title-name-e">差行为扣分</div><div class="child-score-value-e"><span class="child-score-value-text-e">0</span></div></div>
    </div>"""
    douyin_details = """
    <div>
      <div class="analysis-product" data-experience-score-card-id="product"><table><tbody>
        <tr class="tableRow-a"><td><div class="title-a">商品综合评分</div></td><td>100分</td><td><div class="scoreValue-a">4.8527</div></td></tr>
        <tr class="tableRow-b"><td><div class="title-b">商品品质退货率</div></td><td>100分</td><td><div class="scoreValue-b">0.000%</div></td></tr>
      </tbody></table></div>
      <div class="analysis-logistics" data-experience-score-card-id="logistics"><table><tbody>
        <tr class="tableRow-c"><td><div class="title-c">揽收时长平均得分</div></td><td>100分</td><td><div class="scoreValue-c">100</div></td></tr>
        <tr class="tableRow-d"><td><div class="title-d">运单配送时效达成率</div></td><td>100分</td><td><div class="scoreValue-d">97.646%</div></td></tr>
        <tr class="tableRow-e"><td><div class="title-e">发货物流品退率</div></td><td>100分</td><td><div class="scoreValue-e">0.0000%</div></td></tr>
      </tbody></table></div>
      <div class="analysis-service" data-experience-score-card-id="service"><table><tbody>
        <tr class="tableRow-f"><td><div class="title-f">飞鸽平均响应时长</div></td><td>100分</td><td><div class="scoreValue-f">12.904秒</div></td></tr>
        <tr class="tableRow-g"><td><div class="title-g">售后平均审核时长</div></td><td>100分</td><td><div class="scoreValue-g">1.2213小时</div></td></tr>
        <tr class="tableRow-h"><td><div class="title-h">飞鸽会话不满意率</div></td><td>100分</td><td><div class="scoreValue-h">9.5238%</div></td></tr>
        <tr class="tableRow-i"><td><div class="title-i">平台求助率</div></td><td>80分</td><td><div class="scoreValue-i">0.3921%</div></td></tr>
      </tbody></table></div>
    </div>"""
    douyin_result = parse_shop_score(
        "抖音", douyin_scores, douyin_details, "", "2345", "2026-07-15"
    )
    assert douyin_result["reportDate"] == "2026-07-15"
    assert len(douyin_result["metrics"]) == 14
    douyin_values = {
        (metric["metricCategory"], metric["metricName"]): (metric["value"], metric["unit"])
        for metric in douyin_result["metrics"]
    }
    assert douyin_values[("体验分", "我的体验分")] == ("98", "分")
    assert douyin_values[("商品体验", "商品综合评分")] == ("4.8527", "分")
    assert douyin_values[("物流体验", "运单配送时效达成率")] == ("97.646%", "%")
    assert douyin_values[("服务体验", "飞鸽平均响应时长")] == ("12.904秒", "秒")
    assert douyin_values[("服务体验", "售后平均审核时长")] == ("1.2213小时", "小时")
    assert douyin_values[("总览", "近30天有效订单")] == (2345, "单")
    douyin_payload = build_import_payload(douyin_result, "mock官方旗舰店", dry_run=True)
    assert len(douyin_payload["records"]) == 14

    douyin_with_direct = add_direct_metrics(douyin_result, "88单", "2.35%")
    assert len(douyin_with_direct["metrics"]) == 16
    direct_values = {
        (metric["metricCategory"], metric["metricName"]): (metric["value"], metric["unit"])
        for metric in douyin_with_direct["metrics"]
    }
    assert direct_values[("运营", "接待量")] == (88, "单")
    assert direct_values[("退款统计", "退款率")] == ("2.35%", "%")
    direct_payload = build_import_payload(douyin_with_direct, "mock官方旗舰店", dry_run=True)
    assert direct_payload["records"][-2]["note"] == "接待量每日自动采集"
    assert direct_payload["records"][-1]["note"] == "退款率每日自动采集"

    # Current Douyin DOM: semantic overview labels and formal-score detail
    # articles remain parseable when all generated CSS classes change.
    current_douyin_scores = """
    <section aria-label="体验分公式概览">
      <article><span data-title="true">我的总分</span><div><span>96</span><span>分</span></div></article>
      <button type="button"><span data-title="true">商品体验</span><div><span>84</span><span>分</span></div><span>较前1日持平</span></button>
      <button type="button"><span data-title="true">物流体验</span><div><span>96</span><span>分</span></div><span>较前1日1</span></button>
      <button type="button"><span data-title="true">服务体验</span><div><span>89</span><span>分</span></div><span>较前1日持平</span></button>
      <button type="button"><span data-title="true">加分项</span><div><span>7</span><span>分</span></div></button>
      <button type="button"><span data-title="true">扣分项</span><div><span>0</span><span>分</span></div></button>
    </section>"""
    current_douyin_details = """
    <section aria-label="正式分分数详情" data-e2e="formal-score-detail">
      <section id="formal-score-detail-group-goods" data-group-key="goods">
        <article id="formal-score-detail-metric-108"><button aria-label="打开商品综合评分指标详情"></button><div><span><button aria-label="查看商品综合评分指标说明，点击打开指标详情">商品综合评分</button></span><div><span>4.8431</span><span>分</span></div><div>较前1日0.0110</div></div></article>
        <article id="formal-score-detail-metric-103"><button aria-label="打开商品品质退货率指标详情"></button><div><span><button aria-label="查看商品品质退货率指标说明，点击打开指标详情">商品品质退货率</button></span><div><div><span>0.089</span><span>%</span></div><button data-e2e="formal-metric-diagnosis-text">品退原因</button></div><div>较前1日0.003%</div></div></article>
      </section>
      <section id="formal-score-detail-group-logistics" data-group-key="logistics">
        <article id="formal-score-detail-metric-211"><button aria-label="打开平均揽收时长指标详情"></button><div><span><button aria-label="查看平均揽收时长指标说明，点击打开指标详情">平均揽收时长</button></span><div><span>6.2680</span><span>小时</span></div></div></article>
        <article id="formal-score-detail-metric-203"><button aria-label="打开运单配送时效达成率指标详情"></button><div><span><button aria-label="查看运单配送时效达成率指标说明，点击打开指标详情">运单配送时效达成率</button></span><div><span>96.856</span><span>%</span></div></div></article>
        <article id="formal-score-detail-metric-212"><button aria-label="打开商品/包装破损退货订单率指标详情"></button><div><span><button aria-label="查看商品/包装破损退货订单率指标说明，点击打开指标详情">商品/包装破损退货订单率</button></span><div><span>0.0293</span><span>%</span></div></div></article>
      </section>
      <section id="formal-score-detail-group-service" data-group-key="service">
        <article id="formal-score-detail-metric-309"><button aria-label="打开飞鸽人工会话平响时长指标详情"></button><div><span><button aria-label="查看飞鸽人工会话平响时长指标说明，点击打开指标详情">飞鸽人工会话平响时长</button></span><div><span>14.683</span><span>秒</span></div></div></article>
        <article id="formal-score-detail-metric-316"><button aria-label="打开售后平均审核时长指标详情"></button><div><span><button aria-label="查看售后平均审核时长指标说明，点击打开指标详情">售后平均审核时长</button></span><div><span>1.4174</span><span>小时</span></div></div></article>
        <article id="formal-score-detail-metric-317"><button aria-label="打开飞鸽人工会话不满意率指标详情"></button><div><span><button aria-label="查看飞鸽人工会话不满意率指标说明，点击打开指标详情">飞鸽人工会话不满意率</button></span><div><span>10.280</span><span>%</span></div></div></article>
        <article id="formal-score-detail-metric-318"><button aria-label="打开平台求助率指标详情"></button><div><span><button aria-label="查看平台求助率指标说明，点击打开指标详情">平台求助率</button></span><div><div><span>0.2716</span><span>%</span></div><button data-e2e="formal-metric-diagnosis-text">求助数诊断</button></div><div>较前1日0.0083%</div></div></article>
      </section>
      <section id="formal-score-detail-group-add"><article id="formal-score-detail-metric-701"><button aria-label="查看明日达订单占比指标说明，点击打开指标详情">明日达订单占比</button><div>+5分</div></article></section>
      <section id="formal-score-detail-group-deduct"><article id="formal-score-detail-metric-501"><button aria-label="查看虚假交易刷体验分指标说明，点击打开指标详情">虚假交易刷体验分</button><div>0分</div></article></section>
    </section>"""
    current_douyin_result = parse_shop_score(
        "抖音", current_douyin_scores, current_douyin_details, "", "", "2026-09-11"
    )
    assert current_douyin_result["reportDate"] == "2026-09-11"
    assert len(current_douyin_result["metrics"]) == 13
    current_douyin_values = {
        (metric["metricCategory"], metric["metricName"]): (metric["value"], metric["unit"])
        for metric in current_douyin_result["metrics"]
    }
    assert current_douyin_values[("体验分", "我的总分")] == ("96", "分")
    assert current_douyin_values[("商品体验", "商品品质退货率")] == ("0.089%", "%")
    assert current_douyin_values[("物流体验", "平均揽收时长")] == ("6.2680小时", "小时")
    assert current_douyin_values[("服务体验", "平台求助率")] == ("0.2716%", "%")

    pinduoduo_source = """
    <div class="score_scoreWrapper__random">
      <div class="score_title__a"><span>消费者服务体验分</span></div>
      <div class="score_scoreVal__b">3.1</div>
      <div class="score_rightTitle__c"><div class="score_main__d">本店铺体验分在同行排名30%-40%</div></div>
      <div class="score_attitudeScoreBox__e">
        <div class="score_scoreDetail__f"><span>服务态度体验分</span></div>
        <div class="score_scoreItemVal__g">4.9</div><span>较前7日 0.00%</span>
      </div>
      <div class="score_scoreItem__h"><div class="score_detail__i"><span>基础服务体验分</span></div><div class="score_scoreItemVal__j">2.3</div><span>5.00%</span></div>
      <div class="score_scoreItem__k"><div class="score_detail__l"><span>商品服务体验分</span></div><div class="score_scoreItemVal__m">2.6</div><span>1.93%</span></div>
      <div class="score_scoreItem__n"><div class="score_detail__o"><span>发货服务体验分</span></div><div class="score_scoreItemVal__p">3.8</div><span>0.41%</span></div>
      <div class="score_scoreItem__q"><div class="score_detail__r"><span>物流服务体验分</span></div><div class="score_scoreItemVal__s">3.1</div><span>8.61%</span></div>
    </div>"""
    pinduoduo_result = parse_shop_score(
        "拼多多", pinduoduo_source, "", "", "", "2026-07-16"
    )
    assert pinduoduo_result["reportDate"] == "2026-07-16"
    assert len(pinduoduo_result["metrics"]) == 7
    pinduoduo_values = {
        metric["metricName"]: (metric["value"], metric["unit"])
        for metric in pinduoduo_result["metrics"]
    }
    assert pinduoduo_values[PINDUODUO_RANK_NAME] == ("30%-40%", "区间")
    assert pinduoduo_values["消费者服务体验分"] == ("3.1", "分")
    assert pinduoduo_values["服务态度体验分"] == ("4.9", "分")
    assert pinduoduo_values["基础服务体验分"] == ("2.3", "分")
    assert pinduoduo_values["商品服务体验分"] == ("2.6", "分")
    assert pinduoduo_values["发货服务体验分"] == ("3.8", "分")
    assert pinduoduo_values["物流服务体验分"] == ("3.1", "分")
    pinduoduo_payload = build_import_payload(pinduoduo_result, "mock饮品旗舰店")
    assert len(pinduoduo_payload["records"]) == 7
    assert pinduoduo_payload["records"][0]["value"] == "30%-40%"

    jd_result = create_direct_result("京东", "2026-07-15", "1,234")
    assert jd_result["metrics"] == [{
        "metricName": "接待量",
        "metricCategory": "运营",
        "unit": "单",
        "value": 1234,
    }]
    try:
        add_direct_metrics(
            {"platform": "天猫", "reportDate": "2026-07-15", "metrics": []},
            "",
            "1.2%",
        )
    except ShopScoreError as error:
        assert "只有抖音支持" in str(error)
    else:
        raise AssertionError("天猫退款率本应被拒绝")

    print("self-test passed: Tmall 9; Douyin 14+2; Pinduoduo 7; JD reception-only")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse shop score HTML and build import JSON")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--platform")
    parser.add_argument("--source1", type=Path)
    parser.add_argument("--source2", type=Path)
    parser.add_argument("--source3", type=Path, help="optional reception-count OuterHTML")
    parser.add_argument("--valid-orders", default="", help="directly captured 30-day valid order count")
    parser.add_argument("--reception-count", default="", help="directly captured reception count")
    parser.add_argument("--refund-rate", default="", help="directly captured Douyin refund rate")
    parser.add_argument("--report-date", help="explicit YYYY-MM-DD when source has no date")
    parser.add_argument("--reception-only", action="store_true")
    parser.add_argument("--shop")
    parser.add_argument("--formal", action="store_true", help="set dryRun=false")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.platform or not args.shop:
        parser.error("--platform and --shop are required")
    if args.reception_only:
        if not args.source3 or not args.report_date:
            parser.error("--reception-only requires --source3 and --report-date")
        result = parse_reception_only(
            args.platform,
            args.source3.read_text(encoding="utf-8-sig"),
            args.report_date,
        )
        print(yingdao_build_api_body(result, args.shop, dry_run=not args.formal))
        return
    if not args.source1:
        if args.refund_rate:
            parser.error("--refund-rate requires a Douyin score source and yingdao_parse workflow")
        if not args.report_date or not args.reception_count:
            parser.error("without --source1, provide --report-date and --reception-count")
        result = create_direct_result(
            args.platform,
            args.report_date,
            args.reception_count,
        )
        print(yingdao_build_api_body(result, args.shop, dry_run=not args.formal))
        return
    source2 = args.source2.read_text(encoding="utf-8-sig") if args.source2 else ""
    source3 = args.source3.read_text(encoding="utf-8-sig") if args.source3 else ""
    result = parse_shop_score(
        args.platform,
        args.source1.read_text(encoding="utf-8-sig"),
        source2,
        source3,
        args.valid_orders,
        args.report_date or "",
    )
    result = add_direct_metrics(result, args.reception_count, args.refund_rate)
    print(yingdao_build_api_body(result, args.shop, dry_run=not args.formal))


if __name__ == "__main__":
    main()
