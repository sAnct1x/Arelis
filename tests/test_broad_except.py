"""`except Exception` has to leave a reason behind. New ones, anyway.

Fail-soft is usually right in a desktop app — a dead camera or a missing
optional import should not take the window down. The failure mode is not the
broad handler, it is a broad handler that swallows silently, because then a
broken subsystem and a working one that found nothing are indistinguishable.
The audit found three of those, and each produced a confident wrong answer:
the host VRAM guard vanished when its import failed, a vision-capable model
was treated as blind, and a malformed lessons.yaml became an empty dict.

So a broad handler must do at least one of four things:

  1. re-raise;
  2. log at warning or above — `log.info` is below the default level and is
     how the capability probe stayed invisible for months;
  3. use the bound exception for something other than a debug/info log, which
     means it reached a return value, an event, or the UI;
  4. carry a comment saying why silence is correct here.

There are 381 handlers that do none of those, and a check that fails on 381
existing sites is a check nobody adopts. So this is a ratchet, the same shape
as the mypy strict gate: `broad_except_baseline.txt` records a per-file count,
new ones fail, and fixing one means lowering the number. Counts rather than
line numbers, because a line-keyed baseline goes stale on any edit above the
handler and trains people to regenerate it without reading it.

Two thirds of the baseline is `ui/` and `earth/`, which are frozen. This does
not ask anyone to go clean those.
"""

from __future__ import annotations

import ast
import io
import tokenize
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "arelis"
BASELINE = Path(__file__).parent / "broad_except_baseline.txt"

_BROAD = {"Exception", "BaseException"}
_LOUD = {"warning", "warn", "error", "exception", "critical"}
_QUIET = {"debug", "info"}
# A comment this far above the `except` line still counts as its reason.
_COMMENT_REACH = 3


def _is_broad(handler: ast.ExceptHandler) -> bool:
    node = handler.type
    if node is None:  # bare `except:`
        return True
    if isinstance(node, ast.Name):
        return node.id in _BROAD
    if isinstance(node, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in _BROAD for e in node.elts)
    return False


def _walk_body(handler: ast.ExceptHandler):
    return ast.walk(ast.Module(body=handler.body, type_ignores=[]))


def _call_name(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _logs_loudly(handler: ast.ExceptHandler) -> bool:
    return any(_call_name(n) in _LOUD for n in _walk_body(handler))


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for n in _walk_body(handler))


def _surfaces_the_exception(handler: ast.ExceptHandler) -> bool:
    """The bound exception reaches something that is not a quiet log.

    `except Exception as exc: return f"failed: {exc}"` is not silence — the
    caller is told. `except Exception as exc: log.debug(exc)` is, because the
    default level hides it.
    """
    if not handler.name:
        return False
    quiet_only = True
    found = False
    for node in _walk_body(handler):
        if not isinstance(node, ast.Call):
            continue
        reads = any(
            isinstance(inner, ast.Name) and inner.id == handler.name
            for inner in ast.walk(node)
        )
        if not reads:
            continue
        found = True
        if _call_name(node) not in _QUIET:
            quiet_only = False
    if found:
        return not quiet_only
    # Bound and read outside any call at all — an f-string in a return, say.
    return any(
        isinstance(n, ast.Name) and n.id == handler.name for n in _walk_body(handler)
    )


def _comment_lines(src: str) -> set[int]:
    out: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _has_comment(handler: ast.ExceptHandler, comments: set[int]) -> bool:
    last = handler.lineno
    for node in handler.body:
        last = max(last, getattr(node, "end_lineno", None) or node.lineno)
    return any(
        ln in comments for ln in range(handler.lineno - _COMMENT_REACH, last + 1)
    )


def unexplained_in_source(src: str) -> list[int]:
    """Line numbers of broad handlers that give no reason for swallowing."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    comments = _comment_lines(src)
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _is_broad(node):
            continue
        if _reraises(node) or _logs_loudly(node):
            continue
        if _surfaces_the_exception(node) or _has_comment(node, comments):
            continue
        out.append(node.lineno)
    return out


@cache
def scan() -> dict[str, int]:
    """Parsing 500 files twice for two assertions is most of this file's runtime."""
    counts: dict[str, int] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        found = unexplained_in_source(src)
        if found:
            counts[path.relative_to(ROOT).as_posix()] = len(found)
    return counts


def read_baseline() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        count, _, rel = line.partition(" ")
        out[rel.strip()] = int(count)
    return out


def test_no_new_silent_broad_excepts() -> None:
    """A file may not grow a handler that swallows without saying why."""
    found = scan()
    baseline = read_baseline()
    worse = {
        rel: (n, baseline.get(rel, 0))
        for rel, n in found.items()
        if n > baseline.get(rel, 0)
    }
    assert not worse, (
        "new broad `except` with no diagnostic, no surfaced exception and no "
        "comment saying why silence is correct:\n"
        + "\n".join(
            f"  {rel}: {now} now, {was} allowed" for rel, (now, was) in sorted(worse.items())
        )
        + "\n\nGive it a reason — log at warning, return the error, or write a "
        "comment. Only add to broad_except_baseline.txt if it is genuinely a "
        "pre-existing site you are moving, not writing."
    )


def test_the_baseline_ratchets_down_and_never_goes_stale() -> None:
    """Fixing one means lowering the number, or the budget quietly regrows.

    This also turns out to be the canary for the detector. A scanner that
    breaks blind — one wrong AST assumption and every handler reads as
    explained — makes the test above pass with nothing to report. Here it
    fails loudly, because the tree now appears to contain less than the
    baseline says it does.
    """
    found = scan()
    baseline = read_baseline()
    stale = {
        rel: (found.get(rel, 0), was)
        for rel, was in baseline.items()
        if found.get(rel, 0) < was
    }
    assert not stale, (
        "broad_except_baseline.txt allows more than the tree contains, so the "
        "budget would silently refill. Lower these (or delete the line):\n"
        + "\n".join(
            f"  {rel}: {now} now, {was} allowed" for rel, (now, was) in sorted(stale.items())
        )
    )


def test_the_detector_actually_detects() -> None:
    """Proof the check can fail.

    Everything above is green by construction on a clean tree, so a broken
    detector — one bad AST assumption, one typo in the name set — reads
    exactly like a well-behaved codebase. These are the four shapes the rule
    is about, and the four ways out of it.
    """
    caught = "try:\n    f()\nexcept Exception:\n    pass\n"
    assert unexplained_in_source(caught) == [3]

    bare = "try:\n    f()\nexcept:\n    return None\n"
    assert unexplained_in_source(bare) == [3]

    tupled = "try:\n    f()\nexcept (ValueError, Exception):\n    pass\n"
    assert unexplained_in_source(tupled) == [3]

    narrow = "try:\n    f()\nexcept ValueError:\n    pass\n"
    assert unexplained_in_source(narrow) == []

    loud = "try:\n    f()\nexcept Exception:\n    log.warning('no')\n"
    assert unexplained_in_source(loud) == []

    quiet = "try:\n    f()\nexcept Exception as exc:\n    log.info(exc)\n"
    assert unexplained_in_source(quiet) == [3], (
        "log.info is below the default level — that is how the capability "
        "probe stayed invisible, and it must not satisfy the rule"
    )

    surfaced = "try:\n    f()\nexcept Exception as exc:\n    return f'no: {exc}'\n"
    assert unexplained_in_source(surfaced) == []

    explained = "try:\n    f()\n# optional, absence is normal\nexcept Exception:\n    pass\n"
    assert unexplained_in_source(explained) == []

    reraised = "try:\n    f()\nexcept Exception:\n    raise\n"
    assert unexplained_in_source(reraised) == []
