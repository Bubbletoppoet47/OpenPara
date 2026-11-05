"""The 1D FEA study adapter: parameters (loads, profile dimensions), outputs, cases against the beam formula, the live tab untouched, show()."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import beam_tab, sim_tab, profiles1d
import study_iface as si

host = sim_tab.SimHost.__new__(sim_tab.SimHost)
host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
host.sketch_list = lambda: []
b = beam_tab.BeamTab(host)
ad = b.study_adapter()
assert ad.key == "beam" and ad.ready() == "Import a sketch in the simulation first."
bm = sc.Model(); q = [bm.add_point(0, 0), bm.add_point(1000, 0)]; bm.add_line(q[0], q[1])
b.set_model(bm, "cantilever")
b.set_profiles([0], profiles1d.compute("rect", {"b": 20.0, "h": 40.0}))
b.supports = [{"mode": "fixed", "targets": [q[0]]}]
b.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[1]]}]
assert ad.ready() is None
ps = {d["id"]: d for d in ad.params()}
dim_ids = [i for i in ps if i.startswith("beam.mem") and not i.endswith("depth")]
assert "beam.load0.fy" in ps and "beam.e_E" in ps and len(dim_ids) == 2, sorted(ps)
hid = next(i for i in dim_ids if ps[i]["label"].lower().find("h") >= 0 and ps[i]["now"] in ("40", "40.0")) if any(ps[i]["now"] in ("40", "40.0") for i in dim_ids) else None
assert hid, [(i, ps[i]["label"], ps[i]["now"]) for i in dim_ids]
outs = {o["id"]: o for o in ad.outputs()}
assert {"beam.status", "beam.umax", "beam.sigma", "beam.fos_y", "beam.sup0.ry"} <= set(outs)

before = (repr(b.loads), repr(b.members), repr(b.supports))
def run(values):
    sp = ad.prepare(values, {})
    assert sp["error"] is None, sp["error"]
    c = sp["run"](lambda *a, **k: None, lambda: False)
    assert c["status"] == "ok", c
    return c
c1 = run({})
o1 = ad.case_outputs(c1, ["beam.umax", "beam.sigma", "beam.sup0.ry", "beam.ry", "beam.status"])
# cantilever: delta = P L^3 / (3 E I),  sigma = M c / I
E_ = float(b.e_E.text()); I = 20 * 40 ** 3 / 12; P, L = 500.0, 1000.0
unit_E = E_                                                          # E in the unit system of the tab
expect = P * L ** 3 / (3 * unit_E * I)
assert abs(o1["beam.umax"] - expect) / expect < 0.02, (o1, expect)
assert abs(abs(o1["beam.sup0.ry"]) - 500) < 1e-3 and abs(abs(o1["beam.ry"]) - 500) < 1e-3
# twice the load: twice the deflection; a profile twice as deep: 1/8 of the deflection and 1/4 of the stress
c2 = run({"beam.load0.fy": "-1000"})
c3 = run({hid: "80"})
o2, o3 = ad.case_outputs(c2, ["beam.umax"]), ad.case_outputs(c3, ["beam.umax", "beam.sigma"])
assert abs(o2["beam.umax"] / o1["beam.umax"] - 2) < 1e-3
assert abs(o3["beam.umax"] / o1["beam.umax"] - 1 / 8) < 0.01 and abs(o3["beam.sigma"] / o1["beam.sigma"] - 1 / 4) < 0.01, (o1, o3)
assert (repr(b.loads), repr(b.members), repr(b.supports)) == before and b.result is None, "the live tab must not change"
# the member outputs and the E box
mid = next(i for i in outs if i.startswith("beam.m") and i.endswith(".sigma"))
assert ad.case_outputs(c1, [mid])[mid] == o1["beam.sigma"]
c4 = run({"beam.e_E": str(2 * unit_E)})
assert abs(ad.case_outputs(c4, ["beam.umax"])["beam.umax"] / o1["beam.umax"] - 0.5) < 1e-3
# a bad value and an unknown input are reported
assert ad.prepare({"beam.load0.fy": "x"}, {})["error"] and "nope" in ad.prepare({"beam.nope": "1"}, {})["error"]
# cancel and show
try:
    ad.prepare({}, {})["run"](lambda *a, **k: None, lambda: True)
    raise SystemExit("must raise StudyCancelled")
except si.StudyCancelled:
    pass
ad.show(c2)
assert b.result is not None and abs(b.result["umax"] - ad.case_outputs(c2, ["beam.umax"])["beam.umax"]) < 1e-12
print("OK study beam")
os._exit(0)
