# Launch Arelis desktop UI from this checkout (forces a real Windows Qt surface).
#
# A checkout's data root is the repository root, so this reads and writes the real
# data\profile.yaml, data\contacts.yaml, data\secrets.yaml and data\memory.db, and
# re-points every scheduled task named in data\jobs.yaml at this checkout on the way up.
# That is correct where the checkout is the Arelis being used, and wrong where an installed
# copy is -- see run_dev_ui.ps1, the same launcher against a sandbox data root, for working
# on Arelis without touching the one you rely on.
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
