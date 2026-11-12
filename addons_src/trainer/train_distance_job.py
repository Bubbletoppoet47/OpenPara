"""train_distance_job.py - trains a "Classes + boxes + distance" model for the Trainer: two models, one after the other.

Run by the Trainer as   python train_distance_job.py <run>/job.json .   No Qt here.

    Stage 1   the detector   a stock Ultralytics YOLO model (train_helper_job.train_detector), from random weights or continued.
                             Scored on the validation pictures: mAP.  With "distance_only" the detector of the model to continue from is
                             kept exactly as it is and this stage trains nothing.
    Stage 2   the distance   distance_model.DistanceNet, from random weights or continued.  It never sees the detector: it learns from
                             the LABELLED boxes that carry a LiDAR distance, and is scored on the labelled validation boxes.  So its
                             score says how good the distance model is, whatever the detector does.
                             A second, smaller one that sees only the box and the class is trained next to it as the reference: it says
                             how much looking at the picture adds.  Whichever is better on validation is kept.
    Stage 3   together       the detector's own boxes go to the distance model, on the validation pictures.  The difference from the
                             stage 2 score is what imperfect boxes cost.

The result is ONE file: the detector's .pt with the distance model added (distance_model.attach), saved with the Scratch models.  Every
program that reads a YOLO model still reads it as a detector; the Annotator and the Gimble read both parts.
If stage 2 fails after a detector was trained, the detector is saved on its own as a Classes + boxes model, so the hours are not lost.
"""
import csv
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import job_common as jc  # noqa: E402
import train_helper_job as thj  # noqa: E402

LR_NEW, LR_CONTINUE, WEIGHT_DECAY = 0.002, 0.0005, 0.0001
JITTER = 0.05                 # training boxes are moved and resized by up to this share of their size: a detector's boxes are never exact
FOUND_CONF, FOUND_IOU = 0.25, 0.5
COLS = ["epoch", "train/dist_loss", "val/median_rel_err", "val/within_20pct", "val/mae_m", "val/boxes_only_median_rel_err", "lr"]


def fail(job, message):
    print(message, flush=True)
    jc.write_result(job, ok=False, message=message)
    return 1


def pct(x):
    return "-" if x != x else f"{x * 100:.0f}%"


def boxes_of(batch, S, jitter=0.0):
    """(rois (N, 5), classes (N,), metres (N,)) of the boxes of a batch that carry a distance."""
    import torch
    d = batch["dist"]
    ok = torch.isfinite(d)
    xywh = batch["bboxes"][ok] * S
    if jitter > 0 and len(xywh):
        xywh = xywh + (torch.rand_like(xywh) * 2 - 1) * jitter * xywh[:, 2:].repeat(1, 2)
    xyxy = torch.cat([xywh[:, :2] - xywh[:, 2:] / 2, xywh[:, :2] + xywh[:, 2:] / 2], 1)
    return torch.cat([batch["batch_idx"][ok].view(-1, 1).float(), xyxy], 1), batch["cls"][ok].view(-1), d[ok]


def score_labelled(nets, loader, device, S):
    """{name: (scores, predictions, truths, classes)} of each net on the labelled boxes of a loader."""
    import torch
    out = {k: ([], [], []) for k in nets}
    for net in nets.values():
        net.eval()
    with torch.no_grad():
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            rois, cls, d = boxes_of(batch, S)
            if not len(rois):
                continue
            img = batch["img"].float() / 255
            for k, net in nets.items():
                out[k][0].extend(net.metres(img, rois, cls).tolist())
                out[k][1].extend(d.tolist())
                out[k][2].extend(cls.tolist())
    import distance_model as dm
    return {k: (dm.distance_scores(p, t), p, t, c) for k, (p, t, c) in out.items()}


def train_distance(job, src, device, prev, save_dir):
    """Stage 2.  Returns (the kept DistanceNet, info dict)."""
    import torch
    import torch.nn.functional as F
    from torch.utils.data import DataLoader
    import distance_model as dm
    import gimble_data as gd
    S, bs, epochs, patience, workers = int(job["imgsz"]), int(job["batch"]), int(job["epochs"]), int(job["patience"]), int(job.get("workers", 2))
    tr = [s for s in src.samples("train") if any(d == d for d in s["dist"])]
    va = [s for s in src.samples("val") if any(d == d for d in s["dist"])]
    n_tr, n_va = sum(d == d for s in tr for d in s["dist"]), sum(d == d for s in va for d in s["dist"])
    tl = DataLoader(gd.GimbleDataset(tr, src.nc, S, train=True), batch_size=bs, shuffle=True, num_workers=workers, collate_fn=gd.collate,
                    pin_memory=device.type == "cuda", persistent_workers=workers > 0)
    vl = DataLoader(gd.GimbleDataset(va, src.nc, S, train=False), batch_size=bs, shuffle=False, num_workers=workers, collate_fn=gd.collate) if va else None
    logs = [math.log(min(max(d, dm.D_MIN), dm.D_MAX)) for s in tr for d in s["dist"] if d == d]
    usual = math.exp(sum(logs) / len(logs))
    nets = {"picture": dm.DistanceNet(src.nc, True, start_m=usual), "boxes": dm.DistanceNet(src.nc, False, start_m=usual)}
    continued = None
    if prev is not None:
        if prev["config"].get("nc") == src.nc and list(prev.get("names") or []) == list(src.names):
            continued = "picture" if prev["config"].get("use_picture", True) else "boxes"
            nets[continued] = dm.net_of(prev)
        else:
            print("The distance model of the model to continue from was made for other classes: a new one is started.")
    for net in nets.values():
        net.to(device)
    lrs = {k: LR_CONTINUE if k == continued else LR_NEW for k in nets}
    opts = {k: torch.optim.AdamW(net.parameters(), lr=lrs[k], weight_decay=WEIGHT_DECAY) for k, net in nets.items()}
    nb = max(1, len(tl))
    warm = max(nb, 20)

    def factor(ep, it):
        cos = ((1 - math.cos(math.pi * ep / max(epochs, 1))) / 2) * (0.01 - 1) + 1
        step = ep * nb + it
        return cos * (step / warm if step < warm else 1.0)

    print(f"Distance boxes : {n_tr} training (in {len(tr)} pictures) / {n_va} validation (in {len(va)} pictures)")
    print("Start          : " + ("continuing the distance model of " + os.path.basename(job.get("start_weights") or "") if continued
                                 else "new, random weights") + f"   (usual training distance {usual:.1f} m)")
    print(f"Schedule       : up to {epochs} epochs, patience {patience}, batch {bs} pictures, picture size {S}, device {device}")
    if not va:
        print("NOTE: no validation box has a distance - the distance error cannot be scored, so the last epoch is kept.")
    print("", flush=True)

    os.makedirs(save_dir, exist_ok=True)
    resfile = os.path.join(save_dir, "results.csv")
    with open(resfile, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(COLS)
    best = {k: dict(err=float("inf"), epoch=0, state=None, scores=None, rows=None) for k in nets}
    done, t0 = 0, time.time()
    for ep in range(epochs):
        for net in nets.values():
            net.train()
        tot, cnt = 0.0, 0
        for it, batch in enumerate(tl):
            batch = {k: v.to(device, non_blocking=True) for k, v in batch.items()}
            rois, cls, d = boxes_of(batch, S, JITTER)
            if not len(rois):                                   # the zoom of this batch cut every distance box at the picture's edge
                continue
            img = batch["img"].float() / 255
            target = torch.log(d.clamp(dm.D_MIN, dm.D_MAX))
            for k, net in nets.items():
                for g in opts[k].param_groups:
                    g["lr"] = lrs[k] * factor(ep, it)
                loss = F.smooth_l1_loss(net(img, rois, cls), target, beta=0.1)
                if not torch.isfinite(loss):
                    opts[k].zero_grad(set_to_none=True)
                    continue
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 10.0)
                opts[k].step()
                opts[k].zero_grad(set_to_none=True)
                if k == "picture":
                    tot += float(loss.detach()) * len(rois)
                    cnt += len(rois)
        done = ep + 1
        tr_loss = tot / max(cnt, 1)
        if vl is not None:
            res = score_labelled(nets, vl, device, S)
            for k in nets:
                sc = res[k][0]
                if sc["median"] < best[k]["err"]:
                    best[k].update(err=sc["median"], epoch=ep + 1, scores=sc, rows=res[k][1:],
                                   state={n: v.detach().cpu().clone() for n, v in nets[k].state_dict().items()})
            sp, sb = res["picture"][0], res["boxes"][0]
            row = [ep + 1, tr_loss, sp["median"], sp["within20"], sp["mae"], sb["median"], lrs["picture"] * factor(ep, nb - 1)]
            text = (f"validation: median error {pct(sp['median'])} (within 20%: {pct(sp['within20'])}, off by {sp['mae']:.2f} m on average)"
                    f"   [box and class alone: {pct(sb['median'])}]")
        else:
            for k in nets:
                best[k].update(epoch=ep + 1, state={n: v.detach().cpu().clone() for n, v in nets[k].state_dict().items()})
            row = [ep + 1, tr_loss, "", "", "", "", lrs["picture"] * factor(ep, nb - 1)]
            text = "validation: no boxes with a distance"
        with open(resfile, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([f"{x:.6g}" if isinstance(x, float) else x for x in row])
        print(f"distance epoch {ep + 1}/{epochs}  train loss {tr_loss:.4f} | {text}  [{(time.time() - t0) / 60:.1f} min]", flush=True)
        if vl is not None and ep + 1 - max(b["epoch"] for b in best.values()) >= patience:
            print(f"No improvement for {patience} epochs - stopping early.", flush=True)
            break

    keep = "boxes" if vl is not None and best["boxes"]["err"] < best["picture"]["err"] else "picture"
    other = "picture" if keep == "boxes" else "boxes"
    net = nets[keep].cpu()
    if best[keep]["state"] is not None:
        net.load_state_dict(best[keep]["state"])
    net.eval()
    info = {"dist_inputs": keep, "dist_epoch": best[keep]["epoch"], "dist_total_epochs": done, "distance_boxes": {"train": n_tr, "val": n_va}}
    sc = best[keep]["scores"]
    print("")
    if sc:
        import numpy as np
        info.update(dist_median_err=round(sc["median"], 4), dist_within_20=round(sc["within20"], 4), dist_mae_m=round(sc["mae"], 3))
        if best[other]["scores"]:
            info["dist_other_err"] = round(best[other]["scores"]["median"], 4)
        what = {"picture": "the one that looks at the picture", "boxes": "the one that sees only the box and the class"}
        print(f"Distance model kept: {what[keep]} (best epoch {best[keep]['epoch']} of {done}).")
        print(f"  On the labelled validation boxes: median error {pct(sc['median'])}, within 20%: {pct(sc['within20'])}, "
              f"off by {sc['mae']:.2f} m on average ({sc['n']} boxes).")
        if best[other]["scores"]:
            print(f"  {what[other].capitalize()} reached {pct(best[other]['scores']['median'])}.")
        print("  By distance: " + ",  ".join(f"{label}: {pct(m)} ({n})" for label, n, m in sc["bins"] if n))
        p, t, c = (np.asarray(x, float) for x in best[keep]["rows"])
        per = [(name, int((c == i).sum()), float(np.median(np.abs(p - t)[c == i] / t[c == i])) if (c == i).any() else float("nan"))
               for i, name in enumerate(src.names)]
        print("  By class:    " + ",  ".join(f"{name}: {pct(m)} ({n})" for name, n, m in per if n), flush=True)
    else:
        print(f"Distance model kept: the last epoch ({done}); it could not be scored.", flush=True)
    return net, info


def score_together(two, src, device, S, bs, workers):
    """Stage 3: the detector's own boxes go to the distance model, on the validation pictures that have a box with a distance.
    Returns {'boxes', 'found', 'scores'}: a labelled box counts as found when a detection of its class overlaps it by FOUND_IOU or more."""
    import torch
    from torch.utils.data import DataLoader
    from torchvision.ops import box_iou
    import distance_model as dm
    import gimble_data as gd
    va = [s for s in src.samples("val") if any(d == d for d in s["dist"])]
    if not va:
        return {"boxes": 0, "found": 0, "scores": dm.distance_scores([], [])}
    vl = DataLoader(gd.GimbleDataset(va, src.nc, S, train=False), batch_size=bs, shuffle=False, num_workers=workers, collate_fn=gd.collate)
    two.to(device)
    pred, true, total = [], [], 0
    for batch in vl:
        batch = {k: v.to(device) for k, v in batch.items()}
        img = batch["img"].float() / 255
        out = two.infer(img, conf=FOUND_CONF)
        xywh = batch["bboxes"] * S
        xyxy = torch.cat([xywh[:, :2] - xywh[:, 2:] / 2, xywh[:, :2] + xywh[:, 2:] / 2], 1)
        for b in range(img.shape[0]):
            m = (batch["batch_idx"] == b) & torch.isfinite(batch["dist"])
            det, used = out[b], set()
            total += int(m.sum())
            for box, c, d in zip(xyxy[m], batch["cls"][m].view(-1), batch["dist"][m]):
                if not len(det):
                    break
                iou = box_iou(box[None], det[:, :4])[0]
                iou[det[:, 5] != c] = 0
                for j in used:
                    iou[j] = 0
                j = int(iou.argmax())
                if float(iou[j]) >= FOUND_IOU:
                    used.add(j)
                    pred.append(float(det[j, 6]))
                    true.append(float(d))
    return {"boxes": total, "found": len(true), "scores": dm.distance_scores(pred, true)}


def main():
    job = jc.load_job()
    print("Loading PyTorch and Ultralytics ...", flush=True)        # the first line at once: importing them takes a while
    import torch
    import distance_model as dm
    import gimble_data as gd
    import model_library as ml

    start = job.get("start_weights")
    only = bool(job.get("distance_only")) and bool(start)
    prev, round_no = None, 1
    if start:
        try:
            ck, prev = dm.read(start)
            if not (isinstance(ck, dict) and "model" in ck):
                raise ValueError("it is not a YOLO model file")
            det_names = dm.names_of(ck)
            del ck
        except Exception as e:  # noqa: BLE001
            return fail(job, f"Could not continue from {os.path.basename(start)}: {e}\nA model of the earlier kind (one network for boxes and "
                             "distance) can be used but not trained further: train a new Classes + boxes + distance model.")
        if prev is not None:
            round_no = int(prev.get("round") or 0) + 1

    print("Reading the training data ...", flush=True)
    src = gd.Source(job["data_yaml"], use_people=False, classes=job.get("classes") or None)
    info = src.summary()
    if info["n_train"] == 0 or info["n_val"] == 0:
        return fail(job, "The training data has no " + ("training" if info["n_train"] == 0 else "validation") + " pictures.")
    print(f"Training       : {info['n_train']} pictures   boxes: " + ", ".join(f"{n}={c}" for n, c in zip(src.names, info["train_counts"])))
    print(f"Validation     : {info['n_val']} pictures   boxes: " + ", ".join(f"{n}={c}" for n, c in zip(src.names, info["val_counts"])))
    print(f"Distance boxes : {info['train_dist_boxes']} training / {info['val_dist_boxes']} validation", flush=True)
    want = (job.get("dist_counts") or {}).get("train")
    if sum(info["train_counts"]) == 0:
        return fail(job, "The training program found no boxes at all in the run's copy of the data, so nothing can be trained. "
                         f"It looked for label files like: {info['first_label']}")
    if info["train_dist_boxes"] == 0:
        return fail(job, "None of the training boxes has a distance, so the distance model has nothing to learn from."
                    + (f" The Trainer counted {want} when it made the run's copy, so they were lost on the way: please report this." if want else ""))
    if want is not None and want != info["train_dist_boxes"]:
        print(f"NOTE: the Trainer counted {want} training boxes with a distance when it made the run's copy; the training program reads "
              f"{info['train_dist_boxes']}.", flush=True)
    if start and det_names != list(src.names):
        return fail(job, f"The model to continue from knows {det_names}, but this run trains {src.names}. They must be the same.")
    device = torch.device(job.get("device") or ("cuda" if torch.cuda.is_available() else "cpu"))
    S, bs, workers = int(job["imgsz"]), int(job["batch"]), int(job.get("workers", 2))

    print("\n=== Stage 1 of 3: the detector (classes + boxes) ===", flush=True)
    if only:
        det_pt = start
        kept = (ml.read_info(start) or {}).get("scores") or {}
        det_info = {k: kept[k] for k in ("map50", "map50_95") if kept.get(k) is not None} or None
        print(f"Kept as it is: {os.path.basename(start)}" + (f"  (mAP50 {det_info['map50']}, mAP50-95 {det_info.get('map50_95')})" if det_info and "map50" in det_info else ""))
        print("Nothing is trained in this stage.", flush=True)
    else:
        det_pt, det_info = thj.train_detector(job)
        if not os.path.exists(det_pt):
            return jc.finish(job, None)
        if device.type == "cuda":
            torch.cuda.empty_cache()                                # what the detector's training held on the GPU
        if det_info:
            print(f"\nDetector: best epoch {det_info['epoch']} of {det_info['total_epochs']}, mAP50 {det_info['map50']}, mAP50-95 {det_info['map50_95']}", flush=True)

    out = dict(det_info or {})
    try:
        print("\n=== Stage 2 of 3: the distance model, on the labelled boxes ===", flush=True)
        net, dinfo = train_distance(job, src, device, prev, os.path.join(job["run_dir"], "distance"))
        out.update(dinfo, round=round_no)

        print("\n=== Stage 3 of 3: the two models together ===", flush=True)
        ck, _ = dm.read(det_pt)
        two = dm.TwoModel(dm.Detector(ck.get("ema") or ck["model"]), net, src.names)
        del ck
        tog = score_together(two, src, device, S, bs, workers)
        if tog["boxes"]:
            out["dist_found"] = round(tog["found"] / tog["boxes"], 4)
            print(f"The detector found {tog['found']} of the {tog['boxes']} validation boxes that have a distance "
                  f"(confidence {FOUND_CONF} or more, the right class, overlapping by {FOUND_IOU} or more).")
            sc = tog["scores"]
            if sc["n"]:
                out["dist_median_err_detected"] = round(sc["median"], 4)
                print(f"Distance from the detector's own boxes: median error {pct(sc['median'])}, within 20%: {pct(sc['within20'])}, "
                      f"off by {sc['mae']:.2f} m on average" + (f"   (from the labelled boxes it was {pct(out['dist_median_err'])})" if "dist_median_err" in out else ""))
                print("  By distance: " + ",  ".join(f"{label}: {pct(m)} ({n})" for label, n, m in sc["bins"] if n), flush=True)
            else:
                print("So the distance from the detector's own boxes cannot be scored: the detector is what needs work.", flush=True)
        else:
            print("The validation pictures have no box with a distance, so there is nothing to score here.", flush=True)

        out_pt = os.path.join(job["run_dir"], "model.pt")
        dm.attach(det_pt, out_pt, net, names=list(src.names), round=round_no, epoch=out.get("epoch"), map50=out.get("map50"),
                  map=out.get("map50_95"), dist_med_rel=out.get("dist_median_err"), dist_med_rel_detected=out.get("dist_median_err_detected"),
                  imgsz=S, inputs=out["dist_inputs"], based_on=job.get("based_on"), created=time.time())
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        if only:
            return fail(job, f"\nThe distance model could not be trained ({type(e).__name__}: {e}). Nothing was saved from this run.")
        warning = (f"The distance model could not be trained ({type(e).__name__}: {e}). The detector that was trained is saved on its own, "
                   "as a Classes + boxes model: continue from it with the Classes + boxes + distance type to add the distance model.")
        print("\n" + warning, flush=True)
        return jc.finish(dict(job, models_key="assist"), det_pt, det_info, warning=warning)
    return jc.finish(job, out_pt, out)


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        print(f"\nTraining failed ({type(e).__name__}: {e}).", flush=True)
        code = 1
    sys.exit(code)
