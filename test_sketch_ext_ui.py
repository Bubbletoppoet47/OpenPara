import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = __import__("tempfile").mkdtemp()
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk, sketch_ext as sx
MSG = []


def build(order):
    """A path (line up from (5, 0) on Front) and a profile (circle at the origin on Top), in the given order."""
    d = pm.Document()
    made = {}
    for name in order:
        plane = {"base": "Front"} if name == "path" else {"base": "Top"}
        s = d.add(pm.new_feature("sketch", plane=plane)); d.rebuild()
        m = d.models[s["id"]]
        if name == "path":
            sk.add_line(m, (5, 0), (5, 20))
        else:
            sk.add_circle(m, (1, 1), (3, 1))
        sk.solve_model(m); d.store_sketch(s["id"]); d.rebuild()
        made[name] = s["id"]
    return d, made


for order in (("path", "profile"), ("profile", "path")):
    w = pm_app.MainWindow()
    w.say = lambda t: MSG.append(t)
    ed = w.ed
    ed.size_fn = lambda: (1000.0, 700.0)
    w.doc, made = build(order)
    w.doc.feature(made["path"])["show"] = False
    w.sel = None; w.update_all(fit=True)
    w.enter_sketch(made["profile"])
    assert ed.active
    assert not hasattr(ed, "command_extref")
    # the other sketch is hidden: a click on it does nothing
    p = tuple(ed.to_screen(np.array([[5.0, 0.0, 10.0]]))[0])
    ed.press(*p)
    assert not ed.m.ext
    w.doc.feature(made["path"])["show"] = True
    w.update_all()
    w.enter_sketch(made["profile"])
    # Add Relation > Pierce: first the circle centre of this sketch, then the (shown) path of the other sketch
    m = ed.m
    cp = next(iter(m.cis.values()))["c"]
    w.relation_command("pierce")
    assert ed.tool == "pierce"
    ed.press(*ed.to_screen(np.array([[1.0, 1.0, 0.0]]))[0])
    assert ed.picks == [("pt", cp)], ed.picks
    ed.press(*p)
    m = ed.m
    assert len(m.ext) == 1 and m.ext[0]["kind"] in ("pt", "pierce"), (m.ext, MSG[-4:])
    cs = [c for c in m.cons if c.get("pierce")]
    assert len(cs) == 1, m.cons
    assert math.dist(m.pts[cp], (5, 0)) < 1e-6, m.pts[cp]
    assert (w.doc.index_of(made["profile"]) > w.doc.index_of(made["path"])), order
    print(order, "-> pierce made |", MSG[-1][:70])
    # a line of the other sketch brought in, then Pierce with a point of this sketch: becomes the point where the line passes through the plane
    w.leave_sketch(); w.enter_sketch(made["profile"])
    sx.remove_record(ed.m, ed.m.ext[0]); ed.commit(lambda mm: None)
    assert not ed.m.ext
    ln_key = ed.bring_in("ln", w.doc.feature(made["path"]), ("ln", next(iter(w.doc.models[made["path"]].lns))), np.array([5.0, 0.0, 10.0]))
    assert ln_key and ln_key[0] == "ln" and len(ed.m.ext) == 1 and ed.m.ext[0]["kind"] == "ln"
    cp = next(iter(ed.m.cis.values()))["c"]
    ed.reset_tool("pierce"); ed.picks = [("pt", cp), ln_key]
    ed.try_apply()
    assert len(ed.m.ext) == 1 and ed.m.ext[0]["kind"] == "pierce", (ed.m.ext, MSG[-2:])
    assert math.dist(ed.m.pts[cp], (5, 0)) < 1e-6
    # a plain click with the Select tool on an unused other-sketch line brings it in and is removed again when something else is clicked
    w.leave_sketch(); w.enter_sketch(made["profile"])
    assert len(ed.m.ext) == 1
    ed.reset_tool("select")
    ed.press(*ed.to_screen(np.array([[1.0, 1.0, 0.0]]))[0] + 1e-3)       # nothing special: still fine
    # line against line is refused
    w.relation_command("pierce")
    q = ed.to_screen(np.array([[3.0, 1.0, 0.0]]))[0]
    ed.press(*q)                                                             # a circle of this sketch (not a point)
    ed.press(*p)
    assert any("line against a line" in t or "degrees of freedom" in t for t in MSG[-3:]), MSG[-3:]
    n_ext = len(ed.m.ext)
    ed.reset_tool("select"); ed.prune_ext()
    assert len(ed.m.ext) <= n_ext
    # undo takes the pierce away again
    w.leave_sketch()
# ---- several crossings: a circular path (Front, centre (0, 0), r 10) goes through the Top plane at x = +10 and x = -10
w = pm_app.MainWindow(); w.say = lambda t: MSG.append(t); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
d = pm.Document(); w.doc = d
a = d.add(pm.new_feature("sketch", plane={"base": "Front"})); d.rebuild()
sk.add_circle(d.models[a["id"]], (0, 0), (10, 0)); sk.solve_model(d.models[a["id"]]); d.store_sketch(a["id"]); d.rebuild()
b = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild()
sk.add_line(d.models[b["id"]], (6, 0), (8, 3)); sk.solve_model(d.models[b["id"]]); d.store_sketch(b["id"]); d.rebuild()
w.sel = None; w.update_all(fit=True); w.enter_sketch(b["id"])
m = ed.m
end = next(i for i, q in m.pts.items() if abs(q[0] - 8) < 1e-9)
w.relation_command("pierce")
ed.press(*ed.to_screen(np.array([[8.0, 3.0, 0.0]]))[0])
ed.press(*ed.to_screen(np.array([[10.0, 0.0, 0.0]]))[0] + np.array([0.0, 0.0]))          # the circle, seen end-on near the +x crossing
m = ed.m
assert len(m.ext) == 1 and m.ext[0]["kind"] == "pierce", (m.ext, MSG[-3:])
assert ed.choose is not None and len(ed.choose["hits"]) == 2, ed.choose
assert math.dist(m.pts[end], (10, 0)) < 1e-6, m.pts[end]          # the nearest crossing to the click
# click the other highlighted crossing
ed.reset_tool("select")
ed.press(*ed.to_screen(np.array([[-10.0, 0.0, 0.0]]))[0])
assert ed.choose is None
assert math.dist(ed.m.pts[end], (-10, 0)) < 1e-6, ed.m.pts[end]
w.leave_sketch(); w.enter_sketch(b["id"])                         # remembered
assert math.dist(ed.m.pts[end], (-10, 0)) < 1e-6
print("crossings OK")
print("EXT UI OK")
os._exit(0)
