<#
.SYNOPSIS
    Create or refresh the WorkSync desktop shortcut.

.DESCRIPTION
    Points a desktop shortcut at this repository's Start-WorkSync.cmd launcher and gives it
    the generated assets\worksync.ico icon, so the shortcut carries the WorkSync mark
    instead of the generic .cmd icon.

    Re-running updates the existing shortcut in place, so it is safe to repeat. The script
    fails closed: it will not create a shortcut if the launcher or the icon is missing.

.PARAMETER Name
    Shortcut name without the .lnk extension. Defaults to "WorkSync".

.PARAMETER LauncherPath
    The launcher the shortcut starts. Defaults to Start-WorkSync.cmd in this repository.

.PARAMETER IconPath
    The icon the shortcut displays. Defaults to assets\worksync.ico in this repository.

.PARAMETER Location
    Folder to create the shortcut in. Defaults to the current user's Desktop.

.PARAMETER StartMenu
    Also create the shortcut under the current user's Start Menu Programs folder.

.PARAMETER Remove
    Delete the shortcut instead of creating it.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-desktop-shortcut.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-desktop-shortcut.ps1 -StartMenu

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-desktop-shortcut.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Name = 'WorkSync',
    [string]$LauncherPath,
    [string]$IconPath,
    [string]$Location,
    [switch]$StartMenu,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $LauncherPath) { $LauncherPath = Join-Path $repoRoot 'Start-WorkSync.cmd' }
if (-not $IconPath) { $IconPath = Join-Path $repoRoot 'assets\worksync.ico' }

$targets = @()
if ($Location) {
    $targets += Join-Path $Location "$Name.lnk"
} else {
    $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) "$Name.lnk"
}
if ($StartMenu) {
    $programs = Join-Path ([Environment]::GetFolderPath('Programs')) "$Name.lnk"
    if ($programs -notin $targets) { $targets += $programs }
}

$shell = New-Object -ComObject WScript.Shell

if ($Remove) {
    foreach ($target in $targets) {
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "removed $target"
        } else {
            Write-Host "not present: $target"
        }
    }
    exit 0
}

# Fail closed: a shortcut is only useful if what it starts, and what it draws, exist.
if (-not (Test-Path -LiteralPath $LauncherPath)) {
    throw "launcher not found: $LauncherPath"
}
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "icon not found: $IconPath (run: py -3 scripts\make_icon.py)"
}

foreach ($target in $targets) {
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $shortcut = $shell.CreateShortcut($target)
    $shortcut.TargetPath = $LauncherPath
    $shortcut.Arguments = ''
    $shortcut.WorkingDirectory = $repoRoot
    $shortcut.IconLocation = "$IconPath,0"
    $shortcut.Description = 'WorkSync workspace'
    # 7 = minimized: the launcher only spawns the GUI and exits, so its console should not flash.
    $shortcut.WindowStyle = 7
    $shortcut.Save()

    $written = $shell.CreateShortcut($target)
    Write-Host "wrote $target"
    Write-Host "  target      : $($written.TargetPath)"
    Write-Host "  working dir : $($written.WorkingDirectory)"
    Write-Host "  icon        : $($written.IconLocation)"
}
exit 0
