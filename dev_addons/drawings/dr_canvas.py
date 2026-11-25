"""dr_canvas.py - the drawing area: a grey canvas with the white sheet on it, the views drawn at their scale, and the mouse: click a view to select it, drag it to move it (a projected view
slides along its axis only), the wheel zooms, the middle button (or Space + drag) pans.

Placing (like SolidWorks): begin_model(vid)       the view `vid` (just made by the document) follows the pointer; a click puts it down, Esc / right click takes it away again
                           begin_projected(pid)  pick a side of the view `pid` by moving the pointer to it: the projected view appears there and slides along its axis; a click puts it
                                                 down (and the next one can be placed from the same parent), Esc / right click ends

Annotation tools (tool_begin(name): "dim" Smart Dimension, "center_mark", "centerline"):
          dim          click a line, a circle or an arc (a point for a distance between two points); a second click on another point / line / circle makes a distance or an angle;
                       the dimension follows the pointer until a click puts it down.  Esc / right click: takes away what is half done, then ends the tool
          center_mark  click a circle or an arc (or its centre)
          centerline   click two parallel lines
          A click on a dimension / mark with no tool selects it (blue); a dimension can be dragged to put it somewhere else; Delete removes it.

Signals:  selection_changed(vid or None)   changed(what)  the document changed ("move", "place", "delete", "dim", "mark", "annot_move", "annot_delete" ...)   hint(text)
          coords(x, y)  the pointer on the sheet, mm   placing(on)  True while a view follows the pointer   annot_selected(id or None)   tool_changed(name or None)
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import dr_annot as A
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
    annot_selected = pyqtSignal(object)
    tool_changed = pyqtSignal(object)

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
        self.tool = None                            # an annotation tool: "dim" | "center_mark" | "centerline"
        self.picks = []                             # what the tool has picked so far: [(view id, ref)]
        self.float_annot = None                     # the dimension that follows the pointer
        self.hover_pick = None                      # (view id, ref) under the pointer, for the tool
        self.sel_annot = None                       # the selected dimension / mark
        self._last_drag = None
        self.hover_annot = None

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
        if self.sel_annot is not None and not any(a.get("id") == self.sel_annot for a in self.d.dims + self.d.marks):
            self.set_selected_annot(None)
        if self.float_annot is not None and not any(a.get("id") == self.float_annot for a in self.d.dims):
            self.float_annot = None
        self.picks = [pk for pk in self.picks if any(v["id"] == pk[0] for v in self.d.views)]
        self.update()

    def set_selected(self, vid, emit=True):
        if vid is not None and self.sel_annot is not None:
            self.set_selected_annot(None, emit)
        if vid == self.sel:
            return
        self.sel = vid
        if emit:
            self.selection_changed.emit(vid)
        self.update()

    def set_selected_annot(self, aid, emit=True):
        if aid is not None and self.sel is not None:
            self.sel = None
            if emit:
                self.selection_changed.emit(None)
        if aid == self.sel_annot:
            return
        self.sel_annot = aid
        if emit:
            self.annot_selected.emit(aid)
        self.update()

    # ---- placing
    def begin_model(self, vid):
        self.tool_end(emit=False)
        self.end_place(emit=False)
        self.mode, self.float_id = "model", vid
        self.set_selected(vid)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.placing.emit(True)
        self.hint.emit("Click on the sheet to put the view down.  Esc takes it away.")
        self._follow(self.cursor_mm or (self.d.sheet_dims()[0] / 2.0, self.sheet_h() / 2.0))
        self.update()

    def begin_projected(self, parent_id):
        self.tool_end(emit=False)
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

    # ---- the annotation tools
    TOOL_HINT = {"dim": "Click a line, a circle or an arc to dimension it.  For a distance or an angle click two things.  Then click where the dimension goes.  Esc ends.",
                 "center_mark": "Click a circle or an arc to put a center mark on it.  Esc ends.",
                 "centerline": "Click two parallel lines to put a centerline between them.  Esc ends."}

    def tool_begin(self, name):
        if name not in self.TOOL_HINT:
            return False
        self.end_place(emit=False)
        self.tool_end(emit=False)
        self.set_selected(None)
        self.set_selected_annot(None)
        self.tool, self.picks, self.hover_pick = name, [], None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.tool_changed.emit(name)
        self.hint.emit(self.TOOL_HINT[name])
        self.update()
        return True

    def tool_end(self, emit=True):
        """Ends the tool; a dimension that is still following the pointer is taken away."""
        if self.tool is None:
            return
        self._drop_float()
        self.tool, self.picks, self.hover_pick = None, [], None
        self.unsetCursor()
        if emit:
            self.tool_changed.emit(None)
            self.hint.emit("")
        self.update()

    def _drop_float(self):
        if self.float_annot is not None:
            try:
                self.d.remove_annot(self.float_annot)
            except Exception:                                      # noqa: BLE001
                pass
            self.float_annot = None

    def tool_cancel(self):
        """Esc: what is half done goes first (the dimension that follows the pointer, the first pick); then the tool ends."""
        if self.float_annot is not None or self.picks:
            self._drop_float()
            self.picks = []
            self.hint.emit(self.TOOL_HINT.get(self.tool, ""))
            self.update()
            return
        self.tool_end()

    def pick_at(self, x, y):
        """What the tool would take at a point of the sheet: (view id, ref) in the view's own frame, or None."""
        tol = PICK_PX / self.k
        vid = self.r.hit_view(x, y, tol)
        if vid is None:
            return None
        v = self.d.view(vid)
        s, (ox, oy) = v["scale"], v["origin"]
        pr = self.d.projection(v)
        q = ((x - ox) / s, (y - oy) / s)
        t = tol / s
        if self.tool == "dim":
            ref = A.pick(pr, q, t)
        elif self.tool == "center_mark":
            ref = A.pick(pr, q, t)
            if ref is not None and ref["k"] == "pt":                 # the centre of a circle or an arc counts
                ref = next((A.ref_of(e) for e in pr.vis if e["t"] in ("circle", "arc") and abs(e["c"][0] - ref["p"][0]) < 1e-6 and abs(e["c"][1] - ref["p"][1]) < 1e-6), None)
            if ref is not None and ref["k"] not in ("circle", "arc"):
                ref = None
        else:
            ref = A.pick(pr, q, t, points=False)
            if ref is not None and ref["k"] != "line":
                ref = None
        return (vid, ref) if ref is not None else None

    def _on_number(self, a, x, y):
        """True when a click at (x, y) is on the number of the dimension (not on its lines): dragging it then slides the number along its line."""
        try:
            shp = self.d.dim_shape(a)
        except Exception:                                          # noqa: BLE001
            return False
        at = shp.get("at")
        return at is not None and math.hypot(x - at[0], y - at[1]) <= A.TEXT_H * 1.2

    def _tool_press(self, x, y):
        hit = self.pick_at(x, y)
        if self.tool == "center_mark":
            if hit is None:
                self.hint.emit("That is not a circle or an arc.  Click one.")
                return
            self._add_mark(hit[0], [hit[1]])
        elif self.tool == "centerline":
            if hit is None:
                self.hint.emit("That is not a line.  Click a line.")
                return
            if self.picks and (self.picks[0][0] != hit[0]):
                self.picks = []
            if self.picks and A.same_ref(self.picks[0][1], hit[1]):
                return
            self.picks.append(hit)
            if len(self.picks) == 1:
                self.hint.emit("Click the second line, parallel to the first.")
                self.update()
                return
            vid, refs = self.picks[0][0], [pk[1] for pk in self.picks]
            if A.mark_kind_for(refs) is None:
                self.picks = [hit]
                self.hint.emit("Those two lines are not parallel.  Click another line, or start again from this one.")
                self.update()
                return
            self.picks = []
            self._add_mark(vid, refs)
        else:
            self._dim_press(hit, x, y)

    def _add_mark(self, vid, refs):
        try:
            m = self.d.add_mark(vid, refs)
        except Exception as ex:                                    # noqa: BLE001 (the document's own message)
            self.hint.emit(str(ex))
            return
        self.hint.emit(("Center mark" if m["type"] == "center_mark" else "Centerline") + " added.  " + self.TOOL_HINT[self.tool])
        self.changed.emit("mark")
        self.update()

    def _dim_press(self, hit, x, y):
        refs = [pk[1] for pk in self.picks]
        if self.float_annot is not None:
            extend = hit is not None and len(self.picks) == 1 and A.more_picks(refs) and hit[0] == self.picks[0][0] and not A.same_ref(refs[0], hit[1])
            if extend and A.kind_for(refs + [hit[1]]) is not None:
                self._drop_float()
                self.picks.append(hit)
                self._start_float(x, y)
                return
            self.d.place_annot(self.float_annot, (x, y))
            self.float_annot = None
            self.picks = []
            self.hint.emit("Dimension added.  " + self.TOOL_HINT["dim"])
            self.changed.emit("dim")
            self.update()
            return
        if hit is None:
            self.hint.emit("Nothing to dimension there.  Click a line, a circle, an arc or a corner.")
            return
        if self.picks and hit[0] != self.picks[0][0]:
            self.picks = []                                        # the first pick was on another view: start again from this one
        if self.picks and A.same_ref(self.picks[0][1], hit[1]):
            return
        self.picks.append(hit)
        self._start_float(x, y)

    def _start_float(self, x, y):
        """The picks make a dimension (or not yet): it follows the pointer."""
        refs = [pk[1] for pk in self.picks]
        if A.kind_for(refs) is None:
            if len(refs) >= 2:
                self.picks = [self.picks[-1]]
                self.hint.emit("Those two do not make a dimension.  Click another point, line or circle.")
            else:
                self.hint.emit("Click a second point, line or circle to measure to.")
            self.update()
            return
        try:
            dim = self.d.add_dim(self.picks[0][0], refs)
        except Exception as ex:                                    # noqa: BLE001
            self.hint.emit(str(ex))
            self.picks = []
            return
        self.float_annot = dim["id"]
        self.d.place_annot(dim["id"], (x, y))
        self.hint.emit("Click where the dimension goes." + ("  Or click another thing to measure to it." if A.more_picks(refs) else ""))
        self.update()

    def _tool_move(self, x, y):
        if self.float_annot is not None:
            self.d.place_annot(self.float_annot, (x, y))
            self.hover_pick = None
        else:
            hit = self.pick_at(x, y)
            self.hover_pick = hit
        self.update()

    def _paint_tool(self, p):
        if not self.tool:
            return
        floor = MIN_LINE_PX / self.k
        for vid, ref in self.picks:
            self.r.paint_ref(p, vid, ref, R.SELECT, 0.9, floor)
        if self.hover_pick is not None and not any(vid == self.hover_pick[0] and A.same_ref(ref, self.hover_pick[1]) for vid, ref in self.picks):
            self.r.paint_ref(p, self.hover_pick[0], self.hover_pick[1], R.HOVER, 0.9, floor)

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
        self.r.paint(p, min_px=MIN_LINE_PX, selected=(self.sel,) if self.sel and self.sel not in ghost else (), hover=self.hover if not self.drag else None, ghost=ghost,
                     sel_annot=self.sel_annot, hover_annot=self.hover_annot if not self.drag else None, float_annot=self.float_annot)
        self._paint_tool(p)
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
            if self.tool:
                self.tool_cancel()
            elif self.mode != "select":
                self.end_place()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self.to_sheet(pos)
        if self.tool:
            self._tool_press(x, y)
            return
        if self.mode != "select":
            self._follow((x, y))
            self._drop()
            return
        aid = self.r.hit_annot(x, y, PICK_PX / self.k)
        if aid is not None:
            self.set_selected_annot(aid)
            a = next((a for a in self.d.dims if a["id"] == aid), None)
            if a is not None:
                self.drag = {"aid": aid, "moved": False, "text": self._on_number(a, x, y)}
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        self.set_selected_annot(None)
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
        if self.drag and "aid" in self.drag:
            try:
                a = self.d.annot(self.drag["aid"])
                keep = {k: a[k] for k in ("t", "dist", "side", "mode") if k in a}
                self.d.place_annot(a["id"], (x, y))
                if a["type"] == "linear":                          # the number slides along its line, or the line moves: not both
                    for k in (("dist", "side", "mode") if self.drag["text"] else ("t",)):
                        a[k] = keep[k]
                self.drag["moved"] = True
            except Exception:                                      # noqa: BLE001
                pass
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
        if self.tool:
            self._tool_move(x, y)
            return
        if self.mode != "select":
            self._follow((x, y))
            return
        ha = self.r.hit_annot(x, y, PICK_PX / self.k)
        if ha != self.hover_annot:
            self.hover_annot = ha
            self.update()
        h = None if ha is not None else self.r.hit_view(x, y, PICK_PX / self.k)
        if h != self.hover:
            self.hover = h
            self.update()

    def mouseReleaseEvent(self, ev):
        if self.drag:
            moved = self.drag.get("moved")
            self._last_drag, self.drag = self.drag, None
            self.unsetCursor()
            if self.mode != "select":
                self.setCursor(Qt.CursorShape.CrossCursor)
            if moved:
                self.changed.emit("annot_move" if "aid" in (self._last_drag or {}) else "move")
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
            if self.tool:
                self.tool_cancel()
            elif self.mode != "select":
                self.end_place()
            else:
                self.set_selected(None)
                self.set_selected_annot(None)
            return
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.mode == "select" and (self.sel or self.sel_annot):
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
        if self.sel_annot:
            aid = self.sel_annot
            self.sel_annot = None
            try:
                self.d.remove_annot(aid)
            except Exception:                                      # noqa: BLE001
                return False
            self.annot_selected.emit(None)
            self.changed.emit("annot_delete")
            self.update()
            return True
        if not self.sel:
            return False
        vid = self.sel
        self.sel = None
        self.d.remove_view(vid)
        self.selection_changed.emit(None)
        self.changed.emit("delete")
        self.update()
        return True
