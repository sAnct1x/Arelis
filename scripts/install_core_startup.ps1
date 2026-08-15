# Optional: start Arelis core at Windows logon (inbound ingest without UI).
# Idempotent. Does not require admin. Remove with -Uninstall.
param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunCore = Join-Path $PSScriptRoot "run_core.ps1"
$TaskName = "Arelis\Core"

if (-not (Test-Path $RunCore)) {
    Write-Error "Missing $RunCore"
}

if ($Uninstall) {
    schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
    Write-Host "Removed scheduled task $TaskName (if it existed)."
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Missing venv python at $Python"
}

# At logon, run the core hidden. User can still open the UI separately.
$Tr = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunCore`""
schtasks /Create /TN $TaskName /TR $Tr /SC ONLOGON /RL LIMITED /F | Out-Null
Write-Host "Installed logon task: $TaskName"
Write-Host "Core keeps port 8765 up. Open the desktop UI when you want chat."
Write-Host "Remove later with: .\scripts\install_core_startup.ps1 -Uninstall"
