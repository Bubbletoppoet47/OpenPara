"""
std_aisi16.py - AISI S100-16, North American Specification for the Design of Cold-Formed Steel Structural Members (2016 edition), Chapter J: connections.

Screws (J4), bolts (J3, with J3.4 of Appendix A) and welds (J2), written as cell formulas  =AISI16.J4_4_1(tc, d, Fu2) .
The equations and section numbers are the specification's; the wording here is our own.  The specification itself is AISI's copyrighted document: get it
from AISI, and check any result you rely on against it.

Units: inches, psi, lbf.  The method argument (last): "nominal" (default), "ASD", "LRFD" or "LSD".  The interaction checks return the sum divided by what
it may reach, so 1.00 or less passes (they default to ASD).
"""
import math

import sh_std as S
from sh_std import Arg as A
from sh_std import StdFunc as F

E_STEEL = 29_500_000.0          # psi (29,500 ksi)
KSI = 1000.0

SCREW = ("Connections", "Screws")
BOLT = ("Connections", "Bolts")


def _x(t, units="in"):
    return A("t", t, units)


# ------------------------------------------------------------------------------------------------------------------ screws (J4)
def j4_3_1(a):
    t1, t2, d, f1, f2 = a.t1, a.t2, a.d, a.Fu1, a.Fu2
    r = t2 / t1
    p_a = min(4.2 * math.sqrt(t2 ** 3 * d) * f2, 2.7 * t1 * d * f1, 2.7 * t2 * d * f2)
    p_b = min(2.7 * t1 * d * f1, 2.7 * t2 * d * f2)
    p = p_a if r <= 1.0 else p_b if r >= 2.5 else p_a + (r - 1.0) / 1.5 * (p_b - p_a)
    return p * a.fac(3.0, 0.5, 0.4)


def j4_3_2(a):
    return a.Pnvs * a.fac(3.0, 0.5, 0.4)


def j4_4_1(a):
    return 0.85 * a.tc * a.d * a.Fu2 * a.fac(3.0, 0.5, 0.4)


def j4_4_2(a):
    if a.tw:
        dp = a.dh + 2.0 * a.tw + a.t1
        if a.dw:
            dp = min(dp, a.dw)
    else:
        dp = min(a.dh, 0.75)
    if max(a.dh, a.dw or 0.0) < 0.3125:
        a.warn("The head or washer is under 5/16 in. (0.3125), the least J4.4 allows for a screw in tension")
    return 1.5 * a.t1 * dp * a.Fu1 * a.fac(3.0, 0.5, 0.4)


def j4_4_3(a):
    return a.Pnts * a.fac(3.0, 0.5, 0.4)


def j4_5_1(a):
    pnv = 2.7 * a.t1 * a.d * a.Fu1
    pnov = 1.5 * a.t1 * a.dw * a.Fu1 * (0.5 if a.eccentric == "YES" else 1.0)
    return (a.V / pnv + 0.71 * a.T / pnov) / a.cap(1.10, 2.35, 0.65, 0.55)


def j4_5_2(a):
    pnv = 4.2 * math.sqrt(a.t2 ** 3 * a.d) * a.Fu2
    pnot = 0.85 * a.tc * a.d * a.Fu2
    return (a.V / pnv + a.T / pnot) / a.cap(1.15, 2.55, 0.60, 0.50)


def j4_5_3(a):
    return (a.V / a.Pnvs + a.T / a.Pnts) / a.cap(1.3, 3.0, 0.5, 0.4)


SCREW_FUNCS = [
    F("J4_1", "J4.1", "Screw spacing", "Least distance between screw centres", "smin = 3 · d", [A("d", "Screw diameter", "in", example=0.19)], lambda a: 3.0 * a.d, SCREW,
      units="in", keywords="spacing pitch minimum"),
    F("J4_2", "J4.2", "Screw edge distance", "Least distance from screw centre to an edge", "emin = 1.5 · d", [A("d", "Screw diameter", "in", example=0.19)],
      lambda a: 1.5 * a.d, SCREW, units="in", keywords="edge end distance minimum"),
    F("J4_3_1", "J4.3.1", "Screw shear (tilting and bearing)", "Shear strength of the sheet, per screw",
      "t2/t1 ≤ 1:  Pnv = least of 4.2·√(t2³·d)·Fu2,  2.7·t1·d·Fu1,  2.7·t2·d·Fu2\nt2/t1 ≥ 2.5:  Pnv = least of 2.7·t1·d·Fu1,  2.7·t2·d·Fu2\nin between: straight-line interpolation",
      [A("t1", "Sheet under the screw head", "in", example=0.0345, symbol="t1"), A("t2", "Sheet the screw ends in", "in", example=0.0747, symbol="t2"),
       A("d", "Screw diameter", "in", min=0.08, max=0.25, limit_ref="J4", example=0.19), A("Fu1", "Tensile strength of t1", "psi", example=45000, symbol="Fu1"),
       A("Fu2", "Tensile strength of t2", "psi", example=58000, symbol="Fu2")],
      j4_3_1, SCREW, eq="J4.3.1-1 to -5", factors=(3.0, 0.5, 0.4), notes=("Screw's own shear strength: see J4.3.2.", "The strength is also limited by Chapter D."),
      keywords="shear tilting bearing sheet connection"),
    F("J4_3_2", "J4.3.2", "Screw shear (the screw itself)", "The screw's own shear strength, from its maker", "Pnvs = value reported by the manufacturer or a test lab",
      [A("Pnvs", "Shear strength of the screw", "lbf", example=3313.4)], j4_3_2, SCREW, factors=(3.0, 0.5, 0.4),
      notes=("Gives the available strength of a strength you already know.",), keywords="screw shear manufacturer"),
    F("J4_4_1", "J4.4.1", "Screw pull-out", "Screw pulls out of the base steel", "Pnot = 0.85 · tc · d · Fu2",
      [A("tc", "Lesser of thread depth and t2", "in", example=0.0747), A("d", "Screw diameter", "in", min=0.08, max=0.25, limit_ref="J4", example=0.1875),
       A("Fu2", "Tensile strength of the base steel", "psi", example=58000, symbol="Fu2")],
      j4_4_1, SCREW, eq="J4.4.1-1", factors=(3.0, 0.5, 0.4), notes=("tc is the thickness the threads grip.",), keywords="pull out pullout withdrawal tension"),
    F("J4_4_2", "J4.4.2", "Screw pull-over", "Sheet pulls over the screw head or washer", "Pnov = 1.5 · t1 · d'w · Fu1\nd'w = dh + 2·tw + t1 ≤ dw  with a washer;   d'w = dh ≤ 3/4 in  without",
      [A("t1", "Sheet under the head or washer", "in", example=0.058, symbol="t1"), A("dh", "Screw head diameter", "in", example=0.4),
       A("Fu1", "Tensile strength of t1", "psi", example=70000, symbol="Fu1"),
       A("tw", "Washer thickness (blank: no washer)", "in", optional=True, symbol="tw"), A("dw", "Washer diameter (limits d'w)", "in", optional=True)],
      j4_4_2, SCREW, eq="J4.4.2-1, -2", factors=(3.0, 0.5, 0.4),
      notes=("Leave tw and dw blank for a head with no separate washer.", "A head or washer under 5/16 in. is not allowed for tension."),
      keywords="pull over pullover head washer tension"),
    F("J4_4_3", "J4.4.3", "Screw tension (the screw itself)", "The screw's own tension strength, from its maker", "Pnts = value reported by the manufacturer or a test lab",
      [A("Pnts", "Tension strength of the screw", "lbf", example=2200)], j4_4_3, SCREW, factors=(3.0, 0.5, 0.4), keywords="screw tension manufacturer"),
    F("J4_5_1", "J4.5.1", "Shear + pull-over", "Interaction check; 1.00 or less passes", "V/Pnv + 0.71·T/Pnov ≤ 1.10/Ω   (ASD)\nPnv = 2.7·t1·d·Fu1,   Pnov = 1.5·t1·dw·Fu1",
      [A("V", "Shear per screw (required)", "lbf", positive=False, example=150), A("T", "Tension per screw (required)", "lbf", positive=False, example=80),
       A("t1", "Sheet under the head or washer", "in", min=0.0285, max=0.0445, limit_ref="J4.5.1", example=0.036, symbol="t1"),
       A("d", "Screw diameter", "in", min=0.21, max=0.25, limit_ref="J4.5.1: No. 12 or 14", example=0.216),
       A("dw", "Larger of head and washer diameter", "in", max=0.75, limit_ref="J4.5.1", example=0.5),
       A("Fu1", "Tensile strength of t1", "psi", max=70000, limit_ref="J4.5.1", example=55000, symbol="Fu1"),
       A("eccentric", "yes: uneven pull-over (counts 50 %)", kind="text", optional=True, choices=("no", "yes"), default="NO")],
      j4_5_1, SCREW, eq="J4.5.1-1, -2, -3", units="ratio", check=True,
      notes=("Also needs t2/t1 of 2.5 or more.", "V and T must each stay under their own available strengths (J4.3, J4.4)."), keywords="combined interaction shear tension pull over"),
    F("J4_5_2", "J4.5.2", "Shear + pull-out", "Interaction check; 1.00 or less passes", "V/Pnv + T/Pnot ≤ 1.15/Ω   (ASD)\nPnv = 4.2·√(t2³·d)·Fu2,   Pnot = 0.85·tc·d·Fu2",
      [A("V", "Shear per screw (required)", "lbf", positive=False, example=150), A("T", "Tension per screw (required)", "lbf", positive=False, example=80),
       A("t2", "Base steel thickness", "in", min=0.0297, max=0.0724, limit_ref="J4.5.2", example=0.0575, symbol="t2"),
       A("tc", "Lesser of thread depth and t2", "in", example=0.0575),
       A("d", "Screw diameter", "in", min=0.164, max=0.25, limit_ref="J4.5.2: No. 8 to 14", example=0.19),
       A("Fu2", "Tensile strength of the base steel", "psi", max=121000, limit_ref="J4.5.2", example=58000, symbol="Fu2")],
      j4_5_2, SCREW, eq="J4.5.2-1, -2, -3", units="ratio", check=True, notes=("Also needs Fu/Fy between 1.0 and 1.62.",), keywords="combined interaction shear tension pull out"),
    F("J4_5_3", "J4.5.3", "Shear + tension in the screw", "Interaction check; 1.00 or less passes", "V/Pnvs + T/Pnts ≤ 1.3/Ω   (ASD)",
      [A("V", "Shear per screw (required)", "lbf", positive=False, example=150), A("T", "Tension per screw (required)", "lbf", positive=False, example=80),
       A("Pnvs", "Shear strength of the screw", "lbf", example=3313), A("Pnts", "Tension strength of the screw", "lbf", example=2200)],
      j4_5_3, SCREW, eq="J4.5.3-1", units="ratio", check=True, keywords="combined interaction shear tension screw"),
]


# ------------------------------------------------------------------------------------------------------------------ bolts (J3, J3.4 of Appendix A)
_MF = {("OUTER", "STANDARD", "BOTH"): 1.00, ("OUTER", "STANDARD", "FEWER"): 0.75, ("OUTER", "PARALLEL", "FEWER"): 0.70, ("OUTER", "PERPENDICULAR", "FEWER"): 0.55,
       ("INNER", "STANDARD", "BOTH"): 1.33, ("INNER", "STANDARD", "FEWER"): 1.33, ("INNER", "PARALLEL", "BOTH"): 1.10, ("INNER", "PARALLEL", "FEWER"): 1.10,
       ("INNER", "PERPENDICULAR", "BOTH"): 0.90, ("INNER", "PERPENDICULAR", "FEWER"): 0.90}


def j3_3_1_mf(a):
    v = _MF.get((a.position, a.holes, a.washers))
    if v is None:
        a.warn("Table J3.3.1-2 has no row for oversized or slotted holes in an outer sheet with a washer under both head and nut")
        return S.E.NA
    return v


def j3_3_1(a):
    r = a.d / a.t
    if a.holes == "OVERSIZED":
        c = 3.0 if r < 7 else (1.0 + 14.0 / r if r <= 18 else 1.8)
    else:
        c = 3.0 if r < 10 else (4.0 - 0.1 * r if r <= 22 else 1.8)
    return c * a.mf * a.d * a.t * a.Fu * a.fac(2.5, 0.6, 0.5)


def j3_3_2(a):
    return (4.64 * a.t + 1.53) * a.d * a.t * a.Fu * a.fac(2.22, 0.65, 0.55)


def j3_4_1(a):
    if a.method == "LSD":
        a.warn("Appendix A gives no LSD value for bolts")
        return S.E.NA
    return a.Ab * a.Fn * a.fac(2.0, 0.75, 0.0)


def j3_4_2(a):
    if a.method == "LSD":
        a.warn("Appendix A gives no LSD value for bolts")
        return S.E.NA
    if a.method == "LRFD":
        f = 1.3 * a.Fnt - a.Fnt / (0.75 * a.Fnv) * a.fv
        if a.fv > 0.75 * a.Fnv:
            a.warn("The shear stress fv is above φ·Fnv (0.75·Fnv)")
    else:
        f = 1.3 * a.Fnt - 2.0 * a.Fnt / a.Fnv * a.fv
        if a.fv > a.Fnv / 2.0:
            a.warn("The shear stress fv is above Fnv/Ω (Fnv/2.00)")
    return min(f, a.Fnt)


_WASH = ("both", "fewer")
BOLT_FUNCS = [
    F("J3_1", "J3.1", "Bolt spacing", "Least distance between bolt centres", "smin = 3 · d", [A("d", "Bolt diameter", "in", example=0.5)], lambda a: 3.0 * a.d, BOLT,
      units="in", notes=("Oversized or slotted holes: the clear gap between holes is at least 2d.",), keywords="spacing pitch minimum"),
    F("J3_2", "J3.2", "Bolt edge distance", "Least distance from bolt centre to an edge", "emin = 1.5 · d", [A("d", "Bolt diameter", "in", example=0.5)], lambda a: 1.5 * a.d, BOLT,
      units="in", notes=("Oversized or slotted holes: hole edge to member edge is at least d.",), keywords="edge end distance minimum"),
    F("J3_3_1_mf", "J3.3.1", "Bearing: connection factor mf", "Looks up mf in Table J3.3.1-2", "mf from the table",
      [A("position", "Sheet: outer (or single shear) / inner", kind="text", choices=("outer", "inner"), symbol="position", example="outer"),
       A("holes", "Hole type (relative to the load)", kind="text", choices=("standard", "parallel", "perpendicular"), symbol="holes", example="standard"),
       A("washers", "Washers under head and nut", kind="text", choices=_WASH, symbol="washers", example="both")],
      j3_3_1_mf, BOLT, units="", notes=("parallel: oversized or short-slotted along the load; perpendicular: short-slotted across it.",), keywords="modification factor table"),
    F("J3_3_1", "J3.3.1", "Bolt bearing (no hole deformation)", "Bearing strength of the sheet, per bolt", "Pnb = C · mf · d · t · Fu\nC from d/t and hole type (Table J3.3.1-1)",
      [A("d", "Bolt diameter", "in", example=0.5), A("t", "Sheet thickness", "in", min=0.024, max=0.1875, limit_ref="Table J3.3.1-1", example=0.0747),
       A("Fu", "Tensile strength of the sheet", "psi", example=58000, symbol="Fu"), A("mf", "Connection factor (see J3_3_1_mf)", "", example=1.0),
       A("holes", "standard, or oversized (incl. short-slotted)", kind="text", optional=True, choices=("standard", "oversized"), default="STANDARD")],
      j3_3_1, BOLT, eq="J3.3.1-1", factors=(2.5, 0.6, 0.5), keywords="bearing bolt sheet"),
    F("J3_3_2", "J3.3.2", "Bolt bearing (hole deformation counted)", "Bearing strength when the hole may deform", "Pnb = (4.64·t + 1.53) · d · t · Fu   (inches)",
      [A("d", "Bolt diameter", "in", example=0.5), A("t", "Sheet thickness", "in", example=0.0747), A("Fu", "Tensile strength of the sheet", "psi", example=58000, symbol="Fu")],
      j3_3_2, BOLT, eq="J3.3.2-1", factors=(2.22, 0.65, 0.55), notes=("Do not use more than the J3.3.1 value: take the smaller.",), keywords="bearing bolt hole deformation"),
    F("J3_4_1", "J3.4", "Bolt shear or tension", "Strength of the bolt itself", "Pn = Ab · Fn\nFn = Fnv or Fnt from Table J3.4-1",
      [A("Ab", "Gross area of the bolt", "in²", example=0.196), A("Fn", "Fnv or Fnt for the bolt grade", "psi", example=54000)],
      j3_4_1, BOLT, eq="J3.4-1", factors=(2.0, 0.75, 0.0), notes=("Appendix A (US, Mexico): ASD and LRFD only.", "Enter the Table J3.4-1 stress for the bolt grade."), keywords="bolt shear tension area"),
    F("J3_4_2", "J3.4", "Bolt tension reduced by shear", "Tension stress left when the bolt also carries shear", "F'nt = 1.3·Fnt − (Ω·Fnt/Fnv)·fv ≤ Fnt   (ASD)\nF'nt = 1.3·Fnt − Fnt/(φ·Fnv)·fv ≤ Fnt   (LRFD)",
      [A("Fnt", "Tension stress, Table J3.4-1", "psi", example=90000), A("Fnv", "Shear stress, Table J3.4-1", "psi", example=54000),
       A("fv", "Shear stress needed", "psi", positive=False, example=10000)],
      j3_4_2, BOLT, eq="J3.4-2, -3", units="psi", check=True, notes=("Returns F'nt; the bolt carries F'nt × Ab in tension.", "Appendix A (US, Mexico): ASD and LRFD only."),
      keywords="bolt combined shear tension"),
]


# ------------------------------------------------------------------------------------------------------------------ welds (J2)
def _de(a):
    de = min(0.7 * a.d - 1.5 * a.t, 0.55 * a.d)
    if de <= 0:
        a.warn("The effective diameter 0.7d − 1.5t is zero or less: the weld is too small for this sheet")
        raise ValueError
    return de


def j2_1_1(a):
    return a.L * a.te * a.Fy * a.fac(1.70, 0.90, 0.80)


def j2_1_2(a):
    return min(a.L * a.te * 0.6 * a.Fxx * a.fac(1.90, 0.80, 0.70), a.L * a.te * a.Fy / math.sqrt(3.0) * a.fac(1.70, 0.90, 0.80))


def j2_2_2_1(a):
    de = _de(a)
    da = a.d - a.t
    if de < 0.375:
        a.warn("The effective diameter is under 3/8 in., the least J2.2 allows")
    pa = math.pi / 4.0 * de ** 2 * 0.75 * a.Fxx * a.fac(2.55, 0.60, 0.50)
    k = math.sqrt(a.E / a.Fu)
    r = da / a.t
    if r <= 0.815 * k:
        pb = 2.20 * a.t * da * a.Fu * a.fac(2.20, 0.70, 0.60)
    elif r < 1.397 * k:
        pb = 0.280 * (1.0 + 5.59 * k / r) * a.t * da * a.Fu * a.fac(2.80, 0.55, 0.45)
    else:
        pb = 1.40 * a.t * da * a.Fu * a.fac(3.05, 0.50, 0.40)
    return min(pa, pb)


def j2_2_2_2(a):
    if a.Fu > 59000:
        a.warn("Fu is above 59 ksi, the most J2.2.2.2 allows")
    if a.Fxx <= a.Fu:
        a.warn("Fxx must be larger than Fu (J2.2.2.2)")
    return 1.65 * a.t * (a.d - a.t) * a.Fu * a.fac(2.20, 0.70, 0.60)


def j2_2_3(a):
    de = _de(a)
    da = a.d - a.t
    pa = math.pi / 4.0 * de ** 2 * a.Fxx
    pb = 0.8 * (a.Fu / a.Fy) ** 2 * a.t * da * a.Fu
    if a.t * da * a.Fu > 3000.0:
        a.warn("t·da·Fu is above 3 kips, the most J2.2.3 allows")
    if a.Fxx < 60000.0:
        a.warn("Fxx is under 60 ksi (J2.2.3)")
    if a.Fu > 82000.0:
        a.warn("Fu is above 82 ksi (J2.2.3)")
    if a.Fxx <= a.Fu:
        a.warn("Fxx must be larger than Fu (J2.2.3)")
    f = a.fac(2.50, 0.60, 0.50) if a.deck == "YES" else a.fac(3.00, 0.50, 0.40)
    return min(pa, pb) * f


def j2_2_4(a):
    tt = (a.T / a.Pat) ** 1.5
    if tt <= 0.15:
        a.warn("(T/Pat)^1.5 is 0.15 or less: no interaction check is needed")
    return (a.V / a.Pav) ** 1.5 + tt


def j2_3_2_1(a):
    de = 0.7 * a.d - 1.5 * a.t
    if de <= 0:
        a.warn("The effective width 0.7d − 1.5t is zero or less: the weld is too small for this sheet")
        raise ValueError
    da = a.d - a.t
    L = a.L
    if L > 3.0 * a.d:
        a.warn("L is above 3d: 3d is used (J2.3.2.1)")
        L = 3.0 * a.d
    pa = (math.pi / 4.0 * de ** 2 + L * de) * 0.75 * a.Fxx
    pb = 2.5 * a.t * a.Fu * (0.25 * L + 0.96 * da)
    return min(pa, pb) * a.fac(2.55, 0.60, 0.50)


def j2_5(a):
    t = min(a.t1, a.t2)
    if a.load == "TRANSVERSE":
        p1, p2 = a.t1 * a.L * a.Fu1, a.t2 * a.L * a.Fu2
        f = a.fac(2.35, 0.65, 0.60)
    elif a.L / t < 25.0:
        p1, p2 = (1.0 - 0.01 * a.L / a.t1) * a.t1 * a.L * a.Fu1, (1.0 - 0.01 * a.L / a.t2) * a.t2 * a.L * a.Fu2
        f = a.fac(2.55, 0.60, 0.50)
    else:
        p1, p2 = 0.75 * a.t1 * a.L * a.Fu1, 0.75 * a.t2 * a.L * a.Fu2
        f = a.fac(3.05, 0.50, 0.40)
    p = min(p1, p2) * f
    if t > 0.10:
        if a.w and a.Fxx:
            p = min(p, 0.75 * 0.707 * a.w * a.L * a.Fxx * a.fac(2.55, 0.60, 0.50))
        else:
            a.warn("The thinner sheet is over 0.10 in.: give w and Fxx so the weld-metal limit (J2.5-7) is applied")
    return p


def j2_6(a):
    k, fa = {"BEVEL": (0.833, (2.55, 0.60, 0.50)), "LONG": (0.75, (2.80, 0.55, 0.45)), "LONG-LIP": (1.50, (2.80, 0.55, 0.45))}[a.case]
    if a.t > 0.10:
        a.warn("The sheet is over 0.10 in.: also check the weld-metal limit, Eq. J2.6-4")
    return k * a.t * a.L * a.Fu * a.fac(*fa)


def j2_7(a):
    kips = 144.0 * a.t ** 1.47 if a.t < 0.14 else 43.4 * a.t + 1.93
    return kips * 1000.0 * a.fac(2.35, 0.65, 0.55)


WELD = ("Connections", "Welds")
WELD_FUNCS = [
    F("J2_1_1", "J2.1", "Groove weld, tension or compression", "Butt weld loaded square to its throat", "Pn = L · te · Fy",
      [A("L", "Weld length", "in", example=6.0), A("te", "Effective throat", "in", example=0.075), A("Fy", "Yield stress of the weaker base steel", "psi", example=50000, symbol="Fy")],
      j2_1_1, WELD[:1] + ("Welds", "Groove"), eq="J2.1-1", factors=(1.70, 0.90, 0.80), keywords="groove butt weld tension compression"),
    F("J2_1_2", "J2.1", "Groove weld, shear", "Butt weld loaded along its length", "Pn = smaller of L·te·0.6·Fxx and L·te·Fy/√3",
      [A("L", "Weld length", "in", example=6.0), A("te", "Effective throat", "in", example=0.075), A("Fy", "Yield stress of the weaker base steel", "psi", example=50000, symbol="Fy"),
       A("Fxx", "Electrode tensile strength", "psi", example=70000, symbol="Fxx")],
      j2_1_2, WELD[:1] + ("Welds", "Groove"), eq="J2.1-2, -3", factors=(1.70, 0.90, 0.80), notes=("Each limit has its own Ω and φ; the smaller available strength is returned.",),
      keywords="groove butt weld shear"),
    F("J2_2_2_1", "J2.2.2.1", "Arc spot weld, shear (sheet to thicker steel)", "Shear strength of one puddle weld",
      "(a) Pnv = π/4 · de² · 0.75·Fxx\n(b) Pnv from da/t and E/Fu: 2.20, 0.280·[1 + 5.59·√(E/Fu)/(da/t)], or 1.40, times t·da·Fu\nde = 0.7·d − 1.5·t ≤ 0.55·d,   da = d − t",
      [A("d", "Visible weld diameter", "in", example=0.75), A("t", "Sheet thickness (total of sheets)", "in", max=0.15, limit_ref="J2.2", example=0.0575),
       A("Fu", "Tensile strength of the sheet", "psi", example=58000, symbol="Fu"), A("Fxx", "Electrode tensile strength", "psi", example=60000, symbol="Fxx"),
       A("E", "Modulus of elasticity (29 500 000 if blank)", "psi", optional=True, default=E_STEEL)],
      j2_2_2_1, WELD[:1] + ("Welds", "Arc spot"), eq="J2.2.2.1-1 to -5", factors=(2.55, 0.60, 0.50),
      notes=("Returns the smaller of (a) and (b), each with its own Ω and φ.", "Weld washers are needed for sheet under 0.028 in."), keywords="arc spot puddle weld shear"),
    F("J2_2_2_2", "J2.2.2.2", "Arc spot weld, shear (sheet to sheet)", "Two sheets of equal thickness", "Pnv = 1.65 · t · da · Fu,   da = d − t",
      [A("d", "Visible weld diameter", "in", example=0.5), A("t", "Thickness of one sheet", "in", min=0.028, max=0.0635, limit_ref="J2.2.2.2", example=0.04),
       A("Fu", "Tensile strength of the sheet", "psi", example=50000, symbol="Fu"), A("Fxx", "Electrode tensile strength", "psi", example=60000, symbol="Fxx")],
      j2_2_2_2, WELD[:1] + ("Welds", "Arc spot"), eq="J2.2.2.2-1", factors=(2.20, 0.70, 0.60), keywords="arc spot puddle weld shear sheet to sheet"),
    F("J2_2_3", "J2.2.3", "Arc spot weld, tension", "Uplift strength of one puddle weld", "Pnt = smaller of π/4·de²·Fxx and 0.8·(Fu/Fy)²·t·da·Fu",
      [A("d", "Visible weld diameter", "in", example=0.5), A("t", "Sheet thickness (total of sheets)", "in", example=0.0575),
       A("Fu", "Tensile strength of the sheet", "psi", example=58000, symbol="Fu"), A("Fy", "Yield stress of the sheet", "psi", example=50000, symbol="Fy"),
       A("Fxx", "Electrode tensile strength", "psi", example=60000, symbol="Fxx"),
       A("deck", "yes: panel and deck (Ω 2.50)", kind="text", optional=True, choices=("no", "yes"), default="NO")],
      j2_2_3, WELD[:1] + ("Welds", "Arc spot"), eq="J2.2.3-1, -2", factors=(3.0, 0.50, 0.40),
      notes=("Uneven (eccentric) uplift counts only 50 %; a deck sidelap 70 %.", "Several sheets: use the sum of the thicknesses."), keywords="arc spot puddle weld tension uplift"),
    F("J2_2_4", "J2.2.4", "Arc spot weld, shear + tension", "Interaction value; 1.00 or less passes", "(V/Pav)^1.5 + (T/Pat)^1.5 ≤ 1   (check only when (T/Pat)^1.5 > 0.15)",
      [A("V", "Shear per weld (required)", "lbf", positive=False, example=200), A("T", "Tension per weld (required)", "lbf", positive=False, example=150),
       A("Pav", "Available shear strength", "lbf", example=900), A("Pat", "Available tension strength", "lbf", example=500)],
      j2_2_4, WELD[:1] + ("Welds", "Arc spot"), eq="J2.2.4-1", units="ratio", notes=("Use available strengths (J2_2_2_1 and J2_2_3 with ASD or LRFD) and matching V and T.",),
      keywords="arc spot weld combined interaction"),
    F("J2_3_2_1", "J2.3.2.1", "Arc seam weld, shear", "Shear strength of one seam weld", "Pnv = smaller of (π/4·de² + L·de)·0.75·Fxx and 2.5·t·Fu·(0.25·L + 0.96·da)\nde = 0.7·d − 1.5·t,   da = d − t",
      [A("d", "Visible weld width", "in", example=0.5), A("L", "Seam length (without the round ends)", "in", example=1.0), A("t", "Sheet thickness", "in", example=0.0575),
       A("Fu", "Tensile strength of the sheet", "psi", example=58000, symbol="Fu"), A("Fxx", "Electrode tensile strength", "psi", example=60000, symbol="Fxx")],
      j2_3_2_1, WELD[:1] + ("Welds", "Arc seam"), eq="J2.3.2.1-1 to -4", factors=(2.55, 0.60, 0.50), notes=("L counts up to 3d.",), keywords="arc seam weld shear"),
    F("J2_5", "J2.5", "Fillet weld, shear", "Shear strength of a fillet weld, lap or T joint", "Longitudinal, L/t < 25: Pnv = (1 − 0.01·L/t)·t·L·Fu;  L/t ≥ 25: 0.75·t·L·Fu\nTransverse: Pnv = t·L·Fu\nsmaller of the two sheets",
      [A("t1", "Thickness of part 1", "in", example=0.0747, symbol="t1"), A("t2", "Thickness of part 2", "in", example=0.0747, symbol="t2"), A("L", "Weld length", "in", example=2.0),
       A("Fu1", "Tensile strength of part 1", "psi", example=58000, symbol="Fu1"), A("Fu2", "Tensile strength of part 2", "psi", example=58000, symbol="Fu2"),
       A("load", "Load direction", kind="text", choices=("longitudinal", "transverse"), symbol="load", example="longitudinal"),
       A("w", "Smaller weld leg (only if t > 0.10 in.)", "in", optional=True), A("Fxx", "Electrode strength (only if t > 0.10 in.)", "psi", optional=True, symbol="Fxx")],
      j2_5, WELD[:1] + ("Welds", "Fillet"), eq="J2.5-1 to -7", factors=(2.55, 0.60, 0.50), notes=("Ω and φ change with the load direction and L/t; they are applied for you.",
                                                                                                    "Over 0.10 in.: also limited by the weld metal, 0.75·0.707·w·L·Fxx."),
      keywords="fillet weld shear lap tee"),
    F("J2_6", "J2.6", "Flare groove weld, shear", "Shear strength of a flare bevel or flare V-groove weld", "bevel (transverse): 0.833·t·L·Fu;  long: 0.75·t·L·Fu;  long-lip: 1.50·t·L·Fu",
      [A("t", "Thickness of the welded member", "in", example=0.0747), A("L", "Weld length", "in", example=2.0), A("Fu", "Tensile strength", "psi", example=58000, symbol="Fu"),
       A("case", "Case", kind="text", choices=("bevel", "long", "long-lip"), symbol="case", example="bevel")],
      j2_6, WELD[:1] + ("Welds", "Flare groove"), eq="J2.6-1, -2, -3", factors=(2.55, 0.60, 0.50),
      notes=("bevel: transverse load.  long: tw from t to 2t (or lip shorter than L).", "long-lip: tw at least 2t and the lip at least L (Ω 2.80)."), keywords="flare groove bevel v weld shear"),
    F("J2_7", "J2.7", "Resistance (spot) weld, shear", "Shear strength of one resistance weld", "t < 0.14 in.:  Pnv = 144 · t^1.47  (kips)\n0.14 to 0.18 in.:  Pnv = 43.4 · t + 1.93  (kips)",
      [A("t", "Thinnest outside sheet", "in", min=0.01, max=0.18, limit_ref="J2.7", example=0.06)],
      j2_7, WELD[:1] + ("Welds", "Resistance"), eq="J2.7-1, -2", factors=(2.35, 0.65, 0.55), notes=("The result is in lbf (the equation gives kips).",), keywords="resistance spot weld shear"),
]


PACK = S.Pack("aisi-s100-16", "AISI16", "AISI S100-16", "North American Specification for the Design of Cold-Formed Steel Structural Members", "2016 edition", "AISI",
              SCREW_FUNCS + BOLT_FUNCS + WELD_FUNCS, root="Connections",
              about="Chapter J, connections: screws (J4), bolts (J3), welds (J2).  Inches, psi, lbf.")


def register():
    S.register_pack(PACK)
