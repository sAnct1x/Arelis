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


