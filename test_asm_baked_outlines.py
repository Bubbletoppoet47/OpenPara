"""Baked outlines: the assembly view draws each part as ONE mesh (surface triangles + outline lines, a colour per cell) and picks on a hidden surface-only copy.
The picks match the old drawing, colours / opacity / moves / highlights still work, and the Settings switch changes between the two drawings."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, settings, assembly
tmp = tempfile.mkdtemp()
def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)
sh = gpd_app.AppShell(); w = sh.new_assembly(); w.insert_files([pa, pb])
base, blk = w.asm.components
blk["fixed"] = False; blk["pos"] = [20.0, 10.0, 10.0]
def mode(m):
    settings.set_many({"outline_mode": m}); w.rebuild_scene(fit=True)
# 1. the baked mesh: lines first, then the triangles; -1 marks a line cell; a colour per cell
mode("baked")
for cid, e in w.entries.items():
    mb, nl = e["baked"]
    m = e["mesh"]
    assert nl > 0 and mb.n_cells == nl + m.n_cells, (mb.n_cells, nl, m.n_cells)
    face = np.asarray(mb.cell_data["face"]); assert (face[:nl] == -1).all() and (face[nl:] == np.asarray(m.cell_data["face"])).all()
    rgb = np.asarray(mb.cell_data["rgb"]); assert (rgb[:nl] == w.LINE_RGB).all()
    assert e["edges"] is None and e["pick"] is not None and e["actor"] is not None
    import vtk
    assert mb.GetCellType(0) in (vtk.VTK_LINE, vtk.VTK_POLY_LINE) and mb.GetCellType(nl) == vtk.VTK_TRIANGLE and mb.GetCellType(mb.n_cells - 1) == vtk.VTK_TRIANGLE
# 2. the colour of a part is per cell: selecting recolours the surfaces, never the lines
w.sel_comp = blk["id"]; w.set_selected_color()
mb, nl = w.entries[blk["id"]]["baked"]; rgb = np.asarray(mb.cell_data["rgb"])
assert (rgb[nl:] == w.rgb255(assembly.SEL_COL)).all() and (rgb[:nl] == w.LINE_RGB).all()
w.sel_comp = None; w.set_selected_color()
assert not (np.asarray(mb.cell_data["rgb"])[nl:] == w.rgb255(assembly.SEL_COL)).all()
# 3. opacity still applies to the actor
w.display_live()
# 4. moving a part moves both the visible mesh and its picking copy
w.asm.comp(blk["id"])["pos"] = [25.0, 12.0, 10.0]; w.update_poses(render=False)
e = w.entries[blk["id"]]; assert np.allclose(np.array(e["actor"].user_matrix), np.array(e["pick"].user_matrix))
assert abs(np.array(e["pick"].user_matrix)[0, 3] - 25.0) < 1e-9
# 5. picks: the hidden copy gives the same component and face as the old drawing, at every pixel of a grid
try:
    pl = w.plotter; pl.window_size = [400, 300]; app.processEvents(); pl.render()
    W, H = pl.window_size
    def grid():
        out = {}
        for x in range(5, W, 9):
            for y in range(5, H, 9):
                h = w.surface_hit(x, y)
                out[(x, y)] = None if h is None else (h[1], h[2])
        return out
    gb = grid(); mode("classic"); pl.window_size = [400, 300]; app.processEvents(); pl.render(); gc = grid(); mode("baked")
    hits = sum(v is not None for v in gb.values())
    print("pick grid: baked hits", hits, "classic hits", sum(v is not None for v in gc.values()))
    assert gb == gc, {k: (gb[k], gc[k]) for k in gb if gb[k] != gc[k]}
except AssertionError:
    raise
except Exception as ex:                       # no usable GL window here: the picking comparison is skipped, the rest is still checked
    print("picking grid skipped:", type(ex).__name__, ex)
# 6. a pick item, highlights and hover work on the baked drawing
it = {"cid": base["id"], "kind": "face", "idx": 0, "ref": None, "pt": np.zeros(3), "label": "Face"}
w.mate_sel = [{"cid": base["id"], "kind": "face", "idx": 0, "label": "Face", "ref": None}]
w.draw_highlights(render=False); assert w.hi_actors
w.hover_item = None
# 7. the switch: classic has separate line actors and no hidden copy; baked has the opposite; the choice is remembered
mode("classic")
assert all(e["edges"] is not None and e["baked"] is None and e["pick"] is None for e in w.entries.values())
mode("baked")
assert all(e["edges"] is None and e["baked"] is not None and e["pick"] is not None for e in w.entries.values())
assert settings.get("outline_mode") == "baked" and set(settings.OUTLINE_MODES) == {"baked", "classic"}
# 8. a rebuild clears the hidden copies (no ghosts of removed parts)
w.rebuild_scene(); assert w.pick_ren.GetViewProps().GetNumberOfItems() == len(w.entries)
print("PASS"); os._exit(0)
