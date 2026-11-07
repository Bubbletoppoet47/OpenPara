"""
motor_tab.py - the Motor Control tab: connect to an ODESC / ODrive-style board, set it up, calibrate it, run it and look at what its
position sensor (Hall sensors or an encoder) can do.  Everything works on a simulated board too ("Demo board").

Safety: the STOP button (and Esc) always drops the board to idle; any error stops a test; a test needs a calibrated motor and sensor, no
standing errors and has a time limit; settings are not written while the motor is running.  Nothing here has been verified on real hardware
yet - use a low current limit, a free-spinning motor and keep a hand on the power switch.
"""
import csv
import json
import os
from collections import deque

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget)

import motor_analysis as A
import motor_link as ML
import motor_model as M
from motor_ui import LivePlot, Section, big_button, note_label, stop_button, verdict_html

FORMAT = "openpara-motor"
MARKER = "motor.json"
CAL_STATES = (M.MOTOR_CAL, M.ENC_OFFSET_CAL, M.HALL_POLARITY, M.HALL_PHASE, 2, 6, 7, 9, 10, 11)
TICK = 0.05
MAX_TEST_S = 60.0


class MotorTab(QWidget):
    def __init__(self, host=None, path=None):
        super().__init__()
        self.host = host
        self.path = None
        self.link = None
        self.dirty = False
        self.rig = "A"
        self.fields = {}          # path -> widget
        self.job = None           # the running test {kind, t_end, ...}
        self.hist = deque(maxlen=6000)
        self.last_rec = []
        self.cal_pending = False
        self.hcheck = None
        self.poll_n = 0
        self.errors_now = []
        self.wall = None
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.tick(None))
        self.timer.start(int(TICK * 1000))
        QShortcut(QKeySequence("Esc"), self, activated=self.stop).setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        if path:
            self.open_folder(path)
        self.refresh_ports()
        self.update_state_ui()

    # ============================================================================ tab protocol
    def title(self):
        return (os.path.basename(self.path.rstrip("/\\")) if self.path else "Motor Control") + (" *" if self.dirty else "")

    def is_dirty(self):
        return self.dirty

    def can_close(self):
        if self.dirty:
            r = QMessageBox.question(self, "Motor Control", "Save the changes to this motor project first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Save and not self.save():
                return False
        return True

    def shutdown(self):
        self.timer.stop()
        self.disconnect_board()

    # ============================================================================ layout
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)
        # ---- left panel
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.rig_box = QComboBox()
        self.rig_box.addItem("A:  ODESC only  (its own Hall sensors or encoder)", "A")
        self.rig_box.addItem("B:  ESP32 + ODESC  (+ IMU, + encoder)  - coming", "B")
        self.rig_box.currentIndexChanged.connect(self.on_rig)
        top.addWidget(self.rig_box, 1)
        self.stop_btn = stop_button("STOP  (Esc)")
        self.stop_btn.clicked.connect(self.stop)
        top.addWidget(self.stop_btn)
        ll.addLayout(top)
        self.err_lbl = QLabel("")
        self.err_lbl.setWordWrap(True)
        self.err_lbl.setTextFormat(Qt.TextFormat.RichText)
        ll.addWidget(self.err_lbl)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        self.sec_lay = QVBoxLayout(inner)
        sc.setWidget(inner)
        ll.addWidget(sc, 1)
        self.status = QLabel("Not connected.")
        self.status.setWordWrap(True)
        ll.addWidget(self.status)
        self._connect_section()
        self._setup_section()
        self._calibrate_section()
        self._run_section()
        self._sensor_section()
        self._backup_section()
        self._later_sections()
        self.sec_lay.addStretch(1)
        split.addWidget(left)
        # ---- right: live plots
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        self.p_vel = LivePlot("Speed", "turn/s")
        self.p_pos = LivePlot("Position", "turns")
        self.p_cur = LivePlot("Motor current", "A")
        self.p_bus = LivePlot("Supply voltage", "V")
        for p in (self.p_vel, self.p_pos, self.p_cur, self.p_bus):
            rl.addWidget(p, 1)
        self.live_lbl = QLabel("")
        rl.addWidget(self.live_lbl)
        split.addWidget(right)
        split.setSizes([430, 700])
        split.setStretchFactor(1, 1)

    def _connect_section(self):
        s = Section("Connect", True, 1, summary=lambda: self.info_lbl.text())
        self.port_box = QComboBox()
        s.form.addRow("Port", self.port_box)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh ports")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.conn_btn = big_button("Connect")
        self.conn_btn.clicked.connect(self.toggle_connect)
        row.addWidget(self.refresh_btn)
        s.form.addRow(row)
        s.add(self.conn_btn)
        self.demo_btn = QPushButton("Use the demo board (simulated - for trying things out)")
        self.demo_btn.clicked.connect(self.connect_demo)
        s.add(self.demo_btn)
        self.info_lbl = QLabel("Not connected")
        self.info_lbl.setWordWrap(True)
        s.add(self.info_lbl)
        s.add(note_label("Plug in the board's USB cable (the 24 V supply must be on too). The board talks over a virtual serial port; no driver is needed on most computers."))
        self.sec_lay.addWidget(s)
        self.sec_connect = s

    def _setup_section(self):
        s = Section("Motor and sensor setup", True, 2, summary=lambda: "settings of the motor, the sensor, the control loops")
        for title, fields in (("Motor", M.MOTOR_FIELDS), ("Position sensor", M.SENSOR_FIELDS), ("Control loops", M.CONTROL_FIELDS), ("Board", M.BOARD_FIELDS)):
            h = QLabel(f"<b>{title}</b>")
            s.add(h)
            for f in fields:
                w = self._make_field(f)
                lab = QLabel(f.label + (f"  ({f.unit})" if f.unit else ""))
                lab.setToolTip(f.tip)
                w.setToolTip(f.tip)
                s.form.addRow(lab, w)
                self.fields[f.path] = w
        self.hall_btn = QPushButton("Counts per turn = 6 x pole pairs  (for Hall sensors)")
        self.hall_btn.clicked.connect(self.set_hall_cpr)
        s.add(self.hall_btn)
        self.check_lbl = QLabel("")
        self.check_lbl.setWordWrap(True)
        self.check_lbl.setTextFormat(Qt.TextFormat.RichText)
        s.add(self.check_lbl)
        row = QHBoxLayout()
        self.read_btn = QPushButton("Read from board")
        self.read_btn.clicked.connect(self.read_settings)
        self.write_btn = QPushButton("Write to board")
        self.write_btn.clicked.connect(self.write_settings)
        row.addWidget(self.read_btn)
        row.addWidget(self.write_btn)
        s.form.addRow(row)
        s.add(note_label("'Write to board' puts these values on the board for now. 'Save to the board' (section 6) keeps them after power-off."))
        self.sec_lay.addWidget(s)
        self.sec_setup = s

    def _make_field(self, f):
        if f.kind == "enum":
            w = QComboBox()
            for k, v in f.enum.items():
                w.addItem(v, k)
            w.currentIndexChanged.connect(self.on_field)
        elif f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.lo if f.lo is not None else 0), int(f.hi if f.hi is not None else 1000000))
            w.valueChanged.connect(self.on_field)
        elif f.kind == "bool":
            w = QCheckBox()
            w.toggled.connect(self.on_field)
        else:
            w = QDoubleSpinBox()
            w.setDecimals(f.decimals)
            w.setRange(f.lo if f.lo is not None else -1e6, f.hi if f.hi is not None else 1e6)
            w.setSingleStep(10 ** -max(f.decimals - 2, 0))
            w.valueChanged.connect(self.on_field)
        return w

    def _calibrate_section(self):
        s = Section("Calibrate", True, 3, summary=lambda: self.cal_lbl.text()[:90])
        s.add(note_label("Measures the motor's resistance and inductance and teaches the board where the sensor's positions are. The motor will move and beep. "
                         "Let it turn freely, with nothing attached that could be hurt."))
        self.cal_btn = big_button("Calibrate motor and sensor")
        self.cal_btn.clicked.connect(self.calibrate)
        s.add(self.cal_btn)
        self.cal_lbl = QLabel("Not calibrated yet.")
        self.cal_lbl.setWordWrap(True)
        self.cal_lbl.setTextFormat(Qt.TextFormat.RichText)
        s.add(self.cal_lbl)
        self.sec_lay.addWidget(s)
        self.sec_cal = s

    def _run_section(self):
        s = Section("Run the motor", True, 4, summary=lambda: "")
        self.run_mode = QComboBox()
        self.run_mode.addItem("Speed (turn/s)", "speed")
        self.run_mode.addItem("Move to a position (turns from here)", "pos")
        s.form.addRow("What", self.run_mode)
        self.run_val = QDoubleSpinBox()
        self.run_val.setRange(-1000, 1000)
        self.run_val.setDecimals(3)
        self.run_val.setValue(2.0)
        s.form.addRow("Target", self.run_val)
        self.run_dur = QDoubleSpinBox()
        self.run_dur.setRange(0.5, MAX_TEST_S)
        self.run_dur.setValue(5.0)
        self.run_dur.setSuffix(" s")
        s.form.addRow("Stops by itself after", self.run_dur)
        self.run_btn = big_button("Start")
        self.run_btn.clicked.connect(lambda: self.start_run("run"))
        s.add(self.run_btn)
        s.add(note_label("The test refuses to start if the motor or sensor is not calibrated or if the board shows an error. It stops by itself on any error, "
                         "and the current limit in section 2 always applies."))
        self.sec_lay.addWidget(s)
        self.sec_run = s

    def _sensor_section(self):
        s = Section("What can the sensor do?", True, 5, summary=lambda: "")
        self.hall_info = QLabel("")
        self.hall_info.setWordWrap(True)
        s.add(self.hall_info)
        self.hc_btn = QPushButton("Check the Hall wiring (turn the motor by hand)")
        self.hc_btn.clicked.connect(self.toggle_hall_check)
        s.add(self.hc_btn)
        self.hc_lbl = QLabel("")
        self.hc_lbl.setWordWrap(True)
        self.hc_lbl.setTextFormat(Qt.TextFormat.RichText)
        s.add(self.hc_lbl)
        self.an_btn = big_button("Analyze the sensor at the target speed")
        self.an_btn.clicked.connect(lambda: self.start_run("analyze"))
        s.add(self.an_btn)
        self.an_lbl = QLabel("")
        self.an_lbl.setWordWrap(True)
        self.an_lbl.setTextFormat(Qt.TextFormat.RichText)
        s.add(self.an_lbl)
        self.csv_btn = QPushButton("Save the last recording (CSV)...")
        self.csv_btn.clicked.connect(self.save_csv)
        s.add(self.csv_btn)
        s.add(note_label("Runs the motor at the speed set in section 4 and measures how steady the speed reading is, and how often the sensor gives a new step. "
                         "It cannot see the true position, only what the board believes."))
        self.sec_lay.addWidget(s)
        self.sec_sensor = s

    def _backup_section(self):
        s = Section("Settings: save and restore", False, 6, summary=lambda: "file backup, save to the board, factory reset")
        for text, fn in (("Save settings to a file...", self.save_settings_file), ("Load settings from a file...", self.load_settings_file),
                         ("Save to the board (keeps them after power-off)", self.save_to_board), ("Factory reset the board...", self.erase_board)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            s.add(b)
            setattr(self, "bk_" + fn.__name__, b)
        self.clear_btn = QPushButton("Clear errors")
        self.clear_btn.clicked.connect(self.clear_errors)
        s.add(self.clear_btn)
        self.sec_lay.addWidget(s)

    def _later_sections(self):
        self.later = []
        for n, title, text in ((7, "Tune the loops (step tests)", "Coming next: step-response tests with suggested gains."),
                               (8, "ESP32 link (IMU tilt, encoder angle)", "Coming: connect the ESP32 that reads the IMU and an encoder and sends them over serial. Needs the rig 'B' above."),
                               (9, "Balance simulator", "Coming: a two-wheel robot and a unicycle you can tune live before touching real hardware.")):
            s = Section(title, False, n)
            s.add(note_label(text))
            s.setEnabled(False)
            self.sec_lay.addWidget(s)
            self.later.append(s)

    # ============================================================================ rig and fields
    def on_rig(self):
        self.rig = self.rig_box.currentData()
        if self.rig == "B":
            self.say("Rig B (ESP32 + ODESC) is not built yet: only the ODESC side works for now, which is what rig A uses.")
        self.dirty = True
        self.refresh_title()

    def on_field(self, *a):
        if getattr(self, "_loading", False):
            return
        self.dirty = True
        self.refresh_title()
        self.show_checks()

    def field_value(self, f):
        w = self.fields[f.path]
        if f.kind == "enum":
            return w.currentData()
        if f.kind == "bool":
            return 1 if w.isChecked() else 0
        return w.value()

    def set_field(self, f, v):
        w = self.fields[f.path]
        self._loading = True
        try:
            if f.kind == "enum":
                i = w.findData(int(v))
                if i < 0:
                    w.addItem(f"Unknown ({int(v)})", int(v))
                    i = w.count() - 1
                w.setCurrentIndex(i)
            elif f.kind == "bool":
                w.setChecked(bool(v))
            elif f.kind == "int":
                w.setValue(int(v))
            else:
                w.setValue(float(v))
        finally:
            self._loading = False

    def values(self):
        return {f.path: self.field_value(f) for f in M.ALL_FIELDS}

    def show_checks(self):
        v = self.values()
        items = A.check_settings(v)
        if v.get(M.a("encoder.config.mode")) == M.HALL_MODE:
            self.hall_info.setText(A.hall_summary(v[M.a("motor.config.pole_pairs")]) + f" Speeds below about "
                                   f"{A.lowest_usable_speed(v[M.a('motor.config.pole_pairs')]):.1f} turn/s get rough.")
        else:
            cpr = v.get(M.a("encoder.config.cpr")) or 1
            self.hall_info.setText(f"This sensor gives {int(cpr)} counts per turn ({360.0 / max(1, int(cpr)):.3f} degrees each).")
        self.check_lbl.setText(verdict_html(items))

    def set_hall_cpr(self):
        f = [x for x in M.SENSOR_FIELDS if x.path.endswith("cpr")][0]
        self.set_field(f, 6 * int(self.field_value([x for x in M.MOTOR_FIELDS if x.path.endswith("pole_pairs")][0])))
        self.dirty = True
        self.show_checks()

    # ============================================================================ say / errors
    def say(self, text):
        self.status.setText(text)

    def refresh_title(self):
        if self.host is not None:
            try:
                self.host.refresh_titles()
            except Exception:
                pass

    # ============================================================================ connection
    def refresh_ports(self):
        self.port_box.clear()
        for dev, desc in ML.list_ports():
            self.port_box.addItem(f"{dev}  -  {desc}", dev)
        if self.port_box.count() == 0:
            self.port_box.addItem("(no serial ports found)", "")

    def connected(self):
        return self.link is not None

    def toggle_connect(self):
        if self.connected():
            self.disconnect_board()
            return
        dev = self.port_box.currentData()
        if not dev:
            self.say("No serial port found. Plug the board in with a data USB cable and press 'Refresh ports'.")
            return
        try:
            self.attach(ML.SerialLink(dev))
        except ML.LinkError as e:
            self.say(str(e))

    def connect_demo(self):
        if self.connected():
            self.disconnect_board()
        self.attach(ML.SimLink())

    def attach(self, link):
        self.link = link
        info = link.info()
        if info.get("fw_version_major") is None:
            self.link = None
            link.close()
            self.say("The port opened, but the board did not answer. Check that it is powered, that it is the right port, and that nothing else (odrivetool) is using it.")
            return
        hw = f"hardware {info.get('hw_version_major')}.{info.get('hw_version_minor')}" if info.get("hw_version_major") is not None else ""
        self.info_lbl.setText(("DEMO BOARD (simulated)  " if link.sim else "Connected  ") + f"{M.fw_label(info)}  {hw}")
        self.hist.clear()
        self.read_settings()
        self.say("Connected." + (" This is a simulated board: nothing is moving for real." if link.sim else ""))
        self.update_state_ui()
        self.sec_connect.toggle(self.sec_connect.head.isChecked())

    def disconnect_board(self):
        if self.link is not None:
            try:
                self.stop(quiet=True)
                self.link.close()
            except Exception:
                pass
        self.link = None
        self.job = None
        self.info_lbl.setText("Not connected")
        self.update_state_ui()

    def lost(self, e):
        self.say(f"Lost the board: {e}")
        self.disconnect_board()

    def update_state_ui(self):
        c = self.connected()
        self.conn_btn.setText("Disconnect" if c else "Connect")
        for b in (self.read_btn, self.write_btn, self.cal_btn, self.run_btn, self.an_btn, self.clear_btn, self.hc_btn):
            b.setEnabled(c)
        self.demo_btn.setEnabled(not c)
        self.stop_btn.setEnabled(c)
        self.show_checks()

    # ============================================================================ settings <-> board
    def read_settings(self):
        if not self.connected():
            return
        n = 0
        try:
            for f in M.ALL_FIELDS:
                v = self.link.get(f.path)
                w = self.fields[f.path]
                w.setEnabled(v is not None)
                if v is None:
                    w.setToolTip(f.tip + "\n(This setting is not on this board's firmware.)")
                    continue
                self.set_field(f, v)
                n += 1
        except ML.LinkError as e:
            self.lost(e)
            return
        self.dirty = False
        self.show_checks()
        self.say(f"Read {n} settings from the board.")

    def idle(self):
        return self.link.get(M.LIVE["state"]) in (M.IDLE, 0, None)

    def write_settings(self):
        if not self.connected():
            return
        if not self.idle():
            self.say("Not written: the motor is running or calibrating. Press STOP first.")
            return
        bad = [t for l, t in A.check_settings(self.values()) if l == "bad"]
        if bad:
            self.say("Not written: " + " ".join(bad))
            return
        n = 0
        try:
            for f in M.ALL_FIELDS:
                if self.fields[f.path].isEnabled():
                    self.link.set(f.path, self.field_value(f))
                    n += 1
        except ML.LinkError as e:
            self.lost(e)
            return
        self.say(f"Wrote {n} settings to the board. Changing the motor or sensor settings means calibrating again (section 3).")
        self.cal_lbl.setText("Settings changed: calibrate again.")

    def save_to_board(self):
        if self.connected() and self.idle():
            self.link.save()
            self.say("Saved to the board. The board may reboot; reconnect if the port disappears.")
        elif self.connected():
            self.say("Not saved: press STOP first.")

    def erase_board(self):
        if not self.connected():
            return
        if QMessageBox.question(self, "Factory reset", "Erase ALL settings and calibration on the board and reboot it?\nYou will have to set up and calibrate again.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.link.erase()
        self.link.reboot()
        self.read_settings()
        self.say("The board was reset to factory settings.")

    def save_settings_file(self):
        if not self.connected():
            self.say("Connect first: the file holds what is on the board.")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save the board's settings", "board_settings.json", "Settings (*.json)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(A.backup_text(self.link, {"firmware": self.info_lbl.text()}))
            self.say(f"Saved {p}")

    def load_settings_file(self):
        if not self.connected():
            self.say("Connect first.")
            return
        p, _ = QFileDialog.getOpenFileName(self, "Load settings", "", "Settings (*.json)")
        if p:
            self.apply_settings_text(open(p, encoding="utf-8").read())

    def apply_settings_text(self, text):
        if not self.idle():
            self.say("Not loaded: press STOP first.")
            return 0
        try:
            n = A.restore(text, self.link)
        except ValueError as e:
            self.say(str(e))
            return 0
        self.read_settings()
        self.say(f"Restored {n} settings that differed. Calibrate again if the motor or sensor settings changed.")
        return n

    def clear_errors(self):
        if self.connected():
            if hasattr(self.link, "clear_errors"):
                self.link.clear_errors()
            else:
                for p in (M.LIVE["err"], M.LIVE["merr"], M.LIVE["eerr"], M.LIVE["cerr"]):
                    self.link.set(p, 0)
            self.errors_now = []
            self.err_lbl.setText("")

    # ============================================================================ calibrate and run
    def refuse(self, text):
        self.say("Not started: " + text)
        return False

    def read_errors(self):
        return M.error_report(*[self.link.get(M.LIVE[k]) for k in ("err", "merr", "eerr", "cerr")])

    def calibrate(self):
        if not self.connected():
            return
        if not self.idle():
            return self.refuse("the board is busy. Press STOP first.")
        errs = self.read_errors()
        if errs:
            return self.refuse("the board shows errors (see above). Fix the cause, then press 'Clear errors'.")
        bad = [t for l, t in A.check_settings(self.values()) if l == "bad"]
        if bad:
            return self.refuse(" ".join(bad))
        if self.fields_mode_is_hall():
            h = self.link.get(M.LIVE["hall"])
            if h is not None and int(h) not in M.HALL_LEGAL:
                return self.refuse(f"the Hall sensors show the illegal state {int(h)}: no sensor signal. Use 'Check the Hall wiring' in section 5.")
        self.write_settings()
        self.cal_pending = True
        self.link.set(M.a("requested_state"), M.FULL_CAL)
        self.say("Calibrating... the motor will make noise and may turn a little.")
        return True

    def finish_cal(self):
        self.cal_pending = False
        errs = self.read_errors()
        if errs:
            self.cal_lbl.setText(verdict_html([("bad", e) for e in errs]) + "<br>Calibration failed.")
            return
        res = {k: self.link.get(v) for k, v in M.CAL_RESULT.items()}
        items = M.check_calibration(res)
        if res.get("enc_ready"):
            items.append(("ok", "The position sensor is calibrated."))
        else:
            items.append(("bad", "The position sensor is not ready."))
        self.cal_lbl.setText(verdict_html(items))
        self.say("Calibration finished.")

    def start_run(self, kind):
        if not self.connected():
            return False
        if self.hcheck is not None:
            self.finish_hall_check()
        if not self.idle():
            return self.refuse("the board is not idle.")
        errs = self.read_errors()
        if errs:
            return self.refuse("the board shows errors: " + "; ".join(errs))
        if not self.link.get(M.CAL_RESULT["motor_ok"]):
            return self.refuse("the motor is not calibrated (section 3).")
        if not self.link.get(M.CAL_RESULT["enc_ready"]):
            return self.refuse("the sensor is not calibrated (section 3).")
        lim = self.link.get(M.a("motor.config.current_lim")) or 0
        if lim <= 0:
            return self.refuse("the current limit is zero.")
        mode = "speed" if kind == "analyze" else self.run_mode.currentData()
        target = self.run_val.value()
        vlim = self.link.get(M.a("controller.config.vel_limit")) or 0
        if mode == "speed" and abs(target) > vlim:
            return self.refuse(f"the target speed {target:g} turn/s is above the board's speed limit {vlim:g} turn/s.")
        dur = min(self.run_dur.value(), MAX_TEST_S)
        if kind == "analyze":
            dur = max(dur, 3.0)
        link = self.link
        if mode == "speed":
            link.set(M.a("controller.config.control_mode"), 2)
            link.set(M.a("controller.config.input_mode"), 1)
            link.set(M.a("controller.input_vel"), 0.0)
        else:
            link.set(M.a("controller.config.control_mode"), 3)
            link.set(M.a("controller.config.input_mode"), 1)
        link.set(M.a("requested_state"), M.CLOSED_LOOP)
        link.advance(0.01) if link.sim else None
        if self.link.get(M.LIVE["state"]) != M.CLOSED_LOOP:
            return self.refuse("the board would not enter closed-loop control: " + ("; ".join(self.read_errors()) or "unknown reason"))
        t0 = link.now()
        if mode == "speed":
            link.set(M.a("controller.input_vel"), target)
        else:
            link.set(M.a("controller.input_pos"), (link.get(M.LIVE["pos"]) or 0.0) + target)
        self.job = {"kind": kind, "mode": mode, "t0": t0, "t_end": t0 + dur, "target": target, "rec": []}
        self.run_btn.setText("Running...")
        self.say(f"Running: {'speed' if mode == 'speed' else 'move'} {target:g} for {dur:g} s. STOP (or Esc) ends it at once.")
        return True

    HALL_CHECK_S = 30.0

    def toggle_hall_check(self):
        if not self.connected():
            return
        if self.hcheck is not None:
            self.finish_hall_check()
            return
        if not self.idle():
            self.say("Not started: the board is busy. Press STOP first.")
            return
        self.hcheck = {"states": [], "t_end": self.link.now() + self.HALL_CHECK_S}
        self.hc_btn.setText("Stop checking (turn the shaft slowly by hand now)")
        self.hc_lbl.setText("Turn the motor shaft slowly by hand, a full turn or more. The six states should all show up.")
        self.say("Hall wiring check: the motor is NOT powered. Turn the shaft by hand.")

    def finish_hall_check(self):
        hc, self.hcheck = self.hcheck, None
        self.hc_btn.setText("Check the Hall wiring (turn the motor by hand)")
        if hc is None:
            return
        ok, items = A.hall_wiring(hc["states"])
        self.hc_ok = ok
        self.hc_lbl.setText(verdict_html(items))
        self.say("Hall wiring check finished.")

    def stop(self, quiet=False):
        if self.link is None:
            return
        try:
            self.link.set(M.a("controller.input_vel"), 0.0)
            self.link.set(M.a("requested_state"), M.IDLE)
            if self.link.sim:
                self.link.advance(0.002)
        except ML.LinkError as e:
            self.lost(e)
            return
        was = self.job is not None or self.cal_pending
        self.job = None
        self.cal_pending = False
        self.run_btn.setText("Start")
        if was and not quiet:
            self.say("Stopped. The motor is free (idle).")

    def finish_job(self, reason="done"):
        job, self.job = self.job, None
        try:
            self.link.set(M.a("controller.input_vel"), 0.0)
            self.link.set(M.a("requested_state"), M.IDLE)
        except ML.LinkError as e:
            self.lost(e)
            return
        self.run_btn.setText("Start")
        self.last_rec = job["rec"]
        if reason != "done":
            self.say(f"Test ended: {reason}")
        else:
            self.say("Test finished. The motor is free (idle).")
        if job["kind"] == "analyze":
            self.show_analysis(job)

    def show_analysis(self, job):
        rec = [r for r in job["rec"] if r[0] - job["t0"] >= 1.0]       # skip the spin-up
        if len(rec) < 16:
            self.an_lbl.setText(verdict_html([("warn", "Not enough steady data: run for longer.")]))
            return
        ts, vs = [r[0] for r in rec], [r[2] for r in rec]
        pp = int(self.field_value([x for x in M.MOTOR_FIELDS if x.path.endswith("pole_pairs")][0]))
        if int(self.field_value([x for x in M.SENSOR_FIELDS if x.path.endswith("mode")][0])) == M.HALL_MODE:
            items = A.hall_verdict(pp, job["target"], ts, vs)
        else:
            m, s, pct = A.ripple(vs)
            items = [("ok" if pct < 3 else "warn", f"Speed ripple at {m:.2f} turn/s: {pct:.1f}% (std {s:.3f} turn/s).")]
        self.an_lbl.setText(verdict_html(items))
        self.analysis = items

    def save_csv(self):
        if not self.last_rec:
            self.say("No recording yet: run a test first.")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save recording", "recording.csv", "CSV (*.csv)")
        if p:
            self.write_csv(p)

    def write_csv(self, p):
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "position_turns", "speed_turn_s", "current_A", "supply_V"])
            w.writerows(self.last_rec)
        self.say(f"Saved {p}")

    # ============================================================================ the heartbeat
    def tick(self, dt=None):
        """One poll of the board: advance the simulation (if simulated), read the live values, watch for errors and drive the running test."""
        if self.link is None:
            return
        import time as _t
        if dt is None:
            now = _t.time()
            dt = min(0.2, now - self.wall) if self.wall else TICK
            self.wall = now
        try:
            if self.link.sim:
                self.link.advance(dt)
            t = self.link.now()
            row = (t, self.link.get(M.LIVE["pos"]) or 0.0, self.link.get(M.LIVE["vel"]) or 0.0,
                   self.link.get(M.LIVE["iq"]) or 0.0, self.link.get(M.LIVE["vbus"]) or 0.0)
            state = self.link.get(M.LIVE["state"])
            hall = self.link.get(M.LIVE["hall"])
            self.poll_n += 1
            errs = self.read_errors() if (self.poll_n % 2 == 0 or self.job or self.cal_pending) else self.errors_now
        except ML.LinkError as e:
            self.lost(e)
            return
        self.hist.append(row)
        self.errors_now = errs
        self.err_lbl.setText(verdict_html([("bad", e) for e in errs]) if errs else "")
        sname = M.STATES.get(int(state or 0), f"state {state}")
        hall_txt = ""
        if hall is not None and self.fields_mode_is_hall():
            hall_txt = f"   |   Hall state {int(hall)}" + ("  (ILLEGAL: no sensor signal?)" if int(hall) not in M.HALL_LEGAL else "")
        if self.hcheck is not None:
            if hall is not None:
                self.hcheck["states"].append(int(hall))
            if len({x for x in self.hcheck["states"] if x in M.HALL_LEGAL}) == 6 or t >= self.hcheck["t_end"]:
                self.finish_hall_check()
        self.live_lbl.setText(f"{sname}   |   speed {row[2]:.3f} turn/s   position {row[1]:.3f} turns   current {row[3]:.2f} A   supply {row[4]:.1f} V" + hall_txt)
        if self.job is not None:
            self.job["rec"].append(row)
            if errs:
                self.job["rec"] and None
                self.finish_job("the board reported an error and dropped to idle.")
            elif t >= self.job["t_end"]:
                self.finish_job("done")
        if self.cal_pending and state in (M.IDLE, 0) and (t > 0.05):
            if getattr(self, "_cal_seen", False) or errs:
                self._cal_seen = False
                self.finish_cal()
            elif state in (M.IDLE, 0):
                self._cal_seen = False
        if self.cal_pending and int(state or 0) in CAL_STATES:
            self._cal_seen = True
            self.say(f"Calibrating: {sname}...")
        self.redraw()

    def fields_mode_is_hall(self):
        f = [x for x in M.SENSOR_FIELDS if x.path.endswith("config.mode")][0]
        return self.field_value(f) == M.HALL_MODE

    def redraw(self):
        h = list(self.hist)
        ts = [r[0] for r in h]
        self.p_vel.set_data(ts, [r[2] for r in h])
        self.p_pos.set_data(ts, [r[1] for r in h])
        self.p_cur.set_data(ts, [r[3] for r in h])
        self.p_bus.set_data(ts, [r[4] for r in h])

    # ============================================================================ project folder
    def to_dict(self):
        return {"format": FORMAT, "version": 1, "rig": self.rig, "settings": self.values()}

    def save(self, as_new=False):
        folder = self.path
        if as_new or not folder:
            folder, _ = QFileDialog.getSaveFileName(self, "Save Motor Control project (a folder)", "motor_project.motor", "Motor project (*.motor)")
            if not folder:
                return False
            if not folder.lower().endswith(".motor"):
                folder += ".motor"
        return self.save_to(folder)

    def save_to(self, folder):
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, MARKER), "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=1)
            if self.last_rec:
                os.makedirs(os.path.join(folder, "recordings"), exist_ok=True)
                self.write_csv(os.path.join(folder, "recordings", "last_test.csv"))
        except OSError as e:
            QMessageBox.warning(self, "Motor Control", f"Could not save: {e}")
            return False
        self.path = folder
        self.dirty = False
        self.refresh_title()
        self.say(f"Saved {folder}")
        return True

    def open_folder(self, folder):
        try:
            with open(os.path.join(folder, MARKER), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            self.say("That folder is not a Motor Control project.")
            return False
        if d.get("format") != FORMAT:
            self.say("That folder is not a Motor Control project.")
            return False
        by = {f.path: f for f in M.ALL_FIELDS}
        for p, v in d.get("settings", {}).items():
            if p in by:
                self.set_field(by[p], v)
        self.rig_box.setCurrentIndex(0 if d.get("rig", "A") == "A" else 1)
        self.path = folder
        self.dirty = False
        self.show_checks()
        return True


def make_tab(host=None, path=None):
    return MotorTab(host, path)
