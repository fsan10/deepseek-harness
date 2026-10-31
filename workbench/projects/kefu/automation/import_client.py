#!/usr/bin/env python3
"""客服数据台批量导入客户端，仅使用 Python 标准库。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:3000/api/import"
BATCH_SIZE = 200


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def send_batch(url: str, api_key: str, records: list[dict[str, str]], dry_run: bool) -> dict:
    request_id = f"python-{uuid.uuid4().hex[:16]}"
    payload = json.dumps({"requestId": request_id, "dryRun": dry_run, "records": records}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {api_key}",
        "X-Request-Id": request_id,
    }

    for attempt in range(3):
        try:
            with urlopen(Request(url, data=payload, headers=headers, method="POST"), timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"HTTP {error.code}: {body}") from error
        except URLError as error:
            if attempt == 2:
                raise RuntimeError(f"网络请求失败: {error}") from error
        time.sleep(2 ** attempt)
    raise RuntimeError("导入失败")


def main() -> int:
    parser = argparse.ArgumentParser(description="把 CSV 批量导入客服数据台")
    parser.add_argument("--file", required=True, type=Path, help="UTF-8 CSV 文件")
    parser.add_argument("--url", default=os.getenv("KEFU_API_URL", DEFAULT_URL))
    parser.add_argument("--api-key", default=os.getenv("KEFU_API_KEY"))
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写入数据库")
    args = parser.parse_args()

    if not args.api_key:
        parser.error("请通过 --api-key 参数或 KEFU_API_KEY 环境变量提供导入密钥")

    records = read_csv(args.file)
    if not records:
        print("CSV 没有数据", file=sys.stderr)
        return 2

    total = 0
    for offset in range(0, len(records), BATCH_SIZE):
        batch = records[offset: offset + BATCH_SIZE]
        result = send_batch(args.url, args.api_key, batch, args.dry_run)
        if not result.get("ok"):
            raise RuntimeError(json.dumps(result, ensure_ascii=False))
        total += int(result.get("processed", result.get("valid", 0)))
        print(f"批次 {offset // BATCH_SIZE + 1}: {json.dumps(result, ensure_ascii=False)}")

    print(f"完成，共处理 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
