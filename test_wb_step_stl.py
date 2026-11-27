"""WB-1: a STEP file (.step, .stp) or an STL file dropped on the Workbench canvas becomes a block.  A STEP file with one solid is a Part block; with several it asks each time (one Assembly block,
one Part block per solid, or one Part block with all the solids; cancel does nothing).  An STL is a mesh body: a Part block whose body has one flat face for every triangle, however many,
with its triangles kept; an STL that is not closed is refused with the reason.  The blocks wire into an analysis and a drawing like any other part.   python test_wb_step_stl.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(290, exit=True)
import json
import os
import shutil
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "sheets", "controls", "circuits", "drawings"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path[:0] = [os.path.join(HERE, "shared"), HERE]                        # (shared/ is on the path in a full-dev Playground build, where the Workbench is)

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import numpy as np
import pyvista as pv
from build123d import Box, Compound, Cylinder, Pos, export_step
import exchange as ex
import gpd_app
import pm_model as pm
import wb_canvas as cv
import wb_import
import wb_parts
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbs_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
QDialog.exec = lambda self: 0
P = W.project


def drop(paths, x=400.0, y=200.0):
    """A real drop event on the canvas, as a file manager makes it."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    v = W.view
    ev = QDropEvent(QPointF(v.mapFromScene(QPointF(x, y))), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    v.dropEvent(ev)
    for _ in range(5):
        app.processEvents()
    return ev.isAccepted()


ASKED = []
ANSWER = ["each"]


def ask(tab, name, count):
    ASKED.append((name, count))
    return ANSWER[0]


wb_import.ask_step_how = ask


def solid_of(node):
    d = wb_parts.doc_of_text(json.dumps(node.data["doc"]))
    return None if d is None else d.solid


# ----------------------------------------------------------------------------------------------------------------------------------- the files
plate = Box(40, 30, 10) - Pos(10, 0, 0) * Cylinder(4, 10)
f_one = os.path.join(T, "Plate.step")
export_step(plate, f_one)
f_stp = os.path.join(T, "Plate two.stp")
export_step(plate, f_stp)
f_three = os.path.join(T, "Trio.step")
export_step(Compound([Pos(0, 0, 0) * Box(10, 10, 10), Pos(30, 0, 0) * Box(10, 10, 20), Pos(60, 0, 0) * Box(10, 10, 30)]), f_three)
ball = pv.Sphere(radius=10.0, theta_resolution=24, phi_resolution=24).triangulate()
f_stl = os.path.join(T, "Ball.stl")
ball.save(f_stl)
sheet = pv.Plane(i_size=20, j_size=20, i_resolution=4, j_resolution=4).triangulate()
f_open = os.path.join(T, "Sheet.stl")
sheet.save(f_open)
f_junk = os.path.join(T, "Broken.stl")
open(f_junk, "w").write("this is not a mesh")
f_empty = os.path.join(T, "Nothing.step")
open(f_empty, "w").write("")
ok(isinstance(W, wb_tab.WorkbenchTab) and not P.nodes, "the program opened an empty Workbench")
ok(wb_import.what_is(f_one) == ("step", "") and wb_import.what_is(f_stp) == ("step", "") and wb_import.what_is(f_stl) == ("stl", ""), "the importer knows .step, .stp and .stl")

# ----------------------------------------------------------------------------------------------------------------------------------- a STEP file with one solid
ok(drop([f_one], 400.0, 200.0), "the drop is accepted")
parts = [n for n in P.nodes.values() if n.kind == "part"]
ok(len(parts) == 1 and parts[0].title == "Plate" and not ASKED, f"a STEP file with one solid is one Part block named after the file, with no question ({[n.title for n in parts]})")
n_plate = parts[0]
s = solid_of(n_plate)
ok(s is not None and abs(s.volume - plate.volume) < 1e-6 * plate.volume and s.is_valid, f"with the plate in it ({s.volume:.1f} mm3 of {plate.volume:.1f})")
ok(P.status(n_plate.id, "geometry") == wp.OK, "ready: the geometry cell is ok")
feats = n_plate.data["doc"]["features"]
ok(len(feats) == 1 and feats[0]["kind"] == "imported" and feats[0]["source"] == "Plate.step", "the part is one imported body that says where it came from")
ok(abs(n_plate.pos[0] - 400.0) <= 2 * cv.GRID and abs(n_plate.pos[1] - 200.0) <= 2 * cv.GRID, "at the drop point")
ok("Imported Plate.step" in W.line.text(), f"the status line says what happened ({W.line.text()[:60]})")
ed = W.open_cell(n_plate.id, "geometry")
ok(ed is not None and ed.doc.solid is not None and abs(ed.doc.solid.volume - plate.volume) < 1e-6 * plate.volume, "double-click opens it in the part window, built")
shell.close_tab(shell.tabs.indexOf(ed))
# .stp is the same
n0 = len(P.nodes)
drop([f_stp], 700.0, 200.0)
ok(len(P.nodes) == n0 + 1 and any(n.title == "Plate two" for n in P.nodes.values()), "a .stp file too")

# ----------------------------------------------------------------------------------------------------------------------------------- a STEP file with several solids asks each time
n0 = len(P.nodes)
ids0 = set(P.nodes)
ANSWER[0] = "each"
ASKED.clear()
drop([f_three], 400.0, 500.0)
new = [n for n in P.nodes.values() if n.id not in ids0]
ok(ASKED == [("Trio.step", 3)], f"it asks, with the name of the file and the number of solids ({ASKED})")
ok(len(P.nodes) == n0 + 3 and len(new) == 3 and all(n.kind == "part" for n in new), f"one Part block per solid, named as the solids are in the file ({[n.title for n in new]})")
vols = sorted(round(solid_of(n).volume, 3) for n in new)
ok(vols == [1000.0, 2000.0, 3000.0], f"each with its own solid ({vols})")
xs = sorted(n.pos[0] for n in new)
ok(xs[1] - xs[0] >= cv.BLOCK_W and xs[2] - xs[1] >= cv.BLOCK_W, "side by side")
ok(all(P.status(n.id, "geometry") == wp.OK for n in new), "all ready")

n0 = len(P.nodes)
ANSWER[0] = "assembly"
ASKED.clear()
drop([f_three], 400.0, 800.0)
asm = [n for n in P.nodes.values() if n.kind == "assembly"]
ok(ASKED and len(P.nodes) == n0 + 1 and len(asm) == 1 and asm[0].title == "Trio", f"One Assembly block, named after the file ({[n.title for n in asm]})")
obj = asm[0].data["asm"]
ok(len(obj["components"]) == 3 and len(obj["parts"]) == 3 and all(c["fixed"] for c in obj["components"]), "with a fixed component for each solid, and the parts inside it")
import asm_model as am
a = am.Assembly.from_json(json.dumps(obj))
vols_a = []
for c in a.components:
    d = wb_parts.doc_of_text(json.dumps(a.parts[am.embed_key(c["path"])]["doc"]))
    vols_a.append(round(d.solid.volume, 3) if d is not None and d.solid is not None else None)
ok(sorted(vols_a) == [1000.0, 2000.0, 3000.0], f"each component is one of the solids ({vols_a})")
ok(P.status(asm[0].id, "geometry") == wp.OK, "the assembly block is ready")

n0 = len(P.nodes)
ANSWER[0] = "one"
ASKED.clear()
drop([f_three], 800.0, 800.0)
one = [n for n in P.nodes.values() if n.kind == "part" and n.title == "Trio"]
ok(ASKED and len(P.nodes) == n0 + 1 and len(one) == 1, "one Part block with all the solids")
so = solid_of(one[0])
ok(so is not None and abs(sum(x.volume for x in so.solids()) - 6000.0) < 1e-3 and len(list(so.solids())) == 3, f"it holds the three solids ({len(list(so.solids())) if so is not None else 0})")

n0 = len(P.nodes)
ANSWER[0] = None
MSGS.clear()
drop([f_three], 1100.0, 800.0)
ok(len(P.nodes) == n0 and not MSGS and "cancelled" in W.line.text(), f"Cancel makes nothing, and it is not listed as a failure ({W.line.text()[:60]})")

# ----------------------------------------------------------------------------------------------------------------------------------- a file that is not a STEP file
n0 = len(P.nodes)
MSGS.clear()
drop([f_empty], 400.0, 1100.0)
ok(len(P.nodes) == n0 and any("Nothing.step" in m for m in MSGS), f"an empty .step file is refused, with its name and the reason ({MSGS[-1][:80] if MSGS else None})")

# ----------------------------------------------------------------------------------------------------------------------------------- an STL file
ASKED.clear()
t0 = time.time()
ok(drop([f_stl], 1000.0, 200.0), "an STL dropped")
stl = [n for n in P.nodes.values() if n.title == "Ball"]
ok(len(stl) == 1 and stl[0].kind == "part" and not ASKED, "becomes one Part block named after the file, with no question")
nb = stl[0]
feat = nb.data["doc"]["features"][0]
V, T_ = ex.unpack_mesh(feat["mesh"])
ok(len(nb.data["doc"]["features"]) == 1 and feat["kind"] == "imported" and feat["mesh_tris"] == len(T_) == ball.n_cells, f"a mesh body: its {len(T_)} triangles are kept in the part ({ball.n_cells} in the file)")
ok("brep" not in feat and len(json.dumps(nb.data["doc"])) < 60000, f"and only the triangles: the part is {len(json.dumps(nb.data['doc'])) // 1024} KB, not the solid's BREP")
sb = solid_of(nb)
ok(sb is not None and sb.is_valid and len(sb.faces()) == len(T_), f"with a solid that has one flat face for every triangle ({len(sb.faces()) if sb is not None else 0})")
import repair as R
ok(sb is not None and abs(sb.volume - R.signed_volume(*R.arrays(R.to_mesh(V, T_)))) < 1e-3 * sb.volume, f"the solid is the mesh itself: {sb.volume:.2f} mm3, the volume of the triangles")
bb = sb.bounding_box()
ok(abs(bb.size.X - 20.0) < 0.2 and abs(bb.size.Y - 20.0) < 0.2 and abs(bb.size.Z - 20.0) < 0.2, f"in millimetres ({bb.size.X:.2f} x {bb.size.Y:.2f} x {bb.size.Z:.2f})")
ok(P.status(nb.id, "geometry") == wp.OK, "ready")
ok("1056 triangles" in W.line.text() or f"{ball.n_cells} triangles" in W.line.text(), f"the status line says it is a mesh body ({W.line.text()[:90]})")
ex._MESH_SOLIDS.clear()                                                    # (as after the program was started again: the solid is made from the triangles)
sb2 = solid_of(nb)
ok(sb2 is not None and sb2.is_valid and abs(sb2.volume - sb.volume) < 1e-9 * sb.volume and len(sb2.faces()) == len(T_), "the solid is made from the kept triangles when the part is built again, the same one")
ed = W.open_cell(nb.id, "geometry")
ok(ed is not None and ed.doc.solid is not None and abs(ed.doc.solid.volume - sb.volume) < 1e-6 * sb.volume, "it opens in the part window like any part")
shell.close_tab(shell.tabs.indexOf(ed))
ok(time.time() - t0 < 60, f"(it took {time.time() - t0:.1f} s)")

# a surface that is not closed does not enclose a body
n0 = len(P.nodes)
MSGS.clear()
drop([f_open], 1000.0, 500.0)
ok(len(P.nodes) == n0 and any("Sheet.stl" in m and "not closed" in m for m in MSGS), f"an STL that is not closed is refused, and says so ({MSGS[-1][:100] if MSGS else None})")
MSGS.clear()
drop([f_junk], 1000.0, 700.0)
ok(len(P.nodes) == n0 and any("Broken.stl" in m for m in MSGS), "a file that is not an STL is refused too")

# ----------------------------------------------------------------------------------------------------------------------------------- wired like any part: an analysis and a drawing
sol = W.add_block("solid", 1500, 200, title="Ball stress")
ok(P.why_not_link(nb.id, "geometry", sol.id, "geometry") is None and P.why_not_link(n_plate.id, "geometry", sol.id, "geometry") is None, "the geometry of a STEP part and of an STL part can be wired into a 3D analysis")
P.link(nb.id, "geometry", sol.id, "geometry")
ok(P.incoming(sol.id, "geometry") is not None and P.incoming(sol.id, "geometry").a == nb.id, "and is")
drw = W.add_block("drawing", 1500, 600, title="Ball drawing")
P.link(nb.id, "geometry", drw.id, "models")
P.link(n_plate.id, "geometry", drw.id, "models")
w = W.open_cell(drw.id, "document")
app.processEvents()
ok(w is not None and [m["name"] for m in w.d.models] == ["Ball", "Plate"], f"a drawing takes both as models ({[m['name'] for m in w.d.models] if w is not None else None})")
v = w.d.add_view(w.d.models[0]["id"], "Front", (100.0, 100.0))
ok(len(w.d.projection(v).vis) > 0, f"and draws the ball ({len(w.d.projection(v).vis)} lines)")
v2 = w.d.add_view(w.d.models[1]["id"], "Top", (100.0, 40.0))
ok(len(w.d.projection(v2).vis) >= 4, f"and the plate with its hole ({len(w.d.projection(v2).vis)} lines)")

# ----------------------------------------------------------------------------------------------------------------------------------- no limit on the triangles
big = pv.Sphere(radius=10.0, theta_resolution=128, phi_resolution=128).triangulate()
f_big = os.path.join(T, "Big ball.stl")
big.save(f_big)
t0 = time.time()
n0 = len(P.nodes)
drop([f_big], 1000.0, 900.0)
nbig = [n for n in P.nodes.values() if n.title == "Big ball"]
fb = nbig[0].data["doc"]["features"][0] if nbig else {}
ok(big.n_cells > 30000 and len(P.nodes) == n0 + 1 and fb.get("mesh_tris") == big.n_cells, f"an STL of {big.n_cells} triangles (more than the old limit of 30 000) comes in whole ({fb.get('mesh_tris')} kept)")
sbig = solid_of(nbig[0]) if nbig else None
ok(sbig is not None and sbig.is_valid and len(sbig.faces()) == big.n_cells, f"with a solid of {len(sbig.faces()) if sbig is not None else 0} flat faces ({time.time() - t0:.0f} s)")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("ALL OK")
