"""Drawings (dev add-on drawings): the shaded display styles in the window - the style buttons of the panels and the Details, what is painted (pixels: the grey of a face, nothing in a hole,
no lines in Shaded, the visible lines in Shaded With Edges), the picture made once and kept (moving, a little zoom), made again for a new scale or a much bigger zoom, picking and dimensions
on a shaded view, undo, the file (a drawing opens shaded without its models) and the PDF (a 200 dpi picture of the surface under vector lines).   python test_dr_shade_tab.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import math
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pm_app
pm_app.apply_theme(app)
import dr_annot as A
import dr_items as IT
import dr_model as M
import dr_panels as PN
import dr_tab as T

T.DrawingTab.ASK_SHEET = False
FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def settle():
    for _ in range(3):
        app.processEvents()


def plate(w, h, hole=True, r=8.0, at=(30.0, 30.0)):
    """A plate w x h x 10 (a rectangle on the Top plane, extruded), with a hole of radius r at `at`."""
    import pm_model as pm
    import sk_tools as sk
    d = pm.Document()
    d.params = {"H": "10"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    rc = sk.add_rect_corner(m, (0, 0), (w, h))
    m.add_con("dim_h", [("ln", rc["lns"][0])], value=float(w))
    m.add_con("dim_v", [("ln", rc["lns"][1])], value=float(h))
    if hole:
        m.add_circle(m.add_point(*at), r)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    return json.loads(d.to_json())




tmp = tempfile.mkdtemp(prefix="dr_items_")
t = T.DrawingTab()
t.resize(1250, 800)
t.show()
settle()
cv = t.canvas
mid = t.d.add_model("Plate", "part", plate(100, 60), src="n1")
t.models_from_wires = True
t.model_panel.refresh()
ok(all(b.isEnabled() for b in t.model_panel.sbtn.values()) and len(t.model_panel.sbtn) == 5, "the panel offers five display styles")
t.model_panel.sbtn["shaded"].click()
ok(t.model_panel.current_style() == "shaded", "Shaded is picked")
t.model_panel.pick_orientation("Top")
at = lambda x, y: cv.to_screen(x, y).toPoint()
QTest.mouseMove(cv, at(100, 110))
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(100, 110))
settle()
v = t.d.views[0]
vid = v["id"]
s_, o_ = v["scale"], v["origin"]
S = lambda p: (o_[0] + s_ * p[0], o_[1] + s_ * p[1])           # a point of the view's frame on the sheet
ok(len(t.d.views) == 1 and near(s_, 1.0) and v["style"] == "shaded", "the Top view of a 100 x 60 plate with a hole of 16 mm is on the sheet, in the style that was picked")
tol = 1.0 / cv.k                                       # one pixel, in mm: a click is on a whole pixel, so a point clicked is only this exact
P = lambda a, b, f=1.5: abs(a[0] - b[0]) <= f * tol and abs(a[1] - b[1]) <= f * tol
V = lambda a, b, f=1.5: abs(a - b) <= f * tol


def click(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def move(x, y):
    QTest.mouseMove(cv, at(x, y))
    settle()


def drag(x0, y0, x1, y1, steps=4):
    QTest.mouseMove(cv, at(x0, y0))
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=at(x0, y0))
    for i in range(1, steps + 1):
        QTest.mouseMove(cv, at(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps))
        settle()
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=at(x1, y1))
    settle()


def dclick(x, y):
    QTest.mouseMove(cv, at(x, y))
    QTest.mouseDClick(cv, Qt.MouseButton.LeftButton, pos=at(x, y))
    settle()


def key(k):
    QTest.keyClick(cv, k)
    settle()


def dark_count(x0, y0, x1, y1, im=None):
    """Dark pixels in the rectangle (sheet mm, any two corners)."""
    im = im or cv.grab().toImage()
    a, b = at(x0, y0), at(x1, y1)
    n = 0
    for px in range(min(a.x(), b.x()), max(a.x(), b.x()) + 1):
        for py in range(min(a.y(), b.y()), max(a.y(), b.y()) + 1):
            if QColor(im.pixel(px, py)).lightness() < 140:
                n += 1
    return n


def dark_at(x, y, im=None):
    im = im or cv.grab().toImage()
    c = at(x, y)
    return min(QColor(im.pixel(c.x() + dx, c.y() + dy)).lightness() for dx in (-1, 0, 1) for dy in (-1, 0, 1)) < 140


def blue_at(x, y, im=None):
    im = im or cv.grab().toImage()
    c = at(x, y)
    return any((lambda q: q.blue() - q.red() > 40)(QColor(im.pixel(c.x() + dx, c.y() + dy))) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2))


def outline_texts():
    out = []

    def walk(it):
        out.append(it.text(0))
        for i in range(it.childCount()):
            walk(it.child(i))
    for i in range(t.outline.tree.topLevelItemCount()):
        walk(t.outline.tree.topLevelItem(i))
    return out


def seg_mid(shp, i=0, j=0):
    a, b = shp["segs"][i][j], shp["segs"][i][j + 1]
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


import dr_render as R
import dr_shade as SH
import fitz

PLATE_GREY = float(SH.grey(SH.brightness((0.0, 0.0, 1.0))))
calls = []
_real_render = SH.render


def counting_render(mesh, px, ss=2):
    calls.append(px)
    return _real_render(mesh, px, ss)


R.SH.render = counting_render


def grey_at(p, im=None):
    """The lightness of the canvas at a point of the sheet (mm)."""
    im = im or cv.grab().toImage()
    c = at(*p)
    return QColor(im.pixel(c.x(), c.y())).lightness()


def shaded_px(im=None):
    """How many pixels of the canvas have the grey of a face that looks at the viewer."""
    im = im or cv.grab().toImage()
    n = 0
    for x in range(0, im.width(), 3):
        for y in range(0, im.height(), 3):
            if abs(QColor(im.pixel(x, y)).lightness() - PLATE_GREY) <= 6:
                n += 1
    return n


vid0 = t.d.views[0]["id"]
body_pt = S((70.0, 40.0))                                       # on the plate, away from the hole
hole_pt = S((30.0, 30.0))                                       # the middle of the hole
cv.set_selected(None)
settle()
ok(vid0 in cv.r.shades and len(t.d.views) == 1, "the picture of the view was made, and is kept")
im = cv.grab().toImage()
ok(abs(grey_at(body_pt, im) - PLATE_GREY) <= 4, f"Shaded: the plate is the grey of a face that looks at the viewer ({grey_at(body_pt, im)} against {PLATE_GREY:.0f})")
ok(grey_at(hole_pt, im) > 250, f"and the hole is the white of the sheet ({grey_at(hole_pt, im)})")
calls.clear()
x0, y0 = S((0.0, 0.0))
x1, y1 = S((100.0, 60.0))
ok(dark_count(x0 - 1, y0 - 1, x1 + 1, y1 + 1, im) == 0, "Shaded has no lines: not one dark pixel over the whole plate, its edges or the hole's")
ok(not blue_at(*S((50.0, 30.0)), im), "nothing is selected")
n_calls = len(calls)
cv.update()
settle()
cv.grab()
ok(len(calls) == n_calls == 0, "painting again does not make the picture again")

# ---------------------------------------------------------------------------------------------------------------------------- the styles in the Details
vid = t.d.views[0]["id"]
cv.set_selected(vid)
settle()
styles = [t.outline.v_style.itemData(i) for i in range(t.outline.v_style.count())]
ok(styles == ["wireframe", "hlv", "hlr", "shaded_edges", "shaded"], f"the Details of a view list the five styles ({styles})")
ok(t.outline.v_style.currentData() == "shaded" and t.outline.v_style.itemText(3) == "Shaded With Edges", "the style of the view is the one shown")
n_undo = len(t.undo_stack)
ix = t.outline.v_style.findData("shaded_edges")
t.outline.v_style.setCurrentIndex(ix)
t.outline.v_style.activated.emit(ix)
settle()
ok(t.d.views[0]["style"] == "shaded_edges" and len(t.undo_stack) == n_undo + 1, "picking Shaded With Edges in the Details: one undo step")
ok(len(calls) == n_calls, "the same triangles, the same picture: nothing is made again")
cv.set_selected(None)
settle()
im = cv.grab().toImage()
ok(abs(grey_at(body_pt, im) - PLATE_GREY) <= 4 and grey_at(hole_pt, im) > 250, "the plate is still grey, the hole is still open")
ok(dark_at(*S((70.0, 60.0)), im) and dark_at(*S((0.0, 30.0)), im) and dark_at(*S((100.0, 30.0)), im) and dark_at(*S((70.0, 0.0)), im), "and now the four edges of the plate are black lines")
ok(dark_at(*S((30.0, 38.0)), im) and dark_at(*S((22.0, 30.0)), im) and dark_at(*S((38.0, 30.0)), im), "and so is the hole (top, left and right of the circle)")
inner = dark_count(*S((12.0, 12.0)), *S((88.0, 48.0)), im)
circ = 2 * math.pi * 8.0 * cv.k * max(0.5 * cv.k, 1.25) * 1.6
ok(inner < circ, f"the lines are only the edges, nothing across the face: {inner} dark pixels inside, the circle of the hole needs about {circ / 1.6:.0f}")

t.do_undo()
ok(t.d.views[0]["style"] == "shaded" and dark_count(x0 - 1, y0 - 1, x1 + 1, y1 + 1) == 0, "undo: Shaded, no lines again")
t.do_redo()
ok(t.d.views[0]["style"] == "shaded_edges" and dark_at(*S((70.0, 60.0))), "redo: Shaded With Edges")
t.set_view_style(vid, "hlv")
settle()
im = cv.grab().toImage()
ok("mesh" not in t.d.views[0]["geom"] and grey_at(body_pt, im) > 250 and dark_at(*S((70.0, 60.0)), im), "Hidden Lines Visible: lines only: the plate is white again")
t.set_view_style(vid, "shaded_edges")
settle()
ok(len(calls) > n_calls and abs(grey_at(body_pt) - PLATE_GREY) <= 4, "and Shaded With Edges again: the picture is made again")
n_calls = len(calls)

# ---------------------------------------------------------------------------------------------------------------------------- moving, selecting, zooming
click(*S((70.0, 40.0)))
ok(cv.sel == vid, "a click on the grey of the face selects the view (as a click on its lines does)")
im = cv.grab().toImage()
ok(abs(grey_at(body_pt, im) - PLATE_GREY) <= 4 and dark_at(*S((70.0, 60.0)), im), "selected: the picture is the same")
o0 = list(t.d.views[0]["origin"])
drag(*S((70.0, 40.0)), S((70.0, 40.0))[0] + 20.0, S((70.0, 40.0))[1] + 15.0)
ok(P(t.d.views[0]["origin"], (o0[0] + 20.0, o0[1] + 15.0)), "dragging the view moves it")
ok(len(calls) == n_calls, "and the picture moves with it without being made again")
cv.set_selected(None)
settle()
body2 = (body_pt[0] + 20.0, body_pt[1] + 15.0)
ok(abs(grey_at(body2) - PLATE_GREY) <= 4 and grey_at((hole_pt[0] + 20.0, hole_pt[1] + 15.0)) > 250 and abs(grey_at(hole_pt) - PLATE_GREY) <= 4, "it is grey in the new place, with its hole there (and plate where the hole was)")
t.do_undo()
ok(P(t.d.views[0]["origin"], o0) and abs(grey_at(body_pt) - PLATE_GREY) <= 4 and len(calls) == n_calls, "undo puts it back, still without making the picture again")
k0 = cv.k
cv.zoom(1.15)
settle()
cv.grab()
ok(len(calls) == n_calls, f"zooming a little (to {cv.k / k0:.2f} times): the same picture is used")
n_calls = len(calls)
px_before = cv.r.shades[vid][2]
cv.zoom(6.0)
settle()
cv.grab()
px_after = cv.r.shades[vid][2]
ok(len(calls) == n_calls + 1 and px_after > px_before * 1.5 and px_after <= R.SHADE_SCREEN_PX + 1e-9, f"zooming in a lot: a sharper picture is made ({px_before:.2f} -> {px_after:.2f} pixels to the mm, never more than {R.SHADE_SCREEN_PX:.0f})")
n_calls = len(calls)
cv.fit()
settle()
cv.grab()
ok(len(calls) == n_calls and cv.r.shades[vid][2] == px_after, "going back out: the sharp picture is still good enough, none is made")

# ---------------------------------------------------------------------------------------------------------------------------- the scale
cv.fit()
settle()
n0 = shaded_px()
t.set_view_scale(vid, "1:2")
settle()
n_half = shaded_px()
ok(len(calls) > n_calls and 0.2 < n_half / max(1, n0) < 0.3, f"scale 1:2: a new picture, a quarter of the area ({n_half / max(1, n0):.2f})")
t.set_view_scale(vid, "1:1")
settle()
ok(abs(shaded_px() / max(1, n0) - 1.0) < 0.05, "back to 1:1: as big as at first")

# ---------------------------------------------------------------------------------------------------------------------------- dimensions on a shaded view
t.set_view_style(vid, "shaded")
cv.set_selected(None)
settle()
v = t.d.views[0]
s_, o_ = v["scale"], v["origin"]
[a_ for a_ in t.act["dim"].menu().actions() if a_.text() == "Length / distance"][0].trigger()
settle()
click(*S((50.0, 60.0)))
click(*S((50.0, 60.0 + 12.0)))
key(Qt.Key.Key_Escape)
ok(len(t.d.dims) == 1 and t.d.dims[0]["type"] == "linear", "Dimension works on a shaded view: it picks the lines under the grey")
ok(near(A.value(t.d.dims[0]), 100.0, 1e-6), f"and measures the model: {A.value(t.d.dims[0]):.3f}")
ok(abs(grey_at(S((70.0, 40.0))) - PLATE_GREY) <= 4 and dark_at(*S((50.0, 72.0))), "the dimension is painted over the grey")

# ---------------------------------------------------------------------------------------------------------------------------- the file
t.set_view_style(vid, "shaded_edges")
cv.set_selected(None)
settle()
path = os.path.join(tmp, "shaded.opdraw")
ok(t.save_to(path), "saved")
text = open(path, encoding="utf-8").read()
ok(json.loads(text)["views"][0]["geom"]["mesh"]["n"] > 100 and len(text) < 400000, f"the file carries the triangles as text ({len(text)} bytes)")
t2 = T.DrawingTab(path)
t2.resize(1250, 800)
t2.show()
settle()
t2.canvas.fit()
t.canvas.fit()
settle()
im1, im2 = t.canvas.grab().toImage(), t2.canvas.grab().toImage()
same = sum(1 for x in range(0, im1.width(), 3) for y in range(0, im1.height(), 3) if im1.pixel(x, y) == im2.pixel(x, y)) / ((im1.width() // 3 + 1) * (im1.height() // 3 + 1))
ok(same > 0.97, f"the opened drawing looks the same as the one that was saved, shading and all, with no model rebuilt ({same:.3f})")
t2.close()

# ---------------------------------------------------------------------------------------------------------------------------- the PDF
pdf = os.path.join(tmp, "shaded.pdf")
ok(t.export_pdf(pdf) == pdf and os.path.getsize(pdf) > 0, "exported")
page = fitz.open(pdf)[0]
imgs = page.get_images(full=True)
ok(len(imgs) == 1, f"one picture in the PDF: the surface of the view ({len(imgs)})")
rects = page.get_image_rects(imgs[0][0])
mm = 72.0 / 25.4
v = t.d.views[0]
ox, oy = v["origin"]
H_pt = page.rect.height
want = fitz.Rect(ox * mm, H_pt - (oy + 60.0) * mm, (ox + 100.0) * mm, H_pt - oy * mm)
ok(rects and abs(rects[0].x0 - want.x0) < 2.0 and abs(rects[0].x1 - want.x1) < 2.0 and abs(rects[0].y0 - want.y0) < 2.0 and abs(rects[0].y1 - want.y1) < 2.0,
   f"it is where the view is, at true size ({[round(x, 1) for x in rects[0]] if rects else None} against {[round(x, 1) for x in want]})")
dpi = imgs[0][2] / (rects[0].width / 72.0)
ok(190.0 <= dpi <= 201.0, f"at 200 dpi ({dpi:.0f})")
pm = page.get_pixmap(dpi=72)
px_at = lambda sx, sy: pm.pixel(int(round(sx * mm)), int(round(H_pt - sy * mm)))
bx, by = S((70.0, 40.0))
hx, hy = S((30.0, 30.0))
ok(abs(px_at(bx, by)[0] - PLATE_GREY) <= 4, f"on the page the plate is that grey ({px_at(bx, by)})")
ok(min(px_at(hx, hy)) >= 250, f"and the hole is white ({px_at(hx, hy)})")
draws = page.get_drawings()
ok(any(abs(d_["rect"].width - 100 * mm) < 2.0 and abs(d_["rect"].height - 60 * mm) < 2.0 for d_ in draws), "Shaded With Edges: the outline of the plate is a vector path of 100 x 60 mm over the picture")
t.set_view_style(vid, "shaded")
pdf2 = os.path.join(tmp, "shaded2.pdf")
t.export_pdf(pdf2)
page2 = fitz.open(pdf2)[0]
ok(len(page2.get_images()) == 1 and not any(abs(d_["rect"].width - 100 * mm) < 2.0 and abs(d_["rect"].height - 60 * mm) < 2.0 for d_ in page2.get_drawings()), "Shaded: the picture and no outline")
t.set_view_style(vid, "hlv")
pdf3 = os.path.join(tmp, "lines.pdf")
t.export_pdf(pdf3)
page3 = fitz.open(pdf3)[0]
ok(len(page3.get_images()) == 0, "a drawing of lines only has no picture in it: vector lines only")

t.shutdown()
print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
