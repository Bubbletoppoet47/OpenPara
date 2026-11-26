"""coupled_viz.py - the Viz tab of the Coupled Physics window: the RENDERED picture of the last coupled solve, with a playback bar and the two ways of saving it.  The numbers behind it are in
coupled_viz_core (no Qt); this file draws them with QPainter (no matplotlib).

Three pictures, by what was solved.  A 2D solve with a flow: the air temperature or pressure on the air mesh (one at a time), the body with its displacement or von Mises stress (one at a time), the
tracers (streamlines of the last pass with particles travelling along them), and the outline of the body as the flow bent it, drawn exaggerated; every layer is switched on and off in the Outline on
the left.  A 2D heat and stress solve with no flow: the body coloured by its temperature, displacement or von Mises stress (one at a time), the heat-flux tracers (lines that start where heat enters
the body and follow the heat flux of the heat analysis, with particles that go faster where the flux is stronger; the flux field is the one of the Heat flow of the 2D Thermal tab) and the bent
outline.  A 3D solve (heat and stress, with or without a flow): the surface of the part, seen from any side (drag to turn it), coloured by temperature, displacement or von Mises stress (one at a
time), bent from nothing to its solved shape, drawn by a software z-buffer (coupled_viz3d_core: no OpenGL).  The air and tracers of a 3D flow are not drawn.
It shows the LAST solve: nothing here changes a result, and nothing is solved again.  With no solve yet the picture says so.

Looked at only in a headless Qt (frames drawn, saved and compared with the numbers); never seen on a real screen."""
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

import coupled_viz3d_core as V3
import coupled_viz_core as V
import sim_ui

EMPTY = "No solve yet. Press Solve in the Coupled tab: the rendered result appears here."
NO_STRESS = "The result of the stress analysis is not here any more: solve again."
NO_FLUID = "The flow of the last solve is not in its result any more: solve again."
NO_HEAT = "The result of the heat or the stress analysis is not here any more: solve again."
NO_FLUX = "No heat flows in this result (the temperature is the same everywhere), so there are no heat-flux tracers."
STATUS = "Viz: shows the last coupled solve. Nothing here changes the result."
TEAL, INK, MUTED = "#1f7a84", "#1f2933", "#4a5563"
BAR_FRAC = 0.22                                         # the share of the width that the colour bars take


class VizCanvas(QWidget):
    """The picture.  draw() paints frame k into a w x h area; the same code gives the screen, the PNG and every frame of an exported animation."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.frame = None                              # None: the last frame (the still picture)
        self.export_bg = None                          # a grey level while an animation is drawn for a transparent format
        self._static = None
        self._solid = None                             # the last 3D picture (and its depth), kept while nothing in it changed
        self.interacting = False                       # the mouse is turning the 3D part: it is drawn quickly, and well again when the mouse is let go
        self._drag = None
        self.setMinimumSize(420, 320)
        self.setMouseTracking(False)

    # ------------------------------------------------------------------ what is drawn
    def static_image(self, fit, scale, lay):
        """The air and the body as one picture (cached: they do not move)."""
        d = self.page.data
        key = (id(d), fit.w, fit.h, scale, lay.get("air_T"), lay.get("air_p"), lay.get("body_u"), lay.get("body_vm"), lay.get("body_T"))
        if self._static is not None and self._static[0] == key:
            return self._static[1]
        pw, ph = int(round(fit.w * scale)), int(round(fit.h * scale))
        big = V.Fit(d["window"], pw, ph)
        img = np.zeros((ph, pw, 4), np.uint8)
        a, b = d["air"], d["body"]
        if lay.get("air_T"):
            img = V.raster(a["xy"], a["tris"], a["T"], big, a["T_range"][0], a["T_range"][1], "inferno")
        elif lay.get("air_p"):
            img = V.raster(a["xy"], a["tris"], a["p"], big, a["p_range"][0], a["p_range"][1], "inferno")
        elif lay.get("body_T") and d.get("thermal") is not None:                          # (the heat picture: the body coloured by the temperature of the heat analysis)
            th = d["thermal"]
            img = V.raster(th["xy"], th["tris"], th["T"], big, th["T_range"][0], th["T_range"][1], "inferno")
        if b is not None and (lay.get("body_u") or lay.get("body_vm")):
            if lay.get("body_u"):
                top = V.raster(b["xy"], b["tris"], b["umag"], big, b["u_range"][0], b["u_range"][1], "viridis")
            else:
                top = V.raster(b["xy"], b["tris"], b["vm"], big, b["vm_range"][0], b["vm_range"][1], "viridis")
            m = top[..., 3] > 0
            img[m] = top[m]
        qi = QImage(img.data, pw, ph, pw * 4, QImage.Format.Format_RGBA8888).copy()
        self._static = (key, qi)
        return qi

    def draw(self, p, w, h, k, scale=1.0):
        pg = self.page
        bg = QColor("white") if self.export_bg is None else QColor(self.export_bg, self.export_bg, self.export_bg)
        p.fillRect(QRectF(0, 0, w, h), bg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        msg = pg.message()
        if msg:
            p.setPen(QColor(MUTED))
            f = QFont(self.font())
            f.setPixelSize(14)
            p.setFont(f)
            p.drawText(QRectF(24, 0, w - 48, h), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), msg)
            return
        d = pg.data
        if d.get("kind") == "body3d":
            self.draw3d(p, w, h, k, scale)
            return
        lay = V.effective_layers(d, pg.active_layers())
        pw = int(w * (1.0 - BAR_FRAC))
        fit = V.Fit(d["window"], pw, h)
        p.drawImage(QRectF(0, 0, pw, h), self.static_image(fit, scale, lay))
        st = V.frame_state(d, k, pg.exaggeration)
        poly = lambda a: QPolygonF([QPointF(*q) for q in fit.px(a)])      # noqa: E731
        # the body as drawn, thin
        for q in d["rest"]:
            p.setPen(QPen(QColor("#d9d9e0"), 0.8))
            p.drawPolyline(poly(q))
        if lay.get("tracers"):
            p.setPen(QPen(QColor(255, 255, 255, 140), 0.9))
            for line in d["lines"]:
                p.drawPolyline(poly(line))
            p.setPen(QPen(QColor(255, 255, 255, 242), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for t in st["tails"]:
                p.drawPolyline(poly(t))
            p.setBrush(QColor("white"))
            p.setPen(QPen(QColor(30, 30, 40, 200), 0.6))
            for x, y in st["particles"]:
                c = fit.px((x, y))
                p.drawEllipse(QPointF(float(c[0]), float(c[1])), 1.8, 1.8)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if lay.get("bent") and d["body"] is not None:
            for q in st["outline"]:
                pl = poly(q)
                p.setPen(QPen(QColor(20, 20, 30, 230), 2.2))
                p.drawPolyline(pl)
                pen = QPen(QColor("white"), 1.5)
                pen.setDashPattern([3.3, 2.0])
                p.setPen(pen)
                p.drawPolyline(pl)
        self.paint_bars(p, w, h, pw, d, lay)

    def paint_bars(self, p, w, h, pw, d, lay, bars=None):
        bars = V.colour_bars(d, self.page.active_layers()) if bars is None else bars
        if not bars:
            return
        f = QFont(self.font())
        f.setPixelSize(11)
        slot = h / max(2, len(bars))
        for i, (title, lo, hi, name) in enumerate(bars):
            y0 = i * slot + 14
            bh = slot - 56
            x = pw + 22
            p.setPen(QColor(INK))
            fb = QFont(f)
            fb.setBold(True)
            p.setFont(fb)
            p.drawText(QRectF(pw + 8, y0 - 12, w - pw - 12, 30), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), title)
            g = QLinearGradient(0, y0 + 24 + bh, 0, y0 + 24)
            lut = V.lut(name)
            for j in range(0, 256, 16):
                g.setColorAt(j / 255.0, QColor(*[int(v) for v in lut[j]]))
            g.setColorAt(1.0, QColor(*[int(v) for v in lut[255]]))
            p.setPen(QPen(QColor("#9aa5b1"), 0.8))
            p.setBrush(g)
            p.drawRect(QRectF(x, y0 + 24, 14, bh))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(f)
            p.setPen(QColor(INK))
            for t in V.ticks(lo, hi, title):
                yy = y0 + 24 + bh - (0.0 if hi <= lo else (t - lo) / (hi - lo)) * bh
                p.drawLine(QPointF(x + 14, yy), QPointF(x + 18, yy))
                p.drawText(QRectF(x + 20, yy - 8, w - x - 22, 16), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), f"{t:.3g}")

    # ------------------------------------------------------------------ the 3D part
    def camera_at(self, k):
        """The camera of frame k: the view that was set, turned round the part by the animation (the second half of it) unless that is switched off."""
        pg, cam = self.page, self.page.cam
        off = V3.turn_at(k, pg.data["options"]["frames"]) if pg.turn_on else 0.0
        if off == 0.0:
            return cam
        c = V3.Camera(cam.azimuth + off, cam.elevation, cam.zoom)
        c.pan = cam.pan
        return c

    def solid_image(self, d, w, h, k, scale):
        """The part as a picture of the size of the area, and its depth: (QImage, scr, P, zbuf, ss).  Drawn at `ss` times the size (smoother edges) unless the mouse is turning it or the animation
        is playing; the last one is kept while nothing in it changed (the still part of an animation is the same picture for half of its frames)."""
        pg = self.page
        fast = self.interacting or pg.player.playing
        want = max(1.0, float(scale)) * (1.0 if fast else 1.5)
        ss = min(want, max(1.0, (4.0e6 / max(1.0, w * h)) ** 0.5))
        W, H = max(2, int(w * ss)), max(2, int(h * ss))
        ex = pg.exaggeration3()
        fld = pg.active_field()
        bend = V3.frame_positions(d, k, ex)[1] if pg.layers3["bent"] else 0.0
        cam = self.camera_at(k)
        key = (id(d), W, H, round(cam.azimuth, 3), round(cam.elevation, 3), round(cam.zoom, 4), round(float(cam.pan[0]), 2), round(float(cam.pan[1]), 2), fld, round(bend, 5), round(ex, 4),
               round(V.bend_at(k, d["options"]["frames"]), 5) if fld == "u" else 0)
        if self._solid is not None and self._solid[0] == key:
            return self._solid[1:]
        scr = V3.Screen(cam, d["centre"], V3.reach_radius(d, ex), W, H)
        P = V3.frame_positions(d, k, ex)[0] if pg.layers3["bent"] else d["X"]
        shade = V3.shade_of(scr.normals(P, d["tris"]))
        f = next(f for f in V3.FIELDS if f[0] == fld)
        lo, hi = d["ranges"][fld]
        img, zb = V3.raster3d(scr, P, d["tris"], V3.field_values(d, fld, k if pg.layers3["bent"] else None), lo, hi, V.lut(f[3]), shade, chunk=800_000)
        qi = QImage(img.data, W, H, W * 4, QImage.Format.Format_RGBA8888).copy()
        self._solid = (key, qi, scr, P, zb, ss)
        return qi, scr, P, zb, ss

    def draw3d(self, p, w, h, k, scale):
        pg = self.page
        d = pg.data
        pw = int(w * (1.0 - BAR_FRAC))
        qi, scr, P, zb, ss = self.solid_image(d, pw, h, k, scale)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        flux = pg.tracers3_shown()
        p.setOpacity(V3.SHELL_OPACITY if flux else 1.0)                         # (the tracers lie inside the part: its surface is drawn faded while they are on)
        p.drawImage(QRectF(0, 0, pw, h), qi)
        p.setOpacity(1.0)
        edges = d["edges"]
        if pg.layers3["rest"] and len(edges):
            S0 = scr.project(d["X"]) / np.array([ss, ss, 1.0])
            pen = QPen(QColor(120, 130, 145, 170), 1.0)
            pen.setDashPattern([2.0, 3.0])
            p.setPen(pen)
            for a, b in edges:
                p.drawLine(QPointF(S0[a, 0], S0[a, 1]), QPointF(S0[b, 0], S0[b, 1]))
        if pg.layers3["edges"] and len(edges):
            vis = V3.edge_visible(scr, zb, P, edges)
            S1 = scr.project(P) / np.array([ss, ss, 1.0])
            p.setPen(QPen(QColor(20, 24, 32, 215), 1.15))
            for (a, b), v in zip(edges, vis):
                if v:
                    p.drawLine(QPointF(S1[a, 0], S1[a, 1]), QPointF(S1[b, 0], S1[b, 1]))
        if flux:
            self.draw_tracers3d(p, scr, ss, d, k)
        self.paint_triad(p, self.camera_at(k), 40, h - 40)                      # (the axes reach 34 pixels each way from here: they stay in the picture whatever the view)
        fld = pg.active_field()
        f = next(f for f in V3.FIELDS if f[0] == fld)
        lo, hi = d["ranges"][fld]
        self.paint_bars(p, w, h, pw, d, {}, bars=[(f[2], lo, hi, f[3])])

    def draw_tracers3d(self, p, scr, ss, d, k):
        """The heat-flux tracers inside the part: the lines (carried with the bend), the tails and the particles.  Lines and particles nearer to the viewer are drawn darker."""
        pg = self.page
        tr = d["tracers"]
        ex = pg.exaggeration3() if pg.layers3["bent"] else 0.0
        st = V3.tracer_state(tr, k, ex, d["options"]["frames"])
        r = max(V3.reach_radius(d, pg.exaggeration3()), 1e-9)
        sc = np.array([ss, ss, 1.0])
        near = lambda z: float(np.clip((z + r) / (2.0 * r), 0.0, 1.0))                  # noqa: E731 - 0 at the far side of the part, 1 at the near side
        for ln in st["lines"]:
            S = scr.project(ln) / sc
            p.setPen(QPen(QColor(31, 41, 51, int(60 + 120 * near(float(S[:, 2].mean())))), 0.9))
            p.drawPolyline(QPolygonF([QPointF(float(a), float(b)) for a, b, _c in S]))
        for t in st["tails"]:
            S = scr.project(t) / sc
            p.setPen(QPen(QColor(15, 20, 28, int(150 + 100 * near(float(S[:, 2].mean())))), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QPolygonF([QPointF(float(a), float(b)) for a, b, _c in S]))
        if len(st["particles"]):
            S = scr.project(st["particles"]) / sc
            p.setBrush(QColor("white"))
            for a, b, z in S:
                p.setPen(QPen(QColor(15, 20, 28, int(150 + 100 * near(float(z)))), 0.9))
                p.drawEllipse(QPointF(float(a), float(b)), 2.2, 2.2)
            p.setBrush(Qt.BrushStyle.NoBrush)

    def paint_triad(self, p, cam, x0, y0):
        """The three axes of the part as the camera sees them, in the corner."""
        fnt = QFont(self.font())
        fnt.setPixelSize(11)
        fnt.setBold(True)
        p.setFont(fnt)
        L = 34.0
        for name, (dx, dy), ln in V3.axes_triad(cam):
            col = {"x": QColor("#c0392b"), "y": QColor("#27864a"), "z": QColor("#2c5fb3")}[name]
            p.setPen(QPen(col, 2.0))
            end = QPointF(x0 + dx * L, y0 + dy * L)
            p.drawLine(QPointF(x0, y0), end)
            if ln > 0.15:
                p.drawText(QPointF(end.x() + (4 if dx >= 0 else -10), end.y() + (4 if dy >= 0 else -2)), name)

    def mousePressEvent(self, ev):
        d = self.page.data
        if d is None or d.get("kind") != "body3d":
            return super().mousePressEvent(ev)
        self._drag = (ev.position().x(), ev.position().y(), ev.button(), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        self.interacting = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return super().mouseMoveEvent(ev)
        x, y, btn, shift = self._drag
        nx, ny = ev.position().x(), ev.position().y()
        dx, dy = nx - x, ny - y
        cam = self.page.cam
        if shift or btn in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            cam.pan = cam.pan + np.array([dx, dy])
        else:
            cam.turn(-dx * 0.5, dy * 0.5)
        self._drag = (nx, ny, btn, shift)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag is None:
            return super().mouseReleaseEvent(ev)
        self._drag = None
        self.interacting = False
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        d = self.page.data
        if d is not None and d.get("kind") == "body3d":
            self.page.cam.reset()
            self.update()
        else:
            super().mouseDoubleClickEvent(ev)

    def wheelEvent(self, ev):
        d = self.page.data
        if d is None or d.get("kind") != "body3d":
            return super().wheelEvent(ev)
        steps = ev.angleDelta().y() / 120.0
        cam = self.page.cam
        cam.zoom = float(np.clip(cam.zoom * (1.12 ** steps), 0.1, 40.0))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        k = self.page.player.frame if self.frame is None else self.frame
        self.draw(p, self.width(), self.height(), k, scale=max(1.0, float(self.devicePixelRatioF())))
        p.end()

    def render_image(self, k, scale=1.0):
        """Frame k as a picture of the size of the window times `scale` (the PNG is saved at twice the size on the screen)."""
        w, h = max(1, self.width()), max(1, self.height())
        img = QImage(int(w * scale), int(h * scale), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        p.scale(scale, scale)
        self.draw(p, w, h, k, scale=scale)
        p.end()
        return img


class _Marks:
    def __init__(self, keys, page):
        self.keys, self.page = keys, page

    def outline_marks(self):
        return {k: ("ok" if self.page.data is not None else "update") for k in self.keys}


class VizPage:
    """The panel (layers, tracers, animation and export) and the picture with its playback bar.  `panel` goes into the left column of the window, `canvas` (the picture and the bar) into the right."""
    ORDER = ("Layers", "Tracers", "Animation and export")

    def __init__(self, win):
        self.win = win
        self.data = None                               # what the picture is drawn from (coupled_viz_core.build), for the solve it was made from
        self.built_for = None
        self.stale = True
        self.why = None                                # why there is no data (a message), or None
        self.layers = dict(V.LAYERS_ON)
        self.layers_heat = dict(V.LAYERS_HEAT_ON)      # the layers of the heat picture (a 2D solve with no flow)
        self.exaggeration = V.DEFAULTS["exaggeration"]
        self.opts = {"lines": V.DEFAULTS["lines"], "per_line": V.DEFAULTS["per_line"], "trail": V.DEFAULTS["trail"]}
        self.opts_heat = {"lines": V.HEAT_DEFAULTS["lines"], "per_line": V.HEAT_DEFAULTS["per_line"], "trail_frac": V.HEAT_DEFAULTS["trail_frac"]}
        self.player = V.Player()
        self.last_tick = None
        self.mode = None                               # "flow2d" (a 2D solve with a flow), "heat2d" (a 2D heat and stress solve with no flow), "body3d" (a 3D solve), or None (nothing to draw)
        self.cam = V3.Camera()                         # the 3D picture: the view,
        self.field = "u"                               # what colours the part (T, u or vm),
        self.layers3 = {"bent": True, "edges": True, "rest": True, "tracers": True}
        self.exa3 = None                               # the exaggeration of the bend of a 3D part (None: the automatic one)
        self.turn_on = True                            # the view turns once round the part in the second half of the animation
        self.build_panel()
        self.build_picture()

    # ------------------------------------------------------------------ the panel
    def build_panel(self):
        s1 = sim_ui.Section("viz", 1, "Layers", True)
        # --- 2D: the air, the body, the bent outline
        self.grp2d = QWidget()
        g2 = QVBoxLayout(self.grp2d)
        g2.setContentsMargins(0, 0, 0, 0)
        g2.addWidget(sim_ui.wrapped("What the picture shows. The air shows one field at a time (temperature or pressure), and so does the body (displacement or von Mises stress)."))
        self.boxes = {}
        for key, name, _g in V.LAYERS:
            cb = QCheckBox(name)
            cb.setChecked(bool(self.layers[key]))
            cb.toggled.connect(lambda on, k=key: self.layer_toggled(k, on))
            g2.addWidget(cb)
            self.boxes[key] = cb
        s1.body.addWidget(self.grp2d)
        # --- 2D with no flow: the body (temperature, displacement or von Mises stress), the heat-flux tracers, the bent outline
        self.grp_heat = QWidget()
        gh = QVBoxLayout(self.grp_heat)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.addWidget(sim_ui.wrapped("What the picture shows. The body shows one field at a time (temperature, displacement or von Mises stress). The tracers follow the heat flux of the heat analysis."))
        self.boxes_heat = {}
        for key, name, _g in V.LAYERS_HEAT:
            cb = QCheckBox(name)
            cb.setChecked(bool(self.layers_heat[key]))
            cb.toggled.connect(lambda on, k=key: self.layer_toggled(k, on))
            gh.addWidget(cb)
            self.boxes_heat[key] = cb
        s1.body.addWidget(self.grp_heat)
        self.row_ex = QWidget()                         # (the bent outline of both 2D pictures)
        row = QHBoxLayout(self.row_ex)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Exaggeration of the bent outline (x)"))
        self.e_ex = QDoubleSpinBox()
        self.e_ex.setRange(1.0, 1000.0)
        self.e_ex.setDecimals(1)
        self.e_ex.setValue(self.exaggeration)
        self.e_ex.setToolTip("The displacement of the body is far smaller than its size. The dashed outline shows it this many times larger, and says so under the picture.")
        self.e_ex.valueChanged.connect(self.exaggeration_changed)
        row.addWidget(self.e_ex)
        s1.body.addWidget(self.row_ex)
        # --- 3D: the part
        self.grp3d = QWidget()
        g3 = QVBoxLayout(self.grp3d)
        g3.setContentsMargins(0, 0, 0, 0)
        g3.addWidget(sim_ui.wrapped("The part of the last solve. Drag to turn it, scroll to zoom, hold Shift and drag to move it, double-click to start again. The animation bends it from nothing to its solved shape."))
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Colour by"))
        self.cmb_field = QComboBox()
        self.cmb_field.setToolTip("One colouring at a time. The displacement colour grows with the bend; temperature and stress are the solved fields.")
        self.cmb_field.currentIndexChanged.connect(self.field_changed)
        r0.addWidget(self.cmb_field, 1)
        g3.addLayout(r0)
        self.boxes3 = {}
        for key, name, tip in (("bent", "Bent shape (exaggerated)", "Off: the part as it was made, not bent."), ("edges", "Sharp edges", "The edges that show the shape of the part."),
                               ("rest", "Original outline", "The edges of the part before it bent, dotted."),
                               ("tracers", "Heat-flux tracers", "Lines and particles that follow the heat through the part. The part is drawn faded while they are on, so that they show.")):
            cb = QCheckBox(name)
            cb.setToolTip(tip)
            cb.setChecked(bool(self.layers3[key]))
            cb.toggled.connect(lambda on, k=key: self.layer3_toggled(k, on))
            g3.addWidget(cb)
            self.boxes3[key] = cb
        self.cb_turn = QCheckBox("Turn the part in the second half of the animation")
        self.cb_turn.setToolTip("The view goes once round the part after it has bent, so that its shape is seen from every side. The last frame, and the picture you save, are seen from the view you set.")
        self.cb_turn.setChecked(True)
        self.cb_turn.toggled.connect(self.turn_toggled)
        g3.addWidget(self.cb_turn)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Exaggeration of the bend (x)"))
        self.e_ex3 = QDoubleSpinBox()
        self.e_ex3.setRange(1.0, V3.DEFAULTS3["max_exaggeration"])
        self.e_ex3.setDecimals(1)
        self.e_ex3.setValue(1.0)
        self.e_ex3.setToolTip("The displacement of the part is far smaller than the part. The shape is drawn this many times larger; it starts at the factor that makes the largest displacement 8 % of the part.")
        self.e_ex3.valueChanged.connect(self.exaggeration3_changed)
        r1.addWidget(self.e_ex3)
        self.b_auto = QPushButton("Auto")
        self.b_auto.setToolTip("Back to the factor that makes the largest displacement 8 % of the part.")
        self.b_auto.clicked.connect(lambda *_: self.exaggeration3_auto())
        r1.addWidget(self.b_auto)
        g3.addLayout(r1)
        r2 = QHBoxLayout()
        self.view_buttons = {}
        for name in list(V3.VIEWS) + ["Reset"]:
            b = QPushButton(name)
            b.clicked.connect(lambda *_, n=name: self.view_button(n))
            r2.addWidget(b)
            self.view_buttons[name] = b
        g3.addLayout(r2)
        s1.body.addWidget(self.grp3d)

        s2 = sim_ui.Section("viz", 2, "Tracers", True)
        self.grp_trace2d = QWidget()
        t2 = QVBoxLayout(self.grp_trace2d)
        t2.setContentsMargins(0, 0, 0, 0)
        t2.addWidget(sim_ui.wrapped("The tracers follow the velocity of the last pass of the coupled solve, round the body as the flow bent it. The air temperature is the one from the heat exchange."))
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Lines starting on the inlet"))
        self.e_lines = QSpinBox()
        self.e_lines.setRange(3, 101)
        self.e_lines.setValue(self.opts["lines"])
        self.e_lines.valueChanged.connect(self.tracers_changed)
        r1.addWidget(self.e_lines)
        t2.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Particles on each line"))
        self.e_per = QSpinBox()
        self.e_per.setRange(1, 8)
        self.e_per.setValue(self.opts["per_line"])
        self.e_per.valueChanged.connect(self.tracers_changed)
        r2.addWidget(self.e_per)
        t2.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Trail length (mm)"))
        self.e_trail = QDoubleSpinBox()
        self.e_trail.setRange(0.5, 60.0)
        self.e_trail.setValue(self.opts["trail"])
        self.e_trail.valueChanged.connect(self.trail_changed)
        r3.addWidget(self.e_trail)
        t2.addLayout(r3)
        s2.body.addWidget(self.grp_trace2d)
        self.grp_trace_heat = QWidget()
        th_ = QVBoxLayout(self.grp_trace_heat)
        th_.setContentsMargins(0, 0, 0, 0)
        th_.addWidget(sim_ui.wrapped("The tracers follow the heat flux of the heat analysis. Their lines start where heat enters the body, spaced so that every line stands for the same share of the heat "
                                     "that enters, and end where the heat leaves. A particle goes faster where the flux is stronger; that is a display, not a real speed."))
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Lines starting where heat enters"))
        self.e_hlines = QSpinBox()
        self.e_hlines.setRange(3, 101)
        self.e_hlines.setValue(self.opts_heat["lines"])
        self.e_hlines.valueChanged.connect(self.tracers_changed)
        h1.addWidget(self.e_hlines)
        th_.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Particles on each line"))
        self.e_hper = QSpinBox()
        self.e_hper.setRange(1, 8)
        self.e_hper.setValue(self.opts_heat["per_line"])
        self.e_hper.valueChanged.connect(self.tracers_changed)
        h2.addWidget(self.e_hper)
        th_.addLayout(h2)
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Trail length (% of the longest line)"))
        self.e_htrail = QDoubleSpinBox()
        self.e_htrail.setRange(1.0, 60.0)
        self.e_htrail.setDecimals(1)
        self.e_htrail.setValue(100.0 * self.opts_heat["trail_frac"])
        self.e_htrail.valueChanged.connect(self.heat_trail_changed)
        h3.addWidget(self.e_htrail)
        th_.addLayout(h3)
        s2.body.addWidget(self.grp_trace_heat)
        self.lbl_trace3 = sim_ui.wrapped("")
        s2.body.addWidget(self.lbl_trace3)

        s3 = sim_ui.Section("viz", 3, "Animation and export", True)
        self.lbl_anim = sim_ui.wrapped("")
        s3.body.addWidget(self.lbl_anim)
        self.b_png = QPushButton("Save image (PNG)")
        self.b_png.setToolTip("The picture as it is now, at twice the size it has on the screen.")
        self.b_png.clicked.connect(lambda *_: self.save_png())
        s3.body.addWidget(self.b_png)
        self.b_anim = QPushButton("Save animation…")
        self.b_anim.setToolTip("The animation as a file (the formats this computer can write are offered).")
        self.b_anim.clicked.connect(lambda *_: self.save_animation())
        s3.body.addWidget(self.b_anim)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(4)
        self.sections = [s1, s2, s3]
        for s_ in self.sections:
            cl.addWidget(s_)
        cl.addStretch(1)
        panel = sim_ui.make_panel(content, [])
        self.outline = sim_ui.outlinize(panel, None, "coupled", order=self.ORDER)
        self.outline.attach(_Marks(self.ORDER, self))
        self.outline.select("Layers")
        self.outline.touched = True
        self.panel = panel
        self.set_mode(None)

    def set_mode(self, mode):
        """Shows the controls of the picture that is made: the 2D flow (layers, tracers), the 2D heat picture (layers, heat-flux tracers) or the 3D part (colouring, view); with nothing to draw,
        the 2D flow ones."""
        self.mode = mode
        three = mode == "body3d"
        heat = mode == "heat2d"
        self.grp2d.setVisible(not three and not heat)
        self.grp_heat.setVisible(heat)
        self.row_ex.setVisible(not three)
        self.grp3d.setVisible(three)
        self.grp_trace2d.setVisible(not three and not heat)
        flux3 = three and self.flux3_result() is not None
        self.grp_trace_heat.setVisible(heat or flux3)
        self.lbl_trace3.setVisible(three)
        if heat:
            self.lbl_anim.setText(f"{V.DEFAULTS['frames']} frames at {V.DEFAULTS['fps']} frames per second. The result is steady: the body bends from nothing to its final shape over the first "
                                  "half, and the particles go along their lines a whole number of times (a short line more often than a long one), so that the animation repeats without a jump. "
                                  "How fast the particles go on the screen is not how fast the heat goes. The last frame is the still picture.")
        elif three:
            fl = bool((self.solve_result() or {}).get("fluid"))
            if flux3:
                self.lbl_trace3.setText("The tracers lie inside the part, so it is drawn faded while they are on (switch them off under Layers). The bend of the lines is worked out from the displacement of "
                                        "the surface: it is for the picture only." + (" The air of a 3D flow is not drawn yet." if fl else ""))
            else:
                self.lbl_trace3.setText("There are no tracers for this solve: the air of a 3D flow is not drawn yet." if fl else "There are no tracers: this solve has no flow in it.")
            self.lbl_anim.setText(f"{V.DEFAULTS['frames']} frames at {V.DEFAULTS['fps']} frames per second. The result is steady: the part bends from nothing to its solved shape over the first half, and the view "
                                  "goes once round it in the second half (switch that off above). The last frame is the still picture, seen from the view you have set.")
        else:
            self.lbl_anim.setText(f"{V.DEFAULTS['frames']} frames at {V.DEFAULTS['fps']} frames per second. The result is steady: the body bends from nothing to its final shape over the first "
                                  "half, and every particle goes once along its line. How fast the particles go on the screen is not how fast the air goes. The last frame is the still picture.")

    # ------------------------------------------------------------------ the picture and its bar
    def build_picture(self):
        self.view = VizCanvas(self)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.view, 1)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet(f"color:{MUTED}; padding:0 6px;")
        lay.addWidget(self.notes)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 0, 6, 0)
        self.b_play = QPushButton("Play")
        self.b_play.setStyleSheet(f"QPushButton {{ background:{TEAL}; color:white; font-weight:bold; padding:4px 14px; border-radius:4px; }} QPushButton:disabled {{ background:#a9bcc0; }}")
        self.b_play.clicked.connect(lambda *_: self.toggle_play())
        bar.addWidget(self.b_play)
        self.cb_loop = QCheckBox("Loop")
        self.cb_loop.setChecked(True)
        self.cb_loop.toggled.connect(lambda on: setattr(self.player, "loop", bool(on)))
        bar.addWidget(self.cb_loop)
        bar.addWidget(QLabel("Speed"))
        self.cmb_speed = QComboBox()
        for sp in V.SPEEDS:
            self.cmb_speed.addItem(f"{sp:g}x", sp)
        self.cmb_speed.setCurrentIndex(V.SPEEDS.index(1.0))
        self.cmb_speed.currentIndexChanged.connect(lambda *_: setattr(self.player, "speed", float(self.cmb_speed.currentData())))
        bar.addWidget(self.cmb_speed)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, self.player.n)
        self.slider.setValue(self.player.n)
        self.slider.valueChanged.connect(self.slider_moved)
        bar.addWidget(self.slider, 1)
        self.lbl_frame = QLabel("")
        self.lbl_frame.setMinimumWidth(92)
        bar.addWidget(self.lbl_frame)
        lay.addLayout(bar)
        self.canvas = box
        self.timer = QTimer(box)
        self.timer.setInterval(1000 // 30)
        self.timer.timeout.connect(self.tick)
        self.controls = (self.b_play, self.cb_loop, self.cmb_speed, self.slider, self.b_png, self.b_anim)
        self.update_ui()

    # ------------------------------------------------------------------ what there is to show
    def message(self):
        return self.why if self.data is None else None

    def solve_result(self):
        return getattr(self.win, "result", None)

    def members(self):
        """(fluid window, stress window or None) of the analyses shown in the window, or (None, None)."""
        h = getattr(self.win, "hosted", {})
        fl = getattr(h["fluid"].win, "tab", None) if "fluid" in h else None
        st = getattr(h["structural"].win, "tab", None) if "structural" in h else None
        return fl, st

    def windows(self):
        """The windows of the analyses of the block by kind ('solid', 'thermal3d', ...), as the Workbench gave them to the window last."""
        src = getattr(self.win, "src", None) or {}
        w = src.get("windows")
        try:
            return (w() if callable(w) else w) or {}
        except Exception:                                                              # noqa: BLE001
            return {}

    def tab2d(self, kind, role):
        """The solver tab of a 2D analysis of the block ('thermal' or 'fea'): the one the Workbench gave the window, else the one hosted in it; None when there is none."""
        w = self.windows().get(kind)
        if w is not None:
            return w
        h = getattr(self.win, "hosted", {}).get(role)
        return getattr(h.win, "tab", None) if h is not None else None

    def active_layers(self):
        """The layers of the picture that is made: those of the heat picture for a 2D solve with no flow, else those of the flow."""
        return self.layers_heat if self.mode == "heat2d" else self.layers

    def solid_result(self):
        w = self.windows().get("solid")
        return getattr(w, "result", None) if w is not None else None

    def thermal_result(self):
        w = self.windows().get("thermal3d")
        return getattr(w, "result", None) if w is not None else None

    def flux3_result(self):
        """The result of the 3D heat analysis when it holds the heat flux of its tetrahedra (so that there is something for the tracers to follow), else None."""
        tr = self.thermal_result()
        if tr is None or any(tr.get(k) is None for k in ("nodes", "conn", "q", "qmag")):
            return None
        return tr

    def tracers3_shown(self):
        """Are the heat-flux tracers drawn in the 3D picture now?"""
        d = self.data
        return bool(d is not None and d.get("kind") == "body3d" and d.get("tracers") and d["tracers"]["lines"] and self.layers3.get("tracers"))

    def decide(self):
        """Is there something to draw?  Sets self.why (None when there is) and self.mode."""
        res = self.solve_result()
        mode = None
        if res is None:
            self.why = EMPTY
        elif int(res.get("dim") or 2) == 3:
            sr = self.solid_result()
            if sr is None or not sr.get("surface") or sr.get("u") is None:
                self.why = NO_STRESS
            else:
                self.why, mode = None, "body3d"
        elif not res.get("fluid"):                                                       # a 2D heat and stress solve with no flow
            th, fe = self.tab2d("thermal", "thermal"), self.tab2d("fea", "structural")
            tr, sr = getattr(th, "result", None), getattr(fe, "result", None)
            ready = tr is not None and tr.get("mesh") is not None and sr is not None
            self.why = None if ready else NO_HEAT
            mode = "heat2d" if ready else None
        elif "steps" not in res["fluid"]:
            self.why = NO_FLUID
        else:
            fl, _st = self.members()
            ready = fl is not None and getattr(fl, "result", None) is not None and fl.result.get("xy_sketch") is not None
            self.why = None if ready else "The result of the flow is not here any more: solve again."
            mode = "flow2d" if ready else None
        self.set_mode(mode)                                                              # (cheap; the texts of the panel follow what the solve has: a flow or none)
        return self.why is None

    def make_data(self):
        """The data of the last solve: for a 3D solve the surface of the part with its fields; for a 2D solve the flow of the last pass, the stress result and the geometry."""
        if self.mode == "body3d":
            return self.make_data3d()
        if self.mode == "heat2d":
            return self.make_data_heat()
        import coupled_members as cm
        import physics_cfd as pcfd
        fl, st = self.members()
        flow = fl.result
        geom = (st or fl).geom
        mm = float(flow["lscale"]) * 1000.0
        disp = cm.Structural2D(st).displacement_at if st is not None and st.result is not None else None
        return V.build(flow, st.result if (st is not None and st.result is not None) else None, fl.mesh["body_box"], fl.mesh["box"], geom["polys"], [e["kind"] for e in geom["edges"]],
                       disp, pcfd.FlowField(flow).velocity, length_per_unit=mm, options={"lines": self.opts["lines"], "per_line": self.opts["per_line"], "trail": self.opts["trail"],
                                                                                          "exaggeration": self.exaggeration})

    def make_data_heat(self):
        """The data of a 2D heat and stress solve with no flow: the temperature on the mesh of the heat analysis, its heat flux (the flux field of the Heat flow of the 2D Thermal tab) for the
        tracers, the stress result for the body fields and the bent outline."""
        import coupled_members as cm
        import thermal_flow as tflow
        import units
        th, fe = self.tab2d("thermal", "thermal"), self.tab2d("fea", "structural")
        thr, fer = th.result, fe.result
        mesh = thr["mesh"]
        field = tflow.FluxField(mesh["nodes"], mesh["tris"])
        field.set_flux(thr["qx"], thr["qy"], V.reference_heat_flux(thr["qmag"], float(thr["Tmin"]), float(thr["Tmax"])))
        geom = fe.geom
        mm = float(thr["lscale"]) * 1000.0
        d = V.build_heat(thr, fer, field, geom["polys"], [e["kind"] for e in geom["edges"]], cm.Structural2D(fe).displacement_at, length_per_unit=mm,
                         options={"lines": self.opts_heat["lines"], "per_line": self.opts_heat["per_line"], "trail_frac": self.opts_heat["trail_frac"], "exaggeration": self.exaggeration})
        d["field"] = field
        if d["body"] is not None:
            d["body"]["vm_unit"] = units.get(fe.unit_name())["S"]
        return d

    def make_data3d(self):
        """The surface of the part from the stress result (its displacement and von Mises stress at every vertex) and the temperature of the heat result at the same points."""
        sr, tr = self.solid_result(), self.thermal_result()
        gap = []
        temp = None
        if tr is not None:
            def temp(P):                                                                 # noqa: E306
                T, g = V3.surface_temperature(tr, P)
                gap.append(g)
                return T
        d = V3.build3d(sr["nodes"], sr["surface"], sr["u"], vm=sr.get("vm_node"), temperature=temp)
        d["T_gap"] = gap[0] if gap else None
        d["field3"], d["tracers"], d["tracers_why"] = None, None, None
        fr = self.flux3_result()
        if fr is not None:
            try:
                d["field3"] = self.flux_field3(fr)
                d["tracers"] = V3.build_tracers(d["field3"], d["X"], d["U"], self.tracer_options3())
            except Exception as ex:                                                  # noqa: BLE001 - the part is still worth drawing without its tracers
                d["field3"], d["tracers"], d["tracers_why"] = None, None, f"The heat-flux tracers could not be made: {ex}"
        return d

    def flux_field3(self, tr):
        """The heat flux of the 3D heat result as a field the tracers can follow: its tetrahedra (corners only) in mm, one flux vector each, the strong flux as in the 2D picture."""
        mm = float(tr.get("lscale", 1e-3)) * 1000.0
        field = V3.FluxField3D(np.asarray(tr["nodes"], float) * mm, np.asarray(tr["conn"])[:, :4])
        field.set_flux(tr["q"], V.reference_heat_flux(tr["qmag"], float(tr["Tmin"]), float(tr["Tmax"])))
        return field

    def tracer_options3(self):
        return {"lines": self.opts_heat["lines"], "per_line": self.opts_heat["per_line"], "trail_frac": self.opts_heat["trail_frac"]}

    def rebuild_tracers3(self):
        """New tracer lines for the part that is drawn (the surface and its fields stay as they are)."""
        d = self.data
        if d is None or d.get("kind") != "body3d" or d.get("field3") is None:
            return
        try:
            d["tracers"], d["tracers_why"] = V3.build_tracers(d["field3"], d["X"], d["U"], self.tracer_options3()), None
        except Exception as ex:                                                      # noqa: BLE001
            d["tracers"], d["tracers_why"] = None, f"The heat-flux tracers could not be made: {ex}"
        self.update_ui()

    def refresh(self):
        """The window calls this when the solve changed or this tab is shown: decides what there is to draw and (when this tab is the one shown) makes it."""
        ok = self.decide()
        if not ok:
            self.data, self.built_for = None, None
        else:
            self.stale = self.stale or self.built_for != id(self.solve_result())
            if self.stale and getattr(self.win, "role", None) == "viz":
                self.ensure()
        self.update_ui()
        self.view.update()

    def ensure(self):
        """Makes the data now when the last solve has none yet.  -> True when there is something to draw."""
        if not self.decide():
            self.data, self.built_for = None, None
            self.update_ui()
            return False
        if self.data is None or self.built_for != id(self.solve_result()) or self.stale:
            try:
                self.data = self.make_data()
            except Exception as ex:                                                  # noqa: BLE001 - the picture is not worth a failure of the window
                self.data, self.why = None, f"The picture could not be made: {ex}"
                self.update_ui()
                return False
            self.built_for = id(self.solve_result())
            self.stale = False
        self.update_ui()
        return self.data is not None

    # ------------------------------------------------------------------ the controls
    def update_ui(self):
        has = self.data is not None
        for w in self.controls:
            w.setEnabled(has)
        self.lbl_frame.setText(f"Frame {self.player.frame} of {self.player.n}")
        self.b_play.setText("Pause" if self.player.playing else "Play")
        three = has and self.data.get("kind") == "body3d"
        for w in (self.cmb_field, self.e_ex3, self.b_auto, self.cb_turn, *self.boxes3.values(), *self.view_buttons.values()):
            w.setEnabled(three)
        if three:
            has_tr = bool(self.data.get("tracers") and self.data["tracers"]["lines"])
            self.boxes3["tracers"].setEnabled(has_tr)
            for w in (self.e_hlines, self.e_hper, self.e_htrail):
                w.setEnabled(self.data.get("field3") is not None)
        if three:
            self.sync_fields()
            d = self.data
            ex = self.exaggeration3()
            lines = [f"Shape drawn x{ex:g} larger than the real displacement (the largest is {d['ranges']['u'][1]:.3g} mm)"]
            if (self.solve_result() or {}).get("fluid"):
                lines.append("The air and tracers of the 3D flow are not drawn")
            if d["ranges"].get("T") is None:
                lines.append("No heat result: no temperature colouring")
            tr = d.get("tracers")
            if tr and tr["lines"]:
                where = "from the faces where heat enters the part" if tr["heat"]["how"] == "edges" else "through the part (its heat is made inside)"
                lines.append(f"Tracers: the heat flux of the last heat solve, {len(tr['lines'])} lines {where}; the particles are faster where the flux is stronger (not a real speed)")
            elif d.get("tracers_why"):
                lines.append(d["tracers_why"])
            elif d.get("field3") is not None:
                lines.append(NO_FLUX if d["field3"].qref <= 0 else "No tracer lines could be made from this heat flux")
            self.notes.setText("   ·   ".join(lines))
        elif has and self.data.get("kind") == "heat2d":
            d = self.data
            h = d["heat"]
            lines = []
            if d["lines"]:
                where = "from the edges where heat enters the body" if h["how"] == "edges" else "through the body (its heat is made inside)"
                lines.append(f"Tracers: the heat flux of the last solve, {len(d['lines'])} lines {where}; the particles are faster where the flux is stronger (not a real speed)")
            else:
                lines.append(NO_FLUX if h["qref"] <= 0 else "No tracer lines could be made from this heat flux")
            if d["body"] is not None:
                lines.append(f"Dashed outline: the body as bent by the heat, drawn x{self.exaggeration:g}")
            self.notes.setText("   ·   ".join(lines))
        elif has:
            d = self.data
            fl, _st = self.members()
            lines = []
            try:
                sp = float(fl.result.get("speed", 0.0))
                heat = fl.result.get("heat") or {}
                tin = (float(heat["T_in"]) - 273.15) if heat.get("T_in") is not None else None
                lines.append(f"Tracers: air at {sp:.3g} m/s" + (f", {tin:.3g} °C at the inlet" if tin is not None else ""))
            except Exception:                                                        # noqa: BLE001
                pass
            if d["body"] is not None:
                lines.append(f"Dashed outline: the body as the flow bent it, drawn x{self.exaggeration:g}")
            self.notes.setText("   ·   ".join(lines) or " ")
        else:
            self.notes.setText(" ")
        try:
            self.slider.blockSignals(True)
            self.slider.setValue(self.player.frame)
            self.slider.blockSignals(False)
        except RuntimeError:
            pass

    def sync_fields(self):
        """The colourings of this part in the box (the ones it has), the one in use selected, and the exaggeration box showing the factor in use."""
        d = self.data
        fields = V3.available_fields(d)
        keys = [f[0] for f in fields]
        if self.field not in keys:
            self.field = "u"
        if [self.cmb_field.itemData(i) for i in range(self.cmb_field.count())] != keys:
            self.cmb_field.blockSignals(True)
            self.cmb_field.clear()
            for f in fields:
                self.cmb_field.addItem(f[1], f[0])
            self.cmb_field.blockSignals(False)
        i = self.cmb_field.findData(self.field)
        if i >= 0 and self.cmb_field.currentIndex() != i:
            self.cmb_field.blockSignals(True)
            self.cmb_field.setCurrentIndex(i)
            self.cmb_field.blockSignals(False)
        ex = self.exaggeration3()
        if abs(self.e_ex3.value() - ex) > 0.05:
            self.e_ex3.blockSignals(True)
            self.e_ex3.setValue(ex)
            self.e_ex3.blockSignals(False)

    def exaggeration3(self):
        """The factor the bend of the 3D part is drawn with: the one set, else the automatic one."""
        if self.exa3 is not None:
            return float(self.exa3)
        return float(self.data["exaggeration"]) if self.data is not None and self.data.get("kind") == "body3d" else 1.0

    def field_changed(self, *_):
        key = self.cmb_field.currentData()
        if key:
            self.field = key
            self.view.update()

    def active_field(self):
        """The colouring in use: the one chosen when this solve has it, else the displacement."""
        d = self.data
        return self.field if d is not None and d.get("ranges", {}).get(self.field) is not None else "u"

    def turn_toggled(self, on):
        self.turn_on = bool(on)
        self.view.update()

    def layer3_toggled(self, key, on):
        self.layers3[key] = bool(on)
        self.view.update()

    def exaggeration3_changed(self, v):
        self.exa3 = float(v)
        self.update_ui()
        self.view.update()

    def exaggeration3_auto(self):
        self.exa3 = None
        self.update_ui()
        self.view.update()

    def view_button(self, name):
        if name == "Reset":
            self.cam.reset()
        else:
            self.cam.look(name)
        self.view.update()

    def layer_toggled(self, key, on):
        if self.mode == "heat2d":
            self.layers_heat = V.set_layer(self.layers_heat, key, on)
            lay, boxes = self.layers_heat, self.boxes_heat
        else:
            self.layers = V.set_layer(self.layers, key, on)
            lay, boxes = self.layers, self.boxes
        for k, cb in boxes.items():
            if cb.isChecked() != bool(lay[k]):
                cb.blockSignals(True)
                cb.setChecked(bool(lay[k]))
                cb.blockSignals(False)
        self.view.update()

    def exaggeration_changed(self, v):
        self.exaggeration = float(v)
        self.update_ui()
        self.view.update()

    def trail_changed(self, v):
        self.opts["trail"] = float(v)
        if self.data is not None:
            self.data["options"]["trail"] = float(v)
        self.view.update()

    def heat_trail_changed(self, v):
        self.opts_heat["trail_frac"] = float(v) / 100.0
        d = self.data
        if d is not None and d.get("kind") == "heat2d":
            d["options"]["trail_frac"] = float(v) / 100.0
            d["options"]["trail"] = float(v) / 100.0 * d["heat"]["period"]
        elif d is not None and d.get("kind") == "body3d" and d.get("tracers"):
            o = d["tracers"]["options"]
            o["trail_frac"] = float(v) / 100.0
            o["trail"] = float(v) / 100.0 * d["tracers"]["heat"]["period"]
        self.view.update()

    def tracers_changed(self, *_):
        if self.mode == "body3d":
            self.opts_heat["lines"], self.opts_heat["per_line"] = int(self.e_hlines.value()), int(self.e_hper.value())
            self.rebuild_tracers3()
            self.view.update()
            return
        if self.mode == "heat2d":
            self.opts_heat["lines"], self.opts_heat["per_line"] = int(self.e_hlines.value()), int(self.e_hper.value())
        else:
            self.opts["lines"], self.opts["per_line"] = int(self.e_lines.value()), int(self.e_per.value())
        self.stale = True
        if self.data is not None and getattr(self.win, "role", None) == "viz":
            self.ensure()
        self.view.update()

    def slider_moved(self, v):
        self.player.seek(v)
        self.lbl_frame.setText(f"Frame {self.player.frame} of {self.player.n}")
        self.view.update()

    def toggle_play(self):
        if self.player.playing:
            self.player.pause()
            self.timer.stop()
        else:
            self.player.play()
            self.last_tick = time.monotonic()
            self.timer.start()
        self.update_ui()

    def tick(self):
        now = time.monotonic()
        dt, self.last_tick = now - (self.last_tick or now), now
        if self.player.advance(dt):
            self.update_ui()
            self.view.update()
        if not self.player.playing:
            self.timer.stop()
            self.update_ui()

    def stop(self):
        self.player.pause()
        self.timer.stop()

    # ------------------------------------------------------------------ saving
    def save_png(self, path=None):
        """The current frame as a PNG at twice the size of the picture on the screen.  -> the path, or None (nothing to save / cancelled)."""
        if self.data is None:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self.canvas, "Save image", "coupled_viz.png", "PNG picture (*.png)")
            if not path:
                return None
        if not path.lower().endswith(".png"):
            path += ".png"
        img = self.view.render_image(self.player.frame, 2.0)
        if not img.save(path, "PNG"):
            self.say("The picture could not be saved.")
            return None
        self.say(f"Image saved: {path}")
        return path

    def save_animation(self, path_fmt=None):
        """The animation (every frame drawn the way the picture draws it) as a file in a format this computer can write.  -> the path, or None."""
        if self.data is None:
            return None
        import anim_export
        self.stop()
        keep = self.player.frame
        v = self.view

        def grab(k):
            return v.render_image(k + 1, 1.0)

        def set_bg(level):
            v.export_bg = level
        try:
            return anim_export.export(self.canvas, "Coupled", self.player.n, grab, self.player.fps, 1 if self.player.loop else 0, say=self.say, path_fmt=path_fmt, set_bg=set_bg)
        finally:
            v.export_bg = None
            self.player.seek(keep)
            self.view.update()

    def self_check(self):
        """[{"name", "ok", "expected", "got"}]: the picture against the numbers of the solve it shows.  Empty when there is no picture.  (1) the displacement the body is drawn with is the largest one
        of the stress result; (2) the bent outline never moves further than that (the exaggeration taken out); (3) every particle is back where it began after the last frame (the animation
        repeats without a jump); (4) the air temperature range is the one of the heat exchange."""
        d, res = self.data, self.solve_result()
        if d is None or res is None:
            return []
        if d.get("kind") == "body3d":
            return self.self_check3d()
        if d.get("kind") == "heat2d":
            return self.self_check_heat()
        rows = []
        umax = (res.get("fsi") or {}).get("umax")
        if umax is None and (res.get("structural") or {}).get("L") == "mm":
            umax = (res.get("structural") or {}).get("umax")
        b = d.get("body")
        if umax is not None and b is not None and float(umax) > 0:
            got = float(b["u_range"][1])
            rows.append({"name": "Displacement drawn", "ok": abs(got - float(umax)) <= 0.005 * float(umax), "expected": f"{float(umax):.5g} mm (the stress result)", "got": f"{got:.5g} mm"})
            reach = V.bend_reach(d)
            rows.append({"name": "Bent outline within that displacement", "ok": reach <= float(umax) * 1.005, "expected": f"at most {float(umax):.5g} mm", "got": f"{reach:.5g} mm"})
        n = int(d["options"]["frames"])
        gap = V.particle_gap(d, n, 0)
        span = max(d["window"][1] - d["window"][0], d["window"][3] - d["window"][2])
        rows.append({"name": "Animation repeats without a jump", "ok": gap <= 1e-6 * span, "expected": "0 between the last frame and the first", "got": f"{gap:.3g}"})
        tr, fl = d["air"].get("T_range"), res.get("fluid") or {}
        if tr is not None and "Tmin" in fl and "Tmax" in fl:
            lo, hi = float(fl["Tmin"]) - 273.15, float(fl["Tmax"]) - 273.15
            tol = max(0.5, 0.05 * (hi - lo))
            rows.append({"name": "Air temperature range", "ok": abs(tr[0] - lo) <= tol and abs(tr[1] - hi) <= tol, "expected": f"{lo:.4g} .. {hi:.4g} degC (the heat exchange, within {tol:.2g} K)",
                         "got": f"{tr[0]:.4g} .. {tr[1]:.4g} degC"})
        return rows

    def self_check_heat(self):
        """The picture of a 2D heat and stress solve with no flow against the numbers of the solve: (1) the displacement the body is drawn with is the largest one of the stress result; (2) the bent
        outline never moves further than that; (3) every particle is back where it began after the last frame; (4) the temperature drawn runs over the range of the heat result; (5) every point of
        every tracer line lies inside the body (the mesh of the heat analysis); (6) every tracer line runs from hot to cold: it ends no hotter than it starts (heat flows down the temperature)."""
        import coupled_engine as ce
        d, res = self.data, self.solve_result()
        if d is None or res is None:
            return []
        rows = []
        b = d.get("body")
        sm = res.get("structural") or {}
        fe = self.tab2d("fea", "structural")
        if b is not None and sm.get("umax") is not None and fe is not None:
            import units
            umax = float(sm["umax"]) * float(units.get(fe.unit_name())["L_m"]) * 1000.0
            if umax > 0:
                got = float(b["u_range"][1])
                rows.append({"name": "Displacement drawn", "ok": abs(got - umax) <= 0.005 * umax, "expected": f"{umax:.5g} mm (the stress result)", "got": f"{got:.5g} mm"})
                reach = V.bend_reach(d)
                rows.append({"name": "Bent outline within that displacement", "ok": reach <= umax * 1.005, "expected": f"at most {umax:.5g} mm", "got": f"{reach:.5g} mm"})
        n = int(d["options"]["frames"])
        gap = V.particle_gap(d, n, 0)
        span = max(d["window"][1] - d["window"][0], d["window"][3] - d["window"][2])
        rows.append({"name": "Animation repeats without a jump", "ok": gap <= 1e-6 * span, "expected": "0 between the last frame and the first", "got": f"{gap:.3g}"})
        th = res.get("thermal") or {}
        tr = d["thermal"]["T_range"]
        if "T_min" in th and "T_max" in th:
            lo, hi = float(th["T_min"]) - 273.15, float(th["T_max"]) - 273.15
            tol = max(0.5, 0.05 * (hi - lo))
            rows.append({"name": "Temperature range", "ok": abs(tr[0] - lo) <= tol and abs(tr[1] - hi) <= tol, "expected": f"{lo:.4g} .. {hi:.4g} degC (the heat analysis, within {tol:.2g} K)",
                         "got": f"{tr[0]:.4g} .. {tr[1]:.4g} degC"})
        if d["lines"]:
            field = d["field"]
            pts = np.vstack(d["lines"])
            inside = field.locate(pts) >= 0
            rows.append({"name": "Tracer lines inside the body", "ok": bool(inside.all()), "expected": "every point of every line in the mesh of the heat analysis", "got": f"{int(inside.sum())} of {len(inside)} points"})
            t = d["thermal"]
            loc = ce.Locator(t["xy"], t["tris"])
            first = np.array([ln[0] for ln in d["lines"]])
            last = np.array([ln[-1] for ln in d["lines"]])
            Tf, _i = loc.interpolate(t["T"], first)
            Tl, _i = loc.interpolate(t["T"], last)
            rise = float((np.asarray(Tl) - np.asarray(Tf)).max())
            tol = 0.01 * max(t["T_range"][1] - t["T_range"][0], 1e-9)
            rows.append({"name": "Tracer lines run from hot to cold", "ok": rise <= tol, "expected": f"no line ends hotter than it starts (within {tol:.2g} K)", "got": f"the largest rise along a line is {rise:.3g} K"})
        return rows

    def self_check3d(self):
        """The 3D picture against the results it was made from: (1) the displacement the part is drawn with is the largest one of the stress result; (2) the bent shape never moves further than
        that (the exaggeration taken out); (3) the temperatures drawn lie inside the range of the heat result; (4) every point of the surface found a place on the surface of the heat mesh;
        (5) the von Mises stress drawn does not exceed the largest one of the stress result."""
        d, sr, tr = self.data, self.solid_result(), self.thermal_result()
        if d is None or sr is None:
            return []
        rows = []
        umax = float(sr["umax"])
        got = float(d["ranges"]["u"][1])
        rows.append({"name": "Displacement drawn", "ok": got <= umax * (1 + 1e-6) and got >= 0.98 * umax, "expected": f"{umax:.5g} mm (the stress result; the surface holds its largest)", "got": f"{got:.5g} mm"})
        reach = V3.bend_reach3d(d, exaggeration=self.exaggeration3())
        rows.append({"name": "Bent shape within that displacement", "ok": reach <= umax * 1.005, "expected": f"at most {umax:.5g} mm", "got": f"{reach:.5g} mm"})
        rng = d["ranges"].get("T")
        if rng is not None and tr is not None:
            lo, hi = float(tr["Tmin"]) - 273.15, float(tr["Tmax"]) - 273.15
            tol = max(0.5, 0.05 * (hi - lo))
            rows.append({"name": "Temperature inside the heat result's range", "ok": rng[0] >= lo - tol and rng[1] <= hi + tol, "expected": f"{lo:.4g} .. {hi:.4g} degC (within {tol:.2g} K)",
                         "got": f"{rng[0]:.4g} .. {rng[1]:.4g} degC"})
            gap = d.get("T_gap")
            if gap is not None:
                rows.append({"name": "Every point of the surface found on the heat mesh", "ok": gap <= 0.5, "expected": "at most 0.5 element sizes from the surface of the heat mesh", "got": f"{gap:.3g} element sizes"})
        vr = d["ranges"].get("vm")
        if vr is not None and sr.get("vm_max") is not None:
            rows.append({"name": "Von Mises stress inside the stress result's range", "ok": vr[1] <= float(sr["vm_max"]) * 1.001 + 1e-9, "expected": f"at most {float(sr['vm_max']):.5g} MPa", "got": f"{vr[1]:.5g} MPa"})
        rows += self.self_check_tracers3()
        return rows

    def self_check_tracers3(self):
        """The heat-flux tracers of the 3D picture against the heat result they were made from: (1) every point of every line lies inside a tetrahedron of the heat mesh; (2) no line ends hotter
        than it starts (heat goes from hot to cold); (3) the lines are drawn with the displacement they were given: the bend of the lines at the last frame is the displacement of the part."""
        d, tr = self.data, self.thermal_result()
        t = d.get("tracers") if d is not None else None
        field = d.get("field3") if d is not None else None
        if not t or not t["lines"] or field is None or tr is None:
            return []
        rows = []
        pts = np.vstack(t["lines"])
        out = int((field.locate(pts) < 0).sum())
        rows.append({"name": "Tracer lines inside the part", "ok": out == 0, "expected": "every point of every line inside a tetrahedron of the heat mesh", "got": f"{out} of {len(pts)} points outside"})
        T = np.asarray(tr["T"], float)
        vals = T[np.asarray(tr["conn"])[:, :4]]
        rise = 0.0
        for ln in t["lines"]:
            Tl = field.scalar_at(vals, ln[[0, -1]])
            if np.all(np.isfinite(Tl)):
                rise = max(rise, float(Tl[1] - Tl[0]))
        tol = max(0.5, 0.02 * float(tr["Tmax"] - tr["Tmin"]))
        rows.append({"name": "Tracer lines run from hot to cold", "ok": rise <= tol, "expected": f"no line ends hotter than it starts (within {tol:.2g} K)", "got": f"the largest rise along a line is {rise:.3g} K"})
        umax = max((float(np.linalg.norm(dsp, axis=1).max()) for dsp in t["disp"] if len(dsp)), default=0.0)
        top = float(d["ranges"]["u"][1])
        rows.append({"name": "Tracer lines bend within the displacement of the part", "ok": umax <= top * (1 + 1e-6) + 1e-12, "expected": f"at most {top:.5g} mm (the largest displacement of the surface)", "got": f"{umax:.5g} mm"})
        return rows

    def say(self, text):
        try:
            self.win.say(text)
        except Exception:                                                              # noqa: BLE001
            pass
