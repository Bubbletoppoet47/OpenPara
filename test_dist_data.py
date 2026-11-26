import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""dist_data.py: the labelled boxes of a frozen training copy as the six numbers the distance network sees.  A frozen copy is built by hand in the layout the Trainer's
freeze() writes (data.yaml, images/<split>, labels/<split>, distances.csv); the numbers are checked against the formulas worked out by hand, a picture of another size
gives the same numbers for the same box, distorted copies are left out, and (when torch is installed) the numbers are the ones of distance_model.geometry."""
import csv
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
for p in (os.path.join(ADD, "trainer"), os.path.join(ADD, "annotator", "app")):
    sys.path.insert(0, p)
import numpy as np
import cv2

import dist_data as dd

TMP = tempfile.mkdtemp()


def ok(msg):
    print("ok:", msg, flush=True)


def make_copy(root, pictures, names=("person", "vehicle")):
    """pictures: [(split, image name, (W, H), [(class id, xc, yc, w, h, distance or None)])] -> the data.yaml of a frozen copy written the way Trainer.freeze() does."""
    rows = []
    for split in ("train", "val"):
        os.makedirs(os.path.join(root, "images", split), exist_ok=True)
        os.makedirs(os.path.join(root, "labels", split), exist_ok=True)
    for split, name, (W, H), boxes in pictures:
        cv2.imwrite(os.path.join(root, "images", split, name + ".jpg"), np.full((H, W, 3), 100, np.uint8))
        with open(os.path.join(root, "labels", split, name + ".txt"), "w") as f:
            for c, xc, yc, w, h, d in boxes:
                f.write(f"{c} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")
                if d is not None:
                    rows.append((split, name, c, names[c], f"{xc:.6f}", f"{yc:.6f}", f"{w:.6f}", f"{h:.6f}", f"{d:.3f}"))
    with open(os.path.join(root, "distances.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["split", "image", "class_id", "class", "xc", "yc", "w", "h", "distance_m"])
        wr.writerows(rows)
    with open(os.path.join(root, "data.yaml"), "w") as f:
        f.write(f"path: {root.replace(os.sep, '/')}\ntrain: images/train\nval: images/val\nnc: {len(names)}\nnames:\n")
        for i, n in enumerate(names):
            f.write(f"  {i}: {n}\n")
    return os.path.join(root, "data.yaml")


# a person 240 pixels tall (half of a 640 x 480 picture), in the middle, 5 m away; and the same person in a 320 x 240 picture (everything half as big)
B = (0, 0.5, 0.5, 0.25, 0.5, 5.0)                       # class, xc, yc, w, h, distance
pics = [("train", "gim_alpha_000001", (640, 480), [B, (0, 0.2, 0.7, 0.1, 0.3, 9.5), (0, 0.8, 0.4, 0.1, 0.2, None)]),      # the third box has no distance
        ("train", "gim_alpha_000001_dist1", (640, 480), [B, (0, 0.2, 0.7, 0.1, 0.3, 9.5), (0, 0.8, 0.4, 0.1, 0.2, None)]),
        ("train", "gim_alpha_000001_dist2", (640, 480), [B, (0, 0.2, 0.7, 0.1, 0.3, 9.5), (0, 0.8, 0.4, 0.1, 0.2, None)]),
        ("train", "gim_beta_000010", (320, 240), [B]),
        ("train", "gim_beta_000011", (320, 240), [(1, 0.4, 0.6, 0.3, 0.6, 3.2)]),
        ("train", "gim_gamma_000003", (640, 480), [(0, 0.3, 0.3, 0.05, 0.1, None)]),                                  # no distance at all: not used
        ("val", "gim_delta_000001", (640, 480), [B, (0, 0.6, 0.6, 0.2, 0.4, 12.0)])]
root = os.path.join(TMP, "frozen")
yaml_path = make_copy(root, pics)

tr = dd.load_boxes(yaml_path, "train")
va = dd.load_boxes(yaml_path, "val")
assert len(tr) == 4 and tr.pictures == 3 and tr.skipped_copies == 2, (len(tr), tr.pictures, tr.skipped_copies)
assert len(va) == 2 and va.skipped_copies == 0
assert sorted(set(tr.group)) == ["alpha", "beta"] and list(va.group) == ["delta", "delta"], tr.group
assert np.allclose(sorted(tr.dist), [3.2, 5.0, 5.0, 9.5]) and tr.nc == 2 and tr.names == ["person", "vehicle"]
assert not np.isnan(tr.feat).any() and tr.feat.shape == (4, 6) and tr.X().shape == (4, 8)
ok("only the boxes with a distance of the original pictures are read (2 distorted copies of a picture and 1 box without a distance left out)")

withc = dd.load_boxes(yaml_path, "train", unique=False)
assert len(withc) == 4 + 4 and withc.skipped_copies == 0
ok("keeping the distorted copies is possible (unique=False) and doubles their rows")

# the six numbers of B by hand: a 640 x 480 picture letterboxed to 640 x 640 has bars of 80 pixels above and below
r, left, top = dd.letterbox_params(640, 480, 640)
assert (r, left, top) == (1.0, 0, 80)
i = [k for k in range(len(tr)) if abs(tr.dist[k] - 5.0) < 1e-9][0]
x1, y1, x2, y2 = 0.5 * 640 - 80, 0.5 * 480 - 120 + 80, 0.5 * 640 + 80, 0.5 * 480 + 120 + 80       # 240..400 wide, 200..440 tall (letterboxed)
assert np.allclose(tr.xyxy[i], [x1, y1, x2, y2]), tr.xyxy[i]
w, h = x2 - x1, y2 - y1
want = [(x1 + x2) / 2 / 640, (y1 + y2) / 2 / 640, y2 / 640, np.log(h / 640), np.log(w / 640), np.log(h / w)]
assert np.allclose(tr.feat[i], want, atol=1e-12), (tr.feat[i], want)
assert abs(tr.h_px[i] - 240) < 1e-9
ok("the six numbers of a box, worked out by hand, are what is read (centre, bottom edge, log size, log shape)")

# the same person in a 320 x 240 picture (everything half as big) is the same box in the letterboxed picture: the numbers are the same
j = [k for k in range(len(tr)) if tr.image[k] == "gim_beta_000010"][0]
assert np.allclose(tr.feat[j], tr.feat[i], atol=1e-9) and np.allclose(tr.xyxy[j], tr.xyxy[i], atol=1e-9)
ok("a picture of another size gives the same numbers for the same box")

# the way back: a detector's box in the original picture's pixels lands where the labelled box did
orig = np.array([[0.5 * 640 - 80, 0.5 * 480 - 120, 0.5 * 640 + 80, 0.5 * 480 + 120]])
assert np.allclose(dd.orig_to_letterbox(orig, 640, 480, 640), tr.xyxy[i:i + 1])
assert np.allclose(dd.geometry(dd.orig_to_letterbox(orig, 640, 480, 640), 640)[0], tr.feat[i])
sq = dd.letterbox_params(400, 400, 640)
assert sq == (1.6, 0, 0)
ok("a box in the original picture's pixels is moved into the letterboxed frame the way the labelled ones are")

# class columns, targets, standardising
X = tr.X()
assert set(np.unique(X[:, 6:])) <= {0.0, 1.0} and X[:, 6:].sum(1).tolist() == [1.0] * 4 and X[:, 7].sum() == 1.0
one = dd.load_boxes(make_copy(os.path.join(TMP, "one"), [p for p in pics if p[3] and all(b[0] == 0 for b in p[3])], names=("person",)), "train")
assert one.X().shape[1] == 6, one.X().shape
assert np.allclose(np.exp(tr.y()), np.clip(tr.dist, 0.2, 60))
assert np.allclose(dd.log_target([0.01, 1000.0]), np.log([0.2, 60.0]))
sd = dd.Standardiser().fit(X)
Z = sd.apply(X)
assert np.allclose(Z[:, :6].mean(0), 0, atol=1e-12) and np.allclose(Z[:, :6].std(0)[sd.std[:6] != 1.0], 1.0)
assert np.allclose(dd.Standardiser.from_json(sd.to_json()).apply(X), Z)
const = dd.Standardiser().fit(np.ones((5, 2)))
assert np.all(np.isfinite(const.apply(np.ones((3, 2))))) and np.all(const.std == 1.0)
ok("class columns appear only with more than one class; the target is the log distance inside 0.2 - 60 m; the standardiser is fitted on training rows and saved as JSON")

# the start-of-run check
lines, err = dd.input_check(tr, va)
assert err is None and "4 boxes" in lines[0] and "2 distorted" in lines[0] and "2 in training" in lines[2], lines
empty = dd.load_boxes(make_copy(os.path.join(TMP, "empty"), [("train", "gim_a_000001", (640, 480), [(0, 0.5, 0.5, 0.2, 0.2, None)]), ("val", "gim_b_000001", (640, 480), [B])], names=("person",)), "train")
assert len(empty) == 0 and dd.input_check(empty, va)[1] and "nothing to learn" in dd.input_check(empty, va)[1]
assert dd.input_check(tr, empty)[1] and "cannot be scored" in dd.input_check(tr, empty)[1]
ok("the start-of-run check counts what was read and stops with a plain message when there is nothing to train on or to score")

# groups
names = [f"gim_s{k % 3}_{k:06d}" for k in range(900)]
g, kind = dd.cv_groups(names)
assert kind == "time block" and len(set(g)) > 3, (kind, len(set(g)))
names2 = [f"gim_s{k % 8}_{k:06d}" for k in range(80)]
g2, kind2 = dd.cv_groups(names2)
assert kind2 == "recording" and len(set(g2)) == 8
assert dd.recording_of("photo7") == "photo7" and dd.recording_of("vid_clip_000012") == "clip"
ok("cross-validation groups are the recordings, or blocks of 30 s of them when there are fewer than 5 recordings")

# the numbers are the ones of the Trainer's own distance network (when torch is there)
try:
    import torch
except ImportError:
    print("skipped: torch is not installed, the comparison with distance_model.geometry is not made here", flush=True)
else:
    import distance_model as dm
    rng = np.random.default_rng(0)
    x1 = rng.uniform(0, 500, 200)
    y1 = rng.uniform(0, 500, 200)
    bx = np.stack([x1, y1, x1 + rng.uniform(0.2, 300, 200), y1 + rng.uniform(0.2, 300, 200)], 1)
    ref = dm.geometry(torch.tensor(bx, dtype=torch.float64), 640, 640).numpy()
    assert np.allclose(ref, dd.geometry(bx, 640), atol=1e-9)
    ok("the same six numbers as distance_model.geometry on 200 random boxes")

shutil.rmtree(TMP, ignore_errors=True)
print("dist data ok", flush=True)
