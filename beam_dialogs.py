"""Dialogs of the 1D FEA tab: the profile (cross-section) editor, the line-load dialog and the wind / snow dialog."""
import copy
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

import loads1d
import profiles1d as pr1
import section_props as secp
import units


class SectionPreview(QWidget):
    """A small picture of the cross-section, with the neutral axis (centroid line) dashed."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(170, 150)
        self.polys = []
        self.axis_y = None

    def set_profile(self, prof):
        self.polys = pr1.drawing(prof) if prof else []
        self.axis_y = None
        if self.polys:
            ymin = min(y for poly, _ in self.polys for _, y in poly)
            self.axis_y = ymin + prof["c_bottom"]
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QColor("#999999"))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.polys:
            p.setFont(QFont("Arial", 9))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "(no picture)")
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        xs = [x for poly, _ in self.polys for x, _ in poly]
        ys = [y for poly, _ in self.polys for _, y in poly]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        s = 0.8 * min(self.width() / max(w, 1e-12), self.height() / max(h, 1e-12))
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        pt = lambda x, y: QPointF(self.width() / 2 + (x - cx) * s, self.height() / 2 - (y - cy) * s)
        for poly, hole in self.polys:
            p.setPen(QPen(QColor("#1f3d7a"), 1.4))
            p.setBrush(QColor("white") if hole else QColor(190, 215, 245))
            p.drawPolygon(QPolygonF([pt(x, y) for x, y in poly]))
        if self.axis_y is not None:
            p.setPen(QPen(QColor("#c0392b"), 1, Qt.PenStyle.DashLine))
            a, b = pt(min(xs) - 0.1 * w, self.axis_y), pt(max(xs) + 0.1 * w, self.axis_y)
            p.drawLine(a, b)


class ProfileDialog(QDialog):
    """Edits the profile of one member.  After exec(): .profile (dict, or None = cleared) and .rows (the ticked member rows)."""

    def __init__(self, tab, row):
        super().__init__(tab)
        self.tab = tab
        self.row = row
        mem = tab.members[row]
        self.setWindowTitle(f"Profile of {mem['name']}")
        self.setMinimumWidth(480)
        self.profile = copy.deepcopy(mem["profile"])
        self.rows = [row]
        self.cleared = False
        self.U = tab.U()
        self.edits = {}
        self.stored = copy.deepcopy(mem["profile"])
        lay = QVBoxLayout(self)
        note = QLabel("The member bends in the plane of the frame. <b>h</b> is always the depth in that direction (the direction the "
                      "member deflects in). The profile belongs to this member only; copy it to others with the choice at the bottom, or "
                      "right-click the members table.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#555555; font-size:11px;")
        lay.addWidget(note)
        self.shape = QComboBox()
        for key, label, _ in pr1.SHAPES:
            self.shape.addItem(label, key)
        if self.stored and self.stored.get("shape") == "imported":
            self.shape.addItem("Imported / drawn section: " + self.stored.get("label", ""), "imported")
        lay.addWidget(self.shape)
        top = QHBoxLayout()
        self.form_box = QWidget()
        self.form = QFormLayout(self.form_box)
        top.addWidget(self.form_box, 1)
        self.preview = SectionPreview()
        top.addWidget(self.preview)
        lay.addLayout(top)
        row_ = QHBoxLayout()
        self.cb_flip = QCheckBox("Flip upside down")
        self.cb_flip.setToolTip("Swaps the fibre on the member's +y side with the one on the -y side (matters for T and L sections).")
        self.cb_weak = QCheckBox("Bend about the weak axis")
        self.cb_weak.setToolTip("Turns the section 90 degrees so the member bends about its other axis.")
        row_.addWidget(self.cb_flip)
        row_.addWidget(self.cb_weak)
        row_.addStretch(1)
        lay.addLayout(row_)
        row_ = QHBoxLayout()
        b = QPushButton("Import .profprops...")
        b.setToolTip("Use a section drawn in the sketcher (Edit > Section properties). Only its numbers are kept, inside this member.")
        b.clicked.connect(self.import_file)
        row_.addWidget(b)
        b = QPushButton("Export .profprops...")
        b.clicked.connect(self.export_file)
        row_.addWidget(b)
        row_.addStretch(1)
        lay.addLayout(row_)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)
        lay.addWidget(QLabel("<b>Apply to these members</b> (tick any combination)"))
        self.member_list = QListWidget()
        self.member_list.setMaximumHeight(130)
        sel = tab.selected_rows()
        start_rows = set(sel) if (len(sel) > 1 and row in sel) else {row}
        for r_, m_ in enumerate(tab.members):
            it = QListWidgetItem(m_["name"] + ("   (has a profile: " + m_["profile"]["label"] + ")" if m_["profile"] else "   (no profile yet)"))
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setCheckState(Qt.CheckState.Checked if r_ in start_rows else Qt.CheckState.Unchecked)
            self.member_list.addItem(it)
        lay.addWidget(self.member_list)
        row_ = QHBoxLayout()
        for text, fn in (("All", lambda: self.tick_all(True)), ("None", lambda: self.tick_all(False)),
                         ("Members selected in the drawing", self.tick_selected),
                         ("Members without a profile", self.tick_missing)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row_.addWidget(b)
        lay.addLayout(row_)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.b_clear = self.bb.addButton("Remove profile", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.bb.accepted.connect(self.accept_it)
        self.bb.rejected.connect(self.reject)
        self.b_clear.clicked.connect(self.clear_it)
        lay.addWidget(self.bb)
        start = (self.stored or {}).get("shape") or "rect"
        i = self.shape.findData(start)
        self.shape.setCurrentIndex(max(0, i))
        self.cb_flip.setChecked(bool((self.stored or {}).get("flip")))
        self.cb_weak.setChecked(bool((self.stored or {}).get("weak")))
        self.build_form(self.stored if (self.stored and self.stored.get("shape") == start) else None)
        self.shape.currentIndexChanged.connect(self.shape_changed)
        self.cb_flip.toggled.connect(self.recompute)
        self.cb_weak.toggled.connect(self.recompute)
        self.recompute()

    def shape_changed(self, *_):
        self.build_form(None)
        self.recompute()

    def length_label(self, key):
        L = self.U["L"]
        return {"A": f"{L}^2", "I": f"{L}^4"}.get(key, L)

    def build_form(self, existing):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.edits = {}
        key = self.shape.currentData()
        imported = key == "imported"
        self.cb_flip.setEnabled(not imported)
        self.cb_weak.setEnabled(not imported and key not in ("custom", "round", "pipe"))
        if imported:
            self.preview.set_profile(None)
            return
        defaults = pr1.default_dims(key, self.U["L_m"])
        have = existing["dims"] if existing and existing.get("shape") == key else {}
        for k, lab in pr1.dim_defs(key):
            e = QLineEdit(f"{have.get(k, defaults[k]):.6g}")
            e.textChanged.connect(self.recompute)
            self.form.addRow(f"{lab} ({self.length_label(k)})", e)
            self.edits[k] = e

    def recompute(self, *_):
        key = self.shape.currentData()
        ok = True
        if key == "imported":
            self.profile = copy.deepcopy(self.stored)
            self.preview.set_profile(None)
        else:
            try:
                dims = {k: float(e.text()) for k, e in self.edits.items()}
                self.profile = pr1.compute(key, dims, self.cb_flip.isChecked(), self.cb_weak.isChecked() and self.cb_weak.isEnabled())
            except ValueError as ex:
                self.profile = None
                ok = False
                self.info.setText(f"<span style='color:#b00020'>{ex}</span>")
                self.preview.set_profile(None)
        if ok and self.profile:
            pf = self.profile
            L = self.U["L"]
            txt = (f"<b>{pf['label']}</b><br>A = {pf['A']:.6g} {L}&sup2;&nbsp;&nbsp; I = {pf['I']:.6g} {L}&sup4;<br>"
                   f"c(+y side) = {pf['c_top']:.5g} {L}&nbsp;&nbsp; c(-y side) = {pf['c_bottom']:.5g} {L}<br>"
                   f"S = I/c: {pf['I'] / pf['c_top']:.5g} (+y side), {pf['I'] / pf['c_bottom']:.5g} (-y side) {L}&sup3;")
            if pf.get("shape") == "angle":
                txt += ("<br><i>Angle: bending about the horizontal centroidal axis; the product of inertia is ignored (valid when the load acts "
                        "through the shear centre and the member cannot twist).</i>")
            self.info.setText(txt)
            if key != "imported":
                self.preview.set_profile(pf)
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok and self.profile is not None)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import profile properties", "", "Profile properties (*.profprops);;All files (*)")
        if not path:
            return
        try:
            d = secp.read(path)
            if not units.valid(d["units"]):
                raise ValueError(f"The unit system '{d['units']}' of the file is not known here.")
            lf = units.length_factor(d["units"], self.tab.unit_name())
        except (OSError, ValueError, KeyError) as ex:
            QMessageBox.warning(self, "Import profile", str(ex))
            return
        A = d.get("area", d["A_w"])
        I = d.get("Ixx", d["I_w"])
        try:
            prof = pr1.imported(d.get("name", ""), A * lf ** 2, I * lf ** 4, d["c_top"] * lf, d["c_bottom"] * lf)
        except ValueError as ex:
            QMessageBox.warning(self, "Import profile", str(ex))
            return
        self.stored = prof
        if self.shape.findData("imported") < 0:
            self.shape.addItem("Imported / drawn section: " + prof["label"], "imported")
        self.shape.blockSignals(True)
        self.shape.setCurrentIndex(self.shape.findData("imported"))
        self.shape.blockSignals(False)
        self.build_form(None)
        self.recompute()

    def export_file(self):
        if not self.profile:
            QMessageBox.information(self, "Export", "There is no valid profile to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export profile properties", "profile" + secp.EXT, f"Profile properties (*{secp.EXT})")
        if not path:
            return
        pf = self.profile
        polys = pr1.drawing(pf)
        width = (max(x for poly, _ in polys for x, _ in poly) - min(x for poly, _ in polys for x, _ in poly)) if polys else 1.0
        props = {"area": pf["A"], "Ixx": pf["I"], "c_top": pf["c_top"], "c_bottom": pf["c_bottom"], "yc": pf["c_bottom"],
                 "S_top": pf["I"] / pf["c_top"], "S_bottom": pf["I"] / pf["c_bottom"]}
        try:
            secp.write(path, pf["label"], self.tab.unit_name(), self.U["L"], props, width if width > 0 else 1.0)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, "Export", str(ex))

    def tick_all(self, on):
        for i in range(self.member_list.count()):
            self.member_list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def tick_selected(self):
        sel = set(self.tab.selected_rows())
        for i in range(self.member_list.count()):
            self.member_list.item(i).setCheckState(Qt.CheckState.Checked if i in sel else Qt.CheckState.Unchecked)

    def tick_missing(self):
        for i in range(self.member_list.count()):
            self.member_list.item(i).setCheckState(Qt.CheckState.Checked if not self.tab.members[i]["profile"] else Qt.CheckState.Unchecked)

    def ticked(self):
        return [i for i in range(self.member_list.count()) if self.member_list.item(i).checkState() == Qt.CheckState.Checked]

    def accept_it(self):
        if self.profile is None:
            return
        self.rows = self.ticked()
        if not self.rows:
            QMessageBox.information(self, "Profile", "Tick at least one member to apply the profile to.")
            return
        self.accept()

    def clear_it(self):
        self.profile = None
        self.rows = self.ticked()
        if not self.rows:
            QMessageBox.information(self, "Profile", "Tick the members to remove the profile from.")
            return
        self.cleared = True
        self.accept()


class DistDialog(QDialog):
    """A uniform line load on the selected members.  After exec(): .frame ('global' | 'local'), .q1, .q2."""

    def __init__(self, tab, frame="global", q1=0.0, q2=-1.0):
        super().__init__(tab)
        self.setWindowTitle("Line load on the selected members")
        self.setMinimumWidth(460)
        u = tab.U()
        self.unit = f"{u['F']}/{u['L']}"
        self.frame, self.q1, self.q2 = frame, q1, q2
        lay = QVBoxLayout(self)
        lay.addWidget(self._note("A uniform load per length of member, applied to EACH selected member. For a pressure, enter "
                                 "pressure x the width of the strip the member carries (for example a purlin's spacing)."))
        self.combo = QComboBox()
        self.combo.addItem("Fixed directions: x and y", "global")
        self.combo.addItem("Along and across each member", "local")
        self.combo.setCurrentIndex(0 if frame == "global" else 1)
        lay.addWidget(self.combo)
        self.form = QFormLayout()
        self.e1, self.e2 = QLineEdit(f"{q1:g}"), QLineEdit(f"{q2:g}")
        self.l1, self.l2 = QLabel(), QLabel()
        self.form.addRow(self.l1, self.e1)
        self.form.addRow(self.l2, self.e2)
        lay.addLayout(self.form)
        self.hint = self._note("")
        lay.addWidget(self.hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept_it)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.combo.currentIndexChanged.connect(self.labels)
        self.labels()

    @staticmethod
    def _note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

    def labels(self, *_):
        if self.combo.currentData() == "global":
            self.l1.setText(f"qx, along global x ({self.unit})")
            self.l2.setText(f"qy, along global y ({self.unit})")
            self.hint.setText("Positive qy pushes up; negative qy pushes down (gravity, snow).")
        else:
            self.l1.setText(f"Along the member, from its first to its second point ({self.unit})")
            self.l2.setText(f"Across the member, toward its left as drawn from the first to the second point ({self.unit})")
            self.hint.setText("The arrow of the load is drawn on the member, so check its direction after adding.")

    def accept_it(self):
        try:
            self.q1, self.q2 = float(self.e1.text()), float(self.e2.text())
        except ValueError:
            QMessageBox.warning(self, "Line load", "Please enter plain numbers (for example 2.5 or -1e3).")
            return
        if self.q1 == 0 and self.q2 == 0:
            QMessageBox.warning(self, "Line load", "Both values are zero.")
            return
        self.frame = self.combo.currentData()
        self.accept()


class PressureDialog(QDialog):
    """Wind or snow on members, turned into a line load by the per-member depth.  After exec(): .values (the load's fields),
    .depth (a number to store on every target member, or None to keep each member's own) and .targets."""

    def __init__(self, tab, kind, targets, load=None):
        super().__init__(tab)
        self.tab = tab
        self.kind = kind
        self.targets = list(targets)
        self.depth = None
        self.values = None
        self.u = tab.U()
        self.unit = tab.cur_unit
        u = self.u
        ld = dict(load) if load else loads1d.default_load(kind, self.unit)
        self.setWindowTitle(("Wind" if kind == "wind" else "Snow") + " on the selected members")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        if kind == "wind":
            lay.addWidget(DistDialog._note("Plain physics: pressure p = 1/2 x air density x V^2 x Cp. Each member only feels the part of "
                                           "the wind that blows across it, and is pushed toward the side the wind comes from. "
                                           "There is no shielding: every selected member sees the full wind. Choose the members and Cp "
                                           "yourself (a flat plate facing the wind is about 1.0 to 1.3; use a negative Cp for suction)."))
        else:
            lay.addWidget(DistDialog._note("Plain physics: pressure p = snow density x g x snow height x shape factor, straight down. "
                                           "Snow lies on the horizontal projection of a member, so a sloped member carries p x depth x "
                                           "cos(slope) per length along it and a vertical member carries none."))
        form = QFormLayout()
        self.edits = {}
        if kind == "wind":
            rows = [("V", f"Wind speed ({u['V']})"), ("angle", "Direction the wind blows toward (degrees; 0 = +x, 90 = +y)"),
                    ("cp", "Pressure coefficient Cp"), ("rho", f"Air density ({u['rho']})")]
        else:
            rows = [("h", f"Snow height ({u['L']})"), ("wet", None), ("rho", f"Snow density ({u['rho']})"), ("shape", "Shape factor")]
        for key, label in rows:
            if key == "wet":
                self.wet = QComboBox()
                for nm, v in loads1d.SNOW_PRESETS:
                    self.wet.addItem(f"{nm}  ({v:g} kg/m3)", v)
                self.wet.addItem("Custom density", None)
                form.addRow("How wet is the snow", self.wet)
                continue
            e = QLineEdit(f"{ld[key]:.8g}")
            e.textChanged.connect(self.update_preview)
            self.edits[key] = e
            form.addRow(label, e)
        if kind == "snow":
            rho_si = units.density_to_si(ld["rho"], self.unit)
            k = next((i for i, (_, v) in enumerate(loads1d.SNOW_PRESETS) if abs(v - rho_si) <= 1e-6 * v), len(loads1d.SNOW_PRESETS))
            self.wet.setCurrentIndex(k)
            self.wet.currentIndexChanged.connect(self.wet_picked)
            self.edits["rho"].textEdited.connect(lambda _t: self.wet.setCurrentIndex(self.wet.count() - 1))
        depths = {tab.member_by_lid(t).get("depth") for t in self.targets if tab.member_by_lid(t)}
        common = next(iter(depths)) if len(depths) == 1 else None
        self.e_depth = QLineEdit("" if common is None else f"{common:.8g}")
        self.e_depth.setPlaceholderText("(keep each member's own depth)")
        self.e_depth.textChanged.connect(self.update_preview)
        form.addRow(f"In-plane depth of the strip each member carries ({u['L']})", self.e_depth)
        lay.addLayout(form)
        lay.addWidget(DistDialog._note("The depth is stored on each member (Depth column of the members table) and is only used by wind and "
                                       "snow loads. Leave it blank to keep the depths already in the table."))
        self.cb_sel = None
        if load is not None and tab.sel_lines():
            self.cb_sel = QCheckBox("Apply to the members now selected in the drawing instead")
            self.cb_sel.toggled.connect(self.update_preview)
            lay.addWidget(self.cb_sel)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(170)
        lay.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept_it)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.update_preview()

    def wet_picked(self, *_):
        v = self.wet.currentData()
        if v is not None:
            self.edits["rho"].setText(f"{units.density_from_si(v, self.unit):.8g}")

    def current_targets(self):
        if self.cb_sel is not None and self.cb_sel.isChecked():
            return self.tab.sel_lines()
        return self.targets

    def read(self):
        """-> (load dict, depth or None); raises ValueError with a readable message."""
        vals = {"kind": self.kind}
        for k, e in self.edits.items():
            try:
                vals[k] = float(e.text())
            except ValueError:
                raise ValueError("Please enter plain numbers in every box.")
        if self.kind == "wind" and (vals["V"] < 0 or vals["rho"] <= 0):
            raise ValueError("The wind speed cannot be negative and the air density must be positive.")
        if self.kind == "snow":
            if vals["h"] < 0 or vals["rho"] <= 0:
                raise ValueError("The snow height cannot be negative and the density must be positive.")
            vals["wet"] = self.wet.currentText().split("  (")[0] if self.wet.currentData() is not None else "Custom density"
        txt = self.e_depth.text().strip()
        depth = None
        if txt:
            try:
                depth = float(txt)
            except ValueError:
                raise ValueError("The depth must be a plain number.")
            if depth <= 0:
                raise ValueError("The depth must be greater than zero.")
        vals["targets"] = list(self.current_targets())
        return vals, depth

    def update_preview(self, *_):
        u = self.u
        try:
            vals, depth = self.read()
        except ValueError as ex:
            self.preview.setHtml(f"<span style='color:#b36b00'>{ex}</span>")
            return
        depths = {t: depth for t in vals["targets"]} if depth is not None else None
        p, rows = self.tab.pressure_calc(vals, depths)
        pa = loads1d.pressure(vals, self.unit)[1]
        h = []
        if self.kind == "wind":
            h.append(f"p = 1/2 x {vals['rho']:.5g} x {vals['V']:.5g}^2 x {vals['cp']:.4g} = <b>{p:.5g} {u['S']}</b> ({pa:.5g} Pa)")
        else:
            h.append(f"p = {vals['rho']:.5g} x g x {vals['h']:.5g} x {vals['shape']:.4g} = <b>{p:.5g} {u['S']}</b> ({pa:.5g} Pa)")
        h.append(f"Line load = pressure x depth x direction factor, in {u['F']}/{u['L']}:")
        h.append("<table cellspacing=4>")
        h.append("<tr><th align=left>Member</th><th>depth</th><th>factor</th><th>qx</th><th>qy</th></tr>")
        missing = False
        for r in rows:
            if r["vec"] is None:
                missing = True
                h.append(f"<tr><td>{r['name']}</td><td colspan=4 style='color:#b00020'>no depth: this member gets no load</td></tr>")
            else:
                h.append(f"<tr><td>{r['name']}</td><td>{r['depth']:.5g}</td><td>{r['factor']:.4g}</td><td>{r['vec'][0]:.5g}</td>"
                         f"<td>{r['vec'][1]:.5g}</td></tr>")
        h.append("</table>")
        if self.kind == "wind":
            h.append("factor = d|d| with d = (wind direction) . (member normal): 1 when the wind is square to the member, 0 when it runs along it.")
        else:
            h.append("factor = |cos| of the member's angle from horizontal (the horizontal projection).")
        if missing:
            h.append("<span style='color:#b00020'>Enter a depth above, or fill the Depth column of the members table.</span>")
        self.preview.setHtml("<br>".join(h))

    def accept_it(self):
        try:
            vals, depth = self.read()
        except ValueError as ex:
            QMessageBox.warning(self, "Pressure load", str(ex))
            return
        if not vals["targets"]:
            QMessageBox.warning(self, "Pressure load", "No members to apply it to.")
            return
        missing = [t for t in vals["targets"] if depth is None and (self.tab.member_by_lid(t) or {}).get("depth") is None]
        if missing:
            QMessageBox.warning(self, "Pressure load", "Some members have no depth yet. Enter the in-plane depth in the box above.")
            return
        self.values, self.depth, self.targets = vals, depth, vals.pop("targets")
        self.accept()
