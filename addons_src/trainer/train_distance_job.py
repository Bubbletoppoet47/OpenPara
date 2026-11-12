"""train_distance_job.py - trains a classes + boxes + distance model (the Trainer's "Classes + boxes + distance" types).

Run by the Trainer as   python train_distance_job.py <run>/job.json .   No Qt here.

The model is gimble_model.GimbleNet: the YOLO26 detector with a small distance head on the same body, so one network gives the class, the
box and the distance in metres of every object.  It is what the Gimble runs and what the annotator's Scratch models are.

    data        the run's frozen copy: pictures + label files, and distances.csv with the LiDAR distance of every box that has one
    distance    learned only from boxes that carry a distance; every other box still teaches class and position
    start       a new model starts from the pretrained YOLO26 detector weights (the distance head is new) or from random weights;
                "Continue from existing model" goes on from a model of this kind, as its next round
    scores      mAP on the validation pictures, and the distance error measured on the validation boxes that have a distance
    result      <run>/train/weights/best.pt (the best epoch, EMA weights), saved as a new version with the Scratch models

The checkpoints are not stock Ultralytics .pt files (see gimble_model.save_checkpoint).
"""
import csv
import math
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import job_common as jc  # noqa: E402

WEIGHT_DECAY = 0.0005
LR_RANDOM, LR_PRETRAINED, LR_CONTINUE = 0.002, 0.001, 0.0007     # random weights take big steps; learned weights gentler ones

COLS = ["epoch", "train/box_loss", "train/cls_loss", "train/dfl_loss", "train/dist_loss",
        "val/box_loss", "val/cls_loss", "val/dfl_loss", "val/dist_loss",
        "metrics/mAP50", "metrics/mAP50-95", "dist/median_rel_err", "dist/within_20pct", "dist/mae_m", "fitness", "lr"]


# ---------------------------------------------------------------- scores

def _ap(rec, prec):
    import numpy as np
    mr = np.array([0.0] + list(rec) + [1.0])
    mp = np.array([1.0] + list(prec) + [0.0])
    for i in range(len(mp) - 2, -1, -1):
        mp[i] = max(mp[i], mp[i + 1])
    x = np.linspace(0, 1, 101)
    idx = np.searchsorted(mr, x, side="left")
    return float(np.mean([mp[i] if i < len(mp) else 0.0 for i in idx]))


def compute_map(dets, gts, nc):
    """dets: per image (n,6) [x1,y1,x2,y2,conf,cls]; gts: per image (m,5) [cls,x1,y1,x2,y2].
    Returns (map50, map50_95, per-class mAP50-95 list with None for classes absent from the labels).
    A detection counts as right when it overlaps a not yet matched label of its class by at least the threshold (0.5 ... 0.95);
    detections are taken best confidence first, each taking the label it overlaps most."""
    import numpy as np
    import torch
    from torchvision.ops import box_iou
    thr = np.linspace(0.5, 0.95, 10)
    per, per50 = [None] * nc, [None] * nc
    for c in range(nc):
        ngt = sum(int((g[:, 0] == c).sum()) for g in gts if len(g))
        if ngt == 0:
            continue
        conf, where, ious = [], [], {}                       # where: (image, row in that image's overlap table)
        for i, d in enumerate(dets):
            if not len(d):
                continue
            sel = d[d[:, 5] == c]
            if not len(sel):
                continue
            g = gts[i]
            gc = g[g[:, 0] == c][:, 1:5] if len(g) else np.zeros((0, 4), np.float32)
            ious[i] = (box_iou(torch.as_tensor(sel[:, :4]).float(), torch.as_tensor(gc).float()).numpy()
                       if len(gc) else np.zeros((len(sel), 0), np.float32))
            conf.extend(float(x) for x in sel[:, 4])
            where.extend((i, r) for r in range(len(sel)))
        if not conf:
            per[c], per50[c] = 0.0, 0.0
            continue
        order = np.argsort(-np.asarray(conf), kind="stable")
        top = np.array([ious[i][r].max() if ious[i].shape[1] else 0.0 for i, r in where])     # no label near: wrong at every threshold
        ap_t = []
        for t in thr:
            used = {i: np.zeros(m.shape[1], bool) for i, m in ious.items()}
            tp = np.zeros(len(order))
            for k, e in enumerate(order):
                if top[e] < t:
                    continue
                i, r = where[e]
                cand = np.where(used[i] | (ious[i][r] < t), -1.0, ious[i][r])
                j = int(cand.argmax())
                if cand[j] > 0:
                    used[i][j] = True
                    tp[k] = 1
            ctp, cfp = np.cumsum(tp), np.cumsum(1 - tp)
            ap_t.append(_ap(ctp / ngt, ctp / np.maximum(ctp + cfp, 1e-9)))
        per[c], per50[c] = float(np.mean(ap_t)), ap_t[0]
    v = [x for x in per if x is not None]
    v50 = [x for x in per50 if x is not None]
    return (float(sum(v50) / len(v50)) if v50 else 0.0, float(sum(v) / len(v)) if v else 0.0, per)


def evaluate(model, loader, device, nc, S):
    """mAP + distance accuracy on the validation pictures.  Distance is scored on the labelled boxes (the distance head alone)."""
    import numpy as np
    import torch
    model.eval()
    dets, gts, rel, mae = [], [], [], []
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        img = batch["img"].float() / 255
        out = model.infer(img, conf=0.001, max_det=300)
        B = img.shape[0]
        xyxy_all = torch.cat([batch["bboxes"][:, :2] - batch["bboxes"][:, 2:] / 2,
                              batch["bboxes"][:, :2] + batch["bboxes"][:, 2:] / 2], 1) * S
        boxes, ds = [], []
        for b in range(B):
            m = batch["batch_idx"] == b
            gts.append(torch.cat([batch["cls"][m].reshape(-1, 1), xyxy_all[m]], 1).cpu().numpy())
            dets.append(out[b][:, :6].cpu().numpy())
            boxes.append(xyxy_all[m])
            ds.append(batch["dist"][m].cpu())
        for p, t in zip(model.distance_for_boxes(img, boxes), ds):
            ok = torch.isfinite(t)
            if ok.any():
                rel.extend(((p[ok] - t[ok]).abs() / t[ok]).tolist())
                mae.extend((p[ok] - t[ok]).abs().tolist())
    m50, m, per = compute_map(dets, gts, nc)
    res = dict(map50=m50, map=m, per_class=per, n_dist=len(rel))
    if rel:
        a = np.array(rel)
        res.update(dist_med_rel=float(np.median(a)), dist_within20=float((a <= 0.2).mean()), dist_mae=float(np.mean(mae)))
    else:
        res.update(dist_med_rel=float("nan"), dist_within20=float("nan"), dist_mae=float("nan"))
    return res


def val_losses(model, loader, device, dist_gain):
    import torch
    model.train()          # the loss needs the training-style outputs; the batch-norm statistics stay frozen
    for m in model.modules():
        if isinstance(m, (torch.nn.BatchNorm2d, torch.nn.Dropout)):
            m.eval()
    tot = dict(box_loss=0.0, cls_loss=0.0, dfl_loss=0.0, dist_loss=0.0)
    n = 0
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            batch["img"] = batch["img"].float() / 255
            _, items = model.forward_train(batch, dist_gain=dist_gain, jitter=0.0)
            B = batch["img"].shape[0]
            for k in tot:
                tot[k] += items.get(k, 0.0) * B
            n += B
    return {k: v / max(n, 1) for k, v in tot.items()}


# ---------------------------------------------------------------- starting weights

def load_pretrained(model, weights):
    """Copies the pretrained YOLO detector weights into the model's detector: everything whose shape is the same (the body and the box
    branch; the per-class outputs only when the class count happens to match).  The distance head stays new.  Returns (copied, total)."""
    from ultralytics import YOLO
    src = YOLO(weights).model.float().state_dict()
    own = model.det.state_dict()
    take = {k: v for k, v in src.items() if k in own and own[k].shape == v.shape}
    model.det.load_state_dict(take, strict=False)
    return len(take), len(own)


def fail(job, message):
    print(message, flush=True)
    jc.write_result(job, ok=False, message=message)
    return 1


# ---------------------------------------------------------------- main

def main():
    job = jc.load_job()
    print("Loading PyTorch and Ultralytics ...", flush=True)        # the first line at once: importing them takes a while
    import torch
    from torch.utils.data import DataLoader
    import gimble_data as gd
    import gimble_model as gm

    gm.check_ultralytics()
    size = job["size"]
    imgsz, batch_size, epochs, patience = int(job["imgsz"]), int(job["batch"]), int(job["epochs"]), int(job["patience"])
    workers = int(job.get("workers", 2))
    dist_gain = float(job.get("dist_gain") or 2.0)
    start = job.get("start_weights")
    pretrained = None if (start or job.get("from_scratch")) else (job.get("pretrained") or "").format(size=size) or None

    print("Reading the training data ...", flush=True)
    src = gd.Source(job["data_yaml"], use_people=False, classes=job.get("classes") or None)
    info = src.summary()
    if info["n_train"] == 0 or info["n_val"] == 0:
        return fail(job, "The training data has no " + ("training" if info["n_train"] == 0 else "validation") + " pictures.")

    device = torch.device(job.get("device") or ("cuda" if torch.cuda.is_available() else "cpu"))
    round_no = 1
    if start:
        try:
            model, ck = gm.load_checkpoint(start)
        except Exception as e:  # noqa: BLE001
            return fail(job, f"Could not continue from {os.path.basename(start)}: {e}\n"
                             "A classes + boxes + distance model can only be continued from a model of the same kind.")
        if list(model.names) != list(src.names):
            return fail(job, f"The model to continue from knows {model.names}, but this run trains {src.names}. They must be the same.")
        round_no = int(ck.get("round", 0)) + 1
        how = f"CONTINUE (round {round_no}) from {start}"
    else:
        cfg = (job.get("cfg") or "yolo26{size}.yaml").format(size=size)
        model = gm.GimbleNet(src.names, cfg=cfg)
        how = f"NEW {cfg}, random starting weights"
        if pretrained:
            try:
                got, total = load_pretrained(model, pretrained)
            except Exception as e:  # noqa: BLE001
                return fail(job, f"Could not get the pretrained weights {pretrained}: {e}\n"
                                 "They are downloaded the first time, so this needs an internet connection once. Without one, choose the "
                                 "\"not pretrained\" type (random starting weights).")
            if got < total // 2:
                return fail(job, f"The pretrained weights {pretrained} do not fit this model ({got} of {total} parts matched). Nothing was trained.")
            how = f"NEW {cfg}, detector started from the pretrained {pretrained} ({got} of {total} parts; the distance head is new)"
    lr = float(job.get("lr") or (LR_CONTINUE if start else LR_PRETRAINED if pretrained else LR_RANDOM))

    print("=== Plan ===")
    print(f"Classes        : {src.names}")
    print(f"Training       : {info['n_train']} pictures   boxes: " + ", ".join(f"{n}={c}" for n, c in zip(src.names, info["train_counts"])))
    print(f"Validation     : {info['n_val']} pictures   boxes: " + ", ".join(f"{n}={c}" for n, c in zip(src.names, info["val_counts"])))
    print(f"Distance boxes : {info['train_dist_boxes']} training / {info['val_dist_boxes']} validation")
    print(f"Model          : {how}")
    print(f"Schedule       : {epochs} epochs, patience {patience}, lr {lr}, batch {batch_size}, picture size {imgsz}, device {device}")
    if device.type == "cpu":
        print("NOTE: no GPU found - training on the CPU is very slow.")
    if info["train_dist_boxes"] == 0:
        print("WARNING: no distances in the training data - the distance part will not learn this run.")
    if info["val_dist_boxes"] == 0:
        print("NOTE: the validation pictures have no distances - the distance error cannot be scored this run.")
    print("", flush=True)

    model.set_epochs(epochs)
    model.to(device)
    save_dir = os.path.join(job["run_dir"], "train")
    wdir = os.path.join(save_dir, "weights")
    os.makedirs(wdir, exist_ok=True)
    best_path = os.path.join(wdir, "best.pt")

    train_ds = gd.GimbleDataset(src.samples("train"), src.nc, imgsz, train=True)
    val_ds = gd.GimbleDataset(src.samples("val"), src.nc, imgsz, train=False)
    tl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=workers, collate_fn=gd.collate,
                    drop_last=len(train_ds) > batch_size, pin_memory=device.type == "cuda", persistent_workers=workers > 0)
    vl = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=workers, collate_fn=gd.collate)

    decay = [p for p in model.parameters() if p.ndim > 1]
    no_decay = [p for p in model.parameters() if p.ndim <= 1]
    opt = torch.optim.AdamW([dict(params=decay, weight_decay=WEIGHT_DECAY), dict(params=no_decay, weight_decay=0.0)], lr=lr)
    nb = len(tl)
    warm = max(nb, 50) if start else max(3 * nb, 100)

    def lr_at(ep, it):
        cos = ((1 - math.cos(math.pi * ep / max(epochs, 1))) / 2) * (0.01 - 1) + 1
        step = ep * nb + it
        return lr * cos * (step / warm if step < warm else 1.0)

    from ultralytics.utils.torch_utils import ModelEMA
    model.det.criterion = model.det.init_criterion()
    model.det.criterion.updates = 0
    ema = ModelEMA(model)
    use_amp = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    resfile = os.path.join(save_dir, "results.csv")
    with open(resfile, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(COLS)

    best_fit, best_ep, done, t0 = -1.0, 0, 0, time.time()
    for ep in range(epochs):
        model.train()
        tot = dict(box_loss=0.0, cls_loss=0.0, dfl_loss=0.0, dist_loss=0.0)
        cnt = 0
        for it, batch in enumerate(tl):
            batch = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
            batch["img"] = batch["img"].float() / 255
            for g in opt.param_groups:
                g["lr"] = lr_at(ep, it)
            with torch.autocast(device.type, enabled=use_amp):
                loss, items = model.forward_train(batch, dist_gain=dist_gain)
            if not torch.isfinite(loss):
                print("  (skipped a batch with a non-finite loss)", flush=True)
                opt.zero_grad(set_to_none=True)
                continue
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            ema.update(model)
            B = batch["img"].shape[0]
            for k in tot:
                tot[k] += items.get(k, 0.0) * B
            cnt += B
        model.det.criterion.update()
        tr = {k: v / max(cnt, 1) for k, v in tot.items()}

        vloss = val_losses(model, vl, device, dist_gain)
        ev = evaluate(ema.ema, vl, device, src.nc, imgsz)
        fit = 0.1 * ev["map50"] + 0.9 * ev["map"]
        if ev["n_dist"]:
            fit += 0.1 * (1.0 - min(ev["dist_med_rel"], 1.0))
        row = [ep + 1, tr["box_loss"], tr["cls_loss"], tr["dfl_loss"], tr["dist_loss"],
               vloss["box_loss"], vloss["cls_loss"], vloss["dfl_loss"], vloss["dist_loss"],
               ev["map50"], ev["map"], ev["dist_med_rel"], ev["dist_within20"], ev["dist_mae"], fit, opt.param_groups[0]["lr"]]
        with open(resfile, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([f"{x:.6g}" if isinstance(x, float) else x for x in row])
        tmp = os.path.join(wdir, "last.tmp")
        gm.save_checkpoint(tmp, ema.ema, round=round_no, epoch=ep + 1, fitness=fit, map50=ev["map50"], map=ev["map"],
                           dist_med_rel=ev["dist_med_rel"], imgsz=imgsz, pretrained=pretrained, based_on=job.get("based_on"))
        os.replace(tmp, os.path.join(wdir, "last.pt"))
        if fit > best_fit:
            best_fit, best_ep = fit, ep + 1
            shutil.copy2(os.path.join(wdir, "last.pt"), os.path.join(wdir, "best.tmp"))
            os.replace(os.path.join(wdir, "best.tmp"), best_path)
        done = ep + 1
        dtxt = (f"  distance: median error {ev['dist_med_rel'] * 100:.0f}% (within 20%: {ev['dist_within20'] * 100:.0f}%)"
                if ev["n_dist"] else "")
        print(f"epoch {ep + 1}/{epochs}  train box {tr['box_loss']:.3f} cls {tr['cls_loss']:.3f} dist {tr['dist_loss']:.3f} | "
              f"val mAP50 {ev['map50']:.3f} mAP50-95 {ev['map']:.3f}{dtxt}  [{(time.time() - t0) / 60:.1f} min]", flush=True)
        if ep + 1 - best_ep >= patience:
            print(f"No improvement for {patience} epochs - stopping early (best epoch {best_ep}).", flush=True)
            break

    if not os.path.exists(best_path):
        return jc.finish(job, None)
    fin = evaluate(gm.load_checkpoint(best_path)[0].to(device), vl, device, src.nc, imgsz)
    print("\nPer-class mAP50-95 on validation:")
    for name, v in zip(src.names, fin["per_class"]):
        print(f"  {name:18s} {'(no validation boxes)' if v is None else f'{v:.3f}'}")
    out = {"epoch": best_ep, "total_epochs": done, "map50": round(float(fin["map50"]), 4), "map50_95": round(float(fin["map"]), 4),
           "round": round_no, "distance_boxes": {"train": info["train_dist_boxes"], "val": info["val_dist_boxes"]}}
    if fin["n_dist"]:
        out.update(dist_median_err=round(float(fin["dist_med_rel"]), 4), dist_within_20=round(float(fin["dist_within20"]), 4),
                   dist_mae_m=round(float(fin["dist_mae"]), 3))
    return jc.finish(job, best_path, out)


if __name__ == "__main__":
    sys.exit(main())
