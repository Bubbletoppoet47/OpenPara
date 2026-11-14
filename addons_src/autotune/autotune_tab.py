"""
autotune_tab.py - the Autotune tab: sing or speak into a microphone and hear yourself on the notes of a key and scale, live.

Playground only for now (see addons.NOT_RELEASED).  The sound engine is autotune_core.py, the sound card side autotune_audio.py; this file
is the window.  Wear headphones: with speakers the sound goes back into the microphone and howls.
"""
import json
import math
import os
import sys

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                             QScrollArea, QSizePolicy, QSlider, QSplitter, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import autotune_audio as AU  # noqa: E402
import autotune_core as A  # noqa: E402
import ui_kit  # noqa: E402

SETTINGS_FILE = "autotune.json"
EMPTY_TEXT = "Press Start, then sing or speak. The note you are on is shown here, and the correction you hear."


def settings_path():
    import paths
    return os.path.join(paths.user_dir(), SETTINGS_FILE)


def load_settings(path=None):
    try:
        with open(path or settings_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, ImportError):
        return {}


def save_settings(d, path=None):
    try:
        with open(path or settings_path(), "w", encoding="utf-8") as f:
            json.dump(d, f)
    except (OSError, ImportError):
        pass


def level_fraction(db, floor=-60.0):
    return min(1.0, max(0.0, (db - floor) / -floor))


class TunerView(QWidget):
    """What the singer sees: the note they are on, a needle that says how flat or sharp they are, the same after the correction, and
    the level going in and coming out."""

    def __init__(self):
        super().__init__()
        self.state = None
        self.running = False
        self.bypass = False
        self.in_db = self.out_db = -120.0
        self.hold_in = self.hold_out = -120.0
        self.setMinimumSize(380, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def update_view(self, state, in_db, out_db, running, bypass):
        self.state, self.running, self.bypass = state, running, bypass
        self.in_db, self.out_db = in_db, out_db
        self.hold_in = max(in_db, self.hold_in - 1.5)            # the bars fall slowly, rise at once
        self.hold_out = max(out_db, self.hold_out - 1.5)
        self.update()

    @staticmethod
    def x_of(cents, x0, x1):
        return x0 + (max(-50.0, min(50.0, cents)) + 50.0) / 100.0 * (x1 - x0)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(ui_kit.BG))
        st = self.state or {}
        voiced = bool(self.running and st.get("voiced"))
        # the note
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(int(max(36, min(h * 0.26, 120))))
        p.setFont(f)
        p.setPen(QColor(ui_kit.INK if voiced else ui_kit.FAINT))
        note = st.get("note", "") if voiced else "-"
        p.drawText(QRectF(0, h * 0.05, w, h * 0.34), Qt.AlignmentFlag.AlignCenter, note or "-")
        # the line under it
        f2 = QFont(self.font())
        f2.setPixelSize(14)
        p.setFont(f2)
        p.setPen(QColor(ui_kit.MUTED))
        if voiced:
            txt = f"You: {st['hz']:.1f} Hz     Note: {st['target_hz']:.1f} Hz"
        elif self.running:
            txt = "Listening ... sing, hum or speak"
        else:
            txt = EMPTY_TEXT
        p.drawText(QRectF(10, h * 0.40, w - 20, h * 0.10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, txt)
        # the needle
        x0, x1, y = w * 0.10, w * 0.90, h * 0.60
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ui_kit.LINE))
        p.drawRoundedRect(QRectF(x0, y - 5, x1 - x0, 10), 5, 5)
        p.setBrush(QColor(46, 125, 50, 90))
        p.drawRoundedRect(QRectF(self.x_of(-5, x0, x1), y - 5, self.x_of(5, x0, x1) - self.x_of(-5, x0, x1), 10), 4, 4)
        p.setPen(QPen(QColor(ui_kit.FAINT), 1))
        for c in (-50, -25, 0, 25, 50):
            xx = self.x_of(c, x0, x1)
            p.drawLine(int(xx), int(y + 9), int(xx), int(y + (16 if c == 0 else 13)))
        f3 = QFont(self.font())
        f3.setPixelSize(11)
        p.setFont(f3)
        p.setPen(QColor(ui_kit.MUTED))
        p.drawText(QRectF(x0 - 30, y + 18, 70, 16), Qt.AlignmentFlag.AlignLeft, "flat")
        p.drawText(QRectF(x1 - 40, y + 18, 70, 16), Qt.AlignmentFlag.AlignRight, "sharp")
        p.drawText(QRectF(x0, y + 18, x1 - x0, 16), Qt.AlignmentFlag.AlignCenter, "in tune")
        if voiced:
            c_in = st["cents"]
            c_out = c_in + (0.0 if self.bypass else st["applied"])
            # after the correction (filled), before it (ring)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ui_kit.TEAL))
            xo = self.x_of(c_out, x0, x1)
            p.drawEllipse(QRectF(xo - 8, y - 8, 16, 16))
            p.setPen(QPen(QColor(ui_kit.INK), 2))
            p.setBrush(QColor(255, 255, 255, 220))
            xi = self.x_of(c_in, x0, x1)
            p.drawEllipse(QRectF(xi - 7, y - 7, 14, 14))
            p.setPen(QColor(ui_kit.MUTED))
            p.drawText(QRectF(x0, y - 34, x1 - x0, 18), Qt.AlignmentFlag.AlignCenter,
                       f"you are {abs(c_in):.0f} cents {'sharp' if c_in > 0 else 'flat'}" if abs(c_in) >= 1 else "you are in tune")
        # legend
        p.setPen(QPen(QColor(ui_kit.INK), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        ly = h * 0.60 + 46
        p.drawEllipse(QRectF(x0, ly + 2, 10, 10))
        p.setPen(QColor(ui_kit.MUTED))
        p.drawText(QRectF(x0 + 14, ly, 100, 14), Qt.AlignmentFlag.AlignLeft, "your voice")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ui_kit.TEAL))
        p.drawEllipse(QRectF(x0 + 100, ly + 2, 10, 10))
        p.setPen(QColor(ui_kit.MUTED))
        p.drawText(QRectF(x0 + 114, ly, 180, 14), Qt.AlignmentFlag.AlignLeft, "what you hear" + (" (bypassed)" if self.bypass else ""))
        # the levels
        self._meter(p, "In", self.hold_in if self.running else -120.0, x0, h * 0.86, x1 - x0)
        self._meter(p, "Out", self.hold_out if self.running else -120.0, x0, h * 0.86 + 20, x1 - x0)
        p.end()

    def _meter(self, p, label, db, x, y, w):
        p.setPen(QColor(ui_kit.MUTED))
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QRectF(x, y - 2, 30, 14), Qt.AlignmentFlag.AlignLeft, label)
        bx, bw = x + 32, w - 32
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ui_kit.LINE))
        p.drawRoundedRect(QRectF(bx, y, bw, 9), 4, 4)
        fr = level_fraction(db)
        col = QColor(ui_kit.GOOD) if db < -12 else QColor("#e0a000") if db < -2 else QColor(ui_kit.BAD)
        p.setBrush(col)
        if fr > 0:
            p.drawRoundedRect(QRectF(bx, y, max(8.0, bw * fr), 9), 4, 4)


class AutotuneTab(QWidget):
    def __init__(self, host=None, sd=None, settings_file=None):
        super().__init__()
        self.host = host
        self.path = None
        self._sd_arg = sd                      # the tests give a pretend sound card
        self._settings_file = settings_file
        self.sd = None
        self.runner = None
        self.audio_problem = ""
        self.systems, self.in_devs, self.out_devs = [], [], []
        self._loading = True
        self.prefs = load_settings(settings_file)
        self._build()
        self.scale_changed()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.refresh_devices()
        self._loading = False
        self.update_ui()

    # ============================================================================================================ tab protocol
    def title(self):
        return "Autotune"

    def is_dirty(self):
        return False

    def can_close(self):
        return True

    def shutdown(self):
        self.timer.stop()
        self.stop()
        self.save_prefs()

    # ============================================================================================================ layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.addWidget(self._sound_section())
        lv.addWidget(self._key_section())
        lv.addWidget(self._feel_section())
        lv.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(left)
        split.addWidget(sc)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 10, 10, 6)
        top = QHBoxLayout()
        self.start_btn = ui_kit.primary(QPushButton("Start"))
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self.toggle)
        top.addWidget(self.start_btn)
        self.bypass_box = QCheckBox("Bypass (hear yourself without the correction)")
        self.bypass_box.toggled.connect(self.apply_settings)
        top.addWidget(self.bypass_box)
        top.addStretch(1)
        rv.addLayout(top)
        self.view = TunerView()
        rv.addWidget(self.view, 1)
        self.status = ui_kit.StatusLine("")
        rv.addWidget(self.status)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        ui_kit.fit_panel(split, sc, left, lo=330, hi=470)

    def _sound_section(self):
        s = ui_kit.Section("Autotune", 1, "Sound", help_text="Which microphone to listen to and where to play. Wear headphones: with speakers the "
                           "sound goes back into the microphone and howls.", summary=lambda: self.sum_sound())
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.sys_box = QComboBox()
        self.sys_box.setToolTip("How the program talks to the sound card. On Windows WASAPI has the least delay; MME works everywhere but "
                                "is slower.")
        self.in_box = QComboBox()
        self.out_box = QComboBox()
        self.chan_box = QComboBox()
        for text, v in AU.CHANNEL_CHOICES:
            self.chan_box.addItem(text, v)
        self.chan_box.setToolTip("A microphone plugged into an audio interface is often on channel 1 only.")
        self.block_box = QComboBox()
        for b in AU.BLOCKS:
            self.block_box.addItem(f"{b} samples", b)
        self.block_box.setCurrentIndex(AU.BLOCKS.index(AU.DEFAULT_BLOCK))
        self.block_box.setToolTip("The size of the pieces of sound handed over at a time. Smaller is less delay, but the sound can crackle "
                                  "if the computer cannot keep up. Raise it if it crackles.")
        self.voice_box = QComboBox()
        for name in A.VOICES:
            self.voice_box.addItem(name, A.VOICES[name])
        self.voice_box.setCurrentIndex(list(A.VOICES).index(A.DEFAULT_VOICE))
        self.voice_box.setToolTip("How low a voice to listen for. A higher voice needs a shorter stretch of sound to find its pitch, so "
                                  "there is less delay.")
        for lab, w in (("Sound system", self.sys_box), ("Microphone", self.in_box), ("Input", self.chan_box), ("Play to", self.out_box),
                       ("Buffer", self.block_box), ("Voice", self.voice_box)):
            ui_kit.tame_combo(w, 16)
            form.addRow(lab, w)
        s.body.addLayout(form)
        self.gate = QSlider(Qt.Orientation.Horizontal)
        self.gate.setRange(-70, -30)
        self.gate.setValue(-50)
        self.gate.setToolTip("Sounds quieter than this are left alone (breath, room noise, a hum). Lower it if the note stays empty "
                             "while you sing; raise it if the room's noise is taken for a voice.")
        self.gate_lbl = QLabel("")
        row = QHBoxLayout()
        row.addWidget(QLabel("Ignore sounds quieter than"))
        row.addStretch(1)
        row.addWidget(self.gate_lbl)
        s.body.addLayout(row)
        s.body.addWidget(self.gate)
        self.gate.valueChanged.connect(self.apply_settings)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Look for devices again")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        s.body.addLayout(row)
        self.problem_lbl = ui_kit.note("", ui_kit.BAD)
        self.problem_lbl.setVisible(False)
        s.body.addWidget(self.problem_lbl)
        s.body.addWidget(ui_kit.note("Wear headphones. With speakers the sound goes back into the microphone and howls."))
        self.sys_box.currentIndexChanged.connect(self.system_changed)
        for w in (self.in_box, self.out_box, self.chan_box, self.block_box, self.voice_box):
            w.currentIndexChanged.connect(self.save_prefs)
        self.sound_sec = s
        return s

    def _key_section(self):
        s = ui_kit.Section("Autotune", 2, "Key and scale", help_text="The notes the voice is pulled to. Choose a key and a scale, or click "
                           "the notes below to pick your own.", summary=lambda: self.sum_key())
        form = QFormLayout()
        self.key_box = QComboBox()
        for k in A.KEYS:
            self.key_box.addItem(k)
        self.scale_box = QComboBox()
        for name in A.SCALES:
            self.scale_box.addItem(name)
        self.scale_box.addItem(A.CUSTOM)
        form.addRow("Key", self.key_box)
        form.addRow("Scale", self.scale_box)
        s.body.addLayout(form)
        grid = QGridLayout()
        grid.setSpacing(3)
        self.note_btns = []
        for i, n in enumerate(A.NOTE_NAMES):
            b = QPushButton(n)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setMinimumWidth(26)
            b.setStyleSheet(f"QPushButton {{ padding:0 2px; border:1px solid {ui_kit.LINE}; border-radius:4px; background:white; color:{ui_kit.MUTED}; }}"
                            f"QPushButton:checked {{ background:{ui_kit.TEAL}; color:white; border-color:{ui_kit.TEAL}; font-weight:600; }}")
            b.setToolTip("Click to allow or leave out this note.")
            b.toggled.connect(lambda _on, i=i: self.note_clicked(i))
            self.note_btns.append(b)
            grid.addWidget(b, i // 6, i % 6)
        s.body.addLayout(grid)
        s.body.addWidget(ui_kit.note("The notes that are lit are the ones your voice is moved to. Click one to change it."))
        self.a4_spin = QDoubleSpinBox()
        self.a4_spin.setRange(400.0, 480.0)
        self.a4_spin.setDecimals(1)
        self.a4_spin.setSingleStep(1.0)
        self.a4_spin.setValue(440.0)
        self.a4_spin.setSuffix(" Hz")
        self.a4_spin.setToolTip("The pitch of the note A above middle C. 440 Hz is the usual.")
        f2 = QFormLayout()
        f2.addRow("A =", self.a4_spin)
        s.body.addLayout(f2)
        self.key_box.currentIndexChanged.connect(self.scale_changed)
        self.scale_box.currentIndexChanged.connect(self.scale_changed)
        self.a4_spin.valueChanged.connect(self.apply_settings)
        self.key_sec = s
        return s

    def _feel_section(self):
        s = ui_kit.Section("Autotune", 3, "How it feels", help_text="Retune speed: how fast the voice is pulled onto the note. Instant is the "
                           "hard, robotic effect. Slower keeps your own vibrato and slides. Amount: how much of the correction you hear.",
                           summary=lambda: self.sum_feel())
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, 400)
        self.speed.setValue(20)
        self.speed_lbl = QLabel("")
        self.amount = QSlider(Qt.Orientation.Horizontal)
        self.amount.setRange(0, 100)
        self.amount.setValue(100)
        self.amount_lbl = QLabel("")
        for lab, sl, val in (("Retune speed", self.speed, self.speed_lbl), ("Amount", self.amount, self.amount_lbl)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab))
            row.addStretch(1)
            row.addWidget(val)
            s.body.addLayout(row)
            s.body.addWidget(sl)
            sl.valueChanged.connect(self.apply_settings)
        s.body.addWidget(ui_kit.note("Instant = the hard, robotic effect. Around 100 to 300 ms is natural: the voice drifts to the note and "
                                     "keeps its vibrato."))
        self.feel_sec = s
        return s

    # ============================================================================================================ summaries
    def sum_sound(self):
        return f"{self.in_box.currentText()} to {self.out_box.currentText()}"

    def sum_key(self):
        return f"{self.key_box.currentText()} {self.scale_box.currentText()}" if self.scale_box.currentText() != A.CUSTOM else A.CUSTOM

    def sum_feel(self):
        return f"{self.speed_lbl.text()}, {self.amount_lbl.text()}"

    # ============================================================================================================ devices
    def sound_module(self):
        if self.sd is None:
            self.sd = self._sd_arg if self._sd_arg is not None else AU.load_sounddevice()
        return self.sd

    def refresh_devices(self):
        """Fills the sound system, microphone and output lists from the sound card; says in words when that cannot be done."""
        was_loading = self._loading
        self._loading = True
        try:
            for b in (self.sys_box, self.in_box, self.out_box):
                b.blockSignals(True)
                b.clear()
            self.audio_problem = ""
            try:
                sd = self.sound_module()
                self.systems = AU.list_systems(sd)
                if not self.systems:
                    raise AU.AudioError("No microphone and speaker or headphones were found. Plug them in, then press Look for devices again.")
            except AU.AudioError as ex:
                self.systems = []
                self.audio_problem = str(ex)
            except Exception as ex:  # noqa: BLE001 - the sound library failing in its own way
                self.systems = []
                self.audio_problem = f"The sound devices could not be listed: {ex}"
            for s in self.systems:
                self.sys_box.addItem(s["name"], s["index"])
            want = self.prefs.get("system")
            if want and self.sys_box.findText(want) >= 0:
                self.sys_box.setCurrentIndex(self.sys_box.findText(want))
            self.sys_box.blockSignals(False)
            self.fill_devices()
            self.in_box.blockSignals(False)
            self.out_box.blockSignals(False)
        finally:
            self._loading = was_loading
        self.problem_lbl.setText(self.audio_problem)
        self.problem_lbl.setVisible(bool(self.audio_problem))
        self.update_ui()

    def fill_devices(self):
        self.in_box.blockSignals(True)
        self.out_box.blockSignals(True)
        self.in_box.clear()
        self.out_box.clear()
        self.in_devs, self.out_devs = [], []
        if self.systems and self.sys_box.currentIndex() >= 0:
            host = self.sys_box.currentData()
            try:
                sd = self.sound_module()
                self.in_devs = AU.list_devices(sd, host, "input")
                self.out_devs = AU.list_devices(sd, host, "output")
            except Exception as ex:  # noqa: BLE001
                self.audio_problem = f"The sound devices could not be listed: {ex}"
        for d in self.in_devs:
            self.in_box.addItem(d["name"] + ("  (default)" if d["default"] else ""), d["index"])
        for d in self.out_devs:
            self.out_box.addItem(d["name"] + ("  (default)" if d["default"] else ""), d["index"])
        for box, key in ((self.in_box, "input"), (self.out_box, "output")):
            want = self.prefs.get(key)
            for i in range(box.count()):
                if want and box.itemText(i).replace("  (default)", "") == want:
                    box.setCurrentIndex(i)
        self.in_box.blockSignals(False)
        self.out_box.blockSignals(False)

    def system_changed(self):
        if self._loading:
            return
        self.fill_devices()
        self.save_prefs()
        self.update_ui()

    # ============================================================================================================ key and scale
    def allowed(self):
        return tuple(b.isChecked() for b in self.note_btns)

    def scale_changed(self):
        """A key or scale was chosen: the note buttons show its notes (a custom scale keeps what is lit)."""
        custom = self.scale_box.currentText() == A.CUSTOM
        self.key_box.setEnabled(not custom)
        if not custom:
            flags = A.allowed_notes(self.key_box.currentText(), self.scale_box.currentText())
            for b, v in zip(self.note_btns, flags):
                b.blockSignals(True)
                b.setChecked(v)
                b.blockSignals(False)
        self.apply_settings()

    def note_clicked(self, _i):
        """A note button was clicked: the scale becomes 'the notes I tick'."""
        if self.scale_box.currentText() != A.CUSTOM:
            self.scale_box.blockSignals(True)
            self.scale_box.setCurrentIndex(self.scale_box.findText(A.CUSTOM))
            self.scale_box.blockSignals(False)
            self.key_box.setEnabled(False)
        self.apply_settings()

    # ============================================================================================================ settings
    def apply_settings(self, *_a):
        """The window's settings into the running engine (and the labels)."""
        speed, amount = self.speed.value(), self.amount.value()
        self.speed_lbl.setText("Instant" if speed == 0 else f"{speed} ms")
        self.amount_lbl.setText(f"{amount} %")
        self.gate_lbl.setText(f"{self.gate.value()} dB")
        self.configure(self.runner.engine if self.runner and self.runner.engine else None)
        self.view.bypass = self.bypass_box.isChecked()
        for sec in (self.sound_sec, self.key_sec, self.feel_sec):
            sec.refresh_summary()
        self.save_prefs()

    def configure(self, engine):
        if engine is None:
            return
        engine.allowed = self.allowed()
        engine.speed_ms = float(self.speed.value())
        engine.amount = self.amount.value() / 100.0
        engine.bypass = self.bypass_box.isChecked()
        engine.a4 = float(self.a4_spin.value())
        engine.gate_db = float(self.gate.value())

    def save_prefs(self, *_a):
        if self._loading:
            return
        d = {"system": self.sys_box.currentText(), "input": self.in_box.currentText().replace("  (default)", ""),
             "output": self.out_box.currentText().replace("  (default)", ""), "channel": self.chan_box.currentIndex(),
             "block": self.block_box.currentData(), "voice": self.voice_box.currentText(), "key": self.key_box.currentText(),
             "scale": self.scale_box.currentText(), "custom": list(self.allowed()), "speed": self.speed.value(), "amount": self.amount.value(),
             "gate": self.gate.value(),
             "a4": self.a4_spin.value()}
        self.prefs.update(d)
        save_settings(self.prefs, self._settings_file)

    def restore_prefs(self):
        """The choices of the last time (the devices are chosen in refresh_devices)."""
        p = self.prefs
        was = self._loading
        self._loading = True
        try:
            if p.get("key") in A.KEYS:
                self.key_box.setCurrentIndex(A.KEYS.index(p["key"]))
            if p.get("scale") and self.scale_box.findText(p["scale"]) >= 0:
                self.scale_box.setCurrentIndex(self.scale_box.findText(p["scale"]))
            if self.scale_box.currentText() == A.CUSTOM and isinstance(p.get("custom"), list):
                for b, v in zip(self.note_btns, p["custom"]):
                    b.blockSignals(True)
                    b.setChecked(bool(v))
                    b.blockSignals(False)
            for sl, k in ((self.speed, "speed"), (self.amount, "amount"), (self.gate, "gate")):
                if isinstance(p.get(k), (int, float)):
                    sl.setValue(int(p[k]))
            if isinstance(p.get("a4"), (int, float)):
                self.a4_spin.setValue(float(p["a4"]))
            if isinstance(p.get("channel"), int) and 0 <= p["channel"] < self.chan_box.count():
                self.chan_box.setCurrentIndex(p["channel"])
            if p.get("block") in AU.BLOCKS:
                self.block_box.setCurrentIndex(AU.BLOCKS.index(p["block"]))
            if p.get("voice") and self.voice_box.findText(p["voice"]) >= 0:
                self.voice_box.setCurrentIndex(self.voice_box.findText(p["voice"]))
        finally:
            self._loading = was
        self.scale_changed()

    # ============================================================================================================ running
    def running(self):
        return self.runner is not None and self.runner.running()

    def toggle(self):
        if self.running():
            self.stop()
            self.status.say("Stopped.")
        else:
            self.start()

    def start(self):
        if self.running():
            return True
        if self.audio_problem or not self.in_devs or not self.out_devs:
            self.refresh_devices()
        if self.audio_problem or not self.in_devs or not self.out_devs:
            msg = self.audio_problem or "No microphone or output was found."
            self.status.say(msg, "bad")
            QMessageBox.warning(self, "Autotune", msg)
            return False
        ind = self.in_devs[max(0, self.in_box.currentIndex())]
        outd = self.out_devs[max(0, self.out_box.currentIndex())]
        host = self.sys_box.currentText()
        self.runner = AU.Runner(self.sound_module())
        try:
            info = self.runner.start(ind, outd, block=self.block_box.currentData() or AU.DEFAULT_BLOCK, fmin=self.voice_box.currentData(),
                                     in_channel=self.chan_box.currentData(), host_name=host, a4=self.a4_spin.value(), configure=self.configure)
        except AU.AudioError as ex:
            self.runner = None
            self.status.say(str(ex).split("\n")[0], "bad")
            QMessageBox.warning(self, "Autotune", str(ex))
            self.update_ui()
            return False
        self.status.say(f"Listening at {info['fs']} Hz. Delay about {info['total_ms']:.0f} ms "
                        f"({info['engine_ms']:.0f} ms pitch finding + {info['device_ms']:.0f} ms sound card).")
        self.update_ui()
        return True

    def stop(self):
        if self.runner is not None:
            self.runner.stop()
        self.runner = None
        self.view.update_view(None, -120.0, -120.0, False, self.bypass_box.isChecked())
        self.update_ui()

    def tick(self):
        """About 30 times a second: what the engine hears, on the screen."""
        r = self.runner
        if r is None or not r.running():
            return
        if r.error:
            msg = f"The sound engine stopped: {r.error}"
            self.stop()
            self.status.say(msg, "bad")
            return
        e = r.engine
        self.view.update_view(dict(e.state), e.in_db, e.out_db, True, e.bypass)
        if r.dropouts or e.underruns:
            self.status.say(f"Delay about {r.info['total_ms']:.0f} ms. The sound crackled {r.dropouts + e.underruns} time(s): try a bigger "
                            "buffer or close other programs.", "warn")

    def update_ui(self):
        run = self.running()
        self.start_btn.setText("Stop" if run else "Start")
        for w in (self.sys_box, self.in_box, self.out_box, self.chan_box, self.block_box, self.voice_box, self.refresh_btn):
            w.setEnabled(not run)
        self.start_btn.setEnabled(True)
        if not run and not self.status.text():
            self.status.say("Not started." if not self.audio_problem else self.audio_problem, "bad" if self.audio_problem else "")


def make_tab(host=None):
    t = AutotuneTab(host)
    t.restore_prefs()
    return t
