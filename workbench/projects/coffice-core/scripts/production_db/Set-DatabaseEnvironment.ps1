param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('test', 'production')]
    [string]$Environment
)

$ErrorActionPreference = 'Stop'

function Set-PgVariablesFromUrl {
    param([Parameter(Mandatory = $true)][string]$DatabaseUrl)

    $uri = [System.Uri]$DatabaseUrl
    if ($uri.Scheme -notin @('postgres', 'postgresql')) {
        throw '数据库URL必须使用postgres://或postgresql://'
    }
    $userInfo = $uri.UserInfo.Split(':', 2)
    if ($userInfo.Count -lt 1 -or [string]::IsNullOrWhiteSpace($userInfo[0])) {
        throw '数据库URL缺少用户'
    }
    $env:PGHOST = $uri.Host
    $env:PGPORT = if ($uri.Port -gt 0) { [string]$uri.Port } else { '5432' }
    $env:PGDATABASE = [System.Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
    $env:PGUSER = [System.Uri]::UnescapeDataString($userInfo[0])
    if ($userInfo.Count -eq 2) {
        $env:PGPASSWORD = [System.Uri]::UnescapeDataString($userInfo[1])
    }
}

if ($Environment -eq 'production') {
    if ([string]::IsNullOrWhiteSpace($env:PRODUCTION_DATABASE_URL)) {
        throw '必须先设置PRODUCTION_DATABASE_URL，拒绝隐式连接正式库'
    }
    Set-PgVariablesFromUrl -DatabaseUrl $env:PRODUCTION_DATABASE_URL
    if ($env:PGDATABASE -eq 'mock_coffice') {
        throw 'PRODUCTION_DATABASE_URL不能指向mock_coffice'
    }
    $env:COFFICE_ENV = 'production'
}
else {
    if (-not [string]::IsNullOrWhiteSpace($env:TEST_DATABASE_URL)) {
        Set-PgVariablesFromUrl -DatabaseUrl $env:TEST_DATABASE_URL
    }
    else {
        # Keep the project's existing PGHOST/PGPORT/PGUSER defaults and only
        # restore the established development database name.
        $env:PGDATABASE = 'mock_coffice'
    }
    $env:COFFICE_ENV = 'test'
}

Write-Host ("数据库环境已切换为 {0}，目标库 {1}。" -f $env:COFFICE_ENV, $env:PGDATABASE)
