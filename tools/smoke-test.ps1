<#
.SYNOPSIS
    Start YapTracker.exe --smoke-test and fail unless it exits 0 in time.

.DESCRIPTION
    The app exits 0 once its window has loaded the page, or 1 after its own
    90 s timeout. Only the main process is awaited: WebView2 helper processes
    may linger for a moment and must not keep CI waiting.
#>
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [int]$TimeoutSeconds = 150
)

$ErrorActionPreference = 'Stop'

$p = Start-Process $Exe -ArgumentList '--smoke-test' -PassThru
# Holding the handle keeps ExitCode readable after the process is gone (Windows PowerShell 5.1).
$null = $p.Handle
if (-not $p.WaitForExit($TimeoutSeconds * 1000)) {
    Get-Process -Name 'YapTracker' -ErrorAction SilentlyContinue | Stop-Process -Force
    throw "YapTracker.exe --smoke-test did not exit within $TimeoutSeconds s"
}
if ($p.ExitCode -ne 0) { throw "YapTracker.exe --smoke-test exited with $($p.ExitCode)" }
Write-Host 'Smoke test passed: the window opened and loaded the page.'
