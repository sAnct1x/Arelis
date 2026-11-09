"""``run_script`` with ``code=``: new Python in a sandbox (policy A5).

The code runs freely, with no card, inside this turn's work folder
(``outputs/work/<turn>/``). That folder and a private temp folder are the
only places it may change. A write, delete or move anywhere else is refused
and reported, with nothing changed there. The same call made again shows the
user a card listing those paths. If they allow it, the run may change exactly
those paths and nothing else.

What is enforced and what is best effort is in docs/code-sandbox.md. Short
version: on Windows the job object (one process, 2 GB, CPU and wall-time
kill) is kernel-enforced. The file and network guards are a Python audit
hook in the child, so C extensions and ctypes can get around them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arelis.core.cell_work import cell_work_dir
from arelis.tools.child_proc import _close_job, _spawn, child_env
from arelis.tools.python_exec import _changed_png_charts, _figure_data, _png_stamps
from arelis.tools.safety import redact_secrets

SANDBOX_TIMEOUT_S = 60.0
# The Windows job's CPU cap is 130 s (child_proc._CPU_SECONDS). The wall
# cap stays under it, so the clock is what stops a busy script.
SANDBOX_MAX_TIMEOUT_S = 120.0
SANDBOX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
_CPU_S = 130
_CLOSED_PORT = "http://127.0.0.1:9"
_HOST = Path(__file__).with_name("sandbox_host.py")
_BLOCK_PREFIX = "ARELIS_SANDBOX_BLOCKED "


@dataclass
class SandboxRun:
    exit: int
    stdout: str
    stderr: str
    stopped: str  # ok, timeout, cancelled, failed
    folder: Path
    duration_s: float
    blocked: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, str]] = field(default_factory=list)

    def outside_writes(self) -> list[dict[str, str]]:
        return [
            {"op": str(item.get("op") or "write"), "path": str(item.get("path") or "")}
            for item in self.blocked
            if item.get("kind") == "write" and item.get("path")
        ]


def is_sandbox_call(args: dict[str, Any]) -> bool:
    """``code`` and no ``path``. A path is a project script, run as the user."""
    return bool(str(args.get("code") or "").strip()) and not str(args.get("path") or "").strip()


def call_key(args: dict[str, Any]) -> str:
    """Same code and argv, same key. A card approves these bytes only."""
    raw = args.get("args")
    argv = [str(item) for item in raw] if isinstance(raw, (list, tuple)) else (
        [str(raw)] if raw not in (None, "") else []
    )
    blob = json.dumps({"code": str(args.get("code") or ""), "argv": argv})
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sandbox_env(scratch: Path) -> dict[str, str]:
    """Allowlisted environment, temp in the scratch folder, proxies to a closed port."""
    tmp = str(scratch)
    return child_env(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "MPLBACKEND": "Agg",
            "MPL_IGNORE_SYSTEM_FONTS": "1",
            "MPLCONFIGDIR": str(scratch / "mpl"),
            "TEMP": tmp,
            "TMP": tmp,
            "TMPDIR": tmp,
            "HTTP_PROXY": _CLOSED_PORT,
            "HTTPS_PROXY": _CLOSED_PORT,
            "ALL_PROXY": _CLOSED_PORT,
            "http_proxy": _CLOSED_PORT,
            "https_proxy": _CLOSED_PORT,
            "all_proxy": _CLOSED_PORT,
            "NO_PROXY": "",
            "no_proxy": "",
        }
    )


def _work_folder() -> Path:
    try:
        return cell_work_dir().resolve()
    except OSError:
        return Path(tempfile.mkdtemp(prefix="arelis-sandbox-")).resolve()


def run_sandboxed(
    code: str,
    argv: list[str],
    *,
    timeout_s: float,
    grants: list[str],
    is_cancelled: Callable[[], bool] | None = None,
) -> SandboxRun:
    # Imported here: run_script imports this module.
    from arelis.tools.run_script import _kill_tree, _wait

    folder = _work_folder()
    scratch = Path(tempfile.mkdtemp(prefix="arelis-sbx-")).resolve()
    key = call_key({"code": code, "args": argv})
    script = folder / f"snippet_{key[:8]}.py"
    started = time.monotonic()
    try:
        script.write_text(code, encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        return SandboxRun(-1, "", f"Could not save the code: {exc}", "failed", folder, 0.0)
    before = _png_stamps(folder)
    proc, job = _spawn(
        sys.executable,
        folder,
        sandbox_env(scratch),
        runner=_HOST,
        memory_bytes=SANDBOX_MEMORY_BYTES,
        extra_args=("-u",),
    )
    if proc is None or proc.stdin is None:
        shutil.rmtree(scratch, ignore_errors=True)
        return SandboxRun(-1, "", "The sandbox could not start.", "failed", folder, 0.0)
    config = {
        "script": str(script),
        "argv": argv,
        "roots": [str(folder), str(scratch)],
        "grants": list(grants),
        "cpu_s": _CPU_S,
    }
    exit_code, stdout, stderr, stopped = -1, "", "", "failed"
    try:
        try:
            proc.stdin.write(json.dumps(config))
            proc.stdin.close()
        except OSError:
            stopped = "failed"
        else:
            proc.stdin = None
            exit_code, stdout, stderr, stopped = _wait(
                proc, timeout_s=timeout_s, is_cancelled=is_cancelled
            )
    finally:
        if proc.poll() is None:
            _kill_tree(proc)
        _close_job(job)
        shutil.rmtree(scratch, ignore_errors=True)
    stderr, blocked = _take_blocked(stderr)
    return SandboxRun(
        exit=exit_code,
        stdout=stdout,
        stderr=stderr,
        stopped=stopped,
        folder=folder,
        duration_s=time.monotonic() - started,
        blocked=blocked,
        charts=_changed_png_charts(folder, before),
    )


def _take_blocked(stderr: str) -> tuple[str, list[dict[str, Any]]]:
    kept: list[str] = []
    found: list[dict[str, Any]] = []
    for line in (stderr or "").splitlines():
        if line.startswith(_BLOCK_PREFIX):
            try:
                item = json.loads(line[len(_BLOCK_PREFIX) :])
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if isinstance(item, dict):
                found.append(item)
            continue
        kept.append(line)
    return "\n".join(kept), found


def blocked_notes(run: SandboxRun) -> list[str]:
    """Lines for the model. Each says what was refused and the way forward."""
    notes: list[str] = []
    writes = run.outside_writes()
    if writes:
        notes.append("It tried to change files outside the sandbox:")
        notes.extend(f"- {item['op']} {item['path']}" for item in writes)
        notes.append(
            "Nothing was changed there. To ask the user, call run_script again "
            "with the same code and args. Arelis shows them a card first."
        )
    kinds = {str(item.get("kind")) for item in run.blocked}
    if "network" in kinds:
        notes.append("The sandbox has no network. Say so; do not invent the data.")
    if "process" in kinds:
        notes.append("The sandbox cannot start other programs.")
    return notes


def chart_data(run: SandboxRun) -> dict[str, Any]:
    return _figure_data(run.charts)


def sandbox_confirm(args: dict[str, Any], writes: list[dict[str, str]]) -> str:
    """Card body for letting sandboxed code change files outside it."""
    if writes:
        lines = [
            "Let this code change your files",
            "It ran in the sandbox and tried to change these. Only these are allowed:",
        ]
        lines.extend(f"- {item['op']} {item['path']}" for item in writes)
    else:
        lines = ["Run this code in the sandbox", "It cannot change your files."]
    lines.append("Network stays off. The time and memory caps stay on.")
    raw = args.get("args")
    if isinstance(raw, (list, tuple)) and raw:
        lines.append("Argv: " + json.dumps([str(item) for item in raw], ensure_ascii=False))
    # The whole source, like a project script's card. Approving it approves it all.
    code = redact_secrets(str(args.get("code") or ""))
    lines.extend(["", code])
    # Same delete/network/env/secret warnings the project-script card shows.
    from arelis.tools.confirm_preview import _append_loud

    _append_loud(lines, code)
    return "\n".join(lines)
