"""workspace could not answer "where is X defined?" — roadmap 4.2.

The roadmap entry is precise about why this one is worse than a plain missing
verb: *"Find where X is defined is impossible without listing every folder,
which the same-call guard then blocks."* The tool had `list` and `read` and
nothing else, so the only route to a file whose path she did not already know
was to walk the tree one `list` at a time — and `same_call` stops repeating the
same tool, correctly, because from the outside that looks like a model stuck in
a loop. The guard layer was fighting a missing capability rather than a
misbehaving model, which is the most expensive kind of gap in this codebase.

Two actions, because the two questions are different. `find` matches file
*names* ("where is drive.py"). `grep` matches file *contents* ("where is
apply_filament_desk defined"). Both are reads and need no confirm.

The skip list and the caps are the load-bearing parts. A grep that walks
`.git`, `node_modules` and `_pages/*.png` returns garbage slowly, and a tool
that reads a 400 MB file into memory on the GUI thread's behalf is a hang.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.workspace import RootEntry, WorkspaceRoots


def _tree(tmp_path: Path) -> CodeWorkspaceTool:
    root = tmp_path / "proj"
    (root / "arelis" / "ui").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "arelis" / "ui" / "drive.py").write_text(
        "def apply_filament_desk(window):\n    return window\n",
        encoding="utf-8",
    )
    (root / "arelis" / "core.py").write_text(
        "from arelis.ui.drive import apply_filament_desk\n\nAPPLY = apply_filament_desk\n",
        encoding="utf-8",
    )
    (root / "docs" / "notes.md").write_text(
        "The desk calls apply_filament_desk on mount.\n", encoding="utf-8"
    )
    # Noise that must never appear in results.
    (root / ".git").mkdir()
    (root / ".git" / "COMMIT_EDITMSG").write_text("apply_filament_desk\n", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text(
        "apply_filament_desk\n", encoding="utf-8"
    )
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "core.cpython-311.pyc").write_bytes(b"\x00\x01apply_filament_desk\x00")
    return CodeWorkspaceTool(WorkspaceRoots([RootEntry(name="proj", path=root.resolve())]))


@pytest.mark.asyncio
async def test_grep_finds_the_definition_across_folders(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="def apply_filament_desk")

    assert result.ok, result.output
    assert "drive.py" in result.output
    assert ":1:" in result.output, "no line number, so she cannot cite it"


@pytest.mark.asyncio
async def test_grep_reports_every_place_it_is_used(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="apply_filament_desk")

    assert result.ok, result.output
    for expected in ("drive.py", "core.py", "notes.md"):
        assert expected in result.output, f"missed {expected}"


@pytest.mark.asyncio
async def test_the_junk_folders_are_never_walked(tmp_path: Path) -> None:
    """.git and node_modules would bury the real answer and be slow doing it."""
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="apply_filament_desk")

    assert ".git" not in result.output
    assert "node_modules" not in result.output
    assert "COMMIT_EDITMSG" not in result.output
    assert ".pyc" not in result.output


@pytest.mark.asyncio
async def test_a_glob_narrows_the_search(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="apply_filament_desk", glob="*.md")

    assert result.ok, result.output
    assert "notes.md" in result.output
    assert "drive.py" not in result.output


@pytest.mark.asyncio
async def test_a_binary_file_is_skipped_not_dumped(tmp_path: Path) -> None:
    tool = _tree(tmp_path)
    root = Path(tool.roots[0])
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00needle\x00\x00")

    result = await tool.run(action="grep", query="needle")

    assert "logo.png" not in result.output


@pytest.mark.asyncio
async def test_a_miss_says_so_instead_of_looking_like_a_failure(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="zzz_not_here_zzz")

    assert result.ok, "a search that found nothing is not a broken search"
    assert "no match" in result.output.lower()


@pytest.mark.asyncio
async def test_grep_needs_something_to_search_for(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="   ")

    assert not result.ok
    assert "query" in result.output.lower()


@pytest.mark.asyncio
async def test_regex_is_opt_in_so_punctuation_is_literal(tmp_path: Path) -> None:
    """ "APPLY = apply_filament_desk" contains no regex; searching it must work."""
    tool = _tree(tmp_path)

    literal = await tool.run(action="grep", query="APPLY = apply_filament_desk")
    assert literal.ok and "core.py" in literal.output

    as_regex = await tool.run(action="grep", query=r"^APPLY\s*=", regex=True)
    assert as_regex.ok and "core.py" in as_regex.output


@pytest.mark.asyncio
async def test_a_broken_regex_is_a_message_not_a_traceback(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="apply(", regex=True)

    assert not result.ok
    assert "regex" in result.output.lower()


@pytest.mark.asyncio
async def test_results_are_capped(tmp_path: Path) -> None:
    tool = _tree(tmp_path)
    root = Path(tool.roots[0])
    big = root / "many.txt"
    big.write_text("needle\n" * 500, encoding="utf-8")

    result = await tool.run(action="grep", query="needle", max_results=5)

    assert result.ok
    assert len([ln for ln in result.output.splitlines() if ":" in ln]) <= 6
    # A clipped list the model reads as complete is worse than no answer: it
    # will say "used in 5 places" about a symbol used in 500.
    assert "stopped at" in result.output.lower(), "truncation was silent"
    assert result.data["truncated"] is True


@pytest.mark.asyncio
async def test_find_locates_a_file_by_name(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="find", query="drive")

    assert result.ok, result.output
    assert "drive.py" in result.output
    assert "core.py" not in result.output


@pytest.mark.asyncio
async def test_find_takes_a_glob_too(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="find", glob="*.md")

    assert result.ok, result.output
    assert "notes.md" in result.output
    assert "drive.py" not in result.output


@pytest.mark.asyncio
async def test_search_cannot_escape_the_roots(tmp_path: Path) -> None:
    """The whole tool is a sandbox; a search that walks up defeats it."""
    tool = _tree(tmp_path)
    (tmp_path / "outside.txt").write_text("needle\n", encoding="utf-8")

    result = await tool.run(action="grep", query="needle", path="../..")

    assert not result.ok or "outside.txt" not in result.output


@pytest.mark.asyncio
async def test_a_subtree_can_be_named(tmp_path: Path) -> None:
    tool = _tree(tmp_path)

    result = await tool.run(action="grep", query="apply_filament_desk", path="docs")

    assert result.ok, result.output
    assert "notes.md" in result.output
    assert "drive.py" not in result.output


def test_the_schema_and_description_offer_the_new_actions() -> None:
    actions = CodeWorkspaceTool.parameters_schema["properties"]["action"]["enum"]
    assert "grep" in actions
    assert "find" in actions
    props = CodeWorkspaceTool.parameters_schema["properties"]
    for key in ("query", "glob", "regex", "max_results"):
        assert key in props, f"{key} is not offered to the model"
    assert "grep" in CodeWorkspaceTool.description


def test_search_is_not_a_write(tmp_path: Path) -> None:
    """grep must not raise the Allow card; it reads."""
    from arelis.tools.policy import action_is_write

    assert not action_is_write("workspace", {"action": "grep", "query": "x"})
    assert not action_is_write("workspace", {"action": "find", "query": "x"})
    assert action_is_write("workspace", {"action": "write", "path": "a", "content": "b"})
