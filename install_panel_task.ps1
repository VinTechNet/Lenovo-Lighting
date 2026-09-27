<#
.SYNOPSIS
    Register (or remove) the control panel as a hidden-to-tray logon task.

.DESCRIPTION
    Starts control_panel.py minimised to the system tray at logon, so the
    tray icon is always there to switch animation or screen. No admin needed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_panel_task.ps1
    powershell -ExecutionPolicy Bypass -File install_panel_task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "MusicVisualiserPanel"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task '$TaskName'."
    }
    else {
        Write-Output "No scheduled task named '$TaskName'."
    }
    return
}

$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$script = Join-Path $scriptDir "control_panel.py"
if (-not (Test-Path $script)) { throw "Cannot find $script" }

$log = Join-Path $scriptDir "control_panel.log"
$arguments = "`"$script`" --hidden --log `"$log`""

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT25S"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Output "Registered '$TaskName' (starts hidden in the tray):"
Write-Output "  $pythonw $arguments"
Write-Output ""
Write-Output "Remove with:  install_panel_task.ps1 -Uninstall"
