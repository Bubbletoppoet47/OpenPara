"""lab_probe.py - Constraint Lab: the Drag Recorder and the view guard.

Drag Recorder   While it is on, every mouse press / release / drag step on the 3D view is logged together with what the CAMERA does: each time anything
                changes the camera (VTK reports it) the recorder keeps the stack of calls that did it, so a camera that moves while a part is being
                dragged shows who moved it (the drag code, the navigation code, or VTK's own mouse handling).  It also logs the size of the view, the
                interactor style, how long each drag step takes and how many renders it makes.  Turning it off shows the report and saves it
                (drag_record.txt and drag_record_raw.csv in the user folder).
View guard      The assembly view turns VTK's own mouse-orbit off (it installs an empty "user" interactor style through VTK), but pyvista still believes
                its orbit style is active.  If anything makes pyvista apply that style again, a left-drag orbits the camera while the drag code moves the
                part.  The guard looks at the style on every mouse press, puts the empty one back (also telling pyvista) and counts it.
                The recorder reports every correction."""
import csv
import math
import os
import platform
import statistics
import time
import traceback

import numpy as np
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QWidget

try:
    from vtkmodules.vtkInteractionStyle import vtkInteractorStyleUser
except Exception:                                         # pragma: no cover - only without VTK
    vtkInteractorStyleUser = None

CAM_NAMES = ("position", "focal point", "view up", "view angle", "clipping range", "parallel scale")


def widgets_of(plotter):
    return [plotter] + list(plotter.findChildren(QWidget))


def style_name(plotter):
    try:
        return type(plotter.iren.interactor.GetInteractorStyle()).__name__
    except Exception:
        return "?"


def camera_snapshot(cam):
    return np.array(list(cam.GetPosition()) + list(cam.GetFocalPoint()) + list(cam.GetViewUp()) + [cam.GetViewAngle()] + list(cam.GetClippingRange())
                    + [cam.GetParallelScale()], float)


def camera_parts(delta):
    """Which camera quantities a difference vector (13 numbers) touches, with the size of the change."""
    spans = ((0, 3), (3, 6), (6, 9), (9, 10), (10, 12), (12, 13))
    out = []
    for (a, b), name in zip(spans, CAM_NAMES):
        m = float(np.max(np.abs(delta[a:b])))
        if m > 1e-9:
            out.append((name, m))
    return out


class ViewGuard(QObject):
    """Installed after the other mouse hooks, so it sees every press before they and VTK do (Qt calls the last installed filter first)."""

    def __init__(self, win):
        super().__init__(win.plotter)
        self.win, self.enabled, self.fired, self.log = win, True, 0, []
        self.user = vtkInteractorStyleUser() if vtkInteractorStyleUser is not None else None
        self.apply()
        for w in widgets_of(win.plotter):
            w.installEventFilter(self)

    def apply(self):
        """Make the empty style the one pyvista knows about too, so that its own update_style() keeps it."""
        pl = self.win.plotter
        if self.user is None or pl is None:
            return
        try:
            pl.iren.style = self.user
        except Exception:
            try:
                pl.iren.interactor.SetInteractorStyle(self.user)
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        try:
            if self.enabled and self.user is not None and ev.type() == QEvent.Type.MouseButtonPress:
                st = self.win.plotter.iren.interactor.GetInteractorStyle()
                if not isinstance(st, vtkInteractorStyleUser):
                    self.fired += 1
                    self.log.append(type(st).__name__)
                    pr = getattr(self.win, "probe", None)
                    if pr is not None:
                        pr.note(f"view guard: the interactor style was {type(st).__name__} at a mouse press; put the empty one back")
                    self.apply()
                    self.win.say(f"View guard: the view had switched to {type(st).__name__} (left-drag would orbit the camera); put back.")
        except Exception:
            pass
        return False


class DragProbe(QObject):
    """The recorder.  Installed last on the view, so it sees every mouse event before the hooks act on it."""

    MAX_ROWS = 60000

    def __init__(self, win):
        super().__init__(win.plotter)
        self.win, self.pl = win, win.plotter
        self.t0 = time.perf_counter()
        self.rows, self.cam_mods, self.steps, self.renders, self.notes, self.drags = [], [], [], [], [], []
        self.size_changes, self.cur, self.last_event, self.text = [], None, "-", ""
        self.cam = self.pl.camera
        self.snap = camera_snapshot(self.cam)
        self.size = (self.pl.width(), self.pl.height())
        self.start_info = self.environment()
        self.obs = self.cam.AddObserver("ModifiedEvent", self.on_camera)
        self.widgets = widgets_of(self.pl)
        for w in self.widgets:
            w.installEventFilter(self)
        # timing of the drag steps and the renders (instance attributes shadow the methods; removed again in stop())
        self.orig_step = win.drag_move
        win.drag_move = self.timed_step
        self.orig_render = self.pl.render
        self.pl.render = self.counted_render
        self.active = True

    # ------------------------------------------------------------------ what is recorded
    def ms(self):
        return 1000.0 * (time.perf_counter() - self.t0)

    def note(self, text):
        self.notes.append((self.ms(), text))

    def environment(self):
        lines = [f"python {platform.python_version()} on {platform.platform()}"]
        try:
            import pyvista
            import pyvistaqt
            from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
            from vtkmodules.vtkCommonCore import vtkVersion
            lines.append(f"pyvista {pyvista.__version__}, pyvistaqt {pyvistaqt.__version__}, VTK {vtkVersion.GetVTKVersion()}, Qt {QT_VERSION_STR}, PyQt6 {PYQT_VERSION_STR}")
        except Exception:
            pass
        try:
            from PyQt6.QtGui import QGuiApplication
            sc = self.win.screen() or QGuiApplication.primaryScreen()
            lines.append(f"screen {sc.name()}: {sc.size().width()}x{sc.size().height()}, display scale {sc.devicePixelRatio():g}, "
                         f"{len(QGuiApplication.screens())} screen(s); Qt platform {QGuiApplication.platformName()}")
            lines.append(f"3D view {self.pl.width()}x{self.pl.height()} (device pixel ratio {self.pl.devicePixelRatioF():g}); window {self.win.width()}x{self.win.height()}")
        except Exception:
            pass
        try:
            lines.append(f"interactor style now: {style_name(self.pl)}; pyvista believes: {type(self.pl.iren.style).__name__}")
            lines.append(f"projection: {'parallel' if self.cam.GetParallelProjection() else 'perspective'}; engine: {getattr(self.win, 'engine_name', '?')}; "
                         f"outline drawing: {self.win_setting('outline_mode')}; face recolour: {getattr(self.win, 'face_tint', '?')}")
        except Exception:
            pass
        return lines

    @staticmethod
    def win_setting(key):
        try:
            import settings
            return settings.get(key)
        except Exception:
            return "?"

    def on_camera(self, *_a):
        try:
            new = camera_snapshot(self.cam)
            delta = new - self.snap
            self.snap = new
            frames = [f for f in traceback.extract_stack()[:-1] if os.path.basename(f.filename) != "lab_probe.py"]
            tail = [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in frames[-9:]]
            down = self.cur is not None
            changed = camera_parts(delta)
            self.cam_mods.append({"t": self.ms(), "down": down, "event": self.last_event, "changed": changed, "stack": tail, "btn": self.cur["btn"] if down else None,
                                  "sig": " > ".join(t.split(" ")[-1] for t in tail[-5:])})
            if self.cur is not None:
                self.cur["cam_mods"] += 1
                self.cur["cam_changed"] += 1 if changed else 0
        except Exception:
            pass

    def check_size(self):
        """The size of the 3D view is looked at on every resize, mouse event and drag step (a hidden widget gets its resize event late)."""
        size = (self.pl.width(), self.pl.height())
        if size != self.size:
            self.size_changes.append((self.ms(), self.size, size, self.cur is not None))
            self.size = size

    def timed_step(self, *a, **k):
        self.check_size()
        t = time.perf_counter()
        n0 = len(self.renders)
        try:
            return self.orig_step(*a, **k)
        finally:
            self.steps.append((self.ms(), 1000.0 * (time.perf_counter() - t), len(self.renders) - n0))
            if self.cur is not None:
                self.cur["steps"] += 1

    def counted_render(self, *a, **k):
        self.renders.append(self.ms())
        return self.orig_render(*a, **k)

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if t == QEvent.Type.Resize and obj is self.pl:
                self.check_size()
                return False
            if t not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseMove):
                return False
            self.check_size()
            held = int(ev.buttons().value) if hasattr(ev.buttons(), "value") else int(ev.buttons())
            if t == QEvent.Type.MouseMove and not held:
                return False                                   # hovering is not recorded
            kind = {QEvent.Type.MouseButtonPress: "press", QEvent.Type.MouseButtonRelease: "release", QEvent.Type.MouseMove: "move"}[t]
            btn = ev.button().name if kind != "move" else "-"
            p = ev.position()
            self.last_event = f"{kind} {btn if btn != '-' else ''}".strip()
            if len(self.rows) < self.MAX_ROWS:
                self.rows.append((round(self.ms(), 2), kind, btn, held, round(p.x(), 1), round(p.y(), 1), style_name(self.pl), self.pl.width(), self.pl.height()))
            if kind == "press" and self.cur is None:
                self.cur = {"btn": btn, "t0": self.ms(), "cam0": camera_snapshot(self.cam), "size0": (self.pl.width(), self.pl.height()), "moves": 0, "steps": 0,
                            "cam_mods": 0, "cam_changed": 0, "style0": style_name(self.pl), "r0": len(self.renders), "p0": (p.x(), p.y()), "p1": (p.x(), p.y())}
            elif kind == "move" and self.cur is not None:
                self.cur["moves"] += 1
                self.cur["p1"] = (p.x(), p.y())
            elif kind == "release" and self.cur is not None and btn == self.cur["btn"]:
                d, self.cur = self.cur, None
                d.update(t1=self.ms(), cam1=camera_snapshot(self.cam), size1=(self.pl.width(), self.pl.height()), r1=len(self.renders))
                self.drags.append(d)
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ end and report
    def stop(self):
        if not self.active:
            return self.text
        self.active = False
        try:
            self.cam.RemoveObserver(self.obs)
        except Exception:
            pass
        for w in self.widgets:
            try:
                w.removeEventFilter(self)
            except Exception:
                pass
        self.win.__dict__.pop("drag_move", None)               # back to the class's own method
        try:
            self.pl.render = self.orig_render                  # what render was before the recorder wrapped it
        except Exception:
            pass
        if self.cur is not None:                               # a button was still down: close that drag as it is
            d, self.cur = self.cur, None
            d.update(t1=self.ms(), cam1=camera_snapshot(self.cam), size1=(self.pl.width(), self.pl.height()), r1=len(self.renders), open=True)
            self.drags.append(d)
        self.text = self.report()
        return self.text

    @staticmethod
    def pct(v, q):
        v = sorted(v)
        return v[min(len(v) - 1, int(math.ceil(q * len(v))) - 1)] if v else float("nan")

    def report(self):
        L = ["Drag Recorder report", "=" * 20, ""]
        L += self.start_info
        L.append("")
        dur = (self.ms() - 0.0) / 1000.0
        presses = sum(1 for r in self.rows if r[1] == "press")
        L.append(f"Recorded {dur:.1f} s: {len(self.rows)} mouse events with a button down, {presses} button press(es), {len(self.drags)} press-to-release run(s), "
                 f"{len(self.steps)} drag step(s) of the part, {len(self.renders)} render(s).")
        L.append("")
        L.append("Each press-to-release run   (camera columns: the largest change of any camera value between press and release)")
        L.append(f"{'#':>2} {'button':<12} {'secs':>5} {'moves':>6} {'steps':>6} {'renders':>7} {'cam events':>10}  camera change / view size / interactor style")
        for i, d in enumerate(self.drags, 1):
            parts = camera_parts(d["cam1"] - d["cam0"])
            ch = ", ".join(f"{n} {m:.3g}" for n, m in parts) or "none"
            sz = "same size" if d["size0"] == d["size1"] else f"VIEW RESIZED {d['size0']} -> {d['size1']}"
            L.append(f"{i:>2} {d['btn']:<12} {(d['t1'] - d['t0']) / 1000:5.2f} {d['moves']:6d} {d['steps']:6d} {d['r1'] - d['r0']:7d} {d['cam_mods']:10d}  "
                     f"{ch} / {sz} / {d['style0']}")
        L.append("")
        mods_down = [m for m in self.cam_mods if m["down"]]
        L.append(f"Camera modifications reported by VTK: {len(self.cam_mods)} in total, {len(mods_down)} while a mouse button was down.")
        groups = {}
        for m in mods_down:
            groups.setdefault((m["sig"], m["btn"]), []).append(m)
        for (sig, btn_), ms_ in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            L.append(f"  {len(ms_)} x  with the {btn_} down, during a '{ms_[0]['event']}' event; changed: " + (", ".join(f"{n} {v:.3g}" for n, v in ms_[0]["changed"]) or "nothing visible"))
            L.append("       called from:  " + "  >  ".join(ms_[0]["stack"][-7:]))
        L.append("")
        if self.size_changes:
            L.append("The 3D view changed size:")
            for t, a, b, down in self.size_changes[:12]:
                L.append(f"  at {t / 1000:.2f} s: {a} -> {b}" + ("  (while a button was down)" if down else ""))
        else:
            L.append("The 3D view did not change size.")
        L.append("")
        styles = {}
        for r in self.rows:
            if r[1] == "press":
                styles[r[6]] = styles.get(r[6], 0) + 1
        L.append("Interactor style at each press: " + (", ".join(f"{k} x{v}" for k, v in styles.items()) or "-"))
        guard = getattr(self.win, "guard", None)
        L.append(f"View guard: {'on' if guard is not None and guard.enabled else 'off'}, corrected the style {getattr(guard, 'fired', 0)} time(s)")
        for t, text in self.notes[:12]:
            L.append(f"  at {t / 1000:.2f} s: {text}")
        L.append("")
        if self.steps:
            ms_ = [s[1] for s in self.steps]
            gaps = [b[0] - a[0] for a, b in zip(self.steps, self.steps[1:]) if b[0] - a[0] < 1000]
            per = [s[2] for s in self.steps]
            L.append(f"Drag steps (each solves the mates, then redraws): {len(ms_)}; time per step: median {statistics.median(ms_):.1f} ms, 90% under {self.pct(ms_, .9):.1f} ms, "
                     f"slowest {max(ms_):.1f} ms; renders per step: {statistics.mean(per):.2f}.")
            if gaps:
                L.append(f"Time between steps: median {statistics.median(gaps):.1f} ms, 90% under {self.pct(gaps, .9):.1f} ms, longest {max(gaps):.0f} ms "
                         f"(uneven gaps look like jitter).")
        L.append("")
        L.append("What this says")
        nav = [i for i, d in enumerate(self.drags, 1) if d["btn"] == "MiddleButton"]                       # the middle button is the view control: it may move the camera
        bad = [i for i, d in enumerate(self.drags, 1) if d["btn"] != "MiddleButton" and (d["cam_changed"] or camera_parts(d["cam1"] - d["cam0"]))]
        if not self.drags:
            L.append("  Nothing was dragged while recording: no mouse button went down on the view.")
        elif not bad:
            what = "The camera was NOT touched during any drag" if not nav else \
                   f"The camera was NOT touched during any left- or right-button drag (it moved only during {len(nav)} middle-button drag(s), the normal view control)"
            L.append(f"  {what}" + (", and the view kept its size." if not self.size_changes else ", but the view changed size (see above)."))
        else:
            moved = [i for i in bad if self.drags[i - 1]["steps"]]
            L.append(f"  The camera WAS changed during {len(bad)} left- or right-button drag(s) (run {', '.join('#' + str(i) for i in bad)}); "
                     f"{len(moved)} of them also moved a part. The 'called from' lines above show what changed it.")
        if getattr(guard, "fired", 0):
            L.append("  The interactor style had been switched away from the empty one: that is what lets a left-drag orbit the camera.")
        return "\n".join(L) + "\n"

    def raw_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_ms", "event", "button", "buttons_held", "x", "y", "interactor_style", "view_w", "view_h"])
            w.writerows(self.rows)
            w.writerow([])
            w.writerow(["camera_t_ms", "button_down", "during_event", "changed", "called_from"])
            for m in self.cam_mods:
                w.writerow([round(m["t"], 2), m["down"], m["event"], "; ".join(f"{n} {v:.3g}" for n, v in m["changed"]), " > ".join(m["stack"])])
            w.writerow([])
            w.writerow(["step_t_ms", "step_ms", "renders_in_step"])
            w.writerows([(round(a, 2), round(b, 2), c) for a, b, c in self.steps])
