"""thermal3d_example.py - what is there to TEST the 3D Thermal add-on with, and what to send back when something goes wrong.

  load_example(win)        makes a deliberately demanding project in a new folder and opens it in the window: an assembly of four bodies (an aluminium plate
                           with five holes, a copper pad on it that also makes heat inside, a thin stainless fin, a plastic block - conductivities from 0.2 to
                           400 W/(m K)), a fixed temperature on a curved hole face, a heat flow, convection on three different faces, radiation (nonlinear),
                           an insulated face, and a transient run in minutes.  Press Solve, then Run self-check.
  self_check()             solves small problems whose answer is known (a wall, a composite wall, heat generated in a slab, lumped cooling, radiation, a pipe
                           wall with its mesh refinement, the iterative solver against the direct one) and returns the numbers side by side with PASS / FAIL.
                           It needs no window.
  check_example(res, info) what can be said of the example's result without a closed form: the heat balance, the heat generated, the heat flow that was
                           asked for, the temperature range, a hottest point that never cools while heat is only added.
  diagnostics_text(win)    the report: computer and program, geometry, setup in plain numbers, mesh, time of every stage, solver, result, self-check and
                           every message the window gave.
"""
import math
import os
import shutil
import tempfile
import time

import numpy as np

import solid_asm as sasm
import solid_diag
import solid_fem as fem
import solid_geom as sg
import solid_model as sm
import thermal3d_fem as tf
import thermal3d_model as tm

SIGMA = tf.SIGMA
K0 = 273.15
EXAMPLE_NAME = "3D Thermal test example"

# the parts of the example (names as the material library knows them)
AL = {"name": "Aluminum 6061", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0}
CU = {"name": "Copper", "density": 8960.0, "E_MPa": 110000.0, "nu": 0.34, "Sy_MPa": 70.0, "Su_MPa": 220.0}
SS = {"name": "Stainless steel 304", "density": 8000.0, "E_MPa": 193000.0, "nu": 0.29, "Sy_MPa": 215.0, "Su_MPa": 505.0}
ABS = {"name": "ABS plastic", "density": 1050.0, "E_MPa": 2300.0, "nu": 0.35, "Sy_MPa": 40.0, "Su_MPa": 40.0}
EXAMPLE = {"h": 4.0, "t_end": 1800.0, "steps": 30, "frames": 31, "T_fluid": 293.15, "power": 25.0, "gen": 5e5}


# ====================================================================================================================== the example project
def _part(path, shapes, depth, material):
    """A part file: one sketch (rectangles and circles) extruded `depth` mm up from the Top plane."""
    import pm_model as pm
    import sk_tools as sk
    d = pm.Document()
    d.params = {}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    for kind, a, b in shapes:
        (sk.add_rect_corner if kind == "rect" else sk.add_circle)(m, a, b)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth)))
    d.rebuild()
    if d.solid is None:
        raise RuntimeError(f"the part {os.path.basename(path)} could not be built: {d.status}")
    d.material = dict(material)
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return d


def build_sources(folder):
    """Writes the four parts and the assembly into `folder` -> the path of the assembly (.gpa)."""
    import asm_model as am
    os.makedirs(folder, exist_ok=True)
    holes = [("circle", (x, y), (x + 4, y)) for x, y in ((10, 10), (70, 10), (70, 50), (10, 50))] + [("circle", (40, 30), (46, 30))]
    _part(os.path.join(folder, "plate.gpd"), [("rect", (0, 0), (80, 60))] + holes, 6, AL)               # 80 x 60 x 6, four holes of 8 mm and one of 12 mm
    _part(os.path.join(folder, "pad.gpd"), [("circle", (40, 30), (52, 30))], 10, CU)                      # a round pad of 24 mm over the big hole
    _part(os.path.join(folder, "fin.gpd"), [("rect", (0, 0), (2, 40))], 30, SS)                           # a thin wall: 2 mm
    _part(os.path.join(folder, "block.gpd"), [("rect", (0, 0), (12, 16))], 12, ABS)                       # an insulating block
    a = am.Assembly()
    a.add_component("plate.gpd", fixed=True, pos=(0, 0, 0))
    a.add_component("pad.gpd", pos=(0, 0, 6))
    a.add_component("fin.gpd", pos=(62, 10, 6))
    a.add_component("block.gpd", pos=(14, 22, 6))
    path = os.path.join(folder, "heat_sink_test.gpa")
    with open(path, "w", encoding="utf-8") as f:
        f.write(a.to_json())
    return path


def faces_of(g, body=None, normal=None, kind=None, near=None, interface=False):
    """The ids of the faces of a geometry that fit: of a body (index), with a normal (x, y, z), of a kind ('plane' / 'cylinder'), the outside ones (or the
    interface ones), the one nearest to a point when `near` is given."""
    out = []
    for f in g["faces"]:
        if bool(f.get("interface")) != interface:
            continue
        if body is not None and f.get("body") != body:
            continue
        if kind is not None and f["kind"] != kind:
            continue
        if normal is not None and np.linalg.norm(np.asarray(f["normal"]) - np.asarray(normal)) > 1e-6:
            continue
        out.append(f["id"])
    if near is not None and out:
        out = [min(out, key=lambda i: float(np.linalg.norm(np.asarray(g["faces"][i]["center"]) - np.asarray(near))))]
    return out


def apply_example(win):
    """Puts the conditions, the material numbers and the analysis of the test example on the project that holds the assembly."""
    g = win.geom
    names = [b["name"] for b in g["bodies"]]
    plate, pad, fin, block = (names.index(n) for n in ("plate<1>", "pad<1>", "fin<1>", "block<1>"))
    F, S = EXAMPLE["T_fluid"], win.setup
    for key in tm.KEYS:
        S[key] = []
    ok = []
    ok.append(win.add_condition("powers", {"P": EXAMPLE["power"]}, faces_of(g, pad, (0, 0, 1)), "Heater on the pad"))
    ok.append(win.add_condition("temps", {"T": F}, faces_of(g, plate, kind="cylinder", near=(10, 10, 3)), "Cooled bolt hole"))
    ok.append(win.add_condition("convs", {"h": 15.0, "Tinf": F}, faces_of(g, plate, (0, 0, -1)), "Air under the plate"))
    ok.append(win.add_condition("convs", {"h": 25.0, "Tinf": F}, faces_of(g, fin), "Air round the fin"))
    ok.append(win.add_condition("rads", {"eps": 0.85, "Ts": F}, faces_of(g, plate, (0, 0, 1)), "Top of the plate radiates"))
    ok.append(win.add_condition("rads", {"eps": 0.6, "Ts": F}, faces_of(g, pad, kind="cylinder"), "Side of the pad radiates"))
    ok.append(win.add_condition("ins", {}, faces_of(g, block), "Block insulated"))
    if not all(ok):
        raise RuntimeError("the conditions of the test example could not be put on the faces: " + win.status_lbl.text())
    mats = tm.body_materials(g, dict(S, body_mats={}))
    m = dict(mats[pad])
    m["gen"] = EXAMPLE["gen"]
    S["body_mats"] = {names[pad]: {k: m[k] for k in ("name", "k", "rho", "cp", "gen")}}
    S.update({"analysis": "transient", "T0": F, "t_end": EXAMPLE["t_end"], "steps": EXAMPLE["steps"], "frames": EXAMPLE["frames"], "theta": 1.0,
              "time_unit": "min", "h": EXAMPLE["h"]})
    win.fill_part_sizes()
    win.set_size(format(win_length_out(win, EXAMPLE["h"]), ".6g"))
    win.fill_body_materials()
    win.put_physics()
    win.refresh_lists()
    win.invalidate(mesh=True)
    win.colour()
    win.example_info = {"volume_mm3": float(g["volume"]), "names": names, "plate": plate, "pad": pad, "fin": fin, "block": block, "power": EXAMPLE["power"], "gen": EXAMPLE["gen"],
                        "T_fluid": F}
    return True


def win_length_out(win, mm):
    from solid_base import l_out
    return l_out(mm)


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
    scratch = tempfile.mkdtemp(prefix="opara_t3_example_")
    try:
        try:
            asm = build_sources(scratch)
        except Exception as ex:                                                  # noqa: BLE001 - shown, not raised into the event loop
            QMessageBox.warning(win, "Test example", f"The parts of the example could not be built: {ex}")
            win.log_event("error", f"load_example: building the parts: {ex!r}")
            return False
        if not win.create_project(folder):
            return False
        if not win.import_file(asm):
            win.say("The assembly of the example could not be imported: " + win.status_lbl.text())
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
    win.say("The test example is loaded: press Solve (some seconds), then Run self-check, then Diagnostics report...")
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


def _solid(shape):
    return sg.analyze(shape, None)


def _box(lx, ly, lz, at=(0.0, 0.0, 0.0)):
    import build123d as b
    return b.Pos(at[0] + lx / 2, at[1] + ly / 2, at[2] + lz / 2) * b.Box(lx, ly, lz)


def _face(g, normal, at=None, body=None):
    """The outside face with this normal (and, when `at` is given, the one whose centre is nearest to that point)."""
    ids = faces_of(g, body=body, normal=normal, near=at)
    if not ids:
        raise RuntimeError(f"no face with normal {normal}")
    return ids[0]


def _setup(g, **kw):
    s = tm.default_setup()
    s["material"] = {"name": "", "k": kw.pop("k", 167.0), "rho": kw.pop("rho", 2700.0), "cp": kw.pop("cp", 896.0), "gen": kw.pop("gen", 0.0)}
    s.update(kw)
    return s


def _add(s, g, key, fids, **vals):
    s[key].append(dict({"name": f"{tm.NAMES[key]} {len(s[key]) + 1}", "faces": [sg.face_sig(g, f) for f in fids]}, **vals))


def _run(g, s, h, cache=None, progress=None, cancel=None):
    s["h"] = float(h)
    why = tm.check_ready(s, g)
    if why:
        raise fem.FemError(why)
    r = tm.resolve(g, s)
    return tm.run(g, r, cache if cache is not None else {}, cancel or (lambda: False), progress or (lambda t: None))


def _flow(res, name):
    return next(f["Q"] for f in res["flows"] if f["name"] == name)


def _at(res, point):
    """(temperature K at the node nearest to `point` (mm), how far it is)."""
    d = np.linalg.norm(res["nodes"] - np.asarray(point, float), axis=1)
    i = int(np.argmin(d))
    return float(res["T"][i]), float(d[i])


def _balance_row(group, res, tol=1e-6, note=""):
    return Row(group, "heat balance (in - out - stored) / flow", res["balance"]["relative_error"], 0.0, tol, "", relative=False, note=note)


def check_wall(say, cancel):
    """A bar with its two ends at fixed temperatures and nothing through the sides: T falls in a straight line, Q = k A dT / L."""
    k, L, A, T1, T2 = 167.0, 0.1, 4e-4, 373.15, 293.15
    g = _solid(_box(100, 20, 20))
    s = _setup(g, k=k)
    _add(s, g, "temps", [_face(g, (-1, 0, 0))], T=T1)
    _add(s, g, "temps", [_face(g, (1, 0, 0))], T=T2)
    res = _run(g, s, 10.0, progress=say, cancel=cancel)
    Tm, dist = _at(res, (50, 10, 10))
    return [Row("wall", "heat leaving through the cold end", -_flow(res, "Fixed temperature 2"), k * A * (T1 - T2) / L, 1e-6, "W"),
            Row("wall", "heat entering at the hot end", _flow(res, "Fixed temperature 1"), k * A * (T1 - T2) / L, 1e-6, "W"),
            Row("wall", "temperature half way (node %.2g mm from the point)" % dist, Tm, (T1 + T2) / 2, 1e-5, "K", relative=False),
            Row("wall", "largest heat flux", float(res["qmag"].max()), k * (T1 - T2) / L, 1e-6, "W/m2"), _balance_row("wall", res)]


def check_composite(say, cancel):
    """Two bodies in series (copper then stainless steel), bonded: the temperature at the joint from the thermal resistances."""
    ka, kb, La, Lb, A, T1, T2 = 401.0, 16.0, 0.04, 0.06, 4e-4, 373.15, 293.15
    g = sasm.analyze_assembly([("copper", _box(40, 20, 20), CU), ("steel", _box(60, 20, 20, (40, 0, 0)), SS)], 0.0, None)
    s = _setup(g)
    s["body_mats"] = {"copper": {"name": "", "k": ka, "rho": 8960.0, "cp": 385.0, "gen": 0.0}, "steel": {"name": "", "k": kb, "rho": 8000.0, "cp": 500.0, "gen": 0.0}}
    _add(s, g, "temps", faces_of(g, normal=(-1, 0, 0)), T=T1)
    _add(s, g, "temps", faces_of(g, normal=(1, 0, 0)), T=T2)
    res = _run(g, s, 10.0, progress=say, cancel=cancel)
    Q = (T1 - T2) / (La / (ka * A) + Lb / (kb * A))
    Tj, dist = _at(res, (40, 10, 10))
    return [Row("composite wall", "heat through both bodies", -_flow(res, "Fixed temperature 2"), Q, 1e-5, "W"),
            Row("composite wall", "temperature at the joint (node %.2g mm away)" % dist, Tj, T1 - Q * La / (ka * A), 1e-4, "K", relative=False),
            _balance_row("composite wall", res)]


def check_generation(say, cancel):
    """Heat made inside a bar whose ends are held cold: a parabola, hottest in the middle by q L2 / (8 k); all the heat leaves through the ends."""
    k, L, qv, T0, V = 20.0, 0.06, 1e6, 293.15, 0.06 * 4e-4
    g = _solid(_box(60, 20, 20))
    s = _setup(g, k=k, gen=qv)
    _add(s, g, "temps", [_face(g, (-1, 0, 0))], T=T0)
    _add(s, g, "temps", [_face(g, (1, 0, 0))], T=T0)
    res = _run(g, s, 10.0, progress=say, cancel=cancel)
    Tm, dist = _at(res, (30, 10, 10))
    return [Row("heat generated in a bar", "hottest temperature (middle, node %.2g mm away)" % dist, Tm, T0 + qv * L ** 2 / (8 * k), 1e-4, "K", relative=False),
            Row("heat generated in a bar", "heat made inside", res["balance"]["generation"], qv * V, 1e-6, "W"),
            Row("heat generated in a bar", "heat leaving through the two ends", -(_flow(res, "Fixed temperature 1") + _flow(res, "Fixed temperature 2")), qv * V, 1e-6, "W"),
            _balance_row("heat generated in a bar", res)]


def check_lumped(say, cancel):
    """A copper cube cooling in air (transient): T = Tair + (T0 - Tair) exp(-t / tau), tau = rho c V / (h A)."""
    rho, cp, h, a, T0, Ta, t_end = 8960.0, 385.0, 20.0, 0.01, 373.15, 293.15, 300.0
    g = _solid(_box(10, 10, 10))
    s = _setup(g, k=401.0, rho=rho, cp=cp)
    s.update({"analysis": "transient", "T0": T0, "t_end": t_end, "steps": 60, "theta": 0.5, "frames": 6})
    _add(s, g, "convs", [f["id"] for f in g["faces"]], h=h, Tinf=Ta)
    res = _run(g, s, 10.0, progress=say, cancel=cancel)
    tau = rho * cp * a ** 3 / (h * 6 * a * a)
    want = Ta + (T0 - Ta) * math.exp(-t_end / tau)
    return [Row("cube cooling in air (transient)", "temperature after %g s (time constant %.0f s)" % (t_end, tau), float(res["Tmean"]), want, 3e-3, "K", relative=False),
            Row("cube cooling in air (transient)", "temperature difference left", float(res["Tmean"]) - Ta, want - Ta, 3e-3, "K"),
            Row("cube cooling in air (transient)", "temperature spread over the cube", res["Tmax"] - res["Tmin"], 0.0, 0.05, "K", relative=False),
            _balance_row("cube cooling in air (transient)", res, 2e-2, "Crank-Nicolson compares the flows at the end of the last step with the average storage over it: "
                         "it closes only to about dt / (2 tau) = %.4f" % (t_end / 60 / (2 * tau)))]


def check_radiation(say, cancel):
    """A thin copper plate heated on its underside and radiating from its top (nonlinear): P = eps sigma A (T4 - Tsurr4)."""
    P, eps, Ts, A, k, t = 10.0, 0.9, 293.15, 0.01, 401.0, 0.001
    g = _solid(_box(100, 100, 1))
    s = _setup(g, k=k)
    _add(s, g, "powers", [_face(g, (0, 0, -1))], P=P)
    _add(s, g, "rads", [_face(g, (0, 0, 1))], eps=eps, Ts=Ts)
    res = _run(g, s, 20.0, progress=say, cancel=cancel)
    top = (Ts ** 4 + (P / A) / (eps * SIGMA)) ** 0.25
    Tt, dist = _at(res, (50, 50, 1))
    nw = res.get("newton") or {}
    return [Row("radiating plate", "temperature of the top face", Tt, top, 1e-3, "K", relative=False),
            Row("radiating plate", "heat radiated away", -_flow(res, "Radiation 1"), P, 1e-6, "W"),
            Row("radiating plate", "temperature rise across the thickness", res["Tmax"] - res["Tmin"], P / A * t / k, 5e-4, "K", relative=False),
            Row("radiating plate", "Newton iterations (converged = 1)", 1.0 if nw.get("converged") else 0.0, 1.0, 0.0, "", relative=False,
                note=f"{nw.get('iterations', '?')} iteration(s)"), _balance_row("radiating plate", res)]


def _pipe():
    import build123d as b
    return _solid(b.Cylinder(20, 30) - b.Cylinder(10, 30))


def _pipe_run(g, h, say, cancel, order_limit=None):
    s = _setup(g, k=167.0)
    inner = min((f for f in g["faces"] if f["kind"] == "cylinder"), key=lambda f: f["area"])["id"]
    outer = max((f for f in g["faces"] if f["kind"] == "cylinder"), key=lambda f: f["area"])["id"]
    _add(s, g, "temps", [inner], T=373.15)
    _add(s, g, "temps", [outer], T=293.15)
    if order_limit is None:
        return _run(g, s, h, progress=say, cancel=cancel)
    old = tf.DIRECT_LIMIT
    tf.DIRECT_LIMIT = order_limit
    try:
        return _run(g, s, h, progress=say, cancel=cancel)
    finally:
        tf.DIRECT_LIMIT = old


def check_pipe(say, cancel):
    """A pipe wall (curved faces): Q = 2 pi k L dT / ln(ro / ri).  Two meshes, so the error is seen to shrink; then the iterative solver against the direct."""
    k, Lz, ri, ro, dT = 167.0, 0.03, 0.01, 0.02, 80.0
    want = 2 * math.pi * k * Lz * dT / math.log(ro / ri)
    g = _pipe()
    coarse = _pipe_run(g, 8.0, say, cancel)
    fine = _pipe_run(g, 3.0, say, cancel)
    Qc, Qf = -_flow(coarse, "Fixed temperature 2"), -_flow(fine, "Fixed temperature 2")
    it = _pipe_run(g, 8.0, say, cancel, order_limit=0)
    Qi = -_flow(it, "Fixed temperature 2")
    ec, ef = abs(Qc - want) / want, abs(Qf - want) / want
    rows = [Row("pipe wall", "heat through the wall, coarse mesh (%d elements)" % coarse["elements"], Qc, want, 3e-2, "W",
                note="the curved walls are meshed with straight-sided tetrahedra: a few per cent short"),
            Row("pipe wall", "heat through the wall, finer mesh (%d elements)" % fine["elements"], Qf, want, 1e-2, "W"),
            Row("pipe wall", "error of the finer mesh / error of the coarse mesh", ef / max(ec, 1e-300), 0.0, 0.6, "", relative=False,
                note="must be at most 0.6: refining the mesh has to bring the answer closer"),
            Row("pipe wall", "heat balance, finer mesh", fine["balance"]["relative_error"], 0.0, 1e-6, "", relative=False),
            Row("pipe wall", "iterative solver against the direct one (%s)" % it["run"].get("solver", "?"), Qi, Qc, 1e-6, "W",
                note="the same mesh, solved with conjugate gradients and multigrid"),
            Row("pipe wall", "iterative solver was really used", 1.0 if it["run"].get("solver") == "iterative" else 0.0, 1.0, 0.0, "", relative=False)]
    return rows


CHECKS = [("Wall between two temperatures", check_wall), ("Two bodies in series", check_composite), ("Heat made inside a bar", check_generation),
          ("A cube cooling in air", check_lumped), ("A plate radiating", check_radiation), ("A pipe wall: curved faces, mesh refinement, iterative solver", check_pipe)]


def self_check(progress=None, cancel=None):
    """Runs every problem with a known answer.  -> {"rows": [Row ...], "errors": [text ...], "timings": [(title, seconds) ...], "seconds": ...}.  A problem
    that fails to run is an error (with its full traceback) and a failing row, so it counts as a failure."""
    t0 = time.monotonic()
    rows, errors, timings = [], [], []
    for title, fn in CHECKS:
        if cancel is not None and cancel():
            raise fem.Cancelled()
        if progress is not None:
            progress(f"Self-check: {title}")
        t = time.monotonic()
        try:
            rows.extend(fn((lambda txt: None), cancel))
        except fem.Cancelled:
            raise
        except Exception as ex:                                                  # noqa: BLE001 - a check that cannot run is reported as such
            import traceback
            errors.append(f"{title}: {type(ex).__name__}: {ex}\n{traceback.format_exc()}")
            rows.append(Row(title, "the check could not be run", 0.0, 1.0, 0.0, "", relative=False, note=f"{type(ex).__name__}: {ex}"))
        timings.append((title, time.monotonic() - t))
    return {"rows": rows, "errors": errors, "timings": timings, "seconds": time.monotonic() - t0}


def check_example(res, info):
    """Checks of the result of the test example that need no closed form.  -> [Row]."""
    rows = []
    b = res["balance"]
    rows.append(Row("test example", "heat balance (in - out - stored) / flow", b["relative_error"], 0.0, 1e-6, "", relative=False))
    pad = res["bodies"][info["pad"]] if len(res.get("bodies") or []) > info["pad"] else None
    if pad is not None:
        vol = pad["volume_m3"]
        rows.append(Row("test example", "heat generated in the pad = rate x its volume", pad["generation"], info["gen"] * vol, 1e-6, "W"))
    rows.append(Row("test example", "heat generated, the whole model = that of the pad alone", b["generation"], pad["generation"] if pad else 0.0, 1e-6, "W"))
    mesh_v = sum(x["volume_m3"] for x in res.get("bodies") or [])
    if info.get("volume_mm3"):
        rows.append(Row("test example", "volume of the mesh against the volume of the geometry (straight-sided tetrahedra on curved faces)", mesh_v * 1e9,
                        info["volume_mm3"], 5e-3, "mm3"))
    hot = max(res.get("bodies") or [{"Tmax": 0.0, "name": "?"}], key=lambda x: x["Tmax"])
    rows.append(Row("test example", "the hottest body is the one that is heated (pad = %s)" % (res["bodies"][info["pad"]]["name"] if pad else "?"),
                    1.0 if pad is not None and hot is pad else 0.0, 1.0, 0.0, "", relative=False, note="hottest: " + str(hot["name"])))
    heater = next((f for f in res["flows"] if f["name"] == "Heater on the pad"), None)
    rows.append(Row("test example", "heat flow asked for on the pad (W)", heater["Q"] if heater else float("nan"), info["power"], 1e-9, "W"))
    rows.append(Row("test example", "no point colder than the fluid (heat is only added)", res["Tmin"], info["T_fluid"], 1e-6, "K", relative=False,
                    note="" if res["Tmin"] >= info["T_fluid"] - 1e-6 else "colder than anything that cools it"))
    rows[-1].ok = res["Tmin"] >= info["T_fluid"] - 1e-6
    fr = res.get("frames")
    if fr is not None:
        used = np.unique(res["conn"])
        top = fr[:, used].max(axis=1)
        worst = float(np.max(np.maximum(top[:-1] - top[1:], 0.0))) if len(top) > 1 else 0.0
        rows.append(Row("test example", "hottest point never cools while it is being heated (largest drop)", worst, 0.0, 1e-6, "K", relative=False))
        low = fr[:, used].min(axis=1)
        rows.append(Row("test example", "coldest point never falls below the fluid (lowest)", float(low.min()), info["T_fluid"], 1e-6, "K", relative=False))
        rows[-1].ok = float(low.min()) >= info["T_fluid"] - 1e-6
    nw = res.get("newton")
    if nw is not None:
        rows.append(Row("test example", "radiation (Newton) converged in every step", 1.0 if nw.get("converged") else 0.0, 1.0, 0.0, "", relative=False,
                        note=f"{nw.get('iterations', '?')} iteration(s) in all"))
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
        if win.result is not None and win.example_info is not None and len(win.result.get("bodies") or []) == len(win.example_info["names"]):
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
    for key in tm.KEYS:
        for i, c in enumerate(win.setup.get(key) or []):
            nm = sm.name_of(tm.NAMES[key], i, c)
            vals = {k: c[k] for k in tm.VALUES[key]}
            try:
                fids = sm._fids(win.geom, c["faces"], nm) if win.geom is not None else []
                area = sum(win.geom["faces"][f]["area"] for f in fids)
                where = f"{len(fids)} face(s), {area:.6g} mm2"
            except fem.FemError as ex:
                where = f"FACES LOST: {ex}"
            L.append(f"  {nm}: {tm.NAMES[key]} {vals} on {where}")
    return L or ["  none"]


def diagnostics_text(win):
    """The whole state of a 3D Thermal window as plain text (see solid_diag for the parts every 3D window shares)."""
    L = solid_diag.program_lines("3D THERMAL - DIAGNOSTICS REPORT")
    try:
        import unitctl
        from solid_base import UD
        fam = win.family()
        L.append(f"units: system {unitctl.system()} (lengths in {UD()['L']}), heat transfer {fam.name}, temperature shown in {fam.temp}")
    except Exception as ex:                                                      # noqa: BLE001
        L.append(f"units: unknown ({ex})")
    L += solid_diag.section("Project", [f"folder: {win.path or 'none yet'}", f"saved setup equals the screen: {'yes' if not win.is_dirty() else 'NO - changes not saved'}",
                                        f"example loaded: {'yes' if win.example_info else 'no'}"])
    L += solid_diag.section("Geometry", solid_diag.geometry_lines(win))
    S = win.setup
    sl = []
    if win.geom is not None:
        try:
            for b, m in zip(win.geom.get("bodies") or [{"name": "part"}], tm.body_materials(win.geom, S) if win.geom.get("bodies") else [S["material"]]):
                sl.append(f"  material of {b['name']}: '{m.get('name') or 'custom'}' k {m['k']:.6g} W/(m K), rho {m['rho']:.6g} kg/m3, cp {m['cp']:.6g} J/(kg K), "
                          f"heat generated {float(m.get('gen') or 0):.6g} W/m3")
        except Exception as ex:                                                  # noqa: BLE001
            sl.append(f"  materials: {type(ex).__name__}: {ex}")
    sl.append(f"analysis: {S.get('analysis')}" + (f", start {S['T0']:.4f} K, end {S['t_end']:.6g} s, {S['steps']} steps, theta {S['theta']}, {S['frames']} pictures"
                                                     if S.get("analysis") == "transient" else ""))
    sl.append("conditions (SI: K, W, W/m2, W/(m2 K)):")
    sl += _cond_lines(win)
    sl.append(f"element size asked for: {('%.6g mm' % S['h']) if S.get('h') else 'automatic'}"
              + (f"; sizes of the bodies: {S['body_h']}" if S.get("body_h") else "") + f"; mesh options: {S.get('mesh')}")
    try:
        sl.append("ready to solve: " + (tm.check_ready(S, win.geom) or "yes") if win.geom is not None else "ready to solve: no part")
    except Exception as ex:                                                      # noqa: BLE001
        sl.append(f"ready to solve: could not tell ({ex})")
    L += solid_diag.section("Setup", sl)
    sizes = (win.result or {}).get("sizes") or []
    L += solid_diag.section("Mesh", solid_diag.mesh_lines(win.mesh_q, None, S.get("mesh"))
                            + ([("element size asked for: " + ", ".join(f"{b['name']} {x:.6g} mm" for b, x in zip(win.geom["bodies"], sizes)))
                                if win.geom is not None and win.geom.get("bodies") and len(sizes) == len(win.geom["bodies"])
                                else f"element size asked for: {sizes[0]:.6g} mm"] if sizes else []))
    L += solid_diag.section("Jobs and the time of every stage", solid_diag.jobs_lines(win.job_log))
    r = win.result
    if r is None:
        L += solid_diag.section("Result", ["Not solved yet."])
    else:
        b = r["balance"]
        rl = [f"{r['analysis']}; {r['elements']:,} elements, {len(r['nodes']):,} nodes ({'quadratic' if r['order'] == 2 else 'linear'}), {r['unknowns']:,} unknowns of {r['dofs']:,}",
              f"temperature K: lowest {r['Tmin']:.8g}, highest {r['Tmax']:.8g}, volume average {r['Tmean']:.8g}; largest heat flux {float(np.max(r['qmag'])):.6g} W/m2",
              f"heat balance W: in {b['in']:.8g}, out {b['out']:.8g}, stored {b['stored']:.8g}, generated {b['generation']:.8g}, error {b['error']:.3e} "
              f"({b['relative_error']:.2e} of the flow)",
              f"time s: assembling {r['seconds']['assemble']:.3f}, solving {r['seconds']['solve']:.3f}, all {r['seconds']['total']:.3f}",
              f"solver: {r['run']}", f"newton: {r.get('newton')}"]
        if r.get("frames") is not None:
            rl.append(f"pictures kept: {len(r['frames'])}, from t = {float(r['times'][0]):.6g} s to {float(r['times'][-1]):.6g} s")
        rl.append("heat through each condition (W, + = into the body):")
        rl += [f"  {f['name']} ({f['kind']}): {f['Q']:.8g}" + (f" over {f['area']:.6g} m2" if f.get("area") else "") for f in r["flows"]]
        if r.get("bodies"):
            rl.append("bodies:")
            rl += [f"  {x['name']}: volume {x['volume_m3'] * 1e9:.6g} mm3, T mean {x['Tmean']:.6g} K, min {x['Tmin']:.6g}, max {x['Tmax']:.6g}, largest flux {x['q_max']:.6g} W/m2, "
                   f"generates {x['generation']:.6g} W" for x in r["bodies"]]
        for n in sorted(set(r.get("notes") or [])):
            rl.append("NOTE: " + n)
        L += solid_diag.section("Result", rl)
    cr = win.check_rows
    if cr is None:
        L += solid_diag.section("Self-check", ["Not run in this window yet (press Run self-check)."])
    else:
        L += solid_diag.section("Self-check", [summary_text(dict(cr, rows=cr["rows"] + cr.get("extra", [])))] + rows_text(cr["rows"] + cr.get("extra", []))
                                + ["time of each problem: " + "; ".join(f"{t} {s:.2f} s" for t, s in cr.get("timings") or [])] + [e for e in cr.get("errors") or []])
    L += solid_diag.section("Messages (oldest first; errors in full)", solid_diag.events_lines(win.events))
    return "\n".join(L) + "\n"
