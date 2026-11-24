"""Drawings in the Workbench (dev add-ons workbench + drawings) in the real program window: a Drawing block (Component Tools) has a Models cell that takes the Parts and Assemblies wired
into it (nothing else, nothing without a wire), its window does not add models by itself, the views are drawn from the wired blocks, a change in a part says 'refresh' on the cell and
Refresh Project draws the views again (in the open window and in a drawing that is closed), a part that cannot be built is reported and the drawing keeps what it had, unwiring takes the
model and its views out when the drawing is opened again, and the drawing survives saving and opening the project.   python test_wb_drawing.py"""
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
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor", "truss", "controls", "circuits"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("workbench", "drawings"):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
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


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


import gpd_app
import wb_canvas as cv
import wb_example as ex
import wb_project as wp
import wb_tab
import wb_nodes as nodes
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
EXEC = []
QDialog.exec = lambda self: EXEC.append(self) or 0                      # (a dialog that waits for a click would stop the test: this says it was asked for)
P = W.project
import dr_model as M
import dr_panels as PN

bar, _s1 = ex.part_doc(100, 20, 10)
bar2, _s2 = ex.part_doc(150, 20, 10)
frame = ex.frame_asm(100, 20, 20)


def item(n):
    return W.scene.items_by_id[n.id]


def drag(p0, p1, steps=6):
    vp = W.view.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(int(p0.x() + (p1.x() - p0.x()) * i / steps), int(p0.y() + (p1.y() - p0.y()) * i / steps)))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    app.processEvents()


def drawing_of(node):
    """The drawing a block keeps (as a Drawing object)."""
    f = os.path.join(T, "peek.opdraw")
    nodes.adapter_for("drawing").write(node, f)
    with open(f, encoding="utf-8") as fh:
        return M.Drawing.from_json(fh.read())


# ------------------------------------------------------------------------------------------------------------------------------ the kind
sp = wp.spec_of("drawing")
ok(sp is not None and sp.group == "Component Tools" and sp.standalone == ".opdraw", "a Drawing is a Component Tool saved on its own as an .opdraw")
ok([c.key for c in sp.cells] == ["models", "document"], f"it has a Models cell above its document ({[c.key for c in sp.cells]})")
c = sp.cell("models")
ok(c.role == "import" and c.accepts == ("geometry",) and c.many and c.needs_link and not c.optional, "the Models cell takes geometry, any number of wires, and is incomplete without one")
ok(nodes.adapter_for("drawing") is not None and nodes.adapter_for("drawing").available(W)[0], "the Drawings add-on is wired in and available")

# ------------------------------------------------------------------------------------------------------------------------------ blocks and wires
PART = W.add_block("part", 60, 60, title="Bar", data={"doc": bar})
PART2 = W.add_block("part", 60, 360, title="Long bar", data={"doc": bar2})
ASM = W.add_block("assembly", 60, 660, title="Frame", data={"asm": frame})
SOL = W.add_block("solid", 400, 360, title="Bar stress")
DRW = W.add_block("drawing", 400, 60, title="Bar drawing")
DRW2 = W.add_block("drawing", 400, 660, title="Frame drawing")
W.view.fit_all()
app.processEvents()
ok(item(DRW).body_h() == cv.HEAD_H + cv.NAME_H + 2 * cv.CELL_H, "the Drawing block is two cells high")
ok(P.status(DRW.id, "models") == wp.INCOMPLETE and P.status(DRW.id, "document") == wp.INCOMPLETE, "with no wire the Models cell is incomplete (nothing to draw), and so is the document")
ok(item(PART).port_pos("geometry", "out") is not None and item(DRW).port_pos("models", "in") is not None, "the geometry of a part has an output dot, the Models cell an input dot")
why = lambda a, ac, b, bc: P.why_not_link(a.id, ac, b.id, bc)
ok(why(PART, "geometry", DRW, "models") is None and why(ASM, "geometry", DRW, "models") is None, "a part and an assembly can be wired into the Models cell")
ok(why(SOL, "geometry", DRW, "models") is not None, f"the geometry cell of an analysis gives nothing to wire ({why(SOL, 'geometry', DRW, 'models')})")
ok(why(PART, "geometry", DRW, "document") is not None, "and the document cell takes nothing")
p_out = W.view.mapFromScene(item(PART).port_pos("geometry", "out"))
p_in = W.view.mapFromScene(item(DRW).port_pos("models", "in") + QPointF(40, 0))
drag(p_out, p_in)
ks = P.incoming_all(DRW.id, "models")
ok(len(ks) == 1 and ks[0].a == PART.id and P.link_type(ks[0]) == "geometry", f"drawing the wire with the mouse makes the link ({len(ks)})")
P.link(ASM.id, "geometry", DRW2.id, "models")
ok(P.status(DRW.id, "models") in (wp.REFRESH, wp.OK), f"the Models cell is no longer incomplete once the part is wired in ({P.status(DRW.id, 'models')})")

# ------------------------------------------------------------------------------------------------------------------------------ the Drawing window of the block
EXEC.clear()
w = W.open_cell(DRW.id, "document")
app.processEvents()
ok(w is not None and shell.tabs.indexOf(w) >= 0 and w.models_from_wires, "double-clicking the block opens its drawing in a tab of the program")
ok(any(isinstance(d, PN.NewDrawingDialog) for d in EXEC), "a new drawing asks for its sheet (the standard sizes)")
ok([m["name"] for m in w.d.models] == ["Bar"] and w.d.models[0]["src"] == PART.id, "the part wired into the block is its model")
w.open_command("model")
ok(w.model_panel.add_btn.isHidden(), "the Model View panel does not offer to add a model from a file: the wires say what the models are")
ok(w.model_panel.models.count() == 1, "it lists the wired part")
w.model_panel.pick_orientation("Front")
w.canvas._follow((140.0, 120.0))
w.canvas._drop()
w.finish_command()
v1 = w.d.views[0]
ok(len(w.d.views) == 1 and near(w.canvas.r.view_box(v1)[2] - w.canvas.r.view_box(v1)[0], 100.0), "a Front view of the bar is on the sheet, 100 mm long")
W.sync_editors()
ok(bool(DRW.data.get("file")) and P.status(DRW.id, "document") == wp.OK, "the project took the drawing when the block was left (the document cell is ok)")
d1 = drawing_of(DRW)
ok([m["src"] for m in d1.models] == [PART.id] and len(d1.views) == 1 and d1.models[0]["hash"] == M.model_hash(bar), "what it keeps is the drawing with its copy of the part and the view")

# ------------------------------------------------------------------------------------------------------------------------------ a change in the part
PART.data["doc"] = bar2
P.touch(PART.id, "geometry")
ok(P.status(DRW.id, "models") == wp.REFRESH, f"the part changed: the Models cell says refresh ({P.status(DRW.id, 'models')})")
d_, f_ = W.refresh_project()
ok(not f_ and P.status(DRW.id, "models") == wp.OK, f"Refresh Project takes it ({P.status(DRW.id, 'models')}, failed {f_})")
b = w.canvas.r.view_box(w.d.views[0])
ok(near(b[2] - b[0], 150.0) and len(w.d.views) == 1, "the open drawing shows the new part: the view is 150 mm long (the same view, drawn again)")
ok(w.d.models[0]["hash"] == M.model_hash(bar2), "and its copy of the part is the new one")
# the window is closed: Refresh works on the file
W.sync_editors()
ok(shell.close_tab(shell.tabs.indexOf(w)) and W.editor_of(DRW.id) is None, "the drawing's tab is closed")
PART.data["doc"] = bar
P.touch(PART.id, "geometry")
d_, f_ = W.refresh_project()
d2 = drawing_of(DRW)
bb = d2.bbox(d2.views[0])
ok(not f_ and near(bb[2] - bb[0], 100.0) and d2.models[0]["hash"] == M.model_hash(bar) and len(d2.views) == 1,
   f"Refresh with the drawing closed draws the view again in the file: 100 mm long ({bb[2] - bb[0]:.1f}), failed {f_}")
ok(P.status(DRW.id, "models") == wp.OK and P.cell(DRW.id, "document")["stamp"] >= 2, "the cell is ok and the document cell changed")

# ------------------------------------------------------------------------------------------------------------------------------ a part that cannot be built
PART.data["doc"] = {"bad": "part"}
P.touch(PART.id, "geometry")
d_, f_ = W.refresh_project()
ok(len(f_) == 1 and P.status(DRW.id, "models") == wp.FAILED, f"a part that cannot be built: the cell says failed ({P.status(DRW.id, 'models')})")
ok("could not be built" in (P.cell(DRW.id, "models")["failed"] or ""), f"with the reason ({(P.cell(DRW.id, 'models')['failed'] or '')[:80]})")
d3 = drawing_of(DRW)
bb = d3.bbox(d3.views[0])
ok(d3.models[0]["hash"] == M.model_hash(bar) and near(bb[2] - bb[0], 100.0), "and the drawing keeps the part and the view it had")
PART.data["doc"] = bar
P.touch(PART.id, "geometry")
d_, f_ = W.refresh_project()
ok(not f_ and P.status(DRW.id, "models") == wp.OK, "once the part is right again the cell is ok")

# ------------------------------------------------------------------------------------------------------------------------------ an assembly in a drawing
w2 = W.open_cell(DRW2.id, "document")
app.processEvents()
ok(w2 is not None and [m["kind"] for m in w2.d.models] == ["assembly"], "an assembly wired in is a model too")
w2.open_command("model")
w2.model_panel.pick_orientation("Top")
w2.canvas._follow((120.0, 100.0))
w2.canvas._drop()
w2.finish_command()
bx = w2.canvas.r.view_box(w2.d.views[0])
ok(near(bx[2] - bx[0], 100.0, 1e-6) and near(bx[3] - bx[1], 20.0, 1e-6), "its Top view is 100 x 20 mm")
pdf = os.path.join(T, "frame.pdf")
ok(w2.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 500, "and the drawing of the block exports to PDF")

# ------------------------------------------------------------------------------------------------------------------------------ unwiring
W.sync_editors()
ok(shell.close_tab(shell.tabs.indexOf(w2)), "(the second drawing is closed)")
for k in list(P.incoming_all(DRW.id, "models")):
    P.unlink(k)
ok(P.status(DRW.id, "models") == wp.INCOMPLETE, "the wire is taken away: the Models cell is incomplete again")
w = W.open_cell(DRW.id, "document")
app.processEvents()
ok(w is not None and not w.d.models and not w.d.views, "the drawing opened again has no model and no view: they went with the wire")
ok("removed Bar" in W.line.text() or any("removed Bar" in n for n in getattr(W, "notes", [])), f"and the project line said so ({W.line.text()[:80]})")
W.sync_editors()
shell.close_tab(shell.tabs.indexOf(w))
P.link(PART.id, "geometry", DRW.id, "models")

# ------------------------------------------------------------------------------------------------------------------------------ saving and opening
f1 = os.path.join(T, "drawings.opara")
import PyQt6.QtWidgets as qw
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
ok(any(l["from"] == PART.id and l["to"] == DRW.id and l["to_cell"] == "models" for l in raw["links"]), "the wire is in the file")
W.load(f1)
P = W.project
DRW = P.nodes[DRW.id]
ok(P.incoming_all(DRW.id, "models") != [] and DRW.kind == "drawing", "opened again: the block and its wire are there")
w = W.open_cell(DRW.id, "document")
app.processEvents()
ok(w is not None and [m["name"] for m in w.d.models] == ["Bar"], "its window opens with the wired part as its model again")
alone = shell.new_addon_tab("drawing", None)
alone.open_command("model")
ok(alone is not None and alone.models_from_wires is False and not alone.model_panel.add_btn.isHidden(), "a Drawing tab of its own (File > New) is not tied to wires: it adds its models from files")

print()
if FAILS:
    print(f"FAILURES: {len(FAILS)}")
    for x in FAILS:
        print("  " + x)
    sys.exit(1)
print("ALL OK")
