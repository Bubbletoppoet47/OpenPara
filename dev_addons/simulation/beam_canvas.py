"""The drawing of the 1D FEA tab: members, supports, loads, the deformed shape and the result diagrams.

Click selects a joint (point) or a member (line); Ctrl / Shift adds; drag on empty space box-selects; wheel zooms; middle-drag pans.
The constraint hotkeys work while this drawing has the keyboard focus (click in it first); they are handled by the tab.
"""
import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

import result_style

# the standard results (named like the 2D FEA tab's): displacement magnitude / X / Y, von Mises, normal stress X / Y; plus the factor of safety
COLOUR_MODES = ("umag", "ux", "uy", "vm", "sx", "sy", "fos", "sigma", "disp")
MODE_TITLE = {"umag": "Displacement magnitude", "ux": "Displacement X", "uy": "Displacement Y", "vm": "von Mises stress",
              "sx": "Normal stress X", "sy": "Normal stress Y", "fos": "Factor of safety, yield"}
DIAGRAM_MODES = ("N", "V", "M")
FOS_LOW, FOS_HIGH = 0.5, 3.0              # the factor-of-safety colours: red at or below FOS_LOW, blue at or above FOS_HIGH


def colours(t):
    """0..1 -> RGB ints: the colour scheme shared by all result pictures (result_style.py)."""
    return result_style.colours(t)


class BeamCanvas(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 300)
        self.scale = 8.0
        self.org = QPointF(60, 400)
        self.sel = []                       # [("pt", point id) | ("ln", line id)]
        self.pan_from = None
        self.pan_off = QPointF(0, 0)
        self.box = None                     # [start, current, additive]

    # --- transforms
    def w2s(self, x, y):
        return QPointF(self.org.x() + x * self.scale, self.org.y() - y * self.scale)

    def s2w(self, sp):
        return (sp.x() - self.org.x()) / self.scale, (self.org.y() - sp.y()) / self.scale

    def fit(self):
        pts = self.tab.node_xy()
        if not pts:
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        W, H = max(self.width(), 200), max(self.height(), 200)
        self.scale = 0.7 * min(W / max(w, 1e-9), H / max(h, 1e-9)) if (w > 0 or h > 0) else 8.0
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.org = QPointF(W / 2 - cx * self.scale, H / 2 + cy * self.scale)
        self.update()

    def invalidate(self):
        self.update()

    # --- interaction
    @staticmethod
    def seg_dist(p, a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / L2))
        return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))

    def hit(self, sp):
        tab = self.tab
        if tab.model is None:
            return None
        best = None
        for pid in tab.node_ids():
            s = self.w2s(*tab.model.pts[pid])
            d = math.hypot(s.x() - sp.x(), s.y() - sp.y())
            if d < 9 and (best is None or d < best[0]):
                best = (d, ("pt", pid))
        if best:
            return best[1]
        for mem in tab.members:
            a, b = self.w2s(*tab.model.pts[mem["a"]]), self.w2s(*tab.model.pts[mem["b"]])
            d = self.seg_dist(sp, a, b)
            if d < 7 and (best is None or d < best[0]):
                best = (d, ("ln", mem["lid"]))
        return best[1] if best else None

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.pan_from = ev.position()
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            h = self.hit(ev.position())
            add = bool(ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
            if h is None:
                if not add:
                    self.sel = []
                self.box = [ev.position(), ev.position(), add]
            elif add:
                self.sel = [s for s in self.sel if s != h] if h in self.sel else self.sel + [h]
            else:
                self.sel = [h]
            self.tab.selection_changed()
            self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            h = self.hit(ev.position())
            if h is not None and h[0] == "ln":
                self.box = None
                self.tab.edit_profile_lid(h[1])

    def mouseMoveEvent(self, ev):
        sp = ev.position()
        x, y = self.s2w(sp)
        self.tab.coords.setText(f"x = {x:.5g}   y = {y:.5g}")
        if self.pan_from is not None:
            self.pan_off = QPointF(sp.x() - self.pan_from.x(), sp.y() - self.pan_from.y())
            self.update()
        elif self.box is not None:
            self.box[1] = sp
            self.update()

    def box_select(self, a, b, add):
        tab = self.tab
        r = QRectF(a, b).normalized()
        inside = lambda pid: r.contains(self.w2s(*tab.model.pts[pid]))
        got = [("pt", pid) for pid in sorted(tab.node_ids()) if inside(pid)]
        got += [("ln", m["lid"]) for m in tab.members if inside(m["a"]) and inside(m["b"])]
        self.sel = self.sel + [g for g in got if g not in self.sel] if add else got
        return len(got)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.box is not None:
            a, b, add = self.box
            self.box = None
            if abs(a.x() - b.x()) > 4 or abs(a.y() - b.y()) > 4:
                n = self.box_select(a, b, add)
                self.tab.status(f"Box selected {len(self.sel)} object(s)." if n else "Nothing inside the box.")
            self.tab.selection_changed()
            self.update()
        if ev.button() == Qt.MouseButton.MiddleButton and self.pan_from is not None:
            self.org = QPointF(self.org.x() + self.pan_off.x(), self.org.y() + self.pan_off.y())
            self.pan_from = None
            self.pan_off = QPointF(0, 0)
            self.update()

    def wheelEvent(self, ev):
        f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        pos = ev.position()
        wx, wy = self.s2w(pos)
        self.scale *= f
        self.org = QPointF(pos.x() - wx * self.scale, pos.y() + wy * self.scale)
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.sel = []
            self.tab.selection_changed()
            self.update()
        elif not self.tab.handle_key(ev):
            super().keyPressEvent(ev)

    # --- drawing
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        tab = self.tab
        if tab.model is None or not tab.members:
            p.setPen(QColor("#666666"))
            p.setFont(QFont("Arial", 11))
            txt = ("Choose a sketch and press Import (left) to begin." if tab.model is None else
                   "The sketch has no lines to use as members (construction lines are ignored).")
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, txt)
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.pan_from is not None:
            p.translate(self.pan_off)
        res = tab.result
        mode = tab.view_mode()
        self.paint_members(p, res, mode)
        if res is not None and mode in DIAGRAM_MODES:
            self.paint_diagram(p, res, mode)
        if res is not None and tab.cb_def.isChecked():
            self.paint_deformed(p, res)
        self.paint_supports(p)
        self.paint_loads(p)
        self.paint_joints(p)
        p.resetTransform()
        if self.box is not None:
            p.setPen(QPen(QColor("#3a7bd5"), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(58, 123, 213, 30))
            p.drawRect(QRectF(self.box[0], self.box[1]).normalized())
            p.setBrush(Qt.BrushStyle.NoBrush)
        if res is not None:
            self.paint_legend(p, res, mode)

    def station_values(self, res, mode):
        """-> (low, high, {member id: array per station}) for a colour mode."""
        arr = {}
        mode = {"sigma": "vm", "disp": "umag"}.get(mode, mode)
        for r in res["members"]:
            if mode == "vm":                              # the 1D member carries axial force and bending: the largest fibre stress, |sigma|
                arr[r["id"]] = r["sig"]
            elif mode in ("sx", "sy"):                    # the signed fibre stress (the larger of the two extreme fibres) along the member,
                sg = np.where(np.abs(r["sig_top"]) >= np.abs(r["sig_bot"]), r["sig_top"], r["sig_bot"])   # turned into global X / Y
                arr[r["id"]] = sg * (r["c"] ** 2 if mode == "sx" else r["s"] ** 2)
            elif mode == "ux":
                arr[r["id"]] = r["dxy"][:, 0]
            elif mode == "uy":
                arr[r["id"]] = r["dxy"][:, 1]
            elif mode == "umag":
                arr[r["id"]] = np.hypot(r["dxy"][:, 0], r["dxy"][:, 1])
            else:
                sy = r.get("sy")
                arr[r["id"]] = (sy / np.maximum(r["sig"], 1e-300)) if sy and sy > 0 else np.full(len(r["sig"]), np.nan)
        if mode == "fos":
            return FOS_LOW, FOS_HIGH, arr
        hi = max((float(np.nanmax(v)) for v in arr.values()), default=1.0)
        lo = min((float(np.nanmin(v)) for v in arr.values()), default=0.0)       # lowest to highest, as in the 2D tabs
        return lo, (hi if hi > lo else lo + 1.0), arr

    def paint_members(self, p, res, mode):
        tab = self.tab
        sel = set(self.sel)
        rm = {m["id"]: m for m in res["members"]} if res is not None else {}
        vals = self.station_values(res, mode) if (res is not None and mode in COLOUR_MODES) else None
        for mem in tab.members:
            a, b = self.w2s(*tab.model.pts[mem["a"]]), self.w2s(*tab.model.pts[mem["b"]])
            if ("ln", mem["lid"]) in sel:
                p.setPen(QPen(QColor(255, 136, 0, 120), 10))
                p.drawLine(a, b)
            if res is None and mem["lid"] in getattr(tab, "problem_members", ()):
                p.setPen(QPen(QColor(255, 120, 0, 170), 12))
                p.drawLine(a, b)
            r = rm.get(mem["lid"])
            if vals is not None and r is not None:
                lo, hi, arr = vals
                v = arr[mem["lid"]]
                t = (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)
                if mode == "fos":
                    t = 1.0 - t                                      # low safety factor = red
                cols = colours(np.nan_to_num(t, nan=0.0))
                for i in range(len(v) - 1):
                    if np.isnan(v[i]):
                        p.setPen(QPen(QColor("#999999"), 4.5))
                    else:
                        p.setPen(QPen(QColor(int(cols[i][0]), int(cols[i][1]), int(cols[i][2])), 4.5))
                    p.drawLine(self.w2s(*r["xy0"][i]), self.w2s(*r["xy0"][i + 1]))
            else:
                ok = mem["profile"] is not None
                pen = QPen(QColor("#1f3d7a") if ok else QColor("#c0392b"), 2.6 if ok else 2.0)
                if not ok:
                    pen.setStyle(Qt.PenStyle.DashLine)
                if mode in DIAGRAM_MODES and r is not None:
                    pen = QPen(QColor("#6a7ea8"), 1.6)
                p.setPen(pen)
                p.drawLine(a, b)
            if tab.cb_names.isChecked():
                mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
                d = math.hypot(b.x() - a.x(), b.y() - a.y()) or 1.0
                nx, ny = -(b.y() - a.y()) / d, (b.x() - a.x()) / d
                p.setPen(QColor("#333333"))
                p.setFont(QFont("Arial", 8))
                p.drawText(QPointF(mid.x() + nx * 12 - 14, mid.y() + ny * 12 + 4), mem["name"])

    def paint_diagram(self, p, res, mode):
        key = mode
        gm = max((float(np.abs(r[key]).max()) for r in res["members"]), default=0.0)
        if gm <= 0:
            return
        k = 0.16 * min(self.width(), self.height()) / gm
        sign = -1.0 if mode == "M" else 1.0                         # the moment diagram is drawn on the tension side
        p.setFont(QFont("Arial", 8))
        for r in res["members"]:
            arr = r[key]
            n = len(arr)
            S = [self.w2s(*r["xy0"][i]) for i in range(n)]
            nx, ny = -r["s"], -r["c"]                                # the member's left normal on the screen (y points down there)
            O = [QPointF(S[i].x() + nx * sign * arr[i] * k, S[i].y() + ny * sign * arr[i] * k) for i in range(n)]
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n - 1):
                v = 0.5 * (arr[i] + arr[i + 1])
                p.setBrush(QColor(217, 83, 79, 90) if v >= 0 else QColor(60, 120, 200, 90))
                p.drawPolygon(QPolygonF([S[i], S[i + 1], O[i + 1], O[i]]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#444444"), 1.2))
            p.drawPolyline(QPolygonF(O))
            p.drawLine(S[0], O[0])
            p.drawLine(S[-1], O[-1])
            j = int(np.argmax(np.abs(arr)))
            if abs(arr[j]) > 0.02 * gm:
                p.setPen(QColor("#222222"))
                p.drawText(QPointF(O[j].x() + 4, O[j].y() - 4), f"{arr[j]:.4g}")

    def paint_deformed(self, p, res):
        ds = self.tab.deform_scale(res)
        p.setPen(QPen(QColor("#b02a8f"), 1.8, Qt.PenStyle.DashLine))
        for r in res["members"]:
            pts = [self.w2s(r["xy0"][i][0] + ds * r["dxy"][i][0], r["xy0"][i][1] + ds * r["dxy"][i][1]) for i in range(len(r["x"]))]
            p.drawPolyline(QPolygonF(pts))

    def paint_joints(self, p):
        tab = self.tab
        sel = set(self.sel)
        tie_pts = tab.tie_pids() if hasattr(tab, "tie_pids") else set()
        for pid in tab.node_ids():
            s = self.w2s(*tab.model.pts[pid])
            if pid in tie_pts:
                p.setPen(QPen(QColor("#2e8b57"), 1.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(s, 8.5, 8.5)
            if tab.result is None and pid in getattr(tab, "problem_nodes", ()):
                p.setPen(QPen(QColor(255, 120, 0), 2.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(s, 11, 11)
            if ("pt", pid) in sel:
                p.setPen(QPen(QColor("#ff8800"), 1))
                p.setBrush(QColor("#ff8800"))
                p.drawEllipse(s, 5.5, 5.5)
            else:
                p.setPen(QPen(QColor("#1f3d7a"), 1))
                p.setBrush(QColor("#1f3d7a"))
                p.drawEllipse(s, 3.2, 3.2)
        for mem in tab.members:                                       # a small open circle on every pinned member end
            a, b = self.w2s(*tab.model.pts[mem["a"]]), self.w2s(*tab.model.pts[mem["b"]])
            d = math.hypot(b.x() - a.x(), b.y() - a.y())
            if d < 1:
                continue
            ux, uy = (b.x() - a.x()) / d, (b.y() - a.y()) / d
            off = min(8.0, d / 3)
            p.setPen(QPen(QColor("#1f3d7a"), 1.6))
            p.setBrush(QColor("white"))
            if mem["rel_a"]:
                p.drawEllipse(QPointF(a.x() + ux * off, a.y() + uy * off), 4, 4)
            if mem["rel_b"]:
                p.drawEllipse(QPointF(b.x() - ux * off, b.y() - uy * off), 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def paint_supports(self, p):
        tab = self.tab
        nodes = set(tab.node_ids())
        col = QColor("#1a9641")
        for sp_ in tab.supports:
            for pid in sp_["targets"]:
                if pid not in nodes:
                    continue
                s = self.w2s(*tab.model.pts[pid])
                p.setPen(QPen(col, 1.6))
                p.setBrush(QColor(26, 150, 65, 90))
                mode = sp_["mode"]
                if mode == "fixed":
                    p.drawRect(QRectF(s.x() - 9, s.y() - 9, 18, 18))
                    p.drawLine(QPointF(s.x() - 9, s.y() + 9), QPointF(s.x() + 9, s.y() - 9))
                elif mode == "pinned":
                    p.drawPolygon(QPolygonF([s, QPointF(s.x() - 10, s.y() + 16), QPointF(s.x() + 10, s.y() + 16)]))
                    p.drawLine(QPointF(s.x() - 14, s.y() + 16), QPointF(s.x() + 14, s.y() + 16))
                elif mode == "y":                                      # uy = 0: a roller under the joint
                    p.drawPolygon(QPolygonF([s, QPointF(s.x() - 9, s.y() + 14), QPointF(s.x() + 9, s.y() + 14)]))
                    p.drawEllipse(QPointF(s.x() - 5, s.y() + 17.5), 3.5, 3.5)
                    p.drawEllipse(QPointF(s.x() + 5, s.y() + 17.5), 3.5, 3.5)
                    p.drawLine(QPointF(s.x() - 14, s.y() + 21), QPointF(s.x() + 14, s.y() + 21))
                else:                                                  # ux = 0: a roller at the side of the joint
                    p.drawPolygon(QPolygonF([s, QPointF(s.x() - 14, s.y() - 9), QPointF(s.x() - 14, s.y() + 9)]))
                    p.drawEllipse(QPointF(s.x() - 17.5, s.y() - 5), 3.5, 3.5)
                    p.drawEllipse(QPointF(s.x() - 17.5, s.y() + 5), 3.5, 3.5)
                    p.drawLine(QPointF(s.x() - 21, s.y() - 14), QPointF(s.x() - 21, s.y() + 14))
        p.setBrush(Qt.BrushStyle.NoBrush)

    def arrow(self, p, tail, tip):
        dx, dy = tip.x() - tail.x(), tip.y() - tail.y()
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        p.drawLine(tail, tip)
        p.drawPolyline(QPolygonF([QPointF(tip.x() - 8 * ux + 4 * uy, tip.y() - 8 * uy - 4 * ux), tip,
                                  QPointF(tip.x() - 8 * ux - 4 * uy, tip.y() - 8 * uy + 4 * ux)]))

    def paint_loads(self, p):
        tab = self.tab
        nodes = set(tab.node_ids())
        col = QColor("#c0392b")
        p.setFont(QFont("Arial", 8))
        by_lid = {m["lid"]: m for m in tab.members}
        for ld in tab.loads:
            if ld["kind"] == "force":
                fx, fy = ld["fx"], ld["fy"]
                n = math.hypot(fx, fy)
                for pid in ld["targets"]:
                    if pid not in nodes or n == 0:
                        continue
                    s = self.w2s(*tab.model.pts[pid])
                    dx, dy = fx / n, -fy / n                           # on the screen y points down
                    tail = QPointF(s.x() - dx * 42, s.y() - dy * 42)
                    p.setPen(QPen(col, 2.2))
                    self.arrow(p, tail, QPointF(s.x() - dx * 5, s.y() - dy * 5))
                    p.setPen(col)
                    p.drawText(QPointF(tail.x() + 4, tail.y() - 4), f"{fx:g}, {fy:g}")
            elif ld["kind"] == "moment":
                mz = ld["mz"]
                if mz == 0:
                    continue
                sg = 1.0 if mz > 0 else -1.0
                for pid in ld["targets"]:
                    if pid not in nodes:
                        continue
                    s = self.w2s(*tab.model.pts[pid])
                    p.setPen(QPen(col, 2.2))
                    a0 = 30.0 if sg > 0 else 150.0
                    p.drawArc(QRectF(s.x() - 16, s.y() - 16, 32, 32), int(a0 * 16), int(sg * 270 * 16))
                    ae = math.radians(a0 + sg * 270.0)
                    tip = QPointF(s.x() + 16 * math.cos(ae), s.y() - 16 * math.sin(ae))
                    tx, ty = sg * -math.sin(ae), sg * -math.cos(ae)
                    p.drawPolyline(QPolygonF([QPointF(tip.x() - 8 * tx + 4 * ty, tip.y() - 8 * ty - 4 * tx), tip,
                                              QPointF(tip.x() - 8 * tx - 4 * ty, tip.y() - 8 * ty + 4 * tx)]))
                    p.setPen(col)
                    p.drawText(QPointF(s.x() + 18, s.y() - 18), f"{mz:g}")
            elif ld["kind"] in ("dist", "wind", "snow"):
                pv = tab.pressure_vectors(ld) if ld["kind"] != "dist" else None
                for lid in ld["targets"]:
                    mem = by_lid.get(lid)
                    if mem is None:
                        continue
                    pa, pb = tab.model.pts[mem["a"]], tab.model.pts[mem["b"]]
                    L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
                    if L <= 0:
                        continue
                    c, s_ = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
                    if pv is not None:
                        if lid not in pv:
                            continue
                        wx, wy = pv[lid]
                        label = f"{ld['kind']} {math.hypot(wx, wy):.3g}"
                    else:
                        q1, q2 = ld["q1"], ld["q2"]
                        label = f"{q1:g}, {q2:g}"
                        if ld["frame"] == "global":
                            wx, wy = q1, q2
                        else:
                            wx, wy = q1 * c - q2 * s_, q1 * s_ + q2 * c
                    n = math.hypot(wx, wy)
                    if n == 0:
                        continue
                    dx, dy = wx / n, -wy / n
                    a, b = self.w2s(*pa), self.w2s(*pb)
                    count = max(4, int(math.hypot(b.x() - a.x(), b.y() - a.y()) / 34))
                    p.setPen(QPen(col, 1.6))
                    tails = []
                    for i in range(count + 1):
                        f = i / count
                        tip = QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f)
                        tail = QPointF(tip.x() - dx * 30, tip.y() - dy * 30)
                        tails.append(tail)
                        self.arrow(p, tail, QPointF(tip.x() - dx * 3, tip.y() - dy * 3))
                    p.drawPolyline(QPolygonF(tails))
                    mid = tails[len(tails) // 2]
                    p.setPen(col)
                    p.drawText(QPointF(mid.x() + 5, mid.y() - 4), label)

    def paint_legend(self, p, res, mode):
        tab = self.tab
        W = self.width()
        u = tab.U()
        p.setFont(QFont("Arial", 9))
        p.setPen(QColor("#222222"))
        if mode in DIAGRAM_MODES:
            title = {"N": f"Axial force N ({u['F']}), tension +", "V": f"Shear force V ({u['F']})",
                     "M": f"Bending moment M ({u['F']} {u['L']}), drawn on the tension side"}[mode]
            p.drawText(QPointF(10, 18), title)
            peak = res[mode + "_peak"]
            p.drawText(QPointF(10, 34), f"Largest: {peak:.5g} in {res[mode + '_member']}   (red = positive, blue = negative)")
            return
        if mode not in COLOUR_MODES:
            return
        lo, hi, arr = self.station_values(res, mode)
        mode_k = {"sigma": "vm", "disp": "umag"}.get(mode, mode)
        unit = u["L"] if mode_k in ("umag", "ux", "uy") else u["S"]
        title = MODE_TITLE[mode_k] + ("" if mode_k == "fos" else f"  [{unit}]")
        x0, y0, h = W - 70, 36, 160
        p.drawText(QPointF(max(10, W - 230), 18), title)
        for i in range(h):
            t = 1.0 - i / (h - 1)
            c = colours(t)
            p.fillRect(QRectF(x0, y0 + i, 16, 1.5), QColor(int(c[0]), int(c[1]), int(c[2])))
        top, bottom = (f"{FOS_LOW:g} or less", f"{FOS_HIGH:g} or more") if mode == "fos" else (f"{hi:.4g}", f"{lo:.4g}")
        p.drawText(QPointF(x0 + 20, y0 + 10), top)
        p.drawText(QPointF(x0 + 20, y0 + h), bottom)
        if mode == "fos":
            p.drawText(QPointF(x0 - 50, y0 + h + 16), "grey = no yield strength")
