<#
.SYNOPSIS
  Per-frame render-thread trace of her qq3d frames on Atria (d3d11), in four 60 s phases.

.DESCRIPTION
  Measurement build only (branch avatar/qq3d-frametrace). Starts Arelis once (qq3d, d3d11),
  places the window without activating it, waits for frames, settles, then runs:
    1 idle          app idle, llama idle
    2 llama_gen     app idle while llama-server generates a long reply to an external prompt
    3 app_stream    the app streams a chat reply (sent headlessly, see below)
    4 idle2         app idle again, started only once that reply has finished streaming
  The app writes one trace file; each phase is cut from it by trace row count at the phase
  boundaries (rows are flushed about once a second, so edges are accurate to ~1 s).
  Total about 4 min of capture plus start-up and the wait for the reply to end (capped by
  -StreamEndTimeout), under 15 min.

  No keyboard, mouse, clipboard or foreground change on Atria. app_stream: the app is started
  with ARELIS_AUTOCHAT_PROMPT=-ChatPrompt and ARELIS_AUTOCHAT_TRIGGER=<file>; creating the file
  makes the app submit the prompt through its own chat box (arelis/ui/autochat.py, inert when
  unset). The app appends "sent <ms>" / "done <ms>" to autochat.log; idle2 waits for "done".

  llama tokens/s per phase: llama-server /metrics (start it with --metrics) is read at each
  phase edge; tok_s = delta llamacpp:tokens_predicted_total / phase seconds, gen_tok_s = that
  delta / delta llamacpp:tokens_predicted_seconds_total. Without /metrics, llama_gen falls back
  to streamed chunks / seconds (one token per chunk) and the timings.predicted_per_second of
  the final chunk when the reply ends inside the phase. Written to llama.csv and summary.csv.

  Writes into -Out:
    raw_all.csv       the app's raw ARELIS_FRAME_TRACE file
    trace_<phase>.csv rows of that phase only (header kept)
    phases.csv        phase,start_ms,end_ms (wall clock) and the trace row index range
    summary.csv       per phase and column: n, p50, p95, max, % over 33 ms
                      (tools/frametrace_summary.py)
    llama.csv         phase,tokens,seconds,tok_s,gen_tok_s,source
    autochat.log      the app's sent/done lines for the app_stream reply
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
    [int]$StreamEndTimeout = 240
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$Trace = "$Out\trace_all.csv"
$Trigger = "$Out\autochat.go"; $ChatLog = "$Out\autochat.log"
Remove-Item -ErrorAction SilentlyContinue "$Out\trace_*.csv", "$Out\phases.csv", "$Out\summary.csv", "$Out\llama.csv", $Trigger, $ChatLog
"phase,start_ms,end_ms,first_row,last_row" | Set-Content -Encoding ascii "$Out\phases.csv"
"phase,tokens,seconds,tok_s,gen_tok_s,source" | Set-Content -Encoding ascii "$Out\llama.csv"
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
        $t0 = Get-Date; $end = $t0.AddSeconds($sec); $n = 0; $pps = ""
        while ((Get-Date) -lt $end -and -not $rd.EndOfStream) {
            $line = $rd.ReadLine()
            if ($line.StartsWith("data:")) {
                $n++
                if ($line -match '"predicted_per_second"\s*:\s*([0-9.eE+-]+)') { $pps = $Matches[1] }
            }
        }
        $s = ((Get-Date) - $t0).TotalSeconds
        $rd.Dispose(); $cli.Dispose()
        [pscustomobject]@{ chunks = $n; seconds = $s; predicted_per_second = $pps }
    }
}

# llama-server Prometheus counters, or $null when /metrics is off (no --metrics).
function Llama-Counters {
    try {
        $txt = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "$Llama/metrics").Content
        $c = @{}
        foreach ($m in [regex]::Matches($txt, '(?m)^llamacpp:(tokens_predicted_total|tokens_predicted_seconds_total)\s+([0-9.eE+-]+)')) {
            $c[$m.Groups[1].Value] = [double]$m.Groups[2].Value
        }
        if ($c.Count -eq 2) { return $c }
    } catch { }
    return $null
}
$script:NoMetrics = $false

function Trace-Rows { if (Test-Path $Trace) { @(Get-Content $Trace).Count } else { 0 } }

function Phase([string]$phase, [scriptblock]$during = $null) {
    Write-Host "== $phase ($PhaseSeconds s)"
    $m0 = Llama-Counters
    $a = Now-Ms; $r0 = Trace-Rows      # rows are flushed about once a second
    if ($during) { & $during } else { Start-Sleep -Seconds $PhaseSeconds }
    $b = Now-Ms; $r1 = Trace-Rows
    $m1 = Llama-Counters
    "$phase,$a,$b,$r0,$r1" | Add-Content -Encoding ascii "$Out\phases.csv"
    $sec = ($b - $a) / 1000.0
    if ($m0 -and $m1) {
        $tok = $m1.tokens_predicted_total - $m0.tokens_predicted_total
        $gs = $m1.tokens_predicted_seconds_total - $m0.tokens_predicted_seconds_total
        $gen = if ($gs -gt 0) { "{0:F2}" -f ($tok / $gs) } else { "" }
        "$phase,$tok,{0:F1},{1:F2},$gen,metrics" -f $sec, ($tok / $sec) | Add-Content -Encoding ascii "$Out\llama.csv"
    } else { $script:NoMetrics = $true }
}

function Wait-ChatLog([string]$event, [int]$timeout) {
    $until = (Get-Date).AddSeconds($timeout)
    while ((Get-Date) -lt $until) {
        if ((Test-Path $ChatLog) -and (Select-String -Quiet -Path $ChatLog -Pattern "^(never_busy|$event) ")) {
            return (Select-String -Quiet -Path $ChatLog -Pattern "^$event ")
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$envs = @{ ARELIS_AVATAR_ENGINE = "qq3d"; ARELIS_QT_RHI = "d3d11"; ARELIS_AVATAR_QQ3D_DIR = $QQ3DDir; ARELIS_FRAME_TRACE = $Trace
           ARELIS_AUTOCHAT_PROMPT = $ChatPrompt; ARELIS_AUTOCHAT_TRIGGER = $Trigger; ARELIS_AUTOCHAT_LOG = $ChatLog }
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
    Write-Host "   llama_gen chunks=$($r.chunks) in $([Math]::Round($r.seconds, 1)) s"
    if ($script:NoMetrics -and $r -and $r.seconds -gt 0) {   # no /metrics: the stream itself
        "llama_gen,$($r.chunks),{0:F1},{1:F2},$($r.predicted_per_second),stream_chunks" -f $r.seconds, ($r.chunks / $r.seconds) |
            Add-Content -Encoding ascii "$Out\llama.csv"
    }
    Start-Sleep -Seconds 5

    New-Item -ItemType File -Force -Path $Trigger | Out-Null  # the app submits -ChatPrompt itself
    if (Wait-ChatLog "sent" 20) { Start-Sleep -Seconds 3 }     # past prompt processing
    else { Write-Warning "app_stream: the app did not report the prompt sent" }
    Phase "app_stream"

    Write-Host "== waiting for the reply to end (<= $StreamEndTimeout s)"
    if (-not (Wait-ChatLog "done" $StreamEndTimeout)) { Write-Warning "reply still streaming or never started; idle2 is not idle" }
    Start-Sleep -Seconds 5

    Phase "idle2"
    if ($script:NoMetrics) { Write-Warning "llama /metrics unavailable (start llama-server with --metrics): only llama_gen has tokens/s" }
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
