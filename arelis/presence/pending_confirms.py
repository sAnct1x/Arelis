"""Persist send confirms so they survive UI close / core-only mode.

Nothing is auto-sent. Allow still requires a human (UI card). Stored args are
used to execute send_sms / send_email only after Allow on a restored card.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

DEFAULT_STORE_NAME = "pending_confirms.json"
PERSIST_TOOLS = frozenset({"send_sms", "send_email"})


@dataclass
class PendingConfirm:
    id: str
    tool: str
    args: dict[str, str]
    summary: str
    detail: str = ""
    note: str = ""
    source: str = ""
    batch_ok: bool = False
    created_at: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": dict(self.args),
            "summary": self.summary,
            "detail": self.detail,
            "note": self.note,
            "source": self.source,
            "batch_ok": self.batch_ok,
        }


def pending_confirms_path(config: dict[str, Any] | None = None) -> Path:
    raw = ""
    if config:
        presence = config.get("presence") or {}
        raw = str(presence.get("pending_confirms_path") or "").strip()
    path = Path(raw) if raw else PROJECT_ROOT / "data" / DEFAULT_STORE_NAME
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


class PendingConfirmStore:
    """Thread-safe JSON list of outstanding send confirms."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def list(self) -> list[PendingConfirm]:
        with self._lock:
            return list(self._load_unlocked())

    def get(self, confirm_id: str) -> PendingConfirm | None:
        cid = str(confirm_id or "")
        for item in self.list():
            if item.id == cid:
                return item
        return None

    def upsert(self, item: PendingConfirm) -> None:
        if item.tool not in PERSIST_TOOLS:
            return
        with self._lock:
            items = self._load_unlocked()
            items = [x for x in items if x.id != item.id]
            if not item.created_at:
                item.created_at = datetime.now(UTC).isoformat()
            items.append(item)
            self._save_unlocked(items)

    def remove(self, confirm_id: str) -> PendingConfirm | None:
        cid = str(confirm_id or "")
        with self._lock:
            items = self._load_unlocked()
            kept: list[PendingConfirm] = []
            removed: PendingConfirm | None = None
            for item in items:
                if item.id == cid and removed is None:
                    removed = item
                else:
                    kept.append(item)
            if removed is not None:
                self._save_unlocked(kept)
            return removed

    def clear(self) -> None:
        with self._lock:
            self._save_unlocked([])

    def _load_unlocked(self) -> list[PendingConfirm]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read pending confirms %s: %s", self.path, exc)
            return []
        rows = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return []
        out: list[PendingConfirm] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tool = str(row.get("tool") or "")
            if tool not in PERSIST_TOOLS:
                continue
            cid = str(row.get("id") or "").strip()
            if not cid:
                continue
            args_raw = row.get("args") or {}
            args = {
                str(k): str(v)
                for k, v in args_raw.items()
                if isinstance(k, str)
            } if isinstance(args_raw, dict) else {}
            out.append(
                PendingConfirm(
                    id=cid,
                    tool=tool,
                    args=args,
                    summary=str(row.get("summary") or ""),
                    detail=str(row.get("detail") or ""),
                    note=str(row.get("note") or ""),
                    source=str(row.get("source") or ""),
                    batch_ok=bool(row.get("batch_ok", False)),
                    created_at=str(row.get("created_at") or ""),
                )
            )
        return out

    def _save_unlocked(self, items: list[PendingConfirm]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": [asdict(item) for item in items]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def pending_from_event_payload(payload: dict[str, Any]) -> PendingConfirm | None:
    """Build a store row from a TOOL_CONFIRM payload, or None if not persistable."""
    tool = str(payload.get("tool") or "")
    if tool not in PERSIST_TOOLS:
        return None
    cid = str(payload.get("id") or "").strip()
    if not cid:
        return None
    args_raw = payload.get("args") or {}
    args = {
        str(k): str(v)
        for k, v in args_raw.items()
        if isinstance(k, str)
    } if isinstance(args_raw, dict) else {}
    # Prefer full args stashed by auto-reply when present.
    full = payload.get("full_args")
    if isinstance(full, dict) and full:
        args = {str(k): str(v) for k, v in full.items() if isinstance(k, str)}
    return PendingConfirm(
        id=cid,
        tool=tool,
        args=args,
        summary=str(payload.get("summary") or ""),
        detail=str(payload.get("detail") or ""),
        note=str(payload.get("note") or ""),
        source=str(payload.get("source") or ""),
        batch_ok=bool(payload.get("batch_ok", False)),
    )
