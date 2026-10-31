"""联邦单元的零依赖 HTTP 外壳（标准库实现，不引入任何第三方包）。

每个单元自带 `service/unit.json` 描述它拥有哪些模块与资产；这个脚本只负责
把「单元是否健康、手里有什么」如实回答出来，不代行业务逻辑。

用法：python service/app.py --port 8791
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STARTED_AT = time.time()
SKIP = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".next", "var", "outputs"}
UNIT_PATH = ""


def unit_root() -> str:
    """单元根目录：由入口脚本通过 WB_UNIT_ROOT 显式传入，避免外壳猜路径。"""
    env = os.environ.get("WB_UNIT_ROOT")
    if env:
        return os.path.abspath(env)
    return os.getcwd()


def load_unit() -> dict:
    path = os.path.join(unit_root(), "service", "unit.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def scan(rel: str) -> dict:
    """统计一个相对目录的文件数、字节数与最近修改时间。"""
    base = os.path.join(unit_root(), rel)
    files = 0
    size = 0
    latest = 0.0
    if not os.path.isdir(base):
        return {"path": rel, "exists": False, "files": 0, "bytes": 0, "latest": None}
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for name in names:
            full = os.path.join(root, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            files += 1
            size += stat.st_size
            latest = max(latest, stat.st_mtime)
    return {
        "path": rel,
        "exists": True,
        "files": files,
        "bytes": size,
        "latest": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest)) if latest else None,
    }


def build_health() -> dict:
    unit = load_unit()
    modules = []
    for module in unit.get("modules", []):
        info = scan(module["path"])
        modules.append({"name": module.get("name", module["path"]), "kind": module.get("kind", "模块"), **info})
    ok = all(item["exists"] for item in modules)
    return {
        "ok": ok,
        "unit": unit["id"],
        "title": unit.get("title", unit["id"]),
        "port": unit.get("port"),
        "modules": modules,
        "uptimeSec": round(time.time() - STARTED_AT, 1),
        "clock": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def build_summary() -> dict:
    unit = load_unit()
    health = build_health()
    assets = [scan(path) for path in unit.get("assets", [])]
    return {
        "unit": unit["id"],
        "title": unit.get("title", unit["id"]),
        "domain": unit.get("domain", ""),
        "owner": unit.get("owner", ""),
        "splitFrom": unit.get("splitFrom", ""),
        "modules": health["modules"],
        "assets": assets,
        "totals": {
            "files": sum(item["files"] for item in health["modules"]) + sum(item["files"] for item in assets),
            "modules": len(health["modules"]),
        },
        "handoff": unit.get("handoff", []),
    }


LANDING = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title><style>
:root{{color-scheme:light dark}}
body{{margin:0;font:14px/1.6 system-ui,"Segoe UI",sans-serif;background:#f6f7f9;color:#1b1d22;padding:32px}}
@media (prefers-color-scheme:dark){{body{{background:#16181c;color:#e7e9ee}}}}
h1{{font-size:20px;margin:0 0 4px}}p.meta{{color:#6b7280;margin:0 0 24px}}
table{{border-collapse:collapse;width:100%;max-width:880px;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}}
@media (prefers-color-scheme:dark){{table{{background:#1e2126;border-color:#2b3037}}}}
th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid #eef0f3;font-size:13px}}
@media (prefers-color-scheme:dark){{th,td{{border-color:#2b3037}}}}
th{{color:#6b7280;font-weight:500}}code{{font-family:ui-monospace,Consolas,monospace;font-size:12px}}
</style></head><body>
<h1>{title}</h1><p class="meta">{domain} · {owner} · 单元自检页（数据来自本目录文件系统）</p>
<table><tr><th>模块</th><th>路径</th><th>文件</th><th>最近修改</th></tr>{rows}</table>
<p class="meta">健康检查 <code>/health</code> · 汇总 <code>/api/summary</code> · 拆分自 <code>{split}</code></p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "dsh-workbench-unit/1.0"

    def log_message(self, fmt: str, *args) -> None:  # 安静：运行记录由工作台侧审计
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - 标准库协议名
        path = self.path.split("?")[0]
        if path == "/health":
            self.send_json(build_health())
            return
        if path == "/api/summary":
            self.send_json(build_summary())
            return
        if path in ("/", "/index.html"):
            summary = build_summary()
            rows = "".join(
                f"<tr><td>{m['name']}</td><td><code>{m['path']}</code></td><td>{m['files']}</td><td>{m['latest'] or '—'}</td></tr>"
                for m in summary["modules"]
            )
            html = LANDING.format(
                title=summary["title"],
                domain=summary["domain"],
                owner=summary["owner"],
                rows=rows,
                split=summary["splitFrom"],
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        self.send_json({"error": "not-found", "path": path}, 404)


def main() -> None:
    global UNIT_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    UNIT_PATH = unit_root()
    unit = load_unit()
    port = args.port or int(unit.get("port", 8790))
    server = ThreadingHTTPServer((args.host, port), Handler)
    print(f"[{unit['id']}] listening on http://{args.host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
