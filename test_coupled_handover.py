"""What the Coupled Physics window hands over between the analyses it shows: the green, locked rows in the Outline of each analysis, and the green edges on its view.
Two parts.  (1) The rows themselves (coupled_handover, no Qt): who gets which row, from whom, on which edges - with the edges a support holds left out of the pressure, the options of the
block (the structure moves the flow) switching rows on and off, and a check that is shown to FAIL on a deliberately wrong answer.  (2) In the real program window with the example project
(Square part, Air flow, Square heat, Square bending, all in 'Air, heat and bending'): the rows are in the Outline under the right node, their letters go on after the conditions of the
analysis, a selected row draws its edges in green (pixels counted) and shows its note instead of an editable page, the Loads of the stress analysis count as given, the rows follow the options
of the block, and an analysis taken out of the window hands nothing over.  Nothing here was looked at on Windows.
python test_coupled_handover.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
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
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d", "coupled"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (UD, DEV)])

from types import SimpleNamespace as NS

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


import coupled_handover as CHO

# ------------------------------------------------------------------------------------------------------------------------------ 1. the rows (no Qt)
SQUARE = [("ln", 5), ("ln", 6), ("ln", 7), ("ln", 8)]


class Fake:
    def __init__(self, edges=SQUARE, supports=(), coupled=(), walls=None):
        self.geom = {"edges": [{"src": k} for k in edges]}
        self.supports = [{"targets": [k]} for k in supports]
        self._c, self._w = list(coupled), walls

    def coupled_keys(self):
        return list(self._c)

    def selectable(self):
        return self._w


LAB = {"fluid": "Air flow", "thermal": "Square heat", "structural": "Square bending"}
fl, th, st = Fake(coupled=[("ln", 5), ("ln", 6), ("ln", 7)]), Fake(), Fake(supports=[("ln", 8)])
tabs = {"fluid": fl, "thermal": th, "structural": st}


def what(rows):
    return [r["what"] for r in rows]


def keys(rows, w):
    return next((r["keys"] for r in rows if r["what"] == w), "none")


R = {role: CHO.rows_for(role, tabs, LAB, {"moves_flow": False}) for role in LAB}
ok(what(R["fluid"]) == ["wall_temperature"] and keys(R["fluid"], "wall_temperature") == [("ln", 5), ("ln", 6), ("ln", 7)], f"the fluid gets the wall temperature on the walls it shares with the solid ({R['fluid']})")
ok(what(R["thermal"]) == ["air_film"] and keys(R["thermal"], "air_film") == [("ln", 5), ("ln", 6), ("ln", 7)], "the heat analysis gets the air film on the same edges")
ok(what(R["structural"]) == ["air_pressure", "body_temperature"], f"the stress analysis gets the pressure and the temperature ({what(R['structural'])})")
ok(keys(R["structural"], "air_pressure") == [("ln", 5), ("ln", 6), ("ln", 7)] and R["structural"][0]["arrows"] is True, "the pressure is on the edges of the fluid, with arrows")
ok(keys(R["structural"], "body_temperature") is None and R["structural"][1]["where"] == "the whole body", "the temperature is on the whole body")
ok(R["fluid"][0]["type"] == "from Square heat" and R["thermal"][0]["type"] == "from Air flow", "every row says where it comes from, by the name of the analysis")
ok(CHO.edges_text([("ln", 7), ("ln", 5), ("ar", 2), ("ln", 6)]) == "Line 5, 6, 7 and Arc 2", f"edges are named by kind, in order ({CHO.edges_text([('ln', 7), ('ln', 5), ('ar', 2), ('ln', 6)])})")
ok("Line 5, 6, 7" in R["structural"][0]["note"] and "{where}" not in R["structural"][0]["note"], "the note names the edges")

# a condition set by hand on a wall the air takes over is said to be replaced
rows_h = CHO.rows_for("thermal", {"fluid": fl, "thermal": Fake(supports=[("ln", 6)])}, LAB)
ok("replaced by the air" in rows_h[0]["note"] and "replaced by the air" not in R["thermal"][0]["note"], "a condition set by hand on one of those edges is said to be replaced by the air; without one, nothing is said")
ok(R["thermal"][0]["dashed"] is True and R["structural"][0]["dashed"] is False, "the air on the heat analysis is drawn dashed, the pressure is not")

# the structure moves the flow: the fluid gets the moved walls
Rm = CHO.rows_for("fluid", tabs, LAB, {"moves_flow": True})
ok(what(Rm) == ["wall_temperature", "moved_walls"], f"'the structure moves the flow' adds the moved walls to the fluid ({what(Rm)})")
# once the flow is meshed, its walls include the held edge: moved, but still no pressure there
fl2 = Fake(coupled=[("ln", 5), ("ln", 6), ("ln", 7)], walls={("ln", 5), ("ln", 6), ("ln", 7), ("ln", 8)})
t2 = {"fluid": fl2, "thermal": th, "structural": st}
ok(keys(CHO.rows_for("fluid", t2, LAB, {"moves_flow": True}), "moved_walls") == SQUARE, "a meshed flow moves every wall of the body")
ok(keys(CHO.rows_for("structural", t2, LAB), "air_pressure") == [("ln", 5), ("ln", 6), ("ln", 7)], "and the edge a support holds gets no pressure")


def pressure_verdict(rows, held):
    """True when the pressure rows are on edges none of which is held by a support."""
    bad = [k for r in rows if r["what"] == "air_pressure" for k in r["keys"] if tuple(k) in held]
    return (not bad, f"pressure on held edges {bad}")


good = CHO.rows_for("structural", t2, LAB)
ok(pressure_verdict(good, {("ln", 8)})[0], "check: no pressure on a held edge")
broken = [dict(r, keys=list(r["keys"]) + [("ln", 8)]) if r["what"] == "air_pressure" else r for r in good]
ok(not pressure_verdict(broken, {("ln", 8)})[0], "check shown to FAIL on a pressure that reaches the held edge (a deliberately wrong answer)")

# who is wired in decides which rows there are
ok(CHO.rows_for("structural", {"thermal": th, "structural": st}, LAB) and what(CHO.rows_for("structural", {"thermal": th, "structural": st}, LAB)) == ["body_temperature"],
   "heat + stress, no fluid: the stress analysis gets the temperature only")
ok(CHO.rows_for("thermal", {"thermal": th, "structural": st}, LAB) == [], "heat + stress, no fluid: the heat analysis is handed nothing")
ok(what(CHO.rows_for("structural", {"fluid": fl, "structural": st}, LAB)) == ["air_pressure"], "flow + stress: the pressure only")
ok(CHO.rows_for("fluid", {"fluid": fl}, LAB) == [] and CHO.rows_for("thermal", {"thermal": th}, LAB) == [], "an analysis alone is handed nothing")
ok(CHO.rows_for("fluid", {"fluid": Fake(), "thermal": th}, LAB) == [], "a fluid with no wall set as a wall of the thermal analysis has no row to show")

# applying: the same rows keep their objects
tt = NS()
a = CHO.rows_for("structural", tabs, LAB)
ok(CHO.apply(tt, a) is True and tt.handover == a, "applying rows to a window gives it the rows")
first = tt.handover
ok(CHO.apply(tt, CHO.rows_for("structural", tabs, LAB)) is False and tt.handover is first, "the same rows again change nothing (the row selected in an Outline stays selected)")
ok(CHO.apply(tt, []) is True and tt.handover == [], "no rows clears them")

# ------------------------------------------------------------------------------------------------------------------------------ 2. in the program window
import gpd_app
import sim_outline
import sim_tags
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
W.load_example()
P = W.project
byt = {n.title: n for n in P.nodes.values()}
nC = byt["Air, heat and bending"]
W.open_cell(nC.id, "physics")
app.processEvents()
cw = W.editor_of(nC.id)
cw.refresh()
app.processEvents()
GREEN = QColor(sim_tags.colour_of("handover"))


def green_pixels(canvas):
    img = canvas.grab().toImage()
    n = 0
    for y in range(0, img.height(), 1):
        for x in range(0, img.width(), 1):
            c = img.pixelColor(x, y)
            if abs(c.red() - GREEN.red()) <= 8 and abs(c.green() - GREEN.green()) <= 8 and abs(c.blue() - GREEN.blue()) <= 8:
                n += 1
    return n


def texts(role, node):
    return cw.hosted[role].outline.item_texts(node)


ok(texts("fluid", "Fluid and flow") == ["Walls of the thermal analysis · from Square heat", "Moved walls · from Square bending"], f"the fluid analysis lists its two rows under Fluid and flow ({texts('fluid', 'Fluid and flow')})")
ok(texts("thermal", "Conditions") == ["Temperature 1", "Heat exchange with the air · from Air flow"], f"the heat analysis lists its own condition, then the row ({texts('thermal', 'Conditions')})")
ok(texts("structural", "Loads") == ["Pressure of the air · from Air flow", "Temperature · from Square heat"], f"the stress analysis lists its rows under Loads ({texts('structural', 'Loads')})")
ol_t = cw.hosted["thermal"].outline
letters = [tg["letter"] for k, v in ol_t.items.items() for _t, tg in v if k == "Conditions"]
ok(letters == ["A", "B"], f"the letters go on after the conditions of the analysis ({letters})")
ol_s = cw.hosted["structural"].outline
ok(ol_s.marks.get("Loads") == "ok", "the stress analysis has no load of its own, and its Loads still count as given (the pressure and the temperature are handed over)")
ok(all(tg["colour"] == "#23744a" for v in ol_s.items.values() for _t, tg in v if tg.get("kind") == "handover"), "the rows are green")

# a selected row: green edges, its tag, its note instead of a page
tab_s = cw.hosted["structural"].win.tab
tag = next(tg for _t, tg in ol_s.items["Loads"] if tg["name"] == "Pressure of the air")
ol_s.select("Loads", tag)
app.processEvents()
cv = tab_s.canvas
ok(cv.focus == "handover" and [t["letter"] for t in cv.tag_list] == ["B"], f"selecting a row shows only that row on the view ({cv.focus}, {[t['letter'] for t in cv.tag_list]})")
ok(ol_s.note.isVisibleTo(ol_s) and "Line 5, 6, 7" in ol_s.note.text() and not any(n["section"].isVisibleTo(ol_s) for n in ol_s.nodes.values()), "the Details show the note, and no page to edit")
n_sel = green_pixels(cv)
ol_s.select("Geometry")
app.processEvents()
n_geo = green_pixels(cv)
ok(n_sel > 300 and n_geo == 0, f"the edges are green while the row is selected, and not otherwise ({n_sel} pixels, then {n_geo})")
ol_s.select("Loads")
app.processEvents()
ok(len(cv.tag_list) == 2 and green_pixels(cv) > 300, f"the node Loads shows both rows ({len(cv.tag_list)} tags)")


def paint_verdict(count, minimum=300):
    return count >= minimum


cw.ticker.stop()                                                                         # (the window looks at its rows by itself a few times a second: not while this is looked at)
tab_s.handover = []
ol_s.sync()
app.processEvents()
ok(not paint_verdict(green_pixels(cv)), "check shown to FAIL when the rows are taken away: no green is drawn (a deliberately wrong state)")
cw.refresh_handover()
ok(len(tab_s.handover) == 2, "the window gives the rows again")

# the options of the block move the rows
cw.cb_moves.setChecked(False)
app.processEvents()
ok(texts("fluid", "Fluid and flow") == ["Walls of the thermal analysis · from Square heat"], f"without 'the structure moves the flow' the moved walls are gone ({texts('fluid', 'Fluid and flow')})")
cw.cb_moves.setChecked(True)
app.processEvents()
ok(len(texts("fluid", "Fluid and flow")) == 2, "and back with it")

# the fluid view: its row also draws on the fluid view
ol_f = cw.hosted["fluid"].outline
tag = next(tg for _t, tg in ol_f.items["Fluid and flow"] if tg["name"] == "Walls of the thermal analysis")
ol_f.select("Fluid and flow", tag)
app.processEvents()
ok(green_pixels(cw.hosted["fluid"].win.tab.canvas) > 300, "the fluid view draws the walls of the heat exchange in green")

# an analysis taken out of the window hands nothing over
win = cw.unhost_member("structural")
app.processEvents()
ok(win is not None and (win.tab.handover or []) == [], "an analysis taken out of the window is handed nothing")
ok(texts("fluid", "Fluid and flow") == ["Walls of the thermal analysis · from Square heat"], f"and the others lose the rows that were about it ({texts('fluid', 'Fluid and flow')})")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
