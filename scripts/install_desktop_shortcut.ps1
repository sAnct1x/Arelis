# Create Desktop + Start Menu shortcuts for Arelis (idempotent).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunUi = Join-Path $PSScriptRoot "run_ui.ps1"
$Icon = Join-Path $Root "assets\arelis.ico"

if (-not (Test-Path $RunUi)) {
    Write-Error "Missing launcher script: $RunUi"
}
if (-not (Test-Path $Icon)) {
    Write-Error "Missing icon: $Icon - run: .\.venv\Scripts\python.exe scripts\generate_app_icon.py"
}

$Wsh = New-Object -ComObject WScript.Shell
$Target = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunUi`""

function Install-ArelisShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $shortcut = $Wsh.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $Root
    $shortcut.IconLocation = "$Icon,0"
    $shortcut.Description = "Arelis - local research assistant"
    $shortcut.WindowStyle = 7  # Minimized; -WindowStyle Hidden already hides the host
    $shortcut.Save()
    Write-Host "Installed $Path"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Arelis"

Install-ArelisShortcut -Path (Join-Path $Desktop "Arelis.lnk")
Install-ArelisShortcut -Path (Join-Path $StartMenu "Arelis.lnk")

Write-Host ""
Write-Host "Double-click Arelis on the Desktop, or find it in the Start menu."
