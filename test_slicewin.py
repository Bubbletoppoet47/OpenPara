import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, sim_tab, sim_slice, slice3d, mat_lib
tmp = tempfile.mkdtemp()
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (60, 20)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="40")); d.rebuild()
p = os.path.join(tmp, "plate.gpd"); open(p, "w").write(d.to_json())
sh = gpd_app.AppShell([p]); wp = sh.cur()
# --- visibility mirrors the viewport
allp = [n for n, _ in sim_slice.visible_planes(wp, "part")]; print("visible", allp)
assert allp[:3] == ["Front", "Top", "Right"]
wp.plane_show["Top"] = False
assert "Top" not in [n for n, _ in sim_slice.visible_planes(wp, "part")]
wp.vis["planes"] = False
assert not [n for n, _ in sim_slice.visible_planes(wp, "part")]
wp.vis["planes"] = True; wp.plane_show["Top"] = True
# --- picking without a screen
planes = sim_slice.visible_planes(wp, "part")
bodies = [("plate", wp.doc.solid, wp.doc.material)]
sp = sim_slice.ScenePicker(bodies, planes)
print("flat faces", len(sp.faces), "size", round(sp.size, 1))
assert len(sp.faces) == 6
top = sp.pick((30, 10, 200), (0, 0, -1)); print("pick from above", top)
assert top[0] == "face" and abs(top[1]["n"][2] - 1) < 1e-6 and abs(top[1]["o"][2] - 40) < 1e-6
assert sp.pick((1000, 1000, 1000), (0, 0, 1)) is None
side = sp.pick((30, -200, 20), (0, 1, 0)); print("from the front", side)   # hits the face y=0 (or the Front plane in front of it)
# --- the dialog (3D view may not exist offscreen)
dlg = sim_slice.SliceDialog(wp, planes, bodies, None)
print("3D view:", dlg.pl is not None)
dlg.choose(("plane", "Top")); dlg.offset.setText("20"); dlg.update_preview()
if dlg.pl is not None:
    names = set(dlg.pl.renderer._actors.keys()); print('actors', sorted(names)); assert {'_cutplane', '_cutarrow', '_cutlines'} <= names
assert dlg.preview_loops and "outline" in dlg.info.text(), dlg.info.text()
dlg.reverse(); assert dlg.offset.text() == "-20"
dlg.update_preview(); assert not dlg.preview_loops and 'not cut' in dlg.info.text()   # z=-20 is below the part (z 0..40)
dlg.offset.setText("20"); dlg.nudge(+1); print("after + :", dlg.offset.text())
dlg.choose(("face", top[1])); assert dlg.cur_name == sim_slice.FACE
dlg.offset.setText("-10"); dlg.update_preview(); assert dlg.preview_loops
dlg.go(); print(dlg.out); assert dlg.out["face"] and dlg.out["offset"] == -10
# --- slice_json using the face (offscreen: dialog answered by hand)
w = sh.add_sim("fea")
class Auto:
    def __init__(self, parent, planes, bodies, last=None, multi=False): self.out = dict(dlg.out)
    def exec(self): return True
OrigDlg = sim_slice.SliceDialog
sim_tab.sim_slice.SliceDialog = Auto
w.tab.picker.select(sim_tab.SLICE_NEW); w.tab.picker.go()
assert len(w.tab.geom["faces"]) == 1, w.tab.geom["faces"]
w.tab.picker.select(sim_tab.SLICE_LAST); w.tab.picker.go(); assert len(w.tab.geom["faces"]) == 1
print("SLICEWIN OK")
# --- click ray through the real camera
dlg2 = OrigDlg(wp, planes, bodies, None)
if dlg2.pl is not None:
    dlg2.pl.resize(400, 300); dlg2.pl.render()
    W, H = dlg2.pl.window_size
    dlg2.pl.view_vector((0, 0, -1)); dlg2.pl.reset_camera(); dlg2.pl.render()
    o, dv = dlg2.ray(W // 2, H // 2)
    print("ray", o, dv, "window", W, H)
    hit = dlg2.pick.pick(o, dv); print("centre click ->", hit)
    assert hit is not None
# assembly visibility
import asm_model as am
print("ASM check skipped if no assembly API in test")
