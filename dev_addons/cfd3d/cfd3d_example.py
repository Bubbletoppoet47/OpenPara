"""cfd3d_example.py - what is there to TEST the 3D Fluid Flow add-on with, and what to send back when something goes wrong.

  load_example(win)        makes a project in a new folder and opens it in the window: a block of aluminium-sized proportions (30 x 20 x 16 mm) with a
                           round hole through it, in air flowing at about Reynolds number 100, with a hot top face (wall temperature), a heated side face (wall heat
                           flux) and an adiabatic bottom.  Press Solve (a few minutes on a slow computer), then Run self-check.
  self_check()             solves small problems whose answer is known (plane Poiseuille flow between plates, flow in a round pipe, a uniform flow, heat put
                           into a flowing fluid, the iterative solver against the direct one, and a cube in air: the drag is proportional to the speed at a
                           very low speed, and the same for two directions of the flow) and returns the numbers side by side with PASS / FAIL.  It needs no
                           window.
  check_example(res, info) what can be said of the example's result without a closed form: the mass and energy balance, the drag along the flow, the heat of
                           the conditions against the heat carried away, the temperature between the inflow and the wall temperatures.
  diagnostics_text(win)    the report: computer and program, geometry, setup in plain numbers, mesh, time of every stage, solver, result, self-check and
                           every message the window gave.
"""
import os
import shutil
import tempfile
import time

import numpy as np

import cfd3d_flow as cf
import cfd3d_mesh as cmesh
import cfd3d_model as cm
import solid_diag
import solid_fem as fem
import solid_geom as sg
import solid_model as sm

EXAMPLE_NAME = "3D Fluid Flow test example"
EXAMPLE = {"speed": 0.05, "T_in": 293.15, "T_wall": 333.15, "q_side": 50.0, "h": 2.0}
RE_LIMIT_NOTE = "A first-order method: the numbers move with the mesh, which is why the tolerances are as wide as they are."


# ====================================================================================================================== the example project
def build_part(folder):
    """Writes the part of the example into `folder` -> its path (.gpd): a 30 x 20 x 16 mm block with a 10 mm hole through it (along its short side)."""
    import pm_model as pm
    import sk_tools as sk
    os.makedirs(folder, exist_ok=True)
    d = pm.Document()
    d.params = {}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (30, 20))
    sk.add_circle(m, (15, 10), (20, 10))
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="16"))
    d.rebuild()
    if d.solid is None:
        raise RuntimeError(f"the part of the example could not be built: {d.status}")
    d.material = {"name": "Aluminum 6061", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}
    path = os.path.join(folder, "block_with_hole.gpd")
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return path


def faces_of(g, normal=None, kind=None):
    """The ids of the faces of a geometry with this normal (x, y, z) and / or of this kind ('plane' / 'cylinder')."""
    out = []
    for f in g["faces"]:
        if kind is not None and f["kind"] != kind:
            continue
        if normal is not None and np.linalg.norm(np.asarray(f["normal"]) - np.asarray(normal)) > 1e-6:
            continue
        out.append(f["id"])
    return out


def apply_example(win):
    """Puts the fluid, the flow and the conditions of the test example on the project that holds the part."""
    from solid_base import l_out
    g = win.geom
    S = win.setup
    for key in cm.KEYS:
        S[key] = []
    top, bottom, side = faces_of(g, (0, 0, 1)), faces_of(g, (0, 0, -1)), faces_of(g, (0, -1, 0))
    if not (top and bottom and side):
        raise RuntimeError("the faces of the example part were not found (top, bottom, side)")
    S["flow"].update({"speed": EXAMPLE["speed"], "dir": "+x", "heat": True, "T_in": EXAMPLE["T_in"]})
    ok = [win.add_condition("temps", {"T": EXAMPLE["T_wall"]}, top, "Hot top face"),
          win.add_condition("fluxes", {"q": EXAMPLE["q_side"]}, side, "Heated side"),
          win.add_condition("ins", {}, bottom, "Insulated bottom")]
    if not all(ok):
        raise RuntimeError("the conditions of the test example could not be put on the faces: " + win.status_lbl.text())
    win.fill_part_sizes()
    win.set_size(format(l_out(EXAMPLE["h"]), ".6g"))
    win.put_physics()
    win.refresh_lists()
    win.invalidate(mesh=True)
    win.colour()
    win.example_info = {"volume_mm3": float(g["volume"]), "speed": EXAMPLE["speed"], "T_in": EXAMPLE["T_in"], "T_wall": EXAMPLE["T_wall"], "q_side": EXAMPLE["q_side"],
                        "side_area_mm2": float(sum(g["faces"][f]["area"] for f in side)), "top_area_mm2": float(sum(g["faces"][f]["area"] for f in top))}
    return True


def load_example(win, folder=None):
    """Makes the test project in a new project folder (asked for unless `folder` is given) and opens it in `win`.  -> True when it is loaded."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    import sim_project
    if win.geom is not None and win.is_dirty():
        if QMessageBox.question(win, "Test example", "This window has changes that are not saved, and the example replaces what it shows. "
                                                    "Load the example anyway? (The changes are lost; the project on disk is not touched.)") != QMessageBox.StandardButton.Yes:
            return False
    if folder is None:
        start = sim_project.default_name(win.kind, EXAMPLE_NAME, os.getcwd())
        folder, _ = QFileDialog.getSaveFileName(win, f"New {win.label} project for the test example (a folder)", start,
                                                f"{win.label} project (*{sim_project.ext_of(win.kind)})")
        if not folder:
            return False
    scratch = tempfile.mkdtemp(prefix="opara_f3_example_")
    try:
        try:
            part = build_part(scratch)
        except Exception as ex:                                                  # noqa: BLE001 - shown, not raised into the event loop
            QMessageBox.warning(win, "Test example", f"The part of the example could not be built: {ex}")
            win.log_event("error", f"load_example: building the part: {ex!r}")
            return False
        if not win.create_project(folder):
            return False
        if not win.import_file(part):
            win.say("The part of the example could not be imported: " + win.status_lbl.text())
            return False
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    try:
        apply_example(win)
    except Exception as ex:                                                      # noqa: BLE001
        import traceback
        win.log_event("error", "load_example: " + traceback.format_exc())
        QMessageBox.warning(win, "Test example", f"The example was imported but its conditions could not be set: {ex}")
        return False
    win.save()
    win.say("The test example is loaded: press Solve, then Run self-check, then Diagnostics report...")
    return True


# ====================================================================================================================== checks with known answers
class Row:
    """One line of the self-check: what was computed, what it should be, how far apart they may be."""

    def __init__(self, group, name, got, want, tol, unit="", relative=True, note=""):
        self.group, self.name, self.got, self.want, self.tol, self.unit, self.relative, self.note = group, name, float(got), float(want), float(tol), unit, relative, note
        diff = abs(self.got - self.want)
        self.error = diff / max(abs(self.want), 1e-300) if relative else diff
        self.ok = bool(np.isfinite(self.got) and self.error <= self.tol)

    def line(self):
        err = f"{self.error:.2e}" + ("" if self.relative else f" {self.unit}")
        tol = f"{self.tol:.0e}" + ("" if self.relative else f" {self.unit}")
        return (f"{'PASS' if self.ok else 'FAIL'}  {self.group}: {self.name}   got {self.got:.8g}   expected {self.want:.8g} {self.unit}   "
                f"error {err} (allowed {tol}){'   ' + self.note if self.note else ''}")

    def as_dict(self):
        return {"group": self.group, "name": self.name, "got": self.got, "want": self.want, "tol": self.tol, "unit": self.unit, "ok": self.ok, "error": self.error,
                "relative": self.relative}


def below(group, name, got, limit, unit="", note=""):
    """A row that passes when `got` <= `limit` (the number shown as 'expected' is the limit)."""
    r = Row(group, name, got, limit, 0.0, unit, relative=False, note=note or f"must be at most {limit:.4g}")
    r.ok = bool(np.isfinite(r.got) and r.got <= limit)
    return r


def truth(group, name, cond, note=""):
    """A row that passes when `cond` holds (1 against 1)."""
    return Row(group, name, 1.0 if cond else 0.0, 1.0, 0.0, "", relative=False, note=note)


# the channel and the pipe of the tests: lengths in metres, a fluid of kinematic viscosity 0.1 and density 1 (so that the numbers are simple)
CL, CW, CH, NU, U = 4.0, 1.0, 1.0, 0.1, 1.0


def _poiseuille(pts):
    z = pts[:, 2] / CH
    out = np.zeros((len(pts), 3))
    out[:, 0] = 6.0 * U * z * (1.0 - z)
    return out


def _channel_spec(**kw):
    s = {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"x-": _poiseuille}, "outlet": ["x+"], "slip": ["y-", "y+"], "wall": ["z-", "z+"]}
    s.update(kw)
    return s


def _slab(res, x0, tol):
    return np.abs(res["disc"].x[:, 0] - x0) < tol


def _sound(group, res, steps_note=""):
    return truth(group, "the flow settled to a steady state", res["status"] == "converged", f"{res['status']} after {res['steps']} steps {steps_note}".strip())


def check_uniform(say, cancel):
    """A uniform inflow in a box with slip sides: nothing in the way, so the flow stays uniform and the pressure stays zero."""
    q = cmesh.channel(CL, CW, CH, 0.25, cancel=cancel)
    res = cf.solve_flow(q, {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"x-": [1.0, 0, 0]}, "outlet": ["x+"], "slip": ["y-", "y+", "z-", "z+"]}, cancel=cancel)
    return [_sound("uniform flow", res),
            Row("uniform flow", "largest departure of the velocity from the inflow", float(np.abs(res["u"] - [1.0, 0, 0]).max()), 0.0, 1e-5, "m/s", relative=False),
            Row("uniform flow", "largest pressure", float(np.abs(res["p"]).max()), 0.0, 1e-5, "Pa/rho", relative=False),
            Row("uniform flow", "flow rate in", res["mass"]["in"], CW * CH, 1e-9, "m3/s")]


def check_channel(say, cancel):
    """Plane Poiseuille flow between two plates: the pressure falls by 12 nu U / H2 per metre, the centre line runs at 1.5 U, the plates carry the drag."""
    q = cmesh.channel(CL, CW, CH, 0.125, cancel=cancel)
    res = cf.solve_flow(q, _channel_spec(), cancel=cancel)
    x = res["disc"].x[:, 0]
    p, u = res["p"], res["u"]
    dpdx = (p[np.abs(x - 3.0) < 0.05].mean() - p[np.abs(x - 1.0) < 0.05].mean()) / 2.0
    F = cf.wall_force(res, ["z-", "z+"])["total"]
    return [_sound("plane Poiseuille flow", res),
            Row("plane Poiseuille flow", "pressure gradient, -12 nu U / H2", dpdx, -12.0 * NU * U / CH ** 2, 0.03, "Pa/rho/m"),
            Row("plane Poiseuille flow", "speed on the centre line, 1.5 U", float(u[_slab(res, 2.0, 0.05), 0].max()), 1.5 * U, 0.04, "m/s"),
            Row("plane Poiseuille flow", "drag on the two plates, (dp/dx) L W H", F[0], 12.0 * NU * U / CH ** 2 * CL * CW * CH, 0.03, "N/rho"),
            Row("plane Poiseuille flow", "force across the flow on the plates (they push away from each other)", abs(F[2]), 0.0, 0.01 * abs(F[0]), "N/rho", relative=False),
            Row("plane Poiseuille flow", "mass balance (flow in - flow out) / flow in", res["mass"]["mismatch"], 0.0, 0.02, "", relative=False),
            Row("plane Poiseuille flow", "speed on a no-slip wall", float(np.abs(u[np.isin(np.arange(len(x)), res["boundary"].wall_nodes)]).max()), 0.0, 0.0, "m/s",
                relative=False, note="exactly zero"),
            Row("plane Poiseuille flow", "pressure on the outlet", float(np.abs(p[res["boundary"].outlet_nodes]).max()), 0.0, 0.0, "Pa/rho", relative=False, note="exactly zero")]


def check_pipe(say, cancel):
    """Poiseuille flow in a round pipe (curved wall): dp/dx = -8 mu U / R2 and the drag on the wall is dp/dx times the volume."""
    R, L = 0.5, 4.0

    def profile(pts):
        out = np.zeros((len(pts), 3))
        out[:, 0] = 2.0 * U * np.maximum(1.0 - (pts[:, 1] ** 2 + pts[:, 2] ** 2) / R ** 2, 0.0)
        return out

    q = cmesh.pipe(R, L, 0.1, cancel=cancel)
    res = cf.solve_flow(q, {"lscale": 1.0, "nu": NU, "rho": 1.0, "inlet": {"inlet": profile}, "outlet": ["outlet"], "wall": ["wall"]}, cancel=cancel)
    x = res["disc"].x[:, 0]
    dpdx = (res["p"][np.abs(x - 3.0) < 0.04].mean() - res["p"][np.abs(x - 1.0) < 0.04].mean()) / 2.0
    F = cf.wall_force(res, ["wall"])["total"]
    return [_sound("flow in a round pipe", res),
            Row("flow in a round pipe", "pressure gradient, -8 mu U / R2 (five elements across the radius)", dpdx, -8.0 * NU * U / R ** 2, 0.06, "Pa/rho/m"),
            Row("flow in a round pipe", "drag on the wall, (dp/dx) L pi R2", F[0], 8.0 * NU * U / R ** 2 * L * np.pi * R ** 2, 0.07, "N/rho"),
            Row("flow in a round pipe", "force across the flow on the wall", float(np.hypot(F[1], F[2])), 0.0, 0.01 * abs(F[0]), "N/rho", relative=False),
            Row("flow in a round pipe", "mass balance", res["mass"]["mismatch"], 0.0, 0.05, "", relative=False)]


def check_heat(say, cancel):
    """The temperature of the fluid: a fluid at the temperature of its walls stays there; heat put in through the walls is carried away (energy balance) and
    the mixed-cup temperature at the outlet is that heat divided by (mass flow x specific heat)."""
    q = cmesh.channel(CL, CW, CH, 0.125, cancel=cancel)
    cold = cf.solve_flow(q, _channel_spec(heat=True, k=0.2, cp=1.0, T_in=5.0, wall_T={"z-": 5.0, "z+": 5.0}), cancel=cancel)
    QH = 2.0
    hot = cf.solve_flow(q, _channel_spec(heat=True, k=0.2, cp=1.0, T_in=0.0, wall_q={"z-": QH, "z+": QH}), cancel=cancel)
    en = hot["energy"]
    av = hot["boundary"].faces("x+")[1]
    tri = hot["boundary"].patches["x+"]
    mixed = cf._face_product(av, tri, hot["T"], hot["u"]).sum() / cf._face_product(av, tri, np.ones(len(hot["T"])), hot["u"]).sum()
    return [Row("heat in the fluid", "a fluid at the temperature of its walls: largest departure", float(np.abs(cold["T"] - 5.0).max()), 0.0, 1e-9, "K", relative=False),
            Row("heat in the fluid", "heat from the walls into that fluid", cold["energy"]["walls"], 0.0, 1e-9, "W", relative=False),
            Row("heat in the fluid", "heat put in = flux x area of the two walls", hot["heat"]["flux_in"], QH * 2 * CL * CW, 1e-9, "W"),
            Row("heat in the fluid", "energy balance: walls against carried away", en["mismatch"], 0.0, 0.03, "", relative=False),
            Row("heat in the fluid", "mixed-cup temperature at the outlet, heat / (m cp)", mixed, en["walls"] / (hot["mass"]["out"] * 1.0 * 1.0), 0.03, "K")]


def check_iterative(say, cancel):
    """The iterative solver (GMRES with an incomplete LU, used for the big meshes) against the direct one on the channel."""
    q = cmesh.channel(CL, CW, CH, 0.125, cancel=cancel)
    a = cf.solve_flow(q, _channel_spec(), cancel=cancel)
    b = cf.solve_flow(q, _channel_spec(), cancel=cancel, direct_limit=1000)
    return [truth("iterative solver", "the iterative solver was used", b["solver"] == "gmres+ilu", b["solver"]),
            _sound("iterative solver", b),
            Row("iterative solver", "largest difference of the velocity from the direct solver", float(np.abs(a["u"] - b["u"]).max()), 0.0, 1e-4, "m/s", relative=False)]


def _cube_run(g, speed, dirn="+x", h=2.5):
    s = cm.default_setup()
    s["flow"].update({"speed": speed, "dir": dirn})
    s["h"] = float(h)
    why = cm.check_ready(s, g)
    if why:
        raise fem.FemError(why)
    return cm.run(g, cm.resolve(g, s), {})


def _front_back(g, res):
    """Mean pressure (Pa) on the face of a cube that looks into the flow (+x) minus that on the face that looks away from it."""
    pat = res["mesh"]["patches"]

    def mean_p(normal):
        fid = next(f["id"] for f in g["faces"] if np.linalg.norm(np.asarray(f["normal"]) - np.asarray(normal)) < 1e-6)
        return float(res["p"][np.unique(pat[fid])].mean())
    return mean_p((-1, 0, 0)) - mean_p((1, 0, 0))


def check_cube(say, cancel):
    """A 10 mm cube in air, through the same path as the window (box, air mesh, matched faces, forces): at a very low speed the flow is Stokes flow and the
    drag is proportional to the speed; the same cube in another direction of the flow gets the same drag."""
    import build123d as b
    g = sg.analyze(b.Box(10, 10, 10), None)
    slow, fast = _cube_run(g, 0.0002), _cube_run(g, 0.0004)
    other = _cube_run(g, 0.0004, "+y")
    ds, df, do = slow["summary"]["drag"], fast["summary"]["drag"], other["summary"]["drag"]
    return [_sound("a cube in air", slow, "(very slow flow)"),
            Row("a cube in air", "drag at twice the speed / drag (Stokes flow: the ratio is 2)", df / ds, 2.0, 0.005, "",
                note="at ten times this speed the ratio is 2.07: the cell Reynolds number of a first-order method"),
            Row("a cube in air", "the same drag for the flow along +y and along +x", do, df, 0.03, "N"),
            Row("a cube in air", "force across the flow / drag", float(np.linalg.norm(fast["summary"]["side"])) / df, 0.0, 0.01, "", relative=False),
            Row("a cube in air", "mass balance", max(slow["mass"]["mismatch"], fast["mass"]["mismatch"]), 0.0, 0.01, "", relative=False),
            truth("a cube in air", "the pressure is higher on the face towards the flow than on the face away from it", _front_back(g, fast) > 0.0,
                  "mean pressure of the front face minus that of the back face: %.4g Pa" % _front_back(g, fast))]


CHECKS = [("A uniform flow", check_uniform), ("Flow between two plates", check_channel), ("Flow in a round pipe", check_pipe),
          ("Heat put into a flowing fluid", check_heat), ("The iterative solver against the direct one", check_iterative),
          ("A cube in air: the part, its forces, the directions", check_cube)]


def self_check(progress=None, cancel=None):
    """Runs every problem with a known answer.  -> {"rows": [Row ...], "errors": [text ...], "timings": [(title, seconds) ...], "seconds": ...}.  A problem
    that fails to run is an error (with its full traceback) and a failing row, so it counts as a failure."""
    t0 = time.monotonic()
    rows, errors, timings = [], [], []
    cancel = cancel or (lambda: False)
    for title, fn in CHECKS:
        if cancel():
            raise fem.Cancelled()
        if progress is not None:
            progress(f"Self-check: {title}")
        t = time.monotonic()
        try:
            rows.extend(fn((lambda txt: None), cancel))
        except (fem.Cancelled, cf.Cancelled):
            raise
        except Exception as ex:                                                  # noqa: BLE001 - a check that cannot run is reported as such
            import traceback
            errors.append(f"{title}: {type(ex).__name__}: {ex}\n{traceback.format_exc()}")
            rows.append(Row(title, "the check could not be run", 0.0, 1.0, 0.0, "", relative=False, note=f"{type(ex).__name__}: {ex}"))
        timings.append((title, time.monotonic() - t))
    return {"rows": rows, "errors": errors, "timings": timings, "seconds": time.monotonic() - t0}


def check_example(res, info):
    """Checks of the result of the test example that need no closed form.  -> [Row]."""
    g = "test example"
    s = res["summary"]
    run = res["run"]
    rows = [_sound(g, res), Row(g, "mass balance (flow in - flow out) / flow in", s["mass"]["mismatch"], 0.0, 0.02, "", relative=False)]
    rows.append(Row(g, "Reynolds number (size of the part, 30 mm)", s["Re"], 100.0, 0.05, "", note="the example is made for about 100"))
    rows.append(truth(g, "the air pushes the part along the flow (drag > 0)", s["drag"] > 0, f"{s['drag']:.4e} N"))
    rows.append(Row(g, "force across the flow / drag (sideways, y)", float(abs(s["side"][1])) / max(abs(s["drag"]), 1e-300), 0.0, 0.05,
                    "", relative=False, note="the part is symmetric left to right (y); the mesh is not exactly"))
    rows.append(Row(g, "drag = pressure part + friction part", s["drag_pressure"] + s["drag_viscous"], s["drag"], 1e-9, "N"))
    if "T" in res:
        span = info["T_wall"] - info["T_in"]
        under = info["T_in"] - s["T_min"]
        over = s["T_max"] - info["T_wall"]
        rows.append(below(g, "the air is not colder than the inflow by more than 8 % of the temperature range", under, 0.08 * span, "K",
                          f"lowest {s['T_min']:.3f} K, inflow {info['T_in']:.2f} K (a first-order method undershoots a little on a coarse mesh)"))
        rows.append(below(g, "the air is not hotter than the hot face by more than 8 % of the range", over, 0.08 * span, "K", f"highest {s['T_max']:.3f} K"))
        en = s["energy"]
        rows.append(below(g, "energy balance: heat from the walls against heat carried away (as a share of the larger)", en["mismatch"], cm.ENERGY_COARSE, "",
                          f"{en['mismatch'] * 100:.1f} %: the method is first order, so this is the mesh near the part showing - it was 27, 23, 19 and 15 % with elements of 3, 2, "
                          "1.5 and 1 mm when this example was made; far above that means something is wrong"))
        hot = next((f for f in s["flows"] if f["name"] == "Hot top face"), None)
        heated = next((f for f in s["flows"] if f["name"] == "Heated side"), None)
        rows.append(truth(g, "the hot top face heats the air (heat > 0)", hot is not None and hot["Q"] > 0, f"{hot['Q']:.4e} W" if hot else "not found"))
        rows.append(Row(g, "the heat of the side face = flux x its area", heated["Q"] if heated else float("nan"), info["q_side"] * info["side_area_mm2"] * 1e-6, 1e-6, "W"))
        if hot is not None and heated is not None:
            rows.append(Row(g, "the heat of the two conditions = the heat from the walls (the bottom is insulated)", hot["Q"] + heated["Q"], en["walls"], 0.02, "W"))
    q = res["mesh"]
    if info.get("volume_mm3"):
        box = np.asarray(run["hi"], float) - np.asarray(run["lo"], float)
        vol_air = float(res["disc"].V.sum()) * 1e9
        rows.append(Row(g, "volume of the air mesh = volume of the box - volume of the part", vol_air, float(np.prod(box)) - info["volume_mm3"], 5e-3, "mm3",
                        note="straight-sided tetrahedra on the curved hole"))
    rows.append(truth(g, "every surface of the part was matched to a face", not q.get("unmatched"), str(q.get("unmatched") or "")))
    return rows


def rows_text(rows):
    return [r.line() for r in rows]


def summary_text(out):
    rows = out["rows"]
    bad = [r for r in rows if not r.ok]
    return f"{len(rows) - len(bad)} of {len(rows)} checks passed" + (f", {len(bad)} FAILED" if bad else "") + f" ({out['seconds']:.1f} s)"


def html_of(out, extra=None):
    """The self-check as the small table the window shows (the numbers side by side)."""
    import sim_report as R
    rows = list(out["rows"]) + list(extra or [])
    html = R.heading("Self-check", summary_text(dict(out, rows=rows)))
    grp = None
    body = []
    for r in rows:
        if r.group != grp:
            if body:
                html += R.grid(["", "got", "expected", "error"], body)
                body = []
            html += R.subhead(r.group)
            grp = r.group
        err = f"{r.error:.1e}" if r.relative else f"{r.error:.2g} {r.unit}"
        body.append([f"{R.chip('PASS', 'ok') if r.ok else R.chip('FAIL', 'bad')} {r.name}", R.num(r.got, 7), R.num(r.want, 7), err])
    if body:
        html += R.grid(["", "got", "expected", "error"], body)
    for e in out.get("errors") or []:
        html += R.note(e.splitlines()[0], R.RED)
    return html


def run_self_check(win):
    """The window's Run self-check button: the problems run as a job (the window stays alive), the table is shown under the button and kept for the report."""
    def work(progress, cancel):
        return self_check(progress, cancel)

    def done(out):
        extra = []
        if win.result is not None and win.example_info is not None:
            extra = check_example(win.result, win.example_info)
        out["extra"] = extra
        win.check_rows = out
        win.check_lbl.setText(html_of(out, extra))
        win.say(summary_text(dict(out, rows=out["rows"] + extra)))
        for r in out["rows"] + extra:
            if not r.ok:
                win.log_event("check", r.line())
        for e in out["errors"]:
            win.log_event("error", e)
    return win.run_job(work, done, "Self-check")


# ====================================================================================================================== the report
def _cond_lines(win):
    L = []
    for key in cm.KEYS:
        for i, c in enumerate(win.setup.get(key) or []):
            nm = sm.name_of(cm.NAMES[key], i, c)
            vals = {k: c[k] for k in cm.VALUES[key]}
            try:
                fids = sm._fids(win.geom, c["faces"], nm) if win.geom is not None else []
                area = sum(win.geom["faces"][f]["area"] for f in fids)
                where = f"{len(fids)} face(s), {area:.6g} mm2"
            except fem.FemError as ex:
                where = f"FACES LOST: {ex}"
            L.append(f"  {nm}: {cm.NAMES[key]} {vals} on {where}")
    return L or ["  none"]


def diagnostics_text(win):
    """The whole state of a 3D Fluid Flow window as plain text (see solid_diag for the parts every 3D window shares)."""
    L = solid_diag.program_lines("3D FLUID FLOW - DIAGNOSTICS REPORT")
    try:
        import unitctl
        from solid_base import UD
        from cfd3d_tab import pressure_unit
        fam = win.family()
        L.append(f"units: system {unitctl.system()} (lengths in {UD()['L']}, speed in {UD()['V']}, pressure in {pressure_unit()[0]}), heat transfer {fam.name}, temperature shown in {fam.temp}")
    except Exception as ex:                                                      # noqa: BLE001
        L.append(f"units: unknown ({ex})")
    L += solid_diag.section("Project", [f"folder: {win.path or 'none yet'}", f"saved setup equals the screen: {'yes' if not win.is_dirty() else 'NO - changes not saved'}",
                                        f"example loaded: {'yes' if win.example_info else 'no'}"])
    L += solid_diag.section("Geometry", solid_diag.geometry_lines(win))
    S = win.setup
    sl = []
    f, fl, dom = S["fluid"], S["flow"], S["domain"]
    sl.append(f"fluid: {f.get('name')}: density {float(f['rho']):.6g} kg/m3, viscosity {float(f['mu']):.6g} Pa s, conductivity {float(f.get('k') or 0):.6g} W/(m K), "
              f"specific heat {float(f.get('cp') or 0):.6g} J/(kg K)")
    sl.append(f"flow: speed {float(fl['speed']):.6g} m/s {cm.DIR_TEXT.get(fl.get('dir'), fl.get('dir'))}; temperature solved: {'yes, inflow ' + format(float(fl.get('T_in') or 0), '.4f') + ' K' if fl.get('heat') else 'no'}")
    sl.append(f"domain: margins {dom['up']:.6g} upstream, {dom['down']:.6g} downstream, {dom['side']:.6g} at the sides (x the largest size of the part); far element size "
              f"{('%.6g mm' % dom['h_far']) if dom.get('h_far') else 'automatic'}")
    sl.append("conditions (SI: K, W/m2):")
    sl += _cond_lines(win)
    sl.append(f"element size on the part asked for: {('%.6g mm' % S['h']) if S.get('h') else 'automatic'}; mesh options: {S.get('mesh')}")
    try:
        if win.geom is not None:
            sl.append("ready to solve: " + (cm.check_ready(S, win.geom) or "yes"))
            h_near, h_far = cm.sizes_mm(win.geom, S)
            lo, hi = cm.domain_box(win.geom, S)
            sl.append(f"sizes used: {h_near:.6g} mm on the part, {h_far:.6g} mm far away; box {np.round(lo, 4).tolist()} to {np.round(hi, 4).tolist()} mm; about "
                      f"{cm.estimate_nodes(win.geom, S):,} nodes expected")
            sl.append("warnings before the solve: " + ("; ".join(cm.notes(S, win.geom)) or "none"))
        else:
            sl.append("ready to solve: no part")
    except Exception as ex:                                                      # noqa: BLE001
        sl.append(f"ready to solve: could not tell ({type(ex).__name__}: {ex})")
    L += solid_diag.section("Setup", sl)
    L += solid_diag.section("Mesh", solid_diag.mesh_lines(win.mesh_q, None, S.get("mesh")))
    L += solid_diag.section("Jobs and the time of every stage", solid_diag.jobs_lines(win.job_log))
    r = win.result
    if r is None:
        L += solid_diag.section("Result", ["Not solved yet."])
    else:
        s = r["summary"]
        mb = s["mass"]
        rl = [f"{r['status']} after {r['steps']} steps; {len(r['mesh']['tets']):,} tetrahedra, {len(r['mesh']['nodes']):,} nodes (linear), {r['unknowns']:,} unknowns; solver {r['solver']}; {r['seconds']:.2f} s",
              f"last changes of the pseudo-time steps: {[float('%.3g' % x) for x in r['history'][-6:]]}",
              f"Reynolds number {s['Re']:.4g} (size of the part {s['length_m'] * 1e3:.4g} mm); highest speed {s['speed_max']:.6g} m/s",
              f"force on the part N: total {np.round(s['force'], 12).tolist()}, pressure {np.round(s['force_pressure'], 12).tolist()}, friction {np.round(s['force_viscous'], 12).tolist()}",
              f"drag {s['drag']:.8g} N (pressure {s['drag_pressure']:.8g}, friction {s['drag_viscous']:.8g}); side force {np.round(s['side'], 12).tolist()}; drag coefficient {s['Cd']:.5g} on the "
              f"front area {s['area_front_m2'] * 1e6:.6g} mm2 (wetted area {s['area_wall_m2'] * 1e6:.6g} mm2)",
              f"pressure range {s['p_min']:.6g} to {s['p_max']:.6g} Pa; mass balance: in {mb['in']:.8g}, out {mb['out']:.8g} m3/s, mismatch {mb['mismatch']:.3e}"]
        if "T" in r:
            en = s["energy"]
            rl.append(f"temperature K: {s['T_min']:.6g} to {s['T_max']:.6g}; energy: walls {en['walls']:.8g} W, carried away {en['gain']:.8g} W, mismatch {en['mismatch']:.3e}")
            rl += [f"  {x['name']} ({x['kind']}): {x['Q']:.8g} W over {x['area_m2'] * 1e6:.6g} mm2" for x in s["flows"]]
        q = r["mesh"]
        rl.append(f"surfaces of the part that were not matched to a face: {q.get('unmatched') or 'none'}")
        L += solid_diag.section("Result", rl)
    cr = win.check_rows
    if cr is None:
        L += solid_diag.section("Self-check", ["Not run in this window yet (press Run self-check)."])
    else:
        L += solid_diag.section("Self-check", [summary_text(dict(cr, rows=cr["rows"] + cr.get("extra", [])))] + rows_text(cr["rows"] + cr.get("extra", []))
                                + ["time of each problem: " + "; ".join(f"{t} {s:.2f} s" for t, s in cr.get("timings") or [])] + [e for e in cr.get("errors") or []])
    L += solid_diag.section("Messages (oldest first; errors in full)", solid_diag.events_lines(win.events))
    return "\n".join(L) + "\n"
