"""
lidar_camera_overlay.py

Live camera view with the Unitree L2's points drawn on top of it, colored by
distance. Uses the real lens model from camera_intrinsics.json (focal length,
optical center AND distortion coefficients, via cv2.projectPoints), plus the
LiDAR-to-camera mounting offset.

How the projection works
------------------------
Every LiDAR point p_l is moved into the camera's own frame
(x = right, y = down, z = forward, the OpenCV convention):

    p_c = R_adj @ ( M @ p_l  -  c )

  M      3x3 axis map: which LiDAR axis is the camera's right / down / forward.
         Starts from --forward-axis / --right-axis (the L2's +z is forward on
         your rig, per lidar_live_viewer.py) and you can cycle through all 24
         possible mountings live with the 'n' key if the first guess is wrong.
  c      where the camera sits relative to the LiDAR, in camera-aligned axes.
         Starts from your measured separation (--baseline-in 3.76, camera on
         the --camera-side of the LiDAR) and is nudged live.
  R_adj  a small yaw/pitch/roll correction for the mounting not being
         perfectly square. This is the one you'll actually tune.

Then p_c is projected to pixels with the calibrated camera matrix + distortion.

First-run procedure (takes a minute)
------------------------------------
  1. Point the rig at something with clear edges a few meters away (a door
     frame, a table edge, a box on the floor).
  2. If the dots are mirrored, upside-down, or sideways, press 'n' until they
     sit roughly on the right things (that fixes the axis map).
  3. Nudge with j/l (yaw), i/k (pitch), u/o (roll) until the dots hug the
     object edges at BOTH near and far range. If near things are still off
     sideways while far things line up, tune a/d (sideways offset).
  4. Press 'p' to save. Next run loads lidar_camera_extrinsics.json automatically.

Controls
--------
Everything is on the panel to the right of the video: click the buttons and
checkboxes (hold a < > ^ v button to repeat), or CLICK ANY NUMBER (yaw, pitch,
roll, shifts, camera #, ...) and type a value: Enter applies, Tab applies and
jumps to the next number, Esc cancels. Keyboard shortcuts still work
(click the video window first):

    n / N     next / previous axis mounting       c / C   next / previous camera
    j / l     dots left / right (yaw)             i / k   dots up / down (pitch)
    u / o     roll ccw / cw                       a / d   dots left / right (offset)
    w / s     dots up / down (offset)             r / f   depth offset +/-
    , / .     smaller / larger rotation step      [ / ]   LiDAR window shorter / longer
    - / =     color scale far end                 g       toggle dots
    p         save alignment                      SPACE   snapshot PNG
    v         start / stop recording              0       reset fine adjustments
    b         reload saved calibration
    q / Esc   quit

Notes
-----
* The camera and LiDAR are ~9.5 cm apart, so at very short range (< 1 m) the
  LiDAR sees slightly around objects the camera can't. Alignment is best judged
  at 2-5 m.
* Camera and LiDAR are not hardware-synchronized. Keep the rig steady or move
  slowly; the window key ([ ]) trades density against smear.
* The intrinsics were calibrated at 640x480. If the camera opens at another
  size, the matrix is rescaled, but for best accuracy leave it at 640x480.

Usage:
    python lidar_camera_overlay.py
    python lidar_camera_overlay.py --camera 0 --camera-side left
    python lidar_camera_overlay.py --scale 2 --record overlay.mp4
    python lidar_camera_overlay.py --selftest
"""
import argparse
import itertools
import json
import os
import sys
import time

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("This script needs opencv-python:  pip install opencv-python")

IN_TO_M = 0.0254
HERE = os.path.dirname(os.path.abspath(__file__))
AXIS_VECS = {
    "+x": (1, 0, 0), "-x": (-1, 0, 0),
    "+y": (0, 1, 0), "-y": (0, -1, 0),
    "+z": (0, 0, 1), "-z": (0, 0, -1),
}


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def proper_rotations_24():
    """All axis-aligned rotations (signed permutation matrices with det +1)."""
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                M[i, p] = s
            if np.linalg.det(M) > 0:
                mats.append(M)
    return mats


def axis_map(forward, right):
    """Rows = camera x (right), y (down), z (forward) expressed in LiDAR axes."""
    f = np.array(AXIS_VECS[forward], float)
    r = np.array(AXIS_VECS[right], float)
    if abs(f @ r) > 0.5:
        raise SystemExit("--forward-axis and --right-axis must be different axes")
    d = np.cross(f, r)  # down = forward x right  (right x down = forward)
    return np.vstack([r, d, f])


def rot_adj(yaw_deg, pitch_deg, roll_deg):
    y, p, r = np.radians([yaw_deg, pitch_deg, roll_deg])
    Ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    Rz = np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])
    return Rz @ Rx @ Ry


class Extrinsics:
    def __init__(self, M, cam_pos):
        self.M = np.array(M, float)
        self.c = np.array(cam_pos, float)      # camera position, camera-aligned axes (m)
        self.ang = np.zeros(3)                 # yaw, pitch, roll (deg)

    def to_camera(self, pts_lidar):
        R = rot_adj(*self.ang)
        return (pts_lidar @ self.M.T - self.c) @ R.T

    def to_json(self):
        return {"axis_map_rows_are_camera_xyz_in_lidar_axes": self.M.tolist(),
                "camera_position_m": self.c.tolist(),
                "yaw_pitch_roll_deg": self.ang.tolist()}

    @staticmethod
    def from_json(d):
        e = Extrinsics(d["axis_map_rows_are_camera_xyz_in_lidar_axes"], d["camera_position_m"])
        e.ang = np.array(d["yaw_pitch_roll_deg"], float)
        return e


class Intrinsics:
    def __init__(self, path):
        with open(path) as f:
            d = json.load(f)
        self.width = d["resolution"]["width"]
        self.height = d["resolution"]["height"]
        self.K = np.array(d["camera_matrix"], float)
        self.dist = np.array(d["distortion_coefficients"], float)
        self.camera_index = d.get("camera_index", 0)

    def scaled_to(self, w, h):
        if (w, h) == (self.width, self.height):
            return self.K, self.dist
        sx, sy = w / self.width, h / self.height
        K = self.K.copy()
        K[0, :] *= sx
        K[1, :] *= sy
        return K, self.dist


def project(pts_cam, K, dist, w, h, zmin=0.15):
    """pts_cam: (N,3) in camera frame. Returns (u, v, depth) for points that land in the image."""
    z = pts_cam[:, 2]
    x, y = pts_cam[:, 0], pts_cam[:, 1]
    ok = (z > zmin) & ((x * x + y * y) < 4.0 * z * z)   # in front, within ~63 deg of the axis
    p = pts_cam[ok]
    if len(p) == 0:
        return np.empty(0, int), np.empty(0, int), np.empty(0)
    uv, _ = cv2.projectPoints(p.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, dist)
    uv = uv.reshape(-1, 2)
    inside = (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
    uv, depth = uv[inside], p[inside, 2]
    return uv[:, 0], uv[:, 1], depth


def draw_dots(img, u, v, depth, near, far, radius):
    if len(u) == 0:
        return 0
    order = np.argsort(-depth)                 # far first so near points end up on top
    u, v, depth = u[order], v[order], depth[order]
    t = np.clip((depth - near) / max(far - near, 1e-6), 0, 1)
    colors = cv2.applyColorMap((255 * (1 - t)).astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO)
    colors = colors.reshape(-1, 3)
    h, w = img.shape[:2]
    ui, vi = np.round(u).astype(int), np.round(v).astype(int)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                img[np.clip(vi + dy, 0, h - 1), np.clip(ui + dx, 0, w - 1)] = colors
    return len(u)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------


def open_camera(index, width, height):
    backends = [cv2.CAP_DSHOW, cv2.CAP_ANY] if sys.platform.startswith("win") else [cv2.CAP_V4L2, cv2.CAP_ANY]
    for be in backends:
        cap = cv2.VideoCapture(index, be)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, _ = cap.read()
            if ok:
                return cap
            cap.release()
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _captures_dir():
    """Where this tool's own pictures and videos go: overlay_captures/ on the drive (not between the programs)."""
    import gimble_paths as gpaths
    d = os.path.join(gpaths.ROOT, "overlay_captures")
    os.makedirs(d, exist_ok=True)
    return d


def selftest():
    """Projects known camera-frame points, sends them through the inverse of the
    LiDAR->camera transform and back, and checks they hit the same pixels."""
    import gimble_paths as gpaths
    intr = Intrinsics(gpaths.setting("camera_intrinsics.json")) \
        if os.path.exists(gpaths.setting("camera_intrinsics.json")) else None
    if intr is None:
        K = np.array([[240, 0, 296], [0, 240, 216.5], [0, 0, 1.0]])
        dist = np.array([-0.0176, 0.018, 0.0002, 0.0006, -0.016])
    else:
        K, dist = intr.K, intr.dist
    rots = proper_rotations_24()
    assert len(rots) == 24 and all(abs(np.linalg.det(r) - 1) < 1e-9 for r in rots)
    M = axis_map("+z", "-x")
    assert np.allclose(M, np.diag([-1, -1, 1]))
    ext = Extrinsics(M, [0.0955, 0.0, 0.0])
    ext.ang = np.array([1.5, -0.8, 0.4])
    rng = np.random.default_rng(0)
    pc = np.column_stack([rng.uniform(-3, 3, 500), rng.uniform(-2, 2, 500), rng.uniform(1, 12, 500)])
    # build lidar points that the transform maps onto pc
    R = rot_adj(*ext.ang)
    pl = ((pc @ R) + ext.c) @ np.linalg.inv(M).T
    back = ext.to_camera(pl)
    assert np.allclose(back, pc, atol=1e-9), "transform round-trip failed"
    u, v, d = project(back, K, dist, 640, 480)
    u2, v2, d2 = project(pc, K, dist, 640, 480)
    assert np.allclose(u, u2) and len(u) > 50
    # a point straight ahead of the camera lands near the principal point
    uu, vv, _ = project(np.array([[0, 0, 5.0]]), K, dist, 640, 480)
    assert abs(uu[0] - K[0, 2]) < 1e-6 and abs(vv[0] - K[1, 2]) < 1e-6
    # baseline sanity: a point straight ahead of the LiDAR, camera 9.55 cm to its right,
    # must appear LEFT of the image center
    e2 = Extrinsics(M, [0.0955, 0, 0])
    uu, _, _ = project(e2.to_camera(np.array([[0, 0, 5.0]])), K, dist, 640, 480)
    assert uu[0] < K[0, 2] - 3
    # key semantics: positive yaw moves dots right, positive pitch up, positive roll clockwise
    e3 = Extrinsics(M, [0, 0, 0]); e3.ang = np.array([2.0, 0, 0])
    uu, _, _ = project(e3.to_camera(np.array([[0, 0, 5.0]])), K, dist, 640, 480)
    assert uu[0] > K[0, 2]
    e3.ang = np.array([0, 2.0, 0])
    _, vv, _ = project(e3.to_camera(np.array([[0, 0, 5.0]])), K, dist, 640, 480)
    assert vv[0] < K[1, 2]
    # drawing
    img = np.zeros((480, 640, 3), np.uint8)
    n = draw_dots(img, u, v, d, 1, 12, 2)
    assert n == len(u) and img.any()
    print("selftest passed: transform round-trip, baseline direction, key directions, drawing OK")


# ---------------------------------------------------------------------------
# On-screen controls
# ---------------------------------------------------------------------------

PANEL_W = 300
ROW_H = 26
PAD = 8
BG = (38, 38, 38)
BTN = (75, 75, 75)
BTN_HOVER = (110, 110, 110)
ON = (60, 160, 60)
TXT = (235, 235, 235)
DIM = (160, 160, 160)
HEAD = (255, 200, 90)


def _in(rect, x, y):
    x0, y0, x1, y1 = rect
    return x0 <= x < x1 and y0 <= y < y1


class Ui:
    """Tiny immediate-mode widget set drawn straight into the OpenCV canvas."""

    def __init__(self, x0):
        self.x0 = x0
        self.y = PAD
        self.items = []
        self.edit = None      # stepper item currently being typed into
        self.buf = ""
        self.fresh = False    # first keypress replaces the old value

    def _row(self, gap=0):
        r = (self.x0 + PAD, self.y, self.x0 + PANEL_W - PAD, self.y + ROW_H - 4)
        self.y += ROW_H + gap
        return r

    def note(self, text):
        r = self._row()
        self.items.append(dict(t="note", rect=r, text=text))

    def header(self, text):
        self.y += 4
        r = self._row()
        self.items.append(dict(t="head", rect=r, text=text))

    def buttons(self, specs):
        """specs: list of (label, fn, repeat). Equal-width buttons in one row."""
        r = self._row()
        n = len(specs)
        w = (r[2] - r[0] - 6 * (n - 1)) / n
        for i, (label, fn, rep) in enumerate(specs):
            x0 = int(r[0] + i * (w + 6))
            self.items.append(dict(t="btn", rect=(x0, r[1], int(x0 + w), r[3]), label=label,
                                   fn=fn, repeat=rep))

    def check(self, label, get, setter):
        r = self._row()
        self.items.append(dict(t="chk", rect=r, label=label, get=get, set=setter))

    def stepper(self, label, val, dec, inc, repeat=False, dec_label="-", inc_label="+",
                raw=None, setv=None):
        r = self._row()
        bw, vw = 30, 90
        irect = (r[2] - bw, r[1], r[2], r[3])
        drect = (r[2] - bw - vw - bw, r[1], r[2] - bw - vw, r[3])
        self.items.append(dict(t="step", rect=r, label=label, val=val, dec=dec, inc=inc,
                               drect=drect, irect=irect, repeat=repeat, dl=dec_label, il=inc_label,
                               raw=raw, setv=setv,
                               vrect=(drect[2], r[1], irect[0], r[3])))

    def hit(self, x, y):
        """Returns (fn, repeat, value_item) - value_item is set when the click was on a
        typeable number, so the caller can tell that apart from a button."""
        for it in self.items:
            if it["t"] == "btn" and _in(it["rect"], x, y):
                return it["fn"], it["repeat"], None
            if it["t"] == "chk" and _in(it["rect"], x, y):
                return (lambda it=it: it["set"](not it["get"]())), False, None
            if it["t"] == "step":
                if _in(it["drect"], x, y):
                    return it["dec"], it["repeat"], None
                if _in(it["irect"], x, y):
                    return it["inc"], it["repeat"], None
                if it["setv"] is not None and _in(it["vrect"], x, y):
                    return (lambda: None), False, it
        return None

    def draw(self, canvas, mouse):
        mx, my = mouse
        f = cv2.FONT_HERSHEY_SIMPLEX

        def box(rect, label, active=False):
            x0, y0, x1, y1 = rect
            col = ON if active else (BTN_HOVER if _in(rect, mx, my) else BTN)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), col, -1)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (20, 20, 20), 1)
            (tw, th), _ = cv2.getTextSize(label, f, 0.45, 1)
            cv2.putText(canvas, label, (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2),
                        f, 0.45, TXT, 1, cv2.LINE_AA)

        for it in self.items:
            x0, y0, x1, y1 = it["rect"]
            if it["t"] == "note":
                cv2.putText(canvas, it["text"], (x0, y1 - 6), f, 0.4, DIM, 1, cv2.LINE_AA)
            elif it["t"] == "head":
                cv2.putText(canvas, it["text"], (x0, y1 - 4), f, 0.5, HEAD, 1, cv2.LINE_AA)
                cv2.line(canvas, (x0, y1), (x1, y1), (90, 90, 90), 1)
            elif it["t"] == "btn":
                box(it["rect"], it["label"])
            elif it["t"] == "chk":
                on = it["get"]()
                cb = (x0, y0 + 2, x0 + 18, y0 + 20)
                cv2.rectangle(canvas, (cb[0], cb[1]), (cb[2], cb[3]),
                              ON if on else BTN_HOVER if _in(it["rect"], mx, my) else BTN, -1)
                cv2.rectangle(canvas, (cb[0], cb[1]), (cb[2], cb[3]), (200, 200, 200), 1)
                if on:
                    cv2.line(canvas, (cb[0] + 3, cb[1] + 9), (cb[0] + 7, cb[1] + 14), (255, 255, 255), 2)
                    cv2.line(canvas, (cb[0] + 7, cb[1] + 14), (cb[0] + 15, cb[1] + 4), (255, 255, 255), 2)
                cv2.putText(canvas, it["label"], (x0 + 26, y1 - 5), f, 0.48, TXT, 1, cv2.LINE_AA)
            elif it["t"] == "step":
                cv2.putText(canvas, it["label"], (x0, y1 - 5), f, 0.48, TXT, 1, cv2.LINE_AA)
                box(it["drect"], it["dl"])
                box(it["irect"], it["il"])
                vx0, vx1 = it["drect"][2], it["irect"][0]
                editing = self.edit is it
                if it["setv"] is not None:
                    vr = it["vrect"]
                    cv2.rectangle(canvas, (vr[0] + 2, vr[1]), (vr[2] - 2, vr[3]),
                                  (25, 25, 25) if editing else (48, 48, 48), -1)
                    cv2.rectangle(canvas, (vr[0] + 2, vr[1]), (vr[2] - 2, vr[3]),
                                  (0, 220, 255) if editing else (BTN_HOVER if _in(vr, mx, my) else (70, 70, 70)), 1)
                txt = (self.buf + "|") if editing else it["val"]()
                (tw, _), _ = cv2.getTextSize(txt, f, 0.45, 1)
                cv2.putText(canvas, txt, (vx0 + (vx1 - vx0 - tw) // 2, y1 - 5), f, 0.45,
                            (0, 220, 255) if editing else TXT if it["setv"] is not None else DIM, 1, cv2.LINE_AA)


class App:
    def __init__(self, args, hardware=True):
        self.args = args
        self.intr = Intrinsics(args.intrinsics)
        self.calib_idx = self.intr.camera_index
        self.cam_idx = args.camera if args.camera is not None else self.calib_idx
        self.rots = proper_rotations_24()
        sx = 1.0 if args.camera_side == "right" else -1.0
        default_c = [sx * args.baseline_in * IN_TO_M, args.down_in * IN_TO_M, args.forward_in * IN_TO_M]
        self.ext = Extrinsics(axis_map(args.forward_axis, args.right_axis), default_c)
        self.calib_note = "Alignment: defaults (no saved calibration)"
        if not args.fresh:
            self.load_calibration()
        self.base_c = self.ext.c.copy()
        self.axis_idx = next((i for i, r in enumerate(self.rots) if np.allclose(r, self.ext.M)), 0)
        # view state
        self.show_dots = True
        self.show_hud = True
        self.show_legend = True
        self.show_cross = False
        self.step = 0.25
        self.near, self.far = args.near, args.far
        self.dot = args.dot_size
        self.window_s = args.window
        self.running = True
        self.pending_cam = 0
        self.pending_cam_abs = None
        self.msg, self.msg_until = "", 0.0
        self.recording = None
        self.snapshot_req = False
        self.held = None
        self.mouse = (0, 0)
        self.cap = None
        self.receiver = None
        self.w, self.h = self.intr.width, self.intr.height
        self.K, self.dist = self.intr.K, self.intr.dist
        self.cam_fail = 0
        self.scale = args.scale
        self.ui = Ui(int(self.w * self.scale))
        self._build_ui()
        if hardware:
            self.cap = self._open(self.cam_idx)
            if self.cap is None:
                sys.exit(f"Couldn't open camera index {self.cam_idx}. Use the Camera < > buttons "
                         f"or pass --camera N.")
            try:
                from lidar_receiver import LidarReceiver
            except ImportError:
                from lidar_live_viewer import LidarReceiver
            self.receiver = LidarReceiver(args.local_ip, args.local_port, self.window_s)
            self.receiver.start()
            if args.record:
                self.toggle_record(args.record)

    # -- camera --
    def _open(self, idx):
        cap = open_camera(idx, self.intr.width, self.intr.height)
        if cap is None:
            return None
        ok, fr = cap.read()
        if not ok:
            cap.release()
            return None
        self.h, self.w = fr.shape[:2]
        self.K, self.dist = self.intr.scaled_to(self.w, self.h)
        self.cam_fail = 0
        return cap

    def _do_switch(self, delta):
        n = 10
        for k in range(1, n):
            idx = (self.cam_idx + delta * k) % n
            cap = self._open_probe(idx)
            if cap is not None:
                if self.cap is not None:
                    self.cap.release()
                self.cap, self.cam_idx = cap, idx
                self.flash(f"Camera {idx} ({self.w}x{self.h})")
                return
        self.flash("No other camera found")

    def _do_switch_to(self, idx):
        if idx == self.cam_idx:
            self.flash(f"Already on camera {idx}")
            return
        cap = self._open(idx)
        if cap is None:
            self.flash(f"Couldn't open camera {idx}")
            return
        if self.cap is not None:
            self.cap.release()
        self.cap, self.cam_idx = cap, idx
        self.flash(f"Camera {idx} ({self.w}x{self.h})")

    def _open_probe(self, idx):
        if idx == self.cam_idx and self.cap is not None:
            return None
        return self._open(idx)

    # -- actions --
    def flash(self, text, secs=2.5):
        self.msg, self.msg_until = text, time.time() + secs

    def ang(self, i, s):
        self.ext.ang[i] += s * self.step

    def off(self, i, s):
        self.ext.c[i] += s * 0.002

    def cycle_axes(self, d):
        self.axis_idx = (self.axis_idx + d) % 24
        self.ext.M = self.rots[self.axis_idx]

    def bump(self, name, d, lo, hi):
        setattr(self, name, float(np.clip(getattr(self, name) + d, lo, hi)))

    def reset(self):
        self.ext.ang[:] = 0
        self.ext.c = self.base_c.copy()
        self.flash("Fine adjustments reset")

    def load_calibration(self, announce=False):
        """Load lidar_camera_extrinsics.json (from calibrate_lidar_camera.py or a manual 'Save align')."""
        path = self.args.extrinsics
        if not os.path.exists(path):
            if announce:
                self.flash("No saved calibration found")
            return False
        try:
            with open(path) as f:
                d = json.load(f)
            self.ext = Extrinsics.from_json(d)
        except (OSError, KeyError, ValueError) as e:
            print(f"[warn] couldn't read {path}: {e}")
            if announce:
                self.flash("Couldn't read saved calibration")
            return False
        self.base_c = self.ext.c.copy()
        self.axis_idx = next((i for i, r in enumerate(self.rots) if np.allclose(r, self.ext.M)), 0)
        c = d.get("calibration")
        if c:
            sr, st = max(c.get("sigma_rot_deg", [0])), max(c.get("sigma_t_mm", [0]))
            self.calib_note = (f"Calibrated {c.get('saved', '')[:10]}: {c.get('views', '?')} views, "
                               f"+/-{sr:.1f} deg, +/-{st:.0f} mm")
        else:
            self.calib_note = "Alignment: saved by hand (no auto-calibration)"
        print(f"Loaded extrinsics from {path}  [{self.calib_note}]")
        if announce:
            self.flash("Reloaded saved calibration")
        return True

    def save(self):
        self.calib_note = "Alignment: saved by hand (no auto-calibration)"
        with open(self.args.extrinsics, "w") as f:
            json.dump(self.ext.to_json(), f, indent=2)
        self.flash(f"Saved {os.path.basename(self.args.extrinsics)}")
        print(f"Saved extrinsics to {self.args.extrinsics}")

    def toggle_record(self, path=None):
        if self.recording is not None:
            self.recording.release()
            self.recording = None
            self.flash("Recording stopped")
        else:
            path = path if isinstance(path, str) else os.path.join(
                _captures_dir(), time.strftime("overlay_%Y%m%d_%H%M%S.mp4"))
            self.recording = (path, None)
            self.flash(f"Recording to {os.path.basename(path)}")

    # typed-value setters
    def set_ang(self, i, v):
        self.ext.ang[i] = float(np.clip(v, -180.0, 180.0))

    def set_shift_mm(self, i, mm):
        self.ext.c[i] = self.base_c[i] - mm / 1000.0     # positive = dots move right / up

    def set_depth_mm(self, mm):
        self.ext.c[2] = self.base_c[2] + mm / 1000.0

    def set_axis(self, v):
        self.axis_idx = int(np.clip(round(v), 1, 24)) - 1
        self.ext.M = self.rots[self.axis_idx]

    def set_clamped(self, name, lo, hi):
        return lambda v: setattr(self, name, float(np.clip(v, lo() if callable(lo) else lo,
                                                            hi() if callable(hi) else hi)))

    # -- typing into number fields --
    def start_edit(self, it):
        if self.ui.edit is it:
            return
        if self.ui.edit is not None:
            self.commit_edit()
        v = it["raw"]()
        self.ui.edit = it
        self.ui.buf = (f"{v:.3f}".rstrip("0").rstrip(".") or "0")
        self.ui.fresh = True

    def commit_edit(self):
        it, buf = self.ui.edit, self.ui.buf
        self.ui.edit = None
        if it is None:
            return False
        try:
            v = float(buf)
        except ValueError:
            self.flash(f"Not a number: '{buf}'")
            return False
        it["setv"](v)
        return True

    def edit_key(self, k):
        ui = self.ui
        if k == 27:                                   # Esc
            ui.edit = None
        elif k in (13, 10):                           # Enter
            self.commit_edit()
        elif k == 9:                                  # Tab -> apply, jump to next field
            cur = ui.edit
            self.commit_edit()
            fields = [i for i in ui.items if i["t"] == "step" and i["setv"] is not None]
            if cur in fields:
                self.start_edit(fields[(fields.index(cur) + 1) % len(fields)])
        elif k == 8:                                  # Backspace
            ui.buf = "" if ui.fresh else ui.buf[:-1]
            ui.fresh = False
        elif 0 < k < 128 and chr(k) in "0123456789.-+":
            if ui.fresh:
                ui.buf, ui.fresh = "", False
            ui.buf += chr(k)

    def set_attr(self, name):
        return lambda v: setattr(self, name, v)

    # -- panel --
    def _build_ui(self):
        u = self.ui
        u.header("Camera")
        u.note("Click a number to type it (Enter / Tab / Esc)")
        u.stepper("Camera", lambda: f"#{self.cam_idx}",
                  lambda: setattr(self, "pending_cam", -1), lambda: setattr(self, "pending_cam", 1),
                  dec_label="<", inc_label=">", raw=lambda: self.cam_idx,
                  setv=lambda v: setattr(self, "pending_cam_abs", max(0, int(round(v)))))
        u.header("Display")
        u.check("LiDAR dots", lambda: self.show_dots, self.set_attr("show_dots"))
        u.check("Status text", lambda: self.show_hud, self.set_attr("show_hud"))
        u.check("Color legend", lambda: self.show_legend, self.set_attr("show_legend"))
        u.check("Center crosshair", lambda: self.show_cross, self.set_attr("show_cross"))
        u.check("Record video", lambda: self.recording is not None, lambda v: self.toggle_record())
        u.buttons([("Snapshot", lambda: setattr(self, "snapshot_req", True), False),
                   ("Save align", self.save, False),
                   ("Reset", self.reset, False)])
        u.buttons([("Reload calibration", lambda: self.load_calibration(True), False)])
        u.header("Alignment (buttons move the dots)")
        u.stepper("Axes", lambda: f"{self.axis_idx + 1}/24",
                  lambda: self.cycle_axes(-1), lambda: self.cycle_axes(1), dec_label="<", inc_label=">",
                  raw=lambda: self.axis_idx + 1, setv=self.set_axis)
        u.stepper("Yaw", lambda: f"{self.ext.ang[0]:+.2f}", lambda: self.ang(0, -1),
                  lambda: self.ang(0, 1), True, "<", ">",
                  raw=lambda: self.ext.ang[0], setv=lambda v: self.set_ang(0, v))
        u.stepper("Pitch", lambda: f"{self.ext.ang[1]:+.2f}", lambda: self.ang(1, -1),
                  lambda: self.ang(1, 1), True, "v", "^",
                  raw=lambda: self.ext.ang[1], setv=lambda v: self.set_ang(1, v))
        u.stepper("Roll", lambda: f"{self.ext.ang[2]:+.2f}", lambda: self.ang(2, -1),
                  lambda: self.ang(2, 1), True, "cc", "cw",
                  raw=lambda: self.ext.ang[2], setv=lambda v: self.set_ang(2, v))
        u.stepper("Step", lambda: f"{self.step:.2f} deg",
                  lambda: setattr(self, "step", max(0.05, self.step / 2)),
                  lambda: setattr(self, "step", min(2.0, self.step * 2)),
                  raw=lambda: self.step, setv=self.set_clamped("step", 0.01, 10.0))
        u.stepper("Shift L/R", lambda: f"{-self.ext.c[0]*1000 + self.base_c[0]*1000:+.0f} mm",
                  lambda: self.off(0, 1), lambda: self.off(0, -1), True, "<", ">",
                  raw=lambda: (self.base_c[0] - self.ext.c[0]) * 1000, setv=lambda v: self.set_shift_mm(0, v))
        u.stepper("Shift U/D", lambda: f"{-self.ext.c[1]*1000 + self.base_c[1]*1000:+.0f} mm",
                  lambda: self.off(1, -1), lambda: self.off(1, 1), True, "v", "^",
                  raw=lambda: (self.base_c[1] - self.ext.c[1]) * 1000, setv=lambda v: self.set_shift_mm(1, v))
        u.stepper("Depth", lambda: f"{self.ext.c[2]*1000 - self.base_c[2]*1000:+.0f} mm",
                  lambda: self.off(2, -1), lambda: self.off(2, 1), True,
                  raw=lambda: (self.ext.c[2] - self.base_c[2]) * 1000, setv=self.set_depth_mm)
        u.header("LiDAR display")
        u.stepper("Window", lambda: f"{self.window_s:.2f} s",
                  lambda: self.bump("window_s", -0.05, 0.05, 3.0), lambda: self.bump("window_s", 0.05, 0.05, 3.0),
                  True, raw=lambda: self.window_s, setv=self.set_clamped("window_s", 0.05, 3.0))
        u.stepper("Near", lambda: f"{self.near:.1f} m",
                  lambda: self.bump("near", -0.5, 0.0, self.far - 0.5),
                  lambda: self.bump("near", 0.5, 0.0, self.far - 0.5), True,
                  raw=lambda: self.near, setv=self.set_clamped("near", 0.0, lambda: self.far - 0.1))
        u.stepper("Far", lambda: f"{self.far:.1f} m",
                  lambda: self.bump("far", -0.5, self.near + 0.5, 60.0),
                  lambda: self.bump("far", 0.5, self.near + 0.5, 60.0), True,
                  raw=lambda: self.far, setv=self.set_clamped("far", lambda: self.near + 0.1, 200.0))
        u.stepper("Dot size", lambda: f"{self.dot}px",
                  lambda: setattr(self, "dot", max(1, self.dot - 1)),
                  lambda: setattr(self, "dot", min(6, self.dot + 1)),
                  raw=lambda: self.dot, setv=lambda v: setattr(self, "dot", int(np.clip(round(v), 1, 6))))
        u.buttons([("Quit", lambda: setattr(self, "running", False), False)])
        self.panel_h = u.y + PAD

    def on_mouse(self, event, x, y, flags, _):
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = self.ui.hit(x, y)
            item = hit[2] if hit else None
            if self.ui.edit is not None and item is not self.ui.edit:
                self.commit_edit()            # clicking elsewhere applies what was typed
            if item is not None:
                self.start_edit(item)
            elif hit:
                fn, rep, _ = hit
                fn()
                if rep:
                    self.held = (fn, time.time() + 0.4)
        elif event == cv2.EVENT_LBUTTONUP:
            self.held = None

    def compose(self, img):
        """Video image (already scaled) + panel -> full canvas."""
        H = max(img.shape[0], self.panel_h)
        canvas = np.full((H, img.shape[1] + PANEL_W, 3), BG, np.uint8)
        canvas[:img.shape[0], :img.shape[1]] = img
        self.ui.x0 = img.shape[1]
        self.ui.draw(canvas, self.mouse)
        return canvas

    # -- frame --
    def render_video(self, frame, pts):
        sc = self.scale
        img = cv2.resize(frame, None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR) if sc != 1.0 \
            else frame.copy()
        n = 0
        if self.show_dots and pts is not None and len(pts):
            u, v, d = project(self.ext.to_camera(pts[:, :3]), self.K, self.dist, self.w, self.h)
            n = draw_dots(img, u * sc, v * sc, d, self.near, self.far, self.dot)
        if self.show_cross:
            cx, cy = int(self.K[0, 2] * sc), int(self.K[1, 2] * sc)
            cv2.line(img, (cx - 14, cy), (cx + 14, cy), (255, 255, 255), 1, cv2.LINE_AA)
            cv2.line(img, (cx, cy - 14), (cx, cy + 14), (255, 255, 255), 1, cv2.LINE_AA)
        if self.show_legend:
            self._legend(img)
        return img, n

    def _legend(self, img):
        h, w = img.shape[:2]
        bx, by, bw, bh = w - 30, 60, 14, min(220, h - 120)
        ramp = cv2.applyColorMap(np.linspace(255, 0, bh).astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO)
        img[by:by + bh, bx:bx + bw] = ramp.reshape(bh, 1, 3)
        cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (255, 255, 255), 1)
        for txt, yy in ((f"{self.near:.1f}m", by + 10), (f"{self.far:.0f}m", by + bh)):
            cv2.putText(img, txt, (bx - 44, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, txt, (bx - 44, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

    def hud_lines(self, fps, n, pkt_rate):
        lines = [f"cam #{self.cam_idx} {self.w}x{self.h} | {fps:4.1f} fps | {n} dots | LiDAR {pkt_rate:.0f} pkt/s",
                 f"yaw {self.ext.ang[0]:+.2f} pitch {self.ext.ang[1]:+.2f} roll {self.ext.ang[2]:+.2f} deg",
                 self.calib_note]
        if self.cam_idx != self.calib_idx:
            lines.append(f"! intrinsics were calibrated for camera #{self.calib_idx}")
        if pkt_rate < 1:
            lines.append("NO LIDAR DATA - powered / streaming to this PC?")
        if time.time() < self.msg_until:
            lines.append(self.msg)
        return lines

    def run(self):
        win = "LiDAR on camera"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, self.on_mouse)
        t_fps, n_fps, fps = time.time(), 0, 0.0
        last_pkts, last_t, pkt_rate = 0, time.time(), 0.0
        frame = np.zeros((self.h, self.w, 3), np.uint8)
        print("Running. Use the panel on the right of the window (keyboard shortcuts in the file header).")
        try:
            while self.running:
                ok, fr = self.cap.read()
                if ok:
                    frame, self.cam_fail = fr, 0
                else:
                    self.cam_fail += 1
                    frame = np.zeros((self.h, self.w, 3), np.uint8)
                self.receiver.window_seconds = self.window_s
                pts = self.receiver.snapshot()
                img, n = self.render_video(frame, pts)
                if self.cam_fail > 5:
                    cv2.putText(img, "Camera not delivering frames - try Camera < >", (10, img.shape[0] // 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
                if self.pending_cam or self.pending_cam_abs is not None:
                    cv2.putText(img, "Switching camera...", (10, img.shape[0] // 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)

                now = time.time()
                n_fps += 1
                if now - t_fps >= 1.0:
                    fps, n_fps, t_fps = n_fps / (now - t_fps), 0, now
                if now - last_t >= 1.0:
                    pkt_rate = (self.receiver.packets_received - last_pkts) / (now - last_t)
                    last_pkts, last_t = self.receiver.packets_received, now

                clean = img.copy()   # what gets recorded / snapshotted: video + dots, no text
                if self.show_hud:
                    for i, line in enumerate(self.hud_lines(fps, n, pkt_rate)):
                        cv2.putText(img, line, (8, 18 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(img, line, (8, 18 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                    (255, 255, 255), 1, cv2.LINE_AA)
                elif now < self.msg_until:
                    cv2.putText(img, self.msg, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (255, 255, 255), 1, cv2.LINE_AA)
                if self.recording is not None:
                    path, wr = self.recording
                    if wr is None:
                        wr = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 20,
                                             (clean.shape[1], clean.shape[0]))
                        self.recording = (path, wr)
                    wr.write(clean)
                    cv2.circle(img, (img.shape[1] - 20, 20), 7, (0, 0, 255), -1)
                if self.snapshot_req:
                    self.snapshot_req = False
                    p = os.path.join(_captures_dir(), time.strftime("overlay_%Y%m%d_%H%M%S.png"))
                    cv2.imwrite(p, clean)
                    self.flash(f"Saved {os.path.basename(p)}")

                cv2.imshow(win, self.compose(img))
                k = cv2.waitKey(1) & 0xFF
                if self.held and time.time() >= self.held[1]:
                    self.held[0]()
                    self.held = (self.held[0], time.time() + 0.07)
                self.key(k)
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if self.pending_cam:
                    d, self.pending_cam = self.pending_cam, 0
                    self._do_switch(d)
                if self.pending_cam_abs is not None:
                    i, self.pending_cam_abs = self.pending_cam_abs, None
                    self._do_switch_to(i)
        finally:
            self.receiver.stop()
            self.cap.release()
            if self.recording is not None and self.recording[1] is not None:
                self.recording[1].release()
            cv2.destroyAllWindows()

    def key(self, k):
        if k in (255, 0):
            return
        if self.ui.edit is not None:
            self.edit_key(k)
            return
        c = chr(k) if 0 < k < 128 else ""
        if k == 27 or c == "q":
            self.running = False
        elif c == "j": self.ang(0, -1)
        elif c == "l": self.ang(0, 1)
        elif c == "i": self.ang(1, 1)
        elif c == "k": self.ang(1, -1)
        elif c == "u": self.ang(2, -1)
        elif c == "o": self.ang(2, 1)
        elif c == "a": self.off(0, 1)
        elif c == "d": self.off(0, -1)
        elif c == "w": self.off(1, 1)
        elif c == "s": self.off(1, -1)
        elif c == "r": self.off(2, 1)
        elif c == "f": self.off(2, -1)
        elif c == "n": self.cycle_axes(1)
        elif c == "N": self.cycle_axes(-1)
        elif c == "c": self.pending_cam = 1
        elif c == "C": self.pending_cam = -1
        elif c == ",": self.step = max(0.05, self.step / 2)
        elif c == ".": self.step = min(2.0, self.step * 2)
        elif c == "[": self.bump("window_s", -0.05, 0.05, 3.0)
        elif c == "]": self.bump("window_s", 0.05, 0.05, 3.0)
        elif c == "-": self.bump("far", -0.5, self.near + 0.5, 60.0)
        elif c == "=": self.bump("far", 0.5, self.near + 0.5, 60.0)
        elif c == "g": self.show_dots = not self.show_dots
        elif c == "v": self.toggle_record()
        elif c == "0": self.reset()
        elif c == "p": self.save()
        elif c == "b": self.load_calibration(True)
        elif k == 32: self.snapshot_req = True


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    import gimble_paths as gpaths
    ap.add_argument("--intrinsics", default=gpaths.setting("camera_intrinsics.json"))
    ap.add_argument("--extrinsics", default=gpaths.setting("lidar_camera_extrinsics.json"))
    ap.add_argument("--fresh", action="store_true", help="Ignore any saved extrinsics file")
    ap.add_argument("--camera", type=int, default=None,
                    help="Camera index to start on (default: the one used in camera_intrinsics.json)")
    ap.add_argument("--baseline-in", type=float, default=3.76,
                    help="Horizontal LiDAR-to-camera separation in inches")
    ap.add_argument("--camera-side", choices=["right", "left"], default="right",
                    help="Which side of the LiDAR the camera is on, looking from behind the rig")
    ap.add_argument("--down-in", type=float, default=0.0,
                    help="Camera height BELOW the LiDAR's center, inches (negative = above)")
    ap.add_argument("--forward-in", type=float, default=0.0,
                    help="Camera distance IN FRONT of the LiDAR's center, inches (negative = behind)")
    ap.add_argument("--forward-axis", choices=list(AXIS_VECS), default="+z")
    ap.add_argument("--right-axis", choices=list(AXIS_VECS), default="-x")
    ap.add_argument("--local-ip", default="0.0.0.0")
    ap.add_argument("--local-port", type=int, default=6201)
    ap.add_argument("--window", type=float, default=0.5, help="Seconds of LiDAR scan to accumulate")
    ap.add_argument("--near", type=float, default=0.5)
    ap.add_argument("--far", type=float, default=8.0)
    ap.add_argument("--dot-size", type=int, default=2, help="Dot radius in pixels")
    ap.add_argument("--scale", type=float, default=1.5, help="Video upscale factor")
    ap.add_argument("--record", default=None, help="Start recording to this file immediately")
    ap.add_argument("--selftest", action="store_true")
    return ap


def main():
    args = build_parser().parse_args()
    if args.selftest:
        selftest()
        return
    App(args).run()


if __name__ == "__main__":
    main()
