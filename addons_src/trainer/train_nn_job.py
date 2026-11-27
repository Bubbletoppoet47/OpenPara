"""train_nn_job.py - trains the small neural network of np_net.py on the rung of the ladder it is told, with as many learning rates and seeds as asked, and scores every run the
same way as the other distance models.   Run by the Trainer as   python train_nn_job.py <run>/job.json .   No Qt, no PyTorch: numpy only.

    size  "0" ... "8"               one rung of the ladder (0 = the 1986 recipe: sigmoid, mean squared error, plain gradient descent; each next rung changes one ingredient)
          "ladder"                  all nine rungs, in order
          "demo_sigmoid" "demo_relu_he" "demo_bn" (or "demos")   the deep-network demonstrations: 8 hidden layers, to see gradients vanish or not
    job["params"] (all optional)
          seeds     how many seeds per learning rate (default 1; the specification asks for 5 where a result is claimed)
          seed      the first seed (the others follow)
          lrs       "grid" = the specification's grid (8 learning rates for gradient descent, 5 for Adam), a list of numbers, or nothing = the rung's default learning rate
          epochs    (default: the job's epochs, else 200)   batch, depth, width, hidden, activation, init, optimizer, momentum, weight_decay, patience, early_stopping: replace a setting of the rung
          target_err   the error whose first epoch is reported (default 7.5%)      n_boot   bootstrap resamples (default 2000)

Every run is trained from random weights on the training boxes of the frozen copy (original pictures only, boxes with a distance), watching the validation boxes, which it never trains
on.  A run whose loss blows up is stopped, kept in the table as diverged and counted; it is not left out.  For each rung the learning rate with the lowest median validation error over
the seeds is the rung's (a diverged run counts as an error of infinity); the run of that learning rate whose error is the middle one is the run whose model is saved and whose predictions
are scored with intervals.  The learning rate is therefore chosen on the same validation boxes it is scored on: the table lists every learning rate so that the size of that choice can
be seen, and result.json says so.

Written to the run folder:
    results.csv       one row per run: rung, learning rate, seed, diverged?, epochs, best epoch, epochs to the target, the validation scores, seconds, and where its curve is
    lr_sweep.csv      one row per rung and learning rate: seeds, how many diverged, the median / smallest / largest validation error over the seeds that did not
    rungs.csv         one row per rung: the learning rate it chose, the error over its seeds with an interval, divergences, epochs to the target - and the formula k / height beside them
    paired.csv        the chosen run of each rung against the formula and against the rung before: the paired difference of the median error with a 95% interval
    runs/rung<k>/lr<lr>_s<seed>/curve.csv   every epoch of a run: losses, validation scores, and per layer the gradient, update ratio, weight norm, saturation, dead units
    variants/rung<k>/result.json, predictions.csv   the specification's result file and the predicted metres of every validation box, for the chosen run
    models/rung<k>.opdm   the chosen network as one small file (plain numbers)
    result.json       what the Trainer reads
and the models are copied to the Distance folder of the project (job["models_dirs"][0]); not to the Annotator's Models folders.
"""
import csv
import json
import math
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
import np_net as nn  # noqa: E402

DEMO_KEYS = ("demo_sigmoid", "demo_relu_he", "demo_bn")
SIZES = ("ladder", "demos") + tuple(str(i) for i in range(9)) + DEMO_KEYS
DEFAULTS = {"seed": 0, "seeds": 1, "lrs": None, "epochs": None, "target_err": 0.075, "n_boot": 2000, "every": None}
OVERRIDES = ("batch", "depth", "width", "hidden", "activation", "init", "optimizer", "momentum", "weight_decay", "patience", "early_stopping", "loss", "target", "batch_norm", "init_scale")
RUN_COLS = ["rung", "name", "lr", "seed", "diverged", "diverged_epoch", "epochs_run", "best_epoch", "epochs_to_target", "median_rel_err", "within20", "mae_m", "signed_bias",
            "final_train_loss", "seconds", "parameters", "chosen", "curve"]
SELECTION_NOTE = ("The learning rate of each rung is the one with the lowest median error over the seeds on the validation boxes, which are also the boxes the scores come from: "
                  "the scores of the chosen learning rate are a little better than a fresh set of boxes would give. lr_sweep.csv lists every learning rate.")


def fail(job, message):
    print(message, flush=True)
    jc.write_result(job, ok=False, message=message)
    return 1


def pct(x):
    return "-" if x is None or x != x else f"{x * 100:.1f}%"


def chosen_rungs(job):
    """The rungs a job asks for, in order: from params["rungs"] or from the size."""
    p = job.get("params") or {}
    want = p.get("rungs")
    if not want:
        size = str(job.get("size") or "ladder")
        want = list(range(9)) if size in ("ladder", "all", "") else list(DEMO_KEYS) if size == "demos" else [size]
    out = []
    for r in want:
        key = str(r).replace("rung", "").strip()
        if key in DEMO_KEYS:
            out.append(key)
        elif key.isdigit() and 0 <= int(key) <= 8:
            out.append(int(key))
        else:
            raise ValueError(f"Unknown rung {r!r}: choose 0 - 8, a demo ({', '.join(DEMO_KEYS)}) or the whole ladder.")
    return out


def rung_key(r):
    return r if isinstance(r, str) else f"rung{r}"


def settings_for(rung, P):
    over = {k: P[k] for k in OVERRIDES if P.get(k) is not None}
    if "hidden" in over:
        over["hidden"] = tuple(int(x) for x in over["hidden"])
        over.pop("depth", None), over.pop("width", None)
    if isinstance(rung, str) and "hidden" not in over:
        over.setdefault("depth", 8)                                        # the demonstrations are deep on purpose
        over.setdefault("width", 32)
    return nn.rung_config(rung, **over)


def lrs_for(cfg, P):
    spec = P.get("lrs")
    if spec in (None, "", "default"):
        return [nn.default_lr(cfg)]
    if spec == "grid":
        return [float(x) for x in nn.lr_grid(cfg)]
    if isinstance(spec, (int, float)):
        return [float(spec)]
    return [float(x) for x in spec]


def json_cfg(cfg):
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()}


def write_curve(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, restval="")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.8g}" if isinstance(v, float) else v) for k, v in r.items()})


def write_predictions(path, val, pred):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["image", "class", "labelled_m", "predicted_m"])
        for name, c, d, p in zip(val.image, val.cls, val.dist, pred):
            w.writerow([name, val.names[int(c)] if val.names else int(c), f"{d:.3f}", f"{p:.4f}"])


def fmt(v):
    return "" if v is None else f"{v:.6g}" if isinstance(v, float) else v


LIVE_COLS = ("epoch", "val_median_rel_err", "train_median_rel_err", "train_loss", "val_loss")


class Live:
    """live.json in the run folder: the list of runs and the curves of the one that is training, for the Trainer window to draw while it goes.  Written whole (a temporary
    file, then renamed) at most a few times a second."""

    def __init__(self, run, plan, epochs, target_err):
        self.path = os.path.join(run, "live.json")
        self.runs = plan
        self.epochs, self.target = int(epochs), float(target_err)
        self.rows, self.n_hidden = [], 1
        self._t = 0.0

    def begin(self, i, n_hidden):
        self.rows, self.n_hidden = [], int(n_hidden)
        self.runs[i].update(status="running", epoch=0)
        self.write(force=True)

    def epoch(self, i, row, rows):
        self.runs[i].update(epoch=int(row["epoch"]), val_err=_num(row.get("val_median_rel_err")))
        self.rows = rows
        self.write()

    def end(self, i, status, epochs_run=None, val_err=None):
        self.runs[i].update(status=status, val_err=_num(val_err), epoch=int(epochs_run if epochs_run is not None else self.runs[i].get("epoch") or 0))
        self.write(force=True)

    def skip_rest(self):
        for r in self.runs:
            if r["status"] == "queued":
                r["status"] = "skipped"
        self.rows = []
        self.write(force=True)

    def write(self, force=False):
        now = time.time()
        if not force and now - self._t < 0.4:
            return
        self._t = now
        keep = [c for c in self.rows[-1]] if self.rows else []
        cols = [c for c in keep if c in LIVE_COLS or c.startswith(("grad_norm_", "saturation_", "dead_"))]
        rows = [{c: _num(r.get(c)) for c in cols} for r in self.rows]
        data = {"version": 1, "epochs": self.epochs, "target_err": self.target, "n_hidden": self.n_hidden, "runs": self.runs, "current": {"rows": rows}}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass                                                         # (the window only draws less: training goes on)


def _num(v):
    """A float for the JSON file (None for a number that is not one)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def main():
    job = jc.load_job()
    P = dict(DEFAULTS, **(job.get("params") or {}))
    seed0, n_seeds, epochs = int(P["seed"]), max(1, int(P["seeds"])), max(1, int(P["epochs"] or job.get("epochs") or 200))
    run = job["run_dir"]
    try:
        rungs = chosen_rungs(job)
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
        return fail(job, "Some boxes have numbers that are not finite (a box of no size, or a distance that is not positive): the data needs a look before a network is trained on it.")
    try:
        cfgs = {r: settings_for(r, P) for r in rungs}
        lr_lists = {r: lrs_for(cfgs[r], P) for r in rungs}
    except (ValueError, TypeError, KeyError) as e:
        return fail(job, f"These settings cannot be used: {e}")
    sd = dd.Standardiser().fit(train.X())                                        # the standardising comes from the training boxes alone
    Xtr, Xva = sd.apply(train.X()), sd.apply(val.X())
    total = sum(len(lr_lists[r]) * n_seeds for r in rungs)
    print(f"Rungs          : {', '.join(rung_key(r) for r in rungs)}   ({total} run{'s' if total != 1 else ''}: {n_seeds} seed{'s' if n_seeds != 1 else ''} x learning rates per rung, {epochs} epochs each)\n", flush=True)

    ref = dmod.make("pinhole", train.imgsz, train.nc, train.names, seed0).fit(train)
    ref_pred = ref.predict_boxes(val)
    ref_m = {"median_rel_err": eh.median_rel_err(ref_pred, val.dist), "within20": eh.within20(ref_pred, val.dist), "mae_m": eh.mae_m(ref_pred, val.dist)}
    print(f"For comparison, the formula k / height: median error {pct(ref_m['median_rel_err'])}, within 20%: {pct(ref_m['within20'])}.\n", flush=True)

    runs_root = os.path.join(run, "runs")
    records, failed = [], {}
    done = 0
    t_start = time.time()
    plan = [{"tag": f"lr{lr:g}_s{s}", "rung": rung_key(rung), "lr": float(lr), "seed": s, "status": "queued", "epoch": 0, "epochs": epochs, "val_err": None}
            for rung in rungs for lr in lr_lists[rung] for s in range(seed0, seed0 + n_seeds)]
    live = Live(run, plan, epochs, float(P["target_err"]))
    live.write(force=True)
    stop_flag = os.path.join(run, "stop_after_run")                      # the window asks for it: finish the run that is going and start no other
    halted = False
    for rung in rungs:
        cfg, key = cfgs[rung], rung_key(rung)
        print(f"[{key}] {cfg['name']}: {cfg['change']}", flush=True)
        for lr in lr_lists[rung]:
            for s in range(seed0, seed0 + n_seeds):
                if os.path.exists(stop_flag):
                    halted = True
                    break
                done += 1
                tag = f"lr{lr:g}_s{s}"
                slot = done - 1
                live.begin(slot, len(cfg["hidden"]))
                try:
                    every = int(P["every"] or max(1, epochs // 10))
                    r = nn.fit(cfg, Xtr, train.dist, Xva, val.dist, epochs=epochs, seed=s, lr=lr, log=(print if total == 1 else None), target_err=float(P["target_err"]), every=every,
                               on_epoch=lambda row, rows, i=slot: live.epoch(i, row, rows))
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    failed[f"{key} {tag}"] = f"{type(e).__name__}: {e}"
                    print(f"  ({done}/{total}) {tag}: failed: {failed[f'{key} {tag}']}", flush=True)
                    live.end(slot, "failed")
                    continue
                curve = os.path.join("runs", key, tag, "curve.csv")
                write_curve(os.path.join(run, curve), r["rows"])
                rec = {"rung": rung, "key": key, "name": cfg["name"], "lr": float(lr), "seed": s, "diverged": bool(r["diverged"]), "diverged_epoch": r["diverged_epoch"],
                       "epochs_run": r["epochs_run"], "best_epoch": r["best_epoch"], "epochs_to_target": r["epochs_to_target"], "seconds": r["seconds"], "curve": curve.replace(os.sep, "/"),
                       "parameters": r["net"].n_params(), "result": r, "median_rel_err": None, "within20": None, "mae_m": None, "signed_bias": None, "final_train_loss": None, "chosen": False}
                rec["final_train_loss"] = r["rows"][-1]["train_loss"] if r["rows"] else None
                if r["diverged"]:
                    print(f"  ({done}/{total}) {tag}: DIVERGED at epoch {r['diverged_epoch']}", flush=True)
                else:
                    pm = r["final"]["pred_m"]
                    rec.update(median_rel_err=eh.median_rel_err(pm, val.dist), within20=eh.within20(pm, val.dist), mae_m=eh.mae_m(pm, val.dist), signed_bias=eh.signed_bias(pm, val.dist), pred=pm)
                    print(f"  ({done}/{total}) {tag}: {r['epochs_run']} epochs, validation median error {pct(rec['median_rel_err'])}, within 20%: {pct(rec['within20'])}"
                          + (f", reached {P['target_err'] * 100:g}% at epoch {r['epochs_to_target']}" if r["epochs_to_target"] else "") + f"   [{r['seconds']:.1f} s]", flush=True)
                records.append(rec)
                live.end(slot, "diverged" if r["diverged"] else "done", r["epochs_run"], None if r["diverged"] else rec["median_rel_err"])
            if halted:
                break
        if halted:
            break
    if halted:
        live.skip_rest()
        print(f"\nStopped after the run that was going: {len(records)} of {total} runs finished. The model is made from those.", flush=True)
    if not records:
        return fail(job, ("Stopped before any run had finished: no model was made." if halted else "No network could be trained: " + "; ".join(f"{k}: {v}" for k, v in failed.items())))

    # ------------------------------------------------------------ the learning rate and the run of each rung
    os.makedirs(os.path.join(run, "models"), exist_ok=True)
    rung_out, sweep_rows = {}, []
    for rung in rungs:
        key = rung_key(rung)
        mine = [x for x in records if x["rung"] == rung]
        if not mine:
            continue
        per_lr = {}
        for x in mine:
            per_lr.setdefault(x["lr"], []).append(x)
        stats = {}
        for lr, xs in per_lr.items():
            errs = [x["median_rel_err"] if not x["diverged"] else math.inf for x in xs]
            ok_errs = [e for e in errs if math.isfinite(e)]
            stats[lr] = {"n": len(xs), "n_diverged": len(xs) - len(ok_errs), "median_all": float(np.median(errs)),
                         "median": float(np.median(ok_errs)) if ok_errs else None, "min": min(ok_errs) if ok_errs else None, "max": max(ok_errs) if ok_errs else None}
            sweep_rows.append([key, f"{lr:g}", len(xs), stats[lr]["n_diverged"], fmt(stats[lr]["median"]), fmt(stats[lr]["min"]), fmt(stats[lr]["max"])])
        best_lr = min(stats, key=lambda lr: (stats[lr]["median_all"], lr))
        pool = sorted([x for x in per_lr[best_lr] if not x["diverged"]], key=lambda x: x["median_rel_err"])
        if not pool:
            failed[key] = f"every run diverged (learning rates tried: {', '.join(f'{lr:g}' for lr in per_lr)})"
            print(f"[{key}] every run diverged: no model for this rung.", flush=True)
            rung_out[rung] = {"key": key, "lr": best_lr, "stats": stats, "rep": None, "n_runs": len(mine), "n_diverged": sum(x["diverged"] for x in mine)}
            continue
        rep = pool[(len(pool) - 1) // 2]
        rep["chosen"] = True
        cfg = cfgs[rung]
        model = dmod.MLPModel(train.imgsz, train.nc, train.names, rep["seed"]).adopt(rep["result"], sd, dict(cfg))
        errs_ok = [x["median_rel_err"] for x in per_lr[best_lr] if not x["diverged"]]
        across = eh.across_seeds(errs_ok, n_boot=int(P["n_boot"]))
        t_ok = [x["epochs_to_target"] for x in per_lr[best_lr] if not x["diverged"] and x["epochs_to_target"] is not None]
        extra = {"id": "3", "rung": rung, "name": cfg["name"], "change": cfg["change"], "lr": best_lr, "learning_rates_tried": [float(lr) for lr in per_lr],
                 "seeds": [x["seed"] for x in per_lr[best_lr]], "n_seeds": len(per_lr[best_lr]), "n_diverged": stats[best_lr]["n_diverged"], "across_seeds": across,
                 "epochs_to_target": {"target": float(P["target_err"]), "per_seed": [x["epochs_to_target"] for x in per_lr[best_lr] if not x["diverged"]], "median": float(np.median(t_ok)) if t_ok else None},
                 "epochs_run": rep["epochs_run"], "best_epoch": rep["best_epoch"], "parameters": rep["parameters"], "representative_seed": rep["seed"],
                 "selection": SELECTION_NOTE, "overrides": {k: P[k] for k in OVERRIDES if P.get(k) is not None}, "classes": train.names, "imgsz": train.imgsz,
                 "train_recordings": int(len(set(train.group))), "val_recordings": int(len(set(val.group)))}
        res = eh.result_json("3", key, rep["pred"], val.dist, seed=rep["seed"], split="validation", config=json_cfg(cfg), group=val.group, train_rows=len(train),
                             train_seconds=rep["seconds"], n_boot=int(P["n_boot"]), extra=extra)
        vdir = os.path.join(run, "variants", key)
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "result.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        write_predictions(os.path.join(vdir, "predictions.csv"), val, rep["pred"])
        m = res["metrics"]
        scores = {"dist_median_err": round(m["median_rel_err"], 4), "dist_within_20": round(m["within20"], 4), "dist_mae_m": round(m["mae_m"], 3)}
        path = model.save(os.path.join(run, "models", key + dmod.EXT), scores=scores,
                          extra={"trained": {"rows": len(train), "val_rows": len(val), "seconds": round(rep["seconds"], 3), "seed": rep["seed"], "classes": train.names,
                                             "ci95_median_rel_err": res["ci95"]["median_rel_err"], "trainer": job.get("trainer"), "run": os.path.basename(run), "rung": rung}})
        rung_out[rung] = {"key": key, "lr": best_lr, "stats": stats, "rep": rep, "res": res, "path": path, "across": across, "n_runs": len(mine),
                          "n_diverged": sum(x["diverged"] for x in mine), "epochs_to_target_median": extra["epochs_to_target"]["median"], "across_runs_ok": errs_ok}
        print(f"[{key}] learning rate {best_lr:g} chosen: median error {pct(m['median_rel_err'])} "
              f"(95%: {pct(res['ci95']['median_rel_err'][0])} - {pct(res['ci95']['median_rel_err'][1])}), within 20%: {pct(m['within20'])}"
              + (f"; over {len(errs_ok)} seeds {pct(across['min'])} - {pct(across['max'])}" if len(errs_ok) > 1 else "")
              + (f"; {stats[best_lr]['n_diverged']} of {stats[best_lr]['n']} runs at this rate diverged" if stats[best_lr]["n_diverged"] else ""), flush=True)
    made = {r: o for r, o in rung_out.items() if o.get("rep")}
    if not made:
        return fail(job, "No network could be made: every run diverged. " + "; ".join(f"{k}: {v}" for k, v in failed.items()))

    # ------------------------------------------------------------ the tables
    with open(os.path.join(run, "results.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(RUN_COLS)
        for x in records:
            w.writerow([x["key"], x["name"], f"{x['lr']:g}", x["seed"], x["diverged"], x["diverged_epoch"] or "", x["epochs_run"], x["best_epoch"] or "", x["epochs_to_target"] or "",
                        fmt(x["median_rel_err"]), fmt(x["within20"]), fmt(x["mae_m"]), fmt(x["signed_bias"]), fmt(x["final_train_loss"]), f"{x['seconds']:.2f}", x["parameters"],
                        "yes" if x["chosen"] else "", x["curve"]])
    with open(os.path.join(run, "lr_sweep.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rung", "lr", "seeds", "diverged", "median_rel_err", "min_rel_err", "max_rel_err"])
        w.writerows(sweep_rows)
    with open(os.path.join(run, "rungs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rung", "name", "lr", "seeds", "diverged_at_lr", "median_rel_err", "median_rel_err_lo", "median_rel_err_hi", "within20", "mae_m", "seed_min", "seed_max", "seed_median",
                    "epochs_to_target_median", "parameters", "seconds"])
        for r, o in made.items():
            res, rep = o["res"], o["rep"]
            w.writerow([o["key"], res["name"], f"{o['lr']:g}", res["n_seeds"], res["n_diverged"], fmt(res["metrics"]["median_rel_err"]), fmt(res["ci95"]["median_rel_err"][0]),
                        fmt(res["ci95"]["median_rel_err"][1]), fmt(res["metrics"]["within20"]), fmt(res["metrics"]["mae_m"]), fmt(o["across"]["min"]), fmt(o["across"]["max"]),
                        fmt(o["across"]["median"]), fmt(o["epochs_to_target_median"]), rep["parameters"], f"{sum(x['seconds'] for x in records if x['rung'] == r):.1f}"])
        w.writerow(["formula", "k / height of the box", "", "", "", fmt(ref_m["median_rel_err"]), "", "", fmt(ref_m["within20"]), fmt(ref_m["mae_m"]), "", "", "", "", ref.n_params(), ""])
    paired, prev = [], None
    for r, o in made.items():
        d = eh.paired_diff(o["rep"]["pred"], ref_pred, val.dist, group=val.group, n_boot=int(P["n_boot"]))
        paired.append(dict(d, variant=o["key"], versus="formula"))
        if prev is not None:
            d2 = eh.paired_diff(o["rep"]["pred"], prev["rep"]["pred"], val.dist, group=val.group, n_boot=int(P["n_boot"]))
            paired.append(dict(d2, variant=o["key"], versus=prev["key"]))
        prev = o
    with open(os.path.join(run, "paired.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["variant", "versus", "metric", "difference", "ci_lo", "ci_hi", "excludes_zero"])
        for d in paired:
            w.writerow([d["variant"], d["versus"], d["metric"], f"{d['diff']:.6g}", f"{d['ci95'][0]:.6g}", f"{d['ci95'][1]:.6g}", d["excludes_zero"]])
    if paired:
        print("\nDifference in median error (a negative number is better; real only when the interval leaves out zero):")
        for d in paired:
            print(f"  {d['variant']:12s} against {d['versus']:8s} {d['diff'] * 100:+.2f} points   95%: {d['ci95'][0] * 100:+.2f} to {d['ci95'][1] * 100:+.2f}   -> "
                  + ("a real difference" if d["excludes_zero"] else "not a real difference"))
    n_div = sum(x["diverged"] for x in records)
    if n_div:
        print(f"\n{n_div} of {len(records)} runs diverged (counted in lr_sweep.csv and results.csv, not left out).", flush=True)

    best = min(made, key=lambda r: made[r]["res"]["metrics"]["median_rel_err"])
    bm = made[best]["res"]["metrics"]
    info = {"dist_median_err": round(bm["median_rel_err"], 4), "dist_within_20": round(bm["within20"], 4), "dist_mae_m": round(bm["mae_m"], 3), "dist_variant": made[best]["key"]}
    print(f"\nDone in {time.time() - t_start:.0f} s. The best by median error on the validation boxes is {made[best]['key']} ({made[best]['res']['name']}): {pct(bm['median_rel_err'])}, "
          f"within 20%: {pct(bm['within20'])}   (the formula: {pct(ref_m['median_rel_err'])}).", flush=True)
    print(SELECTION_NOTE, flush=True)

    saved = []
    mdirs = job.get("models_dirs") or []
    if mdirs:
        d = os.path.join(mdirs[0], "Distance")
        os.makedirs(d, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d_%H%M", time.localtime())
        for r, o in made.items():
            dest, n = os.path.join(d, f"mlp_{o['key']}_{stamp}{dmod.EXT}"), 1
            while os.path.exists(dest):
                n += 1
                dest = os.path.join(d, f"mlp_{o['key']}_{stamp}_{n}{dmod.EXT}")
            shutil.copyfile(o["path"], dest)
            saved.append(dest)
    jc.write_result(job, ok=True, kind="nn_ladder", best=made[best]["path"], best_variant=made[best]["key"], info=info, saved=saved, finished=time.time(),
                    models=[{"variant": o["key"], "id": "3", "path": o["path"], "lr": o["lr"], "scores": {"dist_median_err": o["res"]["metrics"]["median_rel_err"],
                                                                                                       "dist_within_20": o["res"]["metrics"]["within20"],
                                                                                                       "dist_mae_m": o["res"]["metrics"]["mae_m"]}} for o in made.values()],
                    runs=len(records), diverged=n_div, failed=failed, paired=paired, selection=SELECTION_NOTE, formula=ref_m,
                    warning=("; ".join(f"{k}: {v}" for k, v in failed.items()) or None), stopped_early=(len(records) if halted else None), planned=total)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"\nTraining failed ({type(e).__name__}: {e}).", flush=True)
        code = 1
    sys.exit(code)
