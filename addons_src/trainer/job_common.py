"""job_common.py - what every training script run by the Trainer shares.  No Qt here; runs in the background process.

The Trainer writes <run>/job.json and starts   python <script> <run>/job.json .   A script reads the job with load_job(), trains, then calls
finish() with the best weights: that saves them as a new model version (in the project's models and in the annotator's Models folder, so
the annotator lists it) and writes <run>/result.json.  A run that was stopped or crashed has no result.json.
"""
import csv
import json
import os
import sys
import time


def load_job(argv=None):
    argv = argv if argv is not None else sys.argv
    with open(argv[1], encoding="utf-8") as f:
        job = json.load(f)
    lib = job.get("lib_dir")
    if lib and lib not in sys.path:
        sys.path.insert(0, lib)                      # the annotator's app folder: model_library and friends
    os.makedirs(job["run_dir"], exist_ok=True)
    return job


def write_result(job, **fields):
    path = os.path.join(job["run_dir"], "result.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(fields, f, indent=2)
    os.replace(tmp, path)


def read_results(save_dir):
    try:
        with open(os.path.join(save_dir, "results.csv"), newline="", encoding="utf-8") as f:
            return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    except OSError:
        return []


def best_info(save_dir):
    """{'epoch', 'total_epochs', 'map50', 'map50_95'} of the best epoch of an Ultralytics run, or None."""
    rows = read_results(save_dir)
    if not rows:
        return None
    try:
        best = max(rows, key=lambda r: float(r["metrics/mAP50-95(B)"]))
        return {"epoch": int(float(best["epoch"])), "total_epochs": len(rows), "map50": round(float(best["metrics/mAP50(B)"]), 4),
                "map50_95": round(float(best["metrics/mAP50-95(B)"]), 4)}
    except (KeyError, ValueError):
        return None


def publish(job, best_pt, scores=None):
    """Saves best_pt as a new version in every models folder of the job.  Returns the list of saved paths."""
    import model_library as ml
    key = job.get("models_key", "assist")
    saved = []
    for d in job.get("models_dirs", []):
        try:
            os.makedirs(ml.folder_path(d, key), exist_ok=True)
            p = ml.save_version(d, key, best_pt, job["size"], job.get("trainer") or "trainer", classes=job.get("classes"),
                                scores=scores, based_on=job.get("based_on"), ts=time.time())
            if p:
                saved.append(p)
        except OSError as e:
            print(f"Could not save the model to {d}: {e}", flush=True)
    return saved


def finish(job, best_pt, info=None):
    """The end of a clean run."""
    if not best_pt or not os.path.exists(best_pt):
        print("Training ended without a usable best.pt.", flush=True)
        write_result(job, ok=False, message="Training ended without a usable model.")
        return 1
    scores = {k: info[k] for k in ("map50", "map50_95") if info and k in info} or None
    saved = publish(job, best_pt, scores)
    write_result(job, ok=True, best=best_pt, info=info, saved=saved, finished=time.time())
    if info:
        print(f"\nDone. Best epoch {info['epoch']} of {info['total_epochs']}: mAP50 {info['map50']}, mAP50-95 {info['map50_95']}", flush=True)
    for p in saved:
        print(f"Saved as a new model version: {p}", flush=True)
    return 0
