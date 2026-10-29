import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import numpy as np
from PyQt6.QtWidgets import QApplication, QInputDialog
app = QApplication([])
import pm_model as pm, sk_tools as sk, pm_app, unitctl
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
d = pm.Document(); d.params = {"G": "5"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (100, 50)); sk.solve_model(m)
# two dimensions: width 100 (plain), height 50 (a named symbol)
ids = []
for tool, refs, val in (("dim_h", None, 100.0),):
    pass
pts = sorted(m.pts)
lns = sorted(m.lns)
bottom = next(i for i in lns if all(abs(m.pts[p][1]) < 1e-9 for p in m.lns[i]))
left = next(i for i in lns if all(abs(m.pts[p][0]) < 1e-9 for p in m.lns[i]))
c1 = m.add_con("dim_len", [("ln", bottom)], value=100.0, name="L1")
m.add_param("Hgt", 50.0)
c2 = m.add_con("dim_len", [("ln", left)], value=50.0, name="Hgt", expr="Hgt")
sk.solve_model(m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="20")); d.rebuild()
assert d.status[e["id"]] == "ok", d.status
# ---- rename
d.rename_dimension(s["id"], c1["id"], "FlangeWidth")
for bad in ("G", "1x", "sin", "has space", "FlangeWidth"):
    try:
        d.rename_dimension(s["id"], c2["id"], bad); ok = False
    except pm.ModelError as ex:
        ok = True
    assert ok, bad
d.rename_dimension(s["id"], c2["id"], "Height2")                  # a symbol-driven dimension: the symbol is renamed with it
m2 = d.sketch_model_raw(d.feature(s["id"]))
assert "Height2" in m2.params and "Hgt" not in m2.params and m2.con_by_id(c2["id"])["expr"] == "Height2"
try:
    d.rename_dimension(s["id"], c1["id"], "Height2"); assert False
except pm.ModelError:
    pass
d.rebuild()
assert d.status[s["id"]] == "ok" and d.dimvals["FlangeWidth"] == 100.0, (d.status, d.dimvals)
# ---- a named dimension in a formula
e["depth"] = "FlangeWidth/4 + G"; d.rebuild()
assert d.status[e["id"]] == "ok" and close(d.solid.volume, 100 * 50 * 30), (d.status, d.solid.volume)
# ---- configuration columns
cands = {k: (l, v) for k, l, v in d.cfg_candidates()}
print(sorted(l for l, v in cands.values()))
kd1, kd2 = f"d:{s['id']}:{c1['id']}", f"d:{s['id']}:{c2['id']}"
assert cands[kd1][0] == "FlangeWidth@Sketch1" and cands[kd2][0] == "Height2@Sketch1", (cands[kd1], cands[kd2])
assert close(cands[kd2][1], 50.0)                                 # the number of the symbol, not its name
kf = f"f:{e['id']}:depth"
assert kf in cands and cands[kf][0].startswith("Depth@")
for k in (kd1, kd2, kf):
    d.cfg_add_col(k)
d.cfg_add("Big")
d.cfg_set_cell("Big", kd1, 200.0); d.cfg_set_cell("Big", kd2, 80.0); d.cfg_set_cell("Big", kf, "10")
d.cfg_apply("Big"); d.rebuild()
assert d.status[e["id"]] == "ok" and close(d.solid.volume, 200 * 80 * 10), (d.status, d.solid.volume)
d.cfg_apply("Default"); d.rebuild()
assert close(d.solid.volume, 100 * 50 * 30)
# through-all / nothing to size: no depth column
e2 = d.add(pm.new_feature("cut", sketch=s["id"], depth="5", end1="through"))
assert not any(k.startswith(f"f:{e2['id']}:") for k, l, v in d.cfg_candidates())
f1 = d.add(pm.new_feature("fillet", edges=[], size="2"))
assert any(k == f"f:{f1['id']}:size" for k, l, v in d.cfg_candidates())
print("model OK")
# ---- the interface
w = pm_app.MainWindow(); dd = w.doc
sid = next(f["id"] for f in dd.features if f["kind"] == "sketch")
dim = [c for c in dd.sketch_model_raw(dd.feature(sid)).cons if c["type"] in ("dim_h", "dim_v", "dim_len", "dim_rad", "dim_dia")]
print("demo dims", [(c["name"], c.get("expr"), c["value"]) for c in dim])
w.sel = sid; w.show_props()
from PyQt6.QtWidgets import QTableWidget
tables = [t for t in w.props.findChildren(QTableWidget)]
tab = tables[0]
if tab.rowCount():
    tab.item(0, 0).setText("MyDim")
    sm = dd.sketch_model_raw(dd.feature(sid))
    assert any(c.get("name") == "MyDim" for c in sm.cons) or "MyDim" in sm.params, "rename from the table"
    w.sel = sid; w.show_props(); tab = [t for t in w.props.findChildren(QTableWidget)][0]
    other = tab.item(1, 0).text() if tab.rowCount() > 1 else None
    if other:
        tab.item(1, 0).setText("MyDim")                                # a duplicate is refused
        assert sum(1 for c in dd.sketch_model_raw(dd.feature(sid)).cons if c.get("name") == "MyDim") <= 1
    print("table rename OK")
# units in the configuration table for a feature value
unitctl.set_units("US (in, lbf, psi)", persist=False, notify=False)
cp = w.cfg_panel
key = next(k for k, l, v in dd.cfg_candidates() if k.startswith("f:"))
cp.add_column(key); w.units_changed(); cp.refresh()
col = 1 + dd.cfg["cols"].index(key)
txt0 = cp.table.item(0, col).text()
cp.table.item(0, col).setText("1")
assert dd.cfg["cells"][dd.cfg["active"]][key] == "25.4", dd.cfg["cells"]
unitctl.set_units("Metric (mm, kg, N, s, MPa)", persist=False, notify=False)
print("ALL CFG/DIM TESTS PASSED")
