"""wb_example.py - "Load Example Project": a small project that uses everything the Workbench does, so that it can be tried (and so that a change to the Workbench can be checked on it).

    Parts          Bar (100 x 10 x 10 mm)          Plate (100 x 20 x 10 mm; its sketch is used by the 2D analysis)          Square (20 x 20 x 10 mm)          Block (30 x 10 x 10 mm)
    Assembly       Frame                           keeps its OWN copy of a bar, 20 mm thick (no link to the part blocks)
    Analyses       Bar stress          3D Static Structural from Bar: fixed at one end, 1000 N pulling the other      (u = F L / (A E) = 0.005 mm)
                   Plate stress 2D     2D Static Structural from Plate: fixed on the left edge, 0.5 MPa on the right edge
                   Frame heating       3D Thermal from Frame: 100 C at one end, 20 C at the other
                   Frame check         3D Static Structural from Frame with NO setup: it says what is missing (the example of an incomplete cell)
    Coupled        Bar heating         3D Thermal from Bar: 100 C at one end, 20 C at the other
                   Bar growth          3D Static Structural from Bar: three symmetry planes hold it, NO load; steel, free of thermal stress at 20 C
                   Bar thermal stress  Coupled Physics of the two: the heat analysis is solved, its temperature goes to the stress analysis, and the far end of the bar grows
                                       alpha (Tmean - Tref) L = 12e-6 x 40 x 100 = 0.048 mm: a known answer that is checked (PASS / FAIL) in its window
    Flow           Air flow            2D Fluid Flow of the Square (20 mm): slow air (0.03 m/s, Re about 40) past it; its left edge is held at 50 C, the other three walls are the walls of the heat analysis
                   Square heat         2D Thermal of the Square: a very good conductor (400 W/m/K), left edge held at 50 C, the other edges are cooled by the air
                   Square bending      2D Static Structural of the Square: left edge held, NO load; so soft (E = 5e-8 MPa, on purpose) that the pressure of the air bends it by a visible fraction of a percent
                   Air, heat and bending  Coupled Physics of the three: the air takes the heat of the square, the pressure of the air loads the stress analysis, and the structure MOVES the flow
                                       (the flow is solved again round the bent square until the displacement stops changing).  Known answer: the walls are at 50 C (the body conducts so well it is at one temperature)
    3D flow        Block air flow      3D Fluid Flow of the Block (30 x 10 x 10 mm): slow air (0.06 m/s, Re about 40) along +x; every face but the upstream end is a wall of the thermal analysis
                   Block heat          3D Thermal of the Block: a very good conductor (400 W/m/K), the upstream end held at 70 C, the other faces are cooled by the air
                   Block pressure      3D Static Structural of the Block: the downstream end held, NO load; so soft (E = 4e-7 MPa, on purpose) that the pressure of the air moves it by a visible fraction of its size
                   Air, heat and pressure 3D  Coupled Physics of the three: the air takes the heat of the block, its pressure loads the stress analysis, and the structure MOVES the flow.
                                       Known answer: the walls are at 70 C (the block conducts so well it is at one temperature)
    Study          Bar study           Parametric Study of Bar stress (wired from its Setup; a new study runs one design point, as the analysis is)
    Tools          Load table (Sheets, with formulas), LED circuit (Circuits), Plant (Systems and Controls)

Loading does not compute anything: the geometry cells are refreshed (the parts are copied into the analyses) and the setups are made in the usual windows (as a person would),
then every window is closed again.  Update Project solves the analyses, the two coupled blocks and runs the study; change a part and the analyses that use it say 'refresh'.
A kind whose add-on is not installed is left out (and said).  load(tab) -> [what could not be done].
"""
import json
import os
import shutil
import tempfile

import wb_nodes as nodes
import wb_project as wp

NAME = "Example: a bar, a plate and a frame"


# ---------------------------------------------------------------------------------------------------------------------------- the parts
def part_doc(width, height, depth):
    """A part: one sketch (a rectangle width x height on the Top plane) extruded `depth` mm by the parameter H.  -> (the part as an object, the id of its sketch)."""
    import pm_model as pm
    import sk_tools as sk
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (width, height))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=float(width))
    m.add_con("dim_v", [("ln", r["lns"][1])], value=float(height))
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    if d.solid is None:
        raise RuntimeError("the example part could not be built")
    return json.loads(d.to_json()), s["id"]


def frame_asm(width, height, depth):
    """An assembly with ONE component: its own copy of a bar."""
    import asm_model as am
    doc, _sid = part_doc(width, height, depth)
    a = am.Assembly()
    a.add_component(a.embed_part("Bar", "part", doc), fixed=True)
    return json.loads(a.to_json())


# ---------------------------------------------------------------------------------------------------------------------------- the tool documents
def sheet_blob():
    import sh_book
    wb = sh_book.Workbook()
    name = wb.sheet_names()[0]
    rows = (("Load F (N)", "1000"), ("Width b (mm)", "10"), ("Height h (mm)", "10"), ("Area A (mm2)", "=B3*B4"), ("Stress F/A (MPa)", "=B2/B5"))
    for i, (label, value) in enumerate(rows, start=2):
        wb.set_input(name, i, 1, label)
        wb.set_input(name, i, 2, value)
    return _blob(lambda p: wb.save(p), "Load table.opsheet")


def circuit_blob():
    import circuits_tab as ct
    from editor import CircuitScene
    sc = CircuitScene()
    ct.EXAMPLES["LED with resistor"](sc)
    return _blob(lambda p: _write(p, json.dumps(sc.to_json(), indent=1)), "LED circuit.opcirc")


def controls_blob():
    doc = {"format": "openpara-controls", "version": 1, "sections": {"transfer_function": {"num": "2s+3", "den": "s^2+3s+2"}}}
    return _blob(lambda p: _write(p, json.dumps(doc, indent=1)), "Plant.opctl")


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _blob(make, name):
    d = tempfile.mkdtemp(prefix="opara_wbex_")
    try:
        p = os.path.join(d, name)
        make(p)
        return wp.pack_file(p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------------------- the setups, made in the usual windows
def with_editor(tab, node, fn):
    """Opens the analysis of `node` in its usual window (in the background), lets fn(window) set it up, reads it back into the project and closes the window."""
    a = nodes.adapter_for(node.kind)
    w = a.open_editor(tab, node, front=False)
    if w is None:
        raise RuntimeError("its window could not be opened")
    try:
        fn(w)
    finally:
        tab.sync_editors()
        a.close_editor(tab, node)


def face_by_normal(win, n, plain=False):
    import numpy as np
    return next(f["id"] for f in win.geom["faces"] if np.dot(f["normal"], n) > 0.99 and (not plain or f.get("kind", "") != "x"))


def setup_bar_stress(w):
    w.select_faces([face_by_normal(w, [-1, 0, 0])])
    w.add_support("fixed")
    w.select_faces([face_by_normal(w, [1, 0, 0])])
    w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
    w.set_size("6")
    w.inputs_changed()


def setup_plate_2d(sid):
    def fn(w):
        t = w.tab
        t.picker.refresh()
        t.picker.select(sid)
        t.picker.go()
        xs = {ln: [t.model.pts[p][0] for p in t.model.lns[ln][:2]] for ln in t.model.lns}
        lo, hi = min(min(x) for x in xs.values()), max(max(x) for x in xs.values())
        left = next(ln for ln, x in xs.items() if max(x) < lo + 1e-9)
        right = next(ln for ln, x in xs.items() if min(x) > hi - 1e-9)
        t.supports = [{"mode": "fixed", "targets": [("ln", left)]}]
        t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", right)]}]
        t.e_h.setText("4")
        t.refresh_lists()
    return fn


def setup_bar_growth(w):
    """Three symmetry planes (no rigid movement, nothing else held), no load, steel that is free of thermal stress at 20 C: the temperature is the whole load."""
    w.add_support("disp", [face_by_normal(w, [-1, 0, 0])], {"ux": 0.0, "uy": None, "uz": None})
    w.add_support("disp", [face_by_normal(w, [0, -1, 0])], {"ux": None, "uy": 0.0, "uz": None})
    w.add_support("disp", [face_by_normal(w, [0, 0, -1])], {"ux": None, "uy": None, "uz": 0.0})
    w.e_alpha.setText("1.2e-5")
    w.e_tref.setText("20")
    w.set_size("6")
    w.inputs_changed()


KNOWN = {"name": "the far end of the bar grows alpha (Tmean - Tref) L", "expected": 12e-6 * 40.0 * 100.0, "unit": "mm", "tol_pct": 2.0, "axis": 0}


def setup_coupled(w):
    w.options["known"] = dict(KNOWN)
    w.save()


SQ = 20.0                                                   # the side of the square in the air (mm)
E_SOFT = 5e-8                                               # MPa: so soft that the pressure of this slow air (a few 1e-4 Pa) bends a 20 mm square by about a half percent of its size
KNOWN_AIR = {"kind": "wall_temperature", "name": "a body this conductive is at one temperature, and so are its walls (held at 50 C)", "expected": 50.0, "unit": "degC", "tol_abs": 1.0}


def left_line(t):
    """The id of the line of the square that lies on x = 0."""
    return next(ln for ln in t.model.lns if max(t.model.pts[p][0] for p in t.model.lns[ln][:2]) < 1e-9)


def pick_sketch(t, sid):
    t.picker.refresh()
    t.picker.select(sid)
    t.picker.go()


def setup_air_flow(sid):
    def fn(w):
        import units
        t = w.tab
        pick_sketch(t, sid)
        t.e_speed.setText(f"{units.speed_from_si(0.03, t.unit_name()):.6g}")
        for e, v in ((t.e_hb, "3"), (t.e_hf, "12"), (t.e_ml, "3"), (t.e_mr, "8"), (t.e_mb, "3"), (t.e_mt, "3"), (t.e_cfl, "2"), (t.e_steps, "250"), (t.e_tol, "1e-6"), (t.e_ramp, "5"),
                     (t.e_every, "1000")):
            e.setText(v)
        t.cb_until.setChecked(False)
        t.cb_auto.setChecked(False)                          # (a body that moves needs the mesh to be the one that was asked for)
        t.cb_heat.setChecked(True)
        left = ("ln", left_line(t))
        t.set_wall_condition([left], "temp", "50")
        t.set_wall_condition(sorted({e["src"] for e in t.geom["edges"] if e["src"] != left}), "coupled", "")
    return fn


def setup_square_heat(sid):
    def fn(w):
        t = w.tab
        pick_sketch(t, sid)
        t.supports = [{"kind": "temp", "T": 323.15, "targets": [("ln", left_line(t))]}]
        t.after_conditions()
        t.e_h.setText("2")
        t.e_t.setText("1")
        t.ensure_region_materials()
        for f in t.region_mats:
            t.region_mats[f]["k"] = 400.0                    # (copper: so conductive that the body is at one temperature)
    return fn


def setup_square_bending(sid):
    def fn(w):
        t = w.tab
        pick_sketch(t, sid)
        t.supports = [{"mode": "fixed", "targets": [("ln", left_line(t))]}]
        t.e_E.setText(f"{E_SOFT:g}")
        t.e_alpha.setText("1.2e-5")
        t.e_tref.setText("20")
        t.e_h.setText("2")
        t.cb_auto.setChecked(False)
        t.refresh_lists()
    return fn


def setup_coupled_air(w):
    w.options["known"] = dict(KNOWN_AIR)
    w.options["moves_flow"] = True
    w.cb_moves.setChecked(True)
    w.save()


def setup_frame_heating(w):
    w.add_condition("temps", {"T": 373.15}, [face_by_normal(w, [-1, 0, 0], True)], "Hot end")
    w.add_condition("temps", {"T": 293.15}, [face_by_normal(w, [1, 0, 0], True)], "Cold end")


BLOCK = (30.0, 10.0, 10.0)                                  # the block in the 3D air stream (mm)
E_SOFT3 = 4e-7                                              # MPa: so soft that the pressure of this slow air (a few 1e-9 Pa x mm2 of force) moves a 30 mm block by a fraction of a percent
KNOWN_BLOCK = {"kind": "wall_temperature", "name": "a block this conductive is at one temperature, and so are its walls (held at 70 C at the upstream end)", "expected": 70.0, "unit": "degC", "tol_abs": 1.0}


def setup_block_flow(w):
    """Slow air along +x past the block; every face but the upstream end (which the heat analysis holds at 70 C) is a wall of the thermal analysis."""
    w.setup["flow"].update({"speed": 0.06, "dir": "+x", "heat": True, "T_in": 293.15})
    hot = face_by_normal(w, [-1, 0, 0])
    w.add_condition("exch", {}, [int(f["id"]) for f in w.geom["faces"] if int(f["id"]) != int(hot)], "Wall of the thermal analysis")
    w.fill_part_sizes()
    w.set_size("2.5")
    w.put_physics()
    w.refresh_lists()


def setup_block_heat(w):
    w.add_condition("temps", {"T": 343.15}, [face_by_normal(w, [-1, 0, 0])], "Hot end")
    w.setup["analysis"] = "steady"
    w.e_k.setText("400")                                    # (copper: so conductive that the block is at one temperature)
    w.inputs_changed()
    w.refresh_lists()


def setup_block_pressure(w):
    w.add_support("fixed", [face_by_normal(w, [1, 0, 0])])
    w.e_alpha.setText("2.3e-5")
    w.e_tref.setText("20")
    w.e_E.setText(f"{E_SOFT3:g}")
    w.inputs_changed()


def setup_coupled_block(w):
    w.options["known"] = dict(KNOWN_BLOCK)
    w.options["moves_flow"] = True
    w.cb_moves.setChecked(True)
    w.save()


# ---------------------------------------------------------------------------------------------------------------------------- the project
def load(tab):
    """Replaces the project of `tab` with the example.  -> [what could not be made (the reason)]."""
    problems = []
    tab.set_project(wp.Project(NAME))
    bar, _sid = part_doc(100, 10, 10)
    plate, plate_sid = part_doc(100, 20, 10)
    nBar = tab.add_block("part", 40, 60, title="Bar", data={"doc": bar})
    nPlate = tab.add_block("part", 40, 280, title="Plate", data={"doc": plate})
    nFrame = tab.add_block("assembly", 40, 500, title="Frame", data={"asm": frame_asm(100, 10, 20)})
    square, square_sid = part_doc(SQ, SQ, 10)
    nSquare = tab.add_block("part", 40, 1380, title="Square", data={"doc": square})
    block, _block_sid = part_doc(BLOCK[0], BLOCK[1], BLOCK[2])
    nBlock = tab.add_block("part", 40, 2060, title="Block", data={"doc": block})
    made = {}
    for key, kind, x, y, title, src in (("bar", "solid", 380, 60, "Bar stress", nBar), ("plate", "fea", 380, 280, "Plate stress 2D", nPlate),
                                        ("heat", "thermal3d", 380, 500, "Frame heating", nFrame), ("check", "solid", 380, 720, "Frame check (needs a setup)", nFrame),
                                        ("bheat", "thermal3d", 380, 940, "Bar heating", nBar), ("grow", "solid", 380, 1160, "Bar growth", nBar),
                                        ("air", "cfd", 380, 1380, "Air flow", nSquare), ("sheat", "thermal", 380, 1600, "Square heat", nSquare),
                                        ("sbend", "fea", 380, 1820, "Square bending", nSquare), ("bflow", "fluid3d", 380, 2060, "Block air flow", nBlock),
                                        ("bheat3", "thermal3d", 380, 2280, "Block heat", nBlock), ("bpress", "solid", 380, 2500, "Block pressure", nBlock)):
        ok, why = nodes.availability(tab, kind)
        if not ok:
            problems.append(f"{title}: {why}")
            continue
        n = tab.add_block(kind, x, y, title=title)
        tab.scene.make_link(src.id, "geometry", n.id, "geometry")
        made[key] = n
    nCoupled = None
    if "bheat" in made and "grow" in made:                   # the Coupled Physics block: wired from the Setup of the heat and of the stress analysis
        ok, why = nodes.availability(tab, "coupled")
        if ok:
            nCoupled = tab.add_block("coupled", 720, 1050, title="Bar thermal stress")
            tab.scene.make_link(made["bheat"].id, "setup", nCoupled.id, "physics")
            tab.scene.make_link(made["grow"].id, "setup", nCoupled.id, "physics")
        else:
            problems.append(f"Bar thermal stress: {why}")
    nAir = None
    if all(k in made for k in ("air", "sheat", "sbend")):    # the second Coupled Physics block: the flow, the heat of the square and its bending
        ok, why = nodes.availability(tab, "coupled")
        if ok:
            nAir = tab.add_block("coupled", 720, 1600, title="Air, heat and bending")
            for k in ("air", "sheat", "sbend"):
                tab.scene.make_link(made[k].id, "setup", nAir.id, "physics")
        else:
            problems.append(f"Air, heat and bending: {why}")
    elif any(k in made for k in ("air", "sheat", "sbend")):
        problems.append("Air, heat and bending: one of the three analyses (2D Fluid Flow, 2D Thermal, 2D Static Structural) is not available, so the block was left out.")
    nBlk = None
    if all(k in made for k in ("bflow", "bheat3", "bpress")):  # the third Coupled Physics block: a 3D flow, the heat of a block and the pressure on it
        ok, why = nodes.availability(tab, "coupled")
        if ok:
            nBlk = tab.add_block("coupled", 720, 2280, title="Air, heat and pressure 3D")
            for k in ("bflow", "bheat3", "bpress"):
                tab.scene.make_link(made[k].id, "setup", nBlk.id, "physics")
        else:
            problems.append(f"Air, heat and pressure 3D: {why}")
    elif any(k in made for k in ("bflow", "bheat3", "bpress")):
        problems.append("Air, heat and pressure 3D: one of the three analyses (3D Fluid Flow, 3D Thermal, 3D Static Structural) is not available, so the block was left out.")
    nStudy = None
    if "bar" in made:                                        # a parametric study of the bar analysis (when the add-on for it is there)
        ok, why = nodes.availability(tab, "study")
        if ok:
            nStudy = tab.add_block("study", 720, 60, title="Bar study")
            tab.scene.make_link(made["bar"].id, "setup", nStudy.id, "setup")
        else:
            problems.append(f"Bar study: {why}")
    for kind, x, y, title, make in (("sheets", 1060, 60, "Load table", sheet_blob), ("circuits", 1060, 280, "LED circuit", circuit_blob),
                                    ("controls", 1060, 500, "Plant", controls_blob)):
        ok, why = nodes.availability(tab, kind)
        if not ok:
            problems.append(f"{title}: {why}")
            continue
        try:
            n = tab.add_block(kind, x, y, title=title, data={"file": make()})
            tab.project.set_ready(n.id, "document", True)
        except Exception as ex:                              # noqa: BLE001
            problems.append(f"{title}: {type(ex).__name__}: {ex}")
    tab.scene.refresh()
    done, failed = tab.refresh_project()
    for name, why in failed:
        problems.append(f"{name}: {why}")
    h = tab.host
    if h is None or not hasattr(h, "new_addon_tab"):
        problems.append("The analyses could not be set up here (there is no program window): open them and make the setup by hand.")
    else:
        for key, fn, title in (("bar", setup_bar_stress, "Bar stress"), ("plate", setup_plate_2d(plate_sid), "Plate stress 2D"), ("heat", setup_frame_heating, "Frame heating"),
                               ("bheat", setup_frame_heating, "Bar heating"), ("grow", setup_bar_growth, "Bar growth"),
                               ("air", setup_air_flow(square_sid), "Air flow"), ("sheat", setup_square_heat(square_sid), "Square heat"),
                               ("sbend", setup_square_bending(square_sid), "Square bending"), ("bflow", setup_block_flow, "Block air flow"), ("bheat3", setup_block_heat, "Block heat"),
                               ("bpress", setup_block_pressure, "Block pressure")):
            if key not in made:
                continue
            try:
                with_editor(tab, made[key], fn)
            except Exception as ex:                          # noqa: BLE001
                problems.append(f"{title}: its setup could not be made ({type(ex).__name__}: {ex})")
    if nCoupled is not None and h is not None and hasattr(h, "new_addon_tab"):
        try:
            with_editor(tab, nCoupled, setup_coupled)        # (the known answer of the bar goes into the block's own options)
        except Exception as ex:                              # noqa: BLE001
            problems.append(f"Bar thermal stress: its known answer could not be set ({type(ex).__name__}: {ex})")
    if nAir is not None and h is not None and hasattr(h, "new_addon_tab"):
        try:
            with_editor(tab, nAir, setup_coupled_air)        # (the known answer of the walls goes into the block's own options, and the structure moves the flow)
        except Exception as ex:                              # noqa: BLE001
            problems.append(f"Air, heat and bending: its options could not be set ({type(ex).__name__}: {ex})")
    if nBlk is not None and h is not None and hasattr(h, "new_addon_tab"):
        try:
            with_editor(tab, nBlk, setup_coupled_block)      # (the known answer of the walls goes into the block's own options, and the structure moves the flow)
        except Exception as ex:                              # noqa: BLE001
            problems.append(f"Air, heat and pressure 3D: its options could not be set ({type(ex).__name__}: {ex})")
    if any(n is not None for n in (nStudy, nCoupled, nAir, nBlk)):  # (their cells take the setups that were just made: nothing is computed)
        tab.refresh_project(only=[n.id for n in (nStudy, nCoupled, nAir, nBlk) if n is not None])
    tab.scene.refresh()
    tab.say(f"Example loaded: {len(tab.project.nodes)} blocks. Nothing is computed yet: press Update Project and the analyses are solved (the coupled blocks with their PASS / FAIL known answers) and the study runs." +
            ("  Left out or not set up: " + "; ".join(problems) if problems else ""))
    return problems
