"""独立 CLI 只从 .env.local 加载本功能需要的非密钥配置。"""
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = {"KEFU_DB_PATH", "MOCK_COFFICE_ROOT", "CLOAK_MCP_URL", "COLLECTION_AUTH_DIR", "REVIEWS_AUTH_DIR", "METRICS_AUTH_DIR", "IMPORT_API_KEY", "KEFU_IMPORT_BASE_URL", "COLLECTION_ALERT_CONFIG_PATH"}


def load_runtime_env(path: Path | None = None):
    path = path or PROJECT / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in CONFIG_KEYS:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)
