"""Guard: user-facing / prompt string literals must not contain em dashes.

Scans non-docstring string literals under arelis/ via ast, plus shipped
persona and v0.3.0 release-note text the app shows. Comments, docstrings,
and other docs (including CONTRIBUTING.md) are out of scope.

Skip list (another open PR owns these, or the file must keep the character):
see _SKIP_FILES / _SKIP_PREFIXES below.
"""

from __future__ import annotations

import ast
import tempfile
from pathlib import Path

EM = "\u2014"
HB = "\u2015"
_DASHES = EM + HB

# Forbidden files owned by another open PR, plus modules that must keep the
# character (filter alphabet, year-range regex, QSS comments, strip sets).
_SKIP_FILES = frozenset(
    {
        "arelis/core/intent_catalog.py",
        "arelis/core/look.py",
        "arelis/core/preflight.py",
        "arelis/core/email_complete.py",
        "arelis/core/sms_complete.py",
        "arelis/core/image_refs.py",
        "arelis/core/dash_filter.py",  # filter alphabet
        "arelis/core/claims.py",  # year-range regex must match real dashes
        "arelis/core/skills.py",  # skill cards are not pasted into the prompt
        "arelis/ui/theme_qss.py",  # QSS comments inside style strings
        "arelis/ui/sms_chat.py",  # strip set includes dash chars
        "arelis/ui/event_host.py",  # wall toast strips \u2014 / \u2013 by escape
        "arelis/tools/document.py",  # punctuation strip set
        "arelis/voice/kokoro_tts.py",  # pause map key
    }
)
_SKIP_PREFIXES = (
    "arelis/earth/",  # frozen
    "arelis/eval/",  # scenario fixtures
    "arelis/spatial/",  # math / sensor ranges
)

_TEXT_FILES = (
    "arelis/persona/arelis.md",
    "docs/releases/v0.3.0.md",
)
_TEXT_ALLOW = frozenset(
    {
        "docs/whats-new.md",  # release history
        "docs/earth.md",  # frozen
    }
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    if (
        isinstance(tree, ast.Module)
        and tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        ids.add(id(tree.body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ids.add(id(node.body[0].value))
    return ids


def _scan_py(path: Path) -> list[tuple[int, str]]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    docs = _docstring_ids(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docs:
            continue
        if any(d in node.value for d in _DASHES):
            snippet = node.value.replace(EM, "<EM>").replace(HB, "<HB>")
            hits.append((node.lineno, snippet[:80]))
    return hits


def _scan_text(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [i + 1 for i, line in enumerate(lines) if any(d in line for d in _DASHES)]


def test_no_em_dash_in_arelis_string_literals() -> None:
    root = Path("arelis")
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.as_posix()
        if rel in _SKIP_FILES or rel.startswith(_SKIP_PREFIXES):
            continue
        for lineno, snippet in _scan_py(path):
            bad.append(f"{rel}:{lineno}: {snippet!r}")
    assert not bad, (
        "em dash / horizontal bar in a user-facing or prompt string. "
        "Use a comma, colon, period or hyphen.\n" + "\n".join(bad[:40])
    )


def test_no_em_dash_in_shipped_prompt_and_release_text() -> None:
    bad: list[str] = []
    for rel in _TEXT_FILES:
        path = Path(rel)
        if not path.is_file():
            continue
        for lineno in _scan_text(path):
            bad.append(f"{rel}:{lineno}")
    for path in Path("docs").rglob("*.md"):
        rel = path.as_posix()
        if rel in _TEXT_ALLOW or rel.startswith("docs/roadmap/"):
            continue
        if rel.startswith("docs/releases/") or rel in _TEXT_FILES:
            for lineno in _scan_text(path):
                bad.append(f"{rel}:{lineno}")
    assert not bad, "em dash in shipped text:\n" + "\n".join(bad)


def test_scanner_flags_a_temp_file_with_an_em_dash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.py"
        path.write_text(f'x = "hello {EM} world"\n', encoding="utf-8")
        hits = _scan_py(path)
        assert hits, "scanner must fail when a string literal holds an em dash"


def test_persona_has_no_dash_rule() -> None:
    text = Path("arelis/persona/arelis.md").read_text(encoding="utf-8")
    assert "Never use em dashes or en dashes" in text
    assert EM not in text
    assert "\u2013" not in text
