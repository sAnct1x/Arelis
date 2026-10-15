"""notes tool: add/list/search/read against a real temp workspace.

Roadmap 5.2. keep this: already writes via desk.write_note with no tool
behind it. This file drives NotesTool.run — a helper that looks right
while add never touches disk is the bug.

Mutants this file is supposed to catch:

1. add that does not write a file (or invents a second store and skips
   write_note — no Kept footer, no desk row).
2. search that only matches titles (body-only token must hit).
3. path escape (`../`) on read — must refuse, must not open a sibling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.desk import DeskStore
from arelis.tools.notes import NotesTool
from arelis.workspace import RootEntry, WorkspaceRoots


def _workspace(tmp_path: Path) -> tuple[WorkspaceRoots, Path]:
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return workspace, project


def _tool(tmp_path: Path) -> tuple[NotesTool, Path, DeskStore]:
    workspace, project = _workspace(tmp_path)
    store = DeskStore(path=tmp_path / "desk.json")
    return NotesTool(workspace, store=store), project, store


def _write_outside(project: Path, name: str, body: str) -> Path:
    target = project / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


@pytest.mark.asyncio
async def test_add_writes_a_file_through_write_note(tmp_path: Path) -> None:
    """Mutant: add records a path and never creates the markdown page."""
    tool, project, store = _tool(tmp_path)
    added = await tool.run(
        action="add",
        title="spare key",
        text="the spare key is under the planter",
    )
    assert added.ok, added.output
    notes = list((project / "notes").glob("*.md"))
    assert notes, "add must write a file under the project's notes/"
    page = notes[0].read_text(encoding="utf-8")
    assert "the spare key is under the planter" in page
    assert page.lstrip().startswith("# ")
    assert "Kept " in page
    assert added.data["abs_path"] == str(notes[0])
    assert Path(added.data["abs_path"]).is_file()
    desk = store.list_for()
    assert desk, "write_note must put the page on the desk"
    assert desk[0].kind == "note"
    assert Path(desk[0].abs_path).is_file()


@pytest.mark.asyncio
async def test_list_shows_title_date_and_path(tmp_path: Path) -> None:
    tool, _project, _store = _tool(tmp_path)
    added = await tool.run(
        action="add", title="lab hours", text="doors lock at 9"
    )
    assert added.ok
    listed = await tool.run(action="list")
    assert listed.ok
    assert listed.data["notes"], "list returned no rows"
    row = listed.data["notes"][0]
    assert row["title"] == "lab hours"
    assert row["date"]
    assert row["path"].startswith("notes/")
    assert row["path"].endswith(".md")
    assert "lab hours" in listed.output
    assert row["date"] in listed.output
    assert row["path"] in listed.output


@pytest.mark.asyncio
async def test_read_refuses_path_escape(tmp_path: Path) -> None:
    """Mutant: `../` is joined and a sibling file is returned."""
    tool, project, _store = _tool(tmp_path)
    secret = _write_outside(
        project, "secret.md", "do not leak the vault code 9911"
    )
    planted = project.parent / "outside.md"
    planted.write_text("drive-level secret 7733", encoding="utf-8")
    added = await tool.run(action="add", title="safe", text="this stays inside")
    assert added.ok

    for raw in (
        "../secret.md",
        r"..\secret.md",
        "notes/../secret.md",
        "notes/../../outside.md",
        str(secret),
        str(planted),
    ):
        result = await tool.run(action="read", path=raw)
        assert not result.ok, f"escape must fail for {raw!r}: {result.output}"
        assert "9911" not in result.output
        assert "7733" not in result.output

    listed = await tool.run(action="list")
    assert listed.ok
    paths = [row["abs_path"] for row in listed.data["notes"]]
    assert str(secret.resolve()) not in paths
    assert str(planted.resolve()) not in paths

    leaked = await tool.run(action="search", query="vault code 9911")
    assert leaked.ok
    assert leaked.data["notes"] == []
    assert "do not leak" not in leaked.output.casefold()


