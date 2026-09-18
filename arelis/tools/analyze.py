"""Read a local table, and now also ask it a question.

`summary`, `head` and `describe` describe a file; none of them answers
anything about it. "What did we spend in March?" left the model with a choice
between reading 200 rows out of `head` and adding them up in its own head, or
guessing — and it is the tool's job not to offer that choice.

The obvious implementation is `DataFrame.query()`, and it is not used here on
purpose. That method evaluates its argument: with the python engine it is
`eval`, and `@`-references reach local scope. Handing a model-authored string
to it would be the same defect found in `plot` and in `python_exec` on
2026-09-17, for a third time in one day. So `where` is parsed by the small
parser below into a column, an operator and a literal, and anything it does
not recognise is refused rather than passed through to pandas.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from arelis.core.document_refs import resolve_drop_file
from arelis.tools.base import ToolResult
from arelis.workspace import ResolvedPath, WorkspaceRoots

# Guard rails against a single call swamping the model's context or the loop.
# A table can legitimately have millions of rows; a chat answer cannot.
_MAX_ROWS_READ = 200_000
_MAX_HEAD_ROWS = 200
_MAX_OUTPUT_CHARS = 20_000


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_TEXT_SUFFIXES = {".txt", ".md", ".log", ".yaml", ".yml", ".ini", ".cfg", ".py"}


_QUERY_MAX_ROWS = 100
_QUERY_DEFAULT_ROWS = 20

# Longest first, so ">=" is never read as ">" followed by a stray "=".
_WHERE_OPS: tuple[str, ...] = (
    ">=",
    "<=",
    "!=",
    "==",
    "=",
    ">",
    "<",
    " contains ",
    " startswith ",
    " endswith ",
    " in ",
)

_AGGS = ("sum", "mean", "median", "min", "max", "count", "nunique", "std")


class QueryError(ValueError):
    """A bad query that the user or model can fix from the message alone."""


def _coerce(raw: str) -> Any:
    """A literal from the query string as a number when it looks like one."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        # Quoted means "treat as text", including "007" and "1-2".
        return text[1:-1]
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none", "nan"}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_condition(text: str) -> tuple[str, str, Any]:
    """`"month >= 3"` -> `("month", ">=", 3)`. Raises on anything else.

    Deliberately dumb. It finds one operator and splits on it; there is no
    precedence, no parentheses, no arithmetic and no function calls, because
    every one of those is a step towards needing an evaluator.
    """
    raw = (text or "").strip()
    if not raw:
        raise QueryError("empty condition")
    for op in _WHERE_OPS:
        idx = raw.lower().find(op)
        if idx <= 0:
            continue
        column = raw[:idx].strip().strip("`")
        value = raw[idx + len(op) :].strip()
        if not column or not value:
            raise QueryError(f"could not read condition: {raw!r}")
        return column, op.strip(), _coerce(value)
    raise QueryError(
        f"could not read condition: {raw!r}. "
        "Use one of: col == value, col > value, col contains text, col in a,b,c"
    )


def split_conditions(where: str) -> list[str]:
    """Conditions joined by `and`. `or` is not supported, and says so."""
    raw = (where or "").strip()
    if not raw:
        return []
    if re.search(r"(?i)\bor\b", raw):
        raise QueryError(
            "`or` is not supported in where. Run the two queries separately, "
            "or filter on a single column with `in`."
        )
    return [part for part in re.split(r"(?i)\s+and\s+", raw) if part.strip()]


def _check_column(df: Any, column: str) -> str:
    """Column names are the most common mistake, so the error names the list."""
    if column in df.columns:
        return column
    lowered = {str(c).lower(): c for c in df.columns}
    if column.lower() in lowered:
        return lowered[column.lower()]
    raise QueryError(f"no column named {column!r}. Columns are: {list(df.columns)}")


def apply_where(df: Any, where: str) -> Any:
    """Filter rows with the parsed conditions. No eval anywhere on this path."""
    for condition in split_conditions(where):
        column, op, value = parse_condition(condition)
        column = _check_column(df, column)
        series = df[column]
        if op == "contains":
            mask = series.astype(str).str.contains(str(value), case=False, na=False)
        elif op == "startswith":
            mask = series.astype(str).str.startswith(str(value), na=False)
        elif op == "endswith":
            mask = series.astype(str).str.endswith(str(value), na=False)
        elif op == "in":
            wanted = [_coerce(part) for part in str(value).split(",")]
            mask = series.isin(wanted)
        elif op in {"==", "="}:
            mask = series.isna() if value is None else series == value
        elif op == "!=":
            mask = series.notna() if value is None else series != value
        elif op == ">":
            mask = series > value
        elif op == ">=":
            mask = series >= value
        elif op == "<":
            mask = series < value
        elif op == "<=":
            mask = series <= value
        else:  # pragma: no cover - parse_condition cannot produce this
            raise QueryError(f"unsupported operator {op!r}")
        df = df[mask]
    return df


def _redirect(suffix: str) -> str:
    """Name the tool that can read this file, rather than only refusing."""
    if suffix in _IMAGE_SUFFIXES:
        return "Call vision(path=…) for an image, or ocr for its exact text."
    if suffix == ".pdf":
        return "Call doc_extract(path=…) for a PDF."
    if suffix in _TEXT_SUFFIXES:
        return "Call workspace(action=read, path=…) for text."
    return "This tool reads CSV, TSV, JSON and Excel only."


class AnalyzeTool:
    name = "analyze"
    description = (
        "Read a local spreadsheet or data table: CSV, TSV, JSON or Excel only, "
        "under allowed roots. Actions: summary, head, describe, query. "
        "Use query to answer a question instead of reading rows yourself: "
        'where="month == 3", group_by="region", agg="sum", on="revenue", '
        "sort/desc/limit. Never add up numbers from head output by hand. "
        "With multiple projects, qualify paths as name:relative/path. "
        "Despite the name this is not a general 'analyze this file' tool: for an "
        "image call vision, for a PDF call doc_extract, for text call workspace "
        "action=read. It rejects any other file type."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to table file, or name:relative/path",
            },
            "action": {
                "type": "string",
                "enum": ["summary", "head", "describe", "query"],
                "description": "Analysis action (default summary)",
            },
            "rows": {"type": "integer", "description": "Row count for head (default 5)"},
            "where": {
                "type": "string",
                "description": (
                    "Row filter for query. One or more conditions joined by "
                    "'and': \"status == shipped and amount > 100\". Operators: "
                    "== != > >= < <= contains startswith endswith in. "
                    "'or' is not supported."
                ),
            },
            "group_by": {
                "type": "string",
                "description": "Column(s) to group by for query, comma separated",
            },
            "agg": {
                "type": "string",
                "enum": list(_AGGS),
                "description": "How to combine each group (default sum, or count with no `on`)",
            },
            "on": {
                "type": "string",
                "description": "Column(s) to aggregate, comma separated",
            },
            "select": {
                "type": "string",
                "description": "Columns to keep, comma separated. Ungrouped query only.",
            },
            "sort": {"type": "string", "description": "Column to sort the result by"},
            "desc": {"type": "boolean", "description": "Sort descending"},
            "limit": {
                "type": "integer",
                "description": f"Max result rows (default {_QUERY_DEFAULT_ROWS})",
            },
        },
        "required": ["path"],
    }

    def __init__(self, roots: list[str] | WorkspaceRoots) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]

    def _resolve(self, path_str: str):
        try:
            return self.workspace.resolve_read(path_str)
        except Exception as first:
            drop = resolve_drop_file(
                path_str,
                suffixes={".csv", ".tsv", ".tab", ".xlsx", ".xls", ".json"},
            )
            if drop:
                path = Path(drop)
                return ResolvedPath(
                    path=path,
                    root_name="outputs",
                    root=path.parent,
                )
            raise first

    def _load(self, path: Path) -> Any:
        """Read a table, capped at _MAX_ROWS_READ.

        The cap is applied by the reader rather than after loading, so a file
        larger than memory fails as a truncated read instead of taking the
        process down. pandas ignores nrows for Excel and JSON, so those formats
        are trimmed after the fact.
        """
        import pandas as pd

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path, nrows=_MAX_ROWS_READ)
        if suffix in {".tsv", ".tab"}:
            return pd.read_csv(path, sep="\t", nrows=_MAX_ROWS_READ)
        if suffix == ".json":
            return pd.read_json(path).head(_MAX_ROWS_READ)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, nrows=_MAX_ROWS_READ)
        # The model arrives here because the user said "analyze" about a photo or
        # a PDF, which is the ordinary way to say it. Naming the tool that can
        # actually read the file turns a dead end into one more round.
        raise ValueError(f"{suffix or 'that file'} is not a table. {_redirect(suffix)}")

    async def run(self, **kwargs: Any) -> ToolResult:
        path_str = kwargs.get("path")
        if not path_str:
            return ToolResult(ok=False, output="Missing path")
        action = (kwargs.get("action") or "summary").lower()
        if action not in {"summary", "head", "describe", "query"}:
            return ToolResult(ok=False, output=f"Unknown action: {action}")
        try:
            rows = int(kwargs.get("rows", 5))
        except (TypeError, ValueError):
            rows = 5
        # pandas parsing is CPU and I/O bound and holds the GIL in chunks. Run
        # it off the event loop so streaming, stop, and confirm stay responsive.
        return await asyncio.to_thread(self._analyze, str(path_str), action, rows, dict(kwargs))

    def _analyze(
        self,
        path_str: str,
        action: str,
        rows: int,
        kwargs: dict[str, Any] | None = None,
    ) -> ToolResult:
        kwargs = kwargs or {}
        try:
            resolved = self._resolve(path_str)
            path = resolved.path
            if not path.is_file():
                return ToolResult(ok=False, output=f"Not a file: {path}")
            df = self._load(path)
            display = resolved.qualified(multi=len(self.workspace) > 1)
            if action == "head":
                rows = max(1, min(rows, _MAX_HEAD_ROWS))
                body = df.head(rows).to_string()
            elif action == "describe":
                body = df.describe(include="all").to_string()
            elif action == "query":
                body = _run_query(df, kwargs)
            else:
                body = "\n".join(
                    [
                        f"path: {display}",
                        f"shape: {df.shape[0]} rows x {df.shape[1]} cols",
                        f"columns: {list(df.columns)}",
                        f"dtypes:\n{df.dtypes.to_string()}",
                        f"nulls:\n{df.isna().sum().to_string()}",
                    ]
                )
            if len(body) > _MAX_OUTPUT_CHARS:
                body = body[:_MAX_OUTPUT_CHARS] + f"\n\n[truncated to {_MAX_OUTPUT_CHARS} chars]"
            return ToolResult(
                ok=True,
                output=body,
                data={
                    "path": display,
                    "abs_path": str(path),
                    "root_name": resolved.root_name,
                },
            )
        except QueryError as exc:
            # Separated from the generic handler because every one of these is
            # something the next round can fix: a wrong column name, an `or`,
            # an operator that does not exist. A pandas KeyError traceback is
            # not.
            return ToolResult(ok=False, output=f"analyze query: {exc}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"analyze failed: {exc}")


def _columns(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [part.strip().strip("`") for part in text.split(",") if part.strip()]


def _run_query(df: Any, kwargs: dict[str, Any]) -> str:
    """Filter, group, aggregate, sort, limit — the four verbs a data question
    actually uses, none of which existed before.

    Returns the rendered table. The row count before and after filtering is
    always stated: "12 of 4,310 rows" is the difference between an answer and
    a number with no scale, and a filter that silently matched nothing is
    otherwise indistinguishable from a real zero.
    """
    total = len(df)
    where = str(kwargs.get("where") or "").strip()
    if where:
        df = apply_where(df, where)
    matched = len(df)

    group_by = [_check_column(df, c) for c in _columns(kwargs.get("group_by"))]
    on = [_check_column(df, c) for c in _columns(kwargs.get("on"))]
    agg = str(kwargs.get("agg") or "").strip().lower()
    if agg and agg not in _AGGS:
        raise QueryError(f"unknown agg {agg!r}. Use one of: {', '.join(_AGGS)}")

    try:
        limit = int(kwargs.get("limit") or _QUERY_DEFAULT_ROWS)
    except (TypeError, ValueError):
        limit = _QUERY_DEFAULT_ROWS
    limit = max(1, min(limit, _QUERY_MAX_ROWS))

    header = f"{matched} of {total} rows matched"
    if matched == 0:
        # An empty result is a real answer, but only if it cannot be confused
        # with a broken filter — so say what was applied.
        return f"{header}.\nFilter: {where or '(none)'}\nNo rows to aggregate."

    if group_by:
        agg = agg or ("sum" if on else "count")
        grouped = df.groupby(group_by, dropna=False)
        result = grouped[on].agg(agg) if on else grouped.size().to_frame("count")
        result = result.reset_index()
    elif on:
        agg = agg or "sum"
        # No grouping: one number per column, which is the "what is the total"
        # shape rather than the "by region" shape.
        values = df[on].agg(agg)
        lines = [header, f"{agg} over {matched} rows:"]
        for column in on:
            lines.append(f"  {column}: {values[column]}")
        return "\n".join(lines)
    else:
        result = df
        select = [_check_column(df, c) for c in _columns(kwargs.get("select"))]
        if select:
            result = result[select]

    sort = str(kwargs.get("sort") or "").strip()
    if sort:
        result = result.sort_values(
            _check_column(result, sort), ascending=not bool(kwargs.get("desc"))
        )

    shown = result.head(limit)
    tail = "" if len(result) <= limit else f"\n[showing {limit} of {len(result)} result rows]"
    return f"{header}.\n{shown.to_string(index=False)}{tail}"
