"""
sim_disp.py - the Displacement support of the 1D, 2D and 3D FEA windows: one support that says, for every direction, what the held points do.

    blank = free        0 = held (cannot move)        a number = imposed (moved by exactly that much, in the unit system of the window)

2D: {"mode": "disp", "ux": None | number, "uy": None | number, "targets": [...]}
3D: {"mode": "disp", "ux": ..., "uy": ..., "uz": ..., "faces": [...]}
1D: {"mode": "disp", "ux": ..., "uy": ..., "rz": ..., "targets": [...]}          (rz: the rotation of the joint, in DEGREES, counter-clockwise positive)

It replaces the supports that held one direction at zero ("ux = 0" and "uy = 0" in 1D and 2D): a file saved with them opens as a Displacement with that direction at 0
and the others blank (`upgrade`).  Reactions are reported as before: the force (and, in 1D, the moment) the support puts on the body.
The dialog is the same in the three windows.  No solver here: the solvers take `held(support, keys)` (the dict of the directions that are held, with their value).
"""

KEYS = {1: ("ux", "uy", "rz"), 2: ("ux", "uy"), 3: ("ux", "uy", "uz")}
LABELS = {"ux": "ux", "uy": "uy", "uz": "uz", "rz": "rotation"}
NOTE = ("Blank = free: that direction can move. 0 = held: it cannot move. A number = imposed: the points are moved by exactly that much "
        "(the support pushes or pulls on the part as hard as it takes).")


def parse(text):
    """'' (or 'free') -> None; '0.5' -> 0.5.  ValueError for anything else."""
    t = str(text if text is not None else "").strip().replace(",", ".")
    if not t or t.lower() in ("free", "-"):
        return None
    if t.lower() == "held":
        return 0.0
    return float(t)


def fmt(v):
    """The text of one direction: blank for free."""
    return "" if v is None else f"{float(v):.10g}"


def word(v, unit=""):
    """'free', 'held' or the imposed value, for a list."""
    if v is None:
        return "free"
    if float(v) == 0.0:
        return "held"
    return f"{float(v):.6g}" + (f" {unit}" if unit else "")


def describe(sup, keys, unit_of=None):
    """'ux held, uy 2 mm, rotation free' for a list of the supports.  `unit_of(key)` gives the unit shown after an imposed value."""
    return ", ".join(f"{LABELS[k]} {word(sup.get(k), unit_of(k) if unit_of else '')}" for k in keys)


def held(sup, keys):
    """{key: value} of the directions that are held or imposed (the free ones are not in it)."""
    return {k: float(sup[k]) for k in keys if sup.get(k) is not None}


def is_all_free(sup, keys):
    return not held(sup, keys)


def has_imposed(supports):
    """True when one of the supports moves its points by a non-zero amount (a problem with no loads is still a problem then)."""
    return any(isinstance(s, dict) and s.get("mode") == "disp" and any(s.get(k) not in (None, 0, 0.0) for k in ("ux", "uy", "uz", "rz"))
               for s in (supports or []))


def check(sup, keys):
    """A sentence when the support holds nothing (it does nothing), else None."""
    if is_all_free(sup, keys):
        return "Every direction is blank, so this support holds nothing. Type 0 to hold a direction, or a number to move it."
    return None


# ------------------------------------------------------------------------------------------------------------------------ old files
OLD_HOLDS_2D = {"x": ("ux", 0.0), "y": ("uy", 0.0)}


def upgrade(sup, dim):
    """A support of an older file: the one-direction holds ('x' = ux = 0, 'y' = uy = 0) become a Displacement with that direction at 0 and the rest blank.  Anything
    else (and a Displacement) comes back unchanged (a copy)."""
    sup = dict(sup)
    mode = sup.get("mode")
    if dim in (1, 2) and mode in OLD_HOLDS_2D:
        k, v = OLD_HOLDS_2D[mode]
        sup["mode"] = "disp"
        for kk in KEYS[dim]:
            sup[kk] = v if kk == k else None
    elif mode == "disp":
        for kk in KEYS[dim]:
            sup.setdefault(kk, None)
    return sup


def scale_values(sup, factor, keys=("ux", "uy", "uz")):
    """A copy of a Displacement with its imposed lengths multiplied by `factor` (a change of the length unit); the held (0) and free (None) stay."""
    sup = dict(sup)
    if sup.get("mode") == "disp":
        for k in keys:
            if sup.get(k) is not None:
                sup[k] = float(sup[k]) * factor
    return sup


def upgrade_all(supports, dim):
    return [upgrade(s, dim) for s in (supports or [])]


def upgrade_inplace(supports, dim):
    """The same for a list that is used as it is (the window's own list, whose dicts others may hold): only the old one-direction holds are changed, each dict
    in place; a Displacement and everything else keep their dict."""
    for s in supports or []:
        if dim in (1, 2) and s.get("mode") in OLD_HOLDS_2D:
            s.update(upgrade(s, dim))
    return supports


# ------------------------------------------------------------------------------------------------------------------------ the dialog
def ask(parent, title, keys, units, current=None, note=NOTE):
    """The Displacement dialog: one box per direction (blank = free).  `units`: {key: unit text}.  Returns {key: None | number} or None when cancelled.  A box that
    holds something that is not a number is refused with a message, and the dialog stays open."""
    from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lab = QLabel(note)
    lab.setWordWrap(True)
    lab.setStyleSheet("color:#555555; font-size:11px;")
    lay.addWidget(lab)
    form = QFormLayout()
    edits = {}
    for k in keys:
        e = QLineEdit(fmt((current or {}).get(k)))
        e.setPlaceholderText("free")
        form.addRow(f"{LABELS[k]} ({units.get(k, '')})" if units.get(k) else LABELS[k], e)
        edits[k] = e
    lay.addLayout(form)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    lay.addWidget(bb)
    out = {}

    def accept():
        try:
            vals = {k: parse(e.text()) for k, e in edits.items()}
        except ValueError:
            QMessageBox.warning(dlg, title, "Type a number, or leave the box blank for free.")
            return
        out.update(vals)
        dlg.accept()
    bb.accepted.connect(accept)
    bb.rejected.connect(dlg.reject)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return out
