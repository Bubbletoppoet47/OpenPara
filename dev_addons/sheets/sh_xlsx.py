"""
sh_xlsx.py - Excel files in and out of Sheets (needs openpyxl: sh_deps.py gets it).

    import_xlsx(path)  -> (Workbook, notes)      values, formulas (also array formulas), number formats, bold / italic / colours, column widths, names, pictures
    export_xlsx(wb, path) -> notes               the same back, with the charts as Excel charts and the pictures as Excel pictures at the cell they are over (a video: its first frame, with a note in that cell)

Notes are short lines about what did not come across (charts, merged cells, functions Sheets does not have; AISI and other standards functions leave
Excel as their values, with the formula text in a cell comment, because Excel cannot work them out).
"""
import datetime
import re

import sh_book as B
import sh_deps
import sh_engine as E


class XlsxError(Exception):
    pass


DEF_W, DEF_H = 72, 22                                          # the size of a cell that a sheet gives no size to (the grid's own)
EMU = 9525                                                      # English Metric Units in a pixel (what Excel measures a picture in)
_XLFN = {"IFNA", "IFS", "CONCAT", "TEXTJOIN", "MAXIFS", "MINIFS", "STDEV.S", "STDEV.P", "VAR.S", "VAR.P", "XOR"}


def _need():
    mod = sh_deps.openpyxl()
    if mod is None:
        raise XlsxError("openpyxl is needed to read and write Excel files.")
    return mod


def _hex(color):
    """'#RRGGBB' for an openpyxl colour that is a plain RGB value, else None."""
    try:
        if color is not None and color.type == "rgb" and isinstance(color.rgb, str) and len(color.rgb) in (6, 8):
            c = color.rgb[-6:]
            return None if c.upper() == "000000" else "#" + c.upper()
    except AttributeError:
        pass
    return None


def _clean_formula(text):
    return re.sub(r"_xl(?:fn|ws)\.", "", text)


def _style_from(cell, openpyxl):
    fmt = cell.number_format or "General"
    bold = bool(cell.font and cell.font.b)
    italic = bool(cell.font and cell.font.i)
    fg = _hex(cell.font.color) if cell.font else None
    bg = _hex(cell.fill.fgColor) if cell.fill and cell.fill.fill_type == "solid" else None
    if bg == "#FFFFFF":
        bg = None
    al = cell.alignment.horizontal if cell.alignment else None
    al = al if al in ("left", "center", "right") else None
    return B.intern_style(B.Style(fmt, bold, italic, fg, bg, al))


def import_xlsx(path):
    op = _need()
    notes = []
    try:
        wbx = op.load_workbook(path)
    except Exception as ex:                                  # noqa: BLE001 - a damaged or password-protected file
        raise XlsxError(f"The file could not be read: {ex}")
    wb = B.Workbook(with_sheet=False)
    pics = charts = merged = 0                                # (pics: pictures that could not be brought across)
    unknown = {}
    for ws in wbx.worksheets:
        s = B.Sheet(ws.title)
        charts += len(getattr(ws, "_charts", []))
        merged += len(ws.merged_cells.ranges)
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                st = _style_from(c, op) if c.has_style else None
                if v is None and st is None:
                    continue
                arr = False
                if hasattr(v, "text") and hasattr(v, "ref"):          # an array formula
                    v, arr = v.text, True
                elif v is not None and type(v).__name__ == "DataTableFormula":
                    v = None
                if isinstance(v, str) and c.data_type == "e":
                    v = "=" + v
                if isinstance(v, str) and v.startswith("=") and len(v) > 1:
                    v = _clean_formula(v)
                    for fn in _calls(v):
                        if fn not in E.FUNCS:
                            unknown[fn] = unknown.get(fn, 0) + 1
                elif isinstance(v, bool):
                    pass
                elif isinstance(v, (int, float)):
                    v = float(v)
                elif isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
                    from openpyxl.utils.datetime import to_excel
                    v = float(to_excel(v))
                elif v is not None:
                    v = str(v)
                cell = B.Cell(v, st)
                cell.arr = arr
                s.cells[(c.row, c.column)] = cell
        for letter, dim in ws.column_dimensions.items():
            try:
                if dim.width and not dim.hidden:
                    lo, hi = dim.min or E.col_index(letter), dim.max or E.col_index(letter)
                    for ci in range(lo, min(hi, lo + 200) + 1):
                        s.col_w[ci] = int(round(dim.width * 7 + 5))
            except (TypeError, ValueError):
                pass
        for ri, dim in ws.row_dimensions.items():
            if dim.height:
                s.row_h[ri] = int(round(dim.height * 4 / 3))
        for img in list(getattr(ws, "_images", [])):
            if not _import_picture(wb, s, img):
                pics += 1
        fp = ws.freeze_panes
        if fp:
            a = E.parse_addr(str(fp))
            if a:
                s.freeze = (a[0] - 1, a[1] - 1)
        try:
            for nm, dn in ws.defined_names.items():
                s.names[nm] = "=" + str(dn.attr_text)
        except Exception:                                   # noqa: BLE001
            pass
        wb.sheets.append(s)
    try:
        for nm, dn in wbx.defined_names.items():
            txt = str(dn.attr_text)
            if "!" in txt or E.parse_addr(txt.replace("$", "")):
                wb.names[nm] = "=" + txt
    except Exception:                                       # noqa: BLE001
        pass
    if not wb.sheets:
        wb.sheets.append(B.Sheet("Sheet1"))
    wb._rebuild_all()
    wb.recalc()
    wb._changed.clear()
    if pics:
        notes.append(f"{pics} picture(s) could not be brought across.")
    if charts:
        notes.append(f"{charts} Excel chart(s) were not brought across: make them again with Insert chart.")
    if merged:
        notes.append(f"{merged} merged range(s) became separate cells.")
    if unknown:
        notes.append("Functions Sheets does not have (those cells show #NAME?): " + ", ".join(f"{k} x{v}" for k, v in sorted(unknown.items())))
    return wb, notes


def _calls(text):
    try:
        return E.parse(text).calls
    except E.FormulaError:
        return ()


def _custom(raw):
    """True when a formula calls a function that Excel does not have (a standard's function)."""
    for fn in _calls(raw):
        f = E.FUNCS.get(fn)
        if f is not None and f.pack:
            return True
    return False


def _excel_names(text):
    """The formula text with the newer function names written the way Excel files spell them (_xlfn.IFNA ...)."""
    body = text[1:]
    try:
        toks = E.tokenize(body)
    except E.FormulaError:
        return text
    out, pos = [], 0
    for kind, tx, s, e, val in toks:
        if kind == "func" and val in _XLFN:
            out.append(body[pos:s])
            out.append("_xlfn." + tx)
            pos = e
    out.append(body[pos:])
    return "=" + "".join(out)


def export_xlsx(wb, path):
    op = _need()
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.formula import ArrayFormula
    notes = []
    wx = op.Workbook()
    wx.remove(wx.active)
    custom = 0
    for s in wb.sheets:
        ws = wx.create_sheet(s.name[:31])
        for (r, c), cell in s.cells.items():
            if cell.raw is None and cell.st is None:
                continue
            x = ws.cell(row=r, column=c)
            raw = cell.raw
            if cell.is_formula:
                if _custom(raw):
                    v = wb.value(s.name, r, c)
                    x.value = None if isinstance(v, E.Err) else v
                    x.comment = Comment(f"Sheets formula: {raw}\n(Excel cannot work this one out; the value is as of the export.)", "Sheets")
                    custom += 1
                elif cell.arr:
                    x.value = ArrayFormula(E.addr(r, c), _excel_names(raw))
                else:
                    x.value = _excel_names(raw)
            elif isinstance(raw, str) and raw.startswith("'"):
                x.value = raw[1:]
                x.data_type = "s"
            else:
                x.value = raw
            st = cell.st
            if st is not None:
                if st.fmt and st.fmt != "General":
                    x.number_format = st.fmt
                if st.bold or st.italic or st.fg:
                    x.font = Font(bold=st.bold, italic=st.italic, color=(st.fg or "#000000").lstrip("#"))
                if st.bg:
                    x.fill = PatternFill("solid", fgColor=st.bg.lstrip("#"))
                if st.align:
                    x.alignment = Alignment(horizontal=st.align)
        for ci, w in s.col_w.items():
            ws.column_dimensions[E.col_letter(ci)].width = max(1.0, (w - 5) / 7.0)
        for ri, h in s.row_h.items():
            ws.row_dimensions[ri].height = h * 0.75
        if s.freeze and (s.freeze[0] or s.freeze[1]):
            ws.freeze_panes = E.addr(s.freeze[0] + 1, s.freeze[1] + 1)
        for pic in s.pictures:
            try:
                _export_picture(wb, s, ws, pic)
            except Exception as ex:                          # noqa: BLE001 - one picture Excel cannot hold must not lose the file
                notes.append(f"Picture '{pic.get('name') or pic.get('id')}' was not exported: {ex}")
        for ch in s.charts:
            try:
                _export_chart(wb, wx, ws, ch)
            except Exception as ex:                          # noqa: BLE001 - one chart that Excel cannot hold must not lose the file
                notes.append(f"Chart '{ch.get('title') or ch.get('id')}' was not exported: {ex}")
    from openpyxl.workbook.defined_name import DefinedName
    for nm, txt in wb.names.items():
        try:
            wx.defined_names[nm] = DefinedName(nm, attr_text=txt.lstrip("="))
        except Exception:                                   # noqa: BLE001
            pass
    for s in wb.sheets:
        for nm, txt in s.names.items():
            try:
                wx[s.name[:31]].defined_names[nm] = DefinedName(nm, attr_text=txt.lstrip("="))
            except Exception:                               # noqa: BLE001
                pass
    wx.calculation.fullCalcOnLoad = True
    wx.save(path)
    if custom:
        notes.append(f"{custom} cell(s) use a standard's function: Excel gets their values, and the formula text is in a cell comment.")
    return notes


def _cell_at(s, x, y):
    """(column, row, x offset, y offset) of the cell that holds the pixel (x, y) of the sheet."""
    c, left = 1, 0.0
    while c < E.MAXCOL and left + s.col_w.get(c, DEF_W) <= x:
        left += s.col_w.get(c, DEF_W)
        c += 1
    r, top = 1, 0.0
    while r < E.MAXROW and top + s.row_h.get(r, DEF_H) <= y:
        top += s.row_h.get(r, DEF_H)
        r += 1
    return c, r, x - left, y - top


def _pixel_of(s, col, row, dx=0.0, dy=0.0):
    """The pixel (x, y) of the sheet that is `dx`, `dy` into the cell (column, row)."""
    return (sum(s.col_w.get(c, DEF_W) for c in range(1, col)) + dx, sum(s.row_h.get(r, DEF_H) for r in range(1, row)) + dy)


def _export_picture(wb, s, ws, pic):
    from io import BytesIO

    from openpyxl.drawing.image import Image as XImage
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    data = wb.images.get(pic["image"])
    if not data:
        raise ValueError("its data is missing")
    img = XImage(BytesIO(data))                              # (needs Pillow: openpyxl says so when it is not there)
    c, r, dx, dy = _cell_at(s, pic["pos"][0], pic["pos"][1])
    w, h = pic["size"]
    img.width, img.height = w, h
    img.anchor = OneCellAnchor(_from=AnchorMarker(col=c - 1, row=r - 1, colOff=int(dx * EMU), rowOff=int(dy * EMU)), ext=XDRPositiveSize2D(int(w * EMU), int(h * EMU)))
    ws.add_image(img)
    if pic.get("video"):                                     # Excel has no place for a video that is stored in the file: the first frame is the picture, and a note says so
        from openpyxl.comments import Comment
        cell = ws.cell(row=r, column=c)
        note = (f"Video '{pic.get('name') or 'video'}': the picture here is its first frame.  The video itself stays in the Sheets file (.opsheet); "
                "Excel cannot play it from here.")
        cell.comment = Comment((cell.comment.text + "\n\n" if cell.comment else "") + note, "Sheets")


def _import_picture(wb, s, img):
    """A picture of an Excel sheet -> s.pictures (True), or False when it cannot be read."""
    try:
        raw = img._data()
        a = img.anchor
        mk = getattr(a, "_from", None)
        if mk is not None:
            x, y = _pixel_of(s, mk.col + 1, mk.row + 1, mk.colOff / EMU, mk.rowOff / EMU)
        else:
            x, y = a.pos.x / EMU, a.pos.y / EMU
        ow, oh = float(img.width), float(img.height)         # (the pixels it has)
        ext, end = getattr(a, "ext", None), getattr(a, "to", None)
        if ext is not None and ext.width and ext.height:
            w, h = ext.width / EMU, ext.height / EMU
        elif end is not None:
            x2, y2 = _pixel_of(s, end.col + 1, end.row + 1, end.colOff / EMU, end.rowOff / EMU)
            w, h = x2 - x, y2 - y
        else:
            w, h = ow, oh
        if not raw or w < 1 or h < 1:
            return False
        key = wb.add_image(bytes(raw))
        ids = {p["id"] for p in s.pictures}
        n = 1
        while f"pic{n}" in ids:
            n += 1
        s.pictures.append({"id": f"pic{n}", "image": key, "pos": [max(0.0, x), max(0.0, y)], "size": [float(round(w)), float(round(h))],
                           "orig": [float(round(ow)), float(round(oh))], "keep": True, "name": "Picture"})
        return True
    except Exception:                                        # noqa: BLE001 - a picture that cannot be read must not stop the workbook opening
        return False


def _export_chart(wb, wx, ws, ch):
    from openpyxl.chart import Reference, ScatterChart, Series

    def ref(text):
        p = wb.parse_range(text)
        if p is None:
            raise ValueError("a range could not be read")
        sh, r1, c1, r2, c2 = p
        return Reference(wx[sh[:31]], min_col=c1, max_col=c2, min_row=r1, max_row=r2)
    x = ref(ch["x"])
    left = ScatterChart()
    left.title = ch.get("title") or None
    left.style = 2
    left.x_axis.title = _axis_title(ch.get("x_label"), ch.get("x_units"))
    left.y_axis.title = _axis_title(ch.get("left", {}).get("label"), ch.get("left", {}).get("units"))
    left.x_axis.delete = False
    left.y_axis.delete = False
    right = None
    for sdef in ch.get("series", []):
        y = ref(sdef["y"])
        s = Series(y, x, title=sdef.get("label") or None)
        s.marker.symbol = "circle" if sdef.get("style", "line") in ("markers", "both") else "none"
        if sdef.get("style", "line") == "markers":
            s.graphicalProperties.line.noFill = True
        if sdef.get("axis", "L") == "R":
            if right is None:
                right = ScatterChart()
                right.y_axis.axId = 200
                right.y_axis.title = _axis_title(ch.get("right", {}).get("label"), ch.get("right", {}).get("units"))
                right.y_axis.crosses = "max"
                right.y_axis.delete = False
            right.series.append(s)
        else:
            left.series.append(s)
    if ch.get("x_log"):
        left.x_axis.scaling.logBase = 10
    if ch.get("left", {}).get("log"):
        left.y_axis.scaling.logBase = 10
    if right is not None:
        if not left.series:
            left, right = right, None
        else:
            left += right
    left.height, left.width = 9.5, 16
    ws.add_chart(left, "A" + str(max(ws.max_row, 1) + 3))


def _axis_title(label, units):
    if not label:
        return None
    return f"{label} [{units}]" if units else label
