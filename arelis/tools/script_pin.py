"""Which project scripts the model wrote, and the bytes the Allow card showed.

The card hashes those bytes. The process runs those bytes, so a later edit
on disk cannot swap in a program the card did not show.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import tokenize
from pathlib import Path

_MODEL: set[str] = set()
_PINNED: dict[str, bytes] = {}
_HASH_LEN = 12


def script_key(path: Path) -> str:
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return os.path.normcase(resolved)


def note_model_script(path: Path) -> None:
    """Remember a .py the workspace tool just wrote, edited, or patched."""
    if path.suffix.lower() != ".py":
        return
    _MODEL.add(script_key(path))


def forget_model_script(path: Path) -> None:
    _MODEL.discard(script_key(path))


def is_model_script(path: Path) -> bool:
    return script_key(path) in _MODEL


def pin_script_bytes(path: Path, source: bytes) -> str:
    """Store the bytes the card is showing. Return a short hash of them."""
    _PINNED[script_key(path)] = bytes(source)
    return short_source_hash(source)


def clear_script_pin(path: Path) -> None:
    _PINNED.pop(script_key(path), None)


def take_script_pin(path: Path) -> bytes | None:
    """Return the bytes the card pinned, once. None when no card pinned them."""
    return _PINNED.pop(script_key(path), None)


def short_source_hash(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()[:_HASH_LEN]


def decode_script(source: bytes) -> str:
    """Text the way Python reads a .py, so the card matches the program."""
    try:
        encoding, _lines = tokenize.detect_encoding(io.BytesIO(source).readline)
    except (SyntaxError, LookupError):
        encoding = "utf-8"
    return source.decode(encoding, errors="replace")


def script_import_names(source: str) -> list[str]:
    """Module names this source imports, in the order they appear."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            found.append(name)

    class _Visit(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                add(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                add("." * node.level + node.module)
            else:
                add("." * max(node.level, 1))
            self.generic_visit(node)

    _Visit().visit(tree)
    return found
