"""train_classical_job.py - trains the distance models that look at the box alone and scores them all the same way: the formula and four classical regressors.
Run by the Trainer as   python train_classical_job.py <run>/job.json .   No Qt, no PyTorch here: numpy, and scikit-learn for gradient boosting and the Gaussian process.

    pinhole   2a   loglinear 2b   knn 2c   boosting 2d   gp 2e        (dist_models.py explains each one)

What it does, in order:
    1  reads the frozen training copy the Trainer made for this run (dist_data): original pictures only, boxes with a distance only; prints what it read and stops with a plain
       message when there is nothing to train on or to score
    2  fits each chosen variant on the training boxes (the standardising, k, the grids, the constant of the formula: nothing from the validation boxes)
    3  scores it on the validation boxes with the shared harness (eval_harness): median error, within 20%, mean error, signed bias, by range, each with a 95% bootstrap interval
       (resampling recordings first when the boxes carry them), and the paired difference against the formula
    4  writes, in the run folder:
         results.csv               one row per variant: the comparison table
         paired.csv                the difference of each variant from the formula, with its interval
         variants/<name>/result.json       the result file of the variant (the schema of the specification)
         variants/<name>/predictions.csv   every validation box: picture, class, labelled and predicted metres (figures are drawn from these files, not by hand)
         models/<name>.opdm        the model, as one small file
         result.json               what the Trainer reads: which variants were made and the best one, by median error on validation
    5  saves the models in the Distance folder of the project (job["models_dirs"][0]); a distance model is NOT put in the Annotator's Models folder: it finds no boxes, so
       the Annotator could not use it.
A variant that cannot be made (scikit-learn is not installed, say) is reported and the others go on.
"""
import csv
import json
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import numpy as np  # noqa: E402

import dist_data as dd  # noqa: E402
import dist_models as dmod  # noqa: E402
import eval_harness as eh  # noqa: E402
import job_common as jc  # noqa: E402

ORDER = ("pinhole", "loglinear", "knn", "boosting", "gp")
LABEL = {"pinhole": "formula k / height", "loglinear": "log-linear regression", "knn": "k nearest neighbours", "boosting": "gradient boosting", "gp": "Gaussian process"}
DEFAULTS = {"seed": 0, "folds": 5, "n_boot": 2000, "gp_max_rows": 6000, "gp_restarts": 2, "loglinear_width": False,
            "boosting_learning_rates": [0.03, 0.1], "boosting_depths": [2, 3, 4], "boosting_max_iter": 500}
COLS = ["variant", "id", "median_rel_err", "median_rel_err_lo", "median_rel_err_hi", "within20", "within20_lo", "within20_hi", "mae_m", "mae_m_lo", "mae_m_hi",
        "signed_bias", "parameters", "fit_seconds"]


def fail(job, message):
    print(message, flush=True)
    jc.write_result(job, ok=False, message=message)
    return 1


def pct(x):
    return "-" if x is None or x != x else f"{x * 100:.1f}%"


def chosen_variants(job):
    p = job.get("params") or {}
    want = p.get("variants")
    if not want:
        size = job.get("size") or "all"
        want = list(ORDER) if size in ("all", "") else [size]
    bad = [v for v in want if v not in dmod.FAMILIES]
    if bad:
        raise ValueError(f"Unknown distance model(s): {bad}. Choose from {', '.join(ORDER)}.")
    return [v for v in ORDER if v in want]


def needs_missing(variant):
    """The packages a variant imports that this Python does not have."""
    import importlib.util
    mods = {"scikit-learn": "sklearn", "scipy": "scipy"}
    out = [n for n in dmod.FAMILIES[variant].needs if importlib.util.find_spec(mods.get(n, n)) is None]
    if variant == "gp" and importlib.util.find_spec("scipy") is None and "scipy" not in out:
        out.append("scipy")
    return out


def fit_one(variant, train, val, P, seed, groups, out_dir):
    """Fits and scores one variant.  -> (model, result dict, validation predictions)."""
    opts = {}
    if variant == "loglinear":
        opts["use_width"] = bool(P.get("loglinear_width"))
    model = dmod.make(variant, train.imgsz, train.nc, train.names, seed, **opts)
    t0 = time.time()
    fit_kw = {}
    if variant in ("knn", "boosting"):
        fit_kw.update(folds=int(P["folds"]), groups=groups)
    if variant == "boosting":
        fit_kw.update(learning_rates=[float(x) for x in P["boosting_learning_rates"]], depths=[int(x) for x in P["boosting_depths"]], max_iter=int(P["boosting_max_iter"]))
    if variant == "gp":
        fit_kw.update(max_rows=int(P["gp_max_rows"]), restarts=int(P["gp_restarts"]))
    model.fit(train, **fit_kw)
    seconds = time.time() - t0
    pred = model.predict_boxes(val)
    extra = {"id": model.id, "model_info": model.info, "parameters": model.n_params(), "family": variant, "classes": train.names, "imgsz": train.imgsz,
             "train_recordings": int(len(set(train.group))), "val_recordings": int(len(set(val.group)))}
    if variant == "gp":
        mean, std = model.predict_log_std(val.X())
        truth = np.log(np.clip(val.dist, dd.D_MIN, dd.D_MAX))
        extra["calibration"] = dmod.calibration(truth, mean, std)
        extra["spread_by_range"] = spread_by_range(val.dist, std, np.abs(truth - mean))
        extra["lidar_returns"] = "not available: the frozen copy keeps the distance of a box, not how many LiDAR returns it came from"
    res = eh.result_json("2", variant, pred, val.dist, seed=seed, split="validation", config=dict(model.config(), **{k: P[k] for k in ("folds",) if variant in ("knn", "boosting")}),
                         group=val.group, train_rows=len(train), train_seconds=seconds, n_boot=int(P["n_boot"]), extra=extra)
    return model, res, pred


def spread_by_range(true_m, std_log, abs_err_log):
    """For a model that says how sure it is: in each range of labelled distance, the median spread it claims and the median error it made (both in ln d)."""
    out = {}
    for lo, hi in zip(eh.BINS[:-1], eh.BINS[1:]):
        m = (true_m >= lo) & (true_m < hi)
        out[eh.range_key(lo, hi)] = {"n": int(m.sum()), "median_claimed_spread_log": float(np.median(std_log[m])) if m.any() else None,
                                     "median_abs_error_log": float(np.median(abs_err_log[m])) if m.any() else None}
    return out


def write_predictions(path, val, pred):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["image", "class", "labelled_m", "predicted_m"])
        for name, c, d, p in zip(val.image, val.cls, val.dist, pred):
            w.writerow([name, val.names[int(c)] if val.names else int(c), f"{d:.3f}", f"{p:.4f}"])


def table_row(res):
    m, ci = res["metrics"], res["ci95"]
    f = lambda v: f"{v:.6g}"          # noqa: E731
    return [res["variant"], res.get("id", ""), f(m["median_rel_err"]), f(ci["median_rel_err"][0]), f(ci["median_rel_err"][1]), f(m["within20"]), f(ci["within20"][0]),
            f(ci["within20"][1]), f(m["mae_m"]), f(ci["mae_m"][0]), f(ci["mae_m"][1]), f(m["signed_bias"]), res.get("parameters", ""), f"{res['train_seconds']:.2f}"]


def main():
    job = jc.load_job()
    P = dict(DEFAULTS, **(job.get("params") or {}))
    seed = int(P["seed"])
    run = job["run_dir"]
    try:
        variants = chosen_variants(job)
    except ValueError as e:
        return fail(job, str(e))
    print("Reading the training data ...", flush=True)
    imgsz = int(job.get("imgsz") or 640)
    try:
        src = dd._source(job["data_yaml"], job.get("classes") or None)
        train = dd.load_boxes(job["data_yaml"], "train", imgsz=imgsz, unique=True, source=src)
        val = dd.load_boxes(job["data_yaml"], "val", imgsz=imgsz, unique=True, source=src)
    except Exception as e:  # noqa: BLE001
        return fail(job, f"The training data could not be read ({type(e).__name__}: {e}).")
    lines, err = dd.input_check(train, val)
    print("\n".join(lines), flush=True)
    want = (job.get("dist_counts") or {}).get("train")
    if err:
        return fail(job, err + (f" The Trainer counted {want} training boxes with a distance when it made the run's copy, so they were lost on the way: please report this." if want else ""))
    if not (np.all(dd.rows_ok(train)) and np.all(dd.rows_ok(val))):
        return fail(job, "Some boxes have numbers that are not finite (a box of no size, or a distance that is not positive): the data needs a look before a model is fitted to it.")
    groups, kind = dmod.cv_groups_of(train)
    print(f"Cross-validation is grouped by {kind} ({len(set(groups))} groups).", flush=True)
    if len(set(groups)) < 2 and any(v in ("knn", "boosting") for v in variants):
        return fail(job, "The training boxes come from one recording and cannot be split into groups for cross-validation. Use more recordings.")
    print(f"Variants       : {', '.join(variants)}   (seed {seed})\n", flush=True)

    models_out = os.path.join(run, "models")
    os.makedirs(models_out, exist_ok=True)
    results, models, failed, preds = {}, {}, {}, {}
    for v in variants:
        miss = needs_missing(v)
        if miss:
            failed[v] = f"needs {', '.join(miss)}, which this Python does not have (pip install {' '.join(miss)})"
            print(f"[{v}] skipped: {failed[v]}", flush=True)
            continue
        print(f"[{v}] {LABEL[v]} ...", flush=True)
        try:
            model, res, pred = fit_one(v, train, val, P, seed, groups, run)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            failed[v] = f"{type(e).__name__}: {e}"
            print(f"[{v}] failed: {failed[v]}", flush=True)
            continue
        m = res["metrics"]
        print(f"[{v}] validation: median error {pct(m['median_rel_err'])} (95%: {pct(res['ci95']['median_rel_err'][0])} - {pct(res['ci95']['median_rel_err'][1])}), "
              f"within 20%: {pct(m['within20'])}, off by {m['mae_m']:.2f} m on average   [{res['train_seconds']:.1f} s, {res['parameters']} parameters]", flush=True)
        vdir = os.path.join(run, "variants", v)
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        write_predictions(os.path.join(vdir, "predictions.csv"), val, pred)
        scores = {"dist_median_err": round(m["median_rel_err"], 4), "dist_within_20": round(m["within20"], 4), "dist_mae_m": round(m["mae_m"], 3)}
        path = model.save(os.path.join(models_out, v + dmod.EXT), scores=scores,
                          extra={"trained": {"rows": len(train), "val_rows": len(val), "seconds": round(res["train_seconds"], 3), "seed": seed, "classes": train.names,
                                             "ci95_median_rel_err": res["ci95"]["median_rel_err"], "trainer": job.get("trainer"), "run": os.path.basename(run)}})
        results[v], models[v], preds[v] = res, path, pred
    if not results:
        return fail(job, "No distance model could be made: " + "; ".join(f"{k}: {v}" for k, v in failed.items()))

    with open(os.path.join(run, "results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for v in results:
            w.writerow(table_row(results[v]))
    paired = []
    if "pinhole" in results:
        for v in results:
            if v == "pinhole":
                continue
            d = eh.paired_diff(preds[v], preds["pinhole"], val.dist, group=val.group, n_boot=int(P["n_boot"]))
            paired.append(dict(d, variant=v, versus="pinhole"))
        with open(os.path.join(run, "paired.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["variant", "versus", "metric", "difference", "ci_lo", "ci_hi", "excludes_zero"])
            for d in paired:
                w.writerow([d["variant"], d["versus"], d["metric"], f"{d['diff']:.6g}", f"{d['ci95'][0]:.6g}", f"{d['ci95'][1]:.6g}", d["excludes_zero"]])
        print("\nDifference in median error from the formula (a negative number is better; real only when the interval leaves out zero):")
        for d in paired:
            print(f"  {d['variant']:10s} {d['diff'] * 100:+.2f} points   95%: {d['ci95'][0] * 100:+.2f} to {d['ci95'][1] * 100:+.2f}   -> " + ("a real difference" if d["excludes_zero"] else "not a real difference"))
    best = min(results, key=lambda k: results[k]["metrics"]["median_rel_err"])
    bm = results[best]["metrics"]
    info = {"dist_median_err": round(bm["median_rel_err"], 4), "dist_within_20": round(bm["within20"], 4), "dist_mae_m": round(bm["mae_m"], 3), "dist_variant": best}
    print(f"\nDone. The best by median error on the validation boxes is {LABEL[best]}: {pct(bm['median_rel_err'])}, within 20%: {pct(bm['within20'])}.", flush=True)
    if len(results) > 1:
        print("Differences below about half a point on a few hundred boxes are within the noise: read the intervals, not the ranking.", flush=True)

    saved = []
    mdirs = job.get("models_dirs") or []
    if mdirs:
        d = os.path.join(mdirs[0], "Distance")
        os.makedirs(d, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime())
        for v, p in models.items():
            dest, n = os.path.join(d, f"{v}_{stamp}{dmod.EXT}"), 1
            while os.path.exists(dest):
                n += 1
                dest = os.path.join(d, f"{v}_{stamp}_{n}{dmod.EXT}")
            shutil.copyfile(p, dest)
            saved.append(dest)
    jc.write_result(job, ok=True, kind="classical_regress", best=models[best], best_variant=best, info=info, saved=saved, finished=time.time(),
                    models=[{"variant": v, "id": results[v].get("id"), "path": models[v], "scores": {"dist_median_err": results[v]["metrics"]["median_rel_err"],
                                                                                                  "dist_within_20": results[v]["metrics"]["within20"],
                                                                                                  "dist_mae_m": results[v]["metrics"]["mae_m"]}} for v in models],
                    failed=failed, paired=paired, warning=("; ".join(f"{k}: {v}" for k, v in failed.items()) or None))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"\nTraining failed ({type(e).__name__}: {e}).", flush=True)
        code = 1
    sys.exit(code)
