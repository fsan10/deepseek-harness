param(
    [ValidateRange(1, 65535)]
    [int]$Port = 3000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env.local"))) {
    throw ".env.local is missing. Run scripts\setup-local.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".next"))) {
    throw "The production build is missing. Run scripts\setup-local.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv\Scripts\pythonw.exe"))) {
    throw "The kefu Python environment is missing. Run scripts\setup-reviews.ps1 first."
}

$env:PORT = $Port
Write-Host "Starting the customer service dashboard..." -ForegroundColor Green
Write-Host "Local URL: http://localhost:$Port"

$addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -Unique
foreach ($address in $addresses) {
    Write-Host "LAN URL: http://${address}:$Port"
}
Write-Host "Press Ctrl+C to stop the server."

& npm run start:lan
if ($LASTEXITCODE -ne 0) { throw "The server exited with code $LASTEXITCODE." }
