# Kefu launcher (ASCII only). Requires node_modules created by workbench/scripts/bootstrap.ps1.
$ErrorActionPreference = "Stop"
$Unit = Split-Path $PSScriptRoot -Parent
Set-Location $Unit
$Next = Join-Path $Unit "node_modules\next\dist\bin\next"
if (-not (Test-Path $Next)) {
  Write-Error "missing node_modules: run workbench/scripts/bootstrap.ps1 kefu first"
  exit 1
}
& node $Next dev -p 3100 -H 127.0.0.1
