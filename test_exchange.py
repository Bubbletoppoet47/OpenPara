"""STEP / STL export and STEP import: round trips with negative controls.  python test_exchange.py"""
import os
import struct
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from build123d import Box, Cylinder, Pos

import exchange as ex
import partgen
import pm_model as pm

fails = []


def check(c, m):
    print(("  ok   " if c else "  FAIL ") + m, flush=True)
    if not c:
        fails.append(m)


def vol(s):
    return sum(x.volume for x in s.solids())


tmp = tempfile.mkdtemp()
# ---- a part with holes, and a gear
plate = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(4, 10) - Pos(-10, 5, 0) * Cylinder(3, 10)
d = pm.Document()
d.add(pm.new_feature("partgen", gen="Spur gear", params=partgen.defaults("Spur gear"), place={"plane": "Top", "ox": "0", "oy": "0", "oz": "0"}))
d.rebuild()
gear = d.solid
check(gear is not None and vol(gear) > 0, f"gear built, volume {vol(gear):.1f}")

# ---- STEP round trip of a part
p = os.path.join(tmp, "plate.step")
ex.export_step(p, [("plate", plate)])
back = ex.read_step(p)
check(len(back) == 1 and abs(vol(back[0][1]) - vol(plate)) < 1e-6 * vol(plate), f"plate: STEP out and in, volume {vol(back[0][1]):.3f} vs {vol(plate):.3f}")
check(back[0][0] == "plate", f"the name survives: {back[0][0]!r}")
bb0, bb1 = plate.bounding_box(), back[0][1].bounding_box()
check(np.allclose([bb0.size.X, bb0.size.Y, bb0.size.Z], [bb1.size.X, bb1.size.Y, bb1.size.Z], atol=1e-6), "plate: bounding box equal")
p2 = os.path.join(tmp, "gear.step")
ex.export_step(p2, [("gear", gear)])
g2 = ex.read_step(p2)
check(abs(vol(g2[0][1]) - vol(gear)) < 1e-5 * vol(gear), f"gear: STEP volume {vol(g2[0][1]):.2f} vs {vol(gear):.2f}")
check(not abs(vol(g2[0][1]) - vol(plate)) < 1.0, "negative control: the gear file is not the plate")

# ---- an assembly: two solids in their poses, separate named solids
M = np.eye(4)
M[:3, 3] = [60, 0, 0]
a_items = [("plate<1>", ex.place(plate, np.eye(4))), ("gear<1>", ex.place(gear, M))]
p3 = os.path.join(tmp, "asm.step")
ex.export_step(p3, a_items)
r = ex.read_step(p3)
check(len(r) == 2, f"assembly STEP holds {len(r)} solids")
names = sorted(n for n, _s in r)
check(names == ["gear_1_", "plate_1_"] or names == sorted([ex.safe("gear<1>"), ex.safe("plate<1>")]), f"named solids: {names}")
gx = [s for n, s in r if n.startswith("gear")][0]
check(abs(gx.bounding_box().center().X - 60) < 1.0, f"the moved gear sits at x = {gx.bounding_box().center().X:.2f} (60 expected)")
check(abs(sum(vol(s) for _n, s in r) - (vol(plate) + vol(gear))) < 1e-4 * (vol(plate) + vol(gear)), "assembly: total volume kept")
bad = ex.place(gear, np.eye(4))
p4 = os.path.join(tmp, "asm_bad.step")
ex.export_step(p4, [("plate<1>", plate), ("gear<1>", bad)])
gb = [s for n, s in ex.read_step(p4) if n.startswith("gear")][0]
check(abs(gb.bounding_box().center().X - 60) > 30, "negative control: an unmoved gear is detected as not at x = 60")
pf = os.path.join(tmp, "fused.step")
ex.export_step(pf, [("a", Box(10, 10, 10)), ("b", Pos(5, 0, 0) * Box(10, 10, 10))], fuse=True)
rf = ex.read_step(pf)
check(len(rf) == 1 and abs(vol(rf[0][1]) - 1500) < 1e-3, f"fused: one solid of volume {vol(rf[0][1]):.2f} (1500 expected)")

# ---- STL
ps = os.path.join(tmp, "plate.stl")
ex.export_stl(ps, plate, 0.01, 0.1)
raw = open(ps, "rb").read()
n = struct.unpack("<I", raw[80:84])[0]
check(len(raw) == 84 + 50 * n and n > 100, f"binary STL with {n} triangles")
tri = np.frombuffer(raw[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
V = tri["v"].astype(float)
vstl = abs(np.einsum("ij,ij->i", V[:, 0], np.cross(V[:, 1], V[:, 2])).sum() / 6)
check(abs(vstl - vol(plate)) < 0.005 * vol(plate), f"STL volume {vstl:.2f} vs solid {vol(plate):.2f}")
check(np.allclose(V.reshape(-1, 3).min(0), [-20, -15, -5], atol=1e-3) and np.allclose(V.reshape(-1, 3).max(0), [20, 15, 5], atol=1e-3), "STL bounding box = the plate's")
ps2 = os.path.join(tmp, "plate_coarse.stl")
ex.export_stl(ps2, plate, 0.5, 0.8)
n2 = struct.unpack("<I", open(ps2, "rb").read()[80:84])[0]
check(n2 < n, f"negative control: a coarser tolerance gives fewer triangles ({n2} < {n})")
files = ex.export_stl_each(os.path.join(tmp, "each"), a_items, 0.05, 0.2)
check(len(files) == 2 and all(os.path.getsize(f) > 84 for f in files), f"one STL per component: {[os.path.basename(f) for f in files]}")
try:
    ex.export_stl(os.path.join(tmp, "none.stl"), None)
    check(False, "an empty part must refuse to export")
except ValueError:
    check(True, "an empty part refuses to export")

# ---- imported body inside a part document: save, reload, add features on top
src = ex.read_step(p)[0][1]
import exchange_dialog as xd
doc = xd.import_doc("plate", src, "plate.step")
check(doc.status[doc.features[0]["id"]] == "ok" and abs(vol(doc.solid) - vol(plate)) < 1e-6 * vol(plate), "imported body builds as the first feature")
js = doc.to_json()
d2 = pm.Document.from_json(js)
d2.rebuild()
check(d2.solid is not None and abs(vol(d2.solid) - vol(plate)) < 1e-6 * vol(plate), "imported body survives save and reload (no file needed)")
os.remove(p)
d3 = pm.Document.from_json(js)
d3.rebuild()
check(d3.solid is not None, "...even after the STEP file is deleted")
# a feature on top: a cut through a sketch on the Top plane
d3.add(pm.new_feature("partgen", gen="Spur gear", params=partgen.defaults("Spur gear"), place={"plane": "Top", "ox": "0", "oy": "0", "oz": "20"}))
d3.rebuild()
check(d3.solid is not None and vol(d3.solid) > vol(plate) + 1.0, f"a feature added on top of the imported body: volume {vol(d3.solid):.1f} > {vol(plate):.1f}")
f0 = d3.features[0]
f0["brep"] = "garbage"
d3.rebuild()
check(d3.status[f0["id"]].startswith("error") and d3.solid is None, "a damaged stored shape gives a clear error, not a crash: " + d3.status[f0["id"]][:60])

# ---- the dialogs' data path (no windows): export items of a part window and an assembly
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import pm_app
w = pm_app.MainWindow()
w.doc = doc
w.update_all(fit=True)
items, is_asm, base = xd.export_items(w)
check(items is not None and not is_asm and len(items) == 1 and items[0][1] is not None, "export items of a part tab")
w2 = pm_app.MainWindow()
w2.doc = pm.Document()
items, is_asm, base = xd.export_items(w2)
check(items and items[0][1] is None, "an empty part reports no solid (the dialog then says so)")
print("\nFAILED:" if fails else "\nALL OK", fails if fails else "")
os._exit(1 if fails else 0)
