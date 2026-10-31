"""Import/dispatch the built wheel in an isolated owned directory."""
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from commerce_api.runtime.storage import PROJECT


def main():
    directory = PROJECT / ".runtime"
    wheel = max((directory / "dist").glob("commerce_api_cli-*.whl"), key=lambda p: p.stat().st_mtime)
    with tempfile.TemporaryDirectory(dir=directory, prefix="wheel-check-") as temporary:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(temporary)
        env = {**os.environ, "PYTHONPATH": temporary, "PYTHONDONTWRITEBYTECODE": "1"}
        for args in (["--version"], ["platforms"], ["doctor"], ["schema", "tmall"]):
            result = subprocess.run([sys.executable, "-B", "-m", "commerce_api", *args],
                cwd=temporary, env=env, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                raise RuntimeError("wheel command failed: " + args[0])
            data = json.loads(result.stdout)
            if not data.get("ok"):
                raise RuntimeError("wheel command returned failure")
            if args == ["doctor"] and not all(r["available"] for r in data["data"]["reports"]):
                raise RuntimeError("wheel is missing report modules")
    print(json.dumps({"ok": True, "commands_checked": 4, "parent_dependencies_modified": False}))


if __name__ == "__main__":
    main()
