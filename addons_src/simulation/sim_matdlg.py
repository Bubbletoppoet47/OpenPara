"""
sim_matdlg.py - the "Add a material" dialog and the delete question, shared by 1D FEA, 2D FEA and 3D FEA (the library is the same file,
materials.json; physics_materials has the reading and writing).

    add_material(parent, library, unit_system, prefill) -> the new material's name, or None (cancelled / refused)
    delete_material(parent, name, library)               -> True when it was deleted
"""
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox

import physics_materials as pm


def add_material(parent, library, unit_system, prefill):
    """`prefill`: {"E", "nu", "sy", "su", "eu"} as the strings now in the panel's boxes (in the stress unit of `unit_system`)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Add a material")
    form = QFormLayout(dlg)
    name = QLineEdit()
    E = QLineEdit(prefill.get("E", ""))
    unit = QComboBox()
    for u in pm.UNITS:
        unit.addItem(u)
    unit.setCurrentText(unit_system)
    nu = QLineEdit(prefill.get("nu", ""))
    SY, SU, EU = QLineEdit(prefill.get("sy", "")), QLineEdit(prefill.get("su", "")), QLineEdit(prefill.get("eu", ""))
    form.addRow("Name", name)
    form.addRow("E", E)
    form.addRow("E is in", unit)
    form.addRow("Poisson's ratio", nu)
    form.addRow("Yield strength (same unit, 0 = brittle)", SY)
    form.addRow("Ultimate strength (same unit)", SU)
    form.addRow("Plastic strain at ultimate (%)", EU)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    dlg.fields = {"name": name, "E": E, "unit": unit, "nu": nu, "sy": SY, "su": SU, "eu": EU}      # for tests
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    nm = name.text().strip()
    try:
        e_val, nu_val = float(E.text()), float(nu.text())
        sy_val, su_val = float(SY.text() or 0), float(SU.text() or 0)
        eu_val = float(EU.text()) / 100.0 if EU.text().strip() else None
    except ValueError:
        QMessageBox.warning(parent, "Add a material", "E, Poisson's ratio and the strengths must be numbers.")
        return None
    if not nm or e_val <= 0 or not (-1 < nu_val < 0.5 + 1e-12):
        QMessageBox.warning(parent, "Add a material", "Give a name, a positive E and -1 < nu < 0.5.")
        return None
    if any(x["name"].lower() == nm.lower() for x in library):
        QMessageBox.warning(parent, "Add a material", "A material with that name already exists.")
        return None
    lib = list(library) + [{"name": nm, "E_MPa": pm.to_mpa(e_val, unit.currentText()), "nu": nu_val,
                            "Sy_MPa": pm.to_mpa(max(sy_val, 0.0), unit.currentText()),
                            "Su_MPa": pm.to_mpa(max(su_val, 0.0), unit.currentText()),
                            **({"eps_u": eu_val} if eu_val is not None else {})}]
    try:
        pm.save(lib)
    except OSError as ex:
        QMessageBox.warning(parent, "Add a material", f"Could not write {pm.library_path()}:\n{ex}")
        return None
    return nm


def delete_material(parent, name, library):
    if name is None or name in {n for n, _, _ in pm.DEFAULTS}:
        return False
    if QMessageBox.question(parent, "Delete material", f"Delete '{name}' from materials.json?") != QMessageBox.StandardButton.Yes:
        return False
    try:
        pm.save([x for x in library if x["name"] != name])
    except OSError as ex:
        QMessageBox.warning(parent, "Delete material", f"Could not write {pm.library_path()}:\n{ex}")
        return False
    return True


def can_delete(name):
    """A material the user added (not one of the built-in ones, not 'custom values')."""
    return name is not None and name not in {n for n, _, _ in pm.DEFAULTS}
