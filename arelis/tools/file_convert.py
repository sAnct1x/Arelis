"""Write converted files: tables to csv or xlsx, and LaTeX to PDF.

document from_path= calls these. Values keep their types: a number read
from a csv lands in Excel as a number, not as text that looks like one.
LaTeX needs a TeX engine already on this PC. None is bundled.
"""

from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from arelis.tools.file_read import MAX_TABLE_ROWS, Table

LATEX_TIMEOUT_S = 120.0
# Searched in this order. tectonic is one self-contained exe, so it is the
# easiest for somebody without MiKTeX or TeX Live.
_ENGINES = ("pdflatex", "xelatex", "lualatex", "tectonic")

NO_TEX = (
    "LaTeX to PDF needs a TeX engine, and none was found on this PC "
    "(looked for pdflatex, xelatex, lualatex and tectonic). Arelis does not "
    "bundle one. Install MiKTeX (miktex.org) or TeX Live, or tectonic, then "
    "ask again. Until then I can convert the .tex to docx or markdown, or "
    "write a PDF of its text without LaTeX typesetting."
)


class LatexUnavailableError(RuntimeError):
    pass


def write_table(dest: Path, tab: Table, fmt: str) -> tuple[int, bool]:
    """Stream ``tab`` into csv or xlsx. Returns (rows written, truncated)."""
    limit = min(tab.total, MAX_TABLE_ROWS)
    written = 0
    if fmt == "csv":
        with dest.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(tab.columns)
            for row in tab.rows(limit):
                writer.writerow(["" if v is None else v for v in row])
                written += 1
    else:
        from openpyxl import Workbook

        book = Workbook(write_only=True)
        sheet = book.create_sheet(_sheet_title(tab.name))
        sheet.append(list(tab.columns))
        for row in tab.rows(limit):
            sheet.append([_cell(v) for v in row])
            written += 1
        book.save(str(dest))
    return written, tab.total > written


def _sheet_title(name: str) -> str:
    bad = set('[]:*?/\\')
    clean = "".join("-" if ch in bad else ch for ch in (name or "Sheet1"))
    return clean.strip()[:31] or "Sheet1"


def _cell(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str) and value.startswith("="):
        # Plain conversion: a formula read back from a sheet stays visible
        # as text rather than being run.
        return "'" + value
    return value


def find_tex_engine() -> str | None:
    for name in _ENGINES:
        found = shutil.which(name)
        if found:
            return found
    return None


def compile_latex(source: Path, dest: Path) -> str:
    """Typeset ``source`` into ``dest``. Returns the engine name used.

    Runs with shell escape off, in a scratch folder, with a time limit. The
    source folder is on the input path so \\input and images beside the
    .tex still resolve.
    """
    engine = find_tex_engine()
    if engine is None:
        raise LatexUnavailableError(NO_TEX)
    name = Path(engine).stem.lower()
    with tempfile.TemporaryDirectory(prefix="arelis-tex-") as scratch:
        work = Path(scratch)
        env = dict(os.environ)
        env["TEXINPUTS"] = f"{source.parent}{os.pathsep}"
        if name == "tectonic":
            cmd = [engine, "--outdir", str(work), str(source)]
        else:
            cmd = [
                engine,
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={work}",
                str(source),
            ]
        runs = 1 if name == "tectonic" else 2
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for _ in range(runs):
            try:
                done = subprocess.run(
                    cmd,
                    cwd=str(source.parent),
                    env=env,
                    capture_output=True,
                    timeout=LATEX_TIMEOUT_S,
                    creationflags=flags,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"{name} took longer than {LATEX_TIMEOUT_S:.0f} s and was stopped."
                ) from exc
            if done.returncode != 0:
                raise RuntimeError(f"{name} failed: {_tex_error(done, work, source)}")
        built = work / f"{source.stem}.pdf"
        if not built.is_file():
            raise RuntimeError(f"{name} finished but wrote no PDF.")
        shutil.copyfile(built, dest)
    return name


def _tex_error(done: Any, work: Path, source: Path) -> str:
    log = work / f"{source.stem}.log"
    text = ""
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")
    else:
        text = (done.stdout or b"").decode("utf-8", errors="replace")
        text += (done.stderr or b"").decode("utf-8", errors="replace")
    errors = [ln for ln in text.splitlines() if ln.startswith("!") or "error" in ln.lower()]
    picked = "; ".join(errors[:3]) or text.strip()[-300:]
    return picked or f"exit code {done.returncode}"
