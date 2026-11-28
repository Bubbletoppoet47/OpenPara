"""The Slicer block of the Workbench (SLC-5): Part and Assembly -> Slicer -> G-code and toolpaths, in the real program window (the add-on loaded as the Playground does it).

What it checks: the kind is registered with its four cells and has an adapter; the wires (a Part and an Assembly can be wired into Geometry, an analysis or a slicer cannot); the
mesh of a solid at print grade (welded, closed, the volume of the part); where parts are put on the plate (one in the middle of the bed, several in rows that fit, the side that is up);
with the compiled engine: Update slices a box of known size and the toolpaths are over it in the middle of the Elegoo plate, the plastic is its volume less the infill, the cells go stale
when the Part or the Setup changes, a bad setting is a failure that names the setting, a cancel stops it, the G-code is exported, an assembly prints every component, and a project with a
Slicer saves and reopens with the Setup intact and the result gone.   python test_wb_slicer.py   (ORCA_CORE_BUILD_DIR names the folder with the compiled module, ORCA_CORE_PROFILES the
Orca profiles, ORCA_CORE_RESOURCES Orca's resources folder or the package's own; without them the engine part says so and passes)"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(290, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
shutil.copytree(os.path.join(HERE, "dev_addons", "workbench"), os.path.join(DEV, "workbench"), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "engines", "orca_core", "python"))
sys.path.insert(0, os.path.join(HERE, "dev_addons", "workbench"))

import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
import PyQt6.QtWidgets as qw
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import asm_model as am
import gpd_app
import pm_model as pm
import sk_tools as sk
import wb_nodes
import wb_project as wp
import wb_slicer as ws
import wb_tab

# ------------------------------------------------------------------------------------------------------------------------------------ no window: the pieces
v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
vv = np.vstack([v, v[:2] + [0, 0, 0]])                         # two vertices that are the same point as vertices 0 and 1
w_v, w_f = ws.weld(vv, [[0, 1, 2], [0, 2, 3], [4, 5, 2], [4, 4, 5]])
ok(len(w_v) == 4 and len(w_f) == 3, f"welding merges the vertices that are one point and drops the collapsed triangle ({len(w_v)} vertices, {len(w_f)} triangles)")
for side, vec in (("+Z", (0, 0, 1)), ("-Z", (0, 0, -1)), ("+X", (1, 0, 0)), ("-X", (-1, 0, 0)), ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0))):
    R = ws.UP[side]
    ok(np.allclose(R @ vec, (0, 0, 1)) and abs(np.linalg.det(R) - 1) < 1e-12, f"'{side} up' turns that side to +Z and is a rotation, not a mirror")
c, fits = ws.arrange([(20, 20)], (0, 0, 256, 256))
ok(c == [(128.0, 128.0)] and fits, "one part goes to the middle of the bed")
c, fits = ws.arrange([(100, 50), (100, 50), (100, 50)], (0, 0, 256, 256))
ok(fits and len(c) == 3 and min(abs(a[0] - b[0]) + abs(a[1] - b[1]) for i, a in enumerate(c) for b in c[i + 1:]) >= 50, f"three parts are put apart on the bed: {c}")
c, fits = ws.arrange([(300, 10)], (0, 0, 256, 256))
ok(not fits, "a part wider than the bed is said not to fit")
ok(ws.bed_of({"printable_area": ["0x0", "256x0", "256x256", "0x256"]}) == (0.0, 0.0, 256.0, 256.0), "the bed comes from printable_area")

# ------------------------------------------------------------------------------------------------------------------------------------ the window
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
P = W.project


def box_json(w, d, h):
    doc = pm.Document()
    doc.params = {"H": str(h)}
    s = doc.add(pm.new_feature("sketch", plane={"base": "Top"}))
    doc.rebuild()
    m = doc.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (w, d))
    sk.solve_model(m)
    doc.store_sketch(s["id"])
    doc.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    doc.rebuild()
    return json.loads(doc.to_json())


ok("slicer" in wp.KINDS and [c.key for c in wp.KINDS["slicer"].cells] == ["geometry", "setup", "slicing", "preview"], "the kind is registered with Geometry, Setup, Slicing and Preview")
ok(wp.KINDS["slicer"].cell("slicing").provides == ("toolpaths",) and wp.KINDS["slicer"].cell("geometry").many, "Slicing gives toolpaths; Geometry takes any number of wires")
ok(wb_nodes.adapter_for("slicer") is not None and "slicer" not in wb_nodes.check_kinds(), "it has an adapter and is not listed as 'not wired in'")
ok("Slicer" in [wp.KINDS[k].label for k in wp.KINDS] and wp.KINDS["slicer"].group == "Component Tools", "it is offered in the Component Tools")
A = wb_nodes.adapter_for("slicer")

nP = W.add_block("part", 40, 40, title="Box", data={"doc": box_json(20, 20, 10)})
nS = W.add_block("slicer", 360, 40, title="Print")
ok(nS.data.get("setup", {}).get("machine") == ws.DEFAULT_MACHINE and P.cell(nS.id, "setup")["ready"], "a new block has a Setup (the Elegoo Centauri Carbon 0.4 nozzle, 0.20mm Standard, Elegoo PLA) and it is ready")
ok(P.status(nS.id, "geometry") == wp.INCOMPLETE and P.status(nS.id, "slicing") == wp.INCOMPLETE, "with no wire the geometry is incomplete and so is the slicing")
ok(P.why_not_link(nP.id, "geometry", nS.id, "slicing") is not None and P.why_not_link(nS.id, "slicing", nP.id, "geometry") is not None, "Slicing does not take geometry and Part does not take toolpaths")
nA = W.add_block("solid", 40, 300, title="Analysis")
ok(P.why_not_link(nS.id, "slicing", nA.id, "geometry") is not None, "toolpaths do not go into an analysis' Geometry (that cell comes with the printed-part analysis)")
W.scene.make_link(nP.id, "geometry", nS.id, "geometry")
ok(len(P.incoming_all(nS.id, "geometry")) == 1, "a Part is wired into Geometry")
ok(P.status(nS.id, "geometry") == wp.REFRESH, f"Geometry says refresh ({P.status(nS.id, 'geometry')})")
ok(A.refresh(W, nS, "geometry") is None, "Refresh finds something to print")

# ---- the mesh of a part at print grade, and the plate
objs = ws.objects_of_source(nP)
ok(len(objs) == 1 and objs[0][1] == "Box", "a Part gives one object, named as the block")
_k, _n, mv, mf = objs[0]
ok(abs(mv[:, 0].max() - mv[:, 0].min() - 20) < 1e-6 and abs(mv[:, 2].max() - mv[:, 2].min() - 10) < 1e-6, "its mesh is 20 x 20 x 10 mm")
a = mv[mf[:, 0]]
vol = abs(np.einsum("ij,ij->i", a, np.cross(mv[mf[:, 1]], mv[mf[:, 2]])).sum() / 6)
ok(abs(vol - 4000) < 1e-3, f"and it is closed and has the volume of the part ({vol:.1f} mm3)")
import collections
edges = collections.Counter()
for t in mf:
    for i in range(3):
        edges[tuple(sorted((int(t[i]), int(t[(i + 1) % 3]))))] += 1
ok(set(edges.values()) == {2}, "every edge is shared by two triangles (the faces were welded)")
setup = A.setup_of(nS)
placed, notes = ws.place(objs, setup, (0, 0, 256, 256))
T4 = placed[0][4]
cx = (mv @ T4[:3, :3].T + T4[:3, 3])
ok(np.allclose(cx.min(0), (118, 118, 0)) and np.allclose(cx.max(0), (138, 138, 10)), "one box is put in the middle of the 256 mm bed, on the plate")
setup["parts"][objs[0][0]] = {"up": "+X", "turn": 0.0, "x": 50.0, "y": 60.0, "settings": {}}
placed, _n = ws.place(objs, setup, (0, 0, 256, 256))
T4 = placed[0][4]
cx = (mv @ T4[:3, :3].T + T4[:3, 3])
ok(np.allclose(cx.min(0), (45, 50, 0)) and np.allclose(cx.max(0), (55, 70, 20)), "with 'X up' and a place of its own, the 10 mm side is across and the box stands 20 mm high at (50, 60)")
setup["parts"].clear()

# ---- an assembly of two boxes (embedded copies, as the workbench keeps them)
asm = am.Assembly()
pa = asm.embed_part("Small", "part", box_json(10, 10, 5))
pb = asm.embed_part("Tall", "part", box_json(10, 10, 30))
asm.add_component(pa, pos=(0, 0, 0))
asm.add_component(pb, pos=(40, 0, 0))
nAs = W.add_block("assembly", 40, 160, title="Pair", data={"asm": json.loads(asm.to_json())})
ao = ws.objects_of_source(nAs)
ok(len(ao) == 2 and {o[1] for o in ao} == {"Pair/Small<1>", "Pair/Tall<1>"}, f"an Assembly gives one object for each component ({[o[1] for o in ao]})")
ok(abs(ao[1][2][:, 0].min() - 40) < 1e-6 and abs(ao[1][2][:, 2].max() - 30) < 1e-6, "in the place the assembly puts it")
try:
    ws.objects_of_source(nA)
    ok(False, "an analysis cannot be printed")
except ws.SlicerError as e:
    ok("cannot be printed" in str(e), f"an analysis cannot be printed, in words: {e}")
try:
    ws.objects_of_source(W.add_block("part", 700, 40, title="Nothing"))
    ok(False, "an empty part cannot be printed")
except ws.SlicerError as e:
    ok("empty" in str(e), f"an empty part cannot be printed, in words: {e}")

# ------------------------------------------------------------------------------------------------------------------------------------ with the engine
oc, why = ws.engine()
prof, why2 = ws.profiles()
if oc is None or prof is None:
    ok(True, f"the engine part is skipped here: {why or why2}")
    print("\nSlicer block: " + ("all passed (engine part skipped)" if not FAILS else f"{len(FAILS)} FAILED"))
    sys.exit(1 if FAILS else 0)

ok(wb_nodes.availability(W, "slicer")[0], "with the engine and the profiles the block is offered")
st0 = P.statuses(nS.id)
ok(W.update_project(only={nS.id}) in (None, [], True) or True, "Update Project runs")
res = A.result_of(W, nS)
ok(res is not None and P.status(nS.id, "slicing") == wp.OK, f"Update sliced the part ({P.status(nS.id, 'slicing')}: {P.cell(nS.id, 'slicing')['failed']})")
if res is None:
    print("\nSlicer block: %d FAILED" % len(FAILS))
    sys.exit(1)
ok(res.paths.n_layers == 50 and abs(res.paths.layer_z[-1] - 10.0) < 1e-3, f"10 mm at 0.2 mm is {res.paths.n_layers} layers")
pts = res.paths.select(np.isin(res.paths.role, [1, 2, 3, 4, 5, 6, 7])).points
ok(pts[:, 0].min() > 117.5 and pts[:, 0].max() < 138.5 and pts[:, 1].min() > 117.5 and pts[:, 1].max() < 138.5, "the toolpaths are over the box in the middle of the plate")
ok(0.25 < res.paths.select(np.isin(res.paths.role, list(range(1, 12)))).volumes().sum() / 4000 < 0.75, "and the plastic is a part of the box's volume (walls, infill and skins)")
inf = ws.summary(res)
ok(inf["layers"] == 50 and inf["filament_g"] > 0 and inf["by_role"].get("Outer wall", 0) > 0 and inf["gcode_mb"] > 0, f"the summary has layers, grams and the plastic by role ({inf['time_text']}, {inf['filament_g']:.1f} g)")
ok(P.status(nS.id, "preview") == wp.OK, "Preview is ok")
gx = os.path.join(T, "box.gcode")
A.export_gcode(W, nS, gx)
txt = open(gx, encoding="utf-8").read()
ok("EXCLUDE_OBJECT_DEFINE" in txt and "SET_PRINT_STATS_INFO" in txt and "; generated by" in txt, "the G-code is exported (the Centauri Carbon's own start and layer change)")

# ---- the cells go stale
s_slice = P.cell(nS.id, "slicing")["stamp"]
nP.data["doc"] = box_json(20, 20, 12)
P.touch(nP.id, "geometry")
ok(P.status(nS.id, "geometry") == wp.REFRESH and P.status(nS.id, "slicing") in (wp.UPDATE, wp.INCOMPLETE), f"a change of the Part: Geometry says refresh, Slicing says update ({P.status(nS.id, 'slicing')})")
W.update_project(only={nS.id})
r2 = A.result_of(W, nS)
ok(P.status(nS.id, "slicing") == wp.OK and r2.paths.n_layers == 60, f"Update again: the taller box has {r2.paths.n_layers} layers")
setup = json.loads(json.dumps(A.setup_of(nS)))
setup["overrides"]["sparse_infill_density"] = "40%"
ok(A.apply_setup(W, nS, setup) and P.status(nS.id, "slicing") == wp.UPDATE, "a change in the Setup makes Slicing say update")
ok(A.apply_setup(W, nS, json.loads(json.dumps(setup))) is False, "the same Setup again is not a change")
W.update_project(only={nS.id})
r3 = A.result_of(W, nS)
v2 = r3.paths.select(r3.paths.role == 4).volumes().sum()
v1 = r2.paths.select(r2.paths.role == 4).volumes().sum()
ok(v2 > 1.5 * v1, f"40 % infill gives more sparse infill than 15 % ({v1:.0f} -> {v2:.0f} mm3)")
# ---- the two windows (the dialogs are driven, not shown: exec() is replaced)
from PyQt6.QtWidgets import QDialog, QSlider, QTableWidget, QTableWidgetItem, QWidget
SEEN = {}


def fake_exec(self):
    title = self.windowTitle()
    SEEN[title] = True
    if title.startswith("Slicer setup"):
        t = self.findChildren(QTableWidget)[0]
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem("sparse_infill_density"))
        t.setItem(r, 1, QTableWidgetItem("35%"))
        SEEN["tables"] = len(self.findChildren(QTableWidget))
        self.accept()
    elif title.startswith("Slicer preview"):
        view = [w for w in self.findChildren(QWidget) if type(w).__name__ == "LayerView"][0]
        img = view.grab().toImage()
        bg = img.pixelColor(2, 2).name()
        SEEN["drawn"] = any(img.pixelColor(x, y).name() != bg for x in range(0, img.width(), 7) for y in range(0, img.height(), 7))
        sl = self.findChildren(QSlider)[0]
        sl.setValue(1)
        img2 = view.grab().toImage()
        SEEN["first layer drawn"] = any(img2.pixelColor(x, y).name() != img2.pixelColor(2, 2).name() for x in range(0, img2.width(), 7) for y in range(0, img2.height(), 7))
        self.accept()
    else:
        self.reject()
    return QDialog.DialogCode.Accepted


qw.QDialog.exec = fake_exec
W.open_cell(nS.id, "preview")
ok(SEEN.get("Slicer preview: Print") and SEEN.get("drawn") and SEEN.get("first layer drawn"), "the Preview opens on the result and draws the layers (the last one, and the first after the slider is moved)")
ws.open_setup(W, nS, A)
ok(SEEN.get("Slicer setup: Print") and A.setup_of(nS)["overrides"].get("sparse_infill_density") == "35%", "the Setup window opens, lists the profiles of the printer, and a changed setting is kept")
ok(P.status(nS.id, "slicing") == wp.UPDATE, "and the change makes Slicing say update")
W.update_project(only={nS.id})
ok(P.status(nS.id, "slicing") == wp.OK, "which runs again")
A.apply_setup(W, nS, {**json.loads(json.dumps(A.setup_of(nS))), "overrides": {}})
W.update_project(only={nS.id})
W.open_cell(nS.id, "geometry")
# the setup of a part: which side is up changes how the box lies
setup = json.loads(json.dumps(A.setup_of(nS)))
ws.part_setup(setup, nP.id)["up"] = "+X"
A.apply_setup(W, nS, setup)
ws.part_setup(setup, nP.id)["up"] = "+X"
W.update_project(only={nS.id})
r4 = A.result_of(W, nS)
ok(r4.paths.n_layers == 100, f"printed with the 20 mm side up it is {r4.paths.n_layers} layers, not 60")

# ---- a bad setting is a failure that names it
bad = json.loads(json.dumps(A.setup_of(nS)))
bad["overrides"]["wall_loops"] = "abc"
A.apply_setup(W, nS, bad)
W.update_project(only={nS.id})
ok(P.status(nS.id, "slicing") == wp.FAILED and "wall_loops" in P.cell(nS.id, "slicing")["failed"], f"a setting that cannot be read is a failure that names it: {P.cell(nS.id, 'slicing')['failed']}")
ok(A.result_of(W, nS) is None, "and there is no result left from before")
good = json.loads(json.dumps(bad))
del good["overrides"]["wall_loops"]
A.apply_setup(W, nS, good)
bad2 = json.loads(json.dumps(good))
bad2["machine"], bad2["process"] = "Elegoo Centauri Carbon 0.4 nozzle", "0.30mm Standard @Elegoo CC 0.6 nozzle"
bad2["resolved"] = None
A.apply_setup(W, nS, bad2)
W.update_project(only={nS.id})
ok(P.status(nS.id, "slicing") == wp.FAILED and "not made for the printer" in P.cell(nS.id, "slicing")["failed"], f"a print profile that is not made for the printer is said in words: {P.cell(nS.id, 'slicing')['failed']}")
A.apply_setup(W, nS, good)

# ---- cancel
nBig = W.add_block("part", 40, 420, title="Big", data={"doc": box_json(100, 100, 60)})
nS2 = W.add_block("slicer", 360, 420, title="Slow")
W.scene.make_link(nBig.id, "geometry", nS2.id, "geometry")
big = json.loads(json.dumps(A.setup_of(nS2)))
big["overrides"]["layer_height"] = "0.1"
A.apply_setup(W, nS2, big)
asked = []
orig_say = W.say


def say_and_cancel(text):
    if "slicing" in str(text) and not asked:
        asked.append(A.cancel(W, nS2))
    return orig_say(text)


W.say = say_and_cancel
W.update_project(only={nS2.id})
W.say = orig_say
ok(asked == [True] and P.status(nS2.id, "slicing") == wp.FAILED and "cancel" in P.cell(nS2.id, "slicing")["failed"].lower(), f"a cancel stops a long slice: {P.cell(nS2.id, 'slicing')['failed']}")
ok(A.cancel(W, nS2) is False, "and cancelling when nothing runs does nothing")

# ---- an assembly prints every component
nS3 = W.add_block("slicer", 360, 160, title="Print pair")
W.scene.make_link(nAs.id, "geometry", nS3.id, "geometry")
W.update_project(only={nS3.id})
r5 = A.result_of(W, nS3)
ok(r5 is not None and abs(r5.paths.layer_z[-1] - 30.0) < 1e-3, "the assembly's tallest component sets the height")
x = r5.paths.select(r5.paths.role == 2).points
ok((x[:, 0] < 128).any() and (x[:, 0] > 128).any() and (x[:, 0].max() - x[:, 0].min()) > 20, "both components are printed, apart")

# ---- the project: Setup kept, result gone
f2 = os.path.join(T, "print.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f2, ""))
setup_before = json.loads(json.dumps(A.setup_of(nS)))
ok(W.save(True), "the project is saved with a Slicer in it")
raw = json.load(open(f2))
sl = [n for n in raw["nodes"] if n["kind"] == "slicer" and n["title"] == "Print"][0]
ok(sl["data"]["setup"]["machine"] == ws.DEFAULT_MACHINE and sl["data"]["setup"]["resolved"]["settings"]["gcode_flavor"] == "klipper", "the file holds the Setup with the resolved presets")
ok(set(sl["data"]) == {"setup"} and os.path.getsize(f2) < 400_000, f"and nothing of the result (the whole project file is {os.path.getsize(f2) // 1000} kB)")
W3 = shell.open_path(f2)
p3 = W3.project
nS3b = [n for n in p3.nodes.values() if n.kind == "slicer" and n.title == "Print"][0]
ok(A.setup_of(nS3b) == setup_before, "reopened: the Setup is as it was")
ok(A.result_of(W3, nS3b) is None and p3.status(nS3b.id, "slicing") in (wp.UPDATE, wp.INCOMPLETE), f"and the result is gone; Slicing says {p3.status(nS3b.id, 'slicing')}")
W3.update_project(only={nS3b.id})
ok(A.result_of(W3, nS3b) is not None and p3.status(nS3b.id, "slicing") == wp.OK, "one Update brings it back")
d = A.export(W3, nS3b, T)
ok(os.path.isfile(os.path.join(d, "slicer.json")) and json.load(open(os.path.join(d, "slicer.json")))["setup"]["filament"] == ws.DEFAULT_FILAMENT, "the block is saved on its own as a .slicer folder")

print("\nSlicer block: " + ("all passed" if not FAILS else f"{len(FAILS)} FAILED"))
sys.exit(1 if FAILS else 0)
