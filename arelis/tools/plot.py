"""Named charts — a PNG on disk, not Python the model recites.

A 9B cannot be given matplotlib as a programming language. This tool has three
actions (line, scatter, residuals), reads a table the same way analyze does,
and writes a new file. It never evals user code. Allow stays: risk=write.
Unattended jobs do not get this tool.

Orbit (no room, or a room with no folder) lands under outputs/plots/.
A room with a real project folder lands under that project's plots/.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arelis.paths import display_path, ensure, outputs_dir
from arelis.rooms import RoomStore
from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

_ACTIONS = frozenset({"line", "scatter", "residuals"})
_MAX_ROWS = 20_000
_MAX_INLINE = 2_000
_TABLE_SUFFIXES = {".csv", ".tsv", ".tab", ".json", ".xlsx", ".xls"}
_INLINE_SPLIT = re.compile(r"[,;\s]+")
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")

_np_mod: Any = None
_pd_mod: Any = None


def _numpy() -> Any:
    global _np_mod
    if _np_mod is None:
        import numpy as np

        _np_mod = np
    return _np_mod


def _pandas() -> Any:
    global _pd_mod
    if _pd_mod is None:
        import pandas as pd

        _pd_mod = pd
    return _pd_mod


def _figure() -> tuple[Any, Any]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    return Figure, FigureCanvasAgg


def _unique_dest(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def _parse_numbers(raw: str, *, name: str) -> np.ndarray:
    np = _numpy()
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"Missing {name}.")
    parts = [p for p in _INLINE_SPLIT.split(text) if p]
    if len(parts) > _MAX_INLINE:
        raise ValueError(f"{name} is too long (max {_MAX_INLINE} points).")
    try:
        values = np.array([float(p) for p in parts], dtype=float)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be numbers separated by commas, not an expression."
        ) from exc
    if np.isnan(values).any():
        raise ValueError(f"{name} contained a non-number.")
    return values


def _contained(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


class PlotTool:
    name = "plot"
    description = (
        "Draw a chart from a local table or a short list of numbers and write "
        "a PNG. In a room with a folder, the file lands in that project's "
        "plots/ directory. Otherwise it lands under outputs/plots/. Actions: "
        "line, scatter, residuals. For a CSV/TSV/Excel file pass path plus x "
        "and y column names. For a tiny series pass xs and ys as "
        "comma-separated numbers. residuals fits a straight line (least "
        "squares) and plots data+fit plus residuals — do not invent a trend "
        "or draw an ASCII chart. This is not Python: do not pass code. Allow "
        "is required. Do not use image (Comfy) for data."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["line", "scatter", "residuals"],
                "description": "Chart kind (default line)",
            },
            "path": {
                "type": "string",
                "description": "Table file under a workspace root (CSV/TSV/JSON/Excel)",
            },
            "x": {
                "type": "string",
                "description": "Column name for the horizontal axis",
            },
            "y": {
                "type": "string",
                "description": "Column name for the vertical axis",
            },
            "xs": {
                "type": "string",
                "description": "Comma-separated x numbers when there is no file",
            },
            "ys": {
                "type": "string",
                "description": "Comma-separated y numbers when there is no file",
            },
            "title": {"type": "string", "description": "Chart title"},
            "xlabel": {"type": "string", "description": "Horizontal axis label"},
            "ylabel": {"type": "string", "description": "Vertical axis label"},
            "out": {
                "type": "string",
                "description": (
                    "Output file name only (png). Lands in the room's plots/ "
                    "folder, or outputs/plots/ in orbit"
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots,
        rooms: RoomStore | None = None,
    ) -> None:
        self.workspace = workspace
        self.rooms = rooms

    def drop_dir(self) -> Path:
        return ensure(outputs_dir() / "plots")

    def room_plots_dir(self) -> Path | None:
        """Project/plots when a room with a live folder is open."""
        room = None if self.rooms is None else self.rooms.active
        if room is None or not room.root or self.workspace is None:
            return None
        entry = self.workspace.root_named(room.root)
        if entry is None:
            return None
        return ensure(entry.path / "plots")

    def out_dir(self) -> tuple[Path, str]:
        """(folder, short where-it-landed note)."""
        room_dir = self.room_plots_dir()
        if room_dir is not None:
            return room_dir, "this room's plots folder"
        room = None if self.rooms is None else self.rooms.active
        if room is not None and room.root:
            return (
                self.drop_dir(),
                "the shared drop tray — this room's folder is not a project any more",
            )
        if room is not None:
            return (
                self.drop_dir(),
                "the shared drop tray — this room has no folder",
            )
        return self.drop_dir(), "the shared drop tray (outputs/plots)"

    def preview_path(self, args: dict[str, Any] | None = None) -> Path:
        """Where this call will write, without writing it."""
        args = args or {}
        action = str(args.get("action") or "line").strip().lower()
        if action not in _ACTIONS:
            action = "line"
        folder, _where = self.out_dir()
        return self._dest(args, action, folder)

    async def run(self, **kwargs: Any) -> ToolResult:
        return await asyncio.to_thread(self._run, kwargs)

    def _run(self, kwargs: dict[str, Any]) -> ToolResult:
        action = str(kwargs.get("action") or "line").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output="Unknown action. Use line, scatter, or residuals.",
                data={"fail_class": "fail:action"},
            )
        try:
            x, y, xlabel, ylabel, source = self._series(kwargs)
        except (ValueError, PermissionError, OSError) as exc:
            return ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:args"},
            )
        title = str(kwargs.get("title") or "").strip()
        xlabel = str(kwargs.get("xlabel") or xlabel).strip() or xlabel
        ylabel = str(kwargs.get("ylabel") or ylabel).strip() or ylabel
        try:
            dest, extra = self._draw(
                action, x, y, title=title, xlabel=xlabel, ylabel=ylabel, kwargs=kwargs
            )
        except ValueError as exc:
            return ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:draw"},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"Could not draw that chart: {exc}",
                data={"fail_class": "fail:other"},
            )
        shown = display_path(dest)
        _folder, where = self.out_dir()
        bits = [f"Wrote {shown} ({action}, {len(x)} points) in {where}."]
        if extra:
            bits.append(extra)
        bits.append(
            "Open that file — that chart is from this turn, not a picture I imagined."
        )
        return ToolResult(
            ok=True,
            output=" ".join(bits),
            data={
                "action": action,
                "path": shown,
                "abs_path": str(dest.resolve()),
                "n": len(x),
                "source": source,
                "where": where,
            },
        )

    def _series(
        self, kwargs: dict[str, Any]
    ) -> tuple[np.ndarray, np.ndarray, str, str, str]:
        path_str = str(kwargs.get("path") or "").strip()
        if path_str:
            resolved = self.workspace.resolve_read(path_str)
            path = resolved.path
            if not path.is_file():
                raise ValueError(f"Not a file: {path_str}")
            suffix = path.suffix.lower()
            if suffix not in _TABLE_SUFFIXES:
                raise ValueError(
                    "plot reads CSV, TSV, JSON or Excel. "
                    "For a picture use vision; for text use workspace."
                )
            frame = _load_table(path)
            x_name = str(kwargs.get("x") or "").strip()
            y_name = str(kwargs.get("y") or "").strip()
            if not x_name or not y_name:
                cols = ", ".join(str(c) for c in frame.columns[:12])
                raise ValueError(
                    f"path needs x and y column names. Columns: {cols}."
                )
            x = _column(frame, x_name)
            y = _column(frame, y_name)
            np = _numpy()
            mask = np.isfinite(x) & np.isfinite(y)
            x, y = x[mask], y[mask]
            if len(x) < 2:
                raise ValueError("Need at least two numeric rows after dropping blanks.")
            if len(x) > _MAX_ROWS:
                x, y = x[:_MAX_ROWS], y[:_MAX_ROWS]
            display = resolved.qualified(multi=len(self.workspace) > 1)
            return x, y, x_name, y_name, display
        xs = str(kwargs.get("xs") or "").strip()
        ys = str(kwargs.get("ys") or "").strip()
        if not xs or not ys:
            raise ValueError(
                "Give a table path with x and y columns, or xs and ys as numbers."
            )
        x = _parse_numbers(xs, name="xs")
        y = _parse_numbers(ys, name="ys")
        if len(x) != len(y):
            raise ValueError("xs and ys must be the same length.")
        if len(x) < 2:
            raise ValueError("Need at least two points.")
        return x, y, "x", "y", "inline"

    def _draw(
        self,
        action: str,
        x: np.ndarray,
        y: np.ndarray,
        *,
        title: str,
        xlabel: str,
        ylabel: str,
        kwargs: dict[str, Any],
    ) -> tuple[Path, str]:
        folder, _where = self.out_dir()
        dest = self._dest(kwargs, action, folder)
        ensure(dest.parent)
        extra = ""
        if action == "residuals":
            extra = _residuals_figure(
                dest, x, y, title=title, xlabel=xlabel, ylabel=ylabel
            )
        else:
            figure_cls, canvas_cls = _figure()
            fig = figure_cls(figsize=(8.0, 5.0), dpi=120)
            canvas_cls(fig)
            ax = fig.add_subplot(111)
            if action == "scatter":
                ax.scatter(x, y, s=18, alpha=0.85)
            else:
                ax.plot(x, y, marker="o", linewidth=1.4, markersize=3.5)
            if title:
                ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(dest)
        return dest, extra

    def _dest(self, kwargs: dict[str, Any], action: str, folder: Path) -> Path:
        raw = str(kwargs.get("out") or "").strip().replace("\\", "/")
        leaf = Path(raw).name if raw else f"plot-{action}.png"
        stem = _SAFE_STEM.sub("-", Path(leaf).stem).strip(".-") or f"plot-{action}"
        suffix = Path(leaf).suffix.lower() if raw else ".png"
        if suffix not in {".png", ".pdf"}:
            suffix = ".png"
        dest = _unique_dest(folder, stem, suffix)
        if not _contained(dest, folder):
            dest = _unique_dest(folder, f"plot-{action}", ".png")
        return dest


def _load_table(path: Path) -> pd.DataFrame:
    pd = _pandas()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=_MAX_ROWS)
    if suffix in {".tsv", ".tab"}:
        return pd.read_csv(path, sep="\t", nrows=_MAX_ROWS)
    if suffix == ".json":
        return pd.read_json(path).head(_MAX_ROWS)
    try:
        return pd.read_excel(path, nrows=_MAX_ROWS)
    except ImportError as exc:
        raise ValueError(
            "Excel needs an extra reader that is not in the default install. "
            "Save the sheet as CSV and plot that."
        ) from exc


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    pd = _pandas()
    if name not in frame.columns:
        cols = ", ".join(str(c) for c in frame.columns[:12])
        raise ValueError(f"No column {name!r}. Columns: {cols}.")
    series = pd.to_numeric(frame[name], errors="coerce")
    return series.to_numpy(dtype=float)


def _residuals_figure(
    dest: Path,
    x: np.ndarray,
    y: np.ndarray,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
) -> str:
    if len(x) < 3:
        raise ValueError("residuals needs at least three numeric points.")
    np = _numpy()
    pd = _pandas()
    figure_cls, canvas_cls = _figure()
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    resid = y - yhat
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    fig = figure_cls(figsize=(8.0, 7.0), dpi=120)
    canvas_cls(fig)
    ax = fig.add_subplot(211)
    ax.scatter(x, y, s=18, alpha=0.85, label="data")
    order = np.argsort(x)
    ax.plot(x[order], yhat[order], color="C1", label="fit")
    ax.set_title(title or "Fit")
    ax.set_ylabel(ylabel)
    ax.legend(frameon=False)
    ax.grid(True, alpha=0.3)
    bx = fig.add_subplot(212, sharex=ax)
    bx.axhline(0.0, color="0.5", linewidth=0.8)
    bx.scatter(x, resid, s=18, alpha=0.85)
    bx.set_xlabel(xlabel)
    bx.set_ylabel("residual")
    bx.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(dest)
    table = dest.with_suffix(".csv")
    pd.DataFrame(
        {"x": x, "y": y, "yhat": yhat, "residual": resid}
    ).to_csv(table, index=False)
    shown = display_path(table)
    return (
        f"Least-squares line y = {slope:.6g} x + {intercept:.6g}; "
        f"R^2 = {r2:.4f}. Residuals table: {shown}."
    )
