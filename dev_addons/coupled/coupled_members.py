"""coupled_members.py - the four analysis windows as members of a Coupled Physics solve: 2D Thermal and 3D Thermal (they send a temperature), 2D Static Structural and
3D Static Structural (they take it).  A member drives the window it wraps through the window's own Solve (the setup is the window's: materials, conditions, mesh settings),
waits for it when it runs on a worker thread, and hands the engine (coupled_engine) what it needs: the temperature field and its mesh, or the points of the stress mesh
to ask the temperature for.  Qt is used only to wait for a window's worker."""
import time

import numpy as np

import coupled_engine as ce

WAIT_LIMIT = 3600.0                                          # seconds a member waits for a solve before it says it did not finish


def wait_for(w):
    """A window that solves on a worker thread (3D) is waited for; one that solves at once (2D, or a 3D window made with threaded=False) is already done."""
    if getattr(w, "job", None) is None:
        return
    from PyQt6.QtWidgets import QApplication
    t0 = time.monotonic()
    while getattr(w, "job", None) is not None:
        QApplication.processEvents()
        time.sleep(0.01)
        if time.monotonic() - t0 > WAIT_LIMIT:
            raise ce.CoupledError("A solve did not finish in time.")
    QApplication.processEvents()


def why_not(w):
    """What a 3D window last said when a solve did not give a result: the last line of its error, else its status line."""
    err = (getattr(w, "last_error", "") or "").strip().splitlines()
    if err:
        return err[-1]
    lbl = getattr(w, "status_lbl", None)
    return (lbl.text() if lbl is not None else "") or ""


def reset(w):
    w.result = None
    w.last_error = ""


class Thermal2D(ce.Member):
    role, dim, label = "thermal", 2, "2D Thermal"

    def __init__(self, tab):
        self.tab = tab

    def solve(self):
        t = self.tab
        if getattr(t, "model", None) is None:
            raise ce.CoupledError(f"{self.label}: no sketch is imported yet.")
        if t.mesh is None:
            t.run_mesh()
            if t.mesh is None:
                raise ce.CoupledError(f"{self.label}: the mesh could not be made (see the message in its tab).")
        t.result = None
        t.run_solve()
        if t.result is None:
            raise ce.CoupledError(f"{self.label}: the solve did not give a result (see the message in its tab).")
        return t.result

    def temperature_field(self):
        r = self.tab.result
        mesh = r["mesh"]
        return np.asarray(mesh["nodes"], float), np.asarray(mesh["tris"]), np.asarray(r["T"], float), float(r["Tmean"])      # (a transient run: the temperature at its end)


class Structural2D(ce.Member):
    role, dim, label = "structural", 2, "2D Static Structural"

    def summary(self):
        return _summary_2d(self.tab)

    def __init__(self, tab):
        self.tab = tab
        self.last_weights = self.last_points = None

    def solve(self, temperature_at):
        t = self.tab
        if getattr(t, "model", None) is None:
            raise ce.CoupledError(f"{self.label}: no sketch is imported yet.")
        if t.mesh is None:
            t.run_mesh()
            if t.mesh is None:
                raise ce.CoupledError(f"{self.label}: the mesh could not be made (see the message in its tab).")

        def ask(points):
            mesh = t.mesh
            self.last_points = np.asarray(points, float)
            self.last_weights = ce.lumped_weights(mesh["nodes"], mesh["tris"], n=len(points))
            return temperature_at(points)
        t.result = None
        t.coupled_in = ask
        try:
            t.run_solve()
        finally:
            t.coupled_in = None
        if t.result is None:
            raise ce.CoupledError(f"{self.label}: the solve did not give a result (see the message in its tab).")
        return t.result


def _summary_2d(tab):
    """The largest displacement and von Mises stress of a 2D stress result, in the unit system of the sketch: {"umax", "L", "vm_max", "S"}."""
    import units
    r = tab.result
    uu = units.get(tab.unit_name())
    return {"umax": float(np.max(np.hypot(r["u"][:, 0], r["u"][:, 1]))), "L": uu["L"], "vm_max": float(np.max(r["vm"])), "S": uu["S"]}


def _summary_3d(win):
    """The same for a 3D stress result (the solver works in mm and MPa; shown in the program's units)."""
    import solid_base
    import solid_tab
    r, D = win.result, solid_base.UD()
    return {"umax": float(solid_base.l_out(r["umax"])), "L": D["L"], "vm_max": float(solid_tab.s_out(r["vm_max"])), "S": D["S"]}


class Thermal3D(ce.Member):
    role, dim, label = "thermal", 3, "3D Thermal"

    def __init__(self, win):
        self.win = win

    def solve(self):
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")
        reset(w)
        if w.run_solve() is False and getattr(w, "job", None) is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "it could not be started (see the message in its tab)."))
        wait_for(w)
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "the solve did not give a result."))
        return w.result

    def temperature_field(self):
        r = self.win.result
        conn = np.asarray(r["conn"])
        return np.asarray(r["nodes"], float), conn[:, :4], np.asarray(r["T"], float), float(r["Tmean"])


class Structural3D(ce.Member):
    role, dim, label = "structural", 3, "3D Static Structural"

    def summary(self):
        return _summary_3d(self.win)

    def far_end(self, axis=0):
        """How far the end of the body that is farthest along `axis` has moved along it (mm; the mean over the nodes of that end): what a free bar's growth is."""
        r = self.win.result
        n, u = np.asarray(r["nodes"], float), np.asarray(r["u"], float)
        x = n[:, axis]
        end = np.abs(x - x.max()) < 1e-6 * max(1.0, float(np.ptp(x)))
        return float(u[end, axis].mean())

    def __init__(self, win):
        self.win = win
        self.last_weights = self.last_points = None

    def solve(self, temperature_at):
        w = self.win
        if w.geom is None:
            raise ce.CoupledError(f"{self.label}: no part is imported yet.")

        def ask(points, q=None):
            self.last_points = np.asarray(points, float)
            tets = None if q is None or len(q.get("hexes", ())) or len(q.get("pyrs", ())) else q.get("tets")
            self.last_weights = None if tets is None else ce.lumped_weights(points, tets, n=len(points))      # (a mesh with bricks: no average check)
            return temperature_at(points)
        reset(w)
        w.coupled_in = ask
        try:
            if w.run_solve() is False and getattr(w, "job", None) is None:
                raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "it could not be started (see the message in its tab)."))
            wait_for(w)
        finally:
            w.coupled_in = None
        if w.result is None:
            raise ce.CoupledError(f"{self.label}: " + (why_not(w) or "the solve did not give a result."))
        return w.result


def wrap(kind, window):
    """The member for a window of kind 'thermal' (2D Thermal), 'thermal3d', 'fea' (2D Static Structural) or 'solid' (3D Static Structural)."""
    cls = {"thermal": Thermal2D, "thermal3d": Thermal3D, "fea": Structural2D, "solid": Structural3D}.get(kind)
    if cls is None:
        raise ce.CoupledError(f"A '{kind}' analysis cannot take part in Coupled Physics yet.")
    return cls(window)


def pair(windows):
    """{kind: window} -> {"thermal": member, "structural": member} of ONE dimension, or raises CoupledError in words (what is missing, what does not fit)."""
    th = [(k, w) for k, w in windows.items() if k in ("thermal", "thermal3d")]
    st = [(k, w) for k, w in windows.items() if k in ("fea", "solid")]
    if not th or not st:
        need = " and ".join(n for n, got in (("a 2D or 3D Thermal analysis", th), ("a 2D or 3D Static Structural analysis", st)) if not got)
        raise ce.CoupledError(f"Coupled Physics needs both a heat problem and a stress problem: wire in {need}.")
    if len(th) > 1 or len(st) > 1:
        raise ce.CoupledError("One Thermal and one Structural analysis can be coupled at a time for now.")
    a, b = wrap(*th[0]), wrap(*st[0])
    if a.dim != b.dim:
        raise ce.CoupledError(f"The thermal analysis is {a.dim}D and the structural analysis is {b.dim}D: wire in two of the same dimension.")
    return {"thermal": a, "structural": b}
