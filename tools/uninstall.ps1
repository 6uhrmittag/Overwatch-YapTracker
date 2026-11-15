<#
.SYNOPSIS
    Remove YapTracker: the app, its shortcuts, its autostart and its Apps entry.

.DESCRIPTION
    Closes a running YapTracker, removes the "Start with Windows" entry, the Start menu
    and desktop shortcuts, the entry in Windows Settings -> Apps and <InstallRoot>\app.
    Your data (chat log, players, notes) in <InstallRoot>\data STAYS, unless you ask
    for -RemoveData: then it asks first, and offers a backup zip before deleting.
    update.ps1 puts a copy of this script in <InstallRoot>. Per user, no admin rights.
    Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\YapTracker\uninstall.ps1"
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'YapTracker'),
    # Also delete your data (chat log, players, notes). Asks first.
    [switch]$RemoveData,
    # Answer yes to every question (for scripts): with -RemoveData, back up, then delete.
    [switch]$Yes,
    # Where the backup zip goes with -RemoveData.
    [string]$BackupDir = [Environment]::GetFolderPath('MyDocuments')
)

$ErrorActionPreference = 'Stop'
$AppDir = Join-Path $InstallRoot 'app'
$DataDir = Join-Path $InstallRoot 'data'
$Exe = Join-Path $AppDir 'YapTracker.exe'
# The same names update.ps1 and the app use (autostart.py, #45).
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$AppsKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\YapTracker'
$Shortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'YapTracker.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'YapTracker.lnk')
)

function Test-Ours {
    # A shortcut or Run entry of this install, not of another copy somewhere else.
    param([string]$Text)
    return $Text -and $Text.IndexOf($AppDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Get-Answer {
    param([string]$Question)
    if ($Yes) { Write-Host "$Question yes"; return $true }
    return (Read-Host $Question) -match '^\s*y'
}

Write-Host 'Packing up YapTracker...'

# 1. Close it.
$running = @(Get-Process -Name 'YapTracker' -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and (Test-Ours $_.Path) })
foreach ($p in $running) { [void]$p.CloseMainWindow() }
foreach ($p in $running) {
    if (-not $p.WaitForExit(10000)) { Stop-Process -Id $p.Id -Force }
}
if ($running.Count -gt 0) { Write-Host '  Closed YapTracker.' }

# 2. Start with Windows: off.
$run = Get-ItemProperty -Path $RunKey -Name 'YapTracker' -ErrorAction SilentlyContinue
if ($run -and (Test-Ours $run.YapTracker)) {
    Remove-ItemProperty -Path $RunKey -Name 'YapTracker'
    Write-Host '  No more starting with Windows.'
}

# 3. Shortcuts: only the ones pointing at this install.
$shell = New-Object -ComObject WScript.Shell
foreach ($link in $Shortcuts) {
    if ((Test-Path $link) -and (Test-Ours $shell.CreateShortcut($link).TargetPath)) {
        Remove-Item -Force $link
        Write-Host "  Removed $link"
    }
}

# 4. Windows Settings -> Apps.
if (Test-Path $AppsKey) { Remove-Item -Recurse -Force $AppsKey }

# 5. The app itself (and what an interrupted update left behind).
foreach ($dir in @($AppDir, (Join-Path $InstallRoot 'app.new'), (Join-Path $InstallRoot 'app.old'))) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
}
Write-Host "  Removed the app from $AppDir"

# 6. Your data: stays, unless asked for.
if (Test-Path $DataDir) {
    if (-not $RemoveData) {
        Write-Host "Your yaps are still in $DataDir - chat log, players and notes, for a comeback."
        Write-Host 'Delete them too: run this again with -RemoveData.'
    } elseif (Get-Answer "Delete ALL your yaps, players and notes in ${DataDir}? This can't be undone. [y/N]") {
        if (Get-Answer "Back up first, as a zip in ${BackupDir}? [y/N]") {
            $zip = Join-Path $BackupDir ('YapTracker-data-{0}.zip' -f (Get-Date -Format 'yyyy-MM-dd-HHmm'))
            New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
            Compress-Archive -Path (Join-Path $DataDir '*') -DestinationPath $zip
            Write-Host "  Backed up to $zip"
        }
        Remove-Item -Recurse -Force $DataDir
        Write-Host '  Your data is gone. Clean slate.'
    } else {
        Write-Host "Kept your data in $DataDir."
    }
}

# 7. The copy of this script update.ps1 left there, and the folder if nothing else is in it.
$copy = Join-Path $InstallRoot 'uninstall.ps1'
if (Test-Path $copy) { Remove-Item -Force $copy }
if ((Test-Path $InstallRoot) -and -not (Get-ChildItem -Force $InstallRoot | Select-Object -First 1)) {
    Remove-Item -Force $InstallRoot
}
Write-Host 'YapTracker is uninstalled. GG, and thanks for all the yaps.'
