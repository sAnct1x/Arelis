"""Declarative Dynamic Caste Handler for on-the-fly custom Sentinel creation."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

from sentinel.castes.base import CasteDescriptor, CasteHandler, PermissionViolationError
from sentinel.core.bus import EventBus
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger


class DynamicCasteHandler(CasteHandler):
    """Dynamic, narrow Sentinel Caste with strict capability sandboxing and FSM lifecycle."""

    def __init__(
        self,
        descriptor: CasteDescriptor,
        *,
        evaluator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self._evaluator = evaluator
        self._rules = rules or []

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        cid = self.descriptor.caste_id
        op = str(task_payload.get("capability") or task_payload.get("action") or "").strip()
        if not op:
            # Fall back to single allowed capability if exactly one exists
            if len(self.descriptor.allowed_capabilities) == 1:
                op = next(iter(self.descriptor.allowed_capabilities))
            else:
                raise PermissionViolationError(
                    f"Caste {cid!r} requires specifying a 'capability' or 'action' from {sorted(self.descriptor.allowed_capabilities)}"
                )

        self.descriptor.assert_capability(op)

        target_node_id = task_payload.get("node_id")
        target_pos = None
        if target_node_id and target_node_id in nodes:
            target_pos = list(nodes[target_node_id].position)
        elif task_payload.get("target_position"):
            target_pos = list(task_payload["target_position"])
        else:
            # Inspection point in orbit band
            r = self.descriptor.orbit_radius
            target_pos = [r * 0.7, self.descriptor.orbit_y_band, r * 0.7]

        task_label = str(task_payload.get("target") or task_payload.get("query") or op)[:64]

        # 1. Transition to VECTORING
        unit.transition(
            SentinelState.VECTORING,
            task=f"[{self.descriptor.code_prefix}] Vectoring -> {task_label}",
            target_node_id=target_node_id,
            target_position=target_pos,
        )
        await asyncio.sleep(0.04)

        # 2. Transition to ENGAGED_EXECUTION
        unit.transition(
            SentinelState.ENGAGED_EXECUTION,
            task=f"[{self.descriptor.code_prefix}] Executing {op} -> {task_label}",
            target_node_id=target_node_id,
            target_position=target_pos,
            laser_active=True,
            laser_kind=self.descriptor.laser_kind,
        )

        t0 = time.perf_counter()
        findings: dict[str, Any] = {}
        ok = True
        violations: list[str] = []

        try:
            if self._evaluator is not None:
                findings = await asyncio.to_thread(self._evaluator, task_payload)
                ok = bool(findings.get("ok", True))
                if not ok and "violations" in findings:
                    violations.extend(findings["violations"])
            else:
                # Declarative Rule Engine evaluation
                violations, findings = self._evaluate_rules(op, task_payload)
                ok = len(violations) == 0
        except (ValueError, TypeError, KeyError, RuntimeError, re.error, OSError) as exc:
            ok = False
            violations.append(f"Execution failed: {exc}")
            findings = {"error": str(exc)}


        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        unit.missions_completed += 1
        unit.bytes_processed += len(str(task_payload))

        # 3. Transition to RETURNING then PATROLLING
        unit.transition(
            SentinelState.RETURNING,
            task=f"[{self.descriptor.code_prefix}] Concluded {op}",
            laser_active=False,
        )
        await asyncio.sleep(0.02)
        unit.transition(
            SentinelState.PATROLLING,
            task=f"Patrolling {cid} sector",
            laser_active=False,
        )

        # 4. Mint cryptographic receipt
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=cid,
            kind=self.descriptor.laser_kind,
            source=f"sentinel://{cid}/{op}",
            span=f"{self.descriptor.title} executed {op} on {task_label} (ok={ok}, duration={duration_ms}ms)",
            ok=ok,
            metadata={
                "capability": op,
                "duration_ms": duration_ms,
                "violations": violations,
                "findings": findings,
            },
        )

        return {
            "ok": ok,
            "caste": cid,
            "unit_id": unit.unit_id,
            "capability": op,
            "duration_ms": duration_ms,
            "violations": violations,
            "findings": findings,
            "receipt": receipt.to_dict(),
        }

    def _evaluate_rules(self, op: str, payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        violations: list[str] = []
        rule_findings: dict[str, Any] = {}
        for idx, rule in enumerate(self._rules):
            cap_filter = rule.get("capability")
            if cap_filter and cap_filter != op:
                continue

            target_val = payload.get("data") or payload.get("target") or payload.get("content") or payload

            # Required fields rule
            req_fields = rule.get("required_fields")
            if isinstance(req_fields, list) and isinstance(target_val, dict):
                for rf in req_fields:
                    if rf not in target_val:
                        violations.append(f"Missing required field: {rf!r}")

            # Forbidden patterns (regex)
            patterns = rule.get("forbidden_patterns")
            if isinstance(patterns, list):
                str_val = str(target_val)
                for pat in patterns:
                    if re.search(pat, str_val, re.IGNORECASE):
                        violations.append(f"Forbidden pattern matched: {pat!r}")

            # Numeric bounds
            if "min_value" in rule and isinstance(target_val, (int, float)) and target_val < rule["min_value"]:
                violations.append(f"Value {target_val} below minimum {rule['min_value']}")
            if "max_value" in rule and isinstance(target_val, (int, float)) and target_val > rule["max_value"]:
                violations.append(f"Value {target_val} exceeds maximum {rule['max_value']}")


            rule_findings[f"rule_{idx}"] = {"evaluated": True, "violations_count": len(violations)}

        return violations, rule_findings
