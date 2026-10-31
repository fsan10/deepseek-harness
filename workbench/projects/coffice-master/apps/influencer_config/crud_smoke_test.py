#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对本地达人配置服务执行可回滚的增删改查冒烟测试。"""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from server import ASSIGNMENT_REFRESH_FILES, Database


BASE_URL = "http://127.0.0.1:8765"
TEST_MONTH = "2099-12"
ORIGINAL_ID = "__codex_crud_test_original__"
RENAMED_ID = "__codex_crud_test_renamed__"


def request_json(path: str, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "接口调用失败")
    return result["data"]


def cleanup(database: Database) -> None:
    connection = database.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM dim.dim_influencer_business_assignment_monthly
                WHERE influencer_id IN (%s, %s)
                """,
                (ORIGINAL_ID, RENAMED_ID),
            )
            database.execute_files(cursor, ASSIGNMENT_REFRESH_FILES)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    database = Database(
        argparse.Namespace(
            host=os.getenv("PGHOST", "192.168.77.111"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"),
        )
    )
    cleanup(database)
    try:
        businesses = request_json("/api/businesses")
        owner_id = next(item["business_owner_id"] for item in businesses if item["is_active"])
        base_payload = {
            "platform_code": "douyin",
            "influencer_id": ORIGINAL_ID,
            "influencer_name": "CRUD测试达人",
            "effective_month": f"{TEST_MONTH}-01",
            "business_owner_id": owner_id,
            "source_shop_names": ["测试店铺A", "测试店铺B"],
            "note": "新增测试",
        }
        request_json("/api/assignments", "POST", base_payload)

        query = urlencode({"month": TEST_MONTH, "search": ORIGINAL_ID})
        created = request_json(f"/api/influencers?{query}")
        assert len(created["rows"]) == 1
        assert created["rows"][0]["source_shop_names"] == ["测试店铺A", "测试店铺B"]

        updated_payload = {
            **base_payload,
            "influencer_name": "CRUD测试达人（已修改）",
            "source_shop_names": "测试店铺C\n测试店铺D",
            "note": "修改测试",
            "original_platform_code": "douyin",
            "original_influencer_id": ORIGINAL_ID,
        }
        request_json("/api/assignments", "POST", updated_payload)
        updated = request_json(f"/api/influencers?{query}")
        assert updated["rows"][0]["influencer_name"] == "CRUD测试达人（已修改）"
        assert updated["rows"][0]["source_shop_names"] == ["测试店铺C", "测试店铺D"]

        renamed_payload = {**updated_payload, "influencer_id": RENAMED_ID}
        request_json("/api/assignments", "POST", renamed_payload)
        original_after_rename = request_json(f"/api/influencers?{query}")
        assert original_after_rename["rows"] == []
        renamed_query = urlencode({"month": TEST_MONTH, "search": RENAMED_ID})
        renamed = request_json(f"/api/influencers?{renamed_query}")
        assert len(renamed["rows"]) == 1

        delete_query = urlencode(
            {"month": TEST_MONTH, "platform": "douyin", "influencer_id": RENAMED_ID}
        )
        request_json(f"/api/influencers?{delete_query}", "DELETE")
        deleted = request_json(f"/api/influencers?{renamed_query}")
        assert deleted["rows"] == []
        print("CRUD冒烟测试通过：新增、查询、修改、UID变更、删除均符合预期")
    finally:
        try:
            cleanup(database)
        finally:
            database.close(drain=False)


if __name__ == "__main__":
    main()
