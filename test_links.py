import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, assembly, pm_app, sim_tab, sim_links, sim_slice
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
pb = make_part("block.gpd", ((0, 0), (20, 20)), 40)
sh = gpd_app.AppShell([pa]); wp = sh.cur()
assert wp.doc.sims == [] and not wp.is_dirty()
# a simulation of the part, saved: it is listed and the part becomes dirty
w = sh.add_sim("fea"); w.tab.picker.select(w.source_items()[0][0]); w.tab.picker.go()
sp = os.path.join(tmp, "plate_fea.gps"); w.path = sp
assert w.save(); assert [os.path.basename(e["path"]) for e in wp.doc.sims] == ["plate_fea.gps"], wp.doc.sims
assert wp.doc.sims[0]["path"] == "plate_fea.gps", wp.doc.sims          # relative to the part
assert wp.is_dirty(); print(w.status_lbl.text())
tree_txt = [wp.tree.topLevelItem(0).child(i).text(0) for i in range(wp.tree.topLevelItem(0).childCount())]
assert any("Simulations (1)" in t for t in tree_txt), tree_txt
# save the part: file contains sims; close sim tab, double-click in the tree opens it
assert wp.save(); assert json.load(open(pa))["sims"][0]["path"] == "plate_fea.gps"; assert not wp.is_dirty()
sh.tabs.removeTab(sh.tabs.indexOf(w)); w.deleteLater()
wp2 = sh.open_path(pa); wp2 = sh.tabs.widget(sh.find_tab(pa))
assert not [1 for i in range(sh.tabs.count()) if isinstance(sh.tabs.widget(i), sim_tab.SimWindow)], "must not open by itself"
root = wp2.tree.topLevelItem(0)
sim_item = None
for i in range(root.childCount()):
    c = root.child(i)
    if "Simulations" in c.text(0): sim_item = c.child(0)
assert sim_item is not None
wp2.tree_double(sim_item)
opened = [sh.tabs.widget(i) for i in range(sh.tabs.count()) if isinstance(sh.tabs.widget(i), sim_tab.SimWindow)]
assert len(opened) == 1 and opened[0].src_tab is wp2, opened
print("tree double-click opens the simulation OK")
# change the sim, save the part -> the sim is saved too
s2 = opened[0]; s2.tab.supports_dirty = None
before = s2.saved_sig
s2.saved_sig = "changed"           # pretend it has unsaved changes
assert s2.is_dirty()
wp2.save(); assert not s2.is_dirty(), "saving the part must save its open simulations"
print("part save also saves simulations:", wp2.status_lbl.text() if hasattr(wp2, "status_lbl") else "")
# unlink + undo
wp2.unlink_sim("plate_fea.gps"); assert wp2.doc.sims == []
wp2.do_undo(); assert wp2.doc.sims, "undo restores the link"
print("after undo:", wp2.doc.sims)
# Save as into another folder rebases relative paths
sub = os.path.join(tmp, "sub"); os.makedirs(sub)
wp2.doc.sims = [{"path": "plate_fea.gps"}]
import shutil
orig_dlg = pm_app.QFileDialog.getSaveFileName
pm_app.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(sub, "copy.gpd"), ""))
wp2.save(as_new=True)
print("rebased:", wp2.doc.sims); assert wp2.doc.sims[0]["path"] == os.path.join("..", "plate_fea.gps")
pm_app.QFileDialog.getSaveFileName = orig_dlg
# assembly
wa = sh.new_assembly(); wa.insert_files([pa, pb]); 
ap = os.path.join(tmp, "asm.gpa"); wa.path = ap; wa.save()
wf = sh.add_sim("fea")
assert wf is not None and wf.src["type"] == "asm"
class Auto:
    def __init__(self, parent, planes, bodies, last=None, multi=False): self.out = {"plane": "Top", "offset": 20.0, "flip": False, "excluded": []}
    def exec(self): return True
sim_tab.sim_slice.SliceDialog = Auto
wf.tab.picker.select(sim_tab.SLICE_NEW); wf.tab.picker.go()
wf.path = os.path.join(tmp, "asm_fea.gps"); assert wf.save()
assert wa.asm.sims and wa.is_dirty()
wa.refresh_tree()
tops = [wa.tree.topLevelItem(0).child(i).text(0) for i in range(wa.tree.topLevelItem(0).childCount())]
assert any("Simulations (1)" in t for t in tops), tops
wa.save(); assert json.load(open(ap))["sims"][0]["path"] == "asm_fea.gps"
print("LINKS OK")
