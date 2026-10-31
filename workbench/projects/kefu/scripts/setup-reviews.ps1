param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($Python) {
        & $Python -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $projectRoot ".venv")
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $projectRoot ".venv")
    }
    else {
        throw "Python 3.12 was not found. Install it or pass -Python with its absolute path."
    }
    if ($LASTEXITCODE -ne 0) { throw "Creating the kefu virtual environment failed." }
}

Write-Host "Installing review collector dependencies into kefu\.venv..." -ForegroundColor Cyan
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements-reviews.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing review collector dependencies failed." }
& $venvPython -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Shanghai')"
if ($LASTEXITCODE -ne 0) { throw "The Asia/Shanghai timezone data is missing. Reinstall requirements-reviews.txt." }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv\Scripts\pythonw.exe"))) {
    throw "pythonw.exe is missing. Recreate the virtual environment with the official Windows Python installer."
}
Write-Host "The kefu review runtime is ready. No service was started." -ForegroundColor Green
