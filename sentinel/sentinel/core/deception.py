"""Canary files under the data directory.

audit_canary_integrity flags a canary when the file is missing or its SHA-256
no longer matches the digest stored at seed time. That is an existence and
hash check. It does not prove the change was hostile.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.receipts import ReceiptLedger
from sentinel.core.schemas import (
    ActionBlastRadius,
    MessageSeverity,
    ThreatIncidentEnvelope,
    ThreatIncidentPayload,
)
from sentinel.paths import data_dir

log = logging.getLogger("sentinel.deception")


class CanaryToken:
    """A deterministic canary token placed as bait."""

    def __init__(
        self,
        token_id: str,
        kind: str,
        path: Path,
        expected_digest: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.token_id = token_id
        self.kind = kind  # honey_file, fake_env, honey_key
        self.path = path
        self.expected_digest = expected_digest
        self.metadata = metadata or {}
        self.tripped = False
        self.tripped_at: float | None = None
        self.last_checked: float = time.time()


class DeceptionCoordinator:
    """Writes honey files under the canary directory and flags missing or hash-changed files."""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        bus: EventBus | None = None,
        ledger: ReceiptLedger | None = None,
    ) -> None:
        self.base_dir = (base_dir or data_dir() / "canaries").resolve()
        self.bus = bus
        self.ledger = ledger
        self._lock = threading.RLock()
        self._tokens: dict[str, CanaryToken] = {}
        self.ensure_canary_grid()

    def ensure_canary_grid(self) -> None:
        """Seed default high-signal honey tokens in isolated bait directory."""
        with self._lock:
            self.base_dir.mkdir(parents=True, exist_ok=True)

            # 1. Honey credential file (.env.production.canary)
            fake_env = self.base_dir / "aws_master_keys.json.canary"
            if not fake_env.exists():
                content = json.dumps(
                    {
                        "CANARY_WARNING": "THIS IS A DETECTIVE HONEYTOKEN. ANY USE IS PROSECUTED.",
                        "aws_access_key_id": "AKIA_CANARY_ARELIS_9876543210",
                        "aws_secret_access_key": "sec_canary_v871239857129837192837198273",
                    },
                    indent=2,
                )
                fake_env.write_text(content, encoding="utf-8")

            # 2. Honey research dossier
            honey_doc = self.base_dir / "sovereign_core_blueprint.pdf.canary"
            if not honey_doc.exists():
                honey_doc.write_text(
                    "ARELIS ARCHITECTURE // CLASSIFIED HONEYTOKEN // SHA256: CANARY_BAIT_101",
                    encoding="utf-8",
                )

            # Register tokens in internal registry
            for p in self.base_dir.glob("*.canary"):
                t_id = f"CANARY-{p.name}"
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
                self._tokens[t_id] = CanaryToken(
                    token_id=t_id,
                    kind="honey_file",
                    path=p,
                    expected_digest=digest,
                    metadata={"target_file": p.name},
                )

    def audit_canary_integrity(self) -> list[dict[str, Any]]:
        """Audit all canary tokens for modification, deletion, or access changes.
        
        Returns list of newly tripped canaries.
        """
        tripped_now: list[dict[str, Any]] = []
        with self._lock:
            for token in self._tokens.values():
                if token.tripped:
                    continue  # Already sounded alarm

                now = time.time()
                token.last_checked = now

                # 1. Check file existence
                if not token.path.exists():
                    token.tripped = True
                    token.tripped_at = now
                    incident = self._record_canary_breach(
                        token,
                        reason=f"Canary file DELETED by hostile actor: {token.path.name}",
                    )
                    tripped_now.append(incident)
                    continue

                # 2. Check content modification / tampering
                curr_digest = hashlib.sha256(token.path.read_bytes()).hexdigest()
                if curr_digest != token.expected_digest:
                    token.tripped = True
                    token.tripped_at = now
                    incident = self._record_canary_breach(
                        token,
                        reason=f"Canary content MODIFIED/TAMPERED: {token.path.name} (hash changed)",
                    )
                    tripped_now.append(incident)

        return tripped_now

    def _record_canary_breach(self, token: CanaryToken, reason: str) -> dict[str, Any]:
        log.critical("DECEPTION GRID ALARM TRIPPED: %s", reason)

        incident_envelope = ThreatIncidentEnvelope(
            source_caste="canary_grid",
            source_unit_id="CANARY-COORD-001",
            message_id=f"BREACH-{token.token_id}-{int(time.time())}",
            incident=ThreatIncidentPayload(
                phase="HONEYTOKEN ACCESSED / TAMPERED",
                threat_level=MessageSeverity.CRITICAL,
                indicator_of_compromise=token.path.name,
                confidence=1.0,  # fixed score on this envelope; the check is hash or existence only
                recommended_tier=ActionBlastRadius.TIER_1_REVERSIBLE,
                recommended_action="ISOLATE_PORT",
                details={
                    "token_id": token.token_id,
                    "kind": token.kind,
                    "path": str(token.path),
                    "reason": reason,
                },
            ),
        )

        receipt = None
        if self.ledger:
            receipt = self.ledger.mint(
                unit_id="CANARY-COORD-001",
                caste="canary_grid",
                kind="defense",
                source=str(token.path),
                span=reason,
                ok=False,
                metadata={"envelope": incident_envelope.model_dump()},
            )

        if self.bus:
            self.bus.publish_nowait(
                EventTopic.SECURITY_ALERT,
                {
                    "severity": "CRITICAL",
                    "caste": "canary_grid",
                    "message": reason,
                    "envelope": incident_envelope.model_dump(),
                    "receipt_id": receipt.receipt_id if receipt else None,
                },
            )

        return {
            "token_id": token.token_id,
            "reason": reason,
            "envelope": incident_envelope.model_dump(),
            "receipt_id": receipt.receipt_id if receipt else None,
        }

    def list_tokens(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "token_id": t.token_id,
                    "kind": t.kind,
                    "path": str(t.path),
                    "tripped": t.tripped,
                    "tripped_at": t.tripped_at,
                    "last_checked": t.last_checked,
                }
                for t in self._tokens.values()
            ]
