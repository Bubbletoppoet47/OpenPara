import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""dist_models.py: the formula and the four classical regressors on made-up cameras with known answers.  A pinhole camera with a known focal length and camera height
sees people of a known height, so the distance of every box is known exactly; the labels get noise on top.  What is checked: each model finds what is in the data
(k, the coefficient -1, the right neighbours, a spread that is honest), the numpy answer of the Gaussian process is scikit-learn's, a saved file answers exactly
as the model did, a file with a pickle is not read unless it is trusted, groups never split across a cross-validation fold, and a single recording is refused."""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
sys.path.insert(0, os.path.join(ADD, "trainer"))
import numpy as np

import dist_data as dd
import dist_models as dm
import eval_harness as eh

assert "torch" not in sys.modules and "PyQt6" not in sys.modules, "the models must import without torch or Qt"
TMP = tempfile.mkdtemp()
S = 640
F, CAM, HORIZON = 420.0, 1.2, 300.0              # focal length in pixels (of the 640 x 640 picture), camera height in metres, the horizon row


def ok(msg):
    print("ok:", msg, flush=True)


def scene(n, seed, recordings=10, noise=0.06, heights=(1.7,), jitter=0.0):
    """n boxes of upright objects (height H[class]) seen by a pinhole camera: h = F H / d, foot row = HORIZON + F CAM / d.  Labels = d * exp(noise)."""
    rng = np.random.default_rng(seed)
    cls = rng.integers(0, len(heights), n)
    d = np.exp(rng.uniform(np.log(2.5), np.log(20.0), n))
    H = np.asarray(heights)[cls]
    h = F * H / d * np.exp(rng.normal(0, jitter, n))
    w = 0.4 * h
    cx = rng.uniform(100, 540, n)
    y2 = HORIZON + F * CAM / d
    xyxy = np.stack([cx - w / 2, y2 - h, cx + w / 2, y2], 1)
    label = d * np.exp(rng.normal(0, noise, n))
    rec = rng.integers(0, recordings, n)
    names = [f"gim_rec{r:02d}_{k:06d}" for k, r in enumerate(rec)]
    names_cls = ["person", "tall_object"][:len(heights)]
    b = dd.Boxes(dd.geometry(xyxy, S), cls, label, xyxy, names, len(heights), names_cls, S)
    b.truth = d
    return b


def med(pred, true):
    return eh.median_rel_err(pred, true)


train, val = scene(900, 1), scene(400, 2)

# ---------------------------------------------------------------- 2a the formula
pin = dm.make("pinhole", S, 1, ["person"]).fit(train)
true_k = F * 1.7
assert abs(pin.k_all - true_k) / true_k < 0.02, (pin.k_all, true_k)
assert np.allclose(pin.predict_boxes(val), eh.clip_m(pin.k_all / val.h_px))
clean = scene(300, 3, noise=0.0)
assert abs(dm.make("pinhole", S, 1).fit(clean).k_all - true_k) < 1e-6 * true_k
two = scene(1200, 4, heights=(1.7, 3.4))
p2 = dm.make("pinhole", S, 2, ["person", "tall_object"]).fit(two)
assert abs(p2.k[0] - F * 1.7) < 0.03 * F * 1.7 and abs(p2.k[1] - F * 3.4) < 0.03 * F * 3.4, p2.k
one_k = dm.make("pinhole", S, 1).fit(two)
assert med(p2.predict_boxes(two), two.truth) < 0.5 * med(one_k.predict_boxes(two), two.truth)
ok(f"the formula finds k = {pin.k_all:.0f} (true {true_k:.0f}); with two kinds of object each gets its own k")

# ---------------------------------------------------------------- 2b log-linear
ll = dm.make("loglinear", S, 1).fit(clean)
co = list(ll.info["coefficients"].values())
assert abs(co[1] - (-1.0)) < 1e-9, co                                                                    # ln d = ln(F H) - ln h: the coefficient of ln h is exactly -1
assert med(ll.predict_boxes(clean), clean.truth) < 1e-9, med(ll.predict_boxes(clean), clean.truth)          # exact on a perfect pinhole scene: ln d = ln(F H) - ln h
noisy_ll = dm.make("loglinear", S, 1).fit(train)
assert abs(list(noisy_ll.info["coefficients"].values())[1] + 1.0) < 0.08, noisy_ll.info
withw = dm.make("loglinear", S, 1, use_width=True).fit(train)
assert len(withw.coef) == 4 and "e (ln of box width)" in withw.info["coefficients"]
cls2 = dm.make("loglinear", S, 2, ["person", "tall_object"]).fit(two)
assert len(cls2.coef) == 4 and med(cls2.predict_boxes(two), two.truth) < 0.05
ok(f"log-linear: b = {list(noisy_ll.info['coefficients'].values())[1]:.3f} on noisy data, exact (error {med(ll.predict_boxes(clean), clean.truth):.1e}) on a perfect scene")

# ---------------------------------------------------------------- the folds
g = np.array([f"r{i % 7}" for i in range(500)])
folds = dm.group_folds(g, 5)
assert len(folds) == 5
seen_val = np.concatenate([va for _tr, va in folds])
assert sorted(seen_val) == list(range(500)), "every box is validated once"
for tr, va in folds:
    assert not (set(g[tr]) & set(g[va])), "a recording is never in both sides of a fold"
assert [list(a) for a, _ in folds] == [list(a) for a, _ in dm.group_folds(g, 5)]
assert len(dm.group_folds(g, 20)) == 7                                # no more folds than recordings
try:
    dm.group_folds(np.array(["only"] * 30), 5)
except ValueError as e:
    assert "at least two" in str(e)
else:
    raise AssertionError("one recording cannot be cross-validated")
ok("folds hold whole recordings, validate every box once, are the same every time, and one recording alone is refused")

# ---------------------------------------------------------------- 2c k nearest neighbours
rng = np.random.default_rng(5)
A, y = rng.normal(size=(60, 3)), rng.normal(size=60)
Q = np.vstack([rng.normal(size=(10, 3)), A[:2]])                      # the last two queries are training rows themselves (distance 0)
for k in (1, 3, 7):
    for w in ("uniform", "distance"):
        ref = []
        for q in Q:
            d = np.sqrt(((A - q) ** 2).sum(1))
            idx = np.argsort(d, kind="stable")[:k]
            wt = 1.0 / np.maximum(d[idx], 1e-9) if w == "distance" else np.ones(k)
            ref.append((wt * y[idx]).sum() / wt.sum())
        got = dm._knn_predict(A, y, Q, k, w)
        assert np.allclose(got, ref, atol=1e-9), (k, w, np.abs(got - np.asarray(ref)).max())
ok("k nearest neighbours: the same as a plain loop over the rows, uniform and by distance, also for a query that is a training row")

knn = dm.make("knn", S, 1).fit(train)
assert knn.k in dm.KNN.K_GRID and knn.weights in dm.KNN.W_GRID and len(knn.info["cv_median_rel_err"]) == 12 and knn.info["cv_folds"] == 5
assert med(knn.predict_boxes(val), val.truth) < 0.08
fixed = dm.make("knn", S, 1).fit(train, k=9, weights="distance")
assert fixed.k == 9 and fixed.weights == "distance" and "cv_median_rel_err" not in fixed.info
ok(f"k nearest neighbours chose k = {knn.k}, {knn.weights} weights by cross-validation on the training boxes; error {med(knn.predict_boxes(val), val.truth):.3f}")

# ---------------------------------------------------------------- 2e Gaussian process
from sklearn.gaussian_process import GaussianProcessRegressor  # noqa: E402 (the second half of this test needs scikit-learn)

small = scene(220, 6, noise=0.05)
gp = dm.make("gp", S, 1, seed=3).fit(small, restarts=1)
Xq = scene(60, 7, noise=0.05).X()
mean_np, std_np = gp.predict_log_std(Xq)
mean_sk, std_sk = gp._sk.predict(gp.sd.apply(Xq), return_std=True)
assert np.allclose(mean_np, mean_sk, atol=1e-8) and np.allclose(gp.predict_log(Xq), mean_sk, atol=1e-8), np.abs(mean_np - mean_sk).max()
assert np.allclose(std_np, std_sk, atol=1e-7), np.abs(std_np - std_sk).max()
ok("the Gaussian process answers with numpy exactly as scikit-learn does: the mean to 1e-8 and the spread to 1e-7")

big = scene(1500, 8, noise=0.06)
gp2 = dm.make("gp", S, 1, seed=0).fit(big, max_rows=400, restarts=1)
assert gp2.info["rows"] == 400 and gp2.info["subsampled_from"] == 1500 and len(gp2.Xs) == 400
gp3 = dm.make("gp", S, 1, seed=0).fit(big, max_rows=400, restarts=1)
assert np.allclose(gp3.alpha, gp2.alpha) and np.allclose(gp3.Xs, gp2.Xs), "the same seed takes the same rows"
vb = scene(500, 9, noise=0.06)
m_, s_ = gp2.predict_log_std(vb.X())
cal = dm.calibration(np.log(np.clip(vb.dist, 0.2, 60)), m_, s_)
assert abs(cal["0.68"] - 0.68) < 0.10 and abs(cal["0.95"] - 0.95) < 0.06, cal
ls = gp2.info["length_scales"]
assert ls["ln_height"] < ls["centre_x"], ls                                          # the size of the box matters, where it is sideways does not
assert "centre_x" in gp2.info["at_bound"] and "ln_height" not in gp2.info["at_bound"], gp2.info["at_bound"]
ok(f"Gaussian process: subsampled 1500 -> 400 rows and says so; its 68% / 95% intervals hold {cal['0.68']:.2f} / {cal['0.95']:.2f} of the boxes; length scale of ln height {ls['ln_height']:.2f} vs sideways {ls['centre_x']:.1f}")

# ---------------------------------------------------------------- 2d gradient boosting
bo = dm.make("boosting", S, 1, seed=0).fit(train, folds=3, learning_rates=(0.1,), depths=(2, 3), max_iter=80)
assert bo.chosen["max_depth"] in (2, 3) and 1 <= bo.chosen["trees"] <= 80 and set(bo.info["cv"]) == {"lr=0.1,depth=2", "lr=0.1,depth=3"}
assert med(bo.predict_boxes(val), val.truth) < 0.09, med(bo.predict_boxes(val), val.truth)
bo2 = dm.make("boosting", S, 1, seed=0).fit(train, folds=3, learning_rates=(0.1,), depths=(2, 3), max_iter=80)
assert np.allclose(bo.predict_boxes(val), bo2.predict_boxes(val)), "same seed, same model"
ok(f"gradient boosting chose depth {bo.chosen['max_depth']} and {bo.chosen['trees']} trees by grouped cross-validation; error {med(bo.predict_boxes(val), val.truth):.3f}")

# ---------------------------------------------------------------- saved files
models = {"pinhole": pin, "loglinear": noisy_ll, "knn": knn, "gp": gp2, "boosting": bo}
for fam, m in models.items():
    path = os.path.join(TMP, fam + dm.EXT)
    m.save(path, scores={"dist_median_err": 0.06})
    hdr = dm.read_header(path)
    assert hdr["family"] == fam and hdr["scores"]["dist_median_err"] == 0.06 and hdr["nc"] == 1
    json.load(open(path, encoding="utf-8"))                                           # plain JSON text
    if fam == "boosting":
        try:
            dm.load(path)
        except dm.UntrustedModel as e:
            assert "pickle" in str(e)
        else:
            raise AssertionError("a pickle was read without trust")
        back = dm.load(path, trust_pickle=True)
    else:
        back = dm.load(path)                                                          # no pickle: nothing to trust
    assert type(back) is type(m) and np.array_equal(back.predict_boxes(val), m.predict_boxes(val)), fam
assert dm.read_header(os.path.join(TMP, "boosting" + dm.EXT))["pickled"] is True and dm.read_header(os.path.join(TMP, "gp" + dm.EXT))["pickled"] is False
open(os.path.join(TMP, "not.opdm"), "w").write('{"format": "something else"}')
assert dm.read_header(os.path.join(TMP, "not.opdm")) is None and not dm.is_distance_model_file(os.path.join(TMP, "none.opdm"))
try:
    dm.load(os.path.join(TMP, "not.opdm"))
except ValueError:
    pass
else:
    raise AssertionError("a file of another kind was read")
gp_back = dm.load(os.path.join(TMP, "gp.opdm"))
m3, s3 = gp_back.predict_log_std(Xq)
assert np.allclose(m3, gp2.predict_log_std(Xq)[0], atol=1e-10) and np.allclose(s3, gp2.predict_log_std(Xq)[1], atol=1e-9)
ok("every kind is saved as one file and answers exactly as before; the file with a pickle is read only when trusted; the spread of a loaded Gaussian process is the same")

# ---------------------------------------------------------------- answering for boxes of the original picture
W0, H0 = 640, 480
orig = np.array([[200.0, 100.0, 300.0, 400.0], [10.0, 20.0, 70.0, 200.0]])
lb = dd.orig_to_letterbox(orig, W0, H0, S)
for m in models.values():
    a, b = m.predict_m_orig(orig, W0, H0), m.predict_m(lb)
    assert np.allclose(a, b) and np.all((a >= 0.2) & (a <= 60.0)), (m.family, a, b)
wild = np.array([[0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 640.0, 640.0]])
for m in models.values():
    a = m.predict_m(wild)
    assert np.all(np.isfinite(a)) and np.all((a >= 0.2) & (a <= 60.0)), (m.family, a)
ok("boxes of the original picture are moved into the letterboxed frame first; answers stay inside 0.2 - 60 m, also for absurd boxes")

# ---------------------------------------------------------------- they all score on the shared harness
rows = {}
for fam, m in models.items():
    rows[fam] = med(m.predict_boxes(val), val.truth)
assert all(v < 0.09 for v in rows.values()), rows
ok("on a made-up scene with 6% label noise every kind is within 9% of the TRUE distances: " + ", ".join(f"{k} {v:.3f}" for k, v in rows.items()))

assert pin.n_params() == 1 and noisy_ll.n_params() == 3 and knn.n_params() == 0 and gp2.n_params() == 8 and bo.n_params() > 0
try:
    dm.make("nope")
except ValueError:
    pass
else:
    raise AssertionError
ok("parameter counts: formula 1, log-linear 3, k-NN 0 (it is its rows), Gaussian process 8 (6 length scales, constant, noise), boosting = its tree nodes")

print("dist models ok", flush=True)
