import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
"""np_net.py, the hand-written network.  The mandatory check first: every gradient of the backpropagation equals the central difference (h = 1e-5, float64) for every activation, every loss and
batch normalisation in training mode, on a tiny network; the check is shown to FAIL when a derivative or the batch-norm backward is made wrong (so a pass means something).  Then the rest:
the parameter counts, the optimisers worked out by hand, batch normalisation (statistics, inference = training on a very large batch), the initialisations, that a rung-0 (1986) network
can overfit 20 rows, that a run that blows up is counted as diverged, early stopping, the diagnostics, the size designer and the damping picture.  numpy only."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
sys.path.insert(0, os.path.join(ADD, "trainer"))
import numpy as np

import np_net as nn

assert "torch" not in sys.modules and "PyQt6" not in sys.modules, "the network must import without torch or Qt"


def ok(msg):
    print("ok:", msg, flush=True)


OFFSETS = np.array([0.03, -0.04, 0.5, -0.7, 0.02, 0.9, 0.04, -0.6, 0.35, -0.02, 0.8, -0.5])       # some inside and some outside the smooth-L1 threshold 0.1


def tiny(act, bn, seed, m=12, init="he"):
    """A 3 -> 4 -> 3 -> 1 network, a fixed batch of m rows and targets that sit at known distances from its first answers."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(m, 3))
    net = nn.MLP(3, [4, 3], act, init, batch_norm=bn, seed=seed)
    y = net.forward(X, update_stats=False)[0] + OFFSETS[:m]
    return net, X, y


def kink_distance(net, X, y, loss, beta):
    """How close the point is to a place where the loss is not smooth: a ReLU pre-activation at 0, a smooth-L1 residual at beta."""
    d = float("inf")
    yh, cache = net.forward(X, update_stats=False)
    if net.activation == "relu":
        d = min(d, min(float(np.abs(u).min()) for u in cache["u"]))
    if loss == "smooth_l1":
        d = min(d, float(np.abs(np.abs(yh - y) - beta).min()))
    return d


# ---------------------------------------------------------------- the mandatory gradient check
worst_seen = {}
for act in nn.ACTIVATIONS:
    for loss in nn.LOSSES:
        for bn in (False, True):
            worst = 0.0
            for seed in range(6):
                net, X, y = tiny(act, bn, seed)
                if kink_distance(net, X, y, loss, 0.1) < 1e-3:                       # (stay further from a kink than h: a check across a kink is meaningless)
                    continue
                r = nn.gradient_check(net, X, y, loss, 0.1, richardson=bn)
                worst = max(worst, r["max_rel"])
                tol = 1e-4 if act == "relu" else 1e-6
                assert r["max_rel"] < tol, (act, loss, bn, seed, r["worst"], r["max_rel"])
            worst_seen[(act, loss, bn)] = worst
assert len(worst_seen) == 16 and all(v < 1e-6 for k, v in worst_seen.items() if k[0] != "relu")
ok("gradient check, all 4 activations x 2 losses x with and without batch norm (training mode): worst relative error "
   f"{max(v for k, v in worst_seen.items() if k[0] != 'relu'):.1e} (smooth cases, limit 1e-6), ReLU {max(v for k, v in worst_seen.items() if k[0] == 'relu'):.1e} (limit 1e-4)")

net, X, y = tiny("tanh", False, 0)
deep = nn.MLP(3, [5, 4, 3], "tanh", "glorot", seed=4)
r = nn.gradient_check(deep, X, deep.forward(X)[0] + OFFSETS, "mse")
assert r["max_rel"] < 1e-6 and len(r["per_param"]) == 8, r["max_rel"]
dbn = nn.MLP(3, [5, 4, 3], "silu", "glorot", batch_norm=True, seed=4)
r = nn.gradient_check(dbn, X, dbn.forward(X)[0] + OFFSETS, "smooth_l1", richardson=True)
assert r["max_rel"] < 1e-6 and len(r["per_param"]) == 14, r["max_rel"]                  # (4 weights + 4 biases + gamma and beta of 3 hidden layers)
ok("a deeper network (3 hidden layers), with and without batch norm, passes too")

# the bias of a layer with batch normalisation has no gradient at all: the mean that follows takes it away
net, X, y = tiny("tanh", True, 1)
_yh, cache = net.forward(X, update_stats=False)
g = net.backward(cache, nn.loss_value_grad("mse", _yh, y)[1])
assert max(float(np.abs(g["b1"]).max()), float(np.abs(g["b2"]).max())) < 1e-12 and float(np.abs(g["gamma1"]).max()) > 1e-6
ok("with batch normalisation the bias of a hidden layer has a gradient of exactly zero, gamma and beta do not")

# the check can fail: break a derivative, break the batch-norm backward
real = nn.act_deriv
nn.act_deriv = lambda name, a, z: z if name == "tanh" else real(name, a, z)                  # a wrong derivative of tanh
net, X, y = tiny("tanh", False, 0)
assert nn.gradient_check(net, X, y, "mse")["max_rel"] > 1e-2
nn.act_deriv = real
assert nn.gradient_check(net, X, y, "mse")["max_rel"] < 1e-6


class WrongBN(nn.MLP):
    def backward(self, cache, dyhat):
        saved = []
        for l in range(self.L - 1):                                                          # drop the terms that come from the batch mean and variance
            saved.append(cache["xhat"][l])
            cache["xhat"][l] = cache["xhat"][l] * 0.0
        g = super().backward(cache, dyhat)
        for l in range(self.L - 1):
            cache["xhat"][l] = saved[l]
        return g


net = WrongBN(3, [4, 3], "tanh", "he", batch_norm=True, seed=1)
X = np.random.default_rng(1).normal(size=(12, 3))
assert nn.gradient_check(net, X, net.forward(X)[0] + OFFSETS, "mse")["max_rel"] > 1e-2
ok("the same check FAILS (relative error above 1e-2) when the derivative of tanh is wrong or the batch-norm backward is wrong")

# the activations on their own
a = np.linspace(-4, 4, 41) + 0.013
for act in nn.ACTIVATIONS:
    h = 1e-6
    num = (nn.act_forward(act, a + h) - nn.act_forward(act, a - h)) / (2 * h)
    ana = nn.act_deriv(act, a, nn.act_forward(act, a))
    assert np.allclose(num, ana, atol=1e-7), act
assert np.allclose(nn.act_forward("sigmoid", np.array([0.0, 1e4, -1e4])), [0.5, 1.0, 0.0]) and nn.act_forward("relu", np.array([-1.0, 2.0])).tolist() == [0.0, 2.0]
assert abs(float(nn.act_forward("silu", np.array([2.0]))[0]) - 2.0 / (1 + math.exp(-2.0))) < 1e-15
ok("the four activations and their derivatives are right (also for huge inputs, without overflow)")

# the losses
yh, yt = np.array([1.0, 2.0, 4.0]), np.array([1.5, 2.0, 1.0])
lv, g = nn.loss_value_grad("mse", yh, yt)
assert abs(lv - (0.25 + 0 + 9) / 3) < 1e-15 and np.allclose(g, 2 * (yh - yt) / 3)
lv, g = nn.loss_value_grad("smooth_l1", np.array([0.05, -0.3]), np.array([0.0, 0.0]), beta=0.1)
assert abs(lv - (0.5 * 0.05 ** 2 / 0.1 + (0.3 - 0.05)) / 2) < 1e-15 and np.allclose(g, [0.05 / 0.1 / 2, -1.0 / 2])
ok("mean squared error and smooth-L1 (both of its regimes) on hand-worked numbers")

# ---------------------------------------------------------------- the size
assert nn.MLP(6, [32, 16], "tanh").n_params() == 769 == nn.count_params(6, [32, 16]) and nn.count_params(6, [32, 16]) == 224 + 528 + 17
assert nn.MLP(6, [32] * 4, "relu", "he", batch_norm=True).n_params() == 3681 == nn.count_params(6, [32] * 4, True)
hid, n = nn.design_hidden(3681, 4, 1.0, 6, True)
assert hid == [32, 32, 32, 32] and n == 3681
hid, n = nn.design_hidden(769, 2, 0.5, 6, False)
assert hid == [32, 16] and n == 769
hid, n = nn.design_hidden(10000, 3, 0.5, 6)
assert abs(n - 10000) / 10000 < 0.02 and hid[0] > hid[1] > hid[2], (hid, n)
ok("the reference network 6-32-16-1 has 769 parameters (224 + 528 + 17); 4 x 32 with batch norm 3,681; the size designer finds the widths for a number of parameters and a taper")

# ---------------------------------------------------------------- the optimisers, by hand
def with_grads(vals):
    net = nn.MLP(1, [1], "tanh", "glorot", seed=0)
    net.W[0][...], net.b[0][...], net.W[1][...], net.b[1][...] = 1.0, 2.0, -1.0, 0.5
    return net, {"W1": np.full((1, 1), vals[0]), "b1": np.full(1, vals[1]), "W2": np.full((1, 1), vals[2]), "b2": np.full(1, vals[3])}


net, gr = with_grads([0.5, -1.0, 2.0, 0.0])
nn.Optimizer("sgd", 0.1).step(net, gr)
assert np.allclose([net.W[0][0, 0], net.b[0][0], net.W[1][0, 0], net.b[1][0]], [0.95, 2.1, -1.2, 0.5])
net, gr = with_grads([0.5, -1.0, 2.0, 0.0])
opt = nn.Optimizer("sgd", 0.1, momentum=0.9)
opt.step(net, gr)
opt.step(net, gr)
v1 = -0.1 * 0.5
v2 = 0.9 * v1 - 0.1 * 0.5
assert abs(net.W[0][0, 0] - (1.0 + v1 + v2)) < 1e-15
ok("plain gradient descent and heavy-ball momentum take the steps the equations say (theta - eta g; v <- mu v - eta g, theta <- theta + v)")

for kind, wd in (("adam", 0.0), ("adamw", 0.01)):
    net, gr = with_grads([0.5, -1.0, 2.0, 0.0])
    lr, b1, b2, eps = 0.01, 0.9, 0.999, 1e-8
    opt = nn.Optimizer(kind, lr, beta1=b1, beta2=b2, eps=eps, weight_decay=wd)
    th = {"W1": 1.0, "b1": 2.0, "W2": -1.0, "b2": 0.5}
    m, s = {k: 0.0 for k in th}, {k: 0.0 for k in th}
    for t in (1, 2, 3):
        opt.step(net, gr)
        for k in th:
            g = float(gr[k].ravel()[0])
            m[k], s[k] = b1 * m[k] + (1 - b1) * g, b2 * s[k] + (1 - b2) * g * g
            step = lr * (m[k] / (1 - b1 ** t)) / (math.sqrt(s[k] / (1 - b2 ** t)) + eps)
            decay = lr * wd * th[k] if k.startswith("W") else 0.0                   # decoupled decay: on the weights only, from the weights before the step
            th[k] = th[k] - step - decay
    got = {"W1": net.W[0][0, 0], "b1": net.b[0][0], "W2": net.W[1][0, 0], "b2": net.b[1][0]}
    assert all(abs(got[k] - th[k]) < 1e-12 for k in th), (kind, got, th)
net, gr = with_grads([0.5, -1.0, 2.0, 0.0])
o = nn.Optimizer("adam", 0.01)
before = net.W[0][0, 0]
o.step(net, gr)
assert abs((before - net.W[0][0, 0]) - 0.01) < 1e-6, "the first Adam step is eta in the direction of the sign of the gradient"
assert abs(net.b[1][0] - 0.5) < 1e-12, "a zero gradient moves nothing"
ok("Adam and AdamW (bias correction, decoupled weight decay on the weights only) match an independent implementation of the equations over 3 steps")

# ---------------------------------------------------------------- batch normalisation
net = nn.MLP(3, [4, 3], "tanh", "glorot", batch_norm=True, seed=2)
net.gamma[0][...], net.beta[0][...] = 2.0, 0.5
X = np.random.default_rng(5).normal(size=(64, 3)) * [1, 4, 0.2] + [3, -2, 0]
_y, cache = net.forward(X)
assert np.allclose(cache["xhat"][0].mean(0), 0, atol=1e-12) and np.allclose(cache["xhat"][0].var(0), 1, atol=1e-4)
assert np.allclose(cache["u"][0].mean(0), 0.5, atol=1e-12) and np.allclose(cache["u"][0].var(0), 4.0, atol=1e-3)
assert not np.allclose(net.forward(X, train=False)[0], _y), "at the start the running statistics (0, 1) are not the batch's"
assert np.allclose(net.run_mean[0], 0.1 * cache["a"][0].mean(0)), "the running mean moved by momentum 0.1 towards the batch's"
ok("batch norm in training mode makes each feature mean 0 and variance 1, then gamma and beta scale and shift; the running statistics follow the batches with momentum 0.1")

big = np.random.default_rng(6).normal(size=(5000, 3)) * [1, 2, 0.5] + [1, 0, -1]
net = nn.MLP(3, [8, 6], "relu", "he", batch_norm=True, seed=3)
for _ in range(400):
    net.forward(big)
y_train, _c = net.forward(big, train=True, update_stats=False)
y_eval = net.forward(big, train=False)[0]
assert np.abs(y_train - y_eval).max() < 1e-6, np.abs(y_train - y_eval).max()
ok(f"inference mode equals training mode on a very large batch once the running statistics have settled (largest difference {np.abs(y_train - y_eval).max():.1e})")

# ---------------------------------------------------------------- initialisation
rng = np.random.default_rng(0)
W, b = nn.init_weights(rng, 200, 300, "he")
assert abs(W.std() - math.sqrt(2 / 200)) / math.sqrt(2 / 200) < 0.03 and abs(W.mean()) < 0.01 and not b.any()
W, b = nn.init_weights(rng, 200, 300, "glorot")
lim = math.sqrt(6 / 500)
assert W.max() <= lim and W.min() >= -lim and W.max() > 0.98 * lim and not b.any()
W, b = nn.init_weights(rng, 50, 40, "uniform", 0.1)
assert W.max() <= 0.1 and W.min() >= -0.1 and W.max() > 0.09 and b.any() and np.abs(b).max() <= 0.1
a1, a2 = nn.MLP(6, [32, 16], seed=7), nn.MLP(6, [32, 16], seed=7)
assert all(np.array_equal(x, y) for (_n, x), (_m, y) in zip(a1.params(), a2.params())) and not np.array_equal(nn.MLP(6, [32, 16], seed=8).W[0], a1.W[0])
ok("He: standard deviation sqrt(2/n_in), biases 0; Glorot: uniform within sqrt(6/(n_in+n_out)); the 1986 uniform: within +-0.1; the same seed gives the same weights")

# ---------------------------------------------------------------- what the network is asked for
d = np.array([1.0, 5.0, 20.0, 80.0, 0.05])
t20 = nn.Target("d20")
assert np.allclose(t20.encode(d), [0.05, 0.25, 1.0, 3.0, 0.01]) and np.allclose(t20.decode(np.array([0.05, 0.25, 4.0, -1.0])), [1.0, 5.0, 60.0, 0.2])
tl = nn.Target.fit("log_std", np.exp(np.linspace(0, 3, 50)))
assert abs(tl.mean - 1.5) < 1e-9 and np.allclose(tl.decode(tl.encode(np.array([2.0, 7.0]))), [2.0, 7.0])
assert abs(tl.beta_for(0.1) - 0.1 / tl.std) < 1e-15 and nn.Target("d20").beta_for(0.1) == 0.1
ok("the targets: metres / 20 (answers kept in 0.2 - 60 m), the standardised log (round trip exact); the smooth-L1 threshold of 0.1 in log space is rescaled for the standardised one")

# ---------------------------------------------------------------- the ladder
for k in range(9):
    c = nn.rung_config(k)
    assert c["rung"] == k and c["hidden"] == (32, 16) and c["batch"] == 32
r0, r1, r2, r3, r4, r5, r6, r7, r8 = (nn.rung_config(k) for k in range(9))
assert (r0["activation"], r0["init"], r0["target"], r0["loss"], r0["optimizer"], r0["momentum"], r0["batch_norm"]) == ("sigmoid", "uniform", "d20", "mse", "sgd", 0.0, False)
assert r1["activation"] == "tanh" and r2["momentum"] == 0.9 and r3["target"] == "log_std" and r4["loss"] == "smooth_l1"
assert (r5["activation"], r5["init"]) == ("relu", "he") and r6["optimizer"] == "adam" and r7["batch_norm"] and (r8["optimizer"], r8["weight_decay"], r8["early_stopping"], r8["patience"]) == ("adamw", 1e-4, True, 50)
changes = [(a, b) for a, b in zip((r0, r1, r2, r3, r4, r5, r6, r7, r8), (r1, r2, r3, r4, r5, r6, r7, r8, r8)) if a is not b]
for prev, cur in zip((r0, r1, r2, r3, r4, r5, r6, r7), (r1, r2, r3, r4, r5, r6, r7, r8)):
    diff = [k for k in nn.BASE if prev[k] != cur[k]]
    assert 1 <= len(diff) <= 3, (cur["name"], diff)               # one ingredient (momentum 0.9 -> Adam changes the optimiser and drops momentum; ReLU changes activation and init)
assert nn.rung_config(5, activation="silu")["init"] == "glorot" and nn.rung_config(5, init="uniform")["init"] == "uniform" and nn.rung_config(2, momentum=0.99)["momentum"] == 0.99
dm = nn.rung_config("demo_sigmoid", depth=8)
assert dm["hidden"] == (32,) * 8 and nn.rung_config("demo_relu_he")["init"] == "he" and nn.rung_config("demo_bn")["batch_norm"]
assert nn.lr_grid(r0) == nn.LR_GRID and nn.lr_grid(r6) == nn.LR_ADAM and nn.default_lr(r6) == 1e-3 and nn.default_lr(r0) == 0.03
ok("the nine rungs and the three deep-network demos carry the settings of the specification, each differing from the one before in one ingredient")

# ---------------------------------------------------------------- a rung-0 network can overfit 20 rows
rng = np.random.default_rng(0)
X20, d20 = rng.normal(size=(20, 6)), rng.uniform(2, 15, 20)
res = nn.fit(dict(nn.rung_config(0), batch=20), X20, d20, X20, d20, epochs=65000, seed=1, lr=0.15)
rows = res["rows"]
assert not res["diverged"] and rows[-1]["train_loss"] < 1e-5 and rows[-1]["val_median_rel_err"] < 0.01, (rows[-1]["train_loss"], rows[-1]["val_median_rel_err"])
assert rows[9999]["train_loss"] > 0.05 * rows[0]["train_loss"], "there is a long plateau before the network learns"
ok(f"a 1986 network (sigmoid, mean squared error, plain gradient descent, U(-0.1, 0.1)) overfits 20 rows: loss {rows[0]['train_loss']:.3f} -> {rows[-1]['train_loss']:.1e}, "
   f"after a plateau (loss {rows[9999]['train_loss']:.3f} at epoch 10,000)")

# ---------------------------------------------------------------- a run that blows up is counted
hot = nn.fit(dict(nn.rung_config(0), batch=20), X20, d20, X20, d20, epochs=500, seed=1, lr=3.0)
assert hot["diverged"] and hot["diverged_epoch"] is not None and hot["epochs_run"] <= 5 and "final" not in hot
cool = nn.fit(dict(nn.rung_config(6)), X20, d20, X20, d20, epochs=5, seed=1)
assert not cool["diverged"] and cool["diverged_epoch"] is None and cool["epochs_run"] == 5
ok(f"a learning rate that is too high is flagged as diverged (at epoch {hot['diverged_epoch']}) and stops at once; a sensible one is not")

# ---------------------------------------------------------------- a learning curve, the diagnostics, early stopping
rng = np.random.default_rng(1)
D = np.exp(rng.uniform(np.log(2), np.log(20), 700))
feat = lambda d, noise: np.stack([np.log(1.7 * 420 / d) + noise * rng.normal(size=len(d)), 0.3 + 0.1 * np.log(d), rng.normal(size=len(d))], 1)      # noqa: E731
Xa, Xb = feat(D[:500], 0.02), feat(D[500:], 0.02)
Xa, Xb = (Xa - Xa.mean(0)) / Xa.std(0), (Xb - Xa.mean(0)) / Xa.std(0) if False else (Xb - feat(D[:500], 0.02).mean(0)) / feat(D[:500], 0.02).std(0)
run = nn.fit(nn.rung_config(6, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=60, seed=2, lr=0.003)
rowsx = run["rows"]
assert not run["diverged"] and rowsx[-1]["val_median_rel_err"] < 0.10, rowsx[-1]["val_median_rel_err"]
assert rowsx[-1]["train_loss"] < rowsx[0]["train_loss"] and run["final"]["val_median_rel_err"] == rowsx[-1]["val_median_rel_err"]
need = {"epoch", "train_loss", "val_loss", "val_median_rel_err", "val_within20", "lr", "momentum", "epoch_seconds", "grad_norm_1", "grad_norm_3", "update_ratio_1", "weight_norm_2",
        "saturation_1", "dead_2"}
assert need <= set(rowsx[0]), need - set(rowsx[0])
assert all(rowsx[i]["epoch"] == i + 1 for i in range(len(rowsx))) and all(r["grad_norm_1"] > 0 and 0 < r["update_ratio_1"] < 1 for r in rowsx)
assert run["epochs_to_target"] is not None and rowsx[run["epochs_to_target"] - 1]["val_median_rel_err"] <= 0.075 and all(r["val_median_rel_err"] > 0.075 for r in rowsx[:run["epochs_to_target"] - 1])
ok(f"a small Adam network learns a pinhole-like task to {rowsx[-1]['val_median_rel_err'] * 100:.1f}% median error; every quantity of the specification's table is logged each epoch; "
   f"it first reached 7.5% at epoch {run['epochs_to_target']}")

tan = nn.fit(nn.rung_config(1, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=30, seed=3, lr=0.05)
assert tan["rows"][-1]["saturation_1"] >= 0.0 and tan["rows"][-1]["dead_1"] == 0.0
rel = nn.fit(nn.rung_config(5, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=30, seed=3, lr=0.01)
assert rel["rows"][-1]["saturation_1"] == 0.0 and 0.0 <= rel["rows"][-1]["dead_1"] <= 1.0
sig = nn.fit(nn.rung_config(0, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=3, seed=3, lr=0.05)
assert 0.0 <= sig["rows"][-1]["saturation_1"] <= 1.0 and sig["rows"][-1]["dead_1"] == 0.0
ok("saturation is logged for tanh and sigmoid units, dead units for ReLU (and not the other way round)")

seen = []
watched = nn.fit(nn.rung_config(6, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=8, seed=2, lr=0.003, on_epoch=lambda row, rows: seen.append((row["epoch"], len(rows))))
assert seen == [(i, i) for i in range(1, 9)], "on_epoch is called after every epoch, with the row and the rows so far"
assert [r["train_loss"] for r in watched["rows"]] == [r["train_loss"] for r in rowsx[:8]], "watching a run does not change it"
assert all("train_median_rel_err" in r and 0 < r["train_median_rel_err"] < 5 for r in rowsx), "the error on the training boxes is logged beside the validation error"
assert rowsx[-1]["train_median_rel_err"] < 0.10, rowsx[-1]["train_median_rel_err"]
ok("on_epoch is called after each epoch without changing the run, and every row has the median error on the training boxes (the live chart draws both)")

same = nn.fit(nn.rung_config(6, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=8, seed=2, lr=0.003)
assert [r["train_loss"] for r in same["rows"]] == [r["train_loss"] for r in rowsx[:8]], "the same seed gives the same curve"
other = nn.fit(nn.rung_config(6, hidden=(16, 8)), Xa, D[:500], Xb, D[500:], epochs=8, seed=3, lr=0.003)
assert [r["train_loss"] for r in other["rows"]] != [r["train_loss"] for r in same["rows"]]
ok("the same seed gives the same curve to the last digit, another seed another one")

# early stopping keeps the best epoch
noisyX = np.random.default_rng(9).normal(size=(60, 3))
noisyd = np.exp(np.random.default_rng(10).normal(1.5, 0.6, 60))
valX = np.random.default_rng(11).normal(size=(60, 3))
vald = np.exp(np.random.default_rng(12).normal(1.5, 0.6, 60))
es = nn.fit(dict(nn.rung_config(8, hidden=(64, 64)), patience=15, weight_decay=0.0), noisyX, noisyd, valX, vald, epochs=400, seed=4, lr=0.01)
errs = [r["val_median_rel_err"] for r in es["rows"]]
assert es["epochs_run"] < 400 and es["best_epoch"] == int(np.argmin(errs)) + 1 and es["epochs_run"] - es["best_epoch"] == 15, (es["epochs_run"], es["best_epoch"])
assert abs(es["final"]["val_median_rel_err"] - min(errs)) < 1e-12, "the weights of the best epoch are the ones kept"
ok(f"early stopping stops {15} epochs after the best one (epoch {es['best_epoch']} of {es['epochs_run']}) and keeps its weights")

# a network saved as numbers answers the same
back = nn.MLP.from_dict(es["net"].to_dict())
assert np.allclose(back.predict(valX), es["net"].predict(valX), atol=1e-12)
bnn = nn.fit(nn.rung_config(7, hidden=(8, 8)), Xa, D[:500], Xb, D[500:], epochs=6, seed=5)["net"]
assert np.allclose(nn.MLP.from_dict(bnn.to_dict()).predict(Xb), bnn.predict(Xb), atol=1e-12)
ok("a network written out as plain numbers (with batch-norm statistics) answers exactly the same")

# ---------------------------------------------------------------- the damping picture
for mu in (0.0, 0.5, 0.9, 0.99):
    for el in (0.01, 0.1, 0.5, 1.0, 1.9, 2.5, 3.5, 4.0):
        reg = nn.damping_regime(el, 1.0, mu)
        assert reg["stable"] == (0 < el < 2 * (1 + mu))
        rho = max(abs(x) for x in reg["roots"])
        assert (rho < 1 - 1e-12) == reg["stable"], (mu, el, rho)                          # the closed form agrees with the roots of the characteristic equation
        if reg["stable"]:
            steps = min(200000, int(math.ceil(math.log(1e-6) / (2 * math.log(max(rho, 1e-3))))) + 50)       # long enough for rho^(2 steps) = 1e-6
            tr = nn.heavy_ball(el, 1.0, mu, steps=steps)
            assert tr[-1] < tr[0] * 1e-3, (mu, el, tr[-1])
        else:
            tr = nn.heavy_ball(el, 1.0, mu, steps=200)
            assert tr[-1] > tr[0], (mu, el)
        s_ = 1 + mu - el
        if reg["stable"]:
            assert (reg["regime"] == "underdamped") == (s_ * s_ < 4 * mu - 1e-12) or reg["regime"] == "critical"
        r1, r2 = reg["roots"]                                                                # x_t = A r1^t + B r2^t with x_0 = 1 and x_1 = 1 - eta lambda
        if abs(r1 - r2) > 1e-6:
            B = ((1 - el) - r1) / (r2 - r1)
            xs = np.array([((1 - B) * r1 ** t + B * r2 ** t).real for t in range(40)])
            it = nn.heavy_ball(el, 1.0, mu, steps=39)
            assert np.allclose(0.5 * xs ** 2, it, rtol=1e-6, atol=1e-9 * max(1.0, it.max())), (mu, el)
under = nn.heavy_ball(0.1, 1.0, 0.9, 80)
over = nn.heavy_ball(0.1, 1.0, 0.0, 80)
sign_changes = lambda x: int(np.sum(np.diff(np.sign(np.diff(x))) != 0))                          # noqa: E731
assert nn.damping_regime(0.1, 1.0, 0.9)["regime"] == "underdamped" and nn.damping_regime(0.1, 1.0, 0.0)["regime"] == "overdamped"
assert sign_changes(under) > 3 and sign_changes(over) == 0, "underdamped: the loss goes up and down on its way; overdamped: it only creeps down"
assert nn.damping_regime(3.2, 1.0, 0.5)["regime"] == "unstable" and nn.damping_regime(3.0, 1.0, 0.5)["stable"] is False and nn.damping_regime(0.25, 1.0, 0.25)["regime"] == "critical"
ok("the damping picture: stable for 0 < eta lambda < 2 (1 + mu), underdamped (the loss oscillates) when (1 + mu - eta lambda)^2 < 4 mu, overdamped (a slow creep) above, shown by the iteration itself")

print("np net ok", flush=True)
