"""Dynamic simulation section of the Controls tab (dev_addons/controls): drawing, editing, undo, Learn (background and live), running, playback, G(s) hand-over, files, painting."""
import faulthandler
import json
import os
import sys
import tempfile
import time

faulthandler.dump_traceback_later(420, exit=True)
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


def wait(cond, timeout=90.0):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.005)
        assert time.time() - t0 < timeout, "timed out waiting"


# ---- it opens with the self-balancing robot, ready to run ------------------------------------------------------------------------------------------
assert [p["id"] for p in ds.sk["parts"]] == ["wheel", "body", "battery"] and ds.result is None and ds.run_btn.isEnabled()
assert ds.msg.text() == "" and ds.summary.text() == S.HINT and not ds.play_btn.isEnabled()
assert ds.plist.count() == 3 and ds.n_tkp.value == ds.sk["controller"]["kp"] and ds.pos_on.isChecked()
assert ds.ex.count() == 1 + len(dyn.SHOWN_EXAMPLES) == 2                              # only the robot is offered for now
assert ds.learn_btn.text() == "Learn" and ds.learn_btn2.text() == "Learn" and not ds.restart_btn.isVisible() and ds.learner is None
assert not ds.adv_box.isVisibleTo(ds.inputs) and ds.adv_btn.text().startswith("Advanced")
ds.adv_btn.setChecked(True)
assert ds.adv_box.isVisibleTo(ds.inputs)
# the learned gains are read-only until the user chooses to set them by hand
assert not ds.by_hand.isChecked() and all(getattr(ds, "n_" + k).isReadOnly() for k in ("tkp", "tki", "tkd", "pkp", "pki", "pkd"))
kp0 = ds.sk["controller"]["kp"]
commit(ds.n_tkp, 12.5)
assert ds.sk["controller"]["kp"] == kp0 and len(ds.undo) == 0 and not t.is_dirty()                 # typing into a read-only gain changes nothing
ds.n_tkp.set_value(kp0)
assert not ds.n_clamp.isReadOnly() and not ds.n_rate.isReadOnly()                   # the settings stay editable
ds.by_hand.setChecked(True)
assert not any(getattr(ds, "n_" + k).isReadOnly() for k in ("tkp", "tki", "tkd", "pkp", "pki", "pkd")) and t.is_dirty()

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

# ---- all the engine's examples load, are clean, and run; their forms build ------------------------------------------------------------------------------
ds.load_example(1)
assert ds.ex.currentIndex() == 0 and ds.msg.text() == "" and [p["id"] for p in ds.sk["parts"]] == ["wheel", "body", "battery"]
for i, (name, fn) in enumerate(dyn.EXAMPLES, start=1):
    ds.load_sketch(fn())
    assert ds.msg.text() == "", name
    for p in ds.sk["parts"]:
        ds.select(p["id"])
        assert ds.pform.rowCount() >= 2
    ds.run()
    assert ds.result is not None and ds.result.ok, (name, ds.summary.text())
    ds.pause()
pend = ds.sk
assert dyn.part(pend, "pivot")["kind"] == "pivot" and not ds.n_pkp.isEnabled() and not ds.pos_on.isEnabled() and not ds.g_kind.isEnabled()
ds.load_sketch(dyn.example_cartpole())
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
ds.load_sketch(dyn.example_cartpole())
ds.by_hand.setChecked(True)
commit(ds.n_tkp, 99)
ds.rb_live.setChecked(True)                                                            # the Learn choices travel with the file too
ds.speed_l.setCurrentIndex(2)
ds.show_c.setCurrentIndex(2)
ds.ck_stagnant.setChecked(False)
ds.n_cap.setValue(123)
path = os.path.join(UD, "cartpole.opctl")
t.path = path
t.save()
d = json.load(open(path))
assert d["sections"]["dynamic"]["sketch"]["controller"]["kp"] == 99 and d["sections"]["dynamic"]["sketch"]["parts"][0]["kind"] == "cart"
t2 = T.make_tab(path)
d2 = t2.section("dynamic")
assert d2.sk["controller"]["kp"] == 99 and [p["id"] for p in d2.sk["parts"]] == ["cart", "pole"] and d2.sk == dyn.normalize(d["sections"]["dynamic"]["sketch"])
assert not t2.is_dirty() and d2.n_tkp.value == 99 and d2.result is None
assert d["sections"]["dynamic"]["learn"] == dict(live=True, speed=5.0, show="best", stop_stagnant=False, stop_damped=True, cap=123, by_hand=True)
assert d2.is_live() and d2.speed_l.currentData() == 5.0 and d2.show_c.currentData() == "best" and not d2.ck_stagnant.isChecked() and d2.n_cap.value() == 123
assert d2.by_hand.isChecked() and not d2.n_tkp.isReadOnly() and d2.learner is None
t2.new()                                                                               # New brings back the robot
assert [p["id"] for p in t2.section("dynamic").sk["parts"]] == ["wheel", "body", "battery"]
old_file = {"format": T.FORMAT, "version": 1, "sections": {"transfer_function": {}}}     # a file from before this section existed
json.dump(old_file, open(os.path.join(UD, "old.opctl"), "w"))
t3 = T.make_tab(os.path.join(UD, "old.opctl"))
assert [p["id"] for p in t3.section("dynamic").sk["parts"]] == ["wheel", "body", "battery"]
d3 = t3.section("dynamic")
assert not d3.is_live() and d3.n_cap.value() == 400 and d3.ck_damped.isChecked() and not d3.by_hand.isChecked()          # defaults for a file without Learn choices

# ---- Learn: refusals in plain words ---------------------------------------------------------------------------------------------------------------------
ds.from_json({})
app.processEvents()
ds.load_sketch(dyn.example_cartpole())
ds.learn_btn.click()
assert not ds.learning and ds.worker is None and "self-balancing robot" in ds.status.text() and ds.learner is None
ds.do_undo()
assert [p["id"] for p in ds.sk["parts"]] == ["wheel", "body", "battery"]
ds.edit(lambda: ds.sk["controller"].__setitem__("pos_on", False))
ds.learn_btn.click()
assert not ds.learning and "goal position" in ds.status.text()
ds.do_undo()
ds.edit(lambda: ds.sk["parts"][1].__setitem__("parent", None), True)
ds.learn_btn.click()
assert not ds.learning and "Fix the drawing first" in ds.status.text()
ds.do_undo()
assert ds.learn_btn.isEnabled() and ds.learner is None

# ---- Learn in the background: the screen stays alive, trials are replayed, the best gains are written in as one undo step ----------------------------------
old_gains = {k: ds.sk["controller"][k] for k in ("kp", "ki", "kd", "pkp", "pki", "pkd")}
depth = len(ds.undo)
ds.n_cap.setValue(16)
ds.ck_stagnant.setChecked(False)
ds.ck_damped.setChecked(False)
assert not ds.is_live() and ds.show_c.isEnabled() and not ds.speed_l.isEnabled()
ticks, seen = [0], set()
probe = QTimer()
probe.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))
probe.start(10)
ds.learn_btn2.click()                                                                  # the Learn button on the right page does the same as the one on the left
assert ds.learning and ds.worker is not None and ds.worker.is_alive() and ds.learn_btn.text() == "Stop" and ds.learn_btn2.text() == "Stop"
assert not ds.pal.isEnabled() and not ds.gbox.isEnabled() and not ds.cbox.isEnabled() and not ds.run_btn.isEnabled() and ds.rb_live.isEnabled()
g_now = ds.sk["controller"]["goal"]["x"]
commit(ds.n_gx, 7.0)                                                                   # edits are locked while it learns
assert ds.sk["controller"]["goal"]["x"] == g_now and len(ds.undo) == depth
ds.do_undo()
assert len(ds.undo) == depth
while ds.learning:
    app.processEvents()
    time.sleep(0.005)
    if ds.rp is not None:
        seen.add(ds.rp["tr"].index)
probe.stop()
lr = ds.learner
assert lr is not None and lr.stop_reason == "trials" and len(lr.history) == 16 and ds.worker is None
assert ticks[0] > 40, ticks[0]                                                          # the main thread kept running its timers while the worker computed
assert len(seen) >= 2 and min(seen) >= 1 and max(seen) <= 16                           # some trials were replayed on the drawing, and not necessarily all
assert len(ds.score.pts) == 16 and [p[0] for p in ds.score.pts] == list(range(1, 17)) and ds.score.floor[-1] == lr.best.cost
assert ds.result is not None and ds.result.ok and "16 trials" in ds.summary.text() and "Undo" in ds.summary.text() and not ds.learning
assert ds.learn_btn.text() == "Continue learning" and ds.restart_btn.isVisible() and ds.learn_btn.isEnabled() and ds.pal.isEnabled() and ds.run_btn.isEnabled()
assert len(ds.undo) == depth + 1 and t.is_dirty()                                       # writing the gains is exactly one undo step
new_gains = {k: ds.sk["controller"][k] for k in old_gains}
assert new_gains["ki"] == 0 and new_gains["pki"] == 0 and new_gains["kp"] > 0
for k in ("kp", "kd", "pkp", "pkd"):
    assert abs(new_gains[k] / lr.best.gains[k] - 1) < 5e-3, k                           # rounded for display, otherwise what the best trial used
assert ds.n_tkp.value == new_gains["kp"] and ds.n_tkp.isReadOnly()                      # shown under Advanced, read-only
assert ds.result.ok and abs(ds.result.t[-1] - 10.0) < 1e-9 and ds.timer.isActive()      # the best run (fine physics step) plays on the main plots
ds.pause()
assert "balanced" in lr.summary() and ds.lbl_count.text().startswith("16 trials so far") and "Best so far (trial %d" % lr.best.index in ds.lbl_best.text()
assert ds.trial_lbl.text() == "" and ds.score.mark is None

# undo takes the old gains back, and the trials are still valid (the gains are not part of the problem)
ds.do_undo()
assert {k: ds.sk["controller"][k] for k in old_gains} == old_gains and ds.learner is lr and ds.learn_btn.text() == "Continue learning"

# Continue learning: the same search carries on
ds.n_cap.setValue(8)
ds.learn_btn.click()
assert ds.learning and ds.learner is lr
wait(lambda: not ds.learning, 120)
assert len(lr.history) == 24 and lr.stop_reason == "trials" and len(ds.score.pts) == 24
ds.pause()

# a different goal is a different problem: the old trials go
commit(ds.n_gx, 1.5)
assert ds.learner is None and ds.score.pts == [] and ds.learn_btn.text() == "Learn" and not ds.restart_btn.isVisible() and ds.lbl_count.text() == ""
ds.do_undo()

# Start over forgets the trials and begins again
ds.n_cap.setValue(8)
ds.learn_btn.click()
wait(lambda: not ds.learning, 120)
first = ds.learner
assert len(first.history) == 8
ds.restart_btn.click()
assert ds.learning and ds.learner is not first
wait(lambda: not ds.learning, 120)
assert len(ds.learner.history) == 8 and len(ds.score.pts) == 8
ds.pause()

# ---- Stop: it ends promptly, keeps the best, and the gains go in ---------------------------------------------------------------------------------------------
ds.n_cap.setValue(400)
ds.restart_btn.click()
wait(lambda: len(ds.learner.history) >= 3)
depth = len(ds.undo)
ds.learn_btn.click()
assert ds.stopping and ds.learn_btn.text() == "Stopping…" and not ds.learn_btn.isEnabled()
t0 = time.time()
wait(lambda: not ds.learning, 30)
assert time.time() - t0 < 5 and ds.learner.stop_reason == "stopped" and 3 <= len(ds.learner.history) < 400 and ds.worker is None
assert len(ds.undo) == depth + 1 and "Stopped by you" in ds.summary.text() and ds.result is not None and ds.result.ok
ds.pause()
ds.do_undo()

# the stop conditions can be changed while it runs: with "well damped" on, a good design ends the run by itself
ds.n_cap.setValue(400)
ds.ck_damped.setChecked(True)
ds.restart_btn.click()
wait(lambda: not ds.learning, 120)
assert ds.learner.stop_reason == "damped" and "well damped" in ds.summary.text() and ds.learner.best.zeta >= 0.95
ds.pause()

# ---- Live at real-time speed: every trial plays in turn and the learner never runs far ahead of the screen ----------------------------------------------------
ds.ck_damped.setChecked(False)
ds.n_cap.setValue(10)
ds.rb_live.setChecked(True)
ds.speed_l.setCurrentIndex(2)                                                          # 5x
assert ds.is_live() and ds.speed_l.isEnabled() and not ds.show_c.isEnabled()
ds.restart_btn.click()
assert ds.worker.live
t0, shown, ahead = time.time(), [], 0
wait(lambda: ds.rp is not None, 30)
while len(shown) < 3 and time.time() - t0 < 60:
    app.processEvents()
    time.sleep(0.005)
    if ds.rp is not None:
        if not shown or shown[-1] != ds.rp["tr"].index:
            shown.append(ds.rp["tr"].index)
        ahead = max(ahead, len(ds.learner.history) - ds.rp["tr"].index)
assert shown[:3] == [1, 2, 3], shown                                                    # in order, none skipped
assert ahead <= 2, ahead                                                                # at most the next trial is being worked out while one plays
assert ds.trial_lbl.text().startswith("Trial") and ds.view.animating and ds.score.mark in (1, 2, 3, 4)
assert "trial" in ds.tlabel.text()
ds.rb_bg.setChecked(True)                                                              # flip to the background without losing anything
assert not ds.worker.live and ds.show_c.isEnabled() and not ds.speed_l.isEnabled()
wait(lambda: not ds.learning, 60)
assert len(ds.learner.history) == 10 and ds.learner.stop_reason == "trials" and ds.result is not None and ds.result.ok
ds.pause()

# Stop works while the learner is waiting for a live replay to finish
ds.speed_l.setCurrentIndex(0)                                                          # 1x
ds.rb_live.setChecked(True)
ds.restart_btn.click()
wait(lambda: ds.rp is not None, 30)
t0 = time.time()
ds.learn_btn.click()
wait(lambda: not ds.learning, 30)
assert time.time() - t0 < 5 and ds.learner.stop_reason == "stopped" and ds.worker is None
ds.pause()
ds.rb_bg.setChecked(True)

# Show: best so far only / every 10th trial choose what is replayed in the background
lr_t = [type("T", (), dict(index=i, is_best=(i in (1, 4, 9))))() for i in range(1, 25)]
ds.show_c.setCurrentIndex(1)
assert [t_.index for t_ in lr_t if ds.wants_replay(t_)] == [1, 11, 21]
ds.show_c.setCurrentIndex(2)
assert [t_.index for t_ in lr_t if ds.wants_replay(t_)] == [1, 4, 9]
ds.show_c.setCurrentIndex(0)
assert len(lr_t) == sum(ds.wants_replay(t_) for t_ in lr_t)

# the section can be closed or reloaded in the middle of learning without leaving a thread behind
ds.restart_btn.click()
wait(lambda: len(ds.learner.history) >= 2, 30)
w = ds.worker
ds.from_json({})
assert not ds.learning and ds.worker is None and ds.learner is None and ds.score.pts == []
wait(lambda: not w.is_alive(), 30)
ds.pause()

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
assert "Dynamic simulation" in readme and "ctl_dyn.py" in readme and "ctl_learn.py" in readme and "Learn" in readme
print("PASS controls dyn tab")
