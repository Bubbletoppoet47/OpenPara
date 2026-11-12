"""
distance_model.py - the separate distance model, and the model file that holds a detector and a distance model together.

Two models, used one after the other:

    picture -> detector (a stock Ultralytics YOLO model)  -> boxes with a class and a confidence
    each box -> distance model (DistanceNet, this file)   -> metres

The detector knows nothing about distance and the distance model finds nothing: it is told the box and the class and answers "how far".
They are trained one after the other (the Trainer's "Classes + boxes + distance" type) and scored separately, so a weak result can be
traced to one of them.

What the distance model sees of a box:
    where it is and how big   6 numbers from the box in the letterboxed picture (centre, bottom edge, log height, log width, log shape)
    what it is                the class (a person 200 pixels tall is far closer than a truck 200 pixels tall)
    what it looks like        the box cut out of the picture (with a margin of surroundings) and resized to CROP x CROP pixels
A DistanceNet made with use_picture=False sees the first two only; the Trainer trains that one too, as the reference that says how much
the picture adds.

The model file is the detector's own .pt (so everything that reads a YOLO model still reads it, as a detector) with one more entry, KEY,
that carries the distance model.  attach() writes one, load() reads one.  The older kind of distance model (one network for everything,
gimble_model.GimbleNet) is a different file and keeps working where it is read.
"""
import math
import os

import torch
import torch.nn as nn

KEY = "opara_two_model"
FORMAT = "opara-two-model-v1"
D_MIN, D_MAX = 0.2, 60.0            # metres - distances are modelled in log space inside this range
CROP = 64                           # the box is resized to CROP x CROP pixels for the distance model
MARGIN = 1.25                       # the cut-out is this much wider and taller than the box: a little of what the object stands on
BINS = (2.0, 5.0, 10.0, 20.0)       # the edges of the distance ranges the error is reported in, metres


def geometry(xyxy, H, W):
    """(N, 6) what a box says about distance by itself, from (N, 4) x1 y1 x2 y2 in pixels of an H x W picture."""
    x1, y1, x2, y2 = xyxy[:, 0], xyxy[:, 1], xyxy[:, 2], xyxy[:, 3]
    w, h = (x2 - x1).clamp(min=1.0), (y2 - y1).clamp(min=1.0)
    return torch.stack([(x1 + x2) / 2 / W, (y1 + y2) / 2 / H,           # where the box centre is
                        y2 / H,                                          # where its bottom edge (what it stands on) is
                        torch.log(h / H), torch.log(w / W),              # size (log): distance goes with 1 / size
                        torch.log(h / w)], 1)                            # shape


class DistanceNet(nn.Module):
    """The distance of boxes: forward(img, rois, cls) -> natural log of metres, one per box."""

    def __init__(self, nc, use_picture=True, crop=CROP, margin=MARGIN, start_m=6.0):
        super().__init__()
        self.nc, self.use_picture, self.crop, self.margin = int(nc), bool(use_picture), int(crop), float(margin)

        def block(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, 2, 1, bias=False), nn.GroupNorm(8, o), nn.SiLU())
        self.cnn = nn.Sequential(block(3, 24), block(24, 48), block(48, 96), block(96, 128)) if self.use_picture else None
        self.geo = nn.Sequential(nn.Linear(6, 32), nn.SiLU())
        self.cls = nn.Embedding(max(1, self.nc), 16)
        n = 32 + 16 + (128 if self.use_picture else 0)
        self.head = nn.Sequential(nn.Linear(n, 128), nn.SiLU(), nn.Dropout(0.1), nn.Linear(128, 64), nn.SiLU(), nn.Linear(64, 1))
        nn.init.zeros_(self.head[-1].weight)
        self.set_start(start_m)

    def set_start(self, metres):
        """An untrained model answers this distance for every box (the usual distance of the training boxes is a good start)."""
        self.head[-1].bias.data.fill_(math.log(min(max(float(metres), D_MIN), D_MAX)))

    def config(self):
        return dict(nc=self.nc, use_picture=self.use_picture, crop=self.crop, margin=self.margin)

    def cut(self, img, rois):
        """(N, 3, crop, crop) the boxes cut out of img (B, 3, H, W) float 0-1.  rois: (N, 5) picture number, x1, y1, x2, y2 in pixels."""
        from torchvision.ops import roi_align
        cx, cy = (rois[:, 1] + rois[:, 3]) / 2, (rois[:, 2] + rois[:, 4]) / 2
        w, h = (rois[:, 3] - rois[:, 1]).clamp(min=1.0) * self.margin / 2, (rois[:, 4] - rois[:, 2]).clamp(min=1.0) * self.margin / 2
        wide = torch.stack([rois[:, 0], cx - w, cy - h, cx + w, cy + h], 1)
        return roi_align(img.float(), wide, output_size=self.crop, spatial_scale=1.0, sampling_ratio=2, aligned=True)

    def forward(self, img, rois, cls):
        """img (B, 3, H, W) float 0-1; rois (N, 5) picture number, x1, y1, x2, y2 in pixels of img; cls (N,) class numbers."""
        rois = rois.float()
        if rois.shape[0] == 0:
            return rois.new_zeros(0)
        parts = [self.geo(geometry(rois[:, 1:], img.shape[2], img.shape[3])), self.cls(cls.long().clamp(0, max(0, self.nc - 1)))]
        if self.use_picture:
            parts.append(self.cnn((self.cut(img, rois) - 0.45) / 0.25).mean((2, 3)))
        return self.head(torch.cat(parts, 1)).squeeze(1)

    def metres(self, img, rois, cls):
        return torch.exp(self.forward(img, rois, cls)).clamp(D_MIN, D_MAX)


class Detector(nn.Module):
    """A stock Ultralytics detection model made to hand out its final boxes: (n, 6) x1 y1 x2 y2 confidence class, in pixels of the
    picture it was given.  A model with its own final selection of boxes (YOLO26) uses that; others get the usual overlap filter."""

    def __init__(self, net):
        super().__init__()
        net = net.float().eval()
        head = net.model[-1]
        if hasattr(head, "one2one_cv2"):
            head.end2end = True
        try:
            net = net.fuse()
        except Exception as e:  # noqa: BLE001  (fusing only makes it faster)
            print(f"(not fused: {e})")
        self.net = net
        with torch.no_grad():
            y = net(torch.zeros(1, 3, 64, 64))
        y = y[0] if isinstance(y, (list, tuple)) else y
        self.e2e = y.shape[-1] == 6
        self.max_det = int(getattr(net.model[-1], "max_det", 300))

    def _final(self, p):
        if self.e2e:
            return p[:, :6]                                      # already the final boxes
        import torchvision
        p = p.transpose(0, 1)                                    # (candidates, 4 + classes): centre x, y, w, h, class scores
        conf, cls = p[:, 4:].max(1)
        conf, order = conf.topk(min(1000, p.shape[0]))
        p, cls = p[order], cls[order].to(p.dtype)
        box = torch.cat([p[:, :2] - p[:, 2:4] / 2, p[:, :2] + p[:, 2:4] / 2], 1)
        keep = torchvision.ops.nms(box + cls[:, None] * 8192.0, conf, 0.7)[:self.max_det]       # per class: classes are moved apart
        return torch.cat([box[keep], conf[keep, None], cls[keep, None]], 1)

    def forward(self, img):
        """Every candidate box of the FIRST picture (what the converted model for the Gimble returns)."""
        y = self.net(img)
        y = y[0] if isinstance(y, (list, tuple)) else y
        return self._final(y[0])

    @torch.no_grad()
    def boxes(self, img, conf=0.25, max_det=300):
        """A list with the boxes of every picture of the batch that reach `conf`."""
        y = self.net(img)
        y = y[0] if isinstance(y, (list, tuple)) else y
        out = []
        for b in range(img.shape[0]):
            det = self._final(y[b])
            out.append(det[det[:, 4] >= conf][:max_det])
        return out


class TwoModel:
    """A detector and a distance model used one after the other.  infer() has the same answer shape as GimbleNet.infer."""

    def __init__(self, det, dist, names, meta=None):
        self.det, self.dist, self.names, self.meta = det, dist, list(names), dict(meta or {})
        self.det.eval()
        self.dist.eval()

    def to(self, device):
        self.det.to(device)
        self.dist.to(device)
        return self

    def eval(self):
        return self

    @torch.no_grad()
    def infer(self, img, conf=0.25, max_det=300):
        """img: (B, 3, H, W) float 0-1.  A list (per picture) of (n, 7): x1, y1, x2, y2, confidence, class, distance in metres."""
        dets = self.det.boxes(img, conf, max_det)
        rois = torch.cat([torch.cat([torch.full((len(d), 1), float(b), device=img.device), d[:, :4]], 1) for b, d in enumerate(dets)], 0)
        dm = self.dist.metres(img, rois, torch.cat([d[:, 5] for d in dets])) if len(rois) else rois.new_zeros(0)
        out, i = [], 0
        for d in dets:
            out.append(torch.cat([d[:, :6], dm[i:i + len(d), None]], 1))
            i += len(d)
        return out


# ---- the model file ---------------------------------------------------------------------------

def read(path):
    """(the checkpoint, its distance entry or None).  The checkpoint is a stock Ultralytics one (needs ultralytics to be loaded)."""
    ck = torch.load(path, map_location="cpu", weights_only=False)
    entry = ck.get(KEY) if isinstance(ck, dict) else None
    if entry is not None and not (isinstance(entry, dict) and str(entry.get("format", "")).startswith("opara-two-model")):
        raise ValueError(f"{os.path.basename(path)} carries a distance model this version does not know ({entry.get('format') if isinstance(entry, dict) else '?'})")
    return ck, entry


def net_of(entry):
    """The DistanceNet stored in a distance entry."""
    net = DistanceNet(**entry["config"])
    net.load_state_dict(entry["state_dict"])
    return net.eval()


def names_of(ck):
    model = ck.get("ema") or ck["model"]
    names = model.names
    return [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)


def attach(det_pt, out_pt, net, **meta):
    """Writes out_pt: the detector file det_pt with the distance model `net` added (det_pt itself is only read).
    The distance entry goes FIRST in the file, so the kind of a model can be told from the start of it without loading anything."""
    ck, _old = read(det_pt)
    if not isinstance(ck, dict) or "model" not in ck:
        raise ValueError(f"{os.path.basename(det_pt)} is not a YOLO model file")
    entry = dict(format=FORMAT, config=net.config(), state_dict={k: v.detach().cpu() for k, v in net.state_dict().items()}, **meta)
    out = {KEY: entry}
    out.update({k: v for k, v in ck.items() if k != KEY})
    tmp = out_pt + ".part"
    torch.save(out, tmp)
    os.replace(tmp, out_pt)
    return out_pt


def load(path):
    """(TwoModel, the distance entry) of a model file that carries both models."""
    ck, entry = read(path)
    if entry is None:
        raise ValueError(f"{os.path.basename(path)} has no distance model in it (it is a classes + boxes model)")
    names = names_of(ck)
    meta = {k: v for k, v in entry.items() if k not in ("state_dict", "config")}
    return TwoModel(Detector(ck.get("ema") or ck["model"]), net_of(entry), names, meta), entry


# ---- scores -----------------------------------------------------------------------------------

def distance_scores(pred, true):
    """{'n', 'median', 'within20', 'mae', 'bins': [(label, n, median error)]} from two equally long lists of metres."""
    import numpy as np
    p, t = np.asarray(pred, float), np.asarray(true, float)
    if not len(t):
        return dict(n=0, median=float("nan"), within20=float("nan"), mae=float("nan"), bins=[])
    rel = np.abs(p - t) / t
    edges = (0.0,) + BINS + (float("inf"),)
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (t >= lo) & (t < hi)
        label = f"{lo:g} - {hi:g} m" if hi != float("inf") else f"over {lo:g} m"
        bins.append((label, int(m.sum()), float(np.median(rel[m])) if m.any() else float("nan")))
    return dict(n=len(t), median=float(np.median(rel)), within20=float((rel <= 0.2).mean()), mae=float(np.abs(p - t).mean()), bins=bins)
