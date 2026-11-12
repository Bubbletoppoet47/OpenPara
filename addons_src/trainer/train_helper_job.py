"""train_helper_job.py - trains a "Classes + boxes" model for the Trainer: a stock Ultralytics YOLO detector, from random weights.

Nothing pretrained is used as a start: a new model is built from its description (yolo26<size>.yaml) with random weights, and "Continue
from existing model" goes on from a model you trained.  The data is already a frozen snapshot, so this only trains and hands the result
to job_common.finish().  train_detector() is also stage 1 of a "Classes + boxes + distance" run (train_distance_job.py)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import job_common as jc  # noqa: E402


def train_detector(job):
    """Trains the detector of a job.  Returns (the path of its best.pt, {'epoch', 'total_epochs', 'map50', 'map50_95'} or None)."""
    from ultralytics import YOLO
    size = job["size"]
    start = job.get("start_weights")
    base = job.get("cfg", "yolo26{size}.yaml").format(size=size)
    print(f"Classes        : {job.get('classes')}")
    print(f"Start from     : {start or base}" + (f"  (continuing {os.path.basename(start)})" if start else "  (random weights, nothing pretrained)"))
    print(f"Schedule       : {job['epochs']} epochs, patience {job['patience']}, batch {job['batch']}, imgsz {job['imgsz']}", flush=True)
    try:
        model = YOLO(start or base)
    except Exception as e:  # noqa: BLE001
        if start:
            raise
        fb = job.get("fallback", "yolo11{size}.yaml").format(size=size)
        print(f"Could not build {base} ({type(e).__name__}: {e}); trying {fb} ...", flush=True)
        model = YOLO(fb)
    kw = dict(data=job["data_yaml"], epochs=job["epochs"], patience=job["patience"], imgsz=job["imgsz"], batch=job["batch"],
              workers=job.get("workers", 2), project=job["run_dir"], name="train", exist_ok=True, plots=False)
    if job.get("device") not in (None, ""):
        kw["device"] = job["device"]
    if start:
        kw.update(optimizer="AdamW", lr0=job.get("lr") or 0.0005, warmup_epochs=1)       # gentle steps when continuing
    else:
        kw.update(pretrained=False)                                                      # random weights: nothing is loaded into the new model
    model.train(**kw)
    save_dir = str(getattr(getattr(model, "trainer", None), "save_dir", "") or os.path.join(job["run_dir"], "train"))
    return os.path.join(save_dir, "weights", "best.pt"), jc.best_info(save_dir)


def main():
    job = jc.load_job()
    print("Loading PyTorch and Ultralytics ...", flush=True)        # the first line at once: importing them takes a while
    best, info = train_detector(job)
    return jc.finish(job, best, info)


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        print(f"\nTraining failed ({type(e).__name__}: {e}).", flush=True)
        code = 1
    sys.exit(code)
