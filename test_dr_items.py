"""Drawings (dev add-on drawings): what is drawn on the sheet itself (dr_items.py, and how the drawing document keeps it) - notes (text of any size, several lines, an optional straight or bent
leader with an arrow), balloons (a number in a circle, a leader to a view, an arrow on an edge, a dot on a face), plain drawing items (line, rectangle, circle, arc): the shapes that are
painted, picking by distance, the handles that are dragged, leaders that follow their view, the file and undo.   python test_dr_items.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
import dr_annot as A
import dr_items as IT
import dr_model as M
import wb_example as ex

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, c, tol=1e-6):
    return abs(a - c) <= tol


def nearp(p, q, tol=1e-6):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


# ----------------------------------------------------------------------------------------------------------------------------------- notes
m14 = IT.default_metrics(14.0)
ok(near(m14.em, 14.0 * 25.4 / 72.0) and near(m14.cap, 0.72 * m14.em) and m14.pitch > m14.cap, "text of 14 points: an em of 4.94 mm, a capital about the 3.5 mm of the numbers of a dimension")
ok(near(IT.default_metrics(28.0).width("abc"), 2.0 * m14.width("abc")), "twice the size: twice the width")
n = IT.new_note("Break all sharp edges", (20.0, 80.0))
sn = IT.note_shape(n, None)
w = m14.width("Break all sharp edges")
ok(nearp(sn["box"][:2], (20.0, 80.0 - m14.cap)) and near(sn["box"][2], 20.0 + w) and near(sn["box"][3], 80.0), f"a note's box: top-left corner at the position, as wide as its text ({sn['box']})")
ok(sn["lines"] == [("Break all sharp edges", (20.0, 80.0 - m14.cap))] and not sn["segs"] and not sn["heads"], "one line of text, its baseline a capital's height under the top; no leader")
n2 = IT.new_note("one\ntwo\nthree", (0.0, 0.0), 10.0)
s2 = IT.note_shape(n2, None)
m10 = IT.default_metrics(10.0)
ok(len(s2["lines"]) == 3 and near(s2["lines"][1][1][1] - s2["lines"][0][1][1], -m10.pitch) and near(s2["box"][1], -(m10.cap + 2 * m10.pitch)), "three lines: one pitch apart, the box holds all three")
ok(near(s2["box"][2], m10.width("three")), "as wide as the widest line")
ok(IT.clean_size("abc") == IT.NOTE_SIZE and IT.clean_size(1) == 2.0 and IT.clean_size(900) == 200.0 and IT.clean_size("18") == 18.0, "the size is kept between 2 and 200 points; a word falls back to the default")

# leader: straight
nl = IT.new_note("Hole", (50.0, 50.0), 14.0, {"kind": "straight", "view": None, "p": (10.0, 30.0)})
sl = IT.note_shape(nl, (10.0, 30.0))
bx = sl["box"]
cy = (bx[1] + bx[3]) / 2.0
ok(len(sl["segs"]) == 1 and len(sl["segs"][0]) == 2 and nearp(sl["segs"][0][0], (10.0, 30.0)), "a straight leader is one line, from its tip")
ok(nearp(sl["segs"][0][1], (bx[0] - IT.LEAD_GAP, cy)), "to the middle of the left side of the text (the tip is on the left), a little short of it")
(tip, away, size) = sl["heads"][0]
u = IT._unit((10.0, 30.0), sl["segs"][0][1])
ok(nearp(tip, (10.0, 30.0)) and nearp(away, u) and near(size, A.ARROW), "an arrow at the tip, along the leader")
sl2 = IT.note_shape(nl, (60.0, 20.0))
ok(near(sl2["segs"][0][1][0], (bx[0] + bx[2]) / 2.0) and sl2["segs"][0][1][1] < bx[1], "a tip under the text: the leader joins the middle of the bottom side")
sl3 = IT.note_shape(nl, (200.0, 52.0))
ok(near(sl3["segs"][0][1][0], bx[2] + IT.LEAD_GAP), "a tip far to the right: the right side")
# leader: bent
nb = IT.new_note("Hole", (50.0, 50.0), 14.0, {"kind": "bent", "view": None, "p": (10.0, 30.0)})
sb = IT.note_shape(nb, (10.0, 30.0))
pts = sb["segs"][0]
ok(len(pts) == 3 and nearp(pts[0], (10.0, 30.0)) and near(pts[1][1], cy) and near(pts[2][1], cy) and near(pts[2][0], bx[0] - IT.LEAD_GAP), "a bent leader: the tip, a knee at the height of the text, the text's side")
ok(near(pts[2][0] - pts[1][0], IT.LAND) and pts[1][0] < pts[2][0], f"the level part is {IT.LAND} mm long and runs towards the tip")
ok(abs(sb["heads"][0][1][0] - IT._unit(pts[0], pts[1])[0]) < 1e-9, "the arrow follows the sloping part")
sb2 = IT.note_shape(nb, (bx[0] - IT.LEAD_GAP - 2.0, 40.0))
ok(len(sb2["segs"][0]) == 3 and near(sb2["segs"][0][2][0] - sb2["segs"][0][1][0], 1.0), "a tip that is close: the level part is no longer than half the way")
sb3 = IT.note_shape(nb, (80.0, 40.0))
ok(near(sb3["segs"][0][2][0], bx[2] + IT.LEAD_GAP) and sb3["segs"][0][1][0] > sb3["segs"][0][2][0], "a tip on the right: the leader joins the right side, the level part runs right")
ok(IT.note_shape(nb, None)["segs"] == [] and IT.note_shape(nl, None)["heads"] == [], "no tip, no leader")

# picking by distance
dnote = lambda p: IT.distance(sl, p)
ok(near(dnote(((bx[0] + bx[2]) / 2.0, (bx[1] + bx[3]) / 2.0)), 0.0), "a click on the text is on the note")
ok(near(dnote((bx[2] + 3.0, (bx[1] + bx[3]) / 2.0)), 3.0), "3 mm from the text: 3 mm away")
ok(dnote((30.0, 40.0)) < 6.0 and near(dnote((10.0, 30.0)), 0.0), "the leader counts too, and its tip")

# ----------------------------------------------------------------------------------------------------------------------------------- balloons
bl = IT.new_balloon("3", "v1", (10.0, 10.0), (50.0, 40.0), True)
sbl = IT.balloon_shape(bl, (10.0, 10.0))
c, r = sbl["circle"]
ok(nearp(c, (50.0, 40.0)) and near(r, IT.BALLOON_R), "a balloon: a circle round its position, 4.5 mm for a small number")
ok(sbl["lines"][0][0] == "3" and near(sbl["lines"][0][1][0] + m14.width("3") / 2.0, 50.0) and near(sbl["lines"][0][1][1] + m14.cap / 2.0, 40.0), "the number is in the middle of the circle")
seg = sbl["segs"][0]
ok(near(math.hypot(seg[0][0] - 50.0, seg[0][1] - 40.0), r) and nearp(seg[1], (10.0, 10.0)), "the leader leaves the circle's edge, on the line to the tip")
ok(len(sbl["heads"]) == 1 and not sbl["dots"] and nearp(sbl["heads"][0][0], (10.0, 10.0)) and sbl["heads"][0][1][0] > 0, "an arrow at the tip (on an edge), pointing away from it, towards the balloon")
bl2 = IT.new_balloon("3", "v1", (10.0, 10.0), (50.0, 40.0), False)
sbl2 = IT.balloon_shape(bl2, (10.0, 10.0))
ok(not sbl2["heads"] and sbl2["dots"] == [((10.0, 10.0), IT.DOT_R)], "a tip that is on a face (not on an edge): a dot instead of an arrow")
big = IT.balloon_shape(IT.new_balloon("1234567", "v1", (0, 0), (50.0, 40.0)), (0.0, 0.0))
ok(big["circle"][1] > IT.BALLOON_R and near(big["circle"][1], m14.width("1234567") / 2.0 + IT.BALLOON_PAD), "a longer number makes a bigger circle")
close = IT.balloon_shape(bl, (51.0, 40.0))
ok(close["segs"] == [] and close["heads"] == [], "a tip inside the circle: no leader")
ok(near(IT.distance(sbl, (50.0, 40.0)), 0.0) and near(IT.distance(sbl, (50.0 + r + 2.0, 40.0)), 2.0), "inside the circle is on the balloon; 2 mm out is 2 mm")
ok(near(IT.distance(sbl, (30.0, 25.0)), 0.0, 1e-9) and near(IT.distance(sbl, (30.0, 25.0 + 3.0 * 5 / 5)), A._seg_dist((30.0, 28.0), seg[0], seg[1]), 1e-9) and IT.distance(sbl, (30.0, 28.0)) > 1.0, "the leader counts")
ok(IT.next_balloon_text([]) == "1" and IT.next_balloon_text([{"text": "1"}, {"text": "4"}, {"text": "A"}]) == "5", "the next balloon is one over the biggest number")
ok(IT.bump_text("7") == "8" and IT.bump_text("A") == "A", "a number counts on, a letter stays")

# ----------------------------------------------------------------------------------------------------------------------------------- drawing items
ln = IT.new_item("line", a=(0, 0), b=(30, 40))
ok(ln["type"] == "line" and IT.item_shape(ln)["segs"] == [[(0, 0), (30, 40)]] and near(IT.distance(IT.item_shape(ln), (30, 40.0 + 3.0)), 3.0), "a line, and how far a point is from it")
ok(IT.new_item("line", a=(1, 1), b=(1, 1)) is None, "two points on top of each other draw nothing")
rc = IT.new_item("rect", a=(40, 30), b=(10, 5))
ok(rc["p"] == [[10, 5], [40, 30]], "a rectangle is kept as its lower-left and upper-right corners, whichever corners were clicked")
ok(IT.new_item("rect", a=(0, 0), b=(10, 0)) is None, "a rectangle without height draws nothing")
sr = IT.item_shape(rc)
ok(len(sr["segs"][0]) == 5 and sr["segs"][0][0] == sr["segs"][0][-1] and near(IT.distance(sr, (25, 5 - 2.0)), 2.0) and IT.distance(sr, (25, 17)) > 5.0, "its four sides; a point inside is away from them")
ci = IT.new_item("circle", c=(20, 20), through=(20, 30))
ok(near(ci["r"], 10.0) and IT.new_item("circle", c=(1, 1), through=(1, 1)) is None, "a circle by its centre and a point on it")
sc = IT.item_shape(ci)
ok(sc["circle"] == ((20, 20), 10.0) and near(IT.distance(sc, (20, 20)), 10.0) and near(IT.distance(sc, (31.5, 20)), 1.5), "the outline is what counts, not the inside")
ar = IT.new_item("arc", c=(0, 0), start=(10, 0), end=(0, 10))
ok(near(ar["r"], 10.0) and near(ar["a0"], 0.0) and near(ar["a1"], math.pi / 2), "an arc: centre, start, end - counter-clockwise from the start")
ar2 = IT.new_item("arc", c=(0, 0), start=(0, 10), end=(10, 0))
ok(near(ar2["a1"] - ar2["a0"], 1.5 * math.pi), "from the top round to the right the long way: 270 degrees")
ok(IT.new_item("arc", c=(0, 0), start=(10, 0), end=(20, 0)) is None, "an end on the start's ray makes no arc")
sa = IT.item_shape(ar)
ok(nearp(sa["segs"][0][0], (10, 0)) and nearp(sa["segs"][0][-1], (0, 10)) and all(near(math.hypot(*p), 10.0, 1e-9) for p in sa["segs"][0]) and sa["arc"] == ((0, 0), 10.0, 0.0, math.pi / 2),
   "the arc's points are on the circle, from the start to the end")
ok(IT.describe(ln) == "length 50" and IT.describe(rc) == "width 30, height 25" and IT.describe(ci) == "diameter 20" and IT.describe(ar) == "radius 10, sweep 90°", "what they measure")
ok(IT.label({"type": "note", "text": "Hello there"}) == "Hello there" and IT.label({"type": "note", "text": "x" * 40}).endswith("…") and IT.label({"type": "balloon", "text": "2"}) == "Balloon  2" and IT.label(rc) == "Rectangle",
   "how they read in the Outline")

# handles
ok([h[0] for h in IT.handles(ln)] == ["a", "b"] and [h[0] for h in IT.handles(rc)] == ["c0", "c1", "c2", "c3"] and [h[0] for h in IT.handles(ci)] == ["c", "r"] and [h[0] for h in IT.handles(ar)] == ["c", "s", "e"], "the handles of each")
l2 = dict(ln)
l2["p"] = [list(q) for q in ln["p"]]
ok(IT.drag_handle(l2, "b", (60, 0)) and l2["p"] == [[0, 0], [60.0, 0.0]], "the end of a line dragged")
ok(not IT.drag_handle(l2, "b", (0, 0)) and l2["p"] == [[0, 0], [60.0, 0.0]], "to the other end: refused, the line stays")
r2 = {"type": "rect", "p": [[10, 5], [40, 30]]}
ok(IT.drag_handle(r2, "c2", (50, 40)) and r2["p"] == [[10, 5], [50, 40]], "the corner of a rectangle: the opposite one stays")
ok(IT.drag_handle(r2, "c0", (60, 45)) and r2["p"] == [[50, 40], [60, 45]], "dragged past the opposite corner: the rectangle turns over, still two corners")
c2 = {"type": "circle", "c": [20, 20], "r": 10.0}
ok(IT.drag_handle(c2, "r", (20, 45)) and near(c2["r"], 25.0) and c2["c"] == [20, 20], "the radius handle: the circle grows round its centre")
ok(IT.drag_handle(c2, "c", (0, 0)) and c2["c"] == [0.0, 0.0] and near(c2["r"], 25.0), "the centre handle: the circle moves")
a2 = {"type": "arc", "c": [0, 0], "r": 10.0, "a0": 0.0, "a1": math.pi / 2}
ok(IT.drag_handle(a2, "e", (-10, 0)) and near(a2["a1"], math.pi) and near(a2["r"], 10.0), "the end of an arc: it sweeps to the new angle, the radius stays")
ok(IT.drag_handle(a2, "s", (0, -20)) and near(a2["r"], 20.0) and near(a2["a0"], -math.pi / 2) and near(a2["a1"] - a2["a0"], 1.5 * math.pi), "the start: new radius and angle, the end stays where it was")
ok(not IT.drag_handle(a2, "e", (0, -30)), "an end back on the start makes no arc: refused")
IT.translate(a2, 5, 5)
IT.translate(l2, 1, 2)
IT.translate(rc, -10, 0)
ok(a2["c"] == [5, 5] and l2["p"] == [[1, 2], [61, 2]] and rc["p"] == [[0, 5], [30, 30]], "moved")
nn = IT.new_note("a", (10, 10))
IT.translate(nn, 3, -4)
ok(nn["pos"] == [13.0, 6.0], "a note moves by its position")

# snapping a click onto what it was picked from
ok(IT.snap_on({"k": "pt", "p": (3, 4)}, (3.3, 4.2)) == (3, 4), "a point: the point")
ok(nearp(IT.snap_on({"k": "line", "a": (0, 0), "b": (10, 0)}, (4.0, 0.3)), (4.0, 0.0)) and nearp(IT.snap_on({"k": "line", "a": (0, 0), "b": (10, 0)}, (14.0, 1.0)), (10.0, 0.0)), "a line: the nearest point of it")
sc_ = IT.snap_on({"k": "circle", "c": (0, 0), "r": 10.0}, (0.0, 12.0))
ok(nearp(sc_, (0.0, 10.0)), "a circle: the nearest point of it")
arcref = {"k": "arc", "c": (0, 0), "r": 10.0, "a0": 0.0, "a1": math.pi / 2}
ok(nearp(IT.snap_on(arcref, (7.0, 7.0)), (10 * math.cos(math.pi / 4), 10 * math.sin(math.pi / 4))) and nearp(IT.snap_on(arcref, (10.0, -3.0)), (10.0, 0.0)), "an arc: the nearest point of it, an end when the click is past one")

# ----------------------------------------------------------------------------------------------------------------------------------- the document
bar, _sid = ex.part_doc(100, 20, 10)
d = M.Drawing()
mid = d.add_model("Bar", "part", bar, src="n1")
v = d.add_view(mid, "Front", (100, 100), scale=1.0)
n1 = d.add_note("Hello", (20, 150), 14.0)
ok(n1["id"] == "n1" and d.notes == [n1] and d.counter["note"] == 1 and n1["leader"] is None, "a note is added with an id")
for bad in ("", "   ", None):
    try:
        d.add_note(bad if bad is not None else "", (0, 0))
        ok(False, "an empty note is refused")
    except M.DrawingError as e:
        ok("text" in str(e), f"a note with no text is refused ({e})")
        break
vx = d.view(v["id"])
n2 = d.add_note("Leader", (150, 150), 14.0, {"kind": "straight", "view": v["id"], "p": [10.0, 5.0]})
tip = d.leader_tip(n2)
ok(nearp(tip, (vx["origin"][0] + 10.0 * vx["scale"], vx["origin"][1] + 5.0 * vx["scale"])), "the tip of a leader that points into a view is in that view's frame")
o0 = tuple(d.view(v["id"])["origin"])
d.move_view(v["id"], 130, 90)
o1 = tuple(d.view(v["id"])["origin"])
tip2 = d.leader_tip(n2)
ok(not nearp(o0, o1) and nearp((tip2[0] - tip[0], tip2[1] - tip[1]), (o1[0] - o0[0], o1[1] - o0[1])), "the view moved: the tip went with it, by the same distance")
ok(nearp(tip2, (o1[0] + 10.0, o1[1] + 5.0)), "to the same point of the view")
d.set_scale(v["id"], 2.0)
ok(nearp(d.leader_tip(n2), (d.view(v["id"])["origin"][0] + 20.0, d.view(v["id"])["origin"][1] + 10.0)), "at another scale it is at the same point of the view still")
b1 = d.add_balloon(v["id"], "1", (5.0, 5.0), (200, 180))
ok(b1["id"] == "b1" and d.balloons == [b1] and d.balloon_tip(b1) is not None and b1["snap"], "a balloon on a view, with an id")
try:
    d.add_balloon(v["id"], " ", (0, 0), (0, 0))
    ok(False, "a balloon without a number")
except M.DrawingError as e:
    ok("number" in str(e), f"a balloon without a number is refused ({e})")
try:
    d.add_balloon("nope", "1", (0, 0), (0, 0))
    ok(False, "a balloon on no view")
except M.DrawingError:
    ok(True, "a balloon on a view that is not there is refused")
l1 = d.add_item("line", a=(10, 10), b=(60, 10))
c1 = d.add_item("circle", c=(50, 50), through=(60, 50))
ok(l1["id"] == "l1" and c1["id"] == "l2" and d.lines == [l1, c1] and d.counter["draw"] == 2, "drawing items have ids")
try:
    d.add_item("line", a=(1, 1), b=(1, 1))
    ok(False, "a line of no length")
except M.DrawingError as e:
    ok("nothing" in str(e), f"a line of no length is refused ({e})")
ok(d.annot("n1") is n1 and d.annot("b1") is b1 and d.annot("l2") is c1, "any of them is found by its id")
ok([a["id"] for a in d.sheet_items()] == ["b1", "n1", "n2", "l1", "l2"], "all of them, in the order they are painted (balloons, notes, drawing items)")
ok(d.item_shape(n2)["heads"] and d.item_shape(b1)["circle"] and d.item_shape(l1)["segs"], "a shape for each of them")
ok([a["id"] for a in d.view_items(v["id"])] == ["b1"] and d.annots(v["id"]) == [], "a balloon goes with its view (the Outline shows it there); notes and drawing items are the sheet's")

# changing a note
d.set_note("n1", text="Changed", size=18)
ok(d.annot("n1")["text"] == "Changed" and d.annot("n1")["size"] == 18.0, "a note's text and size change")
d.set_note("n1", leader="bent")
ok(d.annot("n1")["leader"]["kind"] == "bent" and d.annot("n1")["leader"]["view"] is None and d.leader_tip(d.annot("n1")) is not None, "a leader added to a note starts at a point of the sheet, to the lower left of the text")
d.set_note("n1", leader="straight")
ok(d.annot("n1")["leader"]["kind"] == "straight", "a leader changes from bent to straight")
d.set_note("n1", leader=None)
ok(d.annot("n1")["leader"] is None and d.leader_tip(d.annot("n1")) is None, "and goes")
try:
    d.set_note("n1", text="")
    ok(False, "empty text")
except M.DrawingError:
    ok(d.annot("n1")["text"] == "Changed", "the text cannot be made empty")
try:
    d.set_note("b1", text="x")
    ok(False, "not a note")
except M.DrawingError:
    ok(True, "a balloon is not a note")
d.set_balloon_text("b1", " 7 ")
ok(d.annot("b1")["text"] == "7", "a balloon's number changes (trimmed)")

# moving, dragging tips and handles
d.move_item("n1", 5, -5)
ok(d.annot("n1")["pos"] == [25.0, 145.0], "a note is moved")
d.move_item("b1", 10, 0)
ok(d.annot("b1")["pos"] == [210.0, 180.0] and d.annot("b1")["tip"] == [5.0, 5.0], "a balloon's circle is moved, its tip stays on the view")
d.move_item("l2", 1, 1)
ok(d.annot("l2")["c"] == [51.0, 51.0], "a drawing item is moved")
try:
    d.move_item("d1", 1, 1)
    ok(False, "unknown")
except M.DrawingError:
    ok(True, "something that is not there cannot be moved")
vx = d.view(v["id"])
d.set_tip("n2", 0, 0, hit=(v["id"], (30.0, 4.0), True))
ok(d.annot("n2")["leader"]["view"] == v["id"] and d.annot("n2")["leader"]["p"] == [30.0, 4.0], "a leader's tip dragged onto the view's lines: in the view's frame")
d.set_tip("n2", 12.0, 13.0)
ok(d.annot("n2")["leader"]["view"] is None and d.annot("n2")["leader"]["p"] == [12.0, 13.0], "dragged off the view: a point of the sheet")
d.set_tip("b1", 0, 0, hit=(v["id"], (40.0, 8.0), False))
ok(d.annot("b1")["tip"] == [40.0, 8.0] and d.annot("b1")["snap"] is False, "a balloon's tip dragged onto a face: not snapped, so a dot")
sx, sy = vx["origin"][0] + vx["scale"] * 3.0, vx["origin"][1] + vx["scale"] * 4.0
d.set_tip("b1", sx, sy)
ok(nearp(d.annot("b1")["tip"], (3.0, 4.0)) and d.annot("b1")["view"] == v["id"], "dragged off the lines: where the pointer is, in the view's frame (a balloon always belongs to a view)")
d.set_tip("n2", 0, 0, hit=(v["id"], (10.0, 5.0), True))
ok(d.drag_handle("l1", "b", (80, 30)) and d.annot("l1")["p"][1] == [80.0, 30.0], "a drawing item's handle is dragged")
try:
    d.drag_handle("n1", "a", (0, 0))
    ok(False, "a note has no handles")
except M.DrawingError:
    ok(True, "a note has no handles")

# the view looks another way / goes
d.set_orient(v["id"], "Top")
ok(d.balloons == [] and d.annot("n2")["leader"]["view"] is None, "the view looks another way: its balloons go, a note's leader keeps pointing at the same place of the sheet")
ok(d.annot("n2")["leader"]["p"] != [10.0, 5.0], "(as a point of the sheet now)")
d.set_orient(v["id"], "Front")
b2 = d.add_balloon(v["id"], "2", (5.0, 5.0), (200, 180))
d.set_tip("n2", 0, 0, hit=(v["id"], (10.0, 5.0), True))
tipbefore = d.leader_tip(d.annot("n2"))
d.remove_view(v["id"])
ok(d.balloons == [] and d.annot("n2")["leader"]["view"] is None and nearp(d.leader_tip(d.annot("n2")), tipbefore), "the view is deleted: its balloons go with it, a note's leader stays where it pointed")

# the file and undo
d2 = M.Drawing()
mid2 = d2.add_model("Bar", "part", bar, src="n1")
vv = d2.add_view(mid2, "Front", (100, 100), scale=1.0)
d2.add_note("Two\nlines", (20, 150), 12.0, {"kind": "bent", "view": vv["id"], "p": [3.0, 4.0]})
d2.add_balloon(vv["id"], "A", (5.0, 5.0), (200, 180), False)
d2.add_item("rect", a=(10, 10), b=(40, 30))
d2.add_item("arc", c=(0, 0), start=(10, 0), end=(0, 10))
e = M.Drawing.from_json(d2.to_json())
ok(len(e.notes) == 1 and len(e.balloons) == 1 and len(e.lines) == 2 and e.counter["note"] == 1 and e.counter["balloon"] == 1 and e.counter["draw"] == 2, "they are in the file, with the counters")
ok(e.notes[0]["text"] == "Two\nlines" and e.notes[0]["leader"]["kind"] == "bent" and e.balloons[0]["snap"] is False and e.lines[1]["a1"] == d2.lines[1]["a1"], "with everything they say")
ok(e.item_shape(e.notes[0])["segs"] == d2.item_shape(d2.notes[0])["segs"] and e.item_shape(e.balloons[0])["dots"] == d2.item_shape(d2.balloons[0])["dots"], "and are drawn the same after opening")
e.add_note("Next", (0, 0))
ok(e.notes[-1]["id"] == "n2", "the next note carries on counting")
snap = d2.snapshot()
d2.remove_annot("n1")
d2.remove_annot("l1")
d2.move_item("b1", 50, 50)
ok(d2.notes == [] and len(d2.lines) == 1, "removed")
d2.restore(snap)
ok(len(d2.notes) == 1 and len(d2.lines) == 2 and d2.balloons[0]["pos"] == [200.0, 180.0], "undo brings them back")
d2.notes[0]["text"] = "mutated"
d2.restore(snap)
ok(d2.notes[0]["text"] == "Two\nlines", "and the snapshot is not changed by what is done after it")
junk = M.Drawing.from_json('{"format": "openpara-drawing", "version": 1, "notes": [3, {"id": "n9", "type": "note", "text": "ok", "pos": [1, 2]}], "lines": [{"id": "l9", "type": "line", "p": [[0, 0], [1, 1]]}]}')
ok(len(junk.notes) == 1 and len(junk.lines) == 1, "a file with something that is not a record in it: the rest opens")
bad = M.Drawing.from_json('{"format": "openpara-drawing", "version": 1, "notes": [{"id": "n1", "type": "note", "text": "no place"}, {"id": "n2", "type": "note", "text": "bad leader", "pos": [1, 2], "leader": {"kind": "wavy", "p": [0, 0]}}, '
                          '{"id": "n3", "type": "note", "text": "fine", "pos": [1, 2], "leader": {"kind": "bent", "view": null, "p": [0, 0]}}], '
                          '"balloons": [{"id": "b1", "type": "balloon", "text": "1", "view": "v9", "tip": [0, 0], "pos": [5, 5]}], '
                          '"lines": [{"id": "l1", "type": "circle", "c": [0, 0], "r": 0}, {"id": "l2", "type": "arc", "c": [0, 0], "r": 3, "a0": 2, "a1": 1}, {"id": "l3", "type": "rect", "p": [[0, 0]]}, {"type": "line", "p": [[0, 0], [1, 1]]}, '
                          '{"id": "l5", "type": "spiral"}, {"id": "l6", "type": "rect", "p": [[0, 0], [4, 5]]}]}')
ok([n["id"] for n in bad.notes] == ["n3"] and bad.balloons == [] and [x["id"] for x in bad.lines] == ["l6"],
   f"records that are not whole (no place, an unknown leader, a radius of 0, a missing point, no id, an unknown kind, a balloon on a view that is not there) are left out; the whole ones stay ({[n['id'] for n in bad.notes]}, {[x['id'] for x in bad.lines]})")

print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
