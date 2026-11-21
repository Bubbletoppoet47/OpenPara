"""ctl_dyn_view.py - the drawing / animation canvas and the signal plots of the Dynamic simulation section."""
import math

import numpy as np

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QWidget

import ctl_dyn as dyn
from ctl_section import nice_step, ticks

INK, SOFT, GRID = QColor("#2b4c7e"), QColor("#4a5668"), QColor("#e1e6ee")
ACCENT, TEAL, RED, MASS = QColor("#e76f51"), QColor("#2a9d8f"), QColor("#b3261e"), QColor("#7a8696")
BLUE = QColor("#1f77b4")


def _font(px=11, bold=False):
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _fmt(v, digits=3):
    if v == 0:
        return "0"
    s = f"{v:.{digits}g}"
    return s


class SketchView(QWidget):
    """The drawing.  With no run it shows the sketch (names on); with a run it shows one frame of the motion, the camera following the base."""
    picked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 220)
        self.sk = dyn.normalize({})
        self.shapes = []
        self.selected = None
        self.cam_x = 0.0
        self.goal_x = None
        self.note = ""
        self.animating = False
        self._scale = 100.0
        self._ground = 0.0
        self.show_static()

    # ------------------------------------------------------------------ what to draw
    def set_sketch(self, sk):
        self.sk = sk
        if not self.animating:
            self.show_static()
        else:
            self.update()

    def show_static(self):
        self.animating = False
        self.note = ""
        self.shapes = dyn.layout(self.sk)
        base = next((s for s in self.shapes if s["kind"] in ("wheel", "cart", "pivot")), None)
        self.cam_x = base["c"][0] if base else 0.0
        c = self.sk["controller"]
        self.goal_x = float(c["goal"]["x"]) if c["pos_on"] and base is not None and base["kind"] != "pivot" else None
        self.update()

    def show_frame(self, mdl, z, goal=None, note=""):
        self.animating = True
        self.shapes = mdl.layout(z)
        base = next((s for s in self.shapes if s["kind"] in ("wheel", "cart", "pivot")), None)
        self.cam_x = base["c"][0] if base else 0.0
        self.goal_x = goal
        self.note = note
        self.update()

    # ------------------------------------------------------------------ the scale: fixed by the drawing, so the motion is not rescaled as it moves
    def _fit(self):
        shapes = dyn.layout(self.sk)
        ymax, chain, hinge = 0.1, 0.0, 0.0
        for s in shapes:
            if s["kind"] == "wheel":
                ymax, hinge = max(ymax, 2 * s["r"]), s["r"]
            elif s["kind"] == "cart":
                ymax, hinge = max(ymax, s["h"]), s["h"]
            elif s["kind"] == "pivot":
                ymax, hinge = max(ymax, s["c"][1]), s["c"][1]
            elif s["kind"] == "link":
                ymax = max(ymax, s["a"][1], s["b"][1])
                chain += math.hypot(s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
            elif s["kind"] == "mass":
                ymax = max(ymax, s["c"][1])
        ymax = max(ymax, hinge + 0.5 * chain) * 1.18
        reach = chain * 1.1 + 0.15
        w, h = max(self.width(), 1), max(self.height(), 1)
        ground = h * 0.88
        sc = min((ground - 16) / ymax, w * 0.9 / (2 * reach)) if ymax > 0 else 100.0
        return max(sc, 5.0), ground

    def to_px(self, x, y):
        return QPointF(self.width() / 2 + (x - self.cam_x) * self._scale, self._ground - y * self._scale)

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                      # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        if w < 60 or h < 60:
            return
        self._scale, self._ground = self._fit()
        sc, g = self._scale, self._ground
        # ground with a scrolling scale
        p.fillRect(QRectF(0, g, w, h - g), QColor("#eef1f6"))
        p.setPen(QPen(QColor("#6b7a90"), 1.5))
        p.drawLine(QPointF(0, g), QPointF(w, g))
        step = nice_step(70.0 / sc, 1)
        x_lo, x_hi = self.cam_x - w / 2 / sc, self.cam_x + w / 2 / sc
        p.setFont(_font(10))
        k = math.ceil(x_lo / step - 1e-9)
        while k * step <= x_hi + 1e-9:
            q = self.to_px(k * step, 0)
            p.setPen(QPen(QColor("#9aa6b8"), 1))
            p.drawLine(QPointF(q.x(), g), QPointF(q.x(), g + 6))
            p.setPen(SOFT)
            p.drawText(QRectF(q.x() - 30, g + 7, 60, 14), Qt.AlignmentFlag.AlignCenter, _fmt(k * step) + (" m" if k else ""))
            k += 1
        # the goal
        if self.goal_x is not None:
            q = self.to_px(self.goal_x, 0)
            top = self.to_px(self.goal_x, 0.45 * (g - 16) / sc)
            p.setPen(QPen(TEAL, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(q, top)
            p.setBrush(TEAL)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(QPolygonF([top, QPointF(top.x() + 14, top.y() + 5), QPointF(top.x(), top.y() + 10)]))
            p.setPen(TEAL)
            p.setFont(_font(10))
            p.drawText(QPointF(top.x() + 4, top.y() - 3), "goal")
        # parts: bases first, then links, then masses
        order = {"cart": 0, "wheel": 0, "pivot": 0, "link": 1, "mass": 2}
        for s in sorted(self.shapes, key=lambda s: order[s["kind"]]):
            sel = s["id"] == self.selected and not self.animating
            getattr(self, "_draw_" + s["kind"])(p, s, sel)
        if not self.animating:
            self._labels(p)
        if self.note:
            p.setFont(_font(15, True))
            p.setPen(RED)
            p.drawText(QRectF(0, 8, w, 24), Qt.AlignmentFlag.AlignCenter, self.note)

    def _pen(self, ok, sel, width, color=INK):
        if not ok:
            return QPen(RED, width, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap)
        return QPen(ACCENT if sel else color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)

    def _draw_wheel(self, p, s, sel):
        c = self.to_px(*s["c"])
        r = s["r"] * self._scale
        p.setPen(self._pen(True, sel, 2.5))
        p.setBrush(QColor("#dfe6f0"))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor("#8fa0b8"), 1.5))
        for k in range(3):
            a = -s["a"] + k * math.pi / 3
            d = QPointF(math.cos(a) * r, math.sin(a) * r)
            p.drawLine(c - d, c + d)
        p.setBrush(INK)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, 3, 3)

    def _draw_cart(self, p, s, sel):
        c = self.to_px(*s["c"])
        wpx, hpx = s["w"] * self._scale, s["h"] * self._scale
        p.setPen(self._pen(True, sel, 2.5))
        p.setBrush(QColor("#cfd8e6"))
        p.drawRoundedRect(QRectF(c.x() - wpx / 2, c.y() - hpx / 2, wpx, hpx), 3, 3)

    def _draw_pivot(self, p, s, sel):
        c = self.to_px(*s["c"])
        p.setPen(self._pen(True, sel, 2))
        p.setBrush(QColor("#cfd8e6"))
        p.drawPolygon(QPolygonF([c, QPointF(c.x() - 11, c.y() + 18), QPointF(c.x() + 11, c.y() + 18)]))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(c, 4, 4)

    def _draw_link(self, p, s, sel):
        a, b = self.to_px(*s["a"]), self.to_px(*s["b"])
        if sel and s["ok"]:
            p.setPen(QPen(QColor(231, 111, 81, 90), 13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(a, b)
        p.setPen(self._pen(s["ok"], sel, 6))
        p.drawLine(a, b)
        p.setPen(QPen(QColor("#ffffff"), 1.2))
        p.setBrush(INK if s["ok"] else RED)
        p.drawEllipse(a, 4.5, 4.5)
        if s.get("motor"):
            p.setPen(QPen(TEAL, 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(a, 9, 9)

    def _draw_mass(self, p, s, sel):
        c = self.to_px(*s["c"])
        r = max(4.0, min(14.0, 4 + 5 * (max(s["m"], 0) / 0.1) ** (1 / 3)))
        p.setPen(self._pen(s["ok"], sel, 2, MASS))
        p.setBrush(MASS if s["ok"] else QColor("#f4cfcb"))
        p.drawEllipse(c, r, r)

    def _labels(self, p):
        p.setFont(_font(10))
        p.setPen(SOFT)
        names = {q["id"]: q.get("name") or q["id"] for q in self.sk["parts"]}
        for s in self.shapes:
            if s["kind"] == "link":
                a, b = self.to_px(*s["a"]), self.to_px(*s["b"])
                m = QPointF((a.x() + b.x()) / 2 + 10, (a.y() + b.y()) / 2)
            elif s["kind"] == "mass":
                c = self.to_px(*s["c"])
                m = QPointF(c.x() + 14, c.y() + 4)
            elif s["kind"] == "wheel":
                c = self.to_px(*s["c"])
                m = QPointF(c.x() + s["r"] * self._scale + 4, c.y() + 14)
            elif s["kind"] == "cart":
                c = self.to_px(*s["c"])
                m = QPointF(c.x() + s["w"] * self._scale / 2 + 4, c.y() + 4)
            else:
                c = self.to_px(*s["c"])
                m = QPointF(c.x() + 14, c.y() + 14)
            p.drawText(m, names.get(s["id"], s["id"]))

    # ------------------------------------------------------------------ picking
    def hit(self, pos):
        best, bd = None, 1e9
        for s in self.shapes:
            k = s["kind"]
            if k == "mass":
                c = self.to_px(*s["c"])
                d = math.hypot(pos.x() - c.x(), pos.y() - c.y()) - 12
                d = max(d, 0) - 10                                # masses win over the link they sit on
            elif k == "link":
                a, b = self.to_px(*s["a"]), self.to_px(*s["b"])
                d = _seg_dist(pos, a, b) - 7
            elif k == "wheel":
                c = self.to_px(*s["c"])
                d = math.hypot(pos.x() - c.x(), pos.y() - c.y()) - s["r"] * self._scale
            elif k == "cart":
                c = self.to_px(*s["c"])
                dx = max(abs(pos.x() - c.x()) - s["w"] * self._scale / 2, 0)
                dy = max(abs(pos.y() - c.y()) - s["h"] * self._scale / 2, 0)
                d = math.hypot(dx, dy)
            else:
                c = self.to_px(*s["c"])
                d = math.hypot(pos.x() - c.x(), pos.y() - c.y() - 8) - 14
            if d < bd:
                best, bd = s["id"], d
        return best if bd <= 6 else None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            pid = self.hit(ev.position())
            if pid:
                self.picked.emit(pid)


def _seg_dist(p, a, b):
    dx, dy = b.x() - a.x(), b.y() - a.y()
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / n))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


class SignalPlots(QWidget):
    """Tilt, position (with its goal) and motor effort against time, one under another, with a cursor that follows the animation."""
    scrubbed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 200)
        self.res = None
        self.t_cur = 0.0
        self._cache, self._cache_key = None, None            # the curves are drawn once into a picture; only the time cursor moves while it plays
        self._rects = []

    def set_result(self, res):
        self.res = res
        self.t_cur = 0.0
        self._cache = None
        self.update()

    def set_time(self, t):
        self.t_cur = t
        self.update()

    def panels(self):
        r = self.res
        mdl = r.mdl
        out = [dict(title="Tilt (°)", series=[(r.t, np.degrees(r.tilt), BLUE, False)], lines=[])]
        if r.ok is False and r.reason == "tilt":
            lim = float(r.sk["run"]["tilt_limit"])
            out[0]["lines"] = [(lim, RED), (-lim, RED)]
        if mdl.has_pos and r.sk["controller"]["pos_on"]:
            out.append(dict(title="Position x (m)", series=[(r.t, r.x, BLUE, False), (r.t, r.goal, TEAL, True)], lines=[]))
        unit = "N" if mdl.motor_part["kind"] == "cart" else "N·m"
        out.append(dict(title=f"Motor effort ({unit})", series=[(r.t, r.u, BLUE, False)], lines=[(mdl.tmax, ACCENT), (-mdl.tmax, ACCENT)]))
        return out

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            dpr = self.devicePixelRatioF()
            key = (self.width(), self.height(), dpr)
            if self._cache is None or self._cache_key != key:
                pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
                pm.setDevicePixelRatio(dpr)
                pp = QPainter(pm)
                try:
                    self.draw(pp)
                finally:
                    pp.end()
                self._cache, self._cache_key = pm, key
            p.drawPixmap(0, 0, self._cache)
            self.draw_cursor(p)
        except Exception:                      # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw_cursor(self, p):
        g = getattr(self, "_geom", None)
        if self.res is None or self.res.n < 2 or g is None:
            return
        left, right, T = g
        x = left + max(0.0, min(T, self.t_cur)) / T * (right - left)
        p.setPen(QPen(QColor("#222222"), 1))
        for top, bottom in self._rects:
            p.drawLine(QPointF(x, top), QPointF(x, bottom))

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        p.setFont(_font(11))
        self._rects = []
        if self.res is None or self.res.n < 2:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "Press Learn (or Run under Advanced) to see the tilt, position and motor effort here.")
            return
        panels = self.panels()
        left, right, top, axis = 62, 14, 6, 24
        ph = (h - top - axis) / len(panels)
        if ph < 36 or w < left + right + 40:
            return
        T = float(self.res.t[-1]) if self.res.t[-1] > 0 else 1.0
        self._geom = (left, w - right, T)
        res = self.res
        for i, pan in enumerate(panels):
            r = QRectF(left, top + i * ph + 12, w - left - right, ph - 18)
            data = np.concatenate([np.asarray(s[1], float) for s in pan["series"]] + [np.zeros(1)])
            reach = float(np.max(np.abs(data)))
            near = [v for v, _ in pan["lines"] if abs(v) <= reach / 0.35]            # a limit line only stretches the axis if the signal gets near it
            ys = np.concatenate([data, np.array(near, float)])
            lo, hi = float(np.min(ys)), float(np.max(ys))
            if hi - lo < 1e-9:
                lo, hi = lo - 1, hi + 1
            pad = 0.08 * (hi - lo)
            lo, hi = lo - pad, hi + pad

            def X(v, r=r):
                return r.left() + v / T * r.width()

            def Y(v, r=r, lo=lo, hi=hi):
                return r.bottom() - (v - lo) / (hi - lo) * r.height()

            for v in ticks(lo, hi):
                p.setPen(QPen(GRID, 1))
                p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
                p.setPen(SOFT)
                p.drawText(QRectF(0, Y(v) - 7, r.left() - 5, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _fmt(v, 3))
            p.setPen(QPen(QColor("#9aa6b8"), 1))
            p.drawRect(r)
            p.setPen(QPen(QColor("#6b7a90"), 1.2))
            if lo < 0 < hi:
                p.drawLine(QPointF(r.left(), Y(0)), QPointF(r.right(), Y(0)))
            p.setClipRect(r)
            for v, col in pan["lines"]:
                p.setPen(QPen(col, 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
            for t, y, col, dashed in pan["series"]:
                p.setPen(QPen(col, 2 if not dashed else 1.6, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
                pts = [QPointF(X(a), Y(b)) for a, b in zip(t, y)]
                if len(pts) > 1500:                                        # thin a very long run for drawing only
                    pts = pts[::int(math.ceil(len(pts) / 1500))] + [pts[-1]]
                for a, b in zip(pts, pts[1:]):
                    p.drawLine(a, b)
            if not res.ok and res.t_fail is not None:
                p.setPen(QPen(RED, 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(X(res.t_fail), r.top()), QPointF(X(res.t_fail), r.bottom()))
            self._rects.append((r.top(), r.bottom()))
            p.setClipping(False)
            p.setPen(SOFT)
            p.setFont(_font(11, True))
            p.drawText(QRectF(r.left() + 4, r.top() - 13, r.width(), 13), Qt.AlignmentFlag.AlignLeft, pan["title"])
            p.setFont(_font(11))
            if i == len(panels) - 1:
                for v in ticks(0, T):
                    p.setPen(SOFT)
                    p.drawText(QRectF(X(v) - 30, r.bottom() + 3, 60, 14), Qt.AlignmentFlag.AlignCenter, _fmt(v, 4))
                p.drawText(QRectF(r.left(), r.bottom() + 12, r.width(), 14), Qt.AlignmentFlag.AlignCenter, "time (s)")

    def _scrub(self, pos):
        g = getattr(self, "_geom", None)
        if g is None or self.res is None:
            return
        left, right, T = g
        t = (pos.x() - left) / max(right - left, 1) * T
        self.scrubbed.emit(max(0.0, min(T, t)))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._scrub(ev.position())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._scrub(ev.position())


class ScorePlot(QWidget):
    """How the learning is going: the score of every trial (lower is better, log scale).  Green dot = balanced, red dot = fell over or hit the ground,
    the line = the best score so far, the ring = the trial being shown on the drawing."""
    TICKS = (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 400, 800)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(250, 190)
        self.pts = []                              # (trial index, cost, balanced)
        self.mark = None
        self.floor = []                            # best cost so far after each trial

    def reset(self):
        self.pts, self.floor, self.mark = [], [], None
        self.update()

    def add(self, tr):
        self.pts.append((int(tr.index), float(tr.cost), bool(tr.ok)))
        self.floor.append(min(c for _, c, _ in self.pts))
        self.update()

    def set_mark(self, index):
        self.mark = index
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                          # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#ffffff"))
        p.setFont(_font(11))
        if not self.pts:
            p.setPen(QColor("#7a8696"))
            p.drawText(QRectF(8, 0, w - 16, h), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       "Press Learn: the score of every trial appears here (lower is better).")
            return
        left, right, top, bottom = 44, 12, 22, 34
        r = QRectF(left, top, w - left - right, h - top - bottom)
        if r.width() < 40 or r.height() < 30:
            return
        n = max(self.pts[-1][0], 10)
        costs = [c for _, c, _ in self.pts]
        lo, hi = math.log10(max(min(costs) / 1.4, 0.3)), math.log10(max(costs) * 1.25)
        if hi - lo < 0.3:
            hi = lo + 0.3

        def X(i):
            return r.left() + (i - 1) / max(n - 1, 1) * r.width()

        def Y(c):
            return r.bottom() - (math.log10(max(c, 1e-9)) - lo) / (hi - lo) * r.height()
        p.setPen(SOFT)
        p.setFont(_font(11, True))
        p.drawText(QRectF(left, 2, r.width(), 16), Qt.AlignmentFlag.AlignLeft, "Score of each trial (lower is better)")
        p.setFont(_font(10))
        for v in self.TICKS:
            if lo <= math.log10(v) <= hi:
                p.setPen(QPen(GRID, 1))
                p.drawLine(QPointF(r.left(), Y(v)), QPointF(r.right(), Y(v)))
                p.setPen(SOFT)
                p.drawText(QRectF(0, Y(v) - 7, left - 4, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _fmt(v, 3))
        p.setPen(QPen(QColor("#9aa6b8"), 1))
        p.drawRect(r)
        p.setPen(SOFT)
        for v in ticks(1, n):
            if 1 <= v <= n:
                p.drawText(QRectF(X(v) - 24, r.bottom() + 3, 48, 14), Qt.AlignmentFlag.AlignCenter, _fmt(v, 4))
        p.drawText(QRectF(r.left(), r.bottom() + 16, r.width(), 14), Qt.AlignmentFlag.AlignCenter, "trial")
        p.setClipRect(r)
        p.setPen(QPen(BLUE, 1.8))
        prev = None
        for (i, _, _), f in zip(self.pts, self.floor):                  # the best-so-far line is a staircase
            q = QPointF(X(i), Y(f))
            if prev is not None:
                p.drawLine(prev, QPointF(q.x(), prev.y()))
                p.drawLine(QPointF(q.x(), prev.y()), q)
            prev = q
        p.setPen(Qt.PenStyle.NoPen)
        for i, c, ok in self.pts:
            p.setBrush(TEAL if ok else RED)
            p.drawEllipse(QPointF(X(i), Y(c)), 3.0, 3.0)
        if self.mark is not None:
            for i, c, ok in self.pts:
                if i == self.mark:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor("#222222"), 1.6))
                    p.drawEllipse(QPointF(X(i), Y(c)), 6.5, 6.5)
        p.setClipping(False)
