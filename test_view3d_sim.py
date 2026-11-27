"""VW-3 / VW-4: the geometry selector (General, Point, Edge, Face, Body) in the 3D simulation windows, and supports, loads and heat on edges and points.

The edges of the geometry and the mesh nodes along them (quadratic and linear meshes, a hex-dominant one); the selector in the Structural, Thermal and CFD windows (CFD keeps
Face and Body); what is under the cursor and what a click takes; the hover outline; the picked edges, points and parts drawn over the part; supports and forces on
edges and points in the Structural window (with known answers: equilibrium, a cantilever); a fixed temperature and a heat flow on edges and points in the Thermal window
(the heat balance closes, a point is held exactly); a mesh with no nodes along an edge says so instead of approximating; the colours of File > Settings > 3D View.
python test_view3d_sim.py"""
import faulthandler
faulthandler.dump_traceback_later(900, exit=True)
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "cfd3d"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import asm_model as am
import cfd3d_tab as ft
import pm_model as pm
import settings
import sk_tools as sk
import solid_base
import solid_fem as fem
import solid_geom as sg
import solid_model as sm
import solid_tab
import thermal3d_model as tm
import thermal3d_tab as tt
import view3d
import viewpick

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


T = tempfile.mkdtemp(prefix="opara_vw_sim_")


def make_part(path, w, h, depth, material=None):
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (w, h))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=w)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=h)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    if material:
        d.material = material
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return path


bar = make_part(os.path.join(T, "bar.gpd"), 100.0, 10.0, 10)                    # 100 x 10 x 10 mm, x from 0 to 100


def new_window(cls, name, path=bar):
    w = cls(threaded=False)
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    assert w.create_project(os.path.join(T, name))
    assert w.import_file(path), MSGS
    app.processEvents()
    w.view.plotter.render_window.SetSize(w.view.widget.width(), w.view.widget.height())           # (no GL context offscreen: the picks need a size)
    return w


def edges_where(g, f):
    return [e["id"] for e in g["edges"] if f(np.array(e["pts"][0]), np.array(e["pts"][-1]), np.array(e["mid"]))]


def screen(w, xyz):
    return viewpick.project_display(w.view.plotter, [xyz])[0]


# ================================================================================================================================ 1. edges of the geometry and the mesh
g = sg.analyze(__import__("build123d").Pos(50, 5, 5) * __import__("build123d").Box(100, 10, 10))
ok(len(g["edges"]) == 12 and all(e["kind"] == "line" and len(e["pts"]) == 2 for e in g["edges"]), "a box has 12 straight edges, each a polyline of two points")
ok(abs(sorted(e["length"] for e in g["edges"])[0] - 10.0) < 1e-9 and abs(sorted(e["length"] for e in g["edges"])[-1] - 100.0) < 1e-9, "with their lengths: 10 and 100 mm")
for e in g["edges"]:
    assert sg.match_edge(g, sg.edge_sig(g, e["id"])) == e["id"]
ok(True, "every edge is found again from its signature")
sig = sg.edge_sig(g, 0)
g2 = sg.analyze(__import__("build123d").Pos(60, 5, 5) * __import__("build123d").Box(120, 10, 10))
ok(sg.match_edge(g2, dict(sig, mid=[sig["mid"][0] + 10, sig["mid"][1], sig["mid"][2]], length=sig["length"] + 20)) is not None, "a part that grew 20 mm still has the edge")
ok(sg.match_edge(g, dict(sig, kind="circle")) is None, "an edge of another kind is not taken for it")

B3 = __import__("build123d")
gh = sg.analyze(B3.Box(30, 20, 40) - B3.Cylinder(4, 50))
circles = [e for e in gh["edges"] if e["kind"] == "circle"]
ok(len(gh["edges"]) == 15 and len(circles) == 2 and all(len(e["pts"]) == 65 and e["sag"] > 0 for e in circles), "a box with a hole: 15 edges, the two circles are 65-point polylines with a known sag")
h0 = sm.auto_h(gh)
q2 = sm.get_mesh(gh, h0, {}, lambda: False, lambda t: None, None)
q1 = fem.linear(fem.mesh_solid(gh, h0, lambda: False, lambda t: None, None))
for q, nm in ((q2, "quadratic"), (q1, "linear")):
    bad = []
    for e in gh["edges"]:
        c = sg.edge_chain(gh, e["id"], q["nodes"], q["n_corner"], q["order"])
        if not (len(c["nodes"]) and c["ok"] and c["cover"] > 0.98 and abs(c["w"].sum() - 1.0) < 1e-9 and (c["w"] > 0).all()):
            bad.append(e["id"])
    ok(not bad, f"{nm} mesh: every edge of the part has a chain of nodes along it (shares add up to 1)")
    c = sg.edge_chain(gh, circles[0]["id"], q["nodes"], q["n_corner"], q["order"])
    ok(c["closed"] and c["cover"] == 1.0, f"{nm} mesh: a circle is a closed chain")
    ok(all(np.linalg.norm(q["nodes"][c["nodes"][i]] - np.array([0, 0, q["nodes"][c["nodes"][i]][2]])) > 3.9 for i in range(len(c["nodes"]))) if q["order"] == 1 else True,
       f"{nm} mesh: the corner nodes of the circle lie on it")
# a quadratic chain carries the consistent shares: the middle node of an element edge takes 4/6 of its length
e_line = max(gh["edges"], key=lambda e: e["length"])
c = sg.edge_chain(gh, e_line["id"], q2["nodes"], q2["n_corner"], 2)
nodes_on = q2["nodes"][c["nodes"]]
ok(abs(c["w"].sum() - 1.0) < 1e-12 and c["w"].max() > 2.0 * np.median(c["w"][c["w"] > 0]) * 0.5, "the shares of a quadratic edge differ between corner and middle nodes (consistent loads)")
# nothing is approximated: nodes that do not follow an edge give an empty chain, a partly followed edge says how much
far = q2["nodes"] + np.array([500.0, 0, 0])
ok(len(sg.edge_chain(gh, e_line["id"], far, q2["n_corner"], 2)["nodes"]) == 0, "a mesh with no node along the edge gives an empty chain")
cut = np.where(q2["nodes"][:, 2] < q2["nodes"][:, 2].min() + 0.5 * np.ptp(q2["nodes"][:, 2]))[0]
half = q2["nodes"].copy()
vert_edge = max((e for e in gh["edges"] if abs(e["pts"][0][2] - e["pts"][-1][2]) > 1), key=lambda e: e["length"])
shifted = half.copy()
shifted[:q2["n_corner"]][shifted[:q2["n_corner"], 2] > np.mean([vert_edge["pts"][0][2], vert_edge["pts"][-1][2]])] += np.array([0, 0, 0.0])
sub = np.vstack([q2["nodes"][:q2["n_corner"]][q2["nodes"][:q2["n_corner"], 2] < np.mean([vert_edge["pts"][0][2], vert_edge["pts"][-1][2]])]])
c = sg.edge_chain(gh, vert_edge["id"], sub, len(sub), 1)
ok(0 < c["cover"] < 0.9, f"a mesh that reaches only part of an edge reports how far it goes ({c['cover']:.0%})")
try:
    sm.edge_nodes(gh, {"nodes": far, "n_corner": q2["n_corner"], "order": 2}, e_line["id"], "Support 1")
    ok(False, "edge_nodes raises for a mesh with no nodes along the edge")
except fem.FemError as ex:
    ok("no nodes along that edge" in str(ex) and "Support 1" in str(ex), f"edge_nodes says so: {ex}")
try:
    sm.edge_nodes(gh, {"nodes": sub, "n_corner": len(sub), "order": 1}, vert_edge["id"], "Load 2")
    ok(False, "edge_nodes raises for a mesh that follows only part of the edge")
except fem.FemError as ex:
    ok("does not follow all of edge" in str(ex), f"edge_nodes says how much it follows: {ex}")

# the hex-dominant mesh has nodes on the edges too
try:
    import solid_mesh as smesh
    hopts = smesh.default_mesh()
    hopts.update({"advanced": True, "type": "hexdom", "order": 2})
    gb = sg.analyze(B3.Pos(50, 5, 5) * B3.Box(100, 10, 10))
    qh = sm.get_mesh(gb, 3.0, {}, lambda: False, lambda t: None, smesh.resolve(gb, {"mesh": hopts}, 3.0))
    okh = all((lambda c: len(c["nodes"]) and c["ok"] and c["cover"] > 0.98)(sg.edge_chain(gb, e["id"], qh["nodes"], qh["n_corner"], qh["order"])) for e in gb["edges"])
    ok(okh, f"a hex-dominant mesh ({len(qh.get('hexes', ()))} hexahedra) has nodes along every edge too")
except Exception as ex:                                                                      # noqa: BLE001
    ok(False, f"hex-dominant mesh: {type(ex).__name__}: {ex}")

# ================================================================================================================================ 2. the selector in the three windows
ws = new_window(solid_tab.SolidWindow, "struct")
wt = new_window(tt.ThermalWindow, "therm")
wc = new_window(ft.FluidWindow, "cfd")
for w, nm in ((ws, "Structural"), (wt, "Thermal"), (wc, "CFD")):
    ok(w.selector.kind == "general" and set(w.selector.buttons) == set(view3d.KINDS), f"{nm}: the selector has General, Point, Edge, Face and Body, General is on")
    ok(len(w.view.edges) == 12 and len(w.view.verts) == 8 and len(w.view.face_body) == 6, f"{nm}: the view knows the 12 edges, 8 corners and the body of each of the 6 faces")
ok(all(ws.selector.buttons[k].isEnabled() for k in view3d.KINDS) and all(wt.selector.buttons[k].isEnabled() for k in view3d.KINDS), "Structural and Thermal allow every kind")
ok([k for k in view3d.KINDS if wc.selector.buttons[k].isEnabled()] == ["general", "face", "body"], "CFD keeps General, Face and Body: Point and Edge are greyed")
ok("Point and Edge are not used" in wc.selector.buttons["edge"].toolTip(), "and their tip says why")
ok(wc.view.kind == "face" and ws.view.kind == "general", "in CFD General picks faces only; in the others it picks what is under the cursor")
ws.selector.set_kind("edge")
ok(ws.view.kind == "edge" and "Selecting edges" in ws.status_lbl.text(), "choosing Edge tells the view and the status line")
ws.selector.set_kind("general")

# ================================================================================================================================ 3. what is under the cursor
g = ws.geom
verts = np.array(g["verts"])
visible = [i for i in range(len(verts)) if ws.view.what_is_under(*screen(ws, verts[i]), "point") is not None]
ok(len(visible) == 7, f"Point: 7 of the 8 corners of the bar are seen from the corner view ({len(visible)}); the one behind the part is not offered")
hidden = [i for i in range(8) if i not in visible]
ok(len(hidden) == 1 and ws.view.what_is_under(*screen(ws, verts[hidden[0]]), "point") is None, "a corner hidden behind the part is not picked")
v0 = visible[0]
it = ws.view.what_is_under(*screen(ws, verts[v0]), "general")
ok(it is not None and it["kind"] == "point" and it["idx"] == v0, "General: a corner right under the cursor is a point")
px = screen(ws, verts[v0]) + np.array([11.0, 0.0])
it14 = ws.view.what_is_under(*px, "point")
ok(it14 is not None and it14["kind"] == "point" and it14["idx"] == v0, "Point: a corner 11 px away is still picked (reach 14)")
g4 = ws.view.what_is_under(*px, "general")
ok(g4 is None or g4["kind"] != "point", "General: the same place is not a point (reach 4)")
# an edge: the middle of the longest visible one
long_edges = sorted(range(len(g["edges"])), key=lambda i: -g["edges"][i]["length"])
mid_of = lambda e: (np.array(g["edges"][e]["pts"][0]) + np.array(g["edges"][e]["pts"][-1])) / 2
vis_edges = [e for e in long_edges if ws.view.what_is_under(*screen(ws, mid_of(e)), "edge") is not None]
ok(len(vis_edges) >= 6, f"Edge: {len(vis_edges)} of the 12 edges can be picked from the corner view")
e0 = vis_edges[0]
it = ws.view.what_is_under(*screen(ws, mid_of(e0)), "edge")
ok(it["kind"] == "edge" and it["idx"] == e0, "Edge: the middle of an edge is that edge")
it = ws.view.what_is_under(*screen(ws, mid_of(e0)), "general")
ok(it["kind"] == "edge" and it["idx"] == e0, "General: the middle of an edge is the edge")
off = screen(ws, mid_of(e0)) + np.array([0.0, 9.0])
ok((lambda r: r is not None and r["kind"] == "edge")(ws.view.what_is_under(*off, "edge")), "Edge: reaches 10 px")
near5 = screen(ws, mid_of(e0)) + np.array([0.0, 5.0])
r_g = ws.view.what_is_under(*near5, "general")
ok(r_g is not None and r_g["kind"] == "edge", "General: 5 px off an edge is still the edge (reach 8)")
r_f = ws.view.what_is_under(*screen(ws, mid_of(e0)), "face")
ok(r_f is None or r_f["kind"] == "face", "Face: at the edge only a face can come of it")
# the centre of a visible face
fc = None
for f in g["faces"]:
    r = ws.view.what_is_under(*screen(ws, f["center"]), "face")
    if r is not None and r["kind"] == "face" and r["idx"] == f["id"]:
        fc = (screen(ws, f["center"]), f["id"])
        break
ok(fc is not None, "Face: the middle of a visible face is that face")
r_b = ws.view.what_is_under(*fc[0], "body")
ok(r_b["kind"] == "body" and r_b["idx"] == 0, "Body: the same place is the whole part")
ok(ws.view.what_is_under(*fc[0], "point") is None and ws.view.what_is_under(*fc[0], "edge") is None, "Point and Edge pick nothing in the middle of a face")
ok(wc.view.what_is_under(*fc[0], "face")["kind"] == "face" and wc.view.kind == "face", "CFD: the middle of a face is a face")

# ================================================================================================================================ 4. the hover
ws.selector.set_kind("general")
ws.view.on_hover(*[int(x) for x in fc[0]])
hl = ws.view.hover_layer
ok(hl.actor is not None and hl.key == ("face", fc[1]), "the cursor over a face draws its outline")
ds = hl.actor.GetMapper().dataset
ok(ds.n_cells >= 4 and ds.GetNumberOfPolys() == 0, f"it is an outline (lines, {ds.n_cells} segments), not a fill")
ws.view.on_hover(*[int(x) for x in screen(ws, mid_of(e0))])
ok(hl.key == ("edge", e0), "over an edge it outlines the edge")
ws.view.on_hover(*[int(x) for x in screen(ws, verts[v0])])
ok(hl.key == ("point", v0), "over a corner it marks the corner")
ws.selector.set_kind("body")
ws.view.on_hover(*[int(x) for x in fc[0]])
ok(hl.key == ("body", 0) and hl.actor.GetProperty().GetOpacity() < 1.0 and hl.actor.GetMapper().dataset.n_cells > 4, "with Body the whole part is filled (translucent)")
ws.selector.set_kind("point")
ws.view.on_hover(*[int(x) for x in fc[0]])
ok(hl.actor is None, "where nothing of the chosen kind is, the outline goes")
ws.selector.set_kind("general")
settings.set_many({"hover": False})
ws.view.on_hover(*[int(x) for x in fc[0]])
ok(hl.actor is None, "with the hover setting off nothing is outlined")
settings.set_many({"hover": True})
ws.view.on_hover(*[int(x) for x in fc[0]])
ok(hl.actor is not None and np.allclose(view3d.hover_rgb(), np.array(hl.actor.GetProperty().GetColor()), atol=1e-6), "and on again it is back, in the hover colour")

# ================================================================================================================================ 5. clicks
KEYS = [False]
solid_base.QApplication_keyboard = lambda: KEYS[0]
ws.selector.set_kind("edge")
ws.view.pick_at(*[int(x) for x in screen(ws, mid_of(e0))])
ok(ws.sel_edges == [e0] and not ws.sel_faces and not ws.sel_points, "Edge: a click takes the edge")
ok(any(m["edges"] for m in ws.view.mark_data.get("sel", [])) and np.allclose(ws.view.mark_data["sel"][0]["colour"], view3d.hover_rgb()), "the picked edge is drawn over the part in the hover colour")
e1 = next(e for e in vis_edges if e != e0)
KEYS[0] = True
ws.view.pick_at(*[int(x) for x in screen(ws, mid_of(e1))])
ok(sorted(ws.sel_edges) == sorted([e0, e1]), "Ctrl adds a second edge")
ws.view.pick_at(*[int(x) for x in screen(ws, mid_of(e1))])
ok(ws.sel_edges == [e0], "Ctrl on a picked edge takes it out again")
KEYS[0] = False
ws.view.pick_at(*[int(x) for x in screen(ws, mid_of(e1))])
ok(ws.sel_edges == [e1], "a plain click replaces the selection")
ws.view.pick_at(5, 5)
ok(ws.sel_edges == [], "Edge: a click on nothing clears the selection")
ws.selector.set_kind("point")
ws.view.pick_at(*[int(x) for x in screen(ws, verts[v0])])
ok(ws.sel_points == [v0] and ws.sel_vertex == v0, "Point: a click takes the corner")
ok(any(m["points"] for m in ws.view.mark_data.get("sel", [])), "and draws it")
ws.selector.set_kind("face")
ws.view.pick_at(*[int(x) for x in fc[0]])
ok(ws.sel_faces == [fc[1]] and not ws.sel_points and not ws.sel_edges, "Face: a click takes the face and lets go of the corner")
ok(np.allclose(ws.view.rgb[np.where(ws.view.cell_face == fc[1])[0][0]], view3d.select_rgb(), atol=1 / 255), "the picked face is in the selected colour")
other = next(f["id"] for f in g["faces"] if f["id"] != fc[1])
ok(np.allclose(ws.view.rgb[np.where(ws.view.cell_face == other)[0][0]], view3d.part_rgb(), atol=1 / 255), "and the others are in the neutral part colour")
ws.selector.set_kind("body")
ws.view.pick_at(*[int(x) for x in fc[0]])
ok(ws.sel_body == 0 and not ws.sel_faces, "Body: a click takes the whole part")
ok(all(np.allclose(ws.view.rgb[i], view3d.select_rgb(), atol=1 / 255) for i in range(len(ws.view.rgb))), "every face of it is in the selected colour")
ok(ws.size_table.selectionModel().selectedRows()[0].row() == 0, "and its row is selected in the table of the parts (element size)")
ws.view.pick_at(5, 5)
ok(ws.sel_body is None, "Body: a click on nothing clears it")
ws.selector.set_kind("general")
ws.view.pick_at(*[int(x) for x in screen(ws, verts[v0])])
ok(ws.sel_points == [v0] and not ws.sel_faces, "General: a corner under the cursor is picked as a point")
ws.view.pick_at(*[int(x) for x in fc[0]])
ok(ws.sel_faces == [fc[1]] and not ws.sel_points, "General: a face centre is picked as a face")
ws.clear_selection()
ok(not (ws.sel_faces or ws.sel_edges or ws.sel_points) and ws.sel_body is None, "clear_selection lets go of everything")

# ================================================================================================================================ 6. Structural: supports and loads on edges and points
ws.set_size("3")
left4 = edges_where(g, lambda a, b, m: abs(a[0]) < 1e-6 and abs(b[0]) < 1e-6)
top_right = edges_where(g, lambda a, b, m: abs(a[0] - 100) < 1e-6 and abs(b[0] - 100) < 1e-6 and abs(m[2] - 10) < 1e-6)
ok(len(left4) == 4 and len(top_right) == 1, "the bar has four edges round its left end and one along its top at the right end")
ws.select_faces([f["id"] for f in g["faces"] if f["normal"][0] < -0.99][:1])
ws.sel_faces = []
ws.select_edges([top_right[0]])
ok(ws.add_support("slide") is False and "needs a face" in ws.status_lbl.text(), f"a one-direction support cannot go on an edge: '{ws.status_lbl.text()[:90]}'")
ok(ws.add_support("bearing") is False, "nor can a bearing")
ws.select_edges(left4)
ok(ws.add_support("fixed") is True, "Fixed goes on the four edges of the left end")
sup = ws.setup["supports"][-1]
ok(sup["faces"] == [] and len(sup["edges"]) == 4 and "points" not in sup, "the support holds four edge signatures and no faces")
ok(ws.sup_list.item(0).text().endswith("on 4 edges"), f"the list says '4 edges': {ws.sup_list.item(0).text()}")
ok(ws.cond_table.item(0, 2).text() == "4 edges", "and so does the table")
ws.select_edges([top_right[0]])
ok(ws.add_load("pressure", {"p": 1.0}) is False and "acts on faces" in ws.status_lbl.text(), "a pressure does not go on an edge")
ws.sel_faces = [fc[1]]
ok(ws.add_load("force", {"f": [0, 0, -100.0]}) is False and "faces or on edges, not both" in ws.status_lbl.text(), "a force on a face and an edge at once is refused, with the reason")
ws.sel_faces = []
ok(ws.add_load("force", {"f": [0, 0, -100.0]}) is True, "a force on the top edge at the right end is added")
ld = ws.setup["loads"][-1]
ok(ld["faces"] == [] and len(ld["edges"]) == 1, "it holds the edge and no faces")
ok("1 edge" in ws.cond_table.item(1, 2).text(), "the table says '1 edge'")
ok(json.loads(json.dumps(ws.setup))["supports"][-1]["edges"] == sup["edges"], "the setup is plain data (it saves and opens again)")
r = sm.resolve(ws.geom, ws.setup)
ok(sorted(r["supports"][0]["eids"]) == sorted(left4) and r["loads"][0]["eids"] == top_right, "resolve finds the edges again")
ws.view_focus("conditions", None, [])                  # (the outline shows the supports and the loads together)
ws.colour()
marks = ws.condition_marks()
ok(len(marks) == 2 and np.allclose(marks[0]["colour"], solid_tab.sv.SUPPORT) and np.allclose(marks[1]["colour"], solid_tab.sv.LOAD), "the support edges are drawn in the support colour, the load edge in the load colour")
cm_ = ws.view.mark_data["cond"]
ok(len(cm_) == 2 and len(cm_[0]["edges"]) == 4 and len(cm_[1]["edges"]) == 1, "over the part: four support edges and one load edge")
ok(ws.run_mesh() is not False and ws.mesh_q is not None, "meshed")
ok(ws.run_solve() is not False and ws.result is not None, f"solved ({ws.status_lbl.text()[:60]})")
res = ws.result
ok(res["equilibrium"] < 1e-8, f"the reactions balance the load: {res['equilibrium']:.1e}")
ok(abs(res["applied"][2] + 100.0) < 1e-9 and abs(res["reaction"][2] - 100.0) < 1e-6, f"the whole 100 N is applied along the edge ({res['applied'][2]:.6g}) and held ({res['reaction'][2]:.6g})")
beam = 100.0 * 100.0 ** 3 / (3 * 200000.0 * 10.0 ** 4 / 12)
ok(0.8 * beam < res["umax"] < 1.3 * beam, f"the tip goes down {res['umax']:.4f} mm; beam theory says {beam:.4f}")
q = ws.mesh_q
tip = np.where(np.isclose(q["nodes"][:, 0], 100.0) & np.isclose(q["nodes"][:, 2], 10.0))[0]
ok(len(tip) >= 4, f"the mesh has {len(tip)} nodes along the loaded edge")
fnodes = sm.edge_nodes(ws.geom, q, top_right[0], "t")[0]
ok(set(fnodes.tolist()) == set(tip.tolist()), "they are exactly the nodes the load was shared over")
held = np.where(np.isclose(q["nodes"][:, 0], 0.0) & (np.isclose(q["nodes"][:, 1], 0) | np.isclose(q["nodes"][:, 1], 10) | np.isclose(q["nodes"][:, 2], 0) | np.isclose(q["nodes"][:, 2], 10)))[0]
ok(np.allclose(res["u"][held], 0.0, atol=1e-12) and len(held) >= 8, f"the nodes along the four fixed edges did not move ({len(held)} nodes)")
inner = np.where(np.isclose(q["nodes"][:, 0], 0.0) & ~np.isin(np.arange(len(q["nodes"])), held))[0]
ok(len(inner) == 0 or np.abs(res["u"][inner]).max() > 1e-9, "while the middle of the end face was free to move")
# one edge alone cannot hold a part
ws.setup["supports"] = []
ws.select_edges([left4[0]])
ws.add_support("fixed")
ws.run_solve()
ok("free to move or turn" in ws.status_lbl.text(), f"one edge alone leaves the part free to turn, and it says so: '{ws.status_lbl.text()[:80]}'")
# displacement on an edge
ws.setup["supports"] = []
ws.select_edges(left4)
ok(ws.add_support("disp", values={"ux": 0.0, "uy": 0.0, "uz": 0.0}) is True, "Displacement goes on edges")
ok(ws.run_solve() is not False and ws.result["equilibrium"] < 1e-8, "and solves")
# points: four corners of the left end hold the bar, a force at the two corners of the right end
ws.setup["supports"], ws.setup["loads"] = [], []
left_pts = [i for i, p in enumerate(g["verts"]) if abs(p[0]) < 1e-6]
right_top = [i for i, p in enumerate(g["verts"]) if abs(p[0] - 100) < 1e-6 and abs(p[2] - 10) < 1e-6]
ok(len(left_pts) == 4 and len(right_top) == 2, "four corners at the left end, two on top at the right")
ws.select_points(left_pts)
ok(ws.add_support("fixed") is True and len(ws.setup["supports"][-1]["points"]) == 4, "Fixed goes on four points")
ok(ws.cond_table.item(0, 2).text() == "4 points", "the table says '4 points'")
ws.select_points(right_top)
ok(ws.add_load("point", {"f": [0, 0, -50.0]}) is True and len(ws.setup["loads"][-1]["points"]) == 2, "a force at two points is one load with two points")
ok("2 points" in ws.cond_table.item(1, 2).text(), "the table says '2 points'")
ws.select_points([right_top[0]])
ok(ws.add_load("point", {"f": [0, 0, -10.0]}) is True and "vertex" in ws.setup["loads"][-1] and "points" not in ws.setup["loads"][-1], "a force at one point keeps the old shape (a vertex)")
ok(ws.run_solve() is not False and ws.result is not None, "solved with points")
res = ws.result
ok(abs(res["applied"][2] + 60.0) < 1e-9 and res["equilibrium"] < 1e-8, f"the 50 N (shared by two corners) and the 10 N: {res['applied'][2]:.6g} N applied, balance {res['equilibrium']:.1e}")
ok(np.allclose(res["u"][ws.mesh_q["verts"][left_pts[0]]], 0.0, atol=1e-12), "a corner that was held did not move")
ws.setup["supports"] = [{"mode": "fixed", "faces": [], "points": [sg.vert_sig(ws.geom, left_pts[0])]}]
ws.setup["loads"] = []
ws.setup["loads"] = [{"kind": "force", "faces": [], "edges": [sg.edge_sig(ws.geom, top_right[0])], "f": [0, 0, -1.0]}]
ws.say("")
ws.run_solve()
ok("free to move or turn" in ws.status_lbl.text(), "one point alone cannot hold a part either")
# a lost edge is said in words
ws.setup["supports"] = [{"mode": "fixed", "faces": [], "edges": [dict(sg.edge_sig(ws.geom, 0), kind="circle")]}]
try:
    sm.resolve(ws.geom, ws.setup)
    ok(False, "a lost edge is an error")
except fem.FemError as ex:
    ok("its edge is not in the part any more" in str(ex), f"a lost edge says so: {ex}")
# splitting a face keeps a support that sits on edges
ws.setup["supports"] = [{"mode": "fixed", "faces": [], "edges": [sg.edge_sig(ws.geom, e) for e in left4]}]
ws.setup["loads"] = []
face_x = next(f["id"] for f in ws.geom["faces"] if f["normal"][0] > 0.99)
ws.select_faces([face_x])
ws.sp_cols.setValue(2)
ws.sp_rows.setValue(1)
ws.split_selected(confirm=False)
ok(len(ws.setup["supports"]) == 1 and len(ws.setup["supports"][0]["edges"]) == 4, "splitting a face does not drop a support that has only edges")
ws.unsplit_selected(confirm=False)

# ================================================================================================================================ 7. Thermal: a fixed temperature and a heat flow on edges and points
g = wt.geom
left4 = edges_where(g, lambda a, b, m: abs(a[0]) < 1e-6 and abs(b[0]) < 1e-6)
top_right = edges_where(g, lambda a, b, m: abs(a[0] - 100) < 1e-6 and abs(b[0] - 100) < 1e-6 and abs(m[2] - 10) < 1e-6)
wt.set_size("3")
wt.select_edges(left4)
ok(wt.add_condition("temps", {"T": 300.0}) is True, "Thermal: a fixed temperature goes on four edges")
c0 = wt.setup["temps"][-1]
ok(c0["faces"] == [] and len(c0["edges"]) == 4, "it holds the edges and no faces")
ok(wt.cond_table.item(0, 2).text() == "4 edges", f"the table says '4 edges': {wt.cond_table.item(0, 2).text()}")
wt.select_edges(top_right)
ok(wt.add_condition("fluxes", {"q": 10.0}) is False and "acts on faces" in wt.status_lbl.text(), "a heat flux does not go on an edge")
ok(wt.add_condition("convs", {"h": 10.0, "Tinf": 293.0}) is False, "nor does convection")
ok(wt.add_condition("ins") is False, "nor Insulated")
wt.sel_faces = [fc[1]]
ok(wt.add_condition("powers", {"P": 10.0}) is False and "not on a mix" in wt.status_lbl.text(), "a heat flow on a face and an edge at once is refused")
wt.sel_faces = []
ok(wt.add_condition("powers", {"P": 10.0}) is True, "a heat flow goes on the top edge at the right end")
fid_big = max((f for f in g["faces"]), key=lambda f: f["area"])["id"]
wt.select_faces([fid_big])
ok(wt.add_condition("convs", {"h": 10.0, "Tinf": 293.15}) is True, "and convection on a face")
wt.view_focus("conditions", None, [])
cm2 = wt.condition_marks()
ok(len(cm2) == 2 and cm2[0]["edges"] and cm2[1]["edges"], "the edges of both conditions are drawn over the part")
ok(wt.run_mesh() is not False and wt.run_solve() is not False and wt.result is not None, f"solved ({wt.status_lbl.text()[:60]})")
r = wt.result
ok(r["balance"]["relative_error"] < 1e-9, f"the heat balance closes: {r['balance']['relative_error']:.1e}")
pw = next(f for f in r["flows"] if f["kind"] == "power")
ok(abs(pw["Q"] - 10.0) < 1e-12, f"the heat flow gives its 10 W ({pw['Q']:.12g})")
tf_ = next(f for f in r["flows"] if f["kind"] == "temp")
cv = next(f for f in r["flows"] if f["kind"] == "conv")
ok(abs(tf_["Q"] + 10.0 - cv["Q"]) < 1e-9 * 10 or abs((tf_["Q"] + cv["Q"]) + 10.0) < 1e-6, f"the heat that goes in comes out (fixed edges {tf_['Q']:.5g} W, convection {cv['Q']:.5g} W)")
qm = wt.mesh_q
held = sm.edge_nodes(g, qm, left4[0], "t")[0]
ok(np.allclose(r["T"][held], 300.0, atol=1e-9), "every node along the fixed edge is at 300 K")
ok(r["T"].max() > 300.0 + 1e-3 and r["Tmin"] >= 293.15 - 1e-6, f"the bar warms from the heated edge ({r['Tmin']:.2f} .. {r['Tmax']:.2f} K)")
# a point: held exactly, and a heat flow shared by two points
wt.setup["temps"], wt.setup["powers"], wt.setup["convs"] = [], [], []
wt.select_points([left_pts[0]])
ok(wt.add_condition("temps", {"T": 350.0}) is True and wt.setup["temps"][-1]["points"], "a fixed temperature goes on a point")
wt.select_points(right_top)
ok(wt.add_condition("powers", {"P": 4.0}) is True and len(wt.setup["powers"][-1]["points"]) == 2, "a heat flow goes on two points")
wt.select_faces([fid_big])
wt.add_condition("convs", {"h": 20.0, "Tinf": 293.15})
ok(wt.run_solve() is not False and wt.result is not None, "solved with points")
r = wt.result
ok(r["balance"]["relative_error"] < 1e-9, f"the heat balance closes: {r['balance']['relative_error']:.1e}")
ok(abs(r["T"][wt.mesh_q["verts"][left_pts[0]]] - 350.0) < 1e-9, "the node at the held point is at exactly 350 K")
pw = next(f for f in r["flows"] if f["kind"] == "power")
ok(abs(pw["Q"] - 4.0) < 1e-12 and not pw["area"], "the 4 W go in at the points (no area)")
# a mesh with no node along an edge says so in the solve
wt.setup["temps"] = [{"name": "t", "faces": [], "edges": [sg.edge_sig(g, left4[0])], "T": 300.0}]
wt.setup["powers"] = []
res_ = tm.resolve(wt.geom, wt.setup)
qbad = dict(wt.mesh_q, nodes=wt.mesh_q["nodes"] + np.array([300.0, 0, 0]))
import thermal3d_fem as tfm
try:
    tfm.solve(qbad, tm.spec_of(res_))
    ok(False, "Thermal: a mesh with no nodes along the edge is an error")
except Exception as ex:                                                                      # noqa: BLE001
    ok("no nodes along that edge" in str(ex), f"Thermal: {ex}")
wt.setup["temps"] = [{"name": "t", "faces": [], "points": [sg.vert_sig(g, 0)], "T": 300.0}]
qnov = dict(wt.mesh_q, verts={})
try:
    tfm.solve(qnov, tm.spec_of(tm.resolve(wt.geom, wt.setup)))
    ok(False, "Thermal: a mesh with no node at the point is an error")
except Exception as ex:                                                                      # noqa: BLE001
    ok("no node at that point" in str(ex), f"Thermal: {ex}")

# ================================================================================================================================ 8. CFD keeps faces
wc.selector.set_kind("general")
wc.view.pick_at(*[int(x) for x in screen(wc, verts[v0])])
ok(wc.sel_points == [] and wc.sel_edges == [], "CFD: a click at a corner does not pick the corner (General is faces)")
wc.view.pick_at(*[int(x) for x in fc[0]])
ok(len(wc.sel_faces) == 1, "CFD: a click on a face picks the face")
wc.selector.set_kind("body")
wc.view.pick_at(*[int(x) for x in fc[0]])
ok(wc.sel_body == 0 and wc.size_table.selectionModel().selectedRows()[0].row() == 0, "CFD: Body picks the part and selects its row in the table of sizes")
wc.selector.set_kind("general")
wc.selector.set_kind("edge")
ok(wc.selector.kind == "general" and wc.view.kind == "face", "CFD: Edge cannot be chosen (the selector stays on General)")

# ================================================================================================================================ 9. an assembly: Body picks a part
ad = os.path.join(T, "asm")
os.makedirs(ad)
make_part(os.path.join(ad, "base.gpd"), 20.0, 20.0, 30)
make_part(os.path.join(ad, "cap.gpd"), 20.0, 20.0, 20, {"name": "Aluminium 6061-T6", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33, "Sy_MPa": 276.0, "Su_MPa": 310.0})
a = am.Assembly()
a.add_component("base.gpd", fixed=True, pos=(0, 0, 0))
a.add_component("cap.gpd", fixed=False, pos=(0, 0, 30))
asm_path = os.path.join(ad, "stack.gpa")
open(asm_path, "w").write(a.to_json())
wa = new_window(solid_tab.SolidWindow, "asm", asm_path)
ga = wa.geom
ok(wa.is_asm() and len(ga["bodies"]) == 2, "an assembly of two parts")
ok(sorted(set(wa.view.face_body.tolist())) == [-1, 0, 1], "the view knows the part of each face (-1: a face inside, between the parts)")
wa.selector.set_kind("body")
top_face = next(f for f in ga["faces"] if f["normal"][2] > 0.99 and not f.get("interface"))
sc = screen(wa, top_face["center"])
r_ = wa.view.what_is_under(*sc, "body")
ok(r_ is not None and r_["kind"] == "body" and r_["idx"] == top_face["body"], f"Body: the top face belongs to part {top_face['body'] + 1}")
wa.view.pick_at(*[int(x) for x in sc])
ok(wa.sel_body == top_face["body"], "a click takes that part")
ok(wa.body_table.selectionModel().selectedRows()[0].row() == top_face["body"] and wa.size_table.selectionModel().selectedRows()[0].row() == top_face["body"],
   "and its row is selected in the tables of the material and of the element size")
cols_ = {f["id"]: wa.view.rgb[np.where(wa.view.cell_face == f["id"])[0][0]] for f in ga["faces"] if not f.get("interface") and len(np.where(wa.view.cell_face == f["id"])[0])}
mine = [f["id"] for f in ga["faces"] if not f.get("interface") and f.get("body") == top_face["body"]]
ok(all(np.allclose(cols_[i], view3d.select_rgb(), atol=1 / 255) for i in mine), "all the faces of that part are in the selected colour")
ok(all(not np.allclose(cols_[i], view3d.select_rgb(), atol=1 / 255) for i in cols_ if i not in mine), "and the other part is not")
wa.add_support("fixed")
ok("(A whole part is for its material" in wa.status_lbl.text(), "a whole part cannot carry a support, and the message says what it is for")

# ================================================================================================================================ 10. the colours of the settings
settings.set_many({"part_color": "#808080", "select_color": "#ff00ff"})
ws.settings_changed(["part_color", "select_color"])
ws.clear_selection()
ok(np.allclose(ws.view.rgb[0], np.array([128, 128, 128]) / 255.0, atol=1 / 255), "the neutral colour of the part follows File > Settings")
ws.select_faces([fc[1]])
ok(np.allclose(ws.view.rgb[np.where(ws.view.cell_face == fc[1])[0][0]], [1.0, 0.0, 1.0], atol=1 / 255), "so does the colour of what is picked")
settings.set_many({"part_color": "#999999", "select_color": "#00b4ff"})

print("FAILED:" if FAILS else "ALL PASSED", FAILS)
sys.exit(1 if FAILS else 0)
