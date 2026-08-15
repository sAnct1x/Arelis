# Launch Arelis always-on core (inbound ingest, no glass UI)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
# Prefer console python so Ctrl+C / logs are visible; fall back to pythonw.
if (Test-Path $Python) {
    $Launcher = $Python
} elseif (Test-Path $PythonW) {
    $Launcher = $PythonW
} else {
    Write-Error "Missing venv at $Python - run: python -m venv .venv; .\.venv\Scripts\pip install -e ."
}
Set-Location $Root
& $Launcher -m arelis --core @args
