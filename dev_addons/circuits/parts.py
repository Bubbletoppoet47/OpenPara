"""parts.py - the part library of the Circuits add-on: pins, parameters, symbols (drawn with QPainter in grid units) and the
translation of a part into solver elements. Adding a part = one entry in PARTS (+ a draw function)."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPen, QPainterPath

import netsolve as ns

# --------------------------------------------------------------------------------------------------- engineering notation
PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "meg": 1e6, "G": 1e9}


def parse(text):
    """'4.7k' -> 4700.0, '100n' -> 1e-7, '2e-3', '1 meg'. Raises ValueError."""
    t = str(text).strip().replace(" ", "").replace("Ω", "").replace("ohm", "").replace("V", "").replace("A", "").replace("F", "").replace("H", "").replace("Hz", "")
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
        return "OL"
    if x == 0:
        return f"0 {unit}".strip()
    for lim, pre in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")):
        if abs(x) >= lim * 0.99999:
            v = x / lim
            s = f"{v:.{max(digits - 1 - int(math.floor(math.log10(abs(v)))), 0)}f}"
            return f"{s} {pre}{unit}".strip()
    return f"{x:.2e} {unit}".strip()


# --------------------------------------------------------------------------------------------------- the library
# param: (key, label, type, default[, choices]);  type: num | choice | bool
LED_COLORS = {"red": 1.9, "yellow": 2.0, "green": 2.1, "white": 3.1, "blue": 3.0}
WAVES = ["sine", "square", "pulse", "triangle", "sawtooth"]


class Part:
    def __init__(self, kind, label, cat, pins, params, prefix, bbox, unit=""):
        self.kind, self.label, self.cat, self.pins, self.params, self.prefix, self.bbox, self.unit = kind, label, cat, pins, params, prefix, bbox, unit


PARTS = {}


def reg(kind, label, cat, pins, params, prefix, bbox, unit=""):
    PARTS[kind] = Part(kind, label, cat, pins, params, prefix, bbox, unit)


reg("GND", "Ground", "Sources", [("g", 0, 0)], [], "GND", (-1, 0, 1, 1.5))
reg("BAT", "Battery / DC supply", "Sources", [("+", 0, -2), ("-", 0, 2)], [("dc", "Voltage (V)", "num", 9.0)], "B", (-1.2, -2, 1.2, 2), "V")
reg("WALL", "Wall outlet (AC)", "Sources", [("L", 0, -2), ("N", 0, 2)],
    [("vrms", "Voltage RMS (V)", "num", 120.0), ("freq", "Frequency (Hz)", "num", 60.0)], "AC", (-1.5, -2, 1.5, 2), "V")
reg("FGEN", "Function generator", "Sources", [("+", 0, -2), ("-", 0, 2)],
    [("wave", "Wave", "choice", "sine", WAVES), ("amp", "Amplitude (V)", "num", 5.0), ("freq", "Frequency (Hz)", "num", 1000.0),
     ("offset", "Offset (V)", "num", 0.0), ("duty", "Duty (0-1)", "num", 0.5)], "FG", (-1.5, -2, 1.5, 2), "V")
reg("R", "Resistor", "Passive", [("a", -3, 0), ("b", 3, 0)], [("r", "Resistance (Ω)", "num", 1000.0)], "R", (-3, -0.8, 3, 0.8), "Ω")
reg("POT", "Potentiometer", "Passive", [("a", -3, 0), ("b", 3, 0), ("w", 0, -2)],
    [("r", "Resistance (Ω)", "num", 10000.0), ("pos", "Wiper (0-1)", "num", 0.5)], "RV", (-3, -2, 3, 0.8), "Ω")
reg("C", "Capacitor", "Passive", [("a", -2, 0), ("b", 2, 0)], [("c", "Capacitance (F)", "num", 1e-6)], "C", (-2, -1, 2, 1), "F")
reg("L", "Inductor", "Passive", [("a", -3, 0), ("b", 3, 0)], [("l", "Inductance (H)", "num", 1e-3)], "L", (-3, -0.8, 3, 0.4), "H")
reg("SW", "Switch (double-click)", "Passive", [("a", -3, 0), ("b", 3, 0)], [("closed", "Closed", "bool", False)], "S", (-3, -1.2, 3, 0.5))
reg("FUSE", "Fuse", "Passive", [("a", -3, 0), ("b", 3, 0)], [("rating", "Rating (A)", "num", 1.0)], "F", (-3, -0.7, 3, 0.7), "A")
reg("LAMP", "Lamp", "Passive", [("a", -2, 0), ("b", 2, 0)], [("r", "Resistance (Ω)", "num", 100.0), ("watts", "Rated power (W)", "num", 1.0)], "LP", (-2, -1.2, 2, 1.2), "Ω")
reg("D", "Diode", "Semiconductors", [("A", -2, 0), ("K", 2, 0)], [("vf", "Forward drop (V)", "num", 0.7)], "D", (-2, -1, 2, 1))
reg("LED", "LED", "Semiconductors", [("A", -2, 0), ("K", 2, 0)], [("color", "Color", "choice", "red", list(LED_COLORS)), ("imax", "Max current (mA)", "num", 20.0)],
    "LED", (-2, -1.6, 2, 1.2))
reg("ZENER", "Zener diode", "Semiconductors", [("A", -2, 0), ("K", 2, 0)], [("vz", "Zener voltage (V)", "num", 5.1)], "DZ", (-2, -1, 2, 1))
reg("NPN", "NPN transistor", "Semiconductors", [("C", 2, -2), ("B", -2, 0), ("E", 2, 2)], [("bf", "Gain (β)", "num", 100.0)], "Q", (-2, -2, 2, 2))
reg("PNP", "PNP transistor", "Semiconductors", [("C", 2, 2), ("B", -2, 0), ("E", 2, -2)], [("bf", "Gain (β)", "num", 100.0)], "Q", (-2, -2, 2, 2))
reg("NMOS", "N-MOSFET", "Semiconductors", [("D", 2, -2), ("G", -2, 0), ("S", 2, 2)],
    [("vth", "Threshold (V)", "num", 2.0), ("kp", "Gain Kp (A/V²)", "num", 0.5)], "M", (-2, -2, 2, 2))
reg("BUCK", "Buck converter", "Power", [("IN+", -4, -1), ("IN-", -4, 1), ("OUT+", 4, -1), ("OUT-", 4, 1)],
    [("vset", "Output (V)", "num", 5.0), ("eff", "Efficiency (0-1)", "num", 0.9)], "BK", (-4, -2, 4, 2))
reg("BOOST", "Boost converter", "Power", [("IN+", -4, -1), ("IN-", -4, 1), ("OUT+", 4, -1), ("OUT-", 4, 1)],
    [("vset", "Output (V)", "num", 12.0), ("eff", "Efficiency (0-1)", "num", 0.85)], "BS", (-4, -2, 4, 2))
reg("VM", "Voltmeter", "Instruments", [("+", -3, 0), ("-", 3, 0)], [], "VM", (-3, -1.5, 3, 1.5))
reg("AM", "Ammeter (in series)", "Instruments", [("a", -3, 0), ("b", 3, 0)], [], "AM", (-3, -1.5, 3, 1.5))
reg("OHM", "Ohmmeter (unpowered)", "Instruments", [("a", -3, 0), ("b", 3, 0)], [], "OM", (-3, -1.5, 3, 1.5))
reg("SCOPE", "Oscilloscope", "Instruments", [("CH1", -5, -3), ("CH2", -5, -1), ("CH3", -5, 1), ("CH4", -5, 3), ("GND", -5, 5)],
    [("timediv", "Time / div (s)", "num", 1e-3), ("vdiv", "Volts / div (V)", "num", 1.0), ("trig", "Trigger level (V)", "num", 0.0)], "SC", (-5, -4, 5, 6))

PALETTE_ORDER = ["Sources", "Passive", "Semiconductors", "Power", "Instruments"]


def default_params(kind):
    return {p[0]: p[3] for p in PARTS[kind].params}


# --------------------------------------------------------------------------------------------------- symbols
INK = QColor("#1d3557")


def line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def draw_symbol(p, kind, prm, glow=0.0, state=None):
    """Draw the symbol around the part origin, in grid units (the caller scales). `state`: dict of extras (blown, closed ...)."""
    pen = QPen(INK, 0.12)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "GND":
        line(p, 0, 0, 0, 0.5)
        line(p, -0.8, 0.5, 0.8, 0.5)
        line(p, -0.5, 0.85, 0.5, 0.85)
        line(p, -0.2, 1.2, 0.2, 1.2)
    elif kind in ("R", "POT"):
        pts = [(-3, 0), (-2, 0), (-1.75, -0.6), (-1.25, 0.6), (-0.75, -0.6), (-0.25, 0.6), (0.25, -0.6), (0.75, 0.6), (1.25, -0.6), (1.75, 0.6), (2, 0), (3, 0)]
        path = QPainterPath(QPointF(*pts[0]))
        for q in pts[1:]:
            path.lineTo(QPointF(*q))
        p.drawPath(path)
        if kind == "POT":
            line(p, 0, -2, 0, -0.9)
            p.drawLine(QPointF(0, -0.9), QPointF(-0.25, -1.3))
            p.drawLine(QPointF(0, -0.9), QPointF(0.25, -1.3))
    elif kind == "C":
        line(p, -2, 0, -0.3, 0)
        line(p, 0.3, 0, 2, 0)
        line(p, -0.3, -0.9, -0.3, 0.9)
        line(p, 0.3, -0.9, 0.3, 0.9)
    elif kind == "L":
        line(p, -3, 0, -2, 0)
        line(p, 2, 0, 3, 0)
        for k in range(4):
            r = QRectF(-2 + k, -0.5, 1, 1)
            p.drawArc(r, 0, 180 * 16)
    elif kind == "SW":
        line(p, -3, 0, -1, 0)
        line(p, 1, 0, 3, 0)
        if state and state.get("closed"):
            line(p, -1, 0, 1, 0)
        else:
            line(p, -1, 0, 0.8, -1.0)
        p.setBrush(INK)
        p.drawEllipse(QPointF(-1, 0), 0.12, 0.12)
        p.drawEllipse(QPointF(1, 0), 0.12, 0.12)
    elif kind == "FUSE":
        blown = bool(state and state.get("blown"))
        line(p, -3, 0, -1.8, 0)
        line(p, 1.8, 0, 3, 0)
        p.drawRect(QRectF(-1.8, -0.5, 3.6, 1.0))
        if not blown:
            line(p, -1.8, 0, 1.8, 0)
    elif kind == "LAMP":
        line(p, -2, 0, -1, 0)
        line(p, 1, 0, 2, 0)
        if glow > 0:
            c = QColor(255, 214, 90, int(255 * min(glow, 1.0)))
            p.setBrush(c)
        p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        line(p, -0.7, -0.7, 0.7, 0.7)
        line(p, -0.7, 0.7, 0.7, -0.7)
    elif kind in ("D", "LED", "ZENER"):
        line(p, -2, 0, -0.7, 0)
        line(p, 0.7, 0, 2, 0)
        tri = QPainterPath(QPointF(-0.7, -0.8))
        tri.lineTo(QPointF(0.7, 0))
        tri.lineTo(QPointF(-0.7, 0.8))
        tri.closeSubpath()
        if kind == "LED" and glow > 0:
            col = QColor({"red": "#ff3030", "yellow": "#ffd030", "green": "#30e060", "white": "#ffffff", "blue": "#4080ff"}.get(prm.get("color", "red"), "#ff3030"))
            col.setAlpha(int(60 + 195 * min(glow, 1.0)))
            p.setBrush(col)
        p.drawPath(tri)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "ZENER":
            p.drawLine(QPointF(0.7, -0.8), QPointF(0.45, -0.8))
            p.drawLine(QPointF(0.7, 0.8), QPointF(0.95, 0.8))
        line(p, 0.7, -0.8, 0.7, 0.8)
        if kind == "LED":
            for dy in (0, 0.45):
                line(p, 0.2 + dy, -1.0, 0.9 + dy, -1.7)
                line(p, 0.9 + dy, -1.7, 0.6 + dy, -1.65)
                line(p, 0.9 + dy, -1.7, 0.85 + dy, -1.4)
            if glow > 0:
                halo = QColor(255, 255, 200, int(110 * min(glow, 1.0)))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(halo)
                p.drawEllipse(QPointF(0, 0), 0.9 + 0.8 * min(glow, 1.0), 0.9 + 0.8 * min(glow, 1.0))
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind in ("BAT", "WALL", "FGEN"):
        if kind == "BAT":
            line(p, 0, -2, 0, -0.35)
            line(p, 0, 0.35, 0, 2)
            line(p, -0.9, -0.35, 0.9, -0.35)
            line(p, -0.45, 0.35, 0.45, 0.35)
            p.setFont(QFont("Segoe UI", 1))
            line(p, 0.7, -0.9, 1.2, -0.9)
            line(p, 0.95, -1.15, 0.95, -0.65)
        else:
            line(p, 0, -2, 0, -1)
            line(p, 0, 1, 0, 2)
            p.drawEllipse(QPointF(0, 0), 1.0, 1.0)
            path = QPainterPath(QPointF(-0.7, 0))
            for k in range(1, 15):
                x = -0.7 + 1.4 * k / 14
                path.lineTo(QPointF(x, -0.45 * math.sin(2 * math.pi * k / 14)))
            p.drawPath(path)
            line(p, 0.35, -1.5, 0.75, -1.5)
            line(p, 0.55, -1.7, 0.55, -1.3)
    elif kind in ("NPN", "PNP"):
        line(p, -2, 0, -0.5, 0)
        line(p, -0.5, -1.0, -0.5, 1.0)
        pnp = kind == "PNP"
        cy, ey = (2, -2) if pnp else (-2, 2)
        line(p, -0.5, -0.4, 1.2, -1.2 if not pnp else 1.2)
        line(p, -0.5, 0.4, 1.2, 1.2 if not pnp else -1.2)
        line(p, 1.2, -1.2 if not pnp else 1.2, 2, cy if not pnp else cy)
        line(p, 1.2, 1.2 if not pnp else -1.2, 2, ey)
        line(p, 2, cy, 2, cy)
        # arrow on the emitter
        ex, ey2 = (1.2, 1.2) if not pnp else (1.2, -1.2)
        p.setBrush(INK)
        a = QPainterPath()
        if not pnp:
            a.moveTo(1.2, 1.2)
            a.lineTo(0.55, 1.05)
            a.lineTo(0.95, 0.65)
        else:
            a.moveTo(-0.5 + 0.1, -0.4 + 0.1)
            a.moveTo(0.05, 0.1)
            a.lineTo(0.7, -0.05)
            a.lineTo(0.2, 0.55)
        a.closeSubpath()
        p.drawPath(a)
        p.setBrush(Qt.BrushStyle.NoBrush)
        line(p, 2, 1.2 if False else cy, 2, 1.2 if False else cy)
        # straight terminals up / down to the pins
        line(p, 1.2, -1.2 if not pnp else 1.2, 2, -2 if not pnp else 2)
    elif kind == "NMOS":
        line(p, -2, 0, -0.9, 0)
        line(p, -0.9, -0.9, -0.9, 0.9)
        for y in (-0.8, 0, 0.8):
            line(p, -0.5, y - 0.25, -0.5, y + 0.25)
        line(p, -0.5, -0.8, 2, -0.8)
        line(p, 2, -0.8, 2, -2)
        line(p, -0.5, 0.8, 2, 0.8)
        line(p, 2, 0.8, 2, 2)
        line(p, -0.5, 0, 0.5, 0)
        line(p, 0.5, 0, 0.5, 0.8)
        p.setBrush(INK)
        a = QPainterPath(QPointF(-0.5, 0))
        a.lineTo(QPointF(0.0, -0.18))
        a.lineTo(QPointF(0.0, 0.18))
        a.closeSubpath()
        p.drawPath(a)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif kind in ("BUCK", "BOOST"):
        p.setBrush(QColor("#eaf2fb"))
        p.drawRect(QRectF(-3, -2, 6, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for y in (-1, 1):
            line(p, -4, y, -3, y)
            line(p, 3, y, 4, y)
        f = QFont("Segoe UI")
        f.setPointSizeF(0.8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(-3, -2, 6, 3.2), Qt.AlignmentFlag.AlignCenter, "BUCK" if kind == "BUCK" else "BOOST")
        f.setBold(False)
        f.setPointSizeF(0.6)
        p.setFont(f)
        p.drawText(QRectF(-3, 0.6, 6, 1.2), Qt.AlignmentFlag.AlignCenter, "step down" if kind == "BUCK" else "step up")
        f.setPointSizeF(0.55)
        p.setFont(f)
        p.drawText(QRectF(-3, -2, 1.4, 1.2), Qt.AlignmentFlag.AlignCenter, "+")
    elif kind in ("VM", "AM", "OHM"):
        line(p, -3, 0, -1.2, 0)
        line(p, 1.2, 0, 3, 0)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(0, 0), 1.2, 1.2)
        f = QFont("Segoe UI")
        f.setPointSizeF(1.1)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(-1.2, -1.2, 2.4, 2.4), Qt.AlignmentFlag.AlignCenter, {"VM": "V", "AM": "A", "OHM": "Ω"}[kind])
    elif kind == "SCOPE":
        p.setBrush(QColor("#15202b"))
        p.drawRect(QRectF(-4, -4, 8, 10))
        p.setBrush(QColor("#0b3d2e"))
        p.drawRect(QRectF(-3.4, -3.4, 6.8, 6.2))
        gp = QPen(QColor("#1f7a5a"), 0.03)
        p.setPen(gp)
        for k in range(1, 8):
            line(p, -3.4 + k * 6.8 / 8, -3.4, -3.4 + k * 6.8 / 8, 2.8)
        for k in range(1, 6):
            line(p, -3.4, -3.4 + k * 6.2 / 6, 3.4, -3.4 + k * 6.2 / 6)
        p.setPen(pen)
        f = QFont("Segoe UI")
        f.setPointSizeF(0.6)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        for i, (n, y) in enumerate((("1", -3), ("2", -1), ("3", 1), ("4", 3))):
            p.setPen(QColor(CHANNEL_COLORS[i]))
            p.drawText(QRectF(-3.9, y - 0.5, 0.8, 1), Qt.AlignmentFlag.AlignCenter, n)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(-3.9, 4.5, 0.8, 1), Qt.AlignmentFlag.AlignCenter, "⏚")
        for pin_y in (-3, -1, 1, 3, 5):
            p.setPen(pen)
            line(p, -5, pin_y, -4, pin_y)


CHANNEL_COLORS = ["#ffd400", "#2ee6ff", "#ff5cf0", "#7dff4d"]


# --------------------------------------------------------------------------------------------------- part -> solver elements
def to_elements(net, kind, name, nets, prm):
    """Adds the solver element(s) for one part. `nets` = net name per pin, in the order of PARTS[kind].pins."""
    if kind == "BAT":
        net.add("V", name, [nets[0], nets[1]], dc=prm["dc"])
    elif kind == "WALL":
        net.add("V", name, [nets[0], nets[1]], dc=0.0, wave="sine", amp=prm["vrms"] * math.sqrt(2), freq=prm["freq"])
    elif kind == "FGEN":
        net.add("V", name, [nets[0], nets[1]], dc=prm["offset"] if prm["wave"] == "dc" else 0.0, wave=prm["wave"], amp=prm["amp"], freq=prm["freq"],
                offset=prm["offset"], duty=prm["duty"])
    elif kind == "R":
        net.add("R", name, nets, r=prm["r"])
    elif kind == "POT":
        net.add("POT", name, nets, r=prm["r"], pos=prm["pos"])
    elif kind == "C":
        net.add("C", name, nets, c=prm["c"])
    elif kind == "L":
        net.add("L", name, nets, l=prm["l"])
    elif kind == "SW":
        net.add("SW", name, nets, closed=prm["closed"])
    elif kind == "FUSE":
        net.add("R", name, nets, r=0.05)
    elif kind == "LAMP":
        net.add("R", name, nets, r=prm["r"])
    elif kind == "D":
        net.add("D", name, nets, vf=prm["vf"], n=1.0)
    elif kind == "LED":
        net.add("D", name, nets, vf=LED_COLORS.get(prm["color"], 2.0))
    elif kind == "ZENER":
        net.add("D", name, nets, vf=0.7, n=1.0, vz=prm["vz"])
    elif kind == "NPN":
        net.add("Q", name, nets, type="npn", bf=prm["bf"])
    elif kind == "PNP":
        net.add("Q", name, nets, type="pnp", bf=prm["bf"])
    elif kind == "NMOS":
        net.add("M", name, nets, type="n", vth=prm["vth"], kp=prm["kp"])
    elif kind in ("BUCK", "BOOST"):
        net.add(kind, name, nets, vset=prm["vset"], eff=prm["eff"])
    elif kind == "AM":
        net.add("AM", name, nets)
