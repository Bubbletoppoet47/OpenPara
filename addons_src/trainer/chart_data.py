"""chart_data.py - what the Trainer's Charts pane draws, as plain numbers.  No Qt; numpy and the standard library.

A run of the distance network (train_nn_job.py) leaves tables in its run folder: results.csv (a row per training run: rung, learning rate, seed, did it diverge, which one is the chosen
one), lr_sweep.csv (a row per rung and learning rate), rungs.csv (a row per rung with the error and its interval, and the formula beside them), and for every run its curve.csv (a row per
epoch: losses, validation error, and per layer the gradient, the update ratio, the weight norm, the saturated and the dead units).  RunData reads them; figure() turns them into the
description of one chart (a "spec", below), which trainer_charts.PlotWidget draws.  Six figures:

    learning     the learning curve of the chosen run of each rung (the other seeds at the same learning rate thin beside it)
    sweep        the validation error of one rung over its learning rates, with the range over the seeds; where runs diverged, and where the rate was chosen
    layers       per layer: the gradient, the update / weight ratio, the weight norm, the saturated and the dead units, at the start and at the end of training
    final        the error of each rung with its 95 % interval over the boxes, the formula beside them
    epochs       how many epochs each rung needed to get under the target error
    momentum     the toy: heavy-ball momentum on a quadratic - the steps to settle measured, and what the two roots of its equation predict

A spec is {"title", "xlabel", "ylabel", "xlog", "ylog", "xcat": [labels] or None, "y0": include 0 on the axis, "series": [...], "hlines": [(y, label)], "vlines": [(x, label)], "spans":
[(x0, x1, label)], "note", "empty": a sentence when there is nothing to draw}.  A series is {"name", "slot", "line", "markers", "width", "thin", "dash", "legend", "points": [(x, y, tip)],
"whisk": [(x, lo, hi)], "band": [(x, lo, hi)]}; slot is the colour of the series (0-7, fixed by the rung or the run it belongs to) or None when there are more than eight.
"""
import csv
import json
import math
import os

import numpy as np

import np_net as nn

MAX_SERIES = 8
LAYER_METRICS = {"grad_norm": ("Gradient norm", True, 1.0), "update_ratio": ("Update / weight ratio", True, 1.0), "weight_norm": ("Weight norm", True, 1.0),
                 "saturation": ("Saturated units (%)", False, 100.0), "dead": ("Dead units (%)", False, 100.0)}
CURVE_METRICS = {"val_err": ("Validation error (median, %)", "val_median_rel_err", False, 100.0), "train_loss": ("Training loss", "train_loss", True, 1.0),
                 "val_loss": ("Validation loss", "val_loss", True, 1.0)}


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


def finite(v):
    return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def read_table(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def is_run(path):
    """True for a folder that holds what the charts read (a distance-network run)."""
    return os.path.isfile(os.path.join(path, "results.csv")) and os.path.isfile(os.path.join(path, "rungs.csv")) and os.path.isfile(os.path.join(path, "lr_sweep.csv"))


class RunData:
    def __init__(self, run_dir):
        self.dir = run_dir
        self.runs = read_table(os.path.join(run_dir, "results.csv"))
        self.sweep = read_table(os.path.join(run_dir, "lr_sweep.csv"))
        self.rungs = [r for r in read_table(os.path.join(run_dir, "rungs.csv")) if r.get("rung") != "formula"]
        self.formula = next((r for r in read_table(os.path.join(run_dir, "rungs.csv")) if r.get("rung") == "formula"), None)
        try:
            with open(os.path.join(run_dir, "result.json"), encoding="utf-8") as f:
                self.result = json.load(f)
        except (OSError, ValueError):
            self.result = {}
        self.keys, self.names = [], {}
        for r in self.runs:
            if r["rung"] not in self.names:
                self.keys.append(r["rung"])
                self.names[r["rung"]] = r.get("name", "")
        self._curves = {}

    @property
    def ok(self):
        return bool(self.runs) and bool(self.keys)

    def label(self, key):
        return f"{key}  {self.names.get(key, '')}".strip()

    def slot(self, key):
        i = self.keys.index(key) if key in self.keys else 99
        return i if i < MAX_SERIES else None

    def chosen(self, key):
        for r in self.runs:
            if r["rung"] == key and r.get("chosen") == "yes":
                return r
        return None

    def runs_at(self, key, lr):
        return [r for r in self.runs if r["rung"] == key and num(r["lr"]) == num(lr)]

    def curve(self, rel):
        """{column: array} of a curve.csv (relative to the run folder); {} when it is not there."""
        if rel in self._curves:
            return self._curves[rel]
        rows = read_table(os.path.join(self.dir, rel))
        out = {}
        if rows:
            for k in rows[0]:
                out[k] = np.array([num(r.get(k)) for r in rows], float)
        self._curves[rel] = out
        return out

    def diverged_at(self, key, lr):
        return sum(1 for r in self.runs_at(key, lr) if r["diverged"] == "True")

    def groups(self):
        """The choices of the 'rungs' box: [(label, [keys])]."""
        ladder = [k for k in self.keys if not k.startswith("demo")]
        demos = [k for k in self.keys if k.startswith("demo")]
        out = [("All", list(self.keys))]
        if ladder and demos:
            out += [("Ladder rungs only", ladder), ("Deep demonstrations only", demos)]
        out += [(self.label(k), [k]) for k in self.keys]
        return out


def _spec(title, xlabel, ylabel, **kw):
    s = {"title": title, "xlabel": xlabel, "ylabel": ylabel, "xlog": False, "ylog": False, "xcat": None, "y0": False, "xint": False, "series": [], "hlines": [], "vlines": [], "spans": [], "note": "", "empty": None}
    s.update(kw)
    return s


def _series(name, slot, **kw):
    s = {"name": name, "slot": slot, "line": True, "markers": False, "width": 2.0, "thin": False, "dash": False, "legend": True, "points": [], "whisk": [], "band": []}
    s.update(kw)
    return s


def _cap(keys):
    """The rungs that get a colour (eight at most) and a sentence about the ones left out."""
    left = len(keys) - MAX_SERIES
    return keys[:MAX_SERIES], (f" {left} more {'are' if left != 1 else 'is'} left out: pick fewer rungs." if left > 0 else "")


# ------------------------------------------------------------------------------------------------------------------ 1 learning curves
def fig_learning(data, metric="val_err", keys=None):
    title, col, ylog, scale = CURVE_METRICS[metric]
    spec = _spec(title + " by epoch", "epoch", title, ylog=ylog, y0=not ylog, xint=True)
    keys, more = _cap(list(keys or data.keys))
    skipped = 0
    for k in keys:
        rec = data.chosen(k)
        if rec is None:
            continue
        mine = data.runs_at(k, rec["lr"])
        for r in mine:
            if r is rec:
                continue
            if r["diverged"] == "True":
                skipped += 1
                continue
            c = data.curve(r["curve"])
            if col in c:
                pts = [(float(e), float(v) * scale, "") for e, v in zip(c["epoch"], c[col]) if finite(v) and (not ylog or v > 0)]
                spec["series"].append(_series(data.label(k), data.slot(k), thin=True, legend=False, points=pts, width=1.0))
        c = data.curve(rec["curve"])
        if col in c:
            pts = [(float(e), float(v) * scale, f"{data.label(k)}, learning rate {num(rec['lr']):g}, seed {rec['seed']}\nepoch {int(e)}: {v * scale:.4g}") for e, v in zip(c["epoch"], c[col])
                   if finite(v) and (not ylog or v > 0)]
            spec["series"].append(_series(data.label(k), data.slot(k), points=pts))
    if not any(s["points"] for s in spec["series"]):
        spec["empty"] = "No learning curve to draw: every run of the chosen rungs diverged, or the curves are not in the run folder."
    spec["note"] = ("The thick line is the run that was chosen for each rung (its learning rate, the lower-median seed); the thin lines are the other seeds at that rate."
                    + (f" {skipped} diverged run{'s' if skipped != 1 else ''} at the chosen rates {'are' if skipped != 1 else 'is'} not drawn." if skipped else "") + more)
    return spec


# ------------------------------------------------------------------------------------------------------------------ 2 learning-rate sweep
def fig_sweep(data, key=None):
    key = key or (data.keys[0] if data.keys else "")
    spec = _spec(f"Learning rates of {data.label(key)}", "learning rate", "Validation error (median, %)", xlog=True, y0=True)
    rows = sorted((r for r in data.sweep if r["rung"] == key), key=lambda r: num(r["lr"]))
    if not rows:
        spec["empty"] = "No learning-rate sweep for this rung."
        return spec
    slot = data.slot(key)
    pts, band, bad = [], [], []
    for r in rows:
        lr, med, lo, hi = num(r["lr"]), num(r["median_rel_err"]), num(r["min_rel_err"]), num(r["max_rel_err"])
        n, nd = int(num(r["seeds"])), int(num(r["diverged"]))
        if finite(med):
            pts.append((lr, med * 100, f"learning rate {lr:g}\nmedian error {med * 100:.2f} % over {n - nd} seed{'s' if n - nd != 1 else ''}" + (f"\nrange {lo * 100:.2f} - {hi * 100:.2f} %" if finite(lo) else "")
                                         + (f"\n{nd} of {n} runs diverged" if nd else "")))
            if finite(lo) and finite(hi):
                band.append((lr, lo * 100, hi * 100))
        if nd:
            bad.append((lr, nd, n))
    spec["series"].append(_series("median over the seeds", slot if slot is not None else 0, markers=True, points=pts, band=band))
    ymax = max([p[1] for p in pts] + [b[2] for b in band] + [1.0]) if pts else 1.0
    top = ymax * 1.08
    if bad:
        spec["series"].append(_series("runs that diverged", 7, line=False, markers=True, points=[(lr, top, f"learning rate {lr:g}\n{nd} of {n} runs diverged") for lr, nd, n in bad]))
    good = [num(r["lr"]) for r in rows if int(num(r["diverged"])) == 0]
    if good:
        spec["spans"].append((min(good), max(good), "no run diverged"))
    ch = data.chosen(key)
    if ch is not None:
        spec["vlines"].append((num(ch["lr"]), f"chosen {num(ch['lr']):g}"))
    spec["note"] = ("The line is the median over the seeds and the band the smallest to the largest; a red plus at the top is a learning rate where runs diverged (counted, not left out). "
                    "The learning rate was chosen on these same validation boxes, so the chosen point is a little better than fresh boxes would give.")
    return spec


# ------------------------------------------------------------------------------------------------------------------ 3 layer by layer
def _at(c, col, when, k=3):
    v = c.get(col)
    if v is None:
        return None
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    return float(np.mean(v[:k] if when == "start" else v[-k:]))


def fig_layers(data, metric="grad_norm", when="start", keys=None):
    title, ylog, scale = LAYER_METRICS[metric]
    spec = _spec(f"{title}, layer by layer, {'at the start' if when == 'start' else 'at the end'} of training", "layer (1 = next to the input)", title, ylog=ylog, y0=not ylog, xint=True)
    keys, more = _cap(list(keys or data.keys))
    for k in keys:
        rec = data.chosen(k)
        if rec is None:
            continue
        c = data.curve(rec["curve"])
        pts, l = [], 1
        while f"{metric}_{l}" in c:
            v = _at(c, f"{metric}_{l}", when)
            if v is not None and (not ylog or v > 0):
                pts.append((float(l), v * scale, f"{data.label(k)}\nlayer {l}: {v * scale:.4g}"))
            l += 1
        if pts:
            spec["series"].append(_series(data.label(k), data.slot(k), markers=True, points=pts))
    if not spec["series"]:
        spec["empty"] = "No layer numbers for these rungs."
    spec["note"] = ("The mean of the first three epochs (start) or the last three (end) of the chosen run of each rung. "
                    + ("In a deep sigmoid network the gradient shrinks towards the first layers; ReLU with He initialisation and batch normalisation keep it level. " if metric == "grad_norm" else "")
                    + ("Saturated and dead units are counted in the hidden layers only." if metric in ("saturation", "dead") else "") + more)
    return spec


# ------------------------------------------------------------------------------------------------------------------ 4 final error, 5 epochs to the target
def _rung_rows(data, keys=None):
    want = set(keys or data.keys)
    return [r for r in data.rungs if r["rung"] in want]


def fig_final(data, keys=None):
    rows = _rung_rows(data, keys)
    spec = _spec("Error of each rung", "rung", "Validation error (median, %), with its 95 % interval", y0=True, xcat=[r["rung"] for r in rows])
    pts, whisk = [], []
    for i, r in enumerate(rows):
        m, lo, hi = num(r["median_rel_err"]), num(r["median_rel_err_lo"]), num(r["median_rel_err_hi"])
        if not finite(m):
            continue
        lo_s, hi_s = num(r.get("seed_min")), num(r.get("seed_max"))
        pts.append((float(i), m * 100, f"{data.label(r['rung'])}\nmedian error {m * 100:.2f} % (95 %: {lo * 100:.2f} - {hi * 100:.2f})\n{r['seeds']} seed{'s' if r['seeds'] != '1' else ''}"
                    + (f", {lo_s * 100:.2f} - {hi_s * 100:.2f} % over them" if finite(lo_s) and finite(hi_s) and r["seeds"] != "1" else "") + f"\nlearning rate {num(r['lr']):g}"))
        if finite(lo) and finite(hi):
            whisk.append((float(i), lo * 100, hi * 100))
    spec["series"].append(_series("median error", 0, line=False, markers=True, points=pts, whisk=whisk))
    if data.formula is not None and finite(num(data.formula.get("median_rel_err"))):
        spec["hlines"].append((num(data.formula["median_rel_err"]) * 100, f"formula k / height: {num(data.formula['median_rel_err']) * 100:.2f} %"))
    if not pts:
        spec["empty"] = "No rung has a score (every run diverged)."
    spec["note"] = "The whisker is the 95 % interval over the validation boxes (resampled by recording); a network whose whisker does not reach the dashed line is better than the formula by more than the boxes can explain."
    return spec


def fig_epochs(data, keys=None):
    rows = _rung_rows(data, keys)
    spec = _spec("Epochs to reach the target error", "rung", "epochs (median over the seeds that got there)", y0=True, xcat=[r["rung"] for r in rows])
    got, never = [], []
    top = 1.0
    for i, r in enumerate(rows):
        e = num(r.get("epochs_to_target_median"))
        runs = [x for x in data.runs if x["rung"] == r["rung"]]
        top = max([top] + [num(x["epochs_run"]) for x in runs if finite(num(x["epochs_run"]))])
        if finite(e):
            got.append((float(i), e, f"{data.label(r['rung'])}\nreached the target after {e:g} epochs (median)"))
        else:
            never.append(i)
    spec["series"].append(_series("reached the target", 0, line=False, markers=True, points=got))
    if never:
        spec["series"].append(_series("never reached it", 7, line=False, markers=True, points=[(float(i), top, f"{data.label(rows[i]['rung'])}\nno run got under the target") for i in never]))
    if not got and not never:
        spec["empty"] = "Nothing to show."
    spec["note"] = "The target error is the one the run was asked for (target_err). A marker at the top is a rung where no run got there in the epochs it had."
    return spec


# ------------------------------------------------------------------------------------------------------------------ 6 the toy: momentum on a quadratic
TOY_ETA_LAM = (0.05, 0.4)
SETTLE = 1e-4


def settle_steps(eta, mu, lam=1.0, tol=SETTLE, steps=4000):
    """The first step from which the loss of the heavy-ball iteration stays under tol x its start; None when it does not within `steps` (or diverges)."""
    loss = nn.heavy_ball(eta, lam, mu, steps=steps)
    if not np.all(np.isfinite(loss)):
        return None
    above = np.where(loss > tol * loss[0])[0]
    if not len(above):
        return 0
    last = int(above[-1])
    return None if last >= steps else last + 1


def predicted_steps(eta, mu, lam=1.0, tol=SETTLE):
    """The steps until the envelope of the loss, rho^(2 t), is under tol, rho the larger root of z^2 - (1 + mu - eta lam) z + mu = 0 (the loss goes as x squared): ln(tol) / (2 ln rho)."""
    reg = nn.damping_regime(eta, lam, mu)
    if not reg["stable"]:
        return None
    rho = max(abs(r) for r in reg["roots"])
    if rho <= 0 or rho >= 1:
        return None
    return math.log(tol) / (2.0 * math.log(rho))


def critical_mu(eta, lam=1.0):
    """The momentum at which the two roots meet: (1 - sqrt(eta lam))^2 (the fastest settling)."""
    return (1.0 - math.sqrt(eta * lam)) ** 2


def fig_momentum(etas=TOY_ETA_LAM):
    spec = _spec("Momentum on a quadratic (a toy)", "momentum", f"steps until the loss is {SETTLE:g} of its start", ylog=True)
    mus = [round(0.02 * i, 2) for i in range(0, 50)]
    for i, eta in enumerate(etas):
        pred, meas = [], []
        for mu in mus:
            p, m = predicted_steps(eta, mu), settle_steps(eta, mu)
            reg = nn.damping_regime(eta, 1.0, mu)["regime"]
            if p is not None and p > 0:
                pred.append((mu, p, f"learning rate x curvature {eta:g}, momentum {mu:g}\n{reg}: the roots predict {p:.0f} steps"))
            if m is not None and m > 0:
                meas.append((mu, float(m), f"learning rate x curvature {eta:g}, momentum {mu:g}\n{reg}: measured {m} steps"))
        spec["series"].append(_series(f"\u03b7\u03bb = {eta:g}, predicted by the roots", i, points=pred))
        spec["series"].append(_series(f"\u03b7\u03bb = {eta:g}, measured", i, line=False, markers=True, points=meas))
        spec["vlines"].append((critical_mu(eta), f"\u03b7\u03bb {eta:g}: critical {critical_mu(eta):.2f}"))
    spec["note"] = ("Heavy-ball momentum on the loss lambda x^2 / 2 (\u03b7 the learning rate, \u03bb the curvature). Left of a dashed line (the critical momentum of that \u03b7\u03bb) the two roots are real "
                    "and the loss creeps (overdamped); right of it they are complex and the loss oscillates (underdamped); the settling is fastest at the line. Line: from the roots; markers: counted "
                    "by running the iteration.")
    return spec


# ------------------------------------------------------------------------------------------------------------------ the list
FIGURES = [("learning", "Learning curves"), ("sweep", "Learning rates"), ("layers", "Layer by layer"), ("final", "Error by rung"), ("epochs", "Epochs to the target"),
           ("momentum", "Momentum (a toy)")]


def figure(name, data, **opts):
    """The spec of figure `name` for a RunData (None for the toy).  Options: metric, when, keys (a list of rung keys), key (one rung)."""
    if name == "momentum":
        return fig_momentum()
    if data is None or not data.ok:
        return _spec(dict(FIGURES).get(name, name), "", "", empty="No run to draw: finish a distance-network run, or pick one.")
    if name == "learning":
        return fig_learning(data, opts.get("metric") or "val_err", opts.get("keys"))
    if name == "sweep":
        return fig_sweep(data, opts.get("key"))
    if name == "layers":
        return fig_layers(data, opts.get("metric") or "grad_norm", opts.get("when") or "start", opts.get("keys"))
    if name == "final":
        return fig_final(data, opts.get("keys"))
    if name == "epochs":
        return fig_epochs(data, opts.get("keys"))
    raise KeyError(name)


def table_rows(spec):
    """The numbers the chart draws, as (header, rows) for the table view: one row per point of every series that has a legend entry."""
    head = ["series", "x", "y"] + (["low", "high"] if any(s["whisk"] or s["band"] for s in spec["series"]) else [])
    rows = []
    for s in spec["series"]:
        if not s["legend"]:
            continue
        extra = {round(x, 9): (lo, hi) for x, lo, hi in (s["whisk"] or s["band"])}
        for x, y, _tip in s["points"]:
            label = spec["xcat"][int(x)] if spec["xcat"] else x
            row = [s["name"], label, y]
            if len(head) > 3:
                lo, hi = extra.get(round(x, 9), ("", ""))
                row += [lo, hi]
            rows.append(row)
    return head, rows


# ------------------------------------------------------------------------------------------------------------------ the run in progress (the Train page's live charts)
# train_nn_job.py writes live.json into the run folder while it trains; its "rows" are the epochs of the run that is training now (the columns of curve.csv).
def _live_pts(rows, col, scale, label, ylog=False):
    return [(float(r["epoch"]), float(r[col]) * scale, f"{label}, epoch {int(r['epoch'])}: {float(r[col]) * scale:.4g}") for r in rows
            if col in r and finite(r[col]) and (not ylog or float(r[col]) > 0)]


def _live_span(spec, rows, epochs):
    """The epochs still to come, shaded; it also makes the axis run to the last epoch."""
    last = int(rows[-1]["epoch"]) if rows else 0
    if epochs and epochs > last:
        spec["spans"].append((float(last), float(epochs), ""))


def live_error(rows, epochs, target_err=0.075):
    """Median relative error of the run that is training: validation and training, the target as a dashed line."""
    spec = _spec("Median relative error", "epoch", "error (%)", y0=True, xint=True)
    if not rows:
        spec["empty"] = "Waiting for the first epoch ..."
        return spec
    spec["series"].append(_series("Validation", 1, points=_live_pts(rows, "val_median_rel_err", 100.0, "validation")))
    spec["series"].append(_series("Training", 2, points=_live_pts(rows, "train_median_rel_err", 100.0, "training")))
    spec["hlines"].append((target_err * 100.0, f"{target_err * 100:g} % target"))
    _live_span(spec, rows, epochs)
    return spec


def live_grad(rows, epochs, n_hidden):
    """The gradient norm of the first and of the last hidden layer (the vanishing gradient shows as a gap between them)."""
    spec = _spec("Gradient norm per layer", "epoch", "gradient norm", ylog=True, xint=True)
    if not rows:
        spec["empty"] = "Waiting for the first epoch ..."
        return spec
    layers = [1] if n_hidden <= 1 else [1, n_hidden]
    for i, l in enumerate(layers):
        spec["series"].append(_series(f"Hidden {l}", i * 2, dash=bool(i), points=_live_pts(rows, f"grad_norm_{l}", 1.0, f"hidden layer {l}", ylog=True)))
    if not any(sr["points"] for sr in spec["series"]):
        spec["empty"] = "No gradient numbers yet."
    _live_span(spec, rows, epochs)
    return spec


def live_units(rows, epochs, n_hidden):
    """Saturated and dead units, the mean over the hidden layers."""
    spec = _spec("Saturated and dead units", "epoch", "units (%)", y0=True, xint=True)
    if not rows:
        spec["empty"] = "Waiting for the first epoch ..."
        return spec
    for name, key, slot, dash in (("Saturated", "saturation", 3, False), ("Dead", "dead", 5, True)):
        pts = []
        for r in rows:
            v = [float(r[f"{key}_{l}"]) for l in range(1, n_hidden + 1) if f"{key}_{l}" in r and finite(r[f"{key}_{l}"])]
            if v:
                m = sum(v) / len(v) * 100.0
                pts.append((float(r["epoch"]), m, f"{name.lower()} units, epoch {int(r['epoch'])}: {m:.3g} %"))
        spec["series"].append(_series(name, slot, dash=dash, points=pts))
    _live_span(spec, rows, epochs)
    return spec
