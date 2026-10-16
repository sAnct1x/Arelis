"""Bytes an Allow card showed, and script contents the user has approved.

The card hashes the bytes it shows. The process runs those bytes, so a
later edit on disk cannot swap in a program the card did not show.

With the programs toggle off, the card is skipped only when the file's
SHA-256 is already in approved_scripts.json, beside the profile. That
file is the record, so a restart does not forget an approval and a
rename does not invent one. Saving an approval never rewrites the profile.
A missing or unreadable record means the card shows.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
import os
import tokenize
from pathlib import Path

from arelis.profile import approvals_path

log = logging.getLogger(__name__)

_PINNED: dict[str, bytes] = {}
_HASH_LEN = 12
_HEX = frozenset("0123456789abcdef")


def script_key(path: Path) -> str:
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return os.path.normcase(resolved)


def pin_script_bytes(path: Path, source: bytes) -> str:
    """Store the bytes the card is showing. Return a short hash of them."""
    _PINNED[script_key(path)] = bytes(source)
    return short_source_hash(source)


def clear_script_pin(path: Path) -> None:
    _PINNED.pop(script_key(path), None)


def take_script_pin(path: Path) -> bytes | None:
    """Return the bytes the card pinned, once. None when no card pinned them."""
    return _PINNED.pop(script_key(path), None)


def script_sha256(source: bytes) -> str:
    """Full SHA-256 of the exact bytes that ran or will run."""
    return hashlib.sha256(bytes(source)).hexdigest()


def short_source_hash(source: bytes) -> str:
    return script_sha256(source)[:_HASH_LEN]


def _is_hash(item: object) -> bool:
    return isinstance(item, str) and len(item) == 64 and set(item) <= _HEX


def _read_hashes(path: Path) -> list[str] | None:
    """Hashes from the approvals file.

    ``[]`` when the file is missing. ``None`` when it cannot be read or is
    not a list, so the caller shows the card and does not crash.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("Could not read approved scripts: %s", exc)
        return None
    try:
        raw = json.loads(text)
    except ValueError as exc:
        log.warning("Could not read approved scripts: %s", exc)
        return None
    if not isinstance(raw, list):
        log.warning("Approved scripts file is not a list")
        return None
    return [item for item in raw if _is_hash(item)]


def approved_script_hashes() -> set[str]:
    """SHA-256 hex strings the user already allowed.

    Any read problem (missing, malformed, bad encoding, unreadable) is an
    empty set. The card shows. This does not raise.
    """
    found = _read_hashes(approvals_path())
    if not found:
        return set()
    return set(found)


def remember_approved_script(source: bytes) -> None:
    """Record that the user allowed these exact bytes. Survives a restart.

    Writes approved_scripts.json only. A failure is logged and ignored so
    the approved bytes still run this once.
    """
    digest = script_sha256(source)
    path = approvals_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _read_hashes(path)
        hashes = [] if current is None else list(current)
        if digest in hashes and current is not None:
            return
        if digest not in hashes:
            hashes.append(digest)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, ValueError) as exc:
        log.warning("Could not save an approved script hash: %s", exc)


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
