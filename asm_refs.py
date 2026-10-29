"""
asm_refs.py - the assembly's own reference geometry: its origin and Front / Top / Right planes, reference planes and axes (built from faces,
edges, points and planes of the components), the Show menu, picking them in the view and in the (small) tree.
Attached to assembly.AssemblyWindow by install().
"""
import numpy as np
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QMenu, QPushButton, QRadioButton,
                             QToolButton, QWidget, QWidgetAction)

import asm_model as am
import pm_app
import refgeo
import viewpick

PLANE_COL = {"Front": (0.35, 0.60, 0.95), "Top": (0.45, 0.80, 0.45), "Right": (0.90, 0.55, 0.40)}
REF_COL = (0.20, 0.68, 0.74)
AXIS_COL = (0.62, 0.30, 0.80)
HI = (1.0, 0.45, 0.0)
ORD = ["First", "Second", "Third"]
VIS_KEYS = (("planes", "Planes"), ("origin", "Origin"), ("refgeo", "Reference geometry"))


# ------------------------------------------------------------------------------------------- Show bar
def init_vis(win):
    qs = QSettings("GenParametricDesigner", "Modeller")
    win.vis = {k: qs.value("asm_show_" + k, "1") in ("1", 1, True, "true") for k, _ in VIS_KEYS}


def make_show_bar(win):
    bar = QWidget()
    bar.setObjectName("showbar")
    bar.setStyleSheet("#showbar{background:#cfd9ea; border:none;}")
    bl = QHBoxLayout(bar)
    bl.setContentsMargins(6, 3, 6, 0)
    bl.addStretch(1)
    sb = QToolButton()
    sb.setText("Show  ▾")
    sb.setToolTip("Choose what is drawn in the view (tick as many as you like; click elsewhere to close)")
    sb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    sb.setStyleSheet("QToolButton{background:rgba(255,255,255,170); border:1px solid #8fa6c8; border-radius:9px; padding:2px 14px; color:#1d2a44;}"
                     "QToolButton:hover{background:rgba(255,255,255,240);} QToolButton::menu-indicator{image:none;}")
    sm = QMenu(sb)
    win.show_checks = {}
    for key, label in VIS_KEYS:
        cbx = QCheckBox(label)
        cbx.setChecked(win.vis[key])
        cbx.setStyleSheet("QCheckBox{padding:4px 14px 4px 10px;} QCheckBox:hover{background:#dbe8fa;}")
        cbx.toggled.connect(lambda on, k=key: set_show(win, k, on))
        wa = QWidgetAction(sm)
        wa.setDefaultWidget(cbx)
        sm.addAction(wa)
        win.show_checks[key] = cbx
    sb.setMenu(sm)
    bl.addWidget(sb)
    bl.addStretch(1)
    bar.setFixedHeight(28)
    return bar


def set_show(win, key, on):
    win.vis[key] = bool(on)
    QSettings("GenParametricDesigner", "Modeller").setValue("asm_show_" + key, "1" if on else "0")
    win.refresh_tree()
    win.rebuild_scene()


# ------------------------------------------------------------------------------------------- geometry drawing
def scene_size(win):
    top = 0.0
    for cid, e in win.entries.items():
        c = win.asm.comp(cid)
        if c is None:
            continue
        M = win.asm.T4(c)
        P = np.asarray(e["mesh"].points)
        if len(P):
            W = P @ M[:3, :3].T + M[:3, 3]
            top = max(top, float(np.abs(W).max()))
    return max(40.0, 2.4 * top) if top else 100.0


def shape_actor(win, pl, pv, ent, col, opacity, size, line=1.0):
    """A square for a plane, a tube for an axis, a dot for a point - in world coordinates."""
    k = refgeo.kind_of(ent)
    p = np.asarray(ent["p"], float)
    if k == "plane":
        n = np.asarray(ent["n"], float)
        x = np.asarray(ent.get("x", refgeo.frame_x(n)), float)
        y = np.cross(n, x)
        h = size / 2
        a = pl.add_mesh(pv.Plane(center=tuple(p), direction=tuple(n), i_size=size, j_size=size), color=col, opacity=opacity, pickable=False,
                        lighting=False, reset_camera=False)
        cor = np.array([p - x * h - y * h, p + x * h - y * h, p + x * h + y * h, p - x * h + y * h, p - x * h - y * h])
        pl.add_mesh(pm_app.MainWindow.merged_lines([cor]), color=col, line_width=2.5 * line, pickable=False, reset_camera=False)
        return a, (p, x, y, h)
    if k == "line":
        d = np.asarray(ent["d"], float)
        L = 0.7 * size
        tube = pv.Tube(pointa=tuple(p - d * L), pointb=tuple(p + d * L), radius=size * 0.006 * line)
        return pl.add_mesh(tube, color=col, pickable=False, lighting=False, reset_camera=False), (p, d, L)
    return pl.add_mesh(pv.PolyData(np.array([p])), color=col, point_size=12, render_points_as_spheres=True, pickable=False, reset_camera=False), (p,)


def draw_world(win, pl, pv):
    """The assembly's origin / planes / reference planes and axes (called from rebuild_scene).  Fills win.world_geo for picking."""
    a = win.asm
    size = scene_size(win)
    win.world_geo = []
    sel_refs = {s["ref"].get("r", {}).get("id") for s in (win.rg["refs"] if win.rg else []) if s["ref"]["c"] == "@"}
    if win.vis.get("planes", True):
        for nm in ("Front", "Top", "Right"):
            if a.world_show.get(nm, True):
                ent = a.entity({"c": "@", "k": "plane", "r": {"n": nm}})
                _x, info = shape_actor(win, pl, pv, ent, PLANE_COL[nm], 0.12, size, 0.5)
                win.world_geo.append({"type": "plane", "ref": {"c": "@", "k": "plane", "r": {"n": nm}}, "label": f"{nm} Plane", "info": info,
                                      "n": ent["n"]})
    if win.vis.get("origin", True) and a.world_show.get("origin", True):
        L = 0.3 * size
        for vec, col in (((L, 0, 0), (0.85, 0.2, 0.2)), ((0, L, 0), (0.2, 0.7, 0.2)), ((0, 0, L), (0.2, 0.35, 0.9))):
            pl.add_mesh(pv.Line((0, 0, 0), vec), color=col, line_width=2.5, pickable=False, reset_camera=False)
        pl.add_mesh(pv.PolyData(np.array([[0.0, 0.0, 0.0]])), color=(0.8, 0.15, 0.55), point_size=9, render_points_as_spheres=True,
                    pickable=False, reset_camera=False)
        win.world_geo.append({"type": "point", "ref": {"c": "@", "k": "origin", "r": None}, "label": "Origin", "info": (np.zeros(3),)})
    for f in a.refs:
        if not (f.get("show", True) and win.vis.get("refgeo", True)):
            continue
        try:
            ent = a.ref_entity(f["id"])
        except am.MateError:
            continue
        plane = f["kind"] == "refplane"
        hot = f["id"] in sel_refs
        _x, info = shape_actor(win, pl, pv, ent, HI if hot else (REF_COL if plane else AXIS_COL), 0.16 if plane else 1.0, size)
        win.world_geo.append({"type": "plane" if plane else "line", "ref": {"c": "@", "k": "plane" if plane else "axis", "r": {"id": f["id"]}},
                              "label": f["name"], "info": info, "n": ent.get("n")})


def world_pick(win, x, y):
    """The nearest plane / axis / origin of the assembly under the pixel (a ray test; components have priority and are tried first)."""
    if win.ed is None:
        return None
    o, d = win.ed.ray(x, y)
    d = d / max(1e-12, float(np.linalg.norm(d)))
    wpp = viewpick.world_per_pixel(win.plotter)
    best = None
    for g in getattr(win, "world_geo", []):
        t = None
        if g["type"] == "plane":
            p, xv, yv, h = g["info"]
            den = float(d @ g["n"])
            if abs(den) < 1e-9:
                continue
            t = float((p - o) @ g["n"]) / den
            q = o + d * t
            if t < 0 or abs(float((q - p) @ xv)) > h or abs(float((q - p) @ yv)) > h:
                continue
        elif g["type"] == "line":
            p, dv, L = g["info"]
            w = o - p
            b = float(d @ dv)
            den = 1 - b * b
            if abs(den) < 1e-9:
                continue
            tt = (b * float(w @ dv) - float(w @ d)) / den           # along the ray
            s = (float(w @ dv) - b * float(w @ d)) / den             # along the axis
            if tt < 0 or abs(s) > L:
                continue
            if float(np.linalg.norm((o + d * tt) - (p + dv * s))) > max(0.6, 6.0 * wpp):
                continue
            t = tt
        else:
            (p,) = g["info"]
            tt = float((p - o) @ d)
            if tt < 0 or float(np.linalg.norm(o + d * tt - p)) > max(0.6, 7.0 * wpp):
                continue
            t = tt - 0.001
        if best is None or t < best[0]:
            best = (t, g)
    if best is None:
        return None
    g = best[1]
    kind = {"plane": "plane", "line": "axis", "point": "origin"}[g["type"]]
    return {"cid": "@", "kind": kind, "idx": -1, "pt": None, "label": g["label"], "ref": g["ref"]}


def highlight_extra(win, pl, pv, it):
    """Highlight of a picked plane / axis / origin (the face / edge / point ones are drawn by AssemblyWindow)."""
    try:
        ent = win.asm.entity(it["ref"])
    except am.MateError:
        return None
    a, _ = shape_actor(win, pl, pv, ent, HI, 0.35, scene_size(win), 1.6)
    return a


# ------------------------------------------------------------------------------------------- picks from the trees
def item_from_data(win, data):
    k = data[0]
    if k == "cplane":
        return {"cid": data[1], "kind": "plane", "idx": -1, "label": f"{data[2]} Plane", "ref": {"c": data[1], "k": "plane", "r": {"n": data[2]}}}
    if k == "corigin":
        return {"cid": data[1], "kind": "origin", "idx": -1, "label": "Origin", "ref": {"c": data[1], "k": "origin", "r": None}}
    if k == "wplane":
        return {"cid": "@", "kind": "plane", "idx": -1, "label": f"{data[1]} Plane", "ref": {"c": "@", "k": "plane", "r": {"n": data[1]}}}
    if k == "worigin":
        return {"cid": "@", "kind": "origin", "idx": -1, "label": "Origin", "ref": {"c": "@", "k": "origin", "r": None}}
    if k == "aref":
        f = next((r for r in win.asm.refs if r["id"] == data[1]), None)
        if f is None:
            return None
        pl = f["kind"] == "refplane"
        return {"cid": "@", "kind": "plane" if pl else "axis", "idx": -1, "label": f["name"],
                "ref": {"c": "@", "k": "plane" if pl else "axis", "r": {"id": f["id"]}}}
    if k == "cref":
        pl = data[3] == "refplane"
        nm = next((x for x in win.part_doc(win.asm.comp(data[1])).features if x["id"] == data[2]), {"name": "?"})["name"]
        return {"cid": data[1], "kind": "plane" if pl else "axis", "idx": -1, "label": nm,
                "ref": {"c": data[1], "k": "plane" if pl else "axis", "r": {"id": data[2]}}}
    return None


def pick_from_data(win, data):
    """A tree click (big or small) while a command waits for a pick.  True when it was used as a pick."""
    if win.mode == "pattern" and data[0] == "comp":
        win.pat_toggle_comp(data[1])
        return True
    if win.mode not in ("mate", "refgeo", "mirror_plane", "axis_pick"):
        return False
    item = item_from_data(win, data)
    if item is None:
        return False
    if win.mode == "mate":
        win.add_mate_ref(item["ref"], item)
    elif win.mode == "refgeo":
        rg_toggle(win, item)
    elif win.mode == "mirror_plane":
        if item["kind"] != "plane":
            return False
        win.pat_set_plane(item)
    else:
        win.pat_set_entity(item)
    return True


def mini_pick(win, data):
    return pick_from_data(win, data)


# ------------------------------------------------------------------------------------------- the plane / axis tool
def describe(win, s):
    c = win.asm.comp(s["cid"]) if s["cid"] != "@" else None
    return f"{s['label']}" + (f"<{c['name']}>" if c else "")


def start(win, kind, edit=None):
    win.set_mode(None, quiet=True)
    win.mode = "refgeo"
    st = {"kind": kind, "refs": [], "ptype": None, "auto": True, "d": "10", "ang": "45", "flip": False, "edit": edit, "orig": None, "err": "", "ent": None}
    if edit is not None:
        f = next(r for r in win.asm.refs if r["id"] == edit)
        st.update(kind=f["kind"], ptype=f.get("ptype"), auto=False, d=str(f.get("d", "10")), ang=str(f.get("ang", "45")), flip=bool(f.get("flip")),
                  orig=f)
        st["refs"] = [win.sel_item_from_ref(r) for r in f["refs"]]
        st["refs"] = [s for s in st["refs"] if s["idx"] != -1 or s["kind"] in ("plane", "origin", "axis")]
    win.rg = st
    retype(win)
    refresh(win)
    win.left.setCurrentIndex(1)
    win.say("Pick the references: faces, edges, points, planes or axes in the view, or items in the tree / small tree. Click a pick again to remove it.")


def retype(win):
    st = win.rg
    if st["auto"]:
        ents = []
        for s in st["refs"]:
            try:
                ents.append(win.asm.entity(s["ref"]))
            except am.MateError:
                ents.append({"t": "point"})
        st["ptype"] = refgeo.infer_plane_type(ents) if st["kind"] == "refplane" else refgeo.infer_axis_type(ents)


def rg_toggle(win, item):
    st = win.rg
    for i, s in enumerate(st["refs"]):
        if s["ref"] == item["ref"]:
            del st["refs"][i]
            break
    else:
        st["refs"].append(item)
        st["refs"] = st["refs"][-3:]
    retype(win)
    refresh(win)


def compute(win):
    st = win.rg
    st["err"], st["ent"] = "", None
    try:
        ents = [win.asm.entity(s["ref"]) for s in st["refs"]]
        num = lambda x: float(eval(str(x), {"__builtins__": {}}, {}))
        if st["kind"] == "refplane":
            st["ent"] = refgeo.compute_plane(st["ptype"], ents, num(st["d"]), num(st["ang"]), st["flip"])
        else:
            st["ent"] = refgeo.compute_axis(st["ptype"], ents)
    except (refgeo.RefError, am.MateError) as ex:
        st["err"] = str(ex)
    except Exception as ex:
        st["err"] = f"{ex}"


def refresh(win):
    compute(win)
    win.draw_highlights()
    panel(win)


def panel(win):
    st = win.rg
    if st is None:
        return
    plane = st["kind"] == "refplane"
    win.clear_props()
    lay = win.props_lay
    lay.addWidget(QLabel("<b>" + ("Plane" if plane else "Axis") + "</b>"))
    row = QHBoxLayout()
    b = QPushButton("✔  OK")
    b.clicked.connect(lambda: ok(win))
    row.addWidget(b)
    b = QPushButton("✖  Cancel")
    b.clicked.connect(lambda: cancel(win))
    row.addWidget(b)
    w = QWidget()
    w.setLayout(row)
    lay.addWidget(w)
    lay.addWidget(QLabel("References  (click items in the view or the trees; click again to remove):"))
    lw = QListWidget()
    lw.setMaximumHeight(92)
    for i, s in enumerate(st["refs"]):
        lw.addItem(f"{ORD[i]}:  {describe(win, s)}")
    if not st["refs"]:
        lw.addItem("(nothing picked yet)")
    lay.addWidget(lw)
    lay.addWidget(QLabel("<b>Type</b>"))
    grp = QButtonGroup(win.props)
    for t, name, needs, tip in (refgeo.PLANE_TYPES if plane else refgeo.AXIS_TYPES):
        rb = QRadioButton(name)
        rb.setToolTip(f"{tip}.  Needs: {needs}")
        rb.setChecked(st["ptype"] == t)
        rb.toggled.connect(lambda on, t=t: on and set_type(win, t))
        grp.addButton(rb)
        lay.addWidget(rb)
    if st["auto"]:
        lay.addWidget(QLabel("<i>The type follows what you pick - choose one above to fix it.</i>"))
    form = QFormLayout()
    box = QWidget()
    box.setLayout(form)
    lay.addWidget(box)
    from PyQt6.QtWidgets import QLineEdit

    def num(label, key):
        e = QLineEdit(str(st[key]))

        def done():
            st[key] = e.text()
            refresh(win)
        e.editingFinished.connect(done)
        form.addRow(label, e)
    if plane and st["ptype"] == "offset":
        num("Distance (mm)", "d")
    if plane and st["ptype"] == "angle":
        num("Angle (deg)", "ang")
    if plane:
        cb = QCheckBox()
        cb.setChecked(st["flip"])
        cb.toggled.connect(lambda v: (st.__setitem__("flip", bool(v)), refresh(win)))
        form.addRow("Flip", cb)
    msg = QLabel(st["err"] if st["err"] else ("Fully defined" if st["ent"] is not None else ""))
    msg.setWordWrap(True)
    msg.setStyleSheet(("color:#c00000;" if st["err"] else "background:#8cf58c; padding:3px; font-weight:bold;"))
    lay.addWidget(msg)


def set_type(win, t):
    st = win.rg
    if st["ptype"] == t and not st["auto"]:
        return
    st["ptype"], st["auto"] = t, False
    refresh(win)


def ok(win):
    st = win.rg
    if st["ent"] is None:
        win.say(st["err"] or "Pick the references first.")
        return
    win.snapshot()
    a = win.asm
    data = {"kind": st["kind"], "refs": [s["ref"] for s in st["refs"]], "ptype": st["ptype"], "d": st["d"], "ang": st["ang"], "flip": st["flip"]}
    if st["edit"] is not None:
        f = next(r for r in a.refs if r["id"] == st["edit"])
        f.update(data)
    else:
        n = 1 + sum(1 for r in a.refs if r["kind"] == st["kind"])
        base = "Plane" if st["kind"] == "refplane" else "Axis"
        while any(r["name"] == f"{base}{n}" for r in a.refs):
            n += 1
        a.refs.append({"id": a.next_id("R"), "name": f"{base}{n}", "show": True, **data})
    win.rg, win.mode = None, None
    win.solve_all()
    win.update_all()
    win.show_comp_props()
    win.left.setCurrentIndex(0)
    win.say("Reference " + ("plane" if st["kind"] == "refplane" else "axis") + " saved.")


def cancel(win, quiet=False):
    win.rg, win.mode = None, None
    win.update_all()
    win.show_comp_props()
    win.left.setCurrentIndex(0)
    if not quiet:
        win.say("Cancelled.")


def delete_ref(win, rid):
    a = win.asm
    gone = {rid}
    grew = True
    while grew:
        grew = False
        for r in a.refs:
            if r["id"] not in gone and any(x["c"] == "@" and (x.get("r") or {}).get("id") in gone for x in r["refs"]):
                gone.add(r["id"])
                grew = True
    users = [m for m in a.mates if any(x["c"] == "@" and (x.get("r") or {}).get("id") in gone for x in m["refs"])]
    win.snapshot()
    a.refs = [r for r in a.refs if r["id"] not in gone]
    a.mates = [m for m in a.mates if m not in users]
    win.solve_all()
    win.update_all()
    win.say(f"Deleted" + (f" (and {len(users)} mate(s) that used it)." if users else "."))


def install(cls):
    cls.mini_pick = lambda self, data: mini_pick(self, data)
