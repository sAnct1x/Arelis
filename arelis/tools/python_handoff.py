"""Route a short python cell to run_script when it needs the sandbox card.

The numerics cell cannot import urllib or change a file the user named, so
those asks never reached run_script's network or write-outside confirm path.
A first run_script in the sandbox still refuses; the same code again shows
the existing card. Relative saves (a PNG of a fit) stay on the python cell.
"""

from __future__ import annotations

import ast
import re
from typing import Any

_NETWORK_ROOTS = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "httpx",
        "imaplib",
        "nntplib",
        "poplib",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "urllib",
        "websocket",
    }
)
_NETWORK_CALLS = frozenset(
    {
        "urlopen",
        "urlretrieve",
        "urlrequest",
        "create_connection",
        "getaddrinfo",
        "create_server",
    }
)
_WRITE_CALLS = frozenset(
    {
        "open",
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "to_csv",
        "to_excel",
        "to_parquet",
        "to_pickle",
        "savefig",
        "imsave",
        "imwrite",
        "dump",
        "mkdir",
        "makedirs",
        "remove",
        "unlink",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "move",
    }
)
_ABS_PATH = re.compile(
    r"(?:"
    r"[A-Za-z]:[\\/]"
    r"|\\\\"
    r"|/"
    r")"
)
_WRITE_MODE = re.compile(r"^[wax]")


def _code_arg(args: dict[str, Any] | None) -> str:
    raw = args or {}
    return str(raw.get("code") or raw.get("source") or raw.get("script") or "")


def _is_abs_path(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 2:
        return False
    if re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    if text.startswith("\\\\"):
        return True
    return text.startswith("/")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal_strings(node: ast.AST) -> list[str]:
    out: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
        return out
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            out.extend(_literal_strings(part))
        return out
    for child in ast.iter_child_nodes(node):
        out.extend(_literal_strings(child))
    return out


def _has_write_mode(call: ast.Call) -> bool:
    args = list(call.args)
    if len(args) >= 2:
        mode = args[1]
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            return bool(_WRITE_MODE.match(mode.value))
    for kw in call.keywords:
        if kw.arg in {"mode", "file"} or kw.arg is None:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.arg == "mode" and _WRITE_MODE.match(kw.value.value):
                    return True
    return False


def python_code_needs_run_script(code: str) -> bool:
    """True when this cell needs network or a write outside the work folder."""
    source = (code or "").strip()
    if not source:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _needs_run_script_text(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".", 1)[0]
                if root in _NETWORK_ROOTS:
                    return True
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _NETWORK_ROOTS:
                return True
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _NETWORK_CALLS:
                return True
            strings = []
            for arg in node.args:
                strings.extend(_literal_strings(arg))
            for kw in node.keywords:
                strings.extend(_literal_strings(kw.value))
            abs_paths = [item for item in strings if _is_abs_path(item)]
            if not abs_paths:
                continue
            if name in _WRITE_CALLS or _has_write_mode(node):
                return True
    return False


def _needs_run_script_text(source: str) -> bool:
    if re.search(
        r"(?i)\b(?:import|from)\s+(?:urllib|requests|httpx|aiohttp|socket|http)\b",
        source,
    ):
        return True
    if _ABS_PATH.search(source) and re.search(
        r"(?i)\b(?:open|write_text|to_csv|to_excel|savefig)\s*\(",
        source,
    ):
        return True
    return False


def rewrite_python_to_run_script(
    calls: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Hand a python cell that needs network or an outside write to run_script."""
    out: list[tuple[str, dict[str, Any]]] = []
    for name, args in calls:
        if name == "python":
            code = _code_arg(args)
            if python_code_needs_run_script(code):
                rewritten = dict(args or {})
                rewritten["code"] = code
                out.append(("run_script", rewritten))
                continue
        out.append((name, args))
    return out
