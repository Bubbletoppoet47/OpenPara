"""Dynamic simulation section of the Controls tab (dev_addons/controls): drawing, editing, undo, running, playback, G(s) hand-over, files, painting."""
import faulthandler
import json
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "controls"), os.path.join(HERE, "shared"), HERE]
import numpy as np
from PyQt6.QtCore import QPointF, QTimer
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import controls_tab as T
import ctl_dyn as dyn
import ctl_dyn_section as S
import ctl_dyn_view as V

t = T.make_tab()
t.resize(1400, 900)
t.show()
app.processEvents()
ds = t.section("dynamic")
assert ds is not None and ds.tab is t and [s.key for s in t.sections][-1] == "dynamic"
t.show_section("dynamic")
app.processEvents()
assert t.pages.currentWidget() is ds.results and ds.inputs.isVisible() and not t.is_dirty()


def commit(edit, v):
    edit.setText(str(v))
    edit.editingFinished.emit()


# ---- it opens with the self-balancing robot, ready to run ------------------------------------------------------------------------------------------
assert [p["id"] for p in ds.sk["parts"]] == ["wheel", "body", "battery"] and ds.result is None and ds.run_btn.isEnabled()
assert ds.msg.text() == "" and ds.summary.text() == S.HINT and not ds.play_btn.isEnabled()
assert ds.plist.count() == 3 and ds.n_tkp.value == ds.sk["controller"]["kp"] and ds.pos_on.isChecked()

# ---- Run: the result, the plots, the player -----------------------------------------------------------------------------------------------------
ds.run()
r = ds.result
assert r is not None and r.ok and "Held its balance" in ds.summary.text() and "unstable" in ds.summary.text()
assert ds.slider.maximum() == r.n - 1 and ds.play_btn.isEnabled() and ds.timer.isActive() and ds.play_btn.text() == "Pause"
assert ds.run_btn.text() == "Run" and ds.run_btn.isEnabled() and not ds.running and ds.pal.isEnabled()
ds.pause()
assert not ds.timer.isActive() and ds.play_btn.text() == "Play"
ds.slider.setValue(r.n // 2)
assert ds.frame_i == r.n // 2 and abs(ds.plots.t_cur - r.t[r.n // 2]) < 1e-12 and ds.view.animating and not ds.view.note
base = next(s for s in ds.view.shapes if s["kind"] == "wheel")
assert abs(base["c"][0] - r.x[r.n // 2]) < 1e-9                                      # the wheel is drawn where the run says it was
ds.scrub(2.5)
assert abs(r.t[ds.frame_i] - 2.5) < 0.006
ds.t_play = r.t[-1] - 0.01
ds.play()
ds.tick()                                                                              # the end of the run stops the player by itself
assert not ds.timer.isActive() and ds.frame_i == r.n - 1 and "10.00 s" in ds.tlabel.text()
ds.toggle_play()                                                                       # from the end, Play starts again from the beginning
assert ds.timer.isActive() and ds.t_play == 0.0
ds.pause()

# ---- editing a number drops the old result and is one undo step -------------------------------------------------------------------------------------
n0 = len(ds.undo)
old = ds.sk["controller"]["kp"]
commit(ds.n_tkp, 12.5)
assert ds.sk["controller"]["kp"] == 12.5 and ds.result is None and not ds.view.animating and ds.summary.text() == S.HINT and t.is_dirty()
assert len(ds.undo) == n0 + 1 and not ds.play_btn.isEnabled()
commit(ds.n_tkp, 12.5)                                                                  # the same value again is not a change
assert len(ds.undo) == n0 + 1
ds.n_tkp.setText("abc")                                                                 # not a number: the old value comes back, tinted
ds.n_tkp.editingFinished.emit()
assert ds.n_tkp.text() == "12.5" and ds.sk["controller"]["kp"] == 12.5 and ds.n_tkp.styleSheet()
ds.do_undo()
assert ds.sk["controller"]["kp"] == old and ds.n_tkp.value == old
ds.run()
assert ds.result.ok
commit(ds.n_dur, 4)
assert ds.sk["run"]["duration"] == 4 and ds.result is None
ds.run()
assert abs(ds.result.t[-1] - 4.0) < 1e-9
commit(ds.n_dur, 10)

# ---- a run can be stopped -----------------------------------------------------------------------------------------------------------------------------
commit(ds.n_dur, 120)
QTimer.singleShot(0, ds.run)                                                           # a second press of the button, while it is running, stops it
ds.run()
assert ds.result is not None and ds.result.stopped and ds.result.t[-1] < 120 and "Stopped at" in ds.summary.text() and ds.run_btn.text() == "Run"
commit(ds.n_dur, 10)

# ---- gains and the controller fields follow the drawing ---------------------------------------------------------------------------------------------
commit(ds.n_tkp, 0)
commit(ds.n_tkd, 0)
ds.run()
assert not ds.result.ok and "Fell over" in ds.summary.text()
ds.show_frame(ds.result.n - 1)
assert ds.view.note == "Fell over" and ds.plots.res is ds.result
ds.suggest()
c = ds.sk["controller"]
assert c["kp"] > 0 and c["kd"] > 0 and c["pkp"] > 0 and ds.n_tkp.value == c["kp"] and "linear-quadratic" in ds.status.text()
ds.run()
assert ds.result.ok

# ---- the checks are shown in plain words and stop Run -----------------------------------------------------------------------------------------------
ds.edit(lambda: ds.sk["parts"][1].__setitem__("parent", None), True)
assert "not attached" in ds.msg.text() and not ds.run_btn.isEnabled() and ds.view.shapes
ds.run()
assert ds.result is None and "Fix the drawing" in ds.status.text()
ds.do_undo()
assert ds.msg.text() == "" and ds.run_btn.isEnabled()

# ---- the palette: build the robot from nothing, with the parts the way a person would press them ----------------------------------------------
import copy
base_sk, depth = copy.deepcopy(ds.sk), len(ds.undo)
ds.select("wheel")
ds.delete()                                                                            # deleting the base takes everything attached with it
assert ds.sk["parts"] == [] and ds.sel is None and not ds.del_btn.isEnabled() and not ds.add_btn["link"].isEnabled() and ds.add_btn["wheel"].isEnabled()
assert "stand on" in ds.msg.text() and not ds.run_btn.isEnabled()
ds.add("mass")
assert "Add a link first" in ds.status.text() and ds.sk["parts"] == []
ds.add("wheel")
assert [p["kind"] for p in ds.sk["parts"]] == ["wheel"] and ds.sel == "wheel1" and not ds.add_btn["wheel"].isEnabled() and ds.add_btn["link"].isEnabled()
ds.add("link")
assert ds.sel == "link1" and dyn.part(ds.sk, "link1")["parent"] == "wheel1"
ds.add("mass")
assert dyn.part(ds.sk, "mass1")["parent"] == "link1" and ds.sel == "mass1"
ds.add("link")                                                                         # a link while a mass is picked goes on the mass's link
assert dyn.part(ds.sk, "link2")["parent"] == "link1" and dyn.part(ds.sk, "link2")["at"] == dyn.part(ds.sk, "link1")["length"]
ds.delete()                                                                            # remove the second link again
assert dyn.part(ds.sk, "link2") is None
# the form for the picked link: numbers, a parent, a motor
ds.select("link1")
rows = ds.pform.rowCount()
assert rows >= 9
form_edits = [ds.pform.itemAt(i, ds.pform.ItemRole.FieldRole).widget() for i in range(rows)]
length = next(w for w in form_edits if isinstance(w, S.NumEdit) and w.value == 0.3)
commit(length, 0.4)
assert dyn.part(ds.sk, "link1")["length"] == 0.4
ds.edit(lambda: dyn.part(ds.sk, "link1").__setitem__("length", 0.3))
motor_row = form_edits[-1]
cb = motor_row.layout().itemAt(0).widget()
cb.setChecked(True)
assert dyn.part(ds.sk, "link1")["motor"] == {"max": 1.0}
ds.select("wheel1")
mrow = ds.pform.itemAt(ds.pform.rowCount() - 1, ds.pform.ItemRole.FieldRole).widget()
mrow.layout().itemAt(0).widget().setChecked(True)                                      # one motor only: it moves from the link to the wheel
assert dyn.part(ds.sk, "wheel1")["motor"] and not dyn.part(ds.sk, "link1")["motor"] and "switched off" in ds.status.text()
assert any("wheel" in e.lower() or "Wheel" in e for e in dyn.check(ds.sk)[1])
ds.select("link1")
ds.pform.itemAt(ds.pform.rowCount() - 1, ds.pform.ItemRole.FieldRole).widget().layout().itemAt(0).widget().setChecked(True)
assert dyn.part(ds.sk, "link1")["motor"] and not dyn.part(ds.sk, "wheel1")["motor"]
assert dyn.check(ds.sk)[0] == [] and ds.run_btn.isEnabled()
assert ds.c_balance.currentData() == "link1" and "Link" in ds.c_balance.currentText()
ds.suggest()
ds.run()
assert ds.result is not None and ds.result.ok, ds.summary.text()                       # a robot built by hand balances with the suggested gains
while len(ds.undo) > depth:                                                            # and undoing every step brings the original robot back exactly
    ds.do_undo()
assert ds.sk == base_sk and ds.run_btn.isEnabled()

# ---- picking in the drawing selects the part ------------------------------------------------------------------------------------------------------------
ds.from_json({})
app.processEvents()
ds.view.resize(700, 420)
app.processEvents()
ds.view.grab()
got = []
ds.view.picked.connect(got.append)
sh = {s["id"]: s for s in ds.view.shapes}
for pid, pt in (("wheel", sh["wheel"]["c"]), ("battery", sh["battery"]["c"])):
    q = ds.view.to_px(*pt)
    assert ds.view.hit(QPointF(q.x() + 1, q.y() + 1)) == pid, pid
mid = ((sh["body"]["a"][0] + sh["body"]["b"][0]) / 2, (sh["body"]["a"][1] + sh["body"]["b"][1]) / 2 - 0.02)
q = ds.view.to_px(*mid)
assert ds.view.hit(QPointF(q.x() + 3, q.y())) == "body"
assert ds.view.hit(QPointF(5, 5)) is None
ds.select("body")
assert ds.sel == "body" and ds.plist.currentRow() == 1 and ds.view.selected == "body"

# ---- all the examples load, are clean, and run; their forms build ------------------------------------------------------------------------------------
for i, (name, fn) in enumerate(dyn.EXAMPLES, start=1):
    ds.load_example(i)
    assert ds.ex.currentIndex() == 0 and ds.msg.text() == "", name
    for p in ds.sk["parts"]:
        ds.select(p["id"])
        assert ds.pform.rowCount() >= 2
    ds.run()
    assert ds.result is not None and ds.result.ok, (name, ds.summary.text())
    ds.pause()
pend = ds.sk
assert dyn.part(pend, "pivot")["kind"] == "pivot" and not ds.n_pkp.isEnabled() and not ds.pos_on.isEnabled() and not ds.g_kind.isEnabled()
ds.load_example(2)
assert ds.n_pkp.isEnabled() and ds.n_gr.isEnabled() and ds.labels["tkp"][0].text().endswith("(N/rad)")                 # a cart's motor is a force
ds.g_kind.setCurrentIndex(0)
ds.g_kind.activated.emit(0)
assert ds.sk["controller"]["goal"]["kind"] == "hold" and not ds.n_gr.isEnabled() and not ds.n_gt.isEnabled()

# ---- the push, the goal and the fall limit are used ----------------------------------------------------------------------------------------------------
ds.load_example(1)
ds.push_on.setChecked(True)
assert ds.sk["run"]["push"]["on"] and ds.n_pf.isEnabled()
ds.run()
assert ds.result.ok
ds.pause()

# ---- the plant goes to the Transfer function section -------------------------------------------------------------------------------------------------
ds.load_example(1)
ds.send_tf()
tf = t.section("transfer_function")
assert t.pages.currentWidget() is tf.results and tf.num.text().startswith("[") and tf.analysis is not None
poles = sorted(z.real for z in tf.analysis.poles)
assert abs(poles[0] + 11.5) < 0.01 and abs(poles[1] - 11.5) < 0.01 and "unstable" in tf.text.toPlainText().lower()
t.show_section("dynamic")

# ---- the file: the drawing, the gains and the run settings come back --------------------------------------------------------------------------------------
ds.load_example(2)
commit(ds.n_tkp, 99)
path = os.path.join(UD, "cartpole.opctl")
t.path = path
t.save()
d = json.load(open(path))
assert d["sections"]["dynamic"]["sketch"]["controller"]["kp"] == 99 and d["sections"]["dynamic"]["sketch"]["parts"][0]["kind"] == "cart"
t2 = T.make_tab(path)
d2 = t2.section("dynamic")
assert d2.sk["controller"]["kp"] == 99 and [p["id"] for p in d2.sk["parts"]] == ["cart", "pole"] and d2.sk == dyn.normalize(d["sections"]["dynamic"]["sketch"])
assert not t2.is_dirty() and d2.n_tkp.value == 99 and d2.result is None
t2.new()                                                                               # New brings back the robot
assert [p["id"] for p in t2.section("dynamic").sk["parts"]] == ["wheel", "body", "battery"]
old_file = {"format": T.FORMAT, "version": 1, "sections": {"transfer_function": {}}}     # a file from before this section existed
json.dump(old_file, open(os.path.join(UD, "old.opctl"), "w"))
t3 = T.make_tab(os.path.join(UD, "old.opctl"))
assert [p["id"] for p in t3.section("dynamic").sk["parts"]] == ["wheel", "body", "battery"]

# ---- painting at silly sizes, with every kind of result, must never raise ----------------------------------------------------------------------------
sv, sp = V.SketchView(), V.SignalPlots()
for name, fn in dyn.EXAMPLES:
    sk = fn()
    res = dyn.simulate(sk)
    sk2 = fn()
    sk2["controller"].update(kp=0, kd=0, pkp=0, pkd=0)
    bad = dyn.simulate(sk2)
    for rr in (res, bad, None):
        sp.set_result(rr)
        if rr is not None:
            sp.set_time(float(rr.t[-1]) / 2)
        sv.set_sketch(sk)
        if rr is not None:
            sv.show_frame(rr.mdl, rr.z[-1], 0.5, "Fell over")
        else:
            sv.show_static()
        for size in ((1, 1), (10, 5), (50, 50), (320, 220), (2000, 100), (80, 900)):
            for wdg in (sv, sp):
                wdg.setMinimumSize(0, 0)
                wdg.resize(*size)
                wdg.grab()
sv.set_sketch(dyn.normalize({}))
sv.show_static()
sv.resize(400, 300)
sv.grab()
assert sv.hit(QPointF(10, 10)) is None
orphan = dyn.example_robot()
orphan["parts"][1]["parent"] = None
sv.set_sketch(orphan)
sv.show_static()
sv.grab()

# ---- the add-on describes itself ----------------------------------------------------------------------------------------------------------------------------
spec = json.load(open(os.path.join(HERE, "dev_addons", "controls", "addon.json")))
assert "balance" in spec["description"].lower() or "pid" in spec["description"].lower()
readme = open(os.path.join(HERE, "dev_addons", "controls", "README.md"), encoding="utf-8").read()
assert "Dynamic simulation" in readme and "ctl_dyn.py" in readme
print("PASS controls dyn tab")
