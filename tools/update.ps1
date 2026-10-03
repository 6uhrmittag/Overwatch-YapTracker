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
# Windows PowerShell 5.1 downloads crawl while it draws its own progress bar: we draw ours.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Format-PayloadLine {
    # One line of the download bar (#238), e.g.
    #   Pushing the payload  [=========>----------]  47%  31.2 / 66.4 MB  8.4 MB/s
    # Without a size: a spinner and the MB so far. ASCII only (Windows PowerShell 5.1).
    param([long]$Done, [long]$Total, [double]$BytesPerSecond, [int]$Tick = 0, [int]$Width = 20)
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $mb = { param($bytes) ($bytes / 1MB).ToString('0.0', $inv) }
    $speed = '{0} MB/s' -f (& $mb $BytesPerSecond)
    if ($Total -le 0) {
        $spin = '|/-\'[$Tick % 4]
        return 'Pushing the payload  {0}  {1} MB so far  {2}' -f $spin, (& $mb $Done), $speed
    }
    $share = [Math]::Min(1.0, $Done / $Total)
    $filled = [int][Math]::Floor($share * $Width)
    $head = if ($filled -lt $Width) { '>' } else { '' }
    $track = ('=' * $filled) + $head + ('-' * [Math]::Max(0, $Width - $filled - 1))
    $what = if ($share -ge 1) { 'Payload delivered. ' } elseif ($share -ge 0.9) { 'OVERTIME! Push!    ' } else { 'Pushing the payload' }
    return '{0}  [{1}]  {2,3}%  {3} / {4} MB  {5}' -f $what, $track, [int][Math]::Floor($share * 100),
        (& $mb $Done), (& $mb $Total), $speed
}

function Save-WithProgress {
    # Download $Uri to $OutFile and draw the bar, about 10 times a second. When the
    # output isn't a console (redirected, CI), a plain line every 25 % instead.
    param([string]$Uri, [string]$OutFile)
    Add-Type -AssemblyName System.Net.Http
    $client = New-Object System.Net.Http.HttpClient
    $client.DefaultRequestHeaders.UserAgent.ParseAdd('YapTracker-update')
    $console = -not [Console]::IsOutputRedirected
    try {
        $response = $client.GetAsync($Uri, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        [void]$response.EnsureSuccessStatusCode()
        $total = [long]0
        if ($response.Content.Headers.ContentLength) { $total = [long]$response.Content.Headers.ContentLength }
        $in = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $out = [IO.File]::Create($OutFile)
        $done, $tick, $said = [long]0, 0, 0
        $clock = [Diagnostics.Stopwatch]::StartNew()
        try {
            # .NET copies (a byte loop in PowerShell 5.1 would halve the speed); we only look at
            # how far it got, ten times a second.
            $copy = $in.CopyToAsync($out, 1MB)
            while (-not $copy.Wait(100)) {
                $done = $out.Position
                $seconds = $clock.Elapsed.TotalSeconds
                if ($console) {
                    $tick++
                    $line = Format-PayloadLine $done $total ($done / [Math]::Max($seconds, 0.001)) $tick
                    [Console]::Write("`r" + $line.PadRight(79))  # padded: a shorter line leaves no rest
                } elseif ($total -gt 0 -and [int][Math]::Floor(4 * $done / $total) -gt $said) {
                    $said = [int][Math]::Floor(4 * $done / $total)
                    Write-Host ('  {0}% of {1} MB' -f ($said * 25), ($total / 1MB).ToString('0.0', [Globalization.CultureInfo]::InvariantCulture))
                }
            }
            [void]$copy.GetAwaiter().GetResult()  # a broken download throws here
            $done = $out.Position
        } finally {
            $out.Dispose()
            $in.Dispose()
        }
        if ($total -gt 0 -and $done -ne $total) { throw "Download stopped at $done of $total bytes" }
        $speed = $done / [Math]::Max($clock.Elapsed.TotalSeconds, 0.001)
        if ($console) {
            [Console]::WriteLine("`r" + (Format-PayloadLine $done ([Math]::Max($total, $done)) $speed).PadRight(79))
            Write-Host 'GG. Unpacking...'
        } else {
            $inv = [Globalization.CultureInfo]::InvariantCulture
            Write-Host ('  Done: {0} MB at {1} MB/s' -f ($done / 1MB).ToString('0.0', $inv), ($speed / 1MB).ToString('0.0', $inv))
        }
    } finally {
        $client.Dispose()
    }
}

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
    Save-WithProgress -Uri $asset.browser_download_url -OutFile $zip
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
