"""The look of the Workbench is the look of Sheets ("quiet header"): its pictures come from the program's icon kit (the same drawings as the tabs), the bar above the schematic has the
Workbench chip, the name of the file and flat text buttons, the toolbox has a colour swatch per group and kit icons, a block has a grey bevelled bar with the letter in a chip, a
gutter with row numbers, navy wires behind navy dots.  Checked with pixels (headless), at two zooms, and with the kit switched off (an older core).   python test_wb_look.py"""
import faulthandler
faulthandler.dump_traceback_later(250, exit=True)
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared")]
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QLabel, QToolBar, QToolButton

app = QApplication([])
import icon_kit
import wb_canvas as cv
import wb_icons as ic
import wb_kit as kit
import wb_project as wp
import wb_tab as wt

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def px(img, x, y):
    c = img.pixelColor(int(x), int(y))
    return c.red(), c.green(), c.blue()


def near(a, b, tol=30):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def count(img, box, pred):
    x0, y0, w, h = box
    return sum(1 for x in range(x0, x0 + w) for y in range(y0, y0 + h) if pred(*px(img, x, y)))


T = tempfile.mkdtemp(prefix="opara_wbl_")
tab = wt.WorkbenchTab(None)
tab.resize(1300, 760)
tab.show()
app.processEvents()
view, scene, prj = tab.view, tab.scene, tab.project

# ------------------------------------------------------------------------------------------------------------------------ the pictures come from the icon kit
ok(kit.ready(), "the icon kit has the drawings of the workbench")
every = list(kit.KIND.values()) + list(kit.STATUS.values()) + list(kit.CELL.values())
ok(all(icon_kit.has(k) for k in every), f"every kind of block, cell and status mark has a drawing in the kit ({len(set(every))} drawings)")
ok(set(kit.KIND) >= set(wp.KINDS), f"and every kind of block the workbench has is among them ({sorted(set(wp.KINDS) - set(kit.KIND))})")
ok(set(kit.STATUS) == {wp.OK, wp.INCOMPLETE, wp.REFRESH, wp.UPDATE, wp.FAILED}, "five status marks")
ok(kit.KIND["part"] == "tab_part" and kit.KIND["fea"] == "tab_fea" and kit.KIND["solid"] == "tab_solid" and kit.KIND["beam"] == "tab_beam", "a part and an analysis have the icon of their tab")
ok(kit.cell_key("part", "geometry") == "tab_part" and kit.cell_key("assembly", "geometry") == "assembly" and kit.cell_key("solid", "geometry") == "tab_part"
   and kit.cell_key("fea", "geometry") == "sketch" and kit.cell_key("beam", "geometry") == "sketch", "the Geometry cell shows a part, an assembly or a sketch, as what it holds")
ok(kit.cell_key("beam", "profile") == "wb_profile" and kit.cell_key("study", "setup") == "wb_params" and kit.cell_key("sheets", "document") == "wb_sheets", "and the other cells their own")
ok(not ic.kind_icon("sheets").isNull() and ic.kind_icon("sheets", 18).pixmap(18, 18).toImage().pixelColor(9, 9).alpha() > 0, "a kind of block makes a QIcon")
big = icon_kit.image("wb_ok", 18, 2)
ok(big.width() == 36 and count(big, (0, 0, 36, 36), lambda r, g, b: near((r, g, b), (16, 32, 77), 40)) > 20, "the kit draws with the navy ink of the program")

# ------------------------------------------------------------------------------------------------------------------------ the bar, the strip, the toolbox
bar = tab.findChild(QToolBar, "wbBar")
ok(bar is not None and bar.height() == wt.BAR_H, f"the bar above the schematic is {wt.BAR_H} px high ({bar.height() if bar else None})")
chip = tab.findChild(QLabel, "wbChip")
ok(chip is not None and chip.text() == "Workbench" and "#10204d" in chip.styleSheet() and "border-radius: 9px" in chip.styleSheet(), "it starts with the Workbench chip, navy and round")
ok(tab.file_label.text() == "Untitled project", f"then the name of the file ({tab.file_label.text()!r})")
tab.add_block("part", 100, 100)
app.processEvents()
ok(tab.file_label.text() == "Untitled project *", f"a star when there is something to save ({tab.file_label.text()!r})")
path = os.path.join(T, "My Bracket.opara")
tab.project.write(path)
tab.path = path
tab.update_header()
ok(tab.file_label.text() == "My Bracket.opara", f"the file name once it is saved ({tab.file_label.text()!r})")
btns = [b.text() for b in bar.findChildren(QToolButton)]
ok(all(any(t in b for b in btns) for t in ("New", "Open", "Save", "Refresh Project", "Update Project", "Import", "Fit", "Project Report")), f"flat text buttons ({btns})")
ok(all(a.icon().isNull() for a in tab.acts.values()), "with no pictures on them")
strip = tab.findChild(QLabel, "wbStrip")
head = tab.findChild(QLabel, "wbToolboxHead")
ok(strip is not None and strip.text() == "Project Schematic" and strip.height() == 28, "a strip says Project Schematic")
ok(head is not None and head.text() == "Toolbox" and head.height() == wt.BAR_H, "and the toolbox has its header, as high as the bar")
tb = tab.toolbox
groups = [tb.topLevelItem(i) for i in range(tb.topLevelItemCount())]
want = {"Analysis Systems": (106, 63, 184), "Geometry": (11, 122, 112), "Component Tools": (42, 122, 79), "Design Exploration": (42, 98, 212)}
for g in groups:
    im = g.icon(0).pixmap(18, 18).toImage()
    col = px(im, im.width() // 2, im.height() // 2)
    ok(near(col, want[g.text(0)], 20), f"the group {g.text(0)} has a swatch of its own colour ({col})")
ok(tb.iconSize().width() == 18, "the pictures in the toolbox are 18 px")
it = tb.item_of("thermal")
im = it.icon(0).pixmap(18, 18).toImage()
ok(count(im, (0, 0, im.width(), im.height()), lambda r, g, b: near((r, g, b), (16, 32, 77), 40)) > 10, "and drawn by the kit (navy ink)")
ok(ic.GROUP_COLOR["Geometry"].name() == "#0b7a70" and ic.GROUP_COLOR["Analysis Systems"].name() == "#6a3fb8", "the colours of the groups are the ones of the chips")

# ------------------------------------------------------------------------------------------------------------------------ a block, at 1x and 2x
scene.clearSelection()
tab.add_block("fea", 360, 100)
A, B = list(prj.nodes.values())[:2]
prj.link(A.id, "geometry", B.id, "geometry")
scene.rebuild()
app.processEvents()
for zoom in (1.0, 2.0):
    view.resetTransform()
    view.scale(zoom, zoom)
    view.centerOn(300, 200)
    app.processEvents()
    img = view.grab().toImage()
    img.save(f"/tmp/wb_shots/look_{int(zoom)}x.png") if os.path.isdir("/tmp/wb_shots") else None

    def at(x, y, node=None):
        q = view.mapFromScene(QPointF(x, y))
        return q.x(), q.y()
    a_o = at(A.pos[0], A.pos[1])
    out_dot = at(A.pos[0] + cv.BLOCK_W, A.pos[1] + cv.HEAD_H + cv.NAME_H + cv.CELL_H / 2)
    in_dot = at(B.pos[0], B.pos[1] + cv.HEAD_H + cv.NAME_H + cv.CELL_H / 2)
    label = f"at {zoom:g}x"
    ok(near(px(img, a_o[0] + 120 * zoom, a_o[1] + 10 * zoom), (203, 211, 224), 12), f"the bar is grey {label}")
    ok(near(px(img, out_dot[0], out_dot[1]), (31, 58, 110), 30), f"the output dot is navy in the middle {label} ({px(img, out_dot[0], out_dot[1])})")
    ok(near(px(img, out_dot[0], out_dot[1] - 4.2 * zoom), (255, 255, 255), 30), f"with a white ring {label} ({px(img, out_dot[0], out_dot[1] - 4.2 * zoom)})")
    ok(near(px(img, in_dot[0] - 4.2 * zoom, in_dot[1]), (255, 255, 255), 30), f"the wire does not cross the ring of the input dot {label} ({px(img, in_dot[0] - 4.2 * zoom, in_dot[1])})")
    ok(near(px(img, in_dot[0] - 12 * zoom, in_dot[1]), (31, 58, 110), 30), f"but runs up to it {label}")
    ok(not near(px(img, in_dot[0] - 12 * zoom, in_dot[1] + 4 * zoom), (31, 58, 110), 60), f"with no arrowhead {label}")
    # the picture of the first row of B is drawn at the pixels it has on the screen: its ink lines are as thick as the zoom says
    ic_box = at(B.pos[0] + cv.GUTTER + 10, B.pos[1] + cv.HEAD_H + cv.NAME_H + 6)
    n_ink = count(img, (int(ic_box[0]), int(ic_box[1]), int(18 * zoom), int(18 * zoom)), lambda r, g, b: not near((r, g, b), (255, 255, 255), 14) and not near((r, g, b), (245, 247, 251), 8))
    ok(n_ink >= 12 * zoom * zoom, f"the picture of a cell is there, in colour, {label} ({n_ink} px)")
# at 2x the kit is asked for pictures twice as large (sharp, not blown up)
seen = []
orig = icon_kit.image
icon_kit.image = lambda key, size, ratio=2: (seen.append((key, size, ratio)) or orig(key, size, ratio))
view.resetTransform()
view.scale(2.0, 2.0)
app.processEvents()
view.grab()
icon_kit.image = orig
ok(seen and max(r for _k, _s, r in seen) >= 2, f"at 2x the pictures are made at twice the pixels ({sorted(set(seen))[:3]})")
view.resetTransform()

# ------------------------------------------------------------------------------------------------------------------------ a wire being drawn, a selected wire
li = scene.link_items[prj.links[0].key()]
li.setSelected(True)
app.processEvents()
img = view.grab().toImage()
mid = li.pts[0]
q = view.mapFromScene(QPointF((li.pts[0].x() + li.pts[1].x()) / 2, li.pts[0].y()))
ok(near(px(img, q.x(), q.y()), (47, 111, 237), 40), f"a selected wire is blue ({px(img, q.x(), q.y())})")
li.setSelected(False)

# ------------------------------------------------------------------------------------------------------------------------ an older core, with no icon kit
kit._state["ok"] = False
try:
    ok(not ic.kind_icon("part").isNull(), "with no kit a kind of block still has its old picture")
    im = QImage(60, 60, QImage.Format.Format_ARGB32)
    im.fill(QColor("#ffffff"))
    p = QPainter(im)
    ic.paint_status(p, "ok", QPointF(30, 30), 8.0)
    ic.paint_cell(p, "setup", QRectF(2, 2, 18, 18), "solid")
    ic.paint_kind(p, "beam", QRectF(36, 2, 22, 22))
    p.end()
    ok(count(im, (0, 0, 60, 60), lambda r, g, b: (r, g, b) != (255, 255, 255)) > 200, "and the status marks, the cells and the blocks are drawn")
    scene.refresh()
    ok(not view.grab().toImage().isNull(), "a schematic can be drawn")
finally:
    kit._state["ok"] = None
ok(kit.ready(), "(the kit is back)")

shutil.rmtree(T, ignore_errors=True)
shutil.rmtree(UDIR, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f in FAILS:
    print("  -", f)
sys.stdout.flush()
os._exit(1 if FAILS else 0)
