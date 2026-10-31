# Workbench dependency bootstrap (ASCII only, PowerShell 5.1 safe).
#
# Usage:
#   .\scripts\bootstrap.ps1            # install for all projects
#   .\scripts\bootstrap.ps1 liveops
#   .\scripts\bootstrap.ps1 kefu
#
# The coffice units are stdlib-only Python and need no install step.

param([string]$Target = 'all')

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Projects = Join-Path $Root 'projects'

function Install-Liveops {
    $dir = Join-Path $Projects 'liveops'
    if (-not (Test-Path $dir)) { Write-Host 'liveops: not cloned, skip'; return }
    Push-Location $dir
    try {
        if (-not (Test-Path '.venv')) { python -m venv .venv }
        $py = Join-Path $dir '.venv\Scripts\python.exe'
        & $py -m pip install --disable-pip-version-check -q fastapi "uvicorn[standard]" sqlalchemy "httpx[socks]" cryptography python-dotenv tzdata python-multipart openpyxl defusedxml
        & $py -m pip install -q -e . --no-deps
        Write-Host 'liveops: ready'
    } finally { Pop-Location }
}

function Install-Kefu {
    $dir = Join-Path $Projects 'kefu'
    if (-not (Test-Path $dir)) { Write-Host 'kefu: not cloned, skip'; return }
    Push-Location $dir
    try {
        if (-not (Test-Path 'node_modules')) { npm ci --no-audit --no-fund }
        Write-Host 'kefu: ready'
    } finally { Pop-Location }
}

switch ($Target) {
    'liveops' { Install-Liveops }
    'kefu'    { Install-Kefu }
    'all'     { Install-Liveops; Install-Kefu; Write-Host 'coffice-*: stdlib only, nothing to install' }
    default   { Write-Error "unknown target: $Target (use liveops | kefu | all)" }
}
