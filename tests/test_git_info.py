"""Read-only git_info tool — temp repo fixture, no mutate actions."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.git_info import GitInfoTool
from arelis.workspace import WorkspaceRoots

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not on PATH"
)


def _git(cwd: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_AUTHOR_NAME", "Arelis Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "arelis-test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Arelis Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "arelis-test@example.com")
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    # -b main needs git >= 2.28; Arelis targets current desktop git.
    _git(root, "init", "-b", "main")
    (root / "readme.txt").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "readme.txt")
    _git(root, "commit", "-m", "initial")
    return root.resolve()


@pytest.mark.asyncio
async def test_status_clean(git_repo: Path) -> None:
    tool = GitInfoTool([str(git_repo)])
    result = await tool.run(action="status")
    assert result.ok
    assert "main" in result.output or "##" in result.output
    assert result.data["action"] == "status"
    # git_repo fixture already returns a resolved Path; compare as strings.
    assert result.data["repo"] == str(git_repo)


@pytest.mark.asyncio
async def test_status_lists_dirty_file(git_repo: Path) -> None:
    (git_repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    tool = GitInfoTool([str(git_repo)])
    result = await tool.run(action="status")
    assert result.ok
    assert "dirty.txt" in result.output


@pytest.mark.asyncio
async def test_diff_and_log(git_repo: Path) -> None:
    (git_repo / "readme.txt").write_text("hello\nchanged\n", encoding="utf-8")
    tool = GitInfoTool([str(git_repo)])
    diff = await tool.run(action="diff")
    assert diff.ok
    assert "changed" in diff.output or "readme.txt" in diff.output

    log = await tool.run(action="log", n=5)
    assert log.ok
    assert "initial" in log.output


@pytest.mark.asyncio
async def test_rejects_non_git_workspace(tmp_path: Path) -> None:
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    tool = GitInfoTool([str(bare)])
    result = await tool.run(action="status")
    assert not result.ok
    assert "not a git" in result.output.lower()


@pytest.mark.asyncio
async def test_rejects_forbidden_action(git_repo: Path) -> None:
    tool = GitInfoTool([str(git_repo)])
    for action in ("commit", "push", "reset", "checkout"):
        result = await tool.run(action=action)
        assert not result.ok
        assert "forbidden" in result.output.lower() or "unknown" in result.output.lower()


@pytest.mark.asyncio
async def test_output_size_capped(git_repo: Path) -> None:
    (git_repo / "big.txt").write_text("line\n" * 2000, encoding="utf-8")
    _git(git_repo, "add", "big.txt")
    tool = GitInfoTool([str(git_repo)])
    result = await tool.run(action="diff", max_chars=400)
    assert result.ok
    assert len(result.output) <= 400 + len("\n\n[truncated to 400 chars]")
    assert "truncated" in result.output


def test_git_info_registered_and_no_confirm(git_repo: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(git_repo)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("git_info") is not None
    assert not registry.needs_confirm("git_info", {"action": "status"})
    assert not registry.needs_confirm("git_info", {"action": "diff"})
    assert not registry.needs_confirm("git_info", {"action": "log"})
