"""Read-only SQL against memory.db or a workspace table file.

`analyze action=query` already answers where / group_by / agg on one loaded
table, and it does that without handing the model string to pandas. This tool
is the other job: a real SELECT (joins, CTEs, EXPLAIN) against the
conversation archive, or against a CSV/TSV/JSON loaded into a throwaway
in-memory SQLite table. It is not a second path into a Python evaluator.

Safety is two layers, because a denylist of words is one comment-trick behind
and an authorizer is one forgotten action code behind:

1. The text is scanned after comments and string literals are stripped. Only
   SELECT / WITH / EXPLAIN may start the statement; INSERT / UPDATE / DELETE /
   DROP / ATTACH / PRAGMA / WRITE and friends are refused before SQLite sees
   them. Multiple statements are refused. User SQL is never passed to
   executescript.
2. The connection runs a sqlite authorizer that allows READ, SELECT, FUNCTION
   (minus load_extension / writefile / readfile), TRANSACTION (ignored), and
   RECURSIVE. Everything else is DENY, including ATTACH. memory.db is opened
   `mode=ro`. Allowlisted tables only; embeddings and FTS stay out.

CSV load uses pandas readers, then `DataFrame.to_sql`. The query string is
never handed to pandas as an expression.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any

from arelis.paths import state_dir
from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

# Result caps. A SELECT without LIMIT on messages would otherwise dump the
# whole archive into the model's context.
_DEFAULT_ROWS = 50
_MAX_ROWS = 50
_MAX_OUTPUT_CHARS = 12_000
_MAX_LOAD_ROWS = 20_000
_MAX_CELL_CHARS = 80

# User-facing archive tables. embeddings / FTS / sqlite internals stay off
# this list on purpose — they are either blobs or implementation.
MEMORY_TABLES: frozenset[str] = frozenset(
    {
        "sessions",
        "messages",
        "summaries",
        "facts",
        "documents",
        "document_chunks",
        "mail_messages",
        "tasks",
        "decisions",
        "episodes",
        "goals",
    }
)

_TABLE_SUFFIXES = {".csv", ".tsv", ".tab", ".json"}

_DENIED_FUNCS = frozenset({"load_extension", "writefile", "readfile", "eval"})

# Statement-level verbs. REPLACE is a function too (`replace(s,a,b)`), so it
# is not on this list — REPLACE INTO is caught by INTO, and the authorizer
# denies SQLITE_REPLACE / SQLITE_INSERT.
_DENIED_WORDS = re.compile(
    r"(?i)\b("
    r"INSERT|UPDATE|DELETE|DROP|ATTACH|DETACH|PRAGMA|CREATE|ALTER|"
    r"VACUUM|REINDEX|ANALYZE|GRANT|REVOKE|TRUNCATE|WRITE|"
    r"load_extension|writefile|readfile"
    r")\b"
)
_INTO = re.compile(r"(?i)\bINTO\b")
_ALLOWED_HEAD = re.compile(r"(?i)^(WITH|SELECT|EXPLAIN)\b")

# Authorizer allow-list. TRANSACTION is ignored so BEGIN is a no-op rather
# than a way to hold a lock. RECURSIVE is WITH RECURSIVE.
_AUTH_OK = {
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


class SqlTool:
    name = "sql"
    description = (
        "Read-only SQL against memory.db (allowlisted tables: messages, "
        "document_chunks, facts, tasks, goals, sessions, summaries, documents, "
        "mail_messages, decisions, episodes) or a workspace CSV/TSV/JSON "
        "loaded as table `data` (and the file stem). SELECT / WITH / EXPLAIN "
        "only — no INSERT/UPDATE/DELETE/DROP/ATTACH/PRAGMA. For a simple "
        "where/group_by/agg on one spreadsheet, use analyze action=query "
        "instead of writing SQL."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "A single SELECT, WITH, or EXPLAIN statement. "
                    "Joins and CTEs are fine. Writes, ATTACH, and PRAGMA are not."
                ),
            },
            "query": {
                "type": "string",
                "description": "Alias for sql",
            },
            "path": {
                "type": "string",
                "description": (
                    "Workspace CSV/TSV/JSON to load as table `data`. "
                    "Omit to query memory.db. name:relative/path when multi-root."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (f"Max result rows (default {_DEFAULT_ROWS}, hard cap {_MAX_ROWS})"),
            },
        },
        "required": ["sql"],
    }

    def __init__(
        self,
        roots: list[str] | WorkspaceRoots,
        memory_path: Path | str | None = None,
    ) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]
        if memory_path is None:
            self.memory_path = state_dir() / "memory.db"
        else:
            self.memory_path = Path(memory_path)

    async def run(self, **kwargs: Any) -> ToolResult:
        sql = str(kwargs.get("sql") or kwargs.get("query") or "").strip()
        path = str(kwargs.get("path") or "").strip()
        try:
            limit = int(kwargs.get("limit") or _DEFAULT_ROWS)
        except (TypeError, ValueError):
            limit = _DEFAULT_ROWS
        limit = max(1, min(limit, _MAX_ROWS))
        return await asyncio.to_thread(self._run_sync, sql, path, limit)

    def _run_sync(self, sql: str, path: str, limit: int) -> ToolResult:
        if not sql:
            return ToolResult(ok=False, output="Missing sql.")
        reason = denied_reason(sql)
        if reason is not None:
            return ToolResult(ok=False, output=f"sql refused: {reason}")
        try:
            if path:
                return self._query_file(sql, path, limit)
            return self._query_memory(sql, limit)
        except PermissionError as exc:
            return ToolResult(ok=False, output=f"sql refused: {exc}")
        except FileNotFoundError as exc:
            return ToolResult(ok=False, output=f"sql failed: {exc}")
        except ValueError as exc:
            return ToolResult(ok=False, output=f"sql refused: {exc}")
        except sqlite3.Error as exc:
            return ToolResult(ok=False, output=f"sql refused: {exc}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"sql failed: {exc}")

    def _query_memory(self, sql: str, limit: int) -> ToolResult:
        path = self.memory_path
        if not path.is_file():
            return ToolResult(
                ok=False,
                output=f"memory.db is missing: {path}",
            )
        con = _connect_readonly(path)
        try:
            real = _real_tables(con)
            con.set_authorizer(_authorizer(MEMORY_TABLES, real))
            columns, rows, truncated = _fetch(con, sql, limit)
        finally:
            con.close()
        return _result(
            columns,
            rows,
            truncated,
            source="memory",
            extra={"path": str(path.resolve())},
        )

    def _query_file(self, sql: str, path_str: str, limit: int) -> ToolResult:
        resolved = self.workspace.resolve_read(path_str)
        path = resolved.path
        if not path.is_file():
            return ToolResult(ok=False, output=f"Not a file: {path}")
        suffix = path.suffix.lower()
        if suffix not in _TABLE_SUFFIXES:
            return ToolResult(
                ok=False,
                output=(
                    f"{suffix or 'that file'} is not a CSV/TSV/JSON table. "
                    "Use analyze for Excel, or omit path to query memory.db."
                ),
            )
        frame, load_capped = _load_table(path)
        stem = _safe_ident(path.stem)
        aliases = {"data"}
        if stem:
            aliases.add(stem)
        con = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            _disable_extensions(con)
            frame.to_sql("data", con, index=False, if_exists="replace")
            if stem and stem != "data":
                con.execute(f'CREATE VIEW "{stem}" AS SELECT * FROM data')
            con.set_authorizer(_authorizer(aliases, _real_tables(con)))
            columns, rows, truncated = _fetch(con, sql, limit)
        finally:
            con.close()
        display = resolved.qualified(multi=len(self.workspace) > 1)
        notes = []
        if load_capped:
            notes.append(f"loaded first {_MAX_LOAD_ROWS} rows of {display}")
        return _result(
            columns,
            rows,
            truncated,
            source="file",
            extra={
                "path": display,
                "abs_path": str(path),
                "root_name": resolved.root_name,
                "tables": sorted(aliases),
            },
            notes=notes,
        )


def denied_reason(sql: str) -> str | None:
    """Why this statement must not run, or None if the text looks like a read.

    Strings and comments are masked first so `'DELETE'` and a commented INSERT
    do not trip the denylist, and so a second statement cannot hide behind a
    string that the scanner would otherwise skip incompletely.
    """
    scan = mask_for_scan(sql).strip()
    if not scan:
        return "empty statement"
    body = scan[:-1].strip() if scan.endswith(";") else scan
    if ";" in body:
        return "multiple statements are not allowed"
    hit = _DENIED_WORDS.search(body)
    if hit:
        return f"{hit.group(1).upper()} is not allowed"
    if _INTO.search(body):
        return "INTO is not allowed"
    if not _ALLOWED_HEAD.match(body):
        return "only SELECT, WITH, or EXPLAIN is allowed"
    return None


def mask_for_scan(sql: str) -> str:
    """Replace comments and quoted literals with spaces."""
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        two = sql[i : i + 2]
        if two == "--":
            while i < n and sql[i] != "\n":
                i += 1
            out.append(" ")
            continue
        if two == "/*":
            end = sql.find("*/", i + 2)
            if end < 0:
                out.append(" ")
                break
            out.append(" ")
            i = end + 2
            continue
        ch = sql[i]
        if ch in "'\"":
            quote = ch
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    uri = resolved.as_uri()
    sep = "&" if "?" in uri else "?"
    con = sqlite3.connect(
        f"{uri}{sep}mode=ro",
        uri=True,
        check_same_thread=False,
        timeout=5.0,
    )
    con.row_factory = sqlite3.Row
    _disable_extensions(con)
    return con


def _disable_extensions(con: sqlite3.Connection) -> None:
    disable = getattr(con, "enable_load_extension", None)
    if disable is None:
        return
    try:
        disable(False)
    except (AttributeError, sqlite3.Error):
        return


def _real_tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    names = {str(row[0]).lower() for row in rows}
    names.update({"sqlite_master", "sqlite_schema", "sqlite_temp_master"})
    return names


def _authorizer(allowed: set[str], real_tables: set[str]):
    allowed_l = {name.lower() for name in allowed}

    def _check(
        action: int,
        arg1: str | None,
        _arg2: str | None,
        _db: str | None,
        _source: str | None,
    ) -> int:
        if action == sqlite3.SQLITE_TRANSACTION:
            return sqlite3.SQLITE_IGNORE
        if action == sqlite3.SQLITE_FUNCTION:
            name = (arg1 or "").lower()
            if name in _DENIED_FUNCS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table = (arg1 or "").strip().strip('"').strip("`").lower()
            if table.startswith("pragma_"):
                return sqlite3.SQLITE_DENY
            if table in real_tables and table not in allowed_l:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action in _AUTH_OK:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return _check


def _fetch(
    con: sqlite3.Connection, sql: str, limit: int
) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    cur = con.execute(sql)
    raw_cols = cur.description or ()
    columns = [str(col[0]) for col in raw_cols]
    fetched = cur.fetchmany(limit + 1)
    truncated = len(fetched) > limit
    rows = [tuple(_cell(v) for v in row) for row in fetched[:limit]]
    return columns, rows, truncated


def _cell(value: Any) -> Any:
    if isinstance(value, (bytes, memoryview, bytearray)):
        return f"<blob {len(value)} bytes>"
    return value


def _load_table(path: Path) -> tuple[Any, bool]:
    import pandas as pd

    suffix = path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=_MAX_LOAD_ROWS + 1)
    elif suffix in {".tsv", ".tab"}:
        frame = pd.read_csv(path, sep="\t", nrows=_MAX_LOAD_ROWS + 1)
    elif suffix == ".json":
        frame = pd.read_json(path)
    else:  # pragma: no cover - suffix gated by the caller
        raise ValueError(f"{suffix} is not a table")
    capped = len(frame) > _MAX_LOAD_ROWS
    if capped:
        frame = frame.head(_MAX_LOAD_ROWS)
    return frame, capped


def _safe_ident(stem: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", stem.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned.lower()


def _result(
    columns: list[str],
    rows: list[tuple[Any, ...]],
    truncated: bool,
    *,
    source: str,
    extra: dict[str, Any],
    notes: list[str] | None = None,
) -> ToolResult:
    notes = list(notes or [])
    if truncated:
        notes.append(f"showing {len(rows)} rows; more matched (cap {_MAX_ROWS})")
    body = _format_table(columns, rows)
    if notes:
        body = body + "\n\n[" + "; ".join(notes) + "]"
    if len(body) > _MAX_OUTPUT_CHARS:
        body = body[:_MAX_OUTPUT_CHARS] + f"\n\n[truncated to {_MAX_OUTPUT_CHARS} chars]"
    return ToolResult(
        ok=True,
        output=body,
        data={
            "source": source,
            "columns": columns,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
            **extra,
        },
    )


def _format_table(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not columns:
        return f"{len(rows)} row(s)."
    header = f"{len(rows)} row(s). columns: {', '.join(columns)}"
    if not rows:
        return header + "\n(no rows)"
    str_rows: list[list[str]] = []
    widths = [len(c) for c in columns]
    for row in rows:
        cells: list[str] = []
        for i, value in enumerate(row):
            text = "" if value is None else str(value).replace("\n", " ")
            if len(text) > _MAX_CELL_CHARS:
                text = text[: _MAX_CELL_CHARS - 3] + "..."
            cells.append(text)
            if i < len(widths):
                widths[i] = max(widths[i], len(text))
        str_rows.append(cells)
    lines = [
        header,
        "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)),
        "  ".join("-" * widths[i] for i in range(len(columns))),
    ]
    for cells in str_rows:
        lines.append("  ".join(cells[i].ljust(widths[i]) for i in range(len(columns))))
    return "\n".join(lines)
