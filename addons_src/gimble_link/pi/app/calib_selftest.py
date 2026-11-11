"""
calib_selftest.py - end-to-end check of calibrate_lidar_camera.py without hardware.

Renders your real ArUco layout (target_layout.json) into simulated camera frames, makes
matching simulated LiDAR wall points (1.5 cm noise) from a known "true" extrinsic, then runs
the same detect_pose / extract_wall_plane / solve_extrinsics code and reports how close the
recovered calibration is to the truth.

    python calib_selftest.py
"""
import os
import sys

import cv2
import numpy as np

import calibrate_lidar_camera as cc
from lidar_camera_overlay import axis_map, rot_adj, IN_TO_M, Intrinsics

HERE = os.path.dirname(os.path.abspath(__file__))
DEG = np.pi / 180


def rodrigues(v):
    return cv2.Rodrigues(np.asarray(v, float))[0]


def render(layout, K, w, h, R_cw, t_cw, rng):
    """Camera frame of the wall with the tags (white paper margin around each)."""
    img = np.full((h, w), 170, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(cc.ARUCO_DICT)
    for tid, corners in layout.items():
        side = np.linalg.norm(corners[1] - corners[0])
        mk = cv2.aruco.generateImageMarker(d, tid, 240, borderBits=1)
        m = 0.10                        # white margin (fraction of side) around the marker
        page = np.full((360, 360), 255, np.uint8)
        page[60:300, 60:300] = mk
        # page corner points in tag frame: marker corners are at pixel 60..300
        src = np.float32([[0, 0], [360, 0], [360, 360], [0, 360]])
        fac = 360 / 240.0
        u = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
        ex = corners[1] - corners[0]
        ey = corners[3] - corners[0]
        pc = np.array([corners[0] + (uu[0] * fac - (fac - 1) / 2) * ex + (uu[1] * fac - (fac - 1) / 2) * ey for uu in u])
        pw = (pc @ R_cw.T + t_cw)
        pix = (pw / pw[:, 2:3]) @ K.T
        H = cv2.getPerspectiveTransform(src, pix[:, :2].astype(np.float32))
        warped = cv2.warpPerspective(page, H, (w, h), flags=cv2.INTER_AREA, borderValue=0)
        mask = cv2.warpPerspective(np.full((360, 360), 255, np.uint8), H, (w, h))
        img = np.where(mask > 0, warped, img)
    img = cv2.GaussianBlur(img, (0, 0), 0.7).astype(float)
    img += rng.normal(0, 2.0, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def lidar_points(R_cw, t_cw, R_true, t_true, rng, n=6000):
    """Wall points (plane z_w=0) + clutter, in the LiDAR frame."""
    x = rng.uniform(-0.6, 1.7, n)
    y = rng.uniform(-0.8, 1.5, n)
    pw = np.column_stack([x, y, np.zeros(n)])
    pc = pw @ R_cw.T + t_cw
    pl = (pc - t_true) @ R_true                # p_l = R^T (p_c - t)
    # keep the LiDAR-like field of view: in front (+z_l) and within range
    pl = pl[(pl[:, 2] > 0.3) & (np.linalg.norm(pl, axis=1) < 5)]
    dirs = pl / np.linalg.norm(pl, axis=1, keepdims=True)
    pl = pl + dirs * rng.normal(0, 0.015, (len(pl), 1))
    clutter = rng.uniform(-1.5, 1.5, (400, 3)) + [0, 0, 1.0]
    return np.vstack([pl, clutter])


def main():
    rng = np.random.default_rng(3)
    # adj_angles_deg must invert rot_adj
    for a in [(2, -1.5, 1), (10, 5, -7), (-20, 15, 30)]:
        back = cc.adj_angles_deg(rot_adj(*a))
        assert np.allclose(back, a, atol=1e-6), (a, back)
    print("adj_angles_deg inverts rot_adj: OK")

    import gimble_paths as gpaths
    intr = Intrinsics(gpaths.setting("camera_intrinsics.json"))
    K, w, h = intr.K, intr.width, intr.height
    dist0 = np.zeros(5)
    layout = cc.load_layout(gpaths.setting("target_layout.json"))
    det = cc.make_detector()

    M = axis_map("+z", "-x")
    ang_true = np.array([2.0, -1.5, 1.0])
    c_true = np.array([3.76 * IN_TO_M + 0.004, 0.012, -0.015])
    Radj = rot_adj(*ang_true)
    R_true, t_true = Radj @ M, -Radj @ c_true
    # deliberately rough prior (what the overlay tool might have given)
    Radj_p = rot_adj(*(ang_true + [3.0, -2.5, 2.0]))
    prior_R, prior_t = Radj_p @ M, -Radj_p @ (c_true + [0.02, -0.02, 0.03])

    # wall-frame centre of the tags
    ctr = np.mean([v.mean(0) for v in layout.values()], axis=0)
    views = []
    poses = [(0, 0, 1.0), (15, 0, 1.1), (-15, 5, 1.2), (20, -10, 1.0), (-20, -8, 1.3),
             (8, 12, 1.1), (-8, 14, 0.95), (25, 6, 1.25), (-25, 0, 1.15), (0, -14, 1.05),
             (12, 18, 1.2), (-12, -12, 1.3)]
    for yaw, pitch, dist in poses:
        Rc = rodrigues([pitch * DEG, yaw * DEG, 0])          # camera <- wall rotation about tag centre
        # camera looks at the tag centre from distance `dist`
        R_cw = Rc
        t_cw = np.array([0, 0, dist]) - R_cw @ ctr
        img = render(layout, K, w, h, R_cw, t_cw, rng)
        pose = cc.detect_pose(det, img, K, dist0, layout)
        if not pose["solved"] or pose["n_tags"] < 3:
            print(f"  view yaw{yaw} pitch{pitch}: tags {pose['n_tags']} - skipped")
            continue
        pts = lidar_points(R_cw, t_cw, R_true, t_true, rng)
        n_p_true = None
        pred = (prior_R.T @ pose["n"], pose["d"] - pose["n"] @ prior_t)
        # LiDAR-frame predicted plane from prior: n_l = R^T n_c, d_l = d_c - n_c.t
        wall, why = cc.extract_wall_plane(pts, pred, prior_R, prior_t, K, w, h)
        if wall is None:
            print(f"  view yaw{yaw} pitch{pitch}: wall rejected: {why}")
            continue
        views.append(dict(n_c=pose["n"], d_c=pose["d"], n_l=wall["n"], d_l=wall["d"]))
        # truth for this view
        n_true = R_cw[:, 2]
        d_true = float(n_true @ t_cw)
        print(f"  yaw{yaw:>4} pitch{pitch:>4} dist{dist:.2f}: pnp rms {pose['rms']:.2f}px "
              f"normal err {np.degrees(cc.angle_between(pose['n'], n_true)):.2f} deg, "
              f"d err {(pose['d']-d_true)*1000:.1f} mm; wall inliers {wall['n_inliers']}")
    print(f"{len(views)} views usable")
    assert len(views) >= 6, "not enough views survived"
    sol = cc.solve_extrinsics(views, prior_R, prior_t)
    R, t = sol["R"], sol["t"]
    rot_err = np.degrees(cc.angle_between(np.array([1.0, 0, 0]), np.array([1.0, 0, 0])))
    dR = R @ R_true.T
    rot_err = np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))
    terr = (t - t_true) * 1000
    print(f"rotation error {rot_err:.2f} deg   (prior was {np.degrees(np.arccos(np.clip((np.trace(prior_R@R_true.T)-1)/2,-1,1))):.2f} deg off)")
    print(f"translation error mm {np.round(terr, 1)}  |t err| {np.linalg.norm(terr):.1f} mm "
          f"(prior {np.linalg.norm(prior_t-t_true)*1000:.0f} mm off)")
    print(f"reported sigma rot deg {np.round(sol['sigma_rot_deg'],2)}  sigma t mm {np.round(sol['sigma_t_mm'],1)}  chi2_red {sol['chi2_red']:.2f}")
    ok = rot_err < 0.7 and np.linalg.norm(terr) < 25
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
