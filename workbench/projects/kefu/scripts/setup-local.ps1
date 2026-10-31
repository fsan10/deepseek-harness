$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js was not found. Install Node.js 22.13 or newer first."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Reinstall Node.js first."
}

$nodeVersionText = (& node --version).Trim().TrimStart("v")
$nodeVersion = [version]$nodeVersionText
if ($nodeVersion -lt [version]"22.13.0") {
    throw "Node.js $nodeVersionText is too old. Version 22.13.0 or newer is required."
}

$envFile = Join-Path $projectRoot ".env.local"
if (-not (Test-Path -LiteralPath $envFile)) {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $apiKey = "kf_local_" + (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
    $content = "IMPORT_API_KEY=$apiKey`r`nKEFU_DB_PATH=./data/kefu.sqlite`r`n"
    [System.IO.File]::WriteAllText($envFile, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Created .env.local with a random API key." -ForegroundColor Green
}
else {
    Write-Host ".env.local already exists and was not changed." -ForegroundColor Yellow
}

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "npm install failed." }

& (Join-Path $PSScriptRoot "setup-reviews.ps1")

Write-Host "Building the application..." -ForegroundColor Cyan
& npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed." }

Write-Host "Setup complete. Start the application with:" -ForegroundColor Green
Write-Host "powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1"
