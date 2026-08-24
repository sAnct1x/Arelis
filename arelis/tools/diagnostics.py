"""Arelis's own test suite — the same pytest CI runs, not a guess.

The model must not invent pass/fail counts. This tool runs ``python -m pytest``
on tests/ with a fixed argv. It is not a shell. Counts come from pytest's last
summary line, not from the word "passed" showing up in a traceback.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT
from arelis.tools.base import ToolResult

_TIMEOUT_S = 600.0
_MAX_OUTPUT = 12_000
_MAX_FAIL_LINES = 40

# Same quiet run CI uses, plus line traces and no ANSI so the model can read it.
PYTEST_FLAGS = ("-q", "--tb=line", "--color=no")

_SUMMARY_LINE_RE = re.compile(r"^=+\s*(.+?)\s*=+\s*$")
_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|xfailed|xpassed|error|errors|"
    r"warning|warnings)"
)
_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.M)
_NO_TESTS_RE = re.compile(r"no tests (?:ran|collected)", re.I)
_INTERRUPT_RE = re.compile(r"KeyboardInterrupt|interrupted", re.I)

_EXIT_MEANING = {
    0: "ok",
    1: "failed",
    2: "interrupted",
    3: "internal error",
    4: "usage error",
    5: "no tests collected",
}


class DiagnosticsTool:
    name = "diagnostics"
    description = (
        "Run Arelis's own pytest suite (the full tests/ tree CI runs) and "
        "return a factual summary: passed/failed/skipped, failed names, short "
        "traces. Call this only when the user asks to run diagnostics. Do not "
        "invent results. After it returns, report the counts, name the "
        "failures, and say what they likely mean. A failing suite is a real "
        "issue — do not claim everything is fine."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "suite": {
                "type": "string",
                "enum": ["all"],
                "description": "Always all: the full tests/ tree.",
            },
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return await asyncio.to_thread(_run_suite)


def _run_suite() -> ToolResult:
    if os.environ.get("ARELIS_IN_DIAGNOSTICS") == "1":
        return ToolResult(
            ok=False,
            output="Already inside a diagnostics run. Refusing to nest pytest.",
        )
    root = Path(PROJECT_ROOT)
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return ToolResult(
            ok=False,
            output=(
                f"No tests/ directory at {root}. "
                "This checkout cannot run diagnostics."
            ),
        )
    cmd = [sys.executable, "-m", "pytest", str(tests_dir), *PYTEST_FLAGS]
    env = os.environ.copy()
    env["ARELIS_IN_DIAGNOSTICS"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            ok=False,
            output=(
                f"pytest timed out after {int(_TIMEOUT_S)}s. "
                "I will not invent the rest of the results."
            ),
        )
    except FileNotFoundError:
        return ToolResult(
            ok=False,
            output=f"Could not start {sys.executable}. Python is missing from PATH.",
        )
    except OSError as exc:
        return ToolResult(ok=False, output=f"Could not run pytest: {exc}")
    duration = time.monotonic() - started
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if "No module named pytest" in stderr or "No module named pytest" in stdout:
        return ToolResult(
            ok=False,
            output="pytest is not installed in this Python. pip install pytest.",
        )
    parsed = parse_pytest(stdout, stderr, completed.returncode, duration)
    text = format_report(parsed, root=root)
    if len(text) > _MAX_OUTPUT:
        text = text[:_MAX_OUTPUT] + "\n…(truncated)"
    return ToolResult(
        ok=True,
        output=text,
        data=parsed,
    )


def parse_pytest(
    stdout: str,
    stderr: str,
    returncode: int,
    duration_s: float,
) -> dict[str, Any]:
    """Counts come from pytest's last ===== summary ===== line.

    Tracebacks and plugin logs say "passed" all the time. Reading those as
    totals is how a red run gets reported as green.
    """
    blob = f"{stdout}\n{stderr}"
    counts, summary_body = _counts_from_last_summary(blob)
    failed_names = [name for name in _FAILED_RE.findall(blob)]
    duration_match = re.search(r"\bin\s+([\d.]+)s\b", summary_body or blob)
    if duration_match:
        try:
            duration_s = float(duration_match.group(1))
        except ValueError:
            pass
    fail_lines = [
        line
        for line in blob.splitlines()
        if line.startswith("E ")
        or line.startswith("FAILED ")
        or line.startswith("ERROR ")
    ][:_MAX_FAIL_LINES]
    no_tests = bool(_NO_TESTS_RE.search(summary_body or blob)) or returncode == 5
    interrupted = returncode == 2 or bool(_INTERRUPT_RE.search(blob) and returncode != 0)
    green = (
        returncode == 0
        and counts["failed"] == 0
        and counts["errors"] == 0
        and not no_tests
        and not interrupted
    )
    return {
        "summary": _summary_line(counts, duration_s, returncode),
        "summary_line": summary_body,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "xfailed": counts["xfailed"],
        "xpassed": counts["xpassed"],
        "errors": counts["errors"],
        "warnings": counts["warnings"],
        "failed_names": failed_names,
        "fail_lines": fail_lines,
        "exit_code": int(returncode),
        "exit_meaning": _EXIT_MEANING.get(int(returncode), f"exit {returncode}"),
        "duration_s": round(duration_s, 2),
        "green": green,
        "no_tests": no_tests,
        "interrupted": interrupted,
    }


def _counts_from_last_summary(blob: str) -> tuple[dict[str, int], str]:
    counts = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "errors": 0,
        "warnings": 0,
    }
    last = ""
    for line in blob.splitlines():
        match = _SUMMARY_LINE_RE.match(line.strip())
        if match:
            last = match.group(1)
    if last:
        _apply_counts(counts, last)
        return counts, last
    tail = "\n".join(blob.splitlines()[-30:])
    _apply_counts(counts, tail)
    return counts, ""


def _apply_counts(counts: dict[str, int], text: str) -> None:
    for amount, label in _COUNT_RE.findall(text):
        key = {
            "error": "errors",
            "errors": "errors",
            "warning": "warnings",
            "warnings": "warnings",
        }.get(label, label)
        counts[key] = int(amount)


def format_report(parsed: dict[str, Any], *, root: Path) -> str:
    lines = [
        "Arelis diagnostics (pytest)",
        f"root: {root}",
        f"python: {sys.executable}",
        f"flags: {' '.join(PYTEST_FLAGS)}",
        f"exit: {parsed['exit_code']} ({parsed['exit_meaning']})",
        f"duration_s: {parsed['duration_s']}",
        parsed["summary"],
        "",
    ]
    names = parsed.get("failed_names") or []
    if names:
        lines.append("## Failures")
        for name in names[:_MAX_FAIL_LINES]:
            lines.append(f"- {name}")
        extra = len(names) - min(len(names), _MAX_FAIL_LINES)
        if extra > 0:
            lines.append(f"- …and {extra} more")
        lines.append("")
    fail_lines = parsed.get("fail_lines") or []
    if fail_lines:
        lines.append("## Traces")
        lines.extend(fail_lines)
        lines.append("")
    lines.append("## Issues")
    lines.extend(_issues(parsed))
    return "\n".join(lines).strip()


def _summary_line(counts: dict[str, int], duration_s: float, returncode: int) -> str:
    bits = [
        f"{counts[k]} {k}"
        for k in (
            "passed",
            "failed",
            "skipped",
            "xfailed",
            "xpassed",
            "errors",
            "warnings",
        )
        if counts[k]
    ]
    body = ", ".join(bits) if bits else "no tests collected"
    return f"{body} in {duration_s:.2f}s (exit {returncode})"


def _issues(parsed: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if parsed.get("interrupted"):
        out.append("- pytest was interrupted. Do not treat this as a full run.")
    if parsed.get("no_tests"):
        out.append("- pytest collected no tests. That is not a green suite.")
        return out
    if parsed.get("green"):
        out.append("- none from this run. The suite is green.")
        skipped = int(parsed.get("skipped") or 0)
        if skipped:
            out.append(
                f"- {skipped} skipped (usually optional deps or not this OS)."
            )
        warnings = int(parsed.get("warnings") or 0)
        if warnings:
            out.append(f"- {warnings} warning(s). Not a failure.")
        return out
    failed = int(parsed.get("failed") or 0)
    errors = int(parsed.get("errors") or 0)
    if failed:
        out.append(
            f"- {failed} test(s) failed. Treat these as real bugs unless the "
            "trace is an env/key miss."
        )
    if errors:
        out.append(
            f"- {errors} collection/error(s). The suite did not finish cleanly."
        )
    meaning = str(parsed.get("exit_meaning") or "")
    if not failed and not errors and parsed.get("exit_code"):
        out.append(
            f"- pytest {meaning} (exit {parsed['exit_code']}) without a parsed "
            "failure count. Read the traces; do not claim green."
        )
    skipped = int(parsed.get("skipped") or 0)
    if skipped:
        out.append(f"- {skipped} skipped.")
    if not out:
        out.append("- results were inconclusive. Do not invent a pass.")
    return out
