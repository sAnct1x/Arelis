"""What this PC can actually hold.

The existing GPU sampler reads *usage* (Task Manager counters). Setup needs
*capacity* — how big the card is — so we do not recommend a 27B on a 4 GB
laptop because Chrome happened to be idle.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
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


def _probe_vram() -> tuple[str, int | None, list[str]]:
    notes: list[str] = []
    if os.name != "nt":
        notes.append("vram: not Windows")
        return "", None, notes
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


def _disk_free() -> int | None:
    target = os.environ.get("LOCALAPPDATA") or str(Path.home())
    try:
        return int(shutil.disk_usage(target).free)
    except OSError as exc:
        log.info("disk free unread: %s", exc)
        return None
