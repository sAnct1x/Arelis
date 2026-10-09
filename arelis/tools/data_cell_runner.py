"""Child process for the room data cell.

Run this file by path (`python -I data_cell_runner.py`). It must not import
arelis. The parent resolves every input and sends only those paths on stdin.

Network blocks here are defense in depth, not a guarantee. ctypes can still
open a socket or start a process. The parent also points proxy variables at
a closed local port and does not copy the parent environment.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

READ_REFUSAL = "I can only read files in this room."
WRITE_REFUSAL = "I can only save results in this room's results folder."
TOO_BIG = "That file is too big for me to read here."
MEMORY_REFUSAL = "That used too much memory, so I stopped it."

_MAX_SUMMARY = 12_000
_STATE: dict[str, Any] = {}
_IN_HOOK = False


class CellBlocked(BaseException):
    """Raised by the audit hook. BaseException so user code cannot swallow it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def is_unsafe_path(raw: str) -> bool:
    """True for UNC and NT device prefixes. String check only, no resolve."""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if not text:
        return False
    if text[:5].lower() == "file:":
        rest = text[5:].replace("/", "\\")
        if rest.startswith("\\\\\\\\"):
            return True
        if rest.startswith("\\\\") and not rest.startswith("\\\\\\"):
            return True
    norm = text.replace("/", "\\")
    return norm.startswith("\\\\") or norm.startswith("\\??\\")


def _abs(path: Path) -> Path:
    return Path(os.path.abspath(path))


def lexically_inside(path: Path, root: Path) -> bool:
    """True when the path stays under root without following links."""
    if is_unsafe_path(str(path)):
        return False
    root_abs = _abs(root)
    candidate = path if path.is_absolute() else Path.cwd() / path
    if is_unsafe_path(str(candidate)):
        return False
    try:
        Path(os.path.normcase(os.path.abspath(candidate))).relative_to(
            Path(os.path.normcase(str(root_abs)))
        )
    except ValueError:
        return False
    return True


def is_reparse(path: Path) -> bool:
    """Symlink, or a Windows junction on 3.12+ (is_symlink misses junctions)."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return False
    checker = getattr(path, "is_junction", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except OSError:
        return False


def reparse_leaves(path: Path, root: Path) -> bool:
    """True when a symlink or junction on the way resolves outside root."""
    root_abs = _abs(root)
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        rel = os.path.relpath(os.path.abspath(candidate), str(root_abs))
    except ValueError:
        return True
    if rel.startswith(".."):
        return True
    current = root_abs
    for part in Path(rel).parts:
        current = current / part
        if not is_reparse(current):
            continue
        try:
            target = Path(os.path.realpath(current))
        except OSError:
            return True
        if not lexically_inside(target, root_abs):
            return True
        current = target
    return False


def escapes_tree(path: Path, root: Path) -> bool:
    """True when path is outside root, including through a link."""
    if not lexically_inside(path, root):
        return True
    return reparse_leaves(path, root)


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _plain(item())
        except Exception:
            return str(value)
    return str(value)


def _venv_site() -> Path | None:
    exe = Path(sys.executable).resolve()
    if sys.platform == "win32":
        site = exe.parent.parent / "Lib" / "site-packages"
    else:
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        site = exe.parent.parent / "lib" / version / "site-packages"
    return site if site.is_dir() else None


def _enable_venv_site() -> None:
    """-I ignores pyvenv.cfg. Put this interpreter's site-packages back."""
    site = _venv_site()
    if site is not None and str(site) not in sys.path:
        sys.path.append(str(site))


def _read_roots() -> list[Path]:
    roots: list[Path] = []
    for raw in (
        sys.prefix,
        getattr(sys, "base_prefix", ""),
        str(Path(sys.executable).resolve().parent),
    ):
        if raw:
            roots.append(_abs(Path(raw)))
    site = _venv_site()
    if site is not None:
        roots.append(_abs(site))
    roots.append(_abs(Path(__file__).resolve().parent))
    return roots


def _font_read(path: Path) -> bool:
    """Matplotlib opens the OS font folder. That is not the user's files."""
    roots: list[Path] = []
    windir = os.environ.get("SYSTEMROOT", "")
    if windir:
        roots.append(Path(windir) / "Fonts")
    for extra in (
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts",
    ):
        roots.append(Path(extra))
    for root in roots:
        if lexically_inside(path, root) and not reparse_leaves(path, root):
            return True
    return False


def _library_read(path: Path) -> bool:
    for root in _read_roots():
        if lexically_inside(path, root) and not reparse_leaves(path, root):
            return True
    return False


def _is_write(mode: Any, flags: Any) -> bool:
    if isinstance(mode, bytes):
        mode = os.fsdecode(mode)
    text = "" if mode is None else str(mode)
    if any(ch in text for ch in "wax+"):
        return True
    try:
        flag = int(flags or 0)
    except (TypeError, ValueError):
        flag = 0
    bits = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_APPEND", 0)
        | getattr(os, "O_TRUNC", 0)
    )
    return bool(flag & bits)


def _as_path(raw: Any) -> Path | None:
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if raw is None:
        return None
    text = str(raw)
    if not text or text in {"<fdopen>", "<stdin>", "<stdout>", "<stderr>"}:
        return None
    if is_unsafe_path(text):
        raise CellBlocked(READ_REFUSAL)
    return Path(text)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    global _IN_HOOK
    if _IN_HOOK:
        return
    _IN_HOOK = True
    try:
        _audit_inner(event, args)
    finally:
        _IN_HOOK = False


def _audit_inner(event: str, args: tuple[Any, ...]) -> None:
    if event in {
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "urllib.Request",
        "subprocess.Popen",
        "os.system",
    }:
        raise CellBlocked("I can't reach the network from here.")
    if event != "open" or not args:
        return
    mode = args[1] if len(args) > 1 else ""
    flags = args[2] if len(args) > 2 else 0
    path = _as_path(args[0])
    if path is None:
        return
    room = _STATE.get("room")
    results = _STATE.get("results")
    if not isinstance(room, Path) or not isinstance(results, Path):
        raise CellBlocked(READ_REFUSAL)
    if _is_write(mode, flags):
        # Results-only write check. Reads use the room tree below.
        if escapes_tree(path, results):
            raise CellBlocked(WRITE_REFUSAL)
        return
    if _library_read(path) or _font_read(path):
        return
    if escapes_tree(path, room):
        raise CellBlocked(READ_REFUSAL)


def _install_hook() -> None:
    sys.addaudithook(_audit)


def _posix_limits() -> None:
    if sys.platform == "win32":
        return
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (130, 130))
        cap = int(_STATE.get("max_write") or (16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    except (OSError, ValueError):
        return


def _charge_read(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CellBlocked(READ_REFUSAL) from exc
    per = int(_STATE.get("max_input") or 0)
    total_cap = int(_STATE.get("max_total_read") or 0)
    if per and size > per:
        raise CellBlocked(TOO_BIG)
    used = int(_STATE.get("read_bytes") or 0) + size
    if total_cap and used > total_cap:
        raise CellBlocked(TOO_BIG)
    _STATE["read_bytes"] = used


def _authorized(name: str) -> Path:
    files = _STATE.get("files")
    if not isinstance(files, dict):
        raise CellBlocked(READ_REFUSAL)
    key = str(name or "").strip()
    raw = files.get(key)
    if raw is None:
        leaf = Path(key).name
        raw = files.get(leaf)
    if not raw:
        raise CellBlocked(READ_REFUSAL)
    path = Path(str(raw))
    room = _STATE["room"]
    if escapes_tree(path, room):
        raise CellBlocked(READ_REFUSAL)
    if not path.is_file():
        raise CellBlocked("I can't find that file in this room.")
    _charge_read(path)
    return path


def _result_file(name: str) -> Path:
    text = str(name or "").strip()
    if not text or "/" in text.replace("\\", "/") or is_unsafe_path(text):
        raise CellBlocked(WRITE_REFUSAL)
    leaf = Path(text).name
    if not leaf or leaf in {".", ".."}:
        raise CellBlocked(WRITE_REFUSAL)
    dest = Path(_STATE["results"]) / leaf
    if escapes_tree(dest, _STATE["results"]):
        raise CellBlocked(WRITE_REFUSAL)
    return dest


def _account_write(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CellBlocked(WRITE_REFUSAL) from exc
    png_cap = int(_STATE.get("max_png") or 0)
    write_cap = int(_STATE.get("max_write") or 0)
    if png_cap and path.suffix.lower() == ".png" and size > png_cap:
        path.unlink(missing_ok=True)
        raise CellBlocked(TOO_BIG)
    results = Path(_STATE["results"])
    total = 0
    if results.is_dir():
        for item in results.rglob("*"):
            if item.is_file() and ".mpl" not in item.parts:
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    if write_cap and total > write_cap:
        path.unlink(missing_ok=True)
        raise CellBlocked(TOO_BIG)


def read_table(name: str = "", path: str = "") -> Any:
    picked = str(name or path).strip()
    if not picked:
        raise CellBlocked(READ_REFUSAL)
    table_path = _authorized(picked)
    import pandas as pd

    pd.set_option("display.max_rows", 30)
    pd.set_option("display.max_columns", 12)
    pd.set_option("display.width", 120)

    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(table_path)
    if suffix in {".tsv", ".tab"}:
        return pd.read_csv(table_path, sep="\t")
    if suffix == ".json":
        return pd.read_json(table_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(table_path)
    raise CellBlocked("I can only read a table or a FITS file in this room.")


def read_fits(name: str = "", path: str = "") -> dict[str, Any]:
    picked = str(name or path).strip()
    if not picked:
        raise CellBlocked(READ_REFUSAL)
    fits_path = _authorized(picked)
    from astropy.io import fits

    header: dict[str, Any] = {}
    shape: tuple[int, ...] | None = None
    columns: list[str] = []
    with fits.open(fits_path) as hdul:
        for key in hdul[0].header:
            if key:
                header[str(key)] = _plain(hdul[0].header[key])
        for hdu in hdul:
            data = getattr(hdu, "data", None)
            names = getattr(getattr(hdu, "columns", None), "names", None)
            if names:
                columns = [str(item) for item in names]
                continue
            if shape is None and data is not None and hasattr(data, "shape"):
                shape = tuple(int(item) for item in data.shape)
    return {"header": header, "shape": shape, "columns": columns}


def save_png(fig: Any, name: str = "chart.png") -> str:
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib

    matplotlib.use("Agg", force=False)
    dest = _result_file(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest, format="png")
    _account_write(dest)
    return dest.name


def save_csv(frame: Any, name: str) -> str:
    dest = _result_file(name if str(name).lower().endswith(".csv") else f"{name}.csv")
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(dest, index=False)
    _account_write(dest)
    return dest.name


def _unwrap(code: str) -> str:
    text = (code or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str))
    sys.stdout.write("\n")


def _summary(text: str) -> str:
    clean = (text or "").strip()
    if len(clean) <= _MAX_SUMMARY:
        return clean
    return clean[:_MAX_SUMMARY].rstrip() + "\n(truncated)"


def _new_charts(before: set[Path]) -> list[dict[str, str]]:
    results = Path(_STATE["results"])
    found: list[dict[str, str]] = []
    if not results.is_dir():
        return found
    for path in sorted(results.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        if ".mpl" in path.parts or path.resolve() in before:
            continue
        if escapes_tree(path, results):
            continue
        found.append({"name": path.name, "abs_path": str(path.resolve())})
    return found


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        _emit({"ok": False, "error": "refused", "summary": READ_REFUSAL, "charts": []})
        return 1
    room = Path(str(request.get("room") or ""))
    results = Path(str(request.get("results") or ""))
    _STATE["room"] = room
    _STATE["results"] = results
    _STATE["files"] = request.get("files") if isinstance(request.get("files"), dict) else {}
    _STATE["max_input"] = int(request.get("max_input") or 0)
    _STATE["max_total_read"] = int(request.get("max_total_read") or 0)
    _STATE["max_png"] = int(request.get("max_png") or 0)
    _STATE["max_write"] = int(request.get("max_write") or 0)
    _STATE["read_bytes"] = 0
    cache = results / ".mpl"
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["MPLCONFIGDIR"] = str(cache)
    # No real profile is passed in. Point home at the results cache so
    # libraries that insist on a home directory stay inside results.
    os.environ["HOME"] = str(cache)
    os.environ["USERPROFILE"] = str(cache)
    os.environ["APPDATA"] = str(cache)
    os.environ["LOCALAPPDATA"] = str(cache)
    try:
        results.mkdir(parents=True, exist_ok=True)
        (results / ".mpl").mkdir(parents=True, exist_ok=True)
    except OSError:
        _emit({"ok": False, "error": "refused", "summary": WRITE_REFUSAL, "charts": []})
        return 1
    _enable_venv_site()
    _posix_limits()
    _install_hook()
    before = (
        {path.resolve() for path in results.rglob("*") if path.is_file()}
        if results.is_dir()
        else set()
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    namespace = {
        "__name__": "__main__",
        "read_table": read_table,
        "read_fits": read_fits,
        "save_png": save_png,
        "save_csv": save_csv,
    }
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(
                compile(_unwrap(str(request.get("code") or "")), "<data>", "exec"),
                namespace,
                namespace,
            )
    except CellBlocked as exc:
        _emit({"ok": False, "error": "refused", "summary": exc.message, "charts": []})
        return 1
    except MemoryError:
        _emit({"ok": False, "error": "memory", "summary": MEMORY_REFUSAL, "charts": []})
        return 1
    except Exception:
        _emit({"ok": False, "error": "failed", "summary": "I couldn't finish that.", "charts": []})
        return 1
    summary = _summary(stdout.getvalue())
    _emit({"ok": True, "error": "", "summary": summary or "Done.", "charts": _new_charts(before)})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CellBlocked as exc:
        _emit({"ok": False, "error": "refused", "summary": exc.message, "charts": []})
        raise SystemExit(1) from None
    except MemoryError:
        _emit({"ok": False, "error": "memory", "summary": MEMORY_REFUSAL, "charts": []})
        raise SystemExit(1) from None
