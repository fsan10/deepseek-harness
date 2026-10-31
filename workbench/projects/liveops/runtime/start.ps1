# Liveops launcher (ASCII only). Requires .venv created by workbench/scripts/bootstrap.ps1.
$ErrorActionPreference = "Stop"
$Unit = Split-Path $PSScriptRoot -Parent
Set-Location $Unit
$Python = Join-Path $Unit ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  Write-Error "missing .venv: run workbench/scripts/bootstrap.ps1 liveops first"
  exit 1
}
& $Python -m uvicorn liveops.app:app --host 127.0.0.1 --port 8865
