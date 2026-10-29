"""
mat_lib.py - the material of a part: a library (typical textbook values, plus your own) and the Edit Material dialog.

A part's material is a small dict kept in the part file:
    {"name", "density" (kg/m3), "E_MPa", "nu", "Sy_MPa", "Su_MPa"}
The last four may be missing (e.g. water): the simulations then ask you to type the values.  The same values feed the mass
properties (density) and the 1D / 2D simulations (E, nu, yield, ultimate) - a simulation takes them from the part by itself.

Your own materials are stored in gpd_materials.json next to the program.  The built-in ones cannot be changed or deleted.
"""
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QVBoxLayout)

# name, density kg/m3, E MPa, nu, yield MPa (0 = brittle), ultimate MPa   -  typical values, check your own source
BUILTIN = [
    ("Steel (generic)", 7850.0, 200000.0, 0.30, 250.0, 400.0),
    ("Structural steel (A36)", 7850.0, 200000.0, 0.26, 250.0, 400.0),
    ("Steel AISI 1018", 7870.0, 205000.0, 0.29, 370.0, 440.0),
    ("Stainless steel", 8000.0, 193000.0, 0.29, 215.0, 505.0),
    ("Stainless steel 316", 8000.0, 193000.0, 0.30, 205.0, 515.0),
    ("Aluminum 6061", 2700.0, 68900.0, 0.33, 276.0, 310.0),
    ("Aluminum 7075-T6", 2810.0, 71700.0, 0.33, 503.0, 572.0),
    ("Aluminum 2024-T3", 2780.0, 73100.0, 0.33, 345.0, 483.0),
    ("Titanium", 4430.0, 113800.0, 0.342, 880.0, 950.0),
    ("Brass", 8500.0, 110000.0, 0.34, 125.0, 340.0),
    ("Copper", 8960.0, 117000.0, 0.34, 70.0, 220.0),
    ("Cast iron", 7200.0, 110000.0, 0.26, 0.0, 200.0),
    ("Magnesium AZ31B", 1770.0, 45000.0, 0.35, 200.0, 260.0),
    ("Nickel alloy (Inconel 718)", 8190.0, 200000.0, 0.29, 1030.0, 1240.0),
    ("ABS plastic", 1040.0, 2300.0, 0.35, 40.0, 40.0),
    ("Nylon", 1150.0, 2900.0, 0.39, 70.0, 80.0),
    ("Wood (pine)", 500.0, None, None, None, None),
    ("Water", 1000.0, None, None, None, None),
]
KEYS = ("name", "density", "E_MPa", "nu", "Sy_MPa", "Su_MPa")


def _entry(t):
    return dict(zip(KEYS, t))


def user_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpd_materials.json")


def user_materials():
    try:
        with open(user_path(), "r", encoding="utf-8") as fh:
            return [{k: m.get(k) for k in KEYS} for m in json.load(fh).get("materials", []) if m.get("name") and m.get("density")]
    except Exception:
        return []


def save_user(mats):
    with open(user_path(), "w", encoding="utf-8") as fh:
        json.dump({"materials": mats}, fh, indent=2)


def builtin_names():
    return {t[0] for t in BUILTIN}


def library():
    """Built-in materials, then your own (a name you reused replaces the built-in one of that name)."""
    out = {t[0]: _entry(t) for t in BUILTIN}
    for m in user_materials():
        out[m["name"]] = m
    return list(out.values())


def find(name):
    return next((m for m in library() if m["name"] == name), None)


def material_dict(m):
    """A copy of a library entry as the dict stored in a part (keys with no value are left out)."""
    return {k: m[k] for k in KEYS if m.get(k) is not None}


def default_material():
    return material_dict(find("Steel (generic)"))


def elastic(mat):
    """(E_MPa, nu, Sy_MPa, Su_MPa) of a part material, or None when it has no elastic properties."""
    if not mat or mat.get("E_MPa") is None or mat.get("nu") is None:
        return None
    return float(mat["E_MPa"]), float(mat["nu"]), float(mat.get("Sy_MPa") or 0.0), float(mat.get("Su_MPa") or 0.0)


def with_elastic(mat):
    """The material with elastic values filled in from the library when it has none but its name is known (old files)."""
    if mat is None:
        return default_material()
    if mat.get("E_MPa") is None:
        m = find(mat.get("name"))
        if m is not None and m.get("E_MPa") is not None:
            out = dict(mat)
            out.update({k: m[k] for k in KEYS[2:] if m.get(k) is not None})
            return out
    return mat


def summary(mat):
    mat = mat or {}
    e = elastic(mat)
    t = f"{mat.get('name', '?')}:  {mat.get('density', 0):g} kg/m3"
    if e:
        t += f",  E {e[0]:g} MPa,  nu {e[1]:g},  yield {e[2]:g} MPa,  ultimate {e[3]:g} MPa"
    else:
        t += ",  no elastic properties"
    return t


class MaterialDialog(QDialog):
    """Edit Material: pick from the library or type your own values.  result_material() is the dict to store in the part."""

    def __init__(self, parent, current):
        super().__init__(parent)
        self.setWindowTitle("Edit Material")
        self.setMinimumSize(720, 430)
        self.cur = dict(with_elastic(current))
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("Library"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("search...")
        self.search.textChanged.connect(self.fill)
        left.addWidget(self.search)
        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self.picked)
        left.addWidget(self.lst, 1)
        root.addLayout(left, 1)
        right = QVBoxLayout()
        form = QFormLayout()
        self.f = {}
        for key, label in (("name", "Name"), ("density", "Density (kg/m3)"), ("E_MPa", "Young's modulus E (MPa)"), ("nu", "Poisson's ratio"),
                           ("Sy_MPa", "Yield strength (MPa, 0 = brittle)"), ("Su_MPa", "Ultimate strength (MPa)")):
            e = QLineEdit()
            self.f[key] = e
            form.addRow(label, e)
        right.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#707070;")
        right.addWidget(self.note)
        right.addStretch(1)
        row = QHBoxLayout()
        self.b_save = QPushButton("Save to library")
        self.b_save.setToolTip("Keeps these values under this name in your own library (gpd_materials.json).")
        self.b_save.clicked.connect(self.save_lib)
        self.b_del = QPushButton("Delete from library")
        self.b_del.clicked.connect(self.del_lib)
        row.addWidget(self.b_save)
        row.addWidget(self.b_del)
        right.addLayout(row)
        row = QHBoxLayout()
        ok = QPushButton("Apply to this part")
        ok.setDefault(True)
        ok.clicked.connect(self.accept_it)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        right.addLayout(row)
        root.addLayout(right, 2)
        self.out = None
        self.fill()
        self.show_values(self.cur)
        self.select_name(self.cur.get("name"))

    # ------------------------------------------------------------------ library list
    def fill(self, *_):
        q = self.search.text().strip().lower()
        keep = self.lst.currentItem().data(Qt.ItemDataRole.UserRole) if self.lst.currentItem() else None
        self.lst.blockSignals(True)
        self.lst.clear()
        bn = builtin_names()
        for m in library():
            if q and q not in m["name"].lower():
                continue
            it = QListWidgetItem(m["name"] + ("" if m["name"] in bn else "   (mine)"))
            it.setData(Qt.ItemDataRole.UserRole, m["name"])
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        if keep:
            self.select_name(keep)
        self.update_buttons()

    def select_name(self, name):
        for i in range(self.lst.count()):
            if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.lst.blockSignals(True)
                self.lst.setCurrentRow(i)
                self.lst.blockSignals(False)
                break
        self.update_buttons()

    def picked(self, _row):
        it = self.lst.currentItem()
        if it is None:
            return
        m = find(it.data(Qt.ItemDataRole.UserRole))
        if m is not None:
            self.show_values(m)
        self.update_buttons()

    def update_buttons(self):
        it = self.lst.currentItem()
        name = it.data(Qt.ItemDataRole.UserRole) if it else None
        self.b_del.setEnabled(name is not None and name in {m["name"] for m in user_materials()})
        typed = self.f["name"].text().strip()
        self.note.setText("Typical values: check them against your own source. A simulation takes E, nu and the strengths from the part "
                          "by itself (you can still type other values there)." + ("" if typed not in builtin_names() else
                          "  Built-in materials cannot be changed: change a value and use another name to keep it."))

    def show_values(self, m):
        for k, e in self.f.items():
            v = m.get(k)
            e.setText("" if v is None else (str(v) if k == "name" else f"{v:g}"))

    # ------------------------------------------------------------------ read / save
    def read(self):
        name = self.f["name"].text().strip()
        if not name:
            raise ValueError("Give the material a name.")

        def num(key, label, required=False, lo=None):
            t = self.f[key].text().strip()
            if not t:
                if required:
                    raise ValueError(f"{label} is needed.")
                return None
            try:
                v = float(t)
            except ValueError:
                raise ValueError(f"{label} must be a number.")
            if lo is not None and v <= lo:
                raise ValueError(f"{label} must be greater than {lo:g}.")
            return v
        dens = num("density", "Density", True, 0.0)
        E = num("E_MPa", "E", False, 0.0)
        nu = num("nu", "Poisson's ratio")
        sy, su = num("Sy_MPa", "Yield strength"), num("Su_MPa", "Ultimate strength")
        if (E is None) != (nu is None):
            raise ValueError("Give both E and Poisson's ratio, or neither.")
        if nu is not None and not (-1.0 < nu < 0.5):
            raise ValueError("Poisson's ratio must be between -1 and 0.5.")
        if E is not None and (sy is None or su is None):
            sy = 0.0 if sy is None else sy
            su = 0.0 if su is None else su
        if sy and su and su < sy:
            raise ValueError("The ultimate strength cannot be smaller than the yield strength.")
        return {"name": name, "density": dens, "E_MPa": E, "nu": nu, "Sy_MPa": sy, "Su_MPa": su}

    def save_lib(self):
        try:
            m = self.read()
        except ValueError as ex:
            QMessageBox.warning(self, "Material", str(ex))
            return
        if m["name"] in builtin_names():
            QMessageBox.warning(self, "Material", "That name belongs to a built-in material. Use another name to keep your values.")
            return
        mats = [x for x in user_materials() if x["name"] != m["name"]] + [m]
        try:
            save_user(mats)
        except OSError as ex:
            QMessageBox.warning(self, "Material", f"Could not write the library: {ex}")
            return
        self.fill()
        self.select_name(m["name"])

    def del_lib(self):
        it = self.lst.currentItem()
        if it is None:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        if name not in {m["name"] for m in user_materials()}:
            return
        if QMessageBox.question(self, "Material", f"Delete '{name}' from your library?") != QMessageBox.StandardButton.Yes:
            return
        save_user([m for m in user_materials() if m["name"] != name])
        self.fill()

    def accept_it(self):
        try:
            self.out = material_dict(self.read())
        except ValueError as ex:
            QMessageBox.warning(self, "Material", str(ex))
            return
        self.accept()

    def result_material(self):
        return self.out
