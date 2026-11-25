"""The 3D Fluid Flow block of the Workbench in the real program window: it is in the toolbox with its picture, a Part wired to it (Refresh copies the part into the analysis), the
window that opens from the Setup cell, the flow solved from the project (Update), the part edited (the analysis says refresh and update), saving the project and opening it again
(nothing is computed, nothing is lost), the block saved on its own as a .gpw folder that opens in the program, an Assembly (refused with its reason, the setup stays incomplete)
and that the block is offered to Coupled Physics (and not to a parametric study yet).   python test_wb_fluid3d.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(560, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "cfd3d"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

import numpy as np
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
import gpd_app
import pm_model as pm
import sk_tools as sk
import wb_analysis
import wb_kit
import wb_nodes
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbf_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw


def cube_json(side):
    """A cube (a square on the top plane extruded by the parameter S): 10 mm by default."""
    d = pm.Document()
    d.params = {"S": str(side)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (10, 10))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=10.0)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="S"))
    d.rebuild()
    d.material = {"name": "Aluminum 6061", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}
    return json.loads(d.to_json())


def stamp(p, nid, key):
    return p.cell(nid, key)["stamp"]


# ------------------------------------------------------------------------------------------------------------------------------------ the block exists
ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
ok("fluid3d" in addons.tab_kinds(), "the add-on gives the tab kind 'fluid3d'")
ok(wb_nodes.adapter_for("fluid3d") is not None and wb_nodes.availability(W, "fluid3d")[0], f"the kind 'fluid3d' has an adapter and its add-on is there ({wb_nodes.availability(W, 'fluid3d')})")
ok("fluid3d" not in wb_nodes.check_kinds(), f"the block is wired (not wired: {wb_nodes.check_kinds()})")
spec = wp.spec_of("fluid3d")
ok(spec.label == "3D Fluid Flow" and spec.group == "Analysis Systems", f"in the group Analysis Systems as '{spec.label}'")
ok([c.key for c in spec.cells] == ["geometry", "setup", "solution", "results"], f"with the cells of an analysis ({[c.key for c in spec.cells]})")
ok(spec.cell("geometry").needs_link and "geometry" in spec.cell("geometry").accepts, "its Geometry cell comes only from a wire")
ok("coupling" in spec.cell("setup").provides and "analysis" not in spec.cell("setup").provides, f"its Setup is offered to Coupled Physics but not to a parametric study yet ({spec.cell('setup').provides})")
ok(wb_kit.KIND["fluid3d"] == "wb_fluid3d" and "fluid3d" in wb_kit.SOLID_KINDS and wb_kit.cell_key("fluid3d", "geometry") == "tab_part", "the kit knows its picture and that its geometry is a solid")
import wb_icons
ok(wb_icons.KIND_GLYPH.get("fluid3d") is not None, "and the plain drawing of the old pictures has a glyph for it")
if wb_kit.ready():
    ok(not wb_kit.pixmap("wb_fluid3d", 48).isNull(), "the picture draws")
from PyQt6.QtGui import QImage, QPainter
img = QImage(48, 48, QImage.Format.Format_ARGB32)
img.fill(0)
pp = QPainter(img)
wb_icons.KIND_GLYPH["fluid3d"](pp)
pp.end()
ok(any(img.pixel(x, y) >> 24 for x in range(48) for y in range(48)), "the old glyph paints something")
tb = W.toolbox if hasattr(W, "toolbox") else None
ok(tb is not None and tb.item_of("fluid3d") is not None, "the toolbox lists the block")

# ------------------------------------------------------------------------------------------------------------------------------------ Part -> 3D Fluid Flow
P = W.project
nCube = W.add_block("part", 40, 60, title="Cube", data={"doc": cube_json(10)})
nF = W.add_block("fluid3d", 400, 60, title="Cube in air")
ok(nF.kind == "fluid3d" and P.status(nF.id, "geometry") == wp.INCOMPLETE, "the new block has no geometry yet")
W.scene.make_link(nCube.id, "geometry", nF.id, "geometry")
ok(P.status(nF.id, "geometry") == wp.REFRESH, f"a wire to the part: the analysis says refresh ({P.status(nF.id, 'geometry')})")
done, failed = W.refresh_project()
ok(done == 1 and not failed, f"Refresh Project did it ({failed})")
files = nF.data["files"]
man = json.loads(files["simulation.json"]["text"])
ok(man["format"] == "openpara-sim-fluid3d" and man["source"]["orig"] is None, f"the project folder is of the kind fluid3d, no path of this computer in it ({man['format']})")
ok(any(k.startswith("source/") and k.endswith(".gpd") for k in files), "with its own copy of the part")
ok(P.status(nF.id, "setup") == wp.INCOMPLETE, f"the setup waits until the window has been opened ({P.status(nF.id, 'setup')})")

w = W.open_cell(nF.id, "setup")
import cfd3d_tab
ok(isinstance(w, cfd3d_tab.FluidWindow) and shell.tabs.indexOf(w) >= 0, "double-click opens the 3D Fluid Flow window in a tab")
ok(shell.tabs.tabText(shell.tabs.indexOf(w)).startswith(f"{nF.label} Cube in air"), f"named after the block ({shell.tabs.tabText(shell.tabs.indexOf(w))})")
ok(w.geom is not None and abs(w.geom["volume"] - 1000) < 1e-6, "it shows the cube that was copied in")
ok(w.setup["flow"]["speed"] == 0.05 and w.setup["fluid"]["name"].lower().startswith("air"), f"with the defaults: air at {w.setup['flow']['speed']} m/s ({w.setup['fluid']['name']})")
ok(W.sync_editors() == [] or P.status(nF.id, "setup") == wp.OK, "opening it is not a change (or only its first state)")
w.e_speed.setText("0.0606")
w.set_size("2.5")
w.inputs_changed()
ch = W.sync_editors()
ok(nF.id in ch or stamp(P, nF.id, "setup") > 0, f"the project reads the setup back ({ch})")
ok(P.status(nF.id, "setup") == wp.OK, f"the setup is ok ({P.status(nF.id, 'setup')})")
ok(P.status(nF.id, "solution") == wp.UPDATE, f"and the solution says update ({P.status(nF.id, 'solution')})")
st_text = nF.data["files"]["state.sim"]["text"]
ok('"flow"' in st_text and "0.0606" in st_text, "the project file holds the flow")
ok("Reynolds number about 40" in w.re_lbl.text(), f"the window says Reynolds number about 40: '{w.re_lbl.text()}'")

done, failed = W.update_project()
ok(done == 1 and not failed, f"Update Project solved ({failed})")
ok(w.result is not None and w.result["summary"]["drag"] > 0, f"a drag on the cube ({w.result['summary']['drag'] if w.result else None} N)")
cd = w.result["summary"].get("Cd")
ok(cd is not None and 0.8 < cd < 4.0, f"and a drag coefficient of a cube at Reynolds 40 in a sensible range ({cd})")
af1 = w.result["summary"]["area_front_m2"]
ok(abs(af1 - 100e-6) < 0.5e-6, f"seen from the flow the cube is 100 mm2 ({af1 * 1e6:.3f})")
ok(all(P.status(nF.id, k) == wp.OK for k in ("geometry", "setup", "solution", "results")), f"every cell is ok ({P.statuses(nF.id)})")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")
drag1 = w.result["summary"]["drag"]

# the part is edited: the analysis follows
ped = W.open_cell(nCube.id, "geometry")
ped.doc.params["S"] = "12"
ped.update_all()
W.sync_editors()
ok(P.status(nF.id, "geometry") == wp.REFRESH and P.status(nF.id, "solution") == wp.UPDATE, f"the analysis says refresh and update ({P.statuses(nF.id)})")
done, failed = W.update_project()
ok(done == 2 and not failed, f"Update refreshed, then solved ({failed})")
w2 = W.editor_of(nF.id)
ok(w2 is not None and w2 is not w and w2.result is not None, "the analysis is open again in a new tab with a result")
ok(abs(w2.geom["volume"] - 1200) < 1e-6, f"on the new part (10 x 10 x 12 mm: volume {w2.geom['volume']:.0f})")
ok(abs(w2.setup["flow"]["speed"] - 0.0606) < 1e-12, "the speed followed")
drag2 = w2.result["summary"]["drag"]
af2 = w2.result["summary"]["area_front_m2"]
ok(abs(af2 - 120e-6) < 0.6e-6, f"the new part reached the solver: seen from the flow it is {af2 * 1e6:.3f} mm2 (a drag of {drag2:.3e} N, it was {drag1:.3e} N)")
ok(drag2 > 0 and abs(drag2 - drag1) > 1e-12, "and the answer is a new one")
ok(sum(isinstance(shell.tabs.widget(i), cfd3d_tab.FluidWindow) for i in range(shell.tabs.count())) == 1, "there is one fluid tab")

# saving the project and opening it: nothing computed, nothing lost
f1 = os.path.join(T, "cube.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
raw = open(f1, encoding="utf-8").read()
ok("opara_wb" not in raw and T not in raw, "no temporary folder, no path of this computer in the file")
ok(len(raw) < 400000, f"and it is small ({len(raw)} bytes): no mesh, no result")
shell.close_tab(shell.tabs.indexOf(W))
ok(not any(isinstance(shell.tabs.widget(i), cfd3d_tab.FluidWindow) for i in range(shell.tabs.count())), "closing the workbench closed the analysis tab too")
W3 = shell.open_path(f1)
p3 = W3.project
nF3 = [n for n in p3.nodes.values() if n.kind == "fluid3d"][0]
ok(shell.tabs.count() == 1, "the project opens with no editor")
ok(p3.statuses(nF3.id) == {"geometry": wp.OK, "setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"geometry and setup are ok, the solution wants an update ({p3.statuses(nF3.id)})")
done, failed = W3.update_project()
ok(done == 1 and not failed, f"Update Project computes it again ({failed})")
w3 = W3.editor_of(nF3.id)
ok(w3.result is not None and abs(w3.result["summary"]["drag"] - drag2) <= 1e-6 * abs(drag2), f"the same answer from the saved project ({w3.result['summary']['drag']:.6e} against {drag2:.6e})")

# the analysis tab is closed: the result is gone, the solution says so
ok(shell.close_tab(shell.tabs.indexOf(w3)), "the analysis tab is closed")
W3.sync_editors()
ok(p3.status(nF3.id, "solution") == wp.UPDATE and p3.status(nF3.id, "setup") == wp.OK, f"the solution says update again, the setup is still ok ({p3.statuses(nF3.id)})")

# saved on its own
out = os.path.join(T, "out")
os.makedirs(out)
pdir = W3.export_node(nF3.id, out)
ok(pdir and pdir.endswith(".gpw") and os.path.isdir(pdir), f"the analysis is saved on its own as a project folder ({os.path.basename(pdir or '')})")
import sim_project as sp
ok(sp.kind_of_folder(pdir) == "fluid3d" and sp.source_file(pdir) and os.path.isfile(sp.source_file(pdir)), "which has its own copy of the part")
ok(sp.EXT["fluid3d"] not in [v for k, v in sp.EXT.items() if k != "fluid3d"], f"and an ending of its own ({sp.EXT['fluid3d']} against {sorted(v for k, v in sp.EXT.items() if k != 'fluid3d')})")
w4 = cfd3d_tab.FluidWindow.open_project(None, pdir, threaded=False)
ok(abs(w4.setup["flow"]["speed"] - 0.0606) < 1e-12 and w4.geom is not None, "it opens in the program on its own with the setup")
ok(W3.export_node(nF3.id, out) != pdir, "saving again does not overwrite")
w4.close()

# the analysis folder is imported back as a block
import wb_import
res = wb_import.import_analysis(W3, pdir)
nImp = res[0][0]
ok(nImp.kind == "fluid3d" and p3.status(nImp.id, "setup") == wp.OK, f"importing the folder gives a 3D Fluid Flow block with its setup ({nImp.kind}, {p3.status(nImp.id, 'setup')})")

# ------------------------------------------------------------------------------------------------------------------------------------ Assembly: refused with its reason
nAsm = W3.add_block("assembly", 40, 300, title="Pair")
sw = W3.open_cell(nAsm.id, "geometry")
import wb_parts
wb_parts.choose_sources = lambda tab, items, parent=None: ("project", [i for i in items if i["name"] == "Cube"]) if any(i["name"] == "Cube" for i in items) else ("browse", None)
sw.insert_dialog()
ok(len(sw.asm.components) == 1 and am.is_embedded(sw.asm.components[0]["path"]), "an assembly with a copy of the cube in it")
W3.sync_editors()
nF4 = W3.add_block("fluid3d", 400, 300, title="Pair in air")
W3.scene.make_link(nAsm.id, "geometry", nF4.id, "geometry")
done, failed = W3.refresh_project(only={nF4.id})
ok(done == 1 and not failed, f"refreshed from the assembly ({failed})")
wa = W3.open_cell(nF4.id, "setup")
ok(isinstance(wa, cfd3d_tab.FluidWindow) and wa.geom is not None, "the window opens on the assembly")
why = wa.ready()
ok(why and "single part" in why, f"and says that it takes one part: '{why}'")
W3.sync_editors()
ok(p3.status(nF4.id, "setup") != wp.OK, f"the setup cell is not ok ({p3.status(nF4.id, 'setup')})")

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
for f_ in FAILS:
    print("  FAIL:", f_)
sys.exit(1 if FAILS else 0)
