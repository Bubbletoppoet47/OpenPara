"""Driven (measured) and driving dimensions; a dimension whose equation uses a measured value is solved in the same system (a proportion)."""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sketcher_core as sc, sk_tools as sk

def build():
    m = sk.new_model()
    l1 = sk.add_line(m, (0, 0), (30, 0)); a, b = m.lns[l1]
    sk.con(m, "coincident", [("pt", a), ("pt", 0)])
    sk.con(m, "dim_h", [("ln", l1)], value=30.0, sign=1)                        # the input that sets line 1
    l2 = sk.add_line(m, (0, 10), (50, 10)); c, d = m.lns[l2]
    sk.con(m, "fixed", [("pt", c)], xy=(0.0, 10.0))
    return m, l1, l2

# 1. A measures line 1 (driven), B = 2 * A drives line 2: B ends up 60
m, l1, l2 = build()
m.add_param("A", 30.0, is_input=False)
ca = sk.con(m, "dim_len", [("ln", l1)], value=30.0, expr="A", name="A")
cb = sk.con(m, "dim_len", [("ln", l2)], value=50.0, expr="2*A", name="B")
rep = sk.solve_model(m)
ca, cb = m.con_by_id(ca["id"]), m.con_by_id(cb["id"])
assert ca["driven"] and not ca["coupled"], ca
assert cb["coupled"] and not cb["driven"], cb
(x0, y0), (x1, y1) = m.line_pts(l2)
print("line 2 length", math.hypot(x1 - x0, y1 - y0), "dof", rep.dof, "conflicts", rep.conflicts)
assert abs(math.hypot(x1 - x0, y1 - y0) - 60.0) < 1e-6 and not rep.conflicts
assert abs(m.params["A"]["vals"][0] - 30.0) < 1e-6 and abs(cb["value"] - 60.0) < 1e-6
# change the input: line 2 follows
dh = [c for c in m.cons if c["type"] == "dim_h"][0]; dh["value"] = 40.0
rep = sk.solve_model(m); (x0, y0), (x1, y1) = m.line_pts(l2)
assert abs(math.hypot(x1 - x0, y1 - y0) - 80.0) < 1e-6 and abs(m.params["A"]["vals"][0] - 40.0) < 1e-6
# 2. A as an ordinary input (driving): B = 2 * A is just a formula of an input
m2, l1, l2 = build()
m2.add_param("A", 30.0, is_input=True)
sk.con(m2, "dim_len", [("ln", l1)], value=30.0, expr="A", name="A")
cb2 = sk.con(m2, "dim_len", [("ln", l2)], value=50.0, expr="2*A", name="B")
rep = sk.solve_model(m2); c2 = m2.con_by_id(cb2["id"])
assert not c2["driven"] and not c2["coupled"]
(x0, y0), (x1, y1) = m2.line_pts(l2); assert abs(math.hypot(x1 - x0, y1 - y0) - 60.0) < 1e-6
# 3. a loop: B = 2 * A with A measuring B's own line
m3, l1, l2 = build()
m3.add_param("A", 30.0, is_input=False)
sk.con(m3, "dim_len", [("ln", l2)], value=50.0, expr="A", name="A")
cb3 = sk.con(m3, "dim_len", [("ln", l2)], value=50.0, expr="2*A", name="B")
rep = sk.solve_model(m3)
assert cb3["id"] in rep.conflicts and any("loop" in x for x in rep.messages), (rep.conflicts, rep.messages)
# 4. Make driven / Make driving (the toggle): plain dimension, dimension with its own equation, undo-free round trip
m4, l1, l2 = build()
cplain = sk.con(m4, "dim_len", [("ln", l2)], value=50.0, name="L2")
sk.solve_model(m4)
m4.set_driven(cplain["id"], True); rep = sk.solve_model(m4)
c4 = m4.con_by_id(cplain["id"]); assert c4["driven"] and c4["expr"] == "L2" and not m4.params["L2"]["input"]
assert abs(m4.params["L2"]["vals"][0] - 50.0) < 1e-6                      # it measures what the line is (50)
(x0, y0), (x1, y1) = m4.line_pts(l2); assert abs(math.hypot(x1 - x0, y1 - y0) - 50.0) < 1e-6
assert rep.dof == 1                                                       # the length is free now (the constraint is gone)
m4.set_driven(cplain["id"], False); rep = sk.solve_model(m4)
c4 = m4.con_by_id(cplain["id"]); assert not c4["driven"] and rep.dof == 0 and m4.params["L2"]["input"]
# its own equation is kept aside and comes back
m5, l1, l2 = build()
m5.add_param("W", 20.0)
ce = sk.con(m5, "dim_len", [("ln", l2)], value=40.0, expr="W*2", name="Q")
sk.solve_model(m5); m5.set_driven(ce["id"], True); sk.solve_model(m5)
c5 = m5.con_by_id(ce["id"]); assert c5["driven"] and c5["expr_saved"] == "W*2"
m5.set_driven(ce["id"], False); sk.solve_model(m5)
c5 = m5.con_by_id(ce["id"]); assert not c5["driven"] and c5["expr"] == "W*2" and "expr_saved" not in c5 and not any(p.get("made") for p in m5.params.values())
(x0, y0), (x1, y1) = m5.line_pts(l2); assert abs(math.hypot(x1 - x0, y1 - y0) - 40.0) < 1e-6
print("OK driven")

# 5. the window: Make driven / Make driving is offered in an assembly sketch only, and the drawing shows (value) in the driven colour
os.environ["OPARA_USER_DIR"] = __import__("tempfile").mkdtemp()
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import gpd_app, pm_app, asm_sketch as ak, settings
sh = gpd_app.AppShell([]); sw = sh.new_asm_sketch()
f = ak.sketch_feature(sw.doc); sw.enter_sketch(f["id"]); ed = sw.ed; ed.size_fn = lambda: (1000.0, 700.0); m = ed.m
lid = sk.add_line(m, (0, 0), (30, 0)); a, b = m.lns[lid]; cd = sk.con(m, "dim_len", [("ln", lid)], value=30.0)
sw.doc.reports[f["id"]] = sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all()
ed.sel = [("con", cd["id"])]
assert "Make driven" in [n for n, _ in ed.context_actions(-10000, -10000)]
ed.toggle_driven(cd["id"]); c = ed.m.con_by_id(cd["id"]); assert c["driven"]
ed.sel = [("con", cd["id"])]; assert "Make driving" in [n for n, _ in ed.context_actions(-10000, -10000)]
assert ed.dim_actors[cd["id"]], "drawn"
ed.toggle_driven(cd["id"]); c = ed.m.con_by_id(cd["id"]); assert not c["driven"]
plain = pm_app.MainWindow(); plain.sel_plane = "Front"; plain.command("sketch"); pe = plain.ed; pe.size_fn = lambda: (1000.0, 700.0)
pl = sk.add_line(pe.m, (0, 0), (30, 0)); pc = sk.con(pe.m, "dim_len", [("ln", pl)], value=30.0); plain.doc.reports[plain.sel] = sk.solve_model(pe.m); plain.doc.store_sketch(plain.sel); plain.update_all()
pe.sel = [("con", pc["id"])]
assert not [n for n, _ in pe.context_actions(-10000, -10000) if n.startswith("Make driv")] and sw.asm_sketch
print("OK driven window")
