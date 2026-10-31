param(
    [switch]$CreateDatabase,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ComposeFile = Join-Path $PSScriptRoot 'compose.yml'
$EnvFile = Join-Path $ProjectRoot '.env'

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "缺少 $EnvFile，请先复制 deploy/production/.env.example 为 .env 并填写真实值。"
}

$composeArgs = @('compose', '--env-file', $EnvFile, '-f', $ComposeFile)
& docker @composeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 配置校验失败。' }

if (-not $SkipBuild) {
    $buildRevision = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
    & docker @composeArgs build --build-arg "COFFICE_BUILD_REV=$buildRevision"
    if ($LASTEXITCODE -ne 0) { throw 'Docker 镜像构建失败。' }
}

if ($CreateDatabase) {
    & docker @composeArgs --profile tools run --rm create-db
    if ($LASTEXITCODE -ne 0) { throw '正式数据库创建失败。' }
}

& docker @composeArgs up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { throw '服务启动失败。' }

& docker @composeArgs ps
Write-Host '部署命令已完成。请等待 web 状态变为 healthy，再访问经营配置中心。'
