"""ASTValidatorCaste. Static Python AST scan for listed calls, attributes, and imports.

There is no opcode or bytecode pass, and the scanned source is not executed here.
"""

from __future__ import annotations

import ast
import asyncio
import time
from typing import Any

from sentinel.castes.base import CasteDescriptor, CasteHandler
from sentinel.core.bus import EventBus
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger

_DEFAULT_DANGEROUS_CALLS = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
})

_DEFAULT_DANGEROUS_ATTRIBUTES = frozenset({
    "__subclasses__",
    "__globals__",
    "__code__",
    "__bases__",
    "__mro__",
    "__class__",
    "__dict__",
})

_DEFAULT_BANNED_MODULES = frozenset({
    "subprocess",
    "pty",
    "ctypes",
    "socket",
    "multiprocessing",
    "pickle",
    "marshal",
    "shelve",
})


class _ASTSecurityVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        dangerous_calls: frozenset[str],
        dangerous_attrs: frozenset[str],
        banned_modules: frozenset[str],
    ) -> None:
        self.dangerous_calls = dangerous_calls
        self.dangerous_attrs = dangerous_attrs
        self.banned_modules = banned_modules
        self.violations: list[dict[str, Any]] = []

    def _resolve_string(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._resolve_string(node.left)
            right = self._resolve_string(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    def visit_Call(self, node: ast.Call) -> None:
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr

        if name in self.dangerous_calls:
            self.violations.append({
                "type": "dangerous_call",
                "symbol": name,
                "lineno": getattr(node, "lineno", 0),
                "col_offset": getattr(node, "col_offset", 0),
            })

        # Detect obfuscated reflection: getattr(obj, "exec" / "eval" / "__subclasses__")
        if name in {"getattr", "hasattr"} and len(node.args) >= 2:
            target_attr = self._resolve_string(node.args[1])
            if target_attr and (target_attr in self.dangerous_calls or target_attr in self.dangerous_attrs):
                self.violations.append({
                    "type": "obfuscated_reflection",
                    "symbol": f"getattr({target_attr!r})",
                    "lineno": getattr(node, "lineno", 0),
                    "col_offset": getattr(node, "col_offset", 0),
                })

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        target_key = self._resolve_string(node.slice)
        if target_key and (target_key in self.dangerous_attrs or target_key in self.dangerous_calls):
            self.violations.append({
                "type": "obfuscated_subscript",
                "symbol": f"[{target_key!r}]",
                "lineno": getattr(node, "lineno", 0),
                "col_offset": getattr(node, "col_offset", 0),
            })
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.dangerous_attrs:
            self.violations.append({
                "type": "dangerous_dunder_attr",
                "symbol": node.attr,
                "lineno": getattr(node, "lineno", 0),
                "col_offset": getattr(node, "col_offset", 0),
            })
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in self.banned_modules:
                self.violations.append({
                    "type": "banned_import",
                    "module": alias.name,
                    "lineno": getattr(node, "lineno", 0),
                    "col_offset": getattr(node, "col_offset", 0),
                })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in self.banned_modules:
                self.violations.append({
                    "type": "banned_import_from",
                    "module": node.module,
                    "lineno": getattr(node, "lineno", 0),
                    "col_offset": getattr(node, "col_offset", 0),
                })
        self.generic_visit(node)



class InterceptorCaste(CasteHandler):
    """Narrow Sentinel caste that walks a Python AST and reports listed calls, attributes, and imports."""

    descriptor = CasteDescriptor(
        caste_id="interceptor",
        code_prefix="INT",
        title="Code & Syntax Interceptor",
        single_purpose="Static Python AST analysis, sandboxed syntax validation, and code injection auditing",
        allowed_capabilities=frozenset([
            "ast:parse",
            "ast:audit_syntax",
            "ast:detect_banned_calls",
            "ast:verify_ast_clean",
        ]),
        version="1.1.0",
        orbit_radius=21.0,
        orbit_y_band=1.5,
        speed_mult=1.05,
        eye_color="#00e5ff",
        laser_kind="sanitize",
        doctrine="HUNTER-SEEKER",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.dangerous_calls = frozenset(
            cfg.get("ast_dangerous_calls") or _DEFAULT_DANGEROUS_CALLS
        )
        self.dangerous_attrs = frozenset(
            cfg.get("ast_dangerous_attrs") or _DEFAULT_DANGEROUS_ATTRIBUTES
        )
        self.banned_modules = frozenset(
            cfg.get("ast_banned_modules") or _DEFAULT_BANNED_MODULES
        )

    def validate_code(
        self,
        code_str: str,
        *,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Synchronously parse and audit Python code string using the ast visitor."""
        try:
            tree = ast.parse(code_str, filename="<sentinel-ast>")
        except SyntaxError as syn_err:
            return {
                "ok": False,
                "syntax_valid": False,
                "error": f"SyntaxError at line {syn_err.lineno}: {syn_err.msg}",
                "lineno": syn_err.lineno,
                "offset": syn_err.offset,
                "violations": [{"type": "syntax_error", "message": syn_err.msg, "lineno": syn_err.lineno}],
            }

        visitor = _ASTSecurityVisitor(
            dangerous_calls=self.dangerous_calls,
            dangerous_attrs=self.dangerous_attrs,
            banned_modules=self.banned_modules,
        )
        visitor.visit(tree)

        clean = len(visitor.violations) == 0
        return {
            "ok": clean if strict else True,
            "syntax_valid": True,
            "clean": clean,
            "violations_count": len(visitor.violations),
            "violations": visitor.violations,
            "nodes_inspected": len(list(ast.walk(tree))),
        }

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        op = str(task_payload.get("capability") or task_payload.get("action") or "ast:verify_ast_clean").strip()
        self.descriptor.assert_capability(op)

        code_to_check = str(
            task_payload.get("code")
            or task_payload.get("source")
            or task_payload.get("script")
            or ""
        )
        target_name = str(task_payload.get("filename") or task_payload.get("target") or "in-memory-code")[:64]
        strict = bool(task_payload.get("strict", True))

        # 1. State machine transitions: VECTORING -> ENGAGED_EXECUTION
        unit.transition(
            SentinelState.VECTORING,
            task=f"[AST] Vectoring -> {target_name}",
            target_position=[14.0, 1.5, 14.0],
        )
        await asyncio.sleep(0.04)

        unit.transition(
            SentinelState.ENGAGED_EXECUTION,
            task=f"[AST] Inspecting AST: {target_name}",
            laser_active=True,
            laser_kind=self.descriptor.laser_kind,
        )

        t0 = time.perf_counter()
        audit_res = await asyncio.to_thread(self.validate_code, code_to_check, strict=strict)
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        unit.missions_completed += 1
        unit.bytes_processed += len(code_to_check.encode("utf-8", errors="replace"))

        # 2. State machine transitions: RETURNING -> PATROLLING
        unit.transition(
            SentinelState.RETURNING,
            task=f"[AST] Audit concluded: {target_name}",
            laser_active=False,
        )
        await asyncio.sleep(0.02)
        unit.transition(
            SentinelState.PATROLLING,
            task="Patrolling interceptor sector",
            laser_active=False,
        )

        ok = bool(audit_res.get("ok"))
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="sanitize",
            source=f"sentinel://ast/{target_name}",
            span=f"AST Security Audit on {target_name} ({'PASS' if ok else 'VIOLATIONS DETECTED'}, {audit_res.get('violations_count', 0)} issues, {duration_ms}ms)",
            ok=ok,
            metadata={
                "target": target_name,
                "duration_ms": duration_ms,
                "audit": audit_res,
            },
        )

        return {
            "ok": ok,
            "caste": self.descriptor.caste_id,
            "unit_id": unit.unit_id,
            "capability": op,
            "target": target_name,
            "duration_ms": duration_ms,
            "audit": audit_res,
            "receipt": receipt.to_dict(),
        }


ASTValidatorCaste = InterceptorCaste

__all__ = ["ASTValidatorCaste", "InterceptorCaste"]
