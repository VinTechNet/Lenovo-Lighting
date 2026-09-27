<#
.SYNOPSIS
    Register (or remove) the wallpaper spectrum visualiser as a logon task.

.DESCRIPTION
    Runs wallpaper.py hidden at logon. Unlike the keyboard sync this needs no
    administrator rights - it only draws on the desktop.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_wallpaper_task.ps1
    powershell -ExecutionPolicy Bypass -File install_wallpaper_task.ps1 -Uninstall
    powershell -ExecutionPolicy Bypass -File install_wallpaper_task.ps1 -Band 50 -Monitor all
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "DesktopMusicSpectrum",
    [string]$Monitor = "primary",
    [int]$Band = 38,
    [int]$Bars = 64,
    [int]$Fps = 45
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
    Get-Process python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*wallpaper.py*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    return
}

$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$script = Join-Path $scriptDir "wallpaper.py"
if (-not (Test-Path $script)) { throw "Cannot find $script" }

# Style, monitor and sizing deliberately come from settings.json (control
# panel), so they are not pinned on the command line here.
$log = Join-Path $scriptDir "wallpaper.log"
$arguments = "`"$script`" --log `"$log`""

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $scriptDir
# A short delay lets Explorer finish painting the desktop before we capture it.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT20S"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Output "Registered '$TaskName':"
Write-Output "  $pythonw $arguments"
Write-Output ""
Write-Output "Start now :  Start-ScheduledTask -TaskName $TaskName"
Write-Output "Stop      :  Stop-ScheduledTask  -TaskName $TaskName"
Write-Output "Remove    :  install_wallpaper_task.ps1 -Uninstall"
