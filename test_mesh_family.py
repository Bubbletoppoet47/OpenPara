"""The Playground's mesh tabs (Mesh FEA, Voxel FEA, Mesh fixing) belong to the analysis family: numbered foldable sections, the bar on top,
their main action in teal, a panel that shows its contents whole, and the icon of their kind on the tab."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"; os.environ["OPARA_CHANNEL"] = "playground"; os.environ["OPARA_PLAYGROUND_MODE"] = "full"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["OPARA_DEV_ADDONS"] = os.path.join(HERE, "dev_addons")
sys.path.insert(0, HERE)
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
from PyQt6.QtWidgets import QApplication, QComboBox, QGroupBox, QMessageBox, QPushButton
app = QApplication([])
# The offscreen test window has no real graphics card behind it: drawing a 3D model there fails now and then inside VTK (not in OpenPara).
# This test is about panels, bars and names, so the 3D views are simply not drawn.
import pyvista, pyvistaqt
pyvista.plotting.plotter.BasePlotter.render = lambda self, *a, **k: None
pyvistaqt.rwi.QVTKRenderWindowInteractor.paintEvent = lambda self, ev: None
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: print("BOX", a[2])))
import addons, ext, gpd_app, ui_kit
Shell = type("Shell", (*ext.SHELL_MIXINS, gpd_app.AppShell), {}) if ext.SHELL_MIXINS else gpd_app.AppShell
sh = Shell(); sh.resize(1500, 900); sh.show()


def settle():
    for _ in range(5):
        app.processEvents()


def fits(w):
    return w.panel_scroll.viewport().width() >= w.panel.minimumSizeHint().width()


for kind, titles, primary in (("tet", ["Geometry", "Mesh", "Material", "Supports and loads", "Solve", "Results", "Verification"], {"Reduce, mesh and show", "Run"}),
                              ("voxel", ["Geometry", "Voxels", "Material", "Supports and loads", "Solve", "Results", "Verification"], {"Voxelise and show", "Run"})):
    if kind not in addons.tab_kinds():
        continue
    w = sh.new_addon_tab(kind); settle()
    assert w is not None, kind
    assert [s.title for s in w.sections] == titles and [s.number for s in w.sections] == list(range(1, 8)), [(s.number, s.title) for s in w.sections]
    assert all(isinstance(s, ui_kit.Section) for s in w.sections)
    assert not [g for g in w.panel.findChildren(QGroupBox) if g.title()[:2] in ("1.", "2.", "3.", "4.", "5.", "6.")], "no grey group boxes for the steps"
    assert fits(w), (kind, w.panel_scroll.viewport().width(), w.panel.minimumSizeHint().width())
    assert w.menuWidget() is not None and w.bar_lbl.text() == "Nothing loaded yet"
    styled = {b.text() for b in w.panel.findChildren(QPushButton) if "font-weight:600" in b.styleSheet()}
    assert primary <= styled, (kind, styled)
    assert not sh.tabs.tabIcon(sh.tabs.indexOf(w)).isNull()
    w.sections[2].toggle.setChecked(False); assert not w.sections[2].frame.isVisible() or w.sections[2].frame.isHidden()
    w.sections[2].toggle.setChecked(True)
    w.load_test_model(); settle()
    assert "test" in w.bar_lbl.text().lower(), w.bar_lbl.text()
    assert fits(w), "still whole after a shape is loaded"
# a fold is remembered for the next tab of that kind
if "tet" in addons.tab_kinds():
    a = sh.new_addon_tab("tet"); a.sections[6].toggle.setChecked(False)
    b = sh.new_addon_tab("tet"); assert not b.sections[6].is_open(), "the fold of a section is remembered"
    a.sections[6].toggle.setChecked(True)

m = sh.new_addon_tab("mesh"); settle()
assert m is not None and [s.number for s in m.sections] == list(range(1, len(m.sections) + 1)) and m.sections[0].title == "Mesh"
assert "Repair" in {b.text() for b in m.panel.findChildren(QPushButton) if "font-weight:600" in b.styleSheet()}
assert m.menuWidget() is not None and "triangles" in m.bar_lbl.text() or m.bar_lbl.text() == "Nothing loaded yet"
m.load_shape("blob")
import time
t0 = time.time()
while m.mesh is None and time.time() - t0 < 60:              # (the shape is made in the background)
    app.processEvents(); time.sleep(0.02)
settle()
assert "triangles" in m.bar_lbl.text() and fits(m), (m.bar_lbl.text(), m.panel_scroll.viewport().width(), m.panel.minimumSizeHint().width())
assert not sh.tabs.tabIcon(sh.tabs.indexOf(m)).isNull()
import shutil; shutil.rmtree(UD, ignore_errors=True)
print("OK mesh family")
os._exit(0)
