"""coupled_viz.py - the Viz tab of the Coupled Physics window: the RENDERED picture of the last coupled solve, with a playback bar and the two ways of saving it.  The numbers behind it are in
coupled_viz_core (no Qt); this file draws them with QPainter (no matplotlib).

What is in the picture (every layer can be switched on and off in the Outline on the left): the air temperature or pressure on the air mesh (one at a time), the body with its displacement or
von Mises stress (one at a time), the tracers (streamlines of the last pass with particles travelling along them), and the outline of the body as the flow bent it, drawn exaggerated.
It shows the LAST solve: nothing here changes a result, and nothing is solved again.  With no solve yet the picture says so.  The picture is made for a 2D solve; a 3D pair says so too.

Looked at only in a headless Qt (frames drawn, saved and compared with the numbers); never seen on a real screen."""
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

import coupled_viz_core as V
import sim_ui

EMPTY = "No solve yet. Press Solve in the Coupled tab: the rendered result appears here."
NO_3D = "Viz of 3D results comes with the 3D fluid flow work."
NO_FLUID = "The picture is made for a solve with a flow in it: wire a 2D Fluid Flow analysis into the block, and solve."
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
        self.setMinimumSize(420, 320)

    # ------------------------------------------------------------------ what is drawn
    def static_image(self, fit, scale, lay):
        """The air and the body as one picture (cached: they do not move)."""
        d = self.page.data
        key = (id(d), fit.w, fit.h, scale, lay.get("air_T"), lay.get("air_p"), lay.get("body_u"), lay.get("body_vm"))
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
        lay = V.effective_layers(d, pg.layers)
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

    def paint_bars(self, p, w, h, pw, d, lay):
        bars = V.colour_bars(d, self.page.layers)
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
        self.exaggeration = V.DEFAULTS["exaggeration"]
        self.opts = {"lines": V.DEFAULTS["lines"], "per_line": V.DEFAULTS["per_line"], "trail": V.DEFAULTS["trail"]}
        self.player = V.Player()
        self.last_tick = None
        self.build_panel()
        self.build_picture()

    # ------------------------------------------------------------------ the panel
    def build_panel(self):
        s1 = sim_ui.Section("viz", 1, "Layers", True)
        s1.body.addWidget(sim_ui.wrapped("What the picture shows. The air shows one field at a time (temperature or pressure), and so does the body (displacement or von Mises stress)."))
        self.boxes = {}
        for key, name, _g in V.LAYERS:
            cb = QCheckBox(name)
            cb.setChecked(bool(self.layers[key]))
            cb.toggled.connect(lambda on, k=key: self.layer_toggled(k, on))
            s1.body.addWidget(cb)
            self.boxes[key] = cb
        row = QHBoxLayout()
        row.addWidget(QLabel("Exaggeration of the bent outline (x)"))
        self.e_ex = QDoubleSpinBox()
        self.e_ex.setRange(1.0, 1000.0)
        self.e_ex.setDecimals(1)
        self.e_ex.setValue(self.exaggeration)
        self.e_ex.setToolTip("The displacement of the body is far smaller than its size. The dashed outline shows it this many times larger, and says so under the picture.")
        self.e_ex.valueChanged.connect(self.exaggeration_changed)
        row.addWidget(self.e_ex)
        s1.body.addLayout(row)

        s2 = sim_ui.Section("viz", 2, "Tracers", True)
        s2.body.addWidget(sim_ui.wrapped("The tracers follow the velocity of the last pass of the coupled solve, round the body as the flow bent it. The air temperature is the one from the heat exchange."))
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Lines starting on the inlet"))
        self.e_lines = QSpinBox()
        self.e_lines.setRange(3, 101)
        self.e_lines.setValue(self.opts["lines"])
        self.e_lines.valueChanged.connect(self.tracers_changed)
        r1.addWidget(self.e_lines)
        s2.body.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Particles on each line"))
        self.e_per = QSpinBox()
        self.e_per.setRange(1, 8)
        self.e_per.setValue(self.opts["per_line"])
        self.e_per.valueChanged.connect(self.tracers_changed)
        r2.addWidget(self.e_per)
        s2.body.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Trail length (mm)"))
        self.e_trail = QDoubleSpinBox()
        self.e_trail.setRange(0.5, 60.0)
        self.e_trail.setValue(self.opts["trail"])
        self.e_trail.valueChanged.connect(self.trail_changed)
        r3.addWidget(self.e_trail)
        s2.body.addLayout(r3)

        s3 = sim_ui.Section("viz", 3, "Animation and export", True)
        s3.body.addWidget(sim_ui.wrapped(f"{V.DEFAULTS['frames']} frames at {V.DEFAULTS['fps']} frames per second. The result is steady: the body bends from nothing to its final shape over the first "
                                         "half, and every particle goes once along its line. How fast the particles go on the screen is not how fast the air goes. The last frame is the still picture."))
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

    def decide(self):
        """Is there something to draw?  Sets self.why (None when there is)."""
        res = self.solve_result()
        if res is None:
            self.why = EMPTY
        elif int(res.get("dim") or 2) == 3:
            self.why = NO_3D
        elif not res.get("fluid") or "steps" not in (res.get("fluid") or {}):
            self.why = NO_FLUID
        else:
            fl, _st = self.members()
            self.why = None if (fl is not None and getattr(fl, "result", None) is not None and fl.result.get("xy_sketch") is not None) else "The result of the flow is not here any more: solve again."
        return self.why is None

    def make_data(self):
        """The data of the last solve, from the analyses shown in the window (the flow of the last pass, the stress result, the geometry)."""
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
        if has:
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

    def layer_toggled(self, key, on):
        self.layers = V.set_layer(self.layers, key, on)
        for k, cb in self.boxes.items():
            if cb.isChecked() != bool(self.layers[k]):
                cb.blockSignals(True)
                cb.setChecked(bool(self.layers[k]))
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

    def tracers_changed(self, *_):
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

    def say(self, text):
        try:
            self.win.say(text)
        except Exception:                                                              # noqa: BLE001
            pass
