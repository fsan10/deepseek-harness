"""Create the configured first super administrator without resetting it later."""

from __future__ import annotations

import os
from pathlib import Path

from apps.fund_split_adjust.database import Database
from apps.identity_access.module import IdentityAccessModule
from apps.identity_access.security import normalize_username


def main() -> int:
    username = normalize_username(os.getenv("INITIAL_ADMIN_USERNAME", ""))
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    display_name = os.getenv("INITIAL_ADMIN_DISPLAY_NAME", "超级管理员")
    if not username or not password:
        raise SystemExit("必须设置INITIAL_ADMIN_USERNAME和INITIAL_ADMIN_PASSWORD")
    database = Database(
        host=os.getenv("PGHOST", "192.168.77.111"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "coffice_production"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        upload_dir=Path(os.getenv("INGEST_FILE_ROOT", "/tmp/coffice-init")),
    )
    with database.transaction() as cursor:
        cursor.execute("SELECT user_id FROM iam.user_account WHERE username=%s", (username,))
        if cursor.fetchone():
            print(f"初始管理员已存在，保持原密码：{username}")
            return 0
    result = IdentityAccessModule(database).auth.initialize_super_admin(username, password, display_name)
    print(f"已创建初始超级管理员：{result['username']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
