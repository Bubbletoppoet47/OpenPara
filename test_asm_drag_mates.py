"""Dragging a part that is only partly mated (Ian's Test Assembly: a square tube butted on the side of another, its edge on the other's top):
pushing into the face never tears the mates, sliding along it follows smoothly, and every step is on the mates."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
import asm_model as am, pm_model as pm

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data", "ta")
text = open(os.path.join(HERE, "Assembly", "Test Assembly.gpa")).read()
docs = {}


def solid_fn(c):
    p = os.path.normpath(os.path.join(HERE, "Assembly", c["path"].replace("\\", "/")))
    if p not in docs:
        d = pm.Document.from_json(open(p).read()); d.rebuild(); docs[p] = d
    return docs[p].solid


def fresh():
    a = am.Assembly.from_json(text); a.solid_fn = solid_fn; assert a.solve(); return a


GRAB = np.array([19.05, 0, -12.7])


def drag(a, dirv, n=60, step=8.0):
    c = a.components[1]; R0, t0 = a.pose(c); cl = a.cluster(c["id"]); a.drag_reset()
    prev = a.pose(c); worst_move = worst_rot = worst_res = 0.0; fails = 0
    for k in range(1, n + 1):
        ok = a.solve(drag={c["id"]: (R0, t0 + np.array(dirv, float) * step * k)}, limit=cl, grab={c["id"]: GRAB})
        fails += (not ok)
        R, t = a.pose(c)
        worst_move = max(worst_move, np.linalg.norm(t - prev[1]))
        worst_rot = max(worst_rot, np.degrees(np.arccos(np.clip((np.trace(R.T @ prev[0]) - 1) / 2, -1, 1))))
        worst_res = max(worst_res, max(np.abs(a.mate_residual(m)).max() for m in a.mates))
        prev = (R, t)
    return worst_move, worst_rot, worst_res, fails, prev


for name, dv in (("along the tube below", (0, 1, 0)), ("back", (0, -1, 0)), ("into the face", (-1, 0, 0)), ("away", (1, 0, 0)), ("up", (0, 0, 1)),
                 ("down", (0, 0, -1)), ("diagonal", (0.7, 0.7, 0.3))):
    a = fresh()
    mv, rot, res, fails, end = drag(a, dv)
    print(f"{name:22s} biggest step {mv:6.2f} mm  {rot:5.2f} deg   worst mate residual {res:.1e}   failed steps {fails}")
    assert fails == 0 and res < 1e-4, (name, fails, res)
    assert mv < 12.0 and rot < 2.0, (name, mv, rot)          # a step is never more than the mouse moved (8 mm)
a = fresh(); c = a.components[1]; R0, t0 = a.pose(c)
mv, rot, res, fails, end = drag(a, (-1, 0, 0), n=80)
assert abs(end[1][0] - t0[0]) < 1e-3, "the tube went through the face it butts on"      # still on the face (world x unchanged)
mv, rot, res, fails, end = drag(fresh(), (0, 1, 0), n=40)
assert abs(end[1][1] - (t0[1] + 8.0 * 40)) < 1e-3, end[1]                                  # it slid the full way along the free direction
print("OK asm drag with partial mates")
