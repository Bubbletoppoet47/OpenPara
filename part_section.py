"""
part_section.py - Evaluate > Section Properties in the part window: cut the part with a plane (Front, Top, Right, a reference plane, or a flat face
clicked in the view) and read the area, centroid and second moments of area ("area moment of inertia") of the cut.  The numbers come from
solid_section.py; this file is the window, the picking and the drawing.  The methods are attached to pm_app.MainWindow by install().

    section_open()                 the Evaluate button: opens (or re-opens) the window
    section_face_clicked()         a flat face was clicked in the view while the window is open: the cut becomes that face
    draw_section(pl, pv)           the cut, its centroid and its axes in the view (the part is drawn see-through while the window is open)
"""
import os

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from build123d import Plane

import evaluate
import pm_model as pm
import solid_section as sp
import unitctl

FILL_COL = (1.0, 0.66, 0.25)
LINE_COL = (0.80, 0.28, 0.0)
X_COL = (0.85, 0.18, 0.18)
Y_COL = (0.15, 0.62, 0.25)
FACE = "Clicked face"
SEE_THROUGH = 0.35                                          # the opacity of the part while the window is open, so the cut can be seen inside it
HINT = "Choose a plane, or click a flat face of the part in the view."


class SectionDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.result = None                                  # what the view draws: {"props", "outline", "fill"} of the last good cut
        self.solid = None                                   # the solid that result belongs to
        self.face_ref = None                                # the clicked face, as the part keeps references to faces: {"c", "n"}
        self.off_mm = 0.0
        self.setWindowTitle("Section Properties")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(700, 720)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.plane = QComboBox()
        self.fill_planes()
        self.offset = QDoubleSpinBox()
        self.offset.setDecimals(4)
        self.offset.setRange(-1e7, 1e7)
        self.offset.setKeyboardTracking(False)
        self.offset_label = QLabel()
        form.addRow("Cut with", self.plane)
        form.addRow(self.offset_label, self.offset)
        lay.addLayout(form)
        self.hint = QLabel(HINT)
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 9))
        self.out.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        b = QPushButton("Recalculate")
        b.clicked.connect(lambda: self.refresh())
        row.addWidget(b)
        b = QPushButton("Copy to Clipboard")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        row.addWidget(b)
        lay.addLayout(row)
        sf = app.sel_face
        if sf is not None and sf.get("ref") is not None:    # a flat face is already selected: measure it
            self.face_ref = sf["ref"]
            self.plane.setCurrentIndex(self.plane.findText(FACE))
        else:
            self.plane.setCurrentIndex(self.plane.findText("Top"))
        self.set_labels()
        self.plane.currentIndexChanged.connect(self.plane_changed)
        self.offset.valueChanged.connect(self.offset_changed)
        self.refresh(draw=False)

    # ------------------------------------------------------------------ the choices
    def fill_planes(self):
        d = self.app.doc
        self.plane.blockSignals(True)
        self.plane.clear()
        for nm in ("Front", "Top", "Right"):
            self.plane.addItem(nm, {"base": nm})
        for f in d.features:
            if f["kind"] == "refplane" and not f.get("suppressed"):
                self.plane.addItem(f["name"], {"ref": f["id"]})
        self.plane.addItem(FACE, {"face": True})
        self.plane.blockSignals(False)

    def is_face(self):
        return "face" in (self.plane.currentData() or {})

    def set_labels(self):
        lu = unitctl.length_unit()
        self.offset.blockSignals(True)
        self.offset.setSuffix(" " + lu)
        self.offset.setSingleStep(unitctl.to_disp(1.0))
        self.offset.setValue(unitctl.to_disp(self.off_mm))
        self.offset.blockSignals(False)
        if self.is_face():
            self.offset_label.setText("Distance into the part")
            self.offset.setToolTip("0 measures the clicked face itself; a positive distance cuts the part that far inside it, parallel to the face.")
        else:
            spec = self.plane.currentData() or {}
            try:
                pl = pm.BASE_PLANES[spec["base"]] if "base" in spec else self.app.doc.ref_plane(spec["ref"])
                self.offset_label.setText(f"Offset along model {sp.axis_name(np.array(tuple(pl.z_dir)))}")
            except Exception:
                self.offset_label.setText("Offset")
            self.offset.setToolTip("Moves the cut along the plane's normal (the direction named on the left).")

    def plane_changed(self, _i):
        if self.is_face() and self.face_ref is None:
            sf = self.app.sel_face
            if sf is not None and sf.get("ref") is not None:
                self.face_ref = sf["ref"]
        self.set_labels()
        self.refresh()

    def offset_changed(self, v):
        self.off_mm = unitctl.from_disp(float(v))
        self.refresh()

    def units_changed(self):
        self.set_labels()
        self.refresh()

    def use_clicked_face(self, draw=True):
        """The window is open and a face was clicked in the view."""
        sf = self.app.sel_face
        if sf is None:
            return
        if sf.get("ref") is None:
            self.note("That face is curved. Section Properties needs a flat face: click a flat one, or choose a plane.", bad=True)
            return
        self.face_ref = sf["ref"]
        self.off_mm = 0.0
        self.plane.blockSignals(True)
        self.plane.setCurrentIndex(self.plane.findText(FACE))
        self.plane.blockSignals(False)
        self.set_labels()
        self.refresh(draw=draw)

    def note(self, text, bad=False):
        self.hint.setText(text)
        self.hint.setStyleSheet("color: #b3261e;" if bad else "")

    # ------------------------------------------------------------------ the cut
    def build_cut(self, solid):
        """-> (plane, face or None, label) for what is chosen; raises SectionError."""
        spec = self.plane.currentData() or {}
        name = self.plane.currentText()
        lu = unitctl.length_unit()
        shown = f"{self.offset.value():g} {lu}"
        if "base" in spec or "ref" in spec:
            try:
                pl = pm.BASE_PLANES[spec["base"]] if "base" in spec else self.app.doc.ref_plane(spec["ref"])
            except Exception as e:
                raise sp.SectionError(f"The plane {name} cannot be used: {e}")
            plane = pl.offset(self.off_mm) if abs(self.off_mm) > 1e-12 else pl
            what = "plane" if "base" in spec else "reference plane"
            return plane, None, f"{name} {what}" + (f", offset {shown}" if abs(self.off_mm) > 1e-12 else "")
        if self.face_ref is None:
            raise sp.SectionError("Click a flat face of the part in the view to measure it.")
        try:
            face = pm.Document.resolve_face(self.face_ref, solid)
        except Exception:
            raise sp.SectionError("The face you clicked is no longer on the part. Click a flat face again.")
        plane = Plane(face)
        nm = sp.axis_name(np.array(tuple(plane.z_dir)))
        if abs(self.off_mm) > 1e-12:
            return plane.offset(-self.off_mm), None, f"a plane {shown} into the part from the clicked face (face normal model {nm})"
        return plane, face, f"the clicked face itself (a flat face, normal model {nm})"

    def part_name(self):
        try:
            return os.path.splitext(self.app.title())[0]
        except Exception:
            return "Part"

    def refresh(self, draw=True):
        solid = self.app.shown_solid()
        self.solid = solid
        self.result = None
        if solid is None:
            self.out.setPlainText("There is no solid yet.")
        else:
            try:
                plane, face, label = self.build_cut(solid)
                faces, warn = sp.cut(solid, plane, face)
                props = sp.properties(faces, plane)
                lu, lf = evaluate.unit_tuple(evaluate.GLOBAL)[:2]
                self.out.setPlainText(sp.report(self.part_name(), label, props, lu, lf, warn))
                self.result = {"props": props, "outline": sp.outline(faces), "fill": sp.fill(faces)}
                self.note(HINT)
            except sp.SectionError as e:
                self.out.setPlainText(str(e))
            except Exception as e:
                self.out.setPlainText(f"The section could not be measured: {e}")
        if draw:
            self.app.draw()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        try:
            self.app.draw()                                  # the cut goes from the view and the part is solid again
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------------- methods of the part window
def section_open(self):
    self.ensure_built()
    if self.doc.solid is None:
        self.say("Make a solid first.")
        return
    if self.ed is not None and self.ed.active:
        self.say("Leave the sketch first.")
        return
    if self.measuring:
        self.measure_stop()                                  # (clicking a face picks for Measure while it is on)
    if self.section_dialog is not None:
        self.section_dialog.close()
    self.section_dialog = SectionDialog(self)
    self.section_dialog.show()
    self.draw()
    self.say("Section Properties: choose a plane, or click a flat face of the part.")


def section_open_now(self):
    d = getattr(self, "section_dialog", None)
    return d is not None and d.isVisible()


def section_face_clicked(self):
    """(the click's own redraw follows, so the window only measures)"""
    if self.section_open_now():
        self.section_dialog.use_clicked_face(draw=False)


def draw_section(self, pl, pv):
    """The cut (filled), its outline, the centroid and the section's X and Y axes through it."""
    if not self.section_open_now():
        return
    dlg = self.section_dialog
    try:
        solid = self.shown_solid()
        if dlg.solid is not solid:                           # the part was changed while the window is open: measure it again
            dlg.refresh(draw=False)
        r = dlg.result
        if r is None or solid is None:
            return
        verts, tris = r["fill"]
        if len(tris):
            m = pv.PolyData(verts, np.hstack([np.full((len(tris), 1), 3), tris]).ravel())
            a = pl.add_mesh(m, color=FILL_COL, lighting=False, pickable=False, reset_camera=False)
            try:
                mp = a.GetMapper()
                mp.SetResolveCoincidentTopologyToPolygonOffset()
                mp.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2.0, -2.0)
            except Exception:
                pass
        ml = self.merged_lines(r["outline"])
        if ml is not None:
            a = pl.add_mesh(ml, color=LINE_COL, line_width=4, pickable=False, reset_camera=False)
            try:
                mp = a.GetMapper()
                mp.SetResolveCoincidentTopologyToPolygonOffset()
                mp.SetRelativeCoincidentTopologyPolygonOffsetParameters(-4.0, -4.0)
            except Exception:
                pass
        p = r["props"]
        fr = p["frame"]
        c3 = np.asarray(p["c3"], float)
        bb = solid.bounding_box()
        reach = 0.22 * max(bb.size.X, bb.size.Y, bb.size.Z, 1e-6)
        for vec, col in ((fr["u"], X_COL), (fr["v"], Y_COL)):
            seg = self.merged_lines([np.array([c3 - reach * vec, c3 + reach * vec])])
            if seg is not None:
                pl.add_mesh(seg, color=col, line_width=3, pickable=False, reset_camera=False)
        pl.add_mesh(pv.PolyData(np.array([c3])), color=LINE_COL, point_size=12, render_points_as_spheres=True, pickable=False, reset_camera=False)
    except Exception:
        pass                                                 # (a failed overlay never spoils the picture of the part)


def install(cls):
    for fn in (section_open, section_open_now, section_face_clicked, draw_section):
        setattr(cls, fn.__name__, fn)
