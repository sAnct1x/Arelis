"""She can see the repo is dirty and cannot do the one thing that follows.

`git_info` shipped read-only: status, diff, log. "Commit this" always stopped
at the diff, which was second in a census of all 43 tools for "starts the task
but cannot finish it".

The scope here is deliberately narrow, and the narrowness is the point.
Staging and committing are additive and recoverable — the objects stay in the
repo and a bad commit can be amended, reverted, or reset by hand. Push,
reset, clean, checkout and anything that rewrites history are not recoverable
from inside a chat turn, so they stay refused, and the refusals are tested
rather than assumed.

Both new actions are writes: they raise the confirm card, so every commit is
a thing the user clicked Allow on with the message in front of them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arelis.tools.git_info import GitInfoTool
from arelis.tools.policy import action_is_destructive, action_is_write


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    for args in (
        ("init", "-q"),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "Test"),
        ("config", "commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / "README.md").write_text("first\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    return root


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _log(root: Path) -> str:
    return _git(root, "log", "--oneline")


def test_committing_is_a_write_but_not_a_delete() -> None:
    assert action_is_write("git_info", {"action": "commit"}) is True
    assert action_is_write("git_info", {"action": "stage"}) is True
    assert action_is_write("git_info", {"action": "status"}) is False
    # Additive. Not the thing you cannot walk back.
    assert action_is_destructive("git_info", {"action": "commit"}) is False


@pytest.mark.asyncio
async def test_a_change_can_be_staged_and_committed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "README.md").write_text("second\n", encoding="utf-8")
    tool = GitInfoTool([str(root)])

    staged = await tool.run(action="stage")
    assert staged.ok, staged.output

    committed = await tool.run(action="commit", message="Update the readme")
    assert committed.ok, committed.output
    assert "Update the readme" in _log(root)


@pytest.mark.asyncio
async def test_a_commit_needs_a_message(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "README.md").write_text("second\n", encoding="utf-8")
    tool = GitInfoTool([str(root)])
    await tool.run(action="stage")

    result = await tool.run(action="commit")
    assert not result.ok
    assert "message" in result.output.lower()
    assert "Update" not in _log(root)


@pytest.mark.asyncio
async def test_committing_nothing_says_so_instead_of_claiming_success(
    tmp_path: Path,
) -> None:
    """git exits non-zero on an empty commit. She must not report one anyway."""
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="commit", message="Nothing to see")
    assert not result.ok
    assert "Nothing to see" not in _log(root)


@pytest.mark.asyncio
async def test_staging_can_be_scoped_to_one_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "README.md").write_text("second\n", encoding="utf-8")
    (root / "other.txt").write_text("untouched\n", encoding="utf-8")
    tool = GitInfoTool([str(root)])

    await tool.run(action="stage", path="README.md")
    await tool.run(action="commit", message="Only the readme")

    listed = _git(root, "status", "--porcelain")
    assert "other.txt" in listed, "the unnamed file must not have been swept in"


@pytest.mark.parametrize(
    "action",
    ["push", "reset", "clean", "checkout", "rebase", "merge", "branch", "config"],
)
@pytest.mark.asyncio
async def test_the_dangerous_verbs_stay_refused(tmp_path: Path, action: str) -> None:
    """Not recoverable from inside a chat turn. The allow-list is the whole design."""
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action=action, message="x")
    assert not result.ok
    assert action in result.output


@pytest.mark.asyncio
async def test_a_refused_verb_cannot_be_smuggled_through_the_message(
    tmp_path: Path,
) -> None:
    """The message is an argument to git, never a fragment of the command line."""
    root = _repo(tmp_path)
    (root / "README.md").write_text("second\n", encoding="utf-8")
    tool = GitInfoTool([str(root)])
    await tool.run(action="stage")

    result = await tool.run(
        action="commit", message="done\"; git push --force; echo \""
    )
    assert result.ok, result.output
    # It landed as a commit subject, not as a second command.
    assert "git push" in _log(root)
    assert not _git(root, "remote").strip(), (
        "the test repo has no remote; nothing could have been pushed"
    )


@pytest.mark.asyncio
async def test_commit_cannot_reach_a_repo_outside_the_roots(tmp_path: Path) -> None:
    outside = _repo(tmp_path / "elsewhere")
    root = tmp_path / "root"
    root.mkdir()
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="stage", path=str(outside))
    assert not result.ok
