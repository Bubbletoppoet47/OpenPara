"""Drawings (dev add-on drawings): the Linear Note Pattern, without a window (dr_items.py and the drawing document) - where the copies of a note are (one direction, two directions, any
angle, a negative spacing), what is drawn for them (text, leaders and arrows move with each copy), picking on a copy, the plain-words refusals, the file and undo.
python test_dr_pattern.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
import dr_items as IT
import dr_model as M

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, c, tol=1e-6):
    return abs(a - c) <= tol


def nearp(p, q, tol=1e-6):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def refused(fn, *a, **kw):
    """The plain-words message of the refusal, or None when nothing was refused."""
    try:
        fn(*a, **kw)
    except (M.DrawingError, ValueError) as ex:
        return str(ex)
    return None


P = lambda **kw: dict({"a1": 0.0, "s1": 10.0, "c1": 1, "a2": 90.0, "s2": 5.0, "c2": 1}, **kw)

# ----------------------------------------------------------------------------------------------------------------------------------- where the copies are
offs = IT.pattern_offsets(P(c1=3))
ok(len(offs) == 3 and nearp(offs[0], (0, 0)) and nearp(offs[1], (10, 0)) and nearp(offs[2], (20, 0)), "three notes in a row: the note itself, then 10 mm and 20 mm along direction 1")
offs = IT.pattern_offsets(P(c1=2, c2=2))
ok(len(offs) == 4 and [tuple(round(v, 6) for v in o) for o in offs] == [(0, 0), (10, 0), (0, 5), (10, 5)], "two directions: the first row, then the next row 5 mm along direction 2")
offs = IT.pattern_offsets(P(a1=45.0, s1=math.sqrt(2.0) * 10.0, c1=3))
ok(nearp(offs[1], (10, 10)) and nearp(offs[2], (20, 20)), "at 45 degrees the notes step 10 mm across and 10 mm up")
offs = IT.pattern_offsets(P(s1=-10.0, c1=3))
ok(nearp(offs[1], (-10, 0)) and nearp(offs[2], (-20, 0)), "a negative spacing goes the other way")
offs = IT.pattern_offsets(P(a1=30.0, s1=8.0, c1=2, a2=120.0, s2=3.0, c2=3))
ok(len(offs) == 6 and nearp(offs[3], (8 * math.cos(math.radians(30)) + 3 * math.cos(math.radians(120)), 8 * math.sin(math.radians(30)) + 3 * math.sin(math.radians(120)))),
   "any two directions: a copy is i steps along one and j along the other")
ok(IT.pattern_offsets(P()) == [(0.0, 0.0)], "one note in each direction: the note alone")

box = (0.0, -3.5, 40.0, 0.0)
dp = IT.default_pattern(box)
ok(dp["c1"] == 3 and dp["c2"] == 1 and near(dp["s1"], 45.0) and near(dp["s2"], 6.5) and dp["a1"] == 0.0 and dp["a2"] == 90.0, "a first pattern: three in a row, a note's width and 5 mm apart")

# ----------------------------------------------------------------------------------------------------------------------------------- the numbers
ok(IT.clean_pattern(P(a1=370.0, a2=-90.0, c1="3", s1="12.5"))["a1"] == 10.0, "an angle is kept between 0 and 360")
cp = IT.clean_pattern(P(a1=370.0, a2=-90.0, c1="3", s1="12.5"))
ok(near(cp["a2"], 270.0) and cp["c1"] == 3 and near(cp["s1"], 12.5), "angles are kept between 0 and 360 and numbers written as text are read")
for bad, word in ((P(c1=0), "at least one"), (P(c2=-2), "at least one"), (P(c1=30, c2=30), "at most 400"), (P(c1=2, s1=0.0), "at least 0.1"), (P(c2=2, s2=0.05), "at least 0.1"),
                  (P(s1=float("nan")), "needs"), (P(a1=float("inf")), "needs"), ({"a1": 0, "s1": 10, "c1": 2}, "needs"), (P(c1="many"), "needs")):
    msg = refused(IT.clean_pattern, bad)
    ok(msg is not None and word in msg, f"{ {k: v for k, v in bad.items() if bad[k] != P()[k]} } is refused: {msg}")
ok(refused(IT.clean_pattern, P(c1=1, s1=0.0)) is None, "a spacing of nothing does no harm when there is only one note in that direction")
ok(refused(IT.clean_pattern, P(c1=20, c2=20)) is None and refused(IT.clean_pattern, P(c1=21, c2=20)) is not None, "400 notes is the most")

# ----------------------------------------------------------------------------------------------------------------------------------- what is drawn
m14 = IT.default_metrics(14.0)
w = m14.width("Hole")
n = IT.new_note("Hole", (20.0, 80.0))
alone = IT.note_shape(n, None)
n["pattern"] = P(c1=3, s1=30.0)
sp = IT.note_shape(n, None)
ok(len(sp["boxes"]) == 3 and len(sp["lines"]) == 3 and sp["boxes"][0] == alone["box"], "three notes: three boxes and three texts; the first is the note itself")
ok(nearp(sp["lines"][1][1], (alone["lines"][0][1][0] + 30.0, alone["lines"][0][1][1])) and sp["lines"][1][0] == "Hole" and sp["lines"][2][0] == "Hole", "each copy says the same, 30 mm further on")
ok(near(sp["box"][0], 20.0) and near(sp["box"][2], 20.0 + 60.0 + w) and near(sp["box"][3], 80.0) and near(sp["box"][1], 80.0 - m14.cap), "the box of all of them: from the first to the last")
n["pattern"] = P(c1=2, s1=30.0, c2=2, s2=-12.0)
sp = IT.note_shape(n, None)
ok(len(sp["boxes"]) == 4 and near(sp["box"][1], 80.0 - m14.cap - 12.0), "a second direction with a negative spacing adds a row under the first")
n2 = IT.new_note("Two\nlines", (0.0, 0.0), 10.0)
n2["pattern"] = P(c1=2, s1=25.0)
s2 = IT.note_shape(n2, None)
ok(len(s2["lines"]) == 4 and [t for t, _ in s2["lines"]] == ["Two", "lines", "Two", "lines"], "a note of two lines: both lines of each copy")
ok(near(s2["lines"][2][1][0] - s2["lines"][0][1][0], 25.0) and near(s2["lines"][3][1][1], s2["lines"][1][1][1]), "the copy is the same, 25 mm along")

# leaders and arrows go with each copy
nl = IT.new_note("Hole", (50.0, 50.0), 14.0, {"kind": "straight", "view": None, "p": (10.0, 30.0)})
one = IT.note_shape(nl, (10.0, 30.0))
nl["pattern"] = P(c1=3, s1=20.0, a1=90.0)
three = IT.note_shape(nl, (10.0, 30.0))
ok(len(three["segs"]) == 3 and len(three["heads"]) == 3, "a note with a leader: a leader and an arrow for each copy")
ok(nearp(three["segs"][1][0], (10.0, 50.0)) and nearp(three["heads"][1][0], (10.0, 50.0)) and nearp(three["segs"][2][0], (10.0, 70.0)), "the tip of each copy's leader is moved the same way as the copy")
ok(nearp(three["segs"][0][0], one["segs"][0][0]) and nearp(three["segs"][0][1], one["segs"][0][1]) and nearp(three["heads"][0][1], one["heads"][0][1]), "the first leader is the one of the note alone")
ok(nearp(three["heads"][1][1], one["heads"][0][1]) and near(three["heads"][1][2], one["heads"][0][2]), "the arrows of the copies point the same way and are as big")
bl = IT.new_note("Hole", (50.0, 50.0), 14.0, {"kind": "bent", "view": None, "p": (10.0, 30.0)})
bl["pattern"] = P(c1=2, s1=20.0, a1=0.0)
sb = IT.note_shape(bl, (10.0, 30.0))
ok(len(sb["segs"]) == 2 and len(sb["segs"][0]) == len(sb["segs"][1]) and all(nearp(sb["segs"][1][i], (sb["segs"][0][i][0] + 20.0, sb["segs"][0][i][1])) for i in range(len(sb["segs"][0]))),
   "a bent leader is copied with all its corners")

# picking
n = IT.new_note("Hole", (20.0, 80.0))
n["pattern"] = P(c1=3, s1=30.0)
shp = IT.note_shape(n, None)
ok(near(IT.distance(shp, (20.0 + 30.0 + w / 2.0, 80.0 - 1.0)), 0.0), "a point on the text of the second copy: on the note")
ok(near(IT.distance(shp, (20.0 + 60.0 + w + 4.0, 80.0 - 1.0)), 4.0), "4 mm to the right of the last copy: 4 mm from the note")
ok(near(IT.distance(shp, (20.0 + w + 5.0, 80.0 - 1.0)), 5.0), "5 mm to the right of the first copy, far from the next: 5 mm")
gap = IT.distance(shp, (20.0 + w + 10.0, 80.0 - 1.0))
ok(near(gap, min(10.0, 50.0 - (20.0 + w + 10.0))), f"between two copies the distance is to the nearer one ({gap:.3f})")
ok(IT.distance(IT.note_shape(IT.new_note("Hole", (20.0, 80.0)), None), (20.0 + 30.0 + w / 2.0, 80.0 - 1.0)) > 20.0, "and without the pattern that point is nowhere near")

# moving a note moves the copies
mv = IT.new_note("Hole", (20.0, 80.0))
mv["pattern"] = P(c1=3, s1=30.0)
b0 = IT.note_shape(mv, None)["boxes"]
IT.translate(mv, 7.0, -4.0)
b1 = IT.note_shape(mv, None)["boxes"]
ok(all(nearp((b1[i][0] - b0[i][0], b1[i][1] - b0[i][1]), (7.0, -4.0)) for i in range(3)) and mv["pattern"] == P(c1=3, s1=30.0), "moving the note moves every copy by the same, and the pattern stays")

# the text of the pattern in words
ok(IT.pattern_text(P(c1=3, s1=25.0)) == "3 notes, 25 mm along 0°", "in words: 3 notes, 25 mm along 0°")
ok(IT.pattern_text(P(c1=3, s1=-25.0)) == "3 notes, 25 mm along 180°", "a negative spacing reads as the opposite direction")
ok(IT.pattern_text(P(c1=2, s1=10.0, c2=3, s2=4.5)) == "2 × 3 notes: 10 mm along 0°; 4.5 mm along 90°", "two directions: both are told")
ok(IT.pattern_text(P(c2=4, s2=6.0)) == "4 notes, 6 mm along 90°" and IT.pattern_text(P()) == "1 note (no copies)", "a pattern in direction 2 only, and a pattern of nothing")

# ----------------------------------------------------------------------------------------------------------------------------------- the document
d = M.Drawing()
nt = d.add_note("Break edges", (20.0, 150.0), 14.0)
ok(not nt.get("pattern"), "a note has no pattern at first")
d.set_pattern("n1")
pat = d.annot("n1")["pattern"]
bx = IT.note_shape(d.annot("n1"), None)["boxes"][0]
ok(pat["c1"] == 3 and pat["c2"] == 1 and near(pat["s1"], round(bx[2] - bx[0] + 5.0, 1)), "asking for a pattern gives the first one: three in a row")
ok(len(d.item_shape(d.annot("n1"))["boxes"]) == 3, "and the sheet shows three notes")
d.set_pattern("n1", s1=40.0, a1=90.0)
p2 = d.annot("n1")["pattern"]
ok(near(p2["s1"], 40.0) and near(p2["a1"], 90.0) and p2["c1"] == 3, "fields are changed one at a time; the others stay")
d.set_pattern("n1", c1=2, c2=2, s2=15.0)
ok(len(d.item_shape(d.annot("n1"))["boxes"]) == 4, "two by two notes")
before = dict(d.annot("n1")["pattern"])
for kw, word in (({"c1": 0}, "at least one"), ({"c1": 30, "c2": 30}, "at most 400"), ({"s1": 0.0}, "at least 0.1"), ({"s1": float("nan")}, "needs")):
    msg = refused(d.set_pattern, "n1", **kw)
    ok(msg is not None and word in msg and d.annot("n1")["pattern"] == before, f"{kw} is refused in words and the pattern is as it was: {msg}")
d.set_pattern("n1", remove=True)
ok(d.annot("n1")["pattern"] is None and len(d.item_shape(d.annot("n1"))["boxes"]) == 1, "a pattern is taken away; the note stays")
d.set_pattern("n1", remove=True)
ok(d.annot("n1")["pattern"] is None, "taking it away again does no harm")
v_ = d.add_item("line", a=(0, 0), b=(10, 0))
ok("note" in (refused(d.set_pattern, v_["id"]) or ""), "only a note can be repeated: " + str(refused(d.set_pattern, v_["id"])))
ok("not on the drawing" in (refused(d.set_pattern, "n99") or ""), "a note that is not there: " + str(refused(d.set_pattern, "n99")))

# the file, undo and what a damaged file does
d.set_pattern("n1", c1=4, s1=33.0, a1=15.0)
snap = d.snapshot()
e = M.Drawing.from_json(d.to_json())
ok(e.notes[0]["pattern"] == d.notes[0]["pattern"] and len(e.item_shape(e.notes[0])["boxes"]) == 4, "the pattern is in the file, and the sheet shows the same four notes after opening")
d.set_pattern("n1", remove=True)
d.restore(snap)
ok(d.annot("n1")["pattern"]["c1"] == 4, "undo brings the pattern back")
d.set_pattern("n1", c1=2)
ok(snap["annot"]["notes"][0]["pattern"]["c1"] == 4, "and the snapshot is not changed by what is done after it")
text = ('{"format": "openpara-drawing", "version": 1, "notes": [{"id": "n1", "type": "note", "text": "a", "pos": [1, 2], "pattern": {"a1": 0, "s1": 5, "c1": 0, "a2": 90, "s2": 5, "c2": 1}}, '
        '{"id": "n2", "type": "note", "text": "b", "pos": [1, 2], "pattern": "three"}, {"id": "n3", "type": "note", "text": "c", "pos": [1, 2]}, '
        '{"id": "n4", "type": "note", "text": "d", "pos": [1, 2], "pattern": {"a1": 0, "s1": 5, "c1": 2, "a2": 90, "s2": 5, "c2": 1}}]}')
bad = M.Drawing.from_json(text)
ok([n["id"] for n in bad.notes] == ["n1", "n2", "n3", "n4"] and [bool(n["pattern"]) for n in bad.notes] == [False, False, False, True], "a damaged pattern is left out and the note kept; a good one is kept")
ok(len(bad.item_shape(bad.notes[0])["boxes"]) == 1 and len(bad.item_shape(bad.notes[3])["boxes"]) == 2, "and each is drawn as it should be")
big = M.Drawing()
big.add_note("x", (0, 0))
big.notes[0]["pattern"] = P(c1=500, c2=500)                      # a pattern that got into the document by some other way is not drawn as 250000 notes
ok(len(big.item_shape(big.notes[0])["boxes"]) == 1, "a pattern that is out of range is not drawn: just the note")

print("-" * 70)
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
