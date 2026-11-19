"""
solid_screw.py - SCREWS and BOLTS of a 3D FEA assembly: what a screw is, where it sits, and the checks of its connection.  No window.

A screw is placed on one or several PATCHES: faces between two parts (cut with the Split tool, so only the area of the screw is bonded).  Every patch is
bonded; the rest of the joint is frictionless contact (see solid_contact).  The FEA gives the force that passes through each patch: the shear V (in the plane
of the joint) and the tension T (along its normal).  This module turns them into checks:

  SCREW (self-drilling, self-tapping)   AISI S100-16 J4: the sheet's shear strength (tilting and bearing, J4.3.1), pull-out of the base sheet (J4.4.1),
                                        pull-over of the sheet at the head (J4.4.2), the screw's own shear and tension strength (J4.3.2, J4.4.3, as the maker
                                        gives them), the interactions (J4.5.1 to J4.5.3), the spacing (J4.1) and the edge distance (J4.2)
  BOLT                                  AISI S100-16 J3: the bearing of both sheets (J3.3.1), the bolt's own shear and tension (J3.4-1), shear with tension
                                        (J3.4-2), the spacing (J3.1) and the edge distance (J3.2).  No nut pull-out.

The equations are those of the Sheets add-on (std_aisi16), called directly: one set of equations for the spreadsheet and for this window.
A check is a ratio, demand / available strength (an interaction is its sum over what it may reach); 1.00 or less passes.
Units of this module: mm, N, MPa (the equations get inches, lbf and psi).
"""
import math
import types

import numpy as np

IN_MM = 25.4
PSI_PER_MPA = 145.03773773
LBF_N = 4.4482216152605

METHODS = {"ASD": "ASD (allowable strength)", "LRFD": "LRFD (factored loads)", "LSD": "LSD (limit states, Canada)", "nominal": "Nominal strength"}
HEADS = {"thin": "On the thinner part", "first": "On the first part of the joint", "second": "On the second part of the joint"}
KINDS = {"screw": "Screw (self-drilling / self-tapping)", "bolt": "Bolt"}


def default_screw(kind="screw"):
    """The numbers of a new screw or bolt (mm, N, MPa); a #10 screw (4.8 mm), 25 mm long, with a head of 9.5 mm."""
    s = {"kind": kind, "d": 4.8, "length": 25.0, "thread": 0.0, "dh": 9.5, "dw": 0.0, "tw": 0.0, "Pnvs": 0.0, "Pnts": 0.0, "head": "thin"}
    if kind == "bolt":
        s.update({"d": 12.0, "length": 0.0, "Fnv": 0.0, "Fnt": 0.0, "planes": 1})
    return s


NUMBERS = ("d", "length", "thread", "dh", "dw", "tw", "Pnvs", "Pnts", "Fnv", "Fnt", "planes")


def complete(s):
    """A stored screw with every number present."""
    d = default_screw(s.get("kind", "screw"))
    d.update({k: v for k, v in s.items() if k in d or k in ("name", "faces", "kind")})
    return d


def _aisi():
    """The AISI S100-16 module of the Sheets add-on, or None when that add-on is not there."""
    try:
        import std_aisi16
        return std_aisi16
    except Exception:                                                                 # noqa: BLE001 - the add-on may be missing; the forces are still shown
        return None


def _call(fn, method, warns=None, **vals):
    """Calls one equation of std_aisi16 (its argument names) with the method: the available strength, or for an interaction check its ratio."""
    a = types.SimpleNamespace(**vals)
    a.method = method

    def fac(omega, phi, phil):
        return {"nominal": 1.0, "ASD": 1.0 / omega, "LRFD": phi, "LSD": phil}[method]

    def cap(c, omega, phi, phil):
        return {"nominal": c / omega, "ASD": c / omega, "LRFD": c * phi, "LSD": c * phil}[method]
    a.fac, a.cap = fac, cap
    a.warn = (warns.append if warns is not None else (lambda t: None))
    return float(fn(a))


# ------------------------------------------------------------------------------------------------------------------------ where the screw is
def _pieces(geom, body):
    """The pieces (solids) of the fused assembly that belong to a body."""
    sol = geom["solid"].solids()
    return [sol[k] for k, p in enumerate(geom["solids"]) if p["body"] == body and k < len(sol)]


def thickness(geom, body, point, normal):
    """The thickness (mm) of a body at `point` of the joint, measured along `normal` (pointing into the body): the distance to where the line leaves it."""
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    eps = 1e-5 * max(geom["diag"], 1.0)
    best = None
    for p in _pieces(geom, body):
        it = IntCurvesFace_ShapeIntersector()
        it.Load(p.wrapped, 1e-6)
        it.Perform(gp_Lin(gp_Pnt(*[float(x) for x in point]), gp_Dir(*[float(x) for x in n])), eps, 1e9)
        ws = [it.WParameter(i) for i in range(1, it.NbPnt() + 1)]
        if ws:
            w = min(ws)
            best = w if best is None else max(best, w)
    if best is not None:
        return float(best)
    bb = [p.bounding_box() for p in _pieces(geom, body)]                           # no hit (the point is outside): the size of the body along the normal
    if not bb:
        return 0.0
    lo = np.min([[b.min.X, b.min.Y, b.min.Z] for b in bb], axis=0)
    hi = np.max([[b.max.X, b.max.Y, b.max.Z] for b in bb], axis=0)
    return float(abs(np.dot(hi - lo, n)))


def edge_distance(geom, fid):
    """The distance (mm) from the centre of a patch to the nearest edge of the whole face it was cut from (None when that cannot be found)."""
    import build123d as b
    faces = geom["faces"]
    f0 = faces[fid]
    solid_faces = geom["solid"].faces()
    par = f0.get("parent")
    ids = [f["id"] for f in faces if f.get("parent") == par and f["bodies"] == f0["bodies"] and f.get("interface")] if par is not None else [fid]
    if fid not in ids:
        ids.append(fid)
    count = {}
    for i in ids:
        for e in solid_faces[i].edges():
            key = hash(e.wrapped)
            for rec in count.setdefault(key, []):
                if rec[0].wrapped.IsSame(e.wrapped):
                    rec[1] += 1
                    break
            else:
                count[key].append([e, 1])
    edges = [rec[0] for lst in count.values() for rec in lst if rec[1] == 1]
    if not edges:
        return None
    c = b.Vector(*f0["center"])
    return float(min(e.distance_to(c) for e in edges))


def patch_centre(geom, fid):
    return list(geom["faces"][fid]["center"])


# ------------------------------------------------------------------------------------------------------------------------ the checks
def _row(name, clause, demand, cap, note="", unit="N"):
    r = {"name": name, "clause": clause, "demand": demand, "capacity": cap, "applies": True, "note": note, "unit": unit}
    r["ratio"] = (demand / cap) if (cap and cap > 0) else (0.0 if not demand else math.inf)
    return r


def _na(name, clause, why):
    return {"name": name, "clause": clause, "demand": None, "capacity": None, "ratio": None, "applies": False, "note": why, "unit": "N"}


def _outside(args_spec, vals):
    """What of `vals` {argument name: value in the specification's units} lies outside the limits the specification states for that argument."""
    out = []
    for a in args_spec:
        v = vals.get(a.name)
        if v is None:
            continue
        if (a.min is not None and v < a.min - 1e-12) or (a.max is not None and v > a.max + 1e-12):
            out.append(f"{a.symbol} = {v:.4g} {a.units} is outside {a.limits_text()}")
    return out


def evaluate(geom, sc, fid, forces, mats, method, spacing=None, other_centres=()):
    """The checks of one screw on one patch.  sc = the screw (see default_screw), forces = {"V", "T", "a", "b", "area"} of the patch (N), mats = the
    materials of the bodies, method = ASD / LRFD / LSD / nominal, spacing = the distance to the nearest other screw (mm) or None.
    Returns the record described in the README of the window: "checks", "worst", "worst_name", "status", "notes", the thicknesses ..."""
    std = _aisi()
    sc = complete(sc)
    a, b = forces["a"], forces["b"]
    names = [geom["bodies"][a]["name"], geom["bodies"][b]["name"]]
    c = np.array(patch_centre(geom, fid))
    n = np.asarray(forces["n"], float)
    ta = thickness(geom, a, c, -n)
    tb = thickness(geom, b, c, n)
    thin_first = ta <= tb
    head = {"first": True, "second": False}.get(sc["head"], thin_first)             # True: the head (and t1) is on body a
    h_body, base_body = (a, b) if head else (b, a)
    t1, t2 = (ta, tb) if head else (tb, ta)
    V = float(forces["V"])
    T = float(forces["T"])
    Tp = max(T, 0.0)                                                                  # a compression through the patch is not a pull on the screw
    out = {"fid": fid, "centre": [float(x) for x in c], "bodies": names, "a": a, "b": b, "V": V, "T": T, "Tp": Tp, "area": float(forces["area"]),
           "t1": t1, "t2": t2, "head_body": h_body, "base_body": base_body, "d": sc["d"], "kind": sc["kind"], "method": method, "checks": [], "notes": []}
    notes = out["notes"]
    if std is None:
        out.update({"worst": None, "worst_name": "", "status": "incomplete"})
        notes.append("The AISI checks come from the Sheets add-on, which is not installed here: only the forces are given.")
        return out
    fu1, fu2 = float(mats[h_body].get("su") or 0.0), float(mats[base_body].get("su") or 0.0)
    d_in, t1_in, t2_in = sc["d"] / IN_MM, t1 / IN_MM, t2 / IN_MM
    V_lb, T_lb = V / LBF_N, Tp / LBF_N
    Fu1, Fu2 = fu1 * PSI_PER_MPA, fu2 * PSI_PER_MPA
    funcs = {f.name: f for f in std.SCREW_FUNCS + std.BOLT_FUNCS}
    rows = out["checks"]
    eqv = math.pi / 4.0 * sc["d"] ** 2
    if out["area"] > 0 and out["area"] > 16.0 * eqv:
        notes.append(f"The patch is {out['area'] / eqv:.0f} times the area of the screw: it bonds more than a screw would hold, so the joint is stiffer than "
                     "in reality. Split the face so the patch is about the size of the screw.")
    if t1 <= 0 or t2 <= 0:
        notes.append("The thickness of a part could not be found at the screw.")
    if sc["kind"] == "bolt":
        _bolt(out, sc, funcs, method, d_in, t1_in, t2_in, Fu1, Fu2, V_lb, T_lb, names, h_body, base_body)
    else:
        _screw(out, sc, funcs, method, d_in, t1, t2, t1_in, t2_in, Fu1, Fu2, V_lb, T_lb, names, h_body, base_body)
    # spacing and edge distance (J4.1 / J4.2 or J3.1 / J3.2)
    sp_name, ed_name = ("J4.1", "J4.2") if sc["kind"] == "screw" else ("J3.1", "J3.2")
    sf, ef = funcs["J4_1" if sc["kind"] == "screw" else "J3_1"], funcs["J4_2" if sc["kind"] == "screw" else "J3_2"]
    smin = _call(sf.impl, method, d=d_in) * IN_MM
    emin = _call(ef.impl, method, d=d_in) * IN_MM
    if spacing:
        r = _row("Spacing to the nearest screw", sp_name, smin, spacing, f"least {smin:.3g} mm (3 d); here {spacing:.3g} mm")
        r["ratio"] = smin / spacing
        r["unit"] = "mm"
        rows.append(r)
    ed = edge_distance(geom, fid)
    if ed:
        r = _row("Edge distance", ed_name, emin, ed, f"least {emin:.3g} mm (1.5 d); here {ed:.3g} mm")
        r["ratio"] = emin / ed
        r["unit"] = "mm"
        rows.append(r)
    live = [r for r in rows if r["applies"] and r["ratio"] is not None]
    if not live:
        out.update({"worst": None, "worst_name": "", "status": "incomplete"})
        return out
    w = max(live, key=lambda r: r["ratio"])
    out["worst"], out["worst_name"] = float(w["ratio"]), f"{w['name']} ({w['clause']})"
    missing = [r for r in rows if not r["applies"] and r.get("missing")]
    out["status"] = "fails" if w["ratio"] > 1.0 + 1e-9 else ("incomplete" if missing else "ok")
    return out


def _screw(out, sc, funcs, method, d_in, t1, t2, t1_in, t2_in, Fu1, Fu2, V_lb, T_lb, names, h_body, base_body):
    rows, notes = out["checks"], out["notes"]
    if not (Fu1 > 0 and Fu2 > 0):
        nm_of = lambda body: names[0] if body == out["a"] else names[1]
        who = " and ".join(nm_of(bd) for bd, fu in ((h_body, Fu1), (base_body, Fu2)) if not fu > 0)
        notes.append(f"{who} has no tensile strength (Su) typed: the checks that need it cannot be made. Type it in the material.")
        for nm, cl in (("Shear: sheet tilting and bearing", "J4.3.1"), ("Pull-out of the base sheet", "J4.4.1"), ("Pull-over at the head", "J4.4.2")):
            x = _na(nm, cl, "needs the tensile strength Su of the parts")
            x["missing"] = True
            rows.append(x)
        return
    # how far the screw reaches: the threads that grip the base sheet
    L, lt = sc["length"], (sc["thread"] if sc["thread"] > 0 else sc["length"])
    reach = min(L, t1 + t2) - t1                                                      # the length of the screw inside the base sheet
    engaged = max(0.0, min(L, t1 + t2) - max(L - lt, t1))                              # of it, the threaded part
    tc = min(engaged, t2)
    out.update({"tc": tc, "through": L >= t1 + t2 - 1e-9, "reach": max(reach, 0.0)})
    if L < t1 + 1e-9:
        notes.append(f"The screw ({L:.3g} mm) is not longer than the part under its head ({t1:.3g} mm): it does not reach the base sheet.")
    elif L >= t1 + t2 - 1e-9:
        notes.append(f"The screw goes right through the base sheet ({t2:.3g} mm): pull-out uses the whole sheet thickness.")
    else:
        notes.append(f"The screw reaches {reach:.3g} mm into the base sheet ({t2:.3g} mm thick): pull-out uses {tc:.3g} mm of thread.")
    tc_in = tc / IN_MM
    # shear: the sheet
    cap = _call(funcs["J4_3_1"].impl, method, t1=t1_in, t2=t2_in, d=d_in, Fu1=Fu1, Fu2=Fu2) * LBF_N
    rows.append(_row("Shear: sheet tilting and bearing", "J4.3.1", out["V"], cap))
    if sc["Pnvs"] > 0:
        rows.append(_row("Shear: the screw itself", "J4.3.2", out["V"], _call(funcs["J4_3_2"].impl, method, Pnvs=sc["Pnvs"] / LBF_N) * LBF_N))
    else:
        x = _na("Shear: the screw itself", "J4.3.2", "type the shear strength the screw's maker gives")
        x["missing"] = True
        rows.append(x)
    # tension
    if tc > 0:
        rows.append(_row("Pull-out of the base sheet", "J4.4.1", out["Tp"], _call(funcs["J4_4_1"].impl, method, tc=tc_in, d=d_in, Fu2=Fu2) * LBF_N))
    else:
        rows.append(_row("Pull-out of the base sheet", "J4.4.1", out["Tp"], 0.0, "no thread in the base sheet"))
    warns = []
    dw_in = (sc["dw"] / IN_MM) or None
    tw_in = (sc["tw"] / IN_MM) or None
    cap = _call(funcs["J4_4_2"].impl, method, warns, t1=t1_in, dh=sc["dh"] / IN_MM, Fu1=Fu1, tw=tw_in, dw=dw_in) * LBF_N
    rows.append(_row("Pull-over at the head", "J4.4.2", out["Tp"], cap, "; ".join(warns)))
    if sc["Pnts"] > 0:
        rows.append(_row("Tension: the screw itself", "J4.4.3", out["Tp"], _call(funcs["J4_4_3"].impl, method, Pnts=sc["Pnts"] / LBF_N) * LBF_N))
    else:
        x = _na("Tension: the screw itself", "J4.4.3", "type the tension strength the screw's maker gives")
        x["missing"] = True
        rows.append(x)
    # the interactions (only when both a shear and a tension act, and the specification's limits are kept)
    dwb = max(sc["dh"], sc["dw"] or 0.0) / IN_MM
    if out["Tp"] > 0 and out["V"] > 0:
        j1 = funcs["J4_5_1"]
        bad = _outside(j1.args, {"t1": t1_in, "d": d_in, "dw": dwb, "Fu1": Fu1})
        if t2 / max(t1, 1e-12) < 2.5:
            bad.append(f"t2/t1 = {t2 / max(t1, 1e-12):.2f} is under 2.5")
        if bad:
            rows.append(_na("Shear + pull-over", "J4.5.1", "not used: " + "; ".join(bad)))
        else:
            r = _call(j1.impl, method, V=V_lb, T=T_lb, t1=t1_in, d=d_in, dw=dwb, Fu1=Fu1, eccentric="NO")
            rows.append({"name": "Shear + pull-over", "clause": "J4.5.1", "demand": r, "capacity": 1.0, "ratio": r, "applies": True, "note": "sum of the ratios", "unit": ""})
        j2 = funcs["J4_5_2"]
        bad = _outside(j2.args, {"t2": t2_in, "d": d_in, "Fu2": Fu2})
        if bad:
            rows.append(_na("Shear + pull-out", "J4.5.2", "not used: " + "; ".join(bad)))
        elif tc <= 0:
            rows.append(_na("Shear + pull-out", "J4.5.2", "no thread in the base sheet"))
        else:
            r = _call(j2.impl, method, V=V_lb, T=T_lb, t2=t2_in, tc=tc_in, d=d_in, Fu2=Fu2)
            rows.append({"name": "Shear + pull-out", "clause": "J4.5.2", "demand": r, "capacity": 1.0, "ratio": r, "applies": True, "note": "sum of the ratios", "unit": ""})
        if sc["Pnvs"] > 0 and sc["Pnts"] > 0:
            r = _call(funcs["J4_5_3"].impl, method, V=V_lb, T=T_lb, Pnvs=sc["Pnvs"] / LBF_N, Pnts=sc["Pnts"] / LBF_N)
            rows.append({"name": "Shear + tension in the screw", "clause": "J4.5.3", "demand": r, "capacity": 1.0, "ratio": r, "applies": True, "note": "sum of the ratios", "unit": ""})


def _bolt(out, sc, funcs, method, d_in, t1_in, t2_in, Fu1, Fu2, V_lb, T_lb, names, h_body, base_body):
    rows, notes = out["checks"], out["notes"]
    ab = math.pi / 4.0 * d_in ** 2
    planes = max(int(sc.get("planes") or 1), 1)
    if not (Fu1 > 0 and Fu2 > 0):
        notes.append("A part has no tensile strength (Su) typed: the bearing checks cannot be made.")
        x = _na("Bearing of the parts", "J3.3.1", "needs the tensile strength Su of the parts")
        x["missing"] = True
        rows.append(x)
    else:
        mf = _call(funcs["J3_3_1_mf"].impl, method, position="OUTER", holes="STANDARD", washers="BOTH")
        for nm, t, fu, body in (("Bearing: " + names[0], t1_in if h_body == out["a"] else t2_in, Fu1 if h_body == out["a"] else Fu2, out["a"]),
                                ("Bearing: " + names[1], t1_in if h_body == out["b"] else t2_in, Fu1 if h_body == out["b"] else Fu2, out["b"])):
            warns = []
            cap = _call(funcs["J3_3_1"].impl, method, warns, d=d_in, t=t, Fu=fu, mf=mf, holes="STANDARD") * LBF_N
            rows.append(_row(nm, "J3.3.1", out["V"], cap, "standard hole, washers under head and nut"))
    for nm, key, dem, k in (("Shear: the bolt", "Fnv", out["V"], planes), ("Tension: the bolt", "Fnt", out["Tp"], 1)):
        if sc.get(key, 0) > 0:
            cap = _call(funcs["J3_4_1"].impl, method, Ab=ab, Fn=sc[key] * PSI_PER_MPA) * LBF_N
            rows.append(_row(nm, "J3.4", dem, cap * k, f"{planes} shear planes" if k > 1 else ""))
        else:
            x = _na(nm, "J3.4", f"type the stress {key} of the bolt grade (Table J3.4-1)")
            x["missing"] = True
            rows.append(x)
    if sc.get("Fnv", 0) > 0 and sc.get("Fnt", 0) > 0 and out["Tp"] > 0 and method in ("ASD", "LRFD", "nominal"):
        fv = V_lb / (ab * planes)
        warns = []
        fnt_red = _call(funcs["J3_4_2"].impl, "ASD" if method == "nominal" else method, warns, Fnt=sc["Fnt"] * PSI_PER_MPA, Fnv=sc["Fnv"] * PSI_PER_MPA, fv=fv)
        r = (T_lb / ab) / fnt_red if fnt_red > 0 else math.inf
        rows.append({"name": "Shear + tension in the bolt", "clause": "J3.4", "demand": r, "capacity": 1.0, "ratio": r, "applies": True,
                     "note": "tension stress over the tension stress left after the shear; " + "; ".join(warns), "unit": ""})


# ------------------------------------------------------------------------------------------------------------------------ the mesh near a patch
def patch_size(area, h, hmin=0.0):
    """The element size (mm) wanted on a screw patch: a third of its size, never below the finest the mesher may make; None when the global size already is."""
    lp = math.sqrt(max(area, 1e-12))
    want = lp / 3.0
    lo = hmin if hmin else h / 6.0
    want = max(want, lo)
    return want if want < h * 0.999 else None
