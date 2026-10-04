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
# The console's width (#246): never longer, the bar shrinks first, then speed and MB go.
foreach ($columns in 80, 60, 40, 30) {
    foreach ($done in 0.1, 0.5, 0.95, 1.0) {
        $line = Format-PayloadLine ([long]($done * 141.7 * 1MB)) ([long](141.7 * 1MB)) (27.8 * 1MB) -Columns $columns
        if ($line.Length -gt $columns) { throw "a $($line.Length)-char line for $columns columns: $line" }
        if ($line -notmatch '%') { throw "the percent got lost at $columns columns: $line" }
    }
    $spin = Format-PayloadLine ([long](3 * 1MB)) 0 (1.5 * 1MB) 2 -Columns $columns
    if ($spin.Length -gt $columns) { throw "spinner line too long for $columns columns: $spin" }
}
Expect (Format-PayloadLine ([long](31.2 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB) -Columns 70) `
    'Pushing the payload  [=======>-------]   46%  31.2 / 66.4 MB  8.4 MB/s'
Expect (Format-PayloadLine ([long](31.2 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB) -Columns 60) `
    'Pushing the payload  [==>--]   46%  31.2 / 66.4 MB  8.4 MB/s'
Expect (Format-PayloadLine ([long](31.2 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB) -Columns 45) `
    'Pushing the payload  [==>--]   46%'
Expect (Format-PayloadLine ([long](31.2 * 1MB)) ([long](66.4 * 1MB)) (8.4 * 1MB) -Columns 30) `
    'Payload  [==>--]   46%'
$all = (Get-Content $script -Raw)
if ($all -match '[^\x00-\x7F]') { throw 'update.ps1 must stay ASCII (Windows PowerShell 5.1)' }
# What's new since the installed version (#281): every release in between, newest first.
$Repo = 'x/y'
$ue, $mark = [string][char]0x00FC, [string][char]0x25C7
$rel = @(
    [pscustomobject]@{ tag_name = 'v0.5.5'; draft = $false; body = "### What's new`n- Five ${ue}ber $mark`n- Behind the scenes: a`n`nUpdate: run it." },
    [pscustomobject]@{ tag_name = 'v0.5.4'; draft = $true; body = "- Draft" },
    [pscustomobject]@{ tag_name = 'v0.5.3'; draft = $false; body = "- Three`r`n- Behind the scenes: b" },
    [pscustomobject]@{ tag_name = 'v0.5.2'; draft = $false; body = "- Two`n- Five ${ue}ber $mark" },
    [pscustomobject]@{ tag_name = 'v0.5.1'; draft = $false; body = "- One" }
)
Expect ((Get-WhatsNew -Releases $rel -Installed 'v0.5.1') -join '|') `
    ("What's new since v0.5.1 (3 releases):|  - Five ueber <>|  - Three|  - Two|" +
     "  (+ 2 behind-the-scenes changes)|  All notes: https://github.com/x/y/blob/main/CHANGELOG.md")
Expect ((Get-WhatsNew -Releases $rel -Installed '') -join '|') `
    "What's new in v0.5.5:|  - Five ueber <>|  (+ 1 behind-the-scenes change)"
Expect ((Get-WhatsNew -Releases $rel -Installed 'v0.5.5') -join '|') `
    "What's new in v0.5.5:|  - Five ueber <>|  (+ 1 behind-the-scenes change)"
Expect ((Get-WhatsNew -Releases $rel -Installed 'v0.5.3') -join '|') `
    "What's new since v0.5.3 (1 release):|  - Five ueber <>|  (+ 1 behind-the-scenes change)"
Expect ((Get-WhatsNew -Releases $rel -Installed 'v0.4.9' -Cap 2) -join '|') `
    ("What's new since v0.4.9 (more than 4 releases):|  - Five ueber <>|  - Three|  ... and 2 more|" +
     "  (+ 2 behind-the-scenes changes)|  All notes: https://github.com/x/y/blob/main/CHANGELOG.md")
Expect (ConvertTo-Ascii ("Gr" + [char]0x00FC + [char]0x00DF + "e " + [char]0x201C + "hi" + [char]0x201D + " " + [char]0x2014 + " ok " + [char]0x4E2D)) `
    'Gruesse "hi" - ok ?'

Write-Host "Bar lines OK on PowerShell $($PSVersionTable.PSVersion)"

