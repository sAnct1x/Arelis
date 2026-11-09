# Spreadsheets

Ask Arelis for an Excel sheet and she writes a real `.xlsx`, not a table of text.

## What a new sheet gets

- **Real cells.** Numbers are numbers, so Excel can add them up. `12.5%` is stored as 0.125 shown as a percent, `$1,200.50` as currency, `2026-11-09` as a date, and `3.140` keeps its three decimals. IDs with leading zeros, such as `007`, stay text.
- **Live formulas.** Any cell that starts with `=` is a formula, for example `=SUM(B2:B9)` or `=AVERAGE(Runs!B2:B9)`. Excel computes them when the file opens. Newer functions such as `STDEV.S`, `IFS` and `XLOOKUP` are saved the way Excel expects, so they do not show `#NAME?`.
- **Headers and units.** The first row is bold, frozen and filterable. Put units in the header, like `Mass (kg)`. Chart axes use those headers.
- **Charts inside the sheet.** She can add bar, horizontal bar, line, scatter, pie and area charts next to the data. Total and mean rows at the bottom are left out of a chart unless she is told to include them.
- **Number formats** per column, such as two decimals or a percent.

If a formula names a function Excel does not have, or uses a spilling function like `FILTER` that may only show its first value, her reply lists it under "Check".

## Editing a sheet you already have

Point her at an existing `.xlsx` and say what to change: fill in cells, add rows, add a sheet, or add a chart.

- **Your file is not overwritten.** She writes an edited copy named like `budget-edited.xlsx` in the documents folder. If you ask her to replace a file, the previous version is saved first as `name.backup-<date>-<time>.xlsx`.
- **The rest of the workbook stays.** Other sheets, cell styles, formulas, merged cells, tables, comments and charts are kept. New rows take the style of the row above, and a table or filter that ended at the last row grows to include them.
- **She refuses rather than losing anything.** Some things cannot be carried through a save by the library she uses: pivot tables, shapes and text boxes, macros, threaded comments, slicers, form controls and some Excel 2010+ features like sparklines. If your file has any of these, she says what would be lost and writes nothing. Make that change in Excel instead, or ask her for a new sheet built from the data.
- `.xls` and `.xlsm` files are not edited. Charts that were already in the file keep their old data range, so new rows do not appear in them.

Cached results are not stored, so a program that never calculates formulas shows them blank until the file is opened in Excel or LibreOffice.
