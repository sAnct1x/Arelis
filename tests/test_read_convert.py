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
