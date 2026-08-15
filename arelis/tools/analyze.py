from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pandas as pd

from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

# Guard rails against a single call swamping the model's context or the loop.
# A table can legitimately have millions of rows; a chat answer cannot.
_MAX_ROWS_READ = 200_000
_MAX_HEAD_ROWS = 200
_MAX_OUTPUT_CHARS = 20_000


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_TEXT_SUFFIXES = {".txt", ".md", ".log", ".yaml", ".yml", ".ini", ".cfg", ".py"}


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
        "under allowed roots. Actions: summary, head, describe. "
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
                "enum": ["summary", "head", "describe"],
                "description": "Analysis action (default summary)",
            },
            "rows": {"type": "integer", "description": "Row count for head (default 5)"},
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
        return self.workspace.resolve_read(path_str)

    def _load(self, path: Path) -> pd.DataFrame:
        """Read a table, capped at _MAX_ROWS_READ.

        The cap is applied by the reader rather than after loading, so a file
        larger than memory fails as a truncated read instead of taking the
        process down. pandas ignores nrows for Excel and JSON, so those formats
        are trimmed after the fact.
        """
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
        if action not in {"summary", "head", "describe"}:
            return ToolResult(ok=False, output=f"Unknown action: {action}")
        try:
            rows = int(kwargs.get("rows", 5))
        except (TypeError, ValueError):
            rows = 5
        # pandas parsing is CPU and I/O bound and holds the GIL in chunks. Run
        # it off the event loop so streaming, stop, and confirm stay responsive.
        return await asyncio.to_thread(self._analyze, str(path_str), action, rows)

    def _analyze(self, path_str: str, action: str, rows: int) -> ToolResult:
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
        except Exception as exc:
            return ToolResult(ok=False, output=f"analyze failed: {exc}")
