"""Action-token classifier and inviolable-address helper.

classify_action and evaluate_request apply only when a caller invokes them:
- Tier 0 returns allowed.
- Tier 1 returns allowed and records a lease (default 900 seconds).
- Tier 2 returns not allowed until operator_sign_off.
Unknown tokens classify as Tier 2. Live harvest, ban, delete, and EMP paths
do not call evaluate_request.

is_inviolable_address is true for loopback (127.0.0.0/8, ::1, localhost),
link-local (169.254.0.0/16, fe80::/10), and four public DNS addresses
(1.1.1.1, 1.0.0.1, 8.8.8.8, 8.8.4.4). Warden.ban_peer refuses those.
There is no default-gateway entry and no LAN subnet in these sets.
"""

from __future__ import annotations

import ipaddress
import logging
import time
import uuid
from typing import Any

from sentinel.core.schemas import (
    ActionAuthorizationRequest,
    ActionBlastRadius,
)

log = logging.getLogger("sentinel.authority")

# Ranges is_inviolable_address treats as protected: IPv4 and IPv6 loopback and link-local.
INVIOLABLE_SUBNETS = (
    ipaddress.ip_network("127.0.0.0/8"),      # IPv4 Loopback
    ipaddress.ip_network("::1/128"),          # IPv6 Loopback
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local
    ipaddress.ip_network("fe80::/10"),        # IPv6 Link-Local
)

# Names and public DNS addresses treated as protected. Not a gateway and not a LAN subnet.
INVIOLABLE_HOSTS = {
    "127.0.0.1",
    "::1",
    "localhost",
    "1.1.1.1",
    "1.0.0.1",
    "8.8.8.8",
    "8.8.4.4",
}

# Blast-radius mapping for all Sentinel action tokens
ACTION_BLAST_MAP: dict[str, ActionBlastRadius] = {
    # Tier 0 (Observe)
    "SCAN_SOCKETS": ActionBlastRadius.TIER_0_OBSERVE,
    "INSPECT_PATH": ActionBlastRadius.TIER_0_OBSERVE,
    "AUDIT_PROCESSES": ActionBlastRadius.TIER_0_OBSERVE,
    "VERIFY_MERKLE": ActionBlastRadius.TIER_0_OBSERVE,
    "GET_SNAPSHOT": ActionBlastRadius.TIER_0_OBSERVE,
    "PING": ActionBlastRadius.TIER_0_OBSERVE,

    # Tier 1 (Reversible / Auto-Expiring Leases)
    "QUARANTINE_ARTIFACT": ActionBlastRadius.TIER_1_REVERSIBLE,
    "TEMP_BAN_PEER": ActionBlastRadius.TIER_1_REVERSIBLE,
    "ISOLATE_PORT": ActionBlastRadius.TIER_1_REVERSIBLE,
    "EMP_HALT": ActionBlastRadius.TIER_1_REVERSIBLE,
    "EMP_RESTORE": ActionBlastRadius.TIER_1_REVERSIBLE,
    "SCALE_CASTE": ActionBlastRadius.TIER_1_REVERSIBLE,

    # Tier 2 (Irreversible / Destructive -> Human Approval Required)
    "PERMANENT_BAN_PEER": ActionBlastRadius.TIER_2_IRREVERSIBLE,
    "TERMINATE_HOST_PROCESS": ActionBlastRadius.TIER_2_IRREVERSIBLE,
    "DELETE_QUARANTINE_FILE": ActionBlastRadius.TIER_2_IRREVERSIBLE,
    "OVERWRITE_SYSTEM_FILE": ActionBlastRadius.TIER_2_IRREVERSIBLE,
    "FLUSH_FIREWALL_RULES": ActionBlastRadius.TIER_2_IRREVERSIBLE,
}


def is_inviolable_address(ip_str: str) -> bool:
    """Return True for empty input, loopback, link-local, localhost names, or INVIOLABLE_HOSTS.

    Other LAN and WAN addresses return False. The host set is four public DNS
    addresses (1.1.1.1, 1.0.0.1, 8.8.8.8, 8.8.4.4) plus localhost names.
    """
    clean = (ip_str or "").strip().lower()
    if not clean:
        return True
    if clean in INVIOLABLE_HOSTS:
        return True
    clean_ip = clean.removeprefix("::ffff:")
    try:
        addr = ipaddress.ip_address(clean_ip)
        for subnet in INVIOLABLE_SUBNETS:
            if addr in subnet:
                return True
    except ValueError:
        pass
    return False


class AuthorityGate:
    """Enforces blast-radius policies, lease auto-expiry, and operator sign-offs."""

    def __init__(self, *, default_lease_s: float = 900.0) -> None:
        self.default_lease_s = default_lease_s  # 15 minutes default for Tier 1
        self._pending_approvals: dict[str, ActionAuthorizationRequest] = {}
        self._active_leases: dict[str, ActionAuthorizationRequest] = {}

    def classify_action(self, action_token: str) -> ActionBlastRadius:
        """Map action token to blast radius; defaults to Tier 2 if unknown (fail-safe)."""
        token = action_token.upper().strip()
        return ACTION_BLAST_MAP.get(token, ActionBlastRadius.TIER_2_IRREVERSIBLE)

    def evaluate_request(
        self,
        action_token: str,
        target_identifier: str,
        justification: str,
        *,
        lease_duration_s: float | None = None,
    ) -> tuple[bool, ActionAuthorizationRequest]:
        """Classify one submitted token and apply the inviolable-address check for ban tokens.

        Returns (allowed_now, auth_request). Hive, bridge, and caste execute paths do not call this.
        """
        token = action_token.upper().strip()
        radius = self.classify_action(token)

        # Ban tokens whose target is_inviolable_address are refused in this method.
        if token in {"TEMP_BAN_PEER", "PERMANENT_BAN_PEER"} and is_inviolable_address(target_identifier):
            raise PermissionError(

                    f"Action {token} blocked by Inviolable Safety Policy: Target {target_identifier!r} "
                    "is a protected loopback, DNS, or gateway infrastructure address."
                )

        req_id = f"AUTH-{uuid.uuid4().hex[:12].upper()}"
        now = time.time()

        # 2. Tier 0: Autonomous execution immediately
        if radius == ActionBlastRadius.TIER_0_OBSERVE:
            req = ActionAuthorizationRequest(
                request_id=req_id,
                action_token=token,
                blast_radius=radius,
                target_identifier=target_identifier,
                justification=justification,
                auto_approved=True,
                operator_approved=False,
                created_at=now,
            )
            return True, req

        # 3. Tier 1: Autonomous with lease & auto-expiry
        if radius == ActionBlastRadius.TIER_1_REVERSIBLE:
            lease = float(lease_duration_s if lease_duration_s is not None else self.default_lease_s)
            req = ActionAuthorizationRequest(
                request_id=req_id,
                action_token=token,
                blast_radius=radius,
                target_identifier=target_identifier,
                lease_duration_s=lease,
                justification=justification,
                auto_approved=True,
                operator_approved=False,
                created_at=now,
                expires_at=now + lease,
            )
            self._active_leases[req_id] = req
            return True, req

        # 4. Tier 2: Blocked until Operator Signs Off
        req = ActionAuthorizationRequest(
            request_id=req_id,
            action_token=token,
            blast_radius=radius,
            target_identifier=target_identifier,
            justification=justification,
            auto_approved=False,
            operator_approved=False,
            created_at=now,
        )
        self._pending_approvals[req_id] = req
        log.warning(
            "TIER 2 ACTION BLOCKED PENDING OPERATOR SIGN-OFF: [%s] on %s. Request ID: %s",
            token,
            target_identifier,
            req_id,
        )
        return False, req

    def operator_sign_off(self, request_id: str, *, approve: bool) -> ActionAuthorizationRequest:
        """Process operator approval or rejection of Tier 2 action."""
        if request_id not in self._pending_approvals:
            raise KeyError(f"No pending authorization request with ID: {request_id}")
        
        req = self._pending_approvals.pop(request_id)
        if not approve:
            log.info("Operator REJECTED Tier 2 request %s (%s on %s)", request_id, req.action_token, req.target_identifier)
            return req

        updated = req.copy_with(operator_approved=True)
        log.info("Operator APPROVED Tier 2 request %s (%s on %s)", request_id, req.action_token, req.target_identifier)
        return updated


    def list_pending_approvals(self) -> list[dict[str, Any]]:
        return [r.model_dump() for r in self._pending_approvals.values()]

    def list_active_leases(self) -> list[dict[str, Any]]:
        now = time.time()
        # Clean expired
        expired = [k for k, v in self._active_leases.items() if v.expires_at and v.expires_at <= now]
        for k in expired:
            self._active_leases.pop(k, None)
        return [r.model_dump() for r in self._active_leases.values()]
