$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "arelis"))) { $Root = $PSScriptRoot }
Set-Location $Root

# Kill leftover Arelis UI processes (command line mentions arelis).
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match '^(python|pythonw)\.exe$' -and
    $_.CommandLine -and
    ($_.CommandLine -match 'arelis')
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "killed $($_.ProcessId)"
  }

Start-Sleep -Seconds 1

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
$env:QT_QPA_PLATFORM = "windows"
& $Python -m arelis.ui._verify_no_ghost
exit $LASTEXITCODE
