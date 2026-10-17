"""Deterministic SHA-256 Warrant & Evidence Receipt Ledger.

Every action taken by a Sentinel (harvesting a paper, sanitizing a payload,
blocking a port flood, or tripping a file hash alarm) mints an immutable
WarrantReceipt compatible with Arelis's EvidenceLedger.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sentinel.paths import ledger_path
from sentinel.safety.redact import redact_secrets


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8", errors="replace") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class WarrantReceipt:
    receipt_id: str
    unit_id: str
    caste: str
    kind: str  # "web" | "catalog" | "doc" | "sanitize" | "defense" | "tripwire"
    source: str
    ok: bool
    sha256: str
    span: str
    metadata: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_arelis_warrant(self) -> dict[str, Any]:
        """Export in the exact Warrant shape expected by Arelis's EvidenceLedger."""
        return {
            "source": redact_secrets(self.source)[:200],
            "kind": self.kind if self.kind in {"web", "doc", "calc", "recall", "analyze"} else "web",
            "span": redact_secrets(self.span)[:400],
            "ok": self.ok,
            "at": self.at,
            "sha256": self.sha256,
            "sentinel_unit": self.unit_id,
            "sentinel_caste": self.caste,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReceiptLedger:
    """Thread-safe in-memory + append-only JSONL disk ledger for Sentinel warrants."""

    def __init__(
        self,
        *,
        disk_path: Path | None = None,
        max_memory: int = 1000,
        max_disk_entries: int = 5000,
    ) -> None:
        self._lock = threading.RLock()
        self._items: deque[WarrantReceipt] = deque(maxlen=max_memory)
        self._counter = 0
        self._max_disk_entries = max(5, max_disk_entries)
        self._disk_path = disk_path if disk_path is not None else ledger_path()
        self._load_from_disk()

    def compact_disk_ledger(self, max_entries: int | None = None) -> int:
        """Compact the JSONL disk ledger keeping the latest max_entries while maintaining warrant data."""
        limit = max_entries if max_entries is not None else self._max_disk_entries
        with self._lock:
            if not self._disk_path.is_file():
                return 0
            try:
                lines = self._disk_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) <= limit:
                    return 0
                keep = [ln.strip() for ln in lines if ln.strip()][-limit:]
                tmp = self._disk_path.with_name(f"{self._disk_path.name}.tmp")
                tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                tmp.replace(self._disk_path)
                return len(lines) - len(keep)
            except OSError:
                return 0

    def _load_from_disk(self) -> None:
        if not self._disk_path.is_file():
            return
        try:
            lines = self._disk_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for raw_line in lines[-120:]:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                obj = json.loads(raw_line)
                if not isinstance(obj, dict) or "receipt_id" not in obj:
                    continue
                rid = str(obj.get("receipt_id") or "")
                parts = rid.split("-")
                if len(parts) >= 2 and parts[1].isdigit():
                    self._counter = max(self._counter, int(parts[1]))
                rec = WarrantReceipt(
                    receipt_id=rid,
                    unit_id=str(obj.get("unit_id") or "SNT-000"),
                    caste=str(obj.get("caste") or "harvester"),
                    kind=str(obj.get("kind") or "web"),
                    source=str(obj.get("source") or ""),
                    ok=bool(obj.get("ok", True)),
                    sha256=str(obj.get("sha256") or ""),
                    span=str(obj.get("span") or ""),
                    metadata=dict(obj.get("metadata") or {}),
                    at=str(obj.get("at") or datetime.now(UTC).isoformat()),
                )
                self._items.append(rec)
        except (OSError, ValueError, TypeError):
            pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def items(self) -> list[WarrantReceipt]:
        with self._lock:
            return list(self._items)

    def mint(
        self,
        *,
        unit_id: str,
        caste: str,
        kind: str,
        source: str,
        span: str,
        ok: bool,
        raw_content: str | bytes | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WarrantReceipt:
        clean_source = redact_secrets(str(source or "unknown"))[:300]
        clean_span = redact_secrets((span or "").strip())[:600] or "(empty)"
        digest = sha256_hex(raw_content if raw_content is not None else clean_span)

        with self._lock:
            self._counter += 1
            receipt_id = f"WRT-{self._counter:06d}-{digest[:8]}"
            receipt = WarrantReceipt(
                receipt_id=receipt_id,
                unit_id=unit_id,
                caste=caste,
                kind=kind,
                source=clean_source,
                ok=bool(ok),
                sha256=digest,
                span=clean_span,
                metadata=dict(metadata or {}),
            )
            self._items.append(receipt)
            self._append_disk_locked(receipt)
        return receipt

    def _append_disk_locked(self, receipt: WarrantReceipt) -> None:
        try:
            self._disk_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(receipt.to_dict(), separators=(",", ":"), ensure_ascii=False) + "\n"
            with self._disk_path.open("a", encoding="utf-8") as fp:
                fp.write(line)
            if self._counter > self._max_disk_entries:
                self.compact_disk_ledger()
        except OSError:
            pass

    def recent(self, limit: int = 50, *, caste: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items)
        if caste:
            items = [r for r in items if r.caste == caste]
        return [r.to_dict() for r in items[-limit:]]
