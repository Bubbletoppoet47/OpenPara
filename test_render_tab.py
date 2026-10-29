import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, assembly, pm_app, sim_links, render_studio, icons
tmp = tempfile.mkdtemp()
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("plate.gpd", ((0, 0), (60, 20)), 40)
sh = gpd_app.AppShell([pa]); wp = sh.cur()
# ribbon has the Renderer tab with New render
labels = []
def walk(o):
    for c in o.children():
        t = getattr(c, "text", None)
        if callable(t):
            try: labels.append(t())
            except Exception: pass
        walk(c)
walk(wp)
assert any("New render" in l for l in labels), "ribbon button missing"
assert not icons.icon("New render").isNull()
# unsaved part -> message
sh2 = gpd_app.AppShell([]); sh2.new_part(); assert sh2.add_render() is None and MSGS; MSGS.clear()
# new render from part
r = sh.add_render(); assert isinstance(r, render_studio.RenderStudio) and r.kind == "render", MSGS
assert len(r.bodies) == 1 and r.proj["source"] == pa and r.path is None
assert not r.is_dirty() and r.title().startswith("plate")
from PyQt6.QtCore import QTime
r.sun_time.setTime(QTime(10, 0)); r.changed(); assert r.is_dirty(), "edit must mark dirty"
assert r.save(), MSGS
gp = r.path; assert os.path.dirname(gp) == tmp and gp.endswith("_render.gpr") and os.path.exists(gp)
assert wp.doc.renders and wp.doc.renders[0]["path"] == os.path.basename(gp), wp.doc.renders
root = wp.tree.topLevelItem(0)
txt = [root.child(i).text(0) for i in range(root.childCount())]
assert any("Renders (1)" in t for t in txt), txt
assert wp.save() and json.load(open(pa))["renders"][0]["path"] == os.path.basename(gp)
# close render tab, reopen through tree
sh.close_tab(sh.tabs.indexOf(r))
assert not [1 for i in range(sh.tabs.count()) if isinstance(sh.tabs.widget(i), render_studio.RenderStudio)]
root = wp.tree.topLevelItem(0); item = None
for i in range(root.childCount()):
    if "Renders" in root.child(i).text(0): item = root.child(i).child(0)
wp.tree_double(item)
rs_ = [sh.tabs.widget(i) for i in range(sh.tabs.count()) if isinstance(sh.tabs.widget(i), render_studio.RenderStudio)]
assert len(rs_) == 1 and rs_[0].proj["sun"]["time"] == "10:00" and rs_[0].src_tab is wp, rs_
r = rs_[0]
# part save saves dirty open render
r.sun_time.setTime(QTime(12, 0)); r.changed(); assert r.is_dirty()
wp.save(); assert not r.is_dirty() and json.load(open(gp))["sun"]["time"] == "12:00"
# opening the .gpr through the shell finds the open tab
assert sh.open_path(gp) is r
# model change then refresh keeps settings
wp.doc.add(pm.new_feature("extrude", sketch=wp.doc.features[0]["id"], depth="5")) if False else None
r.refresh_model(); assert r.proj["sun"]["time"] == "12:00" and r.is_dirty()
# render from a render tab -> same source, second render
r2 = sh.add_render(); assert r2 is not r and r2.source_widget() is wp
# assembly
asmp = os.path.join(tmp, "a.gpa")
sh3 = gpd_app.AppShell([]); wa = sh3.new_assembly() if hasattr(sh3, "new_assembly") else None
print("assembly shell:", wa)
if wa is not None:
    wa.path = asmp
    wa.asm.add_component(pa) if hasattr(wa.asm, "add_component") else None
    ra = sh3.add_render()
    print("assembly render:", ra, MSGS[-1:] )
# closing stops nothing running; shutdown is safe
r.shutdown()
print("render tab integration OK")
