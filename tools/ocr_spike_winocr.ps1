<#
.SYNOPSIS
    OCR spike (#11): run Windows OCR (Windows.Media.Ocr) on a folder of chat crops.

.DESCRIPTION
    Prints "== <file> <ms> ms" and one "   y=<top> <text>" line per recognised line;
    tools/ocr_spike.py scores that output. -Scale upscales before OCR.
    Copy the crops to a local Windows folder first (WinRT can't open \\wsl$ paths).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ocr_spike_winocr.ps1 -Dir C:\Temp\crops -Scale 2 > winocr-2x.txt
#>
param([string]$Dir, [int]$Scale = 1)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }
Write-Output ("LANGS " + ($langs -join ','))
$lang = if ($langs -contains 'en-US') { 'en-US' } elseif ($langs -contains 'en-GB') { 'en-GB' } else { $langs[0] }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($lang))
Write-Output "USING $lang"
Get-ChildItem $Dir -Filter *.png | Sort-Object Name | ForEach-Object {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($_.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    if ($Scale -gt 1) {
        $tf = [Windows.Graphics.Imaging.BitmapTransform]::new()
        $tf.ScaledWidth = $decoder.PixelWidth * $Scale; $tf.ScaledHeight = $decoder.PixelHeight * $Scale
        $tf.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Cubic
        $bmp = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $tf, [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    } else {
        $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $result = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $sw.Stop()
    Write-Output ("== " + $_.Name + " " + $sw.ElapsedMilliseconds + " ms")
    foreach ($line in $result.Lines) {
        $first = @($line.Words)[0]; $y = [int]($first.BoundingRect.Y / $Scale)
        Write-Output ("   y=" + $y + " " + $line.Text)
    }
}
