"""Desk mode is the default; folders stay underneath."""

from __future__ import annotations

from pathlib import Path

from arelis.desk import Artifact
from arelis.ui.panels.workspace import WorkspacePanel


def test_desk_starts_empty_and_explains_itself(qt_app) -> None:
    panel = WorkspacePanel()
    try:
        panel.show()
        assert panel.empty_face.isVisible()
        assert panel.split.isHidden()
        assert panel.desk_empty.isVisible()
        assert not panel.desk_list.isVisible()
        assert not panel.browse_list.isVisible()
        assert "Nothing on the desk yet" in panel.desk_empty.text()
        assert panel.keep_btn.toolTip() == "Keep a note on the desk"
    finally:
        panel.deleteLater()


def test_desk_lists_pins_first(qt_app, tmp_path: Path) -> None:
    panel = WorkspacePanel()
    try:
        panel.show()
        panel.set_projects(["lab"], "lab", paths={"lab": str(tmp_path)})
        panel.set_desk_items(
            [
                Artifact(
                    abs_path=str(tmp_path / "later.md"),
                    label="later",
                    kind="note",
                    pinned=False,
                    last_seen="2026-08-30T12:00:00",
                ),
                Artifact(
                    abs_path=str(tmp_path / "pin.md"),
                    label="pin me",
                    kind="note",
                    pinned=True,
                    last_seen="2026-08-30T11:00:00",
                ),
            ]
        )
        assert panel.desk_list.isVisible()
        assert panel.split.isVisible()
        assert panel.empty_face.isHidden()
        assert not panel.desk_empty.isVisible()
        assert panel.desk_list.count() == 2
        assert "pin me" in panel.desk_list.item(0).text()
        assert "pinned" in panel.desk_list.item(0).text()
    finally:
        panel.deleteLater()


def test_folders_mode_shows_the_tree(qt_app, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("ok", encoding="utf-8")
    panel = WorkspacePanel()
    try:
        panel.show()
        panel.set_projects(["lab"], "lab", paths={"lab": str(tmp_path)})
        panel.show_folders()
        assert panel.split.isVisible()
        assert panel.empty_face.isHidden()
        assert panel.browse_list.isVisible()
        assert not panel.desk_list.isVisible()
        names = [
            panel.browse_list.item(i).text()
            for i in range(panel.browse_list.count())
        ]
        assert "notes.txt" in names
        panel.show_desk()
        assert not panel.browse_list.isVisible()
    finally:
        panel.deleteLater()


def test_opening_a_file_shows_the_editor(qt_app, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("# Hello\n", encoding="utf-8")
    panel = WorkspacePanel()
    try:
        panel.show()
        panel.set_projects(["lab"], "lab", paths={"lab": str(tmp_path)})
        assert panel.split.isHidden()
        panel.set_file("note.md", "# Hello\n", abs_path=str(note))
        assert panel.empty_face.isHidden()
        assert panel.split.isVisible()
        assert panel.editor_stack.isVisible()
    finally:
        panel.deleteLater()


def test_markdown_opens_as_a_page(qt_app, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("# Hello\n\nworld", encoding="utf-8")
    panel = WorkspacePanel()
    try:
        panel.set_projects(["lab"], "lab", paths={"lab": str(tmp_path)})
        placed = panel.set_file("note.md", "# Hello\n\nworld", abs_path=str(note))
        assert placed
        assert panel.editor_stack.currentWidget() is panel.preview
        assert panel.read_btn.isChecked()
    finally:
        panel.deleteLater()
