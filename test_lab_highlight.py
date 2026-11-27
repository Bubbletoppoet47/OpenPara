"""Constraint Lab face highlight: in the baked outline drawing a picked or hovered face is shown by recolouring the face's own triangles (a colour per cell), not
by a lifted copy.  Picks and hover come and go without leaving a tint behind, edges and points still get their own pieces, the part colour (selected / own
colour) stays under the tints, the classic drawing and the button fall back to the old lifted copy, and the real assembly window is not changed."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "constraint_lab"), os.path.join(DEV, "constraint_lab"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import numpy as np
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
import pm_model as pm, sk_tools as sk, gpd_app, ext, assembly, settings, view3d
addons.startup(); addons.register_extensions(ext); addons.activate()
import lab_tab, lab_highlight

settings.set_many({"outline_mode": "baked", "hover": True}, persist=False)


def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(UD, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)

sh = gpd_app.AppShell([pa]); w = sh.new_addon_tab("constraint_lab")
assert isinstance(w, lab_tab.LabWindow) and isinstance(w, lab_highlight.FaceTint) and w.face_tint is True
assert w.act["lab_tint"].isCheckable() and w.act["lab_tint"].isChecked() and "lab_tint" in w.act
w.insert_files([pa, pb]); base, blk = w.asm.components
blk["fixed"] = False; blk["pos"] = [20.0, 10.0, 10.0]
w.rebuild_scene(fit=True)
HI, HOV, LINE = w.rgb255(assembly.HI_COL), w.rgb255(w.HOVER_COL), list(w.LINE_RGB)


def parts(cid):
    e = w.entries[cid]; mb, nl = e["baked"]
    return mb, nl, np.asarray(mb.cell_data["face"]), np.asarray(mb.cell_data["rgb"])
def part_col(cid): return w.rgb255(w.part_colour(cid, w.entries[cid]))
def faces_of(cid): return sorted(set(parts(cid)[2][parts(cid)[1]:].tolist()))
def colours(cid, idx):
    mb, nl, face, rgb = parts(cid); sel = rgb[face == idx]
    return {tuple(int(v) for v in r) for r in sel}
def only(cid, idx, col): return colours(cid, idx) == {tuple(col)}
def others_plain(cid, idx):
    """every surface cell that is not face `idx` has the part colour, every line cell the line colour"""
    mb, nl, face, rgb = parts(cid)
    surf = np.arange(len(face)) >= nl
    return bool((rgb[surf & (face != idx)] == part_col(cid)).all() and (rgb[:nl] == LINE).all())
def pick(cid, idx):
    return {"cid": cid, "kind": "face", "idx": idx, "label": "Face"}

fb = faces_of(base["id"]); fk = faces_of(blk["id"])
assert len(fb) >= 6 and len(fk) >= 6

# ---- 1. a picked face: its own triangles turn orange, nothing is added to the scene, the rest is untouched
n_actors = len(w.plotter.renderer.actors)
w.mate_start(); w.mate_sel.append(pick(base["id"], fb[2])); w.draw_highlights(render=False)
assert only(base["id"], fb[2], HI) and others_plain(base["id"], fb[2]), "the picked face is orange, nothing else changed"
assert w.hi_actors == [] and len(w.plotter.renderer.actors) == n_actors, "no lifted copy was added"
# a second pick on the other part, and the first one stays
w.mate_sel.append(pick(blk["id"], fk[0])); w.draw_highlights(render=False)
assert only(blk["id"], fk[0], HI) and others_plain(blk["id"], fk[0]) and only(base["id"], fb[2], HI)
# a pick that is taken back gives the colour back
w.mate_sel.pop(0); w.draw_highlights(render=False)
assert others_plain(base["id"], -999) and only(blk["id"], fk[0], HI), "the first pick is gone and its face is the part colour again"
w.mate_sel.pop(0); w.draw_highlights(render=False)
assert others_plain(blk["id"], -999)

# ---- 2. the hover: the face's own cells take the hover colour mixed over the part colour; leaving puts it back
shown = {}
def fake_pick(it): w.pick_item = lambda x, y: it
fake_pick({"cid": base["id"], "kind": "face", "idx": fb[1], "label": "Face"}); w.on_hover(10, 10)
def mixed(cid): return tuple(int(v) for v in np.round(w.HOVER_MIX * np.array(HOV) + (1 - w.HOVER_MIX) * np.array(part_col(cid))))
mix, mixk = mixed(base["id"]), mixed(blk["id"])
assert w.hover_actor is None and w.__dict__["_tint_hover"] == (base["id"], fb[1])
assert colours(base["id"], fb[1]) == {mix} and others_plain(base["id"], fb[1]) and mix != tuple(part_col(base["id"]))
fake_pick({"cid": base["id"], "kind": "face", "idx": fb[3], "label": "Face"}); w.on_hover(11, 10)             # moves to the next face: the old one is released
assert colours(base["id"], fb[3]) == {mix} and others_plain(base["id"], fb[3])
fake_pick({"cid": blk["id"], "kind": "face", "idx": fk[1], "label": "Face"}); w.on_hover(12, 10)              # another part
assert others_plain(base["id"], -999) and colours(blk["id"], fk[1]) == {mixk}
fake_pick(None); w.on_hover(13, 10)
assert others_plain(blk["id"], -999) and others_plain(base["id"], -999) and w.__dict__["_tint_hover"] is None
# a hover over a picked face: the pick stays orange both while hovering and after
w.mate_sel.append(pick(base["id"], fb[2])); w.draw_highlights(render=False)
fake_pick({"cid": base["id"], "kind": "face", "idx": fb[2], "label": "Face"}); w.on_hover(14, 10)
assert only(base["id"], fb[2], HI)
fake_pick(None); w.on_hover(15, 10); assert only(base["id"], fb[2], HI) and others_plain(base["id"], fb[2])
# the hover goes when the mode ends (the cursor is not picking any more)
fake_pick({"cid": blk["id"], "kind": "face", "idx": fk[2], "label": "Face"}); w.on_hover(16, 10); assert colours(blk["id"], fk[2]) == {mixk}
w.mode = "move"; w.on_hover(17, 10); assert others_plain(blk["id"], -999) and w.__dict__["_tint_hover"] is None
w.mode = "mate"

# ---- 3. edges and points still get their own pieces, in the usual way
e0 = w.entries[base["id"]]
w.mate_sel.append({"cid": base["id"], "kind": "edge", "idx": 0, "label": "Edge"}); w.mate_sel.append({"cid": blk["id"], "kind": "vertex", "idx": 0, "label": "Point", "pt": [0.0, 0.0, 0.0]})
w.draw_highlights(render=False)
assert len(w.hi_actors) == 2 and only(base["id"], fb[2], HI), "an edge and a point are drawn as before; the face stays recoloured"
fake_pick({"cid": base["id"], "kind": "edge", "idx": 1, "label": "Edge"}); w.on_hover(18, 10)
assert w.hover_actor is not None and w.__dict__["_tint_hover"] is None
fake_pick(None); w.on_hover(19, 10); assert w.hover_actor is None
w.mate_sel[:] = [pick(base["id"], fb[2])]; w.draw_highlights(render=False)

# ---- 4. the part colour stays under the tints: selecting a part, a colour change, a rebuild
w.sel_comp = base["id"]; w.set_selected_color()
assert colours(base["id"], fb[0]) == {tuple(w.rgb255(view3d.select_rgb()))} and only(base["id"], fb[2], HI), "selected part: blue with the orange face still on it"
fake_pick({"cid": base["id"], "kind": "face", "idx": fb[4], "label": "Face"}); w.on_hover(20, 10); assert len(colours(base["id"], fb[4])) == 1
fake_pick(None); w.on_hover(21, 10)
assert others_plain(base["id"], fb[2])
w.sel_comp = None; w.set_selected_color(); assert others_plain(base["id"], fb[2]) and only(base["id"], fb[2], HI)
w.asm.comp(blk["id"])["color"] = (0.2, 0.7, 0.3); w.rebuild_scene()
assert only(base["id"], fb[2], HI) and others_plain(base["id"], fb[2]) and others_plain(blk["id"], -999), "a rebuilt scene shows the same picks"
assert w.hi_actors == [] and w.__dict__["_tint_hover"] is None

# ---- 5. the button / the old way: the lifted copy comes back, and the tint is taken off
w.act["lab_tint"].setChecked(False); w.tint_toggle()
assert w.face_tint is False and others_plain(base["id"], -999), "no tint left behind"
assert len(w.hi_actors) == 1 and w.hi_actors[0][1] == base["id"], "the picked face is the lifted copy again"
fake_pick({"cid": blk["id"], "kind": "face", "idx": fk[1], "label": "Face"}); w.on_hover(22, 10)
assert w.hover_actor is not None and others_plain(blk["id"], -999), "hover is the lifted copy again"
fake_pick(None); w.on_hover(23, 10)
w.act["lab_tint"].setChecked(True); w.tint_toggle()
assert w.face_tint is True and only(base["id"], fb[2], HI) and w.hi_actors == []

# ---- 6. the classic outline drawing has no per-cell colours: the lifted copy is used whatever the button says
settings.set_many({"outline_mode": "classic"}, persist=False); w.rebuild_scene()
assert all(e["baked"] is None for e in w.entries.values()) and w.face_tint is True
assert len(w.hi_actors) == 1 and w.hi_actors[0][1] == base["id"]
fake_pick({"cid": blk["id"], "kind": "face", "idx": fk[1], "label": "Face"}); w.on_hover(24, 10); assert w.hover_actor is not None
fake_pick(None); w.on_hover(25, 10)
w.sel_comp = blk["id"]; w.set_selected_color(); w.sel_comp = None; w.set_selected_color()
settings.set_many({"outline_mode": "baked"}, persist=False); w.rebuild_scene()
assert only(base["id"], fb[2], HI) and w.hi_actors == []

# ---- 7. ending the mate (OK or cancel) leaves no tint; the engine switch does not disturb it
w.mate_cancel(quiet=True)
assert others_plain(base["id"], -999) and others_plain(blk["id"], -999) and w.mate_sel == []
w.mate_start(); w.mate_sel.append(pick(blk["id"], fk[3])); w.draw_highlights(render=False)
w.set_engine("Experimental"); assert only(blk["id"], fk[3], HI)
w.set_engine("Current"); w.mate_cancel(quiet=True); assert others_plain(blk["id"], -999)

# ---- 8. a real mate made with the recolour on works and clears the tints
def face_of(c, which):
    pl = [f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"]
    return max(pl, key=lambda f: f.center().Z) if which == "top" else min(pl, key=lambda f: f.center().Z)
import asm_model as am
w.mate_start()
w.add_mate_ref({"c": base["id"], "k": "face", "r": am.face_ref(face_of(base, "top"))}, pick(base["id"], fb[0]))
assert only(base["id"], fb[0], HI)
w.add_mate_ref({"c": blk["id"], "k": "face", "r": am.face_ref(face_of(blk, "bot"))}, pick(blk["id"], fk[0]))
w.mate_ok()
assert len(w.asm.mates) == 1 and abs(blk["pos"][2] - 10) < 1e-3
assert others_plain(base["id"], -999) and others_plain(blk["id"], -999), "after OK nothing stays orange"

# ---- 9. the real assembly window is not changed: it still uses the lifted copy
rw = sh.new_assembly()
assert not isinstance(rw, lab_highlight.FaceTint) and not hasattr(rw, "face_tint")
rw.insert_files([pa]); rc = rw.asm.components[0]; rw.rebuild_scene(fit=True)
rw.mate_start(); rw.mate_sel.append(pick(rc["id"], faces_of_real := sorted(set(np.asarray(rw.entries[rc["id"]]["mesh"].cell_data["face"]).tolist()))[0])); rw.draw_highlights(render=False)
assert len(rw.hi_actors) == 1, "the real window still draws the lifted copy"

print("OK lab highlight")
os._exit(0)
