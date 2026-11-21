"""ctl_dyn_learn_ui.py - the Learn part of the Dynamic simulation section (a mixin for DynamicSection).

Learn runs ctl_learn.Learner on a background thread (ctl_learn.Worker).  The screen polls the thread's queue with a timer, so nothing Qt happens off the
main thread.  Two ways to watch:
  * In the background (default): the learner runs at full speed; some trials are replayed on the drawing, each fast (about half a second), and the
    replay trails the learning by a trial or two.  Which ones: every trial, every 10th, or only when a new best appears.
  * Live at real-time speed: every trial is replayed in real time (1x, 2x or 5x), one after another; the learner waits for the screen, never
    running more than one trial ahead.
The mode can be flipped while it runs.  Stop (or one of the stop conditions) ends it; the best gains are then written into the controller as one undo step
and the best run is shown with the normal plots.
"""
import copy
import json
import queue
import time

import numpy as np

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QSpinBox

import ctl_dyn as dyn
import ctl_learn as learn
from ctl_dyn_widgets import head, small

GAIN_KEYS = ("kp", "ki", "kd", "pkp", "pki", "pkd")
SHOW = (("Every trial", "all"), ("Every 10th trial", "tenth"), ("Best so far only", "best"))
SPEEDS = (("1×", 1.0), ("2×", 2.0), ("5×", 5.0))
DEFAULT_PREFS = dict(live=False, speed=1.0, show="all", stop_stagnant=True, stop_damped=True, cap=400, by_hand=False)
BG_REPLAY_S = 0.6                            # a replay in background mode lasts about this long, whatever the length of the run
HOLD_LIVE, HOLD_BG = 0.5, 0.1                # the last frame (a fall, say) stays up this long before the next trial starts
POLL_MS, FRAME_MS = 30, 33


class LearnUI:
    """Mixin: needs sk, status, summary, plots, view, score, trial_lbl, tlabel, undo helpers and set_result from DynamicSection."""

    # ============================================================================================================== the block in the left column
    def init_learn(self):
        self.learner = None
        self.worker = None
        self.learning = False
        self.stopping = False
        self.learn_sig = None
        self.run_start = 0
        self.rq = []                                       # trials waiting to be replayed
        self.rp = None                                     # the replay on screen: {tr, res, t, hold}
        self.shown_index = 0
        self.poll_timer = QTimer()
        self.poll_timer.setInterval(POLL_MS)
        self.poll_timer.timeout.connect(self.poll)
        self.rtimer = QTimer()
        self.rtimer.setInterval(FRAME_MS)
        self.rtimer.timeout.connect(self.replay_tick)
        self.inputs.destroyed.connect(self._abandon)

    def _abandon(self, *_):
        w = self.worker
        if w is not None:
            w.stop()

    def build_learn(self, lay):
        lay.addWidget(head("Learn the controller"))
        lay.addWidget(small("The program finds the gains itself. Each trial is one full run from the start with new gains; a trial that tips over or "
                            "touches the ground fails and other gains are tried. It stops when you press Stop, when the best gains are well damped, or when "
                            "they stop improving."))
        row = QHBoxLayout()
        self.learn_btn = QPushButton("Learn")
        self.learn_btn.setStyleSheet("font-weight:bold;")
        self.learn_btn.setToolTip("Find the PID gains by trying them. Needs the self-balancing robot drawing (a wheel with one body link) and a goal position.")
        self.learn_btn.clicked.connect(lambda _=False: self.learn_pressed())
        self.restart_btn = QPushButton("Start over")
        self.restart_btn.setToolTip("Forget the trials so far and learn again from the starting design.")
        self.restart_btn.clicked.connect(lambda _=False: self.restart_learning())
        self.restart_btn.setVisible(False)
        row.addWidget(self.learn_btn)
        row.addWidget(self.restart_btn)
        lay.addLayout(row)
        self.rb_bg = QRadioButton("In the background")
        self.rb_bg.setToolTip("Learn at full speed. Some trials are replayed on the drawing, quickly, a little behind the learning.")
        self.rb_live = QRadioButton("Live at real-time speed")
        self.rb_live.setToolTip("Every trial is played on the drawing in real time, one after another, and the learner waits for each to finish.\n"
                                "A trial lasts as long as its run (10 s for the robot example), so 30 trials take about 5 minutes at 1x, or one minute at 5x.")
        grp = QButtonGroup(self.inputs)
        grp.addButton(self.rb_bg)
        grp.addButton(self.rb_live)
        self._mode_group = grp
        self.rb_bg.setChecked(True)
        lay.addWidget(self.rb_bg)
        lay.addWidget(self.rb_live)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.speed_l = QComboBox()
        self.speed_l.setMinimumHeight(24)
        for label, v in SPEEDS:
            self.speed_l.addItem(label, v)
        self.speed_l.setToolTip("How fast the trials play in live mode.")
        self.show_c = QComboBox()
        self.show_c.setMinimumHeight(24)
        for label, v in SHOW:
            self.show_c.addItem(label, v)
        self.show_c.setToolTip("Which trials are replayed in background mode. (Live mode shows every trial.)")
        form.addRow("Live playback speed", self.speed_l)
        form.addRow("Show (background)", self.show_c)
        lay.addLayout(form)
        self.ck_stagnant = QCheckBox("Stop when it stops improving")
        self.ck_stagnant.setChecked(True)
        self.ck_damped = QCheckBox("Stop when well damped (critical damping)")
        self.ck_damped.setChecked(True)
        self.ck_damped.setToolTip("Every pole of the linearised loop has a damping ratio of at least 0.95 and the run overshoots the target by under 2 %.")
        cap_row = QHBoxLayout()
        self.n_cap = QSpinBox()
        self.n_cap.setRange(8, 5000)
        self.n_cap.setValue(400)
        self.n_cap.setMinimumHeight(24)
        self.n_cap.setToolTip("The most trials in one go. Continue learning adds this many more.")
        cap_row.addWidget(QLabel("Trial limit"))
        cap_row.addWidget(self.n_cap)
        cap_row.addStretch(1)
        lay.addWidget(self.ck_stagnant)
        lay.addWidget(self.ck_damped)
        lay.addLayout(cap_row)
        self.lbl_count = small("")
        self.lbl_best = small("")
        lay.addWidget(self.lbl_count)
        lay.addWidget(self.lbl_best)
        self.rb_bg.toggled.connect(lambda _=False: self.mode_changed())
        self.rb_live.toggled.connect(lambda _=False: self.mode_changed())
        for w in (self.ck_stagnant, self.ck_damped):
            w.toggled.connect(lambda _=False: self.sync_stop_settings())
        self.n_cap.valueChanged.connect(lambda _=0: self.sync_stop_settings())
        self.mode_changed()

    # ============================================================================================================== settings and files
    def is_live(self):
        return self.rb_live.isChecked()

    def learn_prefs(self):
        return dict(live=self.is_live(), speed=float(self.speed_l.currentData()), show=self.show_c.currentData(), stop_stagnant=self.ck_stagnant.isChecked(),
                    stop_damped=self.ck_damped.isChecked(), cap=int(self.n_cap.value()), by_hand=bool(self.by_hand.isChecked()))

    def set_learn_prefs(self, d):
        p = dict(DEFAULT_PREFS)
        for k, v in (d or {}).items():
            if k in p:
                p[k] = v
        try:
            self.rb_live.setChecked(bool(p["live"]))
            self.rb_bg.setChecked(not bool(p["live"]))
            self.speed_l.setCurrentIndex(max(0, self.speed_l.findData(float(p["speed"]))))
            self.show_c.setCurrentIndex(max(0, self.show_c.findData(p["show"])))
            self.ck_stagnant.setChecked(bool(p["stop_stagnant"]))
            self.ck_damped.setChecked(bool(p["stop_damped"]))
            self.n_cap.setValue(int(min(max(int(p["cap"]), 8), 5000)))
            self.by_hand.setChecked(bool(p["by_hand"]))
        except (TypeError, ValueError):                    # a hand-edited file with nonsense in it keeps the defaults
            pass
        self.mode_changed()

    def learn_settings(self):
        return dict(max_trials=int(self.n_cap.value()), stop_stagnant=self.ck_stagnant.isChecked(), stop_damped=self.ck_damped.isChecked())

    def sync_stop_settings(self):
        """The stop conditions can be changed while it runs."""
        lr = self.learner
        if lr is None or not self.learning:
            return
        s = self.learn_settings()
        lr.set.update(stop_stagnant=s["stop_stagnant"], stop_damped=s["stop_damped"])
        lr.limit = self.run_start + s["max_trials"]

    def mode_changed(self):
        live = self.is_live()
        self.speed_l.setEnabled(live)
        self.show_c.setEnabled(not live)
        w = self.worker
        if w is not None:
            w.live = live
            if not live:
                w.release()                                # leaving live mode: do not leave the learner waiting for the screen

    def sketch_sig(self):
        """The drawing and goal without the gains: if this is unchanged, the trials so far are still about this problem."""
        sk = copy.deepcopy(self.sk)
        for k in GAIN_KEYS:
            sk["controller"].pop(k, None)
        sk["run"].pop("duration", None)
        sk["run"].pop("push", None)
        return json.dumps(sk, sort_keys=True)

    def sync_learn_state(self):
        """Called after any edit: trials that belong to a different drawing are dropped."""
        if self.learning:
            return
        if self.learner is not None and self.sketch_sig() != self.learn_sig:
            self.drop_learner()
        self.update_learn_buttons()

    def drop_learner(self):
        self.learner = None
        self.learn_sig = None
        self.score.reset()
        self.trial_lbl.setText("")
        self.lbl_count.setText("")
        self.lbl_best.setText("")

    # ============================================================================================================== pressing Learn / Stop
    def update_learn_buttons(self):
        if self.learning:
            text, enabled = ("Stopping…" if self.stopping else "Stop"), not self.stopping
            self.restart_btn.setVisible(False)
        else:
            resumable = self.learner is not None and bool(self.learner.history)
            text, enabled = ("Continue learning" if resumable else "Learn"), not self.running
            self.restart_btn.setVisible(resumable)
        for b in (self.learn_btn, self.learn_btn2):
            b.setText(text)
            b.setEnabled(enabled)
        self.restart_btn.setEnabled(not self.running and not self.learning)

    def learn_pressed(self):
        if self.learning:
            self.stop_learning()
        else:
            self.start_learning()

    def restart_learning(self):
        if self.learning or self.running:
            return
        self.drop_learner()
        self.update_learn_buttons()
        self.start_learning()

    def start_learning(self):
        if self.running or self.learning:
            return
        why = learn.refusal(self.sk)
        if why:
            self.status.setText(why)
            self.refresh_notes()
            return
        self.pause()
        s = self.learn_settings()
        if self.learner is not None and self.learner.history and self.sketch_sig() == self.learn_sig:
            lr = self.learner
            lr.set.update(stop_stagnant=s["stop_stagnant"], stop_damped=s["stop_damped"])
            self.run_start = len(lr.history)
            lr.resume(more=s["max_trials"])
        else:
            try:
                lr = learn.Learner(self.sk, s)
            except dyn.SketchError as e:
                self.status.setText(str(e))
                return
            self.learner, self.learn_sig, self.run_start = lr, self.sketch_sig(), 0
            self.score.reset()
        self.rq, self.rp, self.stopping = [], None, False
        self.result = None
        self.plots.set_result(None)
        self.set_player(False)
        self.learning = True
        self.set_busy(True)
        self.status.setText("")
        self.summary.setText("Learning… the trials appear on the drawing and in the score graph.")
        self.worker = learn.Worker(lr)
        self.worker.live = self.is_live()
        self.update_learn_buttons()
        self.update_counts()
        self.worker.start()
        self.poll_timer.start()

    def stop_learning(self):
        if not self.learning or self.stopping:
            return
        self.stopping = True
        if self.worker is not None:
            self.worker.stop()
        self.update_learn_buttons()

    # ============================================================================================================== trials arriving
    def poll(self):
        try:
            self._poll()
        except Exception as e:                             # noqa: BLE001 - a problem here must end the learning cleanly, not close the program
            self.abort_learning(e)

    def abort_learning(self, e):
        self.poll_timer.stop()
        self.rtimer.stop()
        w, self.worker = self.worker, None
        if w is not None:
            w.stop()
        self.rp, self.rq = None, []
        self.learning = self.stopping = False
        self.set_busy(False)
        self.status.setText("Learning stopped because of a problem: %s" % e)
        self.update_learn_buttons()

    def _poll(self):
        w = self.worker
        if w is None:
            self.poll_timer.stop()
            return
        for _ in range(64):
            try:
                item = w.out.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple):
                self.finish_learning(item)
                return
            self.on_trial(item)
        self.pump()

    def wants_replay(self, tr):
        if self.is_live():
            return True
        mode = self.show_c.currentData()
        if mode == "best":
            return bool(tr.is_best)
        if mode == "tenth":
            return (tr.index - 1) % 10 == 0
        return True

    def on_trial(self, tr):
        self.score.add(tr)
        if self.wants_replay(tr):
            self.rq.append(tr)
            if not self.is_live():                         # replay trails the learning: keep it to the latest couple, never dropping a best
                while len(self.rq) > 2:
                    drop = next((t for t in self.rq[:-1] if not t.is_best), None)
                    self.rq.remove(drop if drop is not None else self.rq[0])
        self.update_counts()

    def update_counts(self):
        lr = self.learner
        if lr is None:
            return
        n = len(lr.history)
        ok = sum(1 for t in lr.history if t.ok)
        self.lbl_count.setText("%d trials so far: %d balanced, %d fell or hit the ground." % (n, ok, n - ok) if n else "Starting…")
        b = lr.best
        if b is not None and b.ok:
            g = b.gains
            self.lbl_best.setText("Best so far (trial %d, score %.2f): tilt Kp %.4g, Kd %.4g; position Kp %.4g, Kd %.4g." % (b.index, b.cost, g["kp"], g["kd"], g["pkp"], g["pkd"]))
        else:
            self.lbl_best.setText("Nothing has balanced yet." if n else "")

    # ============================================================================================================== replaying a trial on the drawing
    def pump(self):
        if self.rp is None and self.rq and self.learning:
            self.start_replay(self.rq.pop(0))

    def start_replay(self, tr):
        res = tr.res
        if res is None or res.n < 2:
            if self.worker is not None:
                self.worker.release()                      # nothing to show: never leave the learner waiting for a replay that will not come
            return
        self.rp = dict(tr=tr, res=res, t=0.0, hold=None, last=time.monotonic())
        self.shown_index = tr.index
        self.plots.set_result(res)
        self.score.set_mark(tr.index)
        self.trial_lbl.setText(tr.line(self.learner.best if self.learner else None))
        self.draw_trial_frame(res, 0.0)
        self.rtimer.start()
        if self.is_live() and self.worker is not None:
            self.worker.release()                          # the learner may now work on the next trial while this one plays

    def replay_speed(self, res):
        if self.is_live():
            return float(self.speed_l.currentData() or 1.0)
        return max(1.0, float(res.t[-1]) / BG_REPLAY_S)

    def replay_tick(self):
        try:
            self._replay_tick()
        except Exception as e:                             # noqa: BLE001
            self.abort_learning(e)

    def _replay_tick(self):
        r = self.rp
        if r is None:
            self.rtimer.stop()
            return
        res = r["res"]
        now = time.monotonic()
        dt = min(now - r["last"], 0.25)                    # real elapsed time, so a stuttering screen does not slow a "real-time" replay
        r["last"] = now
        if r["hold"] is not None:
            r["hold"] -= dt
            if r["hold"] <= 0:
                self.rp = None
                if self.learning:
                    self.pump()
                if self.rp is None:
                    self.rtimer.stop()
            return
        r["t"] += dt * self.replay_speed(res)
        if r["t"] >= res.t[-1]:
            r["t"] = float(res.t[-1])
            r["hold"] = HOLD_LIVE if self.is_live() else HOLD_BG
        self.draw_trial_frame(res, r["t"])

    def draw_trial_frame(self, res, t):
        i = min(int(np.searchsorted(res.t, t - 1e-12)), res.n - 1)
        mdl = res.mdl
        use_pos = mdl.has_pos and bool(res.sk["controller"]["pos_on"])
        note = ""
        if i == res.n - 1 and not res.ok:
            note = "Fell over" if res.reason == "tilt" else "Hit the ground"
        self.view.show_frame(mdl, res.z[i], float(res.goal[i]) if use_pos else None, note)
        self.plots.set_time(float(res.t[i]))
        self.tlabel.setText("trial %d: %.2f s / %.1f s" % (self.shown_index, res.t[i], res.t[-1]))

    # ============================================================================================================== the end
    def finish_learning(self, item):
        self.poll_timer.stop()
        self.rtimer.stop()
        self.rp, self.rq = None, []
        w, self.worker = self.worker, None
        if w is not None:
            w.join(2.0)
        self.learning = self.stopping = False
        lr = self.learner
        self.set_busy(False)
        self.score.set_mark(None)
        self.trial_lbl.setText("")
        if item[0] == "error":
            self.status.setText("Learning stopped because of a problem: %s" % item[1])
            self.summary.setText(lr.summary() if lr is not None and lr.history else "")
            self.update_counts()
            self.update_learn_buttons()
            return
        self.update_counts()
        best = lr.best
        if best is None or not best.ok:
            self.summary.setText(lr.summary() + " No gains balanced the robot, so the controller was not changed. Check that the motor is strong enough for the "
                                 "body, or loosen the fall limit.")
            self.view.show_static()
            self.update_learn_buttons()
            self.refresh_controller()
            return
        gains = lr.best_gains()
        self.push_undo()                                   # writing the learned gains is one undo step
        dyn.apply_gains(self.sk, dict(ki=0.0, pki=0.0, **gains))      # the learner uses PD loops; the integral gains are 0
        self.learn_sig = self.sketch_sig()
        self.refresh_controller()
        self.changed()
        res = (w.final if w is not None else None) or lr.verify()
        self.set_result(res)
        text = lr.summary() + "\n" + res.summary() + "\nThe gains were written into the controller (Advanced); Undo takes the old ones back."
        if lr.stop_reason in ("damped", "stagnant"):
            text += " To keep searching, untick the stop condition and press Continue learning."
        self.summary.setText(text)
        self.update_learn_buttons()
