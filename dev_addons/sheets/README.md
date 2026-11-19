# Sheets (dev add-on)

A spreadsheet tab. Playground only; nothing in the core program changes.

- **Formulas**: Excel's syntax, 118 functions, `$` references, other sheets, sheet-scoped names. Cell references stay `F62`-style.
- **Files**: `.opsheet` (JSON). Excel `.xlsx` opens and exports (openpyxl is downloaded once, on first use).
- **Studies**: Data > Import study; Refresh from study reads it again and fills formulas next to it down.
- **Charts**: Insert chart (from the selected cells, or empty and pick the cells after); double-click a chart to open the panel on the right.
  Setup (type, data range, X, series, left/right axis, swap X and Y), Customize (fonts, lines, grid, frame, legend, limit lines, zones, notes) and
  Advanced (every matplotlib setting as a typed input, saved with the chart). Looks (presets) are saved in `chart_presets.json`. PNG/SVG/PDF.
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
`sh_study`, `sh_xlsx`, `sh_std` / `std_aisi16`, `sh_tab` (the window).
