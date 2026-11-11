#!/usr/bin/env python3
"""
view_dataset.py - page through a recorded session with the LiDAR depth shown on top of the image.

    python3 view_dataset.py                 # newest session in ./dataset
    python3 view_dataset.py dataset/20260930_101500

Tap the right half of the picture (or press -> / space) for next, the left half (or <-) for previous,
d toggles the depth overlay, q quits.
"""
import csv
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gimble_paths as gpaths  # noqa: E402


def newest_session():
    root = gpaths.DATASET
    subs = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "index.csv"))) \
        if os.path.isdir(root) else []
    return os.path.join(root, subs[-1]) if subs else None


def main():
    sess = sys.argv[1] if len(sys.argv) > 1 else newest_session()
    if not sess or not os.path.isdir(sess):
        sys.exit("No session found. Record something first.")
    with open(os.path.join(sess, "index.csv")) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("Session is empty.")
    state = dict(i=0, dots=True)

    def show():
        r = rows[state["i"]]
        img = cv2.imread(os.path.join(sess, r["image"]))
        depth = cv2.imread(os.path.join(sess, r["depth"]), cv2.IMREAD_UNCHANGED)
        if state["dots"] and depth is not None:
            vi, ui = np.nonzero(depth)
            z = depth[vi, ui] / 1000.0
            t = np.clip((z - 0.5) / 5.5, 0, 1)
            col = cv2.applyColorMap((255 * (1 - t)).astype(np.uint8).reshape(-1, 1), cv2.COLORMAP_TURBO).reshape(-1, 3)
            for dx in (0, 1):
                for dy in (0, 1):
                    img[np.clip(vi + dy, 0, img.shape[0] - 1), np.clip(ui + dx, 0, img.shape[1] - 1)] = col
        cv2.putText(img, f"{state['i'] + 1}/{len(rows)}  {r['depth_pixels']} depth px  sharp {r['sharpness']}",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, f"{state['i'] + 1}/{len(rows)}  {r['depth_pixels']} depth px  sharp {r['sharpness']}",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow("dataset", img)

    def mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN:
            w = rows and cv2.getWindowImageRect("dataset")[2] or 640
            state["i"] = (state["i"] + (1 if x > w / 2 else -1)) % len(rows)
            show()

    cv2.namedWindow("dataset", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("dataset", mouse)
    show()
    while True:
        k = cv2.waitKey(50) & 0xFF
        if k in (ord("q"), 27):
            break
        if k in (ord(" "), 83, ord("n")):
            state["i"] = (state["i"] + 1) % len(rows); show()
        elif k in (81, ord("p")):
            state["i"] = (state["i"] - 1) % len(rows); show()
        elif k == ord("d"):
            state["dots"] = not state["dots"]; show()
        if cv2.getWindowProperty("dataset", cv2.WND_PROP_VISIBLE) < 1:
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
