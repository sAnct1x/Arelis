"""Read the file types doc_extract and document from_path= share.

PDF, Word and PowerPoint keep their own readers (doc_extract, office_text).
This module adds spreadsheets (xlsx, csv, tsv), markdown and plain text,
LaTeX source, and science data: FITS (astropy), HDF5 and NetCDF-4 (h5py),
and classic NetCDF-3 (a small reader here, so no second HDF5 stack).

Two things come out of a file:

* ``describe`` is what the model reads: a header summary plus a capped
  preview, and a quick-look PNG for 2-D data.
* ``table`` is the data itself for conversion to csv or xlsx. Rows stream
  from the file, so a large table is never held as Python lists.

A selector after ``#`` picks a part: a sheet name, a FITS HDU index or
EXTNAME, an HDF5 dataset or group path, or a NetCDF variable name.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import mmap
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any

import numpy as np

# Excel's row limit, less the header. csv uses the same cap so the two
# targets of one conversion always hold the same rows.
MAX_TABLE_ROWS = 1_048_575
_PREVIEW_ROWS = 20
_SHEET_ROWS = 200
_MAX_FORMULAS = 20
_MAX_ATTRS = 24
_MAX_PREVIEWS = 3
_STATS_SAMPLE = 10_000_000

_SUFFIX_KIND: dict[str, str] = {
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".csv": "csv",
    ".tsv": "csv",
    ".tab": "csv",
    ".md": "md",
    ".markdown": "md",
    ".txt": "md",
    ".tex": "tex",
    ".fits": "fits",
    ".fit": "fits",
    ".fts": "fits",
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".he5": "hdf5",
    ".hdf": "hdf5",
    ".nc": "netcdf",
    ".nc4": "netcdf",
    ".cdf": "netcdf",
}
SUFFIXES = frozenset(_SUFFIX_KIND)
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


class ReadError(ValueError):
    """A file this module was asked for and could not read, said plainly."""


@dataclass
class Table:
    """One table out of a file. ``rows(limit)`` opens the file and streams."""

    name: str
    columns: list[str]
    total: int
    rows: Callable[[int], Iterator[list[Any]]]
    note: str = ""


@dataclass
class Described:
    body: str
    previews: list[str] = field(default_factory=list)


def kind_of(path: Path) -> str | None:
    """Content first, suffix second. A NetCDF-4 file is HDF5 inside."""
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError:
        head = b""
    suffix = path.suffix.lower()
    if head.startswith(b"CDF") and head[3:4] in {b"\x01", b"\x02", b"\x05"}:
        return "netcdf"
    if head.startswith(_HDF5_MAGIC):
        return "netcdf" if _SUFFIX_KIND.get(suffix) == "netcdf" else "hdf5"
    if head.startswith(b"SIMPLE  ="):
        return "fits"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as zf:
                if "xl/workbook.xml" in zf.namelist():
                    return "xlsx"
        except (OSError, zipfile.BadZipFile):
            return None
        return None
    return _SUFFIX_KIND.get(suffix)


def split_selector(raw: str, exists: Callable[[str], bool]) -> tuple[str, str]:
    """``data.h5#/obs/flux`` -> (``data.h5``, ``/obs/flux``).

    A ``#`` that is part of a real file name stays in the name.
    """
    text = (raw or "").strip()
    if "#" not in text or exists(text):
        return text, ""
    head, _, tail = text.rpartition("#")
    return head, tail.strip()


# --- small value helpers ---------------------------------------------------


def _py(value: Any) -> Any:
    """numpy scalar or bytes to a plain value csv and openpyxl both take."""
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "SU" and value.ndim == 1:
            return "".join(_py(v) for v in value.tolist()).rstrip("\x00 ")
        return " ".join(str(_py(v)) for v in value.ravel().tolist())
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00 ")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _fmt(value: Any) -> str:
    value = _py(value)
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _stats(data: Any) -> str:
    try:
        arr = np.asarray(data)
        if arr.dtype.kind not in "iufb" or arr.size == 0:
            return ""
        flat = arr.ravel()[:_STATS_SAMPLE].astype("float64", copy=False)
        finite = flat[np.isfinite(flat)]
        if finite.size == 0:
            return "all values missing"
        sampled = " (first 10M values)" if arr.size > _STATS_SAMPLE else ""
        return (
            f"min {finite.min():.6g}, max {finite.max():.6g}, "
            f"mean {finite.mean():.6g}{sampled}"
        )
    except Exception:
        # Stats are a hint beside the data; an odd dtype just goes without them.
        return ""


def _attr_lines(attrs: dict[str, Any], indent: str = "  ") -> list[str]:
    lines = []
    for idx, (key, value) in enumerate(attrs.items()):
        if idx >= _MAX_ATTRS:
            lines.append(f"{indent}... {len(attrs) - _MAX_ATTRS} more")
            break
        text = _fmt(value)
        if len(text) > 120:
            text = text[:117] + "..."
        lines.append(f"{indent}{key}: {text}")
    return lines


def _preview_png(arr: Any, dest: Path, title: str, *, origin: str) -> str:
    """Quick-look image of 2-D data, 1st to 99th percentile stretch."""
    import matplotlib

    matplotlib.use("Agg", force=False)
    from matplotlib.figure import Figure

    data = np.asarray(arr)
    if data.dtype.kind not in "iufb":
        return ""
    data = data.astype("float64")
    while data.ndim > 2:
        data = data[0]
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return ""
    lo, hi = np.percentile(finite, [1.0, 99.0])
    if hi <= lo:
        lo, hi = float(finite.min()), float(finite.max()) or 1.0
    fig = Figure(figsize=(6, 5), dpi=100)
    ax = fig.add_subplot(1, 1, 1)
    shown = ax.imshow(data, origin=origin, cmap="gray", vmin=lo, vmax=hi, aspect="auto")
    fig.colorbar(shown, ax=ax)
    ax.set_title(title[:60])
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest)
    return str(dest)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:8]


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.") or "data"


# --- text-like files -------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def typed(cell: str) -> Any:
    """'12' -> 12, '3.5' -> 3.5. '007' and '1e' stay text."""
    text = cell.strip()
    if not _NUMBER.match(text):
        return cell
    digits = text.lstrip("+-")
    if len(digits) > 1 and digits[0] == "0" and digits[1].isdigit():
        return cell
    try:
        return int(text)
    except ValueError:
        return float(text)


def _csv_dialect(path: Path) -> Any:
    sample = _read_text(path)[:64_000]
    if path.suffix.lower() in {".tsv", ".tab"}:
        return csv.excel_tab
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _csv_table(path: Path) -> Table:
    dialect = _csv_dialect(path)

    def _all() -> Iterator[list[str]]:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.reader(handle, dialect):
                if any(cell.strip() for cell in row):
                    yield row

    first = next(_all(), [])
    total = max(0, sum(1 for _ in _all()) - 1)

    def rows(limit: int) -> Iterator[list[Any]]:
        body = islice(_all(), 1, None)
        for row in islice(body, limit):
            yield [typed(cell) for cell in row]

    return Table(path.stem, [c.strip() for c in first], total, rows)


# --- xlsx --------------------------------------------------------------------


def _xlsx_sheets(path: Path) -> list[str]:
    from openpyxl import load_workbook

    book = load_workbook(str(path), read_only=True)
    try:
        return list(book.sheetnames)
    finally:
        book.close()


def _xlsx_rows(path: Path, sheet: str) -> Iterator[list[Any]]:
    """Cached values; a formula with no cached value shows as its formula."""
    from openpyxl import load_workbook

    values = load_workbook(str(path), read_only=True, data_only=True)
    formulas = load_workbook(str(path), read_only=True)
    try:
        pairs = zip(
            values[sheet].iter_rows(values_only=True),
            formulas[sheet].iter_rows(values_only=True),
            strict=False,
        )
        for vrow, frow in pairs:
            out = []
            for v, f in zip(vrow, frow, strict=False):
                if v is None and isinstance(f, str) and f.startswith("="):
                    out.append(f)
                else:
                    out.append(v)
            while out and out[-1] is None:
                out.pop()
            yield out
    finally:
        values.close()
        formulas.close()


def _xlsx_pick(path: Path, selector: str) -> str:
    sheets = _xlsx_sheets(path)
    if not sheets:
        raise ReadError("The workbook has no sheets.")
    if not selector:
        return sheets[0]
    for name in sheets:
        if name.lower() == selector.lower():
            return name
    raise ReadError(f"No sheet named {selector!r}. Sheets: {', '.join(sheets)}.")


def _xlsx_table(path: Path, selector: str) -> Table:
    sheet = _xlsx_pick(path, selector)

    def _nonempty() -> Iterator[list[Any]]:
        for row in _xlsx_rows(path, sheet):
            if any(v is not None and str(v).strip() for v in row):
                yield row

    first = next(_nonempty(), [])
    total = max(0, sum(1 for _ in _nonempty()) - 1)
    others = [s for s in _xlsx_sheets(path) if s != sheet]
    note = ""
    if others and not selector:
        note = f"sheet {sheet!r} only; other sheets: {', '.join(others)}"

    def rows(limit: int) -> Iterator[list[Any]]:
        yield from islice(islice(_nonempty(), 1, None), limit)

    return Table(sheet, [_fmt(c) for c in first], total, rows, note)


def _describe_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    out: list[str] = []
    formulas_book = load_workbook(str(path), read_only=True)
    try:
        sheet_names = list(formulas_book.sheetnames)
        found: dict[str, list[str]] = {}
        for name in sheet_names:
            hits: list[str] = []
            for row in formulas_book[name].iter_rows():
                for cell in row:
                    value = getattr(cell, "value", None)
                    if isinstance(value, str) and value.startswith("="):
                        if len(hits) < _MAX_FORMULAS:
                            hits.append(f"{cell.coordinate}: {value}")
            found[name] = hits
    finally:
        formulas_book.close()
    out.append(f"workbook: {len(sheet_names)} sheet(s): {', '.join(sheet_names)}")
    for name in sheet_names:
        rows = list(islice(_xlsx_rows(path, name), _SHEET_ROWS + 1))
        more = len(rows) > _SHEET_ROWS
        out.append(f"\nsheet {name}:")
        uncached = 0
        for row in rows[:_SHEET_ROWS]:
            uncached += sum(1 for v in row if isinstance(v, str) and v.startswith("="))
            out.append(" | ".join(_fmt(v) for v in row))
        if more:
            out.append(f"[first {_SHEET_ROWS} rows; read the rest with analyze]")
        if uncached:
            out.append(
                f"[{uncached} formula(s) have no saved result because the file was "
                "never recalculated in Excel, so they show as the formula. Do not "
                "state their values.]"
            )
        elif found.get(name):
            out.append("formulas:")
            out.extend(f"  {line}" for line in found[name])
    return "\n".join(out).strip()


def _describe_csv(path: Path) -> str:
    table = _csv_table(path)
    lines = [f"table: {table.total} data rows, {len(table.columns)} columns"]
    lines.append(" | ".join(table.columns))
    for row in table.rows(_SHEET_ROWS):
        lines.append(" | ".join(_fmt(v) for v in row))
    if table.total > _SHEET_ROWS:
        lines.append(f"[first {_SHEET_ROWS} rows; analyze answers questions on all of them]")
    return "\n".join(lines)


# --- FITS --------------------------------------------------------------------

# Structure cards the summary already says in words.
_FITS_PLUMBING = re.compile(
    r"^(SIMPLE|BITPIX|NAXIS\d*|EXTEND|XTENSION|PCOUNT|GCOUNT|TFIELDS|"
    r"T(TYPE|FORM|UNIT|DIM|NULL|SCAL|ZERO|DISP)\d+|COMMENT|HISTORY|CHECKSUM|DATASUM)$"
)


def _fits_open(path: Path) -> Any:
    from astropy.io import fits

    return fits.open(str(path), memmap=True)


def _describe_fits(path: Path, preview_dir: Path | None) -> Described:
    previews: list[str] = []
    out: list[str] = []
    with _fits_open(path) as hdul:
        out.append(f"FITS: {len(hdul)} HDU(s)")
        for idx, hdu in enumerate(hdul):
            name = hdu.name or ""
            header = hdu.header
            out.append(f"\nHDU {idx} {name} ({type(hdu).__name__})")
            keys = {k: header[k] for k in header if k and not _FITS_PLUMBING.match(k)}
            out.extend(_attr_lines(keys))
            data = hdu.data
            if data is None:
                continue
            columns = getattr(getattr(hdu, "columns", None), "names", None)
            if columns:
                units = [getattr(c, "unit", None) or "" for c in hdu.columns]
                heads = [f"{n} ({u})" if u else n for n, u in zip(columns, units, strict=False)]
                out.append(f"  table: {len(data)} rows x {len(columns)} columns")
                out.append("  " + " | ".join(heads))
                for row in data[:_PREVIEW_ROWS]:
                    out.append("  " + " | ".join(_fmt(v) for v in row))
                if len(data) > _PREVIEW_ROWS:
                    out.append(f"  [first {_PREVIEW_ROWS} rows]")
                continue
            arr = np.asarray(data)
            out.append(f"  image: shape {arr.shape}, {arr.dtype.name}")
            stats = _stats(arr)
            if stats:
                out.append(f"  {stats}")
            if arr.ndim >= 2 and preview_dir is not None and len(previews) < _MAX_PREVIEWS:
                dest = preview_dir / f"{_safe_name(path.stem)}_hdu{idx}.png"
                shot = _preview_png(arr, dest, f"{path.name} HDU {idx}", origin="lower")
                if shot:
                    previews.append(shot)
    return Described("\n".join(out).strip(), previews)


def _fits_table(path: Path, selector: str) -> Table:
    with _fits_open(path) as hdul:
        index = _fits_pick(hdul, selector)
        hdu = hdul[index]
        label = f"HDU {index} {hdu.name or ''}".strip()
        columns = getattr(getattr(hdu, "columns", None), "names", None)
        if columns:
            units = [getattr(c, "unit", None) or "" for c in hdu.columns]
            heads = [f"{n} ({u})" if u else n for n, u in zip(columns, units, strict=False)]
            total = len(hdu.data)
        else:
            arr = np.asarray(hdu.data)
            heads, total = _matrix_heads(arr)

    def rows(limit: int) -> Iterator[list[Any]]:
        with _fits_open(path) as hdul2:
            hdu2 = hdul2[index]
            if columns:
                for row in islice(iter(hdu2.data), limit):
                    yield [_py(v) for v in row]
            else:
                yield from _matrix_rows(np.asarray(hdu2.data), limit)

    return Table(label, heads, total, rows)


def _fits_pick(hdul: Any, selector: str) -> int:
    if selector:
        if selector.isdigit() and int(selector) < len(hdul):
            return int(selector)
        for idx, hdu in enumerate(hdul):
            if (hdu.name or "").lower() == selector.lower():
                return idx
        raise ReadError(f"No HDU {selector!r} in this FITS file ({len(hdul)} HDUs).")
    for idx, hdu in enumerate(hdul):
        if getattr(hdu, "columns", None) is not None and hdu.data is not None:
            return idx
    for idx, hdu in enumerate(hdul):
        if hdu.data is not None:
            return idx
    raise ReadError("This FITS file has no data, only headers.")


def _matrix_heads(arr: Any) -> tuple[list[str], int]:
    """2-D: one row per image row. Other shapes: one row per value."""
    if arr.ndim == 1:
        return ["value"], int(arr.shape[0])
    if arr.ndim == 2:
        return [f"c{i}" for i in range(arr.shape[1])], int(arr.shape[0])
    return [f"i{d}" for d in range(arr.ndim)] + ["value"], int(arr.size)


def _matrix_rows(arr: Any, limit: int) -> Iterator[list[Any]]:
    if arr.ndim == 1:
        for value in arr[:limit]:
            yield [_py(value)]
    elif arr.ndim == 2:
        for row in arr[:limit]:
            yield [_py(v) for v in row]
    else:
        for n, index in enumerate(np.ndindex(arr.shape)):
            if n >= limit:
                return
            yield [*index, _py(arr[index])]


# --- NetCDF (classic and NetCDF-4) and HDF5 -----------------------------------


@dataclass
class _Var:
    name: str
    dims: list[str]
    shape: tuple[int, ...]
    dtype: str
    attrs: dict[str, Any]
    # load(n) reads the first n entries along the first axis; None reads all.
    load: Callable[[int | None], Any]


def _lead(shape: tuple[int, ...], values: int) -> int | None:
    """Leading rows holding about ``values`` values, or None for all of it."""
    if not shape or int(np.prod(shape, dtype=np.int64)) <= values:
        return None
    per_row = max(1, int(np.prod(shape[1:], dtype=np.int64)))
    return max(1, -(-values // per_row))


def _unpack(var: _Var, arr: Any) -> Any:
    """Apply _FillValue, missing_value, scale_factor and add_offset."""
    arr = np.asarray(arr)
    if arr.dtype.kind not in "iuf":
        return arr
    attrs = var.attrs
    keys = ("_FillValue", "missing_value", "scale_factor", "add_offset")
    if not any(k in attrs for k in keys):
        return arr
    out = arr.astype("float64")
    for key in ("_FillValue", "missing_value"):
        if key in attrs:
            for fill in np.atleast_1d(np.asarray(attrs[key])).ravel():
                out[arr == fill] = np.nan
    if "scale_factor" in attrs:
        out = out * float(np.asarray(attrs["scale_factor"]).ravel()[0])
    if "add_offset" in attrs:
        out = out + float(np.asarray(attrs["add_offset"]).ravel()[0])
    return out


_H5_PLUMBING = frozenset({"DIMENSION_LIST", "REFERENCE_LIST", "CLASS", "NAME"})
_NC_TYPES = {
    1: ">i1", 2: "S1", 3: ">i2", 4: ">i4", 5: ">f4", 6: ">f8",
    7: ">u1", 8: ">u2", 9: ">u4", 10: ">i8", 11: ">u8",
}


class _ClassicNetCDF:
    """NetCDF-3 classic, 64-bit offset, and CDF-5, read only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with path.open("rb") as handle:
            self._buf = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        self.version = self._buf[3]
        self._pos = 4
        self._big = self.version == 5
        numrecs = self._non_neg()
        self.dims = self._dim_list()
        self.attrs = self._att_list()
        self.vars = self._var_list()
        record_vars = [v for v in self.vars if v["record"]]
        if len(record_vars) == 1:
            self.recsize = record_vars[0]["slab"]
        else:
            self.recsize = sum(v["vsize"] for v in record_vars)
        streaming = numrecs in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        if streaming and record_vars and self.recsize:
            start = min(v["begin"] for v in record_vars)
            numrecs = (len(self._buf) - start) // self.recsize
        self.numrecs = 0 if streaming and not record_vars else numrecs

    def close(self) -> None:
        self._buf.close()

    def _int(self, size: int) -> int:
        raw = self._buf[self._pos : self._pos + size]
        self._pos += size
        return int.from_bytes(raw, "big")

    def _non_neg(self) -> int:
        return self._int(8 if self._big else 4)

    def _name(self) -> str:
        n = self._non_neg()
        raw = self._buf[self._pos : self._pos + n]
        self._pos += n + (-n % 4)
        return raw.decode("utf-8", errors="replace")

    def _dim_list(self) -> list[tuple[str, int]]:
        tag = self._int(4)
        count = self._non_neg()
        if tag == 0:
            return []
        return [(self._name(), self._non_neg()) for _ in range(count)]

    def _att_list(self) -> dict[str, Any]:
        tag = self._int(4)
        count = self._non_neg()
        out: dict[str, Any] = {}
        if tag == 0:
            return out
        for _ in range(count):
            name = self._name()
            nc_type = self._int(4)
            n = self._non_neg()
            dtype = np.dtype(_NC_TYPES[nc_type])
            size = n * dtype.itemsize
            raw = bytes(self._buf[self._pos : self._pos + size])
            self._pos += size + (-size % 4)
            if nc_type == 2:
                out[name] = raw.decode("utf-8", errors="replace").rstrip("\x00")
            else:
                values = np.frombuffer(raw, dtype=dtype)
                out[name] = values[0] if values.size == 1 else values
        return out

    def _var_list(self) -> list[dict[str, Any]]:
        tag = self._int(4)
        count = self._non_neg()
        out: list[dict[str, Any]] = []
        if tag == 0:
            return out
        for _ in range(count):
            name = self._name()
            ndims = self._non_neg()
            dimids = [self._non_neg() for _ in range(ndims)]
            attrs = self._att_list()
            nc_type = self._int(4)
            vsize = self._non_neg()
            begin = self._int(4 if self.version == 1 else 8)
            dims = [self.dims[i][0] for i in dimids]
            lengths = [self.dims[i][1] for i in dimids]
            record = bool(lengths) and lengths[0] == 0
            dtype = np.dtype(_NC_TYPES[nc_type])
            inner = lengths[1:] if record else lengths
            slab = int(np.prod(inner, dtype=np.int64)) * dtype.itemsize
            out.append(
                {
                    "name": name, "dims": dims, "lengths": lengths,
                    "attrs": attrs, "dtype": dtype, "vsize": vsize,
                    "begin": begin, "record": record, "slab": slab,
                    "char": nc_type == 2,
                }
            )
        return out

    def read(self, var: dict[str, Any], rows: int | None = None) -> Any:
        dtype = var["dtype"]
        if var["record"]:
            inner = tuple(var["lengths"][1:])
            shape = (self.numrecs, *inner)
            strides = [self.recsize]
            step = dtype.itemsize
            tail = []
            for length in reversed(inner):
                tail.append(step)
                step *= length
            strides += list(reversed(tail))
            view = np.ndarray(
                shape, dtype=dtype, buffer=self._buf, offset=var["begin"],
                strides=tuple(strides),
            )
        else:
            shape = tuple(var["lengths"])
            count = int(np.prod(shape, dtype=np.int64)) if shape else 1
            view = np.frombuffer(self._buf, dtype=dtype, count=count, offset=var["begin"])
            view = view.reshape(shape)
        arr = np.array(view if rows is None or view.ndim == 0 else view[:rows])
        if var["char"] and arr.ndim >= 1:
            return _join_chars(arr)
        return arr.astype(dtype.newbyteorder("="))


def _netcdf_vars(
    path: Path, holder: list[Any]
) -> tuple[list[_Var], dict[str, Any], dict[str, int]]:
    """Variables, global attributes and dimension sizes for either flavour.

    ``holder`` receives the open handle so the caller can close it.
    """
    with path.open("rb") as handle:
        head = handle.read(4)
    if head.startswith(b"CDF"):
        nc = _ClassicNetCDF(path)
        holder.append(nc)
        dims = {name: (n or nc.numrecs) for name, n in nc.dims}
        out = []
        for raw in nc.vars:
            lengths = list(raw["lengths"])
            if raw["record"]:
                lengths[0] = nc.numrecs
            shape = tuple(lengths[:-1] if raw["char"] and lengths else lengths)
            out.append(
                _Var(
                    raw["name"], raw["dims"][: len(shape)], shape,
                    "char" if raw["char"] else str(raw["dtype"].newbyteorder("=")),
                    raw["attrs"], lambda rows=None, raw=raw: nc.read(raw, rows),
                )
            )
        return out, nc.attrs, dims
    import h5py

    h5 = h5py.File(str(path), "r")
    holder.append(h5)
    found: list[_Var] = []
    dims: dict[str, int] = {}

    def visit(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Dataset):
            return
        attrs = {
            k: v
            for k, v in obj.attrs.items()
            if not k.startswith("_Netcdf4") and k not in _H5_PLUMBING
        }
        name_attr = _fmt(obj.attrs.get("NAME", b""))
        is_dim_only = "netCDF dimension but not a netCDF variable" in name_attr
        if obj.attrs.get("CLASS") is not None and obj.ndim == 1:
            dims[name.split("/")[-1]] = int(obj.shape[0])
        if is_dim_only:
            return
        labels = []
        for i in range(obj.ndim):
            try:
                scales = list(obj.dims[i].values())
            except Exception:
                # Unattached or foreign dimension scales: the axis gets dimN.
                scales = []
            if scales:
                labels.append(scales[0].name.split("/")[-1])
            elif obj.attrs.get("CLASS") is not None and obj.ndim == 1:
                labels.append(name.split("/")[-1])
            else:
                labels.append(f"dim{i}")
        if obj.dtype.kind == "S" and obj.dtype.itemsize == 1 and obj.ndim >= 1:
            found.append(
                _Var(
                    name, labels[:-1], tuple(obj.shape[:-1]), "char", attrs,
                    lambda rows=None, obj=obj: _join_chars(_h5_read(obj, rows)),
                )
            )
            return
        found.append(
            _Var(
                name, labels, tuple(obj.shape), str(obj.dtype), attrs,
                lambda rows=None, obj=obj: _h5_read(obj, rows),
            )
        )

    h5.visititems(visit)
    return found, {k: v for k, v in h5.attrs.items() if not k.startswith("_")}, dims


def _h5_read(ds: Any, rows: int | None) -> Any:
    return ds[()] if rows is None or ds.ndim == 0 else ds[:rows]


def _join_chars(arr: Any) -> Any:
    """NetCDF char arrays: the last axis spells one string."""
    arr = np.asarray(arr)
    flat = arr.reshape(-1, arr.shape[-1]) if arr.ndim else arr.reshape(1, 1)
    words = [
        b"".join(row.tolist()).rstrip(b"\x00").decode("utf-8", errors="replace")
        for row in flat
    ]
    return np.array(words, dtype=object).reshape(arr.shape[:-1])


def _close_all(holder: list[Any]) -> None:
    for item in holder:
        try:
            item.close()
        except Exception:
            # Read-only handles; a failed close loses nothing and must not
            # hide the result or the real error being raised.
            pass


def _head(var: _Var) -> str:
    units = _fmt(var.attrs.get("units", ""))
    return f"{var.name} ({units})" if units else var.name


def _is_coord(var: _Var) -> bool:
    return len(var.dims) == 1 and var.dims[0] == var.name.split("/")[-1]


def _describe_netcdf(path: Path, preview_dir: Path | None) -> Described:
    holder: list[Any] = []
    previews: list[str] = []
    try:
        variables, gattrs, dims = _netcdf_vars(path, holder)
        out = ["NetCDF"]
        if dims:
            out.append("dimensions: " + ", ".join(f"{k}={v}" for k, v in dims.items()))
        if gattrs:
            out.append("global attributes:")
            out.extend(_attr_lines(gattrs))
        out.append("variables:")
        for var in variables:
            long_name = _fmt(var.attrs.get("long_name", ""))
            units = _fmt(var.attrs.get("units", ""))
            label = f"  {var.name}({', '.join(var.dims)}) {var.dtype} shape {var.shape}"
            if units:
                label += f" [{units}]"
            if long_name:
                label += f" {long_name}"
            out.append(label)
            if var.dtype == "char":
                continue
            lead = _lead(var.shape, _STATS_SAMPLE)
            data = _unpack(var, var.load(lead))
            stats = _stats(data)
            if stats and lead is not None:
                stats += f" (first {lead} of {var.shape[0]} along {var.dims[0]})"
            if stats:
                out.append(f"    {stats}")
            if lead is None and np.asarray(data).ndim == 1 and _is_coord(var) and data.size:
                first, last = _fmt(data[0]), _fmt(data[-1])
                out.append(f"    from {first} to {last}")
            if (
                np.asarray(data).ndim >= 2
                and preview_dir is not None
                and len(previews) < _MAX_PREVIEWS
            ):
                dest = preview_dir / f"{_safe_name(path.stem)}_{_safe_name(var.name)}.png"
                shot = _preview_png(data, dest, f"{var.name} {units}", origin="lower")
                if shot:
                    previews.append(shot)
        return Described("\n".join(out), previews)
    finally:
        _close_all(holder)


def _pick_var(variables: list[_Var], selector: str) -> _Var:
    usable = [v for v in variables if v.dtype != "char"]
    if selector:
        want = selector.strip("/").lower()
        for var in variables:
            if var.name.strip("/").lower() == want:
                return var
        names = ", ".join(v.name for v in variables)
        raise ReadError(f"No variable {selector!r}. Variables: {names}.")
    data_vars = [v for v in usable if not _is_coord(v)] or usable
    if not data_vars:
        raise ReadError("This file has no numeric variables to convert.")
    return max(data_vars, key=lambda v: int(np.prod(v.shape, dtype=np.int64)))


def _netcdf_table(path: Path, selector: str) -> Table:
    holder: list[Any] = []
    try:
        variables, _gattrs, _dims = _netcdf_vars(path, holder)
        target = _pick_var(variables, selector)
        by_name = {v.name.split("/")[-1]: v for v in variables}
        if len(target.shape) <= 1:
            dim = target.dims[0] if target.dims else ""
            same = [
                v for v in variables
                if v.dims == target.dims and len(v.shape) == 1 and not _is_coord(v)
            ]
            coord = by_name.get(dim)
            cols = ([coord] if coord is not None and coord is not target else []) + same
            heads = [_head(v) for v in cols]
            total = int(target.shape[0]) if target.shape else 1
            names = [v.name for v in cols]
            note = ""
        else:
            heads = [_head(by_name[d]) if d in by_name else d for d in target.dims]
            heads.append(_head(target))
            total = int(np.prod(target.shape, dtype=np.int64))
            names = [target.name]
            note = f"{target.name} in long form: one row per value"
        label = target.name
    finally:
        _close_all(holder)

    def rows(limit: int) -> Iterator[list[Any]]:
        inner: list[Any] = []
        try:
            vs, _g, _d = _netcdf_vars(path, inner)
            lookup = {v.name: v for v in vs}
            short = {v.name.split("/")[-1]: v for v in vs}
            if len(names) == 1 and len(lookup[names[0]].shape) >= 2:
                var = lookup[names[0]]
                data = _unpack(var, var.load(_lead(var.shape, limit)))
                axes = []
                for i, d in enumerate(var.dims):
                    c = short.get(d)
                    if c is not None and len(c.shape) == 1 and c.shape[0] >= data.shape[i]:
                        axes.append(np.asarray(_unpack(c, c.load(None))))
                    else:
                        axes.append(np.arange(data.shape[i]))
                for n, index in enumerate(np.ndindex(data.shape)):
                    if n >= limit:
                        return
                    yield [_py(axes[i][k]) for i, k in enumerate(index)] + [_py(data[index])]
                return
            columns = [_unpack(lookup[n], lookup[n].load(min(limit, total))) for n in names]
            count = min(len(np.atleast_1d(c)) for c in columns) if columns else 0
            for i in range(min(count, limit)):
                yield [_py(np.atleast_1d(c)[i]) for c in columns]
        finally:
            _close_all(inner)

    return Table(label, heads, total, rows, note)


def _describe_hdf5(path: Path, preview_dir: Path | None) -> Described:
    import h5py

    previews: list[str] = []
    out = ["HDF5"]
    with h5py.File(str(path), "r") as h5:
        if h5.attrs:
            out.append("root attributes:")
            out.extend(_attr_lines(dict(h5.attrs)))
        lines: list[str] = []

        def visit(name: str, obj: Any) -> None:
            depth = "  " * (name.count("/") + 1)
            if isinstance(obj, h5py.Group):
                lines.append(f"{depth}{name}/ (group)")
                lines.extend(_attr_lines(dict(obj.attrs), depth + "  "))
                return
            fields = obj.dtype.names
            kind = f"fields {', '.join(fields)}" if fields else str(obj.dtype)
            lines.append(f"{depth}{name} shape {obj.shape} {kind}")
            lines.extend(_attr_lines(dict(obj.attrs), depth + "  "))
            if obj.size and obj.size <= 10 and not fields:
                lines.append(f"{depth}  values: {_fmt(obj[()])}")
            elif obj.size and not fields and obj.dtype.kind in "iufb":
                lead = _lead(obj.shape, _STATS_SAMPLE)
                stats = _stats(_h5_read(obj, lead))
                if stats and lead is not None:
                    stats += f" (first {lead} of {obj.shape[0]} rows)"
                if stats:
                    lines.append(f"{depth}  {stats}")
            if (
                obj.ndim >= 2
                and obj.dtype.kind in "iuf"
                and preview_dir is not None
                and len(previews) < _MAX_PREVIEWS
            ):
                dest = preview_dir / f"{_safe_name(path.stem)}_{_safe_name(name)}.png"
                head = _h5_read(obj, _lead(obj.shape, _STATS_SAMPLE))
                shot = _preview_png(head, dest, name, origin="upper")
                if shot:
                    previews.append(shot)

        h5.visititems(visit)
        out.append("contents:")
        out.extend(lines)
    return Described("\n".join(out), previews)


def _hdf5_table(path: Path, selector: str) -> Table:
    import h5py

    with h5py.File(str(path), "r") as h5:
        if selector and selector.strip("/") and selector.strip("/") not in h5:
            raise ReadError(f"No dataset or group {selector!r} in this file.")
        start = h5[selector.strip("/")] if selector.strip("/") else h5
        if isinstance(start, h5py.Dataset):
            plan = ("dataset", [start.name])
        else:
            plan = _hdf5_plan(start)
        kind, names = plan
        first = h5[names[0]]
        if kind == "columns":
            heads = [_h5_head(h5[n]) for n in names]
            total = int(first.shape[0])
        elif first.dtype.names:
            heads = list(first.dtype.names)
            total = int(first.shape[0]) if first.shape else 1
            kind = "compound"
        else:
            heads, total = _matrix_heads(np.empty(first.shape, dtype="u1"))
        label = names[0] if len(names) == 1 else (start.name or "/")

    def rows(limit: int) -> Iterator[list[Any]]:
        with h5py.File(str(path), "r") as h5b:
            if kind == "columns":
                cols = [h5b[n][: min(limit, total)] for n in names]
                for i in range(min(limit, total)):
                    yield [_py(c[i]) for c in cols]
            elif kind == "compound":
                for record in h5b[names[0]][: min(limit, total)]:
                    yield [_py(v) for v in record]
            else:
                yield from _matrix_rows(h5b[names[0]][()], limit)

    return Table(label, heads, total, rows)


def _h5_head(ds: Any) -> str:
    units = _fmt(ds.attrs.get("units", ""))
    leaf = ds.name.split("/")[-1]
    return f"{leaf} ({units})" if units else leaf


def _hdf5_plan(group: Any) -> tuple[str, list[str]]:
    """1-D datasets of one length in one group become columns; else first dataset."""
    import h5py

    datasets: list[Any] = []
    group.visititems(lambda _n, o: datasets.append(o) if isinstance(o, h5py.Dataset) else None)
    if not datasets:
        raise ReadError("No datasets in this file or group.")
    groups: dict[tuple[str, int], list[str]] = {}
    for ds in datasets:
        if ds.ndim == 1 and not ds.dtype.names:
            parent = ds.name.rsplit("/", 1)[0]
            groups.setdefault((parent, int(ds.shape[0])), []).append(ds.name)
    compound = [ds for ds in datasets if ds.dtype.names]
    if compound:
        return "dataset", [compound[0].name]
    if groups:
        best = max(groups.values(), key=len)
        if len(best) > 1:
            return "columns", best
    return "dataset", [datasets[0].name]


# --- LaTeX -------------------------------------------------------------------

_TEX_HEAD = [
    (re.compile(r"\\section\*?\{([^}]*)\}"), "# "),
    (re.compile(r"\\subsection\*?\{([^}]*)\}"), "## "),
    (re.compile(r"\\subsubsection\*?\{([^}]*)\}"), "### "),
]


def tex_to_markdown(source: str) -> tuple[str, str]:
    """(title, markdown) from LaTeX source. Structure, not typesetting.

    Sections become headings, itemize/enumerate become bullets, display math
    stays as $$...$$ so document writes it the way it writes any equation.
    """
    text = source.replace("\r\n", "\n")
    text = re.sub(r"(?<!\\)%.*", "", text)
    title_match = re.search(r"\\title\{([^}]*)\}", text)
    title = title_match.group(1).strip() if title_match else ""
    body_match = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.S)
    if body_match:
        text = body_match.group(1)
    text = re.sub(r"\\(?:maketitle|tableofcontents|newpage|clearpage|centering)\b", "", text)
    text = re.sub(r"\\(?:label|ref|cite|eqref)\{[^}]*\}", "", text)
    for pattern, mark in _TEX_HEAD:
        text = pattern.sub(lambda m, mark=mark: f"\n\n{mark}{m.group(1).strip()}\n\n", text)
    text = re.sub(
        r"\\begin\{(equation|align|gather|displaymath)\*?\}(.*?)\\end\{\1\*?\}",
        lambda m: f"\n\n$${m.group(2).strip()}$$\n\n",
        text,
        flags=re.S,
    )
    text = re.sub(r"\\\[(.*?)\\\]", lambda m: f"\n\n$${m.group(1).strip()}$$\n\n", text, flags=re.S)
    text = re.sub(r"\\begin\{(?:itemize|enumerate)\}", "\n\n", text)
    text = re.sub(r"\\end\{(?:itemize|enumerate)\}", "\n\n", text)
    text = re.sub(r"\s*\\item\s+", "\n- ", text)
    text = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", text)
    text = re.sub(r"\\(?:textit|emph|texttt|underline)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\begin\{[a-zA-Z*]+\}(?:\[[^\]]*\])?|\\end\{[a-zA-Z*]+\}", "", text)
    lines = [ln.strip() for ln in text.split("\n")]
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return title, joined


# --- entry points ------------------------------------------------------------


def describe(path: Path, kind: str, preview_dir: Path | None) -> Described:
    """Text for the model. ``preview_dir`` None skips quick-look images."""
    try:
        if kind == "xlsx":
            return Described(_describe_xlsx(path))
        if kind == "csv":
            return Described(_describe_csv(path))
        if kind in {"md", "tex"}:
            return Described(_read_text(path).strip())
        dest = None
        if preview_dir is not None:
            dest = preview_dir / f"{_safe_name(path.stem)}_{_digest(path)}"
        if kind == "fits":
            return _describe_fits(path, dest)
        if kind == "netcdf":
            return _describe_netcdf(path, dest)
        if kind == "hdf5":
            return _describe_hdf5(path, dest)
    except ReadError:
        raise
    except ImportError as exc:
        raise ReadError(f"A reader for {kind} is not installed ({exc.name}).") from exc
    except Exception as exc:
        raise ReadError(f"Could not read {path.name} as {kind}: {exc}") from exc
    raise ReadError(f"No reader for {kind}.")


def table(path: Path, kind: str, selector: str = "") -> Table:
    """The data for csv or xlsx output."""
    try:
        if kind == "csv":
            return _csv_table(path)
        if kind == "xlsx":
            return _xlsx_table(path, selector)
        if kind == "fits":
            return _fits_table(path, selector)
        if kind == "netcdf":
            return _netcdf_table(path, selector)
        if kind == "hdf5":
            return _hdf5_table(path, selector)
    except ReadError:
        raise
    except ImportError as exc:
        raise ReadError(f"A reader for {kind} is not installed ({exc.name}).") from exc
    except Exception as exc:
        raise ReadError(f"Could not read a table from {path.name}: {exc}") from exc
    raise ReadError(f"{kind} is not a table format.")


def markdown_table(tab: Table, limit: int) -> str:
    """The first ``limit`` rows as a markdown table, for pdf, docx and md."""
    buf = io.StringIO()
    width = len(tab.columns) or 1
    heads = tab.columns or ["value"]
    buf.write("| " + " | ".join(h.replace("|", "/") for h in heads) + " |\n")
    buf.write("|" + "---|" * width + "\n")
    for row in tab.rows(limit):
        cells = [_fmt(v).replace("|", "/") for v in row]
        buf.write("| " + " | ".join(cells) + " |\n")
    return buf.getvalue()
