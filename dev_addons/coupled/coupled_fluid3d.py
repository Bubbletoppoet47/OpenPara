"""coupled_fluid3d.py - a flowing fluid and a 3D solid that exchange heat, solved to agreement (no Qt).

The same loop as the 2D one (coupled_fluid.py: read its docstring for the reasoning), on the wall NODES of the 3D flow mesh instead of the profiles along the edges of a sketch.  The
flow does not depend on the temperature (a passive scalar), so it is solved once; what is repeated is the temperature of the fluid and of the solid, which meet at the wall:

  * h: the heat transfer coefficient of the wall nodes from an isothermal pass of the fluid (every exchange wall held at T_in + 1 K, flux / 1 K).  It is only the LINEARISATION: the
    answer does not depend on it, only how fast the loop gets there;
  * the solid is solved with  q = h (T - Tref)  on the faces of the exchange, Tref = T_prev - q_prev / h  (the wall temperature and the heat flux of the last fluid pass);
  * the fluid is solved with the wall temperature that the solid gave, node by node, and returns the true heat flux of every wall node;
  * the two agree when the flux the solid takes, q_prev + h (T - T_prev), equals the flux the fluid gives: that is the convergence (area-weighted, as a fraction of the flux).

The two analyses mesh the wall differently, so every field that crosses is interpolated on the triangles of the wall of the other mesh (coupled_surface.SurfaceLocator); how far a point
lay from them is counted and reported.  What is reported at the end: the flux mismatch, the heat that leaves the solid against the heat the fluid receives, the gaps.

The members it needs:
  fluid: coupled_keys() (the face ids of the exchange), solve_flow(), wall_surface() -> {"points" (n, 3) mm, "tris" (nt, 3) rows of points, "area" (n,) m2}, T_in,
         solve_temperature(Tw_at) -> {"T", "q" (W/m2 INTO the fluid), "area", "Q" (W into the fluid)} at the nodes of wall_surface(), where Tw_at(points (n, 3) mm) -> kelvin,
         heat_summary() -> {"Tmin", "Tmax", "balance": {"relative"}, "notes", "Pr"}
  thermal: set_fluid(h_at, Tref_at, fids), solve(), wall_temperature_at(points) -> (kelvin, gap in element sizes), heat_to_fluid() (W)
"""
import numpy as np

import coupled_surface as cs

KELVIN = 273.15


class FluidThermalError(Exception):
    """The loop cannot go on; the message says what to change."""


class WallField:
    """Values at the nodes of the fluid's wall, asked for at any points near it."""

    def __init__(self, surface):
        self.loc = cs.SurfaceLocator(surface["points"], surface["tris"])
        self.h = self.loc.h                                                              # (the size of the wall elements: what a gap is measured in)

    def at(self, values, P):
        """-> (the field at the points P (n, 3), how far every point lies from the wall (n,) in the units of the points)."""
        t, w, dist = self.loc.locate(P)
        v = np.asarray(values, float)
        return np.einsum("nk,nk->n", w, v[self.loc.T[t]]), dist


def solve_fluid_thermal3d(fl, th, opt=None, tick=None):
    """fl: a 3D fluid member, th: a 3D thermal member (the interface is in the module docstring).
    opt: {"conj_tol": 0.01 (the fraction of the heat that the solid and the fluid do not agree on), "conj_max": 25 (iterations), "q_tol": 0.05 (heat leaving the solid against the heat entering the fluid)}.
    -> {"converged", "iterations", "history", "mismatch", "tol", "Q_solid", "Q_fluid", "Q_rel", "q_tol", "gap_fluid", "gap_solid", "flow", "heat", "keys", "T_in", "h_max", "Tw", "q_wall"}"""
    o = {"conj_tol": 0.01, "conj_max": 25, "q_tol": 0.05}
    o.update(opt or {})

    def say(text, frac):
        if tick is not None:
            tick(text, frac)
    fids = [int(f) for f in fl.coupled_keys()]
    if not fids:
        raise FluidThermalError("The 3D Fluid Flow analysis has no wall of the thermal analysis: pick the faces where the fluid touches the solid and add the condition "
                                "'Wall of the thermal analysis' for them (3D Fluid Flow window, Conditions).")
    say(f"{fl.label}: solving the flow", 0.05)
    flow = fl.solve_flow()
    surf = fl.wall_surface()
    area = np.asarray(surf["area"], float)
    n = len(area)
    if n == 0 or not np.sum(area) > 0:
        raise FluidThermalError("The faces of the thermal exchange have no mesh in the flow: check that they are faces of the part.")
    T_in = float(fl.T_in)
    say(f"{fl.label}: the heat transfer coefficient of the walls", 0.30)
    iso = fl.solve_temperature(lambda X: np.full(len(X), T_in + 1.0))                      # every exchange wall at T_in + 1 K: the flux is h
    hv = np.asarray(iso["q"], float)
    hmax = float(np.max(np.abs(hv)))
    if not hmax > 0:
        raise FluidThermalError("The heat transfer coefficient of the walls is zero everywhere: the flow does not touch these walls.")
    hmean = float(np.sum(area * np.abs(hv)) / np.sum(area))
    # The coefficient the solid is linearised with: the isothermal pass can give a very small or a negative value somewhere (the first-order stabilisation, a stagnant corner), which
    # would make the loop crawl there: it is kept at or above a fraction of the mean.  (It sets the speed of the loop, never the answer.)
    h_floor = max(1e-6 * hmax, 0.05 * hmean)
    h_lin = np.maximum(hv, h_floor)
    prof = WallField(surf)
    Tw_vals = np.full(n, T_in)                                                           # the wall temperature and the heat flux of the last fluid pass (to begin with: none)
    q_vals = np.zeros(n)
    gaps = {"fluid": 0.0, "solid": 0.0}

    def h_at(P):
        v, g = prof.at(h_lin, P)
        gaps["fluid"] = max(gaps["fluid"], float(g.max() / prof.h) if len(g) else 0.0)
        return np.maximum(v, h_floor)

    def Tref_at(P):
        T0, g1 = prof.at(Tw_vals, P)
        q0, _g2 = prof.at(q_vals, P)
        return T0 - q0 / h_at(P)

    def Tw_at(P):
        v, g = th.wall_temperature_at(P)
        gaps["solid"] = max(gaps["solid"], float(g))
        return v
    history = []
    omega = 1.0
    prev = None
    converged = False
    wall = None
    for it in range(1, int(o["conj_max"]) + 1):
        say(f"Heat exchange, iteration {it}: the solid", 0.35 + 0.6 * (it - 1) / o["conj_max"])
        th.set_fluid(h_at, Tref_at, fids)
        th.solve()
        say(f"Heat exchange, iteration {it}: the fluid", 0.35 + 0.6 * (it - 0.5) / o["conj_max"])
        wall = fl.solve_temperature(Tw_at)
        T_new, q_new = np.asarray(wall["T"], float), np.asarray(wall["q"], float)
        # what the solid took at the wall nodes (q_prev + h (T - T_prev), at the temperature the fluid was just given) against what the fluid gave
        miss = q_new - q_vals - h_lin * (T_new - Tw_vals)
        # The flux of the wall nodes is spiky (the corners and edges of the part take far more than a node of a flat face), so the mismatch is weighed by the heat that every node carries
        # (area x flux): the fraction of the heat that the solid and the fluid do not agree on.  A norm of the flux itself would be the corners' and say nothing about the faces.
        mism = float(np.sum(area * np.abs(miss)) / max(float(np.sum(area * np.abs(q_new))), 1e-300))
        dT = float(np.max(np.abs(T_new - prev))) if prev is not None and len(prev) == len(T_new) else 0.0
        prev = T_new
        history.append({"it": it, "mismatch": mism, "dT": dT, "omega": omega, "Tw_min": float(T_new.min()), "Tw_max": float(T_new.max())})
        if mism <= o["conj_tol"]:
            converged = True
            break
        if len(history) >= 3 and history[-1]["mismatch"] > history[-2]["mismatch"] > history[-3]["mismatch"]:
            omega = max(0.2, 0.5 * omega)                                                # growing for two iterations in a row: take smaller steps
        Tw_vals = Tw_vals + omega * (T_new - Tw_vals)
        q_vals = q_vals + omega * (q_new - q_vals)
    Q_fluid = float(wall["Q"])
    Q_solid = float(th.heat_to_fluid())
    scale = max(abs(Q_fluid), abs(Q_solid), 1e-300)
    return {"converged": converged, "iterations": len(history), "history": history, "mismatch": history[-1]["mismatch"], "tol": o["conj_tol"], "Q_solid": Q_solid, "Q_fluid": Q_fluid,
            "Q_rel": (Q_solid - Q_fluid) / scale, "q_tol": o["q_tol"], "gap_fluid": gaps["fluid"], "gap_solid": gaps["solid"], "flow": flow, "heat": fl.heat_summary(), "keys": fids,
            "T_in": T_in, "h_max": hmax, "Tw": np.asarray(wall["T"], float), "wall_points": int(n), "q_wall": np.asarray(wall["q"], float), "h": hv, "h_lin": h_lin}
