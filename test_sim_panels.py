"""The left panels of 1D FEA, 2D FEA and 2D CFD (Simulation add-on): numbered collapsible sections whose fold state is remembered, stacked icon
buttons for supports / loads, Mesh / Solve pinned below the scrolling part, and NO hotkeys at all (the keys F X Y B S C P T M D W N R J do nothing)."""
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
import sim_icons, sim_ui
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
want = {"2D FEA": ["Geometry", "Material and analysis", "Supports", "Loads", "Mesh", "Probe regions", "Results"],
        "1D FEA": ["Geometry", "Material", "Joints", "Supports", "Loads", "Ties", "Results"],
        "2D CFD": ["Geometry", "Fluid and flow", "Domain", "Mesh", "Solver", "Results"]}
for name, t in tabs.items():
    t.resize(1200, 800); t.show(); app.processEvents()
    got = [s.title for s in sorted(t.sections, key=lambda s: s.number)]
    assert got == want[name], (name, got)
    assert [s.number for s in sorted(t.sections, key=lambda s: s.number)] == list(range(1, len(got) + 1))
    assert not hasattr(t, "handle_key"), name
    # fold / unfold + summary line while folded
    s = t.sections[0]
    s.toggle.setChecked(False); app.processEvents()
    assert not s.frame.isVisible()
    s.toggle.setChecked(True); app.processEvents()
    assert s.frame.isVisible()
assert not hasattr(tabs["2D FEA"], "add_traction"), "Traction is gone"

# --- fold state is remembered between runs
sec = tabs["2D FEA"].sections[1]            # Material and analysis: folded by default
assert not sec.is_open()
sec.toggle.setChecked(True)
st = json.load(open(os.path.join(UD, sim_ui.STATE_FILE)))
assert st["fea2d/Material and analysis"] is True
sim_ui._state = None
again = physics_tab.PhysicsTab(Win())
assert [s for s in again.sections if s.title == "Material and analysis"][0].is_open()

# --- buttons: stacked supports / loads with icons, the big Solve row
def texts(t, title):
    s = [x for x in t.sections if x.title == title][0]
    return [b.text().strip() for b in s.frame.findChildren(QPushButton)]
fea = tabs["2D FEA"]
assert texts(fea, "Supports") == ["Fixed", "ux = 0", "uy = 0", "Bolt...", "Screw...", "Contact"], texts(fea, "Supports")
assert texts(fea, "Loads")[:3] == ["Force...", "Pressure...", "Pressure from CFD..."] and "Traction..." not in texts(fea, "Loads")
beam = tabs["1D FEA"]
assert texts(beam, "Supports") == ["Fixed", "Pinned", "ux = 0", "uy = 0"]
assert texts(beam, "Loads")[:5] == ["Force...", "Moment...", "Line load...", "Wind...", "Snow..."]
assert texts(beam, "Joints") == ["Rigid joint", "Pinned joint"]
for t in tabs.values():
    assert not [b for b in t.findChildren(QPushButton) if b.parent() is not None and b.parent().objectName() == "pinned"], "no pinned bar any more"
    assert t.b_solve.text() == "Solve" and t.b_solve.minimumHeight() >= 40
    col = t.sections[0].parent()
    holder = t.b_solve if t.b_solve.parent() is col else t.b_solve.parent()          # the Solve button, or the row holding it (CFD: Solve + Stop)
    lay = col.layout()
    i = lay.indexOf(holder)
    assert i >= 0, "Solve sits in the scrolled column"
    assert lay.itemAt(i + 1).widget() is t.study_box, "the parametric-study slot is right under Solve"
    assert lay.itemAt(i + 2).widget() is [x for x in t.sections if x.title == "Results"][0], "Solve (and its study slot) sit directly above the Results"
    pan = col
    while pan is not None and not hasattr(pan, "default_w"):
        pan = pan.parent()
    assert pan is not None and pan.maximumWidth() >= 16000, "the side panel has no maximum width: drag the divider to widen it"
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
sup = [x for x in fea.sections if x.title == "Supports"][0]
sup.toggle.setChecked(False)
assert sup.sum_lbl.text() == "1 support", sup.sum_lbl.text()

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
