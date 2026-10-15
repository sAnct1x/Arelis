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


