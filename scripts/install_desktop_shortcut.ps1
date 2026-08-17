# Create Desktop + Start Menu shortcuts for Arelis (idempotent).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Inside the package, not beside it: the icon has to be shipped with an install,
# and setuptools only packages files under a package directory. It is committed,
# so generate_app_icon.py is for changing it rather than for producing it.
$Icon = Join-Path $Root "arelis\assets\arelis.ico"

if (-not (Test-Path $Icon)) {
    Write-Error "Missing icon: $Icon"
}

# Straight at pythonw.exe, and deliberately not at powershell.exe -File run_ui.ps1.
#
# -WindowStyle Hidden does not mean "no window". PowerShell is a console program:
# Windows allocates a console for it, it starts, and only then does it hide the
# window it already has. The result is a black rectangle that blinks on screen on
# every single launch, which is the first thing anyone sees of this program and
# reads as something having gone wrong.
#
# pythonw.exe is a GUI-subsystem binary, so no console is ever created and there is
# nothing to hide. Everything run_ui.ps1 was doing for us is now done in Python
# where it belongs: run_ui.ps1 set QT_QPA_PLATFORM, and arelis.ui.app already
# corrects that variable itself, and set the working directory, which is what a
# shortcut's own WorkingDirectory field is for.
$Wsh = New-Object -ComObject WScript.Shell
$VenvPythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (Test-Path $VenvPythonW) {
    $Target = $VenvPythonW
} else {
    # An installed tree has pythonw.exe at its root; a bare checkout with no venv
    # has whatever is on PATH, and naming it now beats a shortcut that fails later.
    $Candidate = Join-Path $Root "pythonw.exe"
    if (Test-Path $Candidate) {
        $Target = $Candidate
    } else {
        $Found = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
        if (-not $Found) {
            Write-Error "No pythonw.exe found - create the venv first: python -m venv .venv; .\.venv\Scripts\pip install -e ."
        }
        $Target = $Found
    }
}
$Arguments = "-m arelis"

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
    $shortcut.Description = $Description
    # 1 = Normal. The old value here was 7 (Minimized), which was aimed at the
    # console PowerShell used to open; with pythonw there is no console, and 7
    # would ask the glass itself to come up minimized.
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    Write-Host "Installed $Path"
}

$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Arelis"

# The same two markers as is_source_checkout(), for the same reason: a wheel cannot
# carry tests/. A checkout must not write Arelis.lnk, because that name belongs to the
# installed copy. Overwriting it silently repoints the shortcut somebody uses every day
# at a working tree, against a different data root, and the only symptom is that their
# Arelis one morning has none of their history in it.
$IsCheckout = (Test-Path (Join-Path $Root "pyproject.toml")) -and (Test-Path (Join-Path $Root "tests"))
if ($IsCheckout) {
    $Name = "Arelis (dev).lnk"
    $Description = "Arelis (dev checkout)"
} else {
    $Name = "Arelis.lnk"
    $Description = "Arelis - local research assistant"
}

Install-ArelisShortcut -Path (Join-Path $Desktop $Name)
Install-ArelisShortcut -Path (Join-Path $StartMenu $Name)

Write-Host ""
Write-Host "Double-click Arelis on the Desktop, or find it in the Start menu."
