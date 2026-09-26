"""workspace edit is old→new. Code changes arrive as a unified diff.

Phase 5.5. The applier is in-process and strict: exact context, no fuzz,
no `patch` exe, no `git apply`. Paths come from the +++ / --- headers and
still have to survive resolve(for_write) / for_create — the same gate as
every other write. A mid-diff failure must not leave the first file patched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.policy import WORKSPACE_WRITE_ACTIONS, action_is_destructive, action_is_write


def _udiff(path: str, old: str, new: str) -> str:
    """One-line file, one hunk. Enough to exercise apply without a library."""
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def test_patch_and_apply_hit_the_confirm_table() -> None:
    assert {"patch", "apply"} <= WORKSPACE_WRITE_ACTIONS
    assert action_is_write("workspace", {"action": "patch"}) is True
    assert action_is_write("workspace", {"action": "apply"}) is True
    # A patch is a write, not the one you cannot walk back.
    assert action_is_destructive("workspace", {"action": "patch"}) is False


@pytest.mark.asyncio
async def test_patch_applies_a_real_unified_diff(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    target = tmp_path / "hello.py"
    target.write_text("return 1\n", encoding="utf-8")

    result = await tool.run(
        action="patch",
        diff=_udiff("hello.py", "return 1", "return 2"),
    )
    assert result.ok, result.output
    assert target.read_text(encoding="utf-8") == "return 2\n"


@pytest.mark.asyncio
async def test_apply_and_content_args_also_land(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    via_apply = await tool.run(
        action="apply",
        patch=_udiff("a.txt", "old", "via-apply"),
    )
    assert via_apply.ok, via_apply.output
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "via-apply\n"

    via_content = await tool.run(
        action="patch",
        content=_udiff("a.txt", "via-apply", "via-content"),
    )
    assert via_content.ok, via_content.output
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "via-content\n"


@pytest.mark.asyncio
async def test_empty_diff_is_ok(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "stays.txt").write_text("same\n", encoding="utf-8")

    result = await tool.run(action="patch", diff="")
    assert result.ok
    assert (tmp_path / "stays.txt").read_text(encoding="utf-8") == "same\n"


@pytest.mark.asyncio
async def test_mismatched_context_does_not_apply(tmp_path: Path) -> None:
    """Mutant: skip the context check and the hunk still lands."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    target = tmp_path / "note.txt"
    target.write_text("alpha\n", encoding="utf-8")

    result = await tool.run(
        action="patch",
        diff=_udiff("note.txt", "not-what-is-there", "beta"),
    )
    assert not result.ok
    assert "context" in result.output.lower()
    assert target.read_text(encoding="utf-8") == "alpha\n"


@pytest.mark.asyncio
async def test_dotdot_in_plus_path_does_not_escape(tmp_path: Path) -> None:
    """Mutant: join the +++ path and `../` writes outside the root."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.txt").write_text("hello\n", encoding="utf-8")
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")

    tool = CodeWorkspaceTool([str(root)])
    diff = (
        "--- a/inside.txt\n"
        "+++ b/../victim.txt\n"
        "@@ -1 +1 @@\n"
        "-hello\n"
        "+pwned\n"
    )
    result = await tool.run(action="patch", diff=diff)
    assert not result.ok
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    assert (root / "inside.txt").read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "pwned").exists()


@pytest.mark.asyncio
async def test_second_file_failure_does_not_half_apply(tmp_path: Path) -> None:
    """Mutant: write as you go and file one is already patched when file two dies."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    one = tmp_path / "one.py"
    two = tmp_path / "two.py"
    one.write_text("aaa\n", encoding="utf-8")
    two.write_text("bbb\n", encoding="utf-8")

    diff = (
        _udiff("one.py", "aaa", "AAA")
        + _udiff("two.py", "XXX", "BBB")
    )
    result = await tool.run(action="patch", diff=diff)
    assert not result.ok
    assert one.read_text(encoding="utf-8") == "aaa\n"
    assert two.read_text(encoding="utf-8") == "bbb\n"


@pytest.mark.asyncio
async def test_missing_file_is_refused_unless_dev_null_add(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    missing = await tool.run(
        action="patch",
        diff=_udiff("ghost.py", "old", "new"),
    )
    assert not missing.ok

    created = await tool.run(
        action="patch",
        diff=(
            "--- /dev/null\n"
            "+++ b/born.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world\n"
        ),
    )
    assert created.ok, created.output
    assert (tmp_path / "born.py").read_text(encoding="utf-8") == "hello\nworld\n"


@pytest.mark.asyncio
async def test_binary_diff_is_refused(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    (tmp_path / "x.bin").write_text("not-bin-text\n", encoding="utf-8")
    result = await tool.run(
        action="patch",
        diff="Binary files a/x.bin and b/x.bin differ\n",
    )
    assert not result.ok
    assert "binary" in result.output.lower()
    assert (tmp_path / "x.bin").read_text(encoding="utf-8") == "not-bin-text\n"


@pytest.mark.asyncio
async def test_patch_requires_a_diff(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    result = await tool.run(action="patch")
    assert not result.ok
    assert "diff" in result.output.lower()
