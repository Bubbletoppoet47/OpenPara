"""wb_testing_boxes.py - what Model testing needs to try a DISTANCE-ONLY model on a recorded session, and to put several models side by side.  No Qt.

A distance-only model (.opdm, see the Trainer's dist_models.py) looks at one box and answers how far away it is; it finds no boxes.  Model testing therefore takes the boxes from
a detector (the "Boxes from" slot: any model of the list that finds boxes) and asks the distance model for the metres of each of them:

    detector(picture)  ->  [(class, confidence, x1, y1, x2, y2, its own distance or None)]
    DistanceOnBoxes    ->  the same list, the distance of each box answered by the distance model            (the shape the Analyse code runs: annotator_analysis.run_into)

DetectorBoxes remembers what a detector found in each picture, so trying five distance models on the same session runs the detector over it once.
A model file that holds a pickle (the gradient boosting one) is read only after the person says they trust it (needs_trust, load_model).

summarise() puts one run (an annotator_analysis.Analysis) in a handful of numbers for the side-by-side table and the chart, by the same rules as the Analyse tab:
a box counts when its confidence is at least the setting, passes when the LiDAR number is within the tolerance of the distance the model gave, and is left out of the judging when it has no
distance or too few LiDAR returns.  "Off by" is |LiDAR - model| / model, the Analyse tab's way (a share of the distance the model gave).
"""
import csv
import os
import threading

import numpy as np


def _aa():
    import annotator_analysis as aa
    return aa


def _dm():
    import dist_models as dm
    return dm


# ------------------------------------------------------------------------------------------------------------------ the model
def needs_trust(path):
    """True when the file is a distance model that holds a pickle (read it only when the person trusts where it came from).  A file that is not one: False."""
    head = _dm().read_header(path)
    return bool(head and head.get("pickled"))


def load_model(path, trust=False):
    """The distance model of a .opdm file.  Raises dist_models.UntrustedModel for a pickled one unless `trust`."""
    return _dm().load(path, trust_pickle=bool(trust))


def class_numbers(model, names):
    """The class numbers the model knows for the class names of a detector's boxes: a list with None for a name the model was not trained on.  One class: nothing is needed."""
    if model.nc <= 1:
        return [0] * len(names)
    known = {n: i for i, n in enumerate(model.names)}
    return [known.get(n) for n in names]


# ------------------------------------------------------------------------------------------------------------------ the boxes
class DetectorBoxes:
    """predict(picture path) -> detections, asked once per picture.  Calls come from the worker thread of a run (one at a time)."""

    def __init__(self, predict):
        self.predict = predict
        self.calls = 0                                       # how many pictures the detector was really run on
        self._cache = {}
        self._lock = threading.Lock()

    def __call__(self, path):
        with self._lock:
            hit = self._cache.get(path)
        if hit is not None:
            return hit
        dets = [tuple(d) for d in self.predict(path)]
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
        hit = (dets, size)
        with self._lock:
            self.calls += 1
            self._cache[path] = hit
        return hit

    def forget(self):
        with self._lock:
            self._cache.clear()


class DistanceOnBoxes:
    """The predictor of a run: the boxes of `source` (a DetectorBoxes), the distance of each from `model` (a dist_models.DistanceModel)."""
    has_distance = True

    def __init__(self, source, model):
        self.source, self.model = source, model

    def __call__(self, path):
        dets, (w, h) = self.source(path)
        if not dets:
            return []
        xyxy = np.array([[d[2], d[3], d[4], d[5]] for d in dets], float)
        nums = class_numbers(self.model, [d[0] for d in dets])
        ok = [i for i, c in enumerate(nums) if c is not None]
        metres = [None] * len(dets)
        if ok:
            cls = np.array([nums[i] for i in ok], int)
            answer = self.model.predict_m_orig(xyxy[ok], w, h, cls if self.model.nc > 1 else None)
            for i, m in zip(ok, answer):
                metres[i] = float(m)
        return [(d[0], d[1], d[2], d[3], d[4], d[5], m) for d, m in zip(dets, metres)]


def run_name(model_label, boxes_from=""):
    """How a run is called in the table: a model that finds its own boxes by its label, a distance-only one with the detector it was given."""
    return f"{model_label} (boxes: {boxes_from})" if boxes_from else model_label


# ------------------------------------------------------------------------------------------------------------------ the numbers of a run
def summarise(an, settings):
    """One run in numbers (None where there is nothing to say): {"frames", "boxes", "judged", "passed", "pass_pct", "median_off_pct", "mean_abs_m", "no_lidar", "no_distance", "bands"}.
    bands: [(label, n judged, n passed)] by the LiDAR median, the Analyse tab's six distance bands.  Settings: conf, tol, method (annotator_analysis.Settings)."""
    aa = _aa()
    ev = aa.evaluate(an, settings)
    off, abs_m = [], []
    for res in an.frames:
        if res is None:
            continue
        for d, s in zip(res.dets, res.stats):
            if d.conf < settings.conf:
                continue
            v = s.value(settings.method)
            e = aa.error_fraction(d.pred, v)
            if e is not None:
                off.append(e)
                abs_m.append(abs(v - d.pred))
    p, f = ev.counts[settings.method]
    return {"frames": an.analysed, "boxes": ev.boxes, "judged": p + f, "passed": p, "pass_pct": ev.percent(settings.method),
            "median_off_pct": None if not off else 100.0 * float(np.median(off)), "mean_abs_m": None if not abs_m else float(np.mean(abs_m)),
            "no_lidar": ev.no_lidar, "no_distance": ev.no_distance, "bands": list(ev.bands)}


COLUMNS = ["model", "frames", "boxes", "judged", "passed", "pass_pct", "median_off_pct", "mean_abs_m", "no_lidar", "no_distance"]


def write_comparison(path, items, settings):
    """items: [(name, summary)].  One row per model, then one row per model and distance band; what the settings were is in the first rows."""
    aa = _aa()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["setting", "confidence at least", "pass when within", "LiDAR number"])
        w.writerow(["", settings.conf, settings.tol, aa.METHOD_NAMES[settings.method]])
        w.writerow([])
        w.writerow(COLUMNS)
        for name, s in items:
            w.writerow([name] + ["" if s[k] is None else (round(s[k], 3) if isinstance(s[k], float) else s[k]) for k in COLUMNS[1:]])
        w.writerow([])
        w.writerow(["model", "distance band (LiDAR)", "boxes judged", "boxes passed", "pass_pct"])
        for name, s in items:
            for label, n, p in s["bands"]:
                w.writerow([name, label, n, p, "" if not n else round(100.0 * p / n, 1)])
    return path


def usable_for(summary):
    """True when a run has anything to put in the table (frames were analysed)."""
    return bool(summary and summary["frames"])


def same_reading(a_region, b_region):
    return (a_region or "box") == (b_region or "box")


def folder_key(session):
    return os.path.abspath(session.folder) if session is not None else ""
