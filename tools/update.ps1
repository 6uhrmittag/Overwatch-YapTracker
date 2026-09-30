<#
.SYNOPSIS
    Install or update YapTracker from the newest GitHub (pre-)release.

.DESCRIPTION
    Downloads the newest release zip, closes a running YapTracker, replaces
    <InstallRoot>\app and starts YapTracker again.
    <InstallRoot>\data (chat log, players, notes) is never touched.
    Works in Windows PowerShell 5.1 and PowerShell 7.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File update.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'YapTracker'),
    # Reinstall even if the newest release is already installed.
    [switch]$Force,
    # Do not start YapTracker afterwards.
    [switch]$NoStart,
    # Answer for "Start with Windows?" on a fresh install; Ask shows the question once.
    [ValidateSet('Ask', 'Yes', 'No')]
    [string]$Autostart = 'Ask'
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 downloads crawl while it draws the progress bar.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = '6uhrmittag/Overwatch-YapTracker'
$AppDir = Join-Path $InstallRoot 'app'
$ReleaseFile = Join-Path $AppDir 'release.txt'

function Stop-YapTracker {
    $running = @(Get-Process -Name 'YapTracker' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) })
    if ($running.Count -eq 0) { return }
    Write-Host 'Closing YapTracker...'
    foreach ($p in $running) { [void]$p.CloseMainWindow() }
    foreach ($p in $running) {
        if (-not $p.WaitForExit(10000)) { Stop-Process -Id $p.Id -Force }
    }
}

$headers = @{ 'User-Agent' = 'YapTracker-update' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }

Write-Host 'Looking for the newest YapTracker release...'
$releases = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/$Repo/releases?per_page=20"
$release = $releases | Where-Object { -not $_.draft } | Select-Object -First 1
if (-not $release) { throw "No release found on github.com/$Repo" }
$asset = $release.assets | Where-Object { $_.name -like 'YapTracker-*-win64.zip' } | Select-Object -First 1
if (-not $asset) { throw "Release $($release.tag_name) has no YapTracker-*-win64.zip" }

$installed = if (Test-Path $ReleaseFile) { (Get-Content $ReleaseFile -Raw).Trim() } else { '' }
if ($installed -eq $release.tag_name -and -not $Force) {
    Write-Host "YapTracker $installed is already the newest version."
    exit 0
}

$fresh = -not (Test-Path (Join-Path $AppDir 'YapTracker.exe'))
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
# Stage next to the app folder so the final swap is a same-drive rename.
$staged = Join-Path $InstallRoot 'app.new'
$old = Join-Path $InstallRoot 'app.old'
$zip = Join-Path ([IO.Path]::GetTempPath()) $asset.name
try {
    Write-Host "Downloading $($asset.name)..."
    Invoke-WebRequest -UseBasicParsing -Headers @{ 'User-Agent' = 'YapTracker-update' } -Uri $asset.browser_download_url -OutFile $zip
    if (Test-Path $staged) { Remove-Item -Recurse -Force $staged }
    Expand-Archive -Path $zip -DestinationPath $staged
    if (-not (Test-Path (Join-Path $staged 'YapTracker.exe'))) { throw "$($asset.name) contains no YapTracker.exe" }
    Set-Content -Path (Join-Path $staged 'release.txt') -Value $release.tag_name -Encoding Ascii

    Stop-YapTracker
    if (Test-Path $old) { Remove-Item -Recurse -Force $old }
    if (Test-Path $AppDir) { Move-Item $AppDir $old }
    try {
        Move-Item $staged $AppDir
    } catch {
        if (Test-Path $old) { Move-Item $old $AppDir }
        throw
    }
    if (Test-Path $old) { Remove-Item -Recurse -Force $old }
} finally {
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $staged -ErrorAction SilentlyContinue
}

Write-Host "Installed YapTracker $($release.tag_name) in $AppDir (your data stays in $(Join-Path $InstallRoot 'data'))."
if (-not $NoStart) {
    $exe = Join-Path $AppDir 'YapTracker.exe'
    if ($fresh) {
        # Asked once. The app stores the answer itself - this script never writes the data folder.
        if ($Autostart -eq 'Ask') {
            $answer = Read-Host 'Start YapTracker with Windows? It waits quietly until Overwatch starts. [Y/n]'
            $Autostart = if ($answer -match '^\s*n') { 'No' } else { 'Yes' }
        }
        $choice = if ($Autostart -eq 'No') { 'off' } else { 'on' }
        Start-Process $exe -ArgumentList "--autostart $choice"
    } else {
        Start-Process $exe
    }
}
