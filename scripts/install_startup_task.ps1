$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $root "scripts\start_services.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit 0

Register-ScheduledTask `
    -TaskName "LocalFlow" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start LocalFlow dictation services at Windows logon" `
    -Force
