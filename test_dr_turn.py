"""Drawings (dev add-on drawings): DRW-1, turning a view on the sheet 90 degrees to the left or to the right (like a sheet of paper: again and again, the orientation does not change, the
dimensions, balloons and leaders of the view turn with it, only that view turns, it is kept in the file) and DRW-2, projected views that are views of their own once they are put down
(own orientation, scale, style, position and turn; nothing that happens to the other view happens to them; a model that changed draws them all again; a drawing from before opens with
them free).   python test_dr_turn.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import copy
import json
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pm_app
pm_app.apply_theme(app)
import numpy as np
import dr_annot as A
import dr_model as M
import dr_proj as P
import dr_tab as T
import wb_example as ex

T.DrawingTab.ASK_SHEET = False
FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def nearp(p, q, tol=1e-6):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def settle():
    for _ in range(3):
        app.processEvents()


def rot_about(p, c, step):
    """The point p of the sheet, turned a quarter (+1 left = counter-clockwise, -1 right) about c."""
    dx, dy = p[0] - c[0], p[1] - c[1]
    rx, ry = (-dy, dx) if step > 0 else (dy, -dx)
    return (c[0] + rx, c[1] + ry)


def canon_segs(segs, nd=5):
    """The lines as a sorted list of lists of rounded points; a line read from either end is the same line."""
    out = []
    for sg in segs:
        pts = tuple((round(float(p[0]), nd) + 0.0, round(float(p[1]), nd) + 0.0) for p in sg)
        out.append(min(pts, pts[::-1]))
    return sorted(out)


def same_segs(a, b, tol=1e-6):
    return canon_segs(a) == canon_segs(b)


def turn_heads(heads, c, step):
    """The arrow heads (tip, direction, size) of a drawn dimension, turned about c."""
    return [(rot_about(h[0], c, step), rot_about(h[1], (0.0, 0.0), step), h[2]) for h in heads]


def same_heads(a, b, nd=5):
    canon = lambda hs: sorted((round(h[0][0], nd) + 0.0, round(h[0][1], nd) + 0.0, round(h[1][0], nd) + 0.0, round(h[1][1], nd) + 0.0, round(h[2], nd)) for h in hs)
    return canon(a) == canon(b)


def circle(c, r):
    pts = [(c[0] + r * math.cos(t), c[1] + r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 49)]
    return {"t": "circle", "c": c, "r": r, "pts": pts, "n": 0}


def line(a, c):
    return {"t": "line", "a": a, "b": c, "pts": [a, c], "n": 0}


# ----------------------------------------------------------------------------------------------------------------------------------- a dimension turns with its view (dr_annot)
C1 = A.ref_of(circle((30.0, 5.0), 3.0))
ARC = {"k": "arc", "c": (0.0, 0.0), "r": 10.0, "a0": 0.0, "a1": math.pi / 2}
LA, LB = A.ref_of(line((0, 0), (100, 0))), A.ref_of(line((0, 10), (100, 10)))
LC = A.ref_of(line((0, 0), (30, 30)))
PA, PB = {"k": "pt", "p": (0.0, 0.0)}, {"k": "pt", "p": (100.0, 10.0)}
BB = (0.0, 0.0, 100.0, 10.0)


def dims_to_turn():
    out = []
    for mode in ("h", "v", "a"):
        for side in (1, -1):
            d = A.new_dim([PA, PB], BB, "linear", mode)
            d["side"], d["dist"], d["t"] = side, 9.0, 7.0
            out.append((f"two points, {mode}, side {side}", d))
    d = A.new_dim([LA], BB)
    d["side"], d["dist"], d["t"] = -1, 12.0, -5.0
    out.append(("one line", d))
    d = A.new_dim([LA, LB], BB)
    d["side"], d["dist"] = 1, 20.0
    out.append(("two parallel lines", d))
    d = A.new_dim([PB, LA], BB)
    d["side"], d["dist"] = 1, 6.0
    out.append(("a point and a line", d))
    d = A.new_dim([C1], BB)
    d["lab"] = [20.0, 5.0]
    out.append(("a diameter", d))
    d = A.new_dim([ARC], BB)
    d["lab"] = [-4.0, 15.0]
    out.append(("a radius", d))
    d = A.new_dim([LA, LC], BB)
    d["s1"], d["s2"], d["rho"] = 1, 1, 18.0
    out.append(("an angle", d))
    return out


for name, d0 in dims_to_turn():
    for step in (1, -1):
        s, o = 2.0, (13.0, 21.0)
        before = A.shape(d0, s, o)
        d1 = copy.deepcopy(d0)
        A.turn_annot(d1, step)
        after = A.shape(d1, s, o)
        # the turn of the view is a turn of its picture: the drawn dimension is the old drawn dimension turned about the point where the view's origin stands
        c = o                                                                  # (the origin of the view is where the model's origin is on the sheet: the turn is about it here)
        want = [[rot_about(p, c, step) for p in seg] for seg in before["segs"]]
        want_h = turn_heads(before["heads"], c, step)
        # (the view's frame is turned about its own origin, and the sheet position is scale * frame + origin: a turn of the frame is a turn about the origin)
        ok(same_segs(after["segs"], want) and same_heads(after["heads"], want_h) and sorted(after["kinds"]) == sorted(before["kinds"]),
           f"{name}, turned {'left' if step > 0 else 'right'}: the lines and the arrows are the old ones turned a quarter")
        ok(near(A.value(d1), A.value(d0)), f"{name}, turned {'left' if step > 0 else 'right'}: it says the same number")
        a0 = A.shape(d0, s, o)["at"]
        a1 = after["at"]
        mid = np.mean([p for seg in after["segs"] for p in seg], axis=0)
        ok(math.hypot(a1[0] - mid[0], a1[1] - mid[1]) < 60.0, f"{name}, turned {'left' if step > 0 else 'right'}: the number stays by its lines")
    d2 = copy.deepcopy(d0)
    A.turn_annot(d2, 1)
    A.turn_annot(d2, -1)
    ok(d2["refs"] == d0["refs"] or all(A.same_ref(x, y) for x, y in zip(d2["refs"], d0["refs"])), f"{name}: left then right gives back what it held on to")
    for k in ("mode", "side", "t", "lab", "s1", "s2", "rho", "dist"):
        if k in d0:
            ok(d2.get(k) == d0[k] or (isinstance(d0[k], list) and all(near(x, y) for x, y in zip(d2[k], d0[k]))), f"{name}: left then right gives back '{k}'")
    d4 = copy.deepcopy(d0)
    for _ in range(4):
        A.turn_annot(d4, 1)
    ok(all(A.same_ref(x, y, 1e-9) for x, y in zip(d4["refs"], d0["refs"])) and all(near(x, y) for x, y in zip(d4["bb"], d0["bb"])), f"{name}: four turns to the left give the original")

# ----------------------------------------------------------------------------------------------------------------------------------- a view turns (dr_model)
bar, _sid = ex.part_doc(100, 20, 10)
long_bar, _s2 = ex.part_doc(150, 20, 10)
d = M.Drawing()
m1 = d.add_model("Bar", "part", bar)
v1 = d.add_view(m1, "Front", (100.0, 110.0))
vo = d.add_view(m1, "Top", (100.0, 40.0))                             # (another view: nothing that happens to the first one happens to it)
pr = d.projection(v1)
pt = lambda x, y: {"k": "pt", "p": (x, y)}
W0, H0 = pr.bbox()[2] - pr.bbox()[0], pr.bbox()[3] - pr.bbox()[1]
corners = [A.pick(pr, (pr.bbox()[0] + 0.1, pr.bbox()[1] + 0.1), 1.0), A.pick(pr, (pr.bbox()[2] - 0.1, pr.bbox()[1] + 0.1), 1.0), A.pick(pr, (pr.bbox()[2] - 0.1, pr.bbox()[3] - 0.1), 1.0)]
dh = d.add_dim(v1["id"], [corners[0], corners[1]], "linear", "h")
dv = d.add_dim(v1["id"], [corners[1], corners[2]], "linear", "v")
d.place_annot(dh["id"], (v1["origin"][0] + 50.0, v1["origin"][1] - 14.0))
d.place_annot(dv["id"], (v1["origin"][0] + 120.0, v1["origin"][1] + 5.0))
ln = A.pick(pr, (50.0, pr.bbox()[1] + 0.2), 1.0)
bal = d.add_balloon(v1["id"], "1", ln["a"] if ln["k"] == "line" else (50.0, 0.0), (v1["origin"][0] + 10.0, v1["origin"][1] + 40.0), snap=False)
note = d.add_note("Fillet all round", (v1["origin"][0] + 90.0, v1["origin"][1] + 60.0), leader={"kind": "straight", "view": v1["id"], "p": (30.0, 4.0)})
note_o = d.add_note("Plan", (20.0, 20.0), leader={"kind": "straight", "view": vo["id"], "p": (10.0, 4.0)})
ok(dh["lost"] is False and near(A.value(dh), 100.0) and near(A.value(dv), 10.0), f"(a horizontal dimension {A.value(dh):g} and a vertical one {A.value(dv):g} on the Front view of the bar)")
ok(v1["turn"] == 0 and vo["turn"] == 0 and v1["orient"] == "Front", "a view starts upright: turn 0")


def sheet_state(vid):
    v = d.view(vid)
    s, o = v["scale"], v["origin"]
    out = {"dims": {a["id"]: A.shape(a, s, o) for a in d.dims if a["view"] == vid},
           "tip": A._T(next(b for b in d.balloons if b["view"] == vid)["tip"], s, o), "bpos": list(next(b for b in d.balloons if b["view"] == vid)["pos"]),
           "leader": A._T(next(n for n in d.notes if (n.get("leader") or {}).get("view") == vid)["leader"]["p"], s, o)}
    out["box"] = d.bbox(v)
    return out


S0 = sheet_state(v1["id"])
centre0 = ((S0["box"][0] + S0["box"][2]) / 2, (S0["box"][1] + S0["box"][3]) / 2)
other0 = (list(vo["origin"]), vo["turn"], list(vo["up"]), d.bbox(vo))
note_o_tip0 = A._T(note_o["leader"]["p"], vo["scale"], vo["origin"])
orig = (list(v1["origin"]), list(v1["eye"]), list(v1["up"]), copy.deepcopy(dh), copy.deepcopy(dv), copy.deepcopy(bal), copy.deepcopy(note))
snap0 = d.snapshot()

d.turn_view(v1["id"], 1)
ok(v1["turn"] == 1 and v1["orient"] == "Front", "Turn left: one quarter, and the orientation is still Front")
S1 = sheet_state(v1["id"])
b = S1["box"]
ok(near(b[2] - b[0], H0, 1e-6) and near(b[3] - b[1], W0, 1e-6), f"a turn of 90 degrees: the lines that were {W0:g} wide and {H0:g} high are {H0:g} wide and {W0:g} high")
ok(near((b[0] + b[2]) / 2, centre0[0], 1e-6) and near((b[1] + b[3]) / 2, centre0[1], 1e-6), "the view stays where its middle is")
for aid, shp in S1["dims"].items():
    old = S0["dims"][aid]
    want = [[rot_about(p, centre0, 1) for p in seg] for seg in old["segs"]]
    ok(same_segs(shp["segs"], want, 1e-6), f"the dimension {aid} is drawn where the old one was turned about the middle of the view (the same lines, a quarter round)")
ok(all(not a["lost"] for a in d.dims) and near(A.value(dh), 100.0) and near(A.value(dv), 10.0) and dh["mode"] == "v" and dv["mode"] == "h",
   "the dimensions measure what they did (100 and 10); the horizontal one is vertical now, the vertical one horizontal")
ok(nearp(S1["tip"], rot_about(S0["tip"], centre0, 1), 1e-6), "the balloon points at the same place of the part (turned with it)")
ok(nearp(S1["bpos"], rot_about(S0["bpos"], centre0, 1), 1e-6), "and its circle went round with it")
ok(nearp(S1["leader"], rot_about(S0["leader"], centre0, 1), 1e-6), "a note's leader into the view points at the same place of the part")
ok(list(vo["origin"]) == other0[0] and vo["turn"] == other0[1] and list(vo["up"]) == other0[2] and d.bbox(vo) == other0[3] and nearp(A._T(note_o["leader"]["p"], vo["scale"], vo["origin"]), note_o_tip0),
   "only that view turned: the other view, and what is drawn on it, are as they were")
ok(np.allclose(v1["eye"], orig[1]), "the direction it looks from is the same: only the up of the sheet changed")

d.turn_view(v1["id"], 1)
ok(v1["turn"] == 2 and v1["orient"] == "Front", "again: it can be repeated (180 degrees)")
b = d.bbox(v1)
ok(near(b[2] - b[0], W0) and near(b[3] - b[1], H0) and near((b[0] + b[2]) / 2, centre0[0]), "(the size is as it was, on its head)")
d.turn_view(v1["id"], 1)
d.turn_view(v1["id"], 1)
ok(v1["turn"] == 0, "four presses to the left: turn 0 again")
S4 = sheet_state(v1["id"])
ok(nearp(v1["origin"], orig[0], 1e-6) and np.allclose(v1["up"], orig[2], atol=1e-9) and np.allclose(v1["eye"], orig[1], atol=1e-9), "and the view is the original one: the same origin, direction and up")
ok(all(near(S4["dims"][k]["segs"][i][j][c], S0["dims"][k]["segs"][i][j][c], 1e-6) for k in S0["dims"] for i in range(len(S0["dims"][k]["segs"])) for j in range(len(S0["dims"][k]["segs"][i])) for c in (0, 1)),
   "every dimension is drawn exactly as before the four turns")
ok(dh["mode"] == orig[3]["mode"] and dh["side"] == orig[3]["side"] and near(dh["t"], orig[3]["t"]) and dv["mode"] == orig[4]["mode"] and dv["side"] == orig[4]["side"] and near(dv["t"], orig[4]["t"]),
   "with the mode, the side and the place of the number they had")
ok(nearp(S4["tip"], S0["tip"], 1e-6) and nearp(S4["bpos"], S0["bpos"], 1e-6) and nearp(S4["leader"], S0["leader"], 1e-6), "the balloon and the leader are where they were")

d.turn_view(v1["id"], 1)
d.turn_view(v1["id"], -1)
S5 = sheet_state(v1["id"])
ok(v1["turn"] == 0 and nearp(S5["tip"], S0["tip"], 1e-6) and np.allclose(v1["up"], orig[2], atol=1e-9) and nearp(v1["origin"], orig[0], 1e-6), "left and right cancel")
d.turn_view(v1["id"], -1)
S6 = sheet_state(v1["id"])
b6 = S6["box"]
ok(v1["turn"] == 3 and near(b6[2] - b6[0], H0) and nearp(S6["tip"], rot_about(S0["tip"], centre0, -1), 1e-6) and nearp(S6["bpos"], rot_about(S0["bpos"], centre0, -1), 1e-6),
   "Turn right: three quarters to the left; the balloon went the other way round")
for aid, shp in S6["dims"].items():
    want = [[rot_about(p, centre0, -1) for p in seg] for seg in S0["dims"][aid]["segs"]]
    ok(same_segs(shp["segs"], want, 1e-6), f"the dimension {aid}, turned right, is the old one a quarter round the other way")
d.turn_view(v1["id"], 1)
ok(v1["turn"] == 0, "(back upright)")
d.turn_view(v1["id"], 2)
ok(v1["turn"] == 2, "two quarters at once is a half turn")
d.turn_view(v1["id"], 2)
d.turn_view(v1["id"], 0)
ok(v1["turn"] == 0, "no quarters: nothing")

# the file keeps the turn
d.turn_view(v1["id"], 1)
text = d.to_json()
j = json.loads(text)
ok(next(v for v in j["views"] if v["id"] == v1["id"])["turn"] == 1 and next(v for v in j["views"] if v["id"] == vo["id"])["turn"] == 0, "the turn of each view is in the file")
d2 = M.Drawing.from_json(text)
w1 = d2.view(v1["id"])
ok(w1["turn"] == 1 and np.allclose(w1["up"], v1["up"]) and nearp(w1["origin"], v1["origin"]) and d2.bbox(w1) == d.bbox(v1), "a drawing that is opened shows the view turned the same way")
ok(near(A.value(d2.dims[0]), 100.0) and not any(a["lost"] for a in d2.dims) and d2.dims[0]["mode"] == "v", "with its dimensions in it")
# undo: the turn is part of what a snapshot keeps
snap1 = d.snapshot()
d.turn_view(v1["id"], 1)
d.restore(snap1)
ok(d.view(v1["id"])["turn"] == 1, "a snapshot keeps the turn (undo)")
d.restore(snap0)
ok(d.view(v1["id"])["turn"] == 0 and np.allclose(d.view(v1["id"])["up"], orig[2]), "and gives back the view as it was before")
v1 = d.view(v1["id"])

# a new orientation starts upright
d.turn_view(v1["id"], 1)
d.set_orient(v1["id"], "Right")
ok(v1["orient"] == "Right" and v1["turn"] == 0 and np.allclose(v1["up"], (0, 0, 1)), "choosing an orientation puts the view upright in it")
d.set_orient(v1["id"], "Front")
d.restore(snap0)                                                       # (a view that looks another way has lost its dimensions: back to the drawing with them)
v1 = d.view(v1["id"])

# the model changes: the turned view is drawn again, still turned, its dimensions found again
d.turn_view(v1["id"], 1)
d.refresh_model(m1, long_bar, name="Long bar")
b = d.bbox(v1)
ok(v1["turn"] == 1 and near(b[3] - b[1], 150.0, 1e-4) and near(b[2] - b[0], 10.0, 1e-4), "the bar got longer: the turned view is drawn again, still on its side (10 wide, 150 high)")
ok(all(not a["lost"] for a in d.dims if a["view"] == v1["id"]) and any(near(A.value(a), 150.0, 1e-4) for a in d.dims if a["view"] == v1["id"]), "and its horizontal dimension reads 150 now")
d.refresh_model(m1, bar, name="Bar")
d.turn_view(v1["id"], -1)

# a view that is still being placed cannot be turned
g = d.add_projected(v1["id"], "right", (200.0, 100.0), linked=True)
try:
    d.turn_view(g["id"], 1)
    ok(False, "a view on the pointer cannot be turned")
except M.DrawingError:
    ok(True, "a view that is still on the pointer is not turned (put it down first)")
d.remove_view(g["id"])

# ----------------------------------------------------------------------------------------------------------------------------------- a projected view is a view of its own (DRW-2)
d = M.Drawing()
m1 = d.add_model("Bar", "part", bar)
f = d.add_view(m1, "Front", (100.0, 110.0))
r = d.add_projected(f["id"], "right", (180.0, 110.0))
t = d.add_projected(f["id"], "up", (100.0, 150.0))
b_ = d.add_projected(f["id"], "down", (100.0, 70.0))
l_ = d.add_projected(f["id"], "left", (20.0, 110.0))
ok(all(v["kind"] == "model" and v["parent"] is None and v["side"] is None for v in (r, t, b_, l_)), "a view projected from another is a model view of its own: no parent, no side")
ok([v["orient"] for v in (r, t, b_, l_)] == ["Right", "Top", "Bottom", "Left"] and all(v["turn"] == 0 for v in (r, t, b_, l_)), "its orientation is the one it looks along (to the right of the Front view: the Right view)")
ok(not d.children(f["id"]) and not d.descendants(f["id"]), "the Front view has no views under it")
ok(near(r["origin"][1], f["origin"][1]) and near(t["origin"][0], f["origin"][0]), "(it was put in line with the other one, as it was asked)")
iso = d.add_view(m1, "Isometric", (60.0, 160.0))
ri = d.add_projected(iso["id"], "right", (150.0, 160.0))
ok(ri["orient"] == M.CUSTOM and ri["kind"] == "model", "a view projected from an isometric one looks along none of the nine: its orientation is Custom")
d.turn_view(ri["id"], 1)
ok(ri["orient"] == M.CUSTOM and ri["turn"] == 1, "it can be turned like any other")
d.set_orient(ri["id"], "Front")
ok(ri["orient"] == "Front" and ri["turn"] == 0, "and given a standard orientation")
# free to move, to scale, to style, to change orientation, to turn
before = {v["id"]: (list(v["origin"]), v["scale"], v["style"], v["orient"], v["turn"], list(v["eye"]), list(v["up"])) for v in (f, t, b_, l_)}
d.move_view(r["id"], 40.0, 30.0)
ok(nearp(r["origin"], (40.0, 30.0)), "a projected view moves anywhere: both ways")
d.shift_view(r["id"], 10.0, 15.0)
ok(nearp(r["origin"], (50.0, 45.0)), "also by a distance")
d.set_scale(r["id"], "1:2")
d.set_style(r["id"], "hlr")
d.set_orient(r["id"], "Isometric")
d.turn_view(r["id"], 1)
ok(r["scale"] == 0.5 and r["style"] == "hlr" and r["orient"] == "Isometric" and r["turn"] == 1, "its own scale, style, orientation and turn")
ok(all((list(v["origin"]), v["scale"], v["style"], v["orient"], v["turn"], list(v["eye"]), list(v["up"])) == before[v["id"]] for v in (f, t, b_, l_)),
   "none of that changed the view it was projected from, or the other views")
o_r = (list(r["origin"]), r["scale"], r["style"], r["orient"], r["turn"], list(r["eye"]), list(r["up"]))
d.move_view(f["id"], 20.0, 25.0)
d.set_scale(f["id"], "1:4")
d.set_style(f["id"], "wireframe")
d.set_orient(f["id"], "Back")
d.turn_view(f["id"], -1)
ok((list(r["origin"]), r["scale"], r["style"], r["orient"], r["turn"], list(r["eye"]), list(r["up"])) == o_r and t["orient"] == "Top" and near(t["scale"], before[t["id"]][1]),
   "and moving, scaling, restyling, re-orienting or turning the first view changes none of them (they are not linked)")
d.remove_view(f["id"])
ok(len(d.views) == 6 and {v["id"] for v in d.views} == {r["id"], t["id"], b_["id"], l_["id"], iso["id"], ri["id"]}, "removing the view they were projected from removes only that view")

# first angle or third angle changes how a new view is projected, not the views that are there
d = M.Drawing()
m1 = d.add_model("Bar", "part", bar)
f = d.add_view(m1, "Front", (100.0, 110.0))
r = d.add_projected(f["id"], "right", (180.0, 110.0))
d.set_sheet(first_angle=True)
ok(r["orient"] == "Right" and np.allclose(r["eye"], (1, 0, 0)), "the sheet is first-angle now: the view that was put down on the right still looks from the right")
r2 = d.add_projected(f["id"], "right", (250.0, 110.0))
ok(r2["orient"] == "Left", "a new view on the right of the Front view looks from the left (first angle)")
d.set_sheet(first_angle=False)

# a model that changes is drawn again in every view
long_ids = d.refresh_model(m1, long_bar, name="Long bar")
ok(set(long_ids) == {f["id"], r["id"], r2["id"]}, "every view of the model is drawn again when it changes, the ones that were projected as well")
ok(near(d.bbox(f)[2] - d.bbox(f)[0], 150.0) and near(d.bbox(r)[2] - d.bbox(r)[0], 20.0), "(the Front view is 150 wide; the Right view is as wide as the bar is deep)")
d.refresh_model(m1, bar, name="Bar")

# a drawing from before: a projected view opens free, where it was
old = d.to_json()
jj = json.loads(old)
for v in jj["views"]:
    if v["id"] == r["id"]:
        v["kind"], v["parent"], v["side"] = "projected", f["id"], "right"
        v["orient"] = "Front"                                                # (what the old files kept: the parent's name)
        v.pop("turn", None)                                                # (and no turn)
d_old = M.Drawing.from_json(json.dumps(jj))
ro = d_old.view(r["id"])
ok(ro["kind"] == "model" and ro["parent"] is None and ro["side"] is None and ro["turn"] == 0, "a drawing from before opens with the projected view free: a model view, no parent, not turned")
ok(nearp(ro["origin"], r["origin"]) and np.allclose(ro["eye"], r["eye"]) and np.allclose(ro["up"], r["up"]) and d_old.bbox(ro) == d.bbox(r), "and it is where it was and looks as it did")
ok(ro["orient"] == "Right", "its orientation is the one it really looks along (Right), not its parent's name")
d_old.move_view(ro["id"], 10.0, 10.0)
ok(nearp(ro["origin"], (10.0, 10.0)), "it can be moved anywhere")
back = json.loads(d_old.to_json())
ok(all(v["kind"] == "model" for v in back["views"]), "and it is saved as a view of its own")
# a projected view with a projected view of its own (two levels in an old file)
jj = json.loads(old)
tv = d.add_projected(r["id"], "up", (180.0, 150.0))
jj = json.loads(d.to_json())
for v in jj["views"]:
    if v["id"] == r["id"]:
        v["kind"], v["parent"], v["side"] = "projected", f["id"], "right"
    if v["id"] == tv["id"]:
        v["kind"], v["parent"], v["side"] = "projected", r["id"], "up"
d_old2 = M.Drawing.from_json(json.dumps(jj))
ok(all(v["kind"] == "model" for v in d_old2.views) and not any(v["parent"] for v in d_old2.views), "a view projected from a projected view opens free too")

# ----------------------------------------------------------------------------------------------------------------------------------- the window
tab = T.DrawingTab()
tab.resize(1250, 800)
tab.show()
settle()
cv = tab.canvas
tab.sync_models([{"src": "n1", "name": "Bar", "kind": "part", "data": bar}])
tab.model_panel.pick_orientation("Front")
at = lambda x, y: cv.to_screen(x, y).toPoint()
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
QTest.mouseMove(cv, at(100, 120))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 120))
settle()
tab.finish_command()
v = tab.d.views[0]
ok(all(k in tab.act for k in ("turn_left", "turn_right")), "the View Layout page of the ribbon has Turn Left 90 and Turn Right 90")
ok(tab.act["turn_left"].text().replace("\n", " ") == "Turn Left 90°" and tab.act["turn_right"].text().replace("\n", " ") == "Turn Right 90°", "with their names on the buttons")
cv.set_selected(None)
settle()
ok(not tab.act["turn_left"].isEnabled() and not tab.act["turn_right"].isEnabled(), "with no view selected they are off")
cv.set_selected(v["id"])
settle()
ok(tab.act["turn_left"].isEnabled() and tab.act["turn_right"].isEnabled(), "with a view selected they are on")
box0 = cv.r.view_box(v)
n_undo = len(tab.undo_stack)
tab.act["turn_left"].click()
settle()
box1 = cv.r.view_box(v)
ok(v["turn"] == 1 and len(tab.undo_stack) == n_undo + 1 and near(box1[2] - box1[0], box0[3] - box0[1], 1e-6) and near(box1[3] - box1[1], box0[2] - box0[0], 1e-6),
   "Turn Left 90: the selected view turns a quarter (one undo step), its width and height swapped on the screen")
ok(tab.outline.tree.findItems("Drawing View1   Front, ", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchStartsWith)[0].text(0).endswith("turned 90 degrees left"), "the Outline says it is turned")
ok(cv.sel == v["id"] and "turned 90 degrees left" in tab.outline.v_turn.text(), "the Details of the view say it too")
tab.act["turn_left"].click()
tab.act["turn_left"].click()
tab.act["turn_left"].click()
settle()
ok(v["turn"] == 0 and tab.outline.v_turn.text() == "", "four presses to the left: upright again, and the Details say nothing about a turn")
tab.act["turn_right"].click()
settle()
ok(v["turn"] == 3 and "turned 90 degrees right" in tab.outline.v_turn.text(), "Turn Right 90")
tab.do_undo()
settle()
v = tab.d.view(v["id"])                                              # (an undo brings the views back as new records)
ok(v["turn"] == 0, "undo turns it back")
tab.outline.v_turn_l.click()
settle()
ok(tab.d.view(v["id"])["turn"] == 1, "the Details of a view have the two buttons as well")
tab.set_view_orient(v["id"], "Front")
ok(tab.d.view(v["id"])["turn"] == 0 and tab.d.view(v["id"])["orient"] == "Front", "picking the orientation the view has already puts it upright again")
tab.set_view_orient(v["id"], "Custom")
ok(tab.d.view(v["id"])["orient"] == "Front", "(the word Custom is not an orientation to pick)")
v = tab.d.view(v["id"])

# placing a projected view with the command: put down, it is free
tab.open_command("projected")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 120))
settle()
QTest.mouseMove(cv, at(180, 123))
settle()
ghost = tab.d.view(cv.float_id)
ok(ghost["kind"] == "projected", "(while it follows the pointer it is still tied to its parent)")
n_tab = len(tab.undo_stack)
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(180, 123))
settle()
placed = [x for x in tab.d.views if x["id"] != v["id"]]
ok(len(placed) == 1 and placed[0]["kind"] == "model" and placed[0]["orient"] == "Right" and len(tab.undo_stack) == n_tab + 1, "a click puts it down as a view of its own (the Right view), one undo step")
QTest.keyClick(cv, Qt.Key.Key_Escape)
settle()
tab.finish_command()
cv.set_selected(placed[0]["id"])
settle()
ok(tab.act["turn_left"].isEnabled(), "and it can be turned")
tab.act["turn_left"].click()
settle()
ok(tab.d.view(placed[0]["id"])["turn"] == 1 and tab.d.view(v["id"])["turn"] == 0, "the new view turned, the first one did not")
vtext = tab.outline.tree.findItems(placed[0]["name"], Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchStartsWith)
ok(vtext and vtext[0].parent().text(0) == "Views", "in the Outline both views are in the Views list: nothing is nested under a view")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f_ in FAILS:
        print("  -", f_)
    sys.exit(1)
print("ALL OK")
