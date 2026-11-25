"""One common width for the left panel of every analysis window (1D FEA, 2D FEA, 2D CFD, 2D Thermal, 3D FEA, 3D Thermal): they all open at
sim_ui.SIDE_W, and no page of any of them is cut off or needs a sideways scroll bar - at one and at two screen scales.  Run it plain for scale 1;
it starts itself again with QT_SCALE_FACTOR=2."""
import os, sys, tempfile, subprocess
if "--scale2" not in sys.argv and not os.environ.get("QT_SCALE_FACTOR"):
    env = dict(os.environ, QT_SCALE_FACTOR="2")
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--scale2"], env=env)
    if r.returncode:
        raise SystemExit(r.returncode)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"),
                os.path.join(HERE, "dev_addons", "thermal3d"), os.path.join(HERE, "shared")]
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QScrollArea
app = QApplication([])
SCALE = app.primaryScreen().devicePixelRatio()
QMessageBox.information = staticmethod(lambda *a, **k: None)
import pm_model as pmod, sk_tools as sk
import physics_tab, beam_tab, cfd_tab, solid_tab, thermal_tab, thermal3d_tab
import sim_ui, ui_kit


class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


T = tempfile.mkdtemp()
d = pmod.Document(); d.params = {"T": "10"}
s = d.add(pmod.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m_ = d.models[s["id"]]
r = sk.add_rect_corner(m_, (0, 0), (100, 10))
m_.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m_.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m_); d.store_sketch(s["id"])
d.add(pmod.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())

wins = {}
wins["1D FEA"] = beam_tab.BeamTab(Win())
wins["2D FEA"] = physics_tab.PhysicsTab(Win())
wins["2D CFD"] = cfd_tab.CFDTab(Win())
wins["2D Thermal"] = thermal_tab.ThermalTab(Win())
s3 = solid_tab.SolidWindow(threaded=False); assert s3.create_project(os.path.join(T, "a")) and s3.import_file(part); wins["3D FEA"] = s3
t3 = thermal3d_tab.ThermalWindow(threaded=False); assert t3.create_project(os.path.join(T, "b")) and t3.import_file(part); wins["3D Thermal"] = t3
for name, t in wins.items():
    t.resize(1300, 1000); t.show()
for _ in range(3):
    app.processEvents()


def panel_scroll(t):
    """the scroll area that holds the Details of the window's outline"""
    for w in t.findChildren(QScrollArea):
        if w.widget() is not None and t.sections and w.widget().isAncestorOf(t.sections[0]):
            return w
    raise AssertionError("no panel scroll area")


# 1. the constant and the width every window opens at
assert sim_ui.SIDE_W == 420, sim_ui.SIDE_W
widths = {}
for name, t in wins.items():
    widths[name] = panel_scroll(t).width()
print("panel widths", widths, "scale", SCALE)
assert len(set(widths.values())) == 1, f"the windows open at different widths: {widths}"
assert abs(next(iter(widths.values())) - sim_ui.SIDE_W) <= 1, widths

# 2. every page of every window fits: no sideways scroll bar, nothing needing more than the panel has
for name, t in wins.items():
    sa = panel_scroll(t)
    for k in t.outline.keys():
        t.outline.select(k)
        for _ in range(3):
            app.processEvents()
        bar = sa.horizontalScrollBar()
        need = ui_kit.content_width(sa.widget())
        assert need <= sim_ui.SIDE_W, f"{name} / {k}: the page needs {need} px, the panel is {sim_ui.SIDE_W}"
        assert bar.maximum() == 0 and not bar.isVisible(), f"{name} / {k}: a sideways scroll bar ({bar.maximum()} px)"
        assert sa.width() == widths[name], f"{name} / {k}: the panel changed width to {sa.width()}"

# 3. the pages that were wider now wrap or stack instead of pushing the panel wide
reg = next(w for w in wins["2D Thermal"].findChildren(QLabel) if w.text().startswith("<b>Regions</b>"))
assert reg.wordWrap(), "the Regions caption of the 2D Thermal window wraps"
for name in ("3D FEA", "3D Thermal"):
    t = wins[name]
    t.outline.select("Geometry")
    for _ in range(3):
        app.processEvents()
    assert t.b_split.isVisible() and t.sp_cols.isVisible(), name
    # Split / Unsplit sit on a row of their own, below the row of the two spin boxes
    y_split = t.b_split.mapTo(t, t.b_split.rect().topLeft()).y()
    y_spin = t.sp_cols.mapTo(t, t.sp_cols.rect().topLeft()).y()
    assert y_split >= y_spin + t.sp_cols.height(), (name, y_split, y_spin)

# 4. a narrower window does not change the width the panels open at, and dragging the divider still works
for name, t in wins.items():
    sa = panel_scroll(t)
    split = sa.parentWidget()
    while split is not None and not (type(split).__name__ == "QSplitter" and split.orientation() == Qt.Orientation.Horizontal):
        split = split.parentWidget()                       # (the outline and its Details are in a vertical splitter of their own)
    assert split is not None, name
    sizes = split.sizes()
    split.setSizes([sim_ui.SIDE_W + 120, sizes[1] - 120])
    app.processEvents()
    assert panel_scroll(t).width() == sim_ui.SIDE_W + 120, (name, panel_scroll(t).width())
    split.setSizes([sim_ui.SIDE_W, sizes[1]])
    app.processEvents()

print("sidebar width: all six windows open at", sim_ui.SIDE_W, "- no page needs a sideways scroll bar")
print("OK")
