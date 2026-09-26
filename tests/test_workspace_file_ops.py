"""Rearranging files is where the workspace tool ran out of verbs.

`workspace` shipped with list / read / write / edit / keep. "Delete that",
"rename this", "move it into notes/" had no action, so a file-management ask
dead-ended after she had already found the file.

tools/policy.py was written expecting this: WORKSPACE_WRITE_ACTIONS has
carried "delete" and "remove" and DELETE_ACTIONS["workspace"] has marked them
destructive the whole time. The gate existed and the verbs never arrived.

Safety posture, all enforced below:

  Every path goes through resolve(for_write=True), which contains to allowed
  roots, rejects read-only roots, and — unlike resolve_read — never honours a
  session external-read grant. Reading a granted file must not become licence
  to delete it.

  No recursive delete. A non-empty directory is refused. Emptying a tree is
  the one mistake with no undo, and the model does not get a verb for it.

  No silent overwrite on move/copy. Clobbering a file the user did not name
  is a destructive act wearing a write's clothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.policy import (
    DELETE_ACTIONS,
    WORKSPACE_WRITE_ACTIONS,
    action_is_destructive,
    action_is_write,
)


def test_the_gate_already_expected_these_verbs() -> None:
    assert {"delete", "remove"} <= WORKSPACE_WRITE_ACTIONS
    assert {"delete", "remove"} <= DELETE_ACTIONS["workspace"]
    assert action_is_write("workspace", {"action": "delete"}) is True
    assert action_is_destructive("workspace", {"action": "delete"}) is True
    # Rearranging is a write, but it is not the one you cannot walk back.
    assert action_is_write("workspace", {"action": "move"}) is True
    assert action_is_destructive("workspace", {"action": "move"}) is False


@pytest.mark.asyncio
async def test_a_file_can_be_deleted(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    target = tmp_path / "scratch.txt"
    target.write_text("junk", encoding="utf-8")

    result = await tool.run(action="delete", path="scratch.txt")
    assert result.ok
    assert not target.exists()


@pytest.mark.asyncio
async def test_deleting_something_that_is_not_there_says_so(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    result = await tool.run(action="delete", path="ghost.txt")
    assert not result.ok
    assert "ghost.txt" in result.output


@pytest.mark.asyncio
async def test_an_empty_directory_can_go(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "emptied").mkdir()

    result = await tool.run(action="delete", path="emptied")
    assert result.ok
    assert not (tmp_path / "emptied").exists()


@pytest.mark.asyncio
async def test_a_full_directory_is_refused(tmp_path: Path) -> None:
    """The one mistake with no undo. She does not get a verb for it."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    keep = tmp_path / "project"
    keep.mkdir()
    (keep / "important.txt").write_text("a year of work", encoding="utf-8")

    result = await tool.run(action="delete", path="project")
    assert not result.ok
    assert "not empty" in result.output.lower()
    assert (keep / "important.txt").exists()


@pytest.mark.asyncio
async def test_delete_cannot_reach_outside_the_roots(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "precious.txt"
    victim.write_text("not yours", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()

    tool = CodeWorkspaceTool([str(root)])
    result = await tool.run(action="delete", path=str(victim))
    assert not result.ok
    assert victim.exists()


@pytest.mark.asyncio
async def test_a_read_grant_is_not_a_licence_to_delete(tmp_path: Path) -> None:
    """resolve_read honours external grants. Deletes must use resolve, not that."""
    outside = tmp_path / "outside"
    outside.mkdir()
    granted = outside / "opened.txt"
    granted.write_text("they only opened it", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()

    tool = CodeWorkspaceTool([str(root)])
    tool.workspace.grant_external_read(granted)

    readable = await tool.run(action="read", path=str(granted))
    assert readable.ok, "precondition: the grant makes it readable"

    result = await tool.run(action="delete", path=str(granted))
    assert not result.ok
    assert granted.exists()


@pytest.mark.asyncio
async def test_a_file_can_be_renamed(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "draft.md").write_text("body", encoding="utf-8")

    result = await tool.run(action="rename", path="draft.md", to="final.md")
    assert result.ok
    assert not (tmp_path / "draft.md").exists()
    assert (tmp_path / "final.md").read_text(encoding="utf-8") == "body"


@pytest.mark.asyncio
async def test_a_file_can_be_moved_into_a_folder_that_does_not_exist_yet(
    tmp_path: Path,
) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "loose.md").write_text("body", encoding="utf-8")

    result = await tool.run(action="move", path="loose.md", to="notes/loose.md")
    assert result.ok
    assert (tmp_path / "notes" / "loose.md").read_text(encoding="utf-8") == "body"


@pytest.mark.asyncio
async def test_a_file_can_be_copied_and_the_original_stays(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "template.md").write_text("body", encoding="utf-8")

    result = await tool.run(action="copy", path="template.md", to="copy.md")
    assert result.ok
    assert (tmp_path / "template.md").exists()
    assert (tmp_path / "copy.md").read_text(encoding="utf-8") == "body"


@pytest.mark.asyncio
async def test_move_will_not_quietly_clobber(tmp_path: Path) -> None:
    """An overwrite the user did not name is a delete wearing a write's clothes."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "a.md").write_text("new", encoding="utf-8")
    (tmp_path / "b.md").write_text("existing work", encoding="utf-8")

    result = await tool.run(action="move", path="a.md", to="b.md")
    assert not result.ok
    assert (tmp_path / "b.md").read_text(encoding="utf-8") == "existing work"
    assert (tmp_path / "a.md").exists(), "a refused move must not consume the source"


@pytest.mark.asyncio
async def test_copy_will_not_quietly_clobber(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "a.md").write_text("new", encoding="utf-8")
    (tmp_path / "b.md").write_text("existing work", encoding="utf-8")

    result = await tool.run(action="copy", path="a.md", to="b.md")
    assert not result.ok
    assert (tmp_path / "b.md").read_text(encoding="utf-8") == "existing work"


@pytest.mark.asyncio
async def test_move_cannot_smuggle_a_file_out_of_the_sandbox(tmp_path: Path) -> None:
    """Containment has to hold on the destination, not just the source."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "secret.txt").write_text("stays inside", encoding="utf-8")

    tool = CodeWorkspaceTool([str(root)])
    result = await tool.run(
        action="move", path="secret.txt", to=str(outside / "leaked.txt")
    )
    assert not result.ok
    assert not (outside / "leaked.txt").exists()
    assert (root / "secret.txt").exists()


@pytest.mark.asyncio
async def test_move_needs_a_destination(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "a.md").write_text("body", encoding="utf-8")

    result = await tool.run(action="move", path="a.md")
    assert not result.ok
    assert "to" in result.output.lower()
