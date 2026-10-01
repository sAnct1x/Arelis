"""Regression test for SQL tool with matrix fixtures (S27_sql)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from arelis.tools.sql_query import SqlTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_sql_queries_workspace_csv_correctly(tmp_path: Path) -> None:
    """SQL tool should resolve work/sales.csv and query it (S27_sql)."""
    # Set up workspace like the live matrix does
    ws = tmp_path / "matrix"
    work = ws / "work"
    work.mkdir(parents=True)
    
    # Create sales.csv like make_fixtures does
    (work / "sales.csv").write_text(
        "region,revenue\nnorth,100\nnorth,150\nsouth,250\neast,100\nwest,150\n",
        encoding="ascii",
    )
    
    # Create SQL tool with workspace
    tool = SqlTool(WorkspaceRoots.from_paths([str(ws)]))
    
    # Query for maximum revenue
    result = await tool.run(
        sql="SELECT MAX(revenue) as max_revenue FROM data",
        path="work/sales.csv",
    )
    
    assert result.ok, f"SQL tool failed: {result.output}"
    assert "250" in result.output, f"Expected 250 in output, got: {result.output}"
    assert result.data
    assert result.data["row_count"] >= 1
    rows = result.data.get("rows", [])
    assert len(rows) == 1
    assert rows[0][0] == 250, f"Expected max revenue 250, got {rows[0][0]}"


@pytest.mark.asyncio
async def test_sql_fails_gracefully_when_file_missing(tmp_path: Path) -> None:
    """SQL tool should return ok=False with clear message when file doesn't exist."""
    ws = tmp_path / "matrix"
    ws.mkdir(parents=True)
    
    tool = SqlTool(WorkspaceRoots.from_paths([str(ws)]))
    
    result = await tool.run(
        sql="SELECT * FROM data",
        path="work/nonexistent.csv",
    )
    
    assert not result.ok
    assert "not a file" in result.output.lower() or "not found" in result.output.lower()


@pytest.mark.asyncio
async def test_sql_fails_when_path_missing_and_no_memory_db(tmp_path: Path) -> None:
    """SQL tool should fail gracefully when no path given and memory.db missing."""
    ws = tmp_path / "matrix"
    ws.mkdir(parents=True)
    
    # Point to non-existent memory.db
    memory_path = tmp_path / "memory.db"
    
    tool = SqlTool(WorkspaceRoots.from_paths([str(ws)]), memory_path=memory_path)
    
    result = await tool.run(sql="SELECT * FROM messages")
    
    assert not result.ok
    assert "missing" in result.output.lower() or "not" in result.output.lower()


@pytest.mark.asyncio
async def test_sql_handles_data_dir_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SQL tool should check data dir if workspace resolution fails (defensive)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    
    # Create CSV in data dir (not workspace)
    (data / "data_file.csv").write_text(
        "id,value\n1,100\n2,200\n",
        encoding="ascii",
    )
    
    # Set data dir
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    
    tool = SqlTool(WorkspaceRoots.from_paths([str(ws)]))
    
    # Try to query with a path that doesn't exist in workspace but does in data dir
    result = await tool.run(
        sql="SELECT MAX(value) as max_val FROM data",
        path="data_file.csv",
    )
    
    # Should succeed by falling back to data dir
    assert result.ok, f"SQL should fall back to data dir: {result.output}"
    assert "200" in result.output
