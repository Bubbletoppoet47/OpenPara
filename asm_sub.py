"""
asm_sub.py - an assembly (.gpa) used as a component of another assembly: a RIGID sub-assembly.

The sub-assembly is loaded from its file (or from its open tab), put in the configuration the parent asks for, solved, and turned into a
SubDoc: a stand-in for a part Document whose solid is the compound of all its parts in the sub-assembly's own frame.  Everything that works
for a part (drawing, picking faces / edges / points for mates, mass properties, configurations) then works for a sub-assembly too.
"""
import math
import os

import numpy as np
from build123d import Compound, Location, Plane

import asm_model as am
import evaluate
import pm_model as pm


class SubLoop(Exception):
    """An assembly that (directly or through others) contains itself."""


class SubDoc(pm.Document):
    """Looks like a part Document to the assembly window."""
    is_sub = True

    def rebuild(self):
        pass

    def copy(self):
        return self

    def mass_pr(self):
        return self._mass

    def mesh(self, solid=None, tol=0.05):
        """Like a part's, but the faces buried where two parts touch are left out: they lie exactly in the plane of the other part's
        face, fight with it for the pixels and hide the outline of the joint."""
        hid = getattr(self, "hidden_faces", ())
        return [m for m in super().mesh(solid, tol) if m[0] not in hid]


class Loader:
    """Just enough of an assembly window (its part / solid lookups) to load and solve a sub-assembly without a window."""

    def __init__(self, path, shell, stack):
        self.path, self.shell, self.stack = path, shell, stack
        self.asm = None
        self.part_cache, self.doc_memo, self.sub_cache = {}, {}, {}
        self.derived_changed = False

    def say(self, *_a):
        pass


def install_loader(window_cls):
    for name in ("abs", "wire", "part_base", "part_doc", "solid_of"):
        setattr(Loader, name, getattr(window_cls, name))


def _text(ctx, p):
    """The sub-assembly's saved text - or its live state when it is open (and maybe edited) in a tab."""
    shell = getattr(ctx, "shell", None)
    if shell is not None:
        i = shell.find_tab(p)
        if i is not None:
            w = shell.tabs.widget(i)
            if hasattr(w, "asm"):
                return w.asm.to_json()
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return None


def place(solid, M):
    """The solid moved by a 4x4 (a mirror copy is mirrored first: a mirror cannot be a plain move)."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    R, t = np.array(M, float)[:3, :3], np.array(M, float)[:3, 3]
    if np.linalg.det(R) < 0:
        solid = solid.mirror(Plane.YZ)
        R = R @ np.diag([-1.0, 1.0, 1.0])
    rv = am.rotvec(R)
    ang = float(np.linalg.norm(rv))
    tr = gp_Trsf()
    if ang > 1e-12:
        k = rv / ang
        tr.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*k)), ang)
    tr2 = gp_Trsf()
    tr2.SetTranslation(gp_Vec(*t))
    return solid.moved(Location(tr2 * tr))


def buried_faces(solid):
    """Indices of the faces of a compound that lie against another part's face (same plane, opposite normals) and inside it."""
    fs = solid.faces()
    if len(fs) > 800:
        return set()
    info = []
    for i, f in enumerate(fs):
        if f.geom_type.name != "PLANE":
            continue
        n = f.normal_at()
        c = f.center()
        bb = f.bounding_box()
        info.append((i, np.array([n.X, n.Y, n.Z]), np.array([c.X, c.Y, c.Z]), np.array([bb.min.X, bb.min.Y, bb.min.Z]),
                     np.array([bb.max.X, bb.max.Y, bb.max.Z]), f.area))
    out = set()
    tol = 1e-3
    for a in info:
        for b in info:
            if a[0] == b[0] or float(a[1] @ b[1]) > -0.999 or abs(float((b[2] - a[2]) @ a[1])) > tol:
                continue
            inside = bool(np.all(a[3] >= b[3] - tol) and np.all(a[4] <= b[4] + tol))      # a lies within b's box
            if inside and (a[5] < b[5] - 1e-6 or (abs(a[5] - b[5]) <= 1e-6 and a[0] < b[0])):
                out.add(a[0])
                if abs(a[5] - b[5]) <= 1e-6:
                    out.add(b[0])
    return out


def bodies_of(ctx, a):
    """[(name, solid in the assembly's frame, material dict)] of every visible component of assembly a (a sub-assembly gives its own
    bodies), for cutting a slice through the assembly.  ctx supplies part_doc(component)."""
    out = []
    for c in a.components:
        if c.get("hidden") or c.get("suppressed"):
            continue
        src = a.comp(c["derived"]["src"]) if c.get("derived") else c
        d = ctx.part_doc(src) if src is not None else None
        if d is None or d.solid is None:
            continue
        T = a.T4(c)
        if getattr(d, "is_sub", False):
            for n, s, mat in getattr(d, "leaf_bodies", []):
                out.append((f"{c['name']}/{n}", place(s, T), mat))
        else:
            out.append((c["name"], place(d.solid, T), d.material))
    return out


def combine(items):
    """items = [(properties of a part, 4x4 pose)] -> properties of the whole (same keys as evaluate.mass_properties)."""
    M = V = A = 0.0
    Msum = np.zeros(3)
    parts = []
    for pr, T in items:
        T = np.array(T, float)
        L, t = T[:3, :3], T[:3, 3]
        com = L @ pr["com"] + t
        parts.append((pr["mass"], com, L @ pr["ic"] @ L.T))
        M += pr["mass"]
        V += pr["volume"]
        A += pr["area"]
        Msum += pr["mass"] * com
    if M <= 0:
        return None
    com = Msum / M
    io = sum(ic + m * (float(c @ c) * np.eye(3) - np.outer(c, c)) for m, c, ic in parts)
    icm = io - M * (float(com @ com) * np.eye(3) - np.outer(com, com))
    w, v = np.linalg.eigh(icm)
    return {"volume": V, "area": A, "com": com, "mass": M, "ic": icm, "io": io, "pm": w, "axes": v.T}


def sub_doc(ctx, p, cfg=None):
    """The SubDoc of the assembly file p in configuration cfg (None = as saved).  None when it cannot be loaded (missing, or a loop)."""
    p = os.path.normcase(os.path.abspath(p))
    stack = tuple(getattr(ctx, "stack", ()))
    if p in stack or (getattr(ctx, "path", None) and os.path.normcase(os.path.abspath(ctx.path)) == p):
        raise SubLoop(p)
    text = _text(ctx, p)
    if text is None:
        return None
    cache = ctx.__dict__.setdefault("sub_cache", {})
    key = (p, cfg, hash(text))
    if key in cache:
        return cache[key]
    import asm_patterns
    L = Loader(p, getattr(ctx, "shell", None), stack + ((os.path.normcase(os.path.abspath(ctx.path)),) if getattr(ctx, "path", None) else ()) + (p,))
    L.path = p
    a = am.Assembly.from_json(text)
    L.asm = a
    L.wire(a)
    if cfg and cfg in a.cfg["names"] and cfg != a.cfg["active"]:
        a.cfg_apply(cfg)
    try:
        asm_patterns.rebuild_derived(L)
        a.solve()
        asm_patterns.rebuild_derived(L)
    except am.MateError:
        pass
    solids, items, names = [], [], []
    for c in a.components:
        if c.get("hidden") or c.get("suppressed"):
            continue
        src = a.comp(c["derived"]["src"]) if c.get("derived") else c
        d = L.part_doc(src) if src is not None else None
        if d is None or d.solid is None:
            continue
        T = a.T4(c)
        solids.append(place(d.solid, T))
        pr = d.mass_pr() if getattr(d, "is_sub", False) else evaluate.mass_properties(d.solid, d.material["density"])
        if pr is not None:
            items.append((pr, T))
        names.append(c["name"])
    doc = SubDoc()
    doc.sub_path = p
    doc.cfg = {"active": a.cfg["active"], "names": list(a.cfg["names"]), "cols": [], "cells": {}}
    doc.leaf_names = names
    doc.solid = Compound(solids) if solids else None
    doc._mass = combine(items)
    doc.leaf_bodies = bodies_of(L, a)
    doc.hidden_faces = buried_faces(doc.solid) if doc.solid is not None else set()
    doc.material = {"name": "Assembly", "density": (doc._mass["mass"] / doc._mass["volume"] * 1e9) if doc._mass else 1.0}
    if len(cache) > 20:
        cache.clear()
    cache[key] = doc
    return doc
