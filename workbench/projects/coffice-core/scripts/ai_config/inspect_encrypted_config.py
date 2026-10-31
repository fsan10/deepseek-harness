"""Read-only check for AI configuration rows protected by the master key."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.ai_analysis.crypto import SecretCipher


TABLE_CHECKS = {
    "ai.provider_config": "api_key_ciphertext IS NOT NULL AND deleted_at IS NULL",
    "ai.data_source": "password_ciphertext IS NOT NULL AND deleted_at IS NULL",
    "ai.feishu_app": "app_secret_ciphertext IS NOT NULL AND deleted_at IS NULL",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="只读检查AI配置密文数量")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--validate-current-key",
        action="store_true",
        help="仅报告当前进程主密钥能否解密全部现存配置，不输出明文",
    )
    args = parser.parse_args()

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        application_name="coffice_ai_secret_readonly_check",
    )
    connection.set_session(readonly=True, autocommit=True)
    result: dict[str, int] = {}
    validated_secret_count = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]
            for table, predicate in TABLE_CHECKS.items():
                cursor.execute("SELECT to_regclass(%s)", (table,))
                if cursor.fetchone()[0] is None:
                    result[table] = 0
                    continue
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {predicate}")
                result[table] = int(cursor.fetchone()[0])
            if args.validate_current_key:
                cipher = SecretCipher()
                if result["ai.provider_config"]:
                    cursor.execute(
                        """
                        SELECT config_code, api_key_ciphertext, api_key_nonce
                        FROM ai.provider_config
                        WHERE api_key_ciphertext IS NOT NULL AND deleted_at IS NULL
                        """
                    )
                    for config_code, ciphertext, nonce in cursor.fetchall():
                        cipher.decrypt(ciphertext, nonce, context=f"provider:{config_code}")
                        validated_secret_count += 1
                if result["ai.data_source"]:
                    cursor.execute(
                        """
                        SELECT source_code, password_ciphertext, password_nonce
                        FROM ai.data_source
                        WHERE password_ciphertext IS NOT NULL AND deleted_at IS NULL
                        """
                    )
                    for source_code, ciphertext, nonce in cursor.fetchall():
                        cipher.decrypt(ciphertext, nonce, context=f"data-source:{source_code}")
                        validated_secret_count += 1
                if result["ai.feishu_app"]:
                    cursor.execute(
                        """
                        SELECT config_code,
                               app_secret_ciphertext, app_secret_nonce,
                               verification_token_ciphertext, verification_token_nonce,
                               encrypt_key_ciphertext, encrypt_key_nonce
                        FROM ai.feishu_app
                        WHERE app_secret_ciphertext IS NOT NULL AND deleted_at IS NULL
                        """
                    )
                    labels = ("app-secret", "verification-token", "encrypt-key")
                    for row in cursor.fetchall():
                        config_code = row[0]
                        for index, label in enumerate(labels):
                            ciphertext, nonce = row[1 + index * 2 : 3 + index * 2]
                            if ciphertext is None:
                                continue
                            cipher.decrypt(
                                cipher.decode(ciphertext),
                                cipher.decode(nonce),
                                context=f"feishu:{config_code}:{label}",
                            )
                            validated_secret_count += 1
    finally:
        connection.close()
    print(
        json.dumps(
            {
                "database": database,
                "encrypted_rows": result,
                "current_key_validated": args.validate_current_key,
                "validated_secret_count": validated_secret_count,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
