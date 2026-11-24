"""Importing the files the program already had into a Workbench project (wb_import) in the real program window: a part (.gpd), an assembly (.gpa; its parts are read into it),
analysis project folders (.gpv / .gpf ...: inputs kept, no meshes or results, no path of this computer), tool files (.opsheet .opctl .opcirc, a .truss folder) and another project
(.opara: its blocks and wires are added next to the ones that are here).  The files are not touched; nothing is computed; what cannot be imported says why.
python test_wb_import.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "sheets", "controls", "circuits"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication, QMessageBox
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


import asm_model as am
import assembly
import gpd_app
import physics_store as pstore
import pm_app
import pm_model as pm
import recent
import sim_project as sp
import sk_tools as sk
import wb_analysis
import wb_import
import wb_nodes
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbi_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def bar_json(depth):
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (100, 10))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    return json.loads(d.to_json())


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    return path


def blob(path):
    if os.path.isdir(path):
        return {os.path.relpath(os.path.join(r, f), path): open(os.path.join(r, f), "rb").read() for r, _d, fs in os.walk(path) for f in fs}
    return open(path, "rb").read()


def say():
    return W.line.text()


P = W.project
ok(isinstance(W, wb_tab.WorkbenchTab) and not P.nodes, "the program opened an empty Workbench")

# ------------------------------------------------------------------------------------------------------------------------------------ a part
src = os.path.join(T, "src")
os.makedirs(src)
gpd = write_json(os.path.join(src, "Bar.gpd"), bar_json(10))
before = blob(gpd)
nP = W.import_file(gpd)
ok(nP is not None and nP.kind == "part" and nP.title == "Bar", f"a .gpd becomes a Part block named after the file ({nP.kind if nP else None} {nP.title if nP else None})")
ok(nP.data["doc"]["params"] == {"H": "10"} and len(nP.data["doc"]["features"]) == 2, "with the part inside it")
ok(P.status(nP.id, "geometry") == wp.OK, f"it has a solid: ok ({P.status(nP.id, 'geometry')})")
ok(blob(gpd) == before, "the file itself is not touched")
ok("Imported Bar.gpd" in say(), f"and the status line says what happened ({say()[:70]})")
ed = W.open_cell(nP.id, "geometry")
ok(isinstance(ed, pm_app.MainWindow) and ed.doc.solid is not None and ed.doc.params["H"] == "10", "double-click opens it in the part window, built")
ok(W.sync_editors() == [], "and opening the imported part is not a change")
shell.close_tab(shell.tabs.indexOf(ed))

empty = write_json(os.path.join(src, "Empty.gpd"), json.loads(pm.Document().to_json()))
nE = W.import_file(empty)
ok(nE is not None and P.status(nE.id, "geometry") == wp.INCOMPLETE, "a part with nothing built says incomplete")

# what is not a part
bad = os.path.join(src, "Bad.gpd")
write_json(bad, {"hello": 1})
n_before = len(P.nodes)
ok(W.import_file(bad) is None and "not a part file" in say(), f"JSON that is not a part is refused, with the reason ({say()[:80]})")
open(os.path.join(src, "Junk.gpd"), "w").write("this is not json at all")
ok(W.import_file(os.path.join(src, "Junk.gpd")) is None and "not a part file" in say(), "a file that is not JSON too")
ok(W.import_file(os.path.join(src, "nothing.gpd")) is None and "was not found" in say(), f"a path that is not there ({say()[:60]})")
open(os.path.join(src, "x.txt"), "w").write("x")
ok(W.import_file(os.path.join(src, "x.txt")) is None and "not a kind of file" in say(), f"a kind of file the workbench does not know ({say()[:60]})")
ok(len(P.nodes) == n_before, "none of them added a block")

# ------------------------------------------------------------------------------------------------------------------------------------ an assembly
pa = write_json(os.path.join(src, "pa.gpd"), bar_json(10))
pb = write_json(os.path.join(src, "pb.gpd"), bar_json(20))
a = am.Assembly()
a.add_component("pa.gpd", fixed=True)
a.add_component("pb.gpd", pos=(0, 20, 0), fixed=True)
a.add_component("gone.gpd", pos=(0, 40, 0), fixed=True)
gpa = os.path.join(src, "Frame.gpa")
open(gpa, "w").write(a.to_json())
before_a = blob(gpa)
nA = W.import_file(gpa)
ok(nA is not None and nA.kind == "assembly" and nA.title == "Frame", "a .gpa becomes an Assembly block")
paths = [c["path"] for c in nA.data["asm"]["components"]]
ok(paths[0].startswith("embedded:") and paths[1].startswith("embedded:") and paths[2] == "gone.gpd", f"the parts it refers to are inside it now; the one that is not there stays a reference ({paths})")
ok(len(nA.data["asm"]["parts"]) == 2, "two copies are kept")
ok("gone.gpd" in say() and "not found" in say(), f"and the missing one is named ({say()[-110:]})")
ok(blob(gpa) == before_a, "the assembly file is not touched")
ok(P.status(nA.id, "geometry") == wp.OK, "ready: it has components")
os.remove(pa)
os.remove(pb)
sw = W.open_cell(nA.id, "geometry")
ok(isinstance(sw, assembly.AssemblyWindow) and sw.embed, "it opens in the assembly window")
solids = [sw.solid_of(c) for c in sw.asm.components[:2]]
ok(all(s is not None for s in solids) and abs(solids[1].bounding_box().size.Z - 20) < 1e-6, "and builds from the copies although the part files are gone")
ok(W.sync_editors() == [], "opening it is not a change")
shell.close_tab(shell.tabs.indexOf(sw))

# ------------------------------------------------------------------------------------------------------------------------------------ analysis folders
part_for_sim = write_json(os.path.join(src, "SimBar.gpd"), bar_json(10))
f3 = os.path.join(src, "Bar test.gpv")
sp.create(f3, "solid")
sp.import_source(f3, orig_path=part_for_sim)
# the setup is made the way a person makes it, in the 3D window of the program
import numpy as np
wmake = shell.new_addon_tab("solid", f3)
gface = lambda n: next(f["id"] for f in wmake.geom["faces"] if np.dot(f["normal"], n) > 0.99)
wmake.select_faces([gface([-1, 0, 0])])
wmake.add_support("fixed")
wmake.select_faces([gface([1, 0, 0])])
wmake.add_load("force", {"f": [1000.0, 0.0, 0.0]})
wmake.save()
shell.close_tab(shell.tabs.indexOf(wmake))
before_f3 = blob(f3)
n3 = W.import_file(f3)
ok(n3 is not None and n3.kind == "solid" and n3.title == "Bar test", f"a .gpv folder becomes a 3D Static Structural block ({n3.kind if n3 else None})")
ok("simulation.json" in n3.data["files"] and any(k.startswith("source/") for k in n3.data["files"]), f"it holds the project folder ({sorted(n3.data['files'])})")
man = json.loads(wp.unpack_bytes(n3.data["files"]["simulation.json"]).decode())
ok(man["source"]["orig"] is None, "without the path of the part on this computer")
ok(src not in json.dumps(n3.data) and T not in json.dumps(n3.data), "nor any other path of the folders it was read from")
ok(json.loads(open(os.path.join(f3, "simulation.json")).read())["source"]["orig"] == os.path.abspath(part_for_sim), "(the folder itself still has it: it is not touched)")
ok(blob(f3) == before_f3, "the analysis folder is not touched")
ok(P.status(n3.id, "geometry") == wp.INCOMPLETE and P.status(n3.id, "setup") == wp.OK, f"the setup comes in ok; the geometry waits for a wire from a Geometry block ({P.status(n3.id, 'geometry')}, {P.status(n3.id, 'setup')})")
ok(P.status(n3.id, "solution") == wp.INCOMPLETE and not any(x.kind in ("part", "assembly") for x in P.nodes.values() if x.title == "Bar test"), f"nothing was computed, and no Part block was made for it ({P.status(n3.id, 'solution')})")
w3 = W.open_cell(n3.id, "setup")
import solid_tab
ok(isinstance(w3, solid_tab.SolidWindow) and w3.geom is not None and abs(w3.geom["volume"] - 10000) < 1e-6, "it opens in the 3D window with the part (volume 10000)")
ok(W.sync_editors() == [], "and opening the imported analysis is not a change")
shell.close_tab(shell.tabs.indexOf(w3))

# a 2D analysis with a mesh and a result in its state: inputs kept, the rest left out
class FakeTab:
    model = object()

    def __init__(self):
        self.st = {"model_json": "{}", "supports": [{"mode": "fixed"}], "loads": [{"f": 1}], "inputs": {"e_E": "200000"}, "mesh": {"nodes": list(range(50000))},
                   "result": {"u": list(range(50000))}, "frames": [1, 2, 3]}

    def export_state(self):
        return dict(self.st)


f2 = os.path.join(src, "Plate.gpf")
sp.create(f2, "fea")
pstore.save(os.path.join(f2, "state.sim"), {"main": FakeTab()})
big = os.path.getsize(os.path.join(f2, "state.sim"))
n2 = W.import_file(f2)
ok(n2 is not None and n2.kind == "fea", "a .gpf folder becomes a 2D Static Structural block")
small = len(wp.unpack_bytes(n2.data["files"]["state.sim"]))
ok(small < big / 3, f"its mesh and result are left out ({small} against {big} bytes)")
ok(P.status(n2.id, "setup") == wp.OK and P.status(n2.id, "geometry") == wp.INCOMPLETE, "the setup is ready; no sketch yet (incomplete)")
ok("no geometry yet" in say().lower(), f"and it says so ({say()[-80:]})")

# not an analysis
os.makedirs(os.path.join(src, "plain"))
ok(W.import_file(os.path.join(src, "plain")) is None and "folder" in say(), f"a folder that is nothing known is refused ({say()[:70]})")
os.makedirs(os.path.join(src, "broken.gpv"))
open(os.path.join(src, "broken.gpv", "simulation.json"), "w").write("{not json")
ok(W.import_file(os.path.join(src, "broken.gpv")) is None and "not a simulation project" in say(), f"a project folder with a broken simulation.json too ({say()[:70]})")
real_sp = wb_analysis.sim_project


def no_sim():
    raise ImportError("no simulation")


wb_analysis.sim_project = no_sim
ok(W.import_file(f3) is None and "add-on" in say(), f"without the simulation add-on it says which add-on is needed ({say()[:70]})")
wb_analysis.sim_project = real_sp

# ------------------------------------------------------------------------------------------------------------------------------------ tool files
import sh_book
import truss_core as tc
wbk = sh_book.Workbook()
wbk.set_input(wbk.sheet_names()[0], 2, 2, "42")
fs = os.path.join(src, "Costs.opsheet")
wbk.save(fs)
fc = write_json(os.path.join(src, "Loop.opctl"), {"format": "openpara-controls", "version": 1, "sections": {}})
fq = write_json(os.path.join(src, "Divider.opcirc"), {"format": "openpara-circuit", "version": 1, "parts": [], "wires": []})
ft = os.path.join(src, "Roof.truss")
tc.save(tc.new_project("Roof"), ft)
got = {}
for kind, path in (("sheets", fs), ("controls", fc), ("circuits", fq), ("truss", ft)):
    nn = W.import_file(path)
    got[kind] = nn
    ok(nn is not None and nn.kind == kind and nn.title == wb_import.stem(path), f"{os.path.basename(path)} becomes a {kind} block")
    ok(P.status(nn.id, "document") == wp.OK, f"{kind}: ok (it has a document)")
ok("project.json" in got["truss"].data["files"], "the Truss Generator's folder is kept as its files")
wsh = W.open_cell(got["sheets"].id, "document")
ok(wsh is not None and wsh.wb.value(wsh.wb.sheet_names()[0], 2, 2) == 42.0, "the imported sheet opens with its content")
ok(W.sync_editors() == [], "and opening it is not a change")
shell.close_tab(shell.tabs.indexOf(wsh))
open(os.path.join(src, "Bad.opsheet"), "w").write("nope")
ok(W.import_file(os.path.join(src, "Bad.opsheet")) is None and "not a sheets document" in say(), f"a sheet file that is not one is refused ({say()[:70]})")
write_json(os.path.join(src, "Other.opcirc"), {"format": "something-else"})
ok(W.import_file(os.path.join(src, "Other.opcirc")) is None, "so is a JSON file of another format")
os.makedirs(os.path.join(src, "NoProject.truss"))
ok(W.import_file(os.path.join(src, "NoProject.truss")) is None and "is a folder, but not" in say(), f"and a .truss folder without project.json ({say()[:60]})")

# ------------------------------------------------------------------------------------------------------------------------------------ another project
other = wp.Project("Other")
oa = other.add_node("part", "Wing", (100.0, 200.0), {"doc": bar_json(5)})
ob = other.add_node("solid", "Wing test", (360.0, 200.0))
other.set_ready(oa.id, "geometry", True)
other.link(oa.id, "geometry", ob.id, "geometry")
other.set_ready(ob.id, "setup", True)
raw_other = other.to_dict()
raw_other["nodes"].append({"id": "n99", "kind": "futurekind", "title": "From the future", "label": "Z", "pos": [0, 0], "cells": {}, "data": {}})
fo = os.path.join(src, "Other.opara")
write_json(fo, raw_other)
labels_before = {n.label for n in P.nodes.values()}
n_nodes, n_links = len(P.nodes), len(P.links)
right = max(n.pos[0] for n in P.nodes.values())
top_before = min(n.pos[1] for n in P.nodes.values())
P.saved_rev = P.rev
first = W.import_file(fo)
ok(first is not None and len(P.nodes) == n_nodes + 2, f"another project adds its blocks ({len(P.nodes) - n_nodes} new)")
new = [n for n in P.nodes.values() if n.title in ("Wing", "Wing test")]
ok(len(new) == 2 and {n.label for n in new}.isdisjoint(labels_before), f"with letters of their own ({[n.label for n in new]})")
ok(len(P.links) == n_links + 1, "and the wire between them")
wing, wtest = [n for n in new if n.title == "Wing"][0], [n for n in new if n.title == "Wing test"][0]
ok(any(k.a == wing.id and k.b == wtest.id for k in P.links), "the wire joins the new blocks (not the old ones)")
ok(P.status(wing.id, "geometry") == wp.OK and P.status(wtest.id, "geometry") == wp.REFRESH, f"the cells keep their state (part ok, analysis says refresh: {P.status(wtest.id, 'geometry')})")
ok(min(n.pos[0] for n in new) > right, "they are put to the right of what was here")
ok(min(n.pos[1] for n in new) == top_before, f"and their top lines up with the top of what was here ({min(n.pos[1] for n in new)} and {top_before})")
ok(P.is_dirty(), "the project is changed")
ok("Left out" in say() and "From the future" in say(), f"the block of a kind this program does not know is left out, and said ({say()[-90:]})")
ok(wing.data["doc"] == other.nodes[oa.id].data["doc"] and wing.data is not other.nodes[oa.id].data, "the data is a copy")
# into an empty project the places stay
P0 = wp.Project("Empty")
W.set_project(P0)
P = W.project
first = W.import_file(fo)
pos = sorted(tuple(n.pos) for n in P.nodes.values())
ok(pos == [(100.0, 200.0), (360.0, 200.0)], f"into an empty project the blocks stay where they were ({pos})")
bad_proj = os.path.join(src, "NotAProject.opara")
open(bad_proj, "w").write("{}")
ok(W.import_file(bad_proj) is None and "not an OpenPara project" in say(), f"a .opara that is not a project is refused ({say()[:70]})")
only_future = write_json(os.path.join(src, "Future.opara"), dict(raw_other, nodes=[raw_other["nodes"][-1]], links=[]))
ok(W.import_file(only_future) is None and "no blocks this program knows" in say(), "and one with only unknown blocks too")

# ------------------------------------------------------------------------------------------------------------------------------------ the dialogs, and what is kept
W.set_project(wp.Project("Mixed"))
P = W.project
qw.QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([gpd, os.path.join(src, "x.txt"), gpa, os.path.join(src, "nothing.gpd")], ""))
MSGS.clear()
made = W.import_dialog()
ok([n.kind for n in made] == ["part", "assembly"], f"the Import dialog imports the files that can be ({[n.kind for n in made]})")
ok(len(MSGS) == 1 and "x.txt" in MSGS[0] and "nothing.gpd" in MSGS[0] and "not a kind of file" in MSGS[0] and "was not found" in MSGS[0], f"and lists the ones that cannot, each with its reason ({MSGS[0][:120] if MSGS else None})")
qw.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: f3)
made = W.import_folder_dialog()
ok([n.kind for n in made] == ["solid"], "Import Folder takes an analysis project folder")
qw.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
MSGS.clear()
ok(W.import_folder_dialog() == [] and MSGS == [], "and cancelling does nothing, and shows no message")

# the saved project holds everything; opening it again computes nothing
fp = os.path.join(T, "imported.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (fp, ""))
ok(W.save(True) and os.path.isfile(fp), "Save writes the project")
W.load(fp)
P = W.project
st = {n.title: [P.status(n.id, k) for k in n.cells] for n in P.nodes.values()}
ok(st["Bar"] == [wp.OK] and st["Frame"] == [wp.OK], f"parts and assemblies come back ok ({st['Bar']}, {st['Frame']})")
ok(st["Bar test"][:2] == [wp.INCOMPLETE, wp.OK] and wp.UPDATE not in st["Bar test"], f"the analysis comes back with its setup, still waiting for a geometry wire, and not computed ({st['Bar test']})")
ok(not P.is_dirty(), "opening is not a change")

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
