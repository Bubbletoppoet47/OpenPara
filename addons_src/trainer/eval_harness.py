"""eval_harness.py - one way to score a distance model, used by every model type that gives a distance.  numpy only: no Qt, no PyTorch, no Ultralytics, no scikit-learn.

    score(pred_m, true_m, ...)          the metrics of a set of boxes, each with a 95% bootstrap interval, as the dict of a result file
    paired_diff(pred_a, pred_b, true_m) the interval of the difference of a metric between two models on the SAME resamples
    across_seeds(values)                mean, spread and the interval of the median of one number over seeds
    result_json(...)                    the whole result file of one scored configuration (see "The result file" below)

The definitions are fixed (they are the Trainer's own, train_distance_job / distance_model.distance_scores):
    relative error   r = |predicted - labelled| / labelled          (relative to the LABEL)
    median_rel_err   median(r)                  the headline distance number
    within20         share of boxes with r <= 0.20
    mae_m            mean |predicted - labelled|, metres
    signed_bias      median((predicted - labelled) / labelled)      > 0: the model says too far
    by_range         median r and the box count in 0-2, 2-5, 5-10, 10-20 and 20+ m, grouped by the LABEL

Bootstrap: boxes are resampled with replacement, B times (default 2000), and the 95% percentile interval is taken.  When every box has a recording id (`group`),
the recordings are resampled first and the boxes inside each chosen recording next, because boxes of one recording are not independent of each other.
paired_diff() uses the same resamples for both models; call a difference real only when its interval leaves out zero.

The result file (one JSON per scored configuration)
    {"arm", "variant", "seed", "split", "n", "metrics": {...}, "ci95": {...}, "config": {...}, "env": {...}, "train_rows", "train_seconds"}
"""
import math
import os
import platform
import sys

import numpy as np

BINS = (0.0, 2.0, 5.0, 10.0, 20.0, float("inf"))          # metres; the edges of by_range (the Trainer's BINS, with 0 and infinity)
CI_METRICS = ("median_rel_err", "within20", "mae_m", "signed_bias")
D_MIN, D_MAX = 0.2, 60.0                                    # a distance model's answer is kept inside this range (distance_model.D_MIN / D_MAX)


# ------------------------------------------------------------------ the metrics
def rel_err(pred, true):
    return np.abs(pred - true) / true


def median_rel_err(pred, true):
    return float(np.median(rel_err(pred, true)))


def within20(pred, true):
    return float(np.mean(rel_err(pred, true) <= 0.2))


def mae_m(pred, true):
    return float(np.mean(np.abs(pred - true)))


def signed_bias(pred, true):
    return float(np.median((pred - true) / true))


METRICS = {"median_rel_err": median_rel_err, "within20": within20, "mae_m": mae_m, "signed_bias": signed_bias}


def range_key(lo, hi):
    return f"{lo:g}-{hi:g}" if math.isfinite(hi) else f"{lo:g}+"


def by_range(pred, true, bins=BINS):
    """{"0-2": {"n", "median_rel_err"}, ...}: boxes grouped by their LABEL.  A range with no box has n 0 and a median of None."""
    out = {}
    r = rel_err(pred, true)
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (true >= lo) & (true < hi)
        out[range_key(lo, hi)] = {"n": int(m.sum()), "median_rel_err": float(np.median(r[m])) if m.any() else None}
    return out


# ------------------------------------------------------------------ input check
def _arrays(pred_m, true_m, group=None):
    p, t = np.asarray(pred_m, float).ravel(), np.asarray(true_m, float).ravel()
    if len(p) != len(t):
        raise ValueError(f"{len(p)} predictions but {len(t)} labelled distances: they must be for the same boxes in the same order.")
    if not len(t):
        raise ValueError("There is no box to score.")
    if not np.all(np.isfinite(t)) or np.any(t <= 0):
        raise ValueError("A labelled distance is not a positive number of metres.")
    if not np.all(np.isfinite(p)):
        raise ValueError(f"{int((~np.isfinite(p)).sum())} predictions are not numbers: nothing is scored until every box has one.")
    g = None
    if group is not None:
        g = np.asarray(group).ravel()
        if len(g) != len(t):
            raise ValueError(f"{len(g)} recording ids for {len(t)} boxes.")
    return p, t, g


# ------------------------------------------------------------------ the resamples
def resamples(n, group=None, n_boot=2000, seed=0):
    """The resamples of n boxes: a list of n_boot index arrays (all of length n when the boxes are not grouped).
    With `group` the recordings are drawn first (with replacement) and the boxes of every chosen recording next (with replacement)."""
    rng = np.random.default_rng(seed)
    if group is None:
        idx = rng.integers(0, n, size=(n_boot, n))
        return list(idx)
    keys, inv = np.unique(np.asarray(group), return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(keys))]
    out = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(keys), size=len(keys))
        parts = [members[g][rng.integers(0, len(members[g]), size=len(members[g]))] for g in pick]
        out.append(np.concatenate(parts))
    return out


def _interval(values):
    lo, hi = np.percentile(values, [2.5, 97.5])
    return [float(lo), float(hi)]


def boot_ci(metric, pred, true, sets):
    return _interval([metric(pred[i], true[i]) for i in sets])


# ------------------------------------------------------------------ the public functions
def score(pred_m, true_m, *, bins=BINS, group=None, n_boot=2000, seed=0, metrics=CI_METRICS):
    """The metrics of one model on a set of boxes.  -> {"n", "metrics": {median_rel_err, within20, mae_m, signed_bias, by_range}, "ci95": {metric: [lo, hi]}, "n_boot", "grouped"}.
    pred_m / true_m: predicted / labelled distances in metres, the same boxes in the same order.  group: a recording id per box (grouped bootstrap).  n_boot 0: no intervals."""
    p, t, g = _arrays(pred_m, true_m, group)
    m = {name: METRICS[name](p, t) for name in CI_METRICS}
    m["by_range"] = by_range(p, t, tuple(bins))
    out = {"n": int(len(t)), "metrics": m, "ci95": {}, "n_boot": int(n_boot), "grouped": g is not None}
    if n_boot and n_boot > 0:
        sets = resamples(len(t), g, int(n_boot), seed)
        out["ci95"] = {name: boot_ci(METRICS[name], p, t, sets) for name in metrics}
    return out


def paired_diff(pred_a, pred_b, true_m, metric="median_rel_err", *, group=None, n_boot=2000, seed=0):
    """The difference metric(a) - metric(b) on the SAME resamples.  -> {"metric", "diff", "ci95": [lo, hi], "excludes_zero", "n", "n_boot"}.
    A negative difference of an error means a is better.  The difference is real only when `excludes_zero` is True."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric {metric!r}: {', '.join(METRICS)}")
    a, t, g = _arrays(pred_a, true_m, group)
    b, _t, _g = _arrays(pred_b, true_m, group)
    f = METRICS[metric]
    sets = resamples(len(t), g, int(n_boot), seed)
    diffs = [f(a[i], t[i]) - f(b[i], t[i]) for i in sets]
    lo, hi = _interval(diffs)
    return {"metric": metric, "diff": float(f(a, t) - f(b, t)), "ci95": [lo, hi], "excludes_zero": bool(lo > 0 or hi < 0), "n": int(len(t)), "n_boot": int(n_boot)}


def across_seeds(values, *, n_boot=2000, seed=0):
    """One number over several seeds (an arm that is stochastic runs 5).  -> {"n", "mean", "sd", "median", "min", "max", "ci95_median"}.
    The interval is the bootstrap interval of the median of the seeds' values (it is wide with 5 seeds; that is the information)."""
    v = np.asarray([x for x in values if x is not None and math.isfinite(x)], float)
    if not len(v):
        return {"n": 0, "mean": None, "sd": None, "median": None, "min": None, "max": None, "ci95_median": None}
    rng = np.random.default_rng(seed)
    med = np.median(v[rng.integers(0, len(v), size=(int(n_boot), len(v)))], axis=1)
    return {"n": int(len(v)), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else 0.0, "median": float(np.median(v)),
            "min": float(v.min()), "max": float(v.max()), "ci95_median": _interval(med)}


def env_info():
    """What the numbers were made with: Python, numpy, scikit-learn (when it is there), the platform and, when the code is in a git checkout, the commit."""
    env = {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()}
    try:
        import sklearn
        env["sklearn"] = sklearn.__version__
    except Exception:                                        # noqa: BLE001
        pass
    env["commit"] = _commit()
    return env


def _commit():
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=here, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:                                        # noqa: BLE001
        return None


def result_json(arm, variant, pred_m, true_m, *, seed=0, split="validation", config=None, group=None, train_rows=None, train_seconds=None,
                bins=BINS, n_boot=2000, boot_seed=0, extra=None):
    """The result file of one scored configuration (the schema of the header of this module).  `extra` adds fields of its own (kept under their names)."""
    s = score(pred_m, true_m, bins=bins, group=group, n_boot=n_boot, seed=boot_seed)
    out = {"arm": str(arm), "variant": str(variant), "seed": int(seed), "split": split, "n": s["n"], "metrics": s["metrics"], "ci95": s["ci95"],
           "n_boot": s["n_boot"], "grouped_bootstrap": s["grouped"], "config": dict(config or {}), "env": env_info(),
           "train_rows": None if train_rows is None else int(train_rows), "train_seconds": None if train_seconds is None else round(float(train_seconds), 3)}
    if extra:
        out.update(extra)
    return out


def clip_m(d):
    """A distance model's answer, kept inside the range the Trainer's own models keep to."""
    return np.clip(np.asarray(d, float), D_MIN, D_MAX)


if __name__ == "__main__":                                   # python eval_harness.py pred.csv truth.csv  (one number per line): prints the metrics
    if len(sys.argv) != 3:
        print("usage: eval_harness.py predicted.txt labelled.txt   (one distance in metres per line)")
        sys.exit(2)
    import json
    P, T = (np.loadtxt(a, ndmin=1) for a in sys.argv[1:3])
    print(json.dumps(score(P, T), indent=2))
