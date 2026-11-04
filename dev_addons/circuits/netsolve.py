"""netsolve.py - the circuit solver of the Circuits add-on: modified nodal analysis (MNA).

    net = Net()
    net.add("V", "V1", ["in", "0"], dc=5)             # node "0" is ground
    net.add("R", "R1", ["in", "out"], r=1000)
    net.add("D", "LED1", ["out", "0"], vf=2.0)
    res = dc(net)                                      # operating point
    res.v("out"), res.i("V1")

Analyses: dc(net) operating point (Newton with damping, then gmin / source stepping when it does not converge),
transient(net, tstop, dt) (trapezoidal companion models, backward Euler on the first step), ac_sweep(net, freqs) (small signal around the
operating point), resistance(net, a, b) (what an ohmmeter reads: sources off, small test voltage).

Element kinds (net.add(kind, name, nodes, **params)):
  R r | C c | L l | V dc / ac / wave (sine, square, pulse...) | I dc | D is/vf/n | Z (zener) vz | Q (bjt) type npn/pnp | M (mosfet) type n/p
  SW closed (ron / roff) | AM (ammeter: 0 V source, reads current) | BUCK, BOOST (averaged DC-DC converters)
Everything is dense numpy: circuits here are small (tens of nodes).
"""
import math

import numpy as np

VT = 0.025852           # thermal voltage at 300 K
GMIN = 1e-12
EXP_MAX = 40.0


def sexp(x):
    """exp with a linear continuation beyond EXP_MAX so Newton never overflows."""
    if x > EXP_MAX:
        return math.exp(EXP_MAX) * (1.0 + x - EXP_MAX)
    return math.exp(x)


# --------------------------------------------------------------------------------------------------- waveforms
def waveform(p, t):
    """Value of a V / I source at time t. p: dict with dc and optional wave params."""
    w = p.get("wave", "dc")
    dc = p.get("dc", 0.0)
    if w == "dc":
        return dc
    f = max(p.get("freq", 1000.0), 1e-9)
    amp = p.get("amp", 1.0)
    ph = math.radians(p.get("phase", 0.0))
    off = p.get("offset", 0.0)
    if w == "sine":
        return off + amp * math.sin(2 * math.pi * f * t + ph)
    cyc = ((f * t + ph / (2 * math.pi)) % 1.0)
    if w == "square":
        duty = p.get("duty", 0.5)
        return off + (amp if cyc < duty else -amp)
    if w == "pulse":                  # 0 .. amp
        duty = p.get("duty", 0.5)
        return off + (amp if cyc < duty else 0.0)
    if w == "triangle":
        return off + amp * (4 * abs(cyc - 0.5) - 1) * -1 if False else off + amp * (1 - 4 * abs(cyc - 0.5))
    if w == "sawtooth":
        return off + amp * (2 * cyc - 1)
    return dc


class Element:
    kind = "?"
    nbr = 0                       # branch-current unknowns
    nonlinear = False

    def __init__(self, name, nodes, **p):
        self.name, self.nodes, self.p = name, list(nodes), dict(p)
        self.br = -1              # first branch index (set by Net)
        self.state = {}

    def stamp(self, c):
        pass

    def accept(self, c, x):
        pass

    def current(self, getv, getbr):
        """Current through the element from its first to its second node (for meters / glow); None when it has no such current."""
        return None


class Resistor(Element):
    kind = "R"

    def r(self):
        return max(self.p.get("r", 1000.0), 1e-9)

    def stamp(self, c):
        c.G(self.nodes[0], self.nodes[1], 1.0 / self.r())

    def current(self, getv, getbr):
        return (getv(self.nodes[0]) - getv(self.nodes[1])) / self.r()


class Pot(Element):                # pins a, wiper, b : two resistors
    kind = "POT"

    def stamp(self, c):
        r, pos = max(self.p.get("r", 10e3), 1e-6), min(max(self.p.get("pos", 0.5), 0.0), 1.0)
        a, w, b = self.nodes
        c.G(a, w, 1.0 / max(r * pos, 1e-3))
        c.G(w, b, 1.0 / max(r * (1 - pos), 1e-3))

    def current(self, getv, getbr):
        r, pos = max(self.p.get("r", 10e3), 1e-6), min(max(self.p.get("pos", 0.5), 0.0), 1.0)
        return (getv(self.nodes[0]) - getv(self.nodes[1])) / max(r * pos, 1e-3)


class Switch(Element):
    kind = "SW"

    def rr(self):
        return self.p.get("ron", 1e-3) if self.p.get("closed", False) else self.p.get("roff", 1e9)

    def stamp(self, c):
        c.G(self.nodes[0], self.nodes[1], 1.0 / self.rr())

    def current(self, getv, getbr):
        return (getv(self.nodes[0]) - getv(self.nodes[1])) / self.rr()


class Capacitor(Element):
    kind = "C"

    def stamp(self, c):
        a, b = self.nodes
        C = max(self.p.get("c", 1e-6), 1e-18)
        if c.mode == "ac":
            c.Y(a, b, 1j * c.omega * C)
        elif c.mode == "tran":
            vp, ip = self.state.get("v", 0.0), self.state.get("i", 0.0)
            if c.first:
                g = C / c.dt
                ieq = g * vp
            else:
                g = 2 * C / c.dt
                ieq = g * vp + ip
            c.G(a, b, g)
            c.I(a, ieq)
            c.I(b, -ieq)
            self._g, self._ieq = g, ieq
        elif c.mode == "dc" and "v0" in self.state and c.use_ic:
            pass

    def accept(self, c, x):
        if c.mode == "tran":
            v = c.vx(x, self.nodes[0]) - c.vx(x, self.nodes[1])
            self.state["i"] = self._g * v - self._ieq
            self.state["v"] = v

    def init_dc(self, c, x):
        self.state["v"] = c.vx(x, self.nodes[0]) - c.vx(x, self.nodes[1])
        self.state["i"] = 0.0

    def current(self, getv, getbr):
        return None


class Inductor(Element):
    kind = "L"
    nbr = 1

    def stamp(self, c):
        a, b = self.nodes
        k = self.br
        L = max(self.p.get("l", 1e-3), 1e-15)
        c.branch_kcl(a, b, k)
        if c.mode == "ac":
            c.A[c.nn + k, c.nn + k] += -1j * c.omega * L
        elif c.mode == "tran":
            ip, vp = self.state.get("i", 0.0), self.state.get("v", 0.0)
            if c.first:
                z = L / c.dt
                rhs = -z * ip
            else:
                z = 2 * L / c.dt
                rhs = -z * ip - vp
            c.A[c.nn + k, c.nn + k] += -z
            c.b[c.nn + k] += rhs
            self._z = z
        # dc: short (v = 0)

    def accept(self, c, x):
        if c.mode == "tran":
            i = x[c.nn + self.br]
            v = c.vx(x, self.nodes[0]) - c.vx(x, self.nodes[1])
            self.state["i"], self.state["v"] = i, v

    def init_dc(self, c, x):
        self.state["i"] = x[c.nn + self.br]
        self.state["v"] = 0.0

    def current(self, getv, getbr):
        return getbr(self.br)


class VSource(Element):
    kind = "V"
    nbr = 1

    def stamp(self, c):
        a, b = self.nodes
        k = self.br
        c.branch_kcl(a, b, k)
        if c.mode == "ac":
            val = self.p.get("ac", 0.0)
        elif c.mode == "tran":
            val = waveform(self.p, c.t) * c.scale
        else:
            val = (self.p.get("dc", 0.0) if self.p.get("wave", "dc") == "dc" else waveform(self.p, 0.0)) * c.scale
        c.b[c.nn + k] += val

    def current(self, getv, getbr):
        return getbr(self.br)           # flows from + node through the source to - node (negative when the source delivers)


class Ammeter(VSource):
    kind = "AM"

    def stamp(self, c):
        a, b = self.nodes
        c.branch_kcl(a, b, self.br)


class ISource(Element):
    kind = "I"

    def stamp(self, c):
        a, b = self.nodes
        if c.mode == "ac":
            val = self.p.get("ac", 0.0)
        elif c.mode == "tran":
            val = waveform(self.p, c.t) * c.scale
        else:
            val = self.p.get("dc", 0.0) * c.scale
        c.I(a, -val)                    # current leaves a, enters b
        c.I(b, val)

    def current(self, getv, getbr):
        return self.p.get("dc", 0.0)


class NL(Element):
    """A nonlinear element given by terminal currents as a function of terminal voltages."""
    nonlinear = True

    def currents(self, v):
        raise NotImplementedError

    def stamp(self, c):
        n = len(self.nodes)
        v0 = np.array([c.v(k) for k in self.nodes], dtype=float)
        i0 = np.array(self.currents(v0), dtype=float)
        J = np.zeros((n, n))
        for j in range(n):
            h = 1e-6 * max(1.0, abs(v0[j]))
            v1 = v0.copy()
            v1[j] += h
            J[:, j] = (np.array(self.currents(v1)) - i0) / h
        for k in range(n):
            for j in range(n):
                c.Gm(self.nodes[k], self.nodes[j], J[k, j])
            c.I(self.nodes[k], float(J[k] @ v0 - i0[k]) if c.mode != "ac" else 0.0)


class Diode(NL):
    kind = "D"

    def params(self):
        n = self.p.get("n", 1.0)
        vf = self.p.get("vf")
        if vf:                                                 # forward voltage at 10 mA given: LEDs, Schottky ...
            n = self.p.get("n", 2.0 if vf > 1.5 else 1.0)
            is_ = 0.01 / math.exp(vf / (n * VT))
        else:
            is_ = self.p.get("is", 1e-14)
        return is_, n

    def id(self, v):
        is_, n = self.params()
        i = is_ * (sexp(v / (n * VT)) - 1.0)
        vz = self.p.get("vz")
        if vz:                                                 # zener: breakdown for v < -vz
            nb = 1.5 * VT                                       # vz is the voltage at 5 mA of breakdown current
            i -= 0.005 * (sexp(-(v + vz) / nb) - math.exp(-vz / nb))
        return i

    def currents(self, v):
        i = self.id(v[0] - v[1])
        return [i, -i]

    def current(self, getv, getbr):
        v = getv(self.nodes[0]) - getv(self.nodes[1])
        if np.ndim(v) == 0:
            return self.id(float(v))
        return np.array([self.id(float(x)) for x in v])


class BJT(NL):
    kind = "Q"                # nodes C, B, E

    def currents(self, v):
        sg = 1.0 if self.p.get("type", "npn") == "npn" else -1.0
        vc, vb, ve = v
        vbe, vbc = sg * (vb - ve), sg * (vb - vc)
        is_, bf, br = self.p.get("is", 1e-14), self.p.get("bf", 100.0), self.p.get("br", 2.0)
        ef, er = sexp(vbe / VT) - 1.0, sexp(vbc / VT) - 1.0
        ic = is_ * (ef - er) - is_ / br * er
        ib = is_ / bf * ef + is_ / br * er
        ie = -(ic + ib)
        return [sg * ic, sg * ib, sg * ie]

    def current(self, getv, getbr):
        return None


class MOSFET(NL):
    kind = "M"                # nodes D, G, S

    def currents(self, v):
        sg = 1.0 if self.p.get("type", "n") == "n" else -1.0
        vd, vg, vs = v
        kp, vth, lam = self.p.get("kp", 0.2), self.p.get("vth", 2.0), self.p.get("lam", 0.01)
        vgs, vds = sg * (vg - vs), sg * (vd - vs)
        sw = 1.0
        if vds < 0:                                            # source and drain swap when the channel is reversed
            vgs, vds, sw = vgs - vds, -vds, -1.0
        vov = vgs - vth
        if vov <= 0:
            idr = 0.0
        elif vds < vov:
            idr = kp * (vov * vds - vds * vds / 2.0) * (1 + lam * vds)
        else:
            idr = kp / 2.0 * vov * vov * (1 + lam * vds)
        idr *= sw * sg
        return [idr, 0.0, -idr]


class Converter(Element):
    """Averaged DC-DC converter: nodes in+, in-, out+, out-. The output is an ideal source at the set voltage (as far as the input allows),
    the input draws the power the output delivers divided by the efficiency."""
    nbr = 1

    def vout(self, vin):
        vset = self.p.get("vset", 5.0)
        drop = self.p.get("dropout", 0.3)
        if self.kind == "BUCK":
            return max(0.0, min(vset, vin - drop))
        return vset if vin > 0.8 else 0.0 if vin < 0.8 and vin < 0.5 else max(vin - drop, 0.0)

    def stamp(self, c):
        ip, im, op, om = self.nodes
        vin = c.v(ip) - c.v(im)
        vo = self.vout(vin)
        if self.kind == "BOOST" and vin > 0.8:
            vo = max(self.p.get("vset", 12.0), vin - self.p.get("dropout", 0.3))
        eff = min(max(self.p.get("eff", 0.9), 0.05), 1.0)
        c.branch_kcl(op, om, self.br)
        c.b[c.nn + self.br] += vo * c.scale if c.mode != "ac" else 0.0
        iload = -c.xbr(self.br)                  # current delivered out of out+
        iin = max(vo * iload, 0.0) / (eff * max(vin, 0.5))
        if c.mode == "ac":
            iin = 0.0
        c.I(ip, -iin)                           # drawn from in+ through the converter to in-
        c.I(im, iin)
        self._vo, self._iin = vo, iin

    def current(self, getv, getbr):
        return -getbr(self.br)


class Buck(Converter):
    kind = "BUCK"


class Boost(Converter):
    kind = "BOOST"


KINDS = {"R": Resistor, "POT": Pot, "SW": Switch, "C": Capacitor, "L": Inductor, "V": VSource, "AM": Ammeter, "I": ISource,
         "D": Diode, "Q": BJT, "M": MOSFET, "BUCK": Buck, "BOOST": Boost}


# --------------------------------------------------------------------------------------------------- the netlist
class Net:
    def __init__(self):
        self.elems, self.names = [], {"0": 0, "gnd": 0, "GND": 0}
        self.by_name = {}

    def node(self, name):
        name = str(name)
        if name not in self.names:
            self.names[name] = len(set(self.names.values()))
        return self.names[name]

    def add(self, kind, name, nodes, **p):
        e = KINDS[kind](name, [self.node(n) for n in nodes], **p)
        self.elems.append(e)
        self.by_name[name] = e
        return e

    @property
    def n_nodes(self):
        return len(set(self.names.values())) - 1          # without ground

    def finalize(self):
        k = 0
        for e in self.elems:
            e.br = k if e.nbr else -1
            k += e.nbr
        self.n_br = k


class Ctx:
    def __init__(self, net, mode, x=None, t=0.0, dt=0.0, omega=0.0, scale=1.0, first=False, gmin=GMIN, xop=None):
        self.net, self.mode, self.t, self.dt, self.omega, self.scale, self.first = net, mode, t, dt, omega, scale, first
        self.nn, self.nb = net.n_nodes, net.n_br
        n = self.nn + self.nb
        dtype = complex if mode == "ac" else float
        self.A = np.zeros((n, n), dtype=dtype)
        self.b = np.zeros(n, dtype=dtype)
        self.x = np.zeros(n) if x is None else x
        self.xop = xop
        self.use_ic = False
        for i in range(self.nn):
            self.A[i, i] += gmin

    # voltage of a node in the current guess (the operating point in ac mode)
    def v(self, k):
        src = self.xop if self.mode == "ac" else self.x
        return 0.0 if k == 0 else float(src[k - 1])

    def vx(self, x, k):
        return 0.0 if k == 0 else float(x[k - 1])

    def xbr(self, br):
        src = self.xop if self.mode == "ac" else self.x
        return float(src[self.nn + br])

    def G(self, a, b, g):
        if a:
            self.A[a - 1, a - 1] += g
        if b:
            self.A[b - 1, b - 1] += g
        if a and b:
            self.A[a - 1, b - 1] -= g
            self.A[b - 1, a - 1] -= g

    Y = G

    def Gm(self, a, b, g):
        """dI(a)/dV(b) = g"""
        if a and b:
            self.A[a - 1, b - 1] += g

    def I(self, a, val):
        """current injected into node a"""
        if a:
            self.b[a - 1] += val

    def branch_kcl(self, a, b, k):
        """branch current k leaves node a, enters node b; branch equation  v(a) - v(b) = ..."""
        r = self.nn + k
        if a:
            self.A[a - 1, r] += 1.0
            self.A[r, a - 1] += 1.0
        if b:
            self.A[b - 1, r] -= 1.0
            self.A[r, b - 1] -= 1.0


class SolveError(Exception):
    pass


def _newton(net, mode, x0, t=0.0, dt=0.0, scale=1.0, first=False, gmin=GMIN, maxit=150):
    x = x0.copy()
    nn = net.n_nodes
    for it in range(maxit):
        c = Ctx(net, mode, x, t, dt, 0.0, scale, first, gmin)
        for e in net.elems:
            e.stamp(c)
        try:
            xn = np.linalg.solve(c.A, c.b)
        except np.linalg.LinAlgError:
            xn = np.linalg.lstsq(c.A, c.b, rcond=None)[0]
        if not any(e.nonlinear or isinstance(e, Converter) for e in net.elems):
            return xn, it + 1
        d = xn - x
        dv = np.max(np.abs(d[:nn])) if nn else 0.0
        if dv > 1.0:                                           # damp: no voltage step above 1 V per iteration
            xn = x + d * (1.0 / dv)
            d = xn - x
        tol = 1e-7 + 1e-6 * np.abs(xn)
        tol[nn:] = 1e-9 + 1e-6 * np.abs(xn[nn:])
        x = xn
        if np.all(np.abs(d) < tol) and (dv <= 1.0):
            return x, it + 1
    raise SolveError("did not converge")


def _solve_op(net, x0):
    try:
        return _newton(net, "dc", x0)[0]
    except SolveError:
        pass
    x = x0.copy()                                              # gmin stepping
    try:
        for g in (1e-3, 1e-5, 1e-7, 1e-9, 1e-12):
            x = _newton(net, "dc", x, gmin=g)[0]
        return x
    except SolveError:
        pass
    x = np.zeros_like(x0)                                      # source stepping
    for s in np.linspace(0.05, 1.0, 20):
        x = _newton(net, "dc", x, scale=s)[0]
    return x


class Result:
    """What an analysis returns: node voltages and branch currents, one set (dc) or one per time / frequency step."""

    def __init__(self, net, X, axis=None):
        self.net, self.X, self.axis = net, np.asarray(X), axis
        self.nn = net.n_nodes

    def v(self, node):
        k = self.net.names[str(node)] if str(node) in self.net.names else self.net.node(node)
        if k == 0:
            return 0.0 if self.X.ndim == 1 else np.zeros(self.X.shape[0])
        return self.X[k - 1] if self.X.ndim == 1 else self.X[:, k - 1]

    def vdiff(self, a, b):
        return self.v(a) - self.v(b)

    def branch(self, br):
        return self.X[self.nn + br] if self.X.ndim == 1 else self.X[:, self.nn + br]

    def i(self, name):
        """Current through element `name` (first node to second; for sources: through the source, plus node to minus node)."""
        e = self.net.by_name[name]
        return e.current(lambda k: 0.0 if k == 0 else (self.X[k - 1] if self.X.ndim == 1 else self.X[:, k - 1]), self.branch)


def dc(net, x0=None):
    net.finalize()
    n = net.n_nodes + net.n_br
    x = _solve_op(net, np.zeros(n) if x0 is None else x0)
    return Result(net, x)


def transient(net, tstop, dt, record_every=1, start_dc=True):
    """Fixed-step transient from the DC operating point. Returns a Result whose axis is time."""
    net.finalize()
    n = net.n_nodes + net.n_br
    x = _solve_op(net, np.zeros(n)) if start_dc else np.zeros(n)
    c0 = Ctx(net, "dc", x)
    for e in net.elems:
        if hasattr(e, "init_dc"):
            e.init_dc(c0, x)
    steps = int(round(tstop / dt))
    ts, X = [0.0], [x.copy()]
    for k in range(1, steps + 1):
        t = k * dt
        x, _ = _newton(net, "tran", x, t=t, dt=dt, first=(k == 1))
        cc = Ctx(net, "tran", x, t, dt)
        for e in net.elems:
            e.accept(cc, x)
        if k % record_every == 0:
            ts.append(t)
            X.append(x.copy())
    return Result(net, np.array(X), np.array(ts))


def ac_sweep(net, freqs):
    """Small-signal response around the operating point; sources with an `ac` value drive it. Returns complex X per frequency."""
    net.finalize()
    n = net.n_nodes + net.n_br
    xop = _solve_op(net, np.zeros(n))
    out = []
    for f in freqs:
        c = Ctx(net, "ac", xop, omega=2 * math.pi * f, xop=xop)
        for e in net.elems:
            e.stamp(c)
        try:
            out.append(np.linalg.solve(c.A, c.b))
        except np.linalg.LinAlgError:
            out.append(np.linalg.lstsq(c.A, c.b, rcond=None)[0])
    return Result(net, np.array(out), np.asarray(freqs, float))


def resistance(net, a, b, vtest=0.1):
    """What an ohmmeter between nodes a and b reads: every source off, a small test voltage across, R = V / I (inf when nothing flows)."""
    net2 = Net()
    net2.names = dict(net.names)
    for e in net.elems:
        p = dict(e.p)
        if e.kind in ("V", "I", "BUCK", "BOOST"):
            if e.kind in ("V", "I"):
                p.update(dc=0.0, wave="dc")
            else:
                continue                                       # a converter is not a circuit element when it is switched off
        net2.elems.append(KINDS[e.kind](e.name, e.nodes, **p))
        net2.by_name[e.name] = net2.elems[-1]
    t = net2.add("V", "_ohm", [a, b], dc=vtest)
    res = dc(net2)
    i = -res.i("_ohm")                                         # current delivered by the test source
    if abs(i) < 1e-12:
        return math.inf
    return vtest / i
