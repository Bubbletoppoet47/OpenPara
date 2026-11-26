"""
CFD tab for the sketcher: 2D incompressible flow around the closed shapes of an imported sketch.

  Left   : import, bodies, fluid and flow, domain, mesh, solver, results
  Right  : the picture - wheel = zoom, middle-drag = pan

Stage 1 (this file): laminar Navier-Stokes by finite elements (see physics_cfd.py).
Needs numpy, scipy and gmsh:   pip install numpy scipy gmsh
"""
import math
import platform
import threading
import sys
import time
import traceback

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QCursor, QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                             QSlider, QSplitter, QTextEdit, QToolButton, QVBoxLayout, QWhatsThis, QWidget)

import physics_cfd as pcfd
import physics_cfd_heat as pheat
import physics_refine as prefine
import units
import unitctl
import heatunits as hu
import physics_solve as psolve
import result_style
import physics_store as pstore
import physics_geom as pg
import physics_tab as pt
import sim_mesh2d as sm2
import sim_meshhost
import sim_meshui
import sim_ui
import legend_draw
import anim_export
import sketcher_core as sc
from sketch_pick import SketchPicker
import sketcher_script as scr

FIELD_LIST = [("Speed", "speed", "node", "m/s"), ("Velocity X", "ux", "node", "m/s"), ("Velocity Y", "uy", "node", "m/s"),
              ("Pressure (gauge, relative to the outlet)", "p", "node", "Pa"),
              ("Vorticity (per element, from the vertex velocities)", "vort", "elem", "1/s"),
              ("Turbulent kinetic energy k (turbulence model)", "k", "node", "m2/s2"),
              ("Specific dissipation omega (turbulence model)", "omega", "node", "1/s"),
              ("Eddy viscosity ratio nut/nu (turbulence model, per element)", "nut", "elem", "-"),
              ("Temperature of the fluid (heat transfer)", "T", "node", "K")]


HELP = {
    "unit": "The unit system is chosen in File > Units and is shared with the sketch and the FEA tab. Everything is converted to SI inside, so Reynolds number, forces "
            "and pressures come out right. A wrong unit changes Re and every pressure by orders of magnitude.",
    "fluid": "Presets fill in the density and viscosity below with typical values (check your source). Choose Custom to type your own.",
    "rho": "Density of the fluid. Pressure results scale with it: dynamic pressure q = 1/2 rho U^2. Air is about 1.2 kg/m3 (shown here in your unit system).",
    "mu": "Dynamic viscosity of the fluid. Together with density, speed and size it sets the Reynolds number Re = rho U L / mu, "
          "which decides whether the flow is smooth (low Re) or turbulent (high Re). Air is about 1.8e-5 Pa s (shown here in your unit system).",
    "speed": "Wind speed far upstream. Wind loads grow with the square of it. It also sets Re and the automatic time step.",
    "angle": "Direction the wind blows toward: 0 = along +x, 90 = along +y. Box sides facing the wind become inlets, the "
             "opposite sides outlets. A side the wind runs exactly along becomes a free-slip wall.",
    "margin": "How far the box extends past the bodies on this side, in multiples of the body size. Too small and the box walls "
              "squeeze the flow and distort the pressures; the downstream side needs the most room for the wake. "
              "Typical: 5 on the upstream and sides, 10 to 15 downstream. Bigger = more elements = slower.",
    "hb": "Element size on the body surface (sketch units). Smaller resolves the surface pressure better but costs time. "
          "A good start is the body size / 40. With the turbulence model the boundary-layer layers sit on top of this.",
    "hf": "Element size at the outer edge of the box (sketch units). Far from the body the flow is smooth, so this can be coarse. "
          "Larger = fewer elements = faster.",
    "tr": "Distance, in body sizes, over which the element size grows from the body value to the far value. Short = few elements "
          "but a coarse wake and a worse answer; long = more accurate wake, more elements.",
    "model": "Laminar solves the Navier-Stokes equations as they are: right only for smooth, low-Reynolds flow (up to roughly "
             "hundreds to a few thousand). Wind around structures is turbulent (Re 1e5 and up), so use k-omega SST: it adds "
             "the effect of turbulence and resolves the wall layer. Needs the boundary-layer mesh below.",
    "intensity": "Free-stream turbulence level: size of the incoming velocity fluctuations as a percent of the wind speed. "
                 "Wind tunnel about 0.5 to 1 %, open terrain wind about 5 to 20 %. It sets the inflow turbulent energy "
                 "k = 1.5 (I U)^2 and affects where the flow separates.",
    "ratio": "Eddy viscosity ratio at the inlet: turbulent viscosity divided by the molecular one. 1 to 10 for clean flow, "
             "10 is a common default, up to 100 or more for very turbulent inflow. It sets the inflow value of omega.",
    "yplus": "Target height of the first mesh layer above the wall, in wall units y+. The SST model resolves the wall layer and "
             "needs y+ of about 1 (up to 5 is tolerable). Smaller = more accurate wall shear and pressure but more layers. "
             "The report shows the y+ actually reached.",
    "growth": "How much thicker each boundary-layer layer is than the one below it (1.1 to 1.3). Smaller = smoother but needs "
              "more layers; larger = fewer layers but coarser.",
    "first": "Height of the first layer above the wall, in the length unit of the unit system. Leave blank to use the flat-plate estimate from the target y+. "
             "Typing a value overrides the estimate.",
    "bl_thick": "Total thickness of the boundary-layer mesh, in the length unit of the unit system. Leave blank to use the flat-plate estimate. It should "
                "cover the real boundary layer, which grows with the length of the body.",
    "cfl": "How far the flow travels in one time step, in units of the element size at the body. The solver is implicit, so "
           "5 to 50 works for finding a steady state: larger = fewer steps to settle but rougher in time and it may fail to "
           "converge; smaller = slower but safer. If the run blows up or oscillates, lower it.",
    "dt": "Time step in seconds. Leave blank to use CFL x element size at the body / wind speed. Typing a value overrides it.",
    "until": "Ignore the step limit and keep going until the solution has settled (the change per step stays below the "
             "tolerance for 3 steps). Stop always works. If the change stops improving for a long stretch the run pauses and "
             "asks whether to continue: an unsteady flow (for example vortex shedding at high Reynolds number) never settles "
             "to a steady state however long it runs.",
    "auto": "After the flow settles, find where velocity and pressure change fastest, refine the mesh there and solve again, until the "
            "force on the bodies (along and across the wind) changes by less than 1 % between two meshes. A pass is only judged if "
            "its time marching settled (the change-per-step plot below, which keeps running across the passes); if it did not, "
            "refining stops, because a finer mesh will not fix a run that never settles. Starts from the mesh you made with Mesh.",
    "passes": "The most refinement passes allowed after the first solve. The run stops here even if the forces are still changing.",
    "maxtris": "Largest number of triangles allowed. A refinement that would pass this is not used, and the run stops with the last "
               "mesh that fitted. Each pass costs more time than the one before.",
    "ramp": "Gentle start: the time step begins at 10 % of its full size and grows to 100 % over this many steps. "
            "It calms the violent first steps from the impulsive start and often helps a hard flow settle. 0 turns it off. "
            "Convergence is not judged during the ramp.",
    "steps": "Upper limit on the number of time steps, so a flow that never settles does not run forever. The run stops earlier "
             "if it converges.",
    "tol": "Stop when the relative change of the solution between two steps (velocity, pressure and, with turbulence, k and "
           "omega) stays below this for 3 steps in a row. 1e-5 is typical; smaller = more converged but longer.",
    "every": "Keep a picture of the flow every this many steps so you can scrub or play it back. Smaller = smoother playback "
             "but more memory (older frames are thinned out automatically past 120).",
    "field": "Which quantity is coloured. Speed and pressure are the main ones. Pressure is gauge, relative to the outlet. "
             "With turbulence on you can also show k, omega and the eddy viscosity ratio.",
    "mesh_lines": "Draws the triangle edges on top of the picture, to judge the mesh.",
    "slider": "Frames saved while solving. Drag to look at earlier steps; the last one is the final state.",
    "tracers": "Small particles carried by the final flow, to see where the air goes. Display only, not part of the result.",
    "select": "Click an edge of a solid body on the drawing to select it (Ctrl-click adds or removes more, Esc clears). "
              "The numbers show the pressure and force the flow puts on it. 'Use selection in FEA' selects the same edges in "
              "the FEA tab and opens the pressure-transfer dialog; only the edges you picked are loaded.",
    "heat": "Also finds the temperature of the fluid: the flow carries heat along (convection) while the fluid conducts it. The walls you choose get a fixed "
            "temperature or a heat flux, the wind arrives at the inlet temperature, and every other wall is insulated. The temperature does not change the flow "
            "(density and viscosity stay as typed), so this is right for forced convection with modest temperature differences; hot air rising (buoyancy) is not modelled.",
    "k": "Thermal conductivity of the fluid. Air is about 0.026 W/(m K), water about 0.6 W/(m K) (shown here in your heat-transfer units, File > Units).",
    "cp": "Specific heat of the fluid at constant pressure. Air is about 1006 J/(kg K), water about 4182 J/(kg K). The Prandtl number mu cp / k, shown below, is "
          "about 0.7 for air and 7 for water: the larger it is, the thinner the layer of heated fluid at the wall, so the finer the mesh must be there.",
    "tin": "Temperature of the wind far upstream. It is the temperature at every inlet side of the box.",
    "wall_heat": "Select edges of the bodies on the drawing, then Set on selected edges: a fixed temperature, or a heat flux into the fluid (negative = heat taken "
                 "out of the fluid). An edge that is not listed is insulated: no heat passes through it.",
    "bodies": "Tick the closed outlines that are solid. Outlines inside another outline are ignored. Shared edges between ticked "
              "bodies are treated as inside the solid.",
}


def _wheel_step():
    try:
        import settings
        return settings.zoom_factor()
    except Exception:
        return 1.08


class HelpLabel(QLabel):
    """A form label that explains the input: click it for a note that stays until you click elsewhere (no hover popup)."""

    def __init__(self, text, help_text):
        super().__init__(text)
        self.help = help_text
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet("color:#1f4e8c;")

    def mousePressEvent(self, ev):
        QWhatsThis.showText(QCursor.pos(), "<div style='width:320px'>" + self.help + "</div>", self)


class HelpButton(QToolButton):
    """A small '?' next to a control; click it for the note."""

    def __init__(self, help_text):
        super().__init__()
        self.help = help_text
        self.setText("?")
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet("QToolButton{color:#1f4e8c; border:1px solid #9bb3d3; border-radius:10px; font-weight:bold;}"
                           "QToolButton:hover{background:#e8f0fb;}")
        self.clicked.connect(lambda: QWhatsThis.showText(QCursor.pos(), "<div style='width:320px'>" + self.help + "</div>", self))


def with_help(widget, help_text):
    """The widget with a '?' button on its right."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(widget, 1)
    h.addWidget(HelpButton(help_text))
    return w


def run_heat(mesh, res, heat, cancel=None):
    """The temperature of the fluid on a solved flow, put into `res` (res["heat"]).  A problem with the temperature does not throw the flow away:
    it is written to res["heat_error"] and the window shows it."""
    try:
        hres = pheat.solve_temperature(mesh, res, heat, cancel=cancel)
        if res["status"] != "converged":
            hres["notes"].append("The flow did not converge, so this temperature belongs to its last step, not to a steady flow.")
        pheat.attach(res, hres)
    except pcfd.Cancelled:
        pass
    except pcfd.ModelError as ex:
        res["heat_error"] = str(ex)
    except Exception:                                                                 # noqa: BLE001
        res["heat_error"] = "The temperature solve hit an error:\n" + traceback.format_exc()
    return res


class SolveWorker(QThread):
    progress = pyqtSignal(int, int, float, float, float, float, float)
    frame = pyqtSignal(object)
    done = pyqtSignal(object)
    failed = pyqtSignal(str, bool)
    stall = pyqtSignal(object)
    newmesh = pyqtSignal(object, int)

    def __init__(self, mesh, setup, refine=None, heat=None):
        super().__init__()
        self.mesh, self.setup, self.refine, self.heat = mesh, setup, refine, heat
        self.stop = False
        self.event = threading.Event()
        self.answer = "stop"

    def ask_stall(self, info):
        """Called from the solver thread: ask the window whether to keep going, and wait for the answer."""
        self.answer = "stop"
        self.event.clear()
        self.stall.emit(info)
        while not self.event.wait(0.2):
            if self.stop:
                return "stop"
        return self.answer

    def run(self):
        try:
            setup = dict(self.setup)
            setup["on_stall"] = self.ask_stall
            mesh_final = self.mesh
            if self.refine:
                out = prefine.cfd_auto(self.mesh, setup, self.refine["mesh_args"], self.refine["passes"], self.refine["max_tris"],
                                       progress=lambda *a: self.progress.emit(*a), frame=lambda f: self.frame.emit(f),
                                       cancel=lambda: self.stop, on_mesh=lambda mesh, k: self.newmesh.emit(mesh, k))
                res = out["result"]
                res["refine"] = {"log": out["log"], "reason": out["reason"]}
                res["all_history"] = out["all_history"]
                mesh_final = out["mesh"]
            else:
                res = pcfd.solve(self.mesh, setup, progress=lambda *a: self.progress.emit(*a),
                                 frame=lambda f: self.frame.emit(f), cancel=lambda: self.stop)
            if self.heat and res["status"] != "stopped":
                run_heat(mesh_final, res, self.heat, cancel=lambda: self.stop)
            self.done.emit(res)
        except (pcfd.ModelError, pg.GeometryError) as ex:
            self.failed.emit(str(ex), True)
        except Exception:
            self.failed.emit(traceback.format_exc(), False)


class ConvergencePlot(QWidget):
    """Change per step against the step number (log scale), with the tolerance as a dashed line."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(130)
        self.setMaximumHeight(170)
        self.steps, self.du, self.dp, self.dt = [], [], [], []
        self.tol = None

    def clear(self):
        self.steps, self.du, self.dp, self.dt = [], [], [], []
        self.update()

    def add(self, step, du, dp, dt):
        self.steps.append(step)
        self.du.append(du)
        self.dp.append(dp)
        self.dt.append(dt)
        if len(self.steps) % 3 == 0 or len(self.steps) < 30:
            self.update()

    def set_history(self, history, tol):
        self.steps = [h[0] for h in history]
        self.du = [h[2] for h in history]
        self.dp = [h[3] for h in history]
        self.dt = [h[4] for h in history]
        self.tol = tol
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        W, H = self.width(), self.height()
        l, r, t, b = 38, 8, 18, 22
        p.setPen(QColor("#555555"))
        p.setFont(QFont("Arial", 8))
        p.drawText(l, 12, "Change per step (log)")
        p.drawRect(l, t, W - l - r, H - t - b)
        if len(self.steps) < 2:
            p.drawText(l + 6, t + 16, "no run yet" if not self.steps else "")
            return
        allv = [v for series in (self.du, self.dp, self.dt) for v in series if v > 0]
        if self.tol:
            allv.append(self.tol)
        lo = math.floor(math.log10(max(min(allv), 1e-14)))
        hi = math.ceil(math.log10(max(max(allv), 1e-14)))
        if hi <= lo:
            hi = lo + 1
        n = len(self.steps)
        x0, x1 = self.steps[0], max(self.steps[-1], self.steps[0] + 1)

        def X(s_):
            return l + (s_ - x0) / (x1 - x0) * (W - l - r)

        def Y(v):
            return t + (hi - math.log10(max(v, 1e-14))) / (hi - lo) * (H - t - b)
        for d in range(lo, hi + 1):
            y = Y(10.0 ** d)
            p.setPen(QPen(QColor("#dddddd"), 1))
            p.drawLine(l, int(y), W - r, int(y))
            p.setPen(QColor("#555555"))
            p.drawText(2, int(y) + 4, f"1e{d}")
        p.drawText(l, H - 6, f"step {x0}")
        p.drawText(W - r - 60, H - 6, f"step {x1}")
        stride = max(1, n // 500)
        for series, col in ((self.du, "#1f5fbf"), (self.dp, "#c0182b"), (self.dt, "#1a7a1a")):
            if not any(v > 0 for v in series):
                continue
            pts = [QPointF(X(self.steps[i]), Y(series[i])) for i in range(0, n, stride) if series[i] > 0]
            p.setPen(QPen(QColor(col), 1.4))
            p.drawPolyline(QPolygonF(pts))
        if self.tol:
            p.setPen(QPen(QColor("#777777"), 1, Qt.PenStyle.DashLine))
            p.drawLine(l, int(Y(self.tol)), W - r, int(Y(self.tol)))
        x = W - r - 150
        for txt, col in (("velocity", "#1f5fbf"), ("pressure", "#c0182b"), ("turbulence", "#1a7a1a")):
            p.setPen(QColor(col))
            p.drawText(x, 12, txt)
            x += 50


# ----------------------------------------------------------------------------------------------
# the picture
# ----------------------------------------------------------------------------------------------
class CFDCanvas(pt.PhysCanvas):
    def __init__(self, tab):
        super().__init__(tab)
        self.raster = None            # which triangle (and where in it) every pixel shows, for the current view
        self.base = None              # {"pix", "view", "stamp"}: the coloured field as a picture
        self.mesh_pix = None
        self.mesh_key = None
        self.rebuild_now = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.on_timer)
        self.particles = None         # {"p": (n,2) sketch units, "trail": [...], "age": (n,)}

    # --- view
    def view_key(self):
        return (round(self.scale, 6), round(self.org.x(), 2), round(self.org.y(), 2), self.width(), self.height())

    def fit(self):
        tab = self.tab
        if tab.geom is None:
            return
        if tab.mesh is not None:
            x0, y0, x1, y1 = tab.mesh["box"]
        else:
            xs, ys = [], []
            for pts in tab.geom["polys"]:
                xs += [q[0] for q in pts]
                ys += [q[1] for q in pts]
            if not xs:
                return
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        w, h = x1 - x0, y1 - y0
        W, H = max(self.width(), 200), max(self.height(), 200)
        self.scale = 0.92 * min(W / max(w, 1e-9), H / max(h, 1e-9))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.org = QPointF(W / 2 - cx * self.scale, H / 2 + cy * self.scale)
        self.invalidate()

    def hit(self, sp):
        """The solid-body edge under the pointer (a sketch edge key such as ('ln', 5)), or None."""
        tab = self.tab
        if tab.geom is None:
            return None
        ok = tab.selectable()
        best = None
        for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
            if ok is not None and e["src"] not in ok:
                continue
            sp_pts = [self.w2s(*q) for q in pts]
            if e["kind"] == "ci":
                sp_pts.append(sp_pts[0])
            for a, b in zip(sp_pts[:-1], sp_pts[1:]):
                d = self.seg_dist(sp, a, b)
                if d < 7 and (best is None or d < best[0]):
                    best = (d, e["src"])
        return best[1] if best else None

    def invalidate(self):
        self.update()

    def on_timer(self):
        self.rebuild_now = True
        self.update()

    def wheelEvent(self, ev):
        f = _wheel_step() ** (ev.angleDelta().y() / 120.0)
        pos = ev.position()
        wx, wy = self.s2w(pos)
        self.scale *= f
        self.org = QPointF(pos.x() - wx * self.scale, pos.y() + wy * self.scale)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton and self.pan_from is not None:
            self.org = QPointF(self.org.x() + self.pan_off.x(), self.org.y() + self.pan_off.y())
            self.pan_from = None
            self.pan_off = QPointF(0, 0)
            self.update()

    # --- the field picture
    def build_raster(self):
        import meshdraw as md
        mesh = self.tab.mesh
        W, H = max(self.width(), 10), max(self.height(), 10)
        nodes, tris = mesh["nodes"], mesh["tris"]
        self.gpu = md.backend() == "gpu"
        self.sx = self.org.x() + nodes[:, 0] * self.scale
        self.sy = self.org.y() - nodes[:, 1] * self.scale
        R = None if self.gpu else md.raster(W, H, self.sx, self.sy, tris)     # the GPU draws straight from the triangles
        self.raster = {"key": self.view_key(), "R": R, "W": W, "H": H, "gpu": self.gpu}
        self.mesh_pix = None
        self.mesh_key = None

    def build_base(self, data):
        import meshdraw as md
        R = self.raster
        vals, kind = data["values"], data["kind"]
        lo, hi = float(np.min(vals)), float(np.max(vals))
        span = (hi - lo) or 1.0
        W, H = R["W"], R["H"]
        tris = self.tab.mesh["tris"]
        t = (np.asarray(vals, dtype=float) - lo) / span
        img = None
        if R["gpu"]:
            if md.backend() == "gpu":
                img = md.render(W, H, self.sx, self.sy, tris, nodal=vals if kind == "node" else None,
                                tri_vals=None if kind == "node" else vals, lo=lo, hi=hi)
            if img is None or md.backend() != "gpu":          # the GPU gave up while drawing: carry on on the CPU
                img = None
                R["R"] = md.raster(W, H, self.sx, self.sy, tris)
                R["gpu"] = False
        if img is None:
            img = md.colour_raster(W, H, R["R"], t if kind == "node" else None, tris, None if kind == "node" else t)
        pix = QPixmap.fromImage(img)
        self.base = {"pix": pix, "view": (self.scale, QPointF(self.org)), "stamp": data["stamp"], "lo": lo, "hi": hi}

    def build_mesh_pix(self):
        import meshdraw as md
        mesh = self.tab.mesh
        nodes = mesh["nodes"]
        sx = self.org.x() + nodes[:, 0] * self.scale
        sy = self.org.y() - nodes[:, 1] * self.scale
        e = md.unique_edges(mesh["tris"])
        self.mesh_pix = QPixmap.fromImage(md.edge_overlay(max(self.width(), 10), max(self.height(), 10), sx, sy, e, 0.31))
        self.mesh_key = self.view_key()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg_color())
        tab = self.tab
        if tab.geom is None:
            p.setPen(QColor("#666666"))
            p.setFont(QFont("Arial", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Choose a sketch and press Import (left) to begin.")
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.pan_from is not None:
            p.translate(self.pan_off)
        data = tab.field_data() if (tab.mesh is not None and self.shows("result")) else None
        legend = None
        if tab.mesh is not None and data is not None:
            vk = self.view_key()
            if self.raster is None or self.raster["key"] != vk:
                if self.base is not None and self.raster is not None and self.pan_from is None and not self.rebuild_now:
                    self.timer.start(140)                    # show the old picture, scaled, until the zoom settles
                    r = self.scale / self.base["view"][0]
                    o = self.base["view"][1]
                    p.save()
                    p.translate(self.org.x() - r * o.x(), self.org.y() - r * o.y())
                    p.scale(r, r)
                    p.drawPixmap(0, 0, self.base["pix"])
                    p.restore()
                    self.paint_overlay(p, data, stale=True)
                    return
                if self.pan_from is None:
                    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    try:
                        self.build_raster()
                    finally:
                        QGuiApplication.restoreOverrideCursor()
                    self.rebuild_now = False
                    self.base = None
            if self.raster is not None and self.raster["key"] == vk:
                if self.base is None or self.base["stamp"] != data["stamp"] or self.base["view"][0] != self.scale:
                    self.build_base(data)
                p.drawPixmap(0, 0, self.base["pix"])
            elif self.base is not None:
                p.drawPixmap(0, 0, self.base["pix"])
            legend = (data["name"], self.base["lo"], self.base["hi"], data["unit"]) if self.base else None
        self.paint_overlay(p, data, stale=False)
        p.resetTransform()
        self.paint_tag_chips(p)
        if legend:
            self.paint_legend2(p, *legend)

    def paint_overlay(self, p, data, stale):
        tab = self.tab
        mesh = tab.mesh
        if self.focus is None:
            want_mesh = tab.cb_mesh.isChecked() or data is None
        else:
            want_mesh = self.shows("mesh") or (self.shows("result") and data is not None and tab.cb_mesh.isChecked())
        if mesh is not None and want_mesh and not stale:
            if self.mesh_pix is None or self.mesh_key != self.view_key():
                self.build_mesh_pix()
            p.drawPixmap(0, 0, self.mesh_pix)
        # bodies
        for f in tab.geom["faces"]:
            if f["id"] in tab.body_on:
                p.fillPath(self.body_path(f), QColor(90, 90, 100))
            elif f["depth"] == 0:
                p.fillPath(self.body_path(f), QBrush(QColor(110, 110, 110, 160), Qt.BrushStyle.BDiagPattern))
        for e, pts in zip(tab.geom["edges"], tab.geom["polys"]):
            p.setPen(QPen(QColor("#202030"), 1.6))
            poly = QPolygonF([self.w2s(*q) for q in pts] + ([self.w2s(*pts[0])] if e["kind"] == "ci" else []))
            p.drawPolyline(poly)
            c_ = tab.heat_walls.get(e["src"]) if tab.cb_heat.isChecked() else None
            if c_ is not None:                                                    # an edge with a heat condition: red = fixed temperature, violet = heat flux, green = thermal analysis
                p.setPen(QPen(QColor({"temp": "#d62728", "flux": "#7b3fa0"}.get(c_["kind"], "#2e8b57")), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline(poly)
            if e["src"] in self.sel:
                p.setPen(QPen(QColor("#ff8c00"), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline(poly)
        if mesh is not None and self.focus in (None, "domain", "mesh"):
            x0, y0, x1, y1 = mesh["box"]
            p.setPen(QPen(QColor("#555555"), 1.2, Qt.PenStyle.DashLine))
            a, b = self.w2s(x0, y1), self.w2s(x1, y0)
            p.drawRect(int(a.x()), int(a.y()), int(b.x() - a.x()), int(b.y() - a.y()))
            kinds, _ = pcfd.classify_sides(tab.angle_value())
            p.setFont(QFont("Arial", 9))
            p.setPen(QColor("#555555"))
            mids = {"bottom": ((x0 + x1) / 2, y0, 0, 14), "top": ((x0 + x1) / 2, y1, 0, -6),
                    "left": (x0, (y0 + y1) / 2, 6, 0), "right": (x1, (y0 + y1) / 2, -52, 0)}
            for side, (mx, my, dx, dy) in mids.items():
                s = self.w2s(mx, my)
                p.drawText(int(s.x() + dx), int(s.y() + dy), kinds[side])
        self.paint_handover(p)
        if self.particles is not None and tab.cb_tracers.isChecked() and self.shows("result"):
            P = self.particles
            p.setPen(QPen(QColor(255, 255, 255, 190), 1.5))
            for trail in P["trail"]:
                if len(trail) > 1:
                    p.drawPolyline(QPolygonF([self.w2s(*q) for q in trail]))
            p.setPen(QPen(QColor(10, 10, 10), 3.2))
            for q in P["p"]:
                p.drawPoint(self.w2s(q[0], q[1]))

    def body_path(self, f):
        path = QPainterPath()
        path.addPolygon(QPolygonF([self.w2s(*q) for q in f["poly"]]))
        path.closeSubpath()
        return path

    def paint_legend2(self, p, name, lo, hi, unit):
        labels = [(k / 5, f"{hi - (k / 5) * (hi - lo):.4g}") for k in range(6)]
        legend_draw.draw_legend(p, self.width(), self.height(), f"{name.split('(')[0].strip()}  [{unit}]", labels, pt.colours,
                                subtitle="(range of the frame shown)")


# ----------------------------------------------------------------------------------------------
# the tab
# ----------------------------------------------------------------------------------------------
class CFDTab(sim_meshhost.Mesh2DHost, QWidget):
    SIZE_BOX = "e_hb"                 # the element size the advanced mesh options are compared with
    LOCAL_REGIONS = False             # a local size goes on edges and points of the bodies
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.model = None
        self.geom = None
        self.mesh = None
        self.result = None
        self.frames = []
        self.field_cache = {}
        self.body_on = set()
        self.worker = None
        self.flow = None
        self.body_size = 1.0
        self.deps = pt.dependency_status()
        self.coords = QLabel("")
        self.canvas = CFDCanvas(self)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay0 = lay
        self.sections = []

        def sec(n, title, open_=True, help_text=None, summary=None):
            s_ = sim_ui.Section("cfd2d", n, title, open_, help_text, summary)
            self.sections.append(s_)
            return s_.body
        missing = [n for n, (v, _) in self.deps.items() if v is None]
        if missing:
            warn = QLabel("<b>Missing:</b> " + ", ".join(missing) + "<br>Install with:<br><code>pip install " +
                          " ".join(missing) + "</code><br>then restart the program.<br><small>" +
                          "<br>".join(f"{n}: {t}" for n, (v, t) in self.deps.items() if v is None) + "</small>")
            warn.setWordWrap(True)
            warn.setStyleSheet("background:#fff3cd; padding:6px; border:1px solid #e0c36a;")
            warn.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(warn)

        lay = sec(1, "Geometry", True, summary=lambda: self.info.text().split("\n")[0][:90])
        self.picker = SketchPicker(self.win, self.import_picked)
        lay.addWidget(self.picker)
        b = QPushButton("Clear (start over)")
        b.setToolTip("Removes the imported copy of the sketch and everything set up on this tab (supports, loads, results...) so you can "
                     "import the sketch again from scratch. The sketch itself is not touched.")
        b.clicked.connect(self.clear_tab)
        lay.addWidget(b)
        self.info = QLabel("Nothing imported yet.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        lay.addWidget(sim_ui.wrapped("Solid bodies (tick = solid; the closed outlines of the sketch)"))
        self.bodies = QListWidget()
        self.bodies.setMaximumHeight(110)
        self.bodies.itemChanged.connect(self.body_toggled)
        lay.addWidget(with_help(self.bodies, HELP["bodies"]))

        lay = sec(2, "Fluid and flow", True, help_text="Units: SI inside; per metre of depth. Typical fluid values - check your source. "
                  "0 deg = the wind blows toward +x, 90 deg = toward +y. Box sides facing the wind are inlets, the opposite sides outlets; a "
                  "side the wind runs exactly along is a free-slip wall.",
                  summary=lambda: f"{self.fluid_combo.currentText()}, {self.e_speed.text()} at {self.e_angle.text()} deg" + (", heat" if self.cb_heat.isChecked() else ""))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.units_note = self.note("")
        self.fluid_combo = QComboBox()
        for n in pcfd.FLUIDS:
            self.fluid_combo.addItem(n)
        self.e_rho = QLineEdit("1.225")
        self.e_mu = QLineEdit("1.789e-5")
        lay_units = self.units_note
        self.row(form, "Fluid", self.fluid_combo, HELP["fluid"])
        self.lbl_rho = self.row(form, "Density", self.e_rho, HELP["rho"])
        self.lbl_mu = self.row(form, "Viscosity", self.e_mu, HELP["mu"])
        lay.addLayout(form)
        lay.addWidget(lay_units)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.inputs_unit = self.unit_name()          # the unit system the numbers in the boxes are in
        self.e_speed = QLineEdit(f"{units.speed_from_si(1.0, self.inputs_unit):.6g}")      # 1 m/s
        self.e_angle = QLineEdit("0")
        self.lbl_speed = self.row(form, "Speed", self.e_speed, HELP["speed"])
        self.row(form, "Direction (deg)", self.e_angle, HELP["angle"])
        lay.addLayout(form)
        self.sides_lbl = self.note("")
        lay.addWidget(self.sides_lbl)
        self.heat_walls = {}                                   # edge key -> {"kind": "temp" | "flux", "v": kelvin | W/m2}: what the user set, always in SI
        self.heat_inputs_units = self.hunits()                 # the heat-transfer units the three boxes below are written in
        self.cb_heat = QCheckBox("Include heat transfer (temperature of the fluid)")
        self.cb_heat.toggled.connect(self.heat_toggled)
        lay.addWidget(with_help(self.cb_heat, HELP["heat"]))
        self.heat_box = QWidget()
        hl = QVBoxLayout(self.heat_box)
        hl.setContentsMargins(14, 0, 0, 0)
        hl.setSpacing(3)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_k, self.e_cp = QLineEdit(""), QLineEdit("")
        self.e_Tin = QLineEdit(f"{hu.from_si('T', self.heat_inputs_units['T'], 293.15):.6g}")          # 20 degrees C
        self.lbl_k = self.row(form, "Conductivity", self.e_k, HELP["k"])
        self.lbl_cp = self.row(form, "Specific heat", self.e_cp, HELP["cp"])
        self.lbl_Tin = self.row(form, "Inlet temperature", self.e_Tin, HELP["tin"])
        hl.addLayout(form)
        self.heat_note = self.note("")
        hl.addWidget(self.heat_note)
        hl.addWidget(HelpLabel("Wall conditions (the other walls are insulated)", HELP["wall_heat"]))
        self.heat_list = QListWidget()
        self.heat_list.setMaximumHeight(90)
        hl.addWidget(self.heat_list)
        row = QHBoxLayout()
        self.b_heat_set = QPushButton("Set on selected edges...")
        self.b_heat_set.clicked.connect(self.ask_wall_condition)
        self.b_heat_off = QPushButton("Remove from selected")
        self.b_heat_off.clicked.connect(lambda: self.remove_wall_conditions())
        row.addWidget(self.b_heat_set)
        row.addWidget(self.b_heat_off)
        hl.addLayout(row)
        self.heat_box.setVisible(False)
        lay.addWidget(self.heat_box)

        lay = sec(3, "Domain", False, help_text="Margins around the bodies, in body sizes.",
                  summary=lambda: f"margins {self.e_ml.text()} / {self.e_mr.text()} / {self.e_mb.text()} / {self.e_mt.text()}")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_ml, self.e_mr, self.e_mb, self.e_mt = QLineEdit("5"), QLineEdit("12"), QLineEdit("5"), QLineEdit("5")
        self.row(form, "Left", self.e_ml, HELP["margin"])
        self.row(form, "Right", self.e_mr, HELP["margin"])
        self.row(form, "Bottom", self.e_mb, HELP["margin"])
        self.row(form, "Top", self.e_mt, HELP["margin"])
        lay.addLayout(form)

        lay = sec(4, "Mesh", False, help_text="Element sizes in sketch units. The boundary layer is used with the turbulence model. Advanced mesh options: make the mesh "
                  "finer at curved edges or on single edges and points of the bodies, set a smallest element, and read how good the elements are.",
                  summary=lambda: f"body {self.e_hb.text() or 'auto'}, far {self.e_hf.text() or 'auto'}")
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_hb, self.e_hf, self.e_tr = QLineEdit(""), QLineEdit(""), QLineEdit("3")
        self.lbl_hb = self.row(form, "At the body", self.e_hb, HELP["hb"])
        self.lbl_hf = self.row(form, "Far away", self.e_hf, HELP["hf"])
        self.row(form, "Growth (body sizes)", self.e_tr, HELP["tr"])
        lay.addLayout(form)
        lay.addWidget(QLabel("Boundary layer"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_yp, self.e_gr = QLineEdit("1"), QLineEdit("1.2")
        self.e_first, self.e_bt = QLineEdit(""), QLineEdit("")
        self.e_first.setPlaceholderText("automatic")
        self.e_bt.setPlaceholderText("automatic")
        self.row(form, "Target y+", self.e_yp, HELP["yplus"])
        self.row(form, "Layer growth ratio", self.e_gr, HELP["growth"])
        self.lbl_first = self.row(form, "First layer", self.e_first, HELP["first"])
        self.lbl_bt = self.row(form, "Thickness", self.e_bt, HELP["bl_thick"])
        lay.addLayout(form)
        self.bl_lbl = self.note("")
        lay.addWidget(self.bl_lbl)
        self.mesh_opts = sm2.default_mesh()
        sim_meshui.build_advanced(self, lay, "cfd", None, sm2.GROWTH_RANGE, sm2.CURV_RANGE)
        self.b_mesh = QPushButton("Mesh")
        self.b_mesh.setMinimumHeight(30)
        self.b_mesh.clicked.connect(self.run_mesh)
        lay.addWidget(self.b_mesh)
        self.mesh_lbl = QLabel("")
        self.mesh_lbl.setWordWrap(True)
        lay.addWidget(self.mesh_lbl)
        sim_meshui.build_quality(self, lay)
        self.cb_auto = QCheckBox("Auto-refine the mesh until the forces converge")
        self.cb_auto.toggled.connect(self.auto_toggled)
        lay.addWidget(with_help(self.cb_auto, HELP["auto"]))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.e_passes, self.e_maxtris = QLineEdit("3"), QLineEdit("150000")
        self.row(form, "Maximum refinement passes", self.e_passes, HELP["passes"])
        self.row(form, "Maximum triangles", self.e_maxtris, HELP["maxtris"])
        self.auto_box = QWidget()
        self.auto_box.setLayout(form)
        self.auto_box.setVisible(False)
        lay.addWidget(self.auto_box)

        lay = sec(5, "Solver", True, help_text="Time marching to a steady state. Change per step = relative change of the velocity (and pressure) "
                  "between two time steps. The converged state is the last time step - nothing is averaged.",
                  summary=lambda: self.turb.currentText().split(" (")[0])
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.turb = QComboBox()
        self.turb.addItem("Laminar (no turbulence model)")
        self.turb.addItem("k-omega SST turbulence (wall-resolved)")
        self.e_int, self.e_vr = QLineEdit("5"), QLineEdit("10")
        self.e_cfl, self.e_dt = QLineEdit("5"), QLineEdit("")
        self.e_dt.setPlaceholderText("automatic")
        self.e_steps, self.e_tol, self.e_every = QLineEdit("400"), QLineEdit("1e-5"), QLineEdit("5")
        self.cb_until = QCheckBox("Run until converged (no step limit)")
        self.cb_until.toggled.connect(lambda on: self.e_steps.setEnabled(not on))
        self.e_ramp = QLineEdit("20")
        self.row(form, "Model", self.turb, HELP["model"])
        self.row(form, "Turbulence intensity (%)", self.e_int, HELP["intensity"])
        self.row(form, "Eddy viscosity ratio", self.e_vr, HELP["ratio"])
        self.row(form, "CFL", self.e_cfl, HELP["cfl"])
        self.row(form, "Time step (s)", self.e_dt, HELP["dt"])
        self.row(form, "Maximum steps", self.e_steps, HELP["steps"])
        self.row(form, "Gentle start (steps)", self.e_ramp, HELP["ramp"])
        self.row(form, "Stop when change <", self.e_tol, HELP["tol"])
        self.row(form, "Frame every (steps)", self.e_every, HELP["every"])
        lay.addLayout(form)
        lay.addWidget(with_help(self.cb_until, HELP["until"]))
        self.dt_lbl = self.note("")
        lay.addWidget(self.dt_lbl)
        self.b_solve = sim_ui.solve_button()
        self.b_solve.clicked.connect(self.run_solve)
        self.b_stop = sim_ui.solve_side_button("Stop")
        self.b_stop.clicked.connect(self.stop_solve)
        self.b_stop.setEnabled(False)
        self.study_box = sim_ui.study_slot()
        self.solve_row = sim_ui.solve_row(self.b_solve, self.b_stop)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.prog_lbl = self.note("")
        self.plot = ConvergencePlot()
        self.solve_status = QWidget()                 # progress under the Solve button: the bar, its text and the change-per-step plot
        ssl = QVBoxLayout(self.solve_status)
        ssl.setContentsMargins(4, 0, 4, 0)
        ssl.setSpacing(2)
        ssl.addWidget(self.bar)
        ssl.addWidget(self.prog_lbl)
        ssl.addWidget(self.plot)

        lay = sec(6, "Results", True, help_text="To load a surface of the body in the FEA tab: FEA tab - Pressure from CFD...",
                  summary=lambda: self.field.currentText())
        sim_ui.results_head(lay, self.solve_row, self.solve_status, self.study_box)   # Solve, Stop, the progress and the chart are the first things of the Results page
        sim_ui.solve_shortcut(self, self.b_solve)
        self.field = QComboBox()
        for name, key, _, _ in FIELD_LIST:
            self.field.addItem(name, key)
        self.field.setCurrentIndex(0)
        sim_ui.tame(self.field, 26)                          # its longest entry does not set the width of the whole panel
        self.field.currentIndexChanged.connect(self.refresh)
        lay.addWidget(with_help(self.field, HELP["field"]))
        row = QHBoxLayout()
        row.addWidget(QLabel("Colours"))
        self.cmap_combo = result_style.make_combo(self, lambda: (self.canvas.invalidate(), self.refresh()))
        row.addWidget(self.cmap_combo, 1)
        lay.addLayout(row)
        self.cb_mesh = QCheckBox("Show mesh lines")
        self.cb_mesh.setChecked(False)
        self.cb_mesh.toggled.connect(self.refresh)
        lay.addWidget(with_help(self.cb_mesh, HELP["mesh_lines"]))
        lay.addWidget(QLabel("Time frames (saved while solving)"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.refresh)
        lay.addWidget(with_help(self.slider, HELP["slider"]))
        self.frame_lbl = self.note("no frames yet")
        lay.addWidget(self.frame_lbl)
        self.cb_tracers = QCheckBox("Moving tracer particles (on the final flow)")
        self.cb_tracers.toggled.connect(self.tracers_toggled)
        lay.addWidget(with_help(self.cb_tracers, HELP["tracers"]))
        self.trace_timer = QTimer(self)
        self.trace_timer.timeout.connect(self.tracer_step)
        lay.addWidget(HelpLabel("Selected wall edges", HELP["select"]))
        self.sel_lbl = QLabel("Nothing selected.")
        self.sel_lbl.setWordWrap(True)
        lay.addWidget(self.sel_lbl)
        row = QHBoxLayout()
        self.b_send = QPushButton("Use selection in FEA...")
        self.b_send.clicked.connect(self.send_to_fea)
        self.b_clear_sel = QPushButton("Clear selection")
        self.b_clear_sel.clicked.connect(self.clear_selection)
        row.addWidget(self.b_send)
        row.addWidget(self.b_clear_sel)
        lay.addLayout(row)
        self.b_send.setEnabled(False)
        self.b_clear_sel.setEnabled(False)
        lay.addWidget(QLabel("Animate"))
        self.anim_box = QWidget()
        al = QFormLayout(self.anim_box)
        al.setContentsMargins(14, 0, 0, 0)
        self.e_dur = QLineEdit("3")
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["Once", "Loop", "Back and forth"])
        self.lbl_frames = self.note("Frames: none yet")
        al.addRow(self.lbl_frames)
        al.addRow("Duration (s)", self.e_dur)
        al.addRow("Playback", self.loop_combo)
        arow = QHBoxLayout()
        self.b_play = QPushButton("Play")
        self.b_play.clicked.connect(self.play_frames)
        self.b_play_stop = QPushButton("Stop")
        self.b_play_stop.clicked.connect(self.stop_motion)
        arow.addWidget(self.b_play)
        arow.addWidget(self.b_play_stop)
        al.addRow(arow)
        self.b_export = QPushButton("Export animation...")
        self.b_export.setToolTip("Saves the time frames as a transparent animated WebP or PNG (only what is drawn is kept), an animated GIF" + (", an MP4 video" if anim_export.mp4_available() else
                                 " (an MP4 video too when OpenCV or imageio-ffmpeg is installed)") + " or a folder of PNG pictures. "
                                 "It uses the Duration and Playback above.")
        self.b_export.clicked.connect(lambda: self.export_animation())
        al.addRow(self.b_export)
        al.addRow(self.note("The frames are the time steps saved while solving (Frame every (steps) sets how many). Duration is the length of the whole clip."))
        lay.addWidget(self.anim_box)
        self.play_dir = 1
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.play_step)
        self.res_lbl = QLabel("")
        self.res_lbl.setWordWrap(True)
        lay.addWidget(self.res_lbl)
        row = QHBoxLayout()
        b = QPushButton("Diagnostics report...")
        b.clicked.connect(self.show_diag)
        row.addWidget(b)
        b = QPushButton("Zoom to fit")
        b.clicked.connect(self.canvas.fit)
        row.addWidget(b)
        lay.addLayout(row)
        for s_ in sorted(self.sections, key=lambda x: x.number):
            lay0.addWidget(s_)
        lay0.addStretch(1)

        scroll = sim_ui.make_panel(left, [], 340)
        sim_ui.outlinize(scroll, self, "cfd2d")
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(scroll)
        split.addWidget(self.canvas)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        sim_ui.fit_side_panel(split, scroll, left)   # as wide as its sections need; drag the divider for more (not remembered)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(split, 1)
        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 2)
        self.status_lbl = QLabel("")
        row.addWidget(self.status_lbl, 1)
        row.addWidget(self.coords)
        outer.addLayout(row)

        self.fluid_combo.currentIndexChanged.connect(self.fluid_picked)
        self.e_rho.textEdited.connect(self.set_custom_fluid)
        self.e_mu.textEdited.connect(self.set_custom_fluid)
        self.e_k.textEdited.connect(self.set_custom_fluid)
        self.e_cp.textEdited.connect(self.set_custom_fluid)
        for e in (self.e_k, self.e_cp, self.e_mu, self.e_rho):
            e.textChanged.connect(self.update_heat_note)
        unitctl.on_heat_change(self.heat_changed)
        for e in (self.e_angle,):
            e.textChanged.connect(self.update_sides)
        for e in (self.e_cfl, self.e_speed, self.e_hb, self.e_dt):
            e.textChanged.connect(self.update_dt_note)
        self.turb.currentIndexChanged.connect(self.model_changed)
        for e in (self.e_yp, self.e_gr, self.e_first, self.e_bt, self.e_speed, self.e_rho, self.e_mu):
            e.textChanged.connect(self.update_bl_note)
        self.model_changed()
        self.fluid_picked()
        self.refresh_unit_labels()
        self.update_sides()
        self.enable_buttons()

    # --- small helpers
    def auto_toggled(self, on):
        self.auto_box.setVisible(bool(on))

    def row(self, form, text, widget, help_text):
        """A form row whose label explains itself: click the label for a note."""
        lab = HelpLabel(text, help_text)
        form.addRow(lab, widget)
        return lab

    def refresh_sections(self):
        for s_ in self.sections:
            s_.refresh_summary()

    @staticmethod
    def note(text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:#555555; font-size:11px;")
        return lb

    def status(self, text):
        self.status_lbl.setText(text)
        try:
            self.win.status(text)
        except Exception:
            pass

    def handover_anchor(self, row):
        return pt.handover_anchor_2d(self, row)

    def selectable(self):
        """Edge keys that can be selected: the walls of the solid bodies (None = any edge, before there is a mesh)."""
        if self.result is not None and self.result.get("walls"):
            return set(self.result["walls"].keys())
        if self.mesh is not None and self.mesh.get("wall_segs"):
            return set(self.mesh["wall_segs"].keys())
        return None

    def selection_changed(self):
        sel = list(self.canvas.sel)
        self.refresh_heat_buttons()
        self.b_send.setEnabled(bool(sel) and self.result is not None)
        self.b_clear_sel.setEnabled(bool(sel))
        if not sel:
            self.sel_lbl.setText("Nothing selected.")
            return
        rows = []
        walls = self.result["walls"] if self.result is not None else {}
        per_edge = self.result["forces"]["per_edge"] if self.result is not None else {}
        for k in sel:
            name = f"{pt.KIND_NAME.get(k[0], k[0])} {k[1]}"
            t = walls.get(k)
            if t is None:
                rows.append(f"<b>{name}</b>: " + ("no flow data for this edge." if self.result is not None else "not solved yet."))
                continue
            pa, pb, L = t["p_a"], t["p_b"], t["L"]
            mean = float(np.sum(0.5 * (pa + pb) * L) / max(float(np.sum(L)), 1e-300))
            lo, hi = float(min(np.min(pa), np.min(pb))), float(max(np.max(pa), np.max(pb)))
            fx, fy = per_edge.get(k, (float("nan"), float("nan")))
            (lo, su), (hi, _), (mean, _) = self.pressure_txt(lo), self.pressure_txt(hi), self.pressure_txt(mean)
            (fx, fu), (fy, _) = self.force_txt(fx), self.force_txt(fy)
            rows.append(f"<b>{name}</b>: pressure {lo:.4g} to {hi:.4g} {su} (mean {mean:.4g}); force on the edge "
                        f"({fx:.4g}, {fy:.4g}) {fu} per unit of depth" + self.heat_edge_text(k))
        self.sel_lbl.setText("<br>".join(rows))

    def heat_edge_text(self, key):
        """'; temperature 20 to 50 degC, heat into the fluid 3.2 W per metre of depth, h 41 W/(m2 K)' for an edge of the solved result, or ''."""
        hres = self.result.get("heat") if self.result is not None else None
        tb = hres["walls"].get(key) if hres else None
        if tb is None:
            return ""
        hs = self.hunits()
        L = tb["L"]
        Ltot = max(float(np.sum(L)), 1e-300)
        q_mean = float(np.sum(0.5 * (tb["q_a"] + tb["q_b"]) * L) / Ltot)
        txt = (f"; temperature {hu.from_si('T', hs['T'], tb['T_min']):.4g} to {hu.from_si('T', hs['T'], tb['T_max']):.4g} {hs['T']}, "
               f"heat into the fluid {hu.from_si('P', hs['P'], tb['Q']):.4g} {hs['P']} per metre of depth (mean flux {hu.from_si('q', hs['q'], q_mean):.4g} {hs['q']})")
        dT = float(np.sum(0.5 * (tb["T_a"] + tb["T_b"]) * L) / Ltot) - hres["T_in"]
        if tb["kind"] == "temp" and abs(dT) > 0.01:
            txt += f", h = {hu.from_si('h', hs['h'], q_mean / dT):.4g} {hs['h']} (against the inlet temperature)"
        return txt

    def refresh(self, *_):
        self.canvas.update()

    def num(self, edit, name):
        try:
            return float(edit.text())
        except ValueError:
            raise pcfd.ModelError(f"{name} must be a number.")

    def angle_value(self):
        try:
            return float(self.e_angle.text())
        except ValueError:
            return 0.0

    def unit_name(self):
        if self.model is not None:
            return self.model.unit_system
        return getattr(getattr(self.win, "m", None), "unit_system", units.DEFAULT)

    def U(self):
        return units.get(self.unit_name())

    def lscale(self):
        """Metres per sketch unit."""
        return self.U()["L_m"]

    def refresh_unit_labels(self):
        u = self.U()
        self.lbl_rho.setText(f"Density ({u['rho']})")
        self.lbl_mu.setText(f"Viscosity ({u['mu']})")
        self.lbl_speed.setText(f"Speed ({u['V']})")
        self.lbl_hb.setText(f"At the body ({u['L']})")
        self.lbl_hf.setText(f"Far away ({u['L']})")
        if hasattr(self, "hmin_label"):
            self.hmin_label.setText(f"Minimum size ({u['L']})")
        self.lbl_first.setText(f"First layer ({u['L']})")
        self.lbl_bt.setText(f"Thickness ({u['L']})")
        self.units_note.setText(f"Units: {u['name']}  (change in File > Units)")
        if hasattr(self, "heat_box"):
            self.adopt_heat_units()
            hs = self.hunits()
            self.lbl_k.setText(f"Conductivity ({hs['k']})")
            self.lbl_cp.setText(f"Specific heat ({hs['cp']})")
            self.lbl_Tin.setText(f"Inlet temperature ({hs['T']})")
            self.refresh_heat_list()
            self.update_heat_note()

    def si_inputs(self):
        """(speed m/s, density kg/m3, viscosity Pa s) from the boxes, which are in the unit system."""
        n = self.unit_name()
        return (units.speed_to_si(float(self.e_speed.text()), n), units.density_to_si(float(self.e_rho.text()), n),
                units.viscosity_to_si(float(self.e_mu.text()), n))

    def length_m(self, text):
        return units.length_to_m(float(text), self.unit_name())

    def pressure_txt(self, pa):
        u = self.U()
        return units.pressure_from_pa(pa, u["name"]), u["S"]

    def force_txt(self, n_per_m):
        u = self.U()
        return units.force_per_depth_from_n_per_m(n_per_m, u["name"]), f"{u['F']}/{u['L']}"

    def field_units(self, key):
        """(unit text, divisor from SI) of a field for display."""
        u = self.U()
        return {"speed": (u["V"], u["V_ms"]), "ux": (u["V"], u["V_ms"]), "uy": (u["V"], u["V_ms"]),
                "p": (u["S"], u["S_Pa"]), "k": (f"{u['L']}2/s2", u["L_m"] ** 2)}.get(
            key, {"vort": ("1/s", 1.0), "omega": ("1/s", 1.0), "nut": ("-", 1.0)}.get(key, ("", 1.0)))

    def enable_buttons(self):
        have = {n for n, (v, _) in self.deps.items() if v is not None}
        busy = self.worker is not None
        self.b_mesh.setEnabled(self.geom is not None and "gmsh" in have and "numpy" in have and not busy)
        self.b_solve.setEnabled(self.mesh is not None and "scipy" in have and not busy)
        self.b_stop.setEnabled(busy)
        self.refresh_mesh_info()

    def mesh_kind_text(self):
        return "quadratic velocity, linear pressure"

    def fluid_picked(self, *_):
        name = self.fluid_combo.currentText()
        rho, mu = pcfd.FLUIDS[name]
        if rho is not None:
            n = self.unit_name()
            self.e_rho.setText(f"{units.density_from_si(rho, n):.6g}")
            self.e_mu.setText(f"{units.viscosity_from_si(mu, n):.6g}")
        k, cp = pcfd.FLUID_HEAT.get(name, (None, None))
        if k is not None:
            hs = self.hunits()
            self.e_k.setText(f"{hu.from_si('k', hs['k'], k):.6g}")
            self.e_cp.setText(f"{hu.from_si('cp', hs['cp'], cp):.6g}")

    def set_custom_fluid(self, *_):
        if self.fluid_combo.currentText() != "Custom":
            self.fluid_combo.blockSignals(True)
            self.fluid_combo.setCurrentText("Custom")
            self.fluid_combo.blockSignals(False)

    # --- heat transfer
    def hunits(self):
        """The unit of every heat-transfer quantity as File > Units > Heat transfer sets them for this tab's unit system."""
        try:
            return unitctl.heat_units(self.unit_name())
        except Exception:                                                              # noqa: BLE001
            return unitctl.heat_units()

    def heat_changed(self, *_):
        try:
            self.refresh_unit_labels()
        except RuntimeError:                                                            # the window is gone
            unitctl.off_heat_change(self.heat_changed)

    def closeEvent(self, ev):
        unitctl.off_heat_change(self.heat_changed)
        super().closeEvent(ev)

    def adopt_heat_units(self, old=None):
        """The three boxes hold numbers in `old` (default: the units they were last written in); write them in the units now chosen."""
        new = self.hunits()
        old = dict(old or self.heat_inputs_units)
        if old != new:
            for e, q in ((self.e_k, "k"), (self.e_cp, "cp"), (self.e_Tin, "T")):
                txt = e.text().strip()
                if not txt:
                    continue
                try:
                    e.setText(f"{hu.from_si(q, new[q], hu.to_si(q, old[q], float(txt))):.6g}")
                except (ValueError, KeyError):
                    pass
        self.heat_inputs_units = new

    def heat_toggled(self, on):
        self.heat_box.setVisible(bool(on))
        self.update_heat_note()
        self.refresh_sections()
        self.canvas.update()

    def heat_si(self):
        """(k W/(m K), cp J/(kg K), inlet temperature K) from the boxes, which are in the heat-transfer units."""
        hs = self.hunits()
        return (hu.to_si("k", hs["k"], float(self.e_k.text())), hu.to_si("cp", hs["cp"], float(self.e_cp.text())),
                hu.to_si("T", hs["T"], float(self.e_Tin.text())))

    def update_heat_note(self, *_):
        if not hasattr(self, "heat_note"):
            return
        try:
            k, cp, _ = self.heat_si()
            _, rho, mu = self.si_inputs()
            self.heat_note.setText(f"Prandtl number mu cp / k = {mu * cp / k:.3g};  thermal diffusivity k / (rho cp) = {k / (rho * cp):.3g} m2/s")
        except (ValueError, ZeroDivisionError):
            self.heat_note.setText("")

    def wall_text(self, key):
        """'Line 5: 80 degC (fixed temperature)' for an edge that has a heat condition."""
        c = self.heat_walls[key]
        hs = self.hunits()
        name = f"{pt.KIND_NAME.get(key[0], key[0])} {key[1]}"
        if c["kind"] == "temp":
            return f"{name}: {hu.from_si('T', hs['T'], c['v']):.6g} {hs['T']} (fixed temperature)"
        if c["kind"] == "coupled":
            return f"{name}: wall of the thermal analysis (Coupled Physics)"
        return f"{name}: {hu.from_si('q', hs['q'], c['v']):.6g} {hs['q']} (heat flux into the fluid)"

    def refresh_heat_list(self):
        self.heat_list.clear()
        for key in sorted(self.heat_walls):
            self.heat_list.addItem(self.wall_text(key))
        self.heat_list.setVisible(bool(self.heat_walls))
        self.refresh_heat_buttons()
        self.canvas.update()

    def refresh_heat_buttons(self):
        if not hasattr(self, "b_heat_set"):
            return
        sel = list(self.canvas.sel)
        self.b_heat_set.setEnabled(bool(sel))
        self.b_heat_off.setEnabled(any(tuple(k) in self.heat_walls for k in sel))

    def set_wall_condition(self, keys, kind, text):
        """The condition on the edges `keys`: kind 'temp' (the temperature in the temperature unit) or 'flux' (the heat flux into the fluid).  A ModelError says what is wrong."""
        hs = self.hunits()
        if kind == "coupled":
            if not keys:
                raise pcfd.ModelError("Select at least one edge of a body on the drawing first.")
            for k in keys:
                self.heat_walls[tuple(k)] = {"kind": "coupled", "v": 0.0}
            self.refresh_heat_list()
            self.invalidate_heat_result()
            return
        try:
            v = float(str(text).replace(",", "."))
        except ValueError:
            raise pcfd.ModelError("The value must be a number.")
        if kind == "temp":
            si = hu.to_si("T", hs["T"], v)
            if si <= 0:
                raise pcfd.ModelError("A temperature must be above absolute zero (0 K).")
        elif kind == "flux":
            si = hu.to_si("q", hs["q"], v)
        else:
            raise pcfd.ModelError(f"Unknown heat condition '{kind}'.")
        if not keys:
            raise pcfd.ModelError("Select at least one edge of a body on the drawing first.")
        for k in keys:
            self.heat_walls[tuple(k)] = {"kind": kind, "v": float(si)}
        self.refresh_heat_list()
        self.invalidate_heat_result()

    def remove_wall_conditions(self, keys=None):
        for k in (self.canvas.sel if keys is None else keys):
            self.heat_walls.pop(tuple(k), None)
        self.refresh_heat_list()
        self.invalidate_heat_result()

    def invalidate_heat_result(self):
        """The flow result stays; a temperature that was found with other conditions is not shown as if it belonged to these."""
        if self.result is not None and self.result.get("heat") is not None:
            self.status("The heat conditions changed: solve again to update the temperature.")

    def ask_wall_condition(self):
        keys = list(self.canvas.sel)
        if not keys:
            QMessageBox.information(self, "Heat conditions", "Select at least one edge of a body on the drawing first (click it; Ctrl-click adds more).")
            return
        hs = self.hunits()
        dlg = QDialog(self)
        dlg.setWindowTitle("Heat condition on the selected edges")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(", ".join(f"{pt.KIND_NAME.get(k[0], k[0])} {k[1]}" for k in keys)))
        kind = QComboBox()
        kind.addItem("Fixed temperature", "temp")
        kind.addItem("Heat flux into the fluid", "flux")
        kind.addItem("Wall of the thermal analysis (Coupled Physics)", "coupled")
        lay.addWidget(kind)
        unit = QLabel()
        edit = QLineEdit()
        lay.addWidget(unit)
        lay.addWidget(edit)

        def changed(*_):
            q = "T" if kind.currentData() == "temp" else "q"
            coupled = kind.currentData() == "coupled"
            unit.setText("The temperature and the heat flux of these edges come from the 2D Thermal analysis wired into the same Coupled Physics block."
                         if coupled else f"Value ({hs[q]})")
            edit.setEnabled(not coupled)
            edit.setText("" if q == "q" or coupled else edit.text())
        kind.currentIndexChanged.connect(changed)
        changed()
        row = QHBoxLayout()
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.clicked.connect(dlg.accept)
        cancel.clicked.connect(dlg.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.set_wall_condition(keys, kind.currentData(), edit.text())
        except pcfd.ModelError as ex:
            QMessageBox.warning(self, "Heat conditions", str(ex))

    def coupled_keys(self):
        """The edges that are walls of a thermal analysis (their temperature and heat flux are handed over inside Coupled Physics), sorted."""
        have = {e["src"] for e in self.geom["edges"]} if self.geom is not None else set()
        return sorted(k for k, c in self.heat_walls.items() if c["kind"] == "coupled" and k in have)

    def read_heat(self, allow_coupled=False):
        """The `heat` dict of physics_cfd_heat.solve_temperature from the boxes and the list (SI), or None when heat transfer is off.  A ModelError says what is wrong.
        Walls of the thermal analysis are left out of its walls (Coupled Physics adds them) and are refused unless `allow_coupled`."""
        if not self.cb_heat.isChecked():
            return None
        try:
            k, cp, T_in = self.heat_si()
        except ValueError:
            raise pcfd.ModelError("The conductivity, the specific heat and the inlet temperature must be numbers.")
        if k <= 0 or cp <= 0:
            raise pcfd.ModelError("The conductivity and the specific heat of the fluid must be greater than zero.")
        if T_in <= 0:
            raise pcfd.ModelError("The inlet temperature must be above absolute zero (0 K).")
        have = {e["src"] for e in self.geom["edges"]}
        walls = {}
        coupled = []
        for key, c in self.heat_walls.items():
            if key not in have:
                continue
            if c["kind"] == "coupled":
                coupled.append(key)
                continue
            walls[key] = {"kind": "temp", "T": c["v"]} if c["kind"] == "temp" else {"kind": "flux", "q": c["v"]}
        if coupled and not allow_coupled:
            raise pcfd.ModelError("These walls are set as walls of a thermal analysis: " + ", ".join(f"{pt.KIND_NAME.get(k[0], k[0])} {k[1]}" for k in sorted(coupled)) +
                                  ". That works only inside a Coupled Physics block (its Solve hands the temperature over). Here, set a temperature or a heat flux on them "
                                  "or remove the condition.")
        if not walls and not coupled:
            raise pcfd.ModelError("Heat transfer is on, but no wall has a temperature or a heat flux: select an edge of a body, press 'Set on selected edges...', "
                                  "or switch heat transfer off.")
        return {"k": k, "cp": cp, "T_in": T_in, "walls": walls}

    def update_sides(self, *_):
        kinds, _ = pcfd.classify_sides(self.angle_value())
        self.sides_lbl.setText("Sides:  " + ",  ".join(f"{s} = {kinds[s]}" for s in pcfd.SIDES))
        self.canvas.update()

    def is_sst(self):
        return self.turb.currentIndex() == 1

    def model_changed(self, *_):
        on = self.is_sst()
        for e in (self.e_int, self.e_vr, self.e_yp, self.e_gr, self.e_first, self.e_bt):
            e.setEnabled(on)
        self.update_bl_note()

    def bl_estimate(self):
        """Flat-plate estimate of the boundary-layer mesh from the inputs (metres), or None."""
        try:
            U, rho, mu = self.si_inputs()
            L = self.body_size * self.lscale()
            first = self.length_m(self.e_first.text()) if self.e_first.text().strip() else None
            thick = self.length_m(self.e_bt.text()) if self.e_bt.text().strip() else None
            return pcfd.bl_estimate(U, mu / rho, L, float(self.e_yp.text()), float(self.e_gr.text()), first, thick)
        except (ValueError, ZeroDivisionError, AttributeError):
            return None

    def update_bl_note(self, *_):
        if not self.is_sst():
            self.bl_lbl.setText("Only used with the turbulence model.")
            return
        est = self.bl_estimate()
        if est is None:
            self.bl_lbl.setText("")
            return
        u = self.U()
        txt = (f"Estimate: first layer {est['y1'] / u['L_m']:.3g} {u['L']}, boundary layer {est['delta'] / u['L_m']:.3g} {u['L']} thick, "
               f"about {est['layers']} layers (Re {est['Re']:.3g}, friction velocity {est['u_tau'] / u['V_ms']:.3g} {u['V']})")
        if est["layers"] > 60:
            txt += ".  That is a lot of layers - raise the target y+ or the growth ratio."
        self.bl_lbl.setText(txt)

    def update_dt_note(self, *_):
        try:
            setup = {"cfl": float(self.e_cfl.text()), "h_body": float(self.e_hb.text()), "lscale": self.lscale(),
                     "speed": self.si_inputs()[0]}
            self.dt_lbl.setText(f"Automatic time step = CFL x element size at the body / speed = {pcfd.suggested_dt(setup):.4g} s"
                                + ("   (overridden below)" if self.e_dt.text().strip() else ""))
        except (ValueError, ZeroDivisionError):
            self.dt_lbl.setText("")

    # --- import
    def import_picked(self, sid, text, name):
        m = sc.Model()
        m.from_json(text)
        self.set_model(m, name)
        self.sketch_id = sid

    def import_current(self):
        self.picker.go()

    def clear_tab(self):
        """The Clear button: forget the imported sketch and this tab's setup, so the sketch can be imported again from scratch."""
        if self.model is None:
            self.status("Nothing to clear: no sketch is imported here.") if hasattr(self, "status") else None
            return
        if getattr(self, "worker", None) is not None:
            QMessageBox.information(self, "Clear", "A run is in progress on this tab. Stop it first.")
            return
        if QMessageBox.question(self, "Clear", "Remove the imported sketch and everything set up on this tab (supports, loads, results)? "
                                "The sketch itself is not touched.") != QMessageBox.StandardButton.Yes:
            return
        self.clear_state()
        param = getattr(self.win, "param", None)
        if param is not None:
            try:
                param.refresh_params()
            except Exception:
                pass

    def convert_input_units(self, new):
        """The boxes hold numbers in `self.inputs_unit`; express them in `new` (same physical values)."""
        old = self.inputs_unit
        if old == new or not units.valid(old) or not units.valid(new):
            self.inputs_unit = new
            return
        lf = units.length_factor(old, new)
        for e, f in ((self.e_hb, lf), (self.e_hf, lf), (self.e_first, lf), (self.e_bt, lf),
                     (self.e_rho, units.density_factor(old, new)),
                     (self.e_mu, units.viscosity_factor(old, new))):
            txt = e.text().strip()
            if txt:
                try:
                    e.setText(f"{float(txt) * f:.6g}")
                except ValueError:
                    pass
        self.inputs_unit = new

    def adopt_units(self, m):
        """A sketch copy in another unit system than the program's is converted to it."""
        if getattr(self.win, "_restoring", False):
            return m                                   # a saved tab keeps its own units
        want = getattr(getattr(self.win, "m", None), "unit_system", None)
        if want and units.valid(want) and m.unit_system != want:
            try:
                m.convert_units(want, True)
            except ValueError:
                m.unit_system = want                      # could not be converted safely: take the numbers as they are
        return m

    def set_model(self, m, source):
        self.stop_motion()
        m = self.adopt_units(m)
        self.model, self.source = m, source
        self.convert_input_units(m.unit_system)
        self.refresh_unit_labels()
        self.geom = pg.analyze(m)
        self.mesh, self.result = None, None
        self.frames, self.field_cache = [], {}
        self.canvas.raster = self.canvas.base = None
        self.canvas.particles = None
        self.canvas.sel = []
        self.selection_changed()
        self.slider.setRange(0, 0)
        self.plot.clear()
        self.fill_bodies()
        bodies = pcfd.body_faces(self.geom)
        xs = [p[0] for f in bodies for p in f["poly"]]
        ys = [p[1] for f in bodies for p in f["poly"]]
        size = max(max(xs) - min(xs), max(ys) - min(ys)) if xs else 1.0
        self.body_size = size
        self.e_hb.setText(f"{size / 40:.4g}")
        self.e_hf.setText(f"{size / 5:.4g}")
        g = self.geom
        msg = f"Imported {source}: {len(g['edges'])} edges, {len(bodies)} outline(s) that can be bodies, body size {size:.5g}."
        if g["pruned"]:
            msg += f" {len(g['pruned'])} edge(s) not part of a closed loop were ignored."
            msg += pg.gap_note(g.get("gaps"))
        if g["crossings"]:
            msg += f" WARNING: {len(g['crossings'])} pair(s) of edges cross without a shared point."
        self.info.setText(msg)
        self.status(msg)
        self.res_lbl.setText("")
        self.prog_lbl.setText("")
        self.bar.setValue(0)
        self.frame_lbl.setText("no frames yet")
        self.lbl_frames.setText("Frames: none yet")
        self.canvas.fit()
        self.update_dt_note()
        self.update_bl_note()
        self.enable_buttons()

    def fill_bodies(self):
        self.bodies.blockSignals(True)
        self.bodies.clear()
        self.body_on = set()
        for f in self.geom["faces"]:
            ok = f["depth"] == 0
            it = QListWidgetItem(f"Body {f['id'] + 1}   area {f['area']:.5g}" + ("" if ok else "   (inside another outline - ignored)"))
            it.setFlags((it.flags() | Qt.ItemFlag.ItemIsUserCheckable) if ok else (it.flags() & ~Qt.ItemFlag.ItemIsEnabled))
            it.setCheckState(Qt.CheckState.Checked if ok else Qt.CheckState.Unchecked)
            if ok:
                self.body_on.add(f["id"])
            self.bodies.addItem(it)
        self.bodies.blockSignals(False)

    def body_toggled(self, item):
        r = self.bodies.row(item)
        if item.checkState() == Qt.CheckState.Checked:
            self.body_on.add(r)
        else:
            self.body_on.discard(r)
        self.mesh, self.result = None, None
        self.frames, self.field_cache = [], {}
        self.slider.setRange(0, 0)
        self.canvas.raster = self.canvas.base = None
        self.canvas.particles = None
        self.enable_buttons()
        self.canvas.update()
        self.status("Bodies changed: mesh again.")

    # --- mesh
    def mesh_input_problem(self, text, quiet):
        self.last_input_problem = text
        if not quiet:
            QMessageBox.warning(self, "Mesh", text)

    def read_mesh_inputs(self, quiet=False):
        """(model, geom, body ids, margins, h_body, h_far, transition, boundary layer) from the boxes, or None after telling the user."""
        try:
            margins = tuple(self.num(e, n) for e, n in ((self.e_ml, "Left margin"), (self.e_mr, "Right margin"),
                                                         (self.e_mb, "Bottom margin"), (self.e_mt, "Top margin")))
            hb, hf, tr = self.num(self.e_hb, "The element size at the body"), self.num(self.e_hf, "The far element size"), \
                self.num(self.e_tr, "The growth distance")
        except pcfd.ModelError as ex:
            self.mesh_input_problem(str(ex), quiet)
            return None
        if not self.body_on:
            self.mesh_input_problem("Tick at least one solid body first.", quiet)
            return None
        m, g, ids = self.model, self.geom, set(self.body_on)
        bl = None
        if self.is_sst():
            est = self.bl_estimate()
            if est is None:
                self.mesh_input_problem("Check the speed, density, viscosity and the boundary-layer numbers.", quiet)
                return None
            if est["layers"] > 120:
                self.mesh_input_problem(f"The boundary layer would need {est['layers']} layers. Raise the target y+ or "
                                        "the growth ratio.", quiet)
                return None
            ls = self.lscale()
            bl = {"h1": est["y1"] / ls, "ratio": float(self.e_gr.text()), "thickness": est["delta"] / ls}
            if bl["h1"] >= hb:
                self.mesh_input_problem("The first layer is not thinner than the element size at the body. "
                                        "Lower the target y+ or the element size.", quiet)
                return None
        return m, g, ids, margins, hb, hf, tr, bl

    def run_mesh(self, shape=None):
        """Meshes the fluid around the bodies.  shape = None: the bodies as drawn; or, from a Coupled Physics block, {"edges": {edge index: points}}: the bodies as a structure moved them."""
        args = self.read_mesh_inputs()
        if args is None:
            return
        m, g, ids, margins, hb, hf, tr, bl = args
        try:
            opts = self.mesher_options()
        except ValueError as ex:
            QMessageBox.warning(self, "Mesh", str(ex))
            return
        kind, data = self.run_task("Meshing", lambda progress, cancel: pcfd.mesh_fluid(m, g, ids, margins, hb, hf, tr, progress,
                                                                                         cancel, bl=bl, opts=opts, shape=shape))
        if kind != "ok":
            self.status("Meshing cancelled." if kind == "cancelled" else "Meshing failed.")
            return
        self.stop_motion()
        self.mesh, self.result = data, None
        self.frames, self.field_cache = [], {}
        self.slider.setRange(0, 0)
        self.canvas.raster = self.canvas.base = None
        self.canvas.particles = None
        s = data["stats"]
        self.status(("Mesh around the body as the structure moved it: " if shape else "Mesh: ") + f"{s['n_nodes']} vertices, {s['n_tris']} triangles (quadratic velocity nodes are added by the solver); "
                    f"smallest angle {s['angle_min']:.1f} deg, worst aspect ratio {s['aspect_max']:.2f}."
                    + ("  NOTE: " + "; ".join(s["relaxed"]) + "." if s.get("relaxed") else ""))
        self.frame_lbl.setText("no frames yet")
        self.lbl_frames.setText("Frames: none yet")
        self.res_lbl.setText("")
        self.canvas.fit()
        self.enable_buttons()

    def run_task(self, title, fn):
        dlg = pt.TaskDialog(self, title, fn)
        kind, data = dlg.run() or ("cancelled", None)
        if kind == "user":
            QMessageBox.warning(self, title, data)
        elif kind == "bug":
            QMessageBox.warning(self, title, "The program hit an error. Please copy this and send it to me:\n\n" + data)
        return kind, data

    # --- solve
    def read_setup(self, check_mesh=True):
        nm = self.unit_name()
        setup = {"lscale": self.lscale(), "rho": units.density_to_si(self.num(self.e_rho, "Density"), nm),
                 "mu": units.viscosity_to_si(self.num(self.e_mu, "Viscosity"), nm),
                 "speed": units.speed_to_si(self.num(self.e_speed, "Speed"), nm), "angle": self.num(self.e_angle, "Direction"),
                 "cfl": self.num(self.e_cfl, "CFL"), "h_body": self.num(self.e_hb, "The element size at the body"),
                 "max_steps": int(self.num(self.e_steps, "Maximum steps")) if not self.cb_until.isChecked() else 1,
                 "tol": self.num(self.e_tol, "The tolerance"), "until": self.cb_until.isChecked(),
                 "ramp_steps": int(self.num(self.e_ramp, "The gentle start")),
                 "frame_every": int(self.num(self.e_every, "The frame interval"))}
        txt = self.e_dt.text().strip()
        setup["dt"] = self.num(self.e_dt, "The time step") if txt else None
        setup["turb"] = self.is_sst()
        if setup["turb"]:
            setup["intensity"] = self.num(self.e_int, "The turbulence intensity") / 100.0
            setup["visc_ratio"] = self.num(self.e_vr, "The eddy viscosity ratio")
            if setup["intensity"] <= 0 or setup["visc_ratio"] <= 0:
                raise pcfd.ModelError("Turbulence intensity and eddy viscosity ratio must be positive.")
            if check_mesh and not self.mesh["stats"].get("bl"):
                raise pcfd.ModelError("The turbulence model needs the boundary-layer mesh: select the model, then press Mesh again.")
        setup["edge_geoms"] = {e["src"]: pcfd.edge_geometry(self.model, e) for e in self.geom["edges"]}
        shapes = getattr(self, "deformed_shapes", None)
        if shapes:                                                    # a Coupled Physics block moved the body: where the wall is NOW, and where each point of it was
            setup["edge_shapes"] = dict(shapes)
        return setup

    coupled_flow_only = False        # a Coupled Physics block sets this for the flow solve: the temperature is solved by the block, not by this window
    deformed_shapes = None           # a Coupled Physics block sets this when the structure has moved the body: {edge: moved geometry} (pcfd.poly_geometry)

    def run_solve(self):
        if self.mesh is not None and self.mesh.get("deformed") and not self.deformed_shapes:
            QMessageBox.warning(self, "Solve", "The mesh in this window follows the body as a structure moved it in the last Coupled Physics solve. Press Mesh to mesh the sketch as "
                                "drawn, then Solve.")
            return
        try:
            setup = self.read_setup()
        except pcfd.ModelError as ex:
            QMessageBox.warning(self, "Solve", str(ex))
            return
        refine = None
        if self.cb_auto.isChecked():
            try:
                passes, max_tris = int(float(self.e_passes.text())), int(float(self.e_maxtris.text()))
                if passes < 1 or max_tris < 100:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Solve", "Maximum refinement passes must be a whole number of at least 1, and the maximum "
                                    "number of triangles a number of at least 100.")
                return
            args = self.read_mesh_inputs()
            if args is None:
                return
            try:
                refine = {"passes": passes, "max_tris": max_tris, "mesh_args": args + (self.mesher_options(),)}
            except ValueError as ex:
                QMessageBox.warning(self, "Solve", str(ex))
                return
        try:
            heat = None if self.coupled_flow_only else self.read_heat()
        except pcfd.ModelError as ex:
            QMessageBox.warning(self, "Solve", str(ex))
            return
        self.stop_motion()
        self.setup_used = {k: v for k, v in (dict(setup, heat=heat) if heat else setup).items() if k != "edge_shapes"}       # (the moved geometry is in the mesh and the result)
        self.result = None
        self.selection_changed()
        self.frames, self.field_cache = [], {}
        self.slider.setRange(0, 0)
        self.canvas.base = None
        self.canvas.particles = None
        self.bar.setValue(0)
        self.res_lbl.setText("")
        self.plot.clear()
        self.plot.tol = setup["tol"]
        self.bar.setRange(0, 0 if setup["until"] else 1000)       # a busy bar when there is no step limit
        self.worker = SolveWorker(self.mesh, setup, refine, heat)
        self.worker.newmesh.connect(self.on_newmesh)
        self.worker.stall.connect(self.on_stall)
        self.worker.progress.connect(self.on_progress)
        self.worker.frame.connect(self.on_frame)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.t_start = time.perf_counter()
        self.worker.start()
        self.enable_buttons()
        self.status("Solving...")

    def on_newmesh(self, mesh, k):
        """Auto-refinement made a finer mesh: it replaces the old one on screen, and the frames of the old mesh are dropped."""
        self.stop_motion()
        self.mesh = mesh
        self.frames, self.field_cache = [], {}
        self.slider.setRange(0, 0)
        self.canvas.raster = self.canvas.base = self.canvas.mesh_pix = None
        self.canvas.particles = None
        self.frame_lbl.setText("no frames yet")
        self.lbl_frames.setText("Frames: none yet")
        s_ = mesh["stats"]
        self.status(f"Auto-refine pass {k}: new mesh with {s_['n_tris']:,} triangles, solving again...")
        self.canvas.update()

    def stop_solve(self):
        if self.worker is not None:
            self.worker.stop = True
            self.b_stop.setEnabled(False)
            self.prog_lbl.setText("Stopping after the current step...")

    def on_progress(self, step, mx, t, du, dp, dt_, sec):
        if mx > 0:
            self.bar.setValue(int(1000 * step / max(mx, 1)))
        extra = f", turbulence {dt_:.2e}" if dt_ > 0 else ""
        lim = f"of at most {mx}" if mx > 0 else "(no limit)"
        self.prog_lbl.setText(f"step {step} {lim}   t = {t:.4g} s   change: velocity {du:.2e}, pressure {dp:.2e}{extra}   "
                              f"({sec:.2f} s per step)")
        self.plot.add(step, du, dp, dt_)

    def on_stall(self, info):
        """The solver thread is waiting: the change per step has stopped improving."""
        w = self.worker
        kind = ("is growing: the run is getting worse" if info["kind"] == "diverging" else
                "has stopped improving")
        box = QMessageBox(self)
        box.setWindowTitle("Not settling")
        box.setIcon(QMessageBox.Icon.Warning)
        advice = ("Possible reasons: the flow is physically unsteady (vortex shedding), so there is no steady state to find; "
                  "the time step is too large (lower the CFL); the domain is too tight (larger margins); or, at high Reynolds "
                  "number, the laminar model is the wrong model (use k-omega SST).")
        box.setText(f"After {info['step']} steps the change per step {kind}.\n\n"
                    f"Last change {info['last']:.2e}; best in the last {info['win']} steps {info['best_recent']:.2e}, "
                    f"best in the {info['win']} before that {info['best_before']:.2e}; tolerance {info['tol']:g}.\n\n{advice}")
        keep = box.addButton("Keep going", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Stop here", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if w is not None:
            w.answer = "continue" if box.clickedButton() is keep else "stop"
            w.event.set()

    def on_frame(self, fr):
        follow = self.slider.value() >= len(self.frames) - 1
        self.frames.append(fr)
        if len(self.frames) > 120:                        # keep memory bounded: drop every other older frame
            last = self.frames[-1]
            self.frames = self.frames[:-1:2] + [last]
        self.slider.blockSignals(True)
        self.slider.setRange(0, len(self.frames) - 1)
        if follow:
            self.slider.setValue(len(self.frames) - 1)
        self.slider.blockSignals(False)
        self.canvas.update()

    def finish_worker(self):
        w = self.worker
        self.worker = None
        if w is not None:
            w.wait()
        self.enable_buttons()

    def on_failed(self, text, user):
        self.bar.setRange(0, 1000)
        self.finish_worker()
        self.status("Solve failed.")
        if user:
            QMessageBox.warning(self, "Solve", text)
        else:
            QMessageBox.warning(self, "Solve", "The program hit an error. Please copy this and send it to me:\n\n" + text)

    def on_done(self, res):
        self.finish_worker()
        self.result = res
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000)
        self.show_result(res)

    def study_adapter(self):
        """What the Parametric Studies add-on talks to (study_iface.py)."""
        import study_cfd
        return study_cfd.CFDStudy(self)

    def load_case(self, mesh, res, frame, setup_used):
        """Shows a stored result (from the Parameterization tab): its mesh, its final flow state and its numbers."""
        self.stop_motion()
        self.mesh, self.result, self.setup_used = mesh, res, setup_used
        self.frames, self.field_cache = ([frame] if frame is not None else []), {}
        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.canvas.raster = self.canvas.base = self.canvas.mesh_pix = None
        self.canvas.particles = None
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000)
        self.show_result(res)
        self.canvas.fit()
        self.enable_buttons()

    def show_result(self, res):
        self.plot.set_history(res.get("all_history") or res["history"], res["tol"])
        h = res["history"]
        last = max(h[-1][2:5]) if h else float("nan")
        if res["status"] == "converged":
            verdict = (f"<b style='color:#1a7a1a'>Converged</b> after {res['steps']} steps (t = {res['t']:.4g} s): the change per "
                       f"step stayed below {res['tol']:g}.")
        elif res["status"] == "stalled":
            verdict = (f"<b style='color:#b00020'>Stopped: not settling</b> after {res['steps']} steps (last change {last:.2e}, "
                       f"tolerance {res['tol']:g}). The flow is probably unsteady, or the setup needs a smaller CFL, larger "
                       "margins or the turbulence model. The last step is not a steady state.")
        elif res["status"] == "stopped":
            verdict = (f"<b style='color:#b36b00'>Stopped</b> by you after {res['steps']} steps, NOT converged "
                       f"(last change {last:.2e}, tolerance {res['tol']:g}).")
        else:
            verdict = (f"<b style='color:#b00020'>NOT converged</b> after {res['steps']} steps (last change {last:.2e}, tolerance "
                       f"{res['tol']:g}). The flow may be unsteady (vortex shedding) or needs more steps. "
                       "You can still use this last step, but it is not a steady state.")
        f = res["forces"]
        m_ = res["mass"]
        yp_txt = ""
        if res.get("yplus"):
            ymax = max(v[2] for v in res["yplus"].values())
            col = "#1a7a1a" if ymax <= 5 else "#b00020"
            yp_txt = (f"<br>y+ at the first node: max <b style='color:{col}'>{ymax:.3g}</b>"
                      + ("" if ymax <= 5 else " (above 5: the wall layer is not resolved - lower the target y+ and mesh again)"))
        fa, fu = self.force_txt(f["along"])
        fc, _ = self.force_txt(f["across"])
        self.res_lbl.setText(verdict + yp_txt + f"<br>Re (body size) = {res['re']:.3g}<br>"
                             f"force on the bodies per unit of depth: along the wind {fa:.5g} {fu}, across {fc:.5g} {fu}<br>"
                             f"mass balance: net flux / inflow = {m_['relative']:.2e}")
        rf = res.get("refine")
        if rf:
            lines, why = prefine.summary_lines(rf["log"], rf["reason"], "cfd")
            col = "#1a7a1a" if rf["reason"] == "converged" else "#b36b00"
            self.res_lbl.setText(self.res_lbl.text() + "<br><br><b>Auto-refinement</b><br>" + "<br>".join(lines) +
                                 f"<br><b style='color:{col}'>{why}</b>")
        self.res_lbl.setText(self.res_lbl.text() + self.heat_result_html(res))
        self.status("Solved." if res["status"] == "converged" else "Finished, NOT converged.")
        self.selection_changed()
        self.canvas.update()

    def heat_result_html(self, res):
        """The lines about the temperature under the flow's numbers ('' when this run had no heat transfer)."""
        if res.get("heat_error"):
            return "<br><br><b style='color:#b00020'>Temperature not found:</b> " + res["heat_error"].replace("\n", "<br>")
        h = res.get("heat")
        if h is None:
            return ""
        hs = self.hunits()
        T = lambda v: f"{hu.from_si('T', hs['T'], v):.4g} {hs['T']}"
        b = h["balance"]
        rel = abs(b["relative"])
        col = "#1a7a1a" if rel <= 0.05 else "#b00020"
        rows = [f"<b>Temperature</b>: from {T(h['Tmin'])} to {T(h['Tmax'])} (inlet {T(h['T_in'])}), Prandtl number {h['Pr']:.3g}",
                f"heat from the walls into the fluid {hu.from_si('P', hs['P'], b['walls']):.4g} {hs['P']} per metre of depth; carried away by the flow "
                f"{hu.from_si('P', hs['P'], b['advected']):.4g} {hs['P']}: <b style='color:{col}'>difference {100 * rel:.1f} %</b>"
                + ("" if rel <= 0.05 else " (more than 5 %: the mesh is too coarse for this temperature field, or the flow is not settled)")]
        for n in h.get("notes", []):
            rows.append(f"<span style='color:#b36b00'>{n}</span>")
        return "<br><br>" + "<br>".join(rows)

    # --- save / restore with the sketch file
    INPUTS = ("fluid_combo", "e_rho", "e_mu", "e_speed", "e_angle", "e_ml", "e_mr", "e_mb", "e_mt", "e_hb", "e_hf",
              "e_tr", "e_yp", "e_gr", "e_first", "e_bt", "turb", "e_int", "e_vr", "e_cfl", "e_dt", "e_steps", "e_tol", "e_every", "cb_until", "e_ramp",
              "cb_mesh", "cb_auto", "e_passes", "e_maxtris", "cb_heat", "e_k", "e_cp", "e_Tin")

    def signature_extra(self):
        """What besides the input boxes makes a project 'changed' (the Workbench and the window's own Save ask): the wall conditions of the heat transfer, the bodies that are on."""
        return (sorted((tuple(k), c["kind"], c["v"]) for k, c in self.heat_walls.items()), sorted(self.body_on), dict(self.heat_inputs_units))

    def export_state(self):
        return {"model_json": self.model.to_json(), "source": getattr(self, "source", ""),
                "inputs": pstore.get_inputs(self, self.INPUTS), "body_on": sorted(self.body_on), "body_size": self.body_size,
                "mesh": self.mesh, "result": self.result, "frames": self.frames, "setup_used": getattr(self, "setup_used", None),
                "field": self.field.currentData(), "frame_index": self.slider.value(), "res_html": self.res_lbl.text(),
                "sel": list(self.canvas.sel), "sketch_id": getattr(self, "sketch_id", None), "mesh_opts": self.mesh_state(),
                "heat_walls": [[list(k), c["kind"], c["v"]] for k, c in sorted(self.heat_walls.items())], "heat_units": dict(self.heat_inputs_units)}

    def import_state(self, st, out_of_date=False):
        m = sc.Model()
        m.from_json(st["model_json"])
        self.set_model(m, st.get("source") or "the saved sketch")
        self.sketch_id = st.get("sketch_id")
        pstore.set_inputs(self, st.get("inputs", {}))
        saved = st.get("heat_units")
        self.heat_inputs_units = hu.clean(saved) if isinstance(saved, dict) else self.hunits()          # the units the saved boxes were written in
        self.heat_walls = {tuple(k): {"kind": kind, "v": float(v)} for k, kind, v in st.get("heat_walls", [])}
        self.adopt_heat_units()
        self.heat_box.setVisible(self.cb_heat.isChecked())
        self.refresh_unit_labels()
        self.restore_mesh_options(st)
        self.auto_toggled(self.cb_auto.isChecked())
        on = set(st.get("body_on", []))
        self.body_on = set()
        self.bodies.blockSignals(True)
        for r in range(self.bodies.count()):
            it = self.bodies.item(r)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                ok = r in on
                it.setCheckState(Qt.CheckState.Checked if ok else Qt.CheckState.Unchecked)
                if ok:
                    self.body_on.add(r)
        self.bodies.blockSignals(False)
        self.body_size = st.get("body_size", self.body_size)
        self.model_changed()
        self.update_sides()
        self.update_dt_note()
        self.update_bl_note()
        self.mesh = st.get("mesh")
        self.setup_used = st.get("setup_used")
        self.frames = list(st.get("frames") or [])
        self.field_cache = {}
        self.result = st.get("result")
        self.canvas.raster = self.canvas.base = None
        self.canvas.particles = None
        i = self.field.findData(st.get("field"))
        if i >= 0:
            self.field.blockSignals(True)
            self.field.setCurrentIndex(i)
            self.field.blockSignals(False)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(self.frames) - 1))
        self.slider.setValue(min(int(st.get("frame_index", 0)), max(0, len(self.frames) - 1)) if self.frames else 0)
        self.slider.blockSignals(False)
        self.plot.clear()
        if self.result is not None and self.mesh is not None:
            if st.get("res_html") is None:                      # converted to other units: the text is written again
                self.show_result(self.result)
            else:
                self.res_lbl.setText(st.get("res_html", ""))
            self.bar.setValue(1000)
            self.plot.set_history(self.result.get("all_history") or self.result.get("history", []), self.result.get("tol"))
            self.status("Restored the saved CFD setup and result.")
        elif self.mesh is not None:
            self.status("Restored the saved CFD setup and mesh (not solved).")
        else:
            self.status("Restored the saved CFD setup (not meshed).")
        self.canvas.sel = [tuple(k) for k in st.get("sel", []) if tuple(k) in {e["src"] for e in self.geom["edges"]}]
        self.selection_changed()
        self.canvas.fit()
        self.canvas.update()
        self.enable_buttons()
        if out_of_date:
            self.mark_out_of_date()

    def change_units(self, old, new, convert):
        """The program's unit system changed: convert this tab's copy of the sketch and its numbers.
        The mesh and the result are in SI inside and tied to the old numbers, so they are cleared."""
        had = self.mesh is not None
        st = self.export_state()
        st = pstore.convert_cfd_state(st, old, new, convert)
        self.import_state(st)
        if had and not convert:
            return "The CFD mesh and result were cleared (a relabel changes the model's real size; mesh and solve again)."
        return ""

    def mark_out_of_date(self):
        txt = ("<b style='color:#b36b00'>OUT OF DATE: the sketch has changed since this was saved. This tab still shows the "
               "older copy. Import the sketch again to update it (that clears the mesh and result).</b>")
        self.info.setText(txt + "<br>" + self.info.text())

    def clear_state(self):
        """Back to the freshly started tab (used when another sketch file is opened)."""
        self.stop_motion()
        self.sketch_id = None
        self.model = self.geom = self.mesh = self.result = None
        self.frames, self.field_cache = [], {}
        self.body_on = set()
        self.bodies.clear()
        self.heat_walls = {}
        self.refresh_heat_list()
        self.canvas.sel = []
        self.selection_changed()
        self.canvas.raster = self.canvas.base = None
        self.plot.clear()
        self.canvas.particles = None
        self.slider.setRange(0, 0)
        self.info.setText("Nothing imported yet.")
        self.res_lbl.setText("")
        self.prog_lbl.setText("")
        self.bar.setValue(0)
        self.frame_lbl.setText("no frames yet")
        self.lbl_frames.setText("Frames: none yet")
        self.enable_buttons()
        self.canvas.update()

    # --- display data
    def field_data(self):
        if not self.frames or self.mesh is None:
            return None
        i = min(self.slider.value(), len(self.frames) - 1)
        fr = self.frames[i]
        key = self.field.currentData()
        name, kind, unit = next((n, k, u) for n, kk, k, u in FIELD_LIST if kk == key)
        if key in ("k", "omega", "nut") and key not in fr:
            key = "speed"                                  # this run had no turbulence model
            name, kind, unit = next((n, k_, u) for n, kk, k_, u in FIELD_LIST if kk == key)
        hres = self.result.get("heat") if self.result is not None else None
        if key == "T" and hres is None:
            key = "speed"                                  # this run had no heat transfer
            name, kind, unit = next((n, k_, u) for n, kk, k_, u in FIELD_LIST if kk == key)
        unit, div = self.field_units(key)
        if key == "T":
            hs = self.hunits()
            vals = np.asarray(hu.from_si("T", hs["T"], np.asarray(hres["T"][:len(self.mesh["nodes"])], dtype=float)), dtype=float)
            self.frame_lbl.setText(f"frame {i + 1} of {len(self.frames)}: the temperature is that of the final flow")
            self.lbl_frames.setText(f"Frames: {len(self.frames)}")
            return {"values": vals, "kind": kind, "name": name, "unit": hs["T"], "stamp": (id(hres), key, hs["T"])}
        if key == "speed":
            vals = np.hypot(fr["ux"], fr["uy"])
        elif key in ("ux", "uy", "p", "k", "omega", "nut"):
            vals = fr[key]
        else:
            vals = self.vorticity(fr)
        vals = vals.astype(float)
        step_txt = f"step {fr['step']}, t = {fr['t']:.4g} s, change {fr['change']:.2e}"
        self.frame_lbl.setText(f"frame {i + 1} of {len(self.frames)}:  {step_txt}")
        self.lbl_frames.setText(f"Frames: {len(self.frames)}")
        if div != 1.0:
            vals = vals / div
        return {"values": vals, "kind": kind, "name": name, "unit": unit, "stamp": (id(fr), key, unit)}

    def vorticity(self, fr):
        if "gx" not in self.field_cache:
            tris = self.mesh["tris"]
            p = self.mesh["nodes"][tris] * self.lscale()
            x, y = p[:, :, 0], p[:, :, 1]
            b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
            c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
            A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
            self.field_cache["gx"] = b / (2 * A)[:, None]
            self.field_cache["gy"] = c / (2 * A)[:, None]
        tris = self.mesh["tris"]
        return (fr["uy"][tris] * self.field_cache["gx"]).sum(axis=1) - (fr["ux"][tris] * self.field_cache["gy"]).sum(axis=1)

    # --- frames and tracers
    def anim_duration(self):
        try:
            d = float(self.e_dur.text())
        except ValueError:
            d = 0.0
        if d <= 0:
            QMessageBox.warning(self, "Animate", "Duration must be a positive number of seconds.")
            return None
        return d

    def play_frames(self):
        n = len(self.frames)
        if n < 2:
            QMessageBox.information(self, "Animate", "There are no time frames yet. Solve first (Frame every (steps) sets how many are saved).")
            return
        dur = self.anim_duration()
        if dur is None:
            return
        self.play_timer.stop()
        self.slider.setValue(0)
        self.play_dir = 1
        self.play_timer.start(max(10, int(dur * 1000 / n)))

    def export_animation(self, path_fmt=None):
        """Saves the saved time frames (the slider's positions) as GIF / MP4 / PNG pictures.  -> the path written or None."""
        n = self.slider.maximum() + 1
        dur = self.anim_duration() if n >= 2 else 3.0
        if dur is None:
            return None
        if n < 2:
            QMessageBox.information(self, "Export animation", "There are no time frames yet. Solve first (Frame every (steps) sets how many are saved).")
            return None
        self.stop_motion()
        keep = self.slider.value()

        def grab(k):
            self.slider.setValue(k)
            self.canvas.repaint()
            return self.canvas.grab().toImage()
        cv = self.canvas

        def set_bg(level):
            import meshdraw as md
            md.set_background(255 if level is None else level)
            cv.export_bg = level
            cv.base = None                                      # the field picture starts from the new background
            cv.repaint()
        shown = cv.forced()                                         # the frames show the result, whatever node of the outline is selected
        shown.__enter__()
        try:
            return anim_export.export(self, "CFD", n, grab, n / dur, self.loop_combo.currentIndex(), say=self.status, path_fmt=path_fmt, set_bg=set_bg)
        finally:
            import meshdraw as md
            md.set_background(255)
            cv.export_bg = None
            cv.base = None
            self.slider.setValue(keep)
            shown.__exit__()

    def play_step(self):
        n = self.slider.maximum() + 1
        mode = self.loop_combo.currentIndex()
        v = self.slider.value() + self.play_dir
        if v >= n:
            if mode == 0:
                self.stop_motion()
                return
            if mode == 1:
                v = 0
            else:
                self.play_dir = -1
                v = max(0, n - 2)
        elif v < 0:
            self.play_dir = 1
            v = min(1, n - 1)
        self.slider.setValue(v)

    def stop_motion(self):
        self.play_timer.stop()

    def tracers_toggled(self, on):
        if not on:
            self.trace_timer.stop()
            self.canvas.update()
            return
        if self.result is None:
            QMessageBox.information(self, "Tracers", "Solve first; the particles follow the final flow.")
            self.cb_tracers.blockSignals(True)
            self.cb_tracers.setChecked(False)
            self.cb_tracers.blockSignals(False)
            return
        try:
            self.flow = pcfd.FlowField(self.result)
        except Exception as ex:
            QMessageBox.warning(self, "Tracers", f"Could not prepare the flow field: {ex}")
            self.cb_tracers.setChecked(False)
            return
        self.seed_particles(True)
        self.trace_timer.start(30)

    def seed_points(self, n, whole_domain):
        x0, y0, x1, y1 = self.mesh["box"]
        rng = self.rng
        if whole_domain:
            pts = np.stack([rng.uniform(x0, x1, n), rng.uniform(y0, y1, n)], axis=1)
        else:
            kinds = self.result["sides"]
            inlets = [s for s in pcfd.SIDES if kinds[s] == "inlet"]
            pts = []
            for _ in range(n):
                s = inlets[int(rng.integers(len(inlets)))]
                t = rng.uniform(0.02, 0.98)
                eps = 0.01 * (x1 - x0)
                if s == "left":
                    pts.append((x0 + eps, y0 + t * (y1 - y0)))
                elif s == "right":
                    pts.append((x1 - eps, y0 + t * (y1 - y0)))
                elif s == "bottom":
                    pts.append((x0 + t * (x1 - x0), y0 + eps))
                else:
                    pts.append((x0 + t * (x1 - x0), y1 - eps))
            pts = np.array(pts)
        return pts

    def seed_particles(self, first):
        self.rng = np.random.default_rng(1)
        n = 700
        pts = self.seed_points(n * 3, True)
        _, inside = self.flow.velocity(pts)
        pts = pts[inside][:n]
        self.canvas.particles = {"p": pts, "trail": [[tuple(q)] for q in pts], "age": self.rng.uniform(0, 10, len(pts))}

    def tracer_step(self):
        P = self.canvas.particles
        if P is None or self.result is None or self.flow is None:
            return
        res = self.result
        x0, y0, x1, y1 = self.mesh["box"]
        # model time -> display time: the free stream crosses the domain in about 12 s of display time
        speed_s = res["speed"] / res["lscale"]
        h = ((x1 - x0) / 12.0) / speed_s * 0.03
        p = P["p"]
        v1, in1 = self.flow.velocity(p)
        mid = p + 0.5 * h * v1 / res["lscale"]
        v2, in2 = self.flow.velocity(mid)
        new = p + h * v2 / res["lscale"]
        _, in3 = self.flow.velocity(new)
        P["age"] = P["age"] + 0.03
        dead = ~(in1 & in2 & in3) | (P["age"] > 14.0)
        if np.any(dead):
            pts = self.seed_points(int(dead.sum()), False)
            new[dead] = pts
            P["age"][dead] = self.rng.uniform(0, 3, int(dead.sum()))
        for k in range(len(new)):
            if dead[k]:
                P["trail"][k] = [tuple(new[k])]
            else:
                P["trail"][k].append(tuple(new[k]))
                if len(P["trail"][k]) > 7:
                    P["trail"][k].pop(0)
        P["p"] = new
        self.canvas.update()

    # --- hand over to the FEA tab
    def clear_selection(self):
        self.canvas.sel = []
        self.selection_changed()
        self.canvas.update()

    def send_to_fea(self):
        """Selects the same edges in the FEA tab and opens its pressure-transfer dialog."""
        win = self.win
        fea = getattr(win, "phys", None)
        sel = [k for k in self.canvas.sel if k in (self.result["walls"] if self.result is not None else {})]
        if fea is None or not hasattr(fea, "add_cfd_load"):
            QMessageBox.information(self, "Use in FEA", "The FEA tab is not available.")
            return
        if self.result is None or not sel:
            QMessageBox.information(self, "Use in FEA", "Solve a flow and select at least one wall edge first.")
            return
        if fea.geom is None:
            QMessageBox.information(self, "Use in FEA", "Import the sketch in the FEA tab first (choose a sketch and press Import), "
                                    "then press this button again.")
            return
        have = {e["src"] for e in fea.geom["edges"]}
        same = [k for k in sel if k in have]
        missing = [k for k in sel if k not in have]
        fea.canvas.sel = same
        fea.canvas.update()
        try:
            win.tabs.setCurrentWidget(fea)
        except Exception:
            pass
        if missing:
            QMessageBox.information(self, "Use in FEA", "These edges do not exist in the FEA tab's sketch: " +
                                    ", ".join(f"{pt.KIND_NAME.get(k[0], k[0])} {k[1]}" for k in missing) +
                                    ".\nThe dialog will still offer the CFD selection; select the matching FEA edges first if "
                                    "none were found.")
        fea.add_cfd_load()

    def transfer_info(self):
        """What the FEA tab needs to load a body with this result, or None."""
        if self.result is None or self.model is None:
            return None
        return {"result": self.result, "edge_geoms": self.setup_used["edge_geoms"], "status": self.result["status"],
                "walls": self.result["walls"], "lscale": self.result["lscale"], "heat": self.result.get("heat")}

    # --- diagnostics
    def show_diag(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("CFD diagnostics report")
        dlg.resize(820, 640)
        lay = QVBoxLayout(dlg)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setFont(QFont("Consolas", 9))
        box.setPlainText(self.diagnostics_text())
        lay.addWidget(box)
        row = QHBoxLayout()
        b = QPushButton("Copy to clipboard")
        b.clicked.connect(lambda: QGuiApplication.clipboard().setText(box.toPlainText()))
        row.addWidget(b)
        b = QPushButton("Save as text file...")

        def save():
            path, _ = QFileDialog.getSaveFileName(dlg, "Save report", "cfd_report.txt", "Text (*.txt)")
            if path:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(box.toPlainText())
        b.clicked.connect(save)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        dlg.exec()

    def diagnostics_text(self):
        L = []
        add = L.append
        add("CFD - DIAGNOSTICS")
        add(time.strftime("%Y-%m-%d %H:%M:%S"))
        add(f"python {sys.version.split()[0]} on {platform.platform()}")
        for n, (v, t) in self.deps.items():
            add(f"  {n}: {v if v else 'NOT AVAILABLE  ' + t}")
        if self.geom is None:
            add("\nNothing imported.")
            return "\n".join(L)
        g = self.geom
        add("\n== Sketch ==")
        add(f"source: {getattr(self, 'source', '?')}")
        add(f"edges {len(g['edges'])}, outlines {len(g['faces'])}, not in a closed loop (ignored): "
            f"{[f'{k} {i}' for k, i in g['pruned']] or 'none'}")
        add("possible gaps (ends that almost touch): " + ("none" if not g.get("gaps") else "; ".join(pg.gap_text(x) for x in g["gaps"][:10])))
        add("edge crossings: " + ("none" if not g["crossings"] else str(len(g["crossings"]))))
        add(f"solid bodies: {[i + 1 for i in sorted(self.body_on)]}   (holes inside a body are treated as solid)")
        add("\n== Setup ==")
        add(f"unit system: {self.unit_name()}  (1 sketch unit = {self.lscale():g} m; the report below is in SI unless it says otherwise)")
        try:
            sp_, rho_, mu_ = self.si_inputs()
        except ValueError:
            sp_ = rho_ = mu_ = float("nan")
        add(f"fluid: {self.fluid_combo.currentText()}, density {self.e_rho.text()} {self.U()['rho']} = {rho_:.6g} kg/m3, "
            f"viscosity {self.e_mu.text()} {self.U()['mu']} = {mu_:.6g} Pa s")
        add(f"wind: {self.e_speed.text()} {self.U()['V']} = {sp_:.6g} m/s toward {self.e_angle.text()} deg")
        kinds, _ = pcfd.classify_sides(self.angle_value())
        add("sides: " + ", ".join(f"{s} {kinds[s]}" for s in pcfd.SIDES))
        if self.cb_heat.isChecked():
            hs = self.hunits()
            try:
                k_, cp_, tin_ = self.heat_si()
            except ValueError:
                k_ = cp_ = tin_ = float("nan")
            add(f"heat transfer: ON; conductivity {self.e_k.text()} {hs['k']} = {k_:.6g} W/(m K), specific heat {self.e_cp.text()} {hs['cp']} = {cp_:.6g} J/(kg K), "
                f"inlet temperature {self.e_Tin.text()} {hs['T']} = {tin_:.6g} K")
            if self.heat_walls:
                for key in sorted(self.heat_walls):
                    c = self.heat_walls[key]
                    add(f"  {pt.KIND_NAME.get(key[0], key[0])} {key[1]}: " + (f"fixed temperature {c['v']:.6g} K" if c["kind"] == "temp" else
                                                                             "wall of the thermal analysis (Coupled Physics)" if c["kind"] == "coupled" else
                                                                             f"heat flux into the fluid {c['v']:.6g} W/m2"))
            else:
                add("  no wall has a heat condition (the solve will refuse)")
        else:
            add("heat transfer: off")
        add(f"margins (left, right, bottom, top) in body sizes: {self.e_ml.text()}, {self.e_mr.text()}, {self.e_mb.text()}, {self.e_mt.text()}")
        add(f"solver: {'k-omega SST' if self.is_sst() else 'laminar'}, CFL {self.e_cfl.text()}, time step "
            f"{self.e_dt.text().strip() or 'automatic'}, max steps {'none (run until converged)' if self.cb_until.isChecked() else self.e_steps.text()}, "
            f"tolerance {self.e_tol.text()}, gentle start {self.e_ramp.text()} steps")
        if self.is_sst():
            add(f"turbulence: intensity {self.e_int.text()} %, eddy viscosity ratio {self.e_vr.text()}, target y+ {self.e_yp.text()}, "
                f"layer growth {self.e_gr.text()}, first layer {self.e_first.text().strip() or 'auto'}, "
                f"thickness {self.e_bt.text().strip() or 'auto'}")
            est = self.bl_estimate()
            if est:
                add(f"  flat-plate estimate: first layer {est['y1']:.4g} m, thickness {est['delta']:.4g} m, {est['layers']} layers, "
                    f"u_tau {est['u_tau']:.4g} m/s, Re {est['Re']:.4g}")
        if self.mesh is None:
            add("\nNo mesh yet.")
            return "\n".join(L)
        s = self.mesh["stats"]
        add("\n== Mesh ==")
        add(f"gmsh {s.get('gmsh', '?')}, algorithm {s['algorithm']}; size at the body {s['h_body']:g}, far {s['h_far']:g}, growth distance "
            f"{s['transition']:g} body sizes")
        add(f"body size {self.mesh['size']:.6g}, box {tuple(round(v, 6) for v in self.mesh['box'])}")
        add(f"vertices {s['n_nodes']}, triangles {s['n_tris']}, outlines meshed {self.mesh['n_loops']}")
        add(f"edge length min/max: {s['edge_min']:.6g} / {s['edge_max']:.6g}")
        add(f"angle min/max: {s['angle_min']:.2f} / {s['angle_max']:.2f} deg, aspect ratio mean/max {s['aspect_mean']:.3f} / {s['aspect_max']:.3f}")
        add(f"degenerate triangles: {s['n_degenerate']}, re-oriented: {s['n_flipped']}")
        if s.get("bl"):
            b_ = s["bl"]
            add(f"boundary-layer mesh: first layer {b_['h1']:.4g}, growth {b_['ratio']:g}, thickness {b_['thickness']:.4g} (sketch units); "
                f"smallest element height {s['alt_min']:.4g}, largest stretch (longest edge / height) {s['stretch_max']:.3g}")
        else:
            add("boundary-layer mesh: none")
        for note in s.get("relaxed") or []:
            add("mesher had to relax: " + note)
        if s.get("corners"):
            add(f"sharp convex corners given a boundary-layer fan and extra refinement: {s['corners']}")
        add("wall segments per sketch edge: " + ", ".join(f"{k[0]} {k[1]}: {len(v)}" for k, v in self.mesh["wall_segs"].items()))
        add("box segments: " + ", ".join(f"{k}: {len(v)}" for k, v in self.mesh["box_segs"].items()))
        if self.result is None:
            add("\nNot solved yet." if self.worker is None else "\nSolving...")
            return "\n".join(L)
        r = self.result
        add("\n== Solution ==")
        add(f"velocity nodes (quadratic) {r['n_u']}, pressure nodes {r['n_p']}, unknowns {2 * r['n_u'] + r['n_p']}")
        add(f"status: {r['status'].upper()} after {r['steps']} steps, t = {r['t']:.6g} s, time step {r['dt']:.6g} s, tolerance {r['tol']:g}")
        h = r["history"]
        if h:
            add("change per step (velocity / pressure / turbulence k, omega):")
            pick = sorted(set(list(range(min(5, len(h)))) + list(range(max(0, len(h) - 10), len(h)))))
            for k in pick:
                add(f"  step {h[k][0]:5d}  t = {h[k][1]:.5g}   {h[k][2]:.3e}  {h[k][3]:.3e}  {h[k][4]:.3e}")
            add(f"  minimum over the run: velocity {min(x[2] for x in h):.3e}, pressure {min(x[3] for x in h):.3e}")
        tb_ = r.get("turb")
        if tb_:
            add(f"turbulence: inlet k {tb_['k_in']:.4g} m2/s2, omega {tb_['om_in']:.4g} 1/s;  k range {float(tb_['k'].min()):.4g} .. "
                f"{float(tb_['k'].max()):.4g};  omega range {float(tb_['omega'].min()):.4g} .. {float(tb_['omega'].max()):.4g};  "
                f"max nut/nu {float(np.max(tb_['nut_ratio'])):.4g}")
            for src, (lo, mean, hi) in r["yplus"].items():
                add(f"  y+ at the first node, {src[0]} {src[1]}: min {lo:.3g}, mean {mean:.3g}, max {hi:.3g}")
        add(f"Reynolds number (body size, free stream) {r['re']:.4g}, dynamic pressure q = {r['q']:.6g} Pa")
        m_ = r["mass"]
        add("mass flux through the box sides (positive = out, m2/s per metre of depth): " +
            ", ".join(f"{s_} ({r['sides'][s_]}) {v:.6g}" for s_, v in m_["flux"].items()))
        add(f"inflow {m_['inflow']:.6g}, net {m_['net']:.3e}, net / inflow {m_['relative']:.3e}")
        f = r["forces"]
        add(f"force on the bodies per metre of depth: pressure ({f['pressure'][0]:.6g}, {f['pressure'][1]:.6g}) N, "
            f"viscous ({f['viscous'][0]:.6g}, {f['viscous'][1]:.6g}) N, total ({f['total'][0]:.6g}, {f['total'][1]:.6g}) N")
        add(f"  along the wind {f['along']:.6g} N, across (to the left of the wind) {f['across']:.6g} N")
        add("  per sketch edge (Fx, Fy): " + "; ".join(f"{k[0]} {k[1]}: ({v[0]:.5g}, {v[1]:.5g})" for k, v in f["per_edge"].items()))
        pv = [float(np.min(t["p_a"])) for t in r["walls"].values()] + [float(np.max(t["p_a"])) for t in r["walls"].values()]
        if pv:
            add(f"wall pressure range: {min(pv):.6g} .. {max(pv):.6g} Pa  (gauge, relative to the outlet)")
        hr_ = r.get("heat")
        if r.get("heat_error"):
            add("\n== Temperature ==\nNOT FOUND: " + r["heat_error"])
        elif hr_ is not None:
            b_ = hr_["balance"]
            add("\n== Temperature (passive: the flow does not depend on it) ==")
            add(f"fluid: conductivity {hr_['k']:.6g} W/(m K), specific heat {hr_['cp']:.6g} J/(kg K), Prandtl number {hr_['Pr']:.4g}, "
                f"diffusivity {hr_['alpha']:.4g} m2/s, inlet {hr_['T_in']:.6g} K")
            add(f"temperature range {hr_['Tmin']:.6g} .. {hr_['Tmax']:.6g} K"
                + ("" if hr_.get("overshoot") is None else f"; outside the given temperatures by {hr_['overshoot']:.3g} K"))
            add(f"energy balance (W per metre of depth): from the walls {b_['walls']:.6g}, carried away by the flow {b_['advected']:.6g}, "
                f"difference {100 * b_['relative']:.2f} % of the larger (inlet reaction {b_['inlet']:.3g})")
            for key, tb in hr_["walls"].items():
                add(f"  {key[0]} {key[1]}: {tb['kind']}, heat into the fluid {tb['Q']:.6g} W, temperature {tb['T_min']:.6g} .. {tb['T_max']:.6g} K")
            for n_ in hr_.get("notes", []):
                add("  note: " + n_)
        add("linear solver: " + psolve.status()[1] + ("   (last solve used " + psolve.last_used() + ")" if psolve.last_used() else ""))
        add(f"timing: assemble {r['times']['assemble']:.2f} s, solve {r['times']['solve']:.2f} s, total {r['times']['total']:.2f} s")
        return "\n".join(L)
