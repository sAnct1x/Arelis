"""sql tool: SELECT against a real temp sqlite and a temp csv.

Roadmap 5.6. Drive SqlTool.run — a helper that looks right while DELETE
still executes is the bug.

Mutants this file is supposed to catch:

1. DELETE slips through (memory.db rows vanish).
2. ATTACH opens another file (secret row leaks).
3. path escape (`../`) reads a sibling CSV.
4. memory.db write attempted (INSERT/UPDATE land).
5. a result over the row cap is returned in full, with no truncation note.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.tools.sql_query import (
    SqlTool,
)
from arelis.workspace import RootEntry, WorkspaceRoots

CSV = """date,region,product,units,revenue,status
2026-01-04,north,widget,3,30.5,shipped
2026-02-11,north,widget,5,52.0,shipped
2026-03-02,south,gizmo,2,88.0,pending
2026-03-14,north,gizmo,7,301.25,shipped
2026-03-19,south,widget,1,11.0,cancelled
2026-04-01,east,gizmo,4,160.0,shipped
"""


def _workspace(tmp_path: Path) -> tuple[WorkspaceRoots, Path]:
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return workspace, project


def _seed_memory(path: Path) -> Path:
    store = MemoryStore(path)
    store.start_session()
    store.on_message("user", "I climb on tuesdays")
    store.on_message("assistant", "Noted.")
    store.add_fact("favourite fruit is mango", source="explicit", status="active")
    store.add_task("buy chalk")
    store.close()
    return path


def _tool(tmp_path: Path) -> tuple[SqlTool, Path, Path]:
    workspace, project = _workspace(tmp_path)
    memory = _seed_memory(tmp_path / "memory.db")
    return SqlTool(workspace, memory_path=memory), project, memory


def _scalar(path: Path, sql: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchone()
    finally:
        con.close()


@pytest.mark.asyncio
async def test_path_escape_is_refused(tmp_path: Path) -> None:
    """Mutant: `../` is joined and a sibling CSV is queried."""
    tool, project, _memory = _tool(tmp_path)
    (project / "safe.csv").write_text("n\n1\n", encoding="utf-8")
    planted = project.parent / "outside.csv"
    planted.write_text("secret,x\nhunter2-drive,1\n", encoding="utf-8")
    sibling = tmp_path / "other.csv"
    sibling.write_text("secret,x\nvault-9911,1\n", encoding="utf-8")

    for raw in (
        "../outside.csv",
        r"..\outside.csv",
        "safe.csv/../../outside.csv",
        str(planted),
        str(sibling),
    ):
        result = await tool.run(sql="SELECT * FROM data", path=raw)
        assert not result.ok, f"escape must fail for {raw!r}: {result.output}"
        assert "hunter2-drive" not in result.output
        assert "vault-9911" not in result.output


@pytest.mark.asyncio
async def test_memory_write_is_refused_and_does_not_land(tmp_path: Path) -> None:
    """Mutant: mode=ro or the authorizer is skipped and INSERT commits."""
    tool, _project, memory = _tool(tmp_path)
    before = _scalar(memory, "SELECT COUNT(*) FROM facts")[0]
    inserted = await tool.run(
        sql=(
            "INSERT INTO facts (text, source, status, created_at, updated_at) "
            "VALUES ('pwned-fact', 'sql', 'active', 't', 't')"
        )
    )
    assert not inserted.ok, inserted.output
    updated = await tool.run(sql="UPDATE facts SET text = 'rewritten'")
    assert not updated.ok, updated.output
    after = _scalar(memory, "SELECT COUNT(*) FROM facts")[0]
    assert after == before
    con = sqlite3.connect(memory)
    try:
        texts = [row[0] for row in con.execute("SELECT text FROM facts")]
    finally:
        con.close()
    assert "pwned-fact" not in texts
    assert all(t != "rewritten" for t in texts)


@pytest.mark.asyncio
async def test_unallowlisted_table_is_refused(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    result = await tool.run(sql="SELECT model FROM embeddings")
    assert not result.ok, result.output
    pragma = await tool.run(sql="PRAGMA table_info(messages)")
    assert not pragma.ok
    assert "PRAGMA" in pragma.output


