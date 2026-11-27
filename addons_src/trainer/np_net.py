"""np_net.py - a small neural network written by hand in numpy: forward pass, backpropagation, the optimisers, initialisations, batch normalisation, and what is logged
while it learns.  No PyTorch, no autograd, no Qt.  It is the "ladder" of the Trainer's NumPy distance model: from the 1986 recipe (sigmoid units, mean squared error, plain gradient
descent) one ingredient at a time to a modern one (Adam, batch normalisation, weight decay), so what each ingredient buys can be measured.

Notation (the equations are the ones of the specification):
    a(l) = W(l) z(l-1) + b(l)         z(l) = h(a(l))          z(0) = the input         the output layer is linear
    delta(L) = dL/dyhat               delta(l) = (W(l+1)^T delta(l+1)) * h'(a(l))
    dL/dW(l) = delta(l) z(l-1)^T      dL/db(l) = delta(l)      (averaged over the mini-batch: the loss is a mean)
Rows are examples here (a batch is an array (m, n)), so a layer reads  A = Z W^T + b  and W has the shape (n_out, n_in) as in the equations.
With batch normalisation (before the activation) a hidden layer is  a -> xhat = (a - mean) / sqrt(var + eps) -> u = gamma xhat + beta -> z = h(u); the bias of such a layer is kept (the
count of parameters is the usual one) but its gradient is exactly zero: the mean that follows takes it away again.

What is in the file:
    MLP                the network (forward, backward, parameters, the count of them, saving as plain numbers)
    loss_value_grad    mean squared error and smooth L1
    Optimizer          plain gradient descent, momentum (heavy ball), Adam, AdamW (decoupled weight decay)
    gradient_check     the central-difference check of every gradient (the mandatory unit test uses it)
    Target             what the network is asked for: metres / 20, or the standardised log of the distance
    RUNGS, fit()       the ladder: rung 0 (1986) ... rung 8, the deep-sigmoid demo; and the training loop with the per-epoch diagnostics
    design_hidden      the widths of the hidden layers for a total number of parameters and a taper
    heavy_ball, damping_regime   the damping picture of momentum on a quadratic
"""
import math
import time

import numpy as np

ACTIVATIONS = ("sigmoid", "tanh", "relu", "silu")
LOSSES = ("mse", "smooth_l1")


# ------------------------------------------------------------------ activations
def _sigmoid(a):
    return 1.0 / (1.0 + np.exp(-np.clip(a, -500.0, 500.0)))


def act_forward(name, a):
    if name == "sigmoid":
        return _sigmoid(a)
    if name == "tanh":
        return np.tanh(a)
    if name == "relu":
        return np.maximum(a, 0.0)
    if name == "silu":
        return a * _sigmoid(a)
    raise ValueError(f"Unknown activation {name!r}: {', '.join(ACTIVATIONS)}")


def act_deriv(name, a, z):
    """h'(a), written the way the specification gives it: in terms of z for sigmoid and tanh, of a for ReLU and SiLU."""
    if name == "sigmoid":
        return z * (1.0 - z)
    if name == "tanh":
        return 1.0 - z * z
    if name == "relu":
        return (a > 0).astype(a.dtype)
    if name == "silu":
        s = _sigmoid(a)
        return s * (1.0 + a * (1.0 - s))
    raise ValueError(f"Unknown activation {name!r}")


# ------------------------------------------------------------------ losses
def loss_value_grad(kind, yhat, y, beta=0.1):
    """(mean loss, dL/dyhat of the mean) for predictions and targets of one batch (1-D arrays)."""
    u = np.asarray(yhat, float) - np.asarray(y, float)
    m = len(u)
    if kind == "mse":
        return float(np.mean(u * u)), 2.0 * u / m
    if kind == "smooth_l1":
        a = np.abs(u)
        small = a < beta
        val = np.where(small, 0.5 * u * u / beta, a - 0.5 * beta)
        g = np.where(small, u / beta, np.sign(u))
        return float(np.mean(val)), g / m
    raise ValueError(f"Unknown loss {kind!r}: {', '.join(LOSSES)}")


def loss_value(kind, yhat, y, beta=0.1):
    return loss_value_grad(kind, yhat, y, beta)[0]


# ------------------------------------------------------------------ initialisation
def init_weights(rng, n_in, n_out, kind, scale=0.1):
    """(W (n_out, n_in), b (n_out)).  uniform: U(-scale, scale) for both (the 1986 way).  glorot: U(+-sqrt(6/(n_in+n_out))), biases 0.  he: N(0, 2/n_in), biases 0."""
    if kind == "uniform":
        return rng.uniform(-scale, scale, (n_out, n_in)), rng.uniform(-scale, scale, n_out)
    if kind == "glorot":
        lim = math.sqrt(6.0 / (n_in + n_out))
        return rng.uniform(-lim, lim, (n_out, n_in)), np.zeros(n_out)
    if kind == "he":
        return rng.normal(0.0, math.sqrt(2.0 / n_in), (n_out, n_in)), np.zeros(n_out)
    raise ValueError(f"Unknown initialisation {kind!r}: uniform, glorot, he")


def count_params(n_in, hidden, batch_norm=False):
    """The number of parameters of n_in -> hidden... -> 1: weights and biases, and gamma and beta of every hidden layer with batch normalisation."""
    sizes = [n_in] + list(hidden) + [1]
    p = sum(sizes[i] * sizes[i + 1] + sizes[i + 1] for i in range(len(sizes) - 1))
    return p + (2 * sum(hidden) if batch_norm else 0)


def design_hidden(total, depth, ratio=1.0, n_in=6, batch_norm=False):
    """The widths of `depth` hidden layers (each `ratio` times the one before: 1 = all alike, 0.5 = halving) that come closest to `total` parameters.  -> (list of widths, their count)."""
    best = None
    for w1 in range(1, 4097):
        hidden = [max(1, int(round(w1 * ratio ** i))) for i in range(depth)]
        n = count_params(n_in, hidden, batch_norm)
        if best is None or abs(n - total) < abs(best[1] - total):
            best = (hidden, n)
    return best


# ------------------------------------------------------------------ the network
class MLP:
    """n_in -> hidden... -> 1 (linear output).  params() are the arrays the optimiser changes; they are changed in place."""

    def __init__(self, n_in, hidden, activation="tanh", init="glorot", init_scale=0.1, batch_norm=False, bn_eps=1e-5, bn_momentum=0.1, seed=0, dtype=np.float64):
        if activation not in ACTIVATIONS:
            raise ValueError(f"Unknown activation {activation!r}: {', '.join(ACTIVATIONS)}")
        self.sizes = [int(n_in)] + [int(h) for h in hidden] + [1]
        self.activation, self.init, self.init_scale, self.batch_norm = activation, init, float(init_scale), bool(batch_norm)
        self.bn_eps, self.bn_momentum, self.dtype = float(bn_eps), float(bn_momentum), dtype
        rng = np.random.default_rng(seed)
        self.W, self.b, self.gamma, self.beta, self.run_mean, self.run_var = [], [], [], [], [], []
        for i in range(len(self.sizes) - 1):
            W, b = init_weights(rng, self.sizes[i], self.sizes[i + 1], init, init_scale)
            self.W.append(W.astype(dtype))
            self.b.append(b.astype(dtype))
            if self.batch_norm and i < len(self.sizes) - 2:
                n = self.sizes[i + 1]
                self.gamma.append(np.ones(n, dtype))
                self.beta.append(np.zeros(n, dtype))
                self.run_mean.append(np.zeros(n, dtype))
                self.run_var.append(np.ones(n, dtype))

    @property
    def L(self):
        return len(self.W)

    def params(self):
        """[(name, array)] in a fixed order: W1, b1, [gamma1, beta1], W2, b2, ..."""
        out = []
        for l in range(self.L):
            out += [(f"W{l + 1}", self.W[l]), (f"b{l + 1}", self.b[l])]
            if self.batch_norm and l < self.L - 1:
                out += [(f"gamma{l + 1}", self.gamma[l]), (f"beta{l + 1}", self.beta[l])]
        return out

    def n_params(self):
        return int(sum(a.size for _n, a in self.params()))

    # -- forward
    def forward(self, X, train=True, update_stats=True):
        """-> (yhat (m,), cache).  train: batch normalisation uses the statistics of this batch (and updates the running ones when update_stats); otherwise the running ones."""
        z = np.asarray(X, self.dtype)
        cache = {"z": [z], "a": [], "u": [], "xhat": [], "inv": []}
        for l in range(self.L - 1):
            a = z @ self.W[l].T + self.b[l]
            if self.batch_norm:
                if train:
                    mu, var = a.mean(0), a.var(0)
                    if update_stats:
                        mom = self.bn_momentum
                        self.run_mean[l] = (1.0 - mom) * self.run_mean[l] + mom * mu
                        self.run_var[l] = (1.0 - mom) * self.run_var[l] + mom * var
                else:
                    mu, var = self.run_mean[l], self.run_var[l]
                inv = 1.0 / np.sqrt(var + self.bn_eps)
                xhat = (a - mu) * inv
                u = self.gamma[l] * xhat + self.beta[l]
                cache["xhat"].append(xhat)
                cache["inv"].append(inv)
            else:
                u = a
            z = act_forward(self.activation, u)
            cache["a"].append(a)
            cache["u"].append(u)
            cache["z"].append(z)
        yhat = (z @ self.W[-1].T + self.b[-1])[:, 0]
        return yhat, cache

    def predict(self, X):
        return self.forward(X, train=False)[0]

    # -- backward
    def backward(self, cache, dyhat):
        """The gradient of every parameter, {name: array}, from dL/dyhat (m,) (the loss is a mean, so it already holds the 1/m)."""
        g = {}
        m = len(dyhat)
        delta = np.asarray(dyhat, self.dtype)[:, None]                          # delta(L) = dL/dyhat (the output is linear)
        g[f"W{self.L}"] = delta.T @ cache["z"][-1]
        g[f"b{self.L}"] = delta.sum(0)
        dz = delta @ self.W[-1]                                                   # dL/dz(L-1)
        for l in range(self.L - 2, -1, -1):
            du = dz * act_deriv(self.activation, cache["u"][l], cache["z"][l + 1])        # (W(l+1)^T delta(l+1)) * h'
            if self.batch_norm:
                xhat, inv = cache["xhat"][l], cache["inv"][l]
                g[f"gamma{l + 1}"] = (du * xhat).sum(0)
                g[f"beta{l + 1}"] = du.sum(0)
                dxhat = du * self.gamma[l]
                da = (inv / m) * (m * dxhat - dxhat.sum(0) - xhat * (dxhat * xhat).sum(0))
            else:
                da = du
            g[f"W{l + 1}"] = da.T @ cache["z"][l]
            g[f"b{l + 1}"] = da.sum(0)
            dz = da @ self.W[l]
        return g

    # -- diagnostics of one forward pass
    def unit_stats(self, cache):
        """Per hidden layer: the share of saturated units (|z| > 0.99 for tanh; z < 0.01 or > 0.99 for sigmoid) and of dead ReLU units (<= 0 on every row of the batch)."""
        sat, dead = [], []
        for l in range(self.L - 1):
            z, u = cache["z"][l + 1], cache["u"][l]
            if self.activation == "tanh":
                sat.append(float(np.mean(np.abs(z) > 0.99)))
            elif self.activation == "sigmoid":
                sat.append(float(np.mean((z < 0.01) | (z > 0.99))))
            else:
                sat.append(0.0)
            dead.append(float(np.mean(np.all(u <= 0, axis=0))) if self.activation == "relu" else 0.0)
        return sat, dead

    # -- saving as plain numbers
    def to_dict(self):
        d = {"sizes": self.sizes, "activation": self.activation, "batch_norm": self.batch_norm, "bn_eps": self.bn_eps,
             "W": [w.tolist() for w in self.W], "b": [b.tolist() for b in self.b]}
        if self.batch_norm:
            d.update(gamma=[x.tolist() for x in self.gamma], beta=[x.tolist() for x in self.beta], run_mean=[x.tolist() for x in self.run_mean], run_var=[x.tolist() for x in self.run_var])
        return d

    @classmethod
    def from_dict(cls, d):
        net = cls(d["sizes"][0], d["sizes"][1:-1], d["activation"], "glorot", batch_norm=d.get("batch_norm", False), bn_eps=d.get("bn_eps", 1e-5))
        net.W, net.b = [np.asarray(w, float) for w in d["W"]], [np.asarray(b, float) for b in d["b"]]
        if net.batch_norm:
            net.gamma, net.beta = [np.asarray(x, float) for x in d["gamma"]], [np.asarray(x, float) for x in d["beta"]]
            net.run_mean, net.run_var = [np.asarray(x, float) for x in d["run_mean"]], [np.asarray(x, float) for x in d["run_var"]]
        return net

    def copy_state(self):
        return {n: a.copy() for n, a in self.params()}, ([x.copy() for x in self.run_mean], [x.copy() for x in self.run_var])

    def set_state(self, state):
        params, (rm, rv) = state
        for n, a in self.params():
            a[...] = params[n]
        self.run_mean, self.run_var = [x.copy() for x in rm], [x.copy() for x in rv]


# ------------------------------------------------------------------ optimisers
class Optimizer:
    """kind: 'sgd' (plain gradient descent, or with momentum mu > 0: v <- mu v - eta g, theta <- theta + v), 'adam' or 'adamw'.
    weight_decay lambda is decoupled (theta <- theta - eta lambda theta, outside the gradient) and acts on the weight matrices only.
    After a step, last_ratio[name] = the size of the step taken / the size of the weights, per weight matrix."""

    def __init__(self, kind="sgd", lr=0.01, momentum=0.0, beta1=0.9, beta2=0.999, eps=1e-8, weight_decay=0.0):
        if kind not in ("sgd", "adam", "adamw"):
            raise ValueError(f"Unknown optimiser {kind!r}: sgd, adam, adamw")
        self.kind, self.lr, self.mu, self.b1, self.b2, self.eps, self.wd = kind, float(lr), float(momentum), float(beta1), float(beta2), float(eps), float(weight_decay)
        self.t, self.v, self.s, self.last_ratio = 0, {}, {}, {}

    def step(self, net, grads):
        self.t += 1
        for name, p in net.params():
            g = grads[name]
            is_w = name.startswith("W")
            prev = p.copy() if is_w else None                                  # (the weights before the step: the size of the step, and what the decay acts on)
            if self.kind == "sgd":
                if self.mu > 0:
                    v = self.v.get(name)
                    v = self.mu * (v if v is not None else 0.0) - self.lr * g
                    self.v[name] = v
                    p += v
                else:
                    p -= self.lr * g
            else:
                m = self.b1 * self.v.get(name, 0.0) + (1.0 - self.b1) * g
                s = self.b2 * self.s.get(name, 0.0) + (1.0 - self.b2) * g * g
                self.v[name], self.s[name] = m, s
                mh, sh = m / (1.0 - self.b1 ** self.t), s / (1.0 - self.b2 ** self.t)
                p -= self.lr * mh / (np.sqrt(sh) + self.eps)
            if is_w:
                if self.wd:
                    p -= self.lr * self.wd * prev
                nb = float(np.linalg.norm(prev))
                self.last_ratio[name] = float(np.linalg.norm(p - prev) / nb) if nb > 0 else 0.0


# ------------------------------------------------------------------ the check of every gradient
def gradient_check(net, X, y, loss="mse", beta=0.1, h=1e-5, train=True, small=1e-8, richardson=False):
    """The central-difference check: for every parameter, (L(theta + h) - L(theta - h)) / 2h against the analytic gradient.
    -> {"max_rel": the worst relative error |a - n| / max(|a|, |n|, 1e-12), "worst": its parameter name, "per_param": {name: worst relative error}}.
    A parameter whose gradient is zero to `small` on both sides (the bias of a layer with batch normalisation) counts as agreeing: its relative error is meaningless.
    richardson: the difference is taken at h and h/2 and combined, (4 D(h/2) - D(h)) / 3, which removes the h^2 term: for a loss that bends quickly (batch normalisation on a
    small batch) the plain central difference itself is off by about 1e-6 of the gradient, and that is the check's error, not the gradient's."""
    yhat, cache = net.forward(X, train=train, update_stats=False)
    _l, dy = loss_value_grad(loss, yhat, y, beta)
    grads = net.backward(cache, dy)

    def loss_at():
        return loss_value(loss, net.forward(X, train=train, update_stats=False)[0], y, beta)

    def central(flat, i, step):
        old = flat[i]
        flat[i] = old + step
        lp = loss_at()
        flat[i] = old - step
        lm = loss_at()
        flat[i] = old
        return (lp - lm) / (2.0 * step)

    per = {}
    for name, p in net.params():
        worst = 0.0
        flat, gflat = p.reshape(-1), grads[name].reshape(-1)
        assert np.shares_memory(flat, p), "the parameter must be changed in place"
        for i in range(flat.size):
            num = central(flat, i, h)
            if richardson:
                num = (4.0 * central(flat, i, h / 2.0) - num) / 3.0
            ana = gflat[i]
            if abs(num) < small and abs(ana) < small:
                continue
            worst = max(worst, abs(ana - num) / max(abs(ana), abs(num), 1e-12))
        per[name] = worst
    name = max(per, key=per.get)
    return {"max_rel": per[name], "worst": name, "per_param": per}


# ------------------------------------------------------------------ what the network is asked for
class Target:
    """kind 'd20': the distance divided by 20 (metres scaled into 0 - 1; the answer is 20 x the output).  kind 'log_std': the natural log of the distance, standardised with the
    training mean and standard deviation (the answer is exp(output x std + mean)).  The distance is kept inside 0.2 - 60 m in both."""

    def __init__(self, kind="d20", mean=0.0, std=1.0):
        self.kind, self.mean, self.std = kind, float(mean), float(std) if std else 1.0

    @classmethod
    def fit(cls, kind, dist):
        if kind == "log_std":
            ld = np.log(np.clip(np.asarray(dist, float), 0.2, 60.0))
            return cls(kind, ld.mean(), ld.std() if ld.std() > 1e-9 else 1.0)
        return cls(kind)

    def encode(self, d):
        d = np.clip(np.asarray(d, float), 0.2, 60.0)
        return d / 20.0 if self.kind == "d20" else (np.log(d) - self.mean) / self.std

    def decode(self, yhat):
        """Metres, kept inside 0.2 - 60."""
        y = np.asarray(yhat, float)
        if self.kind == "d20":
            return np.clip(y * 20.0, 0.2, 60.0)
        return np.clip(np.exp(np.clip(y * self.std + self.mean, -20, 20)), 0.2, 60.0)

    def beta_for(self, beta_log):
        """The smooth-L1 threshold in the units of the target: beta_log is in ln d (the Trainer's 0.1)."""
        return beta_log / self.std if self.kind == "log_std" else beta_log

    def to_dict(self):
        return {"kind": self.kind, "mean": self.mean, "std": self.std}


# ------------------------------------------------------------------ the ladder
BASE = dict(activation="sigmoid", init="uniform", init_scale=0.1, target="d20", loss="mse", optimizer="sgd", momentum=0.0, batch_norm=False, weight_decay=0.0,
            early_stopping=False, patience=50, beta_log=0.1, batch=32, hidden=(32, 16))
RUNGS = {
    0: dict(BASE, name="1986 baseline", change="sigmoid units, linear output, target d/20, mean squared error, plain gradient descent, mini-batch 32, init U(-0.1, 0.1), no momentum"),
    1: dict(BASE, name="tanh", change="tanh instead of sigmoid", activation="tanh"),
    2: dict(BASE, name="momentum", change="heavy-ball momentum", activation="tanh", momentum=0.9),
    3: dict(BASE, name="log target", change="target = standardised ln d", activation="tanh", momentum=0.9, target="log_std"),
    4: dict(BASE, name="smooth L1", change="smooth-L1 loss, beta 0.1 in log space", activation="tanh", momentum=0.9, target="log_std", loss="smooth_l1"),
    5: dict(BASE, name="ReLU + He", change="ReLU with He initialisation (or SiLU with Glorot)", activation="relu", init="he", momentum=0.9, target="log_std", loss="smooth_l1"),
    6: dict(BASE, name="Adam", change="Adam", activation="relu", init="he", target="log_std", loss="smooth_l1", optimizer="adam"),
    7: dict(BASE, name="batch norm", change="batch normalisation before the activation", activation="relu", init="he", target="log_std", loss="smooth_l1", optimizer="adam", batch_norm=True),
    8: dict(BASE, name="weight decay + early stopping", change="decoupled weight decay (AdamW) and early stopping on validation", activation="relu", init="he", target="log_std",
            loss="smooth_l1", optimizer="adamw", batch_norm=True, weight_decay=1e-4, early_stopping=True),
}
DEMO_BASE = dict(BASE, target="log_std", loss="mse", momentum=0.9, activation="sigmoid", init="uniform")      # plain recipe with momentum: only depth, activation and batch norm change
DEMOS = {
    "demo_sigmoid": dict(DEMO_BASE, name="deep sigmoid", change="sigmoid, uniform init"),
    "demo_relu_he": dict(DEMO_BASE, name="deep ReLU + He", change="ReLU with He initialisation", activation="relu", init="he"),
    "demo_bn": dict(DEMO_BASE, name="deep batch norm", change="sigmoid with batch normalisation", batch_norm=True),
}
LR_GRID = (1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1)
LR_ADAM = (1e-4, 3e-4, 1e-3, 3e-3, 1e-2)


def rung_config(rung, **over):
    """The full settings of a rung (a number 0 - 8 or 'demo_sigmoid' / 'demo_relu_he' / 'demo_bn'), with any of them replaced.  'depth' and 'width' make `depth` hidden layers of `width`."""
    key = rung if rung in DEMOS else int(rung)
    base = dict((DEMOS if rung in DEMOS else RUNGS)[key])
    depth, width = over.pop("depth", None), over.pop("width", None)
    base.update({k: v for k, v in over.items() if v is not None})
    if depth is not None or width is not None:
        base["hidden"] = (int(width or 32),) * int(depth or 2)
    if over.get("activation") == "silu" and over.get("init") is None and base.get("init") == "he":
        base["init"] = "glorot"
    base["rung"] = rung
    base.setdefault("lr", default_lr(base))
    return base


def default_lr(cfg):
    return 1e-3 if cfg["optimizer"] in ("adam", "adamw") else 0.03


def lr_grid(cfg):
    return LR_ADAM if cfg["optimizer"] in ("adam", "adamw") else LR_GRID


# ------------------------------------------------------------------ the training loop
def median_rel(pred, true):
    return float(np.median(np.abs(pred - true) / true))


def fit(cfg, Xtr, dtr, Xva, dva, *, epochs=1000, seed=0, lr=None, log=None, target_err=0.075, every=1, stop=None, on_epoch=None):
    """Trains a network of the settings `cfg` (rung_config) on standardised inputs Xtr (n, n_in) with labelled distances dtr (metres), watching the validation boxes Xva, dva.
    -> {"net", "target", "rows" (one dict per epoch), "diverged", "diverged_epoch", "best_epoch", "final": {...}, "epochs_run", "epochs_to_target", "seconds"}.
    Each row has: epoch, train_loss, val_loss, val_median_rel_err, val_within20, lr, momentum, epoch_seconds, and per layer l: grad_norm_l, update_ratio_l, weight_norm_l (and
    saturation_l, dead_l for the hidden ones) - the quantities of the specification's table.  A run is `diverged` when its loss is not finite or is above 10 x its first value: it
    stops there and is counted, not dropped.  With early stopping the weights of the best epoch (by validation median error) are kept.
    `on_epoch(row, rows)`, when given, is called after every epoch (the Trainer window draws the run while it trains)."""
    lr = float(lr if lr is not None else cfg.get("lr") or default_lr(cfg))
    Xtr, Xva = np.asarray(Xtr, float), np.asarray(Xva, float)
    target = Target.fit(cfg["target"], dtr)
    ytr, yva = target.encode(dtr), target.encode(dva)
    beta = target.beta_for(cfg["beta_log"])
    net = MLP(Xtr.shape[1], cfg["hidden"], cfg["activation"], cfg["init"], cfg["init_scale"], cfg["batch_norm"], seed=seed)
    opt = Optimizer(cfg["optimizer"], lr, cfg["momentum"], weight_decay=cfg["weight_decay"])
    rng = np.random.default_rng(seed + 100003)
    n, bs = len(ytr), int(cfg["batch"])
    first = loss_value(cfg["loss"], net.forward(Xtr, train=True, update_stats=False)[0], ytr, beta)
    rows, diverged, div_epoch = [], False, None
    best = {"err": float("inf"), "epoch": 0, "state": None}
    reached = None
    t_all = time.time()

    def evaluate():
        pv = net.predict(Xva)
        return loss_value(cfg["loss"], pv, yva, beta), target.decode(pv)

    for ep in range(1, int(epochs) + 1):
        if stop is not None and stop():
            break
        t0 = time.time()
        perm = rng.permutation(n)
        tot, nb = 0.0, 0
        gsum = [0.0] * net.L
        rsum = [0.0] * net.L
        bad = False
        for a in range(0, n, bs):
            idx = perm[a:a + bs]
            if len(idx) < 2 and net.batch_norm:
                continue                                                         # (one row has no batch statistics)
            yh, cache = net.forward(Xtr[idx], train=True)
            lv, dy = loss_value_grad(cfg["loss"], yh, ytr[idx], beta)
            if not math.isfinite(lv) or lv > 1e6:
                bad = True
                break
            grads = net.backward(cache, dy)
            for l in range(net.L):
                gsum[l] += float(np.linalg.norm(grads[f"W{l + 1}"]))
            opt.step(net, grads)
            for l in range(net.L):
                rsum[l] += opt.last_ratio.get(f"W{l + 1}", 0.0)
            tot += lv
            nb += 1
        train_loss = tot / max(nb, 1)
        if bad or not math.isfinite(train_loss) or train_loss > 10.0 * first or any(not np.all(np.isfinite(a)) for _n, a in net.params()):
            diverged, div_epoch = True, ep
            rows.append({"epoch": ep, "train_loss": float("nan") if bad else train_loss, "val_loss": float("nan"), "val_median_rel_err": float("nan"), "val_within20": float("nan"),
                         "lr": lr, "momentum": cfg["momentum"], "epoch_seconds": time.time() - t0})
            if log:
                log(f"epoch {ep}: the loss {'is not a number' if bad or not math.isfinite(train_loss) else f'is {train_loss / first:.0f} times its first value'} - the run has diverged and stops.")
            break
        vl, pm = evaluate()
        err = median_rel(pm, dva)
        row = {"epoch": ep, "train_loss": train_loss, "val_loss": vl, "val_median_rel_err": err, "val_within20": float(np.mean(np.abs(pm - dva) / dva <= 0.2)), "lr": lr,
               "momentum": cfg["momentum"]}
        _y, cache_all = net.forward(Xtr, train=False)
        row["train_median_rel_err"] = median_rel(target.decode(_y), dtr)
        sat, dead = net.unit_stats(cache_all)
        for l in range(net.L):
            row[f"grad_norm_{l + 1}"] = gsum[l] / max(nb, 1)
            row[f"update_ratio_{l + 1}"] = rsum[l] / max(nb, 1)
            row[f"weight_norm_{l + 1}"] = float(np.linalg.norm(net.W[l]))
        for l in range(net.L - 1):
            row[f"saturation_{l + 1}"] = sat[l]
            row[f"dead_{l + 1}"] = dead[l]
        row["epoch_seconds"] = time.time() - t0
        rows.append(row)
        if on_epoch is not None:
            on_epoch(row, rows)
        if reached is None and err <= target_err:
            reached = ep
        if err < best["err"]:
            best.update(err=err, epoch=ep, state=net.copy_state() if cfg["early_stopping"] else None)
        if log and (ep == 1 or ep % max(1, int(every)) == 0):
            log(f"epoch {ep}/{epochs}  train loss {train_loss:.5f}  validation: loss {vl:.5f}, median error {err * 100:.1f}%")
        if cfg["early_stopping"] and ep - best["epoch"] >= int(cfg["patience"]):
            if log:
                log(f"No improvement for {cfg['patience']} epochs - stopping early (the best was epoch {best['epoch']}).")
            break
    if cfg["early_stopping"] and best["state"] is not None and not diverged:
        net.set_state(best["state"])
    out = {"net": net, "target": target, "rows": rows, "diverged": diverged, "diverged_epoch": div_epoch, "best_epoch": best["epoch"], "epochs_run": len(rows),
           "epochs_to_target": reached, "seconds": time.time() - t_all, "first_loss": first, "lr": lr}
    if not diverged:
        vl, pm = evaluate()
        out["final"] = {"val_loss": vl, "pred_m": pm, "val_median_rel_err": median_rel(pm, dva), "val_within20": float(np.mean(np.abs(pm - dva) / dva <= 0.2))}
    return out


# ------------------------------------------------------------------ the damping picture of momentum
def heavy_ball(eta, lam, mu, steps=200, x0=1.0):
    """Heavy-ball iteration on the loss lam x^2 / 2:  v <- mu v - eta lam x;  x <- x + v.  -> the losses (lam x^2 / 2) of steps 0 .. steps."""
    x, v = float(x0), 0.0
    out = [0.5 * lam * x * x]
    for _ in range(int(steps)):
        v = mu * v - eta * lam * x
        x = x + v
        out.append(0.5 * lam * x * x)
    return np.array(out)


def damping_regime(eta, lam, mu):
    """-> {"regime": "unstable" | "underdamped" | "overdamped" | "critical", "roots": the two roots of z^2 - (1 + mu - eta lam) z + mu = 0, "stable"}.
    Stable when 0 < eta lam < 2 (1 + mu); underdamped (the loss oscillates, the roots are complex) when (1 + mu - eta lam)^2 < 4 mu; overdamped (a slow creep) when it is above."""
    s = 1.0 + mu - eta * lam
    roots = np.roots([1.0, -s, mu])
    stable = 0 < eta * lam < 2.0 * (1.0 + mu)
    disc = s * s - 4.0 * mu
    if not stable:
        regime = "unstable"
    elif abs(disc) < 1e-12:
        regime = "critical"
    else:
        regime = "underdamped" if disc < 0 else "overdamped"
    return {"regime": regime, "roots": [complex(r) for r in roots], "stable": bool(stable), "discriminant": float(disc)}
