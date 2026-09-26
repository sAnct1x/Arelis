"""Cross-cutting host sample: RAM, CPU, GPU memory/util (Windows-friendly).

AMD cards on Windows rarely expose a clean ``nvidia-smi``. We read:

* process RAM / CPU via ``psutil`` when installed, else ctypes + ``os``
* GPU dedicated/shared bytes and engine util via Windows Performance Counters
  (``Get-Counter``), which Task Manager also uses
* optional Ollama ``/api/ps`` for which model is resident and its size

A 7B Q4 on a 12GB card often sits around 30-45% dedicated VRAM - that can be
correct, not a bug. This module exists so we measure instead of guessing.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------


@dataclass
class SystemSample:
    ts: float
    cpu_percent: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    gpu_dedicated_bytes: int | None = None
    gpu_shared_bytes: int | None = None
    gpu_util_percent: float | None = None
    gpu_name: str = ""
    ollama_models: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SampleSeries:
    samples: list[SystemSample] = field(default_factory=list)

    def add(self, sample: SystemSample) -> None:
        self.samples.append(sample)

    def peak(self, attr: str) -> float | int | None:
        vals = [getattr(s, attr) for s in self.samples if getattr(s, attr) is not None]
        return max(vals) if vals else None

    def mean(self, attr: str) -> float | None:
        vals = [float(getattr(s, attr)) for s in self.samples if getattr(s, attr) is not None]
        return sum(vals) / len(vals) if vals else None

    def summary(self) -> dict[str, Any]:
        ded_peak = self.peak("gpu_dedicated_bytes")
        shared_peak = self.peak("gpu_shared_bytes")
        util_peak = self.peak("gpu_util_percent")
        ram_peak = self.peak("ram_used_bytes")
        ram_total = next(
            (s.ram_total_bytes for s in self.samples if s.ram_total_bytes), None
        )
        return {
            "n_samples": len(self.samples),
            "gpu_dedicated_peak_bytes": ded_peak,
            "gpu_dedicated_peak_gib": _gib(ded_peak),
            "gpu_shared_peak_bytes": shared_peak,
            "gpu_shared_peak_gib": _gib(shared_peak),
            "gpu_util_peak_percent": util_peak,
            "gpu_util_mean_percent": self.mean("gpu_util_percent"),
            "cpu_mean_percent": self.mean("cpu_percent"),
            "ram_used_peak_bytes": ram_peak,
            "ram_used_peak_gib": _gib(ram_peak),
            "ram_total_gib": _gib(ram_total),
            "vram_fraction_of_12gib": (
                round(float(ded_peak) / (12 * 1024**3), 3) if ded_peak else None
            ),
        }


def _gib(n: int | float | None) -> float | None:
    if n is None:
        return None
    return round(float(n) / (1024**3), 3)


# ---------------------------------------------------------------------------
# Host RAM / CPU
# ---------------------------------------------------------------------------


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _sample_ram_windows() -> tuple[int | None, int | None]:
    if os.name != "nt":
        return None, None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None, None
        total = int(stat.ullTotalPhys)
        used = total - int(stat.ullAvailPhys)
        return used, total
    except Exception:
        return None, None


def _sample_cpu() -> float | None:
    try:
        import psutil  # type: ignore

        return float(psutil.cpu_percent(interval=0.0))
    except Exception:
        # Cheap fallback: load average is not on Windows; leave None.
        return None


# ---------------------------------------------------------------------------
# Windows GPU counters via PowerShell Get-Counter
# ---------------------------------------------------------------------------

_GPU_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{
  dedicated = $null
  shared = $null
  util = $null
  name = ''
}
try {
  $ded = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples |
    Where-Object { $_.CookedValue -gt 0 } |
    Sort-Object CookedValue -Descending |
    Select-Object -First 1
  if ($ded) { $out.dedicated = [int64]$ded.CookedValue; $out.name = $ded.InstanceName }
} catch {}
try {
  $shr = (Get-Counter '\GPU Adapter Memory(*)\Shared Usage').CounterSamples |
    Where-Object { $_.CookedValue -gt 0 } |
    Sort-Object CookedValue -Descending |
    Select-Object -First 1
  if ($shr) { $out.shared = [int64]$shr.CookedValue }
} catch {}
try {
  $eng = (Get-Counter '\GPU Engine(*)\Utilization Percentage').CounterSamples |
    Where-Object { $_.InstanceName -match 'engtype_3D|engtype_Compute' -and $_.CookedValue -ge 0 } |
    Sort-Object CookedValue -Descending |
    Select-Object -First 1
  if ($eng) { $out.util = [double]$eng.CookedValue }
} catch {}
$out | ConvertTo-Json -Compress
"""


def _sample_gpu_windows() -> tuple[int | None, int | None, float | None, str, list[str]]:
    notes: list[str] = []
    if os.name != "nt":
        notes.append("gpu counters: non-Windows host")
        return None, None, None, "", notes
    try:
        from arelis.hidden_proc import hidden_run

        proc = hidden_run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                _GPU_PS,
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except Exception as exc:
        notes.append(f"gpu counters failed: {exc}")
        return None, None, None, "", notes
    raw = (proc.stdout or "").strip()
    if not raw:
        notes.append("gpu counters empty (AMD/Intel drivers may omit them)")
        return None, None, None, "", notes
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        notes.append("gpu counters: bad JSON from PowerShell")
        return None, None, None, "", notes
    ded = data.get("dedicated")
    shared = data.get("shared")
    util = data.get("util")
    name = str(data.get("name") or "")
    return (
        int(ded) if ded is not None else None,
        int(shared) if shared is not None else None,
        float(util) if util is not None else None,
        name,
        notes,
    )


# ---------------------------------------------------------------------------
# Ollama resident models
# ---------------------------------------------------------------------------


def sample_ollama_ps(base_url: str = "http://127.0.0.1:11434") -> list[dict[str, Any]]:
    try:
        import httpx

        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/ps")
            resp.raise_for_status()
            models = resp.json().get("models") or []
            out = []
            for m in models:
                out.append(
                    {
                        "name": m.get("name") or m.get("model"),
                        "size": m.get("size"),
                        "size_vram": m.get("size_vram"),
                        "details": m.get("details") or {},
                    }
                )
            return out
    except Exception:
        return []


def sample_system(*, ollama_base_url: str | None = "http://127.0.0.1:11434") -> SystemSample:
    """One point-in-time sample of host + GPU + optional Ollama residency."""
    notes: list[str] = []
    ram_used, ram_total = _sample_ram_windows()
    if ram_used is None and platform.system() != "Windows":
        try:
            import resource  # noqa: F401

            # Best-effort on Unix via /proc
            with open("/proc/meminfo", encoding="utf-8") as f:
                info = f.read()
            total_kb = int(re.search(r"MemTotal:\s+(\d+)", info).group(1))
            avail_kb = int(re.search(r"MemAvailable:\s+(\d+)", info).group(1))
            ram_total = total_kb * 1024
            ram_used = (total_kb - avail_kb) * 1024
        except Exception:
            notes.append("ram sample unavailable")

    ded, shared, util, gpu_name, gpu_notes = _sample_gpu_windows()
    notes.extend(gpu_notes)

    ollama_models: list[dict[str, Any]] = []
    if ollama_base_url:
        ollama_models = sample_ollama_ps(ollama_base_url)

    return SystemSample(
        ts=time.time(),
        cpu_percent=_sample_cpu(),
        ram_used_bytes=ram_used,
        ram_total_bytes=ram_total,
        gpu_dedicated_bytes=ded,
        gpu_shared_bytes=shared,
        gpu_util_percent=util,
        gpu_name=gpu_name,
        ollama_models=ollama_models,
        notes=notes,
    )
