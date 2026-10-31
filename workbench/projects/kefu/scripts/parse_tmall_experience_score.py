"""解析天猫店铺体验分与咨询人数页面的 HTML 文档块。

设计目标：
1. 不依赖带随机哈希的完整 class 名，只匹配稳定的组件 class 前缀。
2. 只固定一级指标（宝贝质量、物流速度、服务保障），不固定二级指标名称。
3. 二级指标的名称和值始终在同一行内成对提取，避免两个列表错位。
4. 可选解析第三个“咨询人数”文档块，并忽略环比和同行值。
5. 页面缺块时明确报错，避免自动化流程把不完整数据写入日报。

既可以在影刀的 Python 节点中 import 后调用 parse_tmall_blocks，也可以直接：
python parse_tmall_experience_score.py 指标表现.html 体验分.html
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union


PRIMARY_GROUPS: Sequence[str] = ("宝贝质量", "物流速度", "服务保障")
PRIMARY_SCORES: Sequence[str] = ("真实体验分",) + PRIMARY_GROUPS

# 当前页面上的 id 比动态 class 更稳定。即使 id 以后改版，仍会回退到可见的一级指标名称。
SECTION_ID_TO_GROUP = {
    "newGoods": "宝贝质量",
    "newLogistics": "物流速度",
    "newServices": "服务保障",
}

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class TmallParseError(ValueError):
    """HTML 不完整或页面结构已发生无法安全兼容的变化。"""


@dataclass
class Element:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List[Union["Element", str]] = field(default_factory=list)

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
                return
            for child in node.children:
                collect(child)

        collect(self)
        return _clean_text("".join(parts))

    def descendants(self, include_self: bool = False) -> Iterable["Element"]:
        if include_self:
            yield self
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()


class _TolerantDomParser(HTMLParser):
    """足以解析外层 HTML 的轻量 DOM；对常见的非严格 HTML 也可容错。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("__root__")
        self._stack: List[Element] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        element = Element(
            tag=tag.lower(),
            attrs={key: (value or "") for key, value in attrs},
        )
        self._stack[-1].children.append(element)
        if tag.lower() not in _VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: List[tuple]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _clean_text(value: str) -> str:
    value = value.replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", value).strip()


def _parse_dom(html: str) -> Element:
    if not isinstance(html, str) or not html.strip():
        raise TmallParseError("传入的 HTML 文档块为空")
    parser = _TolerantDomParser()
    parser.feed(html)
    parser.close()
    return parser.root


def _find_first_by_class(root: Element, prefix: str) -> Optional[Element]:
    return next(
        (node for node in root.descendants(include_self=True) if node.has_class_prefix(prefix)),
        None,
    )


def _find_all_by_class(root: Element, prefix: str) -> List[Element]:
    return [
        node
        for node in root.descendants(include_self=True)
        if node.has_class_prefix(prefix)
    ]


def _recognize_group(section: Element) -> Optional[str]:
    name_node = _find_first_by_class(section, "PerformanceMetricsTable--name--")
    visible_name = name_node.text_content() if name_node else ""
    if visible_name in PRIMARY_GROUPS:
        return visible_name

    list_name = _find_first_by_class(section, "PerformanceMetricsTable--listName--")
    section_id = list_name.attrs.get("id", "") if list_name else ""
    for marker, group_name in SECTION_ID_TO_GROUP.items():
        if marker in section_id:
            return group_name
    return None


def parse_performance_metrics(html: str, validate: bool = True) -> Dict[str, object]:
    """解析第一个文档块，动态获取三个一级指标下的全部明细。"""

    root = _parse_dom(html)
    result: Dict[str, object] = {group: [] for group in PRIMARY_GROUPS}

    # 页面会给容器 class 加构建哈希，所以只检查固定前缀。
    sections = _find_all_by_class(root, "PerformanceMetricsTable--container--")
    for section in sections:
        group_name = _recognize_group(section)
        if not group_name:
            continue

        rows = _find_all_by_class(section, "PerformanceMetricsTableList--listItem--")
        for row in rows:
            name_node = _find_first_by_class(
                row, "PerformanceMetricsTableList--metricsName--"
            )
            value_node = _find_first_by_class(row, "RankContainer--rankValue--")
            if not name_node or not value_node:
                continue

            metric_name = name_node.text_content()
            metric_value = value_node.text_content()  # 包含“小时”等子节点单位
            if metric_name and metric_value:
                result[group_name].append(
                    {"指标名称": metric_name, "指标值": metric_value}
                )

    # 中文也属于正则的“单词字符”，所以这里不能用 \b 包围日期。
    date_match = re.search(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", root.text_content())
    result_with_date: Dict[str, object] = {
        "数据日期": date_match.group(0) if date_match else None,
        "指标明细": result,
    }

    if validate:
        empty_groups = [name for name in PRIMARY_GROUPS if not result[name]]
        if empty_groups:
            raise TmallParseError(
                "以下一级指标未提取到任何明细："
                + "、".join(empty_groups)
                + "。请确认传入的是完整的“指标表现”文档块，或检查页面是否改版。"
            )
    return result_with_date


def parse_score_details(html: str, validate: bool = True) -> Dict[str, str]:
    """解析第二个文档块，获取真实体验分和三个一级指标分。"""

    root = _parse_dom(html)
    scores: Dict[str, str] = {}

    first_name = _find_first_by_class(root, "ScoreDetails--firstItemName--")
    first_score = _find_first_by_class(root, "ScoreDetails--firstItemScore--")
    if first_name and first_score:
        scores[first_name.text_content()] = first_score.text_content()

    for row in _find_all_by_class(root, "ScoreDetails--item--"):
        name_node = _find_first_by_class(row, "ScoreDetails--itemName--")
        score_node = _find_first_by_class(row, "ScoreDetails--itemScore--")
        if name_node and score_node:
            scores[name_node.text_content()] = score_node.text_content()

    if validate:
        missing = [name for name in PRIMARY_SCORES if not scores.get(name)]
        if missing:
            raise TmallParseError(
                "以下一级指标分未提取到："
                + "、".join(missing)
                + "。请确认传入的是完整的“体验分”文档块，或检查页面是否改版。"
            )
    return scores


def parse_consultation_count(html: str) -> str:
    """解析天猫咨询人数一级值，不读取较前1日或同行同层优秀。"""

    root = _parse_dom(html)
    for group in _find_all_by_class(root, "index-group-level-1"):
        labels = [
            node.text_content()
            for node in _find_all_by_class(group, "index-label")
        ]
        if "咨询人数" not in labels:
            continue
        for value_container in _find_all_by_class(group, "index-value"):
            if not value_container.has_class("level-1"):
                continue
            value_node = _find_first_by_class(value_container, "numbervalue")
            if not value_node:
                continue
            value = value_node.text_content().replace(",", "")
            if re.fullmatch(r"\+?\d+(?:\.\d+)?", value):
                return value.lstrip("+")
    raise TmallParseError("未找到“咨询人数”的一级数值，请确认传入完整文档块")


def parse_valid_order_count(raw_value: object) -> Optional[str]:
    if raw_value is None:
        return None
    text = _clean_text(str(raw_value)).replace(",", "")
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
        raise TmallParseError("近30天有效订单不是有效数字：{}".format(raw_value))
    value = float(text.lstrip("+")) * multiplier
    rounded = round(value)
    if abs(value - rounded) > 1e-9:
        raise TmallParseError("近30天有效订单必须换算为整数：{}".format(raw_value))
    return str(int(rounded))


def parse_tmall_blocks(
    performance_html: str,
    score_html: str,
    validate: bool = True,
    consultation_html: Optional[str] = None,
    valid_order_count: object = None,
) -> Dict[str, object]:
    """影刀推荐入口：传入店铺分源码，并可选传入咨询人数源码。"""

    performance = parse_performance_metrics(performance_html, validate=validate)
    result = {
        "数据日期": performance["数据日期"],
        "一级指标": parse_score_details(score_html, validate=validate),
        "指标明细": performance["指标明细"],
    }
    if consultation_html and consultation_html.strip():
        result["咨询人数"] = parse_consultation_count(consultation_html)
    normalized_orders = parse_valid_order_count(valid_order_count)
    if normalized_orders is not None:
        result["近30天有效订单"] = normalized_orders
    return result


def flatten_result(result: Dict[str, object]) -> Dict[str, Optional[str]]:
    """转成适合写入 Excel 单行日报的扁平字典；新明细会自动成为新字段。"""

    flat: Dict[str, Optional[str]] = {"数据日期": result.get("数据日期")}
    for name, value in result.get("一级指标", {}).items():
        flat[name] = value
    for group_name, metrics in result.get("指标明细", {}).items():
        for metric in metrics:
            # 加一级指标前缀可避免未来不同分组出现同名明细时互相覆盖。
            flat[f"{group_name}/{metric['指标名称']}"] = metric["指标值"]
    if result.get("咨询人数") is not None:
        flat["咨询人数"] = str(result["咨询人数"])
    if result.get("近30天有效订单") is not None:
        flat["近30天有效订单"] = str(result["近30天有效订单"])
    return flat


def yingdao_parse(web_element_attribute, web_element_attribute2, web_element_attribute3=None, valid_order_count=None):
    """影刀“调用模块中的函数”入口，返回适合流程使用的扁平字典。"""

    result = parse_tmall_blocks(
        web_element_attribute,
        web_element_attribute2,
        consultation_html=web_element_attribute3,
        valid_order_count=valid_order_count,
    )
    return flatten_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="解析天猫体验分和可选咨询人数 HTML 文档块")
    parser.add_argument("performance_html", type=Path, help="指标表现 HTML/文本文件")
    parser.add_argument("score_html", type=Path, help="体验分 HTML/文本文件")
    parser.add_argument(
        "consultation_html",
        nargs="?",
        type=Path,
        help="可选：咨询人数 HTML/文本文件",
    )
    parser.add_argument("--valid-orders", default=None, help="近30天有效订单数")
    parser.add_argument(
        "--flat", action="store_true", help="输出适合 Excel 单行写入的扁平 JSON"
    )
    args = parser.parse_args()

    result = parse_tmall_blocks(
        args.performance_html.read_text(encoding="utf-8-sig"),
        args.score_html.read_text(encoding="utf-8-sig"),
        consultation_html=(
            args.consultation_html.read_text(encoding="utf-8-sig")
            if args.consultation_html
            else None
        ),
        valid_order_count=args.valid_orders,
    )
    if args.flat:
        result = flatten_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
