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
    [string]$Autostart = 'Ask',
    # Run this copy as it is, without fetching the newest update.ps1 first (CI tests its own).
    [switch]$NoSelfUpdate
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 downloads crawl while it draws its own progress bar: we draw ours.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Format-PayloadLine {
    # One line of the download bar (#238), e.g.
    #   Pushing the payload  [=========>----------]  47%  31.2 / 66.4 MB  8.4 MB/s
    # Without a size: a spinner and the MB so far. ASCII only (Windows PowerShell 5.1).
    # $Columns: the console's width (#246). The line never wraps: first the bar gets shorter,
    # then the speed goes, then the MB. 0 = no limit.
    param([long]$Done, [long]$Total, [double]$BytesPerSecond, [int]$Tick = 0, [int]$Width = 20,
          [int]$Columns = 0)
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $mb = { param($bytes) ($bytes / 1MB).ToString('0.0', $inv) }
    $speed = '{0} MB/s' -f (& $mb $BytesPerSecond)
    if ($Total -le 0) {
        $spin = '|/-\'[$Tick % 4]
        $parts = @('Pushing the payload', $spin, ('{0} MB so far' -f (& $mb $Done)), $speed)
        while ($Columns -gt 0 -and ($parts -join '  ').Length -gt $Columns -and $parts.Count -gt 2) {
            $parts = $parts[0..($parts.Count - 2)]
        }
        return $parts -join '  '
    }
    $share = [Math]::Min(1.0, $Done / $Total)
    $what = if ($share -ge 1) { 'Payload delivered. ' } elseif ($share -ge 0.9) { 'OVERTIME! Push!    ' } else { 'Pushing the payload' }
    $tail = @(('{0,3}%' -f [int][Math]::Floor($share * 100)), ('{0} / {1} MB' -f (& $mb $Done), (& $mb $Total)), $speed)
    while ($true) {
        $filled = [int][Math]::Floor($share * $Width)
        $head = if ($filled -lt $Width) { '>' } else { '' }
        $track = ('=' * $filled) + $head + ('-' * [Math]::Max(0, $Width - $filled - 1))
        $line = '{0}  [{1}]  {2}' -f $what, $track, ($tail -join '  ')
        if ($Columns -le 0 -or $line.Length -le $Columns) { return $line }
        if ($Width -gt 5) { $Width = [Math]::Max(5, $Width - ($line.Length - $Columns)); continue }
        if ($tail.Count -gt 1) { $tail = $tail[0..($tail.Count - 2)]; continue }
        if ($what.Length -gt 7) { $what = 'Payload'; continue }  # a very narrow window
        return $line.Substring(0, $Columns)
    }
}

function Get-Columns {
    # Room for the bar: the console's width, one column spare so the cursor doesn't wrap.
    try { return [Math]::Max(20, [Console]::WindowWidth - 1) } catch { return 79 }
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
                    $columns = Get-Columns  # read each time: the window can be resized
                    $line = Format-PayloadLine $done $total ($done / [Math]::Max($seconds, 0.001)) $tick -Columns $columns
                    [Console]::Write("`r" + $line.PadRight($columns))  # padded: a shorter line leaves no rest
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
            $columns = Get-Columns
            [Console]::WriteLine("`r" + (Format-PayloadLine $done ([Math]::Max($total, $done)) $speed -Columns $columns).PadRight($columns))
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

function ConvertTo-Ascii {
    # Release notes in the console of Windows PowerShell 5.1 (#281): umlauts spelled out, the
    # icon mark and typographic quotes and dashes as their plain cousins, anything else '?'.
    # This file stays ASCII, so the characters are written as their codes.
    param([string]$Text)
    $map = @{
        0x00E4 = 'ae'; 0x00F6 = 'oe'; 0x00FC = 'ue'; 0x00C4 = 'Ae'; 0x00D6 = 'Oe'; 0x00DC = 'Ue'
        0x00DF = 'ss'; 0x25C7 = '<>'; 0x2018 = "'"; 0x2019 = "'"; 0x201C = '"'; 0x201D = '"'
        0x2013 = '-'; 0x2014 = '-'; 0x2026 = '...'; 0x00B7 = '-'; 0x2192 = '->'; 0x00E9 = 'e'
        0x00EB = 'e'; 0x00ED = 'i'; 0x00C9 = 'E'
    }
    $out = New-Object System.Text.StringBuilder
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if ($code -lt 128) { [void]$out.Append($ch) }
        elseif ($map.ContainsKey($code)) { [void]$out.Append($map[$code]) }
        else { [void]$out.Append('?') }
    }
    return $out.ToString()
}

function Get-WhatsNew {
    # What's new since the installed version (#281): the bullets of every release between it
    # and the new one, newest first, from the release list fetched anyway (no extra call).
    # "Behind the scenes" bullets become a count, repeats show once, at most $Cap bullets.
    # Fresh install or the same version again: the newest release's bullets only.
    param([object[]]$Releases, [string]$Installed, [int]$Cap = 15)
    $list = @($Releases | Where-Object { -not $_.draft })
    if ($list.Count -eq 0) { return @() }
    $newest = $list[0].tag_name
    $since = $Installed -and $Installed -ne $newest
    $bullets = New-Object System.Collections.Generic.List[string]
    $behind, $count, $found = 0, 0, $false
    foreach ($r in $list) {
        if ($since -and $r.tag_name -eq $Installed) { $found = $true; break }
        $count++
        foreach ($line in ("$($r.body)" -split "`r?`n")) {
            if ($line -notmatch '^- ') { continue }
            if ($line -match '^- Behind the scenes') { $behind++; continue }
            $line = ConvertTo-Ascii $line
            if (-not $bullets.Contains($line)) { $bullets.Add($line) }
        }
        if (-not $since) { break }
    }
    if ($bullets.Count -eq 0 -and $behind -eq 0) { return @() }
    $lines = New-Object System.Collections.Generic.List[string]
    if (-not $since) { $lines.Add("What's new in ${newest}:") }
    elseif ($found) { $lines.Add("What's new since $Installed ($count release$(if ($count -ne 1) { 's' })):") }
    else { $lines.Add("What's new since $Installed (more than $count releases):") }
    foreach ($b in ($bullets | Select-Object -First $Cap)) { $lines.Add("  $b") }
    if ($bullets.Count -gt $Cap) { $lines.Add("  ... and $($bullets.Count - $Cap) more") }
    if ($behind -eq 1) { $lines.Add('  (+ 1 behind-the-scenes change)') }
    elseif ($behind -gt 1) { $lines.Add("  (+ $behind behind-the-scenes changes)") }
    if ($since -and ($count -gt 1 -or -not $found)) {
        $lines.Add("  All notes: https://github.com/$Repo/blob/main/CHANGELOG.md")
    }
    return $lines.ToArray()
}

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
# 100: enough to find the installed version and tell everything since (#281), one call.
$releases = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/$Repo/releases?per_page=100"
$release = $releases | Where-Object { -not $_.draft } | Select-Object -First 1
if (-not $release) { throw "No release found on github.com/$Repo" }
$asset = $release.assets | Where-Object { $_.name -like 'YapTracker-*-win64.zip' } | Select-Object -First 1
if (-not $asset) { throw "Release $($release.tag_name) has no YapTracker-*-win64.zip" }

# Keep this script current (#246): a saved copy would run old code for good (and miss what's
# new, #239). The release's own update.ps1 replaces this file and runs instead, same arguments.
$replaced = $false
if (-not $NoSelfUpdate -and $PSCommandPath) {
    try {
        $latest = (Invoke-WebRequest -UseBasicParsing -Headers @{ 'User-Agent' = 'YapTracker-update' } `
            -Uri "https://raw.githubusercontent.com/$Repo/$($release.tag_name)/tools/update.ps1").Content
        $latest = $latest -replace "`r?`n", "`r`n"
        if ($latest -match 'param\(' -and $latest -ne [IO.File]::ReadAllText($PSCommandPath)) {
            [IO.File]::WriteAllText($PSCommandPath, $latest, [Text.Encoding]::ASCII)
            $replaced = $true
        }
    } catch {
        Write-Host "Couldn't check for a newer update.ps1 ($($_.Exception.Message)), going on with this one."
    }
}
if ($replaced) {  # outside the try: if the new one fails, this one must not run as well
    Write-Host 'This update.ps1 was out of date: replaced it with the newest, running that one...'
    $again = @{}
    foreach ($key in $PSBoundParameters.Keys) { $again[$key] = $PSBoundParameters[$key] }
    if ($latest -match 'NoSelfUpdate') { $again['NoSelfUpdate'] = $true }  # older ones don't know it
    $global:LASTEXITCODE = 0
    & $PSCommandPath @again
    exit $LASTEXITCODE
}

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
# The release notes' bullets (#239), everything since the version you had (#281).
foreach ($line in (Get-WhatsNew -Releases $releases -Installed $installed)) { Write-Host $line }
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
