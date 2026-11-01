<#
.SYNOPSIS
  Per-frame render-thread trace of her qq3d frames on Atria (d3d11), in four 60 s phases.

.DESCRIPTION
  Measurement build only (branch avatar/qq3d-frametrace). Starts Arelis once (qq3d, d3d11),
  places the window without activating it, waits for frames, settles, then runs:
    1 idle          app idle, llama idle
    2 llama_gen     app idle while llama-server generates a long reply to an external prompt
    3 app_stream    the app streams a chat reply (prompt typed into the app's chat box)
    4 idle2         app idle again
  The app writes one trace file; each phase is cut from it by trace row count at the phase
  boundaries (rows are flushed about once a second, so edges are accurate to ~1 s).
  Total about 4 min of capture plus start-up, well under 15 min.

  app_stream: there is no headless hook to send a chat turn, so the script activates the window,
  pastes -ChatPrompt from the clipboard and presses Enter (the chat input must have focus on
  launch; -ChatClickX/-ChatClickY click it first if not). Check arelis_*.err.log / the
  chunk count printed for that phase to confirm the reply really streamed.

  Writes into -Out:
    raw_all.csv       the app's raw ARELIS_FRAME_TRACE file
    trace_<phase>.csv rows of that phase only (header kept)
    phases.csv        phase,start_ms,end_ms (wall clock) and the trace row index range
    summary.csv       per phase and column: n, p50, p95, max, % over 33 ms
                      (tools/frametrace_summary.py)
    arelis.out.log / arelis.err.log

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\frametrace_atria.ps1 -Python C:\path\.venv\Scripts\python.exe `
      -QQ3DDir C:\Users\Public\ArelisTest\babbage\qq3d -Out \\...\team\avatar-v14k\diag\frametrace
#>
param(
    [string]$Repo = (Resolve-Path "$PSScriptRoot\.."),
    [string]$Python = "$Repo\.venv\Scripts\python.exe",
    [string]$QQ3DDir = "C:\Users\Public\ArelisTest\babbage\qq3d",
    [string]$Out = $(if ($env:ARELIS_TEAM_DIR) { "$env:ARELIS_TEAM_DIR\avatar-v14k\diag\frametrace" } else { "$PSScriptRoot\..\diag\frametrace" }),
    [string]$Llama = "http://127.0.0.1:8080",
    [int]$X = 60, [int]$Y = 40, [int]$Width = 2560, [int]$Height = 1440,
    [int]$PhaseSeconds = 60, [int]$SettleSeconds = 8, [int]$ReadyTimeout = 150,
    [string]$ChatPrompt = "Write a long, detailed essay on the history of timekeeping, from sundials to atomic clocks. Be thorough.",
    [int]$ChatClickX = -1, [int]$ChatClickY = -1
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$Trace = "$Out\trace_all.csv"
Remove-Item -ErrorAction SilentlyContinue "$Out\trace_*.csv", "$Out\phases.csv", "$Out\summary.csv"
"phase,start_ms,end_ms,first_row,last_row" | Set-Content -Encoding ascii "$Out\phases.csv"
function Now-Ms { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }

Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, IntPtr e);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
}
"@
Add-Type -AssemblyName System.Windows.Forms

# Same streaming client as cpuprof_atria.ps1, straight to llama-server's HTTP API.
function Start-Stream([int]$Seconds) {
    Start-Job -ArgumentList $Llama, $Seconds -ScriptBlock {
        param($base, $sec)
        Add-Type -AssemblyName System.Net.Http
        $body = @{ stream = $true; max_tokens = 8192; temperature = 0.7
            messages = @(@{ role = "user"; content = "Explain in detail, step by step, how a black hole event horizon forms, what an observer falling in would see, and how Hawking radiation works. Be thorough." }) } | ConvertTo-Json -Depth 5
        $cli = [System.Net.Http.HttpClient]::new(); $cli.Timeout = [TimeSpan]::FromSeconds($sec + 30)
        $req = [System.Net.Http.HttpRequestMessage]::new("POST", "$base/v1/chat/completions")
        $req.Content = [System.Net.Http.StringContent]::new($body, [Text.Encoding]::UTF8, "application/json")
        $resp = $cli.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
        $rd = [IO.StreamReader]::new($resp.Content.ReadAsStreamAsync().Result)
        $end = (Get-Date).AddSeconds($sec); $n = 0
        while ((Get-Date) -lt $end -and -not $rd.EndOfStream) { if ($rd.ReadLine().StartsWith("data:")) { $n++ } }
        $rd.Dispose(); $cli.Dispose(); "chunks=$n"
    }
}

function Trace-Rows { if (Test-Path $Trace) { @(Get-Content $Trace).Count } else { 0 } }

function Phase([string]$phase, [scriptblock]$during = $null) {
    Write-Host "== $phase ($PhaseSeconds s)"
    $a = Now-Ms; $r0 = Trace-Rows      # rows are flushed about once a second
    if ($during) { & $during } else { Start-Sleep -Seconds $PhaseSeconds }
    $b = Now-Ms; $r1 = Trace-Rows
    "$phase,$a,$b,$r0,$r1" | Add-Content -Encoding ascii "$Out\phases.csv"
}

$envs = @{ ARELIS_AVATAR_ENGINE = "qq3d"; ARELIS_QT_RHI = "d3d11"; ARELIS_AVATAR_QQ3D_DIR = $QQ3DDir; ARELIS_FRAME_TRACE = $Trace }
foreach ($k in $envs.Keys) { Set-Item "env:$k" $envs[$k] }
$p = Start-Process -FilePath $Python -ArgumentList "-m", "arelis" -WorkingDirectory $Repo -PassThru `
    -RedirectStandardOutput "$Out\arelis.out.log" -RedirectStandardError "$Out\arelis.err.log"
$deadline = (Get-Date).AddSeconds($ReadyTimeout)
while ((Get-Date) -lt $deadline -and (Trace-Rows) -lt 30) { Start-Sleep -Milliseconds 500 }
if ((Trace-Rows) -lt 30) { Write-Warning "no frames traced in $ReadyTimeout s" }

$hw = [W]::FindWindow("Qt6111QWindowIcon", "Arelis")
if ($hw -ne [IntPtr]::Zero) {
    if ([W]::IsIconic($hw) -or [W]::IsZoomed($hw)) { [W]::ShowWindow($hw, 4) | Out-Null }   # SW_SHOWNOACTIVATE
    [W]::SetWindowPos($hw, [IntPtr]::Zero, $X, $Y, $Width, $Height, 0x0014) | Out-Null     # NOZORDER|NOACTIVATE
} else { Write-Warning "Arelis window not found; size not set" }
Start-Sleep -Seconds $SettleSeconds

try {
    Phase "idle"

    $job = Start-Stream ($PhaseSeconds + 10)
    Start-Sleep -Seconds 3                                   # past prompt processing, into tokens
    Phase "llama_gen"
    $r = Receive-Job $job -Wait -AutoRemoveJob -ErrorAction SilentlyContinue
    Write-Host "   llama_gen $r"
    Start-Sleep -Seconds 5

    if ($hw -ne [IntPtr]::Zero) {
        [W]::SetForegroundWindow($hw) | Out-Null; Start-Sleep -Milliseconds 400
        if ($ChatClickX -ge 0) {
            [W]::SetCursorPos($ChatClickX, $ChatClickY) | Out-Null
            [W]::mouse_event(0x2, 0, 0, 0, [IntPtr]::Zero); [W]::mouse_event(0x4, 0, 0, 0, [IntPtr]::Zero)
            Start-Sleep -Milliseconds 300
        }
        [System.Windows.Forms.Clipboard]::SetText($ChatPrompt)
        [System.Windows.Forms.SendKeys]::SendWait("^v"); Start-Sleep -Milliseconds 200
        [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
        Start-Sleep -Seconds 3                               # past prompt processing
    } else { Write-Warning "app_stream: no window, prompt not sent" }
    Phase "app_stream"
    Start-Sleep -Seconds 5

    Phase "idle2"
} finally {
    taskkill /T /F /PID $p.Id 2>&1 | Out-Null               # rows since the last ~1 s flush may be lost
    $p.WaitForExit(15000) | Out-Null
}

# Split by row index (phases.csv) into trace_<phase>.csv.
$lines = @(Get-Content $Trace)
foreach ($row in (Import-Csv "$Out\phases.csv")) {
    $a = [Math]::Max(1, [int]$row.first_row); $b = [Math]::Min($lines.Count, [int]$row.last_row) - 1
    $part = @($lines[0]); if ($b -ge $a) { $part += $lines[$a..$b] }
    $part | Set-Content -Encoding ascii "$Out\trace_$($row.phase).csv"
}
Move-Item -Force $Trace "$Out\raw_all.csv"   # keep it out of the trace_*.csv glob
& $Python "$Repo\tools\frametrace_summary.py" $Out
Write-Host "summary: $Out\summary.csv"
