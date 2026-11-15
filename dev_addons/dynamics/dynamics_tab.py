"""dynamics_tab.py - the System dynamics tab: parts palette, drag-and-drop mechanical diagram, property panel, checks, and three views of the drawn
system: the time response (Run), its equations, and its modes (poles, natural frequency, damping ratio)."""
import json
import math
import os

import numpy as np
from PyQt6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QDrag, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                             QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dyn_core as core
import dyn_parts as P
from dyn_editor import GRID, MIME, DynScene, DynView, PartItem, WireItem, orthogonalize

FILTER = "OpenPara dynamics (*.opdyn);;All files (*)"
QUANTITIES = ("position", "velocity", "acceleration")


# ------------------------------------------------------------------------------------------------------------- analysis
class Model:
    """The drawing turned into a solver network, plus the checks the drawing needs (warnings) and the solved System (or None)."""

    def __init__(self, scene):
        self.scene = scene
        self.warnings = []
        self.net = core.Net()
        self.pin_node = {}                      # (part, pin) -> node name
        self.system = None
        self.error = None
        self.build()

    def build(self):
        sc = self.scene
        net_of_pin, _g, _w = sc.connectivity()
        parts = sorted(sc.parts(), key=lambda q: q.name)
        for p in parts:
            for i in range(len(p.defn.pins)):
                self.pin_node[(p, i)] = f"n{net_of_pin[(p, i)]}"
        # pins that are alone on their node (a one-pin part is fine alone only when it is a wall or a source ... and even then it needs a partner)
        count = {}
        for n in self.pin_node.values():
            count[n] = count.get(n, 0) + 1
        for (p, i), n in self.pin_node.items():
            if count[n] == 1 and len(p.defn.pins) > 1:
                self.warnings.append(f"{p.name} pin {p.defn.pins[i][0]} is not connected to anything.")
        # a wire between the two kinds of motion
        doms = {}
        for (p, i), n in self.pin_node.items():
            doms.setdefault(n, set()).add(p.defn.pins[i][3])
        if any(len(d) > 1 for d in doms.values()):
            bad = sorted({p.name for (p, i), n in self.pin_node.items() if len(doms[n]) > 1})
            self.warnings.append("Translational (blue) and rotational (orange) pins are joined: " + ", ".join(bad)
                                 + ". Use a rack and pinion to go between straight-line and turning motion.")
            return
        if not parts:
            return
        for p in parts:
            nodes = [self.pin_node[(p, i)] for i in range(len(p.defn.pins))]
            P.to_elements(self.net, p.kind, p.name, nodes, p.prm)
        try:
            self.system = core.build(self.net)
        except core.DynError as e:
            self.error = str(e)
            self.warnings.append(str(e))
            return
        except Exception as e:                                   # noqa: BLE001
            self.error = f"Solver problem: {e}"
            self.warnings.append(self.error)
            return
        self.warnings += self.system.warnings
        if not self.system.coords:
            self.warnings.append("Nothing moves yet: add a mass or an inertia (and connect it with springs / dampers and a fixed wall or frame).")
        elif not self.system.inputs:
            self.warnings.append("No source yet: add a force or torque source (or a motor) to push the system and see its response.")
        elif not self.system.stable():
            pl = self.system.poles()
            if any(z.real > 1e-9 for z in pl):
                self.warnings.append("The system runs away (a pole has a positive real part). A link above its pivot, or a negative stiffness, does this.")
            else:
                if any(abs(z) < 1e-9 for z in pl):
                    self.warnings.append("Something is free to drift (a pole at zero): a mass or inertia with no spring to a wall or frame. "
                                         "That is fine for a rigid-body motion, but its position will not settle.")
                if any(abs(z.real) <= 1e-9 and abs(z.imag) > 1e-9 for z in pl):
                    self.warnings.append("Part of the system has no damping (a pole on the imaginary axis), so it will oscillate forever. Add a damper "
                                         "(or a motor, which also damps).")

    def node_of(self, part):
        return self.pin_node[(part, 0)]


# ------------------------------------------------------------------------------------------------------------- response plot
def nice_ticks(lo, hi, n=6):
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=mag)
    first = math.ceil(lo / step) * step
    out = []
    v = first
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


class ResponsePlot(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(380, 240)
        self.data = None            # dict(t, y, xlabel, ylabel, extra)

    def set_data(self, d):
        self.data = d
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        r = QRectF(64, 12, w - 80, h - 48)
        d = self.data
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        if not d:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Press Run to see how the system responds over time.")
            return
        t, y = np.asarray(d["t"]), np.asarray(d["y"])
        lo, hi = float(np.min(y)), float(np.max(y))
        if hi - lo < 1e-12 * max(1.0, abs(hi)):
            lo, hi = lo - 1.0, hi + 1.0
        pad = 0.08 * (hi - lo)
        lo, hi = lo - pad, hi + pad
        t0, t1 = float(t[0]), float(t[-1])
        p.setPen(QPen(QColor("#e1e6ee"), 1))
        for v in nice_ticks(lo, hi):
            yy = r.bottom() - (v - lo) / (hi - lo) * r.height()
            p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(0, yy - 8, r.left() - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:.4g}")
            p.setPen(QPen(QColor("#e1e6ee"), 1))
        for v in nice_ticks(t0, t1):
            xx = r.left() + (v - t0) / (t1 - t0) * r.width()
            p.drawLine(QPointF(xx, r.top()), QPointF(xx, r.bottom()))
            p.setPen(QColor("#4a5668"))
            p.drawText(QRectF(xx - 30, r.bottom() + 3, 60, 16), Qt.AlignmentFlag.AlignCenter, f"{v:.4g}")
            p.setPen(QPen(QColor("#e1e6ee"), 1))
        p.setPen(QPen(QColor("#9aa6b8"), 1))
        p.drawRect(r)
        p.setPen(QColor("#4a5668"))
        p.drawText(QRectF(r.left(), h - 18, r.width(), 16), Qt.AlignmentFlag.AlignCenter, d.get("xlabel", "time (s)"))
        p.save()
        p.translate(12, r.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-r.height() / 2, -8, r.height(), 16), Qt.AlignmentFlag.AlignCenter, d.get("ylabel", ""))
        p.restore()
        p.setClipRect(r)
        for ex in d.get("extra", []):                                       # reference lines (final value, band)
            yy = r.bottom() - (ex["y"] - lo) / (hi - lo) * r.height()
            p.setPen(QPen(QColor(ex.get("color", "#e76f51")), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
        p.setPen(QPen(QColor("#1f77b4"), 2))
        step = max(1, len(t) // 1500)
        xs = r.left() + (t[::step] - t0) / (t1 - t0) * r.width()
        ys = r.bottom() - (y[::step] - lo) / (hi - lo) * r.height()
        pts = [QPointF(float(a), float(b)) for a, b in zip(xs, ys)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)


# ------------------------------------------------------------------------------------------------------------- palette
class Palette(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setRootIsDecorated(True)
        for cat in P.PALETTE_ORDER:
            top = QTreeWidgetItem([cat])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addTopLevelItem(top)
            for kind, d in P.PARTS.items():
                if d.cat == cat:
                    it = QTreeWidgetItem([d.label])
                    it.setData(0, Qt.ItemDataRole.UserRole, kind)
                    top.addChild(it)
            top.setExpanded(True)

    def kind_of(self, item):
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def startDrag(self, actions):
        kind = self.kind_of(self.currentItem())
        if not kind:
            return
        md = QMimeData()
        md.setText(MIME + kind)
        dr = QDrag(self)
        dr.setMimeData(md)
        dr.exec(Qt.DropAction.CopyAction)


# ------------------------------------------------------------------------------------------------------------- the tab
class DynamicsTab(QWidget):
    def __init__(self, path=None):
        super().__init__()
        self.path = None
        self.host = None
        self.dirty = False
        self.model = None
        self.run_data = None
        self.scene = DynScene()
        self.view = DynView(self.scene)
        self.palette = Palette()
        self.props = QWidget()
        self.props_form = QFormLayout(self.props)
        self.warn_list = QListWidget()
        self.warn_list.setMaximumHeight(110)
        self.plot = ResponsePlot()
        self.eq_text = QPlainTextEdit()
        self.eq_text.setReadOnly(True)
        self.mode_text = QPlainTextEdit()
        self.mode_text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.eq_text.setFont(mono)
        self.mode_text.setFont(mono)
        self.eq_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.out_part = QComboBox()
        self.out_qty = QComboBox()
        self.out_qty.addItems(QUANTITIES)
        self.run_time = QLineEdit()
        self.run_time.setMaximumWidth(80)
        self.run_time.setPlaceholderText("auto")
        self.run_time.setToolTip("How long to simulate (seconds). Leave empty to choose from the system's poles.")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.layout_ui()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.live)
        self.scene.changed.connect(self.edited)
        self.scene.selection_changed.connect(self.show_props)
        self.scene.say.connect(self.status.setText)
        self.palette.itemClicked.connect(self.pick_part)
        self.out_part.activated.connect(lambda _i: self.show_run())
        self.out_qty.activated.connect(lambda _i: self.show_run())
        self.view.setFocus()
        self.show_props()
        if path and os.path.isfile(path):
            self.load(path)
        else:
            self.live()

    # ------------------------------------------------------------------ layout
    def layout_ui(self):
        top = QHBoxLayout()
        self.buttons = {}
        for key, text, tip, fn in (("new", "New", "Start an empty system", self.new), ("open", "Open", "Open a .opdyn file", self.open_dialog),
                                   ("save", "Save", "Save (Ctrl+S)", self.save), ("saveas", "Save as", "", self.save_as),
                                   ("undo", "Undo", "Ctrl+Z", self.scene.undo), ("redo", "Redo", "Ctrl+Y", self.scene.redo),
                                   ("wire", "Wire (W)", "Click a start point, click corners, click a pin to finish", self.wire_tool),
                                   ("rot", "Rotate (R)", "Rotate the selected part", self.scene.rotate_selected),
                                   ("flip", "Mirror (F)", "", lambda: self.scene.rotate_selected(flip=True)),
                                   ("del", "Delete", "Delete key", self.scene.delete_selected)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
            self.buttons[key] = b
        top.addSpacing(14)
        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setToolTip("Simulate the system over time")
        self.run_btn.setStyleSheet("font-weight:bold;")
        self.run_btn.clicked.connect(self.run)
        top.addWidget(self.run_btn)
        self.ex = QComboBox()
        self.ex.addItem("Examples…")
        for n in EXAMPLES:
            self.ex.addItem(n)
        self.ex.activated.connect(self.load_example)
        top.addWidget(self.ex)
        top.addStretch(1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Parts - drag onto the sheet, or click then click on the sheet"))
        lv.addWidget(self.palette)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Selected part"))
        rv.addWidget(self.props)
        rv.addWidget(QLabel("Checks"))
        rv.addWidget(self.warn_list)
        tabs = QTabWidget()
        resp = QWidget()
        rl = QVBoxLayout(resp)
        sel = QHBoxLayout()
        sel.addWidget(QLabel("Show"))
        sel.addWidget(self.out_qty)
        sel.addWidget(QLabel("of"))
        sel.addWidget(self.out_part, 1)
        sel.addWidget(QLabel("run time (s)"))
        sel.addWidget(self.run_time)
        rl.addLayout(sel)
        rl.addWidget(self.plot, 1)
        rl.addWidget(self.result)
        tabs.addTab(resp, "Response")
        tabs.addTab(self.eq_text, "Equations")
        tabs.addTab(self.mode_text, "Modes")
        self.tabs = tabs
        rv.addWidget(tabs, 1)

        split = QSplitter()
        split.addWidget(left)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.view, 1)
        mv.addWidget(self.status)
        split.addWidget(mid)
        split.addWidget(right)
        split.setSizes([210, 700, 480])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(split, 1)

    # ------------------------------------------------------------------ tools
    def pick_part(self, item, _col=0):
        kind = self.palette.kind_of(item)
        if kind:
            self.scene.wire_tool = False
            self.scene.place_kind = kind
            self.status.setText(f"Click on the sheet to place {P.PARTS[kind].label} (right-click or Esc to stop).")
            self.view.setFocus()

    def wire_tool(self):
        self.scene.place_kind = None
        self.scene.wire_tool = True
        self.status.setText("Wire tool: click a start point, click corners, click a pin or a wire to finish. Esc cancels. "
                            "You can also start a wire directly on any pin.")
        self.view.setFocus()

    def new(self):
        if self.dirty and QMessageBox.question(self, "New system", "Discard the current system?") != QMessageBox.StandardButton.Yes:
            return
        self.scene.from_json({})
        self.scene.undo_stack.clear()
        self.path = None
        self.dirty = False
        self.run_data = None
        self.edited()

    # ------------------------------------------------------------------ files
    def title(self):
        return os.path.basename(self.path) if self.path else "Dynamics"

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.scene.from_json(d)
        self.scene.undo_stack.clear()
        self.path = path
        self.dirty = False
        self.run_data = None
        if d.get("run_time"):
            self.run_time.setText(str(d["run_time"]))
        self.live()
        self.fit()

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open system", "", FILTER)
        if p:
            self.load(p)

    def is_dirty(self):
        return self.dirty

    def to_json(self):
        d = self.scene.to_json()
        if self.run_time.text().strip():
            d["run_time"] = self.run_time.text().strip()
        return d

    def save(self):
        if not self.path:
            return self.save_as()
        import fileio
        fileio.write_text(self.path, json.dumps(self.to_json(), indent=1))
        self.dirty = False
        self.status.setText(f"Saved {self.path}")

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save system", self.path or "system.opdyn", FILTER)
        if p:
            if not p.lower().endswith(".opdyn"):
                p += ".opdyn"
            self.path = p
            self.save()

    def fit(self):
        r = self.scene.itemsBoundingRect()
        if not r.isEmpty():
            self.view.fitInView(r.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
            if self.view.transform().m11() > 1.6:
                self.view.resetTransform()
                self.view.scale(1.6, 1.6)
                self.view.centerOn(r.center())

    def load_example(self, i):
        if i <= 0:
            return
        name = self.ex.itemText(i)
        self.ex.setCurrentIndex(0)
        self.scene.from_json({})
        EXAMPLES[name](self.scene)
        self.scene.undo_stack.clear()
        self.path = None
        self.run_data = None
        self.dirty = False
        self.live()
        self.fit()
        self.status.setText(f"Example: {name}. Look at the Equations and Modes tabs, then press Run.")

    # ------------------------------------------------------------------ solving
    def edited(self):
        self.dirty = True
        self.run_data = None
        self.timer.start(120)

    def live(self):
        self.model = Model(self.scene)
        m = self.model
        self.warn_list.clear()
        if not m.warnings:
            self.warn_list.addItem("No problems found.")
        for w in m.warnings:
            self.warn_list.addItem("⚠ " + w)
        s = m.system
        self.eq_text.setPlainText(core.equations_text(s) if s else (m.error or "Draw a system to see its equations."))
        self.mode_text.setPlainText(core.modes_text(s) if s and s.coords else "")
        self.refresh_outputs()
        self.plot.set_data(None)
        self.result.setText("")
        self.scene.update()

    def refresh_outputs(self):
        cur = self.out_part.currentText()
        self.out_part.blockSignals(True)
        self.out_part.clear()
        names = [p.name for p in sorted(self.scene.parts(), key=lambda q: q.name) if p.kind in P.MOVERS]
        self.out_part.addItems(names)
        if cur in names:
            self.out_part.setCurrentText(cur)
        self.out_part.blockSignals(False)

    def part_named(self, name):
        for p in self.scene.parts():
            if p.name == name:
                return p
        return None

    def run(self):
        self.live()
        s = self.model.system
        if s is None or not s.coords or not s.inputs:
            self.status.setText("Nothing to simulate yet - add a mass / inertia, a source and (usually) a spring or damper to a wall.")
            return
        try:
            tend = P.parse(self.run_time.text()) if self.run_time.text().strip() else None
            if tend is not None and tend <= 0:
                raise ValueError
        except ValueError:
            self.status.setText("Run time must be a positive number of seconds (or leave it empty).")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.run_data = core.simulate(s, tend)
        except Exception as e:                                  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.warn_list.addItem(f"⚠ Simulation failed: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.tabs.setCurrentIndex(0)
        self.show_run()
        self.status.setText(f"Ran {self.run_data['t'][-1]:.4g} s of system time.")

    def show_run(self):
        s = self.model.system if self.model else None
        if not self.run_data or s is None:
            return self.plot.set_data(None)
        part = self.part_named(self.out_part.currentText())
        if part is None:
            return self.plot.set_data(None)
        q = self.out_qty.currentText()
        node = self.model.node_of(part)
        y = core.response(s, self.run_data, node, q)
        t = self.run_data["t"]
        rot = part.defn.pins[0][3] == "r"
        unit = {"position": "rad" if rot else "m", "velocity": "rad/s" if rot else "m/s", "acceleration": "rad/s²" if rot else "m/s²"}[q]
        extra, msg = [], ""
        stable = s.stable()
        if stable and q != "acceleration":
            final = float(y[-1])
            extra.append({"y": final, "color": "#e76f51"})
            msg = f"Final value {P.eng(final, unit)}."
            if abs(final) > 1e-12:
                peak = float(y[np.argmax(np.abs(y))])
                over = (abs(peak) - abs(final)) / abs(final) * 100
                if over > 0.5:
                    msg += f"  Peak {P.eng(peak, unit)} = {over:.1f}% overshoot."
                band = 0.02 * abs(final)
                out = np.nonzero(np.abs(y - final) > band)[0]
                ts = float(t[out[-1] + 1]) if len(out) and out[-1] + 1 < len(t) else (0.0 if not len(out) else float("nan"))
                if ts == ts:
                    msg += f"  Settles within 2% by {P.eng(ts, 's')}."
        elif not stable:
            msg = ("This system runs away (a pole has a positive real part)." if any(z.real > 1e-9 for z in s.poles())
                   else "This system never settles by itself (it drifts freely or has no damping).")
        self.plot.set_data({"t": t, "y": y, "ylabel": f"{q} of {part.name} ({unit})", "extra": extra})
        self.result.setText(msg)

    # ------------------------------------------------------------------ properties
    def show_props(self):
        while self.props_form.rowCount():
            self.props_form.removeRow(0)
        sel = [i for i in self.scene.selectedItems() if isinstance(i, PartItem)]
        if len(sel) != 1:
            self.props_form.addRow(QLabel("Select one part to edit it." if not sel else f"{len(sel)} parts selected"))
            return
        p = sel[0]
        name = QLineEdit(p.name)
        name.editingFinished.connect(lambda: self.rename(p, name))
        self.props_form.addRow("Name", name)
        for key, label, typ, default, *rest in p.defn.params:
            if typ == "num":
                e = QLineEdit(P.eng(p.prm[key]).replace(" ", ""))
                e.setToolTip("Engineering notation works: 4.7k, 100m, 2meg")
                e.editingFinished.connect(lambda k=key, w=e: self.set_num(p, k, w))
                self.props_form.addRow(label, e)
            elif typ == "choice":
                c = QComboBox()
                c.addItems(rest[0])
                c.setCurrentText(str(p.prm[key]))
                c.activated.connect(lambda _i, k=key, w=c: self.set_val(p, k, w.currentText()))
                self.props_form.addRow(label, c)
            elif typ == "bool":
                c = QCheckBox()
                c.setChecked(bool(p.prm[key]))
                c.toggled.connect(lambda v, k=key: self.set_val(p, k, v))
                self.props_form.addRow(label, c)

    def rename(self, p, w):
        new = w.text().strip()
        if not new or new == p.name:
            return
        if any(q.name == new for q in self.scene.parts() if q is not p):
            self.status.setText(f"The name {new} is already used.")
            w.setText(p.name)
            return
        self.scene.push_undo()
        p.name = new
        p.update()
        self.scene.changed.emit()

    def set_num(self, p, key, w):
        try:
            v = P.parse(w.text())
        except ValueError:
            w.setText(P.eng(p.prm[key]).replace(" ", ""))
            self.status.setText("Could not read that number (examples: 4.7k, 100m, 2meg).")
            return
        if v != p.prm[key]:
            self.set_val(p, key, v)

    def set_val(self, p, key, v):
        self.scene.push_undo()
        p.prm[key] = v
        p.update()
        self.scene.changed.emit()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_S and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return self.save()
        super().keyPressEvent(ev)


# ------------------------------------------------------------------------------------------------------------- examples
def _wire(sc, pts):
    sc.addItem(WireItem(orthogonalize([(x * GRID, y * GRID) for x, y in pts])))


def _msd(sc, rot=False):
    """wall - spring and damper in parallel - mass, pushed by a source (translational, or the same thing turning)."""
    wall = sc.add_part("FRAME" if rot else "WALL", 0, -1 * GRID)
    k = sc.add_part("TSPRING" if rot else "SPRING", 5 * GRID, -4 * GRID)
    c = sc.add_part("RDAMPER" if rot else "DAMPER", 5 * GRID, 0)
    m = sc.add_part("INERTIA" if rot else "MASS", 11 * GRID, 3 * GRID)
    f = sc.add_part("TORQUE" if rot else "FORCE", 15 * GRID, 1 * GRID)
    if rot:
        k.prm["k"], c.prm["c"], m.prm["j"], f.prm["amp"] = 200.0, 20.0, 2.0, 1.0
    else:
        k.prm["k"], c.prm["c"], m.prm["m"], f.prm["amp"] = 200.0, 20.0, 2.0, 1.0
    _wire(sc, [(0, -1), (0, -4), (2, -4)])
    _wire(sc, [(0, -4), (0, 0), (2, 0)])
    _wire(sc, [(8, -4), (11, -4), (11, 1)])
    _wire(sc, [(8, 0), (11, 0)])
    _wire(sc, [(15, -1), (15, -4), (11, -4)])
    return sc


def ex_msd(sc):
    _msd(sc, False)


def ex_rot(sc):
    _msd(sc, True)


def ex_two(sc):
    """wall - k1 - m1 - k2 - m2 with a damper on each mass: two modes."""
    w = sc.add_part("WALL", 0, -1 * GRID)
    k1 = sc.add_part("SPRING", 5 * GRID, -4 * GRID)
    m1 = sc.add_part("MASS", 11 * GRID, 3 * GRID)
    k2 = sc.add_part("SPRING", 17 * GRID, -4 * GRID)
    m2 = sc.add_part("MASS", 23 * GRID, 3 * GRID)
    c1 = sc.add_part("DAMPER", 5 * GRID, 0)
    c2 = sc.add_part("DAMPER", 17 * GRID, 0)
    f = sc.add_part("FORCE", 27 * GRID, 1 * GRID)
    for part, kv in ((k1, 200.0), (k2, 120.0)):
        part.prm["k"] = kv
    for part, cv in ((c1, 4.0), (c2, 2.0)):
        part.prm["c"] = cv
    m1.prm["m"], m2.prm["m"] = 2.0, 1.0
    _wire(sc, [(0, -1), (0, -4), (2, -4)])
    _wire(sc, [(0, -4), (0, 0), (2, 0)])
    _wire(sc, [(8, -4), (11, -4), (11, 1)])
    _wire(sc, [(8, 0), (11, 0)])
    _wire(sc, [(14, -4), (11, -4)])
    _wire(sc, [(14, 0), (11, 0)])
    _wire(sc, [(20, -4), (23, -4), (23, 1)])
    _wire(sc, [(20, 0), (23, 0)])
    _wire(sc, [(27, -1), (27, -4), (23, -4)])
    return sc


def ex_motor_link(sc):
    """A motor with a 30:1 gearbox turning a single link that hangs from its pivot."""
    m = sc.add_part("MOTOR", 0, 0)
    link = sc.add_part("LINK", 8 * GRID, 2 * GRID)
    m.prm.update(v=6.0, n=30.0)
    link.prm.update(m=0.5, l=0.2, jcm=0.002, pose=0.0)
    _wire(sc, [(3, 0), (8, 0)])
    return sc


EXAMPLES = {"Mass, spring and damper": ex_msd, "Rotating inertia, torsional spring and damper": ex_rot, "Two masses (two modes)": ex_two,
            "Motor + gearbox driving a link": ex_motor_link}


def make_tab(path=None):
    return DynamicsTab(path)
