"""Always-on presence: core process, tray, pending confirms, inbound runtime.

See docs/architecture.md (core / tray).
"""

from __future__ import annotations

from arelis.presence.core import run_core
from arelis.presence.inbound_runtime import InboundRuntime, attach_inbound
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import (
    PresenceLock,
    core_lock_path,
    probe_ingest_health,
    ui_lock_path,
)
from arelis.presence.open_ui import ensure_ui_open, spawn_ui_subprocess
from arelis.presence.pending_confirms import PendingConfirmStore, pending_confirms_path
from arelis.presence.readiness import (
    ChipLevel,
    ReadinessChip,
    ReadinessSnapshot,
    probe_readiness,
)
from arelis.presence.tray import CoreTray

__all__ = [
    "ChipLevel",
    "CoreTray",
    "InboundRuntime",
    "IpcClient",
    "IpcServer",
    "PendingConfirmStore",
    "PresenceLock",
    "ReadinessChip",
    "ReadinessSnapshot",
    "attach_inbound",
    "core_lock_path",
    "ensure_ui_open",
    "pending_confirms_path",
    "probe_ingest_health",
    "probe_readiness",
    "run_core",
    "spawn_ui_subprocess",
    "ui_lock_path",
]
