<#
.SYNOPSIS
    Register (or remove) the keyboard music-sync service as a logon task.

.DESCRIPTION
    Runs musiclight.py hidden at logon with highest privileges, which is
    required for --suspend-lenovo to stop Lenovo's lighting agent.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_task.ps1
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall
    powershell -ExecutionPolicy Bypass -File install_task.ps1 -Effect vu
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$TaskName = "LenovoKeyboardMusicSync",
    [ValidateSet("spectrum", "vu", "pulse", "wave")]
    [string]$Effect = "spectrum",
    [int]$Brightness = 100
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this from an elevated PowerShell (needed to register a highest-privilege task)."
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task '$TaskName'."
    }
    else {
        Write-Output "No scheduled task named '$TaskName'."
    }
    Write-Output "Restoring stock lighting..."
    & (Get-Command python).Source (Join-Path $scriptDir "restore.py")
    return
}

# pythonw runs without a console window.
$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$script = Join-Path $scriptDir "musiclight.py"
if (-not (Test-Path $script)) { throw "Cannot find $script" }

# Effect and brightness deliberately come from settings.json (control panel),
# so they are not pinned on the command line here.
$log = Join-Path $scriptDir "musiclight.log"
$arguments = "`"$script`" --suspend-lenovo --log `"$log`""

$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest
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
Write-Output "Remove    :  install_task.ps1 -Uninstall"
