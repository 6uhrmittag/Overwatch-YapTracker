<#
.SYNOPSIS
    Checks the download bar of tools/update.ps1 (#238): only the functions are loaded from
    update.ps1 (nothing else runs), and a few bar lines are checked. The install itself is
    tested by .github/workflows/update-script.yml, on Windows PowerShell 5.1 and PowerShell 7.
#>
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

