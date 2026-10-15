"""Behavior of the room data cell. Prompts are the asks; the calls are what the model would send."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from arelis.tools.data_cell import (
    DataCellTool,
)
from arelis.workspace import RootEntry, WorkspaceRoots

_REFUSE_READ = "I can only read files in this room."
_REFUSE_WRITE = "I can only save results in this room's results folder."
_TOO_BIG = "That file is too big for me to read here."
_TOO_LONG = "That took too long, so I stopped it."
_TOO_MUCH_MEMORY = "That used too much memory, so I stopped it."


def _tool(tmp_path: Path, *, root: str = "lab"):
    room = tmp_path / "room"
    room.mkdir()
    workspace = WorkspaceRoots([RootEntry(name=root, path=room.resolve())])
    rooms = SimpleNamespace(active=SimpleNamespace(root=root))
    return DataCellTool(workspace, rooms), room


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _make_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert made.returncode == 0, made.stderr
        return
    link.symlink_to(target, target_is_directory=True)


def _wait_until_dead(child_pid: int, grand_pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (_alive(child_pid) or _alive(grand_pid)):
        time.sleep(0.1)


def _outside_file(tmp_path: Path, name: str, text: str = "secret") -> Path:
    path = tmp_path / "outside" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


async def test_reading_a_file_outside_the_room_is_refused(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    secret = _outside_file(tmp_path, "secret.txt", "do-not-read")
    (room / "data.csv").write_text("B\n1\n", encoding="utf-8")
    parent = secret.parent
    result = await tool.run(
        code='print(open("../outside/secret.txt", encoding="utf-8").read())',
        files=["../outside/secret.txt"],
    )
    assert not result.ok
    assert result.output == _REFUSE_READ
    assert secret.read_text(encoding="utf-8") == "do-not-read"
    assert not (room / "results").exists() or not any((room / "results").iterdir())
    leaked = [p for p in parent.iterdir() if p.name != "secret.txt" and p.name != "room"]
    assert leaked == []


async def test_writing_outside_results_is_refused(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "data.csv").write_text("B\n1\n2\n", encoding="utf-8")
    outside = tmp_path / "outside" / "leak.csv"
    outside.parent.mkdir(parents=True, exist_ok=True)
    via_name = await tool.run(
        code=("df = read_table('data.csv')\nsave_csv(df, '../leak.csv')\n"),
        files=["data.csv", "../leak.csv"],
    )
    assert not via_name.ok
    assert via_name.output in {_REFUSE_READ, _REFUSE_WRITE}
    assert not outside.exists()
    in_room = room / "leak.csv"
    via_open = await tool.run(
        code=(
            "df = read_table('data.csv')\n"
            f'open(r"{in_room}", "w", encoding="utf-8").write("nope")\n'
            f'open(r"{outside}", "w", encoding="utf-8").write("nope")\n'
        ),
        files=["data.csv"],
    )
    assert not via_open.ok
    assert via_open.output == _REFUSE_WRITE
    assert not in_room.exists()
    assert not outside.exists()


async def test_a_link_pointing_out_of_the_room_is_refused(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    secret = _outside_file(tmp_path, "secret.txt", "do-not-read")
    link = room / "linked"
    _make_link(link, secret.parent)
    try:
        result = await tool.run(
            code='print(open("linked/secret.txt", encoding="utf-8").read())',
            files=[],
        )
        assert not result.ok
        assert result.output == _REFUSE_READ
        assert "do-not-read" not in result.output
        assert secret.read_text(encoding="utf-8") == "do-not-read"
        leaked = [path for path in secret.parent.iterdir() if path.name not in {"secret.txt"}]
        assert leaked == []
    finally:
        if link.exists():
            if sys.platform == "win32":
                os.rmdir(link)
            else:
                link.unlink()


