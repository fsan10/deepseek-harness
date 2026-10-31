"""Load integration settings into this process only; never alter user settings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ...runtime.storage import PROJECT


def legacy_root() -> Path:
    return Path(os.environ.get("COMMERCE_LEGACY_ROOT") or PROJECT.parent).resolve()


def prepare() -> Path:
    root = legacy_root()
    # Borrowing source modules must not create bytecode outside this project.
    sys.dont_write_bytecode = True
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    env_file = Path(os.environ.get("COMMERCE_ENV_FILE") or root / ".env")
    if env_file.is_file():
        values = {}
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ")
            if not key.replace("_", "").isalnum():
                continue
            value = value.strip()
            if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
                value = value[1:-1]
            values[key] = value
        requested = {"CLOAK_MCP_URL", "AUTOMATION_RELAY_URL", "AUTOMATION_RELAY_TOKEN_ENV",
                     "AUTOMATION_ROBOT_TOKEN", "INGEST_ROBOT_TOKEN", "PGHOST", "PGPORT",
                     "PGDATABASE", "PGUSER", "PGPASSWORD", "AI_CONFIG_ENCRYPTION_KEY"}
        requested.add(values.get("AUTOMATION_RELAY_TOKEN_ENV", "AUTOMATION_ROBOT_TOKEN"))
        requested.update(key for key in values if key.startswith(("TMALL_", "DOUYIN_", "JD_", "PDD_", "KUAISHOU_", "XHS_")))
        for key in requested:
            if key in values:
                os.environ.setdefault(key, values[key])
    return root
