"""coupled_fluid.py - a flowing fluid and a solid that exchange heat, solved to agreement (no Qt).

The flow does not depend on the temperature here (a passive scalar), so it is solved ONCE.  What is repeated is the cheap part: the temperature of the fluid and the temperature of
the solid.  They meet at the wall, where two things must hold: the temperature is the same on both sides, and the heat that leaves the solid enters the fluid.

The loop (linearised Robin, "Robin-Dirichlet"):
  * h(s): the heat transfer coefficient of the wall from an isothermal pass of the fluid (every coupled wall held at T_in + 1 K, q / 1 K).  It is only the LINEARISATION: the answer does
    not depend on it, only how fast the loop gets there.
  * the solid is solved with the exchange  q = h(s) (T_wall - T_ref(s)),  T_ref = the inlet temperature to begin with;
  * the fluid is solved with the wall temperature that the solid gave (a fixed temperature, point by point);  it gives the true heat flux q_f(s) of that wall;
  * the exchange the solid is given is then  q = q_f + h (T - T_wall)  (the fluid's flux of the last pass, corrected by h for a change of the wall temperature), written as
    h (T - T_ref) with  T_ref = T_wall - q_f / h  taken at the point where the solid asks.  Where the solid's wall temperature no longer changes, it sees exactly the flux the fluid
    delivers: that is the convergence (the flux the solid would take equals the flux the fluid gives, q_f).
Nothing about the wall temperature is assumed: it is whatever the solid and the fluid together settle on.

What is checked at the end (reported, never hidden): the flux mismatch along the wall, the heat that leaves the solid against the heat the fluid receives (the two meshes integrate it
differently, so they agree to the discretisation, not to rounding), and that every wall point of one mesh found its place on the other mesh.
"""
import numpy as np

KELVIN = 273.15


class FluidThermalError(Exception):
    """The loop cannot go on; the message says what to change."""


def _edge_values(hres, keys, what):
    out = {}
    for k in keys:
        tb = hres["walls"].get(tuple(k))
        if tb is None:
            raise FluidThermalError(f"The fluid solve gave no wall data for {k[0]} {k[1]} (is that body switched on in the CFD window?).")
        out[tuple(k)] = tb
    return out


def solve_fluid_thermal(fl, th, opt=None, tick=None):
    """fl: a fluid member, th: a thermal member (the interface is in the module docstring and in coupled_members.py).
    opt: {"conj_tol": 0.01 (flux mismatch, fraction of the largest flux), "conj_max": 25 (iterations), "q_tol": 0.05 (heat leaving the solid against the heat entering the fluid)}.
    -> {"converged", "iterations", "history", "mismatch", "Q_solid", "Q_fluid", "Q_rel", "gap_fluid", "gap_solid", "h", "flow", "heat", "keys"}"""
    o = {"conj_tol": 0.01, "conj_max": 25, "q_tol": 0.05}
    o.update(opt or {})

    def say(text, frac):
        if tick is not None:
            tick(text, frac)
    keys = [tuple(k) for k in fl.coupled_keys()]
    if not keys:
        raise FluidThermalError("The CFD window has no wall of the thermal analysis: select the edges where the fluid touches the solid and choose 'Wall of the thermal analysis' "
                                "for them (CFD window, Fluid and flow, Wall conditions).")
    say(f"{fl.label}: solving the flow", 0.05)
    flow = fl.solve_flow()
    say(f"{fl.label}: the heat transfer coefficient of the walls", 0.30)
    hvals, _hprof = fl.h_iso()
    for k in keys:
        if k not in hvals:
            raise FluidThermalError(f"The flow has no wall data for {k[0]} {k[1]}.")
    hall = np.concatenate([np.asarray(v, float).reshape(-1) for k in keys for v in hvals[k]])
    hmax = float(np.max(np.abs(hall)))
    if not hmax > 0:
        raise FluidThermalError("The heat transfer coefficient of the walls is zero everywhere: the flow does not touch these walls.")
    # the coefficient the solid is linearised with: the isothermal pass can give a very small or a negative value at a corner (the first-order stabilisation), which would make
    # the loop crawl there; it is kept at or above a fraction of the mean.  (It sets the speed of the loop, never the answer.)
    h_floor = max(1e-6 * hmax, 0.05 * float(np.mean(np.abs(hall))))
    h_lin = {k: tuple(np.maximum(np.asarray(x, float), h_floor) for x in hvals[k]) for k in keys}
    hprof = fl.profile(h_lin)
    T_in = float(fl.T_in)
    # What the solid is given is the exchange  q = q_prev + h (T - T_prev)  with  q_prev  and  T_prev  the heat flux and the wall temperature of the last fluid pass (two smooth
    # profiles along the wall): written as  h (T - Tref)  with  Tref = T_prev - q_prev / h  taken AT THE POINT where the solid asks, so that the h it multiplies by is the h that
    # Tref was divided by, and the flux is exact there whatever the profile of h looks like between the nodes.  To begin with T_prev = T_in and q_prev = 0.
    zeros = {k: tuple(np.zeros(len(np.asarray(hvals[k][0]))) for _ in range(3)) for k in keys}
    Tw_vals = {k: tuple(v + T_in for v in zeros[k]) for k in keys}
    q_vals = zeros
    Tw_prof, q_prof = fl.profile(Tw_vals), fl.profile(q_vals)
    gaps = {"h_max": 0.0, "Tref_max": 0.0, "T_wall_max": 0.0}

    def h_at(P):
        v, g = hprof.at(P)
        v = np.maximum(v, h_floor)
        gaps["h_max"] = max(gaps["h_max"], float(np.max(g) / hprof.h) if len(g) else 0.0)
        return v

    def Tref_at(P):
        T0, g1 = Tw_prof.at(P)
        q0, g2 = q_prof.at(P)
        gaps["Tref_max"] = max(gaps["Tref_max"], float(max(np.max(g1), np.max(g2)) / Tw_prof.h) if len(g1) else 0.0)
        return T0 - q0 / h_at(P)

    def Tw_at(P):
        v, g = th.wall_temperature_at(P)
        gaps["T_wall_max"] = max(gaps["T_wall_max"], g)
        return v
    history = []
    omega = 1.0
    prev = None
    converged = False
    hres = None
    for it in range(1, int(o["conj_max"]) + 1):
        say(f"Heat exchange, iteration {it}: the solid", 0.35 + 0.6 * (it - 1) / o["conj_max"])
        th.set_fluid(h_at, Tref_at, keys)
        th.solve()
        say(f"Heat exchange, iteration {it}: the fluid", 0.35 + 0.6 * (it - 0.5) / o["conj_max"])
        hres = fl.solve_temperature(Tw_at)
        wall = _edge_values(hres, keys, "wall")
        q_max = max(float(np.max(np.abs(np.concatenate([tb["q_a"], tb["q_m"], tb["q_b"]])))) for tb in wall.values())
        T_new, q_new, mism, dT = {}, {}, 0.0, 0.0
        for k in keys:
            tb = wall[k]
            T_new[k] = (tb["T_a"], tb["T_m"], tb["T_b"])
            q_new[k] = (tb["q_a"], tb["q_m"], tb["q_b"])
            for Tn, To, qn, qo, h in zip(T_new[k], Tw_vals[k], q_new[k], q_vals[k], h_lin[k]):
                # what the solid took at the wall nodes (q_prev + h (T - T_prev), at the temperature the fluid was just given) against what the fluid gave
                mism = max(mism, float(np.max(np.abs(qn - qo - h * (Tn - To)))))
        mism = mism / max(q_max, 1e-300)
        Tw_all = np.concatenate([np.concatenate([wall[k]["T_a"], wall[k]["T_m"], wall[k]["T_b"]]) for k in keys])
        if prev is not None and len(prev) == len(Tw_all):
            dT = float(np.max(np.abs(Tw_all - prev)))
        prev = Tw_all
        history.append({"it": it, "mismatch": mism, "dT": dT, "omega": omega, "Tw_min": float(Tw_all.min()), "Tw_max": float(Tw_all.max())})
        if mism <= o["conj_tol"]:
            converged = True
            break
        if len(history) >= 3 and history[-1]["mismatch"] > history[-2]["mismatch"] > history[-3]["mismatch"]:
            omega = max(0.2, 0.5 * omega)                                             # growing for two iterations in a row: take smaller steps
        Tw_vals = {k: tuple(old + omega * (new - old) for new, old in zip(T_new[k], Tw_vals[k])) for k in keys}
        q_vals = {k: tuple(old + omega * (new - old) for new, old in zip(q_new[k], q_vals[k])) for k in keys}
        Tw_prof, q_prof = fl.profile(Tw_vals), fl.profile(q_vals)
    Q_fluid = float(sum(wall[k]["Q"] for k in keys)) * float(th.thickness)               # W: the fluid result is per metre of depth, the solid has its thickness
    Q_solid = float(th.heat_to_fluid())
    scale = max(abs(Q_fluid), abs(Q_solid), 1e-300)
    Q_rel = (Q_solid - Q_fluid) / scale
    gap_f, gap_s = max(gaps["h_max"], gaps["Tref_max"]), gaps["T_wall_max"]
    Tw_end = np.concatenate([np.concatenate([wall[k]["T_a"], wall[k]["T_b"]]) for k in keys])
    return {"Tw": Tw_end, "wall_points": int(sum(len(wall[k]["T_a"]) for k in keys)), "converged": converged, "iterations": len(history), "history": history, "mismatch": history[-1]["mismatch"], "tol": o["conj_tol"],
            "Q_solid": Q_solid, "Q_fluid": Q_fluid, "Q_rel": Q_rel, "q_tol": o["q_tol"], "gap_fluid": gap_f, "gap_solid": gap_s, "h": hvals, "h_lin": h_lin, "flow": flow, "heat": hres,
            "keys": keys, "T_in": T_in, "h_max": hmax}
