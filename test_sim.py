import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, assembly, pm_app, sim_tab, mat_lib, slice3d
tmp = tempfile.mkdtemp()
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
def make_part(name, rect, depth, mat=None):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    if mat: d.material = mat
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
alu = mat_lib.material_dict(mat_lib.find("Aluminum 6061"))
steel = mat_lib.default_material()
pa = make_part("plate.gpd", ((0, 0), (60, 20)), 40, steel)
pb = make_part("block.gpd", ((0, 0), (20, 20)), 40, alu)
sh = gpd_app.AppShell([pa])
wp = sh.cur(); assert isinstance(wp, pm_app.MainWindow)
# --- material editing
assert wp.doc.material["name"] == "Steel (generic)" and wp.doc.material["E_MPa"] == 200000.0
dlg = mat_lib.MaterialDialog(wp, wp.doc.material); dlg.select_name("Aluminum 6061"); dlg.picked(0)
assert dlg.f["E_MPa"].text() == "68900", dlg.f["E_MPa"].text()
dlg.f["name"].setText("My alloy"); dlg.f["density"].setText("2500"); dlg.accept_it()
assert dlg.result_material()["E_MPa"] == 68900.0 and dlg.result_material()["density"] == 2500.0
print("material dialog OK")
# --- 2D FEA of the part, from its sketch
w = sh.add_sim("fea"); assert isinstance(w, sim_tab.SimWindow) and w.src["type"] == "part"
items = w.source_items(); print("items", items)
assert any(i[0] == sim_tab.SLICE_NEW for i in items)
sid = items[0][0]
w.tab.picker.select(sid); w.tab.picker.go()
t = w.tab
assert t.model is not None and len(t.geom["faces"]) == 1, t.geom["faces"]
print("E field", t.e_E.text(), "nu", t.e_nu.text(), "sy", t.e_sy.text())
assert float(t.e_E.text()) == 200000.0 and float(t.e_nu.text()) == 0.3
print("2D FEA from sketch OK;", w.status_lbl.text())
# --- slice of the part
class Fake:   # answer the slice dialog
    pass
orig = sim_tab.sim_slice.SliceDialog
class AutoDlg:
    def __init__(self, parent, planes, bodies=(), last=None, multi=False):
        self.planes, self.bodies = planes, bodies; self.out = {"plane": "Top", "offset": 20.0, "flip": False, "excluded": []}
    def exec(self): return True
sim_tab.sim_slice.SliceDialog = AutoDlg
t.picker.select(sim_tab.SLICE_NEW); t.picker.go()
assert len(t.geom["faces"]) == 1 and w.meta["slice"]["offset"] == 20.0
print("part slice OK;", t.info.text()[:80])
# --- save / reopen
p = os.path.join(tmp, "s1.gps")
import PyQt6.QtWidgets as QW
w.path = p; assert w.save()
w2 = sim_tab.SimWindow.open_file(sh, p)
assert w2.tab.model is not None and w2.meta["slice"]["plane"] == "Top" and w2.kind == "fea"
print("save/open OK")
# --- 2D CFD and 1D
wc = sh.add_sim("cfd"); wc.tab.picker.select(wc.source_items()[0][0]); wc.tab.picker.go(); assert wc.tab.model is not None
wb = sh.add_sim("beam"); wb.tab.picker.select(wb.source_items()[0][0]); wb.tab.picker.go(); assert wb.tab.model is not None
print("cfd + beam import OK", [i[1] for i in wb.source_items()])
# --- assembly slice (two parts, touching, different materials)
sh2 = sh
wa = sh.new_assembly(); wa.insert_files([pa, pb]); A = wa.asm
c0, c1 = A.components
c1["pos"] = [60.0, 0.0, 0.0]; c1["fixed"] = True   # block touches the plate's right end (x = 60..80)
wa.refresh_parts() if hasattr(wa, "refresh_parts") else None
print("comps", [(c["name"], c["pos"]) for c in A.components])
assert sh.add_sim("beam") is None and MSGS and "assembly" in MSGS[-1]
wf = sh.add_sim("fea"); assert wf.src["type"] == "asm"
items = wf.source_items(); print("asm items", items); assert [i[0] for i in items] == [sim_tab.SLICE_NEW]
AutoDlg.__init__ = lambda self, parent, planes, bodies=(), last=None, multi=False: setattr(self, "out", {"plane": "Top", "offset": 20.0, "flip": False, "excluded": []}) or None
wf.tab.picker.select(sim_tab.SLICE_NEW); wf.tab.picker.go()
t = wf.tab
print("regions", [(f["id"], round(f["net_area"], 1), f["included"]) for f in t.geom["faces"]], t.region_names)
assert len(t.geom["faces"]) == 2 and len(t.region_mats) == 2
Es = sorted(m["E_MPa"] for m in t.region_mats.values()); assert Es == [68900.0, 200000.0], Es
print("assembly slice OK;", wf.status_lbl.text())
import sim_slice
assert [n for n, _ in sim_slice.visible_planes(wa, "asm")][:3] == ["Front", "Top", "Right"]
wa.asm.world_show["Top"] = False
assert "Top" not in [n for n, _ in sim_slice.visible_planes(wa, "asm")]
wa.asm.world_show["Top"] = True
print("assembly plane visibility OK")
print("region mats in solver units", t.read_material()["region_mats"])
# --- refresh
wf.tab.result = None; wf.tab.mesh = None
wf.refresh(); assert len(wf.tab.geom["faces"]) == 2 and len(wf.tab.region_mats) == 2
print("refresh OK")
print("SIM OK")
