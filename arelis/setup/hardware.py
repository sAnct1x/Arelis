"""What this PC can actually hold.

The existing GPU sampler reads *usage* (Task Manager counters). Setup needs
*capacity*, how big the card is, so we do not recommend a 27B on a 4 GB
laptop because Chrome happened to be idle.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from arelis.telemetry.system_sample import _sample_ram_windows

log = logging.getLogger(__name__)

_VRAM_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
$class = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
Get-ChildItem $class -ErrorAction SilentlyContinue | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
  if ($null -eq $p) { return }
  $name = [string]$p.DriverDesc
  if (-not $name) { return }
  if ($name -match 'Microsoft Basic') { return }
  $bytes = $p.'HardwareInformation.qwMemorySize'
  if ($bytes -and [int64]$bytes -gt 512MB) {
    $rows += [pscustomobject]@{ name = $name; vram = [int64]$bytes }
  }
}
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits `
    2>$null | ForEach-Object {
    if (-not $_) { return }
    $parts = $_ -split ','
    if ($parts.Count -lt 2) { return }
    $mb = 0.0
    [void][double]::TryParse($parts[1].Trim(), [ref]$mb)
    if ($mb -gt 0) {
      $rows += [pscustomobject]@{ name = $parts[0].Trim(); vram = [int64]($mb * 1MB) }
    }
  }
}
$best = $rows | Sort-Object vram -Descending | Select-Object -First 1
$out = @{ name = ''; vram = $null }
if ($best) { $out.name = $best.name; $out.vram = $best.vram }
$out | ConvertTo-Json -Compress
"""


@dataclass(frozen=True)
class HardwareSnapshot:
    gpu_name: str = ""
    vram_bytes: int | None = None
    ram_bytes: int | None = None
    disk_free_bytes: int | None = None
    notes: tuple[str, ...] = ()

    @property
    def vram_gb(self) -> float | None:
        if self.vram_bytes is None:
            return None
        return round(self.vram_bytes / (1024**3), 1)

    @property
    def ram_gb(self) -> float | None:
        if self.ram_bytes is None:
            return None
        return round(self.ram_bytes / (1024**3), 1)

    @property
    def disk_free_gb(self) -> float | None:
        if self.disk_free_bytes is None:
            return None
        return round(self.disk_free_bytes / (1024**3), 1)

    def plain_card(self) -> str:
        """One sentence a person can read."""
        name = (self.gpu_name or "").strip()
        vram = self.vram_gb
        ram = self.ram_gb
        if name and vram:
            short = _short_gpu(name)
            return f"This PC has {short} with about {vram:g} GB of graphics memory."
        if name:
            return f"This PC has { _short_gpu(name) }. We could not read how large it is."
        if ram:
            return (
                f"We did not see a dedicated graphics card. This PC has about "
                f"{ram:g} GB of system memory."
            )
        return "We could not read this PC's graphics memory, so the recommendation is cautious."


def _short_gpu(name: str) -> str:
    text = " ".join(name.split())
    if len(text) <= 48:
        return text
    return text[:45] + "…"


def probe_hardware() -> HardwareSnapshot:
    """Best-effort. Never raises into the UI."""
    notes: list[str] = []
    gpu_name, vram, gpu_notes = _probe_vram()
    notes.extend(gpu_notes)
    _used, ram_total = _sample_ram_windows()
    if ram_total is None:
        notes.append("ram unread")
    disk = _disk_free()
    if disk is None:
        notes.append("disk unread")
    return HardwareSnapshot(
        gpu_name=gpu_name,
        vram_bytes=vram,
        ram_bytes=ram_total,
        disk_free_bytes=disk,
        notes=tuple(notes),
    )


_ROCM_VRAM = re.compile(r"VRAM Total Memory \(B\):\s*(\d+)")
_ROCM_SERIES = re.compile(r"Card series:\s*(.+)")
_PROBE_TIMEOUT_S = 5


def _probe_vram() -> tuple[str, int | None, list[str]]:
    if sys.platform == "win32":
        return _probe_vram_windows()
    if sys.platform == "darwin":
        return _probe_vram_darwin()
    return _probe_vram_linux()


def _probe_vram_windows() -> tuple[str, int | None, list[str]]:
    notes: list[str] = []
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
                _VRAM_PS,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        notes.append(f"vram probe failed: {exc}")
        return "", None, notes
    raw = (proc.stdout or "").strip()
    if not raw:
        notes.append("vram probe empty")
        return "", None, notes
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        notes.append("vram probe: bad JSON")
        return "", None, notes
    name = str(data.get("name") or "").strip()
    vram = data.get("vram")
    try:
        vram_i = int(vram) if vram is not None else None
    except (TypeError, ValueError):
        vram_i = None
    if vram_i is not None and vram_i <= 0:
        vram_i = None
    return name, vram_i, notes


def _hidden_probe(args: list[str]) -> str:
    from arelis.hidden_proc import hidden_run

    proc = hidden_run(
        args,
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
        check=False,
    )
    return (proc.stdout or "").strip()


def _unknown(notes: list[str], detail: str) -> tuple[str, int | None, list[str]]:
    notes.append(detail)
    return "", None, notes


def _probe_vram_linux() -> tuple[str, int | None, list[str]]:
    notes: list[str] = []
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            raw = _hidden_probe(
                [
                    nvidia,
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ]
            )
        except Exception as exc:
            notes.append(f"vram probe failed: {exc}")
        else:
            name, vram = _parse_nvidia_csv(raw)
            if vram:
                return name, vram, notes
            notes.append("vram probe empty")
    rocm = shutil.which("rocm-smi")
    if rocm:
        try:
            raw = _hidden_probe([rocm, "--showproductname", "--showmeminfo", "vram"])
        except Exception as exc:
            return _unknown(notes, f"vram probe failed: {exc}")
        name, vram = _parse_rocm(raw)
        if vram:
            return name, vram, notes
        return _unknown(notes, "vram probe empty")
    if not notes:
        notes.append("vram probe empty")
    return "", None, notes


def _parse_nvidia_csv(raw: str) -> tuple[str, int | None]:
    best_name = ""
    best = 0
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            mb = float(parts[1])
        except ValueError:
            continue
        if mb <= 0:
            continue
        size = int(mb * 1024 * 1024)
        if size > best:
            best = size
            best_name = parts[0]
    if best <= 0:
        return "", None
    return best_name, best


def _parse_rocm(raw: str) -> tuple[str, int | None]:
    best_name = ""
    best = 0
    series = ""
    for line in raw.splitlines():
        named = _ROCM_SERIES.search(line)
        if named:
            series = named.group(1).strip()
        found = _ROCM_VRAM.search(line)
        if not found:
            continue
        size = int(found.group(1))
        if size > best:
            best = size
            best_name = series or "AMD GPU"
    if best <= 0:
        return "", None
    return best_name, best


def _probe_vram_darwin() -> tuple[str, int | None, list[str]]:
    notes: list[str] = []
    exe = shutil.which("sysctl") or "/usr/sbin/sysctl"
    try:
        raw = _hidden_probe([exe, "-n", "hw.memsize"])
    except Exception as exc:
        return _unknown(notes, f"vram probe failed: {exc}")
    try:
        size = int(raw.split()[0])
    except (IndexError, ValueError):
        return _unknown(notes, "vram probe empty")
    if size <= 0:
        return _unknown(notes, "vram probe empty")
    return "Unified memory", size, notes


def _disk_free() -> int | None:
    target = os.environ.get("LOCALAPPDATA") or str(Path.home())
    try:
        return int(shutil.disk_usage(target).free)
    except OSError as exc:
        log.info("disk free unread: %s", exc)
        return None
