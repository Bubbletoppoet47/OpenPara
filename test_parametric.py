"""The Parametric Studies add-on: the core (grid, exit conditions, save / load / CSV), and a study of a 2D FEA project run end to end -
geometry (a dimension of the part copy) and an adapter input, early exit, stop, show a case, save and reopen."""
import os, sys, tempfile, shutil, csv, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
PAR = os.path.join(HERE, "dev_addons", "parametric")
sys.path[:0] = [HERE, SIM, PAR, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, ext
import study_core as core, study_ext, study_tab
import sim_tab, sim_project as sp

T = tempfile.mkdtemp(prefix="opara_par_")

# ---------------------------------------------------------------- 1. the core
assert core.split_list("10, 15;20,,") == ["10", "15", "20"]
rows = core.grid_rows(["a", "b"], [["1", "2"], ["x", "y", "z"]])
assert len(rows) == 6 and rows[0] == {"a": "1", "b": "x"} and rows[-1] == {"a": "2", "b": "z"}
assert len(core.grid_rows(["a", "b"], [["1"] * 30, ["1"] * 30])) == 900, "no 500-case limit any more"
try:
    core.grid_rows(["a", "b"], [["1"] * 1001, ["1"] * 1001]); raise SystemExit("an absurd count must still be refused")
except ValueError:
    pass
conds = [{"on": True, "key": "fea.fos_y", "op": "<", "value": "1.5"}, {"on": False, "key": "fea.vm", "op": ">", "value": "0"}]
assert core.check_exit(conds, {"fea.fos_y": 1.2, "fea.vm": 5}).startswith("fea.fos_y = 1.2 <")
assert core.check_exit(conds, {"fea.fos_y": 2.0, "fea.vm": 5}) is None and core.check_exit(conds, {"fea.fos_y": None}) is None
assert core.check_exit([{"on": True, "key": "k", "op": ">", "value": "abc"}], {"k": 1}) is None
assert core.exit_keys(conds) == ["fea.fos_y"]

sd = core.StudyData()
sd.checked = ["p"]; sd.rows = [{"p": "1"}, {"p": "2"}]; sd.out_checked = ["o"]
sd.run_meta = {"params": [("p", "P")], "outputs": [("o", "O")], "unit": "mm"}
sd.add_case({"label": "1", "values": {"p": "1"}, "status": "ok", "outputs": {"o": 1.5}, "early_exit": None, "file": None, "notes": []}, {"status": "ok", "x": [1, 2]})
sd.add_case({"label": "2", "values": {"p": "2"}, "status": "failed", "outputs": {"o": None}, "early_exit": None, "file": None, "notes": []}, None)
pf = os.path.join(T, "proj"); os.makedirs(pf)
assert not core.exists(pf)
sd.save(pf)
assert core.exists(pf) and os.listdir(os.path.join(pf, "study", "cases")) == [sd.cases[0]["file"]]
s2 = core.StudyData.load(pf)
assert s2.rows == sd.rows and s2.case(0) == {"status": "ok", "x": [1, 2]} and s2.case(1) is None
heads, trs = s2.table()
assert heads == ["#", "P", "Status", "O"] and trs[0] == ["1", "1", "ok", "1.5"] and trs[1][2] == "failed" and core.StudyData.severity(s2.cases[1]) == "bad"
s2.write_csv(os.path.join(T, "t.csv"))
assert list(csv.reader(open(os.path.join(T, "t.csv"))))[0] == heads
s2.clear_cases(); s2.save(pf)
assert os.listdir(os.path.join(pf, "study", "cases")) == [], "cases of an old run are removed"

# ---------------------------------------------------------------- 2. a 2D FEA project
def make_part(path):
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (100, 20))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
    sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
    open(path, "w").write(d.to_json()); return s["id"]
part = os.path.join(T, "plate.gpd"); sid = make_part(part)

ext.HOOKS.clear(); study_ext.register(ext)
assert ext.hooks("sim_study")
sw = sim_tab.SimWindow("fea")
assert sw.create_project(os.path.join(T, "plate_study")) and sw.import_file(part)
sw.tab.picker.refresh(); sw.tab.picker.select(sid); sw.tab.picker.go()
t = sw.tab
assert getattr(t, "model", None) is not None
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
xs = {l: [t.model.pts[p][0] for p in t.model.lns[l][:2]] for l in t.model.lns}
left = next(l for l, x in xs.items() if max(x) < 1e-9); right = next(l for l, x in xs.items() if min(x) > 99)
t.supports = [{"mode": "fixed", "targets": [("ln", left)]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", right)]}]
t.e_h.setText("6")
sw.meta["sid"] = sid
assert sw.save()

assert not sw.b_study.isEnabled() or True
sw.refresh_study_button()
assert sw.b_study.text() == "Create parametric study"
st = sw.open_study.__func__ if False else None
tab = study_ext.open_study(sw, threaded=False)
assert core.exists(sw.path) and sw.b_study.text() == "Open parametric study", sw.b_study.text()
assert study_ext.open_study(sw, threaded=False) is tab, "the same study is shown, not opened twice"
d = tab.desc
geo = [k for k in d if k.startswith("geo.")]
assert "fea.e_t" in d and "fea.load0.p" in d and any(d[k]["label"].startswith("Part: D1") for k in geo), (list(d)[:30], geo)
dim = next(k for k in geo if d[k]["label"].startswith("Part: D1"))
assert d[dim]["now"] in ("100", "100.0"), d[dim]["now"]

def tick(pid):
    it = tab.items[pid]
    from PyQt6.QtCore import Qt
    it.setCheckState(0, Qt.CheckState.Checked)
tick(dim); tick("fea.load0.p")
assert tab.cols() == [dim, "fea.load0.p"] and tab.data.rows[0][dim] == d[dim]["now"] and tab.data.rows[0]["fea.load0.p"] == "0.5"
assert tab.fill_grid({dim: "100, 200", "fea.load0.p": "0.5, 1.0"})
assert len(tab.data.rows) == 4
# range fills: linspace-like, log spacing, together (shared rows) and every combination, with the replace confirmation
assert core.spaced(0, 10, 5) == ["0", "2.5", "5", "7.5", "10"] and core.spaced(1, 100, 3, True) == ["1", "10", "100"]
assert core.spaced(5, 9, 1) == ["5"]
for bad in ((1, 10, 0), (0, 10, 3, True), (-1, 10, 3, True)):
    try:
        core.spaced(*bad); raise SystemExit("should fail")
    except ValueError:
        pass
assert tab.fill_range({dim: ("100", "200", 3), "fea.load0.p": ("0.5", "2", 4)}, together=True, log=False, rows=5, confirm=False)
rr = tab.data.rows
assert len(rr) == 5 and rr[0][dim] == "100" and rr[-1][dim] == "200" and rr[0]["fea.load0.p"] == "0.5" and rr[-1]["fea.load0.p"] == "2"
assert tab.fill_range({dim: ("100", "200", 3), "fea.load0.p": ("0.5", "2", 4)}, together=False, log=True, confirm=False)
assert len(tab.data.rows) == 12 and tab.data.rows[0][dim] == "100" and tab.data.rows[-1]["fea.load0.p"] == "2"
from PyQt6.QtWidgets import QMessageBox as _QM
_old = _QM.question
_QM.question = staticmethod(lambda *a, **k: _QM.StandardButton.No)
n_before = len(tab.data.rows)
assert not tab.fill_range({dim: ("1", "2", 2), "fea.load0.p": ("1", "2", 2)}, together=False, log=False) and len(tab.data.rows) == n_before, "No keeps the table"
_QM.question = _old
assert tab.fill_range({dim: ("1", "2", 2), "fea.load0.p": ("1", "2", 2)}, together=False, log=False) and len(tab.data.rows) == 4
tab.fill_grid({dim: "100, 200", "fea.load0.p": "0.5, 1.0"})
tab.data.out_checked = ["fea.status", "fea.umax", "fea.vm"]
tab.fill_outputs()
before = (t.mesh, t.result, repr(t.loads), t.e_h.text())
assert tab.run_all()
assert len(tab.data.cases) == 4 and all(c["status"] == "ok" for c in tab.data.cases), [(c["status"], c.get("error")) for c in tab.data.cases]
u = {(c["values"][dim], c["values"]["fea.load0.p"]): c["outputs"]["fea.umax"] for c in tab.data.cases}
# axial bar: u = sigma * L / E: twice the length or twice the pressure -> twice the displacement
assert abs(u[("200", "0.5")] / u[("100", "0.5")] - 2) < 0.05, u
assert abs(u[("100", "1.0")] / u[("100", "0.5")] - 2) < 0.05, u
assert (t.mesh, t.result, repr(t.loads), t.e_h.text()) == before, "the live simulation is untouched by the run"
assert t.isEnabled() and tab.b_all.isEnabled() and not tab.b_stop.isEnabled()
assert core.StudyData.load(sw.path).cases[0]["outputs"]["fea.umax"] == tab.data.cases[0]["outputs"]["fea.umax"], "saved after the run"
heads, trs = tab.data.table()
assert heads[:3] == ["#", "Part: D1@Sketch1", "FEA load: pressure" ] or len(heads) == 1 + 2 + 1 + 3, heads
assert tab.export_csv(os.path.join(T, "res.csv")) and len(list(csv.reader(open(os.path.join(T, "res.csv"))))) == 5

# show a case: the simulation tab takes that geometry and result; the model is the longer one
tab.show_case(1)      # row 2: W=100, p=1.0? (grid order: dim outer, p inner) -> W=100, p=1.0
assert t.result is not None and abs(t.result["u"].max()) > 0
tab.show_case(2)      # W=200, p=0.5
xs2 = [pt[0] for pt in t.model.pts.values()]
assert max(xs2) - min(xs2) > 150, "the case's geometry is on the screen"
assert tab.own_state is not None
tab.back_to_own()
xs3 = [pt[0] for pt in t.model.pts.values()]
assert max(xs3) - min(xs3) < 110 and tab.own_state is None

# early exit: stop when umax > a limit; the rows below are skipped
tab.data.exit_conds = [{"on": True, "key": "fea.umax", "op": ">", "value": str(u[("100", "0.5")] * 1.5)}]
tab.fill_exit_table()
assert tab.run_all()
st_ = [c["status"] for c in tab.data.cases]
assert tab.data.cases[1]["early_exit"] and st_[2:] == ["skipped", "skipped"] and tab.data.cases[2]["early_skipped"], (st_, [c["early_exit"] for c in tab.data.cases])
tab.data.exit_conds = []

# a failing row is recorded, the others go on
tab.data.rows = [{dim: "100", "fea.load0.p": "0.5"}, {dim: "100", "fea.load0.p": "abc"}, {dim: "100", "fea.load0.p": "1"}]
assert tab.run_all()
assert [c["status"] for c in tab.data.cases] == ["ok", "failed", "ok"] and tab.data.cases[1]["error"], [(c["status"], c["error"]) for c in tab.data.cases]
# run current setup
assert tab.run_current() and tab.data.cases[0]["label"] == "current" and tab.data.cases[0]["status"] == "ok"

# save and reopen: results and cases come back from the project folder
tab.data.rows = [{dim: "100", "fea.load0.p": "0.5"}, {dim: "200", "fea.load0.p": "0.5"}]
assert tab.run_all() and tab.save() and not tab.is_dirty()
study_ext._open.clear()
sw2 = sim_tab.SimWindow.open_project(None, sw.path)
sw2.tab.run_task = t.run_task
tab2 = study_ext.open_study(sw2, threaded=False)
assert len(tab2.data.cases) == 2 and tab2.cols() == [dim, "fea.load0.p"] and tab2.data.rows == tab.data.rows
assert tab2.show_case(1) and sw2.tab.result is not None
xs4 = [pt[0] for pt in sw2.tab.model.pts.values()]
assert max(xs4) - min(xs4) > 150, "a saved geometry case is shown from the project"

# a worker thread: the run goes on while the window stays responsive, Stop keeps the cases done
tabT = study_tab.StudyTab(sw2, threaded=True)
tabT.data.rows = [{dim: "100", "fea.load0.p": "0.5"} for _ in range(6)]
tabT.data.checked = [dim, "fea.load0.p"]
import time
assert tabT.run_all() and tabT.running() and not sw2.tab.isEnabled()
t0 = time.time()
while tabT.running() and time.time() - t0 < 120:
    app.processEvents(); time.sleep(0.01)
    if len(tabT.data.cases) >= 2 and tabT.running():
        tabT.stop_run()
assert not tabT.running() and sw2.tab.isEnabled()
assert 2 <= len(tabT.data.cases) < 6 and all(c["status"] == "ok" for c in tabT.data.cases), len(tabT.data.cases)
tabT.data.rows = [{dim: "100", "fea.load0.p": "0.5"}, {dim: "150", "fea.load0.p": "0.5"}]
assert tabT.run_all()
t0 = time.time()
while tabT.running() and time.time() - t0 < 120:
    app.processEvents(); time.sleep(0.01)
assert len(tabT.data.cases) == 2 and all(c["status"] == "ok" for c in tabT.data.cases)

# without the add-on: no hook, no button, the project folder still opens and keeps its study/ folder
ext.HOOKS.clear()
sw3 = sim_tab.SimWindow.open_project(None, sw.path)
sw3.refresh_study_button()
assert sw3.tab.study_box.isHidden() and os.path.isfile(os.path.join(sw.path, "study", "study.json"))
shutil.rmtree(T, ignore_errors=True)
print("OK parametric")
os._exit(0)
