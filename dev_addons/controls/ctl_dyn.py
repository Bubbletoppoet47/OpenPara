"""ctl_dyn.py - time-domain simulation of a drawn 2-D mechanism with a PID controller (no Qt).  Everything is SI: m, kg, s, N, N*m, rad/s.
Angles in the sketch are in degrees (0 = along +x, 90 = straight up); inside the maths they are radians.

A sketch is plain data (it goes straight into the .opctl file):
    {"parts": [...], "controller": {...}, "run": {...}}
Parts (dicts with "id", "kind", "name"):
    wheel  r, m, x0                          rolls on the ground without slipping (the base)
    cart   m, w, h, x0                       slides along the ground (the base)
    pivot  x, y                              a fixed pin at height y (the base)
    link   parent, at, length, m, angle, k, c, motor     a rod; pinned to its parent at distance `at` along the parent link
                                              (a wheel, cart or pivot: at its centre); angle is the drawn absolute angle
    mass   parent, at, m                     a point mass sitting `at` metres along a link
A part with "motor": {"max": N*m (N for a cart)} is driven by the controller.  Positive command = counter-clockwise torque on the link
(or +x force on a cart); the reaction goes to the parent.

The motion is a tree of rigid bodies, so the equations are written with one coordinate per moving body: the base (wheel angle psi / cart x)
and one absolute angle per link.  M(q) q'' = Q - bias is assembled from analytic Jacobians, and integrated with RK4 while the controller
runs at its own sample rate (zero-order hold, saturating, with anti-windup).
"""
import copy
import math

import numpy as np

G = 9.81
ROOTS = ("wheel", "cart", "pivot")
KIND_WORD = {"wheel": "Wheel", "cart": "Cart", "pivot": "Pivot", "link": "Link", "mass": "Mass"}

DEFAULT_PART = {
    "wheel": dict(r=0.05, m=0.1, x0=0.0, motor=None),
    "cart": dict(m=1.0, w=0.3, h=0.1, x0=0.0, motor=None),
    "pivot": dict(x=0.0, y=0.5),
    "link": dict(parent=None, at=0.0, length=0.3, m=0.2, angle=90.0, k=0.0, c=0.0, motor=None),
    "mass": dict(parent=None, at=0.2, m=0.1),
}
DEFAULT_CTRL = dict(balance=None, kp=1.0, ki=0.0, kd=0.1, pos_on=True, pkp=0.0, pki=0.0, pkd=0.0, tilt_clamp=15.0, rate=200.0,
                    goal=dict(kind="ramp", x=1.0, rate=0.2, t=2.0))
DEFAULT_RUN = dict(duration=10.0, start_tilt=5.0, tilt_limit=45.0, push=dict(on=False, force=2.0, t=4.0, dur=0.1))
GOAL_KINDS = ("hold", "step", "ramp")
MAX_SUBSTEP = 0.002                         # physics step never longer than this (s)


class SketchError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------------------ the sketch as data
def normalize(sk):
    """A complete copy of the sketch: every missing field filled with its default (older files stay readable)."""
    sk = copy.deepcopy(sk) if sk else {}
    sk.setdefault("parts", [])
    out = []
    for p in sk["parts"]:
        if p.get("kind") not in DEFAULT_PART:
            continue
        q = dict(DEFAULT_PART[p["kind"]])
        q.update(p)
        q.setdefault("name", q["id"])
        out.append(q)
    sk["parts"] = out
    c = copy.deepcopy(DEFAULT_CTRL)
    c.update(sk.get("controller") or {})
    g = dict(DEFAULT_CTRL["goal"])
    g.update((sk.get("controller") or {}).get("goal") or {})
    c["goal"] = g
    sk["controller"] = c
    r = copy.deepcopy(DEFAULT_RUN)
    r.update(sk.get("run") or {})
    pu = dict(DEFAULT_RUN["push"])
    pu.update((sk.get("run") or {}).get("push") or {})
    r["push"] = pu
    sk["run"] = r
    return sk


def _name(p):
    return p.get("name") or p["id"]


def part(sk, pid):
    for p in sk["parts"]:
        if p["id"] == pid:
            return p
    return None


def add_part(sk, kind, parent=None):
    """Add a part with sensible defaults (a link continues from the tip of its parent link); returns the new id."""
    kind = kind if kind in DEFAULT_PART else "link"
    ids = {p["id"] for p in sk["parts"]}
    k = 1
    while f"{kind}{k}" in ids:
        k += 1
    pid = f"{kind}{k}"
    same = sum(1 for p in sk["parts"] if p["kind"] == kind)
    p = dict(DEFAULT_PART[kind])
    p.update(id=pid, kind=kind, name=KIND_WORD[kind] + (f" {same + 1}" if same else ""))
    par = part(sk, parent) if parent else None
    if kind == "link":
        p["parent"] = parent
        if par is not None and par["kind"] == "link":
            p["at"] = float(par["length"])
            p["angle"] = float(par["angle"])
        elif par is not None and par["kind"] in ("wheel", "cart", "pivot"):
            p["at"] = 0.0
    elif kind == "mass":
        p["parent"] = parent if par is not None and par["kind"] == "link" else None
        if par is not None and par["kind"] == "link":
            p["at"] = round(0.7 * float(par["length"]), 6)
    sk["parts"].append(p)
    return pid


def remove_part(sk, pid):
    """Remove a part and everything attached to it."""
    gone = {pid}
    grew = True
    while grew:
        grew = False
        for p in sk["parts"]:
            if p.get("parent") in gone and p["id"] not in gone:
                gone.add(p["id"])
                grew = True
    sk["parts"] = [p for p in sk["parts"] if p["id"] not in gone]
    if sk["controller"].get("balance") in gone:
        sk["controller"]["balance"] = None
    return gone


def balance_id(sk):
    """The link the controller keeps upright: the one named in the controller, else the first link standing on the base."""
    links = [p for p in sk["parts"] if p["kind"] == "link"]
    b = sk["controller"].get("balance")
    if b and any(p["id"] == b for p in links):
        return b
    for p in links:
        par = part(sk, p["parent"])
        if par is not None and par["kind"] in ROOTS:
            return p["id"]
    return links[0]["id"] if links else None


# ------------------------------------------------------------------------------------------------------------ checking, in plain words
def check(sk):
    """(errors, warnings): plain sentences.  Errors stop a run; warnings are shown beside the result."""
    sk = normalize(sk)
    errs, warns = [], []
    parts = sk["parts"]
    ids = [p["id"] for p in parts]
    if len(set(ids)) != len(ids):
        errs.append("Two parts share the same id; remove one and add it again.")
    roots = [p for p in parts if p["kind"] in ROOTS]
    if not roots:
        errs.append("Nothing to stand on yet. Add a Wheel, a Cart or a Pivot first.")
    elif len(roots) > 1:
        errs.append("There are %d bases (%s). This version works with one base at a time; delete the extra ones." %
                    (len(roots), ", ".join(_name(r) for r in roots)))
    for p in parts:
        k, nm = p["kind"], _name(p)
        if k == "wheel":
            if not p["r"] > 0:
                errs.append(f'"{nm}" needs a radius above zero.')
            if not p["m"] > 0:
                errs.append(f'"{nm}" needs a mass above zero.')
        elif k == "cart":
            if not p["m"] > 0:
                errs.append(f'"{nm}" needs a mass above zero.')
            if not (p["w"] > 0 and p["h"] > 0):
                errs.append(f'"{nm}" needs a width and a height above zero.')
        elif k == "pivot":
            if p["y"] < 0:
                errs.append(f'"{nm}" is below the ground; give it a height of zero or more.')
        elif k == "link":
            if not p["length"] > 0:
                errs.append(f'"{nm}" needs a length above zero.')
            if p["m"] < 0 or p["k"] < 0 or p["c"] < 0:
                errs.append(f'"{nm}": mass, spring and damper values cannot be negative.')
            par = part(sk, p["parent"]) if p["parent"] else None
            if par is None:
                errs.append(f'"{nm}" is not attached to anything. Select a part and press Link, or choose what it is attached to.')
            elif par["kind"] == "mass":
                errs.append(f'"{nm}" cannot be attached to a mass; attach it to a link, wheel, cart or pivot.')
            elif par["kind"] == "link":
                if p["at"] < -1e-9 or p["at"] > par["length"] + 1e-9:
                    errs.append('"%s" is attached %g m along "%s", but that link is only %g m long.' % (nm, p["at"], _name(par), par["length"]))
        elif k == "mass":
            par = part(sk, p["parent"]) if p["parent"] else None
            if par is None or par["kind"] != "link":
                errs.append(f'The mass "{nm}" has to sit on a link. Select a link and press Mass.')
            elif p["at"] < -1e-9 or p["at"] > par["length"] + 1e-9:
                errs.append('The mass "%s" sits %g m along "%s", but that link is only %g m long.' % (nm, p["at"], _name(par), par["length"]))
            if p["m"] < 0:
                errs.append(f'The mass "{nm}" cannot be negative.')
    for p in parts:                                                                 # every link must reach the base
        if p["kind"] != "link":
            continue
        seen, cur = set(), p
        while cur is not None and cur["kind"] == "link" and cur["id"] not in seen:
            seen.add(cur["id"])
            cur = part(sk, cur["parent"]) if cur["parent"] else None
        if cur is None or cur["kind"] not in ROOTS:
            if not any(_name(p) in e for e in errs):
                errs.append(f'"{_name(p)}" is not connected to the base through its parts.')
    motors = [p for p in parts if p.get("motor")]
    for p in motors:
        if not float(p["motor"].get("max", 0)) > 0:
            errs.append(f'The motor on "{_name(p)}" needs a maximum above zero.')
    if not motors:
        errs.append("Nothing drives the system yet. Tick Motor on the joint you want driven (for the robot: the body link).")
    elif len(motors) > 1:
        errs.append("This version drives one motor with the controller, but %d are switched on (%s). Switch the others off." %
                    (len(motors), ", ".join(_name(p) for p in motors)))
    if not any(p["kind"] == "link" for p in parts):
        errs.append("Add a Link: the controller keeps one link upright.")
    c, r = sk["controller"], sk["run"]
    if not 5 <= float(c["rate"]) <= 2000:
        errs.append("The controller sample rate should be between 5 and 2000 Hz.")
    if not float(r["duration"]) > 0:
        errs.append("The run time has to be above zero.")
    if not 0 < float(r["tilt_limit"]) <= 175:
        errs.append("The fall limit has to be between 0 and 175 degrees.")
    if c["goal"]["kind"] not in GOAL_KINDS:
        errs.append("The goal has to be Fixed point, Step or Ramp.")
    if errs:
        return errs, warns
    try:
        mdl = Model(sk, _checked=True)
    except SketchError as e:
        return [str(e)], warns
    ev = np.linalg.eigvalsh(mdl.mass_matrix(mdl.z0(0.0)[:mdl.n]))
    if ev.min() <= 1e-12 * max(1.0, ev.max()):
        errs.append("Some link has no mass at all, so it has nothing to push against. Give every link a mass, or put a mass on it.")
        return errs, warns
    low = mdl.fail_reason(mdl.z0(0.0))
    if low == "ground":
        errs.append("The drawing starts below the ground. Raise the pivot, or turn the links so nothing is under the floor.")
    if mdl.has_pos is False and c["pos_on"] and (float(c["pkp"]) or float(c["pki"]) or float(c["pkd"])):
        warns.append("A pivot cannot move, so the position gains are ignored.")
    if mdl.motor_part["kind"] == "wheel":
        warns.append("The motor is on the wheel itself, against the ground; to drive a body from the wheel, put the motor on the body link.")
    res = mdl.equilibrium_residual()
    if res > 0.05:
        warns.append("As drawn, the pose is not in balance: with the motor off it would start to move at once, so the controller needs a steady "
                     "torque to hold it. Draw the balancing link exactly straight up (or straight down for a hanging pendulum).")
    return errs, warns


# ------------------------------------------------------------------------------------------------------------ the equations of motion
class Model:
    """The compiled sketch.  n coordinates q: [base (wheel angle psi, or cart x)] + one absolute angle per link, in tree order."""

    def __init__(self, sk, _checked=False):
        sk = normalize(sk)
        if not _checked:
            errs, _ = check(sk)
            if errs:
                raise SketchError(" ".join(errs))
        self.sk = sk
        parts = sk["parts"]
        root = [p for p in parts if p["kind"] in ROOTS][0]
        self.root = root
        links = [p for p in parts if p["kind"] == "link"]
        order, placed, pending = [], {root["id"]}, list(links)
        while pending:
            moved = False
            for p in list(pending):
                if p["parent"] in placed:
                    order.append(p)
                    placed.add(p["id"])
                    pending.remove(p)
                    moved = True
            if not moved:
                raise SketchError("Some links are not connected to the base.")
        has_base_body = root["kind"] in ("wheel", "cart")
        bodies = ([root] if has_base_body else []) + order
        n = len(bodies)
        self.n, self.bodies, self.has_pos = n, bodies, has_base_body
        self.idx = {b["id"]: i for i, b in enumerate(bodies)}
        Aw = np.zeros((n, n))
        Bx = np.zeros((n, n))
        X0, Y0 = np.zeros(n), np.zeros(n)
        W, Wj = np.zeros((n, n)), np.zeros((n, n))
        m, I = np.zeros(n), np.zeros(n)
        # the joint point links on the base hang from: a base-only pose plus how it moves with q
        if root["kind"] == "wheel":
            h_bx, h_x0, h_y = np.zeros(n), float(root["x0"]), float(root["r"])
            h_bx[0] = float(root["r"])
            Aw[0, 0], Bx[0], X0[0], Y0[0] = -1.0, h_bx, h_x0, h_y
            m[0], I[0] = root["m"], 0.5 * root["m"] * root["r"] ** 2
        elif root["kind"] == "cart":
            h_bx, h_x0, h_y = np.zeros(n), 0.0, float(root["h"])
            h_bx[0] = 1.0
            Bx[0], X0[0], Y0[0] = h_bx, 0.0, 0.5 * root["h"]
            m[0], I[0] = root["m"], 0.0
        else:
            h_bx, h_x0, h_y = np.zeros(n), float(root["x"]), float(root["y"])
        self.hinge = (h_bx.copy(), h_x0, h_y)
        pts_w, pts_x0, pts_y0, pts_bx, self.pt_info = [], [], [], [], []
        self.parent_b = {}
        link_geo = {}
        off = 1 if has_base_body else 0
        for j, p in enumerate(order):
            b = off + j
            Aw[b, b] = 1.0
            par = part(sk, p["parent"])
            if par["kind"] == "link":
                pb = self.idx[par["id"]]
                Bx[b], X0[b], Y0[b] = Bx[pb], X0[pb], Y0[pb]
                Wj[b] = Wj[pb]
                Wj[b, pb] += float(p["at"])
                self.parent_b[b] = pb
            else:
                Bx[b], X0[b], Y0[b] = h_bx, h_x0, h_y
                self.parent_b[b] = 0 if has_base_body else -1
            ml, L = float(p["m"]), float(p["length"])
            ms = [q for q in parts if q["kind"] == "mass" and q["parent"] == p["id"]]
            mt = ml + sum(float(q["m"]) for q in ms)
            sc = (ml * L / 2 + sum(float(q["m"]) * float(q["at"]) for q in ms)) / mt if mt > 0 else L / 2
            I[b] = ml * L * L / 12 + ml * (L / 2 - sc) ** 2 + sum(float(q["m"]) * (float(q["at"]) - sc) ** 2 for q in ms)
            m[b] = mt
            W[b] = Wj[b]
            W[b, b] += sc
            link_geo[p["id"]] = (b, L, ms)
            # the points that must stay above the ground: the joint, the tip, every mass
            for tag, s in [("joint", 0.0), ("tip", L)] + [("mass", float(q["at"])) for q in ms]:
                w = Wj[b].copy()
                w[b] += s
                pts_w.append(w)
                pts_x0.append(X0[b])
                pts_y0.append(Y0[b])
                pts_bx.append(Bx[b])
                self.pt_info.append((tag, p["id"]))
        self.Aw, self.Bx, self.X0, self.Y0, self.W, self.Wj, self.m, self.I = Aw, Bx, X0, Y0, W, Wj, m, I
        self.PW = np.array(pts_w).reshape(-1, n)
        self.PX0, self.PY0, self.PBx = np.array(pts_x0), np.array(pts_y0), np.array(pts_bx).reshape(-1, n)
        self.link_geo = link_geo
        # the motor
        mp = [p for p in parts if p.get("motor")]
        self.motor_part = mp[0] if mp else None
        self.tmax = float(self.motor_part["motor"]["max"]) if mp else 0.0
        Qm = np.zeros(n)
        if mp:
            mp0 = self.motor_part
            if mp0["kind"] == "link":
                b = self.idx[mp0["id"]]
                Qm = Aw[b].copy()
                pb = self.parent_b[b]
                if pb >= 0:
                    Qm -= Aw[pb]
            elif mp0["kind"] == "cart":
                Qm = Bx[0].copy()
            elif mp0["kind"] == "wheel":
                Qm = Aw[0].copy()
        self.Qm = Qm
        # joint springs / dampers: relative angle of each link to its parent, resting at the drawn pose
        rows, ks, cs, phi0 = [], [], [], []
        for j, p in enumerate(order):
            if float(p["k"]) > 0 or float(p["c"]) > 0:
                b = off + j
                pb = self.parent_b[b]
                row = Aw[b] - (Aw[pb] if pb >= 0 else 0.0)
                rows.append(row)
                ks.append(float(p["k"]))
                cs.append(float(p["c"]))
                par = part(sk, p["parent"])
                phi0.append(math.radians(float(p["angle"])) - (math.radians(float(par["angle"])) if par["kind"] == "link" else 0.0))
        self.SR = np.array(rows).reshape(-1, n)
        self.SK, self.SC, self.Sphi = np.array(ks), np.array(cs), np.array(phi0)
        # balance link and sensing
        bid = balance_id(sk)
        self.bal = self.idx[bid]
        self.bal_id = bid
        self.ref = math.radians(float(part(sk, bid)["angle"]))
        L = link_geo[bid][1]
        self.tipw = Wj[self.bal].copy()
        self.tipw[self.bal] += L
        self.ct = -Aw[self.bal]                                      # tilt - tilt0 = ct @ (q - q0)  (tilt = ref - angle)
        self.cx = Bx[0].copy() if has_base_body else np.zeros(n)     # root x = X0 + cx @ q
        self.x_base = X0[0] if has_base_body else 0.0
        self._lin = None
        self._pol = None

    # ------------------------------------------------------------------ states
    def z0(self, start_tilt_deg=0.0):
        """The drawn pose at rest, with the balance link started `start_tilt_deg` off it."""
        q = np.zeros(self.n)
        if self.root["kind"] == "cart":
            q[0] = float(self.root["x0"])
        for b in self.bodies:
            if b["kind"] == "link":
                q[self.idx[b["id"]]] = math.radians(float(b["angle"]))
        q[self.bal] -= math.radians(start_tilt_deg)
        return np.concatenate([q, np.zeros(self.n)])

    def angles(self, q):
        return self.Aw @ q

    def tilt(self, z):
        return self.ref - self.Aw[self.bal] @ z[:self.n]

    def sense(self, z):
        """What the controller measures: tilt, tilt rate, base x, base speed (all ideal)."""
        n = self.n
        return (self.ref - self.Aw[self.bal] @ z[:n], -(self.Aw[self.bal] @ z[n:]),
                self.x_base + self.cx @ z[:n], self.cx @ z[n:])

    def points_y(self, q):
        th = self.Aw @ q
        return self.PY0 + self.PW @ np.sin(th)

    def fail_reason(self, z, tilt_limit=None):
        if self.PW.size and (self.points_y(z[:self.n]) < -1e-3).any():
            return "ground"
        if tilt_limit is not None and abs(self.tilt(z)) > math.radians(tilt_limit):
            return "tilt"
        return ""

    # ------------------------------------------------------------------ dynamics
    def _jac(self, q):
        th = self.Aw @ q
        s, c = np.sin(th), np.cos(th)
        Ws, Wc = self.W * s, self.W * c
        return th, s, c, self.Bx - Ws @ self.Aw, Wc @ self.Aw, Ws, Wc

    def mass_matrix(self, q):
        th, s, c, Jx, Jy, Ws, Wc = self._jac(q)
        m, I, Aw = self.m, self.I, self.Aw
        return Jx.T @ (m[:, None] * Jx) + Jy.T @ (m[:, None] * Jy) + Aw.T @ (I[:, None] * Aw)

    def deriv(self, z, u=0.0, push=0.0):
        """z' for z = [q, q'], motor command u (N*m or N) and a sideways push (N) on the tip of the balance link."""
        n = self.n
        q, qd = z[:n], z[n:]
        th, s, c, Jx, Jy, Ws, Wc = self._jac(q)
        m, I, Aw = self.m, self.I, self.Aw
        w = Aw @ qd
        w2 = w * w
        a0x = -(Wc @ w2)
        a0y = -(Ws @ w2)
        M = Jx.T @ (m[:, None] * Jx) + Jy.T @ (m[:, None] * Jy) + Aw.T @ (I[:, None] * Aw)
        rhs = -G * (Jy.T @ m) - Jx.T @ (m * a0x) - Jy.T @ (m * a0y)
        if u:
            rhs = rhs + u * self.Qm
        if self.SR.shape[0]:
            rhs = rhs + self.SR.T @ (-(self.SK * (self.SR @ q - self.Sphi) + self.SC * (self.SR @ qd)))
        if push:
            rhs = rhs + push * (self.Bx[self.bal] - (self.tipw * s) @ Aw)
        qdd = np.linalg.solve(M, rhs)
        return np.concatenate([qd, qdd])

    def step(self, z, u, push, h):
        f = self.deriv
        k1 = f(z, u, push)
        k2 = f(z + 0.5 * h * k1, u, push)
        k3 = f(z + 0.5 * h * k2, u, push)
        k4 = f(z + h * k3, u, push)
        return z + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    def energy(self, z):
        n = self.n
        q, qd = z[:n], z[n:]
        th, s, c, Jx, Jy, Ws, Wc = self._jac(q)
        ke = 0.5 * qd @ self.mass_matrix(q) @ qd
        y = self.Y0 + self.W @ s
        pe = G * float(self.m @ y)
        if self.SR.shape[0]:
            pe += 0.5 * float(np.sum(self.SK * (self.SR @ q - self.Sphi) ** 2))
        return ke + pe

    # ------------------------------------------------------------------ linearisation
    def linear(self):
        """A, B of z' = A (z - z0) + B u at the drawn pose, at rest, by central differences (cached)."""
        if self._lin is None:
            z0 = self.z0(0.0)
            nz = 2 * self.n
            A = np.zeros((nz, nz))
            for j in range(nz):
                e = np.zeros(nz)
                e[j] = 1e-6
                A[:, j] = (self.deriv(z0 + e) - self.deriv(z0 - e)) / 2e-6
            B = ((self.deriv(z0, 1e-6) - self.deriv(z0, -1e-6)) / 2e-6).reshape(-1, 1)
            self._lin = (A, B)
        return self._lin

    def equilibrium_residual(self):
        """Largest acceleration left at the drawn pose with no torque (0 = the drawn pose balances by itself)."""
        d = self.deriv(self.z0(0.0))
        return float(np.max(np.abs(d[self.n:]))) if self.n else 0.0

    def sense_matrix(self):
        """Rows [tilt, tilt rate, x, speed] over z = [q, q']."""
        n = self.n
        C = np.zeros((4, 2 * n))
        C[0, :n] = self.ct
        C[1, n:] = self.ct
        C[2, :n] = self.cx
        C[3, n:] = self.cx
        return C

    def polarity(self, ctrl):
        """+1 or -1: which way the controller's torque must act to stand the balance link up (found from the closed-loop poles of the tilt loop)."""
        if self._pol is not None and self._pol[0] == (ctrl["kp"], ctrl["kd"]):
            return self._pol[1]
        A, B = self.linear()
        C = self.sense_matrix()
        K = -(float(ctrl["kp"]) * C[0] + float(ctrl["kd"]) * C[1])        # u = s * K z  (tilt PD, target zero)
        best, bs = None, 1.0
        for sgn in (1.0, -1.0):
            ev = np.linalg.eigvals(A + sgn * (B @ K.reshape(1, -1)))
            worst = float(np.max(ev.real))
            if best is None or worst < best - 1e-9:
                best, bs = worst, sgn
        self._pol = ((ctrl["kp"], ctrl["kd"]), bs)
        return bs

    # ------------------------------------------------------------------ pictures
    def layout(self, z, ang_only=False):
        """Everything to draw at state z."""
        n = self.n
        q = z[:n]
        th = self.Aw @ q
        xr = self.x_base + self.cx @ q if self.has_pos else self.root["x"]
        wa = th[0] if self.root["kind"] == "wheel" else 0.0
        ang = {b["id"]: float(th[self.idx[b["id"]]]) for b in self.bodies if b["kind"] == "link"}
        return layout(self.sk, ang=ang, xr=float(xr), wa=float(wa))


def _tip(x, y, ang, s):
    return (x + s * math.cos(ang), y + s * math.sin(ang))


def layout(sk, ang=None, xr=None, wa=0.0):
    """Positions of every part at a pose, tolerant of unfinished drawings (an unattached part is drawn flagged, not hidden).
    ang = {link id: absolute angle (rad)}, xr = x of the base, wa = wheel rotation (rad, counter-clockwise)."""
    sk = normalize(sk)
    ang = ang or {}
    shapes = []
    parts = sk["parts"]
    root = next((p for p in parts if p["kind"] in ROOTS), None)
    base = {}                                       # id -> (hinge x, hinge y)
    if root is not None:
        x = float(xr) if xr is not None else float(root.get("x0", root.get("x", 0.0)))
        if root["kind"] == "wheel":
            shapes.append(dict(kind="wheel", id=root["id"], c=(x, root["r"]), r=root["r"], a=wa, ok=True))
            base[root["id"]] = (x, root["r"])
        elif root["kind"] == "cart":
            shapes.append(dict(kind="cart", id=root["id"], c=(x, root["h"] / 2), w=root["w"], h=root["h"], ok=True))
            base[root["id"]] = (x, root["h"])
        else:
            shapes.append(dict(kind="pivot", id=root["id"], c=(root["x"], root["y"]), ok=True))
            base[root["id"]] = (root["x"], root["y"])
    link_start = {}
    todo = [p for p in parts if p["kind"] == "link"]
    for _ in range(len(todo) + 1):
        for p in list(todo):
            par = p["parent"]
            if par in base:
                a0 = float(ang.get(p["id"], math.radians(float(p["angle"]))))
                if par in link_start:
                    pl = part(sk, par)
                    px, py, pa = link_start[par]
                    x0, y0 = _tip(px, py, pa, float(p["at"]))
                else:
                    x0, y0 = base[par]
                link_start[p["id"]] = (x0, y0, a0)
                base[p["id"]] = (x0, y0)
                x1, y1 = _tip(x0, y0, a0, float(p["length"]))
                shapes.append(dict(kind="link", id=p["id"], a=(x0, y0), b=(x1, y1), ok=True, motor=bool(p.get("motor"))))
                todo.remove(p)
    for p in todo:                                  # orphans: drawn at the origin, flagged
        a0 = math.radians(float(p["angle"]))
        x1, y1 = _tip(0.0, 0.0, a0, float(p["length"]))
        shapes.append(dict(kind="link", id=p["id"], a=(0.0, 0.0), b=(x1, y1), ok=False, motor=bool(p.get("motor"))))
        link_start[p["id"]] = (0.0, 0.0, a0)
    bad = {sh["id"] for sh in shapes if sh["kind"] == "link" and not sh["ok"]}
    for p in parts:
        if p["kind"] == "mass":
            if p["parent"] in link_start and p["parent"] not in bad:
                x0, y0, a0 = link_start[p["parent"]]
                c = _tip(x0, y0, a0, float(p["at"]))
                shapes.append(dict(kind="mass", id=p["id"], c=c, m=p["m"], ok=True))
            else:
                shapes.append(dict(kind="mass", id=p["id"], c=(0.0, 0.0), m=p["m"], ok=False))
    return shapes


# ------------------------------------------------------------------------------------------------------------ the goal
def goal_at(ctrl, t, x_start):
    g = ctrl["goal"]
    xg = float(g["x"])
    if g["kind"] == "hold":
        return xg
    if g["kind"] == "step":
        return xg if t >= float(g["t"]) else x_start
    d = xg - x_start                                                # ramp
    if t < float(g["t"]) or d == 0:
        return x_start
    step = abs(float(g["rate"])) * (t - float(g["t"]))
    return x_start + math.copysign(min(abs(d), step), d)


# ------------------------------------------------------------------------------------------------------------ a run
class Result:
    def __init__(self, mdl, sk):
        self.mdl, self.sk = mdl, sk
        self.t, self.z, self.u, self.u_cmd, self.tilt, self.x, self.v, self.goal, self.target = [], [], [], [], [], [], [], [], []
        self.ok, self.reason, self.t_fail, self.stopped = True, "", None, False
        self.duration = float(sk["run"]["duration"])

    def finish(self):
        for k in ("t", "u", "u_cmd", "tilt", "x", "v", "goal", "target"):
            setattr(self, k, np.array(getattr(self, k)))
        self.z = np.array(self.z)
        self.n = len(self.t)
        return self

    def max_tilt_deg(self):
        return float(np.degrees(np.max(np.abs(self.tilt)))) if self.n else 0.0

    def saturated_share(self):
        tm = self.mdl.tmax
        return float(np.mean(np.abs(self.u_cmd) >= tm)) if self.n and tm > 0 else 0.0

    def final_error(self):
        return float(self.x[-1] - self.goal[-1]) if self.n else 0.0

    def summary(self):
        """A few plain sentences about the run."""
        mdl = self.mdl
        out = []
        unit = "N" if mdl.motor_part["kind"] == "cart" else "N·m"
        if self.stopped:
            out.append("Stopped at %.1f s, before the end of the run." % self.t[-1])
        elif self.ok:
            out.append("Held its balance for the whole %.1f s." % self.t[-1])
        elif self.reason == "tilt":
            out.append("Fell over after %.2f s: the tilt passed %g°." % (self.t_fail, float(self.sk["run"]["tilt_limit"])))
        else:
            out.append("Hit the ground after %.2f s." % self.t_fail)
        out.append("Largest tilt %.1f°." % self.max_tilt_deg())
        out.append("Peak motor effort %.3g of %.3g %s%s." % (float(np.max(np.abs(self.u))) if self.n else 0.0, mdl.tmax, unit,
                   (", at its limit %.0f %% of the time" % (100 * self.saturated_share())) if self.saturated_share() > 0.005 else ""))
        if self.ok and not self.stopped and mdl.has_pos and self.sk["controller"]["pos_on"]:
            out.append("At the end the base was %.3f m %s the goal." % (abs(self.final_error()), "past" if self.final_error() > 0 else "short of"))
        return " ".join(out)


def simulate(sk, progress=None, stop=None):
    """Run the controller on the sketch.  Returns a Result (check(sk) first: this raises SketchError on a bad drawing)."""
    sk = normalize(sk)
    mdl = Model(sk)
    c, r = sk["controller"], sk["run"]
    dtc = 1.0 / float(c["rate"])
    sub = max(1, int(math.ceil(dtc / MAX_SUBSTEP - 1e-9)))
    h = dtc / sub
    N = int(round(float(r["duration"]) / dtc))
    pol = mdl.polarity(c)
    z = mdl.z0(float(r["start_tilt"]))
    kp, ki, kd = float(c["kp"]), float(c["ki"]), float(c["kd"])
    pkp, pki, pkd = float(c["pkp"]), float(c["pki"]), float(c["pkd"])
    use_pos = bool(c["pos_on"]) and mdl.has_pos
    clamp = math.radians(float(c["tilt_clamp"]))
    tmax = mdl.tmax
    x_start = mdl.sense(z)[2]
    push = r["push"]
    res = Result(mdl, sk)
    it = ix = 0.0
    limit = float(r["tilt_limit"])
    for k in range(N + 1):
        t = k * dtc
        tilt, trate, x, v = mdl.sense(z)
        xg = goal_at(c, t, x_start)
        if use_pos:
            tt_raw = pkp * (xg - x) + pki * ix + pkd * (-v)
            tt = max(-clamp, min(clamp, tt_raw))
            if abs(tt_raw) <= clamp:
                ix += (xg - x) * dtc
        else:
            tt = 0.0
        e = tt - tilt
        u_raw = pol * (kp * e + ki * it + kd * (-trate))
        u = max(-tmax, min(tmax, u_raw))
        if abs(u_raw) <= tmax:
            it += e * dtc
        res.t.append(t)
        res.z.append(z)
        res.u.append(u)
        res.u_cmd.append(u_raw)                                      # what the controller asked for, before the motor limit
        res.tilt.append(tilt)
        res.x.append(x)
        res.v.append(v)
        res.goal.append(xg)
        res.target.append(tt)
        if k == N:
            break
        F = float(push["force"]) if push["on"] and float(push["t"]) <= t < float(push["t"]) + float(push["dur"]) else 0.0
        for _ in range(sub):
            z = mdl.step(z, u, F, h)
        if not np.all(np.isfinite(z)):
            res.ok, res.reason, res.t_fail = False, "tilt", t + dtc
            break
        why = mdl.fail_reason(z, limit)
        if why:
            res.ok, res.reason, res.t_fail = False, why, t + dtc
            tilt, trate, x, v = mdl.sense(z)
            res.t.append(t + dtc)
            res.z.append(z)
            res.u.append(u)
            res.u_cmd.append(u_raw)
            res.tilt.append(tilt)
            res.x.append(x)
            res.v.append(v)
            res.goal.append(goal_at(c, t + dtc, x_start))
            res.target.append(tt)
            break
        if progress and k % 50 == 0:
            progress(k / N)
        if stop and stop():
            res.stopped = True
            break
    return res.finish()


# ------------------------------------------------------------------------------------------------------------ transfer function and gains
def _cancel(zeros, poles, tol=1e-5):
    zeros, poles = list(zeros), list(poles)
    for zz in list(zeros):
        for pp in poles:
            if abs(zz - pp) <= tol * (1.0 + abs(zz)):
                zeros.remove(zz)
                poles.remove(pp)
                break
    return zeros, poles


def _tidy(v, digits=10):
    """Round numerical noise away: 21.581999998 -> 21.582, 8.9e-16 -> 0."""
    v = np.asarray(v, dtype=float)
    top = float(np.max(np.abs(v))) if v.size else 0.0
    v = np.where(np.abs(v) < 1e-9 * max(top, 1e-300), 0.0, v)
    return [float(f"{x:.{digits}g}") for x in v]


def plant_tf(sk, output="tilt"):
    """The plant G(s) from the motor command to the tilt (or to the base x), with matching pole-zero pairs cancelled.
    Returns dict(num, den, zeros, poles, gain, unstable)."""
    import warnings
    import scipy.signal as sg
    mdl = Model(sk)
    A, B = mdl.linear()
    C = mdl.sense_matrix()
    row = C[0] if output == "tilt" else C[2]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        num, den = sg.ss2tf(A, B, row.reshape(1, -1), np.zeros((1, 1)))
        z, p, k = sg.tf2zpk(np.trim_zeros(_tidy(num[0], 12), "f") or [0.0], _tidy(den, 12))
        z, p = _cancel(list(z), list(p), 1e-4)
        nn, dd = sg.zpk2tf(z, p, k)
    return dict(num=_tidy(np.real(nn)), den=_tidy(np.real(dd)), zeros=[complex(v) for v in z], poles=[complex(v) for v in p],
                gain=float(np.real(k)), unstable=any(v.real > 1e-7 for v in p))


def suggest_gains(sk, speed=1.0):
    """PID gains for the cascade from an LQR design on the linearised model (one balancing link, with or without a position loop).
    Returns dict(kp, ki, kd, pkp, pki, pkd) plus a note; raises SketchError with a plain reason when it can't."""
    import scipy.linalg as sl
    mdl = Model(sk)
    n = mdl.n
    if n not in (1, 2) or (n == 2 and not mdl.has_pos):
        raise SketchError("Suggest gains works for one balancing link on a wheel, a cart or a pivot. This drawing has %d moving joints; "
                          "set the gains by hand." % n)
    if mdl.equilibrium_residual() > 0.05:
        raise SketchError("The drawn pose is not in balance, so there is nothing to linearise around. Draw the balancing link straight up or down.")
    A, B = mdl.linear()
    C = mdl.sense_matrix()
    tmax = max(mdl.tmax, 1e-9)
    if mdl.has_pos:
        T = C[[2, 0, 3, 1]]                                         # [x, tilt, v, tilt rate]
        Q = np.diag([1.0 / 0.5 ** 2, 1.0 / 0.1 ** 2, 1.0 / 1.0 ** 2, 1.0 / 1.0 ** 2]) * speed
    else:
        T = C[[0, 1]][:, :2 * n]
        Q = np.diag([1.0 / 0.1 ** 2, 1.0 / 1.0 ** 2]) * speed
    if np.linalg.matrix_rank(T) < T.shape[0]:
        raise SketchError("The drawing is not controllable from its one motor in this form; set the gains by hand.")
    Ti = np.linalg.inv(T)
    At, Bt = T @ A @ Ti, T @ B
    R = np.array([[1.0 / (0.5 * tmax) ** 2]])
    try:
        P = sl.solve_continuous_are(At, Bt, Q, R)
    except Exception:                                               # noqa: BLE001
        raise SketchError("No stabilising gains exist for this drawing with its one motor (it may be too weak or the wrong shape).")
    K = (np.linalg.solve(R, Bt.T @ P)).ravel()
    if mdl.has_pos:
        kx, kth, kv, kw = K
        s = 1.0 if kth >= 0 else -1.0
        out = dict(kp=abs(kth), ki=0.0, kd=s * kw, pkp=kx / kth, pki=0.0, pkd=kv / kth)
    else:
        kth, kw = K
        s = 1.0 if kth >= 0 else -1.0
        out = dict(kp=abs(kth), ki=0.0, kd=s * kw, pkp=0.0, pki=0.0, pkd=0.0)
    out["polarity"] = s
    return out


def apply_gains(sk, gains, digits=3):
    """Write suggested gains into the sketch's controller, rounded for display."""
    c = sk["controller"]
    for k in ("kp", "ki", "kd", "pkp", "pki", "pkd"):
        v = float(gains[k])
        c[k] = float(f"{v:.{digits}g}") if v else 0.0


# ------------------------------------------------------------------------------------------------------------ examples
def _finish(sk):
    sk = normalize(sk)
    try:
        apply_gains(sk, suggest_gains(sk))
    except SketchError:
        pass
    return sk


def example_robot():
    """Two-wheeled-style self-balancing robot seen from the side: one wheel, a body link with a battery on it."""
    sk = dict(parts=[
        dict(id="wheel", kind="wheel", name="Wheel", r=0.05, m=0.1, x0=0.0, motor=None),
        dict(id="body", kind="link", name="Body", parent="wheel", at=0.0, length=0.30, m=0.2, angle=90.0, motor=dict(max=1.0)),
        dict(id="battery", kind="mass", name="Battery", parent="body", at=0.25, m=0.3),
    ], controller=dict(balance="body", goal=dict(kind="ramp", x=1.0, rate=0.2, t=2.0)), run=dict(duration=10.0, start_tilt=5.0))
    return _finish(sk)


def example_cartpole():
    sk = dict(parts=[
        dict(id="cart", kind="cart", name="Cart", m=1.0, w=0.3, h=0.1, x0=0.0, motor=dict(max=20.0)),
        dict(id="pole", kind="link", name="Pole", parent="cart", at=0.0, length=0.5, m=0.1, angle=90.0),
    ], controller=dict(balance="pole", goal=dict(kind="ramp", x=0.5, rate=0.1, t=2.0)), run=dict(duration=10.0, start_tilt=5.0))
    return _finish(sk)


def example_pendulum_up():
    sk = dict(parts=[
        dict(id="pivot", kind="pivot", name="Pivot", x=0.0, y=0.6),
        dict(id="arm", kind="link", name="Arm", parent="pivot", at=0.0, length=0.5, m=0.3, angle=90.0, motor=dict(max=3.0)),
    ], controller=dict(balance="arm", pos_on=False), run=dict(duration=8.0, start_tilt=8.0))
    return _finish(sk)


def example_pendulum_down():
    sk = dict(parts=[
        dict(id="pivot", kind="pivot", name="Pivot", x=0.0, y=0.7),
        dict(id="arm", kind="link", name="Arm", parent="pivot", at=0.0, length=0.5, m=0.3, angle=-90.0, motor=dict(max=2.0)),
    ], controller=dict(balance="arm", pos_on=False), run=dict(duration=8.0, start_tilt=20.0))
    return _finish(sk)


EXAMPLES = (("Self-balancing robot (wheel + body)", example_robot), ("Cart and pole", example_cartpole),
            ("Inverted pendulum on a pivot", example_pendulum_up), ("Hanging pendulum (motor damps the swing)", example_pendulum_down))
