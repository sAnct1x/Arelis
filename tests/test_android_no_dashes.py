"""Companion Kotlin strings must not use typographic dashes."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "android" / "arelis-notify"
_TRIPLE = re.compile(r'"""(.*?)"""', re.DOTALL)
_DOUBLE = re.compile(r'"(?:\\.|[^"\\])*"')
_BAD = ("\u2013", "\u2014")


def _literals(text: str) -> list[str]:
    without_triples: list[str] = []
    found: list[str] = []

    def _keep_triple(match: re.Match[str]) -> str:
        found.append(match.group(1))
        return ""

    stripped = _TRIPLE.sub(_keep_triple, text)
    without_triples.append(stripped)
    for chunk in without_triples:
        for match in _DOUBLE.finditer(chunk):
            found.append(match.group(0)[1:-1])
    return found


def test_kotlin_string_literals_have_no_em_or_en_dash() -> None:
    hits: list[str] = []
    for path in sorted(_ROOT.rglob("*.kt")):
        literals = _literals(path.read_text(encoding="utf-8"))
        for literal in literals:
            if any(mark in literal for mark in _BAD):
                hits.append(f"{path.relative_to(_ROOT)}: {literal}")
    assert hits == []
