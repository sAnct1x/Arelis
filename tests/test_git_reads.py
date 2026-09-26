"""Read-only git_info verbs: branch, stash (list), blame, show.

These stay out of _WRITE_ACTIONS — only stage and commit are writes. Tests
here pin that allow-list and drive GitInfoTool.run against a real temp repo so
a mutation (stash apply as a write, branch via shell=True) fails loudly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from arelis.tools.git_info import _WRITE_ACTIONS, GitInfoTool
from arelis.tools.policy import GIT_WRITE_ACTIONS, action_is_write


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
    (root / "README.md").write_text("first line\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "initial"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "checkout", "-q", "-b", "feature"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("second line\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "stash", "push", "-m", "wip readme"],
        check=True,
        capture_output=True,
    )
    return root


def test_write_actions_stay_stage_and_commit_only() -> None:
    """Roadmap 4.3: widening _WRITE_ACTIONS is a deliberate regression."""
    assert _WRITE_ACTIONS == frozenset({"stage", "commit"})
    assert GIT_WRITE_ACTIONS == frozenset({"stage", "commit"})


@pytest.mark.parametrize(
    "action",
    ["branch", "stash", "blame", "show", "status", "diff", "log"],
)
def test_read_actions_are_not_writes(action: str) -> None:
    assert action_is_write("git_info", {"action": action}) is False


@pytest.mark.asyncio
async def test_branch_lists_locals_with_current_marked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="branch")
    assert result.ok, result.output
    assert "feature" in result.output
    assert "*" in result.output


@pytest.mark.asyncio
async def test_stash_lists_entries(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="stash")
    assert result.ok, result.output
    assert "wip readme" in result.output


@pytest.mark.parametrize("action", ["stash_apply", "stash_pop", "stash_drop", "stash_push"])
@pytest.mark.asyncio
async def test_stash_mutations_stay_refused(tmp_path: Path, action: str) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action=action)
    assert not result.ok
    assert "list-only" in result.output.lower()
    assert action not in _WRITE_ACTIONS


@pytest.mark.asyncio
async def test_blame_needs_a_path(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="blame")
    assert not result.ok
    assert "path" in result.output.lower()


@pytest.mark.asyncio
async def test_blame_annotates_a_file(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="blame", path="README.md")
    assert result.ok, result.output
    assert "initial" in result.output or "Test" in result.output


@pytest.mark.asyncio
async def test_show_defaults_to_head(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="show")
    assert result.ok, result.output
    assert "initial" in result.output


@pytest.mark.asyncio
async def test_show_takes_an_explicit_rev(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="show", rev="HEAD~0")
    assert result.ok, result.output
    assert "initial" in result.output


@pytest.mark.asyncio
async def test_read_git_calls_use_argv_lists_not_shell(tmp_path: Path) -> None:
    """branch must not become shell=True or a single command string."""
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])
    seen: list[list[str]] = []

    real_run = subprocess.run

    def capture(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)):
            seen.append(list(cmd))
        return real_run(cmd, **kwargs)

    with patch("arelis.tools.git_info.subprocess.run", side_effect=capture):
        await tool.run(action="branch")
        await tool.run(action="stash")
        await tool.run(action="blame", path="README.md")
        await tool.run(action="show")

    assert seen, "expected subprocess.run to be called"
    for cmd in seen:
        assert isinstance(cmd, list)
        assert cmd[0] == "git"
    assert any("branch" in cmd for cmd in seen)
    assert any(cmd[-2:] == ["stash", "list"] for cmd in seen)
    assert any("blame" in cmd for cmd in seen)
    assert any("show" in cmd for cmd in seen)
