"""Windows job limit blocks a cell from starting another process.

The runner is bare: it reads JSON from stdin and execs the code. No audit
hook and no module stubs. A marker file means a grandchild ran.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from arelis.tools import child_proc
from arelis.tools.child_proc import _close_job, _spawn, child_env

_RUNNER_SOURCE = """\
import json
import sys

raw = sys.stdin.read()
payload = json.loads(raw) if raw.strip() else {}
code = payload.get("code")
if not isinstance(code, str):
    raise SystemExit("missing code")
exec(compile(code, "<cell>", "exec"), {"__name__": "__main__"})
"""


def _write_runner(directory: Path) -> Path:
    path = directory / "bare_runner.py"
    path.write_text(_RUNNER_SOURCE, encoding="utf-8")
    return path


def _write_helper(path: Path, marker: Path) -> None:
    path.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )


def _private_python(tmp_path: Path) -> tuple[Path, Callable[[], None]]:
    source_dir = Path(sys.executable).parent
    dest = tmp_path / "allowed-exe"
    dest.mkdir()
    exe = dest / "fc-list.exe"
    shutil.copy2(sys.executable, exe)
    for pattern in ("python*.dll", "vcruntime*.dll"):
        for dll in source_dir.glob(pattern):
            shutil.copy2(dll, dest / dll.name)
    lines: list[str] = []
    for name in ("Lib", "DLLs"):
        target = source_dir / name
        if not target.is_dir():
            continue
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest / name), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if made.returncode != 0:
            raise OSError(made.stderr.strip() or f"mklink failed for {name}")
        lines.append(name)
    zip_name = f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    zip_path = source_dir / zip_name
    if zip_path.is_file():
        shutil.copy2(zip_path, dest / zip_name)
        lines.append(zip_name)
    lines.extend([".", "import site"])
    tag = f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    (dest / tag).write_text("\n".join(lines) + "\n", encoding="ascii")

    def cleanup() -> None:
        shutil.rmtree(dest, ignore_errors=True)

    return exe, cleanup


def _place_copied_exe(tmp_path: Path) -> tuple[Path, Callable[[], None]]:
    source = Path(sys.executable)
    beside = source.with_name("fc-list.exe")
    if not beside.exists():
        try:
            shutil.copy2(source, beside)
        except OSError:
            return _private_python(tmp_path)
        return beside, lambda: beside.unlink(missing_ok=True)
    return _private_python(tmp_path)


def _popen_code(helper: Path) -> str:
    return (
        "import subprocess, sys\n"
        "flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)\n"
        f"subprocess.Popen([sys.executable, {str(helper)!r}], creationflags=flags).wait()\n"
    )


def _system_code(helper: Path) -> str:
    return (
        "import os, sys\n"
        f"script = {str(helper)!r}\n"
        "os.system('\"' + sys.executable + '\" \"' + script + '\"')\n"
    )


def _spawnv_code(helper: Path) -> str:
    return (
        "import os, sys\n"
        f"script = {str(helper)!r}\n"
        "os.spawnv(os.P_WAIT, sys.executable, [sys.executable, script])\n"
    )


def _startfile_code(bat: Path, marker: Path) -> str:
    return (
        "import os, time\n"
        "from pathlib import Path\n"
        f"os.startfile({str(bat)!r})\n"
        f"marker = Path({str(marker)!r})\n"
        "for _ in range(40):\n"
        "    if marker.is_file():\n"
        "        break\n"
        "    time.sleep(0.1)\n"
    )


def _winapi_code(helper: Path) -> str:
    return (
        "import subprocess, sys\n"
        "winapi = vars(__import__('os'))['sys'].modules['_winapi']\n"
        f"cmd = subprocess.list2cmdline([sys.executable, {str(helper)!r}])\n"
        "info = subprocess.STARTUPINFO()\n"
        "handles = winapi.CreateProcess(\n"
        "    sys.executable, cmd, None, None, 0, 0x08000000, None, None, info\n"
        ")\n"
        "winapi.WaitForSingleObject(handles[0], 20000)\n"
        "winapi.CloseHandle(handles[0])\n"
        "winapi.CloseHandle(handles[1])\n"
    )


def _exec_code(exe: Path, helper: Path) -> str:
    return (
        "import os\n"
        f"os.execv({str(exe)!r}, [{str(exe)!r}, {str(helper)!r}])\n"
    )


def _run_cell(code: str, work: Path, runner: Path) -> tuple[int | None, str, str, bool]:
    proc, job = _spawn(sys.executable, work, child_env(), runner=runner)
    if proc is None:
        return None, "", "spawn returned no process", False
    out = ""
    err = ""
    hung = False
    try:
        try:
            out, err = proc.communicate(json.dumps({"code": code}), timeout=20)
        except subprocess.TimeoutExpired as exc:
            hung = True
            proc.kill()
            drained_out, drained_err = proc.communicate(timeout=5)
            out = f"{exc.stdout or ''}{drained_out or ''}"
            err = f"{exc.stderr or ''}{drained_err or ''}"
    finally:
        _close_job(job)
    return proc.returncode, out or "", err or "", hung


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:400]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job active process limit")
def test_job_blocks_child_launch_without_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _write_runner(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    markers = tmp_path / "markers"
    markers.mkdir()
    copied, cleanup_copy = _place_copied_exe(tmp_path)
    failures: list[str] = []
    try:
        cases = _cases(work, markers, copied)
        for name, code, marker in cases:
            code_rc, out, err, hung = _run_cell(code, work, runner)
            if marker.is_file():
                failures.append(
                    f"{name}: marker appeared\n{_snippet(out)}\n{_snippet(err)}"
                )
            if hung or code_rc is None:
                failures.append(f"{name}: cell did not exit ({_snippet(err)})")
        monkeypatch.setattr(child_proc, "_ACTIVE_PROCESS_LIMIT", None)
        control = markers / "pwn_control"
        helper = work / "mark_control.py"
        _write_helper(helper, control)
        code_rc, out, err, _hung = _run_cell(_popen_code(helper), work, runner)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not control.is_file():
            time.sleep(0.05)
        if not control.is_file():
            failures.append(
                f"control: marker missing (rc={code_rc})\n{_snippet(out)}\n{_snippet(err)}"
            )
    finally:
        cleanup_copy()
    assert not failures, "\n".join(failures)


def _cases(
    work: Path, markers: Path, copied: Path
) -> list[tuple[str, str, Path]]:
    popen_marker = markers / "pwn_popen"
    system_marker = markers / "pwn_system"
    spawnv_marker = markers / "pwn_spawnv"
    startfile_marker = markers / "pwn_startfile"
    winapi_marker = markers / "pwn_winapi"
    copied_marker = markers / "pwn_copied_exe"
    popen_helper = work / "mark_popen.py"
    system_helper = work / "mark_system.py"
    spawnv_helper = work / "mark_spawnv.py"
    winapi_helper = work / "mark_winapi.py"
    copied_helper = work / "mark_copied_exe.py"
    _write_helper(popen_helper, popen_marker)
    _write_helper(system_helper, system_marker)
    _write_helper(spawnv_helper, spawnv_marker)
    _write_helper(winapi_helper, winapi_marker)
    _write_helper(copied_helper, copied_marker)
    bat = work / "mark_startfile.bat"
    bat.write_text(f'@echo x> "{startfile_marker}"\r\n', encoding="utf-8")
    return [
        ("popen", _popen_code(popen_helper), popen_marker),
        ("system", _system_code(system_helper), system_marker),
        ("spawnv", _spawnv_code(spawnv_helper), spawnv_marker),
        ("startfile", _startfile_code(bat, startfile_marker), startfile_marker),
        ("winapi", _winapi_code(winapi_helper), winapi_marker),
        ("copied_exe", _exec_code(copied, copied_helper), copied_marker),
    ]
