"""
calibrate_lidar_camera.py

Automatic LiDAR-to-camera calibration using the four ArUco squares on your wall
(target_layout.json from measure_targets.py).

The idea
--------
The camera can see the four squares, and because their real positions on the wall
are known, it can compute exactly where the wall is relative to itself (a plane:
normal direction + distance). The LiDAR can't see the squares, but it measures
the wall itself as hundreds of points, from which it fits the same plane in its
own coordinates. Each still capture gives one such pair of planes. Views taken
from different angles give different plane pairs, and the single rigid transform
(rotation + offset) that makes all of them agree IS the LiDAR-to-camera
calibration. The solver reports how uncertain each number is, so you can see when
you've captured enough.

How to use
----------
  1. Run:  python calibrate_lidar_camera.py
     (Use the LiDAR/camera overlay tool first if you can: its saved
      lidar_camera_extrinsics.json is used as a starting guess to pick out the
      wall points. A rough alignment - a few degrees - is enough.)
  2. Face the wall 0.9-1.4 m away so all four squares are in view. The status
     line turns green (READY) when the pose is stable.
  3. Press SPACE (or Capture). Keep the rig as steady as you can for ~2 s (small shake is fine).
     Or tick Auto-capture and just move between poses.
  4. Change the view each time: rotate the rig left/right (yaw) and up/down
     (pitch) by 10-20 degrees, and vary the distance. Keep >= 3 squares visible.
     The panel shows how much angle coverage you have and when it's enough.
  5. From 6 views the solver runs after every capture and shows the result with
     uncertainties. Check "Show LiDAR dots" to see the LiDAR points drawn on the
     camera image using the current result.
  6. Save extrinsics: writes lidar_camera_extrinsics.json (the old one is kept
     as .bak) which lidar_camera_overlay.py loads automatically.

Every capture is stored in calibration_data/<session>/ (camera image + LiDAR
points + measured planes) and calibration_session.json, so a solve can be redone
offline with:   python calibrate_lidar_camera.py --solve-only calibration_data/<session>

Notes
-----
* Depth along the viewing direction can't be told apart from a constant LiDAR
  range offset (they look identical when facing a flat wall). Expect a few mm of
  uncertainty there; it doesn't matter for coloring points.
* Needs: numpy, scipy, opencv-python (aruco included), and the other files in this folder.
"""
import argparse
import json
import math
import os
import sys
import time
from collections import deque

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("This script needs opencv-python:  pip install opencv-python")
try:
    from scipy.optimize import least_squares
except ImportError:
    sys.exit("scipy is required:  pip install scipy")

from lidar_camera_overlay import (
    BG, PAD, PANEL_W, ROW_H, TXT, DIM, HERE, IN_TO_M, Extrinsics, Intrinsics, Ui, axis_map,
    draw_dots, open_camera, project, rot_adj,
)
from measure_targets import rigid_fit, square_corners

ARUCO_DICT = cv2.aruco.DICT_4X4_50
DEG = math.pi / 180.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0.0]])


def exp_so3(w):
    th = np.linalg.norm(w)
    if th < 1e-12:
        return np.eye(3) + skew(w)
    K = skew(w / th)
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)


def angle_between(a, b):
    return math.acos(float(np.clip(a @ b, -1, 1)))


def adj_angles_deg(R_adj):
    """Inverse of lidar_camera_overlay.rot_adj: R = Rz(roll) Rx(pitch) Ry(yaw) -> (yaw, pitch, roll) deg."""
    from scipy.spatial.transform import Rotation
    roll, pitch, yaw = Rotation.from_matrix(R_adj).as_euler("ZXY", degrees=True)
    return yaw, pitch, roll


# ---------------------------------------------------------------------------
# Target layout + camera-side plane (PnP)
# ---------------------------------------------------------------------------


def load_layout(path):
    """target_layout.json -> {id: (4,3) corner coords in metres, wall frame, z=0}.
    Each square is refit as an ideal square of the reference edge length (rigid fit to the
    four hand-marked corners), which averages out click noise."""
    with open(path) as f:
        d = json.load(f)
    s = float(d["square_edge_mm"])
    ideal = square_corners(s)
    out = {}
    for k, t in d["tags"].items():
        meas = np.array(t["corners_mm"], float)
        R, tr = rigid_fit(ideal, meas)
        fitted = ideal @ R.T + tr
        out[int(k)] = np.column_stack([fitted / 1000.0, np.zeros(4)])
    return out


class _LegacyDetector:
    """OpenCV < 4.7 (e.g. the python3-opencv package on Raspberry Pi OS Bookworm, 4.6)."""

    def __init__(self, dictionary, params):
        self.d, self.p = dictionary, params

    def detectMarkers(self, gray):
        return cv2.aruco.detectMarkers(gray, self.d, parameters=self.p)


def make_detector():
    d = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
    if hasattr(cv2.aruco, "ArucoDetector"):
        p = cv2.aruco.DetectorParameters()
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        p.cornerRefinementWinSize = 5
        return cv2.aruco.ArucoDetector(d, p)
    p = cv2.aruco.DetectorParameters_create()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 5
    return _LegacyDetector(d, p)


def detect_pose(det, frame, K, dist, layout):
    """Find the tags and solve the camera pose against the wall.
    Returns dict(n_tags, ids, corners (list of (4,2)), and if solved: n, d, rms, rvec, tvec)."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = det.detectMarkers(gray)
    res = dict(n_tags=0, ids=[], corners=[], solved=False)
    if ids is None:
        return res
    obj, img = [], []
    for c, i in zip(corners, ids.ravel()):
        if int(i) in layout:
            obj.append(layout[int(i)])
            img.append(c.reshape(4, 2))
            res["ids"].append(int(i))
            res["corners"].append(c.reshape(4, 2))
    res["n_tags"] = len(res["ids"])
    if res["n_tags"] == 0:
        return res
    obj = np.vstack(obj).astype(np.float64)
    img = np.vstack(img).astype(np.float64)
    try:
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE)
        if not ok:
            return res
        rvec, tvec = cv2.solvePnPRefineLM(obj, img, K, dist, rvec, tvec)
    except cv2.error:
        return res
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
    rms = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img) ** 2, axis=1))))
    R, _ = cv2.Rodrigues(rvec)
    n = R[:, 2].copy()
    t = tvec.ravel()
    d = float(n @ t)
    if d < 0:
        n, d = -n, -d
    res.update(solved=True, n=n, d=d, rms=rms, rvec=rvec, tvec=tvec, obj=obj)
    return res


# ---------------------------------------------------------------------------
# LiDAR-side plane
# ---------------------------------------------------------------------------


def fit_plane_svd(P):
    c = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    n = Vt[2]
    d = float(n @ c)
    if d < 0:
        n, d = -n, -d
    return n, d


def ransac_plane(P, thr, iters=500, seed=0, sub=8000):
    rng = np.random.default_rng(seed)
    S = P if len(P) <= sub else P[rng.choice(len(P), sub, replace=False)]
    idx = rng.integers(0, len(S), (iters, 3))
    a, b, c = S[idx[:, 0]], S[idx[:, 1]], S[idx[:, 2]]
    nn = np.cross(b - a, c - a)
    nr = np.linalg.norm(nn, axis=1)
    good = nr > 1e-9
    nn = nn[good] / nr[good, None]
    dd = np.einsum("ij,ij->i", nn, a[good])
    best, best_cnt = None, -1
    for i0 in range(0, len(nn), 100):
        dist = np.abs(S @ nn[i0:i0 + 100].T - dd[i0:i0 + 100])
        cnt = (dist < thr).sum(0)
        j = int(np.argmax(cnt))
        if cnt[j] > best_cnt:
            best_cnt, best = int(cnt[j]), (nn[i0 + j], dd[i0 + j])
    return best


def extract_wall_plane(pts_xyz, pred, prior_R, prior_t, K, w, h, band=0.25, thr=0.015,
                       min_range=0.25, max_range=6.0):
    """
    pts_xyz: (N,3) LiDAR points (lidar frame).
    pred: (n_l, d_l) plane predicted from the camera plane + prior extrinsics (lidar frame).
    Returns dict or (None, reason).
    """
    r = np.linalg.norm(pts_xyz, axis=1)
    P = pts_xyz[(r > min_range) & (r < max_range)]
    if len(P) < 500:
        return None, f"only {len(P)} LiDAR points (is it streaming?)"
    pc = P @ prior_R.T + prior_t
    z = pc[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = K[0, 0] * pc[:, 0] / z + K[0, 2]
        v = K[1, 1] * pc[:, 1] / z + K[1, 2]
    inview = (z > 0.15) & (u > -0.05 * w) & (u < 1.05 * w) & (v > -0.05 * h) & (v < 1.05 * h)
    n_p, d_p = pred
    near = np.abs(P @ n_p - d_p) < band
    Q = P[inview & near]
    if len(Q) < 400:
        return None, (f"only {len(Q)} LiDAR points near the expected wall - is the overlay alignment "
                      f"roughly right? (run lidar_camera_overlay.py first)")
    res = ransac_plane(Q, thr)
    if res is None:
        return None, "plane search failed"
    n, d = res
    for thr_i in (thr, thr, 0.010, 0.010):
        inl = np.abs(Q @ n - d) < thr_i
        if inl.sum() < 100:
            return None, "no consistent plane found"
        n, d = fit_plane_svd(Q[inl])
    inl = np.abs(Q @ n - d) < 0.010
    I = Q[inl]
    rms = float(np.sqrt(np.mean((I @ n - d) ** 2)))
    c = I.mean(0)
    sv = np.linalg.svd(I - c, compute_uv=False) / math.sqrt(len(I))
    if len(I) < 600:
        return None, f"too few wall points ({len(I)})"
    if sv[1] < 0.12:
        return None, "wall points cover too small an area"
    frac = len(I) / len(Q)
    if angle_between(n, n_p) > 30 * DEG:
        return None, "found plane disagrees with expected wall orientation by >30 deg"
    return dict(n=n, d=d, n_inliers=int(len(I)), rms=rms, frac=float(frac), spread=float(sv[1]),
                inlier_pts=I[:: max(1, len(I) // 4000)]), ""


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------


def solve_extrinsics(views, prior_R, prior_t, sig_ang_deg=1.0, sig_d_mm=8.0, sig_prior_t_mm=100.0,
                     robust=True):
    """
    views: list of dicts with n_c, d_c (camera plane) and n_l, d_l (LiDAR plane).
    Finds R, t with  p_cam = R p_lidar + t  so that  n_c = R n_l  and  d_c = d_l + n_c . t.
    """
    sa, sd, sp = sig_ang_deg * DEG, sig_d_mm / 1000.0, sig_prior_t_mm / 1000.0
    Nc = np.array([v["n_c"] for v in views])
    Dc = np.array([v["d_c"] for v in views])
    Nl = np.array([v["n_l"] for v in views])
    Dl = np.array([v["d_l"] for v in views])
    m = len(views)
    # Init: Kabsch on normals, then linear solve for t
    Hm = Nl.T @ Nc
    U, _, Vt = np.linalg.svd(Hm)
    R0 = Vt.T @ np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))]) @ U.T
    if m >= 2 and np.linalg.matrix_rank(Nl - Nl.mean(0), tol=1e-3) < 1:
        R0 = prior_R
    Nc0 = Nl @ R0.T
    t0, *_ = np.linalg.lstsq(np.vstack([Nc0, np.eye(3) * (sd / sp)]),
                             np.concatenate([Dc - Dl, prior_t * (sd / sp)]), rcond=None)

    def unpack(x):
        return exp_so3(x[:3]) @ R0, x[3:6]

    def resid(x):
        R, t = unpack(x)
        Np = Nl @ R.T
        r1 = (Nc - Np) / sa
        r2 = (Dc - (Dl + np.einsum("ij,j->i", Np, t))) / sd
        r3 = (t - prior_t) / sp
        return np.concatenate([r1.ravel(), r2, r3])

    x0 = np.concatenate([np.zeros(3), t0])
    sol = least_squares(resid, x0, loss="soft_l1" if robust else "linear", f_scale=2.0, x_scale="jac")
    R, t = unpack(sol.x)
    J = sol.jac
    dof = max(1, 4 * m - 6)
    r = resid(sol.x)
    chi2 = float(np.sum(r[: 4 * m] ** 2) / dof)
    try:
        cov = np.linalg.inv(J.T @ J) * max(1.0, chi2)
    except np.linalg.LinAlgError:
        cov = np.full((6, 6), np.nan)
    sig = np.sqrt(np.clip(np.diag(cov), 0, None))
    Np = Nl @ R.T
    per_view = []
    for i in range(m):
        ang = angle_between(Nc[i], Np[i]) / DEG
        dres = (Dc[i] - (Dl[i] + Np[i] @ t)) * 1000.0
        per_view.append((ang, dres, math.sqrt((ang * DEG / sa) ** 2 + (dres / 1000 / sd) ** 2)))
    return dict(R=R, t=t, sigma_rot_deg=sig[:3] / DEG, sigma_t_mm=sig[3:] * 1000.0, chi2_red=chi2,
                per_view=per_view, cov=cov)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def write_extrinsics(out, M, est, n_views):
    """Write the overlay-compatible extrinsics file (old file is kept as .bak)."""
    R, t = est["R"], est["t"]
    Radj = R @ M.T
    yaw, pitch, roll = adj_angles_deg(Radj)
    c = -Radj.T @ t
    data = {"axis_map_rows_are_camera_xyz_in_lidar_axes": M.tolist(),
            "camera_position_m": c.tolist(),
            "yaw_pitch_roll_deg": [yaw, pitch, roll],
            "R_camera_from_lidar": R.tolist(), "t_camera_from_lidar_m": t.tolist(),
            "calibration": dict(views=n_views, sigma_rot_deg=est["sigma_rot_deg"].tolist(),
                                sigma_t_mm=est["sigma_t_mm"].tolist(), chi2_reduced=est["chi2_red"],
                                saved=time.strftime("%Y-%m-%d %H:%M:%S"))}
    if os.path.exists(out):
        try:
            os.replace(out, out + ".bak")
        except OSError:
            pass
    with open(out, "w") as f:
        json.dump(data, f, indent=2)


COVER_YAW, COVER_PITCH, COVER_DIST = 35.0, 30.0, 0.30


class Calibrator:
    def __init__(self, args, hardware=True):
        self.args = args
        self.intr = Intrinsics(args.intrinsics)
        self.layout = load_layout(args.layout)
        self.det = make_detector()
        self.K, self.dist = self.intr.K, self.intr.dist
        self.w, self.h = self.intr.width, self.intr.height
        self.cam_idx = args.camera if args.camera is not None else self.intr.camera_index
        self.calib_idx = self.intr.camera_index
        # prior extrinsics (camera <- lidar)
        sx = 1.0
        ext = Extrinsics(axis_map("+z", "-x"), [sx * 3.76 * IN_TO_M, 0.0, 0.0])
        self.prior_source = "default axes + 3.76 in offset"
        if os.path.exists(args.extrinsics):
            try:
                with open(args.extrinsics) as f:
                    ext = Extrinsics.from_json(json.load(f))
                self.prior_source = os.path.basename(args.extrinsics)
            except (OSError, KeyError, ValueError):
                pass
        Radj = rot_adj(*ext.ang)
        self.M = ext.M.copy()
        self.prior_R = Radj @ ext.M
        self.prior_t = -Radj @ ext.c
        self.est = None                  # solver result
        self.views = []
        self.min_tags = args.min_tags
        self.capture_s = args.capture_seconds
        self.show_dots = True
        self.auto = False
        self.msg, self.msg_until = "", 0.0
        self.running = True
        self.pending_cam = 0
        self.pending_cam_abs = None
        self.cap = None
        self.receiver = None
        self.cap_state = None            # active capture
        self.hist = deque(maxlen=60)     # (t, n, d) of recent solved poses
        self.last_auto = 0.0
        self.pose = None
        self.mouse = (0, 0)
        self.held = None
        self.scale = args.scale
        self.session_dir = None
        self.lidar_pts_preview = None
        self.ui = Ui(int(self.w * self.scale))
        self._build_ui()
        if hardware:
            self.cap = self._open(self.cam_idx)
            if self.cap is None:
                sys.exit(f"Couldn't open camera index {self.cam_idx}. Use --camera N.")
            try:
                from lidar_receiver import LidarReceiver
            except ImportError:
                from lidar_live_viewer import LidarReceiver
            self.receiver = LidarReceiver(args.local_ip, args.local_port, 1.0)
            self.receiver.start()

    # ---- resources ----
    def _open(self, idx):
        cap = open_camera(idx, self.intr.width, self.intr.height)
        if cap is None:
            return None
        ok, fr = cap.read()
        if not ok:
            cap.release()
            return None
        if fr.shape[1] != self.intr.width or fr.shape[0] != self.intr.height:
            self.flash(f"Camera is {fr.shape[1]}x{fr.shape[0]}, intrinsics are for "
                       f"{self.intr.width}x{self.intr.height}!", 6)
        return cap

    def flash(self, text, secs=3.0):
        self.msg, self.msg_until = text, time.time() + secs
        print(text)

    def current_R_t(self):
        if self.est is not None:
            return self.est["R"], self.est["t"]
        return self.prior_R, self.prior_t

    # ---- session storage ----
    def ensure_session(self):
        if self.session_dir is None:
            self.session_dir = os.path.join(self.args.data_dir, time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.session_dir, exist_ok=True)
        return self.session_dir

    def save_session(self):
        if not self.views:
            return
        path = os.path.join(self.ensure_session(), "calibration_session.json")
        keep = ("n_c", "d_c", "n_l", "d_l", "n_tags", "pnp_rms_px", "lidar_inliers", "lidar_rms_m",
                "cam_std_deg", "cam_std_mm", "time")
        with open(path, "w") as f:
            json.dump(dict(prior_R=self.prior_R.tolist(), prior_t=self.prior_t.tolist(),
                           axis_map=self.M.tolist(),
                           views=[{k: (v[k].tolist() if isinstance(v[k], np.ndarray) else v[k])
                                   for k in keep if k in v} for v in self.views]), f, indent=1)

    # ---- capture ----
    def start_capture(self):
        if self.cap_state is not None:
            return
        if not (self.pose and self.pose["solved"] and self.pose["n_tags"] >= self.min_tags):
            self.flash(f"Need {self.min_tags}+ squares in view with a good pose")
            return
        self.cap_state = dict(t_end=time.time() + self.capture_s, samples=[], t0=time.time(), img=None)
        if self.receiver is not None:
            self.receiver.window_seconds = self.capture_s
        self.flash(f"Capturing {self.capture_s:.1f} s - keep the rig as steady as you can", self.capture_s + 0.5)

    def _add_sample(self, pose):
        self.cap_state["samples"].append((pose["n"], pose["d"], pose["rms"], pose["n_tags"]))

    def finish_capture(self, frame, pts):
        st, self.cap_state = self.cap_state, None
        S = st["samples"]
        if self.receiver is not None:
            self.receiver.window_seconds = 1.0
        if len(S) < 5:
            return self.flash("Capture failed: tags lost during capture")
        Ns = np.array([s[0] for s in S])
        n_c = Ns.mean(0)
        n_c /= np.linalg.norm(n_c)
        d_c = float(np.median([s[1] for s in S]))
        std_deg = float(np.degrees(np.sqrt(np.mean([angle_between(n, n_c) ** 2 for n in Ns]))))
        std_mm = float(np.std([s[1] for s in S]) * 1000)
        # Small shake is normal (the LiDAR spins, the legs flex): the capture averages the pose over the
        # whole window and more views average the rest out. Only a clear move/bump is refused.
        if std_deg > self.args.max_motion_deg or std_mm > self.args.max_motion_mm:
            return self.flash(f"Rig was moved during the capture ({std_deg:.1f} deg, {std_mm:.0f} mm) - capture again")
        # predicted wall plane in lidar frame from the current best extrinsics
        R, t = self.current_R_t()
        pred = (R.T @ n_c, d_c - n_c @ t)
        wall, why = extract_wall_plane(pts[:, :3], pred, R, t, self.K, self.w, self.h)
        if wall is None:
            return self.flash("LiDAR wall not found: " + why, 6)
        view = dict(n_c=n_c, d_c=d_c, n_l=wall["n"], d_l=wall["d"], n_tags=int(min(s[3] for s in S)),
                    pnp_rms_px=float(np.mean([s[2] for s in S])), lidar_inliers=wall["n_inliers"],
                    lidar_rms_m=wall["rms"], cam_std_deg=std_deg, cam_std_mm=std_mm,
                    time=time.time())
        self.views.append(view)
        i = len(self.views)
        d = self.ensure_session()
        cv2.imwrite(os.path.join(d, f"view_{i:02d}.jpg"), frame)
        np.savez_compressed(os.path.join(d, f"view_{i:02d}.npz"), points=pts.astype(np.float32),
                            n_c=n_c, d_c=d_c)
        self.save_session()
        self.lidar_pts_preview = wall["inlier_pts"]
        self.flash(f"View {i} captured: {wall['n_inliers']} wall points, plane rms "
                   f"{wall['rms'] * 1000:.1f} mm, camera {view['pnp_rms_px']:.2f} px")
        self.solve()

    def undo(self):
        if self.views:
            self.views.pop()
            self.save_session()
            self.solve()
            self.flash(f"Removed last view ({len(self.views)} left)")

    def clear(self):
        self.views, self.est, self.session_dir = [], None, None
        self.flash("Cleared all views")

    # ---- solve / save ----
    def solve(self):
        if len(self.views) < self.args.min_views:
            self.est = None
            return
        try:
            self.est = solve_extrinsics(self.views, self.prior_R, self.prior_t,
                                        self.args.sigma_deg, self.args.sigma_mm)
        except Exception as e:  # noqa: BLE001
            self.est = None
            self.flash(f"Solve failed: {e}")

    def coverage(self):
        if not self.views:
            return None
        ys = [math.degrees(math.atan2(v["n_c"][0], v["n_c"][2])) for v in self.views]
        ps = [math.degrees(math.atan2(v["n_c"][1], v["n_c"][2])) for v in self.views]
        ds = [v["d_c"] for v in self.views]
        return (max(ys) - min(ys), max(ps) - min(ps), max(ds) - min(ds))

    def save_extrinsics(self):
        if self.est is None:
            return self.flash(f"Need at least {self.args.min_views} views first")
        write_extrinsics(self.args.extrinsics, self.M, self.est, len(self.views))
        self.flash(f"Saved {os.path.basename(self.args.extrinsics)} (old one kept as .bak)", 5)

    # ---- UI ----
    def _build_ui(self):
        u = self.ui
        u.header("Capture")
        u.buttons([("Capture (SPACE)", self.start_capture, False)])
        u.buttons([("Undo last", self.undo, False), ("Clear all", self.clear, False)])
        u.check("Auto-capture", lambda: self.auto, lambda v: setattr(self, "auto", v))
        u.check("Show LiDAR dots", lambda: self.show_dots, lambda v: setattr(self, "show_dots", v))
        u.stepper("Hold time", lambda: f"{self.capture_s:.1f} s",
                  lambda: setattr(self, "capture_s", max(1.0, self.capture_s - 0.5)),
                  lambda: setattr(self, "capture_s", min(6.0, self.capture_s + 0.5)),
                  raw=lambda: self.capture_s,
                  setv=lambda v: setattr(self, "capture_s", float(np.clip(v, 1.0, 10.0))))
        u.stepper("Min squares", lambda: f"{self.min_tags}",
                  lambda: setattr(self, "min_tags", max(1, self.min_tags - 1)),
                  lambda: setattr(self, "min_tags", min(4, self.min_tags + 1)))
        u.stepper("Camera", lambda: f"#{self.cam_idx}",
                  lambda: setattr(self, "pending_cam", -1), lambda: setattr(self, "pending_cam", 1),
                  dec_label="<", inc_label=">", raw=lambda: self.cam_idx,
                  setv=lambda v: setattr(self, "pending_cam_abs", max(0, int(round(v)))))
        u.buttons([("Save extrinsics", self.save_extrinsics, False)])
        u.buttons([("Quit", lambda: setattr(self, "running", False), False)])
        self.text_y = u.y + 6

    def on_mouse(self, event, x, y, flags, _):
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = self.ui.hit(x, y)
            item = hit[2] if hit else None
            if self.ui.edit is not None and item is not self.ui.edit:
                self.commit_edit()
            if item is not None:
                self.start_edit(item)
            elif hit:
                hit[0]()
                if hit[1]:
                    self.held = (hit[0], time.time() + 0.4)
        elif event == cv2.EVENT_LBUTTONUP:
            self.held = None

    def start_edit(self, it):
        if self.ui.edit is it:
            return
        if self.ui.edit is not None:
            self.commit_edit()
        v = it["raw"]()
        self.ui.edit, self.ui.buf, self.ui.fresh = it, (f"{v:.3f}".rstrip("0").rstrip(".") or "0"), True

    def commit_edit(self):
        it, buf = self.ui.edit, self.ui.buf
        self.ui.edit = None
        try:
            it["setv"](float(buf))
        except (TypeError, ValueError):
            self.flash(f"Not a number: '{buf}'")

    def edit_key(self, k):
        ui = self.ui
        if k == 27:
            ui.edit = None
        elif k in (13, 10):
            self.commit_edit()
        elif k == 8:
            ui.buf, ui.fresh = ("" if ui.fresh else ui.buf[:-1]), False
        elif 0 < k < 128 and chr(k) in "0123456789.-+":
            if ui.fresh:
                ui.buf, ui.fresh = "", False
            ui.buf += chr(k)

    def key(self, k):
        if k in (255, 0):
            return
        if self.ui.edit is not None:
            return self.edit_key(k)
        c = chr(k) if 0 < k < 128 else ""
        if k == 27 or c == "q":
            self.running = False
        elif k == 32:
            self.start_capture()
        elif c == "u":
            self.undo()
        elif c == "a":
            self.auto = not self.auto
        elif c == "g":
            self.show_dots = not self.show_dots
        elif c == "s":
            self.save_extrinsics()
        elif c == "c":
            self.pending_cam = 1

    # ---- per-frame ----
    def status(self):
        """(text, colour BGR, ready)"""
        p = self.pose
        if p is None or p["n_tags"] == 0:
            return "no squares detected", (0, 0, 255), False
        if p["n_tags"] < self.min_tags:
            return f"only {p['n_tags']} square(s) - need {self.min_tags}", (0, 165, 255), False
        if not p["solved"] or p["rms"] > self.args.max_pnp_px:
            return f"pose error high ({p.get('rms', 0):.2f} px)", (0, 165, 255), False
        return "READY", (0, 200, 0), True

    def is_steady(self, span=0.8, deg=1.0, mm=12.0):
        """Loose check used only by AUTO so it doesn't fire while you are still moving the rig between poses."""
        now = time.time()
        H = [h for h in self.hist if now - h[0] < span]
        if len(H) < 6:
            return False
        n0 = np.mean([h[1] for h in H], axis=0)
        n0 /= np.linalg.norm(n0)
        a = max(angle_between(h[1], n0) for h in H) / DEG
        dz = (max(h[2] for h in H) - min(h[2] for h in H)) * 1000
        return a < deg and dz < mm

    def novel(self):
        if not self.pose or not self.pose["solved"]:
            return False
        n, d = self.pose["n"], self.pose["d"]
        for v in self.views:
            if angle_between(n, v["n_c"]) < 6 * DEG and abs(d - v["d_c"]) < 0.15:
                return False
        return True

    def process_frame(self, frame):
        pose = detect_pose(self.det, frame, self.K, self.dist, self.layout)
        self.pose = pose
        now = time.time()
        if pose["solved"] and pose["n_tags"] >= 1:
            self.hist.append((now, pose["n"], pose["d"]))
        else:
            self.hist.clear()
        if self.cap_state is not None:
            if pose["solved"] and pose["n_tags"] >= self.min_tags:
                self._add_sample(pose)
            if now >= self.cap_state["t_end"]:
                pts = self.receiver.snapshot() if self.receiver is not None else np.empty((0, 4))
                self.finish_capture(frame, pts)
        elif self.auto and self.receiver is not None and now - self.last_auto > 1.5:
            if self.status()[2] and self.is_steady(span=0.8, deg=1.0, mm=12.0) and self.novel():
                self.last_auto = now
                self.start_capture()

    def render(self, frame):
        sc = self.scale
        img = cv2.resize(frame, None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
        p = self.pose
        if self.show_dots and self.receiver is not None:
            pts = self.receiver.snapshot()
            if len(pts):
                R, t = self.current_R_t()
                u, v, d = project(pts[:, :3] @ R.T + t, self.K, self.dist, self.w, self.h)
                draw_dots(img, u * sc, v * sc, d, 0.5, 6.0, 2)
        if p and p["n_tags"]:
            for ids, c in zip(p["ids"], p["corners"]):
                pts_i = (c * sc).astype(np.int32)
                cv2.polylines(img, [pts_i], True, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(img, str(ids), tuple(pts_i[0] + [4, -6]), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 255, 0), 2, cv2.LINE_AA)
            if p["solved"]:
                # reprojected wall axes: visual check that the pose fits
                ax = np.float64([[0, 0, 0], [0.25, 0, 0], [0, 0.25, 0], [0, 0, 0.25]])
                q, _ = cv2.projectPoints(ax, p["rvec"], p["tvec"], self.K, self.dist)
                q = (q.reshape(-1, 2) * sc).astype(int)
                for j, col in ((1, (0, 0, 255)), (2, (0, 255, 0)), (3, (255, 0, 0))):
                    cv2.line(img, tuple(q[0]), tuple(q[j]), col, 2, cv2.LINE_AA)
        txt, col, ready = self.status()
        lines = [(txt, col)]
        if p and p["solved"]:
            n = p["n"]
            lines.append((f"{p['n_tags']} squares | {p['d']:.2f} m | pose err {p['rms']:.2f} px", (255, 255, 255)))
            lines.append((f"wall tilt: yaw {math.degrees(math.atan2(n[0], n[2])):+.1f}  "
                          f"pitch {math.degrees(math.atan2(n[1], n[2])):+.1f} deg", (255, 255, 255)))
        if self.cap_state is not None:
            left = max(0.0, self.cap_state["t_end"] - time.time())
            lines.append((f"CAPTURING {left:.1f}s  ({len(self.cap_state['samples'])} frames)", (0, 220, 255)))
        if time.time() < self.msg_until:
            lines.append((self.msg, (0, 255, 255)))
        for i, (t_, c_) in enumerate(lines):
            cv2.putText(img, t_, (8, 22 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, t_, (8, 22 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c_, 1, cv2.LINE_AA)
        return img

    def panel_text(self):
        L = []
        cov = self.coverage()
        n = len(self.views)
        L.append((f"Views: {n}   (need {self.args.min_views}+, 10-15 ideal)", TXT))
        if cov:
            def bar(v, tgt):
                return "OK " if v >= tgt else "   "
            L.append((f"{bar(cov[0], COVER_YAW)}yaw span   {cov[0]:4.0f} / {COVER_YAW:.0f} deg", TXT))
            L.append((f"{bar(cov[1], COVER_PITCH)}pitch span {cov[1]:4.0f} / {COVER_PITCH:.0f} deg", TXT))
            L.append((f"{bar(cov[2], COVER_DIST)}dist span  {cov[2]:4.2f} / {COVER_DIST:.2f} m", TXT))
        else:
            L.append(("Tilt the rig left/right/up/down 10-20 deg", DIM))
            L.append(("and vary distance between captures.", DIM))
        L.append(("", TXT))
        if self.est is not None:
            e = self.est
            Radj = e["R"] @ self.M.T
            yaw, pitch, roll = adj_angles_deg(Radj)
            c = -Radj.T @ e["t"]
            L.append(("RESULT  (vs axis mapping)", (120, 220, 120)))
            L.append((f"yaw {yaw:+.2f} pitch {pitch:+.2f} roll {roll:+.2f} deg", TXT))
            L.append((f"  +/- {e['sigma_rot_deg'][0]:.2f} {e['sigma_rot_deg'][1]:.2f} {e['sigma_rot_deg'][2]:.2f}", DIM))
            L.append((f"cam offset mm: x {c[0]*1000:+.0f} y {c[1]*1000:+.0f} z {c[2]*1000:+.0f}", TXT))
            L.append((f"  +/- {e['sigma_t_mm'][0]:.0f} {e['sigma_t_mm'][1]:.0f} {e['sigma_t_mm'][2]:.0f} mm", DIM))
            good = e["chi2_red"] < 3 and max(e["sigma_rot_deg"]) < 0.6 and max(e["sigma_t_mm"]) < 25
            L.append(("Quality: " + ("GOOD - save it" if good else "keep capturing / check outliers"),
                      (120, 220, 120) if good else (0, 200, 255)))
            L.append(("", TXT))
            L.append(("view  rot(deg)  dist(mm)  sigma", DIM))
            for i, (a, dm, s) in enumerate(e["per_view"][-10:], start=max(1, n - 9)):
                L.append((f"{i:3d}   {a:6.2f}   {dm:+7.1f}   {s:5.1f}" + ("  <-- outlier?" if s > 4 else ""),
                          (0, 140, 255) if s > 4 else TXT))
        else:
            L.append((f"Result appears after {self.args.min_views} views.", DIM))
            L.append((f"Start guess: {self.prior_source}", DIM))
        return L

    def compose(self, img):
        H = max(img.shape[0], self.text_y + 22 * 24)
        canvas = np.full((H, img.shape[1] + PANEL_W, 3), BG, np.uint8)
        canvas[:img.shape[0], :img.shape[1]] = img
        self.ui.x0 = img.shape[1]
        self.ui.draw(canvas, self.mouse)
        y = self.text_y + 14
        x = img.shape[1] + PAD
        for t_, col in self.panel_text():
            cv2.putText(canvas, t_, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1, cv2.LINE_AA)
            y += 17
        return canvas

    def run(self):
        win = "LiDAR-camera calibration"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, self.on_mouse)
        frame = np.zeros((self.h, self.w, 3), np.uint8)
        try:
            while self.running:
                ok, fr = self.cap.read()
                if ok:
                    frame = fr
                    self.process_frame(frame)
                cv2.imshow(win, self.compose(self.render(frame)))
                k = cv2.waitKey(1) & 0xFF
                if self.held and time.time() >= self.held[1]:
                    self.held[0]()
                    self.held = (self.held[0], time.time() + 0.07)
                self.key(k)
                if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if self.pending_cam:
                    d, self.pending_cam = self.pending_cam, 0
                    for kk in range(1, 10):
                        idx = (self.cam_idx + d * kk) % 10
                        cap = self._open(idx)
                        if cap is not None:
                            self.cap.release()
                            self.cap, self.cam_idx = cap, idx
                            self.flash(f"Camera {idx}" + ("" if idx == self.calib_idx else
                                       f" (intrinsics are for camera {self.calib_idx}!)"))
                            break
                if self.pending_cam_abs is not None:
                    i, self.pending_cam_abs = self.pending_cam_abs, None
                    cap = self._open(i) if i != self.cam_idx else None
                    if cap is not None:
                        self.cap.release()
                        self.cap, self.cam_idx = cap, i
                        self.flash(f"Camera {i}")
        finally:
            if self.receiver is not None:
                self.receiver.stop()
            if self.cap is not None:
                self.cap.release()
            cv2.destroyAllWindows()


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    import gimble_paths as gpaths
    ap.add_argument("--layout", default=gpaths.setting("target_layout.json"))
    ap.add_argument("--intrinsics", default=gpaths.setting("camera_intrinsics.json"))
    ap.add_argument("--extrinsics", default=gpaths.setting("lidar_camera_extrinsics.json"))
    ap.add_argument("--data-dir", default=gpaths.CALIBRATION)
    ap.add_argument("--camera", type=int, default=None)
    ap.add_argument("--local-ip", default="0.0.0.0")
    ap.add_argument("--local-port", type=int, default=6201)
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--capture-seconds", type=float, default=2.0)
    ap.add_argument("--min-tags", type=int, default=3)
    ap.add_argument("--min-views", type=int, default=6)
    ap.add_argument("--max-pnp-px", type=float, default=1.2, help="Reject poses with larger reprojection error")
    ap.add_argument("--max-motion-deg", type=float, default=2.0, help="Refuse a capture if the pose wandered more than this (a real bump)")
    ap.add_argument("--max-motion-mm", type=float, default=30.0)
    ap.add_argument("--sigma-deg", type=float, default=1.0, help="Assumed plane-normal noise")
    ap.add_argument("--sigma-mm", type=float, default=8.0, help="Assumed plane-distance noise")
    ap.add_argument("--save", action="store_true", help="With --solve-only: also write the extrinsics file")
    ap.add_argument("--solve-only", metavar="SESSION_DIR",
                    help="Re-solve a saved session folder (no camera / LiDAR needed)")
    return ap


def solve_only(args):
    d = args.solve_only
    p = d if d.endswith(".json") else os.path.join(d, "calibration_session.json")
    with open(p) as f:
        s = json.load(f)
    views = [{k: (np.array(v) if isinstance(v, list) else v) for k, v in vw.items()} for vw in s["views"]]
    prior_R, prior_t = np.array(s["prior_R"]), np.array(s["prior_t"])
    est = solve_extrinsics(views, prior_R, prior_t, args.sigma_deg, args.sigma_mm)
    M = np.array(s["axis_map"])
    Radj = est["R"] @ M.T
    print(f"{len(views)} views")
    print("R_camera_from_lidar =\n", np.round(est["R"], 5))
    print("t_camera_from_lidar (mm) =", np.round(est["t"] * 1000, 1))
    print("yaw/pitch/roll vs axis map (deg) =", np.round(adj_angles_deg(Radj), 3))
    print("sigma rot (deg) =", np.round(est["sigma_rot_deg"], 3), " sigma t (mm) =", np.round(est["sigma_t_mm"], 1))
    print("chi2_reduced =", round(est["chi2_red"], 2))
    for i, (a, dm, sg) in enumerate(est["per_view"], 1):
        print(f"  view {i:2d}: rot {a:5.2f} deg  dist {dm:+6.1f} mm  sigma {sg:4.1f}")
    if args.save:
        write_extrinsics(args.extrinsics, M, est, len(views))
        print("Saved", args.extrinsics)


def main():
    args = build_parser().parse_args()
    if args.solve_only:
        return solve_only(args)
    Calibrator(args).run()


if __name__ == "__main__":
    main()
