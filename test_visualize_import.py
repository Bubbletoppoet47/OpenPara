"""Visualize: getting a model in.  A new tab says how to begin; a part or assembly comes in from an open tab (saved or not), from a file, or by
dropping it; File > New Visualize shows the part on screen at once; another model replaces the first and keeps the general settings; Update
from original reads the file itself; the guide exists; the Render section shows the last picture."""
import os, tempfile, shutil
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")     # a fresh copy of the add-on from addons_src (the others are left out: no downloads)
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "motor"]}')
import addons
addons.NOT_RELEASED = ()          # this test is about an add-on that is not in a normal OpenPara yet (see addons.NOT_RELEASED)
addons.startup()
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import QEvent, QCoreApplication, QTimer, QTime
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog, QTextBrowser, QListWidget
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, render_studio, vis_project as vp, vis_guide
try:                                                          # offscreen VTK now and then fails to draw: the drawing is not what is tested here
    import pyvista, pyvistaqt
    pyvista.plotting.plotter.BasePlotter.render = lambda self, *a, **k: None
    pyvistaqt.rwi.QVTKRenderWindowInteractor.paintEvent = lambda self, ev: None
except Exception:
    pass
tmp = tempfile.mkdtemp(prefix="opara_work_")
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)


def settle():
    for _ in range(4):
        app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def box(doc, rect, depth):
    s = doc.add(pm.new_feature("sketch", plane={"base": "Top"})); doc.rebuild(); m = doc.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); doc.store_sketch(s["id"])
    doc.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); doc.rebuild()


def make_part(name, rect, depth):
    d = pm.Document(); box(d, rect, depth)
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p


def height(r):
    return max(float(m[0][:, 2].max()) for m in r.meshes)


pa = make_part("plate.gpd", ((0, 0), (60, 20)), 40)
pb = make_part("block.gpd", ((0, 0), (30, 30)), 15)

# ---------------------------------------------------------------- 1. a new tab with nothing to show says how to begin
sh = gpd_app.AppShell([])
e = sh.new_addon_tab("visualize"); settle()
assert isinstance(e, render_studio.RenderStudio) and e.proj is None and e.title() == "Visualize"
assert e.stack.currentWidget() is e.empty and [b.text() for b in e.empty.buttons] == ["Import part or assembly...", "Open Visualize project..."]
assert not e.props_dock.isVisibleTo(e), "no panel of greyed-out settings while there is nothing to set"
assert [k for k, b in e.bar_buttons.items() if not b.isHidden()] == ["guide"], "the guidance page has the commands: the bar does not repeat them"
assert e.bar_lbl.text() == "No model yet"
assert e.save() is False and not MSGS, "saving nothing is harmless"
# with no part open, Import goes straight to the file dialog
asked = []
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (asked.append(a[1]) or "", ""))
assert e.import_source() is False and asked == ["Part or assembly to show"] and e.proj is None, "cancelled: nothing changes"
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (pa, ""))
assert e.import_source() is True; settle()
assert len(e.bodies) == 1 and e.src_name == "plate.gpd" and e.title() == "Visualize - plate" and "plate.gpd" in e.bar_lbl.text()
assert e.stack.currentWidget() is e.view_page and e.props_dock.isVisibleTo(e) and e.s_cam.isEnabled()
assert sorted(k for k, b in e.bar_buttons.items() if not b.isHidden()) == ["file", "guide", "import", "render", "update"]
assert e.bar_buttons["update"].isEnabled() and e.original() == ("file", pa), "the file can be read again"
assert not e.is_dirty() and e.proj_path is None and sh.tabs.count() == 1, "the file was read, not opened as another tab"
assert sh.tabs.tabText(sh.tabs.indexOf(e)).startswith("Visualize - plate")

# ---------------------------------------------------------------- 2. what can be dropped on the guidance page
assert e.can_take(pa) and not e.can_take(os.path.join(tmp, "nothing.gpd")) and not e.can_take(tmp)
txt = os.path.join(tmp, "notes.txt"); open(txt, "w").write("x"); assert not e.can_take(txt)

# ---------------------------------------------------------------- 3. Update from original reads the FILE (no tab is opened for it); looks and cameras stay
e.sun_time.setTime(QTime(9, 30)); e.changed(); e.cam_add_preset(); n_cams = len(e.proj["cameras"]); h0 = height(e)
make_part("plate.gpd", ((0, 0), (60, 20)), 75)
e.refresh_model(); settle()
assert abs(height(e) - 75) < 1e-6 and abs(h0 - 40) < 1e-6, (h0, height(e))
assert e.proj["sun"]["time"] == "09:30" and len(e.proj["cameras"]) == n_cams and sh.tabs.count() == 1 and e.is_dirty() and not MSGS, MSGS
assert "Updated from plate.gpd" in e.statusBar().currentMessage()

# ---------------------------------------------------------------- 4. the first save puts the project beside the model; it has its own copy
assert e.save() and e.path.endswith("plate_visual.gpv") and os.path.dirname(e.path) == tmp, e.path
assert os.path.isfile(os.path.join(e.path, "source", "plate.gpd")) and "the copy in the project" in e.bar_lbl.text()
assert e.title() == "plate_visual"

# ---------------------------------------------------------------- 5. another model replaces it: asked first, the general settings stay
answers = []
e.confirm_replace_real = e.confirm_replace
e.confirm_replace = lambda: (answers.append(1) or False)
assert e.import_file(pb) is False and answers == [1] and e.src_name == "plate.gpd" and abs(height(e) - 75) < 1e-6, "No: everything stays"
e.confirm_replace = lambda: (answers.append(2) or True)
e.proj["appearance"]["plate"]["roughness"] = 0.11
assert e.import_file(pb) is True and answers == [1, 2]; settle()
assert e.src_name == "block.gpd" and abs(height(e) - 15) < 1e-6 and list(e.proj["appearance"]) == ["block"]
assert e.proj["sun"]["time"] == "09:30" and len(e.proj["cameras"]) == 2, "the sun stays; the cameras start again for the new model"
assert e.is_dirty() and e.repack and e.title() == "plate_visual" and e.original() == ("file", pb)
assert e.save() and os.listdir(os.path.join(e.path, "source")) == ["block.gpd"], os.listdir(os.path.join(e.path, "source"))
assert json.load(open(os.path.join(e.path, vp.MARKER)))["orig"] == pb
# a model that replaces an untouched, unsaved one is not asked about
f = sh.new_addon_tab("visualize"); assert f.import_file(pa) and not f.is_dirty()
box_made = []
f.confirm_replace_orig = f.confirm_replace
assert f.confirm_replace() is True, "nothing to lose: no question"
assert f.import_file(pb) and f.src_name == "block.gpd"
# a file that cannot be shown changes nothing
bad = os.path.join(tmp, "empty.gpd"); open(bad, "w").write(pm.Document().to_json())
MSGS.clear()
assert f.import_file(bad) is False and MSGS and "no solid" in MSGS[-1] and f.src_name == "block.gpd" and len(f.bodies) == 1, MSGS
MSGS.clear()
assert f.import_file(txt) is False and "not a part" in MSGS[-1] and f.src_name == "block.gpd"; MSGS.clear()
sh.close_tab(sh.tabs.indexOf(f)); settle()

# ---------------------------------------------------------------- 6. open tabs: listed (the one on screen first), saved or not
wp = sh.open_path(pa); wn = sh.new_part(); settle()
box(wn.doc, ((0, 0), (10, 10)), 5); wn.update_all()
assert not getattr(wn, "path", None)
sh.tabs.setCurrentWidget(wp)
g = sh.new_addon_tab("visualize"); settle()
assert g.src_name == "plate.gpd" and g.src_tab is wp and g.stack.currentWidget() is g.view_page, "File > New Visualize shows the part that is on screen"
labels = [t for t, _w in g.open_tabs()]
assert labels[0].startswith("plate.gpd") and "(part)" in labels[0] and any("not saved yet" in t for t in labels) and len(labels) == 2, labels
seen = {}
def press_import():
    d = QApplication.activeModalWidget()
    lst = d.findChild(QListWidget)
    seen["rows"] = [lst.item(i).text() for i in range(lst.count())]
    lst.setCurrentRow(1); d.accept()
QTimer.singleShot(300, press_import)
assert g.import_source() is True and seen["rows"] == labels; settle()
assert g.src_tab is wn and g.snapshot and g.orig_path is None and "not saved yet" in g.bar_lbl.text(), "an unsaved part is shown as it is on screen"
assert g.title().startswith("Visualize - ") and g.original() == ("tab", wn)
# a file that is open in a tab is taken from the tab (what is on screen is what is meant)
assert g.import_file(pa) and g.src_tab is wp and g.snapshot is None

# ---------------------------------------------------------------- 7. an unsaved part: straight from its tab; the save asks where
sh.tabs.setCurrentWidget(wn)
u = sh.add_render(); settle()
assert isinstance(u, render_studio.RenderStudio) and len(u.bodies) == 1 and u.snapshot and not MSGS, MSGS
name = os.path.splitext(u.src_name)[0]
where = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (where.append(a[2]) or os.path.join(tmp, "fresh"), ""))
assert u.save() and where and where[0].endswith("_visual.gpv") and u.path == os.path.join(tmp, "fresh.gpv")
assert os.listdir(os.path.join(u.path, "source")) == [name + ".gpd"] and u.snapshot is None
sh.close_tab(sh.tabs.indexOf(wn)); settle(); u.show_state()
assert u.original() == (None, None) and not u.bar_buttons["update"].isEnabled() and "Import source" in u.bar_buttons["update"].toolTip()
MSGS.clear(); u.refresh_model(); assert MSGS and "own copy" in MSGS[-1] and len(u.bodies) == 1; MSGS.clear()
assert u.sun_time.time() is not None and u.save(), "the project still saves: it has its own copy"

# ---------------------------------------------------------------- 8. a part with no solid yet: the tab opens on its guidance page
we = sh.new_part(); settle()
v = sh.add_render(); settle()
assert v is not None and v.proj is None and v.stack.currentWidget() is v.empty and v.candidate is we and "no solid" in v.statusBar().currentMessage()
assert not MSGS, MSGS
sh.close_tab(sh.tabs.indexOf(v)); sh.close_tab(sh.tabs.indexOf(we)); settle()

# ---------------------------------------------------------------- 9. a project folder: opened in an empty tab; found again when it is open
k = sh.new_addon_tab("visualize") if False else render_studio.RenderStudio(shell=sh); sh.add_tab(k); settle()
assert k.proj is None and k.can_take(e.path)
assert k.take_path(e.path) is True and sh.tabs.currentWidget() is e, "the project is open already: go to it"
sh.close_tab(sh.tabs.indexOf(e)); settle()
proj_dir = os.path.join(tmp, "plate_visual.gpv")
assert k.take_path(proj_dir) is True and k.path == proj_dir and k.src_name == "block.gpd" and k.proj["sun"]["time"] == "09:30"
assert k.title() == "plate_visual" and k.stack.currentWidget() is k.view_page
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k_: tmp)
MSGS.clear(); assert k.open_project_dialog() is False and "not a Visualize project" in MSGS[-1]; MSGS.clear()

# ---------------------------------------------------------------- 10. the guide is there (it used to say a file was missing)
assert "Bring in a model" in vis_guide.GUIDE and "Import source" in vis_guide.GUIDE
got = {}
def read_guide():
    d = QApplication.activeModalWidget()
    got["text"] = d.findChild(QTextBrowser).toPlainText(); got["title"] = d.windowTitle(); d.reject()
QTimer.singleShot(300, read_guide); k.show_guide()
assert got["title"] == "Visualize - guide" and "The three stages" in got["text"] and "was not found" not in got["text"]

# ---------------------------------------------------------------- 11. the Render section: quiet until a render runs, then the picture is there
k.show(); settle()
assert not k.run_row.isVisibleTo(k) and not k.res_box.isVisibleTo(k)
k.set_busy(True); assert k.run_row.isVisibleTo(k) and k.b_stop.isEnabled() and not k.b_render.isEnabled()
k.set_busy(False); assert not k.run_row.isVisibleTo(k) and k.b_render.isEnabled()
png = os.path.join(k.tmp, "preview", "preview_Iso.png"); os.makedirs(os.path.dirname(png), exist_ok=True)
im = QImage(320, 180, QImage.Format.Format_RGB32); im.fill(QColor(20, 90, 160)); im.save(png)
k.add_result(png)
assert k.res_box.isVisibleTo(k) and not k.res_pic.icon().isNull() and k.res_lbl.text() == "Preview (not saved)"
final = os.path.join(tmp, "render_Iso.png"); im.save(final); k.add_result(final)
assert "render_Iso.png" in k.res_lbl.text() and k.last_result == final
assert "No video path yet" in k.an_info.text() and "b00020" not in k.an_info.text(), "a note, not an error"
# lengths are shown without tails of digits
k.cam_o[0].setValue(176.48994321); assert k.cam_o[0].text() == "176.49", k.cam_o[0].text()

for w in (g, u, k):
    w.shutdown()
shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(_ud, ignore_errors=True)
print("OK visualize import")
os._exit(0)
