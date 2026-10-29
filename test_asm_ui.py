import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, assembly, asm_patterns, pm_app
tmp = tempfile.mkdtemp()
def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)
sh = gpd_app.AppShell([pa]); print("tabs", sh.tabs.count(), sh.tabs.tabText(0))
w = sh.new_assembly(); print("tabs", sh.tabs.count(), [sh.tabs.tabText(i) for i in range(sh.tabs.count())])
w.insert_files([pa, pb, pb]); A = w.asm
print("components", [(c["name"], c["fixed"], [round(x, 1) for x in c["pos"]]) for c in A.components])
assert A.components[0]["fixed"] and not A.components[1]["fixed"]
# live doc from the part tab
assert sh.part_doc(pa) is not None
# mate block1 bottom to base top via the panel
def faces(c):
    s = w.solid_of(c); pl = [f for f in s.faces() if f.geom_type.name == "PLANE"]
    return {"top": max(pl, key=lambda f: f.center().Z), "bot": min(pl, key=lambda f: f.center().Z)}
c0, c1, c2 = A.components
w.mate_start(); assert w.mode == "mate"
def R(c, f): return {"c": c["id"], "k": "face", "r": am.face_ref(f)}
w.add_mate_ref(R(c0, faces(c0)["top"]), {"cid": c0["id"], "kind": "face", "idx": 0, "label": "Face"})
w.add_mate_ref(R(c1, faces(c1)["bot"]), {"cid": c1["id"], "kind": "face", "idx": 0, "label": "Face"})
print("type auto", w.mate_type, "err", w.mate_error, [round(x, 2) for x in c1["pos"]])
w.mate_ok(); print("mates", [m["type"] for m in A.mates], A.status, [round(x, 2) for x in c1["pos"]], A.dof)
assert abs(c1["pos"][2] - 10) < 1e-3 or abs(c1["pos"][2] - 20) < 1e-3
# a distance mate in X using side faces (click-free)
sideX = lambda c: max([f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().X)
w.mate_start(); w.add_mate_ref(R(c0, sideX(c0)), {"cid": c0["id"], "kind": "face", "idx": 0, "label": "Face"}); w.add_mate_ref(R(c1, sideX(c1)), {"cid": c1["id"], "kind": "face", "idx": 0, "label": "Face"})
w.set_mate_type("distance"); w.mate_opts["value"] = 5.0; w.mate_preview(); print("preview", w.mate_error, [round(x, 2) for x in c1["pos"]])
w.mate_ok(); print("after distance", [round(x, 2) for x in c1["pos"]], A.dof)
# cancel path
w.mate_start(); w.mate_cancel(); assert w.mode is None
# undo / redo
n = len(A.mates); w.do_undo(); print("undo mates", len(w.asm.mates), "was", n); w.do_redo(); assert len(w.asm.mates) == n; A = w.asm; c0, c1, c2 = A.components[:3]
# linear pattern of block 2
asm_patterns.start(w, "linear"); w.pat_toggle_comp(c2["id"]) if c2["id"] not in w.pat["data"]["seeds"] else None
w.pat["data"]["seeds"] = [A.components[2]["id"]]; w.pat["data"].update(n1=3, s1=20.0, dir1="Y"); w.refresh_derived()
print("derived", [(c["name"], np.round(np.array(c["M"])[:3, 3], 1).tolist()) for c in A.components if c.get("derived")])
assert len([c for c in A.components if c.get("derived")]) == 2
asm_patterns.ok(w); w.update_all()
asm_patterns.start(w, "mirror"); w.pat["data"]["seeds"] = [A.components[2]["id"]]; w.pat["data"]["plane"] = "Right"; w.refresh_derived()
mc = [c for c in A.components if c.get("derived") and c["derived"]["kind"] == "mirror"]; print("mirror", len(mc), np.linalg.det(np.array(mc[0]["M"])[:3, :3]))
assert abs(np.linalg.det(np.array(mc[0]["M"])[:3, :3]) + 1) < 1e-9
asm_patterns.ok(w); w.update_all()
asm_patterns.start(w, "circular"); w.pat["data"]["seeds"] = [A.components[2]["id"]]; w.pat["data"].update(n=4, axis="Z"); w.refresh_derived()
print("circular copies", len([c for c in A.components if c.get("derived") and c["derived"]["kind"] == "circular"])); asm_patterns.cancel(w)
print("after cancel", len(A.patterns), len([c for c in A.components if c.get("derived")]))
# moving the seed moves its copies
c2["fixed"] = False
# drag math
st = w.drag_begin.__func__  # exists
# drag maths (no GL here, so the state is built by hand)
c1["fixed"] = False
A.mates = [m for m in A.mates if m["id"] != "M2"]; w.solve_all()
R0, t0 = A.pose(c1); d_, r_, u_ = w.view_vectors()
st = {"cid": c1["id"], "x": 100, "y": 100, "hit": np.array(t0), "R": R0, "t": t0, "d": d_, "right": r_, "up": u_, "cluster": A.cluster(c1["id"]), "lc": np.array([5.0, 5.0, 5.0])}
w.mode = "move"; w.drag_move(st, 130, 120); print("dragged (stays on the base top)", [round(x, 2) for x in c1["pos"]], A.status)
assert abs(c1["pos"][2] - 10) < 1e-3
w.mode = "rotate"; w.drag_move(st, 140, 100); print("rotated, still on top:", [round(x, 2) for x in c1["pos"]], np.round(am.rodrigues(c1["rv"])[:, 2], 3)); w.drag_end(st)
assert np.allclose(am.rodrigues(c1["rv"])[:, 2], [0, 0, 1], atol=1e-3)
w.mode = None
# mass properties
pr = asm_patterns.assembly_props(w); print("assembly mass kg", round(pr["mass"], 4), "com", np.round(pr["com"], 2))
w.mass_open(); print(w.mass_dlg.out.toPlainText()[:90].replace("\n", " | "))
# save / reopen with relative paths
ap = os.path.join(tmp, "asm1.gpa"); w.path = ap; w.save(); txt = open(ap).read(); print("relative path in file:", '"path": "base.gpd"' in txt)
sh2 = gpd_app.AppShell([ap]); w2 = sh2.cur(); print("reopened", len(w2.asm.components), len(w2.asm.mates), len(w2.asm.patterns), w2.asm.status)
# edit component opens the part tab
w.sel_comp = c1["id"]; n_tabs = sh.tabs.count(); w.edit_component(); print("tabs after edit", n_tabs, sh.tabs.count(), sh.tabs.currentIndex())
# dirty star
p = sh.cur(); p.doc.params["X"] = "5"; sh.refresh_titles(); print(sh.tabs.tabText(sh.tabs.currentIndex()))
print("OK")
