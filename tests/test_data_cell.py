"""Behavior of the room data cell. Prompts are the asks; the calls are what the model would send."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.base import ToolResult
from arelis.tools.data_cell import (
    DATA_CELL_MEMORY_BYTES,
    DATA_CELL_TIMEOUT_S,
    MAX_INPUT_BYTES,
    DataCellTool,
)
from arelis.tools.policy import describe_call, evaluate_capability, evaluate_confirm
from arelis.ui.status_copy import tool_errand
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


async def test_whats_the_average_of_column_b_in_my_data_csv(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "data.csv").write_text("A,B\n1,10\n2,30\n3,20\n", encoding="utf-8")
    result = await tool.run(
        code='df = read_table("data.csv")\nprint(df["B"].mean())',
        files=["data.csv"],
    )
    assert result.ok, result.output
    assert "20" in result.output


async def test_whats_the_average_shows_even_without_print(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "data.csv").write_text("A,B\n1,10\n2,30\n3,20\n", encoding="utf-8")
    result = await tool.run(
        code='read_table("data.csv")["B"].mean()',
        files=["data.csv"],
    )
    assert result.ok, result.output
    assert "20" in result.output


async def test_show_me_my_data_prints_the_table(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "data.csv").write_text("A,B\n1,10\n2,30\n3,20\n", encoding="utf-8")
    result = await tool.run(code='read_table("data.csv")', files=["data.csv"])
    assert result.ok, result.output
    assert "B" in result.output
    assert "10" in result.output


async def test_plot_temperature_over_time_saves_an_open_figure(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "readings.csv").write_text(
        "time,temperature,B\n1,10,2\n2,30,4\n3,20,6\n",
        encoding="utf-8",
    )
    result = await tool.run(
        code=(
            "import matplotlib.pyplot as plt\n"
            "df = read_table('readings.csv')\n"
            "plt.plot(df['time'], df['temperature'])\n"
        ),
        files=["readings.csv"],
    )
    assert result.ok, result.output
    png = room / "results" / "chart.png"
    assert png.is_file()
    assert png.stat().st_size > 0
    assert result.data.get("abs_path") == str(png.resolve())


async def test_savefig_lands_in_the_results_folder(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "readings.csv").write_text(
        "time,temperature,B\n1,10,2\n2,30,4\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    leak = outside / "leak.png"
    result = await tool.run(
        code=(
            "import matplotlib.pyplot as plt\n"
            "df = read_table('readings.csv')\n"
            "plt.plot(df['time'], df['temperature'])\n"
            "plt.savefig('temp_plot.png')\n"
            f"plt.savefig(r'{leak}')\n"
        ),
        files=["readings.csv"],
    )
    assert result.ok, result.output
    saved = room / "results" / "temp_plot.png"
    leaked = room / "results" / "leak.png"
    assert saved.is_file() and saved.stat().st_size > 0
    assert leaked.is_file()
    assert not (outside / "leak.png").exists()
    assert not (room / "temp_plot.png").exists()
    assert result.data.get("abs_path")


async def test_code_that_prints_nothing_says_so(tmp_path: Path) -> None:
    tool, _room = _tool(tmp_path)
    result = await tool.run(code="x = 1\n", files=[])
    assert result.ok, result.output
    assert "printed nothing" in result.output
    assert result.output != "Done."


async def test_a_datetime_column_can_be_read(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "times.csv").write_text(
        "when,value\n2024-01-02T03:04:05Z,1\n2024-06-01T00:00:00Z,2\n",
        encoding="utf-8",
    )
    result = await tool.run(
        code=(
            "import pandas as pd\n"
            "df = pd.read_csv('times.csv', parse_dates=['when'])\n"
            "print(int(df['when'].dt.year.iloc[0]))\n"
        ),
        files=["times.csv"],
    )
    assert result.ok, result.output
    assert "2024" in result.output


async def test_plot_temperature_over_time_from_readings_csv(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "readings.csv").write_text(
        "time,temperature,B\n1,10,2\n2,30,4\n3,20,6\n",
        encoding="utf-8",
    )
    code = (
        "df = read_table('readings.csv')\n"
        "from matplotlib.figure import Figure\n"
        "fig = Figure()\n"
        "ax = fig.subplots()\n"
        "ax.plot(df['time'], df['temperature'])\n"
        "save_png(fig, 'temperature.png')\n"
        "print('chart')\n"
    )
    result = await tool.run(code=code, files=["readings.csv"])
    assert result.ok, result.output
    png = room / "results" / "temperature.png"
    assert png.is_file()
    assert png.stat().st_size > 0
    assert result.data.get("abs_path") == str(png.resolve())
    assert not list((room).glob("*.png"))

    class _Bus:
        def __init__(self) -> None:
            self.events = []

        async def publish(self, event) -> None:
            self.events.append(event)

    class _Loop:
        def __init__(self) -> None:
            self.bus = _Bus()
            self.max_rounds = 3
            self._look = None
            self._timer = None
            self.tools_used: set[str] = set()
            self._trace: list[str] = []
            self._receipts: list[dict] = []
            self.memory = SimpleNamespace(sink=None, messages=[])
            self.tool_output_chars = 8000
            self._expected_tools: set[str] = set()
            self._fail_replan_used = False

        def _tool_message(self, name: str, out: str) -> dict[str, str]:
            return {"role": "tool", "name": name, "content": out}

    loop = _Loop()
    ctx = TurnContext(text="plot temperature over time from readings.csv", role="fast")
    scratch = SimpleNamespace(
        text=ctx.text,
        agent_cfg={"tool_summary_inject": False},
        available_all=set(),
        available=set(),
        visible=set(),
        tool_names=set(),
        sources=[],
        ledger=EvidenceLedger(),
        fail_counts={},
        web_search_ok=set(),
        page_ok=set(),
        sms_sent=set(),
        agenda_created=set(),
        weather_ok_places=set(),
        weather_days_retried=set(),
        exact_need=ctx.exact_need,
        offer_tools=False,
        ollama_tools=[],
        messages=[],
        sms_draft=None,
        email_draft=None,
    )
    packed = ToolResult(ok=True, output=result.output, data=dict(result.data))
    await execute_call(
        loop,
        ctx,
        scratch,
        "data_cell",
        {"code": code, "files": ["readings.csv"]},
        summary="data",
        call_fp="data-cell-plot",
        round_i=1,
        call_i=0,
        fanout_results={0: (1, packed)},
    )
    ready = [e for e in loop.bus.events if e.type == EventType.FILE_READY]
    assert len(ready) == 1
    payload = ready[0].payload
    assert payload["kind"] == "plot"
    assert payload["source"] == "data_cell"
    assert payload["abs_path"] == str(png.resolve())
    assert payload["show_card"] is True


async def test_read_this_fits_header_and_how_big_is_the_image(tmp_path: Path) -> None:
    import numpy as np
    from astropy.io import fits

    tool, room = _tool(tmp_path)
    image = np.zeros((64, 48), dtype=np.float32)
    header = fits.Header()
    header["OBJECT"] = "M31"
    header["EXPTIME"] = 12.5
    fits.PrimaryHDU(image, header=header).writeto(room / "m31.fits")
    code = (
        "info = read_fits('m31.fits')\n"
        "print(info['header'].get('OBJECT'))\n"
        "print(info['header'].get('EXPTIME'))\n"
        "print(info['shape'])\n"
    )
    result = await tool.run(code=code, files=["m31.fits"])
    assert result.ok, result.output
    assert "M31" in result.output
    assert "12.5" in result.output
    assert "64" in result.output and "48" in result.output


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


async def test_an_absolute_path_outside_the_room_is_refused(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    secret = _outside_file(tmp_path, "secret.txt", "do-not-read")
    result = await tool.run(
        code=f'print(open(r"{secret}", encoding="utf-8").read())',
        files=[str(secret)],
    )
    assert not result.ok
    assert result.output == _REFUSE_READ
    assert secret.read_text(encoding="utf-8") == "do-not-read"
    assert not list(room.rglob("leak*"))


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


async def test_an_infinite_loop_is_stopped_and_its_children_die(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert DATA_CELL_TIMEOUT_S == 120
    monkeypatch.setattr(
        "arelis.tools.data_cell.DATA_CELL_TIMEOUT_S",
        3,
    )
    tool, room = _tool(tmp_path)
    if sys.platform == "win32":
        spawn = r"""
import ctypes
from ctypes import wintypes
import sys
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]
class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]
si = STARTUPINFOW()
si.cb = ctypes.sizeof(si)
pi = PROCESS_INFORMATION()
cmd = '"' + sys.executable + '" -c "import time; time.sleep(300)"'
ok = kernel.CreateProcessW(None, cmd, None, None, False, 0x08000000, None, None, ctypes.byref(si), ctypes.byref(pi))
if not ok:
    raise RuntimeError("could not start")
open("results/grandchild.txt", "w", encoding="utf-8").write(str(int(pi.dwProcessId)))
while True:
    pass
"""
    else:
        spawn = (
            "import os, time\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    time.sleep(300)\n"
            "    os._exit(0)\n"
            "open('results/grandchild.txt', 'w', encoding='utf-8').write(str(pid))\n"
            "while True:\n"
            "    time.sleep(0.2)\n"
        )
    started = time.monotonic()
    result = await tool.run(code=spawn, files=[])
    elapsed = time.monotonic() - started
    assert not result.ok
    assert result.output == _TOO_LONG
    assert elapsed < 20
    child_pid = int(result.data.get("child_pid") or 0)
    grand_path = room / "results" / "grandchild.txt"
    assert grand_path.is_file(), result.output
    grand_pid = int(grand_path.read_text(encoding="utf-8").strip())
    _wait_until_dead(child_pid, grand_pid)
    assert not _alive(child_pid)
    assert not _alive(grand_pid)


@pytest.mark.skipif(sys.platform != "win32", reason="the memory cap is a Windows job limit")
async def test_a_memory_bomb_is_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATA_CELL_MEMORY_BYTES == 2 * 1024 * 1024 * 1024
    monkeypatch.setattr("arelis.tools.data_cell.DATA_CELL_MEMORY_BYTES", 256 * 1024 * 1024)
    tool, _room = _tool(tmp_path)
    result = await tool.run(
        code="blob = bytearray(400 * 1024 * 1024)\nprint(len(blob))\n",
        files=[],
    )
    assert not result.ok
    assert result.output == _TOO_MUCH_MEMORY
    assert "400" not in result.output


async def test_a_network_call_is_refused(tmp_path: Path) -> None:
    tool, _room = _tool(tmp_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.settimeout(0.5)
    port = sock.getsockname()[1]
    accepted = False
    try:
        result = await tool.run(
            code=(
                "import socket\n"
                "s = socket.socket()\n"
                "s.settimeout(2)\n"
                f"s.connect(('127.0.0.1', {port}))\n"
                "print('connected')\n"
            ),
            files=[],
        )
        try:
            conn, _addr = sock.accept()
            conn.close()
            accepted = True
        except TimeoutError:
            accepted = False
    finally:
        sock.close()
    assert not result.ok
    assert "connected" not in result.output
    assert not accepted


async def test_starting_another_program_is_refused(tmp_path: Path) -> None:
    tool, _room = _tool(tmp_path)
    result = await tool.run(
        code="import os\nos.system('echo hi')\nprint('ran')\n",
        files=[],
    )
    assert not result.ok
    assert result.output == "I can't start other programs from here."
    assert "ran" not in result.output


async def test_an_oversized_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_INPUT_BYTES == 32 * 1024 * 1024
    monkeypatch.setattr("arelis.tools.data_cell.MAX_INPUT_BYTES", 32)
    tool, room = _tool(tmp_path)
    (room / "data.csv").write_text("B\n" + ("1\n" * 40), encoding="utf-8")
    result = await tool.run(
        code='print(read_table("data.csv")["B"].mean())',
        files=["data.csv"],
    )
    assert not result.ok
    assert result.output == _TOO_BIG
    assert not (room / "results").exists() or not any((room / "results").glob("*.png"))


async def test_no_room_or_no_folder_is_one_refusal(tmp_path: Path) -> None:
    room = tmp_path / "room"
    room.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="lab", path=room.resolve())])
    nowhere = DataCellTool(workspace, None)
    missing = await nowhere.run(code="print(1)", files=[])
    assert not missing.ok
    assert missing.output == _REFUSE_READ
    empty = DataCellTool(workspace, SimpleNamespace(active=SimpleNamespace(root="")))
    no_folder = await empty.run(code="print(1)", files=["data.csv"])
    assert not no_folder.ok
    assert no_folder.output == _REFUSE_READ


async def test_the_child_does_not_see_parent_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_PROBE", "room-secret")
    monkeypatch.setenv("FAKE_TOKEN", "sekret-value")
    tool, _room = _tool(tmp_path)
    result = await tool.run(
        code=(
            "import os\n"
            "print('ARELIS_PROBE=' + str('ARELIS_PROBE' in os.environ))\n"
            "print('FAKE_TOKEN=' + str('FAKE_TOKEN' in os.environ))\n"
            "print('MPL=' + os.environ.get('MPLBACKEND', ''))\n"
        ),
        files=[],
    )
    assert result.ok, result.output
    assert "ARELIS_PROBE=False" in result.output
    assert "FAKE_TOKEN=False" in result.output
    assert "room-secret" not in result.output
    assert "sekret-value" not in result.output
    assert "MPL=Agg" in result.output


def test_room_file_questions_point_at_data_cell() -> None:
    from arelis.core.compact_prompt import compact_tool_policy
    from arelis.core.intent_catalog import weather_intent_matches
    from arelis.core.preflight import detect_intents

    text = compact_tool_policy()
    assert "csv→analyze" in text
    assert "csv in this room→data_cell" in text
    room = {"readings.csv", "m31.fits"}
    questions = (
        "What's the average of column B in readings.csv?",
        "Can you plot temperature over time from readings.csv?",
        "What does the header of the FITS file say?",
        "How big is the image in that FITS file?",
        "Which hour had the highest temperature in my readings?",
    )
    for question in questions:
        hints = detect_intents(question, room_files=room)
        kinds = {hint.kind for hint in hints}
        assert "data_cell" in kinds, question
        assert "weather" not in kinds, question
        assert "analyze" not in kinds, question
        assert "read_table" in next(h.nudge for h in hints if h.kind == "data_cell")
        assert "readings.csv" in next(h.nudge for h in hints if h.kind == "data_cell")
        assert "m31.fits" in next(h.nudge for h in hints if h.kind == "data_cell")
    assert weather_intent_matches("will it rain tomorrow")
    assert weather_intent_matches("what's the temperature outside")
    outside = detect_intents(
        "What's the average of column B in other.csv?",
        room_files=room,
    )
    assert not any(hint.kind == "data_cell" for hint in outside)
    assert any(hint.kind == "analyze" for hint in outside)
    sensor = detect_intents(
        "what was the peak in my sensor log",
        room_files={"sensor_log.csv"},
    )
    assert any(hint.kind == "data_cell" for hint in sensor)
    weather_log = detect_intents(
        "plot the weather log",
        room_files={"weather_log.csv"},
    )
    assert any(hint.kind == "data_cell" for hint in weather_log)
    sensor_data = detect_intents(
        "what is in the sensor data",
        room_files={"sensor-data.tsv"},
    )
    assert any(hint.kind == "data_cell" for hint in sensor_data)
    two = detect_intents(
        "summarize my data",
        room_files={"readings.csv", "m31.fits"},
    )
    assert not any(hint.kind == "data_cell" for hint in two)
    one = detect_intents("summarize my data", room_files={"readings.csv"})
    assert any(hint.kind == "data_cell" for hint in one)


def test_a_room_file_beats_the_weather_preinject(monkeypatch) -> None:
    from arelis.core.intent_catalog import weather_intent_matches

    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv", "m31.fits"},
    )
    assert not weather_intent_matches("Can you plot temperature over time from readings.csv?")
    assert not weather_intent_matches("Which hour had the highest temperature in my readings?")
    assert weather_intent_matches("will it rain tomorrow")
    assert weather_intent_matches("what's the temperature outside")
    assert weather_intent_matches("what's the temperature in other.csv")


def test_only_data_files_and_specific_stems_take_the_room(monkeypatch) -> None:
    from arelis.core.intent_catalog import (
        data_cell_should_reject,
        weather_intent_matches,
    )
    from arelis.core.preflight import detect_intents

    code_room = {"parser.py", "notes.md", "briefing.md", "main.py"}
    for question in ("run the parser", "open the briefing", "what's the weather"):
        hints = detect_intents(question, room_files=code_room)
        assert not any(hint.kind == "data_cell" for hint in hints), question
    assert weather_intent_matches("what's the weather")
    rain = detect_intents("will it rain tomorrow", room_files={"weather.csv"})
    assert any(hint.kind == "weather" for hint in rain)
    assert not any(hint.kind == "data_cell" for hint in rain)
    outside = detect_intents(
        "what's the temperature outside",
        room_files={"data.csv"},
    )
    assert any(hint.kind == "weather" for hint in outside)
    assert not any(hint.kind == "data_cell" for hint in outside)
    named = detect_intents(
        "plot temperature over time from weather.csv",
        room_files={"weather.csv"},
    )
    assert any(hint.kind == "data_cell" for hint in named)
    assert not any(hint.kind == "weather" for hint in named)
    forecast = detect_intents("what's the weather", room_files={"weather.csv"})
    assert any(hint.kind == "weather" for hint in forecast)
    assert not any(hint.kind == "data_cell" for hint in forecast)

    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv", "m31.fits"},
    )
    tools = {"data_cell", "analyze", "weather", "workspace", "python"}
    assert data_cell_should_reject(
        "analyze",
        {},
        "What's the average of column B in readings.csv?",
        tools,
    )
    assert not data_cell_should_reject(
        "analyze",
        {},
        "Which hour had the highest temperature in my readings?",
        tools,
    )
    assert data_cell_should_reject(
        "workspace",
        {"action": "read"},
        "show me readings.csv",
        tools,
    )
    assert not data_cell_should_reject(
        "workspace",
        {"action": "write"},
        "rename readings.csv",
        tools,
    )
    assert not data_cell_should_reject(
        "workspace",
        {"action": "read"},
        "open readings.csv in the editor",
        tools,
    )
    assert not data_cell_should_reject(
        "python",
        {},
        "write a script that reads readings.csv",
        tools,
    )
    assert not data_cell_should_reject(
        "analyze",
        {},
        "What's the average of column B in readings.csv?",
        {"analyze", "weather"},
    )


def test_data_cell_off_leaves_weather_and_analyze(monkeypatch) -> None:
    from arelis.core.intent_catalog import weather_intent_matches
    from arelis.core.preflight import detect_intents

    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv", "m31.fits"},
    )
    room = {"readings.csv", "m31.fits"}
    hints = detect_intents(
        "What's the average of column B in readings.csv?",
        room_files=room,
    )
    kinds = {hint.kind for hint in hints}
    assert "data_cell" not in kinds
    assert "analyze" in kinds
    plot = "Can you plot temperature over time from readings.csv?"
    assert weather_intent_matches(plot)
    again = detect_intents(plot, room_files=room)
    assert not any(hint.kind == "data_cell" for hint in again)
    assert weather_intent_matches("will it rain tomorrow")


def test_data_cell_is_a_local_write_with_a_plain_status() -> None:
    assert evaluate_capability("data_cell", {"code": "print(1)"}) == "WRITE_LOCAL"
    assert evaluate_confirm("data_cell", {"code": "print(1)"}, risk="write") is True
    text = describe_call("data_cell", {"files": ["readings.csv"]})
    assert "results" in text.lower()
    assert "data_cell" not in text
    assert tool_errand("data_cell") == "reading your data"


def test_a_data_cell_chart_is_not_replaced_by_the_plot_guard(monkeypatch) -> None:
    from arelis.core.claims import detect_exactness_need, unsupported_exactness_reply

    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv"},
    )
    ledger = EvidenceLedger()
    ledger.record_tool(
        "data_cell",
        ok=True,
        output="Chart saved as chart.png",
        data={
            "abs_path": r"C:\room\results\chart.png",
            "charts": [{"name": "chart.png", "abs_path": r"C:\room\results\chart.png"}],
        },
    )
    need = detect_exactness_need("Can you plot temperature over time from readings.csv?")
    reply = "The chart is saved."
    missing = ledger.missing_kinds(need.kinds)
    if missing:
        reply = unsupported_exactness_reply(missing)
    assert "ASCII" not in reply
    assert "plot file" not in reply


def test_a_data_cell_number_is_not_refused(monkeypatch) -> None:
    from arelis.core.claims import detect_exactness_need, unsupported_exactness_reply

    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv"},
    )
    ledger = EvidenceLedger()
    ledger.record_tool("data_cell", ok=True, output="5.0", data={})
    need = detect_exactness_need("What's the average of column B in readings.csv?")
    reply = "The average of column B is 5.0."
    missing = ledger.missing_kinds(need.kinds)
    if missing:
        reply = unsupported_exactness_reply(missing)
    assert "5.0" in reply
    assert "analyze reading" not in reply


def test_without_a_data_cell_result_the_guards_stay() -> None:
    from arelis.core.claims import detect_exactness_need, unsupported_exactness_reply

    ledger = EvidenceLedger()
    plot = unsupported_exactness_reply(
        ledger.missing_kinds(
            detect_exactness_need("Can you plot temperature over time from readings.csv?").kinds
        )
    )
    assert "ASCII" in plot
    number = unsupported_exactness_reply(
        ledger.missing_kinds(
            detect_exactness_need("What's the average of column B in readings.csv?").kinds
        )
    )
    assert "analyze reading" in number
    failed = EvidenceLedger()
    failed.record_tool(
        "data_cell",
        ok=False,
        output="I couldn't finish that.",
        data={"abs_path": r"C:\room\results\chart.png"},
    )
    assert failed.missing_kinds(("plot", "math", "analyze")) == ["plot", "math", "analyze"]


async def test_a_bare_list_names_the_files_in_the_room(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "readings.csv").write_text("time,temperature,B\n1,10,2\n", encoding="utf-8")
    (room / "m31.fits").write_bytes(b"not a fits")
    result = await tool.run(code="list", files=[])
    assert result.ok, result.output
    assert "Data files in this room: m31.fits, readings.csv." in result.output


async def test_a_missing_name_is_answered_with_the_room_files(tmp_path: Path) -> None:
    tool, room = _tool(tmp_path)
    (room / "readings.csv").write_text("A,B\n1,2\n", encoding="utf-8")
    result = await tool.run(code='read_table("other.csv")', files=["other.csv"])
    assert not result.ok
    assert "Data files in this room: readings.csv." in result.output


def test_fits_questions_reject_recall_and_workspace(monkeypatch) -> None:
    from arelis.core.intent_catalog import data_cell_should_reject
    from arelis.core.preflight import detect_intents

    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv", "m31.fits"},
    )
    room = {"readings.csv", "m31.fits"}
    tools = {"data_cell", "recall", "workspace", "analyze"}
    for question in (
        "What does the header of the FITS file say?",
        "How big is the image in that FITS file?",
    ):
        hints = detect_intents(question, room_files=room)
        assert any(hint.kind == "data_cell" for hint in hints), question
        assert "m31.fits" in next(h.nudge for h in hints if h.kind == "data_cell")
        assert data_cell_should_reject("recall", {}, question, tools)
        assert data_cell_should_reject("workspace", {"action": "list"}, question, tools)
        assert not data_cell_should_reject("recall", {}, question, {"recall", "workspace"})


def test_the_hottest_hour_is_not_a_forecast(monkeypatch) -> None:
    from arelis.core.claims import detect_exactness_need

    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv", "m31.fits"},
    )
    hour = "Which hour had the highest temperature in my readings?"
    assert not detect_exactness_need(hour, data_cell=True).needs_weather
    assert detect_exactness_need(hour, data_cell=False).needs_weather
    assert detect_exactness_need("will it rain tomorrow", data_cell=True).needs_weather
    assert detect_exactness_need(
        "what's the temperature outside",
        data_cell=True,
    ).needs_weather


def test_claims_stays_on_main_when_the_tool_is_off_or_the_room_has_no_data_file(
    monkeypatch,
) -> None:
    from arelis.core.claims import detect_exactness_need

    hour = "Which hour had the highest temperature in my readings?"
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv"},
    )
    assert detect_exactness_need(hour).needs_weather
    assert detect_exactness_need(hour, data_cell=False).needs_weather
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    assert detect_exactness_need(hour, data_cell=True).needs_weather
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    monkeypatch.setattr("arelis.core.intent_catalog.live_room_filenames", lambda: set())
    assert detect_exactness_need(hour, data_cell=True).needs_weather


def test_evidence_ignores_a_cell_when_the_tool_is_off_or_the_room_has_no_data_file(
    monkeypatch,
) -> None:
    chart = {
        "abs_path": r"C:\room\results\chart.png",
        "charts": [{"name": "chart.png", "abs_path": r"C:\room\results\chart.png"}],
    }
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"readings.csv"},
    )
    off = EvidenceLedger()
    off.record_tool("data_cell", ok=True, output="5.0", data=chart)
    assert off.missing_kinds(("plot", "math", "analyze")) == ["plot", "math", "analyze"]
    plain = EvidenceLedger()
    plain.record_tool("plot", ok=True, output="chart.png", data={"path": "chart.png"})
    assert plain.has_ok("plot")
    assert not plain.has_ok("analyze")
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    monkeypatch.setattr("arelis.core.intent_catalog.live_room_filenames", lambda: set())
    empty = EvidenceLedger()
    empty.record_tool("data_cell", ok=True, output="5.0", data=chart)
    assert empty.missing_kinds(("plot", "math", "analyze")) == ["plot", "math", "analyze"]


def test_preflight_stays_on_main_when_the_tool_is_off_or_the_room_has_no_data_file(
    monkeypatch,
) -> None:
    from arelis.core.preflight import detect_intents

    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    hour = "Which hour had the highest temperature in my readings?"
    held = detect_intents(hour, room_files={"readings.csv"}, offer_data_cell=False)
    assert not any(hint.kind == "data_cell" for hint in held)
    assert any(hint.kind == "weather" for hint in held)
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    flagged = detect_intents(hour, room_files={"readings.csv"}, offer_data_cell=True)
    assert not any(hint.kind == "data_cell" for hint in flagged)
    empty = detect_intents(
        "What does the header of the FITS file say?",
        room_files=set(),
        offer_data_cell=True,
    )
    assert not any(hint.kind == "data_cell" for hint in empty)


def test_intent_catalog_does_not_reject_when_the_tool_is_off_or_no_data_file(
    monkeypatch,
) -> None:
    from arelis.core.intent_catalog import data_cell_should_reject

    question = "What does the header of the FITS file say?"
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"m31.fits"},
    )
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    assert not data_cell_should_reject("recall", {}, question, {"data_cell", "recall"})
    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: True)
    monkeypatch.setattr("arelis.core.intent_catalog.live_room_filenames", lambda: set())
    assert not data_cell_should_reject("recall", {}, question, {"data_cell", "recall"})
    assert not data_cell_should_reject(
        "workspace",
        {"action": "list"},
        question,
        {"data_cell", "workspace"},
    )


@pytest.mark.asyncio
async def test_turn_dispatch_still_calls_recall_when_the_tool_is_off(monkeypatch) -> None:
    from arelis.core.turn_dispatch import dispatch_calls
    from tests.test_no_call_path import _ctx, _FakeLoop, _scratch
    from tests.test_round_scratch import _augment

    monkeypatch.setattr("arelis.core.intent_catalog.data_cell_enabled", lambda: False)
    monkeypatch.setattr(
        "arelis.core.intent_catalog.live_room_filenames",
        lambda: {"m31.fits", "readings.csv"},
    )
    loop = _augment(_FakeLoop())
    called: list[str] = []

    async def _call(name: str, **_kwargs: object) -> SimpleNamespace:
        called.append(name)
        return SimpleNamespace(ok=True, output="ok", data={})

    loop.tools.call = _call
    text = "What does the header of the FITS file say?"
    tools = {"recall", "workspace"}
    r = _scratch(
        text=text,
        calls=[("recall", {"query": "fits"})],
        content="",
        streamed="",
        tool_names=tools,
        available=tools,
        visible=tools,
        available_all=tools,
    )
    ctx = _ctx(text=text, tool_names=tools)
    await dispatch_calls(loop, ctx, r, 1)
    assert called == ["recall"]
    assert not any("Data files in this room" in str(item.get("content", "")) for item in r.messages)
