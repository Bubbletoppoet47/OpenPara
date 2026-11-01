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
            sk.add_circle(m, (0, 0), (3, 0))
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
    # nothing is shown yet: the tool says so and does not start
    w.enter_sketch(made["profile"])
    assert ed.active
    assert not ed.command_extref("pierce") and "Show the other sketch" in MSG[-1], MSG[-1]
    # show the path sketch (its tree checkbox), then start the tool
    w.doc.feature(made["path"])["show"] = True
    w.update_all()
    w.enter_sketch(made["profile"])
    assert ed.command_extref("pierce") and ed.tool == "extref"
    # a click far away from it does nothing
    ed.press(5.0, 5.0)
    assert not ed.m.ext and ed.tool == "extref"
    # click on the path (seen end-on from above: one spot on the screen)
    p = tuple(ed.to_screen(np.array([[5.0, 0.0, 10.0]]))[0])
    ed.press(*p)
    m = ed.m
    assert len(m.ext) == 1 and m.ext[0]["kind"] == "pierce", m.ext
    assert ed.tool == "select"
    assert math.dist(m.pts[m.ext[0]["pt"]], (5, 0)) < 1e-9
    moved = order[0] == "profile"
    assert (w.doc.index_of(made["profile"]) > w.doc.index_of(made["path"])), order
    print(order, "-> pierce point placed", "(profile moved behind the path)" if moved else "", "|", MSG[-1][:70])
    # tie the circle centre to it with the normal relation tool, and undo takes everything back in one step
    cp = next(iter(m.cis.values()))["c"]
    ed.commit(lambda mm: sk.con(mm, "coincident", [("pt", cp), ("pt", m.ext[0]["pt"])]) and None)
    assert math.dist(ed.m.pts[cp], (5, 0)) < 1e-6
    # leaving and re-entering keeps it
    w.leave_sketch(); w.enter_sketch(made["profile"])
    assert len(ed.m.ext) == 1
    # the reference is drawn in its own colour and the sketch still has a closed profile (the reference never joins it)
    assert ("pt", ed.m.ext[0]["pt"]) in sx.ext_keys(ed.m)
    w.leave_sketch()
print("EXT UI OK")
os._exit(0)
