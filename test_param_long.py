"""A long 1D FEA study: more than 500 cases, the window stays responsive, a table row per case, Stop, and the Fill windows remember their values."""
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')          # the big add-ons are not needed here (no download, no disk)
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import addons
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QSpinBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, gpd_app
assert addons.install("simulation") or addons.is_installed("simulation")
addons.activate()
import sim_tab, profiles1d as pr1
import study_core as core

d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
p1, p2 = mm.add_point(0, 0), mm.add_point(1000, 0); mm.add_line(p1, p2)
sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "beam.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part])
w = sh.add_sim("beam")
assert w.create_project(os.path.join(UD, "b1")) and w.project_ok()
w.tab.picker.refresh(); w.tab.picker.select(s["id"]); w.tab.picker.go()
t = w.tab
t.set_profiles([0], pr1.compute("rect", {"b": 20.0, "h": 40.0}))
pts = list(t.model.lns[next(iter(t.model.lns))][:2])
t.supports = [{"mode": "fixed", "targets": [pts[0]]}]
t.loads = [{"kind": "force", "fx": 0.0, "fy": -100.0, "targets": [pts[1]]}]
w.refresh_study_button()
tab = w.open_study()
assert tab is not None and tab.threaded
tab.refresh_params()
from PyQt6.QtCore import Qt
tab.items["beam.load0.fy"].setCheckState(0, Qt.CheckState.Checked)
N = 700
assert tab.fill_range({"beam.load0.fy": ("-100", "-1000", N)}, together=True, log=False, rows=N, confirm=False), "more than 500 rows is allowed"
assert len(tab.data.rows) == N
tab.data.out_checked = ["beam.status", "beam.umax"]
tab.fill_outputs()

# --- the window stays responsive: a 10 ms timer must never be late by much, and starting the run must be quick
gaps, last = [], [time.time()]
def tick():
    now = time.time(); gaps.append(now - last[0]); last[0] = now
tm = QTimer(); tm.timeout.connect(tick); tm.start(10)
t0 = time.time()
assert tab.run_all()
assert time.time() - t0 < 2.0, f"starting took {time.time() - t0:.1f} s"
t1 = time.time()
while tab.running() and time.time() - t1 < 240:
    app.processEvents(); time.sleep(0.002)
tm.stop()
assert not tab.running()
assert len(tab.data.cases) == N and all(c["status"] == "ok" for c in tab.data.cases), (len(tab.data.cases), [c.get("error") for c in tab.data.cases if c["status"] != "ok"][:1])
assert max(gaps) < 1.0, f"the window froze for {max(gaps):.2f} s"
assert tab.res_table.rowCount() == N and tab.res_table.item(N - 1, 0).text() == str(N)
u = [c["outputs"]["beam.umax"] for c in tab.data.cases]
assert abs(u[-1] / u[0] - 10) < 0.01, "ten times the load, ten times the displacement"
assert len(tab.data.heavy) < N and tab.data.case(3) is not None, "finished cases are freed from memory and read back from disk when shown"
print(f"{N} cases, longest freeze {max(gaps) * 1000:.0f} ms, run {time.time() - t1:.1f} s")

# --- Stop keeps what was done
tab.data.rows = tab.data.rows[:400]
assert tab.run_all()
t1 = time.time()
while tab.running() and time.time() - t1 < 120:
    app.processEvents(); time.sleep(0.002)
    if len(tab.data.cases) >= 20 and tab.running():
        tab.stop_run()
assert not tab.running() and 20 <= len(tab.data.cases) < 400

# --- the Fill windows remember their values (also when cancelled), per study, and across a reload
seen = {}
def fake_exec(self):
    edits = [e for e in self.findChildren(QLineEdit) if not isinstance(e.parent(), QSpinBox)]
    seen["texts"] = [e.text() for e in edits]
    if seen.get("write"):
        for e, v in zip(edits, seen["write"]):
            e.setText(v)
    return QDialog.DialogCode.Rejected
QDialog.exec = fake_exec
seen["write"] = ["3, 4, 5"]
assert not tab.fill_grid()
seen.pop("write")
assert not tab.fill_grid() and seen["texts"] == ["3, 4, 5"], seen
seen["write"] = ["-5", "-50"]
assert not tab.fill_range()
seen.pop("write")
assert not tab.fill_range() and seen["texts"] == ["-5", "-50"], seen
st = core.StudyData.load(w.path)
assert st.fill["grid"]["beam.load0.fy"] == "3, 4, 5" and st.fill["range"]["specs"]["beam.load0.fy"][:2] == ["-5", "-50"], st.fill
print("ALL OK")
