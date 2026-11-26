"""How the analyses of a Coupled Physics block open, leave and come back (the example project: Square, Air flow, Square heat, Square bending, all wired into 'Air, heat and bending').
An analysis whose Setup is wired into the Physics cell of a block has no tab of its own: it opens in the window of that block, on its own button of the strip, and says so in the status line.
Checked here, one row each: a double-click on a wired analysis opens the window of the block on that analysis (and makes exactly one tab); asking for the editor of an analysis (what a
Parametric Study does) returns the one in the window and makes no tab; an analysis taken out of the block is saved, leaves the window and opens as a tab of its own; the same analysis wired in
again while its tab is open: the tab goes and it moves into the window with its setup; closing the window saves and shuts the analyses down and their solutions say update; a change made in the
window is kept when the project is saved and opened again.  Counts that must be able to fail are shown to fail on a deliberately wrong number.
python test_coupled_link.py"""
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
OUT = tempfile.mkdtemp(prefix="opara_link_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (UD, DEV, OUT)])

import PyQt6.QtWidgets as qw
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
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


import gpd_app
import wb_nodes as nodes
import wb_project as wp
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
W.load_example()
P = W.project
byt = {n.title: n for n in P.nodes.values()}
nFl, nTh, nSt, nC = byt["Air flow"], byt["Square heat"], byt["Square bending"], byt["Air, heat and bending"]
app.processEvents()


def ntabs():
    return shell.tabs.count()


def alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def tabs_made(before, after):
    return after - before


def verdict(made, expected):
    return made == expected


# ---------------------------------------------------------------------------------------------------------------------------------- a double-click on a wired analysis
t0 = ntabs()
w = W.open_cell(nFl.id, "setup")
app.processEvents()
cw = W.editor_of(nC.id)
ok(cw is not None and W.hosted_by(nFl.id) == nC.id and cw.role == "fluid", f"a double-click on the Air flow opens the window of 'Air, heat and bending' on its Fluid button (role: {cw.role if cw else None})")
ok(w is not None and w is W.editor_of(nFl.id) and w is cw.hosted["fluid"].win, "and returns the analysis window that is in it")
ok(verdict(tabs_made(t0, ntabs()), 1) and not verdict(tabs_made(t0, ntabs()), 4), f"exactly one tab was made, not one for every analysis ({tabs_made(t0, ntabs())}); a count of four would be refused")
text = f"‘{nFl.title}’ is part of ‘{nC.title}’: it opens here."
ok(cw.line.text() == text, f"the status line says why ({cw.line.text()})")
ok(cw.strip.roles() == ["fluid", "thermal", "structural", "coupled", "viz"], f"the strip has the three analyses, then Coupled and Viz ({cw.strip.roles()})")
t1 = ntabs()
W.open_cell(nTh.id, "setup")
app.processEvents()
ok(ntabs() == t1 and cw.role == "thermal" and W.editor_of(nC.id) is cw, "a double-click on the heat analysis goes to its button in the same window: no new tab")
W.open_cell(nC.id, "physics")
app.processEvents()
ok(ntabs() == t1 and W.editor_of(nC.id) is cw, "and one on the block itself shows the same window")

# the editor of an analysis, as a Parametric Study or a multi-case block asks for it
a_st = nodes.adapter_for(nSt.kind)
e = a_st.open_editor(W, nSt, front=False)
ok(e is W.editor_of(nSt.id) and e is cw.hosted["structural"].win and ntabs() == t1, "asking for the editor of an analysis (not to be shown) returns the one in the window and makes no tab")

# ---------------------------------------------------------------------------------------------------------------------------------- taking one out
w_old = cw.hosted["structural"].win
link = next(k for k in P.links if k.a == nSt.id and k.b == nC.id)
W.scene.remove_link(link)
app.processEvents()
ok(W.hosted_by(nSt.id) is None and "structural" not in cw.hosted and "structural" not in cw.strip.roles(), f"unwired: the stress analysis leaves the window and its button goes ({cw.strip.roles()})")
ok(not alive(w_old) or W.editor_of(nSt.id) is None, "its window is shut down and no longer the editor of the block")
ok(P.status(nSt.id, "solution") != wp.OK, f"its Solution is no longer ok: it was solved with the others, and now has no load (it says {P.status(nSt.id, 'solution')})")
t2 = ntabs()
w2 = W.open_cell(nSt.id, "setup")
app.processEvents()
ok(w2 is not None and ntabs() == t2 + 1 and shell.tabs.indexOf(w2) >= 0 and W.hosted_by(nSt.id) is None, "now a double-click on it opens a tab of its own, as it always did")
ok(cw.role in cw.strip.roles() and cw.strip.current() == cw.role, "and the window of the block still shows a tab that exists")

# ---------------------------------------------------------------------------------------------------------------------------------- putting it back while its own tab is open
W.scene.make_link(nSt.id, "setup", nC.id, "physics")
app.processEvents()
ok(W.hosted_by(nSt.id) == nC.id and "structural" in cw.hosted and "structural" in cw.strip.roles(), "wired in again: it moves into the window and its button is back")
ok(ntabs() == t2 and shell.tabs.indexOf(w2) < 0, f"the tab it had is gone ({ntabs()} tabs, as before it was opened)")
ok(P.status(nSt.id, "setup") in (wp.OK, wp.UPDATE) and cw.hosted["structural"].win.tab.supports, f"and it has the setup it had (a support: {len(cw.hosted['structural'].win.tab.supports)}; Setup {P.status(nSt.id, 'setup')})")

# ---------------------------------------------------------------------------------------------------------------------------------- a change in the window is kept
cf = cw.hosted["fluid"].win.tab
cf.e_speed.setText("0.04")
app.processEvents()
ok(cw.is_dirty(), "a change made in an analysis shown in the window makes the window dirty")
f1 = os.path.join(OUT, "link.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")

# ---------------------------------------------------------------------------------------------------------------------------------- closing the window
i = shell.tabs.indexOf(cw)
ok(i >= 0, "the window of the block is a tab of the program")
shell.close_tab(i)
app.processEvents()
ok(W.editor_of(nC.id) is None and all(W.editor_of(n.id) is None for n in (nFl, nTh, nSt)) and not W.hosted, "closing the window closes the analyses that were shown in it")
ok(all(P.status(n.id, "solution") != wp.OK for n in (nFl, nTh, nSt, nC)), "and their solutions say update")
ok(all(W.hosted_by(n.id) is None for n in (nFl, nTh, nSt)), "none is hosted by a window that is not there")
t3 = ntabs()
W.open_cell(nTh.id, "setup")
app.processEvents()
cw2 = W.editor_of(nC.id)
ok(cw2 is not None and cw2 is not cw and cw2.role == "thermal" and ntabs() == t3 + 1, "a double-click on the heat analysis after that opens the block's window again, on the heat button")
ok(cw2.hosted["fluid"].win.tab.e_speed.text() not in ("", None), "and the fluid setup is there")

# ---------------------------------------------------------------------------------------------------------------------------------- saved and opened again
shell.close_tab(shell.tabs.indexOf(W))
W3 = shell.open_path(f1)
app.processEvents()
p3 = W3.project
b3 = {n.title: n for n in p3.nodes.values()}
W3.open_cell(b3["Air flow"].id, "setup")
app.processEvents()
cw3 = W3.editor_of(b3["Air, heat and bending"].id)
ok(cw3 is not None and cw3.hosted["fluid"].win.tab.e_speed.text() == cf.e_speed.text() == "0.04", f"the project opened again has the speed that was set in the window ({cw3.hosted['fluid'].win.tab.e_speed.text() if cw3 else None})")
ok(sorted(cw3.hosted) == ["fluid", "structural", "thermal"], f"and all three analyses in the window ({sorted(cw3.hosted)})")
cw3.shutdown()

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
