import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""eval_harness.py (the one way a distance model is scored): known answers for every metric, the same numbers as the Trainer's own scoring,
bootstrap intervals that behave (a constant error has no spread, a grouped bootstrap is wider than an ungrouped one when recordings differ, the
interval covers the truth about as often as it says), paired differences on shared resamples, seeds, and what is refused.
No Qt, no torch: the harness imports with numpy alone."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
sys.path.insert(0, os.path.join(ADD, "trainer"))
import numpy as np

import eval_harness as eh

assert "torch" not in sys.modules and "PyQt6" not in sys.modules and "ultralytics" not in sys.modules, "the harness must import with numpy alone"


def ok(msg):
    print("ok:", msg, flush=True)


def reference_scores(pred, true):
    """The Trainer's own scoring (distance_model.distance_scores), written out again here because that module needs torch."""
    p, t = np.asarray(pred, float), np.asarray(true, float)
    rel = np.abs(p - t) / t
    edges = (0.0, 2.0, 5.0, 10.0, 20.0, float("inf"))
    bins = [float(np.median(rel[(t >= lo) & (t < hi)])) if ((t >= lo) & (t < hi)).any() else None for lo, hi in zip(edges[:-1], edges[1:])]
    return dict(median=float(np.median(rel)), within20=float((rel <= 0.2).mean()), mae=float(np.abs(p - t).mean()), bins=bins)


# ---------------------------------------------------------------- known answers
true = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
pred = np.array([1.1, 1.5, 4.0, 10.0, 12.0])             # relative errors 0.1, 0.25, 0, 0.25, 0.25
s = eh.score(pred, true, n_boot=0)
m = s["metrics"]
assert abs(m["median_rel_err"] - 0.25) < 1e-12, m
assert abs(m["within20"] - 2 / 5) < 1e-12, m
assert abs(m["mae_m"] - np.mean([0.1, 0.5, 0.0, 2.0, 4.0])) < 1e-12, m
assert abs(m["signed_bias"] - 0.0) < 1e-12, m                                       # (0.1, -0.25, 0, 0.25, -0.25): the middle one is 0
assert eh.signed_bias(true * 1.2, true) > 0.19 and eh.signed_bias(true * 0.8, true) < -0.19
assert s["n"] == 5 and s["ci95"] == {}, s
br = m["by_range"]
assert list(br) == ["0-2", "2-5", "5-10", "10-20", "20+"], list(br)
assert br["0-2"]["n"] == 1 and abs(br["0-2"]["median_rel_err"] - 0.1) < 1e-12, br
assert br["2-5"]["n"] == 2 and abs(br["2-5"]["median_rel_err"] - 0.125) < 1e-12, br          # 2.0 (0.25) and 4.0 (0.0): median 0.125
assert br["5-10"]["n"] == 1 and br["10-20"]["n"] == 1 and br["20+"] == {"n": 0, "median_rel_err": None}, br
ok("every metric and the by-range table on a hand-worked example (a label on an edge goes to the upper range)")

rng = np.random.default_rng(1)
T = np.exp(rng.uniform(np.log(0.5), np.log(25), 793))
P = T * np.exp(rng.normal(0.02, 0.09, 793))
ref, got = reference_scores(P, T), eh.score(P, T, n_boot=0)["metrics"]
assert abs(ref["median"] - got["median_rel_err"]) < 1e-15 and abs(ref["within20"] - got["within20"]) < 1e-15 and abs(ref["mae"] - got["mae_m"]) < 1e-15
assert [b["median_rel_err"] for b in got["by_range"].values()] == ref["bins"]
ok("the same numbers as the Trainer's own scoring on 793 boxes")

# ---------------------------------------------------------------- the intervals
const = eh.score(T * 1.1, T, n_boot=200)                 # every box is off by exactly 10%: no spread at all
assert abs(const["metrics"]["median_rel_err"] - 0.1) < 1e-12
lo, hi = const["ci95"]["median_rel_err"]
assert abs(lo - 0.1) < 1e-12 and abs(hi - 0.1) < 1e-12, const["ci95"]
ok("a constant error has an interval of zero width")

full = eh.score(P, T, n_boot=2000, seed=0)
for k in ("median_rel_err", "within20", "mae_m", "signed_bias"):
    lo, hi = full["ci95"][k]
    assert lo <= full["metrics"][k] <= hi or k == "signed_bias", (k, lo, full["metrics"][k], hi)
assert full["ci95"]["median_rel_err"][1] - full["ci95"]["median_rel_err"][0] < 0.03, full["ci95"]       # about +-0.4 points on 793 boxes
again, other = eh.score(P, T, n_boot=300, seed=0), eh.score(P, T, n_boot=300, seed=1)
assert again["ci95"] == eh.score(P, T, n_boot=300, seed=0)["ci95"] and again["ci95"] != other["ci95"]
ok("intervals contain the estimate, are about as wide as they should be, and are the same for the same seed")

# coverage: the 95% interval of the median error should hold the true median error about 95% of the time
pop_T = np.exp(rng.uniform(np.log(0.5), np.log(25), 200000))
pop_P = pop_T * np.exp(rng.normal(0.0, 0.1, 200000))
truth_med = eh.median_rel_err(pop_P, pop_T)
hit, trials = 0, 120
for k in range(trials):
    i = rng.integers(0, 200000, 300)
    lo, hi = eh.score(pop_P[i], pop_T[i], n_boot=300, seed=k)["ci95"]["median_rel_err"]
    hit += lo <= truth_med <= hi
assert 0.85 <= hit / trials <= 1.0, hit / trials
ok(f"the interval holds the true median error in {hit} of {trials} samples")

# recordings: boxes of one recording share their error, so the grouped interval must be wider than the one that ignores recordings
g = np.repeat(np.arange(12), 60)
level = rng.normal(0, 0.06, 12)[g]                        # every recording has its own bias
Pg = T[:720] * np.exp(level + rng.normal(0, 0.03, 720))
plain, grouped = eh.score(Pg, T[:720], n_boot=600, seed=2), eh.score(Pg, T[:720], group=g, n_boot=600, seed=2)
wp, wg = (plain["ci95"]["median_rel_err"][1] - plain["ci95"]["median_rel_err"][0]), (grouped["ci95"]["median_rel_err"][1] - grouped["ci95"]["median_rel_err"][0])
assert grouped["grouped"] and not plain["grouped"] and wg > 1.5 * wp, (wp, wg)
sets = eh.resamples(720, g, 5, seed=0)
assert all(len(set(g[i])) <= 12 for i in sets) and all(len(i) >= 1 for i in sets)
ok(f"a grouped bootstrap is wider ({wg:.4f}) than one that ignores recordings ({wp:.4f}) when recordings differ")

# ---------------------------------------------------------------- paired differences
same = eh.paired_diff(P, P, T, n_boot=300)
assert same["diff"] == 0 and same["ci95"] == [0.0, 0.0] and not same["excludes_zero"], same
better = T * np.exp(rng.normal(0.0, 0.05, 793))
worse = T * np.exp(rng.normal(0.0, 0.15, 793))
d = eh.paired_diff(better, worse, T, n_boot=500)
assert d["diff"] < 0 and d["ci95"][1] < 0 and d["excludes_zero"], d
d2 = eh.paired_diff(worse, better, T, n_boot=500)
assert d2["diff"] > 0 and d2["ci95"][0] > 0 and abs(d["diff"] + d2["diff"]) < 1e-12, d2
noise = T * np.exp(rng.normal(0.0, 0.09, 793))
twin = noise * np.exp(rng.normal(0.0, 0.0005, 793))     # the same model, one part in two thousand off
dd = eh.paired_diff(noise, twin, T, metric="within20", n_boot=500)
assert not dd["excludes_zero"], dd
assert eh.paired_diff(better, worse, T, metric="mae_m", n_boot=200)["diff"] < 0
ok("paired differences: zero for the same model, real for a clearly better one, not real for a twin")

# the pair of models shares its resamples: a model that is only a little better has a much tighter interval than two independent intervals say
a = T * np.exp(rng.normal(0.0, 0.09, 793))
b = a * np.exp(rng.normal(0.0, 0.02, 793))
pd = eh.paired_diff(a, b, T, n_boot=800)
sa, sb = eh.score(a, T, n_boot=800, seed=0), eh.score(b, T, n_boot=800, seed=0)
width_alone = sa["ci95"]["median_rel_err"][1] - sa["ci95"]["median_rel_err"][0]
assert pd["ci95"][1] - pd["ci95"][0] < 0.85 * width_alone, (pd, width_alone)
ok("a paired interval is tighter than the interval of either model alone (they share their resamples)")

# ---------------------------------------------------------------- seeds
cs = eh.across_seeds([1.0, 2.0, 3.0, 4.0, 5.0], n_boot=500)
assert cs["n"] == 5 and cs["mean"] == 3.0 and abs(cs["sd"] - np.sqrt(2.5)) < 1e-12 and cs["median"] == 3.0 and cs["min"] == 1.0 and cs["max"] == 5.0
assert 1.0 <= cs["ci95_median"][0] <= 3.0 <= cs["ci95_median"][1] <= 5.0, cs
cs2 = eh.across_seeds([0.07, None, float("nan"), 0.08], n_boot=100)
assert cs2["n"] == 2 and abs(cs2["mean"] - 0.075) < 1e-12, cs2
assert eh.across_seeds([])["n"] == 0
ok("mean, spread and the interval of the median over seeds; a missing seed is left out and counted")

# ---------------------------------------------------------------- what is refused
for bad, why in ((lambda: eh.score([1, 2], [1, 2, 3]), "length"), (lambda: eh.score([1.0, float("nan")], [1.0, 2.0]), "nan prediction"),
                 (lambda: eh.score([1.0, 2.0], [1.0, 0.0]), "zero label"), (lambda: eh.score([1.0], [float("inf")]), "infinite label"),
                 (lambda: eh.score([], []), "empty"), (lambda: eh.score([1.0, 2.0], [1.0, 2.0], group=[1]), "group length"),
                 (lambda: eh.paired_diff([1.0], [1.0], [1.0], metric="nope"), "metric")):
    try:
        bad()
    except ValueError as e:
        assert str(e), why
    else:
        raise AssertionError("not refused: " + why)
ok("lengths that differ, predictions that are not numbers, labels that are not distances, nothing to score and an unknown metric are all refused")

# ---------------------------------------------------------------- the result file
rj = eh.result_json("2", "gp_rbf_ard", P, T, seed=3, config={"kernel": "rbf_ard", "restarts": 2}, train_rows=4708, train_seconds=12.34567, n_boot=100,
                    extra={"note": "x"})
text = json.dumps(rj)                                      # it must be plain JSON
rj2 = json.loads(text)
for k in ("arm", "variant", "seed", "split", "n", "metrics", "ci95", "config", "env", "train_rows", "train_seconds"):
    assert k in rj2, k
assert rj2["arm"] == "2" and rj2["variant"] == "gp_rbf_ard" and rj2["seed"] == 3 and rj2["split"] == "validation" and rj2["n"] == 793
assert rj2["train_rows"] == 4708 and rj2["train_seconds"] == 12.346 and rj2["note"] == "x" and rj2["config"]["restarts"] == 2
assert set(rj2["ci95"]) >= {"median_rel_err", "within20", "mae_m"} and set(rj2["env"]) >= {"python", "numpy", "commit"}
assert rj2["metrics"]["by_range"]["0-2"]["n"] >= 0
ok("the result file has the schema of the specification and is plain JSON")

assert float(eh.clip_m([0.01, 5, 900])[0]) == 0.2 and float(eh.clip_m([0.01, 5, 900])[2]) == 60.0
ok("answers are clipped to 0.2 - 60 m like the Trainer's own models")

print("eval harness ok", flush=True)
