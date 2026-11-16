"""The 2D CFD study adapter: parameters, outputs, a coarse case on a scratch tab (live tab untouched), a speed sweep, mesh cache, cancel, show()."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import cfd_tab, sim_tab
import study_iface as si

host = sim_tab.SimHost.__new__(sim_tab.SimHost)
host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
host.sketch_list = lambda: []
t = cfd_tab.CFDTab(host)
m = sc.Model()
p = [m.add_point(*c) for c in ((0, 0), (20, 0), (20, 20), (0, 20))]
for i in range(4):
    m.add_line(p[i], p[(i + 1) % 4])
ad = t.study_adapter()
assert ad.ready() is not None
t.set_model(m, "square")
assert ad.ready() is None and ad.key == "cfd"
spec = ad.mesh_refinement()
assert spec and spec["sizes"] == ["cfd.e_hb", "cfd.e_hf"] and spec["dim"] == 2 and spec["count"] == "cfd.tris" and spec["extra"].get("cfd.cb_auto") == "no"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons_src", "parametric")); import study_core as _core
_r = _core.refinement_rows(spec["sizes"], {"cfd.e_hb": "3", "cfd.e_hf": "12"}, "3", "0.5", 3, spec["extra"])
assert [x["cfd.e_hb"] for x in _r] == ["3", "1.5", "0.75"] and [x["cfd.e_hf"] for x in _r] == ["12", "6", "3"], "body and far-field sizes scale together"
# a coarse, short case
t.e_hb.setText("3"); t.e_hf.setText("12"); t.e_steps.setText("40"); t.cb_until.setChecked(False); t.cb_auto.setChecked(False)
idx = t.turb.findText("Laminar") if hasattr(t.turb, "findText") else -1
if idx >= 0:
    t.turb.setCurrentIndex(idx)

ps = {d["id"]: d for d in ad.params()}
assert {"cfd.e_speed", "cfd.e_hb", "cfd.e_steps", "cfd.cb_auto"} <= set(ps), sorted(ps)
outs = {o["id"]: o for o in ad.outputs()}
assert {"cfd.status", "cfd.along", "cfd.steps", "cfd.tris"} <= set(outs) and not outs["cfd.status"]["numeric"]

before = (t.e_speed.text(), t.mesh, t.result)
ctx = {}
def run(values, cancel=lambda: False):
    spec = ad.prepare(values, ctx)
    assert spec["error"] is None, spec["error"]
    return spec["run"](lambda *a, **k: None, cancel)
c1 = run({})
assert c1["status"] != "failed", c1.get("error")
o1 = ad.case_outputs(c1, ["cfd.status", "cfd.along", "cfd.tris", "cfd.steps", "cfd.mass"])
assert o1["cfd.tris"] > 50 and o1["cfd.steps"] >= 1 and o1["cfd.along"] is not None, o1
assert len(ctx["cache"]) == 1
c2 = run({"cfd.e_speed": str(float(ps["cfd.e_speed"]["now"]) * 2)})
assert len(ctx["cache"]) == 1, "a speed sweep reuses the mesh"
o2 = ad.case_outputs(c2, ["cfd.along"])
assert o2["cfd.along"] is not None and abs(o2["cfd.along"]) > abs(o1["cfd.along"]), (o1, o2)
assert (t.e_speed.text(), t.mesh, t.result) == before, "the live tab is untouched"
# bad input
spec = ad.prepare({"cfd.e_speed": "abc"}, ctx)
assert spec["error"], spec
spec = ad.prepare({"cfd.nope": "1"}, ctx)
assert spec["error"]
# cancel
try:
    run({"cfd.e_hb": "2.5"}, cancel=lambda: True)
    raise SystemExit("cancel must raise")
except si.StudyCancelled:
    pass
# show
ad.show(c1)
assert t.result is c1["result"] and t.mesh is c1["mesh"]
print("OK study cfd")
os._exit(0)
