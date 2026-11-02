"""The File > Export dialog, and the File > Import STEP flow (Qt side of exchange.py)."""
import os

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QLabel, QMessageBox, QVBoxLayout)

import exchange as ex
import settings
import unitctl


class ExportDialog(QDialog):
    def __init__(self, parent, is_asm):
        super().__init__(parent)
        self.setWindowTitle("Export")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)
        self.fmt = QComboBox()
        self.fmt.addItems(["STEP (exact solid, .step)", "STL (triangle mesh, .stl)"])
        form.addRow("Format", self.fmt)
        self.fuse = QCheckBox("Fuse everything into one solid")
        self.each = QCheckBox("One STL file per component (into a folder)")
        self.tol = QDoubleSpinBox()
        self.tol.setDecimals(5)
        self.tol.setRange(unitctl.to_disp(0.0005), unitctl.to_disp(5.0))            # shown in the program's unit (File > Units); the exporter gets mm
        self.tol.setSingleStep(unitctl.to_disp(0.005))
        self.tol.setValue(unitctl.to_disp(float(settings.get("surf_gap")) / 2.5 if settings.get("surf_gap") else 0.02))
        self.tol.setSuffix(" " + unitctl.length_unit())
        self.tol.setToolTip("How far the mesh may lie from the true surface. Smaller = finer mesh, bigger file.")
        self.ang = QDoubleSpinBox()
        self.ang.setDecimals(2)
        self.ang.setRange(0.02, 1.0)
        self.ang.setSingleStep(0.05)
        self.ang.setValue(0.2)
        self.ang.setSuffix(" rad")
        self.ang.setToolTip("The largest turn between neighbouring facets of a curved surface.")
        if is_asm:
            form.addRow(self.fuse)
            form.addRow(self.each)
        form.addRow("STL: surface tolerance", self.tol)
        form.addRow("STL: angle between facets", self.ang)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fmt.currentIndexChanged.connect(self.sync)
        self.sync()
        if not is_asm:
            self.fuse.hide()
            self.each.hide()

    def sync(self, *_a):
        step = self.fmt.currentIndex() == 0
        self.fuse.setEnabled(step)
        self.each.setEnabled(not step)
        self.tol.setEnabled(not step)
        self.ang.setEnabled(not step)
        self.note.setText("STEP keeps the exact geometry; an assembly is written as separate named solids in their assembled positions." if step
                          else "STL is a mesh in mm; an assembly is written as one combined mesh in its assembled pose.")

    def values(self):
        return {"step": self.fmt.currentIndex() == 0, "fuse": self.fuse.isChecked(), "each": self.each.isChecked(), "tol": unitctl.from_disp(self.tol.value()), "ang": self.ang.value()}


def export_items(win):
    """[(name, solid placed in the world)], whether it is an assembly, and a default file name - for the current tab (None if it is not a part or assembly)."""
    if hasattr(win, "asm") and hasattr(win, "solid_of"):
        items = []
        for c in win.asm.components:
            if c.get("hidden") or c.get("suppressed"):
                continue
            s = win.solid_of(c)
            if s is not None:
                items.append((c["name"], ex.place(s, win.asm.T4(c))))
        base = os.path.splitext(win.title())[0]
        return items, True, base
    if hasattr(win, "doc") and hasattr(win.doc, "solid"):
        return [(os.path.splitext(win.title())[0], win.doc.solid)], False, os.path.splitext(win.title())[0]
    return None, False, ""


def run_export(parent, win):
    items, is_asm, base = export_items(win)
    if items is None:
        QMessageBox.information(parent, "Export", "Open a part or an assembly tab first.")
        return
    if not items:
        QMessageBox.information(parent, "Export", "There is nothing to export yet (no solid).")
        return
    dlg = ExportDialog(parent, is_asm)
    if not dlg.exec():
        return
    v = dlg.values()
    try:
        if v["step"]:
            p, _ = QFileDialog.getSaveFileName(parent, "Export STEP", base + ".step", "STEP (*.step *.stp)")
            if not p:
                return
            if not p.lower().endswith((".step", ".stp")):
                p += ".step"
            ex.export_step(p, items, v["fuse"])
            msg = f"Exported {p}"
        elif is_asm and v["each"]:
            d = QFileDialog.getExistingDirectory(parent, "Folder for the STL files (one per component)")
            if not d:
                return
            ps = ex.export_stl_each(d, items, v["tol"], v["ang"])
            msg = f"Exported {len(ps)} STL files into {d}"
        else:
            p, _ = QFileDialog.getSaveFileName(parent, "Export STL", base + ".stl", "STL (*.stl)")
            if not p:
                return
            if not p.lower().endswith(".stl"):
                p += ".stl"
            from build123d import Compound
            shape = items[0][1] if len(items) == 1 else Compound([s for _n, s in items])
            ex.export_stl(p, shape, v["tol"], v["ang"])
            msg = f"Exported {p}"
    except Exception as e:
        QMessageBox.warning(parent, "Export", f"The export failed: {e}")
        return
    try:
        win.say(msg)
    except Exception:
        parent.statusBar().showMessage(msg) if hasattr(parent, "statusBar") else None


def import_doc(name, solid, source):
    """A new part document whose first feature is the imported body."""
    import pm_model as pm
    d = pm.Document()
    d.add(pm.new_feature("imported", brep=ex.pack(solid), source=source, name=name))
    d.rebuild()
    return d


def run_import(shell):
    p, _ = QFileDialog.getOpenFileName(shell, "Import STEP", "", "STEP (*.step *.stp);;All files (*)")
    if not p:
        return None
    try:
        items = ex.read_step(p)
    except Exception as e:
        QMessageBox.warning(shell, "Import STEP", f"That file could not be read: {e}")
        return None
    src = os.path.basename(p)
    base = os.path.splitext(src)[0]
    if len(items) == 1:
        return open_part_doc(shell, items[0][0], items[0][1], src)
    box = QMessageBox(shell)
    box.setWindowTitle("Import STEP")
    box.setText(f"{src} holds {len(items)} solids. How should they open?")
    b_each = box.addButton("One part per solid", QMessageBox.ButtonRole.AcceptRole)
    b_asm = box.addButton("One assembly (parts saved in a folder)", QMessageBox.ButtonRole.AcceptRole)
    b_one = box.addButton("One part with all solids", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    c = box.clickedButton()
    if c is b_each:
        return [open_part_doc(shell, n, s, src) for n, s in items]
    if c is b_one:
        from build123d import Compound
        return open_part_doc(shell, base, Compound([s for _n, s in items]), src)
    if c is b_asm:
        return import_as_assembly(shell, items, p, base)
    return None


def open_part_doc(shell, name, solid, src):
    d = import_doc(name, solid, src)
    w = shell.new_part()
    w.doc = d
    w.update_all(fit=True)
    w.saved_json = ""                                           # an unsaved new part: closing it asks
    return w


def import_as_assembly(shell, items, step_path, base):
    folder = QFileDialog.getExistingDirectory(shell, "Folder for the new parts and the assembly", os.path.dirname(step_path))
    if not folder:
        return None
    paths = []
    for n, s in items:
        fp = os.path.join(folder, ex.safe(n) + ".gpd")
        open(fp, "w", encoding="utf-8").write(import_doc(n, s, os.path.basename(step_path)).to_json())
        paths.append((n, fp))
    w = shell.new_assembly()
    w.path = os.path.join(folder, base + ".gpa")
    for n, fp in paths:
        w.asm.add_component(fp, name=n, fixed=True)           # the solids already sit where they belong, so every component is fixed at the origin
    w.solve_all()
    w.update_all(fit=True)
    w.save()
    return w
