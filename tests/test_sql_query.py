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
    _MAX_ROWS,
    MEMORY_TABLES,
    SqlTool,
    denied_reason,
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
async def test_select_against_temp_sqlite(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    result = await tool.run(sql="SELECT role, content FROM messages ORDER BY id")
    assert result.ok, result.output
    assert result.data["source"] == "memory"
    assert "I climb on tuesdays" in result.output
    assert result.data["row_count"] == 2
    facts = await tool.run(sql="SELECT text FROM facts WHERE status = 'active'")
    assert facts.ok, facts.output
    assert "mango" in facts.output
    tasks = await tool.run(sql="SELECT title FROM tasks")
    assert tasks.ok, tasks.output
    assert "buy chalk" in tasks.output


@pytest.mark.asyncio
async def test_select_against_temp_csv(tmp_path: Path) -> None:
    tool, project, _memory = _tool(tmp_path)
    table = project / "sales.csv"
    table.write_text(CSV, encoding="utf-8")
    result = await tool.run(
        sql="SELECT region, SUM(revenue) AS total FROM data GROUP BY region",
        path="sales.csv",
    )
    assert result.ok, result.output
    assert result.data["source"] == "file"
    assert "north" in result.output
    assert "383.75" in result.output
    # File stem is an alias for the same table.
    again = await tool.run(
        sql="SELECT COUNT(*) AS n FROM sales",
        path="sales.csv",
    )
    assert again.ok, again.output
    assert again.data["rows"][0][0] == 6


@pytest.mark.asyncio
async def test_with_and_explain_are_allowed(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    cte = await tool.run(
        sql=("WITH recent AS (SELECT content FROM messages) SELECT content FROM recent")
    )
    assert cte.ok, cte.output
    assert "climb" in cte.output
    plan = await tool.run(sql="EXPLAIN SELECT COUNT(*) FROM tasks")
    assert plan.ok, plan.output
    assert plan.data["row_count"] >= 1


@pytest.mark.asyncio
async def test_delete_does_not_slip_through(tmp_path: Path) -> None:
    """Mutant: the denylist is a comment and DELETE still runs."""
    tool, _project, memory = _tool(tmp_path)
    before = _scalar(memory, "SELECT COUNT(*) FROM messages")
    result = await tool.run(sql="DELETE FROM messages")
    assert not result.ok, result.output
    assert "DELETE" in result.output
    after = _scalar(memory, "SELECT COUNT(*) FROM messages")
    assert after == before
    assert before[0] == 2
    # Comment / string camouflage still cannot write.
    sneaky = await tool.run(sql="SELECT 1; DELETE FROM messages")
    assert not sneaky.ok
    still = _scalar(memory, "SELECT COUNT(*) FROM messages")
    assert still == before


@pytest.mark.asyncio
async def test_attach_does_not_open_another_file(tmp_path: Path) -> None:
    """Mutant: ATTACH is compiled and a second database is readable."""
    tool, project, _memory = _tool(tmp_path)
    secret = tmp_path / "secret.db"
    con = sqlite3.connect(secret)
    con.execute("CREATE TABLE leak (secret TEXT)")
    con.execute("INSERT INTO leak VALUES ('hunter2-vault')")
    con.commit()
    con.close()
    planted = project / "innocent.csv"
    planted.write_text("n\n1\n", encoding="utf-8")

    attach = await tool.run(sql=f"ATTACH DATABASE '{secret.as_posix()}' AS ev")
    assert not attach.ok, attach.output
    assert "hunter2-vault" not in attach.output

    both = await tool.run(
        sql=(f"ATTACH DATABASE '{secret.as_posix()}' AS ev; SELECT secret FROM ev.leak")
    )
    assert not both.ok, both.output
    assert "hunter2-vault" not in both.output

    via_file = await tool.run(
        sql=f"ATTACH DATABASE '{secret.as_posix()}' AS ev; SELECT * FROM data",
        path="innocent.csv",
    )
    assert not via_file.ok
    assert "hunter2-vault" not in via_file.output


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
async def test_over_cap_is_truncated_with_a_note(tmp_path: Path) -> None:
    """Mutant: fetchall() and the cap is only in the description."""
    tool, project, _memory = _tool(tmp_path)
    rows = ["n"] + [str(i) for i in range(_MAX_ROWS + 30)]
    (project / "many.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = await tool.run(sql="SELECT * FROM data", path="many.csv")
    assert result.ok, result.output
    assert result.data["truncated"] is True
    assert result.data["row_count"] == _MAX_ROWS
    assert "showing" in result.output
    assert "more matched" in result.output
    assert f"cap {_MAX_ROWS}" in result.output
    assert len(result.data["rows"]) == _MAX_ROWS


@pytest.mark.asyncio
async def test_unallowlisted_table_is_refused(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    result = await tool.run(sql="SELECT model FROM embeddings")
    assert not result.ok, result.output
    pragma = await tool.run(sql="PRAGMA table_info(messages)")
    assert not pragma.ok
    assert "PRAGMA" in pragma.output


@pytest.mark.asyncio
async def test_string_literal_delete_is_not_a_write(tmp_path: Path) -> None:
    tool, _project, memory = _tool(tmp_path)
    result = await tool.run(sql="SELECT content FROM messages WHERE content LIKE '%DELETE%'")
    assert result.ok, result.output
    still = _scalar(memory, "SELECT COUNT(*) FROM messages")[0]
    assert still == 2


@pytest.mark.asyncio
async def test_risk_is_read() -> None:
    assert SqlTool.__dict__["risk"] == "read"
    assert "embeddings" not in MEMORY_TABLES
    assert {"messages", "document_chunks", "facts", "tasks", "goals"} <= MEMORY_TABLES


@pytest.mark.asyncio
async def test_missing_sql_fails(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    result = await tool.run(sql="")
    assert not result.ok
    assert "sql" in result.output.lower()


@pytest.mark.asyncio
async def test_query_alias_works(tmp_path: Path) -> None:
    tool, _project, _memory = _tool(tmp_path)
    result = await tool.run(query="SELECT COUNT(*) AS n FROM tasks")
    assert result.ok, result.output
    assert result.data["rows"][0][0] == 1


def test_denied_reason_masks_strings_and_comments() -> None:
    assert denied_reason("SELECT 'DELETE FROM x'") is None
    assert denied_reason("SELECT 1 /* DELETE */") is None
    assert denied_reason("DELETE FROM messages") is not None
    assert denied_reason("ATTACH DATABASE 'x' AS y") is not None
    assert denied_reason("SELECT 1; SELECT 2") is not None


def test_source_does_not_eval() -> None:
    text = Path("arelis/tools/sql_query.py").read_text(encoding="utf-8")
    assert "eval(" not in text
    assert "DataFrame.query" not in text
    assert ".query(" not in text
