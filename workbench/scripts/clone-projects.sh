#!/usr/bin/env bash
# 物理克隆三个源项目到 workbench/projects（源目录只读，不做任何改动）。
# 排除项：版本库、虚拟环境、依赖树、构建产物、缓存、密钥文件。
# 数据文件（sqlite）单独补拷，保证工作台首版能读到真实数据。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_ROOT="/d/fsan10"
DEST="$ROOT/projects"

log() { printf '[clone] %s\n' "$*"; }

# robocopy 退出码 0-7 视为成功
rcopy() {
  local name="$1"; shift
  log "start $name"
  cmd //c robocopy "$@" /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
  local code=$?
  if [ "$code" -ge 8 ]; then
    log "FAILED $name (robocopy exit $code)"
    return 1
  fi
  log "done $name"
}

# ── 1. mock_coffice：一体式平台，完整保留为 coffice-core ────────────────────
rcopy "coffice-core" \
  "$SRC_ROOT\\mock_coffice" "$DEST\\coffice-core" \
  /XD .git .venv __pycache__ .pytest_cache .tmp .tmp_monthly_performance \
      .tmp_monthly_report .tmp_sept_report .codex_tmp .uploads node_modules outputs \
  /XF .env .env.bak-20261010-frp-000822 *.pyc

# ── 2. 直播运营：FastAPI + SQLite ───────────────────────────────────────────
rcopy "liveops" \
  "$SRC_ROOT\\直播运营" "$DEST\\liveops" \
  /XD .git .venv node_modules __pycache__ .pytest_cache .ruff_cache .npm-cache artifacts var \
  /XF .env *.pyc

mkdir -p "$DEST/liveops/var"
for f in liveops.sqlite3 liveops.sqlite3-shm liveops.sqlite3-wal; do
  if [ -f "$SRC_ROOT/直播运营/var/$f" ]; then
    cp "$SRC_ROOT/直播运营/var/$f" "$DEST/liveops/var/$f"
    log "copied var/$f"
  fi
done

# ── 3. kefu：Next.js 客服工作台 ─────────────────────────────────────────────
rcopy "kefu" \
  "$SRC_ROOT\\kefu" "$DEST\\kefu" \
  /XD .git node_modules .next .next-build .venv __pycache__ .wrangler outputs .openai \
  /XF tsconfig.tsbuildinfo .env.local *.pyc

log "all done"
