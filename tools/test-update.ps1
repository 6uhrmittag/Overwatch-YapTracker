<#
.SYNOPSIS
    Checks for tools/update.ps1 (#238). CI runs it on Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
    1. The download bar: only the functions are loaded from update.ps1 (nothing else runs),
       and a few bar lines are checked.
    2. A real install of the newest release into a temp folder. In CI the output isn't a
       console, so this also covers the plain-text fallback.
#>
param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'update.ps1'

$ast = [System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$null, [ref]$null)
$functions = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($f in $functions) { . ([ScriptBlock]::Create($f.Extent.Text)) }

function Expect([string]$Got, [string]$Want) {
    if ($Got -cne $Want) { throw "expected`n  '$Want'`ngot`n  '$Got'" }
}
Expect (Format-PayloadLine ([long](31.2 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB)) `
    'Pushing the payload  [=========>----------]   46%  31.2 / 66.4 MB  8.4 MB/s'
Expect (Format-PayloadLine ([long](62 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB)) `
    'OVERTIME! Push!      [==================>-]   93%  62.0 / 66.4 MB  8.4 MB/s'
Expect (Format-PayloadLine ([long](66.4 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB)) `
    'Payload delivered.   [====================]  100%  66.4 / 66.4 MB  8.4 MB/s'
Expect (Format-PayloadLine ([long](3 * 1MB)) 0 (1.5 * 1MB) 2) `
    'Pushing the payload  -  3.0 MB so far  1.5 MB/s'
$all = (Get-Content $script -Raw)
if ($all -match '[^\x00-\x7F]') { throw 'update.ps1 must stay ASCII (Windows PowerShell 5.1)' }
Write-Host "Bar lines OK on PowerShell $($PSVersionTable.PSVersion)"

if (-not $SkipInstall) {
    $root = Join-Path ([IO.Path]::GetTempPath()) ('yt-update-test-' + [guid]::NewGuid())
    $clock = [Diagnostics.Stopwatch]::StartNew()
    & $script -InstallRoot $root -NoStart -Autostart No
    if (-not (Test-Path (Join-Path $root 'app\YapTracker.exe'))) { throw 'update.ps1 installed no YapTracker.exe' }
    Write-Host ('Installed into a temp folder in {0:N1} s' -f $clock.Elapsed.TotalSeconds)
    Remove-Item -Recurse -Force $root
}
