"""Dataclass envelopes for Sentinel bus messages and action records.

String fields and dict payloads are open. Nothing here rejects free-text
command fields. The loopback bridge reads a plain dict (op, question, query,
reason, and similar keys) and does not construct BrainActionCommand.
Implemented with standard library dataclasses.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class MessageSeverity(StrEnum):
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    THREAT = "THREAT"
    CRITICAL = "CRITICAL"


class ActionBlastRadius(StrEnum):
    """Labels classify_action returns. They do not gate live hive or bridge calls."""
    TIER_0_OBSERVE = "TIER_0_OBSERVE"          # evaluate_request returns allowed
    TIER_1_REVERSIBLE = "TIER_1_REVERSIBLE"    # evaluate_request records a lease and returns allowed
    TIER_2_IRREVERSIBLE = "TIER_2_IRREVERSIBLE" # evaluate_request returns blocked until operator_sign_off


@dataclass(frozen=True)
class SentinelBaseEnvelope:
    """Immutable base model for all Sentinel communications."""
    source_caste: str
    source_unit_id: str
    message_id: str
    schema_version: str = "1.0.0"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)



@dataclass(frozen=True)
class ObservationPayload:
    """Observation fields. target, metric_kind, and details are open values."""
    target: str
    metric_kind: str
    metric_value: Any
    is_anomaly: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObservationEnvelope(SentinelBaseEnvelope):
    """Published when Sentinels inspect system state."""
    observation: ObservationPayload = field(default_factory=lambda: ObservationPayload("", "", None))
    severity: MessageSeverity = MessageSeverity.INFO

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreatIncidentPayload:
    """Threat report fields. phase, indicator, and recommended_action are open strings.

    __post_init__ rejects a confidence outside 0.0 to 1.0. Other strings are not menu-checked.
    """
    phase: str
    indicator_of_compromise: str
    confidence: float
    recommended_action: str
    threat_level: MessageSeverity = MessageSeverity.THREAT
    recommended_tier: ActionBlastRadius = ActionBlastRadius.TIER_1_REVERSIBLE
    evidence_receipt_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence score must be in [0.0, 1.0], got {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreatIncidentEnvelope(SentinelBaseEnvelope):
    """Published when suspicious or hostile activity is intercepted."""
    incident: ThreatIncidentPayload = field(default_factory=lambda: ThreatIncidentPayload("", "", 0.0, ""))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionAuthorizationRequest:
    """Dispatched when an action requires tiered approval."""
    request_id: str
    action_token: str
    blast_radius: ActionBlastRadius
    target_identifier: str
    justification: str
    lease_duration_s: float | None = None
    auto_approved: bool = False
    operator_approved: bool = False
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)

    def copy_with(self, **changes: Any) -> ActionAuthorizationRequest:
        d = asdict(self)
        d.update(changes)
        return ActionAuthorizationRequest(**d)


@dataclass(frozen=True)
class BrainActionCommand:
    """Typed command record: an action token plus an open parameters dict.

    The bridge command handler does not read this type. It accepts free-text
    fields such as question, query, reason, and op on the JSON body.
    """
    command_id: str
    action_token: str
    parameters: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
