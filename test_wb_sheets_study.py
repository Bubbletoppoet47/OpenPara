"""Parametric Study results -> a Sheets block (Workbench, dev add-ons workbench + sheets) in the real program window: the Results cell of a study gives "study", the Sheets block has a
Study Results input cell (any number of wires, optional), only a study wired into it can be imported in the Sheets window of that block (nothing from anywhere else, no Browse),
the imported table remembers which study it came from, the cell says refresh when the study ran again and Update Project reads the table again (in the open window and in a document
that is closed), the link survives saving and opening the project, and a Sheets tab of its own is as it was.   python test_wb_sheets_study.py"""
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
for n in ("workbench", "sheets"):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton
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


import gpd_app
import wb_canvas as cv
import wb_project as wp
import wb_tab
import sh_book
import sh_dialogs
import sh_study
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
EXEC = []
QDialog.exec = lambda self: EXEC.append(self) or 0                      # (a dialog that waits for a click would stop the test: this says it was asked for)
P = W.project


def write_study(project, sub, n, name="Study 1"):
    """A study as the parametric add-on saves it: n cases of one changed input (t) and two outputs."""
    root = os.path.join(project, "study", "studies", sub) if sub else os.path.join(project, "study")
    os.makedirs(root, exist_ok=True)
    outs = [["smax", "Max stress (psi)"], ["d", "Defl (in)"]]
    cases = [{"label": i + 1, "values": {"t": f"{0.05 + 0.01 * i:.12g}"}, "status": "ok", "outputs": {"smax": 1000.0 + 12.5 * i, "d": 0.1 * i}} for i in range(n)]
    j = {"format": "openpara-study", "version": 1, "checked": ["t"], "rows": [{}], "outputs": [o[0] for o in outs], "exit_conds": [], "cases": cases,
         "run_meta": {"params": [["t", "Thickness (in)"]], "outputs": outs, "unit": None}}
    with open(os.path.join(root, "study.json"), "w", encoding="utf-8") as f:
        json.dump(j, f)
    idx = os.path.join(project, "study", "index.json")
    cur = json.load(open(idx))["studies"] if os.path.isfile(idx) else []
    cur = [x for x in cur if x["sub"] != sub] + [{"name": name, "sub": sub}]
    with open(idx, "w", encoding="utf-8") as f:
        json.dump({"studies": cur}, f)


def put_study(node, n, extra=False):
    """The block `node` keeps a study of n cases (as it would after its window was used)."""
    d = os.path.join(T, f"src_{node.id}")
    shutil.rmtree(d, ignore_errors=True)
    write_study(d, "", n)
    if extra:
        write_study(d, "mesh2", 3, "Finer mesh")
    node.data["files"] = wp.pack_folder(d)
    P.changed()


def item(n):
    return W.scene.items_by_id[n.id]


def drag(p0, p1, steps=6):
    vp = W.view.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, QPoint(int(p0.x() + (p1.x() - p0.x()) * i / steps), int(p0.y() + (p1.y() - p0.y()) * i / steps)))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    app.processEvents()


# ------------------------------------------------------------------------------------------------------------------------------ the kinds
sp = wp.spec_of("sheets")
ok([c.key for c in sp.cells] == ["studies", "document"], f"a Sheets block has the Study Results cell above its document ({[c.key for c in sp.cells]})")
c = sp.cell("studies")
ok(c.role == "import" and c.accepts == ("study",) and c.many and c.optional and not c.needs_link, "the cell takes the kind 'study', any number of wires, and none are needed")
ok(wp.spec_of("study").cell("results").provides == ("study",), "the Results cell of a Parametric Study gives 'study'")
ok(wp.spec_of("study").cell("solution").provides == () and wp.spec_of("study").cell("setup").provides == (), "and only that cell of a study gives anything")
ok(sp.standalone == ".opsheet" and wp.KINDS["sheets"].group == "Component Tools", "a Sheets block is still saved as an .opsheet and is a Component Tool")

# ------------------------------------------------------------------------------------------------------------------------------ blocks
SOL = W.add_block("solid", 60, 60, title="Bar stress")
STU = W.add_block("study", 360, 60, title="Bar study")
STU2 = W.add_block("study", 360, 400, title="Other study")
SHT = W.add_block("sheets", 700, 60, title="Results table")
SH0 = W.add_block("sheets", 700, 400, title="Plain table")
W.view.fit_all()
app.processEvents()
ok(item(SHT).body_h() == cv.HEAD_H + cv.NAME_H + 2 * cv.CELL_H, "the Sheets block is two cells high now")
ok(P.status(SHT.id, "studies") == wp.OK and P.status(SH0.id, "studies") == wp.OK, "with no study wired the input cell is fine: a spreadsheet needs none")
ok(P.status(SHT.id, "document") == wp.INCOMPLETE, "and the document cell is as before: incomplete until something is made in it")
ok(item(STU).port_pos("results", "out") is not None and item(SHT).port_pos("studies", "in") is not None, "the Results cell of a study has an output dot, the Study Results cell an input dot")

# ------------------------------------------------------------------------------------------------------------------------------ what can be wired
why = lambda a, ac, b, bc: P.why_not_link(a.id, ac, b.id, bc)
ok(why(STU, "results", SHT, "studies") is None, "Results of a study -> Study Results of Sheets: allowed")
ok("does not give" in (why(STU, "solution", SHT, "studies") or ""), f"the other cells of a study give nothing ({why(STU, 'solution', SHT, 'studies')})")
ok("gives analysis" in (why(SOL, "setup", SHT, "studies") or "") and "takes study" in (why(SOL, "setup", SHT, "studies") or ""), f"an analysis cannot be wired into it ({why(SOL, 'setup', SHT, 'studies')})")
ok("does not take" in (why(STU, "results", SHT, "document") or ""), f"and the document cell of Sheets takes nothing ({why(STU, 'results', SHT, 'document')})")
ok(why(STU, "results", SOL, "geometry") is not None, "a study does not feed an analysis")
# with the mouse: drag from the output dot of the Results cell to the Study Results cell
p_out = W.view.mapFromScene(item(STU).port_pos("results", "out"))
p_in = W.view.mapFromScene(item(SHT).port_pos("studies", "in") + QPointF(40, 0))
drag(p_out, p_in)
ks = P.incoming_all(SHT.id, "studies")
ok(len(ks) == 1 and ks[0].a == STU.id and ks[0].a_cell == "results" and P.link_type(ks[0]) == "study", f"drawing the wire with the mouse makes the link ({len(ks)} wire, type {P.link_type(ks[0]) if ks else ''})")
ok(len(W.scene.link_items) == 1, "and the canvas shows it")
ok("already" in (why(STU, "results", SHT, "studies") or ""), f"the same wire twice is refused ({why(STU, 'results', SHT, 'studies')})")
ok(why(STU2, "results", SHT, "studies") is None, "a second study may be wired in too (the cell takes any number)")
# a Sheets block with no wire is as before; a wire is refused from a wrong cell with a reason on the status line
before = len(P.links)
W.scene.make_link(SOL.id, "setup", SHT.id, "studies")
ok(len(P.links) == before and "takes study" in W.line.text(), f"a wire that does not fit is not made, and the line says why ({W.line.text()[:80]})")

# ------------------------------------------------------------------------------------------------------------------------------ the states of the cell
P.link(SOL.id, "setup", STU.id, "setup")
P.set_ready(SOL.id, "setup")
P.mark_refreshed(STU.id, "setup")
P.mark_updated(STU.id, "solution")
ok(P.status(STU.id, "results") == wp.OK, "the study has run: its Results cell is ok")
ok(P.status(SHT.id, "studies") == wp.REFRESH, f"the Sheets block has not taken the results yet: refresh ({P.status(SHT.id, 'studies')})")
put_study(STU, 4)
d, f = W.refresh_project()
ok(not f and P.status(SHT.id, "studies") == wp.OK, f"Refresh Project takes them: ok ({P.status(SHT.id, 'studies')}, failed {f})")
s0 = P.cell(SHT.id, "studies")["stamp"]
P.mark_updated(STU.id, "solution")                                        # the study ran again
ok(P.status(SHT.id, "studies") == wp.REFRESH, "the study ran again: the cell says refresh")
d, f = W.refresh_project()
ok(not f and P.status(SHT.id, "studies") == wp.OK and P.cell(SHT.id, "studies")["stamp"] > s0, "and Refresh Project takes the new results")
ok(P.status(SH0.id, "studies") == wp.OK, "a Sheets block with no wire is not touched by any of it")
# the second study wired in has not run: the cell cannot be ok
k2 = P.link(STU2.id, "results", SHT.id, "studies")
ok(P.status(SHT.id, "studies") == wp.INCOMPLETE, f"a wired study that has not run yet makes the cell incomplete ({P.status(SHT.id, 'studies')})")
P.unlink(k2)
ok(P.status(SHT.id, "studies") == wp.OK, "(and not any more once that wire is gone)")

# ------------------------------------------------------------------------------------------------------------------------------ the Sheets window of the block
put_study(STU, 4, extra=True)
put_study(STU2, 2)                                                        # a study that is NOT wired into the block
w = W.open_cell(SHT.id, "document")
ok(w is not None and shell.tabs.indexOf(w) >= 0 and w.study_source is not None, "the block's Sheets tab knows where its studies come from")
pr = w.open_study_projects()
ok([n for n, _p in pr] == ["Bar study"], f"the studies it can import are the wired ones, by the name of their block ({[n for n, _p in pr]})")
ok(os.path.isdir(pr[0][1]) and pr[0][1].startswith(W.workspace), "each is a copy in the project's workspace (the study window's own folder is not used)")
ok(not any("Other" in n for n, _p in pr), "the study that is not wired is not offered")
found = [(n, p) for n, p in pr if sh_study.studies(p)]
dlg = sh_dialogs.StudyImportDialog(found, w, browse=False)
ok(not any(b.text().startswith("Browse") for b in dlg.findChildren(QPushButton)), "the window to import has no Browse: nothing can be imported from anywhere else")
ok(dlg.project.count() == 1 and dlg.study.count() == 2 and "wired" in dlg.findChildren(type(dlg.msg))[0].text(), f"it lists the wired study and its two studies ({dlg.study.count()})")
dlg2 = sh_dialogs.StudyImportDialog(found, w)
ok(any(b.text().startswith("Browse") for b in dlg2.findChildren(QPushButton)), "(the window of a Sheets tab of its own still has Browse)")

# a folder that is not a wired study is refused
foreign = os.path.join(T, "foreign")
write_study(foreign, "", 3)
names0 = list(w.wb.sheet_names())
EXEC.clear()
r = w.study_import(choice=(foreign, "", True))
ok(r is None and list(w.wb.sheet_names()) == names0, "a study from another folder cannot be imported into the block")
ok("wired into this block" in w.status.text(), f"and the window says that only a wired study can be ({w.status.text()[:70]})")
link = w.study_import(choice=(pr[0][1], "", True))
ok(link is not None and link.get("wb") == STU.id, f"a wired study is imported, and the table remembers which block it came from ({link.get('wb') if link else None})")
ok(link["name"] == "Bar study - Study 1" and link["rows"] == 4 and link["cols"] == 5, f"named after the block ({link['name']}, {link['rows']} rows)")
sheet = w.grid.sheet                                                      # (the sheet of the first study)
ok(w.wb.value(sheet, 1, 2) == "Thickness (in)" and abs(w.wb.value(sheet, 3, 4) - 1012.5) < 1e-9, "its numbers are on the sheet")
link2 = w.study_import(choice=(pr[0][1], "mesh2", True))
ok(link2 is not None and link2["name"] == "Bar study - Finer mesh" and link2["rows"] == 3, f"any study of the wired block can be imported ({link2['name'] if link2 else None})")

# nothing wired: it says why, and asks for no window
W.sync_editors()
k = P.incoming_all(SHT.id, "studies")[0]
P.unlink(k)
EXEC.clear()
r = w.study_import()
ok(r is None and not EXEC, "with no study wired the Sheets window shows no import window")
ok("wire the Results cell" in w.status.text(), f"and says to wire the Results cell of a study into this block ({w.status.text()[:60]})")
ok(w.open_study_projects() == [], "and offers no study")
P.link(STU.id, "results", SHT.id, "studies")

# ------------------------------------------------------------------------------------------------------------------------------ Update Project reads the tables again
put_study(STU, 6, extra=True)
P.mark_updated(STU.id, "solution")
ok(P.status(SHT.id, "studies") == wp.REFRESH, "the study ran again with more points: the cell says refresh")
d, f = W.update_project(only={SHT.id})
ok(not f and P.status(SHT.id, "studies") == wp.OK, f"Update takes it ({f})")
ls = [x for s in w.wb.sheets for x in s.links]
ok(sorted(x["rows"] for x in ls) == [3, 6], f"the table in the open window has the 6 new rows, the other study its 3 ({sorted(x['rows'] for x in ls)})")
ok(isinstance(w.wb.value(sheet, 7, 4), float) and abs(w.wb.value(sheet, 7, 4) - 1062.5) < 1e-9, f"the last row is on the sheet ({w.wb.value(sheet, 7, 4)})")

# the document is closed: Update reads the file
W.sync_editors()
ok(shell.close_tab(shell.tabs.indexOf(w)) and W.editor_of(SHT.id) is None, "the Sheets tab is closed")
put_study(STU, 3, extra=True)
P.mark_updated(STU.id, "solution")
d, f = W.update_project(only={SHT.id})
ok(not f and P.status(SHT.id, "studies") == wp.OK, f"Update with the document closed ({f})")
tmp = os.path.join(T, "peek")
os.makedirs(tmp, exist_ok=True)
wp.unpack_file(SHT.data["file"], tmp, "peek.opsheet")
peek = sh_book.Workbook.load(os.path.join(tmp, "peek.opsheet"))
rows = sorted(x["rows"] for s in peek.sheets for x in s.links)
ok(rows == [3, 3], f"the document in the project has the 3 rows now ({rows})")
ok(all(x.get("wb") == STU.id for s in peek.sheets for x in s.links), "and still knows which block its tables came from")
ok(P.cell(SHT.id, "document")["stamp"] >= 2, "the document cell changed")

# ------------------------------------------------------------------------------------------------------------------------------ saving and opening
f1 = os.path.join(T, "study_sheets.opara")
import PyQt6.QtWidgets as qw
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
ok(any(l["from"] == STU.id and l["from_cell"] == "results" and l["to"] == SHT.id and l["to_cell"] == "studies" for l in raw["links"]), "the wire is in the file")
W.load(f1)
P = W.project
SHT = P.nodes[SHT.id]
ok(P.incoming_all(SHT.id, "studies") != [] and P.status(SHT.id, "document") == wp.OK, "opened again: the wire is there")
ok(P.status(SHT.id, "studies") == wp.INCOMPLETE, f"nothing was computed, so the study has to run again before the cell is ok ({P.status(SHT.id, 'studies')})")
w = W.open_cell(SHT.id, "document")
lk = [x for s in w.wb.sheets for x in s.links]
ok(len(lk) == 2 and all(os.path.isdir(x["project"]) and x["project"].startswith(W.workspace) for x in lk), "its tables point at the folder of the wired study in THIS session (the old one is gone)")
put_study(P.nodes[STU.id], 5)
done, notes = w.study_refresh_all()
ok(done >= 1 and not [n for n in notes if "no longer" in n], f"and Refresh from the study works after opening the project ({done} read, {notes})")
ok(any(x["rows"] == 5 for s in w.wb.sheets for x in s.links), "with the new rows")

# ------------------------------------------------------------------------------------------------------------------------------ a Sheets tab of its own
alone = shell.new_addon_tab("sheets", None)
ok(alone is not None and getattr(alone, "study_source", 1) is None, "a Sheets tab of its own has no study source")
ok(alone.open_study_projects() == [], "and takes its studies from the open Parametric Study tabs as before")
EXEC.clear()
alone.study_import()
ok(len(EXEC) == 1 and any(b.text().startswith("Browse") for b in EXEC[0].findChildren(QPushButton)), "its import window still has Browse (any project folder)")

print()
if FAILS:
    print(f"FAILURES: {len(FAILS)}")
    for x in FAILS:
        print("  -", x)
    sys.exit(1)
print("ALL OK")
