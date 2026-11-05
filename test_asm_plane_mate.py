"""Mates with the assembly's own planes work with a single component (Mate used to refuse to start with fewer than two)."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, asm_refs
tmp = tempfile.mkdtemp()
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (10, 10)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
pb = os.path.join(tmp, "block.gpd"); open(pb, "w").write(d.to_json())
sh = gpd_app.AppShell([pb]); w = sh.new_assembly(); w.insert_files([pb])
A = w.asm; c = A.components[0]
assert len(A.components) == 1
w.mate_start(); assert w.mode == "mate", "Mate starts with one component"
def pick(*data):
    it = asm_refs.item_from_data(w, data); assert it is not None, data
    w.add_mate_ref(it["ref"], it)
# the single component is fixed by default: free it, move it away, then mate its plane to the assembly's plane
w.mate_cancel(quiet=True)
c["fixed"] = False; c["pos"] = [0.0, 0.0, 30.0]
w.mate_start(); pick("wplane", "Top"); pick("cplane", c["id"], "Top")
assert w.mate_type == "coincident" and not w.mate_error, w.mate_error
w.mate_ok(); assert len(A.mates) == 1 and abs(c["pos"][2]) < 1e-3, (c["pos"], A.status)
# a distance mate to the same plane
c["pos"] = [0.0, 0.0, 30.0]; A.mates.clear()
w.mate_start(); pick("wplane", "Top"); pick("cplane", c["id"], "Top")
w.mate_type = "distance"; w.mate_opts = {"value": 5.0}; w.mate_preview(); assert not w.mate_error, w.mate_error
w.mate_ok(); assert abs(abs(c["pos"][2]) - 5) < 1e-3, c["pos"]
# a symmetric mate: two points of the component about an assembly plane
A.mates.clear(); c["pos"] = [0.0, 0.0, 0.0]
w.mate_start(); w.mate_type = "symmetric"
import asm_model as am
sol = w.solid_of(c); vs = sol.vertices()
def vref(v): p = v.center(); return {"c": c["id"], "k": "vertex", "r": {"p": [p.X, p.Y, p.Z]}}
for v in (vs[0], vs[-1]):
    p = v.center(); w.add_mate_ref(vref(v), {"cid": c["id"], "kind": "vertex", "idx": 0, "pt": [p.X, p.Y, p.Z], "label": "Point"})
pick("wplane", "Front")
assert len(w.mate_sel) == 3 and not w.mate_error, (w.mate_error, len(w.mate_sel))
w.mate_cancel(quiet=True)
print("OK plane mates")
os._exit(0)
