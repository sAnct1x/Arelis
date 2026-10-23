"""Named charts, a PNG on disk, not Python the model recites.

A 9B cannot be given matplotlib as a programming language. This tool draws
named chart kinds (line, scatter, residuals, histogram, bar, subplots), reads
a table the same way analyze does, and writes a new file. It never evals user
code. Allow stays: risk=write. Unattended jobs do not get this tool.

Orbit (no room, or a room with no folder) lands under outputs/plots/.
A room with a real project folder lands under that project's plots/.
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
import re
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arelis.core.cell_work import resolve_cell_work_file
from arelis.core.document_refs import resolve_drop_file, resolve_reported_document_path
from arelis.paths import display_path, ensure, outputs_dir
from arelis.tools.analyze import frame_from_numpy
from arelis.tools.arg_error import arg_error as _arg_error
from arelis.tools.base import ToolResult
from arelis.workspace import ResolvedPath, WorkspaceRoots

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

_ACTIONS = frozenset({"line", "scatter", "residuals", "histogram", "bar", "subplots"})
_LOOKS = ("default", "poster", "paper", "slide")
# Okabe-Ito. Black is left out so a line does not vanish into the axes.
_COLORBLIND = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#D55E00",
    "#CC79A7",
    "#56B4E9",
    "#F0E442",
)
# title, axis label, tick. All larger than Matplotlib's 12 / 10 / 10.
# Default is the chat PNG: 8 in by 5 in at 120 dpi (960x600). Those stock
# sizes vanish when the bubble shrinks the file, so default type is closer
# to a poster than to the library.
_LOOK_FONTS = {
    "default": (20, 18, 16),
    "poster": (22, 18, 16),
    "paper": (16, 14, 12),
    "slide": (26, 20, 18),
}
_SUBPLOT_KINDS = frozenset({"line", "scatter", "histogram", "bar"})
_MAX_SUBPLOTS = 4
_MAX_ROWS = 20_000
_MAX_INLINE = 2_000
_TABLE_SUFFIXES = {".csv", ".tsv", ".tab", ".json", ".xlsx", ".xls", ".npy", ".npz", ".txt"}
_CHART_OUT_SUFFIXES = {".png", ".pdf", ".jpg", ".jpeg", ".webp", ".svg"}
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


def _parse_look(raw: Any) -> str:
    look = str(raw or "default").strip().lower()
    if not look:
        return "default"
    if look not in _LOOKS:
        raise ValueError("look must be default, poster, paper, or slide.")
    return look


def _look_rc(look: str) -> dict[str, Any]:
    title, label, tick = _LOOK_FONTS[look]
    fonts = {
        "font.size": tick,
        "axes.titlesize": title,
        "axes.labelsize": label,
        "xtick.labelsize": tick,
        "ytick.labelsize": tick,
        "legend.fontsize": label,
    }
    if look == "default":
        return fonts
    from cycler import cycler

    return {
        **fonts,
        "axes.prop_cycle": cycler(color=list(_COLORBLIND)),
    }


@contextmanager
def _look_context(look: str):
    from matplotlib import rc_context

    with rc_context(_look_rc(look)):
        yield


def _figure_size(look: str, *, tall: bool = False) -> tuple[float, float]:
    """Inches. Poster keeps the screen size so 300 dpi is the only scale-up."""
    if look == "paper":
        return (6.5, 5.8) if tall else (6.5, 4.2)
    if look == "slide":
        return (13.333, 7.5)
    return (8.0, 7.0) if tall else (8.0, 5.0)


def _open_figure(figsize: tuple[float, float], look: str) -> Any:
    figure_cls, canvas_cls = _figure()
    dpi = 300 if look != "default" else 120
    fig = figure_cls(figsize=figsize, dpi=dpi)
    canvas_cls(fig)
    return fig


def _mark_color(look: str, index: int = 0) -> dict[str, str]:
    if look == "default":
        return {}
    return {"color": _COLORBLIND[index % len(_COLORBLIND)]}


def _stroke(look: str) -> tuple[float, float]:
    """Line width and marker size. Print looks are heavier so they read across a room."""
    if look in {"poster", "slide"}:
        return 2.0, 5.5
    if look == "paper":
        return 1.6, 4.0
    return 1.4, 3.5


def _save_figure(fig: Any, dest: Path, look: str) -> str:
    """Write the PNG (or the asked suffix) and, for a print look, SVG and PDF."""
    dpi = 300 if look != "default" else 120
    fig.savefig(dest, dpi=dpi)
    if look == "default":
        return ""
    names: list[str] = []
    for suffix in (".svg", ".pdf"):
        sibling = dest.with_suffix(suffix)
        if sibling.resolve() == dest.resolve():
            continue
        fig.savefig(sibling, dpi=dpi)
        names.append(sibling.name)
    if dest.suffix.lower() != ".png":
        png = dest.with_suffix(".png")
        if png.resolve() != dest.resolve():
            fig.savefig(png, dpi=dpi)
            names.append(png.name)
    if not names:
        return ""
    return f"Also wrote {', '.join(names)} at 300 dpi ({look} look)."


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


def _looks_like_chart_out(path_str: str) -> bool:
    """True when path= was used as the PNG name (a 9B mix-up)."""
    leaf = Path(str(path_str).replace("\\", "/")).name
    return Path(leaf).suffix.lower() in _CHART_OUT_SUFFIXES


def _missing_inline(raw: Any) -> bool:
    """True when xs/ys/values/categories was omitted or empty."""
    if raw is None:
        return True
    if isinstance(raw, (list, tuple)):
        return len(raw) == 0
    return not str(raw).strip()


def normalize_plot_args(payload: dict[str, Any]) -> dict[str, Any]:
    """Take the subplots key the model sends when it means panels.

    The declared argument is panels. A call that says subplots= instead is
    the same request, and leaving the extra key on the call gets it rejected
    before this tool can draw.
    """
    if not isinstance(payload, dict) or "subplots" not in payload:
        return payload
    out = dict(payload)
    stray = out.pop("subplots")
    if _missing_inline(out.get("panels")) and not _missing_inline(stray):
        out["panels"] = stray
    return out


def _inline_pair(
    kwargs: dict[str, Any],
    *,
    primary: str,
    alias: str,
) -> Any:
    """Inline series: primary (xs/ys) wins over alias (x/y) when both are set."""
    value = kwargs.get(primary)
    if not _missing_inline(value):
        return value
    return kwargs.get(alias)


def _inline_parts(raw: Any, *, name: str, kind: str = "number") -> list[str]:
    """Split an inline series the way the 9B actually writes it.

    Accepts a real list/tuple from native tool calling, a JSON array string,
    Python-ish ``[1, 4, 9]`` / ``(1, 4, 9)``, or the documented comma list.
    Truncation with ``…`` / ``...`` stays refused, inventing the missing
    values is exactly what this tool exists to prevent.
    """
    if isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw if str(p).strip() != ""]
    else:
        text = str(raw if raw is not None else "").strip()
        if not text:
            parts = []
        else:
            if "…" in text or "..." in text:
                raise ValueError(
                    f"{name} is truncated. Pass every {kind}, or a CSV via "
                    "path=. Do not use … or ..."
                )
            parsed: Any = None
            if len(text) >= 2 and text[0] in "[(" and text[-1] in "])":
                candidate = text
                if text[0] == "(" and text[-1] == ")":
                    candidate = f"[{text[1:-1]}]"
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    parsed = None
            if isinstance(parsed, list):
                parts = [str(p).strip() for p in parsed if str(p).strip() != ""]
            elif len(text) >= 2 and text[0] in "[(" and text[-1] in "])":
                # Trailing commas and similar — strip the wrapper, split CSV.
                parts = [p for p in _INLINE_SPLIT.split(text[1:-1]) if p]
            else:
                parts = [p for p in _INLINE_SPLIT.split(text) if p]
    if not parts:
        raise ValueError(f"Missing {name}.")
    unit = "points" if kind == "number" else "labels"
    if len(parts) > _MAX_INLINE:
        raise ValueError(f"{name} is too long (max {_MAX_INLINE} {unit}).")
    return parts


def _parse_numbers(raw: Any, *, name: str) -> np.ndarray:
    if _as_nested_lists(raw) is not None:
        raise ValueError(
            f"{name} is a list of lists. Send one list like {name}=\"1,2,3\", "
            "or use action subplots with one list per panel."
        )
    np = _numpy()
    parts = _inline_parts(raw, name=name, kind="number")
    try:
        values = np.array([float(p) for p in parts], dtype=float)
    except ValueError as exc:
        preview = ",".join(parts[:4])
        if len(preview) > 48:
            preview = preview[:45] + "..."
        raise ValueError(
            f'{name} is not numbers (got {preview!r}). '
            f'Use {name}="1,2,3", or expr="sin(x), cos(x)" with xmin=0, xmax=2*pi.'
        ) from exc
    if np.isnan(values).any():
        raise ValueError(
            f'{name} contained a non-number. Use {name}="1,2,3" (or a {name} list).'
        )
    return values


_MAX_SAMPLES = 5000
_DEFAULT_SAMPLES = 400

# "2pi" is not valid Python, and `parse_cas_expr` runs `ast.parse` before
# SymPy's transformations — which do not include implicit multiplication — so it
# fails on a decimal literal before SymPy ever sees it. Inserting the `*` is
# safe because it cannot create a token that was not already there.
#
# Range endpoints only, deliberately. The expression body stays under exactly
# the rules `cas` enforces, so `2*sin(x)` is written the same way in both tools;
# this is only here because "0 to 2pi" is how the range gets spoken.
#
# The two lookaheads protect scientific notation: without them "1e3" becomes
# "1*e3", which is Euler's number times an unbound symbol, not 1000.
_IMPLICIT_TIMES = re.compile(r"(?<=\d)(?![eE]\d)(?![eE][+-]\d)(?=[a-zA-Z])")


def plot_range_value(raw: str, *, name: str) -> float:
    """A range endpoint, written the way the ask writes it: 2pi, pi/2, -1, 1e3.

    Demanding 6.283185 for "0 to 2pi" would push the rounding onto the model,
    which is where wrong numbers come from. Parsed through the same hardened
    CAS front door as the expression itself, so "pi" costs nothing in safety.
    """
    text = str(raw).strip()
    if not text:
        raise ValueError(f"Missing {name}.")
    text = _IMPLICIT_TIMES.sub("*", text)
    from arelis.tools.cas import parse_cas_expr

    try:
        value = float(parse_cas_expr(text).evalf())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{name} is not a number: {text!r} ({exc})") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {text!r}.")
    return value


_RANGE_FUNCS = frozenset({"linspace", "arange"})
_RANGE_MODULES = frozenset({"np", "numpy"})
_RANGE_KEYWORDS = frozenset({"start", "stop", "num", "step"})


def _range_func_name(func: ast.AST) -> str | None:
    """linspace / arange, or np.linspace / numpy.arange. Nothing else."""
    if isinstance(func, ast.Name):
        ident = func.id.lower()
        return ident if ident in _RANGE_FUNCS else None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id.lower() not in _RANGE_MODULES:
            return None
        ident = func.attr.lower()
        return ident if ident in _RANGE_FUNCS else None
    return None


def _range_arg_value(node: ast.AST, *, name: str) -> float:
    text = ast.unparse(node).strip()
    if not text:
        raise ValueError(f"Missing {name} in the range call.")
    return plot_range_value(text, name=name)


def parse_range_call(raw: Any, *, name: str = "xs") -> Any | None:
    """linspace(a, b, n) or arange(a, b, step), with pi / 2*pi.

    None when this is not that call. ValueError when it is, but the args
    are not a cheap numeric range. AST whitelist plus plot_range_value;
    no eval.
    """
    if isinstance(raw, (list, tuple)) and len(raw) == 1:
        raw = raw[0]
    if not isinstance(raw, str):
        return None
    text = _IMPLICIT_TIMES.sub("*", raw.strip())
    if not text:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    node = tree.body
    if not isinstance(node, ast.Call):
        return None
    kind = _range_func_name(node.func)
    if kind is None:
        return None
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        raise ValueError(
            f'{name} range call cannot unpack arguments. '
            f'Example: {name}="linspace(0, 2*pi, 100)".'
        )
    if any(kw.arg is None for kw in node.keywords):
        raise ValueError(
            f'{name} range call cannot take **kwargs. '
            f'Example: {name}="linspace(0, 2*pi, 100)".'
        )
    extra = [kw.arg for kw in node.keywords if kw.arg not in _RANGE_KEYWORDS]
    if extra:
        raise ValueError(
            f"{name} {kind} does not take {extra[0]}. "
            f'Example: {name}="linspace(0, 2*pi, 100)".'
        )
    pos = [_range_arg_value(arg, name=name) for arg in node.args]
    kw = {
        str(kw.arg): _range_arg_value(kw.value, name=name)
        for kw in node.keywords
        if kw.arg
    }
    np = _numpy()
    if kind == "linspace":
        if len(pos) > 3:
            raise ValueError(
                f'{name} linspace takes start, stop, n. '
                f'Example: {name}="linspace(0, 2*pi, 100)".'
            )
        lo = pos[0] if len(pos) > 0 else kw.get("start")
        hi = pos[1] if len(pos) > 1 else kw.get("stop")
        num_raw = pos[2] if len(pos) > 2 else kw.get("num", float(_DEFAULT_SAMPLES))
        if lo is None or hi is None or num_raw is None:
            raise ValueError(
                f'{name} linspace needs start and stop. '
                f'Example: {name}="linspace(0, 2*pi, 100)".'
            )
        count = round(float(num_raw))
        if count < 2:
            raise ValueError(f"{name} linspace needs at least 2 points.")
        if count > _MAX_SAMPLES:
            raise ValueError(
                f"{name} linspace asked for {count} points "
                f"(max {_MAX_SAMPLES}). Example: {name}=\"linspace(0, 2*pi, 400)\"."
            )
        return np.linspace(float(lo), float(hi), count)
    if len(pos) > 3:
        raise ValueError(
            f'{name} arange takes start, stop, step. '
            f'Example: {name}="arange(0, 2*pi, 0.1)".'
        )
    if len(pos) == 1:
        start, stop, step = 0.0, pos[0], kw.get("step", 1.0)
    elif len(pos) == 2:
        start, stop, step = pos[0], pos[1], kw.get("step", 1.0)
    elif len(pos) == 3:
        start, stop, step = pos[0], pos[1], pos[2]
    else:
        start = kw.get("start", 0.0)
        stop = kw.get("stop")
        step = kw.get("step", 1.0)
    if stop is None or step is None or start is None:
        raise ValueError(
            f'{name} arange needs stop. Example: {name}="arange(0, 2*pi, 0.1)".'
        )
    step_f = float(step)
    if step_f == 0.0 or not math.isfinite(step_f):
        raise ValueError(f"{name} arange step must be a non-zero finite number.")
    start_f = float(start)
    stop_f = float(stop)
    span = stop_f - start_f
    if math.isfinite(span) and ((span > 0 and step_f > 0) or (span < 0 and step_f < 0)):
        est = abs(span / step_f)
        if not math.isfinite(est) or est > _MAX_SAMPLES:
            shown = int(est) if math.isfinite(est) and est < 1e12 else _MAX_SAMPLES + 1
            raise ValueError(
                f"{name} arange would make {shown} points "
                f"(max {_MAX_SAMPLES}). Example: {name}=\"arange(0, 2*pi, 0.1)\"."
            )
    values = np.arange(start_f, stop_f, step_f, dtype=float)
    if values.size > _MAX_SAMPLES:
        raise ValueError(
            f"{name} arange would make {values.size} points "
            f"(max {_MAX_SAMPLES}). Example: {name}=\"arange(0, 2*pi, 0.1)\"."
        )
    if values.size < 2:
        raise ValueError(f"{name} arange needs at least 2 points.")
    return values


def _looks_like_formulas(raw: Any) -> bool:
    """True when every piece is a named expression, not a float list."""
    pieces = _split_plot_expressions(raw)
    if not pieces:
        return False
    for piece in pieces:
        try:
            float(piece)
        except ValueError:
            if not re.search(r"[A-Za-z]", piece):
                return False
            continue
        return False
    return True


def _promote_range_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """9B sends xs=linspace(...) and ys=sin(x), cos(x) instead of expr."""
    path_str = str(kwargs.get("path") or "").strip()
    if path_str and not _looks_like_chart_out(path_str):
        return kwargs
    action = str(kwargs.get("action") or "line").strip().lower()
    if action not in {"line", "scatter", "residuals", "subplots"}:
        return kwargs
    if _split_plot_expressions(kwargs.get("expr")):
        return kwargs
    xs = _inline_pair(kwargs, primary="xs", alias="x")
    ys = _inline_pair(kwargs, primary="ys", alias="y")
    if not _looks_like_formulas(ys):
        return kwargs
    ranged = parse_range_call(xs, name="xs")
    out = dict(kwargs)
    if ranged is not None:
        if _missing_bound(out.get("xmin")):
            out["xmin"] = float(ranged[0])
        if _missing_bound(out.get("xmax")):
            out["xmax"] = float(ranged[-1])
        if not out.get("samples"):
            out["samples"] = int(ranged.size)
    elif _missing_bound(out.get("xmin")) or _missing_bound(out.get("xmax")):
        return kwargs
    out["expr"] = ys
    out.pop("xs", None)
    out.pop("ys", None)
    if parse_range_call(out.get("x"), name="x") is not None:
        out.pop("x", None)
    if _looks_like_formulas(out.get("y")):
        out.pop("y", None)
    return out


def _split_top_level_commas(text: str) -> list[str]:
    """Commas outside (), [], {}, and quotes. atan2(y, x) stays one piece."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\":
                if i + 1 < len(text):
                    buf.append(text[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            if depth:
                depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            piece = "".join(buf).strip()
            if piece:
                parts.append(piece)
            buf = []
        else:
            buf.append(ch)
        i += 1
    piece = "".join(buf).strip()
    if piece:
        parts.append(piece)
    return parts


def _unwrap_parens(text: str) -> str | None:
    """The inside of a wrapping (...) pair, or None when the parens are not a wrapper."""
    if len(text) < 2 or text[0] != "(" or text[-1] != ")":
        return None
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if i != len(text) - 1:
                    return None
                return text[1:-1].strip()
    return None


def _expression_pieces(text: str) -> list[str]:
    parsed = _literal_structure(text)
    if isinstance(parsed, (list, tuple)) and parsed and all(
        isinstance(part, (str, int, float)) and not isinstance(part, bool) for part in parsed
    ):
        return [str(part).strip() for part in parsed if str(part).strip()]
    inner = _unwrap_parens(text)
    if inner is not None:
        inner_parts = _split_top_level_commas(inner)
        if len(inner_parts) > 1:
            return inner_parts
    return _split_top_level_commas(text)


def _split_plot_expressions(raw: Any) -> list[str]:
    """One expression, or several the model joined with a comma or a tuple.

    Each piece is still parsed by parse_cas_expr. This only separates them.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, (list, tuple)):
                parts.extend(_split_plot_expressions(item))
            else:
                one = str(item).strip()
                if one:
                    parts.append(one)
        return parts
    text = str(raw).strip()
    if not text:
        return []
    return _expression_pieces(text) or [text]


def _missing_bound(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str):
        return not raw.strip()
    if isinstance(raw, (list, tuple)):
        return len(raw) == 0
    return False


def _bound_pair(raw: Any) -> tuple[Any, Any] | None:
    """xmin='(0, 10)' or xmin='0, 10' names both ends. A single endpoint stays None."""
    if isinstance(raw, (list, tuple)):
        if len(raw) == 2:
            return raw[0], raw[1]
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    parsed = _literal_structure(text)
    if isinstance(parsed, (list, tuple)) and len(parsed) == 2:
        return parsed[0], parsed[1]
    pieces = _split_top_level_commas(_unwrap_parens(text) or text)
    if len(pieces) == 2:
        return pieces[0], pieces[1]
    return None


def _plot_bounds(xmin: Any, xmax: Any) -> tuple[float, float]:
    """lo, hi. One key may hold both ends; two single endpoints stay as they were."""
    left = _bound_pair(xmin)
    right = _bound_pair(xmax)
    if left is not None and (_missing_bound(xmax) or right is not None):
        lo_raw, hi_raw = left
    elif right is not None and _missing_bound(xmin):
        lo_raw, hi_raw = right
    else:
        lo_raw = "" if xmin is None else xmin
        hi_raw = "" if xmax is None else xmax
    return (
        plot_range_value(lo_raw, name="xmin"),
        plot_range_value(hi_raw, name="xmax"),
    )


def sample_expression(
    expr: str,
    *,
    var: str = "x",
    lo: float,
    hi: float,
    samples: int = _DEFAULT_SAMPLES,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate a one-variable expression across [lo, hi] into plottable arrays.

    `parse_cas_expr` does the parsing on purpose, it whitelists an AST and then
    parses into a locked namespace with empty builtins. Nothing here may reach
    `eval` or bare `sympify`: this field is reachable from any turn, so a hole
    in it is remote code execution behind a chart request.
    """
    from arelis.tools.cas import parse_cas_expr

    np = _numpy()
    text = str(expr or "").strip()
    if not text:
        raise ValueError("Missing expr.")
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        raise ValueError(f"Need xmin < xmax, got xmin={lo} and xmax={hi}.")
    parsed = parse_cas_expr(text)

    import sympy as sp

    symbol = sp.Symbol(str(var or "x").strip() or "x")
    free = {s for s in parsed.free_symbols if s.name != symbol.name}
    if free:
        names = ", ".join(sorted(s.name for s in free))
        raise ValueError(
            f"plot draws one variable against {symbol.name}; {names} "
            f"{'is' if len(free) == 1 else 'are'} unbound. "
            "Give a single-variable expression, or pass xs/ys."
        )
    count = max(2, min(int(samples or _DEFAULT_SAMPLES), _MAX_SAMPLES))
    xs = np.linspace(lo, hi, count)
    fn = sp.lambdify(symbol, parsed, modules=["numpy"])
    with np.errstate(all="ignore"):
        try:
            raw = fn(xs)
        except Exception as exc:
            raise ValueError(f"Could not evaluate {text!r}: {exc}") from exc
        # A constant expression lambdifies to a scalar, not an array.
        ys = np.broadcast_to(np.asarray(raw, dtype=float), xs.shape).astype(float)
        # Complex results (sqrt of a negative) are not plottable on a real axis;
        # asarray(dtype=float) would raise, so they arrive here as nan instead.
        ys = np.where(np.isfinite(ys), ys, np.nan)
    mask = np.isfinite(ys)
    if not mask.any():
        raise ValueError(f"{text!r} has no finite values between {lo} and {hi}, check the range.")
    return xs[mask], ys[mask]


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
        "a PNG. The file lands in the project's plots/ directory when one "
        "is open, otherwise under outputs/plots/. Actions: "
        "line, scatter, residuals, histogram, bar, subplots. For a "
        "CSV/TSV/Excel file pass path plus column names: x and y for line or "
        "scatter; y alone for histogram; x (categories) and y (values) for bar. "
        "For a tiny series pass xs and ys as comma-separated numbers "
        "(or a JSON/[1,2,3] list; x/y are aliases for xs/ys when there is "
        "no path), or ys alone for histogram, or categories and values "
        "for bar. To draw a "
        "formula (sin(x), x^2) pass expr with xmin and xmax, never type the "
        "numbers out yourself. path= is the table, never the PNG, that name "
        "is out=. histogram takes one numeric series (y or ys) with optional "
        "bins. bar draws categories against values, not a line chart. "
        "subplots combines two or more panels in one figure, pass panels as "
        "comma-separated kinds (e.g. line,histogram) with the same data. "
        "look=poster, paper, or slide is 300 dpi, larger type, a colour-blind "
        "palette, and an SVG and a PDF beside the PNG. "
        "residuals fits a straight line (least squares) and plots data+fit "
        "plus residuals, do not invent a trend or draw an ASCII chart. This "
        "is not Python: do not pass code or matplotlib. Allow is required. Do "
        "not use image (Comfy) for data."
    )
    risk = "write"

    @staticmethod
    def _arg_fail(exc: BaseException, *, fail_class: str = "fail:args") -> ToolResult:
        return _arg_error(exc, output=str(exc).strip(), fail_class=fail_class)

    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "line",
                    "scatter",
                    "residuals",
                    "histogram",
                    "bar",
                    "subplots",
                ],
                "description": "Chart kind (default line)",
            },
            "path": {
                "type": "string",
                "description": (
                    "Table file under a workspace root (CSV/TSV/JSON/Excel). "
                    "Not the PNG, that is out="
                ),
            },
            "x": {
                "type": "string",
                "description": (
                    "Column name for the horizontal axis, or (with no path) "
                    "inline x numbers as an alias for xs"
                ),
            },
            "y": {
                "type": "string",
                "description": (
                    "Column name for the vertical axis, or the only column "
                    "for histogram; with no path, inline y numbers as an "
                    "alias for ys"
                ),
            },
            "categories": {
                "type": "string",
                "description": (
                    "Category labels for bar when there is no file "
                    "(comma-separated, or a JSON/list string)"
                ),
            },
            "values": {
                "type": "string",
                "description": (
                    "Numbers for bar when there is no file "
                    "(comma-separated, JSON array, or [1, 2, 3])"
                ),
            },
            "bins": {
                "type": "integer",
                "description": "Bin count for histogram (optional)",
            },
            "panels": {
                "type": "string",
                "description": (
                    "For subplots: comma-separated panel kinds, e.g. "
                    "line,histogram or scatter,bar"
                ),
            },
            "expr": {
                "type": "string",
                "description": (
                    "A one-variable formula to draw, e.g. sin(x) or x^2-3*x. "
                    "Needs xmin and xmax. Use this instead of typing the "
                    "numbers out yourself"
                ),
            },
            "xmin": {
                "type": "string",
                "description": "Start of the range for expr. Accepts pi, 2pi, pi/2",
            },
            "xmax": {
                "type": "string",
                "description": "End of the range for expr. Accepts pi, 2pi, pi/2",
            },
            "samples": {
                "type": "integer",
                "description": "Points to evaluate for expr (default 400)",
            },
            "var": {
                "type": "string",
                "description": "Variable name in expr (default x)",
            },
            "xs": {
                "type": "string",
                "description": (
                    "X numbers when there is no file (comma-separated, "
                    "JSON array, or [1, 2, 3])"
                ),
            },
            "ys": {
                "type": "string",
                "description": (
                    "Y numbers when there is no file (comma-separated, "
                    "JSON array, or [1, 2, 3])"
                ),
            },
            "title": {"type": "string", "description": "Chart title"},
            "xlabel": {"type": "string", "description": "Horizontal axis label"},
            "ylabel": {"type": "string", "description": "Vertical axis label"},
            "out": {
                "type": "string",
                "description": (
                    "Output file name only (png). Lands in the room's plots/ "
                    "folder, or outputs/plots/ in orbit. poster, paper, and "
                    "slide also write svg and pdf beside it"
                ),
            },
            "look": {
                "type": "string",
                "enum": ["default", "poster", "paper", "slide"],
                "description": (
                    "default, poster, paper, or slide. Print looks are 300 dpi "
                    "plus SVG and PDF."
                ),
            },
        },
        "required": [],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots,
        rooms: Any = None,
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
            return room_dir, "the project's plots folder"
        room = None if self.rooms is None else self.rooms.active
        if room is not None and room.root:
            return (
                self.drop_dir(),
                "the shared drop tray",
            )
        if room is not None:
            return (
                self.drop_dir(),
                "the shared drop tray",
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
        kwargs = normalize_plot_args(dict(kwargs))
        try:
            kwargs = _promote_range_args(kwargs)
        except (ValueError, TypeError) as exc:
            return self._arg_fail(exc)
        action = str(kwargs.get("action") or "line").strip().lower()
        if action not in _ACTIONS:
            return self._arg_fail(
                ValueError(
                    "Unknown action. Use line, scatter, residuals, histogram, "
                    "bar, or subplots."
                ),
                fail_class="fail:action",
            )
        try:
            look = _parse_look(kwargs.get("look"))
        except ValueError as exc:
            return self._arg_fail(exc)
        kwargs["look"] = look
        title = str(kwargs.get("title") or "").strip()
        try:
            if action == "histogram":
                values, ylabel, source = self._histogram_series(kwargs)
                xlabel = str(kwargs.get("xlabel") or "").strip() or "bin"
                ylabel = str(kwargs.get("ylabel") or ylabel).strip() or ylabel
                n = len(values)

                def _draw() -> tuple:
                    return self._draw_histogram(
                        values,
                        title=title,
                        xlabel=xlabel,
                        ylabel=ylabel,
                        kwargs=kwargs,
                    )

            elif action == "bar":
                cats, values, xlabel, ylabel, source = self._bar_series(kwargs)
                xlabel = str(kwargs.get("xlabel") or xlabel).strip() or xlabel
                ylabel = str(kwargs.get("ylabel") or ylabel).strip() or ylabel
                n = len(values)

                def _draw() -> tuple:
                    return self._draw_bar(
                        cats,
                        values,
                        title=title,
                        xlabel=xlabel,
                        ylabel=ylabel,
                        kwargs=kwargs,
                    )

            elif action == "subplots":
                draws, source = self._subplot_draws(kwargs)
                _apply_axis_labels(draws, kwargs)
                n = max(len(draw.y) for draw in draws)

                def _draw() -> tuple:
                    return self._draw_subplots(draws, title=title, kwargs=kwargs)

            else:
                path_str = str(kwargs.get("path") or "").strip()
                if path_str and _looks_like_chart_out(path_str):
                    path_str = ""
                exprs = (
                    _split_plot_expressions(kwargs.get("expr")) if not path_str else []
                )
                if len(exprs) > 1 and action in {"line", "scatter"}:
                    lines, lo, hi = self._sample_lines(kwargs, exprs)
                    xlabel = str(kwargs.get("xlabel") or kwargs.get("var") or "x").strip() or "x"
                    ylabel = str(kwargs.get("ylabel") or "").strip() or ", ".join(
                        label for _x, _y, label in lines
                    )
                    n = max(len(x) for x, _y, _label in lines)
                    source = "; ".join(
                        f"{label} over [{lo:g}, {hi:g}]" for _x, _y, label in lines
                    )

                    def _draw() -> tuple:
                        return self._draw_lines(
                            action,
                            lines,
                            title=title,
                            xlabel=xlabel,
                            ylabel=ylabel,
                            kwargs=kwargs,
                        )

                else:
                    x, y, xlabel, ylabel, source = self._series(kwargs)
                    xlabel = str(kwargs.get("xlabel") or xlabel).strip() or xlabel
                    ylabel = str(kwargs.get("ylabel") or ylabel).strip() or ylabel
                    n = len(x)

                    def _draw() -> tuple:
                        return self._draw(
                            action,
                            x,
                            y,
                            title=title,
                            xlabel=xlabel,
                            ylabel=ylabel,
                            kwargs=kwargs,
                        )
        except (ValueError, TypeError, PermissionError, OSError) as exc:
            return self._arg_fail(exc)
        try:
            dest, extra = _draw()
        except ValueError as exc:
            return self._arg_fail(exc, fail_class="fail:draw")
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"Could not draw that chart: {exc}",
                data={"fail_class": "fail:other"},
            )
        shown = display_path(dest)
        _folder, where = self.out_dir()
        kind = f"{action}, {n} points"
        if look != "default":
            kind = f"{kind}, {look} look"
        bits = [f"Wrote {shown} ({kind}) in {where}."]
        if extra:
            bits.append(extra)
        bits.append("Open that file, that chart is from this turn, not a picture I imagined.")
        return ToolResult(
            ok=True,
            output=" ".join(bits),
            data={
                "action": action,
                "path": shown,
                "abs_path": str(dest.resolve()),
                "n": n,
                "source": source,
                "where": where,
                "look": look,
                "dpi": 300 if look != "default" else 120,
            },
        )

    def _resolve_table(self, path_str: str) -> ResolvedPath:
        """This turn's cell work folder, then workspace, then the drop tray.

        Same order as analyze. Cell writes land under outputs/work/<id>/.
        Document writes still land in the drop tray, which sits outside the
        project, so a bare workspace read joins that string onto the project
        and misses the file. Parent segments are refused by the reported-path
        check, same as analyze.
        """
        work = resolve_cell_work_file(path_str, suffixes=set(_TABLE_SUFFIXES))
        if work:
            path = Path(work)
            return ResolvedPath(path=path, root_name="outputs", root=path.parent)
        try:
            hit = self.workspace.resolve_read(path_str)
        except Exception as first:
            drop = resolve_drop_file(path_str, suffixes=set(_TABLE_SUFFIXES))
            if drop:
                path = Path(drop)
                return ResolvedPath(path=path, root_name="outputs", root=path.parent)
            raise first
        if hit.path.is_file():
            return hit
        reported = resolve_reported_document_path(path_str)
        if reported:
            path = Path(reported)
            return ResolvedPath(path=path, root_name="outputs", root=path.parent)
        drop = resolve_drop_file(path_str, suffixes=set(_TABLE_SUFFIXES))
        if drop:
            path = Path(drop)
            return ResolvedPath(path=path, root_name="outputs", root=path.parent)
        return hit

    def _series(self, kwargs: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, str, str, str]:
        path_str = str(kwargs.get("path") or "").strip()
        png_as_path = bool(path_str and _looks_like_chart_out(path_str))
        if png_as_path:
            if not str(kwargs.get("out") or "").strip():
                kwargs["out"] = Path(path_str.replace("\\", "/")).name
            path_str = ""
        if path_str:
            resolved = self._resolve_table(path_str)
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
                raise ValueError(f"path needs x and y column names. Columns: {cols}.")
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
        exprs = _split_plot_expressions(kwargs.get("expr"))
        if exprs:
            if len(exprs) != 1:
                raise ValueError(
                    "Send one expression for this chart, or subplots with "
                    "one expression per panel."
                )
            lo, hi = _plot_bounds(kwargs.get("xmin", ""), kwargs.get("xmax", ""))
            var = str(kwargs.get("var") or "x").strip() or "x"
            try:
                samples = int(kwargs.get("samples") or _DEFAULT_SAMPLES)
            except (TypeError, ValueError):
                samples = _DEFAULT_SAMPLES
            expr = exprs[0]
            x, y = sample_expression(expr, var=var, lo=lo, hi=hi, samples=samples)
            return x, y, var, expr, f"{expr} over [{lo:g}, {hi:g}]"
        xs = _inline_pair(kwargs, primary="xs", alias="x")
        ys = _inline_pair(kwargs, primary="ys", alias="y")
        missing_xs = _missing_inline(xs)
        missing_ys = _missing_inline(ys)
        if missing_xs or missing_ys:
            if png_as_path:
                raise ValueError(
                    'path is the PNG name. Use out= for the file and '
                    'xs="1,2,3", ys="1,4,9" (or xs/ys lists), or path= to a '
                    "CSV with x and y columns."
                )
            if missing_xs and missing_ys:
                raise ValueError(
                    'Need xs and ys. Use xs="1,2,3", ys="1,4,9" (or xs/ys '
                    "lists), or a CSV via path= with x and y column names. "
                    "The PNG name is out=, not path=."
                )
            if missing_xs:
                raise ValueError(
                    'Missing xs. Use xs="1,2,3" (or an xs list) together with ys.'
                )
            raise ValueError(
                'Missing ys. Use ys="1,4,9" (or a ys list) together with xs.'
            )
        ranged = parse_range_call(xs, name="xs")
        x = ranged if ranged is not None else _parse_numbers(xs, name="xs")
        if _looks_like_formulas(ys):
            raise ValueError(
                'ys is a formula, not numbers. Use expr="sin(x), cos(x)" '
                "with xmin=0, xmax=2*pi. Example: plot(action=line, "
                'expr="sin(x), cos(x)", xmin=0, xmax=2*pi).'
            )
        y = _parse_numbers(ys, name="ys")
        if len(x) != len(y):
            raise ValueError(
                f"xs and ys must be the same length "
                f"(got {len(x)} in xs, {len(y)} in ys). "
                'Pass matching lists, or use expr="sin(x), cos(x)", '
                "xmin=0, xmax=2*pi instead of pasting python output."
            )
        if len(x) < 2:
            raise ValueError("Need at least two points in xs/ys.")
        return x, y, "x", "y", "inline"

    def _histogram_series(
        self, kwargs: dict[str, Any]
    ) -> tuple[np.ndarray, str, str]:
        path_str = str(kwargs.get("path") or "").strip()
        png_as_path = bool(path_str and _looks_like_chart_out(path_str))
        if png_as_path:
            if not str(kwargs.get("out") or "").strip():
                kwargs["out"] = Path(path_str.replace("\\", "/")).name
            path_str = ""
        if path_str:
            resolved = self._resolve_table(path_str)
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
            y_name = str(kwargs.get("y") or "").strip()
            if not y_name:
                cols = ", ".join(str(c) for c in frame.columns[:12])
                raise ValueError(f"histogram needs a y column name. Columns: {cols}.")
            values = _column(frame, y_name)
            np = _numpy()
            values = values[np.isfinite(values)]
            if len(values) < 1:
                raise ValueError("Need at least one numeric value in the y column.")
            if len(values) > _MAX_ROWS:
                values = values[:_MAX_ROWS]
            display = resolved.qualified(multi=len(self.workspace) > 1)
            return values, y_name, display
        ys = _inline_pair(kwargs, primary="ys", alias="y")
        if _missing_inline(ys):
            raise ValueError(
                'histogram needs ys="1,2,3" (or a ys list), or a table path '
                "with y= column name."
            )
        values = _parse_numbers(ys, name="ys")
        if len(values) < 1:
            raise ValueError("Need at least one number in ys.")
        return values, "count", "inline"

    def _bar_series(
        self, kwargs: dict[str, Any]
    ) -> tuple[list[str], np.ndarray, str, str, str]:
        path_str = str(kwargs.get("path") or "").strip()
        png_as_path = bool(path_str and _looks_like_chart_out(path_str))
        if png_as_path:
            if not str(kwargs.get("out") or "").strip():
                kwargs["out"] = Path(path_str.replace("\\", "/")).name
            path_str = ""
        if path_str:
            resolved = self._resolve_table(path_str)
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
                raise ValueError(f"bar needs x and y column names. Columns: {cols}.")
            cats = _column_labels(frame, x_name)
            values = _column(frame, y_name)
            np = _numpy()
            mask = np.isfinite(values)
            cats = [cats[i] for i in range(len(cats)) if mask[i]]
            values = values[mask]
            if len(values) < 1:
                raise ValueError("Need at least one category with a numeric value.")
            if len(values) > _MAX_ROWS:
                cats = cats[:_MAX_ROWS]
                values = values[:_MAX_ROWS]
            display = resolved.qualified(multi=len(self.workspace) > 1)
            return cats, values, x_name, y_name, display
        cats_raw = kwargs.get("categories")
        vals_raw = kwargs.get("values")
        if _missing_inline(cats_raw) or _missing_inline(vals_raw):
            which = []
            if _missing_inline(cats_raw):
                which.append("categories")
            if _missing_inline(vals_raw):
                which.append("values")
            raise ValueError(
                f"bar is missing {', '.join(which)}. Use "
                'categories="a,b", values="1,2" (or lists), or a table path '
                "with x and y column names."
            )
        cats = _parse_labels(cats_raw, name="categories")
        values = _parse_numbers(vals_raw, name="values")
        if len(cats) != len(values):
            raise ValueError("categories and values must be the same length.")
        if len(cats) < 1:
            raise ValueError("Need at least one bar.")
        return cats, values, "category", "value", "inline"

    def _sample_lines(
        self, kwargs: dict[str, Any], exprs: list[str]
    ) -> tuple[list[tuple[Any, Any, str]], float, float]:
        lo, hi = _plot_bounds(kwargs.get("xmin", ""), kwargs.get("xmax", ""))
        var = str(kwargs.get("var") or "x").strip() or "x"
        try:
            samples = int(kwargs.get("samples") or _DEFAULT_SAMPLES)
        except (TypeError, ValueError):
            samples = _DEFAULT_SAMPLES
        lines: list[tuple[Any, Any, str]] = []
        for expr in exprs:
            x, y = sample_expression(expr, var=var, lo=lo, hi=hi, samples=samples)
            lines.append((x, y, expr))
        return lines, lo, hi

    def _subplot_series(
        self, kwargs: dict[str, Any], panels: list[str]
    ) -> tuple[np.ndarray, np.ndarray, list[str] | None, str, str, str]:
        needs_xy = any(k in {"line", "scatter"} for k in panels)
        needs_hist = "histogram" in panels
        needs_bar = "bar" in panels
        if needs_bar and not needs_xy:
            cats, values, xlabel, ylabel, source = self._bar_series(kwargs)
            x = _numpy().arange(len(values), dtype=float)
            return x, values, cats, xlabel, ylabel, source
        if needs_hist and not needs_xy and not needs_bar:
            values, ylabel, source = self._histogram_series(kwargs)
            x = _numpy().arange(len(values), dtype=float)
            return x, values, None, "index", ylabel, source
        x, y, xlabel, ylabel, source = self._series(kwargs)
        cats = None
        if needs_bar:
            path_str = str(kwargs.get("path") or "").strip()
            if path_str and not _looks_like_chart_out(path_str):
                frame = _load_table(self._resolve_table(path_str).path)
                x_name = str(kwargs.get("x") or "").strip()
                if x_name and x_name in frame.columns:
                    cats = _column_labels(frame, x_name)
                    np = _numpy()
                    mask = np.isfinite(y)
                    cats = [cats[i] for i in range(len(cats)) if mask[i]]
            elif not _missing_inline(kwargs.get("categories")):
                cats = _parse_labels(kwargs.get("categories"), name="categories")
        return x, y, cats, xlabel, ylabel, source

    def _subplot_draws(
        self, kwargs: dict[str, Any]
    ) -> tuple[list[_PanelDraw], str]:
        kinds, specs = _read_panels(kwargs.get("panels"))
        if specs is not None:
            draws = [
                self._panel_from_spec(kind, spec, kwargs)
                for kind, spec in zip(kinds, specs, strict=True)
            ]
            return draws, "inline"
        ys_raw = _inline_pair(kwargs, primary="ys", alias="y")
        xs_raw = _inline_pair(kwargs, primary="xs", alias="x")
        nested_ys = _as_nested_lists(ys_raw)
        if nested_ys is None:
            nested_ys = _semicolon_series(ys_raw)
        nested_xs = _as_nested_lists(xs_raw)
        if nested_xs is None:
            nested_xs = _semicolon_series(xs_raw)
        if nested_ys is None and nested_xs is None:
            exprs = _split_plot_expressions(kwargs.get("expr"))
            if len(exprs) > 1:
                if len(exprs) != len(kinds):
                    raise ValueError(
                        f"expr has {len(exprs)} expressions and panels has {len(kinds)}. "
                        "Send one expression per panel."
                    )
                draws = []
                for kind, one in zip(kinds, exprs, strict=True):
                    local = dict(kwargs)
                    local["expr"] = one
                    local.pop("path", None)
                    draws.append(self._one_panel(kind, local))
                return draws, "inline"
            x, y, cats, xlabel, ylabel, source = self._subplot_series(kwargs, kinds)
            draws = [
                _PanelDraw(kind, x, y, cats, xlabel, ylabel) for kind in kinds
            ]
            return draws, source
        if nested_ys is not None and len(nested_ys) != len(kinds):
            raise ValueError(
                f"ys has {len(nested_ys)} lists and panels has {len(kinds)}. "
                "Send one ys list per panel, or one flat list for every panel."
            )
        if nested_xs is not None and len(nested_xs) != len(kinds):
            raise ValueError(
                f"xs has {len(nested_xs)} lists and panels has {len(kinds)}. "
                "Send one xs list per panel, or one flat list for every panel."
            )
        draws: list[_PanelDraw] = []
        for index, kind in enumerate(kinds):
            local = dict(kwargs)
            local.pop("path", None)
            if nested_ys is not None:
                local["ys"] = nested_ys[index]
                local.pop("y", None)
            if nested_xs is not None:
                local["xs"] = nested_xs[index]
                local.pop("x", None)
            draws.append(self._one_panel(kind, local))
        return draws, "inline"

    def _panel_from_spec(
        self, kind: str, spec: dict[str, Any], kwargs: dict[str, Any]
    ) -> _PanelDraw:
        local = dict(kwargs)
        own = False
        for key in ("xs", "ys", "x", "y", "categories", "values", "expr", "xmin", "xmax"):
            if key in spec and not _missing_inline(spec.get(key)):
                local[key] = spec[key]
                if key in {"xs", "ys", "x", "y", "categories", "values", "expr"}:
                    own = True
        if own:
            local.pop("path", None)
        return self._one_panel(kind, local)

    def _one_panel(self, kind: str, kwargs: dict[str, Any]) -> _PanelDraw:
        if kind == "histogram":
            values, ylabel, _source = self._histogram_series(kwargs)
            x = _numpy().arange(len(values), dtype=float)
            return _PanelDraw(kind, x, values, None, "index", ylabel)
        if kind == "bar":
            cats, values, xlabel, ylabel, _source = self._bar_series(kwargs)
            x = _numpy().arange(len(values), dtype=float)
            return _PanelDraw(kind, x, values, cats, xlabel, ylabel)
        x, y, xlabel, ylabel, _source = self._series(kwargs)
        return _PanelDraw(kind, x, y, None, xlabel, ylabel)

    def _draw_histogram(
        self,
        values: np.ndarray,
        *,
        title: str,
        xlabel: str,
        ylabel: str,
        kwargs: dict[str, Any],
    ) -> tuple[Path, str]:
        folder, _where = self.out_dir()
        dest = self._dest(kwargs, "histogram", folder)
        ensure(dest.parent)
        look = str(kwargs.get("look") or "default")
        bins = _parse_bins(kwargs.get("bins"))
        with _look_context(look):
            fig = _open_figure(_figure_size(look), look)
            ax = fig.add_subplot(111)
            ax.hist(
                values,
                bins=bins,
                edgecolor="0.3",
                linewidth=0.6,
                **_mark_color(look),
            )
            if title:
                ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel or "count")
            ax.grid(True, alpha=0.3, axis="y")
            fig.tight_layout()
            note = _save_figure(fig, dest, look)
        return dest, note

    def _draw_bar(
        self,
        cats: list[str],
        values: np.ndarray,
        *,
        title: str,
        xlabel: str,
        ylabel: str,
        kwargs: dict[str, Any],
    ) -> tuple[Path, str]:
        folder, _where = self.out_dir()
        dest = self._dest(kwargs, "bar", folder)
        ensure(dest.parent)
        look = str(kwargs.get("look") or "default")
        with _look_context(look):
            fig = _open_figure(_figure_size(look), look)
            ax = fig.add_subplot(111)
            positions = _numpy().arange(len(cats))
            ax.bar(
                positions,
                values,
                width=0.65,
                edgecolor="0.3",
                linewidth=0.6,
                **_mark_color(look),
            )
            ax.set_xticks(positions)
            ax.set_xticklabels(cats, rotation=0 if len(cats) <= 6 else 25, ha="center")
            if title:
                ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3, axis="y")
            fig.tight_layout()
            note = _save_figure(fig, dest, look)
        return dest, note

    def _draw_subplots(
        self,
        draws: list[_PanelDraw],
        *,
        title: str,
        kwargs: dict[str, Any],
    ) -> tuple[Path, str]:
        folder, _where = self.out_dir()
        dest = self._dest(kwargs, "subplots", folder)
        ensure(dest.parent)
        look = str(kwargs.get("look") or "default")
        n = len(draws)
        rows, cols = _subplot_grid(n)
        bins = _parse_bins(kwargs.get("bins"))
        with _look_context(look):
            fig = _open_figure((4.2 * cols, 4.0 * rows), look)
            for idx, draw in enumerate(draws):
                ax = fig.add_subplot(rows, cols, idx + 1)
                _draw_panel(
                    ax,
                    draw.kind,
                    draw.x,
                    draw.y,
                    cats=draw.cats,
                    bins=bins,
                    xlabel=draw.xlabel,
                    ylabel=draw.ylabel,
                    look=look,
                )
            if title:
                fig.suptitle(title)
            fig.tight_layout()
            note = _save_figure(fig, dest, look)
        panels_note = f"Panels: {', '.join(draw.kind for draw in draws)}."
        if note:
            panels_note = f"{panels_note} {note}"
        return dest, panels_note

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
        look = str(kwargs.get("look") or "default")
        if action == "residuals":
            extra = _residuals_figure(
                dest, x, y, title=title, xlabel=xlabel, ylabel=ylabel, look=look
            )
        else:
            width, marker = _stroke(look)
            with _look_context(look):
                fig = _open_figure(_figure_size(look), look)
                ax = fig.add_subplot(111)
                if action == "scatter":
                    ax.scatter(
                        x,
                        y,
                        s=18 if look == "default" else 28,
                        alpha=0.85,
                        **_mark_color(look),
                    )
                else:
                    ax.plot(
                        x,
                        y,
                        marker="o",
                        linewidth=width,
                        markersize=marker,
                        **_mark_color(look),
                    )
                if title:
                    ax.set_title(title)
                ax.set_xlabel(xlabel)
                ax.set_ylabel(ylabel)
                ax.grid(True, alpha=0.3)
                fig.tight_layout()
                extra = _save_figure(fig, dest, look)
        return dest, extra

    def _draw_lines(
        self,
        action: str,
        lines: list[tuple[Any, Any, str]],
        *,
        title: str,
        xlabel: str,
        ylabel: str,
        kwargs: dict[str, Any],
    ) -> tuple[Path, str]:
        """Several expressions on one chart. No new argument: expr already held them."""
        folder, _where = self.out_dir()
        dest = self._dest(kwargs, action, folder)
        ensure(dest.parent)
        look = str(kwargs.get("look") or "default")
        width, marker = _stroke(look)
        with _look_context(look):
            fig = _open_figure(_figure_size(look), look)
            ax = fig.add_subplot(111)
            for index, (x, y, label) in enumerate(lines):
                style = _mark_color(look, index)
                if action == "scatter":
                    ax.scatter(
                        x,
                        y,
                        s=18 if look == "default" else 28,
                        alpha=0.85,
                        label=label,
                        **style,
                    )
                else:
                    ax.plot(
                        x,
                        y,
                        marker="o",
                        linewidth=width,
                        markersize=marker,
                        label=label,
                        **style,
                    )
            if len(lines) > 1:
                ax.legend()
            if title:
                ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            extra = _save_figure(fig, dest, look)
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


def _parse_labels(raw: Any, *, name: str) -> list[str]:
    # Same shapes as numbers: list, JSON array, [a,b], or comma-separated.
    return _inline_parts(raw, name=name, kind="label")


def _parse_bins(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        bins = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("bins must be a positive integer.") from exc
    if bins < 1:
        raise ValueError("bins must be at least 1.")
    return min(bins, 200)


class _PanelDraw:
    """One panel's own series. Shared charts copy the same arrays onto each."""

    def __init__(
        self,
        kind: str,
        x: Any,
        y: Any,
        cats: list[str] | None,
        xlabel: str,
        ylabel: str,
    ) -> None:
        self.kind = kind
        self.x = x
        self.y = y
        self.cats = cats
        self.xlabel = xlabel
        self.ylabel = ylabel


def _apply_axis_labels(draws: list[_PanelDraw], kwargs: dict[str, Any]) -> None:
    xlabel = str(kwargs.get("xlabel") or "").strip()
    ylabel = str(kwargs.get("ylabel") or "").strip()
    if not xlabel and not ylabel:
        return
    for draw in draws:
        if xlabel:
            draw.xlabel = xlabel
        if ylabel:
            draw.ylabel = ylabel


_KIND_ALIASES = {
    "line": "line",
    "line chart": "line",
    "line plot": "line",
    "plot": "line",
    "scatter": "scatter",
    "scatter plot": "scatter",
    "histogram": "histogram",
    "hist": "histogram",
    "bar": "bar",
    "bar chart": "bar",
}


def _literal_structure(text: str) -> Any:
    """A JSON or Python list/dict, or None when the text is a plain series."""
    if not text or text[0] not in "[{(":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, TypeError):
        return None


def _as_nested_lists(raw: Any) -> list[Any] | None:
    """A list of lists, including a JSON or Python string of that shape."""
    if isinstance(raw, (list, tuple)):
        if raw and all(isinstance(part, (list, tuple)) for part in raw):
            return [list(part) for part in raw]
        return None
    if not isinstance(raw, str):
        return None
    parsed = _literal_structure(raw.strip())
    if (
        isinstance(parsed, (list, tuple))
        and parsed
        and all(isinstance(part, (list, tuple)) for part in parsed)
    ):
        return [list(part) for part in parsed]
    return None


def _semicolon_series(raw: Any) -> list[str] | None:
    """'1,2,3;4,5,6' is two series. '1;2;3' stays one series."""
    if not isinstance(raw, str) or ";" not in raw:
        return None
    parts = [part.strip() for part in raw.split(";") if part.strip()]
    if len(parts) < 2 or not all("," in part for part in parts):
        return None
    return parts


def _clean_kind(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    text = text.strip("[]()\"'` ")
    text = " ".join(text.split())
    return _KIND_ALIASES.get(text, text)


def _coerce_panel_items(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return list(raw)
    text = str(raw).strip()
    if not text:
        return []
    parsed = _literal_structure(text)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, (list, tuple)):
        return list(parsed)
    return [part.strip() for part in text.split(",") if part.strip()]


def _check_panel_kinds(kinds: list[str]) -> None:
    if any(not kind for kind in kinds):
        raise ValueError(
            "subplots needs a kind on every panel: line, scatter, histogram, or bar."
        )
    if len(kinds) < 2:
        raise ValueError("subplots needs at least two panels, e.g. line,histogram.")
    if len(kinds) > _MAX_SUBPLOTS:
        raise ValueError(f"At most {_MAX_SUBPLOTS} panels.")
    bad = [kind for kind in kinds if kind not in _SUBPLOT_KINDS]
    if bad:
        allowed = ", ".join(sorted(_SUBPLOT_KINDS))
        raise ValueError(f"Unknown panel kind(s): {', '.join(bad)}. Use: {allowed}.")


def _read_panels(raw: Any) -> tuple[list[str], list[dict[str, Any]] | None]:
    items = _coerce_panel_items(raw)
    if not items:
        raise ValueError(
            "subplots needs panels= with two or more kinds, e.g. line,histogram."
        )
    if any(isinstance(item, dict) for item in items):
        specs: list[dict[str, Any]] = []
        kinds: list[str] = []
        for item in items:
            if isinstance(item, dict):
                kind = _clean_kind(
                    item.get("kind")
                    or item.get("type")
                    or item.get("action")
                    or item.get("chart")
                    or ""
                )
                spec = dict(item)
                spec["kind"] = kind
            else:
                kind = _clean_kind(item)
                spec = {"kind": kind}
            specs.append(spec)
            kinds.append(kind)
        _check_panel_kinds(kinds)
        return kinds, specs
    kinds = [_clean_kind(item) for item in items]
    _check_panel_kinds(kinds)
    return kinds, None


def _parse_panels(raw: Any) -> list[str]:
    kinds, _specs = _read_panels(raw)
    return kinds


def _subplot_grid(n: int) -> tuple[int, int]:
    if n == 2:
        return 1, 2
    if n == 3:
        return 1, 3
    return 2, 2


def _draw_panel(
    ax: Any,
    kind: str,
    x: np.ndarray,
    y: np.ndarray,
    *,
    cats: list[str] | None,
    bins: int | None,
    xlabel: str,
    ylabel: str,
    look: str = "default",
) -> None:
    color = _mark_color(look)
    width, marker = _stroke(look)
    if kind == "histogram":
        ax.hist(y, bins=bins, edgecolor="0.3", linewidth=0.6, **color)
        ax.set_xlabel(ylabel or "value")
        ax.set_ylabel("count")
        ax.grid(True, alpha=0.3, axis="y")
        return
    if kind == "bar":
        labels = cats if cats is not None else [str(v) for v in x]
        np = _numpy()
        positions = np.arange(len(y))
        ax.bar(positions, y, width=0.65, edgecolor="0.3", linewidth=0.6, **color)
        ax.set_xticks(positions)
        ax.set_xticklabels(labels[: len(y)])
        ax.set_xlabel(xlabel or "category")
        ax.set_ylabel(ylabel or "value")
        ax.grid(True, alpha=0.3, axis="y")
        return
    if kind == "scatter":
        ax.scatter(x, y, s=18 if look == "default" else 28, alpha=0.85, **color)
    else:
        ax.plot(x, y, marker="o", linewidth=width, markersize=marker, **color)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)


def _column_labels(frame: pd.DataFrame, name: str) -> list[str]:
    if name not in frame.columns:
        cols = ", ".join(str(c) for c in frame.columns[:12])
        raise ValueError(f"No column {name!r}. Columns: {cols}.")
    return [str(v) for v in frame[name].tolist()]


def _first_data_line(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for _ in range(40):
                line = handle.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped
    except OSError:
        return ""
    return ""


def _whitespace_text(path: Path) -> bool:
    """True when the table is spaces, not commas or tabs."""
    line = _first_data_line(path)
    if not line:
        return False
    return "," not in line and ";" not in line and "\t" not in line


def _frame_from_whitespace(path: Path) -> pd.DataFrame:
    """np.loadtxt, then genfromtxt, then the same 1-D / 2-D frame npy uses."""
    np = _numpy()
    pd = _pandas()
    try:
        data = np.loadtxt(path)
    except Exception:
        # loadtxt is strict; genfromtxt still reads a ragged or commented file.
        data = np.genfromtxt(path)
    data = np.asarray(data)
    names = getattr(data.dtype, "names", None)
    if names:
        return pd.DataFrame(data).head(_MAX_ROWS)
    if data.ndim == 0:
        data = np.atleast_1d(data)
    if data.ndim == 1:
        return pd.DataFrame({"value": data[:_MAX_ROWS]})
    if data.ndim == 2:
        frame = pd.DataFrame(data[:_MAX_ROWS])
        frame.columns = [str(c) for c in frame.columns]
        return frame
    raise ValueError("text table needs a 1-D or 2-D array")


def _csv_header_name(name: object) -> str:
    """numpy savetxt writes header='m,c' as '# m,c'. Plot needs 'm'."""
    text = str(name)
    if text.startswith("# "):
        return text[2:]
    if text.startswith("#"):
        return text[1:]
    return text


def _load_table(path: Path) -> pd.DataFrame:
    pd = _pandas()
    suffix = path.suffix.lower()
    if suffix in {".npy", ".npz"}:
        return frame_from_numpy(path)
    if suffix == ".txt" or (suffix == ".csv" and _whitespace_text(path)):
        return _frame_from_whitespace(path)
    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=_MAX_ROWS)
        frame.columns = [_csv_header_name(c) for c in frame.columns]
        return frame
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
    look: str = "default",
) -> str:
    if len(x) < 3:
        raise ValueError("residuals needs at least three numeric points.")
    np = _numpy()
    pd = _pandas()
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    resid = y - yhat
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    fit_color = "C1" if look == "default" else _COLORBLIND[1]
    with _look_context(look):
        fig = _open_figure(_figure_size(look, tall=True), look)
        ax = fig.add_subplot(211)
        ax.scatter(
            x,
            y,
            s=18 if look == "default" else 28,
            alpha=0.85,
            label="data",
            **_mark_color(look),
        )
        order = np.argsort(x)
        ax.plot(x[order], yhat[order], color=fit_color, label="fit")
        ax.set_title(title or "Fit")
        ax.set_ylabel(ylabel)
        ax.legend(frameon=False)
        ax.grid(True, alpha=0.3)
        bx = fig.add_subplot(212, sharex=ax)
        bx.axhline(0.0, color="0.5", linewidth=0.8)
        bx.scatter(
            x,
            resid,
            s=18 if look == "default" else 28,
            alpha=0.85,
            **_mark_color(look),
        )
        bx.set_xlabel(xlabel)
        bx.set_ylabel("residual")
        bx.grid(True, alpha=0.3)
        fig.tight_layout()
        note = _save_figure(fig, dest, look)
    table = dest.with_suffix(".csv")
    pd.DataFrame({"x": x, "y": y, "yhat": yhat, "residual": resid}).to_csv(table, index=False)
    shown = display_path(table)
    text = (
        f"Least-squares line y = {slope:.6g} x + {intercept:.6g}; "
        f"R^2 = {r2:.4f}. Residuals table: {shown}."
    )
    if note:
        text = f"{text} {note}"
    return text
