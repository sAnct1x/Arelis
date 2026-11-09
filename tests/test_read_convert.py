"""Track A1 read: doc_extract for science data and structured Word text."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from arelis.attachments import detect_kind, route_tool
from arelis.tools.doc_extract import DocExtractTool

# NetCDF-3 classic, written by netCDF4-python: tas(time, lat, lon) int16
# packed with scale_factor 0.1, add_offset 200 and _FillValue -999 at [0, 0, 0].
_CLASSIC = Path(__file__).parent / "fixtures" / "classic3.nc"


async def test_doc_extract_reads_fits_hdf5_and_classic_netcdf(tmp_path: Path) -> None:
    import h5py
    from astropy.io import fits

    image = fits.PrimaryHDU(np.arange(12, dtype="f4").reshape(3, 4))
    image.header["OBJECT"] = "M31"
    cat = fits.BinTableHDU.from_columns(
        [fits.Column(name="ra", format="D", unit="deg", array=[10.5, 11.25])], name="CAT"
    )
    fits.HDUList([image, cat]).writeto(tmp_path / "m31.fits")
    with h5py.File(tmp_path / "run.h5", "w") as h5:
        h5.create_dataset("obs/flux", data=np.array([1.5, 2.5, 4.0]))
    shutil.copy(_CLASSIC, tmp_path / "air.nc")
    tool = DocExtractTool([str(tmp_path)])

    read = await tool.run(path=str(tmp_path / "m31.fits"))
    assert read.ok and read.data["source"] == "fits"
    assert "OBJECT: M31" in read.output and "ra (deg)" in read.output and "11.25" in read.output
    assert Path(read.data["preview_images"][0]).is_file()

    read = await tool.run(path=str(tmp_path / "run.h5"))
    assert read.ok and "obs/flux shape (3,)" in read.output and "values: 1.5 2.5 4.0" in read.output

    read = await tool.run(path=str(tmp_path / "air.nc"))
    assert read.ok and read.data["source"] == "netcdf"
    assert "tas(time, lat, lon)" in read.output and "[K]" in read.output
    # Unpacked and fill-masked: 200.1 is the smallest real value.
    assert "min 200.1, max 211.1" in read.output

    assert detect_kind("air.nc") == "doc" and route_tool("doc") == "doc_extract"


async def test_doc_extract_reads_docx_in_reading_order(tmp_path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("Results", 1)
    table = doc.add_table(rows=2, cols=2)
    for (r, c), text in {(0, 0): "a", (0, 1): "b", (1, 0): "1", (1, 1): "2"}.items():
        table.cell(r, c).text = text
    doc.add_paragraph("after the table")
    doc.save(str(tmp_path / "notes.docx"))

    read = await DocExtractTool([str(tmp_path)]).run(path=str(tmp_path / "notes.docx"))
    assert read.ok, read.output
    text = read.output
    assert text.index("# Results") < text.index("| a | b |") < text.index("after the table")


def test_doc_extract_caps_fits_preview_and_classic_netcdf(
    tmp_path: Path, monkeypatch
) -> None:
    """FITS previews sample; classic NetCDF refuses oversized headers."""
    import struct

    from astropy.io import fits

    import arelis.tools.file_read as fr

    # --- FITS: array larger than the sample cap must not reach _preview_png whole.
    monkeypatch.setattr(fr, "_STATS_SAMPLE", 20)
    seen: list[int] = []
    real_preview = fr._preview_png

    def _capture(arr, dest, title, *, origin):
        seen.append(int(np.asarray(arr).size))
        return real_preview(arr, dest, title, origin=origin)

    monkeypatch.setattr(fr, "_preview_png", _capture)
    fits.PrimaryHDU(np.arange(100, dtype="f4").reshape(10, 10)).writeto(
        tmp_path / "wide.fits"
    )
    described = fr._describe_fits(tmp_path / "wide.fits", tmp_path / "previews")
    assert described.previews, described.body
    assert seen == [20], seen  # lead 2 rows x 10 cols, not the full 100

    # --- Classic NetCDF: a tiny file with a dim count over the ceiling.
    crafted = tmp_path / "oversized.nc"
    crafted.write_bytes(
        b"CDF\x01"
        + struct.pack(">I", 0)  # numrecs
        + struct.pack(">I", 10)  # NC_DIMENSION
        + struct.pack(">I", fr._NC_MAX_DIMS + 1)
    )
    try:
        fr._ClassicNetCDF(crafted)
        raised = None
    except fr.ReadError as exc:
        raised = exc
    assert raised is not None, "oversized dim count must raise ReadError"
    assert "too many" in str(raised).lower()
