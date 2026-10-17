"""Strict Typed Envelopes and Schema Validation for Sentinel Message Bus.

Enforces zero free-text instructions to AI brain context windows.
Every observation, report, and task payload must conform to rigid schema.
Implemented with standard library dataclasses for zero extra external dependencies.
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
    """Tiered Action Authority classification."""
    TIER_0_OBSERVE = "TIER_0_OBSERVE"          # Read-only, zero system impact, autonomous
    TIER_1_REVERSIBLE = "TIER_1_REVERSIBLE"    # Auto-expiring, leased actions (quarantine, temp block)
    TIER_2_IRREVERSIBLE = "TIER_2_IRREVERSIBLE" # High-impact, permanent modification, requires operator approval


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
    """Strictly typed observation report. No unstructured prompts."""
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
    """Strictly typed threat detection report."""
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
    """Commands sent from Arelis or Human Operator to the Sentinel Swarm.
    
    Arelis's LLM brain CANNOT send free-text commands. It must select exclusively
    from this fixed, typed action menu.
    """
    command_id: str
    action_token: str
    parameters: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
