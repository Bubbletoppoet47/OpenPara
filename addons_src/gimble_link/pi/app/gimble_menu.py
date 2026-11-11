#!/usr/bin/env python3
"""
gimble_menu.py - the Gimble's start screen: two big buttons for the two things the rig is for, and the rest below.

    RECORD DATA    camera + LiDAR, saved to dataset/ for training            (gimble_pi.py)
    TEST MODEL     run the trained model live; REC VIDEO there records it    (gimble_detect.py)
    CALIBRATE - VIEW DATA - MEASURE - SETUP - QUIT

A program that is started takes the whole screen; when it is closed (its QUIT) this screen comes back.
Keys: r record, t test, c calibrate, v view data, q quit.      Run: python3 gimble_menu.py   (--windowed, --screen 1024x600)
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("OpenCV missing: sudo apt install -y python3-opencv")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimble_paths as gpaths  # noqa: E402
import gimble_tidy  # noqa: E402

BG = (30, 30, 30)
TXT = (255, 255, 255)
DIM = (190, 190, 190)
GREEN = (60, 140, 60)
BLUE = (160, 100, 40)
GREY = (70, 70, 70)
WARN = (0, 165, 255)
PROGRAMS = {"record": ("gimble_pi.py", [], True), "test": ("gimble_detect.py", [], True), "calibrate": ("gimble_pi.py", ["--calibrate"], True),
            "view": ("view_dataset.py", [], False), "measure": ("measure_targets.py", [], False)}
NAMES = {"record": "Record data", "test": "Test model", "calibrate": "Calibrate", "view": "View data", "measure": "Measure targets",
         "setup": "First-time setup"}


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(gpaths.LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def text(img, s, org, scale=0.55, color=TXT, thick=1):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)       # on plain colours: no outline needed


# ---------------------------------------------------------------- what the start screen says about the drive

def recordings_info():
    n, newest = 0, None
    if os.path.isdir(gpaths.DATASET):
        subs = sorted(d for d in os.listdir(gpaths.DATASET) if os.path.isfile(os.path.join(gpaths.DATASET, d, "index.csv")))
        n, newest = len(subs), (subs[-1] if subs else None)
    try:
        free = shutil.disk_usage(gpaths.ROOT).free / 1e9
    except OSError:
        free = None
    return n, newest, free


def model_info():
    """(first line, second line, has a model) about the model Test model will run."""
    if not os.path.isfile(gpaths.MODEL_FILE):
        return "No model yet", "Send one from OpenPara", False
    meta = {}
    try:
        with open(os.path.splitext(gpaths.MODEL_FILE)[0] + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass
    label = str(meta.get("label") or (f"round {meta.get('round')}" if meta.get("round") is not None else "model"))
    kind = "boxes only" if meta.get("has_distance") is False else "boxes + distance"
    when = datetime.datetime.fromtimestamp(os.path.getmtime(gpaths.MODEL_FILE)).strftime("%Y-%m-%d")
    return label[:30], f"{kind}, put here {when}", True


def videos_info():
    if not os.path.isdir(gpaths.TEST_VIDEOS):
        return 0
    return len([f for f in os.listdir(gpaths.TEST_VIDEOS) if f.lower().endswith((".mp4", ".avi"))])


def calibration_info():
    try:
        with open(gpaths.setting("lidar_camera_extrinsics.json"), encoding="utf-8") as f:
            c = json.load(f).get("calibration")
        return f"Calibrated {c['saved'][:10]}, {c['views']} views" if c else "Alignment saved by hand", True
    except (OSError, ValueError, KeyError, TypeError):
        return "NOT CALIBRATED - tap CALIBRATE before recording", False


class Menu:
    def __init__(self, args):
        self.args = args
        self.sw, self.sh = (int(v) for v in args.screen.lower().split("x"))
        self.running = True
        self.msg, self.msg_until, self.msg_col = "", 0.0, TXT
        self.buttons = []                     # (key, (x0, y0, x1, y1))
        self.info_t = 0.0
        self.refresh()
        self.layout()

    def refresh(self):
        self.rec, self.model, self.videos, self.cal = recordings_info(), model_info(), videos_info(), calibration_info()
        self.info_t = time.time()

    def flash(self, s, secs=6.0, color=TXT):
        self.msg, self.msg_until, self.msg_col = s, time.time() + secs, color
        log(s)

    def layout(self):
        sw, sh = self.sw, self.sh
        pad = max(10, sw // 60)
        top, row_h = int(sh * 0.14), int(sh * 0.16)
        big_h = sh - top - row_h - 3 * pad - 26
        half = (sw - 3 * pad) // 2
        self.buttons = [("record", (pad, top, pad + half, top + big_h)), ("test", (2 * pad + half, top, sw - pad, top + big_h))]
        small = ["calibrate", "view", "measure", "setup", "quit"]
        w = (sw - (len(small) + 1) * pad) // len(small)
        y0 = top + big_h + pad
        for i, key in enumerate(small):
            x0 = pad + i * (w + pad)
            self.buttons.append((key, (x0, y0, x0 + w, y0 + row_h)))

    # ---- drawing
    def big(self, canvas, rect, color, title, lines):
        x0, y0, x1, y1 = rect
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, -1)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (200, 200, 200), 1)
        s = min(1.25, (x1 - x0) / 300.0)
        (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, s, 2)
        text(canvas, title, (x0 + (x1 - x0 - tw) // 2, y0 + int((y1 - y0) * 0.30) + th // 2), s, TXT, 2)
        y = y0 + int((y1 - y0) * 0.52)
        for line, col in lines:
            (lw, lh), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            text(canvas, line, (x0 + max(8, (x1 - x0 - lw) // 2), y), 0.5, col)
            y += lh + 12

    def compose(self):
        canvas = np.full((self.sh, self.sw, 3), BG, np.uint8)
        text(canvas, "Gimble", (14, int(self.sh * 0.09)), 0.95, TXT, 2)
        cal, cal_ok = self.cal
        (cw, _), _ = cv2.getTextSize(cal, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        text(canvas, cal, (self.sw - cw - 14, int(self.sh * 0.085)), 0.48, (0, 255, 0) if cal_ok else WARN)
        n, newest, free = self.rec
        label, kind, have = self.model
        for key, rect in self.buttons:
            if key == "record":
                self.big(canvas, rect, GREEN, "RECORD DATA", [
                    ("camera + LiDAR, for training", TXT),
                    (f"{n} recording{'s' if n != 1 else ''} on the drive" + (f", newest {newest[:8]}" if newest else ""), DIM),
                    (f"{free:.1f} GB free" if free is not None else "", DIM if (free or 9) > 1.0 else WARN)])
            elif key == "test":
                self.big(canvas, rect, BLUE if have else GREY, "TEST MODEL", [
                    (label, TXT if have else WARN), (kind, DIM),
                    (f"REC VIDEO there saves the test ({self.videos} saved)", DIM)])
            else:
                x0, y0, x1, y1 = rect
                cv2.rectangle(canvas, (x0, y0), (x1, y1), GREY, -1)
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (150, 150, 150), 1)
                name = {"calibrate": "CALIBRATE", "view": "VIEW DATA", "measure": "MEASURE", "setup": "SETUP", "quit": "QUIT"}[key]
                (tw, th), _ = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.putText(canvas, name, (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TXT, 1, cv2.LINE_AA)
        if time.time() < self.msg_until:
            text(canvas, self.msg[:110], (14, self.sh - 10), 0.45, self.msg_col)
        else:
            text(canvas, f"Gimble programs {gpaths.version()}   -   {gpaths.ROOT}"[:110], (14, self.sh - 10), 0.4, (150, 150, 150))
        return canvas

    # ---- input
    def on_mouse(self, event, x, y, flags, _):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for key, (x0, y0, x1, y1) in self.buttons:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.pending = key
                return

    def on_key(self, k):
        ch = chr(k) if 0 < k < 128 else ""
        m = {"r": "record", "t": "test", "c": "calibrate", "v": "view", "q": "quit"}
        if k == 27:
            self.pending = "quit"
        elif ch in m:
            self.pending = m[ch]

    # ---- starting a program
    def command(self, key):
        script, extra, sized = PROGRAMS[key]
        cmd = [sys.executable or "python3", os.path.join(HERE, script)] + extra
        if sized:
            cmd += ["--screen", self.args.screen] + (["--windowed"] if self.args.windowed else [])
        return cmd

    def start(self, key):
        """Runs the program and waits for it; returns its exit code (None when it could not be started)."""
        cmd = self.command(key)
        log(f"Start: {NAMES[key]}")
        try:
            with open(gpaths.LOG_FILE, "a") as lf:
                return subprocess.call(cmd, cwd=gpaths.ROOT, stderr=lf)
        except OSError as e:
            log(f"could not start {cmd}: {e}")
            return None

    def setup(self):
        script = os.path.join(HERE, "setup_pi.sh")
        for term in (["x-terminal-emulator", "-e"], ["lxterminal", "-e"], ["xterm", "-e"]):
            if shutil.which(term[0]):
                try:
                    subprocess.Popen(term + ["bash", "-c", f'bash "{script}"; echo; read -p "Done - press Enter to close" x'])
                    return True
                except OSError:
                    pass
        return False

    def do(self, key):
        if key == "quit":
            self.running = False
            return
        if key == "setup":
            if not self.setup():
                self.flash("Open a terminal in the app folder and run:  bash setup_pi.sh", 10, WARN)
            return
        if key == "test" and not self.model[2]:
            self.flash("No model on the drive yet: send one from OpenPara (Annotator > File > Gimble: Send a Model)", 8, WARN)
            return
        self.close_window()
        code = self.start(key)
        self.open_window()
        self.refresh()
        if code is None:
            self.flash(f"{NAMES[key]} could not be started - see logs/gimble_log.txt", 10, WARN)
        elif code != 0:
            self.flash(f"{NAMES[key]} ended with a problem (code {code}) - see logs/gimble_log.txt", 10, WARN)

    def open_window(self):
        cv2.namedWindow("Gimble", cv2.WINDOW_NORMAL)
        if not self.args.windowed:
            cv2.setWindowProperty("Gimble", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        else:
            cv2.resizeWindow("Gimble", self.sw, self.sh)
        cv2.setMouseCallback("Gimble", self.on_mouse)

    def close_window(self):
        cv2.destroyAllWindows()
        for _ in range(3):
            cv2.waitKey(1)

    def run(self):
        self.pending = None
        moved = gimble_tidy.tidy()
        if moved:
            self.flash(f"Tidied the drive: {moved} old file{'s' if moved != 1 else ''} moved to old/ (nothing recorded was touched)", 10)
        self.open_window()
        log(f"Start screen. programs {gpaths.version()}, screen {self.sw}x{self.sh}")
        try:
            while self.running:
                if time.time() - self.info_t > 5:
                    self.refresh()
                cv2.imshow("Gimble", self.compose())
                self.on_key(cv2.waitKey(80) & 0xFF)
                if self.pending:
                    key, self.pending = self.pending, None
                    self.do(key)
                elif self.args.windowed and cv2.getWindowProperty("Gimble", cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            cv2.destroyAllWindows()


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screen", default="800x480", help="Screen size WxH (default 800x480, the official 7in touchscreen)")
    ap.add_argument("--windowed", action="store_true", help="Normal window instead of fullscreen")
    return ap


def main():
    args = build_parser().parse_args()
    try:
        Menu(args).run()
    except Exception:  # noqa: BLE001
        import traceback
        log("CRASH (start screen):\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
