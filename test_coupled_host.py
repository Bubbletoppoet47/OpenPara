"""The container of the Coupled Physics window: the strip of five buttons (Fluid, Thermal, Structural, Coupled, Viz) and the analyses shown inside the window (hosted).
(1) The strip alone: its five buttons in their order, a button for an analysis only while that analysis is wired in, one selected at a time, a mark on each (and a check that is shown to FAIL on a
deliberately wrong order).  (2) The example project (Square, Air flow, Square heat, Square bending in 'Air, heat and bending') in the real program window: the buttons follow the wiring; the marks
follow the Setup cells of the analyses (a stress analysis whose support is taken away says so) and are bolts on Coupled and Viz until there is a solve; a button shows the Outline and the view of
its analysis, each column the width of the side panels of every analysis window; after the block is solved the analyses hold the results, the marks are ticks, and the window's report says where the
pictures are; the options of the block are kept when the project is saved and opened again.  Nothing here was looked at on Windows.
python test_coupled_host.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(1500, exit=True)
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
OUT = tempfile.mkdtemp(prefix="opara_host_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (UD, DEV, OUT)])

import PyQt6.QtWidgets as qw
from PyQt6.QtWidgets import QApplication, QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


import coupled_host as CH
import sim_ui
app = QApplication([])

# ------------------------------------------------------------------------------------------------------------------------------ 1. the strip alone
ORDER = ["fluid", "thermal", "structural", "coupled", "viz"]
st = CH.RoleStrip()
st.show()
ok([r for r, _n in CH.ROLES] == ORDER and [b.text() for b in st.buttons.values()] == ["Fluid", "Thermal", "Structural", "Coupled", "Viz"], "five buttons in the order Fluid, Thermal, Structural, Coupled, Viz")
ok(st.roles() == ["coupled", "viz"] and st.current() == "coupled", f"with nothing wired in there are Coupled and Viz, and Coupled is the one shown ({st.roles()}, {st.current()})")
st.set_roles(["thermal", "structural", "coupled", "viz"])
ok(st.roles() == ["thermal", "structural", "coupled", "viz"] and st.button("fluid").isHidden(), "an analysis that is not wired in has no button")
ok(st.select("structural") and st.current() == "structural" and sum(b.isChecked() for b in st.buttons.values()) == 1, "one button is selected at a time")
ok(st.select("fluid") is False and st.current() == "structural", "a button that is not there cannot be selected")
for kind in ("ok", "update", "incomplete"):
    st.set_mark("thermal", kind)
ok(st.marks()["thermal"] == "incomplete" and "fluid" not in st.marks(), "a mark is kept on its button, and a hidden button has none to show")
picked = []
st.picked.connect(picked.append)
st.button("coupled").click()
ok(picked == ["coupled"], "clicking a button says which")
img = st.grab().toImage()
ok(img.width() > 100 and any(img.pixelColor(x, 20).red() != img.pixelColor(2, 20).red() for x in range(5, img.width(), 7)), "the strip is drawn")


def order_verdict(roles):
    return roles == ["thermal", "structural", "coupled", "viz"]


ok(order_verdict(st.roles()) and not order_verdict(["structural", "thermal", "coupled", "viz"]), "check shown to FAIL on a wrong order (a deliberately wrong answer)")

# ------------------------------------------------------------------------------------------------------------------------------ 2. the example in the program window
import gpd_app
import wb_project as wp
shell = gpd_app.AppShell()
shell.resize(1500, 900)
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
W.load_example()
P = W.project
byt = {n.title: n for n in P.nodes.values()}
nFl, nTh, nSt, nC = byt["Air flow"], byt["Square heat"], byt["Square bending"], byt["Air, heat and bending"]
W.open_cell(nC.id, "physics")
app.processEvents()
cw = W.editor_of(nC.id)
shell.tabs.setCurrentWidget(cw)
cw.refresh()
cw.show_role("coupled")
app.processEvents()
ok(cw.strip.roles() == ORDER, f"the three analyses are wired in: the strip has all five buttons ({cw.strip.roles()})")
m = cw.strip.marks()
ok(m["fluid"] == m["thermal"] == m["structural"] == "ok" and m["coupled"] == "update" and m["viz"] == "update", f"before a solve: ticks on the three analyses, bolts on Coupled and Viz ({m})")

# the panels
for role in ("fluid", "thermal", "structural", "coupled", "viz"):
    cw.show_role(role)
    app.processEvents()
    left, right = cw.page_of(role)
    ok(cw.left.currentWidget() is left and cw.right.currentWidget() is right and cw.strip.current() == role, f"the {role} button shows its own panel and view")
    ok(abs(cw.left.width() - sim_ui.SIDE_W) <= 8, f"its column is as wide as the side panel of any analysis window ({cw.left.width()} against {sim_ui.SIDE_W})")
for role in ("fluid", "thermal", "structural"):
    h = cw.hosted[role]
    ok(h.outline is not None and h.panel is not None and h.view is cw.page_of(role)[1] and h.panel.isAncestorOf(h.outline), f"{role}: the Outline is in the panel, and the view is the analysis window's own view")
    ok(h.win.isHidden() and h.win.parent() is cw, f"{role}: its window stays alive, hidden, inside this window")

# an Outline row of a hosted analysis still changes its view
cw.show_role("structural")
app.processEvents()
ol = cw.hosted["structural"].outline
cv = cw.hosted["structural"].win.tab.canvas
ol.select("Supports")
app.processEvents()
f_sup = cv.focus
ol.select("Geometry")
app.processEvents()
ok(f_sup == "supports" and cv.focus == "geometry", f"selecting a row of the Outline still changes what the view shows ({f_sup}, then {cv.focus})")

# the marks follow the Setup of an analysis
tab_s = cw.hosted["structural"].win.tab
kept = [dict(s) for s in tab_s.supports]
tab_s.supports.clear()
tab_s.after_conditions()
W.sync_editors()
cw.update_marks()
ok(cw.strip.marks()["structural"] == "incomplete" and "not ready" in cw.strip.button("structural").toolTip(), f"a stress analysis with its support taken away says it is not ready ({cw.strip.marks()['structural']})")
ok(cw.strip.marks()["fluid"] == "ok" and cw.strip.marks()["thermal"] == "ok", "and the others do not")
tab_s.supports.extend(kept)
tab_s.after_conditions()
W.sync_editors()
cw.update_marks()
ok(cw.strip.marks()["structural"] == "ok", "with its support back it is ready again")

# an option of the block, kept
cw.e_fsi_max.setValue(7)
cw.e_conj_tol.setValue(0.5)
app.processEvents()
ok(cw.options["fsi_max"] == 7 and cw.options["conj_tol_pct"] == 0.5 and cw.is_dirty(), "the options of the block are changed in the Coupled tab")

# solve, and the analyses hold the results; the steps are listed while it runs
import coupled_steps
seen = []
orig_progress = cw.progress


def spy(text, frac):
    orig_progress(text, frac)
    seen.append(cw.steps_lbl.text())


cw.progress = spy
done, failed = W.update_project(only={nFl.id, nTh.id, nSt.id, nC.id})
cw.progress = orig_progress
ok(not failed and cw.result is not None and cw.result["ok"], f"the block is solved from its window ({failed})")
ticks = [t.count("✓") for t in seen]
ok(len(seen) >= 10 and ticks == sorted(ticks) and ticks[-1] >= len(seen) - 2 and all(t.count("…") == 1 for t in seen), f"while it ran the steps were listed as they came: a tick for each one done, three dots for the one being worked on ({len(seen)} messages, last had {ticks[-1] if ticks else None} ticks)")
ok("Pass 1 of at most" in seen[3] and "Pass 2 of at most" in seen[-1] and "Pass 2 of at most" not in seen[3], "and the lines are the engine's own words, the passes in the order they ran")
ok("Solved in" in cw.steps_lbl.text() and "…" not in cw.steps_lbl.text(), "when the solve is over the list is replaced by the passes of the loop")


def live_verdict(rows):
    return len(rows) == 3 and [d for d, _t in rows] == [True, True, False]


rows = coupled_steps.live_rows(["a", "a", "b", "Done", "c"])
ok(live_verdict(rows) and not live_verdict(coupled_steps.live_rows(["a", "b"])) and coupled_steps.live_rows(["x"] * 3) == [(False, "x")], "live rows: a repeated message counts once, the last row is the one being worked on (and a wrong count is refused)")
fl, th, sk = (cw.hosted[r].win.tab for r in ("fluid", "thermal", "structural"))
ok(fl.result is not None and th.result is not None and sk.result is not None, "the fluid, heat and stress analyses each hold the result of that solve")
m = cw.strip.marks()
ok(m["coupled"] == "ok" and m["viz"] == "ok", f"after the solve Coupled and Viz have ticks ({m})")
for r in ("fluid", "thermal", "structural"):
    cw.hosted[r].outline.sync()


def results_mark(ol):
    return next((v for k, v in ol.marks.items() if k.strip().lower() == "results"), None)


ok(all(results_mark(cw.hosted[r].outline) == "ok" for r in ("fluid", "thermal", "structural")),
   "and the Results of every analysis say so in its Outline (" + ", ".join(f"{r}: {results_mark(cw.hosted[r].outline)}" for r in ("fluid", "thermal", "structural")) + ")")
ok("Viz tab" in cw.report_html(), "the report says where the pictures are")

# saved and opened again
f1 = os.path.join(OUT, "host.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
shell.close_tab(shell.tabs.indexOf(W))
W3 = shell.open_path(f1)
app.processEvents()
b3 = {n.title: n for n in W3.project.nodes.values()}
W3.open_cell(b3["Air, heat and bending"].id, "physics")
app.processEvents()
cw3 = W3.editor_of(b3["Air, heat and bending"].id)
ok(cw3.options["fsi_max"] == 7 and cw3.options["conj_tol_pct"] == 0.5, f"the options came back with the project ({cw3.options['fsi_max']}, {cw3.options['conj_tol_pct']})")
ok(cw3.e_fsi_max.value() == 7 and abs(cw3.e_conj_tol.value() - 0.5) < 1e-9, "and are in the boxes")
ok(cw3.strip.marks()["coupled"] == "update" and cw3.strip.marks()["viz"] == "update", "nothing was computed on opening: Coupled and Viz are bolts again")
cw3.shutdown()

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
