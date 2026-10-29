"""Component patterns, Mirror Components and the assembly mass properties (the parts of the assembly window kept out of assembly.py)."""
import math

import numpy as np
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
                             QPushButton, QVBoxLayout, QWidget)
from PyQt6.QtGui import QFont, QGuiApplication

import asm_model as am

AX = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
BASE_PLANE_N = {"Front": (0.0, -1.0, 0.0), "Top": (0.0, 0.0, 1.0), "Right": (1.0, 0.0, 0.0)}


# ---------------------------------------------------------------------------------------------- the transforms
def translation(v):
    M = np.eye(4)
    M[:3, 3] = v
    return M


def rotation_about(p, d, ang):
    R = am.axis_rotation(d, ang)
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = p - R @ p
    return M


def reflection(p0, n):
    n = am.unit(n)
    M = np.eye(4)
    M[:3, :3] = np.eye(3) - 2 * np.outer(n, n)
    M[:3, 3] = 2 * float(n @ p0) * n
    return M


def dir_of(win, spec):
    """(point, direction) of an axis / direction choice: 'X'|'Y'|'Z' through the origin, or a picked item."""
    if isinstance(spec, str):
        return np.zeros(3), np.array(AX[spec])
    e = win.asm.entity(spec["ref"])
    if e["t"] == "plane":
        return e["p"], e["n"]
    if "d" in e:
        return e["p"], e["d"]
    raise am.MateError("pick a straight edge, a cylinder, a circle or a flat face for the direction")


def transforms(win, p):
    """[4x4] for every copy of a pattern (not the seed)."""
    out = []
    ty = p["type"]
    if ty == "mirror":
        spec = p.get("plane", "Front")
        if isinstance(spec, str):
            return [reflection(np.zeros(3), np.array(BASE_PLANE_N[spec]))]
        e = win.asm.entity(spec["ref"])
        if e["t"] != "plane":
            raise am.MateError("the mirror plane must be a plane or a flat face")
        return [reflection(e["p"], e["n"])]
    if ty == "linear":
        _p, d1 = dir_of(win, p.get("dir1", "X"))
        d1 = am.unit(d1)
        n1, s1 = max(1, int(round(float(p.get("n1", 3))))), float(p.get("s1", 20))
        two = bool(p.get("two"))
        n2, s2 = (max(1, int(round(float(p.get("n2", 2))))), float(p.get("s2", 20))) if two else (1, 0.0)
        d2 = am.unit(dir_of(win, p.get("dir2", "Y"))[1]) if two else np.zeros(3)
        for i in range(n1):
            for j in range(n2):
                if i or j:
                    out.append(translation(d1 * s1 * i + d2 * s2 * j))
        return out
    pt, d = dir_of(win, p.get("axis", "Z"))
    n = max(2, int(round(float(p.get("n", 4)))))
    ang = float(p.get("angle", 360))
    if p.get("equal", True):
        step = ang / n if abs(ang - 360) < 1e-9 else ang / (n - 1)
    else:
        step = ang
    for i in range(1, n):
        out.append(rotation_about(pt, d, math.radians(step * i)))
    return out


def rebuild_derived(win):
    """Make / update the derived components of all patterns (stable ids, so dragging only changes their matrices)."""
    a = win.asm
    wanted = {}
    for p in a.patterns:
        seeds = [a.comp(s) for s in p.get("seeds", [])]
        seeds = [s for s in seeds if s is not None and not s.get("derived")]
        try:
            Xs = transforms(win, p)
        except am.MateError:
            Xs = []
        for s in seeds:
            T = a.T4(s)
            for k, X in enumerate(Xs):
                cid = f"{p['id']}.{s['id']}.{k}"
                wanted[cid] = {"id": cid, "name": f"{s['name']}[{p['name']}{k + 1}]", "path": s["path"], "base": s.get("base"),
                               "pos": [0, 0, 0], "rv": [0, 0, 0], "fixed": True, "hidden": s.get("hidden", False) or bool(s.get("suppressed")),
                               "color": s.get("color"), "opacity": s.get("opacity", 1.0),
                               "derived": {"pat": p["id"], "src": s["id"], "kind": p["type"], "i": k}, "M": (X @ T).tolist()}
    have = {c["id"]: c for c in a.components if c.get("derived")}
    changed = set(have) != set(wanted)
    if changed:
        a.components = [c for c in a.components if not c.get("derived")] + list(wanted.values())
    else:
        for cid, c in have.items():
            c["M"] = wanted[cid]["M"]
            c["hidden"] = wanted[cid]["hidden"]
            c["color"], c["opacity"] = wanted[cid]["color"], wanted[cid]["opacity"]
    win.derived_changed = changed
    return changed


# ---------------------------------------------------------------------------------------------- the editor
def start(win, kind):
    a = win.asm
    seeds = [c for c in a.components if not c.get("derived")]
    if not seeds:
        win.say("Insert a component first.")
        return
    win.set_mode(None, quiet=True)
    win.snapshot()
    pid = a.next_id("P")
    name = {"linear": "LocalLPattern", "circular": "LocalCirPattern", "mirror": "MirrorComponents"}[kind] + pid[1:]
    p = {"id": pid, "name": name, "type": kind, "seeds": [win.sel_comp] if win.sel_comp and not a.comp(win.sel_comp).get("derived") else []}
    if kind == "linear":
        p.update(dir1="X", n1=3, s1=50.0, two=False, dir2="Y", n2=2, s2=50.0)
    elif kind == "circular":
        p.update(axis="Z", n=4, angle=360.0, equal=True)
    else:
        p.update(plane="Right")
    a.patterns.append(p)
    win.pat = {"data": p, "orig": None, "new": True, "hi": []}
    win.mode = "pattern"
    refresh(win)
    win.left.setCurrentIndex(1)
    win.say("Click the components to repeat (in the view or in the tree), then set the options and press the green check.")


def edit(win, pid):
    p = next((x for x in win.asm.patterns if x["id"] == pid), None)
    if p is None:
        return
    win.set_mode(None, quiet=True)
    win.snapshot()
    import copy
    win.pat = {"data": p, "orig": copy.deepcopy(p), "new": False, "hi": []}
    win.mode = "pattern"
    refresh(win)
    win.left.setCurrentIndex(1)


def delete(win, pid):
    win.snapshot()
    win.asm.patterns = [p for p in win.asm.patterns if p["id"] != pid]
    win.refresh_derived()
    win.update_all()


def cancel(win, quiet=False):
    st = win.pat
    if st is None:
        return
    win.pat = None
    if st["new"]:
        win.asm.patterns = [p for p in win.asm.patterns if p is not st["data"]]
    else:
        st["data"].clear()
        st["data"].update(st["orig"])
    if win.undo:
        win.undo.pop()
    win.mode = None
    win.refresh_derived()
    win.update_all()
    win.show_comp_props()
    win.left.setCurrentIndex(0)
    if not quiet:
        win.say("Cancelled.")


def ok(win):
    st = win.pat
    if st is None:
        return
    p = st["data"]
    if not p["seeds"]:
        win.say("Pick at least one component to repeat.")
        return
    try:
        transforms(win, p)
    except am.MateError as ex:
        win.say(str(ex))
        return
    win.pat = None
    win.mode = None
    win.refresh_derived()
    win.update_all()
    win.show_comp_props()
    win.left.setCurrentIndex(0)


def toggle_comp(win, cid):
    st = win.pat
    c = win.asm.comp(cid)
    if st is None or c is None or c.get("derived"):
        return
    s = st["data"]["seeds"]
    if cid in s:
        s.remove(cid)
    else:
        s.append(cid)
    refresh(win)


def set_plane(win, item):
    st = win.pat
    if st is None:
        return
    st["data"]["plane"] = {"ref": item["ref"]}
    win.mode = "pattern"
    refresh(win)


def set_entity(win, item):
    st = win.pat
    if st is None:
        return
    key = st.get("pick_key")
    if key:
        st["data"][key] = {"ref": item["ref"]}
    win.mode = "pattern"
    refresh(win)


def refresh(win):
    win.refresh_derived()
    win.update_all()
    panel(win)


def panel(win):
    st = win.pat
    if st is None:
        return
    p = st["data"]
    win.clear_props()
    lay = win.props_lay
    lay.addWidget(QLabel(f"<b>{p['name']}</b>"))
    row = QHBoxLayout()
    b = QPushButton("✔  OK")
    b.clicked.connect(lambda: ok(win))
    row.addWidget(b)
    b = QPushButton("✖  Cancel")
    b.clicked.connect(lambda: win.set_mode(None))
    row.addWidget(b)
    w = QWidget()
    w.setLayout(row)
    lay.addWidget(w)
    lay.addWidget(QLabel("Components to " + ("Mirror:" if p["type"] == "mirror" else "Pattern:") + "   (click them in the view or tree)"))
    lst = QListWidget()
    lst.setMaximumHeight(80)
    for s in p["seeds"]:
        c = win.asm.comp(s)
        lst.addItem(c["name"] if c else "?")
    lay.addWidget(lst)
    form = QFormLayout()
    box = QWidget()
    box.setLayout(form)
    lay.addWidget(box)

    def num(label, key, integer=False):
        e = QLineEdit(str(p.get(key)))

        def done():
            try:
                v = float(e.text())
                p[key] = int(round(v)) if integer else v
            except ValueError:
                e.setText(str(p.get(key)))
                return
            refresh_keep(win)
        e.editingFinished.connect(done)
        form.addRow(label, e)

    def choose(label, key, extra_label):
        cb = QComboBox()
        names = ["X", "Y", "Z"] if p["type"] != "mirror" else ["Front", "Top", "Right"]
        for n in names:
            cb.addItem(n if p["type"] == "mirror" else n + " axis", n)
        cb.addItem(extra_label, "pick")
        cur = p.get(key)
        cb.setCurrentIndex(names.index(cur) if isinstance(cur, str) and cur in names else len(names))

        def ch(_i):
            v = cb.currentData()
            if v == "pick":
                st["pick_key"] = key
                win.mode = "mirror_plane" if p["type"] == "mirror" else "axis_pick"
                win.say("Click the item in the view" + (" (a flat face)." if p["type"] == "mirror" else " (straight edge, cylinder, circle or face)."))
                return
            p[key] = v
            win.mode = "pattern"
            refresh_keep(win)
        cb.currentIndexChanged.connect(ch)
        form.addRow(label, cb)
    if p["type"] == "linear":
        choose("Direction 1", "dir1", "Picked edge / face")
        num("Spacing (mm)", "s1")
        num("Instances", "n1", True)
        c2 = QCheckBox("Direction 2")
        c2.setChecked(bool(p.get("two")))
        c2.toggled.connect(lambda v: (p.__setitem__("two", bool(v)), refresh_keep(win), panel(win)))
        form.addRow(c2)
        if p.get("two"):
            choose("Direction 2", "dir2", "Picked edge / face")
            num("Spacing 2 (mm)", "s2")
            num("Instances 2", "n2", True)
    elif p["type"] == "circular":
        choose("Axis", "axis", "Picked axis (edge, cylinder, face)")
        num("Angle (deg)", "angle")
        num("Instances", "n", True)
        ce = QCheckBox("Equal spacing")
        ce.setChecked(bool(p.get("equal", True)))
        ce.toggled.connect(lambda v: (p.__setitem__("equal", bool(v)), refresh_keep(win)))
        form.addRow(ce)
    else:
        choose("Mirror plane", "plane", "Picked flat face")
    lay.addStretch(1)


def refresh_keep(win):
    win.refresh_derived()
    win.update_all()
    win.left.setCurrentIndex(1)


# ---------------------------------------------------------------------------------------------- mass properties
def assembly_props(win):
    import evaluate
    a = win.asm
    M = 0.0
    V = 0.0
    A = 0.0
    Msum = np.zeros(3)
    items = []
    for c in a.components:
        if c.get("hidden") or c.get("suppressed"):
            continue
        d = win.part_doc(c if not c.get("derived") else a.comp(c["derived"]["src"]))
        if d is None or d.solid is None:
            continue
        pr = d.mass_pr() if getattr(d, "is_sub", False) else evaluate.mass_properties(d.solid, d.material["density"])
        if pr is None:
            continue
        T = a.T4(c)
        L, t = T[:3, :3], T[:3, 3]
        com = L @ pr["com"] + t
        ic = L @ pr["ic"] @ L.T
        items.append((pr["mass"], com, ic))
        M += pr["mass"]
        V += pr["volume"]
        A += pr["area"]
        Msum += pr["mass"] * com
    if M <= 0:
        return None
    com = Msum / M
    io = sum(ic + m * (float(c @ c) * np.eye(3) - np.outer(c, c)) for m, c, ic in items)
    icm = io - M * (float(com @ com) * np.eye(3) - np.outer(com, com))
    w, v = np.linalg.eigh(icm)
    return {"volume": V, "area": A, "com": com, "mass": M, "ic": icm, "io": io, "pm": w, "axes": v.T}


class AsmMass(QDialog):
    def __init__(self, win):
        super().__init__(win)
        import evaluate
        self.win, self.ev = win, evaluate
        self.setWindowTitle("Mass Properties - assembly")
        self.resize(560, 620)
        lay = QVBoxLayout(self)
        self.units = QComboBox()
        self.units.addItems(list(evaluate.UNITS))
        form = QFormLayout()
        form.addRow("Units", self.units)
        lay.addLayout(form)
        lay.addWidget(QLabel("Each component uses the density of its own part (set in the part's Mass Properties)."))
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
        self.units.currentTextChanged.connect(lambda _t: self.refresh())
        self.refresh()

    def refresh(self):
        try:
            pr = assembly_props(self.win)
            if pr is None:
                self.out.setPlainText("There is nothing with a solid in the assembly yet.")
                return
            dens = pr["mass"] / pr["volume"] * 1e9
            self.out.setPlainText(self.ev.mass_text(self.win.title(), pr, self.units.currentText(), dens)
                                  + "\n\n(The density shown is the average of the whole assembly.)")
        except Exception as ex:
            self.out.setPlainText(f"Could not compute the mass properties: {ex}")


def mass_dialog(win):
    d = getattr(win, "mass_dlg", None)
    if d is not None:
        d.close()
    win.mass_dlg = AsmMass(win)
    win.mass_dlg.show()
