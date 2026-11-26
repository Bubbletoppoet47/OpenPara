"""The left panels of 1D FEA, 2D FEA and 2D CFD (Simulation add-on): an Outline (the tree of the sections) with the Details of the selected one below it, stacked icon
buttons for supports / loads, Solve at the top of the Results page, and NO hotkeys at all (the keys F X Y B S C P T M D W N R J do nothing).  A free Section still folds and remembers it."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QPushButton
app = QApplication([])
import sim_icons, sim_ui, sim_outline
import physics_tab, beam_tab, cfd_tab
import sketcher_core as sc


class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


# --- icons: every one draws something, and the two sets agree
assert set(sim_icons.NAMES)
for n in sim_icons.NAMES:
    img = sim_icons.pixmap(n, 48).toImage()
    assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 48, 2) for y in range(0, 48, 2)), n
    assert not sim_icons.icon(n).isNull()

# --- sections
tabs = {"2D FEA": physics_tab.PhysicsTab(Win()), "1D FEA": beam_tab.BeamTab(Win()), "2D CFD": cfd_tab.CFDTab(Win())}
want = {"2D FEA": ["Geometry", "Material and analysis", "Supports", "Loads", "Mesh", "Results"],
        "1D FEA": ["Geometry", "Material and analysis", "Joints", "Ties", "Supports", "Loads", "Mesh", "Results"],
        "2D CFD": ["Geometry", "Fluid and flow", "Domain", "Mesh", "Solver", "Results"]}
for name, t in tabs.items():
    t.resize(1200, 800); t.show(); app.processEvents()
    got = [s.title for s in sorted(t.sections, key=lambda s: s.number)]
    assert got == want[name], (name, got)
    assert [s.number for s in sorted(t.sections, key=lambda s: s.number)] == list(range(1, len(got) + 1))
    assert not hasattr(t, "handle_key"), name
    # the outline: one node per section, the Details show the selected one only
    ol = t.outline
    assert ol.keys() == [x.title for x in sorted(t.sections, key=sim_outline.rank)], (name, ol.keys())
    for k in ol.keys():
        assert ol.select(k)
        app.processEvents()
        shown = [x.title for x in t.sections if x.isVisibleTo(t)]
        assert shown == [k], (name, k, shown)
        assert ol.head.text() == f"Details of “{k}”"
    s = t.sections[0]
    assert not s.toggle.isVisibleTo(t) and not s.sum_lbl.isVisibleTo(t), "no fold bar, no summary line in the Details"
assert not hasattr(tabs["2D FEA"], "add_traction"), "Traction is gone"

# --- a free Section still folds, and its state is remembered between runs
free = sim_ui.Section("paneltest", 2, "Free section", open_=False)
free.show(); app.processEvents()
assert not free.is_open() and not free.frame.isVisible()
free.toggle.setChecked(True); app.processEvents()
assert free.frame.isVisible()
st = json.load(open(os.path.join(UD, sim_ui.STATE_FILE)))
assert st["paneltest/Free section"] is True
sim_ui._state = None
assert sim_ui.Section("paneltest", 2, "Free section", open_=False).is_open()
# a section that is a page of the Details does not fold and does not write the file
emb = tabs["2D FEA"].sections[1]
assert emb.embedded and not emb.toggle.isVisibleTo(tabs["2D FEA"])
emb.toggle.setChecked(False)
assert "fea2d/" + emb.title not in json.load(open(os.path.join(UD, sim_ui.STATE_FILE)))

# --- buttons: stacked supports / loads with icons, the Solve button on the Results page
def texts(t, title):
    s = [x for x in t.sections if x.title == title][0]
    return [b.text().strip() for b in s.frame.findChildren(QPushButton)]
fea = tabs["2D FEA"]
assert texts(fea, "Supports") == ["Fixed", "Displacement...", "Bolt...", "Screw...", "Contact", "Edit selected...", "Remove selected"], texts(fea, "Supports")   # (and its own table's buttons)
assert texts(fea, "Loads")[:3] == ["Force...", "Pressure...", "Pressure from CFD..."] and "Traction..." not in texts(fea, "Loads")
beam = tabs["1D FEA"]
assert texts(beam, "Supports") == ["Fixed", "Pinned", "Displacement..."]
assert texts(beam, "Loads")[:5] == ["Force...", "Moment...", "Line load...", "Wind...", "Snow..."]
assert texts(beam, "Joints") == ["Rigid joint", "Pinned joint"]
def results_sec(t):
    return [x for x in t.sections if x.title == "Results"][0]
for name, t in tabs.items():
    assert not [b for b in t.findChildren(QPushButton) if b.parent() is not None and b.parent().objectName() == "pinned"], "no pinned bar any more"
    # Solve is on the Results page, plain like Mesh (a grey button, not the teal call to action), and nothing of it is left under the Outline
    rs = results_sec(t)
    assert t.b_solve.text() == "Solve" and rs.isAncestorOf(t.b_solve), name
    assert t.b_solve.styleSheet() == "" and t.b_solve.property("simrole") != "solve", (name, "plain, like the Mesh button")
    if hasattr(t, "b_mesh"):
        assert t.b_solve.minimumHeight() == t.b_mesh.minimumHeight(), (name, t.b_solve.minimumHeight(), t.b_mesh.minimumHeight())
    lay = rs.body
    holder = t.solve_row if hasattr(t, "solve_row") else t.b_solve                      # the Solve button, or the row holding it (CFD: Solve + Stop)
    assert lay.indexOf(holder) == 0, (name, "Solve is the first thing of the Results page")
    under = {"1D FEA": ["cb_auto"], "2D CFD": ["solve_status"]}.get(name, [])
    under = [getattr(t, a) for a in under]        # what belongs right under the Solve button of a page
    for k, w in enumerate(under):
        assert lay.itemAt(1 + k).widget() is w, (name, "the Solve button's own status / choice is right under it")
    assert lay.itemAt(1 + len(under)).widget() is t.study_box, "the parametric-study slot is under Solve (and what belongs to it)"
    t.outline.select("Results"); app.processEvents()
    assert t.b_solve.isVisible(), "Solve shows when the Results page is selected"
    t.outline.select("Geometry"); app.processEvents()
    assert not t.b_solve.isVisible(), "and only then: it is a button of the Results page"
    pan = t.outline.parent()
    while pan is not None and not hasattr(pan, "default_w"):
        pan = pan.parent()
    assert pan is not None and pan.maximumWidth() >= 16000, "the side panel has no maximum width: drag the divider to widen it"
    assert pan.outline is t.outline and t.outline.split.count() == 2
    assert pan.layout().count() == 1, (name, "the Outline is all there is in the column: no strip under the Details")
mesh_sec = [x for x in fea.sections if x.title == "Mesh"][0]
assert "Mesh" in texts(fea, "Mesh") and fea.e_h.parent() is not None
assert mesh_sec.isAncestorOf(fea.e_h) and mesh_sec.isAncestorOf(fea.order_combo) and mesh_sec.isAncestorOf(fea.cb_auto)
mat_sec = [x for x in fea.sections if x.title == "Material and analysis"][0]
assert not mat_sec.isAncestorOf(fea.e_h) and not mat_sec.isAncestorOf(fea.order_combo) and mat_sec.isAncestorOf(fea.cb_nl)
assert [x for x in tabs["2D CFD"].sections if x.title == "Mesh"][0].isAncestorOf(tabs["2D CFD"].b_mesh)
for b in [x for x in fea.findChildren(QPushButton) if x.text().strip() in ("Fixed", "Bolt...", "Contact")]:
    assert not b.icon().isNull()
assert "(" not in "".join(texts(fea, "Supports") + texts(fea, "Loads") + texts(beam, "Supports") + texts(beam, "Loads")), "no hotkey hints on buttons"

# --- no hotkeys: a rectangle is imported, selected, and the keys change nothing
m = sc.Model()
p = [m.add_point(*c) for c in ((0, 0), (100, 0), (100, 20), (0, 20))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
fea.set_model(m, "rect")
fea.canvas.sel = [("pt", p[0])]
fea.canvas.setFocus()
for key in (Qt.Key.Key_F, Qt.Key.Key_X, Qt.Key.Key_Y, Qt.Key.Key_B, Qt.Key.Key_S, Qt.Key.Key_C, Qt.Key.Key_P, Qt.Key.Key_T):
    for mod in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
        fea.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mod, ""))
assert fea.supports == [] and fea.loads == [], (fea.supports, fea.loads)
fea.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, ""))   # Esc still clears the selection
assert fea.canvas.sel == []
# the buttons do the work
fea.canvas.sel = [("pt", p[0])]
fea.add_support("fixed")
assert len(fea.supports) == 1 and "1 support" == fea.count_text(fea.supports, "support")

# --- beam: same, with a frame
bm = sc.Model()
q = [bm.add_point(*c) for c in ((0, 0), (100, 0), (100, 50))]
bm.add_line(q[0], q[1]); bm.add_line(q[1], q[2])
beam.set_model(bm, "frame") if hasattr(beam, "set_model") else None
for key in (Qt.Key.Key_F, Qt.Key.Key_P, Qt.Key.Key_X, Qt.Key.Key_Y, Qt.Key.Key_M, Qt.Key.Key_D, Qt.Key.Key_W, Qt.Key.Key_N, Qt.Key.Key_T, Qt.Key.Key_R, Qt.Key.Key_J):
    beam.canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, ""))
assert beam.supports == [] and beam.loads == []
print("OK sim panels")
os._exit(0)
