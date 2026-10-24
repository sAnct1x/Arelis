"""Structured telemetry log for Sentinel.

record() appends one entry to an in-memory ring and to logs/sentinel_telemetry.jsonl
and logs/sentinel_events.log. It logs the events callers pass in. It does not
observe every packet or every socket on the host by itself.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sentinel.paths import logs_dir
from sentinel.safety.redact import redact_secrets


@dataclass(frozen=True)
class TelemetryEntry:
    seq: int
    timestamp: float
    iso_time: str
    level: str  # "INFO" | "HARVEST" | "SANITIZE" | "WARDEN" | "TRIPWIRE" | "ALERT" | "CRITICAL" | "EMP"
    unit_id: str
    caste: str
    phase: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelemetryLogger:
    """Thread-safe structured telemetry logger for the Hive and 3D Overseer."""

    def __init__(
        self,
        *,
        max_entries: int = 250,
        log_dir: Path | None = None,
        max_file_bytes: int = 5_242_880,
        max_backups: int = 2,
    ) -> None:
        self._lock = threading.Lock()
        self._entries: deque[TelemetryEntry] = deque(maxlen=max_entries)
        self._seq = 0
        base_dir = log_dir if log_dir is not None else logs_dir()
        self._jsonl_path = base_dir / "sentinel_telemetry.jsonl"
        self._text_path = base_dir / "sentinel_events.log"
        self._max_file_bytes = max(256, max_file_bytes)
        self._max_backups = max(1, min(max_backups, 10))

    @property
    def jsonl_path(self) -> Path:
        return self._jsonl_path

    @property
    def text_path(self) -> Path:
        return self._text_path

    def _rotate_if_needed_locked(self, file_path: Path) -> bool:
        """Rotate a log file if it exceeds the maximum size limit."""
        if not file_path.is_file():
            return False
        try:
            if file_path.stat().st_size < self._max_file_bytes:
                return False
            for i in range(self._max_backups - 1, 0, -1):
                src = file_path.with_name(f"{file_path.name}.{i}")
                dst = file_path.with_name(f"{file_path.name}.{i + 1}")
                if src.is_file():
                    src.replace(dst)
            b1 = file_path.with_name(f"{file_path.name}.1")
            file_path.replace(b1)
            return True
        except OSError:
            return False

    def prune_disk_logs(
        self,
        *,
        max_bytes: int | None = None,
        max_backups: int | None = None,
    ) -> dict[str, Any]:
        """Prune or rotate disk logs to prevent unbounded storage consumption."""
        mb = max_bytes if max_bytes is not None else self._max_file_bytes
        bk = max_backups if max_backups is not None else self._max_backups
        rotated: list[str] = []
        removed_backups: list[str] = []

        with self._lock:
            for p in (self._jsonl_path, self._text_path):
                if p.is_file():
                    try:
                        if p.stat().st_size > mb and self._rotate_if_needed_locked(p):
                            rotated.append(p.name)
                    except OSError:
                        pass
                # Remove backups exceeding retention limit
                for backup_file in p.parent.glob(f"{p.name}.*"):
                    try:
                        idx = int(backup_file.name.rsplit(".", 1)[-1])
                        if idx > bk:
                            backup_file.unlink(missing_ok=True)
                            removed_backups.append(backup_file.name)
                    except (ValueError, OSError):
                        continue

        return {"rotated": rotated, "removed_backups": removed_backups}

    def record(
        self,
        level: str,
        *,
        unit_id: str = "HIVE-CORE",
        caste: str = "core",
        phase: str = "SYSTEM",
        message: str,
        details: dict[str, Any] | None = None,
    ) -> TelemetryEntry:
        now = time.time()
        iso = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
        clean_msg = redact_secrets(message)[:500]
        clean_details = details or {}

        with self._lock:
            self._seq += 1
            entry = TelemetryEntry(
                seq=self._seq,
                timestamp=now,
                iso_time=iso,
                level=level.upper(),
                unit_id=unit_id,
                caste=caste,
                phase=phase,
                message=clean_msg,
                details=clean_details,
            )
            self._entries.append(entry)
            self._write_disk_locked(entry)
        return entry

    def _write_disk_locked(self, entry: TelemetryEntry) -> None:
        try:
            # Check rotation periodically (every 25 events or scaled for tiny test limits)
            check_interval = max(1, min(25, self._max_file_bytes // 200))
            if self._seq % check_interval == 0:
                self._rotate_if_needed_locked(self._jsonl_path)
                self._rotate_if_needed_locked(self._text_path)

            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self._jsonl_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry.to_dict(), separators=(",", ":"), ensure_ascii=False) + "\n")
            with self._text_path.open("a", encoding="utf-8") as fp:
                fp.write(
                    f"[{entry.iso_time}] [{entry.level:<8}] [{entry.unit_id:<11}] "
                    f"({entry.phase}) {entry.message}\n"
                )
        except OSError:
            pass

    def recent(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._entries)[-limit:]
        return [e.to_dict() for e in items]
