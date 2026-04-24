@echo off
setlocal EnableExtensions

set "INPUT_DIR=%~1"
set "OUTPUT_DIR=%~2"

if "%INPUT_DIR%"=="" set "INPUT_DIR=."
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=converted"

if not exist "%INPUT_DIR%\" (
    echo Input directory not found: %INPUT_DIR% 1>&2
    exit /b 1
)

if not exist "%OUTPUT_DIR%\" mkdir "%OUTPUT_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:INPUT_DIR='%INPUT_DIR%'; $env:OUTPUT_DIR='%OUTPUT_DIR%'; Invoke-Expression ((Get-Content -LiteralPath '%~f0' -Raw) -replace '(?s).*?# BEGIN POWERSHELL', '')"

if errorlevel 1 exit /b 1
exit /b 0

# BEGIN POWERSHELL
$inputDir = $env:INPUT_DIR
$outputDir = $env:OUTPUT_DIR
$files = Get-ChildItem -LiteralPath $inputDir -File
if ($files.Count -eq 0) { Write-Error ('No files found in ' + $inputDir); exit 1 }
foreach ($file in $files) {
  if ($file.Extension -eq '.bat' -or $file.Extension -eq '.sh') { continue }
  $text = $null
  foreach ($enc in @('utf8', 'default', 'unicode', 'bigendianunicode')) {
    try { $text = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::$enc); break } catch {}
  }
  if ($null -eq $text) { Write-Error ('Cannot read file: ' + $file.FullName); exit 1 }
  $linesText = $text -split "`r?`n" | Where-Object { $_.Trim().Length -gt 0 }
  $rows = @()
  foreach ($line in $linesText) { $rows += ,@($line -split "`t") }
  if ($rows.Count -lt 2) { continue }
  $best = @()
  for ($r = 0; $r -lt $rows.Count - 1; $r++) {
    $xs = $rows[$r]; $ys = $rows[$r + 1]; $pairs = @()
    for ($i = 0; $i -lt $xs.Count; $i++) {
      $xText = $xs[$i].Trim().Trim('"')
      $x = 0.0; $y = 0.0
      if (-not [double]::TryParse($xText, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$x)) { continue }
      if ($i -ge $ys.Count) { continue }
      $yText = $ys[$i].Trim().Trim('"')
      if (-not [double]::TryParse($yText, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$y)) { continue }
      $pairs += [pscustomobject]@{ X = $x; Y = $y }
    }
    if ($pairs.Count -gt $best.Count) { $best = $pairs }
  }
  if ($best.Count -eq 0) { continue }
  $outFile = Join-Path $outputDir ($file.BaseName + '_xy.txt')
  $lines = @('# x_um' + "`t" + 'y')
  foreach ($p in $best) { $lines += ('{0:G10}' -f $p.X) + "`t" + ('{0:G10}' -f $p.Y) }
  [System.IO.File]::WriteAllLines($outFile, $lines, [System.Text.UTF8Encoding]::new($false))
  Write-Host ('Converted ' + $file.FullName + ' -> ' + $outFile + ' (' + $best.Count + ' points)')
}
