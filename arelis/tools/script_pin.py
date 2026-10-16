"""Bytes an Allow card showed, and script contents the user has approved.

The card hashes the bytes it shows. The process runs those bytes, so a
later edit on disk cannot swap in a program the card did not show.

With the programs toggle off, the card is skipped only when the file's
SHA-256 is already in the profile. The profile is the record, so a
restart does not forget an approval and a rename does not invent one.
"""

from __future__ import annotations

import ast
import hashlib
import io
import logging
import os
import tokenize
from pathlib import Path

import yaml

from arelis.profile import resolve_profile_path

log = logging.getLogger(__name__)

_PINNED: dict[str, bytes] = {}
_HASH_LEN = 12
_PROFILE_KEY = "approved_script_hashes"


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


def _profile_path() -> Path:
    return resolve_profile_path()


def _read_profile(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read profile for script approvals: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def approved_script_hashes() -> set[str]:
    """SHA-256 hex strings the user already allowed, from the profile."""
    raw = _read_profile(_profile_path())
    values = raw.get(_PROFILE_KEY)
    if not isinstance(values, list):
        return set()
    return {item for item in values if isinstance(item, str) and len(item) == 64}


def remember_approved_script(source: bytes) -> None:
    """Record that the user allowed these exact bytes. Survives a restart."""
    digest = script_sha256(source)
    path = _profile_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _read_profile(path)
        current = raw.get(_PROFILE_KEY)
        if isinstance(current, list):
            hashes = [item for item in current if isinstance(item, str)]
        else:
            hashes = []
        if digest in hashes:
            return
        hashes.append(digest)
        raw[_PROFILE_KEY] = hashes
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
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
