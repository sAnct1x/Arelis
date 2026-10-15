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


@pytest.mark.asyncio
async def test_branch_lists_locals_with_current_marked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action="branch")
    assert result.ok, result.output
    assert "feature" in result.output
    assert "*" in result.output


@pytest.mark.parametrize("action", ['stash_apply', 'stash_pop'])
@pytest.mark.asyncio
async def test_stash_mutations_stay_refused(tmp_path: Path, action: str) -> None:
    root = _repo(tmp_path)
    tool = GitInfoTool([str(root)])

    result = await tool.run(action=action)
    assert not result.ok
    assert "list-only" in result.output.lower()
    assert action not in _WRITE_ACTIONS


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
