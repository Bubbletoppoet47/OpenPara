"""train_helper_job.py - trains a Helper model (stock Ultralytics YOLO, pretrained start, boxes + classes) for the Trainer.
Ported from the old train_helper.py: the data is already a frozen snapshot, so this only trains and hands the result to job_common.finish()."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import job_common as jc  # noqa: E402


def main():
    job = jc.load_job()
    from ultralytics import YOLO
    size = job["size"]
    start = job.get("start_weights")
    continuing = bool(start)
    scratch = bool(job.get("from_scratch")) and not continuing
    base = job.get("pretrained", "yolo26{size}.pt").format(size=size)
    print(f"Classes        : {job.get('classes')}")
    print(f"Start from     : {start or base}" + (f"  (continuing {os.path.basename(start)})" if continuing else
                                                  "  (random weights, nothing pretrained)" if scratch else "  (pretrained)"))
    print(f"Schedule       : {job['epochs']} epochs, patience {job['patience']}, batch {job['batch']}, imgsz {job['imgsz']}", flush=True)
    try:
        model = YOLO(start or base)
    except Exception as e:  # noqa: BLE001
        if continuing:
            raise
        fb = job.get("fallback", "yolo11{size}.pt").format(size=size)
        print(f"Could not load {base} ({type(e).__name__}: {e}); trying {fb} ...", flush=True)
        model = YOLO(fb)
    kw = dict(data=job["data_yaml"], epochs=job["epochs"], patience=job["patience"], imgsz=job["imgsz"], batch=job["batch"],
              workers=job.get("workers", 2), project=job["run_dir"], name="train", exist_ok=True, plots=False)
    if job.get("device") not in (None, ""):
        kw["device"] = job["device"]
    if continuing:
        kw.update(optimizer="AdamW", lr0=job.get("lr", 0.0005), warmup_epochs=1)       # gentle steps when continuing
    model.train(**kw)
    save_dir = str(getattr(getattr(model, "trainer", None), "save_dir", "") or os.path.join(job["run_dir"], "train"))
    return jc.finish(job, os.path.join(save_dir, "weights", "best.pt"), jc.best_info(save_dir))


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        print(f"\nTraining failed ({type(e).__name__}: {e}).", flush=True)
        code = 1
    sys.exit(code)
