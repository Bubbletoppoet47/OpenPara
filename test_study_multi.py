"""Several studies per project (a mesh refinement study, then the real analysis), the convergence estimate, the CSV button, old project folders."""
import os, sys, tempfile, csv, json, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
PAR = os.path.join(HERE, "addons_src", "parametric")
sys.path[:0] = [HERE, SIM, PAR, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, ext
import study_core as core, study_ext, study_tab
import sim_tab

T = tempfile.mkdtemp(prefix="opara_multi_")

# ---------------------------------------------------------------- 1. the maths: a case with a known answer (u = 10 + 3 h^2, 2D)
def lv(h):
    return {"label": str(h), "h": h, "n": (1.0 / h) ** 2, "outputs": {"u": 10 + 3 * h * h}}
hs = [8 * 0.5 ** k for k in range(7)]
res = core.convergence([lv(h) for h in hs], dim=2, tol=2.0)
o = res["outputs"]["u"]
assert abs(o["order"] - 2.0) < 1e-6 and abs(o["limit"] - 10.0) < 1e-6, o
assert res["recommend"] is not None and res["recommend"] >= 3
assert core.convergence([lv(h) for h in hs[:3]])["recommend"] is None
rows = core.refinement_rows(["s"], {"s": "10"}, "10", "0.5", 3)
assert [r["s"] for r in rows] == ["10", "5", "2.5"], rows
for bad in (("0", "0.7", 5), ("10", "1.2", 5), ("10", "0.7", 1), ("x", "0.7", 5), ("10", "0.7", 99)):
    try:
        core.refinement_rows(["s"], {"s": "10"}, *bad); raise SystemExit(f"should be refused: {bad}")
    except ValueError:
        pass

# ---------------------------------------------------------------- 2. index and migration
pf = os.path.join(T, "proj"); os.makedirs(pf)
assert core.read_index(pf)[0] == [{"name": "Study 1", "sub": ""}]
sd = core.StudyData(); sd.checked = ["p"]; sd.rows = [{"p": "1"}]; sd.save(pf)
assert core.exists(pf) and core.read_index(pf) == ([{"name": "Study 1", "sub": ""}], 0), "an old folder opens as 'Study 1'"
assert not os.path.exists(os.path.join(pf, "study", "index.json"))

# ---------------------------------------------------------------- 3. a 2D FEA project
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
sw = sim_tab.SimWindow("fea")
assert sw.create_project(os.path.join(T, "plate_study")) and sw.import_file(part)
sw.tab.picker.refresh(); sw.tab.picker.select(sid); sw.tab.picker.go()
t = sw.tab
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
xs = {l: [t.model.pts[p][0] for p in t.model.lns[l][:2]] for l in t.model.lns}
left = next(l for l, x in xs.items() if max(x) < 1e-9); right = next(l for l, x in xs.items() if min(x) > 99)
t.supports = [{"mode": "fixed", "targets": [("ln", left)]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", right)]}]
t.e_h.setText("8")
sw.meta["sid"] = sid
assert sw.save()
tab = study_ext.open_study(sw, threaded=False)
assert [x["name"] for x in tab.studies] == ["Study 1"] and not tab.b_del.isEnabled()
assert tab.act_refine.isEnabled()

# the first study: a normal one-row run, kept
tab.data.out_checked = ["fea.status", "fea.umax"]; tab.fill_outputs()
assert tab.run_current() and len(tab.data.cases) == 1

# the CSV button, clicked (a stubbed file dialog): this is what failed before
out_csv = os.path.join(T, "button.csv")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out_csv, ""))
btn = next(b for b in tab.findChildren(study_tab.QPushButton) if b.text().startswith("Export"))
btn.click()
assert os.path.isfile(out_csv) and len(list(csv.reader(open(out_csv)))) == 2, "the Export button writes the file"

# ---------------------------------------------------------------- 4. a mesh refinement study
for bad in (("m", "0", "0.7", 5), ("m", "6", "1.5", 5), ("m", "6", "0.7", 1)):
    try:
        tab.new_refinement(*bad); raise SystemExit(f"should be refused: {bad}")
    except ValueError:
        pass
assert len(tab.studies) == 1, "a refused dialog creates nothing"
assert tab.new_refinement("Mesh refinement", "8", "0.7", 5)
assert [x["name"] for x in tab.studies] == ["Study 1", "Mesh refinement"] and tab.cur == 1 and tab.b_del.isEnabled()
assert [r["fea.e_h"] for r in tab.data.rows] == ["8", "5.6", "3.92", "2.744", "1.921"], tab.data.rows
assert tab.data.refine and tab.data.refine["sizes"] == ["fea.e_h"] and tab.data.cases == []
assert tab.tabs_bottom.isTabVisible(tab.tabs_bottom.indexOf(tab.conv))
assert "fea.umax" in tab.data.out_checked and "fea.tris" in tab.data.out_checked
assert tab.run_all()
assert len(tab.data.cases) == 5 and all(c["status"] == "ok" for c in tab.data.cases), [(c["status"], c.get("error")) for c in tab.data.cases]
n = [c["outputs"]["fea.tris"] for c in tab.data.cases]
assert n == sorted(n) and n[-1] > 2 * n[0], n
res = tab.conv.res
assert res and len(res["levels"]) == 5 and "fea.umax" in res["outputs"] and "fea.tris" not in res["outputs"]
print("umax verdict:", res["outputs"]["fea.umax"]["verdict"], res["outputs"]["fea.umax"]["text"], "| recommend:", res["recommend"])
# the CSV of this study
p2 = os.path.join(T, "ref.csv")
assert tab.export_csv(p2) and len(list(csv.reader(open(p2)))) == 6
# use the recommended size (force a recommendation if the data did not give one)
if tab.conv.res["recommend"] is None:
    tab.conv.res["recommend"] = 2
assert tab.use_size()
assert t.e_h.text() == tab.data.cases[tab.conv.res["recommend"]]["values"]["fea.e_h"], t.e_h.text()
assert tab.save()

# ---------------------------------------------------------------- 5. the real analysis as a second study; copy, rename, delete
assert tab.new_empty("Real analysis") and tab.cur == 2 and tab.data.refine is None and not tab.tabs_bottom.isTabVisible(tab.tabs_bottom.indexOf(tab.conv))
tab.data.out_checked = ["fea.status", "fea.umax"]; tab.fill_outputs()
assert tab.run_current() and len(tab.data.cases) == 1
assert tab.copy_study("Real analysis copy") and tab.cur == 3 and tab.data.cases == [] and tab.data.out_checked == ["fea.status", "fea.umax"]
assert not tab.rename_study("Study 1"), "names are unique"
assert tab.rename_study("Final run") and tab.studies[3]["name"] == "Final run"
assert tab.delete_study() and tab.cur == 0 and len(tab.studies) == 3
assert not tab.delete_study(), "the first study cannot be deleted"
assert tab.switch_study(1) and tab.data.refine and len(tab.data.cases) == 5
assert tab.switch_study(2) and len(tab.data.cases) == 1 and tab.data.refine is None
assert tab.save()

# ---------------------------------------------------------------- 6. save and reopen
study_ext._open.clear()
sw2 = sim_tab.SimWindow.open_project(None, sw.path)
tab2 = study_ext.open_study(sw2, threaded=False)
assert [x["name"] for x in tab2.studies] == ["Study 1", "Mesh refinement", "Real analysis"] and tab2.cur == 2
assert tab2.switch_study(1) and len(tab2.data.cases) == 5 and tab2.conv.res and len(tab2.conv.res["levels"]) == 5
assert tab2.switch_study(0) and len(tab2.data.cases) == 1
print("OK test_study_multi")
