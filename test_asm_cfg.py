import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QInputDialog
app = QApplication([])
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, asm_patterns
tmp = tempfile.mkdtemp()
def make_part(name, rect, depth, cfg=None):
    d = pm.Document(); d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H")); d.rebuild()
    if cfg:
        d.cfg_add_col("g:H"); d.cfg_add("Tall"); d.cfg_set_cell("Tall", "g:H", str(cfg))
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10, cfg=30)
sh = gpd_app.AppShell([]); w = sh.new_assembly(); w.insert_files([pa, pb, pb]); A = w.asm
c0, c1, c2 = A.components
def faces(c):
    pl = [f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"]
    return max(pl, key=lambda f: f.center().Z), min(pl, key=lambda f: f.center().Z)
R = lambda c, f: {"c": c["id"], "k": "face", "r": am.face_ref(f)}
w.mate_start(); w.add_mate_ref(R(c0, faces(c0)[0]), {"cid": c0["id"], "kind": "face", "idx": 0, "label": "F"}); w.add_mate_ref(R(c1, faces(c1)[1]), {"cid": c1["id"], "kind": "face", "idx": 0, "label": "F"}); w.mate_ok()
A = w.asm; c0, c1, c2 = A.components[:3]
print("part cfg names for block:", A.part_cfgs_fn(c1), "current:", A.part_cfg_fn(c1))
cp = w.cfg_panel
for key in (f"c:{c1['id']}", f"x:{c2['id']}"):
    cp.add_column(key)
QInputDialog.getText = staticmethod(lambda *a, **k: ("TallBlock", True)); cp.add_config()
print("assembly cfg", A.cfg["names"], [A.cfg_label(k) for k in A.cfg["cols"]])
r = A.cfg["names"].index("TallBlock")
A.cfg_set_cell("TallBlock", f"c:{c1['id']}", "Tall"); A.cfg_set_cell("TallBlock", f"x:{c2['id']}", True)
top = lambda: max(w.solid_of(c1).bounding_box().max.Z, 0)
print("block height now", w.solid_of(c1).bounding_box().size.Z)
cp.activate("TallBlock")
w = sh.cur() if False else w; A = w.asm
c1 = A.comp(c1["id"]); c2 = A.comp(c2["id"])
print("active", A.cfg["active"], "block config", c1.get("config"), "height", w.solid_of(c1).bounding_box().size.Z, "c2 suppressed", c2.get("suppressed"),
      "entries", sorted(w.entries), "pos", np.round(c1["pos"], 2), "status", A.status)
assert abs(w.solid_of(c1).bounding_box().size.Z - 30) < 1e-6 and c2.get("suppressed") and c2["id"] not in w.entries
cp.activate("Default"); A = w.asm; c1 = A.comp(c1["id"]); c2 = A.comp(c2["id"])
print("back: height", w.solid_of(c1).bounding_box().size.Z, "c2 suppressed", c2.get("suppressed"), sorted(w.entries))
assert abs(w.solid_of(c1).bounding_box().size.Z - 10) < 1e-6 and not c2.get("suppressed")
# display
w.asm.comp(c1["id"])["color"] = [1, 0, 0]; w.asm.comp(c1["id"])["opacity"] = 0.4; w.display_changed(); print("display rows", w.disp_panel.table.rowCount())
# save/reload keeps configs
ap = os.path.join(tmp, "a.gpa"); w.path = ap; w.save(); sh2 = gpd_app.AppShell([ap]); w2 = sh2.cur(); print("reloaded", w2.asm.cfg["names"], w2.asm.cfg["cols"], w2.asm.comp(c1["id"]).get("color"))
w2.cfg_panel.activate("TallBlock"); print("reloaded active", w2.asm.cfg["active"], w2.solid_of(w2.asm.comp(c1["id"])).bounding_box().size.Z)
print("OK")
