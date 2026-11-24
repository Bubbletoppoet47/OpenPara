"""Files from a folder on the computer are dropped on the Workbench canvas and become blocks (no Import source anywhere): a part .gpd a Part block, an assembly .gpa an Assembly block, a
simulation project folder an analysis block with its setup and results ONLY (no Part block is added: it is wired by hand), what is not importable is said.  File > Open of an old simulation
folder, Open Project Folder and a drop on the program window land in the Workbench the same way; File > New, the Add menu and the start page offer no simulation of their own any more.
python test_wb_drop.py"""
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

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication, QMessageBox
MSGS, ASKED = [], []
QMessageBox.question = staticmethod(lambda *a, **k: ASKED.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Yes)
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
import gpd_app
import pm_model as pm
import sim_project as sp
import sk_tools as sk
import wb_canvas as cv
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbd_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)


def bar_json(depth):
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (100, 10))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth)))
    d.rebuild()
    return json.loads(d.to_json())


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    return path


def drop(paths, x=400.0, y=200.0):
    """A real drop event on the canvas, as a file manager makes it."""
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    v = W.view
    pos = QPointF(v.mapFromScene(QPointF(x, y)))
    ev = QDropEvent(pos, Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    v.dropEvent(ev)
    for _ in range(5):
        app.processEvents()
    return ev.isAccepted()


P = W.project
src = os.path.join(T, "src")
os.makedirs(src)
gpd = write_json(os.path.join(src, "Bar.gpd"), bar_json(10))
pa = write_json(os.path.join(src, "pa.gpd"), bar_json(10))
a = am.Assembly()
a.add_component("pa.gpd", fixed=True)
gpa = os.path.join(src, "Frame.gpa")
open(gpa, "w").write(a.to_json())
f3 = os.path.join(src, "Old study.gpv")
sp.create(f3, "solid")
sp.import_source(f3, orig_path=pa)

ok(isinstance(W, wb_tab.WorkbenchTab) and not P.nodes, "the program opened an empty Workbench")
ok(W.view.acceptDrops() and W.view.viewport().acceptDrops(), "the canvas takes drops")

# ---- a drop of several things at once
ok(drop([gpd, gpa, f3], 400.0, 200.0), "the drop is accepted")
kinds = [n.kind for n in sorted(P.nodes.values(), key=lambda n: n.pos[0])]
ok(kinds == ["part", "assembly", "solid"], f"a part, an assembly and a simulation folder made three blocks, left to right ({kinds})")
ok(len(P.nodes) == 3 and not P.links, "and nothing else: no Part block for the simulation, no wire")
nodes = {n.kind: n for n in P.nodes.values()}
xs = sorted(n.pos[0] for n in P.nodes.values())
ok(xs[1] - xs[0] >= cv.BLOCK_W and xs[2] - xs[1] >= cv.BLOCK_W, f"side by side, not on top of each other ({xs})")
ok(abs(xs[0] - 400.0) <= 2 * cv.GRID and abs(P.nodes[nodes["part"].id].pos[1] - 200.0) <= 2 * cv.GRID, "the first at the drop point (to the grid)")
sol = nodes["solid"]
ok(sol.title == "Old study" and "simulation.json" in sol.data["files"], f"the analysis keeps its project files ({sol.title})")
ok(P.incoming(sol.id, "geometry") is None, "its Geometry cell has no wire: it waits for one")
ok("Imported" in W.line.text(), f"and the status line says what happened ({W.line.text()[:60]})")

# ---- what cannot be imported is listed with its reason
n0 = len(P.nodes)
junk = os.path.join(src, "x.txt")
open(junk, "w").write("x")
MSGS.clear()
ok(drop([junk, gpd], 800.0, 600.0), "a drop with something unknown is accepted too")
ok(len(P.nodes) == n0 + 1 and any("x.txt" in m and "not a kind of file" in m for m in MSGS), f"the part still came in, the other is listed with its reason ({MSGS[-1][:70] if MSGS else None})")

# ---- the toolbox still drops kinds
md = QMimeData()
md.setText(cv.MIME + "sheets")
v = W.view
ev = QDropEvent(QPointF(v.mapFromScene(QPointF(100.0, 500.0))), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
n1 = len(P.nodes)
v.dropEvent(ev)
ok(len(P.nodes) == n1 + 1, "a kind dragged from the toolbox still makes its block")

# ---- the program window: nothing makes a simulation on its own
fm = [x for x in shell.menuBar().actions() if x.text() == "&File"][0].menu()
labels = [x.text() for x in fm.actions()]
ok("New Workbench Project" in labels or any("Workbench" in l for l in labels), f"File > New offers the Workbench ({[l for l in labels if l.startswith('New')]})")
ok(not any(l.startswith("New") and any(k in l for k in ("FEA", "CFD", "Thermal", "Parametric")) for l in labels), "but no simulation, no study")
add = [x for x in shell.menuBar().actions() if x.text() == "&Add"]
ok(not add or not any(("FEA" in y.text() or "CFD" in y.text() or "arametric" in y.text()) for y in add[0].menu().actions()), "the Add menu has no simulation either")
ok(not any(any(k in x["text"] for k in ("FEA", "CFD", "Thermal", "Parametric")) for x in shell.start_actions()), "nor has the start page")
ok(not hasattr(shell, "add_sim"), "and the program window has no add_sim")

# ---- File > Open of an old simulation folder: it goes into the Workbench that is open
old = os.path.join(src, "Older.gpv")
sp.create(old, "solid")
sp.import_source(old, orig_path=pa)
n2 = len(P.nodes)
n_tabs = shell.tabs.count()
got = shell.open_project_folder(old)
ok(got is W and len(P.nodes) == n2 + 1 and shell.tabs.count() == n_tabs, "Open Project Folder puts it in the Workbench as a block (no tab of its own)")
ok(shell.tabs.currentWidget() is W, "and shows the Workbench")
got = shell.open_path(os.path.join(src, "Old study.gpv"))
ok(got is W and len(P.nodes) == n2 + 2 and shell.tabs.count() == n_tabs, "File > Open of a folder too")
ok(sum(1 for n in P.nodes.values() if n.kind == "solid") == 3, "three analysis blocks in all")

# ---- a project folder inside a Workbench workspace is opened as it is (it is the editor of a block)
ed = W.open_cell(sol.id, "setup")
ok(ed is not None and shell.tabs.indexOf(ed) >= 0 and getattr(ed, "kind", None) == "solid", "the block's own window opens as a tab (that is what the Workbench does)")
ok(shell.open_path(ed.path) is ed, "and asking for it again shows it")

# ---- no Workbench open: it asks for one
shell.close_tab(shell.tabs.indexOf(ed))
shell.close_tab(shell.tabs.indexOf(W))
ASKED.clear()
ok(shell.workbench_tab(ask=False) is None, "(no Workbench is open now)")
got = shell.open_project_folder(os.path.join(src, "Old study.gpv"))
ok(len(ASKED) == 1 and "Workbench" in ASKED[0], f"opening a simulation folder asks whether to start a Workbench project ({ASKED[:1]})")
ok(isinstance(got, wb_tab.WorkbenchTab) and any(n.kind == "solid" for n in got.project.nodes.values()), "a new Workbench project took it")

print("OK" if not FAILS else f"FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
