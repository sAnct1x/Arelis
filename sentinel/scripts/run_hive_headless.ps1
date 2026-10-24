# Launch Sentinel Hive in headless daemon mode (3D Overseer accessible via http://127.0.0.1:8790/overseer)
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot
try {
    if (Test-Path "$RepoRoot\.venv\Scripts\python.exe") {
        & "$RepoRoot\.venv\Scripts\python.exe" -m sentinel --headless @args
    } else {
        python -m sentinel --headless @args
    }
} finally {
    Pop-Location
}
