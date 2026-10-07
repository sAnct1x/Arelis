"""Fail if arelis/ or scripts/ calls os.kill with signal 0 or CTRL_C_EVENT.

On Windows that call is not a no-op liveness check. Signal 0 is not
supported there and the target can die. CTRL_C_EVENT is the same trap.
The lock path already has a Windows-safe query; this scan exists so
nobody puts the probe back.

The check is an AST walk, not a line regex, so a split call, a bare
kill imported from os, a name bound to 0, a hex zero, and a keyword
argument are all the same hit. Comments and strings are not calls.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_OS_MOD = "os-module"
_SIG_MOD = "signal-module"
_KILL_FN = "kill-fn"
_ZERO = "zero"
_CTRL = "ctrl-c"
_UNKNOWN = "unknown"


def default_roots() -> list[Path]:
    base = Path(__file__).resolve().parent.parent
    return [base / "arelis", base / "scripts"]


def _eval_signal(node: ast.AST, env: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and type(node.value) is int and node.value == 0:
        return _ZERO
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        if _eval_signal(node.operand, env) == _ZERO:
            return _ZERO
        return _UNKNOWN
    if isinstance(node, ast.Name):
        return env.get(node.id, _UNKNOWN)
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "CTRL_C_EVENT"
        and isinstance(node.value, ast.Name)
        and env.get(node.value.id) == _SIG_MOD
    ):
        return _CTRL
    return _UNKNOWN


def _bind_target(target: ast.AST, value: str, env: dict[str, str]) -> None:
    if isinstance(target, ast.Name):
        env[target.id] = value
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            if isinstance(elt, ast.Name):
                env[elt.id] = _UNKNOWN


def _capture_walrus(node: ast.AST, env: dict[str, str]) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
            env[child.target.id] = _eval_signal(child.value, env)


def _apply_import(stmt: ast.Import | ast.ImportFrom, env: dict[str, str]) -> None:
    if isinstance(stmt, ast.Import):
        for alias in stmt.names:
            top = alias.name.split(".", 1)[0]
            bound = alias.asname or top
            if top == "os":
                env[bound] = _OS_MOD
            elif top == "signal":
                env[bound] = _SIG_MOD
            else:
                env[bound] = _UNKNOWN
        return
    module = stmt.module or ""
    for alias in stmt.names:
        if alias.name == "*":
            continue
        bound = alias.asname or alias.name
        if module == "os" and alias.name == "kill":
            env[bound] = _KILL_FN
        elif module == "signal" and alias.name == "CTRL_C_EVENT":
            env[bound] = _CTRL
        else:
            env[bound] = _UNKNOWN


def _apply_binding(stmt: ast.AST, env: dict[str, str]) -> None:
    if isinstance(stmt, ast.Assign):
        value = _eval_signal(stmt.value, env)
        for target in stmt.targets:
            _bind_target(target, value, env)
    elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
        _bind_target(stmt.target, _eval_signal(stmt.value, env), env)
    elif isinstance(stmt, ast.AugAssign):
        _bind_target(stmt.target, _UNKNOWN, env)
    elif isinstance(stmt, ast.Delete):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                env.pop(target.id, None)


def _is_bad_kill(node: ast.Call, env: dict[str, str]) -> bool:
    func = node.func
    is_kill = False
    if isinstance(func, ast.Name) and env.get(func.id) == _KILL_FN:
        is_kill = True
    elif (
        isinstance(func, ast.Attribute)
        and func.attr == "kill"
        and isinstance(func.value, ast.Name)
        and env.get(func.value.id) == _OS_MOD
    ):
        is_kill = True
    if not is_kill:
        return False
    sig: ast.AST | None = None
    for keyword in node.keywords:
        if keyword.arg == "sig":
            sig = keyword.value
            break
    if sig is None and len(node.args) >= 2:
        sig = node.args[1]
    if sig is None:
        return False
    kind = _eval_signal(sig, env)
    return kind in {_ZERO, _CTRL}


class _Scanner:
    def __init__(self, path: Path, lines: list[str]) -> None:
        self.path = path
        self.lines = lines
        self.hits: list[tuple[Path, int, str]] = []
        self._seen: set[int] = set()

    def add(self, lineno: int) -> None:
        if lineno in self._seen:
            return
        self._seen.add(lineno)
        line = self.lines[lineno - 1].strip() if 1 <= lineno <= len(self.lines) else ""
        self.hits.append((self.path, lineno, line))

    def record(self, node: ast.AST, env: dict[str, str]) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and _is_bad_kill(child, env):
                self.add(child.lineno)

    def body(self, statements: list[ast.stmt], env: dict[str, str]) -> None:
        for stmt in statements:
            self.statement(stmt, env)

    def statement(self, stmt: ast.stmt, env: dict[str, str]) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in stmt.decorator_list:
                self.record(deco, env)
            for default in (*stmt.args.defaults, *stmt.args.kw_defaults):
                if default is not None:
                    self.record(default, env)
            inner = dict(env)
            inner[stmt.name] = _UNKNOWN
            slots = (*stmt.args.posonlyargs, *stmt.args.args, *stmt.args.kwonlyargs)
            for arg in slots:
                inner[arg.arg] = _UNKNOWN
            if stmt.args.vararg is not None:
                inner[stmt.args.vararg.arg] = _UNKNOWN
            if stmt.args.kwarg is not None:
                inner[stmt.args.kwarg.arg] = _UNKNOWN
            self.body(stmt.body, inner)
            env[stmt.name] = _UNKNOWN
            return
        if isinstance(stmt, ast.ClassDef):
            for deco in stmt.decorator_list:
                self.record(deco, env)
            inner = dict(env)
            inner[stmt.name] = _UNKNOWN
            self.body(stmt.body, inner)
            env[stmt.name] = _UNKNOWN
            return
        if isinstance(stmt, ast.If):
            self.record(stmt.test, env)
            branch = dict(env)
            _capture_walrus(stmt.test, branch)
            self.body(stmt.body, dict(branch))
            self.body(stmt.orelse, dict(env))
            _capture_walrus(stmt.test, env)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self.record(stmt.iter, env)
            inner = dict(env)
            _bind_target(stmt.target, _UNKNOWN, inner)
            self.body(stmt.body, inner)
            self.body(stmt.orelse, dict(env))
            return
        if isinstance(stmt, ast.While):
            self.record(stmt.test, env)
            self.body(stmt.body, dict(env))
            self.body(stmt.orelse, dict(env))
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            inner = dict(env)
            for item in stmt.items:
                self.record(item.context_expr, env)
                if item.optional_vars is not None:
                    _bind_target(item.optional_vars, _UNKNOWN, inner)
            self.body(stmt.body, inner)
            return
        if isinstance(stmt, ast.Try):
            self.body(stmt.body, dict(env))
            for handler in stmt.handlers:
                inner = dict(env)
                if handler.name:
                    inner[handler.name] = _UNKNOWN
                self.body(handler.body, inner)
            self.body(stmt.orelse, dict(env))
            self.body(stmt.finalbody, dict(env))
            return
        if isinstance(stmt, ast.Match):
            self.record(stmt.subject, env)
            for case in stmt.cases:
                inner = dict(env)
                for node in ast.walk(case.pattern):
                    if isinstance(node, ast.MatchAs) and node.name:
                        inner[node.name] = _UNKNOWN
                self.body(case.body, inner)
            return
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            _apply_import(stmt, env)
            return
        self.record(stmt, env)
        _apply_binding(stmt, env)


def iter_hits(root: Path) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        return hits
    for path in sorted(root.rglob("*.py")):
        if any(part == "__pycache__" for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            hits.append((path, 0, f"<unreadable: {exc}>"))
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            hits.append((path, exc.lineno or 0, f"<syntax: {exc.msg}>"))
            continue
        scanner = _Scanner(path, lines)
        scanner.body(tree.body, {"os": _OS_MOD})
        hits.extend(scanner.hits)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="Directories to scan (default: arelis/ and scripts/ next to this file)",
    )
    args = parser.parse_args(argv)
    roots = list(args.roots) if args.roots else default_roots()
    hits: list[tuple[Path, int, str]] = []
    for root in roots:
        hits.extend(iter_hits(root))
    if not hits:
        return 0
    for path, lineno, line in hits:
        print(f"{path}:{lineno}: {line}", file=sys.stderr)
    where = ", ".join(str(root) for root in roots)
    print(
        f"os.kill(..., 0) or CTRL_C_EVENT is a Windows footgun; {len(hits)} hit(s) in {where}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
