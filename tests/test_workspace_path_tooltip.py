"""Labels and tooltips must not show the account name in a path."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.paths import expand_displayed_home, ui_display_path
from arelis.ui.attach_bar import AttachmentTile
from arelis.ui.first_run import FirstRunDialog
from arelis.ui.panels.workspace import WorkspacePanel
from arelis.ui.settings_dialog import SettingsDialog
from arelis.workspace import RootEntry, WorkspaceRoots


def test_workspace_tooltips_hide_the_account_name(
    qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project under the account home used to put that name on the tooltip.

    The path box already shortens a file under the data folder. The project
    tooltip, the folder tooltip, the attachment source, and the welcome line
    were still the absolute path. ``~`` is the form, and opening it again
    lands on the same folder.
    """
    home = tmp_path / "Users" / "someone"
    project = home / "Documents" / "papers"
    project.mkdir(parents=True)
    note = project / "note.txt"
    note.write_text("hi", encoding="utf-8")
    shot = project / "shot.png"
    shot.write_bytes(b"png")
    data = home / "AppData" / "Local" / "Arelis"
    diagram = data / "outputs" / "diagrams" / "diagram.png"
    diagram.parent.mkdir(parents=True)
    diagram.write_bytes(b"png")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))

    raw = str(project.resolve())
    assert "someone" in raw.replace("\\", "/")
    assert ui_display_path(project) == "~/Documents/papers"
    assert ui_display_path(home) == "~"
    assert ui_display_path(diagram) == "outputs/diagrams/diagram.png"
    assert ui_display_path(outside) == outside.resolve().as_posix()
    assert "someone" not in ui_display_path(project)
    assert "someone" not in ui_display_path(diagram)
    assert Path(expand_displayed_home("~/Documents/papers")).resolve() == project.resolve()

    roots = WorkspaceRoots([RootEntry(name="papers", path=project.resolve())])
    opened = roots.resolve_read("~/Documents/papers/note.txt")
    assert opened.path.resolve() == note.resolve()

    panel = WorkspacePanel()
    welcome = FirstRunDialog(project)
    tile = AttachmentTile(
        {
            "id": "1",
            "name": "shot.png",
            "path": "data/drops/shot.png",
            "source_path": str(shot),
            "kind": "other",
        }
    )
    settings = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "models": {"fast": "x", "research": "x", "vision": "x"},
            "workspace": {
                "named_roots": [
                    {"name": "papers", "path": str(project.resolve()), "read_only": False}
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        }
    )
    try:
        panel.set_projects(["papers"], "papers", paths={"papers": str(project.resolve())})
        panel.set_recent([str(shot.resolve())])
        qt_app.processEvents()
        visible = [
            panel.root_label.text(),
            panel.root_label.toolTip(),
            panel.project_combo.toolTip(),
            panel.console_cwd.text(),
            panel.console_cwd.toolTip(),
            panel.browse_label.text(),
            panel.browse_label.toolTip(),
            panel.recent_combo.itemText(1),
        ]
        for text in visible:
            assert "someone" not in text, text
        assert panel.project_combo.toolTip() == "~/Documents/papers"
        assert panel.root_label.toolTip() == "~/Documents/papers"
        assert panel.console_cwd.toolTip() == "~/Documents/papers"
        assert panel.console_cwd.text() == "papers"
        assert panel.browse_label.toolTip() == "~/Documents/papers"
        assert panel.browse_label.text() == "papers"
        assert panel.recent_combo.itemText(1) == "~/Documents/papers/shot.png"
        assert panel.recent_combo.itemData(1) == str(shot.resolve())

        panel.show_image(str(diagram))
        assert panel.path_edit.text() == "outputs/diagrams/diagram.png"
        assert "someone" not in panel.image_label.toolTip()

        panel.set_file("note.txt", "hi", abs_path=str(note))
        assert panel.root_label.toolTip() == "~/Documents/papers"
        assert "someone" not in panel.root_label.toolTip()

        panel._project_paths = {}
        panel.root_label.setToolTip("~/Documents/papers")
        assert Path(panel._dialog_start_dir()).resolve() == project.resolve()

        assert welcome._path_label.text() == "~/Documents/papers"
        assert welcome.root == project
        assert "someone" not in welcome._path_label.text()

        tip = tile.toolTip()
        assert tip == "data/drops/shot.png\nfrom ~/Documents/papers/shot.png"
        assert "someone" not in tip

        assert "someone" not in settings.roots_list.item(0).text()
        assert "~/Documents/papers" in settings.roots_list.item(0).text()
        settings.roots_list.setCurrentRow(0)
        qt_app.processEvents()
        assert settings.root_path.text() == "~/Documents/papers"
        settings._update_root()
        assert Path(settings._roots[0]["path"]).resolve() == project.resolve()
        assert "someone" not in settings.roots_list.item(0).text()
    finally:
        panel.deleteLater()
        welcome.deleteLater()
        tile.deleteLater()
        settings.deleteLater()
