<#
.SYNOPSIS
  What paces her frames on the CPU side, on Atria: GUI wakeup lateness, frame intervals and a
  py-spy profile, with and without a 1 ms system timer (ARELIS_TIMER_RES=1).

.DESCRIPTION
  Measurement build only (branch avatar/qq3d-cpuprof; see arelis/ui/cpuprof.py).
  For each configuration (timer15 = Windows' default timer, timer1 = timeBeginPeriod(1)),
  repeated -Repeat times in alternating order, it starts Arelis fresh (qq3d, d3d11), places the
  window without activating it, waits for her frames, settles, then records:
    idle          -IdleSeconds, nothing else running
    stream        -StreamSeconds while the 35B streams (straight from llama-server's HTTP API)
    stream_pyspy  -StreamSeconds more streaming with py-spy attached
                  (py-spy --native pauses the process for each sample, so this phase's own
                  wakeup and frame numbers are perturbed; read its stacks, not its timings)
  then closes Arelis (taskkill /T /F).

  Writes into -Out:
    wake_<run>.csv     t_epoch_ms,scheduled_ms,actual_ms,late_ms (1 ms PreciseTimer probe, GUI thread)
    frames_<run>.csv   t_epoch_ms,frame_ms (ARELIS_FRAMETIME_LOG, one line per frame)
    pyspy_<run>.txt    py-spy raw collapsed stacks, --threads (load in speedscope.app too)
    phases.csv         config,phase,start_ms,end_ms
    arelis_<run>.out.log / .err.log   the app's stdout/stderr (stderr has the
                       "[cpuprof] timeBeginPeriod(1) ok=..." line in timer1 runs)
    summary.csv        wakeup lateness p50/p95/p99/max and share over 2 / 10 ms; frame p50/p95,
                       share over 33 ms, share on a 15.6 ms tick, per run and phase
    pyspy_top.txt      per thread: hottest leaf frames
  (tools/cpuprof_summary.py)

.EXAMPLE
  python -m pip install py-spy
  powershell -ExecutionPolicy Bypass -File tools\cpuprof_atria.ps1 -Python C:\path\.venv\Scripts\python.exe `
      -QQ3DDir C:\Users\Public\ArelisTest\babbage\qq3d -Out \\...\team\avatar-v14k\diag\cpuprof
#>
param(
    [string]$Repo = (Resolve-Path "$PSScriptRoot\.."),
    [string]$Python = "$Repo\.venv\Scripts\python.exe",
    [string]$PySpy = "",
    [string]$QQ3DDir = "C:\Users\Public\ArelisTest\babbage\qq3d",
    [string]$Out = $(if ($env:ARELIS_TEAM_DIR) { "$env:ARELIS_TEAM_DIR\avatar-v14k\diag\cpuprof" } else { "$PSScriptRoot\..\diag\cpuprof" }),
    [string]$Llama = "http://127.0.0.1:8080",
    [int]$X = 60, [int]$Y = 40, [int]$Width = 2560, [int]$Height = 1440,
    [int]$IdleSeconds = 20, [int]$StreamSeconds = 20, [int]$SettleSeconds = 8, [int]$ReadyTimeout = 150,
    [int]$Repeat = 2, [int]$Rate = 200,
    [switch]$NoPySpy
)
$ErrorActionPreference = "Stop"
if (-not $PySpy) { $PySpy = Join-Path (Split-Path $Python) "py-spy.exe" }
if (-not $NoPySpy -and -not (Test-Path $PySpy)) { throw "py-spy not found at $PySpy (pip install py-spy into that venv, or pass -PySpy)" }

$Configs = [ordered]@{
    "timer15" = @{ ARELIS_TIMER_RES = "" }
    "timer1"  = @{ ARELIS_TIMER_RES = "1" }
}
$Order = @()
for ($i = 1; $i -le $Repeat; $i++) {
    $names = @($Configs.Keys); if ($i % 2 -eq 0) { [array]::Reverse($names) }   # A B, B A, ...
    foreach ($n in $names) { $Order += , @($n, "$n-r$i") }
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path $Out).Path
"config,phase,start_ms,end_ms" | Set-Content -Encoding ascii "$Out\phases.csv"
function Now-Ms { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }

Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsZoomed(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
}
"@

function Start-Stream([int]$Seconds) {
    Start-Job -ArgumentList $Llama, $Seconds -ScriptBlock {
        param($base, $sec)
        Add-Type -AssemblyName System.Net.Http
        $body = @{ stream = $true; max_tokens = 4096; temperature = 0.7
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

# The venv launcher starts a child python: the app is the "-m arelis" python with the most memory.
function Find-AppPid {
    $c = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match "-m arelis" })
    if (-not $c.Count) { return $null }
    ($c | Sort-Object WorkingSetSize -Descending | Select-Object -First 1).ProcessId
}

function Phase([string]$run, [string]$phase, [int]$sec, [scriptblock]$during = $null) {
    $a = Now-Ms
    if ($during) { & $during } else { Start-Sleep -Seconds $sec }
    $b = Now-Ms
    "$run,$phase,$a,$b" | Add-Content -Encoding ascii "$Out\phases.csv"
}

foreach ($pair in $Order) {
    $name, $run = $pair
    Write-Host "== $run"
    $envs = @{
        ARELIS_AVATAR_ENGINE = "qq3d"; ARELIS_QT_RHI = "d3d11"; ARELIS_AVATAR_QQ3D_DIR = $QQ3DDir
        ARELIS_FRAMETIME_LOG = "$Out\frames_$run.csv"; ARELIS_WAKE_LOG = "$Out\wake_$run.csv"; ARELIS_WAKE_PROBE_MS = "1"
    }
    foreach ($k in $Configs[$name].Keys) { $envs[$k] = $Configs[$name][$k] }
    foreach ($k in $envs.Keys) { Set-Item "env:$k" $envs[$k] }
    $p = Start-Process -FilePath $Python -ArgumentList "-m", "arelis" -WorkingDirectory $Repo -PassThru `
        -RedirectStandardOutput "$Out\arelis_$run.out.log" -RedirectStandardError "$Out\arelis_$run.err.log"
    $frames = "$Out\frames_$run.csv"
    $deadline = (Get-Date).AddSeconds($ReadyTimeout)
    while ((Get-Date) -lt $deadline -and -not ((Test-Path $frames) -and (Get-Content $frames).Count -gt 30)) { Start-Sleep -Milliseconds 500 }
    if (-not ((Test-Path $frames) -and (Get-Content $frames).Count -gt 30)) { Write-Warning "$run : no frames logged in $ReadyTimeout s" }

    $hw = [W]::FindWindow("Qt6111QWindowIcon", "Arelis")
    if ($hw -ne [IntPtr]::Zero) {
        if ([W]::IsIconic($hw) -or [W]::IsZoomed($hw)) { [W]::ShowWindow($hw, 4) | Out-Null }   # SW_SHOWNOACTIVATE
        [W]::SetWindowPos($hw, [IntPtr]::Zero, $X, $Y, $Width, $Height, 0x0014) | Out-Null     # NOZORDER|NOACTIVATE
    } else { Write-Warning "$run : Arelis window not found; size not set" }
    Start-Sleep -Seconds $SettleSeconds
    $app = Find-AppPid
    Write-Host "   app pid $app"

    Phase $run "idle" $IdleSeconds

    $job = Start-Stream ($StreamSeconds * 2 + 6)
    Start-Sleep -Seconds 3                                   # past prompt processing, into tokens
    Phase $run "stream" $StreamSeconds
    if (-not $NoPySpy -and $app) {
        Phase $run "stream_pyspy" $StreamSeconds {
            & $PySpy record --native --threads --idle -r $Rate -d $StreamSeconds -p $app -f raw -o "$Out\pyspy_$run.txt" 2>&1 |
                Out-File -Encoding utf8 "$Out\pyspy_$run.log"
        }
    }
    $r = Receive-Job $job -Wait -AutoRemoveJob -ErrorAction SilentlyContinue
    Write-Host "   stream $r"

    taskkill /T /F /PID $p.Id 2>&1 | Out-Null
    $p.WaitForExit(15000) | Out-Null
    Start-Sleep -Seconds 3
}
& $Python "$Repo\tools\cpuprof_summary.py" $Out
Write-Host "summary: $Out\summary.csv  stacks: $Out\pyspy_top.txt"
