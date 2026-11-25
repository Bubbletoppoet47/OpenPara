"""The example project of the Workbench (Load Example Project) in the real program window: it loads without computing anything, every block says what it is ready for, no editor is left
open, Update Project solves the three analyses and the answers are right (the bar's u = F L / (A E), the two temperatures), the project saves and opens again, and the report tells it.
python test_wb_example.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(1200, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled", "sheets", "controls", "circuits"):
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


import gpd_app
import wb_example
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbe_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
import PyQt6.QtWidgets as qw

ok(not addons.load_errors(), f"the add-ons load without errors ({addons.load_errors()})")
W.add_block("part", 20, 20, title="Something that was here")
P0 = W.project
ok(P0.is_dirty(), "(the tab has an unsaved block: loading the example asks first)")
res = W.load_example()
P = W.project
ok(res is P and P is not P0 and P.name == wb_example.NAME, f"Load Example Project makes a project of its own ({P.name})")
ok(all(n.title != "Something that was here" for n in P.nodes.values()), "and replaces what was in the tab")
byt = {n.title: n for n in P.nodes.values()}
ok(sorted(byt) == sorted(["Bar", "Plate", "Frame", "Bar stress", "Plate stress 2D", "Frame heating", "Frame check (needs a setup)", "Bar heating", "Bar growth", "Bar thermal stress",
                          "Bar study", "Load table", "LED circuit", "Plant", "Square", "Air flow", "Square heat", "Square bending", "Air, heat and bending"]), f"nineteen blocks ({sorted(byt)})")
ok(len(P.links) == 15 and sum(k.a_cell == "geometry" and k.b_cell == "geometry" for k in P.links) == 9, f"nine wires, geometry to geometry, one from a setup to the study and five from setups to Coupled Physics ({len(P.links)})")
ok(sorted((P.node(k.a).title, k.a_cell, P.node(k.b).title, k.b_cell) for k in P.links if k.b_cell == "physics") == [("Air flow", "setup", "Air, heat and bending", "physics"), ("Bar growth", "setup", "Bar thermal stress", "physics"), ("Bar heating", "setup", "Bar thermal stress", "physics"),
    ("Square bending", "setup", "Air, heat and bending", "physics"), ("Square heat", "setup", "Air, heat and bending", "physics")],
   "the Coupled Physics blocks take the Setup of the heat and of the stress analysis of the bar, and of the flow, the heat and the stress analysis of the square")
import wb_canvas as _cv
import wb_route as _wr
_its = list(W.scene.items_by_id.values())
ok(len(_its) == 19 and all(_cv.clear_of(a.keep(), [b.keep() for b in _its if b is not a]) for a in _its), "the blocks of the example keep the gap from each other")
_rects = W.scene.keep_rects()
ok(len(W.scene.link_items) == 15 and all(_wr.crossings([(q.x(), q.y()) for q in l.pts], _rects) == [] for l in W.scene.link_items.values()), "and none of its fifteen wires runs behind a block")
src_of = {P.node(k.b).title: P.node(k.a).title for k in P.links if k.b_cell == "geometry"}
ok([(P.node(k.a).title, k.a_cell, P.node(k.b).title, k.b_cell) for k in P.links if k.b_cell == "setup"] == [("Bar stress", "setup", "Bar study", "setup")], "the study takes the Setup of Bar stress")
ok(src_of == {"Bar stress": "Bar", "Plate stress 2D": "Plate", "Frame heating": "Frame", "Frame check (needs a setup)": "Frame", "Bar heating": "Bar", "Bar growth": "Bar", "Air flow": "Square", "Square heat": "Square", "Square bending": "Square"}, f"each analysis is wired to its part ({src_of})")
ok(not MSGS, f"nothing complained ({MSGS})")
ok(shell.tabs.count() == 1 and not [i for i in W.editors if W.editor_of(i) is not None], f"no editor is left open ({shell.tabs.count()} tab)")
ok("Left out or not set up" not in W.line.text(), f"and nothing was left out ({W.line.text()[:100]})")


def st(title):
    return P.statuses(byt[title].id)


for title in ("Bar", "Plate", "Frame"):
    ok(st(title) == {"geometry": wp.OK}, f"{title}: ok ({st(title)})")
ok(st("Load table") == {"studies": wp.OK, "document": wp.OK}, f"Load table: its document is ok, and its Study Results cell needs no wire ({st('Load table')})")
for title in ("LED circuit", "Plant"):
    ok(st(title) == {"document": wp.OK}, f"{title}: ok ({st(title)})")
for title in ("Bar stress", "Plate stress 2D", "Frame heating", "Bar heating", "Bar growth", "Air flow", "Square heat", "Square bending"):
    ok(st(title) == {"geometry": wp.OK, "setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"{title}: geometry and setup ok, the solution waits for Update ({st(title)})")
ok(st("Bar thermal stress") == {"physics": wp.OK, "setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"Bar thermal stress: Physics and Setup ok (the stress analysis needs no load once it is wired in), the solution waits for Update ({st('Bar thermal stress')})")
ok(st("Air, heat and bending") == {"physics": wp.OK, "setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"Air, heat and bending: Physics and Setup ok, the solution waits for Update ({st('Air, heat and bending')})")
chk = st("Frame check (needs a setup)")
ok(chk["geometry"] == wp.OK and chk["setup"] == wp.INCOMPLETE and chk["solution"] == wp.INCOMPLETE, f"Frame check: geometry ok, setup incomplete ({chk})")
why = P.why_incomplete(byt["Frame check (needs a setup)"].id, "setup")
ok("Setup of 'Frame check" in why and "not set up yet" in why, f"and it says why ({why})")
ok(all(not json.dumps(n.data).count("opara_wb") for n in P.nodes.values()), "no temporary folder of the workbench is in any block")
ok(all('"orig": "/' not in json.dumps(n.data) for n in P.nodes.values()), "and no path of a file on this computer")
plan = [(s["name"], s["action"]) for s in P.plan_update()]
ok(len(plan) == 11 and all(a == "update" for _n, a in plan), f"Update would solve the eight analyses, solve them coupled (two blocks) and run the study, nothing else ({plan})")
ok(st("Bar study") == {"setup": wp.OK, "solution": wp.UPDATE, "results": wp.INCOMPLETE}, f"the study: its Parameters are ok, its Study waits for Update ({st('Bar study')})")

# ---------------------------------------------------------------------------------------------------------------------------- Update Project
done, failed = W.update_project()
ok(done == 11 and not failed, f"Update Project solved them, solved the coupled blocks and ran the study ({done} done, {failed})")
ok(all(v == wp.OK for v in st("Bar study").values()), f"Bar study: every cell ok ({st('Bar study')})")
for title in ("Bar stress", "Plate stress 2D", "Frame heating", "Bar heating", "Bar growth", "Bar thermal stress", "Air flow", "Square heat", "Square bending", "Air, heat and bending"):
    ok(all(v == wp.OK for v in st(title).values()), f"{title}: every cell ok ({st(title)})")
wcp = W.editor_of(byt["Bar thermal stress"].id)
kn = wcp.result.get("known") if wcp is not None and wcp.result else None
ok(kn is not None and kn["ok"] and abs(kn["got"] - 0.048) / 0.048 < 0.02 and all(c["ok"] for c in wcp.result["checks"]),
   f"the coupled bar: the far end grows alpha (Tmean - Tref) L = 0.048 mm, PASS beside the number ({kn})")
ok("PASS" in wcp.report_html() and "Known answer" in wcp.report_html() and "Known answer" in wcp.diagnostics_text(), "the window and its diagnostics report show the known answer")
# the flow, the heat and the bending of the square in the air, together
wair = W.editor_of(byt["Air, heat and bending"].id)
ra = wair.result if wair is not None else None
ok(ra is not None and ra["ok"] and ra["dim"] == 2 and all(c["ok"] for c in ra["checks"]) and {"fluid", "thermal", "structural", "fsi"} <= set(ra),
   "the square in the air: flow, heat and bending in one solve, every check passes: " + ("; ".join(f"{c['name']}: {c['ok']}" for c in ra["checks"]) if ra else "no result"))
kn_a = ra.get("known") if ra else None
ok(kn_a is not None and kn_a["ok"] and abs(kn_a["got"] - 50.0) <= 1.0, f"its known answer: the walls of a body this conductive are at 50 degC, PASS beside the number ({kn_a})")
ok(ra is not None and ra["fsi"]["converged"] and ra["fsi"]["iterations"] >= 2 and 0.05 < ra["fsi"]["umax"] < 1.0,
   f"the structure moves the flow: converged in {ra['fsi']['iterations'] if ra else '?'} passes, the largest displacement {ra['fsi']['umax'] if ra else 0:.3g} mm of the 20 mm square")
ok("PASS" in wair.report_html() and "Known answer" in wair.report_html() and "Known answer" in wair.diagnostics_text() and "moves the flow" in wair.report_html(), "its window and its diagnostics report show the known answer and the passes")
ok(wair.options["moves_flow"] and "walls" in wair.diagnostics_text().lower(), "'the structure moves the flow' is ticked in it")
wbar = W.editor_of(byt["Bar stress"].id)
um = wbar.result["umax"] if wbar is not None and wbar.result else None
ok(um is not None and abs(um - 0.005) / 0.005 < 0.03, f"the bar: u = F L / (A E) = 0.005 mm ({um})")
wh = W.editor_of(byt["Frame heating"].id)
ok(wh is not None and wh.result is not None and abs(wh.result["Tmax"] - 373.15) < 0.5 and abs(wh.result["Tmin"] - 293.15) < 0.5, "the frame: between 100 C and 20 C")
w2 = W.editor_of(byt["Plate stress 2D"].id)
ok(w2 is not None and w2.tab.result is not None, "the plate has its result")
ok(P.plan_update() == [], "nothing is out of date after it")
ok(W.update_project()[0] == 0, "a second Update has nothing to do")
bl = P.blocked()
ok(len(bl) == 2 and all("Frame check" in b[1] for b in bl), f"only Frame check is left (its setup and, behind it, its solution), and it says so ({bl})")

# a part changes: what uses it says so
bar_ed = W.open_cell(byt["Bar"].id, "geometry")
bar_ed.doc.params["H"] = "20"
bar_ed.update_all()
W.sync_editors()
ok(P.status(byt["Bar stress"].id, "geometry") == wp.REFRESH and P.status(byt["Frame heating"].id, "geometry") == wp.OK, "after the Bar is changed only the analysis wired to it says refresh (the frame has its own copy)")
shell.close_tab(shell.tabs.indexOf(bar_ed))

# ---------------------------------------------------------------------------------------------------------------------------- save, open, report
f = os.path.join(T, "example.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f, ""))
ok(W.save(True) and os.path.isfile(f), "the project saves")
size = os.path.getsize(f)
ok(size < 3_000_000, f"in one file of a sensible size ({size // 1024} KB: no meshes or results in it)")
W.load(f)
P = W.project
byt = {n.title: n for n in P.nodes.values()}
ok(not P.is_dirty() and len(P.nodes) == 19, "it opens again with nineteen blocks, unchanged")
ok(all(P.status(byt[t_].id, "solution") == wp.UPDATE for t_ in ("Bar stress", "Plate stress 2D", "Frame heating")), "nothing was computed: the solutions say update")
ok(P.status(byt["Bar stress"].id, "geometry") == wp.REFRESH, "and the bar analysis still says refresh (the part was changed before it was saved)")
plan = [(s_["name"], s_["action"]) for s_ in P.plan_update()]
print("     plan after reopening:", plan)
done, failed = W.update_project()
ok(done == len(plan) == 14 and not failed and sum(a_ == "refresh" for _n, a_ in plan) == 3 and sum(a_ == "update" for _n, a_ in plan) == 11,
   f"Update Project refreshes the three analyses that use the bar, solves the eight analyses and the two coupled blocks, and runs the study ({done} steps, {failed})")
wbar = W.editor_of(byt["Bar stress"].id)
ok(abs(wbar.geom["volume"] - 20000) < 1e-6 and wbar.result is not None, f"the bar analysis follows the change: the bar is 20 thick now (volume {wbar.geom['volume']:.0f})")
rep = W.report_text()
ok("Frame check" in rep and "Bar stress" in rep and "incomplete" in rep.lower(), "the project report names the blocks and what is incomplete")
ok("Traceback" not in rep, "and has no error in it")

# the tools open with their content
wsh = W.open_cell(byt["Load table"].id, "document")
nm = wsh.wb.sheet_names()[0]
ok(wsh.wb.value(nm, 5, 2) == 100.0 and abs(wsh.wb.value(nm, 6, 2) - 10.0) < 1e-9, "the sheet works its formulas out: A = 100 mm2, stress = 10 MPa")
wct = W.open_cell(byt["Plant"].id, "document")
ok(wct.sections[0].num.text() == "2s+3" and wct.sections[0].den.text() == "s^2+3s+2", "the controls tab has the plant")
wc = W.open_cell(byt["LED circuit"].id, "document")
ok(sorted(p.kind for p in wc.scene.parts()) == sorted(["BAT", "R", "LED", "GND", "VM"]), f"the circuit has its parts ({sorted(p.kind for p in wc.scene.parts())})")
ok(W.sync_editors() == [], "opening the tools is not a change")
ok(wsh.wb.cell(nm, 5, 2).is_formula and wsh.wb.cell(nm, 6, 2).is_formula, "the area and the stress are formulas, not numbers")
wsh.wb.set_input(nm, 3, 2, "20")
ok(wsh.wb.value(nm, 5, 2) == 200.0 and abs(wsh.wb.value(nm, 6, 2) - 5.0) < 1e-9, "change the width and they follow (A = 200 mm2, stress = 5 MPa)")
ok(W.sync_editors() == [byt["Load table"].id] and P.is_dirty(), "and the project takes the change")

# loading it again replaces it; with no program window the analyses cannot be set up, and it says so
W.load_example()
ok(len(W.project.nodes) == 19, "loading it again gives nineteen blocks, not thirty-eight")
bare = wb_tab.WorkbenchTab(None)
probs = wb_example.load(bare)
ok(any("no program window" in p for p in probs) and len(bare.project.nodes) == 19, f"without a program window the blocks are made and it says the analyses need setting up ({probs[:1]})")
ok(bare.project.status(next(n.id for n in bare.project.nodes.values() if n.title == "Bar stress"), "setup") == wp.INCOMPLETE, "(they say incomplete)")

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
