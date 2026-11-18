# Sheets (dev add-on)

A spreadsheet tab. Playground only; nothing in the core program changes.

- **Formulas**: Excel's syntax, 118 functions, `$` references, other sheets, sheet-scoped names. Cell references stay `F62`-style.
- **Files**: `.opsheet` (JSON). Excel `.xlsx` opens and exports (openpyxl is downloaded once, on first use).
- **Studies**: Data > Import study; Refresh from study reads it again and fills formulas next to it down.
- **Charts**: select cells, Insert chart; several Y series, left/right axes, limit lines, zones, notes, PNG/SVG/PDF.
- **Standards**: Engineering tab. `std_aisi16.py` encodes AISI S100-16 connection equations (J2, J3, J4) as `AISI16.J4_4_1(...)` etc.
  Equations and section numbers only; the standard's text is not copied.
- **Other add-ons** can offer a standard through the `sheets_standard` hook (return a `sh_std.Pack`).

Modules: `sh_engine` / `sh_funcs` (formulas), `sh_book` (workbook, undo), `sh_grid` / `sh_edit` (grid and editing), `sh_dialogs`, `sh_chart`,
`sh_study`, `sh_xlsx`, `sh_std` / `std_aisi16`, `sh_tab` (the window).
