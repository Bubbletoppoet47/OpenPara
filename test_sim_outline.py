"""The ANSYS-style left column of every FEA window (1D, 2D, 3D, thermal 2D / 3D, CFD): the Outline (a tree: geometry, material, mesh, supports, loads, results) on top, the
Details of the selected node below, both dividers draggable; the conditions are rows under their node with a lettered colour tag (A, B ...); the marks in front of the nodes
follow what exists; and the VIEW shows only what the selected node or row is about (the bare part for the pages about the part, only the mesh for Mesh, only the supports,
only the loads, only the solution).  There is no legend and no explaining text.     python test_sim_outline.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QSplitter
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import physics_fea as pf
import physics_tab, beam_tab, cfd_tab, profiles1d, sim_outline, sim_tags, sim_ui
import sketcher_core as sc

BAD = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        BAD.append(msg)


class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


def settle(w=None):
    app.processEvents()
    if w is not None:
        w.outline.sync()
    app.processEvents()


def count(img, rgb, tol=6):
    """How many pixels of the picture are (nearly) this colour."""
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if abs(c.red() - rgb[0]) <= tol and abs(c.green() - rgb[1]) <= tol and abs(c.blue() - rgb[2]) <= tol:
                n += 1
    return n


def shot(cv):
    cv.sel = []
    cv.repaint()
    return cv.grab().toImage()


def green(img):
    """How many pixels of the picture are clearly green (a support, drawn with a see-through fill)."""
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.green() - c.red() > 50 and c.green() - c.blue() > 40:
                n += 1
    return n


def inside(cv):
    """A pixel of the canvas that is inside the bar (50, 10 of the sketch)."""
    s_ = cv.w2s(50.0, 10.0)
    return int(s_.x()), int(s_.y())


def differs(a, b):
    """How many pixels differ between two pictures of the same size."""
    return sum(1 for y in range(0, a.height(), 2) for x in range(0, a.width(), 2) if a.pixel(x, y) != b.pixel(x, y))


FORBIDDEN = ("up to date", "needs update", "incomplete", "no mesh yet", "press generate mesh", "something it depends on")


def no_hand_holding(w):
    texts = [lb.text().lower() for lb in w.outline.findChildren(QLabel)]
    ok(not any(any(f in t for f in FORBIDDEN) for t in texts), f"{w.__class__.__name__}: no legend, no explaining text in the outline column ({[t for t in texts if t][:4]})")


# =========================================================================================================== the tree and the Details (all windows)
WANT = {"2D FEA": ["Geometry", "Material and analysis", "Mesh", "Supports", "Loads", "Results"],
        "1D FEA": ["Geometry", "Material and analysis", "Joints", "Ties", "Mesh", "Supports", "Loads", "Results"],
        "2D CFD": ["Geometry", "Fluid and flow", "Domain", "Mesh", "Solver", "Results"]}
fea = physics_tab.PhysicsTab(Win())
beam = beam_tab.BeamTab(Win())
cfd = cfd_tab.CFDTab(Win())
# the hidden scratch window of a study case gets no Outline (hundreds of them are built in a long study)
with sim_ui.plain_panels():
    scratch_beam = beam_tab.BeamTab(Win())
ok(getattr(scratch_beam, "outline", None) is None and scratch_beam.canvas.focus is None, "a scratch window is built without an Outline and draws everything")
ok(getattr(beam_tab.BeamTab(Win()), "outline", None) is not None, "and a window made after it has its Outline again")
for name, w in (("2D FEA", fea), ("1D FEA", beam), ("2D CFD", cfd)):
    w.resize(1200, 800)
    w.show()
    settle()
    ol = w.outline
    ok(ol.keys() == WANT[name], f"{name}: the tree is {ol.keys()}")
    ok(ol.tree.topLevelItemCount() == len(WANT[name]) and ol.tree.isHeaderHidden(), f"{name}: one tree item per node, no header")
    for k in ol.keys():
        ol.select(k)
        settle()
        shown = [x.title for x in w.sections if x.isVisibleTo(w)]
        ok(shown == [k] and ol.head.text() == f"Details of “{k}”", f"{name}: selecting {k} shows its page only ({shown})")
    no_hand_holding(w)
    ok(ol.split.orientation() == Qt.Orientation.Vertical and ol.split.count() == 2, f"{name}: Outline above, Details below, one divider between them")
    ol.split.setSizes([120, 400])
    settle()
    a = ol.split.sizes()
    ol.split.setSizes([300, 220])
    settle()
    b = ol.split.sizes()
    ok(a[0] < b[0] and a[1] > b[1], f"{name}: the divider between the Outline and the Details moves ({a} -> {b})")
    sp = w.findChildren(QSplitter)
    side = [s_ for s_ in sp if s_.orientation() == Qt.Orientation.Horizontal and s_.count() == 2]
    ok(bool(side), f"{name}: the divider between the column and the view is there")
    if side:
        side[0].setSizes([380, 700])
        settle()
        w1 = side[0].sizes()[0]
        side[0].setSizes([560, 520])
        settle()
        ok(side[0].sizes()[0] > w1, f"{name}: and it moves ({w1} -> {side[0].sizes()[0]})")
    ol.select("Results"); settle()
    ok(w.b_solve.isVisible() and not w.b_solve.visibleRegion().isEmpty(), f"{name}: Solve is in view at the top of the Results page")
    ol.select("Geometry"); settle()
    ok(not w.b_solve.isVisible(), f"{name}: and only there: no Solve bar under the Details")

# a real click on a node of the tree changes the Details
fea.outline.select("Geometry")
settle()
it = fea.outline.nodes["Loads"]["item"]
QTest.mouseClick(fea.outline.tree.viewport(), Qt.MouseButton.LeftButton, pos=fea.outline.tree.visualItemRect(it).center())
settle()
ok(fea.outline.current[0] == "Loads" and [x.title for x in fea.sections if x.isVisibleTo(fea)] == ["Loads"] and fea.canvas.focus == "loads", "a click on 'Loads' in the tree shows the Loads page and the loads")

# =========================================================================================================== 2D FEA: rows, tags, marks, what the view shows
m = sc.Model()
p = [m.add_point(*c) for c in ((0, 0), (100, 0), (100, 20), (0, 20))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
ol = fea.outline
settle(fea)
ok(ol.marks.get("Geometry") == "incomplete" and ol.marks.get("Mesh") == "incomplete" and ol.marks.get("Results") == "incomplete", f"2D FEA with no part: the marks say what is missing ({ol.marks})")
fea.set_model(m, "bar")
fea.resize(1100, 700)
settle(fea)
ok(ol.marks.get("Geometry") == "ok" and ol.marks.get("Mesh") == "update" and ol.marks.get("Supports") == "incomplete" and ol.marks.get("Loads") == "incomplete",
   f"2D FEA with a part: geometry ok, mesh can be made, no support / load yet ({ol.marks})")
fea.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
fea.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [("pt", p[1])]}, {"kind": "pressure", "p": 0.5, "targets": [("ln", ls[2])]}]
fea.after_conditions()
settle(fea)
ok(ol.item_texts("Supports") == ["Fixed 1"] and ol.item_texts("Loads") == ["Force 1", "Pressure 1"], f"the conditions are rows under their node ({ol.item_texts('Supports')}, {ol.item_texts('Loads')})")
tg = ol.tags
ok([t["letter"] for t in tg] == ["A", "B", "C"] and [t["group"] for t in tg] == ["Supports", "Loads", "Loads"], f"lettered A, B, C in the order of the table ({[t['letter'] for t in tg]})")
ok(tg[0]["colour"] == sim_tags.colour_of("support") and tg[1]["colour"] == sim_tags.colour_of("force") and tg[2]["colour"] == sim_tags.colour_of("pressure")
   and len({t["colour"] for t in tg}) == 3, "each kind has its own colour")
ok(all(t["anchor"] is not None and len(t["anchor"]) == 2 for t in tg), f"every condition has a place on the model ({[t['anchor'] for t in tg]})")
ok(abs(tg[0]["anchor"][0] - 0.0) < 1e-9 and abs(tg[1]["anchor"][0] - 100.0) < 1e-9 and abs(tg[2]["anchor"][1] - 20.0) < 1e-9, "a tag sits at its point or at the middle of its edge")
ok(ol.marks.get("Supports") == "ok" and ol.marks.get("Loads") == "ok" and ol.marks.get("Results") == "update", f"with supports and loads the solution can be made ({ol.marks})")

ARROW, GREEN = (192, 24, 43), (26, 150, 65)
ol.select("Geometry")
settle(fea)
g0 = shot(fea.canvas)
ok(fea.canvas.focus == "geometry" and not fea.canvas.tag_list, "Geometry: the bare part, no tags")
ok(count(g0, ARROW) == 0 and count(g0, GREEN) == 0, "Geometry: no load arrows, no support marks")
ol.select("Supports")
settle(fea)
s0 = shot(fea.canvas)
ok([t["letter"] for t in fea.canvas.tag_list] == ["A"], "Supports: the tag list holds the supports only")
ok(count(s0, GREEN) > 50 and count(s0, ARROW) == 0, f"Supports: the supports are drawn, the loads are not (green {count(s0, GREEN)}, arrows {count(s0, ARROW)})")
ol.select("Loads")
settle(fea)
l0 = shot(fea.canvas)
ok([t["letter"] for t in fea.canvas.tag_list] == ["B", "C"], "Loads: the tag list holds the loads only")
ok(count(l0, ARROW) > 50 and count(l0, GREEN) == 0, f"Loads: the loads are drawn, the supports are not (arrows {count(l0, ARROW)}, green {count(l0, GREEN)})")
ok(l0.pixel(*inside(fea.canvas)) == g0.pixel(*inside(fea.canvas)), "Loads: the part itself is the bare part")
# a row: only that condition
ol.select("Loads", ol.items["Loads"][0][1])
settle(fea)
f1 = shot(fea.canvas)
ok(fea.canvas.focus_item is fea.loads[0] and [t["letter"] for t in fea.canvas.tag_list] == ["B"], "the row 'Force 1' selects that one load")
ok(0 < differs(f1, g0) < 0.5 * differs(l0, g0), f"only the force is drawn, not the pressure ({differs(f1, g0)} pixels against {differs(l0, g0)} for both loads)")
ok(fea.cond_table.currentRow() == 1, "and its row in the table of the Details is the selected one (Edit selected / Remove selected work on it)")
ol.select("Loads", ol.items["Loads"][1][1])
settle(fea)
ok(fea.canvas.focus_item is fea.loads[1] and fea.cond_table.currentRow() == 2, "the row 'Pressure 1' selects the pressure")

# Mesh: only the mesh; Results: only the solution
fea.e_h.setText("6")
fea.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
ol.select("Mesh")
settle(fea)
fea.b_mesh.click()
settle(fea)
ok(fea.mesh is not None and ol.marks.get("Mesh") == "ok", "the mesh is made; Mesh has its check")
m0 = shot(fea.canvas)
ok(fea.canvas.focus == "mesh" and differs(m0, g0) > 400, f"Mesh: the view shows the mesh ({differs(m0, g0)} pixels differ from the bare part)")
ok(count(m0, ARROW) == 0 and count(m0, GREEN) == 0, "Mesh: no loads, no supports over it")
ol.select("Loads")
settle(fea)
ok(differs(shot(fea.canvas), g0) < differs(m0, g0), "going back to Loads takes the mesh off the view")
fea.canvas.sel = []
fea.show_solution(pf.solve(fea.mesh, fea.read_material(), fea.supports, [dict(x) for x in fea.loads], lambda *a, **k: None, lambda: False))
fea.field.setCurrentIndex(1)
settle(fea)
ok(ol.marks.get("Results") == "ok", "solved: Results has its check")
ol.touched = True
ol.select("Geometry")
settle(fea)
g1 = shot(fea.canvas)
ok(g1.pixel(*inside(fea.canvas)) == g0.pixel(*inside(fea.canvas)), "Geometry with a result in the window: still the bare part")
ol.select("Results")
settle(fea)
r0 = shot(fea.canvas)
ok(fea.canvas.focus == "results" and differs(r0, g1) > 2000, f"Results: the solution is drawn ({differs(r0, g1)} pixels differ)")
ok(count(r0, ARROW) == 0 and count(r0, GREEN) == 0, "Results: only the solution")
# the Solve button takes you to the solution when it is ready
ol.select("Loads")
settle(fea)
fea.result_keep = fea.result
fea.result = None
settle(fea)
ok(ol.marks.get("Results") == "update", "no solution: the lightning bolt")
fea.b_solve.clicked.disconnect()
fea.b_solve.clicked.connect(lambda: None)
ol.expect_node("Results")                          # what the Solve button does (its own handler is replaced here so that nothing is solved)
fea.result = fea.result_keep
settle(fea)
ok(ol.current[0] == "Results", "Solve pressed: when the solution is there, the view shows it")
ol.select("Loads")
settle(fea)
settle(fea)
ok(ol.current[0] == "Loads", "and only then: the person who looks elsewhere afterwards stays where they are")
# the animation pictures show the solution whatever node is selected
import anim_export
fea.e_frames.setText("4")
fea.e_dur.setText("1")
out = fea.export_animation(path_fmt=(os.path.join(tempfile.mkdtemp(), "x.gif"), "gif"))
ok(bool(out) and ol.current[0] == "Loads" and fea.canvas.focus == "loads", "exporting an animation from the Loads page: the frames are of the solution, and the view comes back to Loads")
from PIL import Image
im = Image.open(out)
im.seek(im.n_frames - 1)
ok(len(set(im.convert("RGB").getdata())) > 30, "the exported frames carry the result colours")

# =========================================================================================================== 1D FEA
bm = sc.Model()
q = [bm.add_point(0, 0), bm.add_point(1000, 0), bm.add_point(1000, 500)]
ln0 = bm.add_line(q[0], q[1])
bm.add_line(q[1], q[2])
beam.set_model(bm, "frame")
beam.set_profiles([0, 1], profiles1d.compute("rect", {"b": 20.0, "h": 40.0}))
beam.supports = [{"mode": "fixed", "targets": [q[0]]}]
beam.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[2]]}, {"kind": "dist", "frame": "global", "q1": 0.0, "q2": -2.0, "targets": [ln0]}]
beam.after_conditions()
beam.cb_auto.setChecked(False)
beam.result = None
beam.resize(1100, 700)
beam.canvas.fit()
settle(beam)
bo = beam.outline
ok(bo.item_texts("Supports") and len(bo.item_texts("Loads")) == 2, f"1D FEA: rows under Supports / Loads ({bo.item_texts('Supports')}, {bo.item_texts('Loads')})")
ok([t["letter"] for t in bo.tags] == ["A", "B", "C"] and all(t["anchor"] is not None for t in bo.tags), "1D FEA: lettered, each with a place on the frame")
ok(abs(bo.tags[2]["anchor"][0] - 500.0) < 1e-9 and abs(bo.tags[2]["anchor"][1]) < 1e-9, "a line load's tag is at the middle of its member")
ok(bo.marks.get("Geometry") == "ok" and bo.marks.get("Mesh") == "ok" and bo.marks.get("Supports") == "ok" and bo.marks.get("Results") == "update", f"1D FEA marks ({bo.marks})")
LOADC, SUPC = (192, 57, 43), (26, 150, 65)
bo.select("Geometry")
settle(beam)
bg = shot(beam.canvas)
GBASE = green(bg)                                    # (the compass in the corner has a green Y axis: it is always there)
ok(count(bg, LOADC) < 5, f"1D Geometry: members only (red {count(bg, LOADC)}, green {GBASE} of the compass)")
bo.select("Supports")
settle(beam)
bs = shot(beam.canvas)
ok(green(bs) - GBASE > 20 and count(bs, LOADC) < 5 and [t["letter"] for t in beam.canvas.tag_list] == ["A"], f"1D Supports: the supports and their tag (green {green(bs)})")
bo.select("Loads")
settle(beam)
bl = shot(beam.canvas)
ok(count(bl, LOADC) > 50 and green(bl) - GBASE < 5 and [t["letter"] for t in beam.canvas.tag_list] == ["B", "C"], "1D Loads: the loads and their tags")
bo.select("Loads", bo.items["Loads"][1][1])
settle(beam)
b1 = shot(beam.canvas)
ok(beam.canvas.focus_item is beam.loads[1] and count(b1, LOADC) > 20 and count(b1, LOADC) < count(bl, LOADC), "1D: the row of the line load draws only that load")
beam.solve()
settle(beam)
ok(beam.result is not None and bo.marks.get("Results") == "ok", "1D solved")
bo.select("Mesh")
settle(beam)
bm0 = shot(beam.canvas)
ok(beam.canvas.focus == "mesh" and count(bm0, LOADC) < 5 and green(bm0) - GBASE < 5, "1D Mesh: the members with their element nodes, nothing else")
bo.select("Results")
settle(beam)
br = shot(beam.canvas)
ok(differs(br, bg) > 500, f"1D Results: the solution ({differs(br, bg)} pixels differ from the bare frame)")

# =========================================================================================================== 2D CFD
co = cfd.outline
cfd.canvas.focus = None
co.select("Domain")
settle(cfd)
ok(cfd.canvas.focus == "domain", "CFD: the Domain page shows the domain")
co.select("Mesh")
settle(cfd)
ok(cfd.canvas.focus == "mesh" and not cfd.canvas.tag_list, "CFD: the Mesh page shows the mesh")
co.select("Results")
settle(cfd)
ok(cfd.canvas.focus == "results", "CFD: Results shows the solution")
co.select("Fluid and flow")
settle(cfd)
ok(cfd.canvas.focus == "geometry" and not co.item_texts("Domain"), "CFD: the pages about the fluid show the bare part; there are no rows to add under the nodes")
cfd.canvas.repaint()

# =========================================================================================================== thermal 2D
import thermal_tab as tt
th = tt.ThermalTab(Win())
th.resize(1100, 700)
th.show()
settle()
tn = th.outline.keys()
ok(tn[:2] == ["Geometry", "Material and analysis"] and "Mesh" in tn and "Results" in tn and ("Conditions" in tn or ("Supports" in tn and "Loads" in tn)), f"thermal 2D: the tree is {tn}")
no_hand_holding(th)
th.set_model(m, "plate")
th.supports = [{"kind": "temp", "T": 373.15, "targets": [("ln", ls[3])]}]
th.loads = [{"kind": "conv", "h": 20.0, "Tinf": 293.15, "targets": [("ln", ls[1])]}, {"kind": "ins", "targets": [("ln", ls[0])]}]
th.refresh_lists()
th.canvas.fit()
settle(th)
node = "Conditions" if "Conditions" in tn else "Supports"
ok(len(th.outline.tags) == 3 and [t["letter"] for t in th.outline.tags] == ["A", "B", "C"], f"thermal 2D: three conditions, lettered ({[t['letter'] for t in th.outline.tags]})")
ok([t["kind"] for t in th.outline.tags] == ["temperature", "convection", "insulated"] and len({t["colour"] for t in th.outline.tags}) == 3, "thermal: a colour for temperature, convection, insulation")
th.outline.select("Geometry")
settle(th)
t_g = shot(th.canvas)
th.outline.select(node)
settle(th)
t_c = shot(th.canvas)
ok(differs(t_c, t_g) > 300 and th.canvas.tag_list, f"thermal: the conditions page shows the conditions and their tags ({differs(t_c, t_g)} pixels)")
th.outline.select(node, th.outline.items[node][1][1])
settle(th)
ok(th.canvas.focus_item is th.loads[0] and [t["letter"] for t in th.canvas.tag_list] == ["B"], "thermal: a row shows just that condition")

# =========================================================================================================== 3D FEA
import pm_model as pm, sk_tools as sk
import solid_tab
T = tempfile.mkdtemp(prefix="opara_so_")
d = pm.Document()
d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
d.rebuild()
mm = d.models[s["id"]]
r_ = sk.add_rect_corner(mm, (0, 0), (100, 10))
mm.add_con("dim_h", [("ln", r_["lns"][0])], value=100.0)
mm.add_con("dim_v", [("ln", r_["lns"][1])], value=10.0)
sk.solve_model(mm)
d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T"))
d.rebuild()
part = os.path.join(T, "bar.gpd")
open(part, "w").write(d.to_json())
w3 = solid_tab.SolidWindow(threaded=False)
w3.resize(1200, 800)
w3.show()
settle()
ok(w3.outline.keys() == ["Geometry", "Material and analysis", "Mesh", "Supports", "Loads", "Results"], f"3D FEA: the tree is {w3.outline.keys()}")
no_hand_holding(w3)
ok(w3.create_project(os.path.join(T, "bar_o")) and w3.import_file(part), "3D FEA: a part is imported")
settle(w3)
ok(w3.outline.marks.get("Geometry") == "ok" and w3.outline.marks.get("Supports") == "incomplete" and w3.outline.marks.get("Mesh") == "update", f"3D marks before conditions ({w3.outline.marks})")


def face(n):
    return next(f["id"] for f in w3.geom["faces"] if np.dot(f["normal"], n) > 0.99)


w3.select_faces([face([-1, 0, 0])])
w3.add_support("fixed")
w3.select_faces([face([1, 0, 0])])
w3.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w3.select_faces([face([0, 0, 1])])
w3.add_load("pressure", {"p": 2.0})
settle(w3)
o3 = w3.outline
ok(o3.item_texts("Supports") == ["Fixed support 1"] and len(o3.item_texts("Loads")) == 2, f"3D rows: {o3.item_texts('Supports')}, {o3.item_texts('Loads')}")
ok([t["letter"] for t in o3.tags] == ["A", "B", "C"] and all(t["anchor"] is not None and len(t["anchor"]) == 3 for t in o3.tags), "3D: lettered, each with a 3D place (the centre of its face)")
ok(abs(o3.tags[0]["anchor"][0]) < 1e-9 and abs(o3.tags[1]["anchor"][0] - 100.0) < 1e-9, f"3D: the tag of the fixed face is at x = 0, the force's at x = 100 ({o3.tags[0]['anchor']}, {o3.tags[1]['anchor']})")
o3.select("Supports")
settle(w3)
ok(w3.view.focus == "supports" and [t["letter"] for t in w3.view.tags] == ["A"], "3D Supports: the view is told: supports, tag A")
w3.view.tag_names and ok(w3.view.tag_names == ["tag_A"], f"3D: a chip at the condition on the model ({w3.view.tag_names})")
cols = {}
w3.condition_colours(cols)
ok(set(cols) == {face([-1, 0, 0])} and cols[face([-1, 0, 0])] == solid_tab.sv.SUPPORT, "3D Supports: only the supported face is coloured")
o3.select("Loads")
settle(w3)
cols = {}
w3.condition_colours(cols)
ok(set(cols) == {face([1, 0, 0]), face([0, 0, 1])} and all(c == solid_tab.sv.LOAD for c in cols.values()), "3D Loads: only the faces of the loads are coloured")
o3.select("Loads", o3.items["Loads"][0][1])
settle(w3)
cols = {}
w3.condition_colours(cols)
ok(set(cols) == {face([1, 0, 0])} and [t["letter"] for t in w3.view.tags] == ["B"], "3D: the row of the force colours only the force's face")
o3.select("Geometry")
settle(w3)
cols = {}
w3.condition_colours(cols)
ok(cols == {} and w3.view.tags == [], "3D Geometry: the bare part, no colours, no tags")
w3.set_size("6")
w3.inputs_changed()
o3.select("Mesh")
settle(w3)
w3.b_mesh.click()
settle(w3)
ok(w3.mesh_q is not None and o3.marks.get("Mesh") == "ok", "3D: meshed")
if w3.view.plotter is not None:
    ok(w3.view.focus_mesh_actor is not None and w3.view.focus_mesh_actor.GetVisibility() and not w3.view.actor.GetVisibility(), "3D Mesh: the mesh is on show, the part is not")
    o3.select("Geometry")
    settle(w3)
    ok(w3.view.focus_mesh_actor is None and w3.view.actor.GetVisibility(), "3D Geometry: the mesh is taken off, the bare part is back")
w3.select_faces([face([0, 1, 0])])
w3.set_size("6")
w3.e_face_h.setText("3")
w3.cb_adv.setChecked(True)
ok(w3.set_face_size() and len(w3.setup["mesh"]["face_sizes"]) == 1, "3D: a local element size is set")
settle(w3)
ok(len(o3.item_texts("Mesh")) == 1 and "3" in o3.item_texts("Mesh")[0], f"3D: the local size is a row under Mesh ({o3.item_texts('Mesh')})")
o3.select("Mesh", o3.items["Mesh"][0][1])
settle(w3)
ok(w3.face_table.currentRow() == 0 and w3.sel_faces, "3D: its row selects it in the sizes table and its face on the part")
w3.run_mesh()
w3.run_solve()
settle(w3)
ok(w3.result is not None and o3.marks.get("Results") == "ok", "3D solved")
o3.select("Results")
settle(w3)
if w3.view.plotter is not None:
    ok(w3.view.result_actor is not None and w3.view.result_actor.GetVisibility() and not w3.view.actor.GetVisibility(), "3D Results: the solution is on show")
    o3.select("Loads")
    settle(w3)
    ok(not w3.view.result_actor.GetVisibility() and w3.view.actor.GetVisibility(), "3D Loads: the solution is hidden, the part is shown")
    o3.select("Results")
    settle(w3)
    ok(w3.view.result_actor.GetVisibility(), "and Results brings it back without solving again")

# =========================================================================================================== 3D thermal
import thermal3d_tab as t3
tw = t3.ThermalWindow(threaded=False)
tw.resize(1200, 800)
tw.show()
settle()
tw_keys = tw.outline.keys()
ok("Conditions" in tw_keys or "Supports" in tw_keys, f"3D thermal: the tree is {tw_keys}")
no_hand_holding(tw)
ok(tw.load_example(os.path.join(T, "example.gpt")) is True, "3D thermal: the test example loads")
settle(tw)
n_cond = len(tw.outline.tags)
ok(n_cond == 7 and [t["letter"] for t in tw.outline.tags] == list("ABCDEFG"), f"3D thermal: seven conditions A to G ({n_cond})")
ok(len({t["kind"] for t in tw.outline.tags}) >= 4 and all(t["anchor"] is not None for t in tw.outline.tags), f"3D thermal: their kinds {sorted({t['kind'] for t in tw.outline.tags})}, each placed")
tw.outline.select("Conditions")
settle(tw)
ok(tw.view.focus == "conditions" and len(tw.view.tags) == 7, "3D thermal: the Conditions page tells the view all seven tags")
tw.outline.select("Conditions", tw.outline.items["Conditions"][2][1])
settle(tw)
ok([t["letter"] for t in tw.view.tags] == ["C"], "3D thermal: a row: its one tag")

if BAD:
    print(f"\nFAILED ({len(BAD)}):")
    for b in BAD:
        print("  -", b)
    os._exit(1)
print("\nall passed")
os._exit(0)
