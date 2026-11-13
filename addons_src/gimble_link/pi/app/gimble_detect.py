#!/usr/bin/env python3
"""
gimble_detect.py - run your trained Gimble model live on the Raspberry Pi.

Same screen, camera, LiDAR and dot-range controls as gimble_pi.py, plus the model's detections:
every box shows  class  confidence  and the model's own DISTANCE estimate; when the LiDAR is running it
also shows what the LiDAR measures inside that box, so you can see how far off the model is.

    ONLY the camera is needed for the model; the LiDAR is optional (a yardstick).

Model files (sent from OpenPara: Annotator > File > Gimble: Send a Model; or made on the PC by export_pi.py), in the drive's model/ folder:
    model/gimble_model.onnx     model/gimble_model.json
A model that only finds boxes (an "Assist" model, has_distance false in the .json) is shown without a distance of its own.
A model trained as two models (a detector, then a distance model; "parts" in the .json) arrives as the same one file: the conversion
on the PC joins them, so nothing here runs differently.  Its distance model looks only at the surer boxes; a box it did not look at
has the distance 0.0 and is shown without one.
A .pt file (the model as the PC trains it) cannot run here - there is no PyTorch on the Pi.  It has to be SENT from OpenPara, which
converts it; a .pt copied into model/ by hand is named on the screen so it is clear why nothing runs.

REC VIDEO records what you see - the picture with the boxes, classes and distances drawn in - to test_videos/<date_time>.mp4, and writes
every prediction of every recorded frame to test_videos/<date_time>.csv (class, confidence, box, the model's distance, the LiDAR's).

Buttons: REC VIDEO / STOP, DOTS (LiDAR dots on/off), RANGE (dot range), CONF (detection threshold, cycles), CAM, QUIT (tap twice).
Keys:    r record, d dots, m range, c conf threshold, q quit.
Run:     python3 gimble_detect.py            (--windowed to try it in a window, --conf 0.4, --model path, --video-fps 10)
Needs:   pip install onnxruntime (see setup_pi.sh) - no PyTorch / Ultralytics on the Pi.
"""
import csv
import datetime
import json
import os
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

import gimble_paths as gpaths  # noqa: E402
import gimble_pi as gp  # noqa: E402
from lidar_camera_overlay import project  # noqa: E402

CONF_STEPS = [0.25, 0.35, 0.5, 0.7]
PALETTE = [(60, 60, 255), (60, 200, 60), (255, 160, 40), (0, 200, 255), (220, 80, 220), (200, 200, 60),
           (120, 120, 255), (160, 255, 160), (255, 200, 120)]


# ---------------------------------------------------------------- model helpers (also used by the tests)

def preprocess(frame_bgr, S):
    """Same letterbox as training. Returns (1,3,S,S) float32 RGB 0-1, scale, pad_x, pad_y."""
    h, w = frame_bgr.shape[:2]
    r = S / max(h, w)
    nh, nw = max(1, round(h * r)), max(1, round(w * r))
    img = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
    top, left = (S - nh) // 2, (S - nw) // 2
    canvas = np.full((S, S, 3), 114, np.uint8)
    canvas[top:top + nh, left:left + nw] = img
    x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return np.ascontiguousarray(x), r, left, top


def postprocess(dets, dist, shape, r, left, top, conf):
    """dets (300,6) letterboxed pixels -> list of dict in original-image pixels."""
    h, w = shape[:2]
    out = []
    for row, d in zip(dets, dist):
        if row[4] < conf:
            continue
        x1, y1, x2, y2 = (row[0] - left) / r, (row[1] - top) / r, (row[2] - left) / r, (row[3] - top) / r
        x1, x2 = float(np.clip(x1, 0, w - 1)), float(np.clip(x2, 0, w - 1))
        y1, y2 = float(np.clip(y1, 0, h - 1)), float(np.clip(y2, 0, h - 1))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        out.append(dict(box=(x1, y1, x2, y2), conf=float(row[4]), cls=int(row[5]), dist=float(d), lidar=None))
    return out


def no_model_text(model_dir):
    """What to say when model/ has no gimble_model.onnx: how to get one - and, when a .pt lies there, that a .pt cannot run here."""
    try:
        pts = sorted(f for f in os.listdir(model_dir) if f.lower().endswith(".pt"))
    except OSError:
        pts = []
    if pts:
        return f"{pts[0]} cannot run here (a .pt needs the PC). Send it from OpenPara: Annotator > File > Gimble: Send a Model"
    return "No model yet: send one from OpenPara (Annotator > File > Gimble: Send a Model)"


def has_distance(d):
    """True when the model worked out a distance for this box (0 = it did not: the box was not sure enough for the distance model)."""
    return d["dist"] > 0


def lidar_in_box(u, v, z, box, shrink=0.2):
    """Median LiDAR depth of the points inside the middle of the box (None if fewer than 3)."""
    x1, y1, x2, y2 = box
    mx, my = (x2 - x1) * shrink, (y2 - y1) * shrink
    m = (u >= x1 + mx) & (u <= x2 - mx) & (v >= y1 + my) & (v <= y2 - my)
    if m.sum() < 3:
        return None
    return float(np.median(z[m]))


class DetApp(gp.App):
    def __init__(self, args):
        self.conf_i = min(range(len(CONF_STEPS)), key=lambda i: abs(CONF_STEPS[i] - args.conf))
        self.results, self.res_t, self.infer_ms, self.fps = [], 0.0, 0.0, 0.0
        self.model_msg = ""
        self.sess, self.meta, self.S, self.names = None, {}, 640, []
        self.has_dist = True                      # False for a model that only finds boxes: no distance of its own is shown
        self.vid = None                           # the video being recorded: {"wr", "csv_f", "csv", "path", "t0", "next", "n"}
        self.load_model(args.model)
        super().__init__(args)

    # ---- model ----
    def load_model(self, path):
        try:
            import onnxruntime as ort
        except ImportError:
            self.model_msg = "onnxruntime missing - run setup_pi.sh (or: pip install onnxruntime)"
            return
        if not os.path.exists(path):
            self.model_msg = no_model_text(os.path.dirname(path))
            return
        try:
            so = ort.SessionOptions()
            so.intra_op_num_threads = 4
            self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            with open(os.path.splitext(path)[0] + ".json", encoding="utf-8") as f:
                self.meta = json.load(f)
            self.S = int(self.meta.get("imgsz", 640))
            self.names = list(self.meta.get("names", []))
            self.has_dist = self.meta.get("has_distance", True) is not False
            gp.log(f"Model loaded: {path} ({self.model_label()}" + ("" if self.has_dist else ", boxes only - no distance of its own")
                   + (f", {self.meta['parts']}" if self.meta.get("parts") else "") + ")")
        except Exception as e:  # noqa: BLE001
            self.sess = None
            self.model_msg = f"Could not load model: {e}"

    def model_label(self):
        m = self.meta
        return str(m.get("label") or (f"round {m.get('round')}" if m.get("round") is not None else m.get("source") or "model"))

    def detect(self, frame):
        x, r, left, top = preprocess(frame, self.S)
        dets, dist = self.sess.run(None, {"images": x})
        return postprocess(dets, dist, frame.shape, r, left, top, CONF_STEPS[self.conf_i])

    def infer_loop(self):
        last_t = 0.0
        while self.running:
            if self.sess is None or self.frame is None or self.frame_t == last_t:
                time.sleep(0.01)
                continue
            fr, last_t = self.frame.copy(), self.frame_t
            t0 = time.time()
            try:
                res = self.detect(fr)
            except Exception as e:  # noqa: BLE001
                self.model_msg = f"Inference error: {e}"
                time.sleep(0.5)
                continue
            if self.rx is not None and self.rx.alive() and res:
                pts = self.rx.snapshot(window=self.args.window)
                if len(pts):
                    u, v, z = project(pts[:, :3] @ self.R.T + self.t, self.K, self.dist, self.w, self.h, zmin=0.02)
                    keep = (z >= self.rmin) & (z <= self.rmax)
                    for d in res:
                        d["lidar"] = lidar_in_box(u[keep], v[keep], z[keep], d["box"])
            dt = time.time() - t0
            self.infer_ms = dt * 1000
            self.fps = 0.8 * self.fps + 0.2 / max(time.time() - self.res_t, 1e-3) if self.res_t else 1 / max(dt, 1e-3)
            self.results, self.res_t = res, time.time()

    # ---- buttons ----
    def layout_buttons(self):
        self.live_keys = ["rec", "dots", "range", "conf", "cam", "quit"]
        self.calib_keys = self.live_keys
        n = len(self.live_keys)
        bh = min(gp.BTN_H + 8, self.sh // n)
        x0 = self.sw - gp.PANEL_W
        self.btn_rects = [(x0 + 5, i * bh + 4, self.sw - 5, i * bh + 4 + bh - 8) for i in range(n)]

    def label_for(self, key):
        if key == "conf":
            return f"CONF {CONF_STEPS[self.conf_i]:.2f}", gp.BTN_BG
        if key == "rec":
            return ("STOP", gp.BTN_RED) if self.vid else ("REC VIDEO", gp.BTN_BG)
        return super().label_for(key)

    def press(self, key):
        if key == "conf":
            self.conf_i = (self.conf_i + 1) % len(CONF_STEPS)
        elif key == "rec":
            self.stop_video() if self.vid else self.start_video()
        elif key in ("dots", "range", "cam", "quit"):
            super().press(key)

    # ---- recording the test as a video (what is on the screen, with the predictions) ----
    def start_video(self):
        if self.frame is None:
            self.flash("No camera picture yet - nothing to record", 4)
            return
        try:
            os.makedirs(self.args.video_dir, exist_ok=True)
        except OSError as e:
            self.flash(f"Cannot make {self.args.video_dir}: {e}", 6)
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fps = max(1.0, float(self.args.video_fps))
        wr = path = None
        for ext, four in ((".mp4", "mp4v"), (".avi", "MJPG")):         # .mp4 where this OpenCV can write it, else .avi
            path = os.path.join(self.args.video_dir, stamp + ext)
            wr = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*four), fps, (self.vw, self.vh))
            if wr.isOpened():
                break
            wr.release()
            wr = None
            try:
                os.remove(path)
            except OSError:
                pass
        if wr is None:
            self.flash("This OpenCV cannot write a video file here", 6)
            return
        csv_f = open(os.path.join(self.args.video_dir, stamp + ".csv"), "w", newline="")
        table = csv.writer(csv_f)
        table.writerow(["frame", "time_s", "class", "confidence", "x1", "y1", "x2", "y2", "model_distance_m", "lidar_distance_m"])
        with open(os.path.join(self.args.video_dir, stamp + ".json"), "w") as f:
            json.dump(dict(started=datetime.datetime.now().isoformat(timespec="seconds"), video=os.path.basename(path), fps=fps,
                           frame_size=[self.vw, self.vh], image_size=[self.w, self.h], model=self.meta, model_file=self.args.model,
                           confidence_threshold=CONF_STEPS[self.conf_i], lidar=bool(self.rx is not None and self.rx.alive()),
                           calibration_note=self.calib_note,
                           note="boxes in the .csv are in pixels of the camera image (image_size); the video is that image scaled to "
                                "frame_size with everything drawn in"), f, indent=2)
        self.vid = dict(wr=wr, csv_f=csv_f, csv=table, path=path, t0=time.time(), next=0.0, n=0, step=1.0 / fps)
        self.flash(f"Recording video: {os.path.basename(path)}")

    def stop_video(self, quiet=False):
        v, self.vid = self.vid, None
        if v is None:
            return
        try:
            v["wr"].release()
            v["csv_f"].close()
        except Exception:  # noqa: BLE001
            pass
        text = f"Video saved: test_videos/{os.path.basename(v['path'])}  ({v['n'] * v['step']:.0f} s)"
        gp.log(text) if quiet else self.flash(text, 5)

    def video_frame(self, img, shown):
        """Writes the picture as it is shown (boxes, classes, distances drawn in) and the predictions on it, at the video's own pace."""
        v = self.vid
        now = time.time()
        if now < v["next"]:
            return
        v["next"] = max(v["next"] + v["step"], now - v["step"]) if v["next"] else now + v["step"]
        out = img.copy()
        stamp = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
        (tw, _th), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        gp.shadow_text(out, stamp, (self.vw - tw - 10, 18), 0.45, (255, 255, 255))            # when this was (the model's name is bottom left)
        try:
            v["wr"].write(out)
            t = f"{now - v['t0']:.2f}"
            if not shown:
                v["csv"].writerow([v["n"], t, "", "", "", "", "", "", "", ""])
            for d in shown:
                name = self.names[d["cls"]] if d["cls"] < len(self.names) else str(d["cls"])
                v["csv"].writerow([v["n"], t, name, f"{d['conf']:.3f}"] + [f"{c:.0f}" for c in d["box"]]
                                  + [f"{d['dist']:.2f}" if self.has_dist and has_distance(d) else "", f"{d['lidar']:.2f}" if d["lidar"] is not None else ""])
            v["n"] += 1
            if v["n"] % 50 == 0:
                v["csv_f"].flush()
                if shutil.disk_usage(self.args.video_dir).free < 300 * 1024 * 1024:
                    self.stop_video()
                    self.flash("Drive nearly full - video stopped", 8)
        except (OSError, cv2.error) as e:
            self.stop_video(quiet=True)
            self.flash(f"Video stopped: {e}", 8)

    def on_key(self, k):
        if k in (255, 0xFF) or k < 0:
            return
        ch = chr(k) if 0 < k < 128 else ""
        if self.edit is not None:
            self.edit_key(k, ch)
            return
        if k == 27 or ch == "q":
            self.running = False
        elif ch == "r":
            self.press("rec")
        elif ch == "d":
            self.press("dots")
        elif ch == "m":
            self.press("range")
        elif ch == "c":
            self.press("conf")

    # ---- drawing ----
    def video_live(self, frame):
        img = super().video_live(frame)
        s = self.scale
        stale = time.time() - self.res_t > 1.5
        shown = [] if stale else sorted(self.results, key=lambda d: d["conf"])
        if not stale:
            for d in shown:
                x1, y1, x2, y2 = (int(v * s) for v in d["box"])
                col = PALETTE[d["cls"] % len(PALETTE)]
                name = self.names[d["cls"]] if d["cls"] < len(self.names) else str(d["cls"])
                cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
                own = self.has_dist and has_distance(d)
                txt = f"{name} {d['conf']:.2f}" + (f"  {d['dist']:.1f} m" if own else "")
                if d["lidar"] is not None:
                    txt += f"  (LiDAR {d['lidar']:.1f})" if own else f"  LiDAR {d['lidar']:.1f} m"
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                ty = y1 - 4 if y1 - th - 6 > 0 else y1 + th + 6
                cv2.rectangle(img, (x1, ty - th - 4), (x1 + tw + 6, ty + 3), col, -1)
                cv2.putText(img, txt, (x1 + 3, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        if self.sess is None:
            gp.shadow_text(img, self.model_msg, (8, 60), 0.5, (0, 165, 255))
        else:
            info = f"{self.model_label()}  {self.infer_ms:.0f} ms  {self.fps:.1f} fps  boxes {len(self.results)}"
            gp.shadow_text(img, info, (8, self.vh - 28), 0.42, (220, 220, 220))
            if self.model_msg:
                gp.shadow_text(img, self.model_msg, (8, 60), 0.5, (0, 165, 255))
        if self.vid is not None:
            self.video_frame(img, shown)
            if self.vid is not None:                 # the mark that it is recording is on the screen only, not in the video
                el = time.time() - self.vid["t0"]
                cv2.circle(img, (self.vw - 150, 16), 7, (0, 0, 255), -1)
                gp.shadow_text(img, f"REC VIDEO {int(el // 60):02d}:{int(el % 60):02d}", (self.vw - 136, 21), 0.5, (120, 120, 255))
        return img

    def run(self):
        th = threading.Thread(target=self.infer_loop, daemon=True)
        th.start()
        try:
            super().run()
        finally:
            self.running = False
            self.stop_video(quiet=True)
            th.join(timeout=3)                    # let the picture that is being looked at finish before the program ends


def build_parser():
    ap = gp.build_parser()
    ap.description = "Run the trained Gimble model live (see the top of gimble_detect.py)"
    ap.add_argument("--model", default=gpaths.MODEL_FILE)
    ap.add_argument("--video-dir", default=gpaths.TEST_VIDEOS, help="Where REC VIDEO saves (default: test_videos/ on the drive)")
    ap.add_argument("--video-fps", type=float, default=10.0, help="Frames per second of a recorded video")
    ap.add_argument("--conf", type=float, default=0.35, help="Detection threshold (also the CONF button)")
    return ap


def main():
    args = build_parser().parse_args()
    try:
        DetApp(args).run()
    except Exception:  # noqa: BLE001
        import traceback
        gp.log("CRASH:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
