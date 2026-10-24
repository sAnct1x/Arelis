"""Tests for Sentinel Strict Typed Envelopes, Tiered Authority Gate, and Deception Canary Grid."""

from __future__ import annotations

import pytest

from sentinel.core.authority import (
    AuthorityGate,
    is_inviolable_address,
)
from sentinel.core.deception import DeceptionCoordinator
from sentinel.core.hive import SwarmHive
from sentinel.core.schemas import (
    ActionBlastRadius,
    BrainActionCommand,
    MessageSeverity,
    ObservationEnvelope,
    ObservationPayload,
    ThreatIncidentEnvelope,
    ThreatIncidentPayload,
)


def test_inviolable_address_allowlist_protection() -> None:
    # Loopback and DNS must NEVER be allowed to be banned
    assert is_inviolable_address("127.0.0.1") is True
    assert is_inviolable_address("127.0.0.100") is True
    assert is_inviolable_address("localhost") is True
    assert is_inviolable_address("::1") is True
    assert is_inviolable_address("1.1.1.1") is True
    assert is_inviolable_address("8.8.8.8") is True

    # Hostile WAN/LAN IPs are not inviolable
    assert is_inviolable_address("198.51.100.42") is False
    assert is_inviolable_address("203.0.113.19") is False


def test_tiered_authority_gate_classification_and_leases() -> None:
    gate = AuthorityGate(default_lease_s=600.0)

    # 1. Tier 0: Read-only autonomous
    t0_ok, t0_req = gate.evaluate_request("SCAN_SOCKETS", "system", "Periodic socket audit")
    assert t0_ok is True
    assert t0_req.blast_radius == ActionBlastRadius.TIER_0_OBSERVE
    assert t0_req.auto_approved is True

    # 2. Tier 1: Reversible auto-expiring lease
    t1_ok, t1_req = gate.evaluate_request(
        "QUARANTINE_ARTIFACT",
        "/tmp/suspicious_payload.bin",
        "Polyglot magic byte anomaly",
    )
    assert t1_ok is True
    assert t1_req.blast_radius == ActionBlastRadius.TIER_1_REVERSIBLE
    assert t1_req.lease_duration_s == 600.0
    assert t1_req.expires_at is not None

    # 3. Tier 2: Irreversible -> Operator Approval Required
    t2_ok, t2_req = gate.evaluate_request(
        "TERMINATE_HOST_PROCESS",
        "PID:4821",
        "Unauthorized reverse shell lineage",
    )
    assert t2_ok is False
    assert t2_req.blast_radius == ActionBlastRadius.TIER_2_IRREVERSIBLE
    assert t2_req.auto_approved is False
    assert t2_req.operator_approved is False
    assert len(gate.list_pending_approvals()) == 1

    # Operator signs off
    signed = gate.operator_sign_off(t2_req.request_id, approve=True)
    assert signed.operator_approved is True
    assert len(gate.list_pending_approvals()) == 0

    # 4. Attempting to ban an inviolable loopback or DNS address must raise PermissionError
    with pytest.raises(PermissionError) as exc_info:
        gate.evaluate_request("PERMANENT_BAN_PEER", "127.0.0.1", "Spoofed attack")
    assert "Inviolable Safety Policy" in str(exc_info.value)


def test_strict_typed_envelope_schemas() -> None:
    obs = ObservationEnvelope(
        source_caste="warden",
        source_unit_id="SNT-WRD-001",
        message_id="MSG-001",
        observation=ObservationPayload(
            target="0.0.0.0:8765",
            metric_kind="socket_exposure",
            metric_value={"open": True, "established": 2},
            is_anomaly=False,
        ),
    )
    assert obs.schema_version == "1.0.0"
    assert obs.observation.metric_kind == "socket_exposure"

    incident = ThreatIncidentEnvelope(
        source_caste="sanitizer",
        source_unit_id="SNT-SAN-001",
        message_id="INC-001",
        incident=ThreatIncidentPayload(
            phase="POLYGLOT_EXECUTION",
            threat_level=MessageSeverity.CRITICAL,
            indicator_of_compromise="malicious_payload.elf",
            confidence=0.99,
            recommended_action="QUARANTINE_ARTIFACT",
            details={"file_size": 1024},
        ),
    )
    assert incident.incident.confidence == 0.99
    assert incident.incident.threat_level == MessageSeverity.CRITICAL

    cmd = BrainActionCommand(
        command_id="CMD-001",
        action_token="SCAN_SOCKETS",
        parameters={"timeout_s": 5.0},
    )
    assert cmd.action_token == "SCAN_SOCKETS"


def test_deception_canary_grid_and_tamper_detection(tmp_path) -> None:
    canary_dir = tmp_path / "canaries"
    coordinator = DeceptionCoordinator(base_dir=canary_dir)

    tokens = coordinator.list_tokens()
    assert len(tokens) >= 2  # aws_master_keys and sovereign_core_blueprint

    # Clean audit initially -> 0 tripped
    initial_trips = coordinator.audit_canary_integrity()
    assert len(initial_trips) == 0

    # Simulate adversary tampering with canary file
    canary_file = canary_dir / "aws_master_keys.json.canary"
    canary_file.write_text("TAMPERED HONEYTOKEN BY RED TEAM ADVERSARY", encoding="utf-8")

    # Audit again -> must detect 100% true-positive breach
    tripped = coordinator.audit_canary_integrity()
    assert len(tripped) == 1
    assert "TAMPERED" in tripped[0]["reason"]
    assert tripped[0]["envelope"]["incident"]["confidence"] == 1.0


@pytest.mark.asyncio
async def test_hive_authority_and_deception_integration() -> None:
    hive = SwarmHive()
    assert hasattr(hive, "authority")
    assert hasattr(hive, "deception")

    # Neutralizing an inviolable address like 127.0.0.1 must be vetoed safely without crash
    res = await hive.neutralize_target(ip="127.0.0.1", reason="Malicious spoof test")
    assert res["ok"] is False
    assert res.get("neutralized") is False
    assert "disabled" in res.get("error", "").lower()
