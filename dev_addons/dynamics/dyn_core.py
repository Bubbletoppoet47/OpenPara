"""dyn_core.py - the solver of the System dynamics add-on: lumped mechanical networks (translational AND rotational) turned into a linear
state-space model, its equations as text, its modes and its time response.  No Qt in here, so it can be tested on its own.

The method (mobility analogy: force = current, velocity = voltage - the same bookkeeping as the circuit solver):
  * every pin net is a *node* that has a velocity (translational, m/s) or an angular velocity (rotational, rad/s);
  * a fixed wall / frame pins its node to zero velocity; a gear pair, lever or rack-and-pinion forces a fixed ratio between two nodes.
    These ideal constraints are removed first: every node velocity becomes   v_node = T_node . u   where u are the independent velocities;
  * masses and inertias at nodes give the mass matrix M, dampers give D, springs and the linearised gravity of a link give K:
        M q'' + D q' + K q = Tm' (N Kt i) + sum of source forces / torques                       (q' = u)
  * a DC motor with gearbox adds its current i:   L di/dt = V - R i - Ke N (Tm . u),  its rotor inertia / friction reflected by N^2.
The state is  x = [q ; u ; motor currents] and the model  x' = A x + B s,  where s are the source amplitudes.
"""
import math

import numpy as np

GROUND = "G"
G_ACCEL = 9.80665

TRANSLATIONAL, ROTATIONAL = "t", "r"


class DynError(Exception):
    """A problem with the drawn system, in words for the person at the window."""


# --------------------------------------------------------------------------------------------------- the network
class Elem:
    def __init__(self, kind, name, nodes, p):
        self.kind, self.name, self.nodes, self.p = kind, name, list(nodes), dict(p)


class Net:
    """A list of elements; nodes are any hashable names."""

    def __init__(self):
        self.elems = []

    def add(self, kind, name, nodes, **p):
        self.elems.append(Elem(kind, name, nodes, p))


# source waveforms --------------------------------------------------------------------------------
WAVES = ("step", "sine", "square", "ramp", "pulse", "off")


def wave_value(p, t):
    """The source's amplitude at time t (array).  p: amp, wave, freq, delay, width."""
    amp = float(p.get("amp", 0.0))
    w = p.get("wave", "step")
    t = np.asarray(t, float)
    d = float(p.get("delay", 0.0))
    f = float(p.get("freq", 1.0))
    if w == "off":
        return np.zeros_like(t)
    if w == "step":
        return amp * (t >= d)
    if w == "ramp":
        return amp * np.maximum(t - d, 0.0)
    if w == "sine":
        return amp * np.sin(2 * math.pi * f * np.maximum(t - d, 0.0)) * (t >= d)
    if w == "square":
        return amp * np.where(t >= d, np.where(np.mod((t - d) * f, 1.0) < 0.5, 1.0, -1.0), 0.0)
    if w == "pulse":
        width = float(p.get("width", 0.1))
        return amp * ((t >= d) & (t < d + width))
    return np.zeros_like(t)


# --------------------------------------------------------------------------------------------------- the model
class System:
    """A solved network.  Attributes:
        coords      list of dicts(name, domain, node, label)  - the independent coordinates q
        M, D, K     nq x nq matrices
        T           {node: row vector (nq)} so that velocity(node) = T[node] . u
        inputs      list of dicts(name, kind, p, node) - the sources, in the order of the columns of B
        motors      list of motor dicts
        A, B        state matrices; x = [q; u; i...]
        state_names list of nx names
    """

    def __init__(self):
        self.coords, self.inputs, self.motors = [], [], []
        self.warnings = []

    # -- outputs --------------------------------------------------------------------------------
    def output(self, node, quantity):
        """(C row, D row) for quantity 'position' | 'velocity' | 'acceleration' of a node."""
        nq, nx = len(self.coords), self.A.shape[0]
        t = self.T.get(node)
        if t is None:
            raise DynError(f"{node} is not a moving part of this system")
        C = np.zeros(nx)
        Dr = np.zeros(self.B.shape[1])
        if quantity == "position":
            C[:nq] = t
        elif quantity == "velocity":
            C[nq:2 * nq] = t
        elif quantity == "acceleration":
            C = t @ self.A[nq:2 * nq, :]
            Dr = t @ self.B[nq:2 * nq, :]
        else:
            raise DynError(f"unknown quantity {quantity}")
        return C, Dr

    def poles(self):
        return np.linalg.eigvals(self.A)

    def gain(self, i_in, node, quantity, s):
        """G(s) from source number i_in to the quantity of a node, at the complex frequency s (scalar or array)."""
        C, Dr = self.output(node, quantity)
        b = self.B[:, i_in]
        I = np.eye(self.A.shape[0])
        s = np.atleast_1d(np.asarray(s, complex))
        out = np.empty(len(s), complex)
        for k, sk in enumerate(s):
            out[k] = C @ np.linalg.solve(sk * I - self.A, b) + Dr[i_in]
        return out

    def dc_gain(self, i_in, node, quantity):
        C, Dr = self.output(node, quantity)
        try:
            x = np.linalg.solve(-self.A, self.B[:, i_in])
        except np.linalg.LinAlgError:
            return math.inf
        return float(C @ x + Dr[i_in])

    def modes(self):
        """Poles grouped as modes: list of dicts(pole, wn, zeta, wd, kind) sorted by |pole|.  Complex pairs appear once."""
        out = []
        for p in sorted(self.poles(), key=lambda z: (abs(z), -z.imag)):
            if abs(p.imag) < 1e-9 * max(1.0, abs(p)):
                out.append({"pole": complex(p.real, 0.0), "wn": abs(p.real), "zeta": 1.0 if p.real < 0 else (-1.0 if p.real > 0 else 0.0),
                            "wd": 0.0, "kind": "real"})
            elif p.imag > 0:
                wn = abs(p)
                out.append({"pole": complex(p), "wn": wn, "zeta": -p.real / wn, "wd": p.imag, "kind": "pair"})
        return out

    def stable(self):
        return bool(np.all(self.poles().real < -1e-9))

    def undamped(self):
        """Natural frequencies (rad/s) of M q'' + K q = 0 (negative stiffness gives an imaginary frequency, shown as a negative number)."""
        if not len(self.coords):
            return np.zeros(0)
        w2 = np.sort(np.real(np.linalg.eigvals(np.linalg.solve(self.M, self.K))))
        return np.array([math.sqrt(x) if x >= 0 else -math.sqrt(-x) for x in w2])


def _expm(Amat):
    """Matrix exponential by scaling and squaring with a Taylor series (numpy only)."""
    n = Amat.shape[0]
    nrm = np.linalg.norm(Amat, 1)
    s = max(0, int(math.ceil(math.log2(nrm / 0.5))) + 1) if nrm > 0.5 else 0
    X = Amat / (2 ** s)
    R = np.eye(n)
    term = np.eye(n)
    for k in range(1, 22):
        term = term @ X / k
        R = R + term
    for _ in range(s):
        R = R @ R
    return R


def build(net):
    """Network -> System.  Raises DynError with a plain-words reason."""
    sysm = System()
    # --- nodes and their domains ---------------------------------------------------------------------------
    node_dom = {}

    def dom(n, d, who):
        if node_dom.setdefault(n, d) != d:
            raise DynError(f"{who} joins a translational and a rotational part on one node - use a rack and pinion to go between them.")

    DOMS = {"MASS": "t", "SPRING": "t", "DAMPER": "t", "FORCE": "t", "WALL": "t", "LEVER": "t",
            "INERTIA": "r", "TSPRING": "r", "RDAMPER": "r", "TORQUE": "r", "FRAME": "r", "LINK": "r", "GEAR": "r", "MOTOR": "r"}
    for e in net.elems:
        if e.kind == "RACK":
            dom(e.nodes[0], "r", e.name)
            dom(e.nodes[1], "t", e.name)
        else:
            for n in e.nodes:
                dom(n, DOMS[e.kind], e.name)

    # --- ideal constraints: v_b = r v_a --------------------------------------------------------------------
    parent = {n: None for n in node_dom}
    parent[GROUND] = None

    def find(n):
        if n == GROUND:
            return GROUND, 1.0
        pr = parent[n]
        if pr is None:
            return n, 1.0
        r, s = find(pr[0])
        res = (r, pr[1] * s)
        parent[n] = res
        return res

    def lock(root):
        if root != GROUND:
            parent[root] = (GROUND, 0.0)

    def tie(a, b, r):
        ra, sa = find(a)
        rb, sb = find(b)
        tol = 1e-12
        if ra == rb:
            if ra != GROUND and abs(sb - r * sa) > tol * max(1.0, abs(sb)):
                lock(ra)
        elif rb == GROUND or abs(sb) < tol:
            if abs(r * sa) > tol:
                lock(ra)
        elif ra == GROUND or abs(sa) < tol or abs(r) < tol:
            lock(rb)
        else:
            parent[rb] = (ra, r * sa / sb)

    for e in net.elems:
        k = e.kind
        if k in ("WALL", "FRAME"):
            lock(find(e.nodes[0])[0])
        elif k == "GEAR":
            if abs(e.p["ratio"]) < 1e-12:
                raise DynError(f"{e.name}: the gear ratio cannot be zero.")
            tie(e.nodes[0], e.nodes[1], 1.0 / e.p["ratio"])
        elif k == "LEVER":
            tie(e.nodes[0], e.nodes[1], e.p["ratio"])
        elif k == "RACK":
            tie(e.nodes[0], e.nodes[1], e.p["r"])

    roots = []
    for n in node_dom:
        r, s = find(n)
        if r != GROUND and abs(s) > 1e-12 and r not in roots:
            roots.append(r)
    nq = len(roots)
    col = {r: i for i, r in enumerate(roots)}
    T = {}
    for n in node_dom:
        r, s = find(n)
        t = np.zeros(nq)
        if r != GROUND and abs(s) > 1e-12:
            t[col[r]] = s
        T[n] = t
    sysm.T = T
    sysm.node_dom = node_dom

    # --- matrices ------------------------------------------------------------------------------------------
    M = np.zeros((nq, nq))
    D = np.zeros((nq, nq))
    K = np.zeros((nq, nq))
    named = {i: [] for i in range(nq)}                     # parts that carry inertia on each coordinate (for the names)
    motors = []
    inputs = []

    def outer(t):
        return np.outer(t, t)

    for e in net.elems:
        k, p = e.kind, e.p
        t0 = T[e.nodes[0]]
        if k in ("MASS", "INERTIA"):
            m = p["m"] if k == "MASS" else p["j"]
            if m <= 0:
                raise DynError(f"{e.name}: the {'mass' if k == 'MASS' else 'inertia'} must be positive.")
            M += m * outer(t0)
            for i in np.nonzero(t0)[0]:
                named[i].append(e.name)
        elif k == "LINK":
            jp = p["jcm"] + p["m"] * p["l"] ** 2
            if jp <= 0:
                raise DynError(f"{e.name}: the link has no inertia - give it a mass or an inertia.")
            M += jp * outer(t0)
            K += p["m"] * G_ACCEL * p["l"] * math.cos(math.radians(p["pose"])) * outer(t0)
            if p["m"] * p["l"] * math.cos(math.radians(p["pose"])) < -1e-12:
                sysm.warnings.append(f"{e.name}: the link is above its pivot (pose beyond 90°), so gravity makes it unstable (it falls over).")
            for i in np.nonzero(t0)[0]:
                named[i].append(e.name)
        elif k in ("SPRING", "TSPRING"):
            t = t0 - T[e.nodes[1]]
            K += p["k"] * outer(t)
        elif k in ("DAMPER", "RDAMPER"):
            t = t0 - T[e.nodes[1]]
            D += p["c"] * outer(t)
        elif k == "MOTOR":
            n_g = p["n"]
            if abs(n_g) < 1e-12:
                raise DynError(f"{e.name}: the gear ratio cannot be zero.")
            M += (n_g ** 2) * p["jm"] * outer(t0)
            D += (n_g ** 2) * p["bm"] * outer(t0)
            if p["r"] <= 0:
                raise DynError(f"{e.name}: the winding resistance must be positive.")
            motors.append(e)
            for i in np.nonzero(t0)[0]:
                named[i].append(e.name)
        elif k in ("FORCE", "TORQUE"):
            inputs.append({"name": e.name, "kind": k, "p": p, "node": e.nodes[0], "elem": e})
    for e in motors:
        inputs.append({"name": e.name, "kind": "MOTOR", "p": {"amp": e.p["v"], "wave": e.p.get("wave", "step"), "freq": e.p.get("freq", 1.0),
                                                              "delay": e.p.get("delay", 0.0), "width": e.p.get("width", 0.1)},
                       "node": e.nodes[0], "elem": e})

    # --- coordinates need inertia ---------------------------------------------------------------------------
    inv_name = {}
    for r in roots:
        inv_name[r] = r
    for i, r in enumerate(roots):
        if M[i, i] <= 1e-300:
            owner = [n for n in node_dom if abs(T[n][i]) > 1e-12]
            elems = sorted({el.name for el in net.elems for n in el.nodes if n in owner})
            raise DynError("Some part has no mass or inertia to move: add a mass / inertia on the same node as "
                           + ", ".join(elems[:4]) + ".")
    # coordinate names
    for i, r in enumerate(roots):
        d = node_dom[r]
        who = named[i][0] if named[i] else str(r)
        sysm.coords.append({"name": ("x_" if d == "t" else "θ_") + who, "domain": d, "node": r, "label": who})

    # --- motors: electrical states or the L = 0 shortcut ---------------------------------------------------
    ne = sum(1 for e in motors if e.p["l"] > 0)
    nx = 2 * nq + ne
    A = np.zeros((nx, nx))
    nin = len(inputs)
    B = np.zeros((nx, nin))
    Minv = np.linalg.inv(M) if nq else np.zeros((0, 0))
    A[:nq, nq:2 * nq] = np.eye(nq)
    Deff = D.copy()
    Bu = np.zeros((nq, nin))
    for j, s in enumerate(inputs):
        if s["kind"] in ("FORCE", "TORQUE"):
            Bu[:, j] = T[s["node"]]
    ecol = 2 * nq
    state_names = [c["name"] for c in sysm.coords] + [c["name"] + "'" for c in sysm.coords]
    for e in motors:
        j = [i for i, s in enumerate(inputs) if s["elem"] is e][0]
        tm = T[e.nodes[0]]
        n_g, kt, ke, r_w, l_w = e.p["n"], e.p["kt"], e.p["ke"], e.p["r"], e.p["l"]
        if l_w > 0:
            # M u' += n kt i tm ;  L i' = V - R i - ke n tm.u
            A[nq:2 * nq, ecol] = Minv @ (n_g * kt * tm)
            A[ecol, nq:2 * nq] = -ke * n_g * tm / l_w
            A[ecol, ecol] = -r_w / l_w
            B[ecol, j] = 1.0 / l_w
            state_names.append("i_" + e.name)
            ecol += 1
        else:
            Deff += (n_g * kt) * (ke * n_g) / r_w * outer(tm)
            Bu[:, j] = tm * n_g * kt / r_w
    A[nq:2 * nq, :nq] = -Minv @ K
    A[nq:2 * nq, nq:2 * nq] = -Minv @ Deff
    for j in range(nin):
        B[nq:2 * nq, j] += Minv @ Bu[:, j]
    sysm.M, sysm.D, sysm.K, sysm.Deff = M, D, K, Deff
    sysm.A, sysm.B, sysm.inputs, sysm.motors = A, B, inputs, motors
    sysm.state_names = state_names
    sysm.roots = roots
    sysm.net = net
    return sysm


# --------------------------------------------------------------------------------------------------- time response
def default_horizon(sysm):
    """A sensible run time (s) from the poles: ~5 time constants of the slowest decaying pole, or a few periods of an undamped one."""
    p = sysm.poles()
    if not len(p):
        return 1.0
    sig = [-z.real for z in p if z.real < -1e-9]
    wn = [abs(z) for z in p if abs(z) > 1e-9]
    if sig and not any(z.real > 1e-9 for z in p):
        t = 5.0 / min(sig)
        if any(abs(z.real) <= 1e-9 and abs(z.imag) > 1e-9 for z in p):
            t = max(t, 6 * 2 * math.pi / min(abs(z.imag) for z in p if abs(z.real) <= 1e-9 and abs(z.imag) > 1e-9))
    elif wn:
        t = 8 * 2 * math.pi / min(wn) if min(wn) > 0 else 10.0
        t = min(t, 20.0 * 2 * math.pi / min(wn))
    else:
        t = 10.0
    return float(min(max(t, 1e-3), 1e4))


def simulate(sysm, tend=None, steps=3000, x0=None, sources=None):
    """Time response, exact for inputs that are constant within a step.  -> dict(t, x (nx x n), u (nin x n)).
    sources: optional {input name: param dict} that replaces the wave settings."""
    tend = default_horizon(sysm) if tend is None else float(tend)
    nx, nin = sysm.A.shape[0], sysm.B.shape[1]
    t = np.linspace(0.0, tend, steps + 1)
    dt = t[1] - t[0]
    U = np.zeros((nin, len(t)))
    for j, s in enumerate(sysm.inputs):
        p = dict(s["p"])
        if sources and s["name"] in sources:
            p.update(sources[s["name"]])
        U[j] = wave_value(p, t + 0.0)
        # evaluate at the start of each step; the step source's edge is then within one dt of the true time
    big = np.zeros((nx + nin, nx + nin))
    big[:nx, :nx] = sysm.A * dt
    big[:nx, nx:] = sysm.B * dt
    E = _expm(big)
    Ad, Bd = E[:nx, :nx], E[:nx, nx:]
    X = np.zeros((nx, len(t)))
    x = np.zeros(nx) if x0 is None else np.asarray(x0, float)
    X[:, 0] = x
    for k in range(len(t) - 1):
        x = Ad @ x + Bd @ U[:, k]
        X[:, k + 1] = x
    return {"t": t, "x": X, "u": U}


def response(sysm, run, node, quantity):
    C, Dr = sysm.output(node, quantity)
    return C @ run["x"] + Dr @ run["u"]


# --------------------------------------------------------------------------------------------------- the equations as text
def _num(x):
    if x == 0:
        return "0"
    a = abs(x)
    if 1e-3 <= a < 1e5:
        s = f"{x:.4g}"
    else:
        s = f"{x:.3e}"
    return s


def _lin(terms):
    """[(coef, symbol)] -> '10 x1'' + 2 x1' - 3 x2' (zero terms dropped)."""
    out = ""
    for c, sym in terms:
        if abs(c) < 1e-15:
            continue
        sign = "-" if c < 0 else "+"
        mag = _num(abs(c))
        body = f"{sym}" if mag == "1" else f"{mag} {sym}"
        out += (f" {sign} " if out else ("-" if c < 0 else "")) + body
    return out or "0"


UNITS = {"MASS": "kg", "SPRING": "N/m", "DAMPER": "N·s/m", "INERTIA": "kg·m²", "TSPRING": "N·m/rad", "RDAMPER": "N·m·s/rad"}


def equations_text(sysm):
    """The equations of the drawn system, readable: coordinates, equations of motion, motor equations, state-space matrices and modes."""
    nq = len(sysm.coords)
    L = []
    if not nq:
        return "Nothing to solve yet: add a mass or inertia, connect springs / dampers to it and to a fixed wall or frame."
    L.append("COORDINATES (measured from where the system sits at rest; springs are unstretched there)")
    for c in sysm.coords:
        unit = "m" if c["domain"] == "t" else "rad"
        what = "position" if c["domain"] == "t" else "angle"
        L.append(f"  {c['name']}   {what} of {c['label']} ({unit})")
    L.append("")
    L.append("EQUATIONS OF MOTION   (primes are time derivatives: x' = velocity, x'' = acceleration)")
    syms = [c["name"] for c in sysm.coords]
    rhs_in = []
    for i, c in enumerate(sysm.coords):
        terms = [(sysm.M[i, j], syms[j] + "''") for j in range(nq)]
        terms += [(sysm.Deff[i, j], syms[j] + "'") for j in range(nq)]
        terms += [(sysm.K[i, j], syms[j]) for j in range(nq)]
        rhs = []
        for jn, s in enumerate(sysm.inputs):
            t = sysm.T[s["node"]]
            if s["kind"] in ("FORCE", "TORQUE") and abs(t[i]) > 1e-12:
                rhs.append((t[i], s["name"]))
        for e in sysm.motors:
            if e.p["l"] > 0:
                t = sysm.T[e.nodes[0]]
                if abs(t[i]) > 1e-12:
                    rhs.append((t[i] * e.p["n"] * e.p["kt"], "i_" + e.name))
            else:
                t = sysm.T[e.nodes[0]]
                if abs(t[i]) > 1e-12:
                    rhs.append((t[i] * e.p["n"] * e.p["kt"] / e.p["r"], e.name + "_V"))
        L.append(f"  {c['label']}:  {_lin(terms)} = {_lin(rhs)}")
    L.append("")
    if sysm.motors:
        L.append("MOTOR EQUATIONS   (L di/dt + R i = V - Ke N w_out,   torque on the shaft = N Kt i)")
        for e in sysm.motors:
            p = e.p
            t = sysm.T[e.nodes[0]]
            idx = [i for i in np.nonzero(t)[0]]
            wsym = (sysm.coords[idx[0]]["name"] + "'") if idx else "0"
            if p["l"] > 0:
                L.append(f"  {e.name}:  {_num(p['l'])} {e.name}_i' + {_num(p['r'])} {e.name}_i = {e.name}_V - {_num(p['ke'] * p['n'] * (t[idx[0]] if idx else 0))} {wsym}"
                         f"        (i = {'i_' + e.name})")
            else:
                L.append(f"  {e.name}:  inductance is zero, so i = ({e.name}_V - {_num(p['ke'] * p['n'])} {wsym}) / {_num(p['r'])}  - the motor adds "
                         f"{_num(p['n'] ** 2 * p['kt'] * p['ke'] / p['r'])} of viscous damping")
            L.append(f"        reflected rotor: inertia N²·Jm = {_num(p['n'] ** 2 * p['jm'])} kg·m², friction N²·bm = {_num(p['n'] ** 2 * p['bm'])}")
        L.append("")
    if sysm.inputs:
        L.append("SOURCES (the columns of B)")
        for j, s in enumerate(sysm.inputs):
            what = {"FORCE": "force (N)", "TORQUE": "torque (N·m)", "MOTOR": "motor voltage (V)"}[s["kind"]]
            L.append(f"  u{j + 1} = {s['name']}   {what}")
        L.append("")
    L.append("MATRIX FORM   M q'' + D q' + K q = (source terms)")
    with np.printoptions(precision=4, suppress=True, linewidth=120):
        L.append("  M =\n" + _indent(str(sysm.M)))
        L.append("  D =\n" + _indent(str(sysm.Deff)))
        L.append("  K =\n" + _indent(str(sysm.K)))
    L.append("")
    L.append("STATE SPACE   x' = A x + B u,   x = [" + ", ".join(sysm.state_names) + "]")
    with np.printoptions(precision=4, suppress=True, linewidth=140):
        L.append("  A =\n" + _indent(str(sysm.A)))
        if sysm.B.shape[1]:
            L.append("  B =\n" + _indent(str(sysm.B)))
    return "\n".join(L)


def _indent(s):
    return "\n".join("    " + ln for ln in s.splitlines())


def modes_text(sysm):
    L = []
    L.append("POLES (the roots of the characteristic equation; stable when every real part is negative)")
    for m in sysm.modes():
        p = m["pole"]
        if m["kind"] == "pair":
            L.append(f"  {p.real:+.4g} ± {p.imag:.4g}j    wn = {m['wn']:.4g} rad/s ({m['wn'] / 2 / math.pi:.4g} Hz)    zeta = {m['zeta']:.4g}"
                     f"    wd = {m['wd']:.4g} rad/s")
        else:
            L.append(f"  {p.real:+.4g}            {'decay' if p.real < 0 else 'growth' if p.real > 0 else 'free (rigid-body) motion'}"
                     + (f"    time constant {1 / -p.real:.4g} s" if p.real < 0 else ""))
    un = sysm.undamped()
    if len(un):
        L.append("")
        L.append("UNDAMPED NATURAL FREQUENCIES (dampers and motors removed): "
                 + ", ".join((f"{w:.4g} rad/s" if w >= 0 else f"unstable ({-w:.4g})") for w in un))
    return "\n".join(L)
