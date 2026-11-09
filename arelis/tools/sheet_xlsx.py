"""Real Excel workbooks for the document tool: typed cells, formulas, charts.

``document`` keeps its schema. For format=xlsx:

- rows cells become numbers, dates, percents, currency or text, and a cell
  that starts with ``=`` is a live formula Excel computes on open;
- ``chart: <bar|hbar|line|scatter|pie|area> [x=A] [y=B:C] [rows=2:13] [title]``
  and ``format: B=0.00 C=0.0%`` lines in body add an in-sheet chart and
  per-column number formats;
- from_path=<an existing .xlsx> edits a copy. Rows of ``[cell, value]`` set
  those cells, other rows append below the data, and a title that is not a
  sheet yet adds that sheet. The original is never written. If saving would
  drop something openpyxl cannot carry (pivot tables, shapes, macros,
  threaded comments, slicers, Excel 2010+ extensions), the edit is refused
  and nothing is written.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

# Functions Excel stores with the _xlfn. prefix. openpyxl's FORMULAE list
# predates them, and an unprefixed name opens as #NAME? in Excel.
_XLFN = frozenset(
    (
        "AGGREGATE BINOM.DIST CEILING.MATH CHISQ.TEST CONCAT CONFIDENCE.NORM "
        "CONFIDENCE.T COVARIANCE.P COVARIANCE.S DAYS ERF.PRECISE EXPON.DIST "
        "F.DIST F.TEST FLOOR.MATH FORECAST.LINEAR GAMMA IFNA IFS ISOWEEKNUM LET "
        "LOGNORM.DIST MAXIFS MINIFS MODE.SNGL NORM.DIST NORM.INV NORM.S.DIST "
        "NORM.S.INV PERCENTILE.EXC PERCENTILE.INC POISSON.DIST QUARTILE.EXC "
        "QUARTILE.INC RANK.AVG RANK.EQ STDEV.P STDEV.S SWITCH T.DIST T.DIST.2T "
        "T.INV T.INV.2T T.TEST TEXTJOIN VAR.P VAR.S XLOOKUP XMATCH XOR "
    ).split()
)
# Dynamic-array functions. openpyxl writes a plain cell formula, so these
# may show only their first value instead of spilling.
_NO_SPILL = frozenset({"FILTER", "SORT", "SORTBY", "UNIQUE", "SEQUENCE", "RANDARRAY", "LAMBDA"})
_CELL_REF = re.compile(
    r"^(?:(?P<sheet>'[^']+'|[^'!]+)!)?\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>\d{1,7})$"
)
_FUNC = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z][A-Za-z0-9.]*)\s*\(")
_STRING_LIT = re.compile(r'"(?:[^"]|"")*"')
_NUMBER = re.compile(
    r"^(?P<sign>[-+])?(?P<cur>[$€£])?(?P<int>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.(?P<dec>\d+))?(?:[eE](?P<exp>[-+]?\d+))?(?P<pct>%)?$"
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?$")
_DIRECTIVE = re.compile(r"^\s*(chart|format)\s*:\s*(.*?)\s*$", re.I)
_CHART_KINDS = ("bar", "column", "hbar", "line", "scatter", "pie", "area")
# Trailing total/mean rows stay out of a chart unless rows= says otherwise.
_SUMMARY_LABEL = re.compile(
    r"^\s*(?:grand\s+)?(?:total|sum|subtotal|mean|average|avg|median|std|stdev|"
    r"count|min|max)\b",
    re.I,
)
_PALETTE = ("4472C4", "C0504D", "9BBB59", "8064A2", "F79646", "4BACC6")
_X14 = re.compile(r"<x14:(?:sparklineGroup|conditionalFormatting|dataValidation)[ >]")
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_MAX_ROWS = 5_000
_MAX_COLS = 40
_CURRENCY = {"$": '"$"', "€": '"€"', "£": '"£"'}


class SheetRefusedError(Exception):
    """The edit would lose content or cannot be done safely. Nothing written."""


# ---------------------------------------------------------------- cells


def prefix_formula(formula: str) -> tuple[str, list[str]]:
    """Add _xlfn. where Excel needs it. Returns (formula, notes)."""
    from openpyxl.utils import FORMULAE

    notes: list[str] = []
    masked = _STRING_LIT.sub(lambda m: " " * len(m.group(0)), formula)
    out: list[str] = []
    last = 0
    for match in _FUNC.finditer(masked):
        name = match.group(1)
        upper = name.upper()
        if upper.startswith(("_XLFN.", "_XLWS.")):
            continue
        start = match.start(1)
        out.append(formula[last:start])
        if upper in FORMULAE:
            out.append(upper)
        elif upper in _XLFN or upper in _NO_SPILL:
            out.append(f"_xlfn.{upper}")
            if upper in _NO_SPILL:
                notes.append(
                    f"{upper} is a spilling function; this file may show only its first value"
                )
        else:
            out.append(name)
            notes.append(f"{name} is not an Excel function (cell shows #NAME?)")
        last = match.end(1)
    out.append(formula[last:])
    fixed = "".join(out)
    if masked.count("(") != masked.count(")"):
        notes.append(f"unbalanced parentheses in {formula}")
    return fixed, notes


def coerce_cell(value: Any) -> tuple[Any, str | None]:
    """(cell value, number format or None) for one incoming cell."""
    if value is None or isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)):
        return value, None
    text = str(value).strip()
    if not text:
        return None, None
    if text.startswith("=") and len(text) > 1:
        return text, None
    match = _NUMBER.match(text.replace(" ", "")) if len(text) < 40 else None
    if match:
        whole = match.group("int").replace(",", "")
        # Leading zeros (IDs, ZIP codes) and 16+ digit numbers stay text so
        # Excel does not eat digits.
        if (len(whole) > 1 and whole.startswith("0") and not match.group("dec")) or len(whole) > 15:
            return text, None
        dec = match.group("dec") or ""
        number = float(f"{whole}.{dec}" if dec else whole)
        if match.group("exp"):
            number *= 10 ** int(match.group("exp"))
        if match.group("sign") == "-":
            number = -number
        places = "." + "0" * len(dec) if dec else ""
        if match.group("pct"):
            return number / 100, f"0{places}%"
        if match.group("exp"):
            return number, f"0{places or '.00'}E+00"
        if match.group("cur"):
            return number, f"{_CURRENCY[match.group('cur')]}#,##0{places}"
        if "," in match.group("int"):
            return (int(number) if not dec else number), f"#,##0{places}"
        if not dec:
            return int(number), None
        return number, f"0{places}"
    try:
        if _DATE.match(text):
            return _dt.date.fromisoformat(text), "yyyy-mm-dd"
        if _DATETIME.match(text):
            return _dt.datetime.fromisoformat(text.replace(" ", "T")), "yyyy-mm-dd hh:mm"
    except ValueError:
        pass
    return text, None


def split_body(body: str) -> tuple[list[str], list[str]]:
    """(chart/format directive lines, the rest of body)."""
    directives: list[str] = []
    rest: list[str] = []
    for line in (body or "").splitlines():
        if _DIRECTIVE.match(line):
            directives.append(line.strip())
        else:
            rest.append(line)
    return directives, rest


def typed_rows(rows_raw: str, body_rest: str) -> list[list[Any]]:
    """Rows with native JSON values kept. Text cells get the usual clean."""
    from arelis.tools.document import _clean, _parse_rows

    text = (rows_raw or "").strip()
    parsed: Any = None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
    if isinstance(parsed, list) and parsed:
        rows: list[list[Any]] = []
        for item in parsed[:_MAX_ROWS]:
            cells = item if isinstance(item, list) else [item]
            rows.append(
                [
                    c if not isinstance(c, str) or c.strip().startswith("=") else _clean(c)
                    for c in cells[:_MAX_COLS]
                ]
            )
        return rows
    return _parse_rows(text, body=body_rest)


def _sheet_name(title: str, fallback: str = "Sheet1") -> str:
    name = _BAD_SHEET_CHARS.sub("-", (title or "").strip()).strip("'")[:31]
    return name or fallback


# ---------------------------------------------------------------- writing


def _put(ws: Any, row: int, col: int, raw: Any, notes: list[str]) -> Any:
    value, fmt = coerce_cell(raw)
    if isinstance(value, str) and value.startswith("="):
        value, found = prefix_formula(value)
        notes.extend(f"{ws.cell(row, col).coordinate}: {n}" for n in found)
    cell = ws.cell(row, col)
    cell.value = value
    if fmt:
        cell.number_format = fmt
    return cell


def _is_header(row: list[Any], body_rows: list[list[Any]]) -> bool:
    if not row or not body_rows:
        return False
    if not any(isinstance(c, str) and c.strip() for c in row):
        return False
    for cell in row:
        value, _fmt = coerce_cell(cell)
        if value is not None and not (isinstance(value, str) and not value.startswith("=")):
            return False
    return True


def _sheet_has_header(ws: Any) -> bool:
    """Row one is labels: some text, no plain numbers (a side formula is fine)."""
    values = [c.value for c in ws[1] if c.value is not None]
    texts = [v for v in values if isinstance(v, str) and not v.startswith("=")]
    others = [v for v in values if not isinstance(v, str)]
    return bool(texts) and not others and _last_row(ws) > 1


def _style_header(ws: Any, row: int, width: int) -> None:
    from openpyxl.styles import Border, Font, PatternFill, Side

    bold = Font(bold=True)
    fill = PatternFill("solid", start_color="FFE8E4F4")
    rule = Border(bottom=Side(style="thin", color="FF7A6FA8"))
    for col in range(1, width + 1):
        cell = ws.cell(row, col)
        cell.font = bold
        cell.fill = fill
        cell.border = rule


def _autofit(ws: Any) -> None:
    from openpyxl.utils import get_column_letter

    widths: dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            shown = str(cell.value)
            if shown.startswith("="):
                shown = "0000000000"
            widths[cell.column] = max(widths.get(cell.column, 0), len(shown))
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = min(max(width + 2, 8), 60)


def _write_table(ws: Any, rows: list[list[Any]], top: int, notes: list[str]) -> bool:
    """Write rows starting at row ``top``. True when row one was a header."""
    header = _is_header(rows[0], rows[1:])
    width = max(len(r) for r in rows)
    for r_i, row in enumerate(rows):
        for c_i, raw in enumerate(row, start=1):
            _put(ws, top + r_i, c_i, raw, notes)
    if header:
        _style_header(ws, top, width)
        if top == 1:
            from openpyxl.utils import get_column_letter

            ws.freeze_panes = "A2"
            ws.auto_filter.ref = f"A1:{get_column_letter(width)}{len(rows)}"
    return header


def _last_row(ws: Any) -> int:
    for r in range(ws.max_row, 0, -1):
        if any(c.value is not None for c in ws[r]):
            return r
    return 0


def _col_index(token: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(token.strip().upper())


def _col_span(token: str) -> list[int]:
    out: list[int] = []
    for part in token.split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            out.extend(range(_col_index(a), _col_index(b) + 1))
        elif part.strip():
            out.append(_col_index(part))
    return out


def apply_formats(ws: Any, directives: list[str], first: int, last: int) -> None:
    for line in directives:
        kind, rest = _DIRECTIVE.match(line).groups()  # type: ignore[union-attr]
        if kind.lower() != "format":
            continue
        for token in rest.split():
            if "=" not in token:
                continue
            cols, fmt = token.split("=", 1)
            try:
                indexes = _col_span(cols)
            except ValueError:
                continue
            for col in indexes:
                for r in range(first, last + 1):
                    ws.cell(r, col).number_format = fmt


def _numeric_col(ws: Any, col: int, first: int, last: int) -> bool:
    for r in range(first, last + 1):
        value = ws.cell(r, col).value
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.startswith("=")):
            return True
    return False


def add_charts(ws: Any, directives: list[str], *, header: bool, last: int, notes: list[str]) -> int:
    """Add each chart: line. Returns how many charts were added."""
    from openpyxl.chart import (
        AreaChart,
        BarChart,
        LineChart,
        PieChart,
        Reference,
        ScatterChart,
        Series,
    )
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.utils import get_column_letter

    added = 0
    width = ws.max_column
    for line in directives:
        kind_word, rest = _DIRECTIVE.match(line).groups()  # type: ignore[union-attr]
        if kind_word.lower() != "chart":
            continue
        words = rest.split()
        kind = words[0].lower() if words else "bar"
        if kind not in _CHART_KINDS:
            notes.append(f"chart type {kind!r} unknown; used bar")
            kind = "bar"
        else:
            words = words[1:]
        opts: dict[str, str] = {}
        title_words: list[str] = []
        for word in words:
            key, sep, val = word.partition("=")
            if sep and key.lower() in {"x", "y", "rows", "at"}:
                opts[key.lower()] = val
            else:
                title_words.append(word)
        first = 2 if header else 1
        stop = last
        while stop > first and _SUMMARY_LABEL.match(str(ws.cell(stop, 1).value or "")):
            stop -= 1
        if "rows" in opts:
            a, _sep, b = opts["rows"].partition(":")
            try:
                first, stop = int(a), int(b or a)
            except ValueError:
                notes.append(f"chart rows={opts['rows']} unreadable; used all rows")
        try:
            x_col = _col_index(opts["x"]) if "x" in opts else 1
            y_cols = (
                _col_span(opts["y"])
                if "y" in opts
                else [
                    c
                    for c in range(1, width + 1)
                    if c != x_col and _numeric_col(ws, c, first, stop)
                ]
            )
        except ValueError:
            notes.append(f"chart columns unreadable in {line!r}; skipped")
            continue
        if not y_cols or stop < first:
            notes.append(f"no numeric columns to chart for {line!r}; skipped")
            continue
        head = first - 1 if header and first > 1 else None
        if kind == "scatter":
            chart: Any = ScatterChart()
            chart.style = 13
            chart.scatterStyle = "marker"
            xs = Reference(ws, min_col=x_col, min_row=first, max_row=stop)
            for n, col in enumerate(y_cols):
                ys = Reference(ws, min_col=col, min_row=head or first, max_row=stop)
                series = Series(ys, xs, title_from_data=head is not None)
                series.marker.symbol = "circle"
                series.marker.size = 7
                colour = _PALETTE[n % len(_PALETTE)]
                series.marker.graphicalProperties = GraphicalProperties(solidFill=colour)
                series.marker.graphicalProperties.line.solidFill = colour
                series.graphicalProperties.line.noFill = True
                chart.series.append(series)
        else:
            chart = {
                "bar": BarChart,
                "column": BarChart,
                "hbar": BarChart,
                "line": LineChart,
                "pie": PieChart,
                "area": AreaChart,
            }[kind]()
            if kind == "hbar":
                chart.type = "bar"
            for col in y_cols[:1] if kind == "pie" else y_cols:
                data = Reference(ws, min_col=col, min_row=head or first, max_row=stop)
                chart.add_data(data, titles_from_data=head is not None)
            chart.set_categories(Reference(ws, min_col=x_col, min_row=first, max_row=stop))
        chart.title = " ".join(title_words) or None
        if kind != "pie" and head is not None:
            chart.x_axis.title = str(ws.cell(head, x_col).value or "") or None
            if len(y_cols) == 1:
                chart.y_axis.title = str(ws.cell(head, y_cols[0]).value or "") or None
        if kind != "pie":
            # Newer Excel hides axes openpyxl leaves at the default delete=None.
            chart.x_axis.delete = False
            chart.y_axis.delete = False
        chart.width, chart.height = 16, 8.5
        anchor = opts.get("at") or f"{get_column_letter(width + 2)}{2 + 18 * added}"
        ws.add_chart(chart, anchor)
        added += 1
    return added


def _finish(book: Any) -> None:
    from openpyxl.workbook.properties import CalcProperties

    if book.calculation is None:
        book.calculation = CalcProperties()
    book.calculation.fullCalcOnLoad = True


def count_formulas(book: Any) -> int:
    return sum(
        1
        for ws in book.worksheets
        for row in ws.iter_rows()
        for cell in row
        if isinstance(cell.value, str) and cell.value.startswith("=")
    )


def write_new(
    dest: Path, rows: list[list[Any]], title: str, directives: list[str]
) -> dict[str, Any]:
    from openpyxl import Workbook

    notes: list[str] = []
    book = Workbook()
    ws = book.active
    ws.title = _sheet_name(title)
    header = _write_table(ws, rows, 1, notes)
    apply_formats(ws, directives, 2 if header else 1, len(rows))
    _autofit(ws)
    charts = add_charts(ws, directives, header=header, last=len(rows), notes=notes)
    _finish(book)
    book.save(str(dest))
    return {
        "sheet": ws.title,
        "formulas": count_formulas(book),
        "charts": charts,
        "notes": notes,
    }


# ---------------------------------------------------------------- editing


def inventory(path: Path) -> Counter[str]:
    """What a workbook package holds, by the names a person would use."""
    found: Counter[str] = Counter()
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            low = name.lower()
            if re.match(r"xl/charts/chart\d+\.xml$", low):
                found["charts"] += 1
            elif low.startswith("xl/chartsheets/") and low.endswith(".xml"):
                found["chart sheets"] += 1
            elif low.startswith("xl/media/"):
                found["images"] += 1
            elif low.startswith("xl/pivottables/") and low.endswith(".xml"):
                found["pivot tables"] += 1
            elif low.startswith(("xl/slicers/", "xl/slicercaches/")):
                found["slicers"] += 1
            elif low.startswith(("xl/timelines/", "xl/timelinecaches/")):
                found["timelines"] += 1
            elif low.endswith("vbaproject.bin"):
                found["macros"] += 1
            elif low.startswith(("xl/threadedcomments/", "xl/persons/")):
                found["threaded comments"] += 1
            elif low.startswith("xl/embeddings/"):
                found["embedded objects"] += 1
            elif low.startswith("xl/ctrlprops/"):
                found["form controls"] += 1
            elif low.startswith("xl/querytables/") or low == "xl/connections.xml":
                found["data connections"] += 1
            elif low.startswith("xl/externallinks/") and low.endswith(".xml"):
                found["external links"] += 1
            elif low.startswith("xl/tables/") and low.endswith(".xml"):
                found["tables"] += 1
            elif low.startswith("customxml/") and low.endswith(".xml"):
                found["custom XML"] += 1
            if re.match(r"xl/drawings/drawing\d+\.xml$", low):
                text = package.read(name).decode("utf-8", "replace")
                found["shapes"] += len(re.findall(r"<(?:xdr:)?(?:sp|grpSp|cxnSp)[ >]", text))
            elif re.match(r"xl/worksheets/sheet\d+\.xml$", low):
                text = package.read(name).decode("utf-8", "replace")
                found["sheets"] += 1
                found["Excel 2010+ extras (sparklines, rich rules)"] += len(_X14.findall(text))
                found["data validations"] += len(re.findall(r"<dataValidation[ >]", text))
                found["conditional formats"] += len(re.findall(r"<cfRule[ >]", text))
                found["merged ranges"] += len(re.findall(r"<mergeCell[ >]", text))
            elif re.match(r"xl/comments\d*\.xml$|xl/comments/comment\d+\.xml$", low):
                text = package.read(name).decode("utf-8", "replace")
                found["comments"] += len(re.findall(r"<comment[ >]", text))
            elif low == "xl/workbook.xml":
                text = package.read(name).decode("utf-8", "replace")
                # Built-in names (filter ranges, print areas) are rewritten by
                # openpyxl from sheet settings, so only the user's own count.
                found["named ranges"] += len(
                    re.findall(r'<definedName\b[^>]*\bname="(?!_xlnm\.)', text)
                )
    return +found


def losses(before: Counter[str], after: Counter[str]) -> list[str]:
    return [
        f"{before[key] - after.get(key, 0)} {key}"
        for key in sorted(before)
        if after.get(key, 0) < before[key]
    ]


def _cell_edits(rows: list[list[Any]]) -> list[tuple[str | None, str, Any]] | None:
    """[(sheet, A1, value)] when every row is a [cell, value] pair."""
    out: list[tuple[str | None, str, Any]] = []
    for row in rows:
        if len(row) != 2 or not isinstance(row[0], str):
            return None
        match = _CELL_REF.match(row[0].strip())
        if not match:
            return None
        sheet = match.group("sheet")
        if sheet:
            sheet = sheet.strip("'")
        out.append((sheet, f"{match.group('col').upper()}{match.group('row')}", row[1]))
    return out


def _copy_style(src: Any, dst: Any) -> None:
    from copy import copy

    if src.has_style:
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.number_format = src.number_format


def edit_copy(
    src: Path,
    dest: Path,
    rows: list[list[Any]],
    title: str,
    directives: list[str],
) -> dict[str, Any]:
    """Apply rows/directives to a copy of ``src`` saved at ``dest``.

    ``dest`` may be an existing file only when the caller asked to replace;
    it is then backed up first. ``src`` is never written.
    """
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    suffix = src.suffix.lower()
    if suffix != ".xlsx":
        raise SheetRefusedError(
            f"I edit .xlsx workbooks only; {src.name} is {suffix or 'not a workbook'}. "
            "Nothing was written."
        )
    before = inventory(src)
    book = load_workbook(str(src))
    notes: list[str] = []
    edits = _cell_edits(rows) if rows else None
    changed = 0
    touched: dict[str, None] = {}
    target_name = (title or "").strip()
    if edits is not None:
        for sheet, ref, value in edits:
            name = sheet or target_name or book.active.title
            if name not in book.sheetnames:
                raise SheetRefusedError(
                    f"No sheet named {name!r} in {src.name}. Nothing was written."
                )
            ws = book[name]
            touched.setdefault(name, None)
            _put(ws, ws[ref].row, ws[ref].column, value, notes)
            changed += 1
        ws = book[target_name] if target_name in book.sheetnames else book.active
        header = _sheet_has_header(ws)
    elif target_name and _sheet_name(target_name) not in book.sheetnames:
        ws = book.create_sheet(_sheet_name(target_name))
        header = _write_table(ws, rows, 1, notes) if rows else False
        _autofit(ws)
        changed = len(rows)
    else:
        ws = book[_sheet_name(target_name)] if target_name else book.active
        header = _sheet_has_header(ws)
        last = _last_row(ws)
        new_rows = list(rows)
        if (
            new_rows
            and header
            and [str(c).strip() for c in new_rows[0]]
            == [str(c.value).strip() for c in ws[1][: len(new_rows[0])]]
        ):
            new_rows = new_rows[1:]
        for r_i, row in enumerate(new_rows, start=last + 1):
            for c_i, raw in enumerate(row, start=1):
                cell = _put(ws, r_i, c_i, raw, notes)
                if r_i > 1:
                    above = ws.cell(r_i - 1, c_i)
                    keep = cell.number_format
                    _copy_style(above, cell)
                    if keep != "General":
                        cell.number_format = keep
        changed = len(new_rows)
        if new_rows:
            end = last + len(new_rows)
            for table in ws.tables.values():
                start_ref, _sep, end_ref = table.ref.partition(":")
                match = _CELL_REF.match(end_ref)
                if match and int(match.group("row")) == last:
                    table.ref = f"{start_ref}:{match.group('col')}{end}"
                    if table.autoFilter is not None:
                        table.autoFilter.ref = table.ref
            if ws.auto_filter.ref:
                start_ref, _sep, end_ref = ws.auto_filter.ref.partition(":")
                match = _CELL_REF.match(end_ref)
                if match and int(match.group("row")) == last:
                    ws.auto_filter.ref = f"{start_ref}:{match.group('col')}{end}"
            if ws._charts:
                notes.append("existing charts keep their old range; the new rows are not in them")
    last = _last_row(ws)
    apply_formats(ws, directives, 2 if header else 1, last)
    charts = add_charts(ws, directives, header=header, last=last, notes=notes)
    if (
        not changed
        and not charts
        and not any(
            _DIRECTIVE.match(d).group(1).lower() == "format"
            for d in directives  # type: ignore[union-attr]
        )
    ):
        raise SheetRefusedError(
            "No edits given (rows, chart: or format: lines). Nothing was written."
        )
    _finish(book)
    staging = dest.with_name(f".{dest.stem}.arelis-partial.xlsx")
    try:
        book.save(str(staging))
        lost = losses(before, inventory(staging))
        if lost:
            raise SheetRefusedError(
                f"Saving {src.name} here would drop: {', '.join(lost)}. "
                "I did not write anything and the original is untouched. Make the "
                "change in Excel, or ask me for a new sheet built from its data."
            )
        backup = None
        if dest.exists():
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = dest.with_name(f"{dest.stem}.backup-{stamp}{dest.suffix}")
            shutil.copy2(dest, backup)
        staging.replace(dest)
    finally:
        if staging.exists():
            staging.unlink()
    return {
        "sheet": ", ".join(touched) or ws.title,
        "sheets": list(book.sheetnames),
        "changed": changed,
        "formulas": count_formulas(book),
        "charts": charts,
        "notes": notes,
        "backup": str(backup) if backup else None,
        "used_range": f"A1:{get_column_letter(max(ws.max_column, 1))}{max(last, 1)}",
    }
