# Registers a Windows Task Scheduler job that runs the watcher every N minutes.
# Run this from an elevated or normal PowerShell prompt (elevated recommended):
#   .\scripts\register_task_scheduler.ps1 -IntervalMinutes 2

param(
    [int]$IntervalMinutes = 2,
    [string]$TaskName = "TicketWatchdog"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = (Get-Command python).Source
$WatcherScript = Join-Path $ProjectRoot "src\watcher.py"

$Action = New-ScheduledTaskAction -Execute $PythonExe `
    -Argument "`"$WatcherScript`" --config `"$ProjectRoot\config.json`" --state `"$ProjectRoot\state.json`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force

Write-Host "Registered task '$TaskName' running every $IntervalMinutes minute(s)."
Write-Host "Manage it in Task Scheduler, or remove with: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
