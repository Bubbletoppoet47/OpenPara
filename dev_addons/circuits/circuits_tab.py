"""circuits_tab.py - the Circuits tab: palette, schematic editor, property panel, live meters, Run (transient) and oscilloscope."""
import json
import math
import os

import numpy as np
from PyQt6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QDrag, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPushButton, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import netsolve as ns
import parts as P
from editor import CircuitScene, CircuitView, GRID, PartItem, WireItem, orthogonalize

FILTER = "OpenPara circuit (*.opcirc);;All files (*)"


# ------------------------------------------------------------------------------------------------------------- analysis
class Model:
    """The drawing turned into a solver network, plus what the drawing needs back (net names per pin, warnings)."""

    def __init__(self, scene, blown=()):
        self.scene, self.blown = scene, set(blown)
        self.warnings = []
        self.net = ns.Net()
        self.pin_net = {}                       # (part, pin) -> net name
        self.build()

    def nname(self, nid, gnd):
        return "0" if nid in gnd else f"n{nid}"

    def build(self):
        sc = self.scene
        net_of_pin, gnd, _w = sc.connectivity()
        parts = sorted(sc.parts(), key=lambda q: q.name)
        for p in parts:
            for i in range(len(p.defn.pins)):
                self.pin_net[(p, i)] = self.nname(net_of_pin[(p, i)], gnd)
        self.has_ground = bool(gnd)
        for p in parts:
            nets = [self.pin_net[(p, i)] for i in range(len(p.defn.pins))]
            if p.kind in ("GND", "VM", "OHM", "SCOPE"):
                continue
            if p.kind == "FUSE" and p.name in self.blown:
                self.net.add("SW", p.name, nets, closed=False)
                continue
            if p.kind == "SW" and False:
                pass
            P.to_elements(self.net, p.kind, p.name, nets, p.prm)
        # warnings -------------------------------------------------------------------------------------------
        if parts and not self.has_ground:
            self.warnings.append("No ground symbol: add a Ground and connect it to the 0 V side of the circuit.")
        count = {}
        for (p, i), n in self.pin_net.items():
            count[n] = count.get(n, 0) + 1
        for (p, i), n in self.pin_net.items():
            if n != "0" and count[n] == 1 and p.kind not in ("SCOPE", "GND") and not (p.kind == "POT" and i == 2):
                self.warnings.append(f"{p.name} pin {p.defn.pins[i][0]} is not connected to anything.")
        for p in parts:
            if p.kind == "LED":
                a, k = self.pin_net[(p, 0)], self.pin_net[(p, 1)]
                has_r = any(q.kind in ("R", "POT", "LAMP") for q in parts)
                if not has_r:
                    self.warnings.append(f"{p.name}: no resistor in the circuit - an LED needs a current-limiting resistor.")
        vs = [p for p in parts if p.kind in ("BAT", "WALL", "FGEN")]
        for p in vs:
            if self.pin_net[(p, 0)] == self.pin_net[(p, 1)]:
                self.warnings.append(f"{p.name}: both terminals are on the same net (shorted).")

    def source_periods(self):
        fs = [p.prm["freq"] for p in self.scene.parts() if p.kind in ("WALL", "FGEN") and p.prm.get("freq", 0) > 0
              and not (p.kind == "FGEN" and p.prm["wave"] == "dc")]
        return fs


def pn(model, part, i):
    return model.pin_net[(part, i)]


def apply_dc(model, scene, res):
    """Show the operating point on the drawing: meters, LED glow, lamp glow, fuse state. Returns extra warnings and fuses to blow."""
    warns, blow = [], []
    ac = bool(model.source_periods())
    for p in scene.parts():
        p.readout = ""
        p.glow = 0.0
        p.state = {}
        k = p.kind
        try:
            if k == "VM":
                v = res.vdiff(pn(model, p, 0), pn(model, p, 1))
                p.readout = "…" if ac else P.eng(float(v), "V")
            elif k == "AM":
                p.readout = "…" if ac else P.eng(float(res.i(p.name)), "A")
            elif k == "OHM":
                r = ns.resistance(model.net, pn(model, p, 0), pn(model, p, 1))
                p.readout = P.eng(r, "Ω")
            elif k == "LED":
                i = float(res.i(p.name))
                p.glow = max(0.0, min(1.0, i / (p.prm["imax"] * 1e-3)))
                if i > 1.5 * p.prm["imax"] * 1e-3:
                    warns.append(f"{p.name}: {P.eng(i, 'A')} is far over its {p.prm['imax']:g} mA rating - it would burn out.")
            elif k == "LAMP":
                i = float(res.i(p.name))
                p.glow = min(1.0, i * i * p.prm["r"] / max(p.prm["watts"], 1e-9))
            elif k == "FUSE":
                i = abs(float(res.i(p.name)))
                if i > p.prm["rating"]:
                    blow.append(p.name)
            elif k in ("BAT",):
                i = abs(float(res.i(p.name)))
                if i > 10:
                    warns.append(f"{p.name}: {P.eng(i, 'A')} flows - the supply is probably shorted.")
        except Exception:
            p.readout = "?"
        if p.name in model.blown:
            p.state = {"blown": True}
        p.update()
    return warns, blow


def run_transient(model, scene, power_on=True):
    """-> dict(res, tstop) with the transient result and what the meters / scope need."""
    scopes = sorted((p for p in scene.parts() if p.kind == "SCOPE"), key=lambda q: q.name)
    fs = model.source_periods()
    if scopes:
        tstop = 20 * scopes[0].prm["timediv"]
    elif fs:
        tstop = 6.0 / min(fs)
    else:
        tstop = 10e-3
    steps = 3000
    dt = tstop / steps
    res = ns.transient(model.net, tstop, dt, start_dc=not power_on)
    return {"res": res, "tstop": tstop}


def apply_run(model, scene, run):
    res, tstop = run["res"], run["tstop"]
    t = res.axis
    sel = t >= tstop / 2
    for p in scene.parts():
        try:
            if p.kind == "VM":
                v = res.vdiff(pn(model, p, 0), pn(model, p, 1))[sel]
                p.readout = fmt_ac(v, "V")
            elif p.kind == "AM":
                p.readout = fmt_ac(np.asarray(res.i(p.name))[sel], "A")
        except Exception:
            p.readout = "?"
        p.update()


def fmt_ac(x, unit):
    avg = float(np.mean(x))
    rms = float(np.sqrt(np.mean(np.square(x))))
    ripple = float(np.sqrt(max(rms * rms - avg * avg, 0.0)))
    if ripple < 0.02 * max(abs(avg), 1e-12) or ripple < 1e-9:
        return P.eng(avg, unit)
    return f"{P.eng(rms, unit)} rms"


# ------------------------------------------------------------------------------------------------------------- scope screen
class ScopeScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 240)
        self.data = None          # dict(t, ch[list of arrays or None], timediv, vdiv, trig)

    def set_data(self, d):
        self.data = d
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#06140f"))
        m = 8
        r = QRectF(m, m, w - 2 * m, h - 2 * m)
        p.setPen(QPen(QColor("#1d5e45"), 1))
        for k in range(11):
            x = r.left() + r.width() * k / 10
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for k in range(9):
            y = r.top() + r.height() * k / 8
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(QColor("#2f8f6b"), 1.5))
        p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
        p.drawLine(QPointF(r.center().x(), r.top()), QPointF(r.center().x(), r.bottom()))
        d = self.data
        if not d:
            p.setPen(QColor("#6bbf9d"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Add an oscilloscope, wire CH1..CH4 and GND, then press Run.")
            return
        t, td, vd = d["t"], d["timediv"], d["vdiv"]
        t0 = trigger_start(t, d["ch"], d["trig"], td)
        p.setClipRect(r)
        for ci, y in enumerate(d["ch"]):
            if y is None:
                continue
            p.setPen(QPen(QColor(P.CHANNEL_COLORS[ci]), 2))
            sel = (t >= t0) & (t <= t0 + 10 * td)
            tt, yy = t[sel] - t0, y[sel]
            if len(tt) < 2:
                continue
            xs = r.left() + tt / (10 * td) * r.width()
            ys = r.center().y() - yy / (8 * vd) * 8 * r.height() / 8 * 1.0 / 1.0
            ys = r.center().y() - (yy / vd) * (r.height() / 8)
            ys = np.clip(ys, -1e4, 1e4)
            pts = [QPointF(float(a), float(b)) for a, b in zip(xs, ys)]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
        # trigger marker
        p.setPen(QPen(QColor("#ff9f1c"), 1, Qt.PenStyle.DashLine))
        ty = r.center().y() - d["trig"] / d["vdiv"] * (r.height() / 8)
        p.drawLine(QPointF(r.left(), ty), QPointF(r.right(), ty))
        p.setClipping(False)
        f = QFont("Consolas")
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#9fe3c6"))
        p.drawText(QRectF(r.left() + 4, r.bottom() - 16, 300, 14), Qt.AlignmentFlag.AlignLeft, f"{P.eng(td, 's')}/div   {P.eng(vd, 'V')}/div")


def trigger_start(t, chans, level, td):
    """Time of the first rising crossing of `level` on the first connected channel (after the first division); 0 when none."""
    for y in chans:
        if y is None:
            continue
        sel = np.where(t >= td)[0]
        if len(sel) < 2:
            return 0.0
        yy = y[sel[0]:]
        hit = np.where((yy[:-1] < level) & (yy[1:] >= level))[0]
        if len(hit):
            k = sel[0] + hit[0]
            f = (level - y[k]) / (y[k + 1] - y[k]) if y[k + 1] != y[k] else 0.0
            return float(t[k] + f * (t[k + 1] - t[k]))
        return 0.0
    return 0.0


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
        md.setText("opcirc-part:" + kind)
        dr = QDrag(self)
        dr.setMimeData(md)
        dr.exec(Qt.DropAction.CopyAction)


# ------------------------------------------------------------------------------------------------------------- the tab
class CircuitsTab(QWidget):
    def __init__(self, path=None):
        super().__init__()
        self.path = None
        self.host = None
        self.blown = set()
        self.last_run = None
        self.dirty = False
        self.scene = CircuitScene()
        self.view = CircuitView(self.scene)
        self.palette = Palette()
        self.props = QWidget()
        self.props_form = QFormLayout(self.props)
        self.warn_list = QListWidget()
        self.warn_list.setMaximumHeight(110)
        self.scope = ScopeScreen()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.power_on = QCheckBox("Power-on transient (start at 0 V)")
        self.power_on.setChecked(True)
        self.scope_pick = QComboBox()
        self.scope_pick.currentIndexChanged.connect(self.scope_changed)
        self.sc_edits = {}
        self.layout_ui()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.live)
        self.scene.changed.connect(self.edited)
        self.scene.selection_changed.connect(self.show_props)
        self.scene.say.connect(self.status.setText)
        self.palette.itemClicked.connect(self.pick_part)
        self.view.setFocus()
        if path and os.path.isfile(path):
            self.load(path)
        else:
            self.live()

    # ------------------------------------------------------------------ layout
    def layout_ui(self):
        top = QHBoxLayout()
        self.buttons = {}
        for key, text, tip, fn in (("new", "New", "Start an empty circuit", self.new), ("open", "Open", "Open a .opcirc file", self.open_dialog),
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
        self.run_btn.setToolTip("Simulate over time (the oscilloscope and the meters' average / RMS use this)")
        self.run_btn.setStyleSheet("font-weight:bold;")
        self.run_btn.clicked.connect(self.run)
        top.addWidget(self.run_btn)
        top.addWidget(self.power_on)
        self.ex = QComboBox()
        self.ex.addItem("Examples…")
        for n in EXAMPLES:
            self.ex.addItem(n)
        self.ex.activated.connect(self.load_example)
        top.addWidget(self.ex)
        rf = QPushButton("Replace fuses")
        rf.clicked.connect(self.reset_fuses)
        top.addWidget(rf)
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
        rv.addWidget(QLabel("Oscilloscope"))
        sh = QHBoxLayout()
        sh.addWidget(self.scope_pick)
        for key, label in (("timediv", "time/div"), ("vdiv", "V/div"), ("trig", "trigger V")):
            e = QLineEdit()
            e.setMaximumWidth(70)
            e.setToolTip(label)
            e.editingFinished.connect(lambda k=key: self.scope_edit(k))
            self.sc_edits[key] = e
            sh.addWidget(QLabel(label))
            sh.addWidget(e)
        rv.addLayout(sh)
        rv.addWidget(self.scope, 1)

        split = QSplitter()
        split.addWidget(left)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.view, 1)
        mv.addWidget(self.status)
        split.addWidget(mid)
        split.addWidget(right)
        split.setSizes([210, 760, 420])
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
        if self.dirty and QMessageBox.question(self, "New circuit", "Discard the current circuit?") != QMessageBox.StandardButton.Yes:
            return
        self.scene.from_json({})
        self.scene.undo_stack.clear()
        self.blown.clear()
        self.path = None
        self.dirty = False
        self.last_run = None
        self.edited()

    def reset_fuses(self):
        self.blown.clear()
        self.last_run = None
        self.live()

    # ------------------------------------------------------------------ files
    def title(self):
        return os.path.basename(self.path) if self.path else "Circuit"

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.scene.from_json(d)
        self.scene.undo_stack.clear()
        self.path = path
        self.dirty = False
        self.last_run = None
        self.blown.clear()
        self.live()
        self.fit()

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open circuit", "", FILTER)
        if p:
            self.load(p)

    def is_dirty(self):
        return self.dirty

    def save(self):
        if not self.path:
            return self.save_as()
        import fileio
        fileio.write_text(self.path, json.dumps(self.scene.to_json(), indent=1))
        self.dirty = False
        self.status.setText(f"Saved {self.path}")

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save circuit", self.path or "circuit.opcirc", FILTER)
        if p:
            if not p.lower().endswith(".opcirc"):
                p += ".opcirc"
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
        self.blown.clear()
        self.last_run = None
        self.dirty = False
        self.live()
        self.fit()
        self.status.setText(f"Example: {name}. Press Run to see it over time.")

    # ------------------------------------------------------------------ solving
    def edited(self):
        self.dirty = True
        self.last_run = None
        self.timer.start(120)

    def live(self):
        sc = self.scene
        model = Model(sc, self.blown)
        warns = list(model.warnings)
        self.model = model
        for p in sc.parts():
            p.readout, p.glow, p.state = "", 0.0, {}
        if sc.parts() and model.has_ground and model.net.elems:
            try:
                res = ns.dc(model.net)
                w, blow = apply_dc(model, sc, res)
                warns += w
                if blow:
                    self.blown.update(blow)
                    warns.append("Fuse blown: " + ", ".join(blow) + " (Replace fuses to reset).")
                    return self.live()
            except ns.SolveError as e:
                warns.append(f"The solver could not find an operating point: {e}")
            except Exception as e:                      # noqa: BLE001
                warns.append(f"Solver problem: {e}")
        elif sc.parts() and model.has_ground:
            apply_dc(model, sc, ns.dc(model.net)) if model.net.elems else None
        for p in sc.parts():
            if p.name in self.blown:
                p.state = {"blown": True}
                p.update()
        self.fill_warnings(warns)
        self.refresh_scope_list()
        self.scope.set_data(None)
        sc.update()

    def fill_warnings(self, warns):
        self.warn_list.clear()
        if not warns:
            self.warn_list.addItem("No problems found.")
        for w in warns:
            self.warn_list.addItem("⚠ " + w)

    def run(self):
        self.live()
        model = self.model
        if not model.has_ground or not model.net.elems:
            self.status.setText("Nothing to simulate yet - add a source and a ground.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            run = run_transient(model, self.scene, self.power_on.isChecked())
        except Exception as e:                           # noqa: BLE001
            QApplication.restoreOverrideCursor()
            self.warn_list.addItem(f"⚠ Transient failed: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.last_run = run
        apply_run(model, self.scene, run)
        self.draw_scope()
        self.status.setText(f"Ran {P.eng(run['tstop'], 's')} of circuit time. Meters now show the average (or RMS for AC) over the second half.")
        self.scene.update()

    # ------------------------------------------------------------------ oscilloscope
    def scopes(self):
        return sorted((p for p in self.scene.parts() if p.kind == "SCOPE"), key=lambda q: q.name)

    def refresh_scope_list(self):
        cur = self.scope_pick.currentText()
        self.scope_pick.blockSignals(True)
        self.scope_pick.clear()
        names = [s.name for s in self.scopes()]
        self.scope_pick.addItems(names)
        if cur in names:
            self.scope_pick.setCurrentText(cur)
        self.scope_pick.blockSignals(False)
        self.scope_changed()

    def cur_scope(self):
        n = self.scope_pick.currentText()
        for s in self.scopes():
            if s.name == n:
                return s
        return None

    def scope_changed(self):
        s = self.cur_scope()
        for k, e in self.sc_edits.items():
            e.setEnabled(s is not None)
            e.setText(P.eng(s.prm[k]).replace(" ", "") if s else "")
        self.draw_scope()

    def scope_edit(self, key):
        s = self.cur_scope()
        if not s:
            return
        try:
            v = P.parse(self.sc_edits[key].text())
            if key != "trig" and v <= 0:
                raise ValueError
        except ValueError:
            self.sc_edits[key].setText(P.eng(s.prm[key]).replace(" ", ""))
            return
        if v == s.prm[key]:
            return
        s.prm[key] = v
        s.update()
        self.dirty = True
        if key == "timediv" and self.last_run is not None:
            self.run()
        else:
            self.draw_scope()

    def draw_scope(self):
        s = self.cur_scope()
        if not s or not self.last_run:
            return self.scope.set_data(None)
        res = self.last_run["res"]
        gnd = pn(self.model, s, 4)
        ch = []
        for i in range(4):
            n = pn(self.model, s, i)
            cnt = sum(1 for (q, j), nn in self.model.pin_net.items() if nn == n and not (q is s))
            ch.append(np.asarray(res.v(n) - res.v(gnd), float) if cnt else None)
        self.scope.set_data({"t": res.axis, "ch": ch, "timediv": s.prm["timediv"], "vdiv": s.prm["vdiv"], "trig": s.prm["trig"]})

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
                e.setToolTip("Engineering notation works: 4.7k, 100n, 2meg")
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
            self.status.setText("Could not read that number (examples: 4.7k, 100n, 2meg).")
            return
        if v != p.prm[key]:
            self.set_val(p, key, v)

    def set_val(self, p, key, v):
        self.scene.push_undo()
        p.prm[key] = v
        p.update()
        self.scene.changed.emit()
        if p.kind == "SCOPE":
            self.refresh_scope_list()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_S and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return self.save()
        super().keyPressEvent(ev)


# ------------------------------------------------------------------------------------------------------------- examples
def _wire(sc, a, b=None, pts=None):
    """a, b = (part, pin_index); or pts = explicit list of grid points. Wires are drawn as elbows."""
    if pts is None:
        pa, pb = a[0].pin_scene(a[1]), b[0].pin_scene(b[1])
        pts = [(pa.x(), pa.y()), (pb.x(), pb.y())]
    else:
        pts = [(x * GRID, y * GRID) for x, y in pts]
    sc.addItem(WireItem(orthogonalize(pts)))


def ex_led(sc):
    b = sc.add_part("BAT", 0, 0)
    b.prm["dc"] = 9.0
    r = sc.add_part("R", 6 * GRID, -2 * GRID)
    r.prm["r"] = 330.0
    led = sc.add_part("LED", 12 * GRID, 0, rot=1)
    g = sc.add_part("GND", 0, 4 * GRID)
    vm = sc.add_part("VM", 6 * GRID, -6 * GRID)
    _wire(sc, (b, 0), (r, 0))
    _wire(sc, (r, 1), (led, 0))
    _wire(sc, None, pts=[(12, 2), (0, 2)])
    _wire(sc, (b, 1), (g, 0))
    _wire(sc, None, pts=[(3, -6), (3, -2)])
    _wire(sc, None, pts=[(9, -6), (9, -2)])


def ex_rc(sc):
    f = sc.add_part("FGEN", 0, 0)
    f.prm.update(wave="square", amp=5.0, freq=1000.0, offset=5.0)
    r = sc.add_part("R", 6 * GRID, -2 * GRID)
    r.prm["r"] = 1000.0
    c = sc.add_part("C", 9 * GRID, 2 * GRID, rot=1)
    c.prm["c"] = 220e-9
    g1 = sc.add_part("GND", 0, 4 * GRID)
    g2 = sc.add_part("GND", 9 * GRID, 6 * GRID)
    s = sc.add_part("SCOPE", 18 * GRID, 0)
    s.prm.update(timediv=0.5e-3, vdiv=3.0, trig=5.0)
    _wire(sc, (f, 0), (r, 0))
    _wire(sc, (r, 1), (c, 0))
    _wire(sc, (c, 1), (g2, 0))
    _wire(sc, (f, 1), (g1, 0))
    _wire(sc, None, pts=[(13, -3), (13, -8), (1, -8), (1, -2)])
    _wire(sc, None, pts=[(13, -1), (9, -1)])
    _wire(sc, None, pts=[(13, 5), (13, 6), (9, 6)])


def ex_buck(sc):
    b = sc.add_part("BAT", 0, 0)
    b.prm["dc"] = 12.0
    sc.add_part("BUCK", 8 * GRID, 0)
    r = sc.add_part("R", 18 * GRID, 0, rot=1)
    r.prm["r"] = 10.0
    sc.add_part("VM", 22 * GRID, 0, rot=1)
    g1 = sc.add_part("GND", 0, 4 * GRID)
    sc.add_part("GND", 12 * GRID, 4 * GRID)
    _wire(sc, None, pts=[(0, -2), (4, -2), (4, -1)])
    _wire(sc, None, pts=[(0, 2), (4, 2), (4, 1)])
    _wire(sc, (b, 1), (g1, 0))
    _wire(sc, None, pts=[(12, -1), (18, -1), (18, -3)])
    _wire(sc, None, pts=[(12, 1), (12, 4)])
    _wire(sc, None, pts=[(18, 3), (18, 4), (12, 4)])
    _wire(sc, None, pts=[(18, -3), (22, -3)])
    _wire(sc, None, pts=[(22, 3), (22, 4), (18, 4)])


EXAMPLES = {"LED with resistor": ex_led, "RC low-pass (scope)": ex_rc, "Buck converter 12 V → 5 V": ex_buck}


def make_tab(path=None):
    return CircuitsTab(path)
