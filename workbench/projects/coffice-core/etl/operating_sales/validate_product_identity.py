#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只读验收公司商品识别、数量解析、赠品与GMV分摊语义。"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


PRODUCT_COMPONENT_UNION = """
    SELECT * FROM dws.dws_douyin_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_jd_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_ks_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_product_allocation
    UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_product_allocation
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate(cursor: RealDictCursor) -> dict[str, object]:
    cursor.execute(
        """
        WITH samples(raw_code) AS (
            VALUES
                ('M-MGNT-1'), ('M-MGNT-2'), ('M-MGNT-3'),
                ('M-MGNT-8'), ('M-MGNT-10'), ('2MG')
        )
        SELECT
            s.raw_code,
            parsed.code_expression,
            parsed.quantity_position,
            parsed.parsed_quantity,
            p.product_id,
            p.company_product_code
        FROM samples s
        CROSS JOIN LATERAL common.parse_company_product_component(s.raw_code) parsed
        LEFT JOIN dim.dim_company_product_code_mapping m
          ON m.alias_code = parsed.code_expression
         AND m.quantity_position = parsed.quantity_position
         AND m.is_active
        LEFT JOIN dim.dim_influencer_product p
          ON p.product_id = m.product_id
         AND p.is_active
        ORDER BY s.raw_code
        """
    )
    parsed_samples = cursor.fetchall()
    by_raw = {row["raw_code"]: row for row in parsed_samples}
    expected_quantities = {
        "M-MGNT-1": Decimal("1"),
        "M-MGNT-2": Decimal("2"),
        "M-MGNT-3": Decimal("3"),
        "M-MGNT-8": Decimal("8"),
        "M-MGNT-10": Decimal("10"),
    }
    product_ids = set()
    for raw_code, expected_quantity in expected_quantities.items():
        row = by_raw[raw_code]
        if row["parsed_quantity"] != expected_quantity:
            raise RuntimeError(f"{raw_code}数量解析错误：{row['parsed_quantity']}")
        if row["company_product_code"] != "M-MGNT" or not row["product_id"]:
            raise RuntimeError(f"{raw_code}未归属M-MGNT：{row}")
        product_ids.add(row["product_id"])
    if len(product_ids) != 1:
        raise RuntimeError(f"M-MGNT数量族产生多个商品身份：{product_ids}")

    short_code = by_raw["2MG"]
    if (
        short_code["code_expression"] != "MG"
        or short_code["parsed_quantity"] != Decimal("2")
        or short_code["company_product_code"] != "M-MGNT"
        or short_code["product_id"] not in product_ids
    ):
        raise RuntimeError(f"2MG简写识别错误：{short_code}")

    cursor.execute(
        """
        WITH components(component_index, raw_code) AS (
            VALUES (1, 'M-MGNT-2'), (2, 'M-NXSY-3')
        ), parsed AS (
            SELECT component_index, result.*
            FROM components
            CROSS JOIN LATERAL common.parse_company_product_component(raw_code) result
        ), resolved AS (
            SELECT
                parsed.component_index,
                parsed.parsed_quantity,
                product.company_product_code
            FROM parsed
            JOIN dim.dim_company_product_code_mapping mapping
              ON mapping.alias_code = parsed.code_expression
             AND mapping.quantity_position = parsed.quantity_position
             AND mapping.is_active
            JOIN dim.dim_influencer_product product
              ON product.product_id = mapping.product_id
             AND product.is_active
        )
        SELECT
            company_product_code,
            parsed_quantity,
            ROUND(100::NUMERIC * parsed_quantity / SUM(parsed_quantity) OVER (), 2)
                AS allocated_gmv
        FROM resolved
        ORDER BY component_index
        """
    )
    paid_bundle = cursor.fetchall()
    if [row["company_product_code"] for row in paid_bundle] != ["M-MGNT", "M-NXSY"]:
        raise RuntimeError(f"2+3组合商品识别错误：{paid_bundle}")
    if [row["allocated_gmv"] for row in paid_bundle] != [Decimal("40.00"), Decimal("60.00")]:
        raise RuntimeError(f"2+3组合GMV分摊错误：{paid_bundle}")

    cursor.execute(
        f"""
        WITH components AS ({PRODUCT_COMPONENT_UNION})
        SELECT
            platform_code,
            shop_code,
            sub_order_no,
            merchant_code,
            product_spec,
            component_index,
            company_product_code,
            component_quantity,
            paid_quantity,
            gift_quantity,
            is_gift,
            allocation_weight,
            source_line_gmv_amount,
            allocated_gmv_amount,
            is_mapped
        FROM components
        WHERE merchant_code = 'M-NXSY-2+M-MLXY-2+M-RYKK-1'
          AND product_spec LIKE '%赠%'
        ORDER BY platform_code, shop_code, sub_order_no, component_index
        """
    )
    gift_rows = cursor.fetchall()
    gift_groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in gift_rows:
        gift_groups[(row["platform_code"], row["shop_code"], row["sub_order_no"])].append(row)

    validated_gift_example = None
    for key, rows in gift_groups.items():
        if [row["company_product_code"] for row in rows] != ["M-NXSY", "M-MLXY", "M-RYKK"]:
            continue
        expected_paid = [Decimal("2"), Decimal("2"), Decimal("0")]
        expected_gift = [Decimal("0"), Decimal("0"), Decimal("1")]
        if [row["paid_quantity"] for row in rows] != expected_paid:
            continue
        if [row["gift_quantity"] for row in rows] != expected_gift:
            continue
        source_gmv = rows[0]["source_line_gmv_amount"]
        expected_allocations = [source_gmv / 2, source_gmv / 2, Decimal("0")]
        if [row["allocated_gmv_amount"] for row in rows] != expected_allocations:
            continue
        if not all(row["is_mapped"] for row in rows):
            continue
        validated_gift_example = {
            "platform_code": key[0],
            "shop_code": key[1],
            "sub_order_no": key[2],
            "source_gmv": source_gmv,
            "allocations": [row["allocated_gmv_amount"] for row in rows],
        }
        break
    if validated_gift_example is None:
        raise RuntimeError("真实订单中未找到符合2+2付费、1赠品且赠品GMV为0的验收样例")

    cursor.execute(
        f"""
        WITH components AS ({PRODUCT_COMPONENT_UNION})
        SELECT
            COUNT(*) FILTER (WHERE is_gift AND allocated_gmv_amount <> 0) AS bad_gift_gmv,
            COUNT(*) FILTER (WHERE is_gift AND allocation_weight <> 0) AS bad_gift_weight,
            COUNT(*) FILTER (WHERE paid_quantity > 0 AND gift_quantity > 0) AS mixed_components,
            COUNT(*) AS component_rows,
            COUNT(*) FILTER (WHERE is_gift) AS gift_component_rows
        FROM components
        """
    )
    gift_invariants = cursor.fetchone()
    if gift_invariants["bad_gift_gmv"] or gift_invariants["bad_gift_weight"]:
        raise RuntimeError(f"赠品分摊约束失败：{gift_invariants}")

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE mapping_status = 'partial') AS partial_rows,
            COUNT(*) FILTER (WHERE mapping_status = 'unmapped') AS unmapped_rows,
            COUNT(*) FILTER (WHERE mapping_status = 'mapped') AS mapped_rows,
            COUNT(*) FILTER (WHERE mapping_status = 'inactive') AS inactive_rows
        FROM common.v_operating_sales_product_code_observation
        """
    )
    mapping_status = cursor.fetchone()
    if mapping_status["partial_rows"]:
        raise RuntimeError(f"统一映射工作台仍存在partial：{mapping_status}")

    cursor.execute(
        """
        SELECT
            product.company_product_code,
            product.product_type,
            mapping.quantity_position,
            mapping.mapping_kind
        FROM dim.dim_influencer_product product
        JOIN dim.dim_company_product_code_mapping mapping
          ON mapping.product_id = product.product_id
         AND mapping.is_active
        WHERE product.company_product_code IN (
            'A1', 'B2', 'C3', 'TMALL-PREORDER-VOUCHER', 'M-MHB'
        )
        ORDER BY product.company_product_code, mapping.mapping_id
        """
    )
    special_code_rows = cursor.fetchall()
    special_types = {
        row["company_product_code"]: row["product_type"]
        for row in special_code_rows
    }
    expected_special_types = {
        "A1": "non_product",
        "B2": "non_product",
        "C3": "non_product",
        "TMALL-PREORDER-VOUCHER": "non_product",
        "M-MHB": "promotion",
    }
    if special_types != expected_special_types:
        raise RuntimeError(
            f"购物金、预定有价券或红包规则缺失/类型错误：{special_code_rows}"
        )

    cursor.execute(
        f"""
        WITH components AS ({PRODUCT_COMPONENT_UNION})
        SELECT code_expression, quantity_position, COUNT(DISTINCT company_product_id) AS product_count
        FROM components
        WHERE is_mapped
        GROUP BY code_expression, quantity_position
        HAVING COUNT(DISTINCT company_product_id) <> 1
        """
    )
    ambiguous_expressions = cursor.fetchall()
    if ambiguous_expressions:
        raise RuntimeError(f"同一编码表达命中多个公司商品：{ambiguous_expressions[:5]}")

    cursor.execute(
        f"""
        WITH components AS ({PRODUCT_COMPONENT_UNION})
        SELECT
            COUNT(DISTINCT company_product_id) AS product_count,
            ARRAY_AGG(DISTINCT platform_code ORDER BY platform_code) AS platform_codes,
            ARRAY_AGG(DISTINCT merchant_code_component ORDER BY merchant_code_component)
                AS observed_codes
        FROM components
        WHERE code_expression = 'M-MGNT'
          AND component_quantity = 2
          AND is_mapped
        """
    )
    cross_platform_quantity = cursor.fetchone()
    if cross_platform_quantity["product_count"] != 1:
        raise RuntimeError(
            f"M-MGNT数量2跨平台产生多个商品身份：{cross_platform_quantity}"
        )

    cursor.execute(
        """
        SELECT product_id, company_product_code
        FROM dim.dim_influencer_product
        WHERE product_id LIKE 'PRD-MANUAL-%'
           OR (
               product_id NOT LIKE 'PRD-TMALL-%'
               AND product_id <> 'PRD-RED-ENVELOPE'
               AND product_id !~ '^PRD-CODE-[0-9A-F]{16}$'
           )
        ORDER BY product_id
        """
    )
    invalid_product_ids = cursor.fetchall()
    if invalid_product_ids:
        raise RuntimeError(f"公司商品仍存在非统一ID：{invalid_product_ids}")

    cursor.execute(
        """
        SELECT product_id, company_product_code
        FROM dim.dim_influencer_product
        WHERE company_product_code = 'M-CHK'
        """
    )
    black_coffee = cursor.fetchone()
    if not black_coffee or black_coffee["product_id"] != "PRD-CODE-3EF49F8208684BEB":
        raise RuntimeError(f"黑咖啡商品ID未迁移为短格式：{black_coffee}")

    cursor.execute(
        """
        SELECT
            raw_merchant_code_component,
            normalization_rule_id,
            merchant_code_component,
            company_product_code,
            component_quantity,
            paid_quantity,
            gift_quantity,
            allocated_gmv_amount,
            is_mapped
        FROM dws.dws_jd_operating_sales_product_allocation
        WHERE raw_merchant_code_component = 'M-RYKK-1M-NXSY-XD-1'
        ORDER BY component_index
        """
    )
    jd_repaired_components = cursor.fetchall()
    if [row["merchant_code_component"] for row in jd_repaired_components] != [
        "M-RYKK-1", "M-NXSY-XD-1"
    ]:
        raise RuntimeError(f"京东漏分隔编码未拆为两个组件：{jd_repaired_components}")
    if [row["company_product_code"] for row in jd_repaired_components] != [
        "M-RYKK", "M-NXSY-XD"
    ]:
        raise RuntimeError(f"京东修正组件商品归属错误：{jd_repaired_components}")
    if any(
        not row["normalization_rule_id"]
        or not row["is_mapped"]
        or row["paid_quantity"] != 0
        or row["gift_quantity"] != Decimal("1")
        or row["allocated_gmv_amount"] != 0
        for row in jd_repaired_components
    ):
        raise RuntimeError(f"京东修正组件赠品或GMV语义错误：{jd_repaired_components}")

    return {
        "quantity_family": parsed_samples,
        "stable_product_id": next(iter(product_ids)),
        "paid_bundle_example": paid_bundle,
        "gift_example": validated_gift_example,
        "gift_invariants": gift_invariants,
        "mapping_status": mapping_status,
        "special_codes": special_code_rows,
        "cross_platform_quantity": cross_platform_quantity,
        "ambiguous_expression_count": len(ambiguous_expressions),
        "black_coffee": black_coffee,
        "jd_repaired_components": jd_repaired_components,
    }


def json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"不支持JSON序列化：{type(value)!r}")


def main() -> None:
    args = build_parser().parse_args()
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            result = validate(cursor)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
