"""Track A 0.3.5 fixes: spaced-path Allow, table verify, composer grow."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.claims import detect_exactness_need, unsupported_exactness_reply
from arelis.core.events import Event, EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.core.orchestrator_shared import typed_absolute_paths
from arelis.tools.base import ToolRegistry
from arelis.ui.theme_tokens import METRICS
from arelis.workspace import WorkspaceRoots


class _StubRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None


_WIN_CSV = (
    r"C:\Users\origi\Desktop\Arelis 0.3.5 test files\planets.csv"
)
_WIN_PROMPT = (
    "Make a new Excel workbook of the 8 planets from "
    rf"{_WIN_CSV}, with mass, radius, moons and AU as real numbers."
)


def test_typed_path_with_spaces_raises_external_read_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed path with spaces must raise the existing external_read card."""
    found = typed_absolute_paths(_WIN_PROMPT)
    assert _WIN_CSV in found

    root = tmp_path / "proj"
    root.mkdir()
    folder = tmp_path / "Arelis 0.3.5 test files"
    folder.mkdir()
    outside = folder / "planets.csv"
    outside.write_text("planet,au\nEarth,1\n", encoding="utf-8")
    ask = (
        "Make a new Excel workbook of the 8 planets from "
        f"{outside}, with mass, radius, moons and AU as real numbers."
    )
    assert str(outside) in typed_absolute_paths(ask)

    # A typed folder followed by a sentence that names a file must keep the
    # real folder as a fallback, or the Allow card never appears. The
    # folder is created here, but the assertion and Allow check run after
    # the original spaced-file card so a revert still proves that case.
    typed_folder = tmp_path / "test"
    typed_folder.mkdir()
    folder_ask = (
        f"List the files in {typed_folder} and convert sample.nc to csv"
    )

    async def _quiet_run(self, *args, **kwargs):
        self.terminal_sent = True

    monkeypatch.setattr(AgentLoop, "run", _quiet_run)

    async def _expect_allow(ask_text: str, expected: Path) -> None:
        bus = EventBus()
        orch = Orchestrator(
            bus,
            _StubRouter(),  # type: ignore[arg-type]
            ToolRegistry(),
            {
                "agent": {"confirm_timeout_s": 30},
                "workspace": {"roots": [str(root)]},
                "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            },
            SessionMemory(),
            workspace=WorkspaceRoots.from_paths([str(root)]),
        )
        task = asyncio.create_task(
            orch.on_user_message(
                Event(EventType.USER_MESSAGE, {"text": ask_text})
            )
        )
        try:
            for _ in range(100):
                if orch._confirm_live:
                    break
                await asyncio.sleep(0)
            assert len(orch._confirm_live) == 1
            live = next(iter(orch._confirm_live.values()))
            assert live["tool"] == "external_read"
            assert Path(live["args"]["path"]) == expected.resolve()
            next(iter(orch._confirm_waiters.values())).set_result("allow")
            await asyncio.wait_for(task, timeout=2)
            assert orch.workspace.has_external_read(expected)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _run() -> None:
        await _expect_allow(ask, outside)
        assert str(typed_folder) in typed_absolute_paths(folder_ask)
        await _expect_allow(folder_ask, typed_folder)

    asyncio.run(_run())


def test_table_verify_reports_tool_error_or_accepts_python() -> None:
    """A table ask must not ship the canned analyze refuse over a real outcome.

    A failed file read should name that error (and ask for access when the
    path is outside the roots). A successful python cell that already printed
    the table must be allowed to stand.
    """
    ask = (
        "Write and run Python in the sandbox that writes a tiny FITS table "
        "and a tiny HDF5 file of wavelength and flux, then read both and "
        "convert each to CSV."
    )
    need = detect_exactness_need(ask)
    assert "analyze" in need.kinds
    canned = unsupported_exactness_reply(["analyze"])

    failed = EvidenceLedger()
    failed.record_tool(
        "analyze",
        ok=False,
        output="Path outside allowed workspace roots: C:\\data\\planets.csv",
        data={},
        args={"path": r"C:\data\planets.csv", "action": "head"},
    )
    reply = _exactness_finish_refuse(
        "Earth has 1 moon.",
        exact_need=need,
        ledger=failed,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert reply is not None
    assert reply != canned
    lowered = reply.lower()
    assert "outside" in lowered and "workspace" in lowered
    assert "allow" in lowered

    done = EvidenceLedger()
    done.record_tool(
        "python",
        ok=True,
        output="wrote flux.fits and flux.h5; csv rows: 4",
        data={"result": "wrote flux.fits and flux.h5; csv rows: 4"},
    )
    assert (
        _exactness_finish_refuse(
            "The FITS and HDF5 tables each have 4 rows of wavelength and flux.",
            exact_need=need,
            ledger=done,
            numeric_gate=True,
            evidence_gate=True,
        )
        is None
    )


def test_analyze_and_vision_failure_replies_hide_tool_detail() -> None:
    """Failed analyze or vision replies must not paste raw tool output."""
    details = (
        (
            "Traceback (most recent call last):\n"
            '  File "/home/x/.arelis/sandbox/cell.py", line 2\n'
            "FileNotFoundError: ... /home/x/.arelis/sandbox/data.csv"
        ),
        (
            "summary | /home/x/Arelis/workspace/data/planets.csv | "
            "pandas ParserError: expected 3 fields"
        ),
        "data_cell is off (tools.data_cell.enabled=false)",
    )
    banned = (
        "Traceback",
        "FileNotFoundError",
        "/home/x/.arelis/sandbox/cell.py",
        "/home/x/.arelis/sandbox/data.csv",
        "/home/x/Arelis/workspace/data/planets.csv",
        "pandas ParserError",
        "tools.data_cell.enabled",
        "data_cell is off",
        "summary |",
    )
    for detail in details:
        for kind, failed_kw, detail_kw in (
            ("analyze", "analyze_failed", "analyze_detail"),
            ("vision", "vision_failed", "vision_detail"),
        ):
            reply = unsupported_exactness_reply(
                [kind],
                **{failed_kw: True, detail_kw: detail},
            )
            assert reply
            assert detail not in reply
            lowered = reply.lower()
            for needle in banned:
                assert needle.lower() not in lowered, (
                    f"{kind} reply leaked {needle!r}: {reply}"
                )


def test_workbench_composer_grows_or_scrolls_long_text(qt_app) -> None:
    """Long typed text in the seated composer must stay visible, not clipped."""
    from arelis.core.bus import EventBus as Bus
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.idle_host import sync_idle_mode

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600, "theme": "sodium"},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        Bus(),
    )
    try:
        window._reset_layout()
        window.resize(800, 600)
        window.show()
        qt_app.processEvents()
        window.chat.add_user("hello")
        sync_idle_mode(window)
        qt_app.processEvents()
        conv = window.conversation
        assert not conv._idle_mode
        edit = conv.input
        floor = int(METRICS["control"])
        prompt = (
            "Convert C:\\Users\\origi\\Desktop\\Arelis 0.3.5 test files\\"
            "observing-notes.md to a Word file, then that Word file to PDF, "
            "then the PDF back to markdown. Read each result and check the "
            "2.4 arcsec and 30 second figures survived. Also keep the notes "
            "about Saturn exposures and the 8 inch Dobsonian in the converted "
            "copies so none of that text is lost."
        )
        edit.setText(prompt)
        conv._fit_workbench_prompt()
        qt_app.processEvents()
        conv._fit_workbench_prompt()
        qt_app.processEvents()
        assert edit.text() == prompt
        bar = edit.verticalScrollBar()
        # A long typed ask must grow so the whole draft is on screen (the
        # old six-line cap left a leftover scroll and hid the start).
        assert edit.height() > floor, (
            f"composer stayed at {edit.height()}px (floor {floor})"
        )
        assert bar.maximum() == 0, (
            f"text still clipped: scroll_max={bar.maximum()} "
            f"value={bar.value()} height={edit.height()} "
            f"view={edit.viewport().height()}"
        )
        assert bar.value() == 0
        # A narrow Filament-like width may reach the cap and then must
        # offer a scrollbar rather than hide the overflow.
        from PySide6.QtCore import Qt

        edit.setFixedWidth(280)
        conv._fit_workbench_prompt()
        qt_app.processEvents()
        conv._fit_workbench_prompt()
        qt_app.processEvents()
        bar = edit.verticalScrollBar()
        assert edit.height() > floor
        if bar.maximum() > 0:
            assert (
                edit.verticalScrollBarPolicy()
                == Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
        else:
            assert bar.value() == 0
    finally:
        window.hide()
        window.loop.close()
