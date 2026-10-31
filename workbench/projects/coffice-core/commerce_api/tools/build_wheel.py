"""Build in isolated owned temporary directories without changing parent deps."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from commerce_api.runtime.storage import PROJECT
from commerce_api.core.errors import redact


def main():
    root = PROJECT / ".runtime"
    root.mkdir(exist_ok=True)
    destination = root / "dist"
    destination.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="build-temp-") as temporary:
        env = {**os.environ, "TMP": temporary, "TEMP": temporary, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-B", "-m", "pip", "wheel", "--no-deps", "--no-cache-dir",
            "--wheel-dir", str(destination), str(PROJECT)], cwd=PROJECT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        if result.returncode:
            print(json.dumps({"ok": False, "exit_code": result.returncode, "diagnostic": redact(result.stderr[-600:])}))
            return result.returncode
    wheels = list(destination.glob("commerce_api_cli-*.whl"))
    if not wheels:
        raise RuntimeError("wheel not produced")
    wheel = max(wheels, key=lambda p: p.stat().st_mtime)
    with zipfile.ZipFile(wheel) as bundle:
        members = bundle.namelist()
    forbidden = [name for name in members if any(part in {".runtime", ".env", "tests", "tools", "__pycache__"} for part in name.split("/"))]
    if forbidden:
        wheel.unlink()
        raise RuntimeError("build contained forbidden runtime/development data")
    print(json.dumps({"ok": True, "wheel": str(wheel), "files": len(members), "runtime_data_included": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
