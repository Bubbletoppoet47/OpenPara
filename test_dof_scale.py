"""Degrees of freedom do not depend on the size of the sketch: an angle on a 7.6 m roof counts as much as a length."""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, copy, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sk_tools as sk
m = sk.new_model()
span, rise = 7600.0, 1900.0
l1 = sk.add_line(m, (0, 0), (span, 0)); a, b = m.lns[l1]
l2 = sk.add_line(m, (span, 0), (span / 2, rise)); c, d = m.lns[l2]
l3 = sk.add_line(m, (span / 2, rise), (0, 0)); e, f = m.lns[l3]
sk.con(m, "coincident", [("pt", a), ("pt", 0)])
sk.con(m, "coincident", [("pt", b), ("pt", c)]); sk.con(m, "coincident", [("pt", d), ("pt", e)]); sk.con(m, "coincident", [("pt", f), ("pt", a)])
sk.con(m, "horizontal", [("ln", l1)])
sk.con(m, "dim_len", [("ln", l1)], value=span, name="Span")
pitch = sk.con(m, "dim_ang", [("ln", l1), ("ln", l3)], value=math.degrees(math.atan2(rise, span / 2)), name="Pitch_Angle")
sk.con(m, "equal", [("ln", l2), ("ln", l3)])
rep = sk.solve_model(m)
print("dof", rep.dof, "free", len(rep.free_pts), "redundant", rep.redundant)
assert rep.dof == 0 and not rep.free_pts and not rep.conflicts and pitch["id"] not in rep.redundant
mm = copy.deepcopy(m); mm.cons = [c for c in mm.cons if c["id"] != pitch["id"]]
r2 = sk.solve_model(mm); assert r2.dof == 1 and r2.free_pts, r2.dof
print("OK dof scale")
