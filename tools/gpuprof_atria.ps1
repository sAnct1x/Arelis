<#
.SYNOPSIS
  Her GPU cost per pass, on Atria: each ablation configuration for 20 s idle, then 20 s while the 35B streams.

.DESCRIPTION
  Measurement build only (branch avatar/qq3d-gpuprof; see arelis/ui/persona_face/gpuprof.py).
  For each configuration it starts Arelis fresh (qq3d engine, d3d11, Filament), places the window
  at 2560x1440, waits for her first frames, settles, records 20 s idle, then streams a long reply
  from llama-server for 20 s (straight to its HTTP API, so the 35B loads the GPU the same way
  without typing into the app), then closes Arelis. Every second it logs GPU 3D-engine
  utilisation for llama-server and for Arelis (Windows "GPU Engine" counters).

  Writes into -Out:
    frames_<config>.csv   per frame: t_epoch_ms,gpu_ms,interval_ms (ARELIS_GPU_PROFILE_LOG)
    phases.csv            config,phase,start_ms,end_ms
    gpu_util.csv          t_epoch_ms,llama_util,app_util (every second, whole run)
    arelis_<config>.log   stdout/stderr of each launch
    summary.csv           GPU ms p50/p95, interval p50/p95, share over 33 ms, mean util,
                          per configuration and phase (tools/gpuprof_summary.py)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\gpuprof_atria.ps1 -Python C:\path\.venv\Scripts\python.exe `
      -QQ3DDir C:\Users\Public\ArelisTest\babbage\qq3d -Out \\...\team\avatar-v14k\diag\gpuprof
#>
param(
    [string]$Repo = (Resolve-Path "$PSScriptRoot\.."),
    [string]$Python = "$Repo\.venv\Scripts\python.exe",
    [string]$QQ3DDir = "C:\Users\Public\ArelisTest\babbage\qq3d",
    [string]$Out = $(if ($env:ARELIS_TEAM_DIR) { "$env:ARELIS_TEAM_DIR\avatar-v14k\diag\gpuprof" } else { "$PSScriptRoot\..\diag\gpuprof" }),
    [string]$Llama = "http://127.0.0.1:8080",
    [int]$X = 0, [int]$Y = 0, [int]$Width = 2560, [int]$Height = 1440,
    [int]$IdleSeconds = 20, [int]$StreamSeconds = 20, [int]$SettleSeconds = 8, [int]$ReadyTimeout = 90,
    [string[]]$Only = @()
)
$ErrorActionPreference = "Stop"

# name = env vars on top of the base set; every pass switchable on its own.
$Configs = [ordered]@{
    "base"        = @{}
    "nobloom"     = @{ ARELIS_GPU_NO_BLOOM = "1" }
    "bloomhalf"   = @{ ARELIS_GPU_BLOOM_HALF = "1" }
    "noparticles" = @{ ARELIS_GPU_NO_PARTICLES = "1" }
    "nohair"      = @{ ARELIS_GPU_NO_HAIR = "1" }
    "composite"   = @{ ARELIS_GPU_COMPOSITE_ONLY = "1" }
    "scale075"    = @{ ARELIS_GPU_RENDER_SCALE = "0.75" }
    "scale05"     = @{ ARELIS_GPU_RENDER_SCALE = "0.5" }
}
if ($Only.Count) { $keep = [ordered]@{}; foreach ($k in $Only) { $keep[$k] = $Configs[$k] }; $Configs = $keep }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Out = (Resolve-Path $Out).Path
"config,phase,start_ms,end_ms" | Set-Content -Encoding ascii "$Out\phases.csv"
function Now-Ms { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }

Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
"@

# --- GPU utilisation sampler, every second, for the whole run -------------------------------
$llamaPid = (Get-Process llama-server -ErrorAction SilentlyContinue | Select-Object -First 1).Id
if (-not $llamaPid) { Write-Warning "llama-server is not running: streaming phases will not load the GPU" }
$sampler = Start-Job -ArgumentList "$Out\gpu_util.csv", $llamaPid -ScriptBlock {
    param($path, $llamaPid)
    "t_epoch_ms,llama_util,app_util" | Set-Content -Encoding ascii $path
    while ($true) {
        $t = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $llama = 0.0; $app = 0.0
        try {
            $appPids = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
                Where-Object { $_.CommandLine -match "-m arelis" } | ForEach-Object { $_.ProcessId })
            $s = (Get-Counter "\GPU Engine(*engtype_3D)\Utilization Percentage" -ErrorAction SilentlyContinue).CounterSamples
            foreach ($c in $s) {
                if ($c.InstanceName -match "pid_(\d+)_") {
                    $p = [int]$Matches[1]
                    if ($p -eq $llamaPid) { $llama += $c.CookedValue }
                    elseif ($appPids -contains $p) { $app += $c.CookedValue }
                }
            }
            # llama-server's CUDA work shows under the Compute/Cuda engines, not 3D.
            $cs = (Get-Counter "\GPU Engine(pid_$($llamaPid)_*)\Utilization Percentage" -ErrorAction SilentlyContinue).CounterSamples
            $llama = [math]::Max($llama, (($cs | Measure-Object CookedValue -Maximum).Maximum))
        } catch {}
        "{0},{1:F1},{2:F1}" -f $t, $llama, $app | Add-Content -Encoding ascii $path
        $left = 1000 - ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $t)
        if ($left -gt 0) { Start-Sleep -Milliseconds $left }
    }
}

# --- one streamed reply from the 35B, cut off after N seconds -------------------------------
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

try {
    foreach ($name in $Configs.Keys) {
        Write-Host "== $name"
        $frames = "$Out\frames_$name.csv"
        Remove-Item $frames -ErrorAction SilentlyContinue
        $envs = @{
            ARELIS_AVATAR_ENGINE = "qq3d"; ARELIS_QT_RHI = "d3d11"; ARELIS_AVATAR_QQ3D_DIR = $QQ3DDir
            ARELIS_GPU_PROFILE = "1"; ARELIS_GPU_PROFILE_LOG = $frames; QSG_RHI_PROFILE = "1"; QSG_INFO = "1"
            ARELIS_GPU_NO_BLOOM = ""; ARELIS_GPU_BLOOM_HALF = ""; ARELIS_GPU_NO_PARTICLES = ""; ARELIS_GPU_NO_HAIR = ""
            ARELIS_GPU_COMPOSITE_ONLY = ""; ARELIS_GPU_RENDER_SCALE = ""; ARELIS_GPU_HIDE = ""
        }
        foreach ($k in $Configs[$name].Keys) { $envs[$k] = $Configs[$name][$k] }
        foreach ($k in $envs.Keys) { Set-Item "env:$k" $envs[$k] }
        $p = Start-Process -FilePath $Python -ArgumentList "-m", "arelis" -WorkingDirectory $Repo -PassThru `
            -RedirectStandardOutput "$Out\arelis_$name.log" -RedirectStandardError "$Out\arelis_$name.err.log"
        # ready = her frames are being logged
        $deadline = (Get-Date).AddSeconds($ReadyTimeout)
        while ((Get-Date) -lt $deadline -and -not ((Test-Path $frames) -and (Get-Content $frames).Count -gt 30)) { Start-Sleep -Milliseconds 500 }
        if (-not ((Test-Path $frames) -and (Get-Content $frames).Count -gt 30)) { Write-Warning "$name : no frames logged in $ReadyTimeout s" }
        $p.Refresh()
        if ($p.MainWindowHandle -ne 0) {
            [W]::ShowWindow($p.MainWindowHandle, 9) | Out-Null   # SW_RESTORE
            [W]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, $X, $Y, $Width, $Height, 0x0040) | Out-Null
        } else { Write-Warning "$name : no main window handle; size not set" }
        Start-Sleep -Seconds $SettleSeconds

        $a = Now-Ms; Start-Sleep -Seconds $IdleSeconds; $b = Now-Ms
        "$name,idle,$a,$b" | Add-Content -Encoding ascii "$Out\phases.csv"

        $job = Start-Stream $StreamSeconds
        Start-Sleep -Seconds 2                     # past prompt processing, into token streaming
        $a = Now-Ms; Start-Sleep -Seconds ($StreamSeconds - 2); $b = Now-Ms
        "$name,stream,$a,$b" | Add-Content -Encoding ascii "$Out\phases.csv"
        $r = Receive-Job $job -Wait -AutoRemoveJob -ErrorAction SilentlyContinue
        Write-Host "   stream $r"

        Stop-Process -Id $p.Id -ErrorAction SilentlyContinue
        $p.WaitForExit(15000) | Out-Null
        Start-Sleep -Seconds 3
    }
} finally {
    Stop-Job $sampler -ErrorAction SilentlyContinue; Remove-Job $sampler -Force -ErrorAction SilentlyContinue
}
& $Python "$Repo\tools\gpuprof_summary.py" $Out
Write-Host "summary: $Out\summary.csv"
