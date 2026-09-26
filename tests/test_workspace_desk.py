"""Allow-card diffs, named project runs, and the workspace tile's search list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_write_card_marks_a_new_file(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool(_roots(tmp_path))
    text = tool.confirm_detail(
        {"action": "write", "path": "note.txt", "content": "hello\n"}
    )
    assert "New file." in text
    assert "+hello" in text


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


@pytest.mark.asyncio
async def test_run_task_prints_from_a_declared_argv(tmp_path: Path) -> None:
    (tmp_path / "arelis-tasks.json").write_text(
        json.dumps({"hello": ["python", "-c", "print(42)"]}),
        encoding="utf-8",
    )
    tool = RunTaskTool(_roots(tmp_path))
    listed = await tool.run(action="list")
    assert listed.ok
    assert "hello" in listed.data["tasks"]
    result = await tool.run(action="run", name="hello")
    assert result.ok
    assert "42" in result.output
    assert result.data["cwd"] == str(tmp_path.resolve())


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


def test_pytest_is_offered_when_tests_exist(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    tool = RunTaskTool(_roots(tmp_path))
    text = tool.confirm_detail({"action": "run", "name": "pytest", "args": ["-q"]})
    assert "pytest" in text
    assert "-q" in text
    assert "runs as you" in text


def test_search_hit_opens_that_line(qt_app) -> None:
    from arelis.ui.panels.workspace import WorkspacePanel

    panel = WorkspacePanel()
    got: list[tuple[str, int]] = []
    panel.open_line_requested.connect(lambda path, line: got.append((path, line)))
    panel.show_search_hits([{"path": "a.py", "line": 12, "text": "def foo"}])
    assert not panel.search_list.isHidden()
    panel._on_search_hit(panel.search_list.item(0))
    assert got == [("a.py", 12)]
    panel.set_file("a.py", "one\ntwo\nthree\n", abs_path=str(Path("a.py")))
    panel.reveal_line(2)
    assert panel.editor.textCursor().blockNumber() == 1


def test_console_submit_is_only_the_typed_line(qt_app) -> None:
    from arelis.ui.panels.workspace import WorkspacePanel

    panel = WorkspacePanel()
    got: list[str] = []
    panel.console_submit.connect(got.append)
    panel.console_edit.setText("Get-ChildItem")
    panel._submit_console()
    assert got == ["Get-ChildItem"]
    panel.set_console_busy(True)
    stopped: list[bool] = []
    panel.console_stop_requested.connect(lambda: stopped.append(True))
    panel._submit_console()
    assert stopped == [True]
    assert got == ["Get-ChildItem"]
