[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)

$ErrorActionPreference = 'Stop'
$commerceRoot = $PSScriptRoot
$commerceCandidates = @(
    (Join-Path $commerceRoot '.venv\Scripts\python.exe'),
    (Join-Path (Split-Path $commerceRoot -Parent) '.venv\Scripts\python.exe')
)
$commerceInterpreter = $commerceCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $commerceInterpreter) { throw '未找到 Python 3.12 项目虚拟环境；请先准备本项目 .venv。' }
$commerceExitCode = 1
Push-Location (Split-Path $commerceRoot -Parent)
try {
    & $commerceInterpreter -B -m commerce_api --runtime-dir (Join-Path $commerceRoot '.runtime') @CliArgs
    $commerceExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $commerceExitCode
