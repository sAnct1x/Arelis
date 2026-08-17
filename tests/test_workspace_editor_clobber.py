"""Nothing may replace unsaved work in the workspace editor without saying so.

The editor is a plain buffer with no undo history across loads and no autosave
behind it, so a replacement is final. Three different things replace it — the
operator opening a file, Arelis writing one, and a save flushing it back — and
each of them was unconditional. Type for ten minutes into a file Arelis then
touches and the ten minutes are gone, with no message and nothing on screen to
suggest anything happened.

The rule these tests pin is not "refuse", it is "never silently". Every path
still gets to do what it was asked to do; it just has to be a decision. Where
the operator asked for the replacement it happens after one warning, and where
Arelis did it happens to the file on disk but not to the buffer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.workspace import WorkspaceRoots


@pytest.fixture
def panel(qt_app):
    from arelis.ui.panels.workspace import WorkspacePanel

    return WorkspacePanel()


@pytest.fixture
def window(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real window rooted at a scratch directory, with chat captured.

    The guards live across the panel and the window — the panel owns the dirty
    buffer, the window owns the disk and the copy — so a panel-only test would
    miss the half that matters.
    """
    import arelis.ui.app as app_module
    from arelis.ui.app import ArelisWindow, BusBridge

    monkeypatch.setattr(app_module, "push_recent_workspace_file", lambda path: [])
    roots = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
            "_workspace": roots,
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    said: list[str] = []
    monkeypatch.setattr(window.chat, "add_system", said.append)
    window.said = said
    try:
        yield window
    finally:
        window.hide()
        window.loop.close()


def test_a_write_underneath_unsaved_edits_keeps_the_edits(panel) -> None:
    """The defect, stated directly: her write must not take the buffer.

    This is the assertion that would have failed before the change. The file on
    disk is already hers by the time this runs — the only question is whether
    the operator's unsaved version survives alongside it, and it has to, because
    it exists nowhere else.
    """
    panel.set_file("notes.txt", "from disk", abs_path="/tmp/notes.txt")
    panel.editor.setPlainText("half an hour of typing")

    placed = panel.set_file("notes.txt", "arelis rewrote this", abs_path="/tmp/notes.txt")

    assert placed is False
    assert panel.editor.toPlainText() == "half an hour of typing"


def test_a_write_lands_normally_when_nothing_is_unsaved(panel) -> None:
    """Overcorrecting here would break the ordinary case, which is most cases.

    A clean buffer has nothing to lose, so a write should appear immediately and
    silently the way it always did.
    """
    panel.set_file("notes.txt", "from disk", abs_path="/tmp/notes.txt")

    placed = panel.set_file("notes.txt", "arelis rewrote this", abs_path="/tmp/notes.txt")

    assert placed is True
    assert panel.editor.toPlainText() == "arelis rewrote this"


def test_loading_a_file_does_not_count_as_editing_it(panel) -> None:
    """Dirty is derived, not latched, and setPlainText fires textChanged.

    If loading marked the buffer dirty, the very first thing every session does
    would arm both gates and every subsequent open would demand confirmation for
    nothing — which trains people to click through the warning that matters.
    """
    panel.set_file("notes.txt", "from disk", abs_path="/tmp/notes.txt")

    assert not panel.has_unsaved_changes()


def test_typing_then_undoing_by_hand_clears_the_dirty_state(panel) -> None:
    panel.set_file("notes.txt", "from disk", abs_path="/tmp/notes.txt")
    panel.editor.setPlainText("scratch")
    assert panel.has_unsaved_changes()

    panel.editor.setPlainText("from disk")

    assert not panel.has_unsaved_changes()


def test_opening_over_unsaved_edits_warns_once_then_obeys(window, tmp_path: Path) -> None:
    """The operator's own discard: allowed, but not on the first click.

    Opening is the one replacement the operator explicitly asked for, so refusing
    outright would be wrong. Doing it silently is still a data-loss bug, because
    from the outside a click on `open` looks like navigation, not deletion.
    """
    (tmp_path / "a.txt").write_text("first file", encoding="utf-8")
    (tmp_path / "b.txt").write_text("second file", encoding="utf-8")
    window._open_file("a.txt")
    window.workspace.editor.setPlainText("unsaved work")

    window._open_file("b.txt")

    assert window.workspace.editor.toPlainText() == "unsaved work"
    assert "Unsaved changes" in window.said[-1]

    window._open_file("b.txt")

    assert window.workspace.editor.toPlainText() == "second file"


def test_the_open_warning_does_not_carry_to_a_different_file(
    window, tmp_path: Path
) -> None:
    """Arming is per target, or the second warning gets skipped by accident.

    Confirming a discard into b.txt must not leave c.txt pre-approved, since the
    operator answered a question about b.txt.
    """
    (tmp_path / "a.txt").write_text("first file", encoding="utf-8")
    (tmp_path / "b.txt").write_text("second file", encoding="utf-8")
    (tmp_path / "c.txt").write_text("third file", encoding="utf-8")
    window._open_file("a.txt")
    window.workspace.editor.setPlainText("unsaved work")
    window._open_file("b.txt")

    window._open_file("c.txt")

    assert window.workspace.editor.toPlainText() == "unsaved work"
    assert "Unsaved changes" in window.said[-1]


def test_saving_over_a_file_she_changed_warns_once_then_obeys(
    window, tmp_path: Path
) -> None:
    """The clobber running the other way, which is the easier one to miss.

    The buffer was loaded before she wrote, so flushing it back is a silent
    revert of her work — and the operator pressing `save` has no way to know the
    file moved underneath them.
    """
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    window._open_file("notes.txt")
    target.write_text("arelis wrote this", encoding="utf-8")

    window._save_file("notes.txt", "original")

    assert target.read_text(encoding="utf-8") == "arelis wrote this"
    assert "changed on disk" in window.said[-1]

    window._save_file("notes.txt", "original")

    assert target.read_text(encoding="utf-8") == "original"


def test_an_ordinary_save_is_never_questioned(window, tmp_path: Path) -> None:
    """A false positive here makes save feel broken, which is worse than silent.

    Nothing touched the file, so the staleness check has to stay out of the way
    of the path that runs hundreds of times a session.
    """
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    window._open_file("notes.txt")
    window.workspace.editor.setPlainText("edited by hand")

    window._save_file("notes.txt", "edited by hand")

    assert target.read_text(encoding="utf-8") == "edited by hand"
    assert not any("changed on disk" in line for line in window.said)
    assert not window.workspace.has_unsaved_changes()


def test_saving_a_new_file_is_not_treated_as_stale(window, tmp_path: Path) -> None:
    """Nothing is loaded, so there is no baseline to be behind."""
    window._save_file("fresh.txt", "brand new")

    assert (tmp_path / "fresh.txt").read_text(encoding="utf-8") == "brand new"
    assert not any("changed on disk" in line for line in window.said)
