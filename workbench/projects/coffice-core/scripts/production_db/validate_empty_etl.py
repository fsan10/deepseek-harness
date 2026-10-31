"""Run every enabled ETL against the empty production schema and capture results."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs/production_database/empty_etl_validation.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证启用ETL从空正式库启动时的行为")
    add_connection_arguments(parser)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser


def load_registry():
    path = ROOT / "apps/file_ingest/registry.py"
    spec = importlib.util.spec_from_file_location("empty_etl_validation_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载ETL注册表")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tail(value: str, limit: int = 4000) -> str:
    value = value.strip()
    return value[-limit:] if len(value) > limit else value


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    assert_not_source_database(str(kwargs["dbname"]))
    registry = load_registry()
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": str(kwargs["host"]),
            "PGPORT": str(kwargs["port"]),
            "PGDATABASE": str(kwargs["dbname"]),
            "PGUSER": str(kwargs["user"]),
            "PGPASSWORD": str(kwargs.get("password") or ""),
            "PYTHONUTF8": "1",
        }
    )
    specs = sorted(
        (item for item in registry.ETL_SPECS.values() if item.enabled),
        key=lambda item: (item.priority, item.key),
    )
    results = []
    for spec in specs:
        command = [sys.executable, str(ROOT / spec.script), *spec.args]
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout_seconds,
                check=False,
            )
            results.append(
                {
                    "etl_key": spec.key,
                    "label": spec.label,
                    "script": spec.script,
                    "exit_code": completed.returncode,
                    "status": "success" if completed.returncode == 0 else "failed",
                    "stdout_tail": tail(completed.stdout),
                    "stderr_tail": tail(completed.stderr),
                }
            )
        except subprocess.TimeoutExpired as exc:
            results.append(
                {
                    "etl_key": spec.key,
                    "label": spec.label,
                    "script": spec.script,
                    "exit_code": None,
                    "status": "timeout",
                    "stdout_tail": tail((exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
                    "stderr_tail": tail((exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")),
                }
            )
    report = {
        "database": kwargs["dbname"],
        "enabled_etl_count": len(specs),
        "success_count": sum(item["status"] == "success" for item in results),
        "failed_count": sum(item["status"] == "failed" for item in results),
        "timeout_count": sum(item["status"] == "timeout" for item in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("database", "enabled_etl_count", "success_count", "failed_count", "timeout_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
