"""Gear systems: a train of up to three gears, and a planetary set (sun, planets, ring).  Plain maths, no Qt, no CAD kernel.

The functions turn a few inputs into the parameters of each gear (the same dicts gears.* takes), the centre distances, the
ratios and the angles each part must be turned by for its teeth to mesh.  Angles are degrees, counter-clockwise looking down
the +Z axis; a part is first turned about its own axis by that angle and then moved to its position.

Centre distance with profile shift (transverse section, x_t = x cos(beta) in modules):
    inv(aw) = inv(at) + 2 tan(at) (x_t1 + x_t2) / (z1 + z2)        C = mt (z1 + z2) / 2 * cos(at) / cos(aw)
The tooth tips are shortened by  k = (x1 + x2) - (C - a0) / mn  (modules) so that the tip clearance stays what it was.
"""
import math

import gears

CLEARANCE = 0.25                                  # tip clearance in modules (the standard 1.25 - 1.0)


def inv_angle(v):
    """The angle a with  tan a - a = v  (Newton)."""
    if v <= 0:
        return 0.0
    a = (3 * v) ** (1 / 3)
    for _ in range(60):
        f = math.tan(a) - a - v
        d = math.tan(a) ** 2
        if d == 0:
            break
        na = a - f / d
        if abs(na - a) < 1e-15:
            a = na
            break
        a = na
    return a


def pair_centre(D1, D2):
    """Centre distance of two external gears (dims dicts) with their profile shifts, and the tip shortening k (in modules)."""
    z1, z2 = D1["z"], D2["z"]
    a0 = D1["mt"] * (z1 + z2) / 2
    xs = (D1["x"] + D2["x"]) * math.cos(D1["beta"])
    aw = inv_angle(gears.inv(D1["at"]) + 2 * math.tan(D1["at"]) * xs / (z1 + z2))
    C = a0 * math.cos(D1["at"]) / math.cos(aw)
    k = max(0.0, (D1["x"] + D2["x"]) - (C - a0) / D1["mn"])
    return {"C": C, "a0": a0, "aw": aw, "k": k}


def shift_for_centre(D1, z2, C):
    """Total profile shift (sum x1 + x2, in normal modules) that gives centre distance C for z1, z2; None if C is out of reach."""
    z1 = D1["z"]
    a0 = D1["mt"] * (z1 + z2) / 2
    c = a0 * math.cos(D1["at"]) / C
    if not 0 < c < 1:
        return None
    aw = math.acos(c)
    xt = (z1 + z2) * (gears.inv(aw) - gears.inv(D1["at"])) / (2 * math.tan(D1["at"]))
    return xt / math.cos(D1["beta"])


def contact_ratio(D1, D2, C):
    """Transverse contact ratio of an external pair with tips ra and centre distance C."""
    aw = math.acos((D1["rb"] + D2["rb"]) / C)
    s = math.sqrt(D1["ra"] ** 2 - D1["rb"] ** 2) + math.sqrt(D2["ra"] ** 2 - D2["rb"] ** 2) - C * math.sin(aw)
    return s / (math.pi * D1["mt"] * math.cos(D1["at"]))


def mesh_angle(zi, ai, zj, phi):
    """External pair.  Gear i has a tooth centre at angle ai (degrees) and gear j sits in direction phi (degrees) from it.
    Returns the angle of one tooth centre of gear j so the pair meshes (modulo its tooth pitch)."""
    ai, phi = math.radians(ai), math.radians(phi)
    a = phi + math.pi + math.pi / zj - (ai - phi) * zi / zj
    return math.degrees(a) % (360.0 / zj)


def mesh_angle_internal(zr, ar, zp, phi):
    """Planet in a ring.  The ring has a tooth centre at ar (degrees), the planet sits in direction phi from the ring axis."""
    ar, phi = math.radians(ar), math.radians(phi)
    a = phi + (ar - phi - math.pi / zr) * zr / zp
    return math.degrees(a) % (360.0 / zp)


def _hand_flip(h):
    return "left" if h == "right" else "right"


# ------------------------------------------------------------------------------------------------------------ gear train
def solve_train(g1, links, bend=180.0):
    """g1: parameters of gear 1 (module, teeth, pressure, helix, hand, width, bore, shift, backlash ... as gears.* take).
    links: one or two dicts, one per further gear, each  {"how": "ratio"|"teeth"|"centre"|"span", "value": number,
    "width":, "bore":}.   For a 3-gear train the SECOND link may be  how="span"  : value = total of both centre distances (the
    first link then gives the ratio / teeth of gear 2).   bend: angle at the middle gear between the two centre lines (180 = straight).
    Returns {"gears": [param dicts], "C": [centre distances], "pos": [(x, y)], "turn": [deg], "ratio": [...], "notes": [...]}."""
    notes = []
    gs = [dict(g1)]
    gs[0].setdefault("shift", 0.0)
    gs[0]["hand"] = g1.get("hand", "right")
    Cs, ks, pairs = [], [], []
    for n, link in enumerate(links):
        prev = gs[-1]
        Dp = gears.dims(prev)
        mt, mn = Dp["mt"], Dp["mn"]
        how, val = link["how"], float(link["value"])
        z1 = Dp["z"]
        target = None
        if how == "ratio":
            if val <= 0:
                raise ValueError("the ratio must be positive")
            z2 = max(3, int(round(z1 * val)))
        elif how == "teeth":
            z2 = max(3, int(round(val)))
        elif how in ("centre", "span"):
            target = val
            if how == "span":
                target = val - Cs[0]
            if target <= 0:
                raise ValueError("the centre distance must be positive")
            z2 = int(round(2 * target / mt - z1))
            if z2 < 6:
                raise ValueError(f"Gear {n + 2}: a centre distance of {target:.3f} mm leaves room for only {max(z2, 0)} teeth; "
                                 f"it must be at least {mt * (z1 + 6) / 2:.3f} mm" + (" (after gear 1-2 has taken its share of the total)" if how == "span" else ""))
        else:
            raise ValueError(f"unknown way to size a gear: {how}")
        g = dict(prev)
        g.update(teeth=z2, width=link.get("width", prev["width"]), bore=link.get("bore", prev["bore"]), shift=0.0,
                 hand=_hand_flip(prev["hand"]) if Dp["beta"] else prev["hand"], add=1.0)
        gears_prev = gears.dims(prev)
        a0 = mt * (z1 + z2) / 2
        if target is not None:
            gap = target - a0
            S = shift_for_centre(gears_prev, z2, target)
            if S is not None and abs(gap) <= 0.5 * mn:
                g["shift"] = S - float(prev.get("shift", 0))
                if abs(gap) > 1e-6:
                    notes.append(f"Gear {n + 2}: {z2} teeth is the nearest whole number; the remaining {gap:+.3f} mm of centre distance is "
                                 f"made up with profile shift (x total {S:+.3f}).")
            else:
                notes.append(f"Gear {n + 2}: the nearest centre distance that {z2} teeth can reach is {a0:.3f} mm "
                             f"(asked {target:.3f}; {gap:+.3f} mm is more than half a module, so no profile shift is used).")
        D2 = gears.dims(g)
        pc = pair_centre(gears_prev, D2)
        Cs.append(pc["C"])
        ks.append(pc["k"])
        pairs.append(pc)
        gs.append(g)
    # shorten the tips by k: gear i belongs to pair i-1 and pair i, so it takes the larger k
    for i, g in enumerate(gs):
        k = max([ks[j] for j in (i - 1, i) if 0 <= j < len(ks)] or [0.0])
        g["add"] = 1.0 - k
    ds = [gears.dims(g) for g in gs]
    # re-evaluate the centre distance from the final shifts (does not depend on the tips)
    ratio = [ds[i + 1]["z"] / ds[i]["z"] for i in range(len(ds) - 1)]
    pos = [(0.0, 0.0), (Cs[0], 0.0)]
    phi = [0.0]
    if len(gs) == 3:
        phi23 = 180.0 - bend
        phi.append(phi23)
        pos.append((Cs[0] + Cs[1] * math.cos(math.radians(phi23)), Cs[1] * math.sin(math.radians(phi23))))
    turn = [0.0, mesh_angle(ds[0]["z"], 0.0, ds[1]["z"], 0.0)]
    if len(gs) == 3:
        turn.append(mesh_angle(ds[1]["z"], turn[1], ds[2]["z"], phi[1]))
    cr = [contact_ratio(ds[i], ds[i + 1], Cs[i]) for i in range(len(Cs))]
    for i, c in enumerate(cr):
        if c < 1.2:
            notes.append(f"Gear {i + 1}-{i + 2}: contact ratio {c:.2f} is low (below about 1.2 the teeth hand over roughly).")
    for i, D in enumerate(ds):
        if D["undercut"] and float(gs[i].get("shift", 0)) <= 0:
            notes.append(f"Gear {i + 1} ({D['z']} teeth) is undercut at {math.degrees(D['an']):g} deg; use more teeth or a positive profile shift.")
    return {"gears": gs, "dims": ds, "C": Cs, "pos": pos, "turn": turn, "ratio": ratio, "total_ratio": math.prod(ratio),
            "contact": cr, "notes": notes, "phi": phi}


# ------------------------------------------------------------------------------------------------------------ planetary
def planet_checks(zs, zp, zr, n, D_planet, C):
    """(ok, reason) for N planets equally spaced."""
    if (zs + zr) % n:
        return False, f"({zs} + {zr}) is not divisible by {n}"
    if n > 1 and 2 * C * math.sin(math.pi / n) < D_planet["da"] + 0.5 * D_planet["mn"]:
        return False, f"{n} planets would touch each other"
    return True, ""


def solve_planetary(base, given, zs=None, zp=None, zr=None, n=3, widths=None, bores=None, rim=None):
    """base: module, pressure, helix, hand (the SUN's hand), backlash.   given: which two of ("sun", "planet", "ring") are set.
    Returns the three part-parameter dicts, centre distance, ratios, planet counts and the angles for mounting."""
    notes = []
    if given == "sun+planet":
        zr = zs + 2 * zp
    elif given == "ring+planet":
        zs = zr - 2 * zp
    elif given == "sun+ring":
        if (zr - zs) % 2:
            notes.append(f"Ring minus sun must be even for a whole planet: {zr - zs} is odd. Nearest: ring {zr - 1} or {zr + 1}.")
            zr = zr + 1
            notes.append(f"Using {zr} ring teeth.")
        zp = (zr - zs) // 2
    else:
        raise ValueError("choose which two gears set the size")
    if zs < 3 or zp < 3 or zr < zs + 2 * zp:
        raise ValueError("these tooth counts do not fit: the ring needs sun + 2 x planet teeth")
    hand = base.get("hand", "right")
    beta = float(base.get("helix", 0))
    widths = widths or {"sun": 10, "planet": 10, "ring": 10}
    bores = bores or {"sun": 8, "planet": 4}
    common = {"module": base["module"], "pressure": base.get("pressure", 20), "helix": beta, "backlash": base.get("backlash", 0)}
    sun = {**common, "teeth": zs, "width": widths["sun"], "bore": bores["sun"], "shift": 0.0, "add": 1.0, "ded": 1.25, "hand": hand}
    planet = {**common, "teeth": zp, "width": widths["planet"], "bore": bores["planet"], "shift": 0.0, "add": 1.0, "ded": 1.25,
              "hand": _hand_flip(hand) if beta else hand}
    ring = {**common, "teeth": zr, "width": widths["ring"], "add": 1.0, "ded": 1.25, "hand": planet["hand"]}
    Ds, Dp = gears.dims(sun), gears.dims(planet)
    Dr = gears.ring_dims({**ring})
    rim = rim if rim is not None else 2.5 * base["module"]
    ring["rim"] = rim
    C = Ds["mt"] * (zs + zp) / 2
    # planets that fit: equal spacing needs (zs + zr) divisible by N, and they must not touch each other
    valid = [k for k in range(1, 13) if planet_checks(zs, zp, zr, k, Dp, C)[0]]
    ok, why = planet_checks(zs, zp, zr, n, Dp, C)
    if not ok:
        near = sorted(valid, key=lambda k: (abs(k - n), k))[:3]
        notes.append(f"{n} planets do not work: {why}. Planet counts that do: {', '.join(map(str, valid)) or 'none'}"
                     + (f" (nearest {near[0]})." if near else "."))
        alt = []
        for ds in (-1, 1, -2, 2, -3, 3):
            for dp in (0, -1, 1):
                z1, z2 = zs + ds, zp + dp
                if z1 >= 3 and z2 >= 3 and (z1 + z1 + 2 * z2) % n == 0:
                    alt.append((abs(ds) + abs(dp), z1, z2))
        alt.sort()
        if alt:
            notes.append("For " + str(n) + " planets, nearby tooth counts: " + "; ".join(f"sun {a} / planet {b}" for _, a, b in alt[:3]) + ".")
    # mounting: the sun is not turned.  Planet 0 sits on +X and is turned to mesh the sun; the ring is built turned by `ring_phase`
    # so that this same planet angle also meshes the ring (the ring's tooth spaces start on the +X axis when the phase is 0).
    p0 = mesh_angle(zs, 0.0, zp, 0.0)
    planet_turn = []
    ring_phase = (p0 * zp / zr) % (360.0 / zr)
    for i in range(max(1, n)):
        phi = 360.0 * i / n
        planet_turn.append(mesh_angle(zs, 0.0, zp, phi))
    ring["phase"] = ring_phase
    ratio = {"ring fixed (sun in, carrier out)": 1 + zr / zs, "sun fixed (ring in, carrier out)": 1 + zs / zr,
             "carrier fixed (sun in, ring out)": -zr / zs, "carrier fixed (sun in, planet out)": -zs / zp}
    return {"sun": sun, "planet": planet, "ring": ring, "zs": zs, "zp": zp, "zr": zr, "C": C, "ratios": ratio, "valid_n": valid,
            "n": n, "n_ok": ok, "planet_turn": planet_turn, "ring_phase": ring_phase, "notes": notes,
            "dims": {"sun": Ds, "planet": Dp, "ring": Dr}}
