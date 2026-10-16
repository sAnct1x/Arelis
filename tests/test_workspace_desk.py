"""Allow-card diffs, named project runs, and the workspace tile's search list."""

from __future__ import annotations

import json
from pathlib import Path

from arelis.tools.base import ToolRegistry
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.run_script import RunScriptTool
from arelis.tools.run_task import RunTaskTool
from arelis.workspace import WorkspaceRoots


def _roots(tmp_path: Path) -> WorkspaceRoots:
    return WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)


def test_edit_card_is_a_diff_and_flags_a_delete(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("keep\n", encoding="utf-8")
    tool = CodeWorkspaceTool(_roots(tmp_path))
    reg = ToolRegistry()
    reg.register(tool)
    text = reg.describe_call(
        "workspace",
        {
            "action": "edit",
            "path": "a.py",
            "old": "keep",
            "new": "import shutil\nshutil.rmtree('C:/Users')\n",
        },
    )
    assert "Delete-looking lines:" in text
    assert "rmtree" in text
    assert "+import shutil" in text


def test_run_script_card_says_the_process_is_you(tmp_path: Path) -> None:
    script = tmp_path / "probe.py"
    script.write_text("import shutil\nshutil.rmtree('C:/')\nprint(1)\n", encoding="utf-8")
    tool = RunScriptTool(_roots(tmp_path))
    reg = ToolRegistry()
    reg.register(tool)
    text = reg.describe_call("run_script", {"path": "probe.py", "args": ["--ok"]})
    assert "runs as you" in text
    assert "rmtree" in text
    assert "probe.py" in text
    assert '"--ok"' in text


def test_grep_hits_are_structured(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def needle():\n    return 1\n", encoding="utf-8")
    tool = CodeWorkspaceTool(_roots(tmp_path))

    import asyncio

    result = asyncio.run(tool.run(action="grep", query="needle"))
    assert result.ok
    hits = result.data["hits"]
    assert hits[0]["path"].endswith("a.py")
    assert hits[0]["line"] == 1
    assert "needle" in hits[0]["text"]


def test_run_task_refuses_a_shell_and_an_absolute_arg(tmp_path: Path) -> None:
    (tmp_path / "arelis-tasks.json").write_text(
        json.dumps(
            {
                "wipe": ["powershell", "-Command", "Remove-Item C:\\"],
                "hello": ["python", "-c", "print(1)"],
            }
        ),
        encoding="utf-8",
    )
    tool = RunTaskTool(_roots(tmp_path))

    import asyncio

    listed = asyncio.run(tool.run(action="list"))
    assert "wipe" not in listed.output
    assert "hello" in listed.data["tasks"]
    refused = asyncio.run(
        tool.run(action="run", name="hello", args=["C:/Windows/notepad.exe"])
    )
    assert not refused.ok
    assert "absolute" in refused.output


def test_model_written_script_card_shows_full_source(tmp_path: Path) -> None:
    """A script the model wrote stays on the card, hash and all.

    The programs toggle can hide a script the user already had. It cannot
    hide one the workspace tool just wrote, and the process runs the bytes
    the card hashed, not a later edit of the file.
    """
    import asyncio
    import hashlib

    from arelis.tools.policy import confirm_mode, set_confirm_mode

    (tmp_path / "helper_mod.py").write_text("N = 7\n", encoding="utf-8")
    lines = ["import math", "import helper_mod"]
    lines.extend(f"n_{i} = {i}" for i in range(1, 49))
    lines.append("print(helper_mod.N)")
    lines.append("print('HASHED_OK')")
    source = "\n".join(lines) + "\n"
    assert len(source.splitlines()) > 40

    roots = _roots(tmp_path)
    wrote = asyncio.run(
        CodeWorkspaceTool(roots).run(action="write", path="made.py", content=source)
    )
    assert wrote.ok, wrote.output
    script = tmp_path / "made.py"
    approved = script.read_bytes()
    (tmp_path / "user_owned.py").write_text("print('user')\n", encoding="utf-8")

    tool = RunScriptTool(roots)
    reg = ToolRegistry()
    reg.register(tool)
    previous = confirm_mode()
    set_confirm_mode("card")
    try:
        assert reg.needs_confirm("run_script", {"path": "made.py"}, confirm_run=False)
        assert reg.needs_confirm(
            "run_script",
            {"path": "made.py"},
            confirm_run=False,
            asked=True,
        )
        assert not reg.needs_confirm(
            "run_script",
            {"path": "user_owned.py"},
            confirm_run=False,
        )
    finally:
        set_confirm_mode(previous)

    text = reg.describe_call("run_script", {"path": "made.py"})
    digest = hashlib.sha256(approved).hexdigest()[:12]
    assert f"Source hash: {digest}" in text
    assert "Imports: math, helper_mod" in text
    assert "HASHED_OK" in text
    assert "more lines" not in text
    assert "\u2014" not in text

    script.write_text("print('MUTATED_NO')\n", encoding="utf-8")
    assert hashlib.sha256(script.read_bytes()).hexdigest()[:12] != digest
    first = asyncio.run(tool.run(path="made.py"))
    assert first.ok, first.output
    stdout = first.output.split("stdout:", 1)[-1]
    assert "HASHED_OK" in stdout
    assert "7" in stdout
    assert "MUTATED_NO" not in first.output

    second = asyncio.run(tool.run(path="made.py"))
    assert second.ok, second.output
    assert "MUTATED_NO" in second.output.split("stdout:", 1)[-1]
    assert "HASHED_OK" not in second.output
    assert list(tmp_path.glob(".arelis-src-*")) == []


def test_npm_script_body_is_on_the_card(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"clean": "Remove-Item -Recurse C:\\Users"}}),
        encoding="utf-8",
    )
    tool = RunTaskTool(_roots(tmp_path))
    text = tool.confirm_detail({"action": "run", "name": "clean"})
    assert "Remove-Item" in text
    assert "runs as you" in text
    assert "Delete-looking lines:" in text


