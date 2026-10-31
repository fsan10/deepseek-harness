# 主数据与治理 unit launcher (ASCII only).
$ErrorActionPreference = "Stop"
$Unit = Split-Path $PSScriptRoot -Parent
Set-Location $Unit
$Python = "python"
if (Test-Path (Join-Path $Unit ".venv\Scripts\python.exe")) {
  $Python = Join-Path $Unit ".venv\Scripts\python.exe"
}
& $Python (Join-Path $Unit "service\app.py") --port 8793
