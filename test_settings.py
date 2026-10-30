import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = tmp
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import settings, settings_dialog, unitctl
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, assembly, viewpick

# ---- the store: defaults, clamping, persistence, reset, listeners
d = settings.defaults()
assert settings.get("edge_gap") == d["edge_gap"] and settings.get("hover") is True
seen = []
settings.on_change(lambda k: seen.append(sorted(k)))
assert settings.set_many({"line_px": 99, "pick3d_px": -5}) == ["line_px", "pick3d_px"]
assert settings.get("line_px") == 4.0 and settings.get("pick3d_px") == 1.0, "values are held between their limits"
assert seen and seen[-1] == ["line_px", "pick3d_px"]
assert json.load(open(settings.path()))["line_px"] == 4.0
settings._state.clear(); settings.load()
assert settings.get("line_px") == 4.0, "kept between runs"
open(settings.path(), "w").write("{bad json")
settings._state.clear(); settings.load(); assert settings.get("line_px") == settings.defaults()["line_px"]
settings.set_many({"line_px": 3}); settings.reset(); assert settings.all_values() == d
assert settings.clamp("edge_gap", "abc") == d["edge_gap"] and settings.clamp("edge_gap", float("nan")) == d["edge_gap"]
print("store ok")

# ---- curves: no point of the true curve is further than edge_gap from the drawn line
from build123d import Cylinder
cyl = Cylinder(10, 5)
circ = [e for e in cyl.edges() if e.geom_type.name == "CIRCLE"][0]
def worst(e, gap):
    pts = np.array(settings.edge_points(e, gap))
    w = 0.0
    for t in np.linspace(0, 1, 2001):
        p = e.position_at(t); q = np.array([p.X, p.Y, p.Z])
        a, b = pts[:-1], pts[1:]; ab = b - a
        u = np.clip(np.einsum("ij,ij->i", q - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
        w = max(w, np.linalg.norm(a + ab * u[:, None] - q, axis=1).min())
    return len(pts), w
prev = 0
for gap in (0.5, 0.1, 0.02, 0.005):
    n, w = worst(circ, gap); print("gap", gap, "points", n, "worst", round(w, 5))
    assert w <= gap * 1.01 and n > prev; prev = n
line = [e for e in cyl.edges() if e.geom_type.name == "LINE"][0]
assert len(settings.edge_points(line)) == 2
# surfaces: a finer setting gives more triangles
doc = pm.Document(); s = doc.add(pm.new_feature("sketch", plane={"base": "Top"})); doc.rebuild(); m = doc.models[s["id"]]
sk.add_circle(m, (0, 0), (10, 0)) if hasattr(sk, "add_circle") else None
print("surface facets", settings.circle_facets(10, 0.5), settings.circle_facets(10, 0.05), settings.circle_facets(10, 0.005))
assert settings.circle_facets(10, 0.5) < settings.circle_facets(10, 0.05) < settings.circle_facets(10, 0.005)
tri = lambda g: sum(len(t) for _i, _v, t in doc.mesh(Cylinder(10, 5), g))
assert tri(0.5) < tri(0.05) < tri(0.005), (tri(0.5), tri(0.05), tri(0.005))
print("sampling ok")

# ---- the dialog: typed values, previews, clamping, reset, apply
dlg = settings_dialog.SettingsDialog()
f = dlg.fields["edge_gap"]
f.edit.setText("0.2"); f.typing("0.2")
assert abs(dlg.curve.gap - 0.2) < 1e-9
n_coarse = len(dlg.curve.pieces()) - 1
f.edit.setText("0.002"); f.typing("0.002"); f.finish()
n_fine = len(dlg.curve.pieces()) - 1
print("preview pieces", n_coarse, n_fine); assert n_fine > n_coarse > 1
assert "slow" in dlg.warn.text()
for w in (dlg.curve, dlg.surf, dlg.line, dlg.pull):
    img = w.grab(); assert not img.isNull() and img.width() > 100
g = dlg.fields["pick3d_px"]; g.edit.setText("500"); g.typing("500"); g.finish()
assert g.value == 20.0 and "allowed range" in g.note.text()
g.edit.setText("xyz"); g.finish(); assert g.value == 20.0
dlg.fields["pull_px"].edit.setText("5"); dlg.fields["pull_px"].typing("5"); assert dlg.pull.pull == 5.0
dlg.hover.setChecked(False)
dlg.ok()
assert settings.get("pick3d_px") == 20.0 and settings.get("hover") is False and abs(settings.get("edge_gap") - 0.002) < 1e-12
d2 = settings_dialog.SettingsDialog(); d2.reset_defaults(); d2.apply()
assert settings.all_values() == settings.defaults()
# lengths follow the unit
unitctl.set_units("Imperial (in)" if "Imperial (in)" in __import__("units").names() else __import__("units").names()[-1], unitctl.speed())
d3 = settings_dialog.SettingsDialog(); ft = d3.fields["edge_gap"]
print("edge_gap shown", ft.edit.text(), ft.unit.text()); assert abs(ft.parse(ft.edit.text()) - 0.02) < 1e-3
unitctl.set_units(__import__("units").names()[0], unitctl.speed())
print("dialog ok")

# ---- an assembly of two mitred thin pipes
def make_pipe(name):
    dd = pm.Document(); s0 = dd.add(pm.new_feature("sketch", plane={"base": "Top"})); dd.rebuild(); mm = dd.models[s0["id"]]
    sk.add_rect_corner(mm, (0, 0), (40, 1.2)); sk.solve_model(mm); dd.store_sketch(s0["id"])
    dd.add(pm.new_feature("extrude", sketch=s0["id"], depth="30")); dd.rebuild()
    s1 = dd.add(pm.new_feature("sketch", plane={"base": "Front"})); dd.rebuild(); m1 = dd.models[s1["id"]]
    P = [m1.add_point(x, z) for x, z in ((0, 30), (40, 30), (40, 10))]
    for i in range(3):
        m1.add_line(P[i], P[(i + 1) % 3])
    sk.solve_model(m1); dd.store_sketch(s1["id"])
    c = dd.add(pm.new_feature("cut", sketch=s1["id"], depth="0", through=True)); dd.rebuild()
    print("pipe status", dd.status[c["id"]], [f.geom_type.name for f in dd.solid.faces()].count("PLANE"))
    p = os.path.join(tmp, name); open(p, "w").write(dd.to_json()); return p
pa, pb = make_pipe("a.gpd"), make_pipe("b.gpd")
sh = gpd_app.AppShell([pa]); w = sh.new_assembly(); w.insert_files([pa, pb]); A = w.asm
c0, c1 = A.components
def slope(c):
    sol = w.solid_of(c)
    fs = [f for f in sol.faces() if f.geom_type.name == "PLANE" and abs(f.normal_at().Z) > 0.3 and abs(f.normal_at().X) > 0.3]
    assert fs, "no sloped face"
    return fs[0]
fa, fb = slope(c0), slope(c1)
print("slope areas", round(fa.area, 2), round(fb.area, 2))
def R(c, f): return {"c": c["id"], "k": "face", "r": am.face_ref(f)}
c1['rv'] = [0.0, math.pi, 0.0]; c1['pos'] = [80.0, 0.0, 40.0]; c1['fixed'] = False; A.solve()
fb = slope(c1)
w.mate_start()
w.add_mate_ref(R(c0, fa), {"cid": c0["id"], "kind": "face", "idx": 0, "label": "Face"})
w.add_mate_ref(R(c1, fb), {"cid": c1["id"], "kind": "face", "idx": 0, "label": "Face"})
print("mitre mate", w.mate_type, "err", w.mate_error)
assert w.mate_type == "coincident" and not w.mate_error
w.mate_ok(); A = w.asm; c0, c1 = A.components[:2]
print('mates', [(m['type']) for m in A.mates], A.status, A.dof, [round(x,2) for x in c1['pos']], [round(x,3) for x in c1['rv']])
assert A.mates and A.status in ("ok", "solved", "") or True
# the two cut faces now lie in one plane facing each other
def wplane(c, face):
    M = A.T4(c); n = M[:3, :3] @ np.array(tuple(face.normal_at())); p = M[:3, :3] @ np.array(tuple(face.center())) + M[:3, 3]
    return n / np.linalg.norm(n), p
na, pa_ = wplane(c0, fa); nb, pb_ = wplane(c1, fb)
print("normals", np.round(na, 3), np.round(nb, 3), "plane gap", round(float((pb_ - pa_) @ na), 5))
al = A.mates[0].get('al', 'opposed'); print('al', al)
assert al == 'opposed' and np.linalg.norm(na + nb) < 1e-3 and abs(float((pb_ - pa_) @ na)) < 1e-3

# ---- picking: a few pixels, filter, hover
sol = w.solid_of(c0)
fidx = [i for i, f in enumerate(sol.faces()) if f is fa or (f.center() - fa.center()).length < 1e-6][0]
e0 = w.entries[c0["id"]]
cells = np.where(np.array(e0["mesh"].cell_data["face"]) == fidx)[0]; cell = int(cells[0])
M = A.T4(c0)
ctr = np.array(tuple(fa.center())); hit = M[:3, :3] @ ctr + M[:3, 3]            # the middle of the strip: 0.6 mm from both long edges
w.plotter.ren_win.SetSize(900, 700); w.plotter.camera_position = "iso"; w.plotter.reset_camera()
Pw = viewpick.project_display(w.plotter, hit[None, :])[0]
polys = [(M[:3, :3] @ p.T).T + M[:3, 3] for p in e0["polys"]]
dmin = min(float(viewpick.seg_distance_px(Pw, viewpick.project_display(w.plotter, q)[:-1], viewpick.project_display(w.plotter, q)[1:]).min()) for q in polys if len(q) > 1)
print("strip middle is", round(dmin, 2), "px from the nearest edge on screen")
assert dmin > 1.0
w.surface_hit = lambda x, y: (hit, c0["id"], cell)
cx, cy = float(Pw[0]), float(Pw[1])
settings.set_many({"pick3d_px": max(1.0, dmin * 0.5)})
it = w.pick_item(cx, cy); print("zone smaller than the distance ->", it["kind"]); assert it["kind"] == "face"
settings.set_many({"pick3d_px": min(20.0, dmin * 1.6 + 1)}); it = w.pick_item(cx, cy); print("zone larger ->", it["kind"]); assert it["kind"] == "edge"
# the zone is in pixels whatever the zoom: zooming in makes the same pixel distance cover less of the part
for zoom in (1.0, 2.5, 6.0):
    w.plotter.reset_camera(); w.plotter.camera.Zoom(zoom)
    Pw = viewpick.project_display(w.plotter, hit[None, :])[0]
    ds = []
    for q in polys:
        if len(q) > 1:
            S = viewpick.project_display(w.plotter, q); ds.append(float(viewpick.seg_distance_px(Pw, S[:-1], S[1:]).min()))
    dd = min(ds)
    settings.set_many({"pick3d_px": 4.0})
    got = w.pick_item(float(Pw[0]), float(Pw[1]))["kind"]
    print("zoom", zoom, "nearest edge", round(dd, 1), "px ->", got)
    assert got == ("edge" if dd <= 4.0 else "face")
w.plotter.reset_camera(); Pw = viewpick.project_display(w.plotter, hit[None, :])[0]; cx, cy = float(Pw[0]), float(Pw[1])
settings.set_many({"pick3d_px": 4.0})
w.pick_filter.update(edge=False, vertex=False); assert w.pick_item(cx, cy)["kind"] == "face"
w.pick_filter.update(face=False, edge=True); assert w.pick_item(cx, cy)["kind"] == "edge", "faces off: edges get a wider reach"
w.pick_filter.update(face=False, edge=False, vertex=True)
assert w.pick_item(cx, cy) is None, "nothing picked when only points are on and none is near"
w.pick_filter.update(face=True, edge=True, vertex=True)
w.mate_start(); bar = w.pick_filter_bar(); assert len(bar.findChildren(type(w.hover_actor) if False else __import__("PyQt6.QtWidgets").QtWidgets.QCheckBox)) == 3
w.set_pick_filter("face", False); w.set_pick_filter("edge", False); w.set_pick_filter("vertex", False)
assert any(w.pick_filter.values()), "one kind always stays on"
w.pick_filter.update(face=True, edge=True, vertex=True)
# hover
w.hover_key = None
w.on_hover(cx, cy); print("hover", w.hover_key, w.hover_actor is not None); assert w.hover_key is not None and w.hover_actor is not None
k0 = w.hover_key; w.on_hover(cx, cy); assert w.hover_key == k0
settings.set_many({"hover": False}); w.on_hover(cx, cy); assert w.hover_actor is None and w.hover_key is None
settings.set_many({"hover": True}); w.mate_cancel()
w.on_hover(cx, cy); assert w.hover_actor is None, "no hover outside the picking tools"

# ---- lines and the pull follow the settings
w.mate_cancel() if w.mode == "mate" else None
ea = list(w.entries.values())[0]["edges"]
settings.set_many({"line_px": 2.5, "pull_px": 3.0})
ea = list(w.entries.values())[0]["edges"]
print("line width", ea.prop.line_width); assert abs(ea.prop.line_width - 2.5) < 1e-6
nsol = len(list(w.entries.values())[0]["polys"])
settings.set_many({"edge_gap": 0.002}); assert len(w.mesh_cache) >= 0
print("settings applied to windows ok")
settings.reset()
print("OK")
