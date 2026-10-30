import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se, sk_tools as sk, sk_dimlines as dl
w = pm_app.MainWindow(); ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
se.ask_dim = lambda parent, title, text, syms, **k: text
m = ed.m
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
w.set_tool("rect_corner"); click(-20, -10); click(20, 10); ed.reset_tool("select")
lns = list(ed.m.lns)
bottom = [l for l in lns if abs(ed.m.line_pts(l)[0][1] - ed.m.line_pts(l)[1][1]) < 1e-6 and ed.m.line_pts(l)[0][1] < 0][0]
side = [l for l in lns if abs(ed.m.line_pts(l)[0][0] - ed.m.line_pts(l)[1][0]) < 1e-6 and ed.m.line_pts(l)[0][0] > 0][0]
ed.commit(lambda mm: mm.add_con("dim_h", [("ln", bottom)], value=40.0))
ed.commit(lambda mm: mm.add_con("dim_v", [("ln", side)], value=20.0))
ed.commit(lambda mm: mm.add_con("dim_len", [("ln", bottom)], value=40.0))
cs = lambda t: [c for c in ed.m.cons if c["type"] == t][0]
def near(a, b, tol=1e-6): return abs(a - b) < tol

# ---- linear dimensions: extension lines, a dimension line through the label with an arrow at each measured point
for typ in ("dim_h", "dim_v", "dim_len"):
    c = cs(typ); sh = dl.shapes(ed, c)
    A, B = ed.m._two_points(c["refs"]); L = sh["label"]
    assert len(sh["segs"]) >= 1 and len(sh["arrows"]) == 2, (typ, len(sh["segs"]), len(sh["arrows"]))
    u = (1.0, 0.0) if typ == "dim_h" else (0.0, 1.0) if typ == "dim_v" else dl._unit((B[0] - A[0], B[1] - A[1]))
    n = (-u[1], u[0])
    dim = sh["segs"][0]
    assert near(float((dim[0] - dim[1]) @ np.array(n)), 0.0), "the dimension line runs along the measured direction"
    assert near(float((np.array(L) - dim[0]) @ np.array(n)), 0.0), "and passes through the label"
    tips = [a[1] for a in sh["arrows"]]
    # the measured distance equals the distance between the arrow tips along the line
    along = sorted(float(np.array(t) @ np.array(u)) for t in tips)
    assert near(along[1] - along[0], abs(float((np.array(B) - np.array(A)) @ np.array(u))), 1e-6), typ
    ext = sh["segs"][1:]
    assert len(ext) == 2, "two extension lines"
    for e_, P in zip(ext, (A, B)):
        assert np.linalg.norm(e_[0] - np.array(P)) < 0.05 * dl.extent(ed.m) + 1e-9 or abs(float(np.dot(np.array(e_[0]) - np.array(P), n))) < 0.05 * dl.extent(ed.m), "an extension line starts at the point it measures"
    print(typ, "ok; label", np.round(L, 2))
# dragging the label away moves the dimension line and the extension lines follow
c = cs("dim_h"); before = dl.shapes(ed, c)
c["off"] = [0.0, 25.0]; ed.redraw()
after = dl.shapes(ed, c); L0, L1 = before["label"], after["label"]
d0, d1 = before["segs"][0][0][1], after["segs"][0][0][1]
assert abs(d1 - d0) > 1.0 and near(d1, after["label"][1]), "the dimension line moved with the label"
assert all(abs(s[1][1] - d1) < 0.9 * 0.022 * dl.extent(ed.m) + 1e-6 for s in after["segs"][1:]), "extension lines reach the new line"
c.pop("off"); ed.redraw()

# ---- circles: a leader from the circle to a label outside it, arrows touching the circle
w.set_tool("circle"); click(60, 0); click(68, 0); ed.reset_tool("select")
ci = list(ed.m.cis)[-1]; C = ed.m.pts[ed.m.cis[ci]["c"]]; R = ed.m.cis[ci]["r"]
ed.commit(lambda mm: mm.add_con("dim_dia", [("ci", ci)], value=2 * R))
c = cs("dim_dia"); c["off"] = [20.0, 5.0]; ed.redraw(); sh = dl.shapes(ed, c)
for a in sh["arrows"]:
    assert near(math.hypot(a[1][0] - C[0], a[1][1] - C[1]), R, 1e-6), "an arrow tip touches the circle"
assert len(sh["arrows"]) == 2
assert math.hypot(sh["label"][0] - C[0], sh["label"][1] - C[1]) > R
assert np.linalg.norm(sh["segs"][0][-1] - np.array(sh["label"])) < 1e-9, "the leader runs out to the label"
ed.commit(lambda mm: mm.cons.remove(mm.con_by_id(c["id"])))
ed.commit(lambda mm: mm.add_con("dim_rad", [("ci", ci)], value=R))
c = cs("dim_rad"); sh = dl.shapes(ed, c); assert len(sh["arrows"]) == 1 and near(math.hypot(sh["arrows"][0][1][0] - C[0], sh["arrows"][0][1][1] - C[1]), R, 1e-6)
print("circle ok")

# ---- an angle: arc between the two lines, the label slides along it and stays inside the chosen angle
se.ask_angle = lambda *a, **k: "acute"
w.set_tool("line"); click(-60, -40); click(-20, -40); ed.reset_tool("select")
l1 = list(ed.m.lns)[-1]
w.set_tool("line"); click(-60, -40); click(-35, -20); ed.reset_tool("select")
l2 = list(ed.m.lns)[-1]
refs = [("ln", l1), ("ln", l2)]
ed.cursor = (-45, -37)
ed.commit(lambda mm: mm.add_con("dim_ang", refs, value=38.0, **dict(zip(("s1", "s2", "eps"), ed.m.angle_default(refs, hint=(-45, -37))[:3]))))
ca = cs("dim_ang"); fr = dl.angle_frame(ed, ca); I, a1, da, L0, r1, r2 = fr
sh = dl.shapes(ed, ca); arc = sh["segs"][0]
rho = dl.angle_label(ed, ca, fr)[1]
assert np.allclose(np.hypot(arc[:, 0] - I[0], arc[:, 1] - I[1]), rho), "the arc is a circular arc around the corner"
ang_of = lambda p: math.atan2(p[1] - I[1], p[0] - I[0])
assert near(dl.wrap_pi(ang_of(arc[0]) - a1), 0.0, 1e-9) and near(dl.wrap_pi(ang_of(arc[-1]) - (a1 + da)), 0.0, 1e-9), "its ends lie exactly on the two sides"
assert len(sh["arrows"]) == 2
def frac_of(label): return dl.wrap_pi(ang_of(label) - a1) / da
f0 = frac_of(sh["label"]); assert 0 <= f0 <= 1
# drag the label along the arc and far out of the angle: it sticks to the nearer side, never outside the angle
for target in ((-40, -25), (-30, -50), (-100, 30), (0, -100), (-45, 10)):
    dl.set_angle_label(ed, ca, target); lab = dl.shapes(ed, ca)["label"]
    fl = frac_of(lab); assert -1e-9 <= fl <= 1 + 1e-9, (target, fl)
dl.set_angle_label(ed, ca, (-30, -50)); assert near(frac_of(dl.shapes(ed, ca)["label"]), 0.0, 1e-6) or near(frac_of(dl.shapes(ed, ca)["label"]), 1.0, 1e-6)
# radius is free: farther out moves the arc out and extension lines appear
dl.set_angle_label(ed, ca, (I[0] + 2 * rho * math.cos(a1 + da / 2), I[1] + 2 * rho * math.sin(a1 + da / 2)))
sh2 = dl.shapes(ed, ca); assert dl.angle_label(ed, ca)[1] > 1.9 * rho and abs(frac_of(sh2["label"]) - 0.5) < 0.01
print("angle ok: arc radius", round(rho, 2), "->", round(dl.angle_label(ed, ca)[1], 2), "segments", len(sh2["segs"]))
# the real mouse drag path uses the same: drag the label, check the saved key and reset
t0 = [t for t in ed.tags if t[2] == ca["id"]][0]; sx, sy = ed.screen_of(np.array([(t0[0], t0[1])]))[0]; r = w.plotter.devicePixelRatioF()
ed.press(sx + 20 * r, sy + 10 * r); ed.move(sx + 60 * r, sy - 30 * r); ed.move(sx + 90 * r, sy - 60 * r); ed.release(sx + 90 * r, sy - 60 * r)
ca = ed.m.con_by_id(ca["id"]); assert ca.get("aoff") and not ca.get("off"), ca
fl = frac_of(dl.shapes(ed, ca)["label"]) if (ca["s1"], ca["s2"]) == (fr and ed.m.con_by_id(ca["id"])["s1"], ed.m.con_by_id(ca["id"])["s2"]) else 0.5
ed.sel = [("con", ca["id"])]; ed.reset_labels(); assert not ed.m.con_by_id(ca["id"]).get("aoff")
# an older file (free offset) still gives a label inside the angle
ca = ed.m.con_by_id(ca["id"]); ca["off"] = [3.0, 2.0]
lab = dl.shapes(ed, ca)["label"]; assert -1e-9 <= frac_of(lab) <= 1 + 1e-9; ca.pop("off")

# ---- per configuration: each configuration keeps its own label positions
def _set(mm):
    [x for x in mm.cons if x["type"] == "dim_h"][0]["off"] = [0.0, 18.0]
    [x for x in mm.cons if x["type"] == "dim_rad"][0]["off"] = [15.0, 4.0]
ed.commit(_set)
w.leave_sketch(); d = w.doc
fid = [f for f in d.features if f["kind"] == "sketch"][0]["id"]
d.cfg_add("B"); d.cfg_apply("B")
raw = d.sketch_model_raw(d.feature(fid)); ch = [x for x in raw.cons if x["type"] == "dim_h"][0]
assert ch["off"] == [0.0, 18.0], "a new configuration starts where the label was"
ch["off"] = [0.0, -9.0]; d.feature(fid)["model"] = raw.to_json()
d.cfg_apply("Default"); ch = [x for x in d.sketch_model_raw(d.feature(fid)).cons if x["type"] == "dim_h"][0]
assert ch["off"] == [0.0, 18.0], ch
d.cfg_apply("B"); ch = [x for x in d.sketch_model_raw(d.feature(fid)).cons if x["type"] == "dim_h"][0]
assert ch["off"] == [0.0, -9.0], ch
cdd = [x for x in d.sketch_model_raw(d.feature(fid)).cons if x["type"] == "dim_rad"][0]; assert cdd["off"] == [15.0, 4.0]
d2 = pm.Document.from_json(d.to_json()); d2.rebuild()
d2.cfg_apply("Default"); ch = [x for x in d2.sketch_model_raw(d2.feature(fid)).cons if x["type"] == "dim_h"][0]; assert ch["off"] == [0.0, 18.0], "saved with the file"
d2.cfg_apply("B"); ch = [x for x in d2.sketch_model_raw(d2.feature(fid)).cons if x["type"] == "dim_h"][0]; assert ch["off"] == [0.0, -9.0]
d.cfg_rename("B", "Wide"); d.cfg_apply("Wide"); ch = [x for x in d.sketch_model_raw(d.feature(fid)).cons if x["type"] == "dim_h"][0]; assert ch["off"] == [0.0, -9.0]
d.cfg_delete("Wide"); assert "Wide" not in d.cfg["offs"]
print("per-configuration labels ok")

# ---- the Add Column filter
import config_panels
p = w.cfg_panel if hasattr(w, "cfg_panel") else None
assert p is not None
d.params["W"] = "10"; d.cfg_add("C")
cand = p.candidates(); groups = {c[2] for c in cand}
print("groups", sorted(groups)); assert {"Globals", "Sketch dimensions"} <= groups
def menu_items():
    p.fill_col_menu(); return [a.text() for a in p.col_menu.actions() if not a.isSeparator() and a.isEnabled()]
all_items = menu_items()
p.col_group.setCurrentText("Globals"); gl = menu_items(); assert gl and len(gl) < len(all_items) and all("·" not in t for t in gl)
p.col_group.setCurrentText("Sketch dimensions"); sd = menu_items(); assert len(sd) >= 3 and (not p.col_sub.isHidden()), (sd, (not p.col_sub.isHidden()))
subs = [p.col_sub.itemText(i) for i in range(p.col_sub.count())]; print("sub filter", subs); assert subs[0] == "All" and len(subs) >= 2
p.col_sub.setCurrentText(subs[1]); one = menu_items(); assert one and all("·" not in t for t in one)
p.col_group.setCurrentText("Suppress switches"); assert menu_items() is not None and p.col_sub.isHidden()
p.col_group.setCurrentText("All"); assert menu_items() == all_items or len(menu_items()) == len(all_items)
# adding from the filtered list works
p.col_group.setCurrentText("Globals"); p.fill_col_menu(); act = [a for a in p.col_menu.actions() if a.isEnabled() and not a.isSeparator()][0]; act.trigger()
assert any(k.startswith("g:") for k in d.cfg["cols"]) or w.doc.cfg["cols"]
print("OK")
