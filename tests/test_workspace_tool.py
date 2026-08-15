import pytest

from arelis.tools.code_workspace import CodeWorkspaceTool


@pytest.mark.asyncio
async def test_workspace_write_read(tmp_path):
    tool = CodeWorkspaceTool([str(tmp_path)])
    target = tmp_path / "note.txt"
    w = await tool.run(action="write", path=str(target), content="hello arelis")
    assert w.ok
    r = await tool.run(action="read", path=str(target))
    assert r.ok
    assert "hello arelis" in r.output


@pytest.mark.asyncio
async def test_workspace_list_edit_and_python_file(tmp_path):
    tool = CodeWorkspaceTool([str(tmp_path)])
    py = tmp_path / "hello.py"
    written = await tool.run(
        action="write",
        path=str(py),
        content="def n():\n    return 1\n",
    )
    assert written.ok
    listed = await tool.run(action="list", path=".")
    assert listed.ok
    assert "hello.py" in listed.output
    edited = await tool.run(
        action="edit",
        path=str(py),
        old="return 1",
        new="return 2",
    )
    assert edited.ok
    read_back = await tool.run(action="read", path=str(py))
    assert read_back.ok
    assert "return 2" in read_back.output
    assert "return 1" not in read_back.output
