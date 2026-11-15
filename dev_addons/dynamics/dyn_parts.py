"""dyn_parts.py - the part library of the System dynamics add-on: pins, parameters, symbols (drawn with QPainter in grid units) and the
translation of a drawn part into solver elements (dyn_core).  Adding a part = one entry in PARTS (+ a few lines in draw_symbol).

A pin is (name, x, y, domain) with domain "t" translational or "r" rotational; the editor and the tab use the domain to catch a wire that
joins the two kinds of motion.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainterPath, QPen

import dyn_core as core

# --------------------------------------------------------------------------------------------------- engineering notation
PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "meg": 1e6, "G": 1e9}


def parse(text):
    """'4.7k' -> 4700.0, '100n' -> 1e-7, '2e-3', '1 meg'.  Raises ValueError."""
    t = str(text).strip().replace(" ", "")
    for junk in ("N·m·s/rad", "N·m/rad", "N·s/m", "kg·m²", "N/m", "rad/s", "rad", "kg", "Hz", "°"):
        t = t.replace(junk, "")
    if not t:
        raise ValueError("empty")
    low = t.lower()
    if low.endswith("meg"):
        return float(low[:-3]) * 1e6
    if t[-1] in PREFIX and t[-1] not in "eE":
        try:
            return float(t[:-1]) * PREFIX[t[-1]]
        except ValueError:
            pass
    return float(t)


def eng(x, unit="", digits=3):
    """4700 -> '4.70 kΩ'"""
    if x is None:
        return "-"
    if x != x:
        return "?"
    if math.isinf(x):
        return "inf"
    if x == 0:
        return f"0 {unit}".strip()
    if unit == "kg":                                           # a prefix on the kilogram would read "mkg": count in grams instead
        x, unit = x * 1000.0, "g"
    elif any(c in unit for c in "·/²"):
        return f"{x:.4g} {unit}".strip()                        # compound units: no prefix
    for lim, pre in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")):
        if abs(x) >= lim * 0.99999:
            v = x / lim
            s = f"{v:.{max(digits - 1 - int(math.floor(math.log10(abs(v)))), 0)}f}"
            return f"{s} {pre}{unit}".strip()
    return f"{x:.2e} {unit}".strip()


# --------------------------------------------------------------------------------------------------- the library
# param: (key, label, type, default[, choices]);  type: num | choice | bool
class Part:
    def __init__(self, kind, label, cat, pins, params, prefix, bbox, unit=""):
        self.kind, self.label, self.cat, self.pins, self.params, self.prefix, self.bbox, self.unit = kind, label, cat, pins, params, prefix, bbox, unit


PARTS = {}


def reg(kind, label, cat, pins, params, prefix, bbox, unit=""):
    PARTS[kind] = Part(kind, label, cat, pins, params, prefix, bbox, unit)


SRC = [("wave", "Wave", "choice", "step", list(core.WAVES)), ("freq", "Frequency (Hz)", "num", 1.0),
       ("delay", "Starts at (s)", "num", 0.0), ("width", "Pulse width (s)", "num", 0.1)]

# translational
reg("MASS", "Mass", "Translational", [("a", 0, -2, "t")], [("m", "Mass (kg)", "num", 1.0)], "m", (-2, -2, 2, 1.2), "kg")
reg("SPRING", "Spring", "Translational", [("a", -3, 0, "t"), ("b", 3, 0, "t")], [("k", "Stiffness (N/m)", "num", 100.0)], "k", (-3, -1, 3, 1), "N/m")
reg("DAMPER", "Damper", "Translational", [("a", -3, 0, "t"), ("b", 3, 0, "t")], [("c", "Damping (N·s/m)", "num", 5.0)], "c", (-3, -1.2, 3, 1.2), "N·s/m")
reg("FORCE", "Force source", "Translational", [("a", 0, -2, "t")], [("amp", "Force (N)", "num", 1.0)] + SRC, "F", (-1.2, -2, 1.2, 1.4), "N")
reg("WALL", "Fixed wall", "Translational", [("a", 0, 0, "t")], [], "W", (-1.2, 0, 1.2, 1.4))
reg("LEVER", "Lever (ideal)", "Translational", [("a", -3, 0, "t"), ("b", 3, 0, "t")],
    [("ratio", "Speed ratio b / a (negative: pivot between)", "num", -1.0)], "LV", (-3, -1, 3, 1.6))
# rotational
reg("INERTIA", "Inertia (flywheel)", "Rotational", [("a", 0, -2, "r")], [("j", "Inertia J (kg·m²)", "num", 0.01)], "J", (-1.6, -2, 1.6, 1.4), "kg·m²")
reg("TSPRING", "Torsional spring", "Rotational", [("a", -3, 0, "r"), ("b", 3, 0, "r")], [("k", "Stiffness (N·m/rad)", "num", 10.0)], "kt", (-3, -1, 3, 1), "N·m/rad")
reg("RDAMPER", "Rotational damper", "Rotational", [("a", -3, 0, "r"), ("b", 3, 0, "r")], [("c", "Damping (N·m·s/rad)", "num", 0.1)], "b", (-3, -1.4, 3, 1.4),
    "N·m·s/rad")
reg("TORQUE", "Torque source", "Rotational", [("a", 0, -2, "r")], [("amp", "Torque (N·m)", "num", 1.0)] + SRC, "T", (-1.4, -2, 1.4, 1.4), "N·m")
reg("FRAME", "Fixed frame (ground)", "Rotational", [("a", 0, 0, "r")], [], "FR", (-1.2, 0, 1.2, 1.4))
reg("GEAR", "Gear pair (ideal)", "Rotational", [("a", -3, 0, "r"), ("b", 3, 0, "r")],
    [("ratio", "Ratio N (turns of a per turn of b)", "num", 3.0)], "G", (-3, -1.6, 3, 1.6))
reg("LINK", "Link / arm (hangs from its pivot)", "Rotational", [("a", 0, -2, "r")],
    [("m", "Mass (kg)", "num", 0.5), ("l", "Pivot to centre of mass (m)", "num", 0.2), ("jcm", "Inertia about its centre (kg·m²)", "num", 0.002),
     ("pose", "Pose: angle from hanging down (°)", "num", 0.0)], "L", (-1.2, -2, 1.2, 3), "kg")
# couplers and actuators
reg("RACK", "Rack and pinion", "Couplers", [("rot", -3, 0, "r"), ("lin", 3, 0, "t")], [("r", "Pinion radius (m)", "num", 0.02)], "RP", (-3, -1.6, 3, 1.6), "m")
reg("MOTOR", "DC motor + gearbox", "Actuators", [("shaft", 3, 0, "r")],
    [("v", "Voltage (V)", "num", 12.0), ("r", "Winding resistance R (Ω)", "num", 2.0), ("l", "Inductance L (H, 0 = ignore)", "num", 0.5e-3),
     ("kt", "Torque constant Kt (N·m/A)", "num", 0.05), ("ke", "Back-EMF constant Ke (V·s/rad)", "num", 0.05),
     ("jm", "Rotor inertia Jm (kg·m²)", "num", 1e-5), ("bm", "Rotor friction bm (N·m·s/rad)", "num", 1e-6),
     ("n", "Gearbox ratio N (motor turns per output turn)", "num", 30.0)] + SRC, "M", (-4, -2, 3, 2), "V")
# the motor takes its voltage "v" through the same wave / freq / delay / width settings as the other sources

PALETTE_ORDER = ["Translational", "Rotational", "Couplers", "Actuators"]


def default_params(kind):
    return {p[0]: p[3] for p in PARTS[kind].params}


# --------------------------------------------------------------------------------------------------- symbols
INK = QColor("#1d3557")
HATCH = QColor("#6b7a90")


def line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _zig(p, x0, x1, n=6, amp=0.6):
    pts = [(x0, 0)]
    span = x1 - x0
    for k in range(n):
        pts.append((x0 + span * (k + 0.5) / n, amp if k % 2 == 0 else -amp))
    pts.append((x1, 0))
    path = QPainterPath(QPointF(*pts[0]))
    for q in pts[1:]:
        path.lineTo(QPointF(*q))
    p.drawPath(path)


def _hatch(p, x0, x1, y, dy=0.5, n=5):
    p.save()
    p.setPen(QPen(HATCH, 0.08))
    for k in range(n):
        x = x0 + (x1 - x0) * k / (n - 1)
        line(p, x, y, x - 0.4, y + dy)
    p.restore()


def _arrow(p, x0, y0, x1, y1, head=0.3):
    line(p, x0, y0, x1, y1)
    ang = math.atan2(y1 - y0, x1 - x0)
    for s in (-0.5, 0.5):
        line(p, x1, y1, x1 - head * math.cos(ang + s), y1 - head * math.sin(ang + s))


def _text(p, rect, txt, size=0.8, bold=False):
    f = QFont("Segoe UI")
    f.setPointSizeF(size)
    f.setBold(bold)
    p.setFont(f)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, txt)


def draw_symbol(p, kind, prm, glow=0.0, state=None):
    """Draw the symbol around the part origin, in grid units (the caller scales)."""
    pen = QPen(INK, 0.12)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind in ("WALL", "FRAME"):
        line(p, 0, 0, 0, 0.5)
        line(p, -1.0, 0.5, 1.0, 0.5)
        _hatch(p, -0.6, 1.0, 0.5)
        if kind == "FRAME":
            p.drawEllipse(QPointF(0, 0.5), 0.12, 0.12)
    elif kind == "MASS":
        line(p, 0, -2, 0, -1)
        p.setBrush(QColor("#dfeaf7"))
        p.drawRect(QRectF(-1.6, -1, 3.2, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        _text(p, QRectF(-1.6, -1, 3.2, 2.0), "m", 1.0, True)
    elif kind == "INERTIA":
        line(p, 0, -2, 0, -1.3)
        p.setBrush(QColor("#dfeaf7"))
        p.drawEllipse(QPointF(0, 0), 1.3, 1.3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 0.25, 0.25)
        line(p, 0, -1.3, 0, -0.25)
        _text(p, QRectF(0.1, -0.3, 1.1, 1.0), "J", 0.9, True)
    elif kind in ("SPRING", "TSPRING"):
        line(p, -3, 0, -2, 0)
        line(p, 2, 0, 3, 0)
        _zig(p, -2, 2, 7, 0.55)
        if kind == "TSPRING":
            p.drawArc(QRectF(-0.5, -1.0, 1.0, 1.0), 20 * 16, 140 * 16)
            _arrow(p, -0.4, -0.8, -0.55, -0.62, 0.2)
    elif kind in ("DAMPER", "RDAMPER"):
        line(p, -3, 0, -0.6, 0)
        line(p, -1.4, -0.9, -1.4, 0.9)                         # piston
        line(p, -1.4, 0, -0.6, 0)
        line(p, -2.0, -0.45, -2.0, 0.45)
        line(p, -2.0, -0.45, -1.4, -0.45)
        line(p, -2.0, 0.45, -1.4, 0.45)
        p.drawRect(QRectF(-1.0, -0.9, 2.6, 1.8))               # cylinder
        line(p, 1.6, 0, 3, 0)
        line(p, -1.0, 0, -0.6, 0)
        if kind == "RDAMPER":
            p.drawArc(QRectF(-0.2, -1.3, 1.2, 1.2), 20 * 16, 140 * 16)
    elif kind in ("FORCE", "TORQUE"):
        line(p, 0, -2, 0, -1.1)
        p.setBrush(QColor("#fff3e0"))
        p.drawEllipse(QPointF(0, 0), 1.1, 1.1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "FORCE":
            _arrow(p, -0.65, 0, 0.65, 0, 0.35)
        else:
            p.drawArc(QRectF(-0.65, -0.65, 1.3, 1.3), 30 * 16, 280 * 16)
            _arrow(p, 0.55, -0.4, 0.62, -0.1, 0.25)
        f = QFont("Segoe UI")
        f.setPointSizeF(0.55)
        p.setFont(f)
        p.drawText(QRectF(0.55, 0.45, 1.0, 1.0), Qt.AlignmentFlag.AlignCenter, "F" if kind == "FORCE" else "T")
    elif kind == "GEAR":
        line(p, -3, 0, -2.2, 0)
        line(p, 2.2, 0, 3, 0)
        for cx, r in ((-1.1, 1.1), (1.5, 1.5)):
            p.setBrush(QColor("#dfeaf7"))
            p.drawEllipse(QPointF(cx, 0), r, r)
            for k in range(10):
                a = 2 * math.pi * k / 10
                line(p, cx + r * math.cos(a), r * math.sin(a), cx + (r + 0.18) * math.cos(a), (r + 0.18) * math.sin(a))
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "LEVER":
        line(p, -3, 0, -2.6, 0)
        line(p, 2.6, 0, 3, 0)
        line(p, -2.6, 0, 2.6, 0)
        tri = QPainterPath(QPointF(0, 0))
        tri.lineTo(QPointF(-0.6, 1.2))
        tri.lineTo(QPointF(0.6, 1.2))
        tri.closeSubpath()
        p.setBrush(QColor("#dfeaf7"))
        p.drawPath(tri)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "LINK":
        line(p, 0, -2, 0, -1.4)
        p.setBrush(QColor("#dfeaf7"))
        p.drawRoundedRect(QRectF(-0.35, -1.4, 0.7, 3.8), 0.35, 0.35)
        p.setBrush(INK)
        p.drawEllipse(QPointF(0, -1.05), 0.12, 0.12)
        p.setBrush(QColor("#ffd166"))
        p.drawEllipse(QPointF(0, 1.1), 0.28, 0.28)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == "RACK":
        line(p, -3, 0, -1.4, 0)
        p.setBrush(QColor("#dfeaf7"))
        p.drawEllipse(QPointF(-0.3, 0), 1.1, 1.1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(-1.0, 1.1, 3.2, 0.5))
        for k in range(8):
            line(p, -0.9 + 0.4 * k, 1.1, -0.9 + 0.4 * k, 0.9)
        line(p, 2.2, 1.35, 2.6, 1.35)
        line(p, 2.6, 1.35, 2.6, 0)
        line(p, 2.6, 0, 3, 0)
    elif kind == "MOTOR":
        line(p, 2, 0, 3, 0)
        p.setBrush(QColor("#fff3e0"))
        p.drawEllipse(QPointF(-2.6, 0), 1.4, 1.4)
        p.setBrush(QColor("#dfeaf7"))
        p.drawRect(QRectF(-1.2, -1.0, 3.2, 2.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        line(p, -1.2, 0, -1.2, 0)
        _text(p, QRectF(-4.0, -1.4, 2.8, 2.8), "M", 1.3, True)
        _text(p, QRectF(-1.2, -1.0, 3.2, 2.0), "1:N", 0.9, False)


# --------------------------------------------------------------------------------------------------- part -> solver elements
def to_elements(net, kind, name, nets, prm):
    """Adds the solver element for one part.  `nets` = net name per pin, in the order of PARTS[kind].pins."""
    if kind == "MASS":
        net.add("MASS", name, nets, m=prm["m"])
    elif kind == "SPRING":
        net.add("SPRING", name, nets, k=prm["k"])
    elif kind == "DAMPER":
        net.add("DAMPER", name, nets, c=prm["c"])
    elif kind == "FORCE":
        net.add("FORCE", name, nets, amp=prm["amp"], wave=prm["wave"], freq=prm["freq"], delay=prm["delay"], width=prm["width"])
    elif kind == "WALL":
        net.add("WALL", name, nets)
    elif kind == "LEVER":
        net.add("LEVER", name, nets, ratio=prm["ratio"])
    elif kind == "INERTIA":
        net.add("INERTIA", name, nets, j=prm["j"])
    elif kind == "TSPRING":
        net.add("TSPRING", name, nets, k=prm["k"])
    elif kind == "RDAMPER":
        net.add("RDAMPER", name, nets, c=prm["c"])
    elif kind == "TORQUE":
        net.add("TORQUE", name, nets, amp=prm["amp"], wave=prm["wave"], freq=prm["freq"], delay=prm["delay"], width=prm["width"])
    elif kind == "FRAME":
        net.add("FRAME", name, nets)
    elif kind == "GEAR":
        net.add("GEAR", name, nets, ratio=prm["ratio"])
    elif kind == "LINK":
        net.add("LINK", name, nets, m=prm["m"], l=prm["l"], jcm=prm["jcm"], pose=prm["pose"])
    elif kind == "RACK":
        net.add("RACK", name, nets, r=prm["r"])
    elif kind == "MOTOR":
        net.add("MOTOR", name, nets, v=prm["v"], r=prm["r"], l=prm["l"], kt=prm["kt"], ke=prm["ke"], jm=prm["jm"], bm=prm["bm"], n=prm["n"],
                wave=prm["wave"], freq=prm["freq"], delay=prm["delay"], width=prm["width"])


MOVERS = ("MASS", "INERTIA", "LINK", "MOTOR")            # parts whose motion can be read out
