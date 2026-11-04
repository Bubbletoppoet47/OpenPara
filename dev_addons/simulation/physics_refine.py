"""Automatic mesh refinement for the FEA and CFD tabs.

Solve, estimate where the error is largest, refine the mesh there, solve again - until the monitored values stop changing
(by less than physics_geom.MESH_TOL between two meshes) or a limit the user set is reached.

  FEA monitors : strain energy and the largest displacement.
  CFD monitors : the force on the bodies along and across the wind.  A CFD pass is only judged (and refined) if the time
                 marching of that pass converged; refining a mesh on a run that never settled would only add noise.
"""
import physics_cfd as pcfd
import physics_fea as pf
import physics_geom as pg

import numpy as np


def _rel(a, b, scale=None):
    scale = abs(b) if scale is None else scale
    return abs(a - b) / max(scale, 1e-300)


def fea_auto(m, geom, included, h, mesh, mat, supports, loads, max_passes, max_tris, progress=None, cancel=None):
    """-> {"mesh", "result", "log", "reason"}.  `mesh` is the pass-0 mesh the user already made."""
    def tick(txt, f):
        if cancel and cancel():
            raise pf.Cancelled()
        if progress:
            progress(txt, f)

    log, prev, res, reason = [], None, None, ""
    lin_mat = dict(mat, nl_on=False)                 # the refinement passes are linear; the nonlinear solve is done once, at the end
    floor = float(mesh["stats"]["edge_min"]) * 0.5 ** max_passes * 0.9
    total = max_passes + 1
    for k in range(total):
        base = k / total
        res = pf.solve(mesh, lin_mat, supports, loads,
                       progress=lambda t, f, base=base, k=k: tick(f"Pass {k} of {max_passes}: {t}", base + f * 0.7 / total),
                       cancel=cancel)
        umax = float(np.max(np.hypot(res["u"][:, 0], res["u"][:, 1])))
        entry = {"pass": k, "n_tris": int(len(mesh["tris"])), "energy": float(res["energy"]), "umax": umax,
                 "vmax": float(np.max(res["vm"])), "change": None}
        log.append(entry)
        if prev is not None:
            entry["change"] = max(_rel(res["energy"], prev[0]), _rel(umax, prev[1]))
            if entry["change"] < pg.MESH_TOL:
                reason = "converged"
                break
        prev = (float(res["energy"]), umax)
        if k == max_passes:
            reason = "max_passes"
            break
        tick(f"Pass {k} of {max_passes}: refining the mesh", base + 0.75 / total)
        vm = res.get("mesh") or mesh                 # a quadratic result lives on a mesh of 4 small triangles per element
        ind = pg.fea_indicator(vm["nodes"], vm["tris"], res)
        if vm is not mesh:
            ind = np.bincount(vm["parent"], weights=ind, minlength=len(mesh["tris"]))
        marked = pg.mark_elements(ind)
        sizes = pg.refined_sizes(mesh["nodes"], mesh["tris"], marked, floor=floor)
        new = pg.mesh_faces(m, geom, included, h, None, cancel, refine={"nodes": mesh["nodes"], "tris": mesh["tris"], "sizes": sizes})
        if new["stats"]["n_tris"] > max_tris:
            log.append({"pass": k + 1, "n_tris": int(new["stats"]["n_tris"]), "skipped": True})
            reason = "max_tris"
            break
        mesh = new
    if mat.get("nl_on"):
        lim, frac, sy = mat.get("nl_disp"), mat.get("nl_yield"), float(mat.get("sy") or 0.0)
        hit = (not mat.get("lin_on", True)) or (lim and umax > float(lim)) or (frac and sy > 0 and float(np.max(res["vm"])) > float(frac) * sy)
        if hit:                                      # the final mesh is solved again, nonlinearly (the trigger is tested inside)
            res = pf.solve(mesh, mat, supports, loads, progress=lambda t, f: tick(f"Final nonlinear solve: {t}", 0.8 + 0.2 * f),
                           cancel=cancel)
    return {"mesh": mesh, "result": res, "log": log, "reason": reason}


def cfd_auto(mesh, setup, mesh_args, max_passes, max_tris, progress=None, frame=None, cancel=None, on_mesh=None):
    """-> {"result", "mesh", "log", "reason", "all_history"}.  mesh_args = (model, geom, body ids, margins, h_body, h_far, transition, bl).
    progress / frame as in physics_cfd.solve (the step numbers continue from pass to pass); on_mesh(mesh, pass_no) is called
    whenever a finer mesh replaces the old one."""
    m, geom, ids, margins, hb, hf, tr, bl = mesh_args
    log, prev, reason, all_hist, offset, res = [], None, "", [], 0, None
    if bl and mesh["stats"].get("bl"):
        bl = dict(mesh["stats"]["bl"])          # the boundary layer the first mesh really got (it may have been thinned to fit)
    base_min = 0.5 * (bl["h1"] if bl else hb)
    floor = base_min * 0.5 ** max_passes * 0.9
    for k in range(max_passes + 1):
        st = dict(setup)
        if not st.get("dt"):
            st["h_body"] = setup["h_body"] * 0.7 ** k                 # the automatic time step follows the finer elements
        off = offset
        res = pcfd.solve(mesh, st, progress=(lambda step, mx, *a, off=off: progress(step + off, mx, *a)) if progress else None,
                         frame=frame, cancel=cancel)
        all_hist += [(h[0] + off,) + tuple(h[1:]) for h in res["history"]]
        offset += res["steps"]
        f = res["forces"]
        entry = {"pass": k, "n_tris": int(len(mesh["tris"])), "along": float(f["along"]), "across": float(f["across"]),
                 "status": res["status"], "steps": int(res["steps"]), "change": None}
        log.append(entry)
        if res["status"] != "converged":
            reason = "stopped" if res["status"] == "stopped" else "not_settled"
            break
        if prev is not None:
            scale = max(abs(f["along"]), abs(f["across"]), abs(prev[0]), abs(prev[1]))
            entry["change"] = max(_rel(f["along"], prev[0], scale), _rel(f["across"], prev[1], scale))
            if entry["change"] < pg.MESH_TOL:
                reason = "converged"
                break
        prev = (float(f["along"]), float(f["across"]))
        if k == max_passes:
            reason = "max_passes"
            break
        marked = pg.mark_elements(pcfd.refine_indicator(mesh, res))
        sizes = pg.refined_sizes(mesh["nodes"], mesh["tris"], marked, floor=floor)
        try:
            new = pcfd.mesh_fluid(m, geom, ids, margins, hb, hf, tr, None, cancel, bl=bl,
                                  refine={"nodes": mesh["nodes"], "tris": mesh["tris"], "sizes": sizes, "floor": floor})
        except pg.Cancelled:
            reason = "stopped"
            break
        if new["stats"]["n_tris"] > max_tris:
            log.append({"pass": k + 1, "n_tris": int(new["stats"]["n_tris"]), "skipped": True})
            reason = "max_tris"
            break
        mesh = new
        if bl and mesh["stats"].get("bl"):
            bl = dict(mesh["stats"]["bl"])      # keep a thinned boundary layer for the later passes, so the passes stay comparable
        if on_mesh:
            on_mesh(mesh, k + 1)
    return {"result": res, "mesh": mesh, "log": log, "reason": reason, "all_history": all_hist}


def summary_lines(log, reason, kind):
    """Plain text lines for the result label (kind = 'fea' or 'cfd')."""
    out = []
    for e in log:
        if e.get("skipped"):
            out.append(f"pass {e['pass']}: would have {e['n_tris']:,} triangles - over your limit, not used")
            continue
        ch = "" if e["change"] is None else f", change {100 * e['change']:.2f} %"
        if kind == "fea":
            out.append(f"pass {e['pass']}: {e['n_tris']:,} triangles, energy {e['energy']:.5g}, max |u| {e['umax']:.5g}, "
                       f"max von Mises {e['vmax']:.5g}{ch}")
        else:
            out.append(f"pass {e['pass']}: {e['n_tris']:,} triangles, {e['steps']} steps, force along {e['along']:.5g}, "
                       f"across {e['across']:.5g}{ch}" + ("" if e["status"] == "converged" else f" ({e['status']})"))
    tol = 100 * pg.MESH_TOL
    why = {"converged": f"Mesh converged: the monitored values changed by less than {tol:g} % between the last two meshes.",
           "max_passes": "Stopped at your maximum number of passes - NOT mesh converged.",
           "max_tris": "Stopped at your maximum number of triangles - NOT mesh converged.",
           "stopped": "Stopped by you - NOT mesh converged.",
           "not_settled": "Stopped: the time marching of the last pass did not settle, so the mesh was not refined further."}
    return out, why.get(reason, "")


def resolve_cfd_links(loads, info, fea_geoms, factor):
    """Copies of `loads` where every live CFD link is replaced by a concrete CFD load made from `info` (the CFD tab's transfer_info
    dict: result, edge_geoms, status, walls).  `factor` converts Pa to the FEA unit system.  -> list of loads.
    Raises pf.ModelError when a link needs a CFD result and there is none."""
    out = []
    for ld in loads:
        if ld["kind"] != "cfd" or not ld.get("live"):
            out.append(ld)
            continue
        if info is None:
            raise pf.ModelError("A load takes its pressure from the CFD, but there is no CFD result yet. Solve the flow in the CFD tab "
                                "first, or run the case from the Parameterization tab (it solves the CFD, then the FEA).")
        walls = info["walls"]
        pairs = []
        for pr in ld["pairs"]:
            src, tgt = tuple(pr["source"]), tuple(pr["target"])
            if src not in walls:
                raise pf.ModelError(f"The CFD result has no wall data for CFD edge {src[0]} {src[1]} (is its body switched on, "
                                    "and did the sketch change?).")
            tb = walls[src]
            pairs.append({"target": tgt, "source": src, "fea_geom": fea_geoms[tgt], "table": tb, "factor": factor,
                          "closed": tgt[0] == "ci" and src[0] == "ci",
                          "pmax": float(max(np.max(np.abs(tb["p_a"])), np.max(np.abs(tb["p_b"]))))})
        new = dict(ld)
        new.update({"pairs": pairs, "live": False, "targets": [p["target"] for p in pairs], "converged": info["status"] == "converged"})
        out.append(new)
    return out
