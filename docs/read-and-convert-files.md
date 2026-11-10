# Reading and converting files

## Reading

Ask Arelis to read a file in your workspace folder, or attach it, and she
reads it herself. You do not need to paste anything.

| File | What she reads |
| --- | --- |
| PDF | The text, page by page. A scanned or handwritten PDF is read from the page pictures. |
| Word (.docx) | The text in reading order, with headings, lists and tables kept. |
| PowerPoint (.pptx) | The text on each slide. |
| Excel (.xlsx) | Every sheet, the first 200 rows of each, and the formulas in it. A formula whose result was never saved (the file was not recalculated in Excel) shows as the formula, not a value. |
| CSV, TSV | The columns and the first 200 rows. Ask a question about the numbers and she uses the data tool on all of them. |
| Markdown, text, LaTeX (.tex) | The file as written. |
| FITS | Each HDU: key header cards, table columns with units, and image size and value range. |
| HDF5 (.h5) | The tree of groups and datasets, with shapes, attributes and value ranges. |
| NetCDF (.nc) | Dimensions, global attributes and each variable with its units. Packed values are unpacked and fill values count as missing. NetCDF-3 and NetCDF-4 both work. |
| Pictures | She describes them or reads the text in them, as before. |

For 2-D data in FITS, HDF5 or NetCDF she also saves a quick-look picture
(1st to 99th percentile stretch) under `outputs/images/data_previews/`, and
can look at it if you ask what the data shows.

## Converting

Ask for the format you want, for example "turn report.docx into a PDF" or
"save air.nc as a spreadsheet". The new file lands next to her other
documents (the project's `documents` folder, or `outputs/documents`), and
the original is never changed.

| From | To |
| --- | --- |
| Word, markdown, text, PowerPoint | PDF, Word, markdown, text |
| PDF | Word, markdown, text (the text only; layout and pictures are not kept) |
| CSV | Excel, and Excel to CSV. Numbers stay numbers. |
| FITS, HDF5, NetCDF | CSV or Excel, then a chart from the CSV if you ask |
| LaTeX | PDF (needs a TeX engine, see below), Word, markdown |
| Pictures | PNG, JPG, WebP, TIFF, BMP, at any size |

To pick one part of a file, add `#` and its name: `obs.xlsx#Sheet2`,
`image.fits#1` or `image.fits#EVENTS`, `run.h5#/obs/flux`, `air.nc#tas`.
Without one, she picks the first sheet, the first FITS table, or the
largest NetCDF variable. A variable with more than one dimension is written
one row per value, with a column for each coordinate.

Excel holds at most 1,048,575 rows. A bigger table stops there, and she
says so. A PDF or Word copy of a table shows its first 500 rows.

Writing formulas or charts into a spreadsheet, or editing one you already
have, is a separate feature.

## LaTeX to PDF

Arelis does not include a TeX engine. If MiKTeX, TeX Live or tectonic is
installed (she looks for `pdflatex`, `xelatex`, `lualatex` and `tectonic`),
she typesets the .tex with it, with shell escape off, and tells you which
engine she used. If none is installed she says so, and can still convert
the .tex to Word or markdown with its math kept.

## Files outside the workspace

If you type a path that is not inside a workspace folder, Arelis shows an
Allow card before she reads it. That includes folders whose names have
spaces, such as a Desktop folder. Allow is read-only and lasts for this
session. She will not change that file. To keep access, add the folder in
Settings.

If you skip the card, she does not open the file.

## The message box

The box you type into grows with the text, up to about six lines, and then
scrolls, so a long path or a long question stays visible.

