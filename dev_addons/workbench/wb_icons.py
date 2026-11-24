"""wb_icons.py - the little pictures of the workbench: one for every kind of block, one for every kind of cell, and the five status marks (up to date, incomplete, refresh,
update, failed).  They are drawn by the program's icon kit (wb_kit.py), the look of Sheets; a core with no icon kit gets the pictures drawn below with QPainter instead (a 24 x 24
box that is scaled to the rectangle asked for)."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

import wb_kit as kit

NAVY = QColor("#1d3557")
BLUE = QColor("#2b7de9")
TEAL = QColor("#2a9d8f")
ORANGE = QColor("#e76f51")
AMBER = QColor("#f2a900")
GREEN = QColor("#2e9e5b")
RED = QColor("#d62828")
GREY = QColor("#6a7790")
PALE = QColor("#e6efff")
GROUP_COLOR = {"Analysis Systems": QColor("#6a3fb8"), "Geometry": QColor("#0b7a70"), "Component Tools": QColor("#2a7a4f"), "Design Exploration": QColor("#2a62d4")}   # the letter chip, the toolbox swatch
INK = QColor("#10204d")                                      # the ink of the icon kit: text, outlines
HEAD = QColor("#cbd3e0")                                     # the grey of the bar of a block (the body colour of the kit)
EDGE = QColor("#8793ad")
WIRE_NAVY = QColor("#1f3a6e")
SELECT_BLUE = QColor("#2f6fed")


def _pen(c, w=1.5):
    return QPen(QColor(c), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _cube(p, x, y, s, col, fill=True):
    """An isometric cube whose top corner is at (x, y) and whose side is s."""
    h = s * 0.5
    top = [(x, y), (x + s, y + h), (x, y + 2 * h), (x - s, y + h)]
    left = [(x - s, y + h), (x, y + 2 * h), (x, y + 2 * h + s), (x - s, y + h + s)]
    right = [(x + s, y + h), (x, y + 2 * h), (x, y + 2 * h + s), (x + s, y + h + s)]
    p.setPen(_pen(col, 1.2))
    for pts, a in ((top, 70), (left, 150), (right, 230)):
        c = QColor(col)
        c.setAlpha(a if fill else 0)
        p.setBrush(QBrush(c))
        p.drawPolygon(_poly(pts))


def _thermo(p, x, y, col):
    p.setPen(_pen(col, 1.4))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawRoundedRect(QRectF(x - 1.6, y, 3.2, 10), 1.6, 1.6)
    p.setBrush(QBrush(col))
    p.drawEllipse(QPointF(x, y + 11.5), 3.2, 3.2)
    p.drawLine(QPointF(x, y + 3), QPointF(x, y + 11))


def _g_part(p):
    _cube(p, 12, 3.5, 7.5, TEAL)


def _g_assembly(p):
    _cube(p, 8, 4, 5.5, TEAL)
    _cube(p, 16, 9.5, 5.5, NAVY)


def _g_solid(p):
    _cube(p, 12, 3.5, 7.5, BLUE)
    p.setPen(_pen(ORANGE, 1.6))
    p.drawLine(QPointF(4, 21), QPointF(9, 18))
    p.drawLine(QPointF(20, 21), QPointF(15, 18))


def _g_thermal3d(p):
    _cube(p, 9, 4.5, 6.5, BLUE)
    _thermo(p, 19, 5, ORANGE)


def _g_fea(p):
    p.setPen(_pen(BLUE, 1.5))
    p.setBrush(QBrush(QColor(43, 125, 233, 60)))
    p.drawRect(QRectF(3.5, 5.5, 17, 13))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)


def _g_thermal(p):
    p.setPen(_pen(BLUE, 1.5))
    p.setBrush(QBrush(QColor(43, 125, 233, 60)))
    p.drawRect(QRectF(2.5, 7.5, 13, 11))
    _thermo(p, 19, 4, ORANGE)


def _g_cfd(p):
    p.setPen(_pen(BLUE, 1.7))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for dy in (-5, 0, 5):
        path = QPainterPath(QPointF(2.5, 12 + dy))
        path.cubicTo(8, 7 + dy, 13, 17 + dy, 21.5, 12 + dy)
        p.drawPath(path)


def _g_beam(p):
    p.setPen(_pen(NAVY, 2.2))
    p.drawLine(QPointF(3, 10), QPointF(21, 10))
    p.setPen(_pen(NAVY, 1.4))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawPolygon(_poly([(5, 11), (2, 17), (8, 17)]))
    p.drawPolygon(_poly([(19, 11), (16, 17), (22, 17)]))
    p.setPen(_pen(ORANGE, 1.6))
    p.drawLine(QPointF(12, 2), QPointF(12, 8))
    p.drawPolygon(_poly([(12, 9.5), (10.2, 6.5), (13.8, 6.5)]))


def _page(p, col):
    p.setPen(_pen(col, 1.5))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawPolygon(_poly([(5, 3), (15, 3), (19, 7), (19, 21), (5, 21)]))
    p.drawLine(QPointF(15, 3), QPointF(15, 7))
    p.drawLine(QPointF(15, 7), QPointF(19, 7))


def _g_sheets(p):
    p.setPen(_pen(GREEN, 1.4))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawRect(QRectF(3.5, 4.5, 17, 15))
    p.drawLine(QPointF(3.5, 9.5), QPointF(20.5, 9.5))
    p.drawLine(QPointF(3.5, 14.5), QPointF(20.5, 14.5))
    p.drawLine(QPointF(9.5, 4.5), QPointF(9.5, 19.5))
    p.drawLine(QPointF(15, 4.5), QPointF(15, 19.5))


def _g_pdf(p):
    _page(p, RED)
    p.setPen(_pen(RED, 1.3))
    p.drawLine(QPointF(8, 12), QPointF(16, 12))
    p.drawLine(QPointF(8, 15), QPointF(16, 15))
    p.drawLine(QPointF(8, 18), QPointF(13, 18))


def _g_controls(p):
    p.setPen(_pen(NAVY, 1.4))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawRect(QRectF(8, 6.5, 8, 7))
    p.drawLine(QPointF(2, 10), QPointF(8, 10))
    p.drawLine(QPointF(16, 10), QPointF(22, 10))
    p.drawLine(QPointF(19, 10), QPointF(19, 18))
    p.drawLine(QPointF(19, 18), QPointF(5, 18))
    p.drawLine(QPointF(5, 18), QPointF(5, 10.8))


def _g_circuits(p):
    p.setPen(_pen(TEAL, 1.6))
    p.drawPolyline(_poly([(2, 12), (6, 12), (8, 7), (11, 17), (14, 7), (17, 17), (18.5, 12), (22, 12)]))


def _g_visualize(p):
    p.setPen(_pen(NAVY, 1.4))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.setBrush(QBrush(QColor(255, 255, 255, 220)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(9.2, 9), 2.6, 2.2)
    p.setPen(_pen(NAVY, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(4, 4, 16, 16), 200 * 16, 150 * 16)


def _g_motor(p):
    p.setPen(_pen(NAVY, 1.5))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawEllipse(QPointF(11, 12), 7.5, 7.5)
    p.drawLine(QPointF(18.5, 12), QPointF(22, 12))
    f = QFont()
    f.setPixelSize(9)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(3.5, 4.5, 15, 15), int(Qt.AlignmentFlag.AlignCenter), "M")


def _g_trainer(p):
    p.setPen(_pen(NAVY, 1.1))
    cols = [[(5, 7), (5, 12), (5, 17)], [(12, 5), (12, 10), (12, 14), (12, 19)], [(19, 9.5), (19, 14.5)]]
    for a, b in zip(cols, cols[1:]):
        for x0, y0 in a:
            for x1, y1 in b:
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    p.setBrush(QBrush(BLUE))
    for col in cols:
        for x, y in col:
            p.drawEllipse(QPointF(x, y), 1.8, 1.8)


def _g_annotator(p):
    p.setPen(QPen(ORANGE, 1.6, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(4, 7.5, 16, 12))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(ORANGE))
    p.drawRect(QRectF(4, 3.5, 8, 4))


def _g_truss(p):
    p.setPen(_pen(NAVY, 1.5))
    p.drawPolyline(_poly([(3, 18), (12, 6), (21, 18), (3, 18)]))
    p.drawLine(QPointF(12, 6), QPointF(12, 18))
    p.drawLine(QPointF(7.5, 12), QPointF(16.5, 12))


def _g_study(p):
    p.setPen(_pen(GREY, 1.6))
    for y, x in ((7, 8), (12, 15), (17, 10)):
        p.drawLine(QPointF(3, y), QPointF(21, y))
        p.setBrush(QBrush(QColor("#c77d0a")))
        p.drawEllipse(QPointF(x, y), 2.3, 2.3)


def _g_drawing(p):
    p.setPen(_pen(NAVY, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(5, 3.5, 14, 17))
    p.setPen(_pen(GREY, 1.5))
    p.drawRect(QRectF(8, 6.5, 8, 5))
    p.drawRect(QRectF(8, 13.5, 8, 4))


KIND_GLYPH = {"part": _g_part, "assembly": _g_assembly, "solid": _g_solid, "thermal3d": _g_thermal3d, "fea": _g_fea, "thermal": _g_thermal, "cfd": _g_cfd,
              "beam": _g_beam, "sheets": _g_sheets, "pdf": _g_pdf, "controls": _g_controls, "circuits": _g_circuits, "visualize": _g_visualize, "motor": _g_motor,
              "trainer": _g_trainer, "annotator": _g_annotator, "truss": _g_truss, "study": _g_study, "drawing": _g_drawing}


def _g_unknown(p):
    p.setPen(_pen(GREY, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(4, 4, 16, 16))
    f = QFont()
    f.setPixelSize(13)
    p.setFont(f)
    p.drawText(QRectF(4, 4, 16, 16), int(Qt.AlignmentFlag.AlignCenter), "?")


def paint_kind(p, kind, rect):
    """The picture of a kind of block in `rect` (a QRectF)."""
    if kind in kit.KIND and kit.ready() and kit.draw(p, kit.KIND[kind], rect):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.topLeft())
    p.scale(rect.width() / 24.0, rect.height() / 24.0)
    KIND_GLYPH.get(kind, _g_unknown)(p)
    p.restore()


# ---------------------------------------------------------------------------------------------------------------------------- the cells
def _c_geometry(p):
    _cube(p, 12, 4.5, 6.5, TEAL)


def _c_setup(p):
    p.setPen(_pen(NAVY, 1.5))
    for y, x in ((7, 8), (12, 15), (17, 10)):
        p.drawLine(QPointF(4, y), QPointF(20, y))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(x, y), 2.3, 2.3)


def _c_solution(p):
    p.setPen(_pen(NAVY, 1.5))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 3, 3)
    p.setBrush(QBrush(BLUE))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(_poly([(9.5, 7.5), (9.5, 16.5), (16.5, 12)]))


def _c_results(p):
    p.setPen(_pen(NAVY, 1.4))
    p.drawLine(QPointF(4, 20), QPointF(20, 20))
    p.setPen(Qt.PenStyle.NoPen)
    for x, h, c in ((5, 6, BLUE), (10.5, 11, TEAL), (16, 15, ORANGE)):
        p.setBrush(QBrush(c))
        p.drawRect(QRectF(x, 20 - h, 4, h))


def _c_document(p):
    _page(p, NAVY)
    p.setPen(_pen(NAVY, 1.2))
    p.drawLine(QPointF(8, 12), QPointF(16, 12))
    p.drawLine(QPointF(8, 16), QPointF(16, 16))


CELL_GLYPH = {"geometry": _c_geometry, "setup": _c_setup, "solution": _c_solution, "results": _c_results, "document": _c_document}


def paint_cell(p, key, rect, kind=None):
    """The picture of a cell (`key`) of a block of kind `kind` in `rect`."""
    if kit.ready() and kit.draw(p, kit.cell_key(kind, key), rect):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.topLeft())
    p.scale(rect.width() / 24.0, rect.height() / 24.0)
    CELL_GLYPH.get(key, _c_document)(p)
    p.restore()


# ---------------------------------------------------------------------------------------------------------------------------- the status marks
def paint_status(p, status, center, r=8.0):
    """The mark of a cell: green check (up to date), blue ? (incomplete), green circling arrows (refresh), amber lightning bolt (update), red cross (failed)."""
    if kit.ready() and kit.draw(p, kit.STATUS.get(status, "wb_failed"), QRectF(QPointF(center) - QPointF(r * 1.125, r * 1.125), QPointF(center) + QPointF(r * 1.125, r * 1.125))):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QPointF(center)
    u = r / 8.0
    p.translate(c)
    p.scale(u, u)
    white = _pen("#ffffff", 1.9)
    if status == "ok":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(GREEN))
        p.drawEllipse(QPointF(0, 0), 8, 8)
        p.setPen(white)
        p.drawPolyline(_poly([(-3.8, 0.3), (-1.2, 3.2), (4, -3)]))
    elif status == "incomplete":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(BLUE))
        p.drawEllipse(QPointF(0, 0), 8, 8)
        f = QFont()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(-8, -8.5, 16, 16), int(Qt.AlignmentFlag.AlignCenter), "?")
    elif status == "refresh":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(0, 0), 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(GREEN, 2.0))
        p.drawArc(QRectF(-5, -5, 10, 10), 30 * 16, 120 * 16)
        p.drawArc(QRectF(-5, -5, 10, 10), 210 * 16, 120 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(GREEN))
        p.drawPolygon(_poly([(4.9, -3.2), (6.8, 0.6), (2.4, 0.4)]))
        p.drawPolygon(_poly([(-4.9, 3.2), (-6.8, -0.6), (-2.4, -0.4)]))
    elif status == "update":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(0, 0), 8, 8)
        p.setBrush(QBrush(AMBER))
        p.setPen(_pen("#a87000", 0.8))
        p.drawPolygon(_poly([(1.8, -7), (-4.2, 1.2), (-0.6, 1.2), (-2, 7), (4.4, -1.6), (0.6, -1.6)]))
    else:                                                    # failed
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(RED))
        p.drawEllipse(QPointF(0, 0), 8, 8)
        p.setPen(white)
        p.drawLine(QPointF(-3.4, -3.4), QPointF(3.4, 3.4))
        p.drawLine(QPointF(-3.4, 3.4), QPointF(3.4, -3.4))
    p.restore()


def kind_icon(kind, size=22):
    """A QIcon of a kind of block (for the toolbox and the tab strip)."""
    if kind in kit.KIND and kit.ready():
        ic = kit.icon(kit.KIND[kind], size)
        if ic is not None:
            return ic
    img = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_kind(p, kind, QRectF(0, 0, size * 2, size * 2))
    p.end()
    return QIcon(QPixmap.fromImage(img))
