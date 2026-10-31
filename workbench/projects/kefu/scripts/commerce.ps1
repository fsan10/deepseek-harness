$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$interpreter = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $interpreter)) { throw "Run scripts\setup-reviews.ps1 first." }
Push-Location $projectRoot
try {
    & $interpreter -m automation.commerce_cli @args
    exit $LASTEXITCODE
}
finally { Pop-Location }
