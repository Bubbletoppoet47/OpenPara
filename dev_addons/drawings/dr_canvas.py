"""dr_canvas.py - the drawing area: a grey canvas with the white sheet on it, the views drawn at their scale, and the mouse: click a view to select it, drag it to move it (a projected view
slides along its axis only), the wheel zooms, the middle button (or Space + drag) pans.

Placing (like SolidWorks): begin_model(vid)       the view `vid` (just made by the document) follows the pointer; a click puts it down, Esc / right click takes it away again
                           begin_projected(pid)  pick a side of the view `pid` by moving the pointer to it: the projected view appears there and slides along its axis; a click puts it
                                                 down (and the next one can be placed from the same parent), Esc / right click ends

Signals:  selection_changed(vid or None)   changed(what)  the document changed ("move", "place", "delete", ...)   hint(text)   coords(x, y)  the pointer on the sheet, mm
          placing(on)  True while a view follows the pointer
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import dr_render as R

CANVAS = QColor("#a9b1bf")
SHEET = QColor("#ffffff")
SHADOW = QColor(0, 0, 0, 55)
PICK_PX = 6.0                                       # how close the pointer must be to a line to pick the view, pixels
MIN_LINE_PX = 1.25


class SheetCanvas(QWidget):
    selection_changed = pyqtSignal(object)
    changed = pyqtSignal(str)
    hint = pyqtSignal(str)
    coords = pyqtSignal(float, float)
    placing = pyqtSignal(bool)

    def __init__(self, drawing, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)
        self.d = drawing
        self.r = R.Renderer(drawing)
        self.k = 1.0                                # pixels per mm
        self.pan = QPointF(20, 20)                  # where the sheet's top-left corner is on the widget
        self.fitted = False
        self.sel = None                             # the selected view id
        self.hover = None
        self.mode = "select"                        # "select" | "model" | "projected"
        self.float_id = None                        # the view that follows the pointer
        self.float_side = None
        self.proj_parent = None
        self.proj_style = None                      # the style of a new projected view (None: its parent's)
        self.drag = None                            # {"vid", "last": (x, y), "moved": bool} while a view is dragged, or {"pan": last QPointF}
        self.space = False
        self.cursor_mm = None                       # the pointer on the sheet

    # ---- coordinates
    def sheet_h(self):
        return self.d.sheet_dims()[1]

    def to_sheet(self, pos):
        return ((pos.x() - self.pan.x()) / self.k, self.sheet_h() - (pos.y() - self.pan.y()) / self.k)

    def to_screen(self, x, y):
        return QPointF(self.pan.x() + self.k * x, self.pan.y() + self.k * (self.sheet_h() - y))

    def fit(self):
        w, h = self.d.sheet_dims()
        m = 28.0
        self.k = max(0.05, min((self.width() - 2 * m) / w, (self.height() - 2 * m) / h))
        self.pan = QPointF((self.width() - self.k * w) / 2.0, (self.height() - self.k * h) / 2.0)
        self.fitted = True
        self.update()

    def zoom(self, factor, at=None):
        at = at if at is not None else QPointF(self.width() / 2.0, self.height() / 2.0)
        x, y = (at.x() - self.pan.x()) / self.k, (at.y() - self.pan.y()) / self.k
        self.k = min(60.0, max(0.05, self.k * factor))
        self.pan = QPointF(at.x() - x * self.k, at.y() - y * self.k)
        self.fitted = False
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.fitted or not self.isVisible():
            self.fit()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self.fitted:
            self.fit()

    # ---- what the document says changed
    def refresh(self, reset=False):
        """The document changed from outside (a panel): paint again; reset=True forgets the converted lines (a model was refreshed, an undo)."""
        if reset:
            self.r.cache.clear()
        if self.sel is not None and not any(v["id"] == self.sel for v in self.d.views):
            self.set_selected(None)
        self.update()

    def set_selected(self, vid, emit=True):
        if vid == self.sel:
            return
        self.sel = vid
        if emit:
            self.selection_changed.emit(vid)
        self.update()

    # ---- placing
    def begin_model(self, vid):
        self.end_place(emit=False)
        self.mode, self.float_id = "model", vid
        self.set_selected(vid)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.placing.emit(True)
        self.hint.emit("Click on the sheet to put the view down.  Esc takes it away.")
        self._follow(self.cursor_mm or (self.d.sheet_dims()[0] / 2.0, self.sheet_h() / 2.0))
        self.update()

    def begin_projected(self, parent_id):
        self.end_place(emit=False)
        self.mode, self.proj_parent, self.float_id, self.float_side = "projected", parent_id, None, None
        self.set_selected(parent_id)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.placing.emit(True)
        self.hint.emit("Move the pointer to the side of the view where the projected view should go, then click.  Esc ends.")
        if self.cursor_mm:
            self._follow(self.cursor_mm)
        self.update()

    def end_place(self, emit=True):
        """Ends placing: a view still following the pointer (a model view not put down, a ghost of a projected view) is taken away."""
        was = self.mode != "select"
        if self.float_id is not None:
            try:
                self.d.remove_view(self.float_id)
            except Exception:                                      # noqa: BLE001
                pass
            if self.sel == self.float_id:
                self.sel = None
                self.selection_changed.emit(None)
        self.mode, self.float_id, self.float_side, self.proj_parent = "select", None, None, None
        self.unsetCursor()
        if was and emit:
            self.placing.emit(False)
            self.hint.emit("")
            self.changed.emit("place_end")
        self.update()

    def _follow(self, pt):
        x, y = pt
        if self.mode == "model" and self.float_id is not None:
            self.d.center_view(self.float_id, x, y)
        elif self.mode == "projected" and self.proj_parent is not None:
            try:
                x0, y0, x1, y1 = self.r.view_box(self.d.view(self.proj_parent))
            except Exception:                                      # noqa: BLE001
                return
            inside = x0 <= x <= x1 and y0 <= y <= y1
            side = None if inside else self.d.side_of(self.proj_parent, (x, y))
            if side != self.float_side and self.float_id is not None:
                self.d.remove_view(self.float_id)
                self.float_id = None
            if side is not None and self.float_id is None:
                v = self.d.add_projected(self.proj_parent, side, (x, y), style=self.proj_style)
                self.float_id = v["id"]
            self.float_side = side
            if self.float_id is not None:
                self.d.center_view(self.float_id, x, y)
        self.update()

    def _drop(self):
        """A click while placing: the view stays where it is."""
        if self.float_id is None:
            return
        vid = self.float_id
        self.float_id, self.float_side = None, None
        if self.mode == "model":
            self.mode = "select"
            self.unsetCursor()
            self.placing.emit(False)
            self.hint.emit("")
        else:
            self.hint.emit("Placed.  Move to another side for another view, or press Esc to finish.")
        self.set_selected(vid)
        self.changed.emit("place")
        self.update()

    # ---- painting
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), CANVAS)
        w, h = self.d.sheet_dims()
        sheet = QRectF(self.pan.x(), self.pan.y(), w * self.k, h * self.k)
        p.fillRect(sheet.translated(4, 5), SHADOW)
        p.fillRect(sheet, SHEET)
        p.setPen(QPen(QColor("#7d8799"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(sheet)
        p.save()
        p.setClipRect(sheet)
        p.translate(self.pan)
        p.scale(self.k, self.k)
        ghost = (self.float_id,) if self.float_id is not None else ()
        self.r.paint(p, min_px=MIN_LINE_PX, selected=(self.sel,) if self.sel and self.sel not in ghost else (), hover=self.hover if not self.drag else None, ghost=ghost)
        p.restore()
        if not self.d.views and self.float_id is None:
            self._empty(p, sheet)
        p.end()

    def _empty(self, p, sheet):
        f = QFont(self.font())
        f.setPointSizeF(11)
        p.setFont(f)
        p.setPen(QColor("#9aa3b2"))
        text = "Nothing on the sheet yet.\nOpen Model View, pick a model and a view, then click here to place it." if self.d.models else \
               "Nothing on the sheet yet.\nAdd a part or an assembly (Models), then place a view of it."
        p.drawText(sheet, Qt.AlignmentFlag.AlignCenter, text)

    # ---- the mouse
    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if dy:
            self.zoom(1.15 ** (dy / 120.0), ev.position())
        ev.accept()

    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        if ev.button() == Qt.MouseButton.MiddleButton or (ev.button() == Qt.MouseButton.LeftButton and self.space):
            self.drag = {"pan": pos}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() == Qt.MouseButton.RightButton:
            if self.mode != "select":
                self.end_place()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self.to_sheet(pos)
        if self.mode != "select":
            self._follow((x, y))
            self._drop()
            return
        vid = self.r.hit_view(x, y, PICK_PX / self.k)
        self.set_selected(vid)
        if vid:
            self.drag = {"vid": vid, "last": (x, y), "moved": False}
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        x, y = self.to_sheet(pos)
        self.cursor_mm = (x, y)
        self.coords.emit(x, y)
        if self.drag and "pan" in self.drag:
            last = self.drag["pan"]
            self.pan = QPointF(self.pan.x() + pos.x() - last.x(), self.pan.y() + pos.y() - last.y())
            self.drag["pan"] = pos
            self.fitted = False
            self.update()
            return
        if self.drag and "vid" in self.drag:
            lx, ly = self.drag["last"]
            if abs(x - lx) > 0 or abs(y - ly) > 0:
                self.d.shift_view(self.drag["vid"], x - lx, y - ly)
                self.drag["last"] = (x, y)
                self.drag["moved"] = True
                self.update()
            return
        if self.mode != "select":
            self._follow((x, y))
            return
        h = self.r.hit_view(x, y, PICK_PX / self.k)
        if h != self.hover:
            self.hover = h
            self.update()

    def mouseReleaseEvent(self, ev):
        if self.drag:
            moved = self.drag.get("moved")
            self.drag = None
            self.unsetCursor()
            if self.mode != "select":
                self.setCursor(Qt.CursorShape.CrossCursor)
            if moved:
                self.changed.emit("move")
            self.update()

    def leaveEvent(self, ev):
        if self.hover is not None:
            self.hover = None
            self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self.space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if ev.key() == Qt.Key.Key_Escape:
            if self.mode != "select":
                self.end_place()
            else:
                self.set_selected(None)
            return
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.mode == "select" and self.sel:
            self.delete_selected()
            return
        if ev.key() == Qt.Key.Key_F and self.mode == "select":
            self.fit()
            return
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self.space = False
            if not self.drag:
                self.unsetCursor()
                if self.mode != "select":
                    self.setCursor(Qt.CursorShape.CrossCursor)
            return
        super().keyReleaseEvent(ev)

    def delete_selected(self):
        if not self.sel:
            return False
        vid = self.sel
        self.sel = None
        self.d.remove_view(vid)
        self.selection_changed.emit(None)
        self.changed.emit("delete")
        self.update()
        return True
