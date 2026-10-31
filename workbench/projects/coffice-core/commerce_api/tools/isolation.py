"""Snapshot/verify existing tracked files without altering any legacy file."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "commerce_api/.runtime/isolation-baseline.json"


def fingerprints() -> dict[str, str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    paths = [ROOT / p for p in result.stdout.decode("utf-8").split("\0") if p and not p.startswith("commerce_api/")]
    automations = Path.home() / ".codex/automations"
    if automations.exists():
        paths += list(automations.glob("*/automation.toml"))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "missing" for p in paths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "verify"])
    args = parser.parse_args()
    current = fingerprints()
    if args.action == "snapshot":
        if SNAPSHOT.exists():
            raise SystemExit("Existing baseline retained; use verify")
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"baseline_files": len(current)}))
        return 0
    before = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed = [p for p, digest in before.items() if current.get(p) != digest]
    print(json.dumps({"ok": not changed, "checked": len(before), "changed": changed}, ensure_ascii=False))
    return int(bool(changed))


if __name__ == "__main__":
    raise SystemExit(main())
