"""The Study tab with the soft look of the simulation panels: the bar on top, the left panel and the area of the two tables get the style sheet (the tab
itself and the dialogs it opens do not), the sections have their hint lines, the Run bar is built like the Solve bar (wide Run + Stop beside it), the
stop-early table is usable, a refinement study shows its Convergence tab; and a Simulation add-on without the look leaves the tab as it always was."""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
PAR = os.path.join(HERE, "addons_src", "parametric")
sys.path[:0] = [HERE, SIM, PAR, os.path.join(HERE, "shared")]
from PyQt6.QtCore import Qt, QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel, QPushButton, QComboBox, QTableWidget, QTabWidget, QScrollArea
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, ext
import study_core as core, study_ext, study_tab
import sim_tab, sim_ui, sim_style


def flush():
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


T = tempfile.mkdtemp(prefix="opara_ss_")
d = pm.Document()
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 20))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(T, "plate.gpd"); open(part, "w").write(d.to_json()); sid = s["id"]
ext.HOOKS.clear(); study_ext.register(ext)
sw = sim_tab.SimWindow("fea")
assert sw.create_project(os.path.join(T, "plate_soft")) and sw.import_file(part)
sw.tab.picker.refresh(); sw.tab.picker.select(sid); sw.tab.picker.go()
t = sw.tab
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
xs = {l: [t.model.pts[p][0] for p in t.model.lns[l][:2]] for l in t.model.lns}
left = next(l for l, x in xs.items() if max(x) < 1e-9); right = next(l for l, x in xs.items() if min(x) > 99)
t.supports = [{"mode": "fixed", "targets": [("ln", left)]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", right)]}]
t.e_h.setText("6"); sw.meta["sid"] = sid; assert sw.save()
tab = study_ext.open_study(sw, threaded=False)
tab.resize(1400, 1000); tab.show(); flush()

# ------------------------------------------------------------------ the look is on, and only where it belongs
assert tab.soft is True
for area in (tab.header, tab.panel, tab.right):
    assert area.objectName() == "simpanel" and "QPushButton" in area.styleSheet(), area
assert sim_style.TABS in tab.right.styleSheet() and sim_style.TABS not in tab.panel.styleSheet(), "only the right-hand area holds a tab widget"
assert tab.styleSheet() == "", "the tab itself has no style sheet: the dialogs it opens keep the program's look"
dlg = study_tab.RefineDialog(tab, "6", "mm")
assert dlg.styleSheet() == "" and tab.styleSheet() == ""
dlg.close()
from PyQt6.QtWidgets import QWidget
assert sw.tab.styleSheet() == "" and sum(1 for w in sw.tab.findChildren(QWidget) if w.objectName() == "simpanel") == 1, "the simulation tab next to it keeps its own one panel"
assert not any(tab.isAncestorOf(w) for w in sw.tab.findChildren(QWidget) if w.objectName() == "simpanel")

# ------------------------------------------------------------------ the three sections: hint line, then the table
sections = {s_.title: s_ for s_ in tab.sections}
assert list(sections) == ["Inputs to vary", "Outputs to record", "Stop early when"]
for title, first in (("Inputs to vary", "Tick the inputs"), ("Outputs to record", "These results"), ("Stop early when", "Checked after every case")):
    body = sections[title].body
    lab = body.itemAt(0).widget()
    assert isinstance(lab, QLabel) and lab.text().startswith(first) and lab.wordWrap(), (title, lab)
    assert body.itemAt(1).widget() is not None and not isinstance(body.itemAt(1).widget(), QLabel), "the table follows the hint"

# ------------------------------------------------------------------ the column of the FEA windows: an Outline of the steps with the Details of the selected one below it
ol = tab.outline
assert ol is not None and ol.keys() == ["Inputs to vary", "Outputs to record", "Stop early when"], "the sections are the nodes of an Outline"
lay_ = tab.panel.layout()
assert lay_.indexOf(ol) == 0 and lay_.indexOf(tab.runbar) == lay_.count() - 1, "the Outline is on top and the Run bar stays pinned under everything"
assert ol.current == ("Inputs to vary", None) and sections["Inputs to vary"].isVisibleTo(tab) and not sections["Outputs to record"].isVisibleTo(tab), "the Details show the selected step only"
assert ol.head.text() == "Details of “Inputs to vary”"
ol.select("Outputs to record"); flush()
assert sections["Outputs to record"].isVisibleTo(tab) and not sections["Inputs to vary"].isVisibleTo(tab) and ol.head.text() == "Details of “Outputs to record”"
ol.select("Inputs to vary"); flush()
ol.sync()
assert ol.marks.get("Inputs to vary") == "incomplete" and ol.marks.get("Outputs to record") == "ok", f"no input ticked yet: a question mark ({ol.marks})"

# ------------------------------------------------------------------ the Run bar is the Solve bar of this tab
assert tab.b_all.property("simrole") == "solve" and tab.b_stop.property("simrole") == "solveside"
assert tab.b_all.height() >= 44 and tab.b_stop.height() >= 44 and abs(tab.b_all.height() - tab.b_stop.height()) <= 2, (tab.b_all.height(), tab.b_stop.height())
assert tab.b_all.width() > 2 * tab.b_stop.width(), "wide Run, narrow Stop beside it"
assert "0e7f86" in tab.b_all.styleSheet().lower() or "17949b" in tab.b_all.styleSheet().lower(), "the teal Solve look"
assert tab.runbar.parentWidget() is tab.panel and tab.b_sel.height() < 40 and tab.b_cur.height() < 40
assert tab.b_all.isEnabled() and not tab.b_stop.isEnabled()

# ------------------------------------------------------------------ a real run still works with the new look; the conditions table
dim = next(k for k in tab.desc if k.startswith("geo."))
for pid in (dim, "fea.load0.p"):
    tab.items[pid].setCheckState(0, Qt.CheckState.Checked)
assert tab.fill_grid({dim: "100, 150", "fea.load0.p": "0.5, 1.0"}) and len(tab.data.rows) == 4
tab.data.out_checked = ["fea.status", "fea.umax", "fea.vm", "fea.fos_y"]; tab.fill_outputs()
ol.sync()
assert ol.marks["Inputs to vary"] == "ok", "an input is ticked: a check"
ol.select("Stop early when"); flush()
tab.add_exit()
assert len(tab.data.exit_conds) == 1
tab.data.exit_conds[0].update({"key": "fea.fos_y", "op": "<", "value": "1.5"}); tab.fill_exit_table(); flush()
et = tab.exit_table
assert et.columnWidth(0) == 40 and et.columnWidth(2) == 70
cb = et.cellWidget(0, 1)
assert isinstance(cb, QComboBox) and cb.sizeAdjustPolicy() != QComboBox.SizeAdjustPolicy.AdjustToContents and "Factor of safety" in cb.currentText()
assert et.item(0, 3).text() == "1.5" and et.cellWidget(0, 0).isChecked()
cells = [w for w in et.viewport().findChildren(QComboBox) if w.isVisible()]
assert len(cells) == 2, "one Output and one operator combo: no stale cell widgets"
assert tab.run_all() and len(tab.data.cases) == 4 and all(c["status"] == "ok" for c in tab.data.cases), [(c["status"], c.get("error")) for c in tab.data.cases]
tab.grab().save(os.path.join(T, "study.png"))

# ------------------------------------------------------------------ a refinement study: the Convergence tab is there and has the look
tab.new_refinement("Refine", "8", 0.7, 3); assert tab.run_all(); flush()
assert tab.tabs_bottom.count() == 2 and tab.tabs_bottom.tabText(1) == "Convergence"
assert tab.right.isAncestorOf(tab.tabs_bottom) and tab.conv.table.rowCount() >= 3
tab.tabs_bottom.setCurrentIndex(1); flush(); tab.grab()

# ------------------------------------------------------------------ an older Simulation add-on (no soft look to call): the tab is as it always was
saved = sim_ui.soften_area
del sim_ui.soften_area
try:
    old = study_tab.StudyTab(sw, threaded=False)
finally:
    sim_ui.soften_area = saved
assert old.soft is False and old.styleSheet() == "" and old.panel.objectName() != "simpanel" and old.b_all.minimumHeight() == 34
assert old.b_all.property("simrole") is None and old.exit_table.columnWidth(2) == 70
hints = [w for w in old.panel.findChildren(QLabel) if w.text().startswith("Tick the inputs")]
assert len(hints) == 1, "the hint lines are part of the layout either way"
old.shutdown() if hasattr(old, "shutdown") else None
shutil.rmtree(T, ignore_errors=True)
print("OK study soft")
os._exit(0)
