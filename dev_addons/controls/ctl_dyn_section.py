"""ctl_dyn_section.py - the "Dynamic simulation" section of the Controls tab.

Draw a self-balancing robot (or another mechanism) from preset parts, say where it should go and what it must not do (tip over or touch the ground), and press
Learn: the program finds the PID gains itself by trying them, in the background, while you watch the trials.  The gains it finds are shown under Advanced, where
they can also be set by hand and tried with a single run.  The engine is ctl_dyn.py, the learner ctl_learn.py (no Qt); the Learn panel is ctl_dyn_learn_ui.py; the
drawing and the plots are in ctl_dyn_view.py.  Units are SI (m, kg, s, N, N*m, degrees for angles); File > Units does not change this section yet.
"""
import copy
import math

import numpy as np

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSlider,
                             QSplitter, QVBoxLayout, QWidget)

import ctl_core as core
import ctl_dyn as dyn
from ctl_dyn_learn_ui import LearnUI
from ctl_dyn_view import ScorePlot, SignalPlots, SketchView
from ctl_dyn_widgets import NumEdit, head, small
from ctl_section import Section

HINT = "Press Learn to find the gains for this drawing, or open Advanced and press Run to try gains by hand. The tilt, position and motor effort appear here."
UNDO_LIMIT = 60
KIND_LABEL = {"wheel": "wheel", "cart": "cart", "pivot": "pivot", "link": "link", "mass": "mass"}


class DynamicSection(LearnUI, Section):
    key = "dynamic"
    title = "Dynamic simulation: balance a drawn system"

    def __init__(self, changed):
        super().__init__(changed)
        self.sk = dyn.example_robot()
        self.sel = "wheel"
        self.result = None
        self.undo = []
        self.loading = False
        self.running = False
        self.stop_flag = False
        self.t_play = 0.0
        self.frame_i = 0
        self.refreshers = []
        self.labels = {}
        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.init_learn()
        self.build_inputs()
        self.build_results()
        self.refresh_all()

    @property
    def busy(self):
        return self.running or self.learning

    # ============================================================================================================== the left column
    def build_inputs(self):
        lay = QVBoxLayout(self.inputs)
        lay.setContentsMargins(8, 4, 8, 8)
        self.ex = QComboBox()
        self.ex.addItem("Examples…")
        for name, _ in dyn.SHOWN_EXAMPLES:
            self.ex.addItem(name)
        self.ex.activated.connect(self.load_example)
        lay.addWidget(self.ex)

        lay.addWidget(head("Drawing"))
        self.pal = QWidget()
        pl = QVBoxLayout(self.pal)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(3)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        self.add_btn = {}
        for kind, tip in (("wheel", "Base: a wheel that rolls on the ground without slipping"), ("cart", "Base: a cart that slides along the ground"),
                          ("pivot", "Base: a fixed pin at a height above the ground")):
            self.add_btn[kind] = self._btn(r1, kind.capitalize(), tip, lambda _=False, k=kind: self.add(k))
        self.add_btn["link"] = self._btn(r2, "Link", "A rod, pinned to the selected part", lambda _=False: self.add("link"))
        self.add_btn["mass"] = self._btn(r2, "Mass", "A point mass on the selected link", lambda _=False: self.add("mass"))
        self.del_btn = self._btn(r2, "Delete", "Delete the selected part and everything attached to it", lambda _=False: self.delete())
        self.undo_btn = self._btn(r2, "Undo", "Undo the last change to the drawing or the numbers", lambda _=False: self.do_undo())
        pl.addLayout(r1)
        pl.addLayout(r2)
        lay.addWidget(self.pal)
        lay.addWidget(small("Pick a part in the list or in the drawing; Link and Mass attach to the picked part. The wheel, the body and the masses are the "
                            "geometry; the motor's maximum torque is the hardware limit. Metres, kilograms, N·m; angles in degrees."))
        self.plist = QListWidget()
        self.plist.setMinimumHeight(72)
        self.plist.setMaximumHeight(110)
        self.plist.currentRowChanged.connect(self._row)
        lay.addWidget(self.plist)
        self.pbox = QFrame()
        self.pform = QFormLayout(self.pbox)
        self.pform.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.pbox)

        lay.addWidget(head("Goal and condition"))
        self.gbox = QFrame()
        gf = QFormLayout(self.gbox)
        gf.setContentsMargins(0, 0, 0, 0)
        c = lambda: self.sk["controller"]                                                       # noqa: E731
        g = lambda: c()["goal"]                                                                 # noqa: E731
        r = lambda: self.sk["run"]                                                              # noqa: E731
        self.c_balance = QComboBox()
        self.c_balance.setMinimumHeight(24)
        self.c_balance.setToolTip("The link that must not tip over.")
        self.c_balance.activated.connect(lambda _: self.edit(lambda: c().__setitem__("balance", self.c_balance.currentData())))
        gf.addRow("Keep this link upright", self.c_balance)
        self.pos_on = QCheckBox("Reach and hold a goal position (x)")
        self.pos_on.setToolTip("The objective: get the base to a target x and keep it there.")
        self.pos_on.toggled.connect(lambda on: self.edit(lambda: c().__setitem__("pos_on", bool(on))))
        gf.addRow(self.pos_on)
        self.g_kind = QComboBox()
        self.g_kind.setMinimumHeight(24)
        for k, label in (("hold", "Fixed point"), ("step", "Step at a time"), ("ramp", "Ramp (moves at a speed)")):
            self.g_kind.addItem(label, k)
        self.g_kind.activated.connect(lambda _: self.edit(lambda: g().__setitem__("kind", self.g_kind.currentData())))
        gf.addRow("Goal", self.g_kind)
        self.nrow(gf, "gx", "Goal x (m)", lambda: g()["x"], lambda v: g().__setitem__("x", v), "Where the base should end up.")
        self.nrow(gf, "gr", "Ramp speed (m/s)", lambda: g()["rate"], lambda v: g().__setitem__("rate", v), "How fast a ramp goal moves toward x.")
        self.nrow(gf, "gt", "Starts at (s)", lambda: g()["t"], lambda v: g().__setitem__("t", v), "When a step or a ramp begins.")
        self.nrow(gf, "st", "Starts leaning (°)", lambda: r()["start_tilt"], lambda v: r().__setitem__("start_tilt", v),
                  "How far the balancing link starts away from the drawn angle (positive = toward +x).")
        self.nrow(gf, "lim", "Fallen when it leans past (°)", lambda: r()["tilt_limit"], lambda v: r().__setitem__("tilt_limit", v),
                  "The condition: a trial fails when the tilt passes this, or when any part touches the ground.")
        lay.addWidget(self.gbox)

        self.build_learn(lay)

        self.adv_btn = QPushButton("Advanced ▸")
        self.adv_btn.setCheckable(True)
        self.adv_btn.setFlat(True)
        self.adv_btn.setStyleSheet("text-align:left;font-weight:bold;margin-top:8px;")
        self.adv_btn.setToolTip("The learned gains, and a single run with gains you type yourself.")
        lay.addWidget(self.adv_btn)
        self.adv_box = QFrame()
        al = QVBoxLayout(self.adv_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(small("These gains are what the learner found; they are read-only. Tick the box to type your own and test them with Run."))
        self.by_hand = QCheckBox("Set the gains by hand")
        self.by_hand.toggled.connect(lambda _=False: self.by_hand_changed())
        al.addWidget(self.by_hand)
        self.cbox = QFrame()
        cf = QFormLayout(self.cbox)
        cf.setContentsMargins(0, 0, 0, 0)
        self.nrow(cf, "tkp", "Tilt  Kp", lambda: c()["kp"], lambda v: c().__setitem__("kp", v), "Motor effort per radian of tilt (N·m/rad, or N/rad for a cart).")
        self.nrow(cf, "tki", "Tilt  Ki", lambda: c()["ki"], lambda v: c().__setitem__("ki", v), "Integral gain on the tilt error (0 = off).")
        self.nrow(cf, "tkd", "Tilt  Kd", lambda: c()["kd"], lambda v: c().__setitem__("kd", v),
                  "Damping: motor effort per rad/s of tilt rate (it uses the measured rate, like a gyro).")
        self.nrow(cf, "pkp", "Position  Kp", lambda: c()["pkp"], lambda v: c().__setitem__("pkp", v), "Tilt target (rad) per metre of position error.")
        self.nrow(cf, "pki", "Position  Ki", lambda: c()["pki"], lambda v: c().__setitem__("pki", v), "Integral gain on the position error (0 = off).")
        self.nrow(cf, "pkd", "Position  Kd", lambda: c()["pkd"], lambda v: c().__setitem__("pkd", v), "Tilt target (rad) per m/s of speed (damps the motion).")
        self.nrow(cf, "clamp", "Largest lean (°)", lambda: c()["tilt_clamp"], lambda v: c().__setitem__("tilt_clamp", v),
                  "The position loop is never allowed to ask for more tilt than this.")
        self.nrow(cf, "rate", "Sample rate (Hz)", lambda: c()["rate"], lambda v: c().__setitem__("rate", v), "How often the controller reads the sensors and updates the motor.")
        al.addWidget(self.cbox)
        self.sug_btn = QPushButton("Suggest gains")
        self.sug_btn.setToolTip("Work out PID gains for this drawing from its linearised model (a linear-quadratic design written as a cascade of PIDs). "
                                "This is also where Learn starts from.")
        self.sug_btn.clicked.connect(lambda _=False: self.suggest())
        al.addWidget(self.sug_btn)
        al.addWidget(head("Try the gains once"))
        self.rbox = QFrame()
        rf = QFormLayout(self.rbox)
        rf.setContentsMargins(0, 0, 0, 0)
        self.nrow(rf, "dur", "Duration (s)", lambda: r()["duration"], lambda v: r().__setitem__("duration", v))
        self.push_on = QCheckBox("Push the top once")
        self.push_on.toggled.connect(lambda on: self.edit(lambda: r()["push"].__setitem__("on", bool(on))))
        rf.addRow(self.push_on)
        p = lambda: r()["push"]                                                                 # noqa: E731
        self.nrow(rf, "pf", "Push force (N)", lambda: p()["force"], lambda v: p().__setitem__("force", v))
        self.nrow(rf, "pt", "Push at (s)", lambda: p()["t"], lambda v: p().__setitem__("t", v))
        self.nrow(rf, "pd", "Push lasts (s)", lambda: p()["dur"], lambda v: p().__setitem__("dur", v))
        al.addWidget(self.rbox)
        self.run_btn = QPushButton("Run")
        self.run_btn.setStyleSheet("font-weight:bold;")
        self.run_btn.setToolTip("Run the controller once with the gains shown above.")
        self.run_btn.clicked.connect(lambda _=False: self.run())
        al.addWidget(self.run_btn)
        self.tf_btn = QPushButton("Open G(s) in Transfer function")
        self.tf_btn.setToolTip("Linearise at the drawn pose and send G(s) (motor command to tilt) to the Transfer function section: poles, zeros, Routh test.")
        self.tf_btn.clicked.connect(lambda _=False: self.send_tf())
        al.addWidget(self.tf_btn)
        self.adv_box.setVisible(False)
        lay.addWidget(self.adv_box)
        self.adv_btn.toggled.connect(self.show_advanced)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#1d6b5f;")
        lay.addWidget(self.status)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.msg)
        lay.addStretch(1)
        self.groups = [self.pal, self.plist, self.pbox, self.gbox, self.cbox, self.rbox, self.ex, self.sug_btn, self.tf_btn, self.by_hand]

    def show_advanced(self, on):
        self.adv_box.setVisible(bool(on))
        self.adv_btn.setText("Advanced ▾" if on else "Advanced ▸")

    def by_hand_changed(self):
        if self.loading:
            return
        self.refresh_controller()
        self.changed()

    def _btn(self, layout, text, tip, fn):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(fn)
        layout.addWidget(b)
        return b

    def nrow(self, form, key, label, getter, setter, tip=""):
        """A labelled number field bound to a value in the sketch; editing it is one undoable step."""
        w = NumEdit(getter(), tip)
        w.committed.connect(lambda v, s=setter: self.edit(lambda: s(v)))
        lb = QLabel(label)
        if tip:
            lb.setToolTip(tip)
        form.addRow(lb, w)
        self.labels[key] = (lb, label)
        setattr(self, "n_" + key, w)
        self.refreshers.append(lambda w=w, g=getter: w.set_value(g()))

    # ============================================================================================================== the right page
    def build_results(self):
        rl = QVBoxLayout(self.results)
        rl.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(4, 4, 4, 0)
        self.trial_lbl = QLabel("")
        self.trial_lbl.setStyleSheet("font-weight:bold;color:#2b4c7e;")
        self.view = SketchView()
        self.view.picked.connect(self.select)
        self.score = ScorePlot()
        row = QSplitter(Qt.Orientation.Horizontal)
        row.addWidget(self.view)
        row.addWidget(self.score)
        row.setStretchFactor(0, 3)
        row.setStretchFactor(1, 2)
        row.setSizes([520, 340])
        bar = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(lambda _=False: self.toggle_play())
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._slid)
        self.tlabel = QLabel("")
        self.tlabel.setMinimumWidth(170)
        self.speed = QComboBox()
        for label, v in (("1×", 1.0), ("0.5×", 0.5), ("0.25×", 0.25), ("2×", 2.0)):
            self.speed.addItem(label, v)
        self.speed.setToolTip("Playback speed")
        for wdg in (self.play_btn, self.slider, self.tlabel, self.speed):
            bar.addWidget(wdg, 1 if wdg is self.slider else 0)
        hr = QHBoxLayout()
        self.learn_btn2 = QPushButton("Learn")                  # the same button as in the left column, where the eye already is
        self.learn_btn2.setStyleSheet("font-weight:bold;")
        self.learn_btn2.clicked.connect(lambda _=False: self.learn_pressed())
        hr.addWidget(self.learn_btn2)
        hr.addWidget(self.trial_lbl, 1)
        tl.addLayout(hr)
        tl.addWidget(row, 1)
        tl.addLayout(bar)
        bot = QWidget()
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(4, 0, 4, 4)
        self.plots = SignalPlots()
        self.plots.scrubbed.connect(self.scrub)
        self.summary = QLabel(HINT)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setStyleSheet("padding:4px 2px;")
        bl.addWidget(self.plots, 1)
        bl.addWidget(self.summary)
        split.addWidget(top)
        split.addWidget(bot)
        split.setSizes([430, 380])
        rl.addWidget(split)

    # ============================================================================================================== state, undo, refresh
    def base_kind(self):
        return next((p["kind"] for p in self.sk["parts"] if p["kind"] in dyn.ROOTS), None)

    def motor_unit(self):
        mp = next((p for p in self.sk["parts"] if p.get("motor")), None)
        return "N" if mp is not None and mp["kind"] == "cart" else "N·m"

    def push_undo(self):
        self.undo.append(copy.deepcopy(self.sk))
        del self.undo[:-UNDO_LIMIT]

    def edit(self, fn, structural=False):
        """Every change to the drawing or the numbers goes through here: one undo step, the old result is dropped, the notes are refreshed."""
        if self.busy or self.loading:
            return
        self.push_undo()
        fn()
        self.after_edit(structural)

    def after_edit(self, structural=False):
        self.result = None
        self.pause()
        self.status.setText("")
        self.view.set_sketch(self.sk)
        self.view.show_static()
        self.plots.set_result(None)
        self.summary.setText(HINT)
        self.set_player(False)
        if structural:
            self.refresh_parts()
        self.refresh_controller()
        self.refresh_notes()
        self.changed()

    def do_undo(self):
        if self.busy or not self.undo:
            return
        self.sk = self.undo.pop()
        if dyn.part(self.sk, self.sel) is None:
            self.sel = self.sk["parts"][0]["id"] if self.sk["parts"] else None
        self.result = None
        self.pause()
        self.status.setText("")
        self.refresh_all()
        self.changed()

    def refresh_all(self):
        self.loading = True
        try:
            self.view.set_sketch(self.sk)
            self.view.show_static()
            self.plots.set_result(None)
            self.summary.setText(HINT)
            self.set_player(False)
            self.refresh_parts()
            self.refresh_controller()
            self.refresh_notes()
        finally:
            self.loading = False

    def refresh_parts(self):
        self.plist.blockSignals(True)
        self.plist.clear()
        for p in self.sk["parts"]:
            self.plist.addItem(f'{p.get("name") or p["id"]}   ({KIND_LABEL[p["kind"]]})')
        ids = [p["id"] for p in self.sk["parts"]]
        if self.sel not in ids:
            self.sel = ids[0] if ids else None
        if self.sel in ids:
            self.plist.setCurrentRow(ids.index(self.sel))
        self.plist.blockSignals(False)
        self.view.selected = self.sel
        self.view.update()
        self.rebuild_form()
        base = self.base_kind()
        for k in ("wheel", "cart", "pivot"):
            self.add_btn[k].setEnabled(base is None)
        self.add_btn["link"].setEnabled(base is not None)
        self.add_btn["mass"].setEnabled(any(p["kind"] == "link" for p in self.sk["parts"]))
        self.del_btn.setEnabled(self.sel is not None)
        self.undo_btn.setEnabled(bool(self.undo))

    def refresh_controller(self):
        self.loading = True
        try:
            for fn in self.refreshers:
                fn()
            c = self.sk["controller"]
            links = [p for p in self.sk["parts"] if p["kind"] == "link"]
            self.c_balance.clear()
            for p in links:
                self.c_balance.addItem(p.get("name") or p["id"], p["id"])
            bid = dyn.balance_id(self.sk)
            i = self.c_balance.findData(bid)
            if i >= 0:
                self.c_balance.setCurrentIndex(i)
            self.pos_on.setChecked(bool(c["pos_on"]))
            self.g_kind.setCurrentIndex(max(0, self.g_kind.findData(c["goal"]["kind"])))
            self.push_on.setChecked(bool(self.sk["run"]["push"]["on"]))
        finally:
            self.loading = False
        unit = self.motor_unit()
        for key, text in (("tkp", f"Tilt  Kp  ({unit}/rad)"), ("tki", f"Tilt  Ki  ({unit}/rad·s)"), ("tkd", f"Tilt  Kd  ({unit}·s/rad)"),
                          ("pkp", "Position  Kp  (rad/m)"), ("pki", "Position  Ki  (rad/m·s)"), ("pkd", "Position  Kd  (rad·s/m)")):
            self.labels[key][0].setText(text)
        has_pos = self.base_kind() in ("wheel", "cart")
        on = has_pos and bool(c["pos_on"])
        self.pos_on.setEnabled(has_pos)
        for key in ("pkp", "pki", "pkd", "clamp"):
            getattr(self, "n_" + key).setEnabled(on)
            self.labels[key][0].setEnabled(on)
        self.g_kind.setEnabled(on)
        kind = c["goal"]["kind"]
        for key, enabled in (("gx", on), ("gr", on and kind == "ramp"), ("gt", on and kind in ("step", "ramp"))):
            getattr(self, "n_" + key).setEnabled(enabled)
            self.labels[key][0].setEnabled(enabled)
        for key in ("pf", "pt", "pd"):
            getattr(self, "n_" + key).setEnabled(bool(self.sk["run"]["push"]["on"]))
        hand = self.by_hand.isChecked()                     # the learned gains are shown read-only unless the user chooses to type them
        for key in ("tkp", "tki", "tkd", "pkp", "pki", "pkd"):
            getattr(self, "n_" + key).setReadOnly(not hand)
        self.undo_btn.setEnabled(bool(self.undo))
        self.sync_learn_state()

    def refresh_notes(self):
        errs, warns = dyn.check(self.sk)
        out = ["<span style='color:#b3261e'>%s</span>" % _esc(e) for e in errs] + ["<span style='color:#8a6100'>%s</span>" % _esc(w) for w in warns]
        self.msg.setText("<br>".join(out))
        self.run_btn.setEnabled((not errs or self.running) and not self.learning)

    # ============================================================================================================== the part list and form
    def _row(self, i):
        if 0 <= i < len(self.sk["parts"]) and not self.loading:
            self.select(self.sk["parts"][i]["id"])

    def select(self, pid):
        if dyn.part(self.sk, pid) is None:
            return
        self.sel = pid
        ids = [p["id"] for p in self.sk["parts"]]
        self.plist.blockSignals(True)
        self.plist.setCurrentRow(ids.index(pid))
        self.plist.blockSignals(False)
        self.view.selected = pid
        self.view.update()
        self.rebuild_form()
        self.del_btn.setEnabled(True)

    def rebuild_form(self):
        while self.pform.rowCount():
            self.pform.removeRow(0)
        p = dyn.part(self.sk, self.sel) if self.sel else None
        if p is None:
            return
        k = p["kind"]
        unit_t = "N" if k == "cart" else "N·m"

        def num(label, key, tip="", lo=None):
            w = NumEdit(p[key], tip)
            w.committed.connect(lambda v, key=key: self.edit(lambda: p.__setitem__(key, v)))
            lb = QLabel(label)
            if tip:
                lb.setToolTip(tip)
            self.pform.addRow(lb, w)
            return w

        name = QLineEdit(p.get("name") or p["id"])
        name.setMinimumHeight(24)
        name.editingFinished.connect(lambda: self._rename(p, name.text()))
        self.pform.addRow("Name", name)
        if k == "wheel":
            num("Radius (m)", "r")
            num("Mass (kg)", "m")
            num("Starts at x (m)", "x0")
        elif k == "cart":
            num("Mass (kg)", "m")
            num("Width (m)", "w", "Drawing only.")
            num("Height (m)", "h", "Drawing only; the pole hinge is on top.")
            num("Starts at x (m)", "x0")
        elif k == "pivot":
            num("x (m)", "x")
            num("Height above ground (m)", "y")
        elif k in ("link", "mass"):
            cand = self._parent_candidates(p)
            combo = QComboBox()
            combo.setMinimumHeight(24)
            combo.addItem("(nothing)", None)
            for q in cand:
                combo.addItem(q.get("name") or q["id"], q["id"])
            combo.setCurrentIndex(max(0, combo.findData(p.get("parent"))))
            combo.activated.connect(lambda _, combo=combo: self.edit(lambda: p.__setitem__("parent", combo.currentData()), True))
            self.pform.addRow("Attached to" if k == "link" else "Sits on", combo)
            par = dyn.part(self.sk, p.get("parent")) if p.get("parent") else None
            at = num("Distance along it (m)", "at", "Measured from the start of the link it is attached to.")
            if k == "link" and (par is None or par["kind"] != "link"):
                at.setEnabled(False)
                at.setToolTip("Attached at the centre of the wheel or cart, or at the pivot.")
            if k == "link":
                num("Length (m)", "length")
                num("Mass (kg)", "m", "The rod's own mass (spread evenly); put extra weight on with Mass.")
                num("Drawn angle (°)", "angle", "0 = pointing along +x, 90 = straight up, -90 = straight down.")
                num(f"Spring ({'N·m/rad'})", "k", "Torsion spring between this link and what it hangs from, resting at the drawn angle.")
                num("Damper (N·m·s/rad)", "c", "Viscous friction in the joint.")
            else:
                num("Mass (kg)", "m")
        if k in ("wheel", "cart", "link"):
            cb = QCheckBox("Motor")
            cb.setChecked(bool(p.get("motor")))
            mx = NumEdit(float((p.get("motor") or {}).get("max", 1.0 if k != "cart" else 20.0)),
                         "The most torque (N·m) or force (N) the motor can give. It is ideal: no losses, no back-EMF.")
            mx.setEnabled(cb.isChecked())
            cb.toggled.connect(lambda on, p=p, mx=mx: self._motor(p, on, mx.value))
            mx.committed.connect(lambda v, p=p: self.edit(lambda: p["motor"].__setitem__("max", v)) if p.get("motor") else None)
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(cb)
            hl.addWidget(mx)
            hl.addWidget(QLabel("max " + unit_t))
            self.pform.addRow("", row)

    def _parent_candidates(self, p):
        if p["kind"] == "mass":
            return [q for q in self.sk["parts"] if q["kind"] == "link"]
        below = {p["id"]}
        grew = True
        while grew:
            grew = False
            for q in self.sk["parts"]:
                if q.get("parent") in below and q["id"] not in below:
                    below.add(q["id"])
                    grew = True
        return [q for q in self.sk["parts"] if q["kind"] in ("wheel", "cart", "pivot", "link") and q["id"] not in below]

    def _rename(self, p, text):
        text = text.strip()
        if text and text != (p.get("name") or p["id"]):
            self.edit(lambda: p.__setitem__("name", text), True)

    def _motor(self, p, on, maxv):
        if self.loading:
            return
        moved = [q.get("name") or q["id"] for q in self.sk["parts"] if q.get("motor") and q is not p] if on else []

        def do():
            if on:
                for q in self.sk["parts"]:
                    q["motor"] = None
                p["motor"] = dict(max=float(maxv) if maxv > 0 else 1.0)
            else:
                p["motor"] = None
        self.edit(do, True)
        if moved:
            self.status.setText("There can be one motor, so the motor on %s was switched off." % ", ".join(moved))

    # ============================================================================================================== the palette
    def add(self, kind):
        sk = self.sk
        parent = None
        sel = dyn.part(sk, self.sel) if self.sel else None
        if kind == "link":
            if sel is not None and sel["kind"] in ("wheel", "cart", "pivot", "link"):
                parent = sel["id"]
            elif sel is not None and sel["kind"] == "mass":
                parent = sel.get("parent")
            if parent is None:
                links = [p for p in sk["parts"] if p["kind"] == "link"]
                parent = links[-1]["id"] if links else next((p["id"] for p in sk["parts"] if p["kind"] in dyn.ROOTS), None)
        elif kind == "mass":
            if sel is not None and sel["kind"] == "link":
                parent = sel["id"]
            elif sel is not None and sel["kind"] == "mass":
                parent = sel.get("parent")
            if parent is None:
                links = [p for p in sk["parts"] if p["kind"] == "link"]
                parent = links[-1]["id"] if links else None
            if parent is None:
                self.status.setText("Add a link first, then press Mass to put a mass on it.")
                return

        def do():
            self.sel = dyn.add_part(sk, kind, parent)
        self.edit(do, True)

    def delete(self):
        if self.sel is None:
            return
        nxt = self.sel

        def do():
            gone = dyn.remove_part(self.sk, nxt)
            self.sel = next((p["id"] for p in self.sk["parts"] if p["id"] not in gone), None)
        self.edit(do, True)

    def load_example(self, i):
        if i <= 0 or self.busy:
            return
        self.ex.setCurrentIndex(0)
        self.load_sketch(dyn.SHOWN_EXAMPLES[i - 1][1]())

    def load_sketch(self, sk):
        """Replace the drawing (one undo step)."""
        if self.busy:
            return
        self.push_undo()
        self.sk = dyn.normalize(sk)
        self.sel = self.sk["parts"][0]["id"] if self.sk["parts"] else None
        self.result = None
        self.pause()
        self.status.setText("")
        self.refresh_all()
        self.changed()

    # ============================================================================================================== running
    def set_busy(self, busy):
        for wdg in self.groups:
            wdg.setEnabled(not busy)
        self.run_btn.setText("Stop" if self.running else "Run")
        self.update_learn_buttons()
        self.refresh_notes()

    def _progress(self, f):
        self.run_btn.setText("Stop (%d %%)" % int(100 * f))
        QApplication.processEvents()

    def run(self):
        if self.learning:
            return
        if self.running:
            self.stop_flag = True
            return
        errs, _ = dyn.check(self.sk)
        if errs:
            self.status.setText("Fix the drawing first; the notes below say what is missing.")
            self.refresh_notes()
            return
        self.pause()
        self.running, self.stop_flag = True, False
        self.set_busy(True)
        try:
            res = dyn.simulate(self.sk, progress=self._progress, stop=lambda: self.stop_flag)
        except dyn.SketchError as e:
            self.status.setText(str(e))
            return
        finally:
            self.running = False
            self.set_busy(False)
            self.refresh_controller()
        self.status.setText("")
        self.set_result(res)

    def plant_note(self):
        try:
            tf = dyn.plant_tf(self.sk)
        except Exception:                                   # noqa: BLE001 - the note is a courtesy; the run itself is already done
            return ""
        up = [v.real for v in tf["poles"] if v.real > 1e-6]
        if up:
            v = max(up)
            return "Without control this design is unstable: it has a pole at +%.3g rad/s, so a small lean doubles in about %.2g s." % (v, math.log(2) / v)
        return "Without control this design is stable: every pole of the plant is in the left half-plane."

    def set_result(self, res):
        self.result = res
        self.plots.set_result(res)
        self.summary.setText(res.summary() + "\n" + self.plant_note())
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(res.n - 1, 0))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.set_player(True)
        self.t_play = 0.0
        self.show_frame(0)
        if res.n > 1:
            self.play()

    # ============================================================================================================== playback
    def set_player(self, on):
        for wdg in (self.play_btn, self.slider, self.speed):
            wdg.setEnabled(on)
        if not on:
            self.tlabel.setText("")

    def speed_value(self):
        return float(self.speed.currentData() or 1.0)

    def play(self):
        if self.result is None:
            return
        if self.t_play >= self.result.t[-1] - 1e-9:
            self.t_play = 0.0
        self.timer.start()
        self.play_btn.setText("Pause")

    def pause(self):
        self.timer.stop()
        self.play_btn.setText("Play")

    def toggle_play(self):
        if self.timer.isActive():
            self.pause()
        else:
            self.play()

    def tick(self):
        r = self.result
        if r is None:
            self.timer.stop()
            return
        self.t_play += self.timer.interval() / 1000.0 * self.speed_value()
        if self.t_play >= r.t[-1]:
            self.t_play = float(r.t[-1])
            self.pause()
        self.goto_time(self.t_play)

    def goto_time(self, t):
        r = self.result
        if r is None:
            return
        self.show_frame(min(int(np.searchsorted(r.t, t - 1e-12)), r.n - 1))

    def show_frame(self, i):
        r = self.result
        if r is None or r.n == 0:
            return
        i = max(0, min(i, r.n - 1))
        self.frame_i = i
        mdl = r.mdl
        use_pos = mdl.has_pos and bool(r.sk["controller"]["pos_on"])
        note = ""
        if i == r.n - 1 and not r.ok:
            note = "Fell over" if r.reason == "tilt" else "Hit the ground"
        self.view.show_frame(mdl, r.z[i], float(r.goal[i]) if use_pos else None, note)
        self.plots.set_time(float(r.t[i]))
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self.tlabel.setText("%.2f s / %.1f s" % (r.t[i], r.t[-1]))

    def _slid(self, i):
        self.pause()
        if self.result is not None:
            self.t_play = float(self.result.t[min(i, self.result.n - 1)])
            self.show_frame(i)

    def scrub(self, t):
        self.pause()
        self.t_play = t
        self.goto_time(t)

    # ============================================================================================================== gains and G(s)
    def suggest(self):
        try:
            g = dyn.suggest_gains(self.sk)
        except dyn.SketchError as e:
            self.status.setText(str(e))
            return
        except Exception:                                   # noqa: BLE001
            self.status.setText("Could not work out gains for this drawing; set them by hand.")
            return
        self.edit(lambda: dyn.apply_gains(self.sk, g))
        self.status.setText("Gains filled in from a linear-quadratic design on the linearised model. Press Run to try them; change a gain and run again.")

    def send_tf(self):
        errs, _ = dyn.check(self.sk)
        if errs:
            self.status.setText("Fix the drawing first; the notes below say what is missing.")
            return
        tfs = self.tab.section("transfer_function") if self.tab is not None else None
        if tfs is None:
            self.status.setText("The Transfer function section is not available in this tab.")
            return
        try:
            tf = dyn.plant_tf(self.sk)
        except Exception:                                   # noqa: BLE001
            self.status.setText("Could not linearise this drawing.")
            return
        tfs.num.setText("[" + " ".join(core.fmt(x, 12) for x in tf["num"]) + "]")
        tfs.den.setText("[" + " ".join(core.fmt(x, 12) for x in tf["den"]) + "]")
        self.tab.show_section("transfer_function")

    # ============================================================================================================== file
    def to_json(self):
        return {"sketch": copy.deepcopy(self.sk), "learn": self.learn_prefs()}

    def from_json(self, d):
        sk = (d or {}).get("sketch")
        self._abandon()
        self.learning = self.stopping = False
        self.poll_timer.stop()
        self.rtimer.stop()
        self.worker, self.rp, self.rq = None, None, []
        self.sk = dyn.normalize(sk) if sk and sk.get("parts") else dyn.example_robot()
        self.sel = self.sk["parts"][0]["id"] if self.sk["parts"] else None
        self.undo = []
        self.result = None
        self.pause()
        self.status.setText("")
        self.loading = True
        try:
            self.set_learn_prefs((d or {}).get("learn"))
        finally:
            self.loading = False
        self.drop_learner()
        self.refresh_all()


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
