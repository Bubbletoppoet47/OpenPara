"""Sheets (dev_addons/sheets): images - a screenshot pasted with Ctrl+V lands at the selected cell, Insert image from a PNG / JPEG file, drag to move and the corner to
resize (one undo step each), the image panel (width, height, keep proportions, scale, original size), copy / duplicate / export / delete, the Images tab,
Paste special > Picture, saving in the .opsheet file and opening it again, copied sheets, and Excel files in and out."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import QEvent, QMimeData, QPointF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication([])
import sh_book as B
import sh_deps
import sh_picture as P
import sh_prefs
import sh_tab as TAB
import sh_xlsx

T = tempfile.mkdtemp(prefix="opara_si_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
answers = {"open": "", "save": ""}
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (answers["open"], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (answers["save"], ""))
LEFT, NO = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier


def fresh():
    t = TAB.make_tab()
    t.resize(1300, 800)
    t.show()
    app.processEvents()
    return t


def shot(w, h, color="#3a7bd5", ratio=1.0, split=False):
    """A picture to paste: `color` all over (and in `split` mode left half red, right half blue, so a resize can be told from a crop)."""
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    if split:
        for y in range(h):
            for x in range(w // 2):
                img.setPixelColor(x, y, QColor("#d03030"))
    img.setDevicePixelRatio(ratio)
    return img


def to_clipboard(img, text=None):
    md = QMimeData()
    md.setImageData(img)
    if text is not None:
        md.setText(text)
    QGuiApplication.clipboard().setMimeData(md)


def pics(t, sheet=None):
    return t.wb.get_sheet(sheet or t.grid.sheet).pictures


def send(f, kind, local, glob, buttons=Qt.MouseButton.LeftButton):
    button = LEFT if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease) else Qt.MouseButton.NoButton
    app.sendEvent(f, QMouseEvent(kind, QPointF(local), QPointF(glob), button, buttons, NO))


def drag_frame(f, local, dx, dy, steps=3):
    """Press at `local` (a point of the frame), drag by (dx, dy) in steps, let go: real mouse events to the frame (the frame moves while it is dragged, so the
    points are worked out on the screen, not on the frame)."""
    g0 = f.mapToGlobal(QPointF(local[0], local[1]).toPoint())
    send(f, QEvent.Type.MouseButtonPress, QPointF(local[0], local[1]), QPointF(g0))
    for i in range(1, steps + 1):
        p = QPointF(g0.x() + dx * i / steps, g0.y() + dy * i / steps)
        send(f, QEvent.Type.MouseMove, QPointF(f.mapFromGlobal(p.toPoint())), p)
    pe = QPointF(g0.x() + dx, g0.y() + dy)
    send(f, QEvent.Type.MouseButtonRelease, QPointF(f.mapFromGlobal(pe.toPoint())), pe, Qt.MouseButton.NoButton)


# ======================================================================================================== paste
t = fresh()
g, wb = t.grid, t.wb
S = g.sheet
assert not pics(t) and not t.act["pic_edit"].isEnabled(), "an empty sheet has no image to edit"
assert [t.ribbon.tabText(i) for i in range(t.ribbon.count())] == ["Home", "Data", "Charts", "Images", "Engineering", "View"], "the Images tab sits next to Charts"
assert t.act["pic_new"].isEnabled(), "Insert image is always there"

g.select(3, 2)
to_clipboard(shot(300, 160))
g.paste()                                                                       # Ctrl+V on a screenshot
p = pics(t)
assert len(p) == 1, p
pic = p[0]
assert pic["pos"] == [g.cols.pos(2), g.rows.pos(3)], "it lands at the selected cell"
assert pic["size"] == [300.0, 160.0] and pic["orig"] == [300.0, 160.0], pic
assert g.sel_picture == pic["id"] and g.pframes[pic["id"]].selected, "it is picked, so it can be dragged at once"
assert wb.undo_label() == "Insert picture"
assert t.act["pic_edit"].isEnabled() and t.act["pic_copy"].isEnabled() and t.act["pic_export"].isEnabled() and t.act["pic_del"].isEnabled()
assert wb.version != t.saved_version and t.is_dirty(), "a pasted picture makes the file different"

wb.undo()
assert not pics(t) and not g.pframes, "undo takes it off again"
wb.redo()
assert len(pics(t)) == 1 and pics(t)[0]["image"] == pic["image"] and len(g.pframes) == 1, "redo puts it back"

# a big screenshot is made to fit what can be seen; its original size stays what it was
g.select(1, 1)
to_clipboard(shot(3000, 1800))
g.paste()
big = pics(t)[-1]
vw, vh = g.viewport().width() - g.hw, g.viewport().height() - g.hh
assert big["orig"] == [3000.0, 1800.0], big
assert big["size"][0] <= vw and big["size"][1] <= vh, ("fits", big["size"], vw, vh)
assert abs(big["size"][0] / big["size"][1] - 3000 / 1800) < 0.01, "proportions kept"
# a screenshot of a screen with 2 pixels per point is shown at the size it had on that screen
to_clipboard(shot(400, 200, ratio=2.0))
g.paste()
hd = pics(t)[-1]
assert hd["size"] == [200.0, 100.0] and hd["orig"] == [200.0, 100.0], hd
assert len({q["id"] for q in pics(t)}) == 3, "every picture has its own id"
assert len(wb.images) == 3
to_clipboard(shot(300, 160))                                                    # the same bytes again: stored once
n_before = len(wb.images)
g.paste()
assert len(wb.images) == n_before and len(pics(t)) == 4, "the same picture is kept once"
for q in list(pics(t)):
    g.delete_picture(q["id"])
assert not pics(t)
wb.undo()
assert len(pics(t)) == 1, "one undo, one picture back"

# nothing on the clipboard that is a picture
for q in list(pics(t)):
    g.delete_picture(q["id"])
md = QMimeData()
md.setText("hello")
QGuiApplication.clipboard().setMimeData(md)
g.select(1, 1)
g.paste()
assert not pics(t) and wb.display(S, 1, 1) == "hello", "text on the clipboard is still pasted as text"

# text and an image together (cells copied in Excel put both): the cells win; Paste special > Picture takes the image
to_clipboard(shot(120, 60), text="7\t8")
g.select(5, 1)
g.paste()
assert not pics(t) and wb.display(S, 5, 1) == "7" and wb.display(S, 5, 2) == "8", "cells first"
g.paste("picture")
assert len(pics(t)) == 1 and pics(t)[0]["size"] == [120.0, 60.0], "Paste special > Picture"
assert [rb.key for rb in __import__("sh_dialogs").PasteSpecialDialog().opts][-1] == "picture"
for q in list(pics(t)):
    g.delete_picture(q["id"])
g.paste_picture(QMimeData())                                                    # (an empty clipboard: said, not an error)
assert not pics(t)

# cells copied inside Sheets paste as cells, not as a picture
wb.set_input(S, 10, 1, "42")
g.select(10, 1)
g.copy()
g.select(11, 1)
g.paste()
assert wb.display(S, 11, 1) == "42" and not pics(t)

# ======================================================================================================== move, resize, undo
g.select(2, 2)
to_clipboard(shot(300, 200, split=True))
g.paste()
pid = pics(t)[0]["id"]
f = g.pframes[pid]
x0, y0 = pics(t)[0]["pos"]
steps_before = len(wb._undo)
drag_frame(f, (100, 80), 50, 30)                                                # drag the body
q = pics(t)[0]
assert q["pos"] == [x0 + 50, y0 + 30] and q["size"] == [300.0, 200.0], q
assert len(wb._undo) == steps_before + 1 and wb.undo_label() == "Move picture", "a drag is one undo step"
assert f.geometry().x() == int(g.hw + q["pos"][0] - g.x0), "the frame follows"
wb.undo()
assert pics(t)[0]["pos"] == [x0, y0], "undo puts it back"
wb.redo()
assert pics(t)[0]["pos"] == [x0 + 50, y0 + 30]
f = g.pframes[pid]
steps_before = len(wb._undo)
drag_frame(f, (f.width() - 6, f.height() - 6), 90, 20)                          # drag the corner: proportions kept (the bigger pull wins)
q = pics(t)[0]
assert abs(q["size"][0] / q["size"][1] - 1.5) < 0.02 and q["size"][0] > 300, q["size"]
assert wb.undo_label() == "Resize picture" and len(wb._undo) == steps_before + 1
wb.undo()
assert pics(t)[0]["size"] == [300.0, 200.0]
wb.redo()
q = pics(t)[0]
q["keep"] = False
f = g.pframes[pid]
w0, h0 = q["size"]
drag_frame(f, (f.width() - 6, f.height() - 6), 40, -30)                         # not kept: free
assert pics(t)[0]["size"] == [w0 + 40, h0 - 30], pics(t)[0]["size"]
pics(t)[0]["keep"] = True
# a click that moves nothing records nothing
steps_before = len(wb._undo)
drag_frame(g.pframes[pid], (20, 20), 0, 0)
assert len(wb._undo) == steps_before, "no move, no undo step"
# it cannot be dragged off the sheet's top-left
drag_frame(g.pframes[pid], (20, 20), -5000, -5000)
assert pics(t)[0]["pos"] == [0.0, 0.0]

# ======================================================================================================== the panel
t.picture_edit()                                                                # (the Edit image button)
assert t.pic_panel_open() and not (t.panel is not None and not t.panel.isHidden())
pp = t.pic_panel
pic = pics(t)[0]
pic["size"] = [300.0, 200.0]
pp.load()
assert (pp.w.value(), pp.h.value(), pp.scale.value()) == (300, 200, 100) and pp.keep.isChecked()
assert "300 × 200" in pp.orig_lbl.text()
steps_before = len(wb._undo)
pp.w.setValue(150)                                                              # width with proportions kept: the height follows
assert pics(t)[0]["size"] == [150.0, 100.0] and pp.h.value() == 100 and pp.scale.value() == 50, pics(t)[0]
assert wb.undo_label() == "Resize picture" and len(wb._undo) == steps_before + 1
assert g.pframes[pid].width() == 150 and g.pframes[pid].height() == 100, "the picture on the sheet follows the panel"
pp.h.setValue(200)
assert pics(t)[0]["size"] == [300.0, 200.0]
pp.scale.setValue(25)
assert pics(t)[0]["size"] == [75.0, 50.0], pics(t)[0]["size"]
pp.keep.setChecked(False)
pp.w.setValue(400)                                                              # not kept: only the width changes
assert pics(t)[0]["size"] == [400.0, 50.0] and not pics(t)[0]["keep"]
pp.keep.setChecked(True)
pp.reset.click()
assert pics(t)[0]["size"] == [300.0, 200.0], "Original size"
wb.undo()
assert pics(t)[0]["size"] == [400.0, 50.0], "undo steps back through the panel's changes"
wb.undo()
wb.undo()
assert pics(t)[0]["size"] == [75.0, 50.0] and pp.w.value() == 75 and pp.h.value() == 50, "the panel follows an undo"
pics(t)[0]["keep"] = True
# the panel follows the picture that is picked and closes when its picture goes
g.select(2, 2)
to_clipboard(shot(50, 50, "#20a040"))
g.paste()
second = pics(t)[-1]["id"]
assert pp.picture["id"] == second, "the panel follows the picture that is picked"
g.pick_picture(pid)
assert pp.picture["id"] == pid
g.delete_picture(pid)
g.delete_picture(second)
assert not t.pic_panel_open(), "the panel closes when its picture is gone"

# a chart panel and the image panel share the place: one at a time
to_clipboard(shot(80, 40))
g.paste()
t.picture_edit()
assert t.pic_panel_open()
for j, h in enumerate(["x", "y"], 1):
    wb.set_input(S, 20, j, h)
for i in range(1, 6):
    wb.set_input(S, 20 + i, 1, str(i))
    wb.set_input(S, 20 + i, 2, f"=A{20 + i}^2")
if sh_deps.matplotlib() is not None:
    g.select(20, 1, 25, 2)
    t.chart_new()
    assert t.panel_open() and not t.pic_panel_open(), "opening a chart closes the image panel"
    t.picture_edit()
    assert t.pic_panel_open() and not t.panel_open(), "and the other way round"
    for c in list(wb.get_sheet(S).charts):
        g.delete_chart(c["id"])
t.pic_panel.close_panel()

# ======================================================================================================== right-click menu, copy, cut, duplicate, delete, keys
pid = pics(t)[0]["id"]
pics(t)[0]["size"] = [64.0, 32.0]
g.pick_picture(pid)
g.copy()                                                                        # Ctrl+C on a picked picture: the picture goes on the clipboard
cb = QGuiApplication.clipboard().mimeData()
assert cb.hasImage() and not cb.hasText()
g.select(8, 4)
g.paste()
assert len(pics(t)) == 2 and pics(t)[1]["pos"] == [g.cols.pos(4), g.rows.pos(8)]
assert pics(t)[1]["image"] == pics(t)[0]["image"], "the same bytes: kept once"
assert pics(t)[1]["size"] == [64.0, 32.0], "pasted inside Sheets it keeps the size it had on the sheet"
g.pick_picture(pics(t)[1]["id"])
g.copy(cut=True)
assert len(pics(t)) == 1, "Ctrl+X takes it off"
g.paste()
assert len(pics(t)) == 2
g.pick_picture(pics(t)[1]["id"])
n = len(pics(t))
t.picture_copy()                                                                # Copy image = a duplicate, a little down and right
assert len(pics(t)) == n + 1
d = pics(t)[-1]
src = pics(t)[1]
assert d["pos"] == [src["pos"][0] + 24, src["pos"][1] + 24] and d["size"] == src["size"] and d["image"] == src["image"] and d["id"] != src["id"]
assert g.sel_picture == d["id"] and wb.undo_label() == "Copy picture"
QTest.keyClick(g, Qt.Key.Key_Delete)                                            # Delete on a picked picture deletes the picture, not the cells
assert len(pics(t)) == n and wb.display(S, 11, 1) == "42"
g.select(11, 1)
assert g.sel_picture is None, "clicking a cell lets go of the picture"
QTest.keyClick(g, Qt.Key.Key_Delete)
assert wb.display(S, 11, 1) == "", "and Delete clears the cells again"
t.picture_delete()
assert len(pics(t)) == n - 1

# ======================================================================================================== Insert image (a file)
png = os.path.join(T, "photo.png")
shot(640, 480, "#c08030").save(png)
jpg = os.path.join(T, "photo.jpg")
shot(320, 240, "#30a0c0").save(jpg, "JPEG", 90)
bad = os.path.join(T, "notes.png")
with open(bad, "wb") as fh:
    fh.write(b"this is not a picture")
t2 = fresh()
g2, wb2 = t2.grid, t2.wb
g2.select(4, 3)
answers["open"] = png
t2.picture_new()
p2 = pics(t2)[0]
assert p2["name"] == "photo" and p2["orig"] == [640.0, 480.0] and p2["pos"] == [g2.cols.pos(3), g2.rows.pos(4)], p2
assert wb2.images[p2["image"]] == open(png, "rb").read(), "a PNG file is kept as it is"
answers["open"] = jpg
g2.select(20, 1)
t2.picture_new()
p3 = pics(t2)[1]
assert P.kind_of(wb2.images[p3["image"]]) == "jpeg" and wb2.images[p3["image"]] == open(jpg, "rb").read(), "a JPEG file is kept as it is (it does not grow)"
n = len(pics(t2))
answers["open"] = bad
t2.picture_new()
assert len(pics(t2)) == n and "not a picture" in t2.status.text().lower(), t2.status.text()
answers["open"] = os.path.join(T, "missing.png")
t2.picture_new()
assert len(pics(t2)) == n
answers["open"] = ""                                                            # the dialog was cancelled
t2.picture_new()
assert len(pics(t2)) == n
# a very big picture is made smaller when it comes in
huge = os.path.join(T, "huge.png")
shot(5000, 2500).save(huge)
data, image, _name = P.read_file(huge)
assert max(image.width(), image.height()) == P.MAX_SIDE, (image.width(), image.height())
# a BMP is stored as a PNG
bmp = os.path.join(T, "pic.bmp")
shot(40, 30).save(bmp)
assert P.kind_of(P.read_file(bmp)[0]) == "png"

# ======================================================================================================== Export image
ex = os.path.join(T, "out.png")
answers["save"] = ex
t2.picture_export(pics(t2)[0]["id"])
assert open(ex, "rb").read() == open(png, "rb").read(), "exporting a PNG gives the same bytes"
ex2 = os.path.join(T, "out.jpg")
answers["save"] = ex2
t2.picture_export(pics(t2)[0]["id"])                                            # another kind than it is stored as: converted
assert P.kind_of(open(ex2, "rb").read()) == "jpeg"
ex3 = os.path.join(T, "out2")                                                   # no ending: the picture's own
answers["save"] = ex3
t2.picture_export(pics(t2)[0]["id"])
assert os.path.isfile(ex3 + ".png")

# ======================================================================================================== the file: save, open, sheets
f1 = os.path.join(T, "book.opsheet")
wb2.set_input(g2.sheet, 1, 1, "hello")
pics(t2)[0]["size"] = [200.0, 150.0]
wb2.add_sheet("Second")
t2.show_sheet(g2.sheet)
answers["save"] = f1
t2.save()
assert os.path.isfile(f1)
size = os.path.getsize(f1)
assert 1000 < size < 1_500_000, size
t3 = fresh()
t3.open_path(f1)
q3 = pics(t3, t3.grid.sheet)
assert len(q3) == 2 and q3[0]["size"] == [200.0, 150.0] and q3[0]["orig"] == [640.0, 480.0] and q3[0]["name"] == "photo", q3
assert t3.wb.images[q3[0]["image"]] == open(png, "rb").read(), "the bytes come back as they went"
assert len(t3.grid.pframes) == 2, "and the pictures are on the sheet"
import json
d0 = json.loads(open(f1, encoding="utf-8").read())
assert set(d0["images"]) == {p["image"] for s in d0["sheets"] for p in s["pictures"]}, "the file carries each picture's bytes once, and only the ones in use"
t3.grid.pick_picture(q3[0]["id"])
t3.picture_edit()
assert t3.pic_panel_open()
t3.picture_copy()
n3 = len(pics(t3, t3.grid.sheet))
# a copy of the sheet carries the pictures (the bytes are shared)
dup = t3.wb.duplicate_sheet(t3.grid.sheet)
assert len(dup.pictures) == n3 and {p["image"] for p in dup.pictures} == {p["image"] for p in pics(t3, t3.grid.sheet)}
n_images = len(t3.wb.images)
t3.wb.undo()
assert len(t3.wb.images) == n_images, "the bytes stay while a step might still need them"
f2 = os.path.join(T, "book2.opsheet")
answers["save"] = f2
t3.save(True)
t4 = fresh()
t4.open_path(f2)
assert len(pics(t4, t4.grid.sheet)) == n3, "a saved copy has the pictures too"
# a picture that lost its bytes (a damaged file) is dropped, the rest opens
d = json.loads(open(f2, encoding="utf-8").read())
d["images"] = {}
bad2 = os.path.join(T, "damaged.opsheet")
open(bad2, "w", encoding="utf-8").write(json.dumps(d))
wb5 = B.Workbook.load(bad2)
assert wb5.sheets[0].pictures == [] and wb5.display(wb5.sheets[0].name, 1, 1) == "hello"
# a picture with nonsense numbers is made sane
d2 = json.loads(open(f2, encoding="utf-8").read())
d2["sheets"][0]["pictures"][0]["size"] = [-5, "x"]
wb6 = B.Workbook.from_json(d2)
assert len(wb6.sheets[0].pictures) == n3 - 1, "unreadable numbers: that picture is dropped, not the file"

# ======================================================================================================== Excel
op = sh_deps.openpyxl()
if op is None:
    print("SKIP the Excel part of test_sheets_images: openpyxl is not installed here")
else:
    try:
        import PIL  # noqa: F401
        have_pil = True
    except ImportError:
        have_pil = False
    if not have_pil:
        print("SKIP the Excel part of test_sheets_images: Pillow is not installed here")
    else:
        wb7 = B.Workbook()
        s7 = wb7.sheets[0].name
        wb7.set_input(s7, 1, 1, "x")
        wb7.sheets[0].col_w[2] = 100
        wb7.sheets[0].row_h[3] = 40
        data = open(png, "rb").read()
        wb7.add_picture(s7, {"id": "pic1", "image": wb7.add_image(data), "pos": [72.0 + 100.0 + 10, 22.0 * 2 + 40.0 + 5], "size": [160.0, 120.0], "orig": [640.0, 480.0],
                             "keep": True, "name": "photo"})
        out = os.path.join(T, "pics.xlsx")
        notes = sh_xlsx.export_xlsx(wb7, out)
        assert not notes, notes
        xl = op.load_workbook(out)
        imgs = xl.active._images
        assert len(imgs) == 1, "the picture is in the Excel file"
        a = imgs[0].anchor
        assert (a._from.col, a._from.row) == (2, 3), ("anchored at the cell it is over (col C, row 4)", a._from.col, a._from.row)
        assert abs(a._from.colOff / sh_xlsx.EMU - 10) < 1 and abs(a._from.rowOff / sh_xlsx.EMU - 5) < 1
        assert abs(a.ext.width / sh_xlsx.EMU - 160) < 1 and abs(a.ext.height / sh_xlsx.EMU - 120) < 1
        wb8, notes8 = sh_xlsx.import_xlsx(out)                                     # ... and back
        assert not any("picture" in n for n in notes8), notes8
        p8 = wb8.sheets[0].pictures
        assert len(p8) == 1, p8
        assert abs(p8[0]["pos"][0] - 182) < 1 and abs(p8[0]["pos"][1] - 89) < 1, p8[0]["pos"]
        assert p8[0]["size"] == [160.0, 120.0] and p8[0]["orig"] == [640.0, 480.0]
        assert wb8.images[p8[0]["image"]] == data
        # a picture Excel cannot hold does not lose the file
        wb7.images[wb7.sheets[0].pictures[0]["image"]] = b"not a picture"
        notes9 = sh_xlsx.export_xlsx(wb7, os.path.join(T, "pics2.xlsx"))
        assert any("was not exported" in n for n in notes9), notes9
        assert os.path.isfile(os.path.join(T, "pics2.xlsx"))

# ======================================================================================================== the picture does not hide the cell behind its header
t10 = fresh()
g10 = t10.grid
g10.select(3, 3)
to_clipboard(shot(200, 100))
g10.paste()
f10 = g10.pframes[pics(t10)[0]["id"]]
g10.horizontalScrollBar().setValue(int(pics(t10)[0]["pos"][0]) + 50)           # scrolled until the left 50 px are under the headers
app.processEvents()
assert f10.mask().boundingRect().left() == 50, f10.mask().boundingRect()
g10.horizontalScrollBar().setValue(int(pics(t10)[0]["pos"][0]) + 500)          # and far enough that it is out of sight
app.processEvents()
assert f10.isHidden(), "a picture that is wholly scrolled out is not drawn over the headers"

print("test_sheets_images OK")
