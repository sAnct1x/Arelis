# Launch Arelis desktop UI (forces a real Windows Qt surface)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $PythonW) {
    $Launcher = $PythonW
} elseif (Test-Path $Python) {
    $Launcher = $Python
} else {
    Write-Error "Missing venv at $Python - run: python -m venv .venv; .\.venv\Scripts\pip install -e ."
}
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$env:QT_QPA_PLATFORM = "windows"
Set-Location $Root
& $Launcher -m arelis @args
