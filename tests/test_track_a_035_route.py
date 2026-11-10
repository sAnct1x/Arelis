"""Track A 0.3.5 routing: sandbox cards, file edits, leftover Drive strip."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.cell_work import begin_cell_work
from arelis.core.intent_catalog import DOCUMENT, RUN_SCRIPT
from arelis.core.preflight import (
    detect_intents,
    unasked_desktop_block,
    unasked_notes_write_block,
    user_asked_for_desktop,
)
from arelis.tools.base import ToolRegistry
from arelis.tools.python_handoff import (
    python_code_needs_run_script,
    rewrite_python_to_run_script,
)
from arelis.tools.run_script import RunScriptTool

_EDIT = (
    "Edit that workbook: add a sheet called Notes with the text "
    "'30 second Saturn exposures', and add Earth to the chart if it was "
    "missing. Confirm she wrote a new *-edited copy and did not overwrite "
    "the first file."
)
_HTTP = "Write and run Python that fetches https://example.com and prints the HTTP status code."
_WRITE = (
    "Write and run Python that appends a line to "
    r"C:\Users\origi\Desktop\Arelis 0.3.5 test files\observing-notes.md."
)
_FIT = (
    "Write and run Python that fits a line to 50 noisy points, prints the "
    "slope and intercept, and saves a PNG of the fit."
)


@pytest.mark.asyncio
async def test_network_or_outside_write_python_goes_through_run_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    http_code = (
        "import urllib.request\n"
        "print(urllib.request.urlopen('https://example.com', timeout=1).status)\n"
    )
    write_code = (
        r"open(r'C:\Users\origi\Desktop\Arelis 0.3.5 test files\observing-notes.md', 'a')"
        ".write('x')\n"
    )
    fit_code = (
        "import numpy as np\n"
        "xs = np.arange(50)\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot(xs, xs)\n"
        "plt.savefig('line_fit.png')\n"
        "print(2.21, -2.68)\n"
    )
    assert python_code_needs_run_script(http_code)
    assert python_code_needs_run_script(write_code)
    assert not python_code_needs_run_script(fit_code)

    rewritten = rewrite_python_to_run_script(
        [
            ("web_fetch", {"url": "https://example.com"}),
            ("python", {"code": http_code}),
            ("python", {"code": write_code}),
            ("python", {"code": fit_code}),
        ]
    )
    assert rewritten[0][0] == "web_fetch"
    assert rewritten[1] == ("run_script", {"code": http_code})
    assert rewritten[2][0] == "run_script" and rewritten[2][1]["code"] == write_code
    assert rewritten[3] == ("python", {"code": fit_code})

    assert RUN_SCRIPT.matches(_HTTP)
    assert RUN_SCRIPT.matches(_WRITE)
    assert not RUN_SCRIPT.matches(_FIT)

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "data"))
    begin_cell_work("t035-route-http")
    tool = RunScriptTool([str(tmp_path / "proj")])
    (tmp_path / "proj").mkdir()
    registry = ToolRegistry()
    registry.register(tool)
    args = {"code": http_code}
    assert registry.needs_confirm("run_script", args) is False
    first = await tool.run(**args)
    assert not first.ok
    assert "no network" in first.output
    assert registry.needs_confirm("run_script", args) is True
    card = registry.describe_call("run_script", args)
    assert "Let this code use the network" in card


def test_edit_workbook_routes_to_document_not_desktop() -> None:
    assert DOCUMENT.matches(_EDIT)
    assert not user_asked_for_desktop(_EDIT)
    hints = detect_intents(_EDIT)
    kinds = {h.kind for h in hints}
    assert "document" in kinds
    assert "desktop" not in kinds
    assert "desktop_look" not in kinds
    nudge = next(h.nudge for h in hints if h.kind == "document")
    assert "from_path" in nudge
    assert "desktop" in nudge.lower()


def test_file_tasks_refuse_unasked_desktop_and_notes() -> None:
    assert unasked_desktop_block(_EDIT) is not None
    assert unasked_desktop_block(_WRITE) is not None
    assert unasked_notes_write_block(_WRITE, {"action": "add"}) is not None
    assert unasked_notes_write_block(_WRITE, {"action": "list"}) is None
    assert unasked_desktop_block("Open notepad and type hello") is None
    assert (
        unasked_notes_write_block("Add a note about Saturn tonight", {"action": "add"})
        is None
    )


def test_failed_desktop_drive_clears_the_strip(arelis_window, qt_app) -> None:
    window = arelis_window()
    window.show()
    window.chat.add_user(_EDIT)
    qt_app.processEvents()
    window._drive_session = True
    window.conversation.set_drive(True, "capturing…")
    qt_app.processEvents()
    assert window.conversation.drive.isVisible()
    assert "capturing" in window.conversation.drive.status.text()
    window._set_busy(True)
    qt_app.processEvents()
    window._set_busy(False)
    qt_app.processEvents()
    assert not window.conversation.drive.isVisible()
    assert window._drive_session is False
