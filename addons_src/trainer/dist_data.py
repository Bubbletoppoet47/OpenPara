"""dist_data.py - the labelled boxes of a frozen training copy as numbers for the distance models that look at the box alone (no PyTorch, no Qt).

A box is described the way the Trainer's distance network sees it (distance_model.geometry): the picture is letterboxed to imgsz x imgsz (scaled to fit, grey bars
on the short side), the box is moved the same way, and six numbers come out of it (W = H = imgsz):

    g = [ (x1+x2)/(2W), (y1+y2)/(2H), y2/H, ln(h/H), ln(w/W), ln(h/w) ]        w = x2-x1, h = y2-y1 (at least 1 pixel)
         box centre     bottom edge    log size            log shape

The target is ln d (natural log of the distance in metres, d kept inside 0.2 - 60 m); a model's answer is exp(prediction), kept inside the same range.
With more than one class the class is added as one 0/1 column per class (a person 200 pixels tall is far closer than a truck 200 pixels tall); with one class
there is nothing to add.

What is read: the frozen copy the Trainer made (data.yaml, the train / val lists, YOLO label files, distances.csv), through the annotator's own reader
(gimble_data.Source) so a box finds its distance exactly as it does for the YOLO jobs.  Only boxes that carry a distance are used.  The distorted copies of a
picture (<picture>_dist<n>: same boxes, other colours) are left out by default, because they would only repeat their rows.
A recording id is read from the picture's name (gim_<session>_<frame>, vid_<session>_<frame>) for the grouped bootstrap and grouped cross-validation.
"""
import os
import re
import sys

import numpy as np

D_MIN, D_MAX = 0.2, 60.0
FEATURE_NAMES = ("centre_x", "centre_y", "bottom_edge", "ln_height", "ln_width", "ln_shape")
_COPY = re.compile(r"_dist\d+$")
_FRAME = re.compile(r"^(?:(?:gim|vid)_)?(.+?)_(\d+)$")


def is_copy(name):
    """True for a distorted copy of a picture (named <picture>_dist<n> by the annotator)."""
    return bool(_COPY.search(name))


def recording_of(name):
    """The recording a picture is from: gim_<session>_<frame> -> <session>.  A picture of another kind is its own recording."""
    base = _COPY.sub("", name)
    m = _FRAME.match(base)
    return m.group(1) if m else base


def frame_of(name):
    m = _FRAME.match(_COPY.sub("", name))
    return int(m.group(2)) if m else 0


def time_blocks(images, frames=300):
    """Recording id + contiguous block of `frames` frames (300 frames = 30 s at the Gimble's 10 pictures a second): the groups to cross-validate on when
    there are too few recordings, because neighbouring frames are near duplicates."""
    return np.array([f"{recording_of(n)}#{frame_of(n) // max(1, int(frames))}" for n in images])


def cv_groups(images, min_groups=5, frames=300):
    """The groups for cross-validation: the recordings; when there are fewer than min_groups of them, time blocks of the recordings.  -> (array, "recording" or "time block")."""
    rec = np.array([recording_of(n) for n in images])
    if len(set(rec)) >= min_groups:
        return rec, "recording"
    return time_blocks(images, frames), "time block"


# ------------------------------------------------------------------ the picture's letterbox and the six numbers
def letterbox_params(W0, H0, S):
    """(scale, left, top) of a W0 x H0 picture letterboxed to S x S, as gimble_data.letterbox does it."""
    r = S / max(H0, W0)
    nh, nw = max(1, round(H0 * r)), max(1, round(W0 * r))
    return r, (S - nw) // 2, (S - nh) // 2


def letterbox_xyxy(xywh_norm, W0, H0, S):
    """(N, 4) x1 y1 x2 y2 in the pixels of the letterboxed S x S picture, from (N, 4) centre x, centre y, width, height as shares of the picture W0 x H0."""
    b = np.asarray(xywh_norm, float).reshape(-1, 4)
    r, left, top = letterbox_params(W0, H0, S)
    px = b * np.array([W0, H0, W0, H0], float)
    out = np.concatenate([px[:, :2] - px[:, 2:] / 2, px[:, :2] + px[:, 2:] / 2], 1) * r
    out[:, [0, 2]] += left
    out[:, [1, 3]] += top
    return out


def orig_to_letterbox(xyxy, W0, H0, S):
    """(N, 4) x1 y1 x2 y2 in the pixels of the original W0 x H0 picture -> the same in the pixels of the letterboxed S x S picture (what a detector hands over)."""
    b = np.asarray(xyxy, float).reshape(-1, 4)
    r, left, top = letterbox_params(W0, H0, S)
    out = b * r
    out[:, [0, 2]] += left
    out[:, [1, 3]] += top
    return out


def geometry(xyxy, S):
    """(N, 6) the six numbers of boxes (N, 4) in the pixels of a letterboxed S x S picture (distance_model.geometry, in numpy)."""
    b = np.asarray(xyxy, float).reshape(-1, 4)
    x1, y1, x2, y2 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    w, h = np.maximum(x2 - x1, 1.0), np.maximum(y2 - y1, 1.0)
    return np.stack([(x1 + x2) / 2 / S, (y1 + y2) / 2 / S, y2 / S, np.log(h / S), np.log(w / S), np.log(h / w)], 1)


def with_class(feat, cls, nc):
    """The six numbers plus one 0/1 column per class when there is more than one class."""
    if nc <= 1:
        return feat
    oh = np.zeros((len(feat), nc))
    oh[np.arange(len(feat)), np.clip(np.asarray(cls, int), 0, nc - 1)] = 1.0
    return np.concatenate([feat, oh], 1)


def log_target(d):
    return np.log(np.clip(np.asarray(d, float), D_MIN, D_MAX))


# ------------------------------------------------------------------ standardising
class Standardiser:
    """Mean and standard deviation of the columns of the TRAINING rows (nothing from validation or from a live recording touches them)."""

    def __init__(self, mean=None, std=None):
        self.mean, self.std = mean, std

    def fit(self, X):
        X = np.asarray(X, float)
        self.mean = X.mean(0)
        self.std = np.where(X.std(0) > 1e-9, X.std(0), 1.0)            # a column that never changes (one class) is left as it is
        return self

    def apply(self, X):
        return (np.asarray(X, float) - self.mean) / self.std

    def to_json(self):
        return {"mean": [float(x) for x in self.mean], "std": [float(x) for x in self.std]}

    @classmethod
    def from_json(cls, d):
        return cls(np.asarray(d["mean"], float), np.asarray(d["std"], float))


class Boxes:
    """The labelled boxes of one side (train or val) of a frozen copy.  Arrays, all N long: feat (N, 6), cls, dist (metres, as labelled), xyxy (letterboxed pixels), image, group, h_px."""

    def __init__(self, feat, cls, dist, xyxy, image, nc, names, imgsz, skipped_copies=0, pictures=0):
        self.feat, self.cls, self.dist, self.xyxy = feat, cls, dist, xyxy
        self.image, self.nc, self.names, self.imgsz = list(image), int(nc), list(names), int(imgsz)
        self.skipped_copies, self.pictures = int(skipped_copies), int(pictures)
        self.group = np.array([recording_of(n) for n in self.image])

    def __len__(self):
        return len(self.dist)

    @property
    def h_px(self):
        return np.maximum(self.xyxy[:, 3] - self.xyxy[:, 1], 1.0)

    def X(self):
        """The inputs before standardising: the six numbers (+ the class columns)."""
        return with_class(self.feat, self.cls, self.nc)

    def y(self):
        return log_target(self.dist)

    def subset(self, idx):
        """The boxes at the given positions (an index array or a boolean mask)."""
        idx = np.asarray(idx)
        if idx.dtype == bool:
            idx = np.flatnonzero(idx)
        return Boxes(self.feat[idx], self.cls[idx], self.dist[idx], self.xyxy[idx], [self.image[i] for i in idx], self.nc, self.names, self.imgsz,
                     self.skipped_copies, self.pictures)


def image_size(path):
    """(width, height) of a picture, read from its header."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:                                                  # noqa: BLE001
        import cv2
        im = cv2.imread(path)
        if im is None:
            raise OSError(f"cannot read the picture {path}")
        return im.shape[1], im.shape[0]


def _source(data_yaml, classes):
    """The annotator's reader of a frozen copy.  Its folder is on the path when a job runs (job_common); otherwise it is looked for next to this add-on."""
    try:
        import gimble_data as gd
    except ImportError:
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "annotator", "app")
        if not os.path.isdir(app):
            raise RuntimeError("The distance models read the training data with the Annotator add-on's code, and that add-on is not installed.")
        sys.path.insert(0, app)
        import gimble_data as gd
    return gd.Source(data_yaml, use_people=False, classes=classes or None)


def load_boxes(data_yaml, split, *, classes=None, imgsz=640, unique=True, source=None):
    """The boxes with a distance of 'train' or 'val' of the frozen copy `data_yaml`.  -> Boxes.  unique: leave out the distorted copies (<picture>_dist<n>)."""
    src = source or _source(data_yaml, classes)
    feats, cls, dist, xyxy, names = [], [], [], [], []
    seen, copies, sizes = 0, 0, {}
    for s in src.samples("train" if split == "train" else "val"):
        name = os.path.splitext(os.path.basename(s["path"]))[0]
        if unique and is_copy(name):
            copies += 1
            continue
        got = [(r, d) for r, d in zip(s["rows"], s["dist"]) if d == d]
        if not got:
            continue
        seen += 1
        key = s["path"]
        if key not in sizes:
            sizes[key] = image_size(key)
        W0, H0 = sizes[key]
        b = letterbox_xyxy([r[1:5] for r, _d in got], W0, H0, imgsz)
        xyxy.append(b)
        cls.extend(int(r[0]) for r, _d in got)
        dist.extend(float(d) for _r, d in got)
        names.extend([name] * len(got))
    if xyxy:
        xyxy = np.concatenate(xyxy, 0)
    else:
        xyxy = np.zeros((0, 4))
    return Boxes(geometry(xyxy, imgsz) if len(xyxy) else np.zeros((0, 6)), np.asarray(cls, int), np.asarray(dist, float), xyxy, names, src.nc, src.names, imgsz,
                 skipped_copies=copies, pictures=seen)


def input_check(train, val):
    """The start-of-run input check of the distance jobs, like the YOLO jobs print: -> (lines of text, error message or None)."""
    lines = [f"Training       : {train.pictures} pictures with a distance box, {len(train)} boxes with a distance"
             + (f" (left out: {train.skipped_copies} distorted copies of pictures)" if train.skipped_copies else ""),
             f"Validation     : {val.pictures} pictures with a distance box, {len(val)} boxes with a distance",
             f"Recordings     : {len(set(train.group))} in training, {len(set(val.group))} in validation"]
    if len(train) == 0:
        return lines, "None of the training boxes has a distance, so a distance model has nothing to learn from."
    if len(val) == 0:
        return lines, "None of the validation boxes has a distance, so the model cannot be scored."
    return lines, None


def rows_ok(boxes):
    """A box whose six numbers or distance are not finite numbers cannot be used: -> a mask of those that can."""
    return np.all(np.isfinite(boxes.feat), axis=1) & np.isfinite(boxes.dist) & (boxes.dist > 0) & np.all(np.isfinite(boxes.xyxy), axis=1)
