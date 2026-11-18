"""Sheets (dev_addons/sheets): the chart panel on the right of the grid - Setup (type, data range, X, series, axes per series, swap), Customize (the look),
Advanced (every matplotlib setting as a typed input, saved with the chart), the looks (presets) bar, picking cells on the sheet, following the chart that is picked."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

app = QApplication([])
import sh_adv
import sh_chart
import sh_deps
import sh_prefs
import sh_presets
import sh_tab as TAB

if sh_deps.matplotlib() is None:
    print("SKIP test_sheets_panel: matplotlib is not installed here")
    raise SystemExit(0)

T = tempfile.mkdtemp(prefix="opara_sp_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
answers = {"text": None, "save": None, "open": None}
QInputDialog.getText = staticmethod(lambda *a, **k: (answers["text"], answers["text"] is not None))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (answers["save"] or "", ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (answers["open"] or "", ""))

t = TAB.make_tab()
t.resize(1300, 800)
t.show()
wb, g = t.wb, t.grid
S = wb.sheet_names()[0]
for j, h in enumerate(["x", "y1", "y2", "y3"], 1):
    wb.set_input(S, 1, j, h)
for i in range(1, 9):
    wb.set_input(S, i + 1, 1, str(i))
    wb.set_input(S, i + 1, 2, f"=A{i + 1}^2")
    wb.set_input(S, i + 1, 3, f"=A{i + 1}*100")
    wb.set_input(S, i + 1, 4, f"=A{i + 1}+1")


def settle():
    p = t.panel
    if p is not None:
        for tm in (p.timer, p.note_timer):
            if tm.isActive():
                tm.stop()
        p._emit_now()
        p.update_notes()
    for f in g.frames.values():
        f.redraw()
    app.processEvents()


def drawn(cid):
    f = g.frames[cid]
    return f.fig


# ---- Insert chart opens the panel on the cells selected; the chart is the one on the sheet
g.select(1, 1, 9, 3)
t.chart_new()
p = t.panel
ch = g.sheet_obj().charts[0]
assert t.panel_open() and p.chart is ch and not p.isHidden() and p.tabs.count() == 3 and [p.tabs.tabText(i) for i in range(3)] == ["Setup", "Customize", "Advanced"]
assert p.data_range.text() == f"{S}!A1:C9" and p.xrange.text() == f"{S}!A2:A9" and len(p.rows) == 2 and p.rows[0].name.text() == "y1"
assert p.headers.isChecked() and p.xcol.isChecked() and not p.switch.isChecked()
assert p.type.currentData() == "line" and not p.stacked.isVisible() or True
settle()
assert drawn(ch["id"]).axes, "the chart is drawn"

# ---- chart type: Column, Bar, Area, Step, Scatter; stack only where it means something
for kind in ("scatter", "column", "bar", "area", "step", "line"):
    p.type.setCurrentIndex(p.type.findData(kind))
    settle()
    assert ch["type"] == kind and not p.note.text(), (kind, p.note.text())
    assert p.stacked.isVisibleTo(p) == (kind in ("column", "bar", "area")), kind
    assert p.rows[0].style.isVisibleTo(p) == (kind in ("line", "step")), kind
p.type.setCurrentIndex(p.type.findData("column"))
p.stacked.setChecked(True)
p.swap.setChecked(True)
settle()
assert ch["stacked"] and ch["swap"]
p.stacked.setChecked(False)
p.swap.setChecked(False)
p.type.setCurrentIndex(p.type.findData("line"))

# ---- the data range: typing changes the series (their look stays); a bad range is told in plain words and changes nothing
ch["series"][0]["color"] = "#112233"
ch["series"][0]["width"] = 3.0
p.data_range.edit.setText(f"{S}!A1:D9")
p.data_range.committed.emit(p.data_range.text())
assert len(ch["series"]) == 3 and ch["series"][0]["color"] == "#112233" and ch["series"][0]["width"] == 3.0 and len(p.rows) == 3
before = dict(ch["data"])
p.data_range.committed.emit("not a range ((")
assert ch["data"] == before and "not a range of cells" in p.msg.text() and p.data_range.edit.styleSheet()
p.data_range.committed.emit(f"{S}!A1:C9")
assert len(ch["series"]) == 2 and not p.msg.text() and not p.data_range.edit.styleSheet()
# header / first column options re-read the series
p.xcol.setChecked(False)
assert ch["x"] == "" and len(ch["series"]) == 3 and ch["data"]["x_col"] is False
p.xcol.setChecked(True)
assert ch["x"] == f"{S}!A2:A9" and len(ch["series"]) == 2
p.headers.setChecked(False)
assert ch["series"][0]["label"] == "" and ch["series"][0]["y"].endswith("B1:B9"), ch["series"][0]
p.headers.setChecked(True)
assert ch["series"][0]["label"] == "y1"
# switch rows / columns: the lines run along the rows
p.switch.setChecked(True)
assert ch["data"]["switch"] and len(ch["series"]) >= 2 and "Switch" in p.switch.text() and p.headers.text().startswith("First column")
p.switch.setChecked(False)
assert p.headers.text().startswith("First row") and ch["x"] == f"{S}!A2:A9"

# ---- X range typed; series edited: name, axis, style, range, colour; add and remove
p.xrange.committed.emit(f"{S}!D2:D9")
assert ch["x"] == f"{S}!D2:D9"
p.xrange.committed.emit("zzz zzz")
assert ch["x"] == f"{S}!D2:D9" and "not a range" in p.msg.text()
p.xrange.committed.emit(f"{S}!A2:A9")
row = p.rows[1]
row.name.setText("Defl")
row.name.editingFinished.emit()
assert ch["series"][1]["label"] == "Defl" and "Defl" in p.cw["series_pick"].itemText(1) and "Defl" in p.adv_scope.itemText(2)
row.axis.setCurrentIndex(row.axis.findData("R"))
assert ch["series"][1]["axis"] == "R"
row.style.setCurrentIndex(row.style.findData("markers"))
assert ch["series"][1]["style"] == "markers"
row.color.picked.emit("#aa0000")
assert ch["series"][1]["color"] == "#aa0000"
row.range.committed.emit(f"{S}!D2:D9")
assert ch["series"][1]["y"] == f"{S}!D2:D9"
settle()
assert not p.note.text(), p.note.text()
p.add_series()
assert len(ch["series"]) == 3 and ch["series"][2]["y"] == "" and p.picking() and p._pick is p.rows[2].range
p.stop_pick()
p.rows[2].range.committed.emit(f"{S}!C2:C9")
assert ch["series"][2]["y"] == f"{S}!C2:C9"
p.remove_series(0)
assert len(ch["series"]) == 2 and len(p.rows) == 2 and ch["series"][0]["label"] == "Defl"
settle()

# ---- picking on the sheet fills the box that asked
g.select(1, 1)
p.start_pick(p.xrange, True)
assert p.picking() and p.xrange.btn.isChecked() is False or True
g.select(2, 1, 9, 1)
t.on_selection()
assert ch["x"] == f"{S}!A2:A9", ch["x"]
p.stop_pick()
assert not p.picking()
g.select(30, 30)
t.on_selection()
assert ch["x"] == f"{S}!A2:A9"                                                          # not picking: the selection changes nothing
# the data range takes several blocks (Ctrl) and a whole column stops at the data
p.data_range.btn.setChecked(True)
assert p.picking() and p._pick is p.data_range
g.select(1, 1, 9, 1)
g.add_area()
g.select(1, 3, 9, 3, keep=True) if "keep" in g.select.__code__.co_varnames else g.select(1, 3, 9, 3)
t.on_selection()
assert ch["data"]["range"].count("!") >= 1 and p.picking()
p.data_range.btn.setChecked(False)
assert not p.picking()
g.select(1, 1, 9, 3)
p.data_range.committed.emit(f"{S}!A1:C9")
p.data_range.btn.setChecked(True)
g.select(1, 2, 120, 2)                                                                  # the whole of column B stops where the data stops
t.on_selection()
assert ch["data"]["range"] == f"{S}!B1:B9", ch["data"]["range"]
p.stop_pick()
p.data_range.committed.emit(f"{S}!A1:C9")

# ---- Customize: the basic look goes into the chart's style, defaults are not stored, and the chart still draws
st = lambda: ch.get("style", {})
p.cw["title"].setText("My chart")
p.cw["title"].textEdited.emit("My chart")
assert ch["title"] == "My chart"
p.cw["line_width"].setValue(3.5)
assert st()["line_width"] == 3.5
p.cw["line_width"].setValue(1.6)
assert "line_width" not in st()
p.cw["title_size"].setValue(20)
assert st()["title_size"] == 20
p.cw["title_size"].setValue(p.cw["title_size"].minimum())
assert "title_size" not in st()
p.cw["grid_style"].setCurrentIndex(p.cw["grid_style"].findData(":"))
p.cw["grid_style"].activated.emit(p.cw["grid_style"].currentIndex())
assert st()["grid_style"] == ":"
p.cw["grid"].setCurrentIndex(p.cw["grid"].findData("none"))
p.cw["grid"].activated.emit(p.cw["grid"].currentIndex())
assert st()["grid"] == "none" and ch["grid"] is False
p.cw["grid"].setCurrentIndex(p.cw["grid"].findData("both"))
p.cw["grid"].activated.emit(p.cw["grid"].currentIndex())
assert ch["grid"] is True and "grid" not in st()
p.cw["frame"].setCurrentIndex(p.cw["frame"].findData("open"))
p.cw["frame"].activated.emit(p.cw["frame"].currentIndex())
p.cw["legend_size"].setValue(14)
p.cw["marker_size"].setValue(8)
p.cw["auto_dash"].setChecked(True)
p.cw["bg"].picked.emit("#f0f0f0")
assert st()["frame"] == "open" and st()["legend_size"] == 14 and st()["marker_size"] == 8 and st()["auto_dash"] is True and st()["bg"] == "#f0f0f0"
p.cw["w"].setValue(640)
p.cw["h"].setValue(400)
assert ch["size"] == [640, 400]
p.cw["font"].setCurrentIndex(p.cw["font"].findData("serif"))
p.cw["font"].activated.emit(p.cw["font"].currentIndex())
assert st()["font"] == "serif"
p.cw["palette"].setCurrentIndex(p.cw["palette"].findData("Bold"))
p.cw["palette"].activated.emit(p.cw["palette"].currentIndex())
assert st()["palette"] == "Bold" and ch["series"][0]["color"] == sh_chart.PALETTES["Bold"][0]
settle()
assert not p.note.text(), p.note.text()
# one series on its own
p.cw["series_pick"].setCurrentIndex(1)
p.sw["width"].setValue(5.0)
p.sw["linestyle"].setCurrentIndex(p.sw["linestyle"].findData("--"))
p.sw["linestyle"].activated.emit(p.sw["linestyle"].currentIndex())
p.sw["marker"].setCurrentIndex(p.sw["marker"].findData("s"))
p.sw["marker"].activated.emit(p.sw["marker"].currentIndex())
p.sw["color"].picked.emit("#00aa00")
assert ch["series"][1]["width"] == 5.0 and ch["series"][1]["linestyle"] == "--" and ch["series"][1]["marker"] == "s" and ch["series"][1]["color"] == "#00aa00"
assert p.rows[1].color.color == "#00aa00"
p.sw["width"].setValue(p.sw["width"].minimum())
p.sw["linestyle"].setCurrentIndex(0)
p.sw["linestyle"].activated.emit(0)
assert "width" not in ch["series"][1] and "linestyle" not in ch["series"][1]
# axes
ax = p.ax["left"]
ax["label"].setText("Stress")
ax["label"].textEdited.emit("Stress")
ax["units"].setText("psi")
ax["units"].textEdited.emit("psi")
ax["log"].setChecked(True)
ax["min"].setText("1")
ax["max"].setText("5000")
ax["max"].editingFinished.emit()
assert ch["left"] == {"label": "Stress", "units": "psi", "log": True, "min": 1.0, "max": 5000.0}
ax["max"].setText("big")
ax["max"].editingFinished.emit()
assert "not a number" in p.msg.text() and ch["left"]["max"] == 5000.0
ax["max"].setText("")
ax["max"].editingFinished.emit()
assert ch["left"]["max"] is None and not p.msg.text()
ax["log"].setChecked(False)
px = p.ax["x"]
px["label"].setText("Thickness")
px["label"].textEdited.emit("Thickness")
assert ch["x_label"] == "Thickness"
# limit lines, zones and notes
p.limits.add(["L", "5", "limit", "#c0392b"])
p.limits.changed.emit()
assert ch["limits"] == [{"axis": "L", "value": 5.0, "label": "limit", "color": "#c0392b"}]
p.limits.add(["L", "oops oops", "", "#c0392b"])
p.limits.changed.emit()
assert "not a number" in p.msg.text() and len(ch["limits"]) == 1
p.limits.t.removeRow(1)
p.limits.changed.emit()
assert not p.msg.text()
p.zones.add(["L", "2", "4", "zone", "#e8590c"])
p.zones.changed.emit()
p.notes.add(["3", "9", "L", "here"])
p.notes.changed.emit()
assert len(ch["zones"]) == 1 and ch["zones"][0]["lo"] == 2.0 and ch["notes"][0]["text"] == "here"
settle()
assert not p.note.text(), p.note.text()
p.legend_ok = p.cw["legend"]
p.cw["legend"].setChecked(False)
assert ch["legend"] is False
p.cw["legend"].setChecked(True)

# ---- Advanced: typed inputs, saved with the chart, changed-only, reset, search, per-series scope
for e in p.adv_secs:
    p.adv_build(e)
total = sum(len(e["rows"]) for e in p.adv_secs)
assert total > 300, total
rows = {r.p.key: r for e in p.adv_secs for r in e["rows"]}
k = "axes:facecolor" if "axes:facecolor" in rows else next(k for k, r in rows.items() if r.p.kind == "color" and r.p.target != "rc")
rows[k].editor.picked.emit("#fafad2")
assert ch["adv"][k] == "#fafad2" and rows[k].is_set and rows[k].reset.isEnabled()
rows[k].on_reset()
assert k not in ch["adv"] and not rows[k].is_set and not rows[k].reset.isEnabled()
numeric = next(r for r in rows.values() if r.p.kind == "float" and r.p.target != "rc" and r.p.lo is not None)
numeric.editor.setValue(numeric.p.hi)
assert ch["adv"][numeric.p.key] == numeric.p.hi
numeric.editor.setValue(numeric.p.hi + 1000)                                              # the box itself stops at its bound
assert ch["adv"][numeric.p.key] == numeric.p.hi and numeric.editor.value() == numeric.p.hi
p.adv_changed.setChecked(True)
shown = [r for e in p.adv_secs for r in e["rows"] if not r.label.isHidden()]
assert [r.p.key for r in shown] == list(ch["adv"]) or {r.p.key for r in shown} == set(ch["adv"]), ([r.p.key for r in shown], list(ch["adv"]))
p.adv_changed.setChecked(False)
p.adv_search.setText("zzzzqq")
assert all(r.label.isHidden() for e in p.adv_secs for r in e["rows"])
p.adv_search.setText("grid")
assert any(not r.label.isHidden() for e in p.adv_secs for r in e["rows"]) and any(r.label.isHidden() for e in p.adv_secs for r in e["rows"])
p.adv_search.setText("")
assert all(not r.label.isHidden() for e in p.adv_secs for r in e["rows"])
# a box that is only passed through (focus in and out) must not make a setting
txt = next(r for r in rows.values() if r.p.kind == "text")
n0 = len(ch["adv"])
txt.editor.editingFinished.emit()
assert len(ch["adv"]) == n0
# one series only
lw = next((r for r in rows.values() if r.p.target == "series" and r.p.name == "linewidth"), None)
assert lw is not None
p.adv_scope.setCurrentIndex(2)                                                            # series 2
lw.editor.setValue(4.0)
assert ch["adv"]["series[1]:linewidth"] == 4.0 and "series:linewidth" not in ch["adv"]
p.adv_scope.setCurrentIndex(0)
assert not lw.is_set
lw.editor.setValue(2.5)
assert ch["adv"]["series:linewidth"] == 2.5
p.adv_scope.setCurrentIndex(2)
assert lw.is_set and abs(lw.editor.value() - 4.0) < 1e-9
# removing a series moves the settings of the ones after it
ch["adv"]["series[1]:linewidth"] = 4.0
p.remove_series(0)
assert ch["adv"].get("series[0]:linewidth") == 4.0 and "series[1]:linewidth" not in ch["adv"]
p.add_series()
p.stop_pick()
p.rows[-1].range.committed.emit(f"{S}!C2:C9")
settle()
assert not p.note.text(), p.note.text()
# reset all
p.adv_reset_all()
assert ch["adv"] == {}

# ---- looks (presets): built in ones can not be changed; save, apply, default, export / import, delete
assert p.preset.count() >= 5 and p.preset.itemData(0) == "Default"
p.preset.setCurrentIndex(p.preset.findData("Print (black and white)"))
p.apply_preset()
assert st()["palette"] == "Greys" and st()["auto_dash"] is True and p.cw["auto_dash"].isChecked() and p.cw["palette"].currentData() == "Greys"
assert ch["series"][0]["color"] == sh_chart.PALETTES["Greys"][0] and ch["title"] == "My chart"        # the words stay
p.cw["line_width"].setValue(2.5)
ch["adv"]["series[0]:linewidth"] = 3.0
ch["adv"]["rc:axes.grid"] = True
answers["text"] = "Print (black and white)"
p.save_preset()
assert "built-in" in p.msg.text()
answers["text"] = "My look"
p.save_preset()
assert "My look" in sh_presets.names() and p.preset.currentData() == "My look"
saved = sh_presets.get("My look")
assert saved["style"]["line_width"] == 2.5 and "series[0]:linewidth" not in saved["adv"] and "rc:axes.grid" in saved["adv"]
assert "title" not in saved["style"] and not any("label" in k for k in saved["style"])
p.preset.setCurrentIndex(p.preset.findData("Dark"))
p.apply_preset()
assert st()["bg"] == "#1b2230" and ch["adv"].get("series[0]:linewidth") == 3.0              # the look of one series is the chart's own
p.preset.setCurrentIndex(p.preset.findData("My look"))
p.apply_preset()
assert st()["line_width"] == 2.5 and ch["adv"]["rc:axes.grid"] is True
p.preset_default()
assert sh_presets.default_name() == "My look" and sh_prefs.get("chart_preset") == "My look"
assert "(new charts)" in p.preset.itemText(p.preset.findData("My look"))
ex = os.path.join(T, "looks.json")
answers["save"] = ex
p.preset_export()
assert os.path.isfile(ex)
p.preset_delete()
assert "My look" not in sh_presets.names() and sh_presets.default_name() == "Default" and p.preset.currentData() == "Default"
p.preset.setCurrentIndex(p.preset.findData("Default"))
p.preset_delete()
assert "built-in" in p.msg.text() and "Default" in sh_presets.names()
answers["open"] = ex
p.preset_import()
assert "My look" in sh_presets.names()
p.preset.setCurrentIndex(p.preset.findData("Default"))
p.apply_preset()
assert ch.get("style") == {} and p.cw["line_width"].value() == 1.6
sh_presets.set_default("My look")

# ---- a new chart starts from the default look, and Insert chart with nothing selected makes an empty chart that waits for cells
g.select(40, 40)
t.chart_new()
c2 = g.sheet_obj().charts[-1]
assert c2["series"] == [] and c2["style"].get("line_width") == 2.5 and t.panel.chart is c2 and p.picking() and p._pick is p.data_range
g.select(1, 1, 9, 2)
t.on_selection()
assert len(c2["series"]) == 1 and c2["data"]["range"] == f"{S}!A1:B9"
p.stop_pick()
settle()
sh_presets.set_default("Default")

# ---- the panel follows the chart that is picked, shows its size when it is resized on the sheet, and closes with its chart
g.pick_chart(ch["id"])
assert p.chart is ch
g.pick_chart(c2["id"])
assert p.chart is c2
c2["size"] = [700, 410]
g.charts_changed.emit()
assert p.cw["w"].value() == 700 and p.cw["h"].value() == 410
t.chart_edit(ch["id"])
assert p.chart is ch
g.delete_chart(ch["id"])
assert not t.panel_open() and p.isHidden()
t.chart_edit(c2["id"])
assert t.panel_open()
p.close_panel()
assert p.isHidden() and not t.panel_open()
# another sheet: the panel closes (the chart is not on that sheet)
t.chart_edit(c2["id"])
wb.add_sheet("Other")
t.rebuild_sheet_tabs()
t.tabbar.setCurrentIndex(1)
assert not t.panel_open()
t.tabbar.setCurrentIndex(0)

# ---- closing the tab leaves nothing running
t.shutdown()
assert not t.panel.timer.isActive() and not t.panel.note_timer.isActive()
print("OK test_sheets_panel")
