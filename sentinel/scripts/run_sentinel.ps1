# Launch Sentinel Hive + Native 3D Overseer Window
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    if (Test-Path "$RepoRoot\.venv\Scripts\python.exe") {
        & "$RepoRoot\.venv\Scripts\python.exe" -m sentinel @args
    } else {
        python -m sentinel @args
    }
} finally {
    Pop-Location
}
