param(
    [string]$Destination = 'D:\fsan10\coffice_production_deploy'
)

$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Destination = [System.IO.Path]::GetFullPath($Destination)

if (-not $Destination.StartsWith('D:\fsan10\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "部署副本必须创建在 D:\fsan10 的明确子目录中：$Destination"
}
if (Test-Path -LiteralPath $Destination) {
    throw "目标目录已存在，为避免覆盖请先人工确认或改用新的目录名：$Destination"
}

New-Item -ItemType Directory -Path $Destination | Out-Null

function Copy-Tree([string]$RelativePath, [string[]]$ExtraExcludedDirectories = @()) {
    $from = Join-Path $Source $RelativePath
    $to = Join-Path $Destination $RelativePath
    New-Item -ItemType Directory -Path $to -Force | Out-Null
    $excluded = @('__pycache__', '.vendor', 'node_modules', 'tests', '.pytest_cache') + $ExtraExcludedDirectories
    $arguments = @($from, $to, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/XF', '*.pyc', '*.pyo')
    if ($excluded.Count -gt 0) {
        $arguments += '/XD'
        $arguments += $excluded
    }
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "复制失败：$RelativePath，robocopy=$LASTEXITCODE"
    }
}

# The application upload directories are runtime state (and may contain local
# test workbooks).  They are created by Docker volumes/Dockerfile at runtime
# and must never be copied into a portable deployment bundle.
Copy-Tree 'apps' @('uploads')
Copy-Tree 'etl'
Copy-Tree 'sql'
Copy-Tree 'scripts' @('auto_download')
Copy-Tree 'deploy'

New-Item -ItemType Directory -Path (Join-Path $Destination 'docs\deployment') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Source 'docs\deployment\production_docker_deployment.md') -Destination (Join-Path $Destination 'docs\deployment\production_docker_deployment.md')
Copy-Item -LiteralPath (Join-Path $Source 'docs\automation_api.md') -Destination (Join-Path $Destination 'docs\automation_api.md')
Copy-Item -LiteralPath (Join-Path $Source '.dockerignore') -Destination (Join-Path $Destination '.dockerignore')

$manifest = @"
# 正式部署副本清单

- 生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')
- 源项目：$Source
- 目标目录：$Destination
- 包含：apps、etl、sql、生产数据库工具、Docker部署配置、部署文档和影刀/验证码自动化 API 文档
- 排除：scripts/auto_download、data、.uploads、应用 uploads、outputs、测试目录、Windows vendor依赖、node_modules、原型项目和Git元数据
- 数据库：不包含任何数据库明文密码、数据库dump或业务数据

启动前必须复制 deploy/production/.env.example 为根目录 .env 并填写真实环境变量。
"@
Set-Content -LiteralPath (Join-Path $Destination 'DEPLOYMENT_BUNDLE_MANIFEST.md') -Value $manifest -Encoding UTF8

Write-Host "正式部署副本已生成：$Destination"
