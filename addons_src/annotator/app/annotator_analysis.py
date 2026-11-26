"""
annotator_analysis.py - post-analysis of a recorded Gimble session: run a model over the photos, compare what it says (class + distance)
with the LiDAR returns inside each box, and count what holds up.

No toolkit in here (numpy and PIL only), so it is all testable without a window; annotator_window.py / annotator_analyse.py show it.

A session is the folder the Gimble rig records:  images/N.jpg, depth/N.png (16-bit millimetres, 0 = no LiDAR return, the photo's pixel grid),
index.csv, meta.json.  Nothing in it is changed or copied.

How a box is judged.  The model is run once, down to FLOOR confidence, and every detection is kept; the confidence slider only filters
afterwards, so moving it (or the tolerance) is instant.  For each box the LiDAR returns inside it give three numbers to compare with the
model's distance:
    closest point   the return nearest to the predicted distance (forgives LiDAR that lags the picture: any one return that agrees is enough)
    median          the median of the returns (what the Pi itself reports, from the middle 60 % of the box)
    average         the mean of the returns (the harshest: wall behind a person pulls it away)
A method PASSES when its number is within `tol` (a fraction, 0.10 = 10 %) of the predicted distance and FAILS when it is not.  A box with fewer
than MIN_POINTS returns has no reference ("no LiDAR"), and a detection without a distance (a model that does not give one) has nothing to
compare: neither passes or fails, they are counted on their own.
"""
import base64
import csv
import html
import json
import os

import numpy as np
from PIL import Image

FLOOR = 0.10                      # the lowest confidence the model is asked for; the slider filters above it
MIN_POINTS = 3                    # fewer LiDAR returns in a box than this: no reference
CORE_FRACTION = 0.6               # "core" region: the middle part of a box (the Pi measures there)
METHODS = ("closest", "median", "average")
METHOD_NAMES = {"closest": "Closest point", "median": "Median of points", "average": "Average of points"}
BANDS = ((0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0), (8.0, 10.0), (10.0, None))      # metres, of the LiDAR median
STATES = ("pass", "fail", "none", "empty")


def band_label(lo, hi):
    return f"{lo:g}-{hi:g} m" if hi is not None else f"{lo:g} m and more"


# ---------------------------------------------------------------------------------------------- a session
class Frame:
    __slots__ = ("index", "key", "image", "depth")

    def __init__(self, index, key, image, depth):
        self.index, self.key, self.image, self.depth = index, key, image, depth


class Session:
    def __init__(self, folder, frames, meta):
        self.folder, self.frames, self.meta = folder, frames, meta
        self.name = os.path.basename(os.path.normpath(folder))

    def __len__(self):
        return len(self.frames)


def is_session(path):
    return os.path.isdir(os.path.join(path, "images")) and (os.path.isfile(os.path.join(path, "index.csv")) or os.path.isdir(os.path.join(path, "depth")))


def find_sessions(path):
    """[session folder, ...]: the folder itself if it is one, else the sessions inside it (a dataset folder), sorted."""
    if is_session(path):
        return [path]
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return []
    return [os.path.join(path, n) for n in names if is_session(os.path.join(path, n))]


def open_session(folder):
    """The session's frames in the order they were recorded (index.csv when there is one, else the photos by name)."""
    if not is_session(folder):
        raise ValueError(f"Not a recorded session (needs an images folder and index.csv or depth): {folder}")
    frames = []
    index = os.path.join(folder, "index.csv")
    if os.path.isfile(index):
        with open(index, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                img = os.path.join(folder, row.get("image") or "")
                if not row.get("image") or not os.path.isfile(img):
                    continue
                dep = os.path.join(folder, row["depth"]) if row.get("depth") else None
                frames.append((os.path.splitext(os.path.basename(img))[0], img, dep if dep and os.path.isfile(dep) else None))
    else:
        for n in sorted(os.listdir(os.path.join(folder, "images"))):
            if n.lower().endswith((".jpg", ".jpeg", ".png")):
                stem = os.path.splitext(n)[0]
                dep = os.path.join(folder, "depth", stem + ".png")
                frames.append((stem, os.path.join(folder, "images", n), dep if os.path.isfile(dep) else None))
    if not frames:
        raise ValueError(f"No photos found in {folder}")
    meta = {}
    try:
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        pass
    return Session(folder, [Frame(i, k, im, dp) for i, (k, im, dp) in enumerate(frames)], meta)


def depth_points(path):
    """(u, v, z_m): the LiDAR returns of one frame (pixel columns, rows, metres), or three empty arrays."""
    if not path:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    try:
        with Image.open(path) as im:
            d = np.array(im)
    except (OSError, ValueError):
        return np.zeros(0), np.zeros(0), np.zeros(0)
    v, u = np.nonzero(d)
    return u.astype(np.float32), v.astype(np.float32), d[v, u].astype(np.float32) / 1000.0


# ---------------------------------------------------------------------------------------------- one box
class Detection:
    __slots__ = ("cls", "conf", "box", "pred")

    def __init__(self, cls, conf, box, pred):
        self.cls, self.conf, self.box, self.pred = cls, float(conf), tuple(float(v) for v in box), (None if pred is None else float(pred))


class BoxStats:
    """What the LiDAR says inside one box: how many returns, and the three numbers (None without a reference)."""
    __slots__ = ("n", "avg", "med", "closest", "closest_uv")

    def __init__(self, n, avg=None, med=None, closest=None, closest_uv=None):
        self.n, self.avg, self.med, self.closest, self.closest_uv = n, avg, med, closest, closest_uv

    def value(self, method):
        return {"closest": self.closest, "median": self.med, "average": self.avg}[method]


def region_box(box, region):
    """The part of a box the returns are taken from: all of it ("box") or its middle CORE_FRACTION ("core")."""
    x1, y1, x2, y2 = box
    if region != "core":
        return box
    cx, cy, hw, hh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2 * CORE_FRACTION, (y2 - y1) / 2 * CORE_FRACTION
    return cx - hw, cy - hh, cx + hw, cy + hh


def points_in_box(points, box, region="box"):
    u, v, z = points
    x1, y1, x2, y2 = region_box(box, region)
    return (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2)


def box_stats(points, det, region="box"):
    u, v, z = points
    inside = points_in_box(points, det.box, region)
    n = int(inside.sum())
    if n < MIN_POINTS:
        return BoxStats(n)
    zi = z[inside]
    closest = uv = None
    if det.pred is not None:
        k = int(np.argmin(np.abs(zi - det.pred)))
        closest, uv = float(zi[k]), (float(u[inside][k]), float(v[inside][k]))
    return BoxStats(n, float(zi.mean()), float(np.median(zi)), closest, uv)


def judge(pred, value, tol):
    """True: within tol of the predicted distance; False: not; None: nothing to compare (no prediction or no reference)."""
    if pred is None or value is None or pred <= 0:
        return None
    return abs(value - pred) <= tol * pred


def error_fraction(pred, value):
    return None if pred is None or value is None or pred <= 0 else abs(value - pred) / pred


# ---------------------------------------------------------------------------------------------- running it
class FrameResult:
    __slots__ = ("dets", "stats")

    def __init__(self, dets, stats):
        self.dets, self.stats = dets, stats


class Analysis:
    """One run: for every frame reached, the detections (down to FLOOR) and their LiDAR numbers.  Settings are not part of it."""

    def __init__(self, session, model="", region="box"):
        self.session, self.model, self.region = session, model, region
        self.frames = [None] * len(session)            # FrameResult, or None for a frame not reached (stopped, or not run yet)
        self.finished = False

    @property
    def analysed(self):
        return sum(1 for f in self.frames if f is not None)


def run_into(an, predict, progress=None, stop=None, region="box"):
    """Fills `an` frame by frame (so a screen can show the frames reached so far).  predict(image_path) ->
    [(class name, confidence, x1, y1, x2, y2, distance_m or None)], pixel boxes, down to FLOOR.
    progress(done, total) after each frame; stop() -> True ends the run early (what was done is kept)."""
    total = len(an.session)
    for fr in an.session.frames:
        if stop is not None and stop():
            return an
        dets = [Detection(c, conf, (x1, y1, x2, y2), d) for (c, conf, x1, y1, x2, y2, d) in predict(fr.image) if conf >= FLOOR]
        pts = depth_points(fr.depth)
        an.frames[fr.index] = FrameResult(dets, [box_stats(pts, d, region) for d in dets])
        if progress is not None:
            progress(fr.index + 1, total)
    an.finished = True
    return an


def run(session, predict, progress=None, stop=None, region="box", model=""):
    """A whole run in one call (see run_into)."""
    return run_into(Analysis(session, model, region), predict, progress, stop, region)


def restat(an, region, progress=None, stop=None):
    """The LiDAR numbers again for another region of the box (the model is not run again)."""
    an.region = region
    total = len(an.session)
    for fr in an.session.frames:
        if stop is not None and stop():
            return
        res = an.frames[fr.index]
        if res is None:
            continue
        pts = depth_points(fr.depth)
        res.stats = [box_stats(pts, d, region) for d in res.dets]
        if progress is not None:
            progress(fr.index + 1, total)


class AssistPredictor:
    """Makes the annotator's model objects (gimble_assist) fit run(): class names, pixel boxes, the distance when the model gives one."""

    def __init__(self, assist):
        self.assist = assist
        self.has_distance = hasattr(assist, "predict_detections")

    def __call__(self, image_path):
        with Image.open(image_path) as im:
            w, h = im.size
        names = list(getattr(self.assist, "class_names", []) or [])
        out = []
        if self.has_distance:
            raw = [(c, xc, yc, bw, bh, conf, dist) for (c, xc, yc, bw, bh, conf, dist) in self.assist.predict_detections(image_path, conf_threshold=FLOOR)]
        else:
            raw = [(c, xc, yc, bw, bh, 1.0, None) for (c, xc, yc, bw, bh) in self.assist.predict_boxes(image_path, conf_threshold=FLOOR)]
        for c, xc, yc, bw, bh, conf, dist in raw:
            name = names[c] if 0 <= c < len(names) else f"class {c}"
            out.append((name, conf, (xc - bw / 2) * w, (yc - bh / 2) * h, (xc + bw / 2) * w, (yc + bh / 2) * h, dist))
        return out


# ---------------------------------------------------------------------------------------------- what the settings make of a run
class Settings:
    def __init__(self, conf=0.85, tol=0.10, method="closest"):
        self.conf, self.tol, self.method = conf, tol, method


def verdicts(det, st, tol):
    """{method: True / False / None} for one box."""
    return {m: judge(det.pred, st.value(m), tol) for m in METHODS}


class Evaluation:
    def __init__(self):
        self.boxes = 0                       # detections at or above the confidence, over the frames analysed
        self.counts = {m: [0, 0] for m in METHODS}        # [pass, fail]
        self.no_lidar = 0                    # boxes with too few returns
        self.no_distance = 0                 # boxes the model gave no distance for
        self.bands = []                      # [(label, n judged, n passed)] by LiDAR median, for the chosen method
        self.state = []                      # per frame: "pass" / "fail" / "none" / "empty" (None: not analysed)
        self.with_fail = []                  # frame indices
        self.with_no_lidar = []

    def percent(self, method):
        p, f = self.counts[method]
        return None if p + f == 0 else 100.0 * p / (p + f)


def evaluate(an, settings):
    ev = Evaluation()
    bands = [[0, 0] for _ in BANDS]
    for fi, res in enumerate(an.frames):
        if res is None:
            ev.state.append(None)
            continue
        kept = [(d, s) for d, s in zip(res.dets, res.stats) if d.conf >= settings.conf]
        fail = ok = nolidar = False
        for d, s in kept:
            ev.boxes += 1
            vs = verdicts(d, s, settings.tol)
            if s.n < MIN_POINTS:
                ev.no_lidar += 1
                nolidar = True
            if d.pred is None:
                ev.no_distance += 1
            for m in METHODS:
                if vs[m] is not None:
                    ev.counts[m][0 if vs[m] else 1] += 1
            mine = vs[settings.method]
            if mine is True:
                ok = True
            elif mine is False:
                fail = True
            if mine is not None and s.med is not None:
                for bi, (lo, hi) in enumerate(BANDS):
                    if s.med >= lo and (hi is None or s.med < hi):
                        bands[bi][0] += 1
                        bands[bi][1] += 1 if mine else 0
                        break
        ev.state.append("fail" if fail else "pass" if ok else "none" if kept else "empty")
        if fail:
            ev.with_fail.append(fi)
        if nolidar:
            ev.with_no_lidar.append(fi)
    ev.bands = [(band_label(lo, hi), n, p) for (lo, hi), (n, p) in zip(BANDS, bands)]
    return ev


def rows(an, settings):
    """One dict per box at or above the confidence, with everything the CSV and the Boxes list show."""
    out = []
    for fi, res in enumerate(an.frames):
        if res is None:
            continue
        key = an.session.frames[fi].key
        for bi, (d, s) in enumerate(zip(res.dets, res.stats)):
            if d.conf < settings.conf:
                continue
            vs = verdicts(d, s, settings.tol)
            row = {"frame": fi + 1, "image": key, "box": bi + 1, "class": d.cls, "confidence": round(d.conf, 3),
                   "x1": round(d.box[0], 1), "y1": round(d.box[1], 1), "x2": round(d.box[2], 1), "y2": round(d.box[3], 1),
                   "predicted_m": None if d.pred is None else round(d.pred, 3), "lidar_points": s.n}
            for m in METHODS:
                v, e = s.value(m), error_fraction(d.pred, s.value(m))
                row[f"{m}_m"] = None if v is None else round(v, 3)
                row[f"{m}_off_pct"] = None if e is None else round(100 * e, 1)
                row[f"{m}_result"] = "no distance" if d.pred is None else "no LiDAR" if s.n < MIN_POINTS else ("pass" if vs[m] else "fail")
            out.append(row)
    return out


CSV_FIELDS = ["frame", "image", "box", "class", "confidence", "x1", "y1", "x2", "y2", "predicted_m", "lidar_points"] + [
    f"{m}_{k}" for m in METHODS for k in ("m", "off_pct", "result")]


def write_csv(path, an, settings):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows(an, settings):
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})


def report_html(an, settings, ev, examples=(), made=""):
    """A single self-contained page (the pictures are inside it): settings, the three methods, by distance, and the frames chosen."""
    esc = html.escape
    pct = lambda m: "-" if ev.percent(m) is None else f"{ev.percent(m):.0f} %"
    rows_m = "".join(f"<tr><td>{esc(METHOD_NAMES[m])}{' (judges the boxes)' if m == settings.method else ''}</td><td>{ev.counts[m][0]}</td><td>{ev.counts[m][1]}</td><td><b>{pct(m)}</b></td></tr>" for m in METHODS)
    rows_b = "".join(f"<tr><td>{esc(lbl)}</td><td>{n}</td><td>{p}</td><td>{'-' if n == 0 else f'{100 * p / n:.0f} %'}</td></tr>" for lbl, n, p in ev.bands if n)
    figs = "".join(f'<figure><img src="data:image/png;base64,{base64.b64encode(png).decode()}" alt="{esc(cap)}"><figcaption>{esc(cap)}</figcaption></figure>' for cap, png in examples)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Model check - {esc(an.session.name)}</title>
<style>body{{font:14px/1.45 'Segoe UI',system-ui,sans-serif;color:#1f2a3c;max-width:980px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:26px 0 8px}} .m{{color:#5a6577}}
table{{border-collapse:collapse;margin:6px 0}} td,th{{border-bottom:1px solid #d5dbe6;padding:5px 14px 5px 0;text-align:left}}
figure{{margin:18px 0}} img{{display:block;width:100%;border:1px solid #bbb}} figcaption{{font-size:12px;color:#5a6577}}</style></head><body>
<h1>Model check against the LiDAR</h1>
<div class="m">Session {esc(an.session.name)} &middot; {len(an.session)} frames ({an.analysed} analysed) &middot; model {esc(an.model or "-")} &middot; {esc(made)}</div>
<h2>Settings</h2>
<p>Boxes with confidence of at least <b>{settings.conf * 100:.0f} %</b>. A box passes when the LiDAR number is within <b>{settings.tol * 100:.0f} %</b> of the predicted distance.
LiDAR returns taken from {"the middle 60 % of each box" if an.region == "core" else "the whole box"}. Boxes counted: <b>{ev.boxes}</b>
({ev.no_lidar} without enough LiDAR returns, {ev.no_distance} without a predicted distance; those neither pass nor fail).</p>
<h2>How the predicted distance compares</h2>
<table><tr><th>LiDAR number</th><th>Pass</th><th>Fail</th><th>Share passing</th></tr>{rows_m}</table>
<p class="m">Closest point: the return in the box nearest the prediction (forgives LiDAR that lags the picture and whatever is behind the object). Median: the middle return of the box (the Pi's own number is a median of the middle of the box). Average: every return counts equally, so what is behind the object pulls it away.</p>
<h2>By distance ({esc(METHOD_NAMES[settings.method])}, grouped by the LiDAR median)</h2>
<table><tr><th>Distance</th><th>Boxes judged</th><th>Pass</th><th>Share passing</th></tr>{rows_b or '<tr><td colspan="4">nothing judged</td></tr>'}</table>
<h2>Frames</h2>{figs or '<p class="m">No frames chosen.</p>'}
</body></html>"""


# ---------------------------------------------------------------------------------------------- a made-up session and a self-check
# Six frames, made so every answer is known by hand: 100 LiDAR returns in each box (a 10 x 10 grid), 30 of them on the wall behind the object (the
# outer ring) and 70 on the object itself (exact distance), so the median is the object, the average is pulled toward the wall, and the
# closest-to-prediction return depends on where the model aims.  See DEMO_BOXES for who is where.
DEMO_W, DEMO_H = 320, 240
DEMO_SLOTS = {"A": (40, 60, 120, 200), "B": (180, 90, 240, 190), "C": (250, 100, 300, 160)}
# frame -> [(slot, class, conf, predicted m or None, object m, wall m, lidar?)]
DEMO_BOXES = {0: [("A", "person", 0.93, 3.0, 3.0, 8.0, True), ("B", "person", 0.91, 6.2, 6.0, 9.0, True)],
              1: [("A", "person", 0.90, 4.0, 3.0, 8.0, True), ("C", "person", 0.88, 5.0, 5.0, 9.0, False)],
              2: [("A", "person", 0.80, 3.2, 3.0, 8.0, True), ("B", "person", 0.95, 7.5, 6.0, 8.0, True)],
              3: [],
              4: [("A", "person", 0.90, None, 3.0, 8.0, True)],
              5: [("B", "person", 0.20, 6.0, 6.0, 9.0, True)]}


def make_demo_session(folder):
    """Writes the made-up session (photos, depth, index.csv, meta.json) into `folder` and returns its path."""
    os.makedirs(os.path.join(folder, "images"), exist_ok=True)
    os.makedirs(os.path.join(folder, "depth"), exist_ok=True)
    lines = ["idx,time_unix,image,depth,lidar,lidar_points_total,depth_pixels,sharpness"]
    for k in range(len(DEMO_BOXES)):
        img = np.full((DEMO_H, DEMO_W, 3), (170, 176, 170), np.uint8)
        depth = np.zeros((DEMO_H, DEMO_W), np.uint16)
        for slot, cls, conf, pred, d_obj, d_wall, lidar in DEMO_BOXES[k]:
            x1, y1, x2, y2 = DEMO_SLOTS[slot]
            img[y1:y2, x1:x2] = (110, 140, 190)
            if lidar:
                xs = np.linspace(x1 + 3, x2 - 4, 10).round().astype(int)
                ys = np.linspace(y1 + 3, y2 - 4, 10).round().astype(int)
                wall = 30                                       # the first 30 cells of the outer ring (row by row) are wall, the other 70 object
                for iy in range(10):
                    for ix in range(10):
                        ring = iy in (0, 9) or ix in (0, 9)
                        is_wall = ring and wall > 0
                        wall -= 1 if is_wall else 0
                        depth[ys[iy], xs[ix]] = round((d_wall if is_wall else d_obj) * 1000)
        name = f"{k:06d}"
        Image.fromarray(img).save(os.path.join(folder, "images", name + ".jpg"), quality=92)
        Image.fromarray(depth).save(os.path.join(folder, "depth", name + ".png"))
        lines.append(f"{k},{1.7e9 + k},images/{name}.jpg,depth/{name}.png,,{int((depth > 0).sum())},{int((depth > 0).sum())},1.0")
    with open(os.path.join(folder, "index.csv"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"made_up": True}, f)
    return folder


def demo_predictor(image_path):
    """What a model would say about the made-up photos (the frame number is in the file name)."""
    k = int(os.path.splitext(os.path.basename(image_path))[0])
    return [(cls, conf, *DEMO_SLOTS[slot], pred) for slot, cls, conf, pred, _o, _w, _l in DEMO_BOXES[k]]


def selfcheck(workdir):
    """Builds the made-up session in `workdir`, runs the analysis on it and checks the answers worked out by hand.
    Returns [(what, passed, detail)]."""
    out = []

    def check(what, got, want):
        out.append((what, got == want, f"got {got!r}, expected {want!r}" if got != want else ""))
    sess = open_session(make_demo_session(os.path.join(workdir, "demo_session")))
    check("session opens with 6 frames", len(sess), 6)
    an = run(sess, demo_predictor, model="made-up model")
    check("all frames analysed", an.analysed, 6)
    ev = evaluate(an, Settings(0.85, 0.10, "closest"))
    check("boxes at 85 %", ev.boxes, 6)
    check("closest point pass / fail", ev.counts["closest"], [3, 1])
    check("median pass / fail", ev.counts["median"], [2, 2])
    check("average pass / fail", ev.counts["average"], [0, 4])
    check("no LiDAR / no distance", (ev.no_lidar, ev.no_distance), (1, 1))
    check("frame states", ev.state, ["pass", "fail", "pass", "empty", "none", "empty"])
    check("frames with a fail / without LiDAR", (ev.with_fail, ev.with_no_lidar), ([1], [1]))
    check("closest by distance (2-4 m, 6-8 m)", [(b[1], b[2]) for b in ev.bands if b[1]], [(2, 1), (2, 2)])
    ev2 = evaluate(an, Settings(0.75, 0.10, "closest"))
    check("a lower confidence adds the 80 % box", (ev2.boxes, ev2.counts["closest"], ev2.counts["median"]), (7, [4, 1], [3, 2]))
    ev3 = evaluate(an, Settings(0.85, 0.30, "median"))
    check("a wider tolerance passes the 25 % miss", (ev3.counts["median"], ev3.counts["closest"]), ([4, 0], [4, 0]))
    rs = rows(an, Settings(0.85, 0.10, "closest"))
    check("rows: first box", (rs[0]["class"], rs[0]["predicted_m"], rs[0]["closest_m"], rs[0]["median_m"], rs[0]["average_m"], rs[0]["lidar_points"]), ("person", 3.0, 3.0, 3.0, 4.5, 100))
    check("rows: wall return nearer than the object counts as closest", (rs[4]["closest_m"], rs[4]["median_m"]), (8.0, 6.0))
    check("rows: results", [r["closest_result"] for r in rs], ["pass", "pass", "fail", "no LiDAR", "pass", "no distance"])
    an2 = run(sess, demo_predictor, region="core")
    r2 = [r for r in rows(an2, Settings()) if r["median_m"] is not None]
    check("middle 60 % of a box: only the object is left, so median and average agree", [(r["median_m"], r["average_m"]) for r in r2], [(3.0, 3.0), (6.0, 6.0), (3.0, 3.0), (6.0, 6.0), (3.0, 3.0)])
    stopped = run(sess, demo_predictor, stop=lambda: True)
    check("stop keeps what was done (nothing here)", (stopped.analysed, stopped.finished), (0, False))
    return out
