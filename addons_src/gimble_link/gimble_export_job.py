"""gimble_export_job.py - turns a trained model (.pt) into the ONE file the Gimble's Raspberry Pi runs (gimble_detect.py reads it).

    python gimble_export_job.py --weights model.pt --out folder --app <the Annotator's app folder> [--label "Medium 2026-11-10"]
                                [--paths <folders with the packages>]

Writes  gimble_model.onnx  (image in; candidate boxes with class and confidence, and a distance per box, out) and  gimble_model.json
(class names, image size, what it was made from).  Three kinds of model are understood, told apart by the file itself:
    Scratch   boxes + distance.  Either a YOLO detector with a distance model added (what the Trainer makes: the two are joined here
              into the one file, the detector's boxes going straight to the distance model), or the earlier one-network Gimble model
              (exported exactly like the rig's own export_pi.py)
              In the joined file the distance model looks only at the boxes with a confidence of DIST_FROM_CONF or more, DIST_MOST at
              the most (the surest ones): the detector always hands out 300 candidates, nearly all of them nothing, and working out
              a distance for every one made a picture take about three times as long.  The others get the distance 0.0 = not worked out.
    Assist    a YOLO detector (boxes only): the same outputs, with every distance 0.0 because the model does not predict one
Runs in a Python that has torch, ultralytics, onnx and onnxruntime.  It only READS the .pt.  Lines starting with "GIMBLE " are for the
program that started it; the rest is for the log.
"""
import argparse
import json
import os
import sys


DIST_FROM_CONF = 0.1          # below every threshold the Gimble's CONF button offers (0.25 and up)
DIST_MOST = 50


def say(tag, **kw):
    print("GIMBLE " + json.dumps(dict(kw, tag=tag)), flush=True)


def load(weights, app):
    """(kind, torch module returning (dets, dist), class names, extra info for the json)"""
    import torch
    import torch.nn as nn
    ck = torch.load(weights, map_location="cpu", weights_only=False)
    if isinstance(ck, dict) and str(ck.get("format", "")).startswith("gimble-det-dist"):
        sys.path.insert(0, app)
        import gimble_model as gm
        model, ck = gm.load_checkpoint(weights)
        model.eval()

        class Scratch(nn.Module):
            def __init__(self, net):
                super().__init__()
                self.net = net

            def forward(self, img):
                net = self.net
                net.det.end2end = True
                y, preds = net.det(img)
                det = y[0]
                rois = torch.cat([torch.zeros(det.shape[0], 1, dtype=det.dtype), det[:, :4]], 1)
                logd = net.dist(preds["one2one"]["feats"], rois, (img.shape[2], img.shape[3]))
                return det[:, :6], torch.exp(logd).clamp(gm.D_MIN, gm.D_MAX)
        names = model.names
        extra = dict(round=ck.get("round"), epoch=ck.get("epoch"), map50=ck.get("map50"), map=ck.get("map"), dist_median_rel_err=ck.get("dist_med_rel"),
                     imgsz=ck.get("imgsz"))
        return "scratch", Scratch(model).eval(), names, extra

    if isinstance(ck, dict) and "opara_two_model" in ck:        # a detector with a distance model added (distance_model.py)
        del ck
        sys.path.insert(0, app)
        import distance_model as dm
        two, entry = dm.load(weights)

        class Two(nn.Module):
            def __init__(self, two, floor=DIST_FROM_CONF, most=DIST_MOST):
                super().__init__()
                self.det, self.dist, self.floor, self.most = two.det, two.dist, floor, most

            def forward(self, img):
                det = self.det(img)[:, :6]                           # the final boxes, surest first: x1 y1 x2 y2 conf class
                keep = torch.nonzero(det[:, 4] >= self.floor).squeeze(1)[:self.most]
                sel = det.index_select(0, keep)
                # one more, empty box at the end and its answer dropped again: the distance model then never gets a list of no boxes
                rois = torch.cat([torch.cat([sel[:, :1] * 0.0, sel[:, :4]], 1), det.new_zeros(1, 5)], 0)
                cls = torch.cat([sel[:, 5], det.new_zeros(1)], 0)
                d = self.dist.metres(img, rois, cls)[:-1]
                return det, torch.zeros_like(det[:, 4]).scatter(0, keep, d)
        extra = dict(round=entry.get("round"), epoch=entry.get("epoch"), map50=entry.get("map50"), map=entry.get("map"),
                     dist_median_rel_err=entry.get("dist_med_rel"), imgsz=entry.get("imgsz"),
                     more=dict(parts="detector + distance model", distance_inputs=entry.get("inputs"),
                               dist_median_rel_err_detected=entry.get("dist_med_rel_detected"),
                               distance_from_conf=DIST_FROM_CONF, distance_max_boxes=DIST_MOST),
                     every=Two(two, floor=-1.0, most=100000).eval())          # the same with a distance for every candidate: for the check
        return "scratch", Two(two).eval(), two.names, extra

    from ultralytics import YOLO
    yolo = YOLO(weights)
    net = yolo.model.float().eval()
    head = net.model[-1]
    if hasattr(head, "one2one_cv2"):                         # a model with its own final selection of boxes (YOLO26): use that branch
        head.end2end = True
    try:
        net = net.fuse()
    except Exception as e:  # noqa: BLE001  (fusing only makes it faster)
        print(f"(not fused: {e})")
    head = net.model[-1]
    with torch.no_grad():
        y = net(torch.zeros(1, 3, 64, 64))
    y = y[0] if isinstance(y, (list, tuple)) else y
    e2e = y.shape[-1] == 6
    max_det = int(getattr(head, "max_det", 300))

    class Assist(nn.Module):
        def __init__(self, net):
            super().__init__()
            self.net = net

        def forward(self, img):
            y = self.net(img)
            y = y[0] if isinstance(y, (list, tuple)) else y
            if e2e:
                det = y[0][:, :6]                                    # already the final boxes: x1 y1 x2 y2 conf class
            else:
                import torchvision
                p = y[0].transpose(0, 1)                             # (candidates, 4 + classes): centre x, y, w, h, class scores
                conf, cls = p[:, 4:].max(1)
                k = min(1000, p.shape[0])
                conf, order = conf.topk(k)
                p, cls = p[order], cls[order].to(p.dtype)
                xy, wh = p[:, :2], p[:, 2:4]
                box = torch.cat([xy - wh / 2, xy + wh / 2], 1)
                keep = torchvision.ops.nms(box + cls[:, None] * 8192.0, conf, 0.7)[:max_det]      # per class: classes are moved apart
                det = torch.cat([box[keep], conf[keep, None], cls[keep, None]], 1)
            return det, det[:, 4] * 0.0
    names = yolo.names
    names = [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    trained = (getattr(yolo, "ckpt", None) or {}).get("train_args") or {}
    return "assist", Assist(net).eval(), names, {"imgsz": trained.get("imgsz")}


def picture_size(asked, trained):
    """The picture size the Pi will use: the one asked for, else the one the model was trained at, else 640 (a multiple of 32, 160 ... 1280).
    A model looks for objects at the pixel sizes it was trained on, so it is run at its own size."""
    try:
        s = int(asked or (max(trained) if isinstance(trained, (list, tuple)) else trained) or 640)
    except (TypeError, ValueError):
        s = 640
    return max(160, min(1280, int(round(s / 32)) * 32))


def letterbox(path, S):
    """A picture file as the Gimble gives it to the model: (1, 3, S, S) float32 RGB 0-1, padded with 114.  The same steps as
    preprocess() in the Gimble's gimble_detect.py."""
    import cv2
    import numpy as np
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    r = S / max(h, w)
    nh, nw = max(1, round(h * r)), max(1, round(w * r))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
    top, left = (S - nh) // 2, (S - nw) // 2
    canvas = np.full((S, S, 3), 114, np.uint8)
    canvas[top:top + nh, left:left + nw] = img
    return np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)


def convert(wrapper, x, path):
    """Writes wrapper as an ONNX file, traced on the picture x.  Returns what the original answers for x."""
    import torch
    with torch.no_grad():
        ref = wrapper(x)
        kw = dict(input_names=["images"], output_names=["dets", "dist"], opset_version=17)
        try:
            torch.onnx.export(wrapper, x, path, dynamo=False, **kw)
        except TypeError:                                    # a torch without the 'dynamo' switch
            torch.onnx.export(wrapper, x, path, **kw)
    return ref


def compare(ref, got):
    """(same, different, largest distance difference in metres, boxes of DIST_FROM_CONF or more) between what the original answers
    (ref) and what the converted file answers (got), candidate by candidate.  Candidates whose confidence ties with another (an
    untrained model scores everything alike) may swap places and are left out."""
    import numpy as np
    r_det, r_ds = ref
    d, ds = got
    ok = bad = 0
    dmax = 0.0
    if len(d) != len(r_det):
        return 0, max(len(d), len(r_det)), 0.0, 0
    for row, dd in zip(r_det, r_ds):
        if (np.abs(r_det[:, 4] - row[4]) < 1e-4).sum() > 1 or not len(d):
            continue
        diff = np.abs(d - row[None]).max(1)
        j = int(diff.argmin())
        if diff[j] < 0.05:
            ok += 1
            dmax = max(dmax, abs(float(ds[j]) - float(dd)))
        else:
            bad += 1
    return ok, bad, dmax, int((r_det[:, 4] >= DIST_FROM_CONF).sum())


def main():
    global DIST_FROM_CONF, DIST_MOST
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--app", default="")
    ap.add_argument("--imgsz", type=int, default=0, help="picture size on the Pi; 0 = the size the model was trained at (640 when it does not say)")
    ap.add_argument("--label", default="")
    ap.add_argument("--paths", default="", help="folders to look for packages in (the program's own list), joined with the path separator")
    ap.add_argument("--check-image", default="", help="a picture the model should find something in: the converted file is checked on it as well")
    ap.add_argument("--dist-from-conf", type=float, default=DIST_FROM_CONF, help="the distance model looks at boxes of this confidence or more")
    ap.add_argument("--dist-most", type=int, default=DIST_MOST, help="... and at this many boxes at the most (the surest)")
    a = ap.parse_args()
    DIST_FROM_CONF, DIST_MOST = a.dist_from_conf, max(1, a.dist_most)
    for p in reversed([p for p in a.paths.split(os.pathsep) if p]):          # OpenPara's Python ignores PYTHONPATH: the add-on folders come this way
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import torch
        import onnxruntime as ort
    except ImportError as e:
        say("error", text=f"This Python cannot export the model: {e}. It needs torch, ultralytics, onnx and onnxruntime.")
        return 2
    if not os.path.isfile(a.weights):
        say("error", text=f"The model file is not there: {a.weights}")
        return 2
    say("step", text="Reading the model")
    try:
        kind, wrapper, names, extra = load(a.weights, a.app)
    except Exception as e:  # noqa: BLE001
        say("error", text=f"{os.path.basename(a.weights)} could not be read as a model ({type(e).__name__}: {e}).")
        return 2
    names = [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    S = picture_size(a.imgsz, extra.get("imgsz"))
    os.makedirs(a.out, exist_ok=True)
    onnx_path = os.path.join(a.out, "gimble_model.onnx")
    dummy = torch.rand(1, 3, S, S)
    pictures = [("a test pattern", dummy)]
    if a.check_image:
        try:
            x = letterbox(a.check_image, S)
        except Exception:  # noqa: BLE001  (no OpenCV here, or a file that is no picture: the check goes on without it)
            x = None
        if x is not None:
            pictures.append(("the picture open in the Annotator", torch.from_numpy(x)))
    tmp = os.path.join(a.out, "check_every_box.onnx")

    def run(path, x):
        return ort.InferenceSession(path, providers=["CPUExecutionProvider"]).run(None, {"images": x.numpy()})

    def wrong(what, bad, dmax):
        say("error", text=f"The converted model does not give the same answers as the original on {what} ({bad} boxes differ, distance off "
                          f"by up to {dmax:.2f} m), so it was not sent.")
        return 1
    every = extra.pop("every", None)
    if every is not None:
        # the distance model, on every candidate box of the test pattern (in the file that is sent it only looks at the sure ones,
        # and a test pattern has none of those)
        say("step", text="Checking the distance model's conversion")
        try:
            ref = convert(every, dummy, tmp)
            ok, bad, dmax, _n = compare([r.numpy() for r in ref], run(tmp, dummy))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        print(f"Distance model, every candidate: {ok} identical, {bad} different, max distance difference {dmax:.4f} m")
        if bad or dmax > 0.5:
            return wrong("the distance model's check", bad, dmax)
    say("step", text="Converting it to the Pi's format")
    convert(wrapper, pictures[-1][1], onnx_path)                     # traced on the real picture when there is one
    say("step", text="Checking the converted model against the original")
    ok, found, on = 0, None, pictures[0][0]
    for what, x in pictures:
        with torch.no_grad():
            ref = [r.numpy() for r in wrapper(x)]
        k, bad, dmax, n = compare(ref, run(onnx_path, x))
        print(f"ONNX vs PyTorch on {what}: {k} distinct candidates identical, {bad} different, max distance difference {dmax:.4f} m, "
              f"{n} boxes of confidence {DIST_FROM_CONF} or more")
        if bad or dmax > 0.5:
            return wrong(what, bad, dmax)
        ok += k
        if x is not dummy:
            found, on = n, what
    meta = dict(names=names, imgsz=S, round=extra.get("round") if kind == "scratch" and extra.get("round") is not None else (a.label or None),
                epoch=extra.get("epoch"), map50=extra.get("map50"), map=extra.get("map"), dist_median_rel_err=extra.get("dist_median_rel_err"),
                source=os.path.basename(a.weights), kind=kind, label=a.label, has_distance=kind == "scratch",
                note="input: RGB float 0-1, letterboxed to imgsz (pad 114); outputs dets (N,6) xyxy,conf,cls and dist (N,) metres"
                     + ("" if kind == "scratch" else "; this model does not predict distance: dist is 0.0")
                     + ("; dist 0.0 = not worked out for that box (its confidence is under distance_from_conf)" if extra.get("more") else ""))
    meta.update({k: v for k, v in (extra.get("more") or {}).items() if v is not None})
    with open(os.path.join(a.out, "gimble_model.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    say("done", onnx=onnx_path, json=os.path.join(a.out, "gimble_model.json"), kind=kind, mb=round(os.path.getsize(onnx_path) / 1e6, 1),
        names=names, checked=ok, checked_on=on, found=found, parts=(extra.get("more") or {}).get("parts"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
