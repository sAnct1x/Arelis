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

Converting files to another format is a separate step.
