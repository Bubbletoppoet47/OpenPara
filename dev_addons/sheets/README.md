# Sheets (dev add-on)

A spreadsheet tab. Playground only; nothing in the core program changes.

- **Formulas**: Excel's syntax, 118 functions, `$` references, other sheets, sheet-scoped names. Cell references stay `F62`-style.
- **Files**: `.opsheet` (JSON, pictures inside). Excel `.xlsx` opens and exports (openpyxl is downloaded once, on first use).
- **Studies**: Data > Import study; Refresh from study reads it again and fills formulas next to it down (it acts on the study under or next to the cursor, and asks when the cursor is elsewhere). Select study picks the whole block; Delete study (Data tab or right-click) takes it off the sheet - its cells go, or the numbers stay as plain cells - in one undo step, and Refresh no longer touches that area.
- **Charts**: Insert chart (from the selected cells, or empty and pick the cells after); double-click a chart to open the panel on the right.
  Setup (type, data range, X, series, left/right axis, swap X and Y), Customize (fonts, lines, grid, frame, legend, limit lines, zones, notes) and
  Advanced (every matplotlib setting as a typed input, saved with the chart). Looks (presets) are saved in `chart_presets.json`. PNG/SVG/PDF.
- **Images**: copy a screenshot (or any picture) and press Ctrl+V: it lands at the selected cell. The Images tab mirrors Charts: Insert image (a PNG / JPG / BMP / GIF / WebP file),
  Edit image, Copy image (a duplicate), Export image, Delete image. Drag a picture to move it, drag its corner to resize it; double-click it to open the panel on the right
  (width, height, keep proportions, scale, back to the original size). Ctrl+C / Ctrl+X on a picked picture copy it for other programs. Pictures are kept inside the `.opsheet`
  file and go into the `.xlsx` as Excel pictures (and come back from it). Cells copied from Excel paste as cells; Paste special > Picture takes the image instead.
  Like charts, a picture sits at a pixel position, so inserting rows above it does not move it.
- **Import CSV**: Import tab > Import CSV brings a `.csv` / `.tsv` / `.txt` file onto the sheet, at the selected cell or on a new sheet named after the file. A window shows the
  start of the file first: the separator (comma, semicolon, tab or pipe; guessed from the first lines), "first row holds column names" (made bold; guessed), and "numbers are
  written with a decimal comma" (guessed). UTF-8 (with or without a BOM), UTF-16 and Windows-1252 files are read; quoted fields with separators and line breaks work.
  Numbers, percentages and TRUE / FALSE become real values; everything else stays text. Nothing from a file becomes a formula (text that starts with `=` stays text), codes
  such as 007 keep their zeros, and dates stay text (Sheets has no date type yet). Cells the import would replace are counted and asked about first. The whole import is one
  undo step (a new sheet included). Rows or columns beyond the sheet, and anything past 1,000,000 cells, are left out and said so. Import study and Import .xlsx stay on the Data tab.
- **Selecting**: Shift / Ctrl + click on cells, rows and columns; every block takes part in clear, format, fill, widths, insert and delete.
- **Editing references**: F4 in the cell editor or the formula bar cycles the reference at the cursor (or every one in the selection) through `$B$2`, `B$2`, `$B2`, `B2`.
- **Fill and move**: dragging the fill handle outlines the cells it will fill and shows the values they will get. Dragging the border of a selection moves it
  (Ctrl: copies it), and so does Cut and Paste: every formula, name, chart range, limit line and study block that points at the moved cells follows them, in one undo step.
- **Ribbon size**: View > Ribbon size (icon 10-48 pt, text 8-20 pt), kept in `prefs.json` next to the looks.
- **Standards**: Engineering tab. `std_aisi16.py` encodes AISI S100-16 connection equations (J2, J3, J4) as `AISI16.J4_4_1(...)` etc.
  Equations and section numbers only; the standard's text is not copied.
- **Other add-ons** can offer a standard through the `sheets_standard` hook (return a `sh_std.Pack`).

Modules: `sh_engine` / `sh_funcs` (formulas), `sh_book` (workbook, undo), `sh_grid` / `sh_edit` (grid and editing), `sh_dialogs`, `sh_chart` (drawing),
`sh_panel` (the chart panel), `sh_adv` (the advanced settings, built from the installed matplotlib), `sh_presets` (looks), `sh_prefs` / `sh_ribbon` (ribbon size),
`sh_picture` (pictures on the sheet and their panel), `sh_csv` (reading a CSV file; no Qt), `sh_study`, `sh_xlsx`, `sh_std` / `std_aisi16`, `sh_tab` (the window).
