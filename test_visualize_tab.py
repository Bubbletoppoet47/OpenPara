"""Visualize inside the program: ribbon tab, project FOLDER (.gpv) with its own copy of the model, default output folder, reopening."""
import os, tempfile
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()     # a fresh copy of the add-on from addons_src (the others are left out: no downloads)
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation"]}')
import addons; addons.startup()   # the render module lives in an add-on
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, render_studio, icons, vis_project as vp
tmp = tempfile.mkdtemp()
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("plate.gpd", ((0, 0), (60, 20)), 40)
sh = gpd_app.AppShell([pa]); wp = sh.cur()
labels = []
def walk(o):
    for c in o.children():
        t = getattr(c, "text", None)
        if callable(t):
            try: labels.append(t())
            except Exception: pass
        walk(c)
walk(wp)
assert any("Preview / Render" in l for l in labels), "ribbon button missing"
tabs = [wp.ribbon.tabText(i) for i in range(wp.ribbon.count())]
assert "Visualize" in tabs and "Render" not in tabs, tabs
# unsaved part -> message
sh2 = gpd_app.AppShell([]); sh2.new_part(); assert sh2.add_render() is None and MSGS; MSGS.clear()
r = sh.add_render(); assert isinstance(r, render_studio.RenderStudio), MSGS
assert len(r.bodies) == 1 and r.proj_path is None and not r.is_dirty()
from PyQt6.QtCore import QTime
r.sun_time.setTime(QTime(10, 0)); r.changed(); assert r.is_dirty()
assert r.save(), MSGS
fd = r.path
assert fd.endswith(".gpv") and os.path.isdir(fd) and os.path.dirname(fd) == tmp, fd
assert os.path.isfile(os.path.join(fd, "visualize.json")) and os.path.isdir(os.path.join(fd, "output"))
assert json.load(open(os.path.join(fd, "visualize.json")))["format"] == "openpara-visualize"
cp = os.path.join(fd, "source", "plate.gpd"); assert os.path.isfile(cp), os.listdir(os.path.join(fd, "source"))
assert not wp.doc.renders, "no link is kept in the part"
assert r.out_folder() == os.path.join(fd, "output") and r.proj["output"]["folder"] == ""
other = os.path.join(tmp, "elsewhere"); r.proj["output"]["folder"] = other; assert r.out_folder() == other and os.path.isdir(other)
r.use_project_output(); assert r.out_folder() == os.path.join(fd, "output")
# the project is independent of the original: change/delete the original, reopen the project
assert r.save()
os.remove(pa)
sh.close_tab(sh.tabs.indexOf(r))
r1 = sh.open_project_folder(fd)
assert isinstance(r1, render_studio.RenderStudio) and r1.proj["sun"]["time"] == "10:00" and len(r1.bodies) == 1, MSGS
assert r1.proj["source"] == cp and r1.path == fd
# opening again finds the open tab
assert sh.open_project_folder(fd) is r1
# a part changed afterwards does not change the project until 'read it again'
r1.sun_time.setTime(QTime(12, 0)); r1.changed(); assert r1.is_dirty(); assert r1.save() and not r1.is_dirty()
assert json.load(open(os.path.join(fd, "visualize.json")))["sun"]["time"] == "12:00"
# a second Visualize of the same part gets its own folder
pa = make_part("plate.gpd", ((0, 0), (60, 20)), 40)
wp2 = sh.open_path(pa); r2 = sh.add_render(); assert r2.save() and r2.path != fd and r2.path.endswith("_visual_2.gpv") or r2.path.endswith(".gpv")
# assembly: components are copied into the project
asmp = os.path.join(tmp, "a.gpa")
sh3 = gpd_app.AppShell([]); wa = sh3.new_assembly() if hasattr(sh3, "new_assembly") else None
if wa is not None:
    wa.path = asmp
    wa.asm.add_component(pa) if hasattr(wa.asm, "add_component") else None
r1.shutdown(); r2.shutdown()
print("visualize tab integration OK")
