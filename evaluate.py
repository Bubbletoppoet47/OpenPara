"""Evaluate tools: mass properties and measure.  Everything is computed in mm / kg and converted for display."""

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

MATERIALS = [("Steel (generic)", 7850.0), ("Stainless steel", 8000.0), ("Aluminum 6061", 2700.0), ("Titanium", 4430.0),
             ("Brass", 8500.0), ("Copper", 8960.0), ("Cast iron", 7200.0), ("ABS plastic", 1040.0), ("Nylon", 1150.0),
             ("Wood (pine)", 500.0), ("Water", 1000.0)]
LB = 2.2046226218
# name -> (length unit, mm per... length units per mm, mass unit, mass units per kg, density unit, density units per kg/m3)
UNITS = {
    "Metric (mm, g)": ("mm", 1.0, "g", 1000.0, "g/cm3", 1e-3),
    "Metric (m, kg)": ("m", 1e-3, "kg", 1.0, "kg/m3", 1.0),
    "US (in, lb)": ("in", 1 / 25.4, "lb", LB, "lb/in3", LB * 0.0254 ** 3),
}


def mass_properties(solid, density):
    """dict of volume (mm3), area (mm2), com (mm), mass (kg), inertia about the centre of mass and about the origin (kg mm2),
    principal moments / axes.  density in kg/m3."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, g)
    vol = g.Mass()
    c = g.CentreOfMass()
    com = np.array([c.X(), c.Y(), c.Z()])
    M = g.MatrixOfInertia()
    unit_i = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])          # mm5, about the centre of mass
    s = GProp_GProps()
    BRepGProp.SurfaceProperties_s(solid.wrapped, s)
    rho = density * 1e-9                                                                  # kg per mm3
    mass = vol * rho
    ic = unit_i * rho
    io = ic + mass * (float(com @ com) * np.eye(3) - np.outer(com, com))
    w, v = np.linalg.eigh(ic)
    return {"volume": vol, "area": s.Mass(), "com": com, "mass": mass, "ic": ic, "io": io, "pm": w, "axes": v.T}


def mass_text(name, props, system, density):
    lu, lf, mu, mf, du, df = UNITS[system]
    L, Mf = lf, mf
    p = props
    f = lambda x: f"{x:.5f}"
    ic, io = p["ic"] * Mf * L * L, p["io"] * Mf * L * L
    o = [f"Mass properties of {name}", "    Coordinate system: -- default --", "",
         f"Density = {f(density * df)} {du}", "",
         f"Mass = {f(p['mass'] * Mf)} {mu}", "",
         f"Volume = {f(p['volume'] * L ** 3)} cubic {lu}", "",
         f"Surface area = {f(p['area'] * L ** 2)} square {lu}", "",
         f"Center of mass: ( {lu} )"]
    o += [f"     {a} = {f(x * L)}" for a, x in zip("XYZ", p["com"])]
    o += ["", f"Principal axes of inertia and principal moments of inertia: ( {mu} * square {lu} )", "Taken at the center of mass."]
    for k, a in enumerate(("Ix", "Iy", "Iz")):
        ax = p["axes"][k]
        o.append(f"     {a} = ( {ax[0]:.5f}, {ax[1]:.5f}, {ax[2]:.5f} )      P{a[1]} = {f(p['pm'][k] * Mf * L * L)}")
    for title, T, tag in ((f"Moments of inertia: ( {mu} * square {lu} )\nTaken at the center of mass and aligned with the output coordinate system. (Using positive tensor notation.)", ic, "L"),
                          (f"Moments of inertia: ( {mu} * square {lu} )\nTaken at the output coordinate system. (Using positive tensor notation.)", io, "I")):
        o += ["", title]
        for i, a in enumerate("xyz"):
            o.append("     " + "      ".join(f"{tag}{a}{b} = {f(T[i, j])}" for j, b in enumerate("xyz")))
    return "\n".join(o)


class MassDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Mass Properties")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.mat = QComboBox()
        for n, d in MATERIALS:
            self.mat.addItem(f"{n}   ({d:g} kg/m3)", (n, d))
        self.mat.addItem("Custom", ("Custom", None))
        self.units = QComboBox()
        self.units.addItems(list(UNITS))
        self.units.setCurrentText(app.mass_units)
        self.dens = QLineEdit()
        self.dlabel = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.dens)
        row.addWidget(self.dlabel)
        form.addRow("Material", self.mat)
        form.addRow("Density", row)
        form.addRow("Units", self.units)
        lay.addLayout(form)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 9))
        self.out.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        b = QPushButton("Recalculate")
        b.clicked.connect(self.refresh)
        row.addWidget(b)
        b = QPushButton("Copy to Clipboard")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        row.addWidget(b)
        lay.addLayout(row)
        mat = app.doc.material
        idx = next((i for i, (n, d) in enumerate(MATERIALS) if n == mat.get("name")), len(MATERIALS))
        self.mat.setCurrentIndex(idx)
        self.mat.currentIndexChanged.connect(self.pick_material)
        self.units.currentTextChanged.connect(self.change_units)
        self.dens.editingFinished.connect(self.typed_density)
        self.show_density()
        self.refresh()

    def show_density(self):
        u = UNITS[self.units.currentText()]
        self.dens.setText(f"{self.app.doc.material['density'] * u[5]:.6g}")
        self.dlabel.setText(u[4])

    def pick_material(self, _i):
        n, d = self.mat.currentData()
        if d is not None:
            import mat_lib
            self.app.doc.material = mat_lib.material_dict(mat_lib.find(n)) if mat_lib.find(n) else {"name": n, "density": d}
            self.show_density()
        else:
            self.app.doc.material = dict(self.app.doc.material, name="Custom")
        self.app.refresh_tree()
        self.refresh()

    def typed_density(self):
        try:
            v = float(self.dens.text()) / UNITS[self.units.currentText()][5]
            if v <= 0:
                raise ValueError
        except ValueError:
            self.show_density()
            return
        self.app.doc.material = dict(self.app.doc.material, name="Custom", density=v)
        self.mat.blockSignals(True)
        self.mat.setCurrentIndex(len(MATERIALS))
        self.mat.blockSignals(False)
        self.app.refresh_tree()
        self.refresh()

    def change_units(self, name):
        self.app.mass_units = name
        self.show_density()
        self.refresh()

    def refresh(self):
        solid = self.app.shown_solid()
        if solid is None:
            self.out.setPlainText("There is no solid yet.")
            return
        try:
            p = mass_properties(solid, self.app.doc.material["density"])
            self.out.setPlainText(mass_text("Part", p, self.units.currentText(), self.app.doc.material["density"]))
        except Exception as ex:
            self.out.setPlainText(f"Could not compute the mass properties: {ex}")


# ---------------------------------------------------------------------------------------------- measure
def item_center(it):
    s = it["shape"]
    try:
        if it["kind"] == "edge" and s.geom_type.name == "CIRCLE":
            c = s.arc_center
            return np.array([c.X, c.Y, c.Z])
    except Exception:
        pass
    c = s.center()
    return np.array([c.X, c.Y, c.Z])


def item_points(it):
    s, k = it["shape"], it["kind"]
    if k == "vertex":
        return np.array([item_center(it)])
    if k == "edge":
        return np.array([tuple(s.position_at(t)) for t in np.linspace(0, 1, 60)])
    pts = [tuple(v.center()) for v in s.vertices()]
    try:
        vs, _t = s.tessellate(0.2)
        pts += [tuple(v) for v in vs]
    except Exception:
        pass
    return np.array(pts[:3000])


def describe(it, L, lu):
    s, k = it["shape"], it["kind"]
    if k == "vertex":
        c = item_center(it)
        return f"Point   X = {c[0] * L:.4f}   Y = {c[1] * L:.4f}   Z = {c[2] * L:.4f} {lu}"
    if k == "edge":
        t = f"Edge   length = {s.length * L:.4f} {lu}"
        try:
            if s.geom_type.name == "CIRCLE":
                t += f"   radius = {s.radius * L:.4f}   diameter = {2 * s.radius * L:.4f} {lu}"
        except Exception:
            pass
        return t
    t = f"Face   area = {s.area * L * L:.4f} {lu}2"
    try:
        if s.geom_type.name in ("CYLINDER", "SPHERE", "CONE"):
            t += f"   radius = {s.radius * L:.4f} {lu}"
    except Exception:
        pass
    return t


def measure_report(items, opts, unit):
    """(text, [(p, q) segments to draw])  for the picked items; opts = dict(xyz, cc, mn, mx)."""
    L = 1.0 if unit == "mm" else 1 / 25.4
    lu = unit
    if not items:
        return "Click a point, an edge or a face in the view.\nClick a second item to measure between them.", []
    lines = [f"{n + 1}:  " + describe(it, L, lu) for n, it in enumerate(items)]
    segs = []
    if len(items) == 2:
        a, b = items

        def show(label, p, q):
            d = np.array(q) - np.array(p)
            segs.append((np.array(p), np.array(q)))
            lines.append("")
            lines.append(f"{label}:  {np.linalg.norm(d) * L:.4f} {lu}")
            if opts["xyz"]:
                lines.append(f"      dX = {d[0] * L:.4f}   dY = {d[1] * L:.4f}   dZ = {d[2] * L:.4f} {lu}")
        any_mode = opts["mn"] or opts["mx"] or opts["cc"]
        if not any_mode:
            lines += ["", "Turn on Minimum, Maximum or Center to center distance."]
        if opts["cc"]:
            show("Center to center", item_center(a), item_center(b))
        if opts["mn"]:
            try:
                _d, p, q = a["shape"].distance_to_with_closest_points(b["shape"])
                show("Minimum distance", tuple(p), tuple(q))
            except Exception as ex:
                lines.append(f"\nMinimum distance failed: {ex}")
        if opts["mx"]:
            pa, pb = item_points(a), item_points(b)
            dm = np.linalg.norm(pa[:, None, :] - pb[None, :, :], axis=2)
            i, j = np.unravel_index(int(np.argmax(dm)), dm.shape)
            show("Maximum distance", pa[i], pb[j])
            lines.append("      (found from points sampled along the shapes)")
    return "\n".join(lines), segs


class MeasurePanel(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Measure")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.resize(430, 300)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.unit = QComboBox()
        self.unit.addItems(["mm", "in"])
        self.unit.setCurrentText(app.measure_unit)
        self.unit.setToolTip("Units shown")
        row.addWidget(QLabel("Units"))
        row.addWidget(self.unit)
        self.opt = {}
        for key, text, tip, on in (("xyz", "XYZ", "Also show the X, Y and Z differences", True),
                                   ("mn", "Minimum", "Minimum distance between the two items", True),
                                   ("cc", "Center to center", "Between the centers (arc / circle centers, face centers, midpoints)", False),
                                   ("mx", "Maximum", "Maximum distance between the two items", False)):
            c = QCheckBox(text)
            c.setChecked(on)
            c.setToolTip(tip)
            c.toggled.connect(self.changed)
            self.opt[key] = c
            row.addWidget(c)
        row.addStretch(1)
        lay.addLayout(row)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 10))
        lay.addWidget(self.out, 1)
        b = QPushButton("Clear selection")
        b.clicked.connect(app.measure_clear)
        lay.addWidget(b)
        self.unit.currentTextChanged.connect(self.changed)

    def options(self):
        return {k: c.isChecked() for k, c in self.opt.items()}

    def changed(self, *_a):
        self.app.measure_unit = self.unit.currentText()
        self.app.measure_update()

    def closeEvent(self, e):
        self.app.measure_stop()
        super().closeEvent(e)
