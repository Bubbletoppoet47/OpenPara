import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import math
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se, sk_tools as sk
w = pm_app.MainWindow()
def _form(parent, title, fields, checks=(), **kw):
    if "Polygon" in title: return ([6.0], [])
    if "fillet" in title: return ([4.0], [])
    if "Linear" in title: return ([2.0, 5.0, 0.0], [])
    if "Move" in title: return ([1.0, 2.0], [])
    if "Circular" in title: return ([3, 90.0, 0, 0], [])
    return ([3.0, 0, 0][:len(fields)], [False, True, True][:len(checks)])
se.ask_form = _form
ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.doc.params = {"Length": "40"}; w.sel = None; w.update_all(fit=True)
w.sel_plane = "Front"; w.command("sketch")
assert ed.active and not ed.edge_on()
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v):
    ed.press(*px(u, v)); ed.release(*px(u, v))
def m(): return ed.m
for uv in [(0, 0), (12.5, -7.25), (-30, 20)]:
    p = px(*uv); back = ed.to_plane(*p); assert abs(back[0] - uv[0]) < 1e-6
# --- rectangle (corner) by two clicks: 4 lines, auto horizontal/vertical, dof 4
w.set_tool("rect_corner"); click(-20, -10); click(20, 10)
print("rect:", len(m().lns), "lines, dof", ed.rep.dof); assert len(m().lns) == 4 and ed.rep.dof == 4
# --- a hole circle inside
w.set_tool("circle"); click(0, 0); click(5, 0)
assert len(m().cis) == 1
# --- extrude: rect with a hole
sid = w.sel; w.leave_sketch(); w.sel = sid; w.command("extrude"); f = w.doc.feature(w.sel); f["depth"] = "10"; w.update_all(); w.pm_ok()
v = w.doc.solid.volume; print("volume", v, "expected", (800 - math.pi * 25) * 10)
assert abs(v - (800 - math.pi * 25) * 10) < 1, v
# --- reopen, dimension the width with a global, check it follows the global
w.enter_sketch(sid)
horiz = [i for i, (a, b) in m().lns.items() if abs(m().pts[a][1] - m().pts[b][1]) < 1e-6][0]
se.ask_dim = lambda parent, title, text, syms: "Length"
w.relation_command("dim_h"); click(0, -10)          # bottom edge
print("dims:", [(c["type"], c.get("expr"), round(c["value"], 3)) for c in m().cons if c["type"] in se.DIMS])
assert any(c.get("expr") == "Length" for c in m().cons)
w.leave_sketch(); w.doc.params["Length"] = "60"; w.update_all()
b = w.doc.solid.bounding_box(); print("width after Length=60:", b.size.X); assert abs(b.size.X - 60) < 1e-6
# --- drag a corner point with the solver
w.enter_sketch(sid)
before = [tuple(p) for p in m().pts.values()]
ed.press(*px(30, 10)); ed.move(*px(30, 10)); ed.move(*px(31, 14)); ed.release(*px(31, 14))
print("dragged, dof", ed.rep.dof)
# --- undo of the drag
w.do_undo(); print("undo ok", ed.active)
w.leave_sketch()
# --- new sketch: every tool
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Top"; w.command("sketch"); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
def tool(name, *pts, expect=None):
    w.set_tool(name)
    for p in pts: click(*p)
    n = (len(m().lns), len(m().cis), len(m().ars))
    print(f"{name:16s} lines/circles/arcs = {n}  dof {ed.rep.dof}  ok {ed.rep.ok}")
    return n
tool("midline", (-60, 40), (-50, 40))
tool("centerline", (0, 0), (30, 0))
tool("rect_center", (-30, -30), (-20, -25))
tool("rect_3pt", (10, -40), (20, -35), (15, -30))
tool("parallelogram", (30, -40), (40, -40), (45, -30))
tool("circle_3pt", (50, 0), (60, 10), (50, 20))
tool("arc_center", (-60, 0), (-50, 0), (-60, 10))
tool("arc_3pt", (-40, 0), (-30, 0), (-35, 5))
tool("slot_straight", (-70, -40), (-50, -40), (-50, -35))
tool("slot_arc_center", (80, 0), (90, 0), (80, 10), (95, 5))
tool("polygon", (70, 40), (75, 40))
tool("point", (0, 40))
print("tools done: model dof", ed.rep.dof, "conflicts", ed.rep.conflicts)
assert not ed.rep.conflicts
# tangent arc from the end of the centerline? use a normal line first
w.set_tool("line"); click(-60, -60); click(-40, -60); ed.cancel()
w.set_tool("arc_tangent"); click(-40, -60); click(-30, -50)
print("tangent arc: arcs", len(m().ars))
# --- selection, mirror about the centerline, pattern, move, trim
cl = [i for i in m().lns if ("ln", i) in m().constr][-1]
w.set_tool("select")
ed.sel = [("ci", list(m().cis)[0])]
n0 = len(m().cis); ed.command_mirror(); a, b = m().line_pts(cl); mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); click(*mid)
print("mirror: circles", n0, "->", len(m().cis)); assert len(m().cis) == n0 + 1
ed.sel = [("ci", list(m().cis)[0])]; n0 = len(m().cis); ed.command_linear(); print("linear pattern:", n0, "->", len(m().cis)); assert len(m().cis) == n0 + 2
ed.sel = [("ci", list(m().cis)[0])]; n0 = len(m().cis); ed.command_circular(); print("circular pattern:", n0, "->", len(m().cis)); assert len(m().cis) == n0 + 3
pp = [i for i in m().pts if abs(m().pts[i][0]) < 1e-9 and abs(m().pts[i][1] - 40) < 1e-9][0]
ed.sel = [("pt", pp)]; ed.command_move(); c1 = m().pts[pp]; print("move", c1); assert abs(c1[0] - 1) < 1e-6 and abs(c1[1] - 42) < 1e-6
# fillet a rectangle corner
w.set_tool("rect_corner"); click(100, 50); click(130, 70)
se_r = ed.fillet_r; w.set_tool("fillet") if False else (ed.reset_tool("fillet")); n0 = len(m().ars); click(100, 50); print("fillet arcs", n0, "->", len(m().ars)); assert len(m().ars) == n0 + 1
# trim: cross two lines then trim a piece
ed.reset_tool("line"); click(100, 90); click(130, 90); ed.cancel(); w.set_tool("line"); click(115, 80); click(115, 100); ed.cancel()
nl = len(m().lns); ed.reset_tool("trim"); click(115, 95); print("trim: lines", nl, "->", len(m().lns))
# delete + undo
ed.reset_tool("select"); ed.press(*px(115, 85)); k = list(ed.sel); print("selected", k); ed.release(*px(115, 85))
nl = len(m().lns); ed.delete_selected(); print("delete", nl, "->", len(m().lns)); w.do_undo(); print("undo", len(m().lns))
# preview drawing does not crash
w.set_tool("slot_arc_3pt"); click(0, 70); click(20, 70); ed.move(*px(10, 75)); ed.redraw(); ed.reset_tool("select")
print("OK")
