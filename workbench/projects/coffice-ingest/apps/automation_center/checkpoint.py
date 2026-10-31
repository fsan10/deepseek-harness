"""Run-scoped checkpoint compatibility with the older date-scoped download controller.

A historic web Run can have successful steps in the shared CLI checkpoint.
Only import entries corroborated by that *same* Run's database history.
Never copy another Run's success just because it shares a business date.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterable


def restore_legacy_checkpoint(
    legacy_path: Path,
    run_path: Path,
    *,
    scope: str,
    successful_steps: Iterable[tuple[str, str, str]],
) -> int:
    if run_path.exists() or not legacy_path.is_file():
        return 0
    verified = {
        (str(profile), str(module), str(name))
        for profile, module, name in successful_steps
    }
    if not verified:
        return 0
    try:
        original = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(original, dict) or original.get("scope") != scope:
        return 0
    profiles = original.get("profiles")
    if not isinstance(profiles, dict):
        return 0
    filtered = {}
    count = 0
    for profile, entry in profiles.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("steps"), dict):
            continue
        completed = {
            key: value for key, value in entry["steps"].items()
            if isinstance(value, dict) and value.get("status") == "success"
            and (str(profile), str(value.get("module") or ""),
                 str(value.get("name") or "")) in verified
        }
        if not completed:
            continue
        filtered[str(profile)] = {
            key: value for key, value in entry.items()
            if key != "last_failure" and key != "steps"
        }
        filtered[str(profile)]["steps"] = completed
        count += len(completed)
    if not count:
        return 0
    original["profiles"] = filtered
    original["updated_at"] = original.get("updated_at")
    run_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = run_path.with_name(f"{run_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if run_path.exists():
            return 0
        temporary.replace(run_path)
    finally:
        temporary.unlink(missing_ok=True)
    return count
