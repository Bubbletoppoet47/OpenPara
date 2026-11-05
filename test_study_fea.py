"""The 2D FEA study adapter (the interface of the Parametric Studies add-on): parameters, outputs, a case on a scratch tab (the live tab is not touched),
a load sweep that is linear, a thickness sweep, a geometry-independent cache, show()."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import physics_tab, sim_tab
import study_iface as si


def rect(w=100, h=20):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (w, 0), (w, h), (0, h))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
    return m, p, ls


host = sim_tab.SimHost.__new__(sim_tab.SimHost)
host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
host.sketch_list = lambda: []
t = physics_tab.PhysicsTab(host)
m, p, ls = rect()
t.set_model(m, "rect")
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
ad = t.study_adapter()
assert isinstance(ad, si.StudyAdapter) and ad.key == "fea" and ad.ready() == "The simulation has no supports or no loads yet."
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", ls[1])]}, {"kind": "force", "fx": 0.0, "fy": -2.0, "targets": [("pt", p[2])]}]
t.e_h.setText("5")
assert ad.ready() is None

ps = {d["id"]: d for d in ad.params()}
assert {"fea.e_E", "fea.e_t", "fea.e_h", "fea.cb_nl", "fea.rb_strain", "fea.load0.p", "fea.load1.fx", "fea.load1.fy"} <= set(ps), sorted(ps)
assert ps["fea.cb_nl"]["kind"] == "bool" and ps["fea.e_t"]["now"] == "1" and ps["fea.load0.p"]["now"] == "0.5"
outs = {o["id"]: o for o in ad.outputs()}
assert {"fea.status", "fea.umax", "fea.vm", "fea.fos_y"} <= set(outs) and outs["fea.vm"]["numeric"] and not outs["fea.status"]["numeric"]

before = (t.e_t.text(), repr(t.loads), repr(t.supports), t.mesh, t.result)
ctx = {}
def run(values):
    spec = ad.prepare(values, ctx)
    assert spec["error"] is None, spec["error"]
    case = spec["run"](lambda *a, **k: None, lambda: False)
    assert case["status"].startswith("ok"), case
    return case
# the base case, then a pressure twice as big: linear -> twice the stress and displacement (the load is small enough to stay linear)
c1 = run({})
c2 = run({"fea.load0.p": "1.0", "fea.load1.fy": "-4"})
o1, o2 = ad.case_outputs(c1, ["fea.umax", "fea.vm", "fea.status", "fea.solver"]), ad.case_outputs(c2, ["fea.umax", "fea.vm"])
assert o1["fea.solver"] == "linear" and o1["fea.status"] == "ok" and o1["fea.umax"] > 0
assert abs(o2["fea.umax"] / o1["fea.umax"] - 2) < 0.02 and abs(o2["fea.vm"] / o1["fea.vm"] - 2) < 0.03, (o1, o2)
# thickness: the plate gets twice as thick -> the stress and displacement of a membrane drop to about half
c3 = run({"fea.e_t": "2"})
o3 = ad.case_outputs(c3, ["fea.umax"])
assert abs(o3["fea.umax"] / o1["fea.umax"] - 0.5) < 0.03, (o3, o1)
# the live tab is untouched, and the mesh was shared between the cases with the same element size
assert (t.e_t.text(), repr(t.loads), repr(t.supports), t.mesh, t.result) == before
assert len(ctx["cache"]) == 1
c4 = run({"fea.e_h": "8"})
assert len(ctx["cache"]) == 2 and ad.case_outputs(c4, ["fea.tris"])["fea.tris"] < ad.case_outputs(c1, ["fea.tris"])["fea.tris"]
# a bad value is reported, not raised
bad = ad.prepare({"fea.e_t": "abc"}, ctx)
assert bad["error"] and bad["run"] is None, bad
bad = ad.prepare({"fea.nope": "1"}, ctx)
assert bad["error"] and "nope" in bad["error"]
bad = ad.prepare({"fea.cb_auto": "maybe"}, ctx)
assert bad["error"]
# a choice / a tick box
ok = ad.prepare({"fea.rb_strain": "yes", "fea.cb_nl": "no"}, ctx)
assert ok["error"] is None
# cancel
spec = ad.prepare({}, {})
try:
    spec["run"](lambda *a, **k: None, lambda: True)
    raise SystemExit("a cancelled case must raise StudyCancelled")
except si.StudyCancelled:
    pass
# the automatic refinement runs inside a case
auto = ad.prepare({"fea.cb_auto": "yes", "fea.e_passes": "2", "fea.e_maxtris": "5000"}, {})
assert auto["error"] is None
ca = auto["run"](lambda *a, **k: None, lambda: False)
assert ca["status"].startswith("ok") and ca["result"]["refine"]["log"], ca["status"]
# show(): the finished case appears in the live tab
ad.show(c2)
assert t.result is not None and abs(float(np.max(np.hypot(t.result["u"][:, 0], t.result["u"][:, 1]))) - o2["fea.umax"]) < 1e-9
print("OK study fea")
os._exit(0)
