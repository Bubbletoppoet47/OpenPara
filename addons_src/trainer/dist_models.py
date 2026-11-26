"""dist_models.py - distance models that look at the box alone: a formula and four classical regressors.  No PyTorch, no Qt; numpy, and scikit-learn for two of them.

All of them answer ln d (the natural log of the distance in metres) from the numbers of dist_data (six numbers of the box, and one 0/1 column per class when there is
more than one class); the distance is exp(answer), kept inside 0.2 - 60 m.  A model is fitted on the TRAINING rows only (the standardising, k, the grid, the
formula's constant: nothing from the validation boxes), and is saved as ONE small file (.opdm, JSON text) that carries everything it needs to answer.

    pinhole     2a   d = k / (height of the box in pixels)                  k = median of d * height over the training boxes (one k per class)
    loglinear   2b   ln d = a + b ln h + c (bottom edge) [+ e ln w]          ordinary least squares; b should come out near -1
    knn         2c   the mean of ln d of the k nearest training boxes       k and uniform / distance weights chosen by cross-validation grouped by recording
    boosting    2d   gradient boosting of trees (scikit-learn HistGradientBoostingRegressor, absolute error)   learning rate, depth and number of trees by grouped cross-validation
    gp          2e   Gaussian process, constant x RBF with one length scale per input + white noise (scikit-learn), target ln d standardised; also says how sure it is
    mlp         3    a small neural network written out in numpy (np_net.py), trained from random weights on the rung of the ladder it is told (0 = the 1986 recipe ... 8)

A saved gradient boosting model holds a pickle of the scikit-learn model: a pickle can run code when it is read, so it is read only when the caller says it
trusts the file (load(..., trust_pickle=True)).  Every other kind is plain numbers.  The Gaussian process is saved as numbers too (its training rows, kernel and weights).
"""
import base64
import json
import os
import pickle
import time

import numpy as np

import dist_data as dd
import eval_harness as eh
import np_net as nn

FORMAT = "opara-distance-model-v1"
EXT = ".opdm"
FAMILIES = {}                                 # family key -> class
D_MIN, D_MAX = dd.D_MIN, dd.D_MAX
IDS = {"pinhole": "2a", "loglinear": "2b", "knn": "2c", "boosting": "2d", "gp": "2e", "mlp": "3"}


class UntrustedModel(Exception):
    """A model file holds a pickle and the caller did not say it trusts the file."""


def register(cls):
    FAMILIES[cls.family] = cls
    return cls


# ------------------------------------------------------------------ cross-validation grouped by recording
def group_folds(groups, n_splits=5):
    """[(train positions, validation positions)] with whole groups (recordings, or time blocks) in a fold, balanced by size.  Deterministic."""
    keys, inv, counts = np.unique(np.asarray(groups), return_inverse=True, return_counts=True)
    n_splits = min(int(n_splits), len(keys))
    if n_splits < 2:
        raise ValueError("Cross-validation needs at least two recordings (or two blocks of one): the training boxes come from just one group.")
    load, fold_of = np.zeros(n_splits), np.zeros(len(keys), int)
    for g in np.argsort(-counts, kind="stable"):
        f = int(np.argmin(load))
        fold_of[g] = f
        load[f] += counts[g]
    fold = fold_of[inv]
    return [(np.flatnonzero(fold != f), np.flatnonzero(fold == f)) for f in range(n_splits)]


def cv_groups_of(train, min_groups=5, frames=300):
    """The groups of the training boxes to cross-validate on (see dist_data.cv_groups). -> (groups, "recording" | "time block")."""
    return dd.cv_groups(train.image, min_groups, frames)


# ------------------------------------------------------------------ the base
class DistanceModel:
    family = ""
    needs = ()                                # extra Python packages it imports to fit or to answer (scikit-learn)
    pickled = False

    def __init__(self, imgsz=640, nc=1, names=None, seed=0):
        self.imgsz, self.nc, self.names, self.seed = int(imgsz), int(nc), list(names or []), int(seed)
        self.info = {}                        # what the fit says about itself (chosen k, coefficients, ...): goes into the result and the file

    # -- what a subclass does
    def fit(self, train, **kw):
        raise NotImplementedError

    def predict_log(self, X):
        raise NotImplementedError

    def params_dict(self):
        raise NotImplementedError

    def load_params(self, p):
        raise NotImplementedError

    def n_params(self):
        raise NotImplementedError

    def config(self):
        return {"seed": self.seed}

    # -- answering
    @property
    def id(self):
        return IDS.get(self.family, "")

    def predict_m(self, xyxy_lb, cls=None):
        """Metres for boxes (N, 4) in the pixels of the letterboxed imgsz x imgsz picture; cls: class numbers (needed with more than one class)."""
        feat = dd.geometry(xyxy_lb, self.imgsz)
        c = np.zeros(len(feat), int) if cls is None else np.asarray(cls, int)
        return self.answer(dd.with_class(feat, c, self.nc))

    def predict_m_orig(self, xyxy, W0, H0, cls=None):
        """Metres for boxes (N, 4) in the pixels of the original W0 x H0 picture (what a detector hands over)."""
        return self.predict_m(dd.orig_to_letterbox(xyxy, W0, H0, self.imgsz), cls)

    def predict_boxes(self, boxes):
        """Metres for a dd.Boxes (the labelled boxes of a side)."""
        return self.answer(boxes.X())

    def answer(self, X):
        return eh.clip_m(np.exp(self.predict_log(np.asarray(X, float))))

    # -- the file
    def to_dict(self):
        return {"format": FORMAT, "family": self.family, "id": self.id, "imgsz": self.imgsz, "nc": self.nc, "names": self.names, "seed": self.seed,
                "feature_names": list(dd.FEATURE_NAMES) + ([f"class_{n}" for n in self.names] if self.nc > 1 else []), "clip_m": [D_MIN, D_MAX],
                "config": self.config(), "info": self.info, "params": self.params_dict(), "needs": list(self.needs), "pickled": self.pickled}

    def save(self, path, scores=None, extra=None):
        d = self.to_dict()
        d["created"] = time.time()
        if scores:
            d["scores"] = scores
        if extra:
            d.update(extra)
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, path)
        return path


def from_dict(d, trust_pickle=False):
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        raise ValueError("This is not an OpenPara distance model file.")
    cls = FAMILIES.get(d.get("family"))
    if cls is None:
        raise ValueError(f"A distance model of the kind {d.get('family')!r} is not known to this version.")
    if cls.pickled and not trust_pickle:
        raise UntrustedModel("This model file holds a pickle of a scikit-learn model. A pickle can run code when it is read: open the file only if you trust where it came from.")
    m = cls(d.get("imgsz", 640), d.get("nc", 1), d.get("names"), d.get("seed", 0))
    m.info = d.get("info") or {}
    m.load_params(d["params"])
    return m


def load(path, trust_pickle=False):
    with open(path, encoding="utf-8") as f:
        return from_dict(json.load(f), trust_pickle)


def read_header(path):
    """The first-glance facts of a model file (family, scores, classes, ...) without building the model: -> dict or None.  Never reads a pickle."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        return None
    return {k: d.get(k) for k in ("family", "id", "imgsz", "nc", "names", "seed", "config", "info", "needs", "pickled", "created", "scores", "trained")}


def is_distance_model_file(path):
    return read_header(path) is not None


def _col(X, name):
    return X[:, dd.FEATURE_NAMES.index(name)]


def _class_of(X, nc):
    return np.argmax(X[:, 6:6 + nc], axis=1) if nc > 1 else np.zeros(len(X), int)


# ------------------------------------------------------------------ 2a the formula
@register
class Pinhole(DistanceModel):
    """d = k / h, h the height of the box in pixels (of the letterboxed picture).  A camera with focal length f sees an upright object of height H at distance Z with
    h = f H / Z, so k = f H is one number when the objects are alike; with several classes there is one k per class."""
    family = "pinhole"

    def fit(self, train, **kw):
        h, d, cls = train.h_px, train.dist, train.cls
        self.k_all = float(np.median(d * h))
        self.k = [float(np.median((d * h)[cls == c])) if (cls == c).any() else self.k_all for c in range(max(1, self.nc))]
        self.info = {"k": self.k_all if self.nc <= 1 else self.k, "k_all_classes": self.k_all}
        return self

    def predict_log(self, X):
        h = self.imgsz * np.exp(_col(X, "ln_height"))
        k = np.asarray(self.k, float)[_class_of(X, self.nc)]
        return np.log(k / h)

    def params_dict(self):
        return {"k": self.k, "k_all": self.k_all}

    def load_params(self, p):
        self.k, self.k_all = [float(x) for x in p["k"]], float(p["k_all"])

    def n_params(self):
        return len(self.k)


# ------------------------------------------------------------------ 2b log-linear regression
@register
class LogLinear(DistanceModel):
    """ln d = a + b ln h + c (bottom edge / H) [+ e ln w] [+ a shift per class]: ordinary least squares on the raw numbers, so the coefficients can be read.
    A pinhole camera has b = -1; the bottom edge is the ground-contact cue (an object standing on level ground is nearer the lower its foot is in the picture)."""
    family = "loglinear"

    def __init__(self, *a, use_width=False, **kw):
        super().__init__(*a, **kw)
        self.use_width = bool(use_width)

    def config(self):
        return {"seed": self.seed, "use_width": self.use_width}

    def design(self, X):
        cols = [np.ones(len(X)), _col(X, "ln_height"), _col(X, "bottom_edge")]
        if self.use_width:
            cols.append(_col(X, "ln_width"))
        if self.nc > 1:
            cols += [X[:, 6 + c] for c in range(1, self.nc)]               # the first class is the one the intercept belongs to
        return np.stack(cols, 1)

    def names_of_terms(self):
        n = ["a (intercept)", "b (ln of box height)", "c (bottom edge)"] + (["e (ln of box width)"] if self.use_width else [])
        return n + [f"shift for class {self.names[c] if c < len(self.names) else c}" for c in range(1, self.nc)] if self.nc > 1 else n

    def fit(self, train, use_width=None, **kw):
        if use_width is not None:
            self.use_width = bool(use_width)
        A, y = self.design(train.X()), train.y()
        self.coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        self.coef = np.asarray(self.coef, float)
        self.info = {"coefficients": dict(zip(self.names_of_terms(), [float(c) for c in self.coef]))}
        return self

    def predict_log(self, X):
        return self.design(X) @ self.coef

    def params_dict(self):
        return {"coef": [float(c) for c in self.coef], "use_width": self.use_width}

    def load_params(self, p):
        self.coef, self.use_width = np.asarray(p["coef"], float), bool(p.get("use_width", False))

    def n_params(self):
        return len(self.coef)


# ------------------------------------------------------------------ 2c k nearest neighbours
def _knn_predict(Xs_train, y, Xq, k, weights, chunk=512):
    out = np.empty(len(Xq))
    k = min(int(k), len(Xs_train))
    sq_train = (Xs_train ** 2).sum(1)
    for a in range(0, len(Xq), chunk):
        q = Xq[a:a + chunk]
        d2 = (q ** 2).sum(1)[:, None] + sq_train[None, :] - 2.0 * q @ Xs_train.T
        np.maximum(d2, 0, out=d2)
        idx = np.argpartition(d2, k - 1, axis=1)[:, :k] if k < d2.shape[1] else np.tile(np.arange(d2.shape[1]), (len(q), 1))
        nd = np.sqrt(np.take_along_axis(d2, idx, 1))
        if weights == "distance":
            w = 1.0 / np.maximum(nd, 1e-9)
            out[a:a + chunk] = (w * y[idx]).sum(1) / w.sum(1)
        else:
            out[a:a + chunk] = y[idx].mean(1)
    return out


@register
class KNN(DistanceModel):
    """The mean of ln d of the k nearest training boxes in the standardised numbers.  k and the weights (all alike, or by 1 / distance) are chosen by cross-validation
    grouped by recording on the training boxes only."""
    family = "knn"
    K_GRID = (3, 5, 9, 15, 25, 41)
    W_GRID = ("uniform", "distance")

    def config(self):
        return {"seed": self.seed, "k_grid": list(self.K_GRID), "weights_grid": list(self.W_GRID)}

    def fit(self, train, k=None, weights=None, folds=5, groups=None, **kw):
        X, y = train.X(), train.y()
        grid = [(kk, ww) for kk in self.K_GRID for ww in self.W_GRID] if k is None else [(int(k), weights or "uniform")]
        cv = {}
        if len(grid) > 1:
            grp = groups if groups is not None else cv_groups_of(train)[0]
            pairs = group_folds(grp, folds)
            oof = {g: np.zeros(len(y)) for g in grid}
            for tr, va in pairs:
                sd = dd.Standardiser().fit(X[tr])
                A, B = sd.apply(X[tr]), sd.apply(X[va])
                for kk, ww in grid:
                    oof[(kk, ww)][va] = _knn_predict(A, y[tr], B, kk, ww)
            for g in grid:
                cv[g] = eh.median_rel_err(eh.clip_m(np.exp(oof[g])), train.dist)
            k, weights = min(grid, key=lambda g: (cv[g], g[0]))
            self.info = {"cv_median_rel_err": {f"k={g[0]},{g[1]}": round(v, 5) for g, v in cv.items()}, "cv_folds": len(pairs)}
        self.k, self.weights = int(k), weights or "uniform"
        self.sd = dd.Standardiser().fit(X)
        self.Xs, self.y = self.sd.apply(X), y.copy()
        self.info.update(k=self.k, weights=self.weights, rows=int(len(y)))
        return self

    def predict_log(self, X):
        return _knn_predict(self.Xs, self.y, self.sd.apply(X), self.k, self.weights)

    def params_dict(self):
        return {"k": self.k, "weights": self.weights, "standardiser": self.sd.to_json(), "X": self.Xs.tolist(), "y": self.y.tolist()}

    def load_params(self, p):
        self.k, self.weights, self.sd = int(p["k"]), p["weights"], dd.Standardiser.from_json(p["standardiser"])
        self.Xs, self.y = np.asarray(p["X"], float), np.asarray(p["y"], float)

    def n_params(self):
        return 0                                       # nothing is learned: the model is its rows (see info["rows"])


# ------------------------------------------------------------------ 2d gradient boosting (scikit-learn)
@register
class Boosting(DistanceModel):
    """scikit-learn HistGradientBoostingRegressor (absolute error) on the standardised numbers.  The learning rate, the depth and the NUMBER OF TREES (up to 500: the early
    stopping) are chosen by cross-validation grouped by recording on the training boxes only; the model is then refitted on all training boxes."""
    family = "boosting"
    needs = ("scikit-learn",)
    pickled = True
    LR_GRID, DEPTH_GRID, MAX_ITER = (0.03, 0.1), (2, 3, 4), 500

    def config(self):
        return {"seed": self.seed, "loss": "absolute_error", "learning_rate_grid": list(self.LR_GRID), "depth_grid": list(self.DEPTH_GRID), "max_iter": self.MAX_ITER}

    @staticmethod
    def _make(lr, depth, iters, seed):
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(loss="absolute_error", learning_rate=lr, max_depth=depth, max_iter=iters, early_stopping=False, random_state=seed)

    def fit(self, train, folds=5, groups=None, learning_rates=None, depths=None, max_iter=None, **kw):
        X, y = train.X(), train.y()
        lrs, depths = tuple(learning_rates or self.LR_GRID), tuple(depths or self.DEPTH_GRID)
        iters = int(max_iter or self.MAX_ITER)
        pairs = group_folds(groups if groups is not None else cv_groups_of(train)[0], folds)
        cv, best = {}, None
        for lr in lrs:
            for dep in depths:
                oof = np.zeros((iters, len(y)))
                for tr, va in pairs:
                    sd = dd.Standardiser().fit(X[tr])
                    m = self._make(lr, dep, iters, self.seed).fit(sd.apply(X[tr]), y[tr])
                    for i, p in enumerate(m.staged_predict(sd.apply(X[va]))):
                        oof[i, va] = p
                    if i + 1 < iters:                          # (a fit that stopped before max_iter keeps its last answer)
                        oof[i + 1:, va] = oof[i, va]
                err = np.array([eh.median_rel_err(eh.clip_m(np.exp(o)), train.dist) for o in oof])
                n_trees = int(np.argmin(err)) + 1
                cv[f"lr={lr},depth={dep}"] = {"trees": n_trees, "cv_median_rel_err": round(float(err[n_trees - 1]), 5)}
                if best is None or err[n_trees - 1] < best[0]:
                    best = (float(err[n_trees - 1]), lr, dep, n_trees)
        _e, lr, dep, n_trees = best
        self.sd = dd.Standardiser().fit(X)
        self.model = self._make(lr, dep, n_trees, self.seed).fit(self.sd.apply(X), y)
        self.chosen = {"learning_rate": lr, "max_depth": dep, "trees": n_trees}
        self.info = {"chosen": self.chosen, "cv": cv, "cv_folds": len(pairs), "rows": int(len(y))}
        return self

    def predict_log(self, X):
        return self.model.predict(self.sd.apply(X))

    def params_dict(self):
        import sklearn
        return {"standardiser": self.sd.to_json(), "chosen": self.chosen, "sklearn": sklearn.__version__, "pickle_b64": base64.b64encode(pickle.dumps(self.model)).decode("ascii")}

    def load_params(self, p):
        self.sd, self.chosen = dd.Standardiser.from_json(p["standardiser"]), p.get("chosen") or {}
        self.model = pickle.loads(base64.b64decode(p["pickle_b64"]))                      # (only reached when the caller trusts the file)

    def n_params(self):
        try:
            return int(sum(t[0].nodes.shape[0] for t in self.model._predictors))
        except Exception:                                   # noqa: BLE001
            return None


# ------------------------------------------------------------------ 2e Gaussian process
@register
class GaussianProcess(DistanceModel):
    """scikit-learn GaussianProcessRegressor: constant x RBF (one length scale per input) + white noise, target ln d standardised, 2 restarts of the optimiser.
    More than max_rows training boxes are subsampled (at random, the seed is kept) because the fit costs about n^3.  Saved as numbers (the rows, the kernel and the
    weights), and answered with numpy alone: the answer is the same as scikit-learn's."""
    family = "gp"
    needs = ("scikit-learn",)
    JITTER = 1e-10                                          # scikit-learn's alpha

    def config(self):
        return {"seed": self.seed, "kernel": "constant * rbf(ard) + white", "restarts": 2, "normalize_y": True, "max_rows": getattr(self, "max_rows", 6000)}

    def fit(self, train, max_rows=6000, restarts=2, **kw):
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import ConstantKernel as C, RBF, WhiteKernel
        self.max_rows = int(max_rows)
        X, y = train.X(), train.y()
        sub = None
        if len(y) > self.max_rows:
            sub = np.sort(np.random.default_rng(self.seed).choice(len(y), self.max_rows, replace=False))
            X, y = X[sub], y[sub]
        self.sd = dd.Standardiser().fit(X)
        Xs = self.sd.apply(X)
        kernel = C(1.0, (1e-3, 1e3)) * RBF(length_scale=np.ones(Xs.shape[1]), length_scale_bounds=(1e-2, 1e2)) + WhiteKernel(0.1, (1e-6, 1e1))
        import warnings
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)             # (a length scale that runs to its bound is a finding: it is reported as "at_bound")
            gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, n_restarts_optimizer=int(restarts), random_state=self.seed).fit(Xs, y)
        k = gp.kernel_
        self.c, self.ls, self.noise = float(k.k1.k1.constant_value), np.asarray(k.k1.k2.length_scale, float), float(k.k2.noise_level)
        self.Xs, self.alpha = Xs, np.asarray(gp.alpha_, float)
        self._sk = gp                                        # (kept in memory only: it is what a test or a check compares the numpy answer with; never saved)
        self.y_mean, self.y_std = float(np.ravel(gp._y_train_mean)[0]), float(np.ravel(gp._y_train_std)[0])
        self._L = None
        names = list(dd.FEATURE_NAMES) + ([f"class_{n}" for n in self.names] if self.nc > 1 else [])
        self.info = {"rows": int(len(y)), "subsampled_from": int(len(train)) if sub is not None else None, "constant": self.c, "noise_level": self.noise,
                     "length_scales": {n: float(v) for n, v in zip(names, self.ls)}, "log_marginal_likelihood": float(gp.log_marginal_likelihood_value_),
                     "at_bound": [n for n, v in zip(names, self.ls) if v > 99.0 or v < 0.0101]}          # the input is ignored (an upper bound) or fitted to the noise (a lower bound)
        return self

    def _cross(self, Xq):
        A, B = Xq / self.ls, self.Xs / self.ls
        d2 = (A ** 2).sum(1)[:, None] + (B ** 2).sum(1)[None, :] - 2.0 * A @ B.T
        return self.c * np.exp(-0.5 * np.maximum(d2, 0))

    def predict_log(self, X):
        Xq = self.sd.apply(X)
        out = np.empty(len(Xq))
        for a in range(0, len(Xq), 1024):
            out[a:a + 1024] = self._cross(Xq[a:a + 1024]) @ self.alpha
        return out * self.y_std + self.y_mean

    def cholesky(self):
        """The factor of the training matrix (n x n, built once on first use: only the predictive spread needs it)."""
        if getattr(self, "_L", None) is None:
            K = self._cross(self.Xs) + (self.noise + self.JITTER) * np.eye(len(self.Xs))
            self._L = np.linalg.cholesky(K)
        return self._L

    def predict_log_std(self, X):
        """(mean, standard deviation) of ln d for the rows X: how sure the model is.  The spread includes the noise the model found in the labels."""
        from scipy.linalg import solve_triangular
        Xq = self.sd.apply(np.asarray(X, float))
        mean, var = np.empty(len(Xq)), np.empty(len(Xq))
        L = self.cholesky()
        for a in range(0, len(Xq), 1024):
            Kq = self._cross(Xq[a:a + 1024])
            mean[a:a + 1024] = Kq @ self.alpha
            v = solve_triangular(L, Kq.T, lower=True)
            var[a:a + 1024] = np.maximum(self.c + self.noise - (v ** 2).sum(0), 0.0)
        return mean * self.y_std + self.y_mean, np.sqrt(var) * self.y_std

    def params_dict(self):
        return {"standardiser": self.sd.to_json(), "constant": self.c, "length_scales": self.ls.tolist(), "noise": self.noise, "jitter": self.JITTER,
                "y_mean": self.y_mean, "y_std": self.y_std, "X": self.Xs.tolist(), "alpha": self.alpha.tolist()}

    def load_params(self, p):
        self.sd, self.c, self.ls, self.noise = dd.Standardiser.from_json(p["standardiser"]), float(p["constant"]), np.asarray(p["length_scales"], float), float(p["noise"])
        self.JITTER = float(p.get("jitter", 1e-10))
        self.y_mean, self.y_std = float(p["y_mean"]), float(p["y_std"])
        self.Xs, self.alpha, self._L = np.asarray(p["X"], float), np.asarray(p["alpha"], float), None

    def n_params(self):
        return len(self.ls) + 2                              # one length scale per input, the constant and the noise


# ------------------------------------------------------------------ 3 a small neural network (np_net)
@register
class MLPModel(DistanceModel):
    """The network of np_net.py on the standardised numbers of the box.  Its settings are those of a rung of the ladder (np_net.rung_config); it is saved as plain numbers.
    What it answers depends on its target: metres / 20 (rung 0 - 2) or the standardised ln d (rung 3 and up); answer() turns either into metres inside 0.2 - 60."""
    family = "mlp"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cfg, self.net, self.target, self.sd, self.run = None, None, None, None, {}

    def config(self):
        return {"seed": self.seed, **({k: (list(v) if isinstance(v, tuple) else v) for k, v in (self.cfg or {}).items() if k not in ("change",)})}

    def fit(self, train, val=None, rung=6, cfg=None, epochs=200, lr=None, log=None, stop=None, target_err=0.075, every=1, **over):
        """Trains on the TRAINING rows.  `val` (dd.Boxes) is what the learning curve and early stopping watch; it is never trained on.  With no `val` the training rows are watched
        (and early stopping cannot be asked for).  `cfg` is a complete settings dict, else `rung` and any `over`rides (activation=, hidden=, optimizer=, ...)."""
        self.cfg = nn.rung_config(rung, **over) if cfg is None else dict(cfg)
        if val is None and self.cfg.get("early_stopping"):
            raise ValueError("Early stopping needs validation boxes to watch.")
        Xtr = train.X()
        self.sd = dd.Standardiser().fit(Xtr)
        v = train if val is None else val
        r = nn.fit(self.cfg, self.sd.apply(Xtr), train.dist, self.sd.apply(v.X()), v.dist, epochs=epochs, seed=self.seed, lr=lr, log=log, stop=stop, target_err=target_err, every=every)
        return self.adopt(r, self.sd, self.cfg)

    def adopt(self, r, sd, cfg):
        """Takes the result of np_net.fit (made on inputs standardised with `sd`) as this model: the job fits many networks and keeps some, so it does not train twice."""
        self.cfg, self.sd = dict(cfg), sd
        self.run, self.net, self.target = r, r["net"], r["target"]
        self.cfg["lr"] = r["lr"]
        self.info = {"rung": self.cfg.get("rung"), "name": self.cfg.get("name"), "lr": r["lr"], "epochs_run": r["epochs_run"], "best_epoch": r["best_epoch"], "diverged": r["diverged"],
                     "epochs_to_target": r["epochs_to_target"], "hidden": list(self.cfg["hidden"]), "activation": self.cfg["activation"], "optimizer": self.cfg["optimizer"]}
        return self

    def answer(self, X):
        if self.net is None or r_diverged(self):
            raise ValueError("This network has no usable weights (the run diverged).")
        return self.target.decode(self.net.predict(self.sd.apply(np.asarray(X, float))))

    def predict_log(self, X):
        return np.log(self.answer(X))

    def params_dict(self):
        return {"standardiser": self.sd.to_json(), "target": self.target.to_dict(), "cfg": self.config(), "net": self.net.to_dict()}

    def load_params(self, p):
        self.sd = dd.Standardiser.from_json(p["standardiser"])
        t = p["target"]
        self.target = nn.Target(t["kind"], t["mean"], t["std"])
        self.cfg = dict(p.get("cfg") or {})
        self.net = nn.MLP.from_dict(p["net"])

    def n_params(self):
        return self.net.n_params() if self.net is not None else 0


def r_diverged(m):
    return bool(m.run.get("diverged")) if m.run else False


def calibration(y_true_log, mean, std, levels=(0.68, 0.95)):
    """The share of boxes whose true ln d lies inside the predictive interval of each level (the interval is mean +- z std).  Near the level when the model's spread is honest."""
    from math import erf, sqrt
    out = {}
    z_of = {0.68: 1.0, 0.95: 1.959964}
    for lv in levels:
        z = z_of.get(lv)
        if z is None:                                        # any other level: the z whose two-sided share is lv (found by bisection)
            lo, hi = 0.0, 10.0
            for _ in range(60):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if erf(mid / sqrt(2)) < lv else (lo, mid)
            z = (lo + hi) / 2
        out[f"{lv:g}"] = float(np.mean(np.abs(np.asarray(y_true_log) - mean) <= z * std))
    return out


def make(variant, imgsz=640, nc=1, names=None, seed=0, **opts):
    """A new, unfitted model of a variant key ('pinhole', 'loglinear', 'knn', 'boosting', 'gp')."""
    if variant not in FAMILIES:
        raise ValueError(f"Unknown distance model {variant!r}: {', '.join(FAMILIES)}")
    return FAMILIES[variant](imgsz, nc, names, seed, **opts)
