#!/usr/bin/env python3
"""
gimble_pi.py - the whole LiDAR + camera pipeline on the Raspberry Pi (touchscreen friendly).

What it does
------------
  * Shows the live USB-camera picture with the LiDAR dots drawn on it (using the saved
    calibration in lidar_camera_extrinsics.json and the lens model in camera_intrinsics.json).
  * REC saves a training dataset: for every sample a camera image plus a metric depth map
    made from the LiDAR (and optionally the raw LiDAR points), so a vision-only depth model
    can be trained to predict what the LiDAR measures.
  * CALIB runs the wall-target calibration (the four ArUco squares) right on the Pi.

Buttons (right-hand panel, all big enough for a finger)
-------------------------------------------------------
  Live screen:   REC / STOP   SNAP   DOTS   RANGE   CALIB   CAM   QUIT (tap twice)
  Calib screen:  CAPTURE   UNDO   AUTO   DOTS   SAVE   BACK
Keyboard (optional):  r rec/stop, s snap, d dots, m range (type min / max in metres), c calibrate, q quit.
RANGE: only LiDAR points between min and max metres are drawn and written into the depth maps; the colours
span that range. The raw LiDAR .npz always keeps every point. The setting is remembered (gimble_settings.json).

Where files go: next to this script (so on the USB drive itself):
    dataset/<date_time>/images/000001.jpg      camera frame (raw, as the camera delivered it)
    dataset/<date_time>/depth/000001.png       16-bit PNG, depth in millimetres, 0 = no LiDAR return
                                               (looks almost black in a normal image viewer - that is normal)
    dataset/<date_time>/depth_vis/000001.jpg   the same depth as coloured dots on the dimmed picture, for looking at
    dataset/<date_time>/lidar/000001.npz       raw LiDAR points x,y,z,intensity (LiDAR frame, metres)
    dataset/<date_time>/index.csv, meta.json   timestamps, camera model, extrinsics, settings
Depth is the z-distance along the camera's optical axis (what depth-estimation networks predict)
in the same pixel grid as the raw image. Use view_dataset.py to page through a session.

Run:  python3 gimble_pi.py            (see README_PI.md for one-time setup)
"""
import argparse
import csv
import datetime
import json
import os
import queue
import shutil
import sys
import threading
import time

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("OpenCV missing: sudo apt install -y python3-opencv")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimble_paths as gpaths  # noqa: E402   (where the settings, recordings, model and log are on the drive)

from lidar_camera_overlay import Extrinsics, Intrinsics, draw_dots, project, rot_adj  # noqa: E402
from lidar_receiver import LidarReceiver  # noqa: E402

PANEL_W = 118
BTN_H = 50           # button height (px) - compact but still fine for a finger
DEFAULT_RANGE = (0.15, 10.0)   # metres: LiDAR points outside this are not drawn / not put in depth maps
BTN_BG = (70, 70, 70)
BTN_ON = (60, 140, 60)
BTN_RED = (40, 40, 200)
BTN_WARN = (0, 130, 220)
TXT = (255, 255, 255)


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(gpaths.LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def shadow_text(img, text, org, scale=0.55, color=TXT, thick=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Dataset writer (background thread so saving never freezes the picture)
# ---------------------------------------------------------------------------


def depth_vis(frame, depth_mm, background=0.45, near=0.5, far=6.0):
    """Human-viewable depth: the picture dimmed, with each LiDAR return drawn as a coloured 3x3 dot.
    (The real depth PNG is 16-bit millimetres, so image viewers show it as almost black.)"""
    img = (frame.astype(np.float32) * background).astype(np.uint8)
    vi, ui = np.nonzero(depth_mm)
    if len(vi):
        z = depth_mm[vi, ui] / 1000.0
        t = np.clip((z - near) / (far - near), 0, 1)
        col = cv2.applyColorMap((255 * (1 - t)).astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(-1, 3)
        order = np.argsort(-z)
        h, w = depth_mm.shape
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                img[np.clip(vi[order] + dy, 0, h - 1), np.clip(ui[order] + dx, 0, w - 1)] = col[order]
    return img


class SessionWriter:
    def __init__(self, root, meta, save_points, rng=(0.5, 6.0)):
        self.rng = rng
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(root, stamp)
        for sub in ("images", "depth", "depth_vis", "lidar"):
            os.makedirs(os.path.join(self.dir, sub), exist_ok=True)
        with open(os.path.join(self.dir, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        self.csv_f = open(os.path.join(self.dir, "index.csv"), "w", newline="")
        self.csv = csv.writer(self.csv_f)
        self.csv.writerow(["idx", "time_unix", "image", "depth", "lidar", "lidar_points_total",
                           "depth_pixels", "sharpness"])
        self.save_points = save_points
        self.q = queue.Queue(maxsize=40)
        self.count = 0
        self.dropped = 0
        self.t0 = time.time()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    def add(self, t, frame, depth_mm, pts, n_depth, sharp):
        self.count += 1
        item = (self.count, t, frame, depth_mm, pts, n_depth, sharp)
        try:
            self.q.put_nowait(item)
        except queue.Full:
            self.dropped += 1
            self.count -= 1

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                break
            i, t, frame, depth, pts, n_depth, sharp = item
            try:
                name = f"{i:06d}"
                cv2.imwrite(os.path.join(self.dir, "images", name + ".jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                cv2.imwrite(os.path.join(self.dir, "depth", name + ".png"), depth)
                cv2.imwrite(os.path.join(self.dir, "depth_vis", name + ".jpg"), depth_vis(frame, depth, near=self.rng[0], far=self.rng[1]),
                            [cv2.IMWRITE_JPEG_QUALITY, 90])
                lid = ""
                if self.save_points:
                    lid = f"lidar/{name}.npz"
                    np.savez_compressed(os.path.join(self.dir, lid), points=pts.astype(np.float32))
                self.csv.writerow([i, f"{t:.4f}", f"images/{name}.jpg", f"depth/{name}.png", lid,
                                   len(pts), n_depth, f"{sharp:.1f}"])
                self.csv_f.flush()
            except OSError as e:
                log(f"write error: {e}")

    def close(self):
        self.q.put(None)
        self._th.join(timeout=10)
        try:
            self.csv_f.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class Button:
    def __init__(self, key, rect):
        self.key, self.rect = key, rect


class App:
    def __init__(self, args):
        self.args = args
        self.intr = Intrinsics(args.intrinsics)
        self.K, self.dist = self.intr.K, self.intr.dist
        self.w, self.h = self.intr.width, self.intr.height
        sw, sh = (int(v) for v in args.screen.lower().split("x"))
        self.sw, self.sh = sw, sh
        self.scale = min((sw - PANEL_W) / self.w, sh / self.h)
        self.vw, self.vh = int(self.w * self.scale), int(self.h * self.scale)
        self.vx = (sw - PANEL_W - self.vw) // 2
        self.vy = (sh - self.vh) // 2
        self.mode = "live"
        self.running = True
        self.show_dots = True
        self.cap = None
        self.cam_idx = args.camera
        self.cam_try_t = 0.0
        self.frame = None
        self.frame_t = 0.0
        self.rx = None
        self.msg, self.msg_until = "", 0.0
        self.quit_armed = 0.0
        self.writer = None
        self.rec = False
        self.next_sample = 0.0
        self.session_root = os.path.join(gpaths.ROOT, args.data_dir)
        self.cal = None
        self.pending_calib = args.calibrate
        self.last_depth_px = None
        self.last_lidar_pts = 0
        self.mouse = (0, 0)
        self.settings_path = gpaths.setting("gimble_settings.json")
        self.rmin, self.rmax = DEFAULT_RANGE
        try:
            with open(self.settings_path) as f:
                st = json.load(f)
            self.rmin, self.rmax = float(st["range_min_m"]), float(st["range_max_m"])
        except (OSError, ValueError, KeyError):
            pass
        if args.range_min is not None:
            self.rmin = args.range_min
        if args.range_max is not None:
            self.rmax = args.range_max
        if not (0 <= self.rmin < self.rmax):
            self.rmin, self.rmax = DEFAULT_RANGE
        self.edit = None            # range-entry dialog state while open
        self.load_extrinsics()
        self.layout_buttons()

    # ---- setup ----
    def flash(self, text, secs=3.0):
        self.msg, self.msg_until = text, time.time() + secs
        log(text)

    def load_extrinsics(self):
        path = self.args.extrinsics
        self.calib_note = "NOT CALIBRATED - using default axes"
        ext = Extrinsics(np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1.0]]), [0.0955, 0.0, 0.0])
        self.ext_json = None
        if os.path.exists(path):
            try:
                with open(path) as f:
                    d = json.load(f)
                ext = Extrinsics.from_json(d)
                self.ext_json = d
                c = d.get("calibration")
                self.calib_note = (f"Calibrated {c['saved'][:10]}, {c['views']} views" if c
                                   else "Alignment saved by hand")
            except (OSError, KeyError, ValueError) as e:
                log(f"couldn't read {path}: {e}")
        Radj = rot_adj(*ext.ang)
        self.R = Radj @ ext.M
        self.t = -Radj @ ext.c

    def start_lidar(self):
        try:
            self.rx = LidarReceiver(self.args.local_ip, self.args.local_port, 0.3)
            self.rx.start()
        except OSError as e:
            self.rx = None
            self.flash(f"LiDAR socket error: {e}", 8)

    def open_cam(self, idx):
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, fr = cap.read()
        if not ok or fr is None:
            cap.release()
            return None
        if fr.shape[1] != self.w or fr.shape[0] != self.h:
            self.flash(f"Camera gives {fr.shape[1]}x{fr.shape[0]}, calibration is for {self.w}x{self.h}", 8)
        return cap

    def find_cam(self, start=None, skip=None):
        order = [start] if start is not None else list(range(0, 16))
        for idx in order:
            if idx == skip:
                continue
            cap = self.open_cam(idx)
            if cap is not None:
                return cap, idx
        return None, None

    def next_cam(self):
        cur = self.cam_idx if self.cam_idx is not None else -1
        for k in range(1, 17):
            idx = (cur + k) % 16
            if idx == cur:
                continue
            cap = self.open_cam(idx)
            if cap is not None:
                if self.cap is not None:
                    self.cap.release()
                self.cap, self.cam_idx = cap, idx
                self.flash(f"Camera /dev/video{idx}")
                return
        self.flash("No other camera found")

    # ---- buttons ----
    def layout_buttons(self):
        self.live_keys = ["rec", "snap", "dots", "range", "calib", "cam", "quit"]
        self.calib_keys = ["capture", "undo", "auto", "dots", "save", "back"]
        self.rects = {}
        n = len(self.live_keys)
        bh = min(BTN_H + 8, self.sh // n)
        x0 = self.sw - PANEL_W
        self.btn_rects = [(x0 + 5, i * bh + 4, self.sw - 5, i * bh + 4 + bh - 8) for i in range(n)]

    def keys(self):
        return self.live_keys if self.mode == "live" else self.calib_keys

    def label_for(self, key):
        c = self.cal
        if key == "rec":
            return ("STOP", BTN_RED) if self.rec else ("REC", BTN_BG)
        if key == "snap":
            return "SNAP", BTN_BG
        if key == "dots":
            return ("DOTS on", BTN_ON) if self.show_dots else ("DOTS off", BTN_BG)
        if key == "range":
            return f"{self.rmin:g}-{self.rmax:g} m", BTN_BG
        if key == "calib":
            return "CALIBRATE", BTN_BG
        if key == "cam":
            return f"CAM {self.cam_idx if self.cam_idx is not None else '?'}", BTN_BG
        if key == "quit":
            return ("TAP AGAIN", BTN_WARN) if time.time() < self.quit_armed else ("QUIT", BTN_BG)
        if key == "capture":
            busy = c is not None and c.cap_state is not None
            return ("CAPTURING" if busy else "CAPTURE"), (BTN_WARN if busy else BTN_ON)
        if key == "undo":
            return "UNDO", BTN_BG
        if key == "auto":
            return ("AUTO on", BTN_ON) if (c and c.auto) else ("AUTO off", BTN_BG)
        if key == "save":
            ok = c is not None and c.est is not None
            return "SAVE", (BTN_ON if ok else BTN_BG)
        if key == "back":
            return "BACK", BTN_BG
        return key, BTN_BG

    def press(self, key):
        c = self.cal
        if key == "rec":
            self.stop_rec() if self.rec else self.start_rec()
        elif key == "snap":
            self.snap()
        elif key == "dots":
            self.show_dots = not self.show_dots
            if c:
                c.show_dots = self.show_dots
        elif key == "range":
            self.open_range_dialog()
        elif key == "calib":
            self.enter_calib()
        elif key == "cam":
            self.next_cam()
        elif key == "quit":
            if time.time() < self.quit_armed:
                self.running = False
            else:
                self.quit_armed = time.time() + 3
        elif key == "capture":
            c.start_capture()
        elif key == "undo":
            c.undo()
        elif key == "auto":
            c.auto = not c.auto
        elif key == "save":
            c.save_extrinsics()
        elif key == "back":
            self.exit_calib()

    def on_mouse(self, event, x, y, flags, _):
        self.mouse = (x, y)
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if self.edit is not None:
            for i, (x0, y0, x1, y1) in enumerate(self.edit["rects"]):
                if x0 <= x <= x1 and y0 <= y <= y1:
                    self.edit["sel"], self.edit["fresh"] = i, True
            return
        for key, (x0, y0, x1, y1) in zip(self.keys(), self.btn_rects):
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.press(key)
                return

    def on_key(self, k):
        if k in (255, 0xFF) or k < 0:
            return
        ch = chr(k) if 0 < k < 128 else ""
        if self.edit is not None:
            self.edit_key(k, ch)
            return
        if self.mode == "live":
            m = {"r": "rec", "s": "snap", "d": "dots", "m": "range", "c": "calib", "q": "quit"}
        else:
            m = {" ": "capture", "u": "undo", "a": "auto", "d": "dots", "s": "save", "q": "back"}
        if k == 27:
            self.press("quit" if self.mode == "live" else "back")
        elif ch in m:
            if ch == "q" and self.mode == "live":
                self.running = False
            else:
                self.press(m[ch])

    # ---- range entry ----
    def open_range_dialog(self):
        self.edit = dict(vals=[f"{self.rmin:g}", f"{self.rmax:g}"], sel=0, fresh=True, rects=[(0, 0, 0, 0)] * 2)

    def edit_key(self, k, ch):
        e = self.edit
        if k == 27:
            self.edit = None
        elif k in (13, 10):
            try:
                lo, hi = float(e["vals"][0]), float(e["vals"][1])
            except ValueError:
                self.flash("Type numbers in metres, e.g. 0.2 and 15", 3)
                return
            if not (0 <= lo < hi <= 200):
                self.flash("Need 0 <= min < max <= 200 m", 3)
                return
            self.rmin, self.rmax = lo, hi
            try:
                with open(self.settings_path, "w") as f:
                    json.dump({"range_min_m": lo, "range_max_m": hi}, f)
            except OSError:
                pass
            self.edit = None
            self.flash(f"Dot range set to {lo:g} - {hi:g} m", 3)
        elif k == 9:
            e["sel"], e["fresh"] = 1 - e["sel"], True
        elif k in (8, 127):
            e["vals"][e["sel"]] = "" if e["fresh"] else e["vals"][e["sel"]][:-1]
            e["fresh"] = False
        elif ch and (ch.isdigit() or ch == "."):
            e["vals"][e["sel"]] = (ch if e["fresh"] else e["vals"][e["sel"]] + ch)[:8]
            e["fresh"] = False

    def draw_range_dialog(self, canvas):
        e = self.edit
        bw, bh = 330, 170
        x0 = max((self.sw - PANEL_W - bw) // 2, 4)
        y0 = max((self.sh - bh) // 2, 4)
        cv2.rectangle(canvas, (x0, y0), (x0 + bw, y0 + bh), (40, 40, 40), -1)
        cv2.rectangle(canvas, (x0, y0), (x0 + bw, y0 + bh), (200, 200, 200), 1)
        shadow_text(canvas, "Dot range (metres)", (x0 + 14, y0 + 26), 0.65)
        for i, name in enumerate(("Min", "Max")):
            yy = y0 + 45 + i * 38
            shadow_text(canvas, name, (x0 + 14, yy + 22), 0.6)
            r = (x0 + 70, yy, x0 + 200, yy + 30)
            e["rects"][i] = r
            cv2.rectangle(canvas, r[:2], r[2:], (255, 255, 255) if e["sel"] == i else (120, 120, 120), 2 if e["sel"] == i else 1)
            txt = e["vals"][i] + ("|" if e["sel"] == i and int(time.time() * 2) % 2 == 0 else "")
            shadow_text(canvas, txt, (r[0] + 8, r[1] + 22), 0.6, (0, 255, 255))
            shadow_text(canvas, "m", (r[2] + 8, r[1] + 22), 0.55)
        shadow_text(canvas, "Tab: switch   Enter: apply   Esc: cancel", (x0 + 14, y0 + bh - 14), 0.45, (200, 200, 200))

    # ---- calibration mode ----
    def enter_calib(self):
        if self.rec:
            self.stop_rec()
        import calibrate_lidar_camera as cc
        cargs = cc.build_parser().parse_args([])
        cargs.intrinsics, cargs.layout, cargs.extrinsics = self.args.intrinsics, self.args.layout, self.args.extrinsics
        cargs.data_dir = gpaths.CALIBRATION
        cargs.scale = self.scale
        try:
            self.cal = cc.Calibrator(cargs, hardware=False)
        except Exception as e:  # noqa: BLE001
            self.flash(f"Calibrator error: {e}", 8)
            return
        self.cal.receiver = self.rx
        self.cal.scale = self.scale
        self.cal.show_dots = self.show_dots
        self.mode = "calib"
        self.flash("Face the wall squares from ~1 m, all 4 in view", 6)

    def exit_calib(self):
        self.cal = None
        self.mode = "live"
        self.load_extrinsics()
        self.flash("Back to live view (calibration reloaded)")

    # ---- dataset ----
    def meta(self):
        return dict(created=datetime.datetime.now().isoformat(timespec="seconds"),
                    image_size=[self.w, self.h], camera_matrix=self.K.tolist(),
                    distortion=self.dist.tolist(),
                    R_camera_from_lidar=self.R.tolist(), t_camera_from_lidar_m=self.t.tolist(),
                    calibration_note=self.calib_note,
                    extrinsics_file=self.ext_json,
                    depth_png="uint16 millimetres, z-depth along optical axis in the raw image pixel grid, 0=no data",
                    lidar_window_s=self.args.window, sample_rate_hz=self.args.hz,
                    lidar_frame="Unitree L2, metres; p_cam = R @ p_lidar + t",
                    camera_lag_s=self.args.cam_lag,
                    depth_range_m=[self.rmin, self.rmax])

    def ensure_session(self):
        if self.writer is None:
            os.makedirs(self.session_root, exist_ok=True)
            self.writer = SessionWriter(self.session_root, self.meta(), not self.args.no_points)
            log(f"Session {self.writer.dir}")
        return self.writer

    def start_rec(self):
        if self.rx is None or not self.rx.alive():
            self.flash("No LiDAR data - not recording", 5)
            return
        self.close_session()
        self.ensure_session()
        self.rec = True
        self.next_sample = 0.0
        self.flash("Recording")

    def stop_rec(self):
        self.rec = False
        n = self.writer.count if self.writer else 0
        self.close_session()
        self.flash(f"Stopped: {n} samples saved")

    def close_session(self):
        if self.writer is not None:
            self.writer.close()
            self.writer = None

    def snap(self):
        if self.rx is None or self.frame is None:
            return
        self.take_sample(self.frame, self.frame_t)
        self.flash(f"Snapshot saved ({self.writer.count} in session)", 2)

    def depth_map(self, pts):
        """LiDAR points -> uint16 mm depth image in the raw camera pixel grid (nearest return wins)."""
        depth = np.zeros((self.h, self.w), np.uint16)
        n = 0
        if len(pts):
            pc = pts[:, :3] @ self.R.T + self.t
            u, v, z = project(pc, self.K, self.dist, self.w, self.h, zmin=0.02)
            keep = (z >= self.rmin) & (z <= self.rmax)
            u, v, z = u[keep], v[keep], z[keep]
            if len(u):
                ui = np.clip(np.round(u).astype(int), 0, self.w - 1)
                vi = np.clip(np.round(v).astype(int), 0, self.h - 1)
                order = np.argsort(-z)                       # far first, near overwrites
                depth[vi[order], ui[order]] = np.clip(z[order] * 1000, 1, 65535).astype(np.uint16)
                n = int((depth > 0).sum())
        return depth, n

    def take_sample(self, frame, t_img):
        pts = self.rx.snapshot(window=self.args.window, t_end=t_img - self.args.cam_lag)
        depth, n = self.depth_map(pts)
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
        self.last_depth_px = n
        self.last_lidar_pts = len(pts)
        if n == 0:
            self.flash("WARNING: sample has NO depth (LiDAR points: %d) - check LiDAR / calibration" % len(pts), 4)
        wr = self.ensure_session()
        wr.rng = (self.rmin, self.rmax)
        wr.add(t_img, frame.copy(), depth, pts, n, sharp)

    # ---- drawing ----
    def draw_panel(self, canvas):
        for key, (x0, y0, x1, y1) in zip(self.keys(), self.btn_rects):
            label, col = self.label_for(key)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), col, -1)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (150, 150, 150), 1)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.putText(canvas, label, (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, TXT, 1, cv2.LINE_AA)

    def video_live(self, frame):
        img = cv2.resize(frame, (self.vw, self.vh), interpolation=cv2.INTER_LINEAR)
        n = 0
        if self.show_dots and self.rx is not None:
            pts = self.rx.snapshot(window=self.args.window)
            if len(pts):
                u, v, d = project(pts[:, :3] @ self.R.T + self.t, self.K, self.dist, self.w, self.h, zmin=0.02)
                keep = (d >= self.rmin) & (d <= self.rmax)
                n = draw_dots(img, u[keep] * self.scale, v[keep] * self.scale, d[keep],
                              self.rmin, self.rmax, 1 if self.scale < 1.2 else 2)
            shadow_text(img, f"dots {n}   range {self.rmin:g}-{self.rmax:g} m   (M to change)",
                        (self.vw - 300, self.vh - 10), 0.42, (220, 220, 220))
        y = 20
        if self.rec and self.writer:
            el = time.time() - self.writer.t0
            cv2.circle(img, (16, 16), 7, (0, 0, 255), -1)
            shadow_text(img, f"REC {int(el // 60):02d}:{int(el % 60):02d}  {self.writer.count} samples"
                             + (f"  (dropped {self.writer.dropped})" if self.writer.dropped else "")
                             + (f"  depth px {self.last_depth_px}" if self.last_depth_px is not None else ""),
                        (30, 21), 0.55, (120, 120, 255))
            y += 20
        if self.rx is None or not self.rx.alive():
            shadow_text(img, "NO LIDAR DATA - check cable / power / eth0 = 192.168.1.2", (8, y), 0.45,
                        (0, 165, 255))
            y += 18
        shadow_text(img, f"{self.calib_note}", (8, self.vh - 10), 0.45, (0, 255, 0) if "Calibrated" in self.calib_note else (0, 165, 255))
        if time.time() < self.msg_until:
            shadow_text(img, self.msg, (8, y), 0.5, (0, 255, 255))
        return img

    def video_calib(self, frame):
        c = self.cal
        c.process_frame(frame)
        img = c.render(frame)
        img = img[:self.vh, :self.vw]
        n = len(c.views)
        line = f"views {n} (need {c.args.min_views}+)"
        cov = c.coverage()
        if cov:
            line += f" | span yaw {cov[0]:.0f} pitch {cov[1]:.0f} deg, dist {cov[2]:.2f} m"
        bar = np.zeros((44, img.shape[1], 3), np.uint8)
        shadow_text(bar, line, (6, 16), 0.42)
        if c.est is not None:
            e = c.est
            good = e["chi2_red"] < 3 and max(e["sigma_rot_deg"]) < 0.6 and max(e["sigma_t_mm"]) < 25
            shadow_text(bar, f"+/-{max(e['sigma_rot_deg']):.1f} deg, +/-{max(e['sigma_t_mm']):.0f} mm  "
                             + ("GOOD - tap SAVE" if good else "keep capturing"), (6, 36), 0.45,
                        (0, 255, 0) if good else (0, 200, 255))
        else:
            shadow_text(bar, "Tilt / turn the rig 10-20 deg between captures", (6, 36), 0.42, (200, 200, 200))
        img[-44:, :] = bar
        return img

    def compose(self, frame):
        canvas = np.full((self.sh, self.sw, 3), 30, np.uint8)
        if frame is None:
            shadow_text(canvas, "Waiting for camera...", (20, self.sh // 2), 0.8)
            shadow_text(canvas, "Plug in the USB camera, or tap CAM", (20, self.sh // 2 + 30), 0.6, (0, 165, 255))
        else:
            img = self.video_calib(frame) if self.mode == "calib" else self.video_live(frame)
            canvas[self.vy:self.vy + img.shape[0], self.vx:self.vx + img.shape[1]] = img
        self.draw_panel(canvas)
        if self.edit is not None:
            self.draw_range_dialog(canvas)
        return canvas

    # ---- main loop ----
    def run(self):
        self.start_lidar()
        win = "Gimble"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        if not self.args.windowed:
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow(win, self.sw, self.sh)
        cv2.setMouseCallback(win, self.on_mouse)
        log(f"Started. screen {self.sw}x{self.sh}, video scale {self.scale:.2f}, {self.calib_note}")
        try:
            while self.running:
                if self.cap is None:
                    if time.time() - self.cam_try_t > 2.0:
                        self.cam_try_t = time.time()
                        self.cap, self.cam_idx = self.find_cam(self.args.camera)
                        if self.cap is not None:
                            log(f"Camera /dev/video{self.cam_idx}")
                else:
                    ok, fr = self.cap.read()
                    if ok:
                        self.frame, self.frame_t = fr, time.time()
                    else:
                        self.cap.release()
                        self.cap, self.frame = None, None
                        self.flash("Camera lost - reconnecting", 4)
                if self.pending_calib and self.frame is not None:
                    self.pending_calib = False
                    self.enter_calib()
                if self.frame is not None and self.mode == "live" and self.rec and self.writer is not None:
                    if time.time() >= self.next_sample and self.rx is not None:
                        self.next_sample = time.time() + 1.0 / max(self.args.hz, 0.1)
                        self.take_sample(self.frame, self.frame_t)
                        free = shutil.disk_usage(self.writer.dir).free
                        if free < 300 * 1024 * 1024:
                            self.stop_rec()
                            self.flash("Drive nearly full - recording stopped", 8)
                cv2.imshow(win, self.compose(self.frame))
                self.on_key(cv2.waitKey(1) & 0xFF)
                if not self.args.windowed:
                    pass
                elif cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            self.close_session()
            if self.rx is not None:
                self.rx.stop()
            if self.cap is not None:
                self.cap.release()
            cv2.destroyAllWindows()
            log("Stopped.")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screen", default="800x480", help="Screen size WxH (default 800x480, the official 7in touchscreen)")
    ap.add_argument("--windowed", action="store_true", help="Normal window instead of fullscreen")
    ap.add_argument("--camera", type=int, default=None, help="/dev/videoN to use (default: auto-detect)")
    ap.add_argument("--calibrate", action="store_true", help="Open straight into the calibration screen")
    ap.add_argument("--hz", type=float, default=3.0, help="Dataset samples per second while recording")
    ap.add_argument("--window", type=float, default=0.2, help="Seconds of LiDAR accumulated per sample/frame")
    ap.add_argument("--cam-lag", type=float, default=0.0, help="Camera delay to compensate (s)")
    ap.add_argument("--no-points", action="store_true", help="Don't save raw LiDAR points (depth maps only)")
    ap.add_argument("--range-min", type=float, default=None, help="Nearest LiDAR distance to show/record, metres")
    ap.add_argument("--range-max", type=float, default=None, help="Farthest LiDAR distance to show/record, metres")
    ap.add_argument("--data-dir", default="dataset")
    ap.add_argument("--intrinsics", default=gpaths.setting("camera_intrinsics.json"))
    ap.add_argument("--extrinsics", default=gpaths.setting("lidar_camera_extrinsics.json"))
    ap.add_argument("--layout", default=gpaths.setting("target_layout.json"))
    ap.add_argument("--local-ip", default="0.0.0.0")
    ap.add_argument("--local-port", type=int, default=6201)
    return ap


def main():
    args = build_parser().parse_args()
    try:
        App(args).run()
    except Exception:  # noqa: BLE001
        import traceback
        log("CRASH:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
