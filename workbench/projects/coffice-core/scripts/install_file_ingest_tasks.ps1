param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [string]$ProjectRoot = "D:\fsan10\mock_coffice",
    [string]$TaskPrefix = "MockCoffice"
)

$ErrorActionPreference = "Stop"
$resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path

$legacyNightlyTask = Get-ScheduledTask -TaskName "$TaskPrefix-FileIngest-Nightly" -ErrorAction SilentlyContinue
if ($legacyNightlyTask) {
    Unregister-ScheduledTask -InputObject $legacyNightlyTask -Confirm:$false
}

$workerAction = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument "-m apps.file_ingest.worker" `
    -WorkingDirectory $resolvedProject
$workerTrigger = New-ScheduledTaskTrigger -AtStartup
$workerSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask `
    -TaskName "$TaskPrefix-FileIngest-Worker" `
    -Action $workerAction `
    -Trigger $workerTrigger `
    -Settings $workerSettings `
    -Description "常驻处理mock_coffice文件导入和ETL任务。" `
    -Force | Out-Null

Write-Output "已移除旧的 $TaskPrefix-FileIngest-Nightly（如存在），并注册 $TaskPrefix-FileIngest-Worker。ETL定时任务由 Automation Workbench 管理。"
