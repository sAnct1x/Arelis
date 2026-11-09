"""Declarative Dynamic Caste Handler for on-the-fly custom Sentinel creation."""

from __future__ import annotations

import asyncio
import functools
import re
import time
from collections.abc import Mapping
from typing import Any

from sentinel.castes.base import CasteDescriptor, CasteHandler, PermissionViolationError
from sentinel.core.bus import EventBus
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger

MAX_DYNAMIC_CASTES = 16
MAX_CAPS_PER_CASTE = 8
MAX_PURPOSE_CHARS = 240
MAX_TITLE_CHARS = 80
MAX_RULES = 12
MAX_PATTERNS_PER_RULE = 6
MAX_PATTERN_CHARS = 80
MAX_REQUIRED_FIELDS = 8
MAX_FIELD_NAME = 40
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
CAP_RE = re.compile(r"^[a-z][a-z0-9_:]{1,63}$")
RULE_KEYS = frozenset({
    "capability",
    "required_fields",
    "forbidden_patterns",
    "min_value",
    "max_value",
})
FORBIDDEN_RULE_KEYS = frozenset({
    "expr", "expression", "eval", "exec", "code", "script", "python", "handler",
})


@functools.lru_cache(maxsize=1)
def builtin_caste_ids() -> frozenset[str]:
    from sentinel.castes import build_default_caste_registry

    return frozenset(build_default_caste_registry().caste_ids)


@functools.lru_cache(maxsize=1)
def builtin_capability_union() -> frozenset[str]:
    """Union of built-in caste tools only. Dynamic registrations never widen this."""
    from sentinel.castes import build_default_caste_registry

    caps: set[str] = set()
    registry = build_default_caste_registry()
    for cid in registry.caste_ids:
        caps |= set(registry.get(cid).descriptor.allowed_capabilities)
    return frozenset(caps)


def _as_plain_text(value: Any, *, field: str) -> str:
    if isinstance(value, (list, tuple, dict, set)):
        raise ValueError(
            f"{field} must be exactly one plain-text string, not {type(value).__name__}"
        )
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _validate_rules(rules: Any) -> list[dict[str, Any]]:
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise ValueError("rules must be a list of bound field and pattern checks")
    if len(rules) > MAX_RULES:
        raise ValueError(f"at most {MAX_RULES} rules are allowed")
    out: list[dict[str, Any]] = []
    allowed = builtin_capability_union()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("each rule must be an object")
        extra = set(rule) - RULE_KEYS
        hostile = extra & FORBIDDEN_RULE_KEYS
        if hostile:
            raise ValueError(
                f"rules cannot include executable keys {sorted(hostile)}"
            )
        if extra:
            raise ValueError(f"unknown rule keys: {sorted(extra)}")
        cleaned: dict[str, Any] = {}
        cap = rule.get("capability")
        if cap is not None:
            cap_s = str(cap).strip()
            if not CAP_RE.match(cap_s) or cap_s not in allowed:
                raise ValueError(f"rule capability {cap_s!r} is not a built-in capability")
            cleaned["capability"] = cap_s
        req = rule.get("required_fields")
        if req is not None:
            if not isinstance(req, list) or len(req) > MAX_REQUIRED_FIELDS:
                raise ValueError("required_fields is over the bound")
            fields = []
            for item in req:
                name = str(item).strip()
                if not name or len(name) > MAX_FIELD_NAME or "/" in name or chr(92) in name:
                    raise ValueError(f"required field name {name!r} is not safe")
                fields.append(name)
            cleaned["required_fields"] = fields
        pats = rule.get("forbidden_patterns")
        if pats is not None:
            if not isinstance(pats, list) or len(pats) > MAX_PATTERNS_PER_RULE:
                raise ValueError("forbidden_patterns is over the bound")
            compiled = []
            for pat in pats:
                text = str(pat)
                if len(text) > MAX_PATTERN_CHARS:
                    raise ValueError("a forbidden pattern exceeds the length bound")
                try:
                    re.compile(text)
                except re.error as exc:
                    raise ValueError(f"invalid forbidden pattern: {exc}") from exc
                compiled.append(text)
            cleaned["forbidden_patterns"] = compiled
        for key in ("min_value", "max_value"):
            if key in rule:
                raw = rule[key]
                if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                    raise ValueError(f"{key} must be a number")
                cleaned[key] = raw
        out.append(cleaned)
    return out


def validate_dynamic_spec(
    *,
    caste_id: str,
    code_prefix: str,
    title: str,
    single_purpose: Any,
    allowed_capabilities: Any,
    rules: Any = None,
    purposes: Any = None,
    extra_purpose: Any = None,
) -> dict[str, Any]:
    """Reject unsafe names, unknown capabilities, and more than one purpose field."""
    if purposes is not None or extra_purpose is not None:
        raise ValueError("exactly one purpose field is allowed (single_purpose)")
    purpose = _as_plain_text(single_purpose, field="single_purpose")
    if len(purpose) > MAX_PURPOSE_CHARS:
        raise ValueError(f"single_purpose exceeds {MAX_PURPOSE_CHARS} characters")
    cid = str(caste_id or "").strip().lower()
    if not NAME_RE.match(cid):
        raise ValueError(
            "caste_id must be a lowercase identifier of 2 to 32 letters, digits, or _"
        )
    if cid in builtin_caste_ids():
        raise ValueError(f"caste name {cid!r} clashes with a built-in caste")
    prefix = str(code_prefix or "").strip().upper() or cid[:3].upper()
    if not PREFIX_RE.match(prefix):
        raise ValueError("code_prefix must be 2 to 6 uppercase letters or digits")
    title_s = _as_plain_text(title, field="title")
    if len(title_s) > MAX_TITLE_CHARS:
        raise ValueError(f"title exceeds {MAX_TITLE_CHARS} characters")
    if not isinstance(allowed_capabilities, (list, tuple, set, frozenset)):
        raise ValueError("allowed_capabilities must be a list of built-in capability names")
    caps = []
    seen: set[str] = set()
    allowed = builtin_capability_union()
    for item in allowed_capabilities:
        cap = str(item).strip()
        if not CAP_RE.match(cap):
            raise ValueError(f"capability name {cap!r} is not safe")
        if cap not in allowed:
            raise ValueError(
                f"capability {cap!r} is not in the built-in capability union"
            )
        if cap not in seen:
            caps.append(cap)
            seen.add(cap)
    if not caps:
        raise ValueError("at least one built-in capability is required")
    if len(caps) > MAX_CAPS_PER_CASTE:
        raise ValueError(f"at most {MAX_CAPS_PER_CASTE} capabilities are allowed")
    cleaned_rules = _validate_rules(rules)
    return {
        "caste_id": cid,
        "code_prefix": prefix,
        "title": title_s,
        "single_purpose": purpose,
        "allowed_capabilities": caps,
        "rules": cleaned_rules,
    }


def spec_to_record(spec: dict[str, Any], extras: Mapping[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "caste_id": spec["caste_id"],
        "code_prefix": spec["code_prefix"],
        "title": spec["title"],
        "single_purpose": spec["single_purpose"],
        "allowed_capabilities": list(spec["allowed_capabilities"]),
        "rules": list(spec.get("rules") or []),
    }
    if extras:
        for key in (
            "version",
            "orbit_radius",
            "orbit_y_band",
            "speed_mult",
            "eye_color",
            "laser_kind",
            "doctrine",
        ):
            if key in extras:
                row[key] = extras[key]
    return row

class DynamicCasteHandler(CasteHandler):
    """Dynamic caste handler bounded to the built-in capability union.

    execute() refuses a capability absent from this descriptor, runs the
    bounded field and pattern rules, then delegates to the built-in handler
    that already owns that capability. It does not evaluate caller code,
    grant new privileges, or invent tools.
    """

    def __init__(
        self,
        descriptor: CasteDescriptor,
        *,
        rules: list[dict[str, Any]] | None = None,
        delegates: Mapping[str, CasteHandler] | None = None,
    ) -> None:
        self.descriptor = descriptor
        self._rules = rules or []
        self._delegates = dict(delegates or {})

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
            violations, findings = self._evaluate_rules(op, task_payload)
            ok = len(violations) == 0
            if ok:
                delegate = self._delegate_for(op)
                delegated = await delegate.execute(
                    unit,
                    task_payload,
                    bus=bus,
                    ledger=ledger,
                    nodes=nodes,
                )
                duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                if isinstance(delegated, dict):
                    out = dict(delegated)
                    out["caste"] = cid
                    out["capability"] = op
                    out.setdefault("delegated_handler", delegate.descriptor.caste_id)
                    out.setdefault("violations", violations)
                    out.setdefault("findings", findings)
                    out["duration_ms"] = duration_ms
                    return out
        except PermissionViolationError:
            raise
        except (ValueError, TypeError, KeyError, RuntimeError, re.error, OSError) as exc:
            ok = False
            violations.append(f"Execution failed: {exc}")
            findings = {"error": str(exc)}

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        unit.missions_completed += 1
        unit.bytes_processed += len(str(task_payload))

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

    def _delegate_for(self, op: str) -> CasteHandler:
        for handler in self._delegates.values():
            if op in handler.descriptor.allowed_capabilities:
                return handler
        raise PermissionViolationError(
            f"Caste {self.descriptor.caste_id!r} has no built-in handler for {op!r}."
        )

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
