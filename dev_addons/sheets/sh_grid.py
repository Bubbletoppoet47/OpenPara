"""
sh_grid.py - the grid of Sheets: cells, row and column headers, selection, in-cell editing, copy / paste, the fill handle and the charts that float over it.

The grid draws only the cells that are on screen, so a sheet of any size scrolls smoothly.  It knows the Workbook (sh_book.py) and nothing about the ribbon:
sh_tab.py puts the ribbon, the formula bar and the sheet tabs around it and listens to its signals.
"""
import bisect
import json
import os
import traceback

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication, QLabel, QMenu, QMessageBox, QToolTip, QVBoxLayout, QWidget

import sh_book as B
import sh_chart
import sh_deps
import sh_edit
import sh_engine as E
import sh_fmt

MIME = "application/x-openpara-sheets"
TOKEN = f"{os.getpid()}"
DEF_W, DEF_H, HDR_H, MIN_W, MIN_H = 72, 22, 22, 14, 10
MOVE_LIMIT = 200_000            # the biggest block that can be dragged by its border (whole columns and rows are too big)

LINE = QColor("#dfe3ea")
HEAD_BG, HEAD_SEL, HEAD_INK = QColor("#eef1f6"), QColor("#d3e2fa"), QColor("#4b5870")
SEL_FILL, ACCENT = QColor(43, 125, 233, 38), QColor("#2b7de9")
ERR_INK, WARN_INK, LINK_INK = QColor("#b00020"), QColor("#e8590c"), QColor("#0e7f86")
INK = QColor("#1f2a3c")


class Axis:
    """The widths of the columns (or heights of the rows): a default and a few exceptions; positions found without walking every column."""

    def __init__(self, default, maximum, floor):
        self.default, self.maximum, self.floor = default, maximum, floor
        self.sizes = {}
        self._keys, self._cum = [], []

    def set_sizes(self, d):
        self.sizes = {int(k): max(self.floor, int(v)) for k, v in d.items() if int(v) != self.default}
        self._keys = sorted(self.sizes)
        acc, cum = 0, []
        for k in self._keys:
            acc += self.sizes[k] - self.default
            cum.append(acc)
        self._cum = cum

    def size(self, i):
        return self.sizes.get(i, self.default)

    def pos(self, i):
        """Where index i (1-based) starts."""
        j = bisect.bisect_left(self._keys, i)
        return (i - 1) * self.default + (self._cum[j - 1] if j else 0)

    def index_at(self, off):
        if off <= 0:
            return 1
        lo, hi = 1, self.maximum
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.pos(mid) <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo


def log_error(text):
    try:
        import gpd_app
        gpd_app.log_error(text)
    except Exception:                                    # noqa: BLE001 - logging must never be the thing that fails
        pass


# ------------------------------------------------------------------------------------------------------------------ a chart on the grid
class ChartFrame(QWidget):
    """A chart floating over the cells: drag the top strip to move it, the corner to resize it, double-click to edit, right-click for more."""
    STRIP = 20
    changed = pyqtSignal(str)                 # chart id: moved or resized (the file is now different)
    edit_asked = pyqtSignal(str)
    menu_asked = pyqtSignal(str, QPoint)
    picked = pyqtSignal(str)

    def __init__(self, grid, chart):
        super().__init__(grid.viewport())
        self.grid, self.chart_id = grid, chart["id"]
        self.selected = False
        self._drag = None
        self.setMouseTracking(True)
        self.canvas = None
        self.fig = None
        mpl = sh_deps.matplotlib()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, self.STRIP, 1, 1)
        if mpl is None:
            self.note = QLabel("matplotlib is needed to draw charts.")
            self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(self.note)
        else:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure
            self.fig = Figure(figsize=(5, 3), dpi=100)
            self.canvas = FigureCanvasQTAgg(self.fig)
            self.canvas.setStyleSheet("background:white;")
            self.canvas.installEventFilter(self)
            lay.addWidget(self.canvas)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self.redraw)
        self.show()

    def chart(self):
        for c in self.grid.sheet_obj().charts:
            if c.get("id") == self.chart_id:
                return c
        return None

    def later(self):
        self._timer.start()

    def redraw(self):
        ch = self.chart()
        if ch is None or self.fig is None:
            return
        try:
            sh_chart.draw(self.fig, self.grid.wb, ch, compact=self.width() < 380)
            self.canvas.draw()                           # (now, not later: a failure while painting would not be caught)
        except Exception:                                # noqa: BLE001 - a chart that cannot be drawn must not stop the grid
            log_error("A chart could not be drawn:\n" + traceback.format_exc())
            try:
                self.fig.clear()
                self.fig.text(0.5, 0.5, "This chart could not be drawn.\nCheck its Advanced settings.", ha="center", va="center", color="#b00020")
                self.canvas.draw()
            except Exception:                            # noqa: BLE001
                pass

    def place(self):
        ch = self.chart()
        if ch is None:
            return
        x, y = ch.get("pos", [40, 40])
        w, h = ch.get("size", sh_chart.DEFAULT_SIZE)
        g = self.grid
        self.setGeometry(int(g.hw + x - g.x0), int(g.hh + y - g.y0), int(w), int(h))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.later()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.fillRect(0, 0, self.width(), self.STRIP, QColor("#dbe7fb") if self.selected else QColor("#eef1f6"))
        ch = self.chart() or {}
        p.setPen(QColor("#4b5870"))
        f = p.font()
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.drawText(QRect(8, 0, self.width() - 16, self.STRIP), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, ch.get("title") or "Chart")
        p.setPen(QPen(ACCENT if self.selected else QColor("#b8c2d3"), 2 if self.selected else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#8fa0bb"))
        w, h = self.width(), self.height()
        p.drawPolygon(QPolygonF([QPointF(w - 11, h - 2), QPointF(w - 2, h - 2), QPointF(w - 2, h - 11)]))
        p.end()

    def eventFilter(self, obj, ev):
        if obj is self.canvas and ev.type() == QEvent.Type.MouseButtonPress:
            self.picked.emit(self.chart_id)
            if ev.button() == Qt.MouseButton.RightButton:
                self.menu_asked.emit(self.chart_id, ev.globalPosition().toPoint())
                return True
        if obj is self.canvas and ev.type() == QEvent.Type.MouseButtonDblClick:
            self.edit_asked.emit(self.chart_id)
            return True
        return False

    def _in_corner(self, pos):
        return pos.x() > self.width() - 16 and pos.y() > self.height() - 16

    def mousePressEvent(self, ev):
        self.picked.emit(self.chart_id)
        if ev.button() == Qt.MouseButton.RightButton:
            self.menu_asked.emit(self.chart_id, ev.globalPosition().toPoint())
            return
        ch = self.chart()
        if ch is None or ev.button() != Qt.MouseButton.LeftButton:
            return
        if self._in_corner(ev.position().toPoint()):
            self._drag = ("size", ev.globalPosition().toPoint(), list(ch.get("size", sh_chart.DEFAULT_SIZE)))
        elif ev.position().y() <= self.STRIP:
            self._drag = ("move", ev.globalPosition().toPoint(), list(ch.get("pos", [40, 40])))

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._in_corner(pos) else (Qt.CursorShape.SizeAllCursor if pos.y() <= self.STRIP else Qt.CursorShape.ArrowCursor))
            return
        ch = self.chart()
        if ch is None:
            return
        kind, start, orig = self._drag
        d = ev.globalPosition().toPoint() - start
        if kind == "move":
            ch["pos"] = [max(0, orig[0] + d.x()), max(0, orig[1] + d.y())]
        else:
            ch["size"] = [max(220, orig[0] + d.x()), max(150, orig[1] + d.y())]
        self.place()

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self.changed.emit(self.chart_id)

    def mouseDoubleClickEvent(self, ev):
        self.edit_asked.emit(self.chart_id)


# ------------------------------------------------------------------------------------------------------------------ the grid
class Grid(QAbstractScrollArea):
    selection_changed = pyqtSignal()
    edit_started = pyqtSignal()
    edit_ended = pyqtSignal()
    edit_text = pyqtSignal(str)
    message = pyqtSignal(str, str)
    command = pyqtSignal(str)                 # a command that needs a window: the tab runs it (format, paste_special, chart_edit ...)
    charts_changed = pyqtSignal()
    sheet_asked = pyqtSignal(str)             # a click on a reference in another sheet: show that sheet's tab

    def __init__(self, wb, bar=None, parent=None):
        super().__init__(parent)
        self.wb = wb
        self.bar = bar                        # the formula bar's FormulaEdit (shares the edit with the in-cell editor)
        self.sheet = wb.sheets[wb.active].name
        self.cols = Axis(DEF_W, E.MAXCOL, MIN_W)
        self.rows = Axis(DEF_H, E.MAXROW, MIN_H)
        self.hw = 46
        self.hh = HDR_H
        self.x0 = self.y0 = 0
        self.r = self.c = 1                   # the active cell (the one that is typed into)
        self.er = self.ec = 1                 # the other corner of the selected block
        self.areas = []                       # the blocks kept earlier in a selection made with Ctrl (the block being worked on is sel())
        self.nr, self.nc = 120, 40
        self.views = {}                       # sheet name -> (r, c, er, ec, x0, y0)
        self.copied = None                    # (sheet, [rects], cut) shown with a dashed border
        self.edit = None                      # {"sheet", "r", "c"} while a cell is being edited
        self.frames = {}
        self.sel_chart = None
        self._drag = None
        self._moved_to = None                 # where a block that is being dragged by its border would land
        self._copying = False                 # ... and whether Ctrl makes it a copy
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._autoscroll)
        self._pending = None
        self._last_cursor = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        base = QApplication.font()
        base.setPointSizeF(max(9.5, base.pointSizeF() if base.pointSizeF() > 0 else 10))
        self.f_norm = QFont(base)
        self.f_bold = QFont(base)
        self.f_bold.setBold(True)
        self.f_ital = QFont(base)
        self.f_ital.setItalic(True)
        self.f_bi = QFont(self.f_bold)
        self.f_bi.setItalic(True)
        self.f_head = QFont(base)
        self.f_head.setPointSizeF(base.pointSizeF() - 0.5)
        self.editor = sh_edit.FormulaEdit(self.viewport())
        self.editor.setFrame(False)
        self.editor.setStyleSheet("QLineEdit { background:white; border:2px solid #2b7de9; padding:0 3px; selection-background-color:#9ec1f3; }")
        self.editor.hide()
        self.editor.done.connect(self.commit_edit)
        self.editor.cancelled.connect(self.cancel_edit)
        self.editor.textEdited.connect(self._editor_text)
        if bar is not None:
            bar.textEdited.connect(self._bar_text)
            bar.done.connect(self.commit_edit)
            bar.cancelled.connect(self.cancel_edit)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        wb.listeners.append(self._on_wb)
        self._load_sizes()
        self._update_scroll()

    # ------------------------------------------------------------------ the sheet shown
    def set_workbook(self, wb):
        """Shows another workbook (a file was opened into this tab)."""
        self.finish_edit(commit=False)
        try:
            self.wb.listeners.remove(self._on_wb)
        except ValueError:
            pass
        self.wb = wb
        wb.listeners.append(self._on_wb)
        self.views = {}
        self.copied = None
        self.sel_chart = None
        for f in self.frames.values():
            f.hide()
            f.deleteLater()
        self.frames = {}
        self.sheet = wb.sheets[min(wb.active, len(wb.sheets) - 1)].name
        self.r = self.c = self.er = self.ec = 1
        self.areas = []
        self.nr, self.nc = 120, 40
        self._load_sizes()
        self._update_scroll()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.x0 = self.y0 = 0
        self._sync_charts()
        self.viewport().update()
        self.selection_changed.emit()

    def sheet_obj(self):
        return self.wb.get_sheet(self.sheet)

    def _load_sizes(self):
        s = self.sheet_obj()
        self.cols.set_sizes(s.col_w if s else {})
        self.rows.set_sizes(s.row_h if s else {})

    def set_sheet(self, name, keep_edit=True):
        if name == self.sheet or self.wb.get_sheet(name) is None:
            return
        if self.edit is None or not keep_edit:
            self.finish_edit(commit=self.edit is not None)
        self.views[self.sheet] = (self.r, self.c, self.er, self.ec, self.x0, self.y0)
        self.areas = []
        self.sheet = name
        self.wb.active = self.wb.sheet_names().index(name)
        self._load_sizes()
        v = self.views.get(name)
        self.sel_chart = None
        if v:
            self.r, self.c, self.er, self.ec, x0, y0 = v
        else:
            self.r = self.c = self.er = self.ec = 1
            x0 = y0 = 0
        self._update_scroll()
        self.horizontalScrollBar().setValue(x0)
        self.verticalScrollBar().setValue(y0)
        self.x0, self.y0 = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        self._sync_charts()
        self._place_editor()
        self.viewport().update()
        self.selection_changed.emit()

    def _on_wb(self, changed, structure):
        if structure:
            if self.wb.get_sheet(self.sheet) is None:
                self.sheet = self.wb.sheets[min(self.wb.active, len(self.wb.sheets) - 1)].name
                self.views.pop(self.sheet, None)
            self._load_sizes()
            self._update_scroll()
            self._sync_charts()
            self.selection_changed.emit()
        else:
            for f in self.frames.values():
                f.later()
        self.viewport().update()

    # ------------------------------------------------------------------ selection
    def sel(self):
        """The block being worked on (the active cell is one of its corners)."""
        return (min(self.er, self.r), min(self.ec, self.c), max(self.er, self.r), max(self.ec, self.c))

    def rects(self):
        """Every selected block: the ones kept with Ctrl first, the current one last (each once)."""
        out = []
        for a in list(self.areas) + [self.sel()]:
            if a not in out:
                out.append(a)
        return out

    def used_rects(self):
        """The selected blocks cut down to the used area (a whole column or row stops where the data stops)."""
        mr, mc = self.wb.extent(self.sheet)
        return [(r1, c1, max(r1, min(r2, mr)), max(c1, min(c2, mc))) for r1, c1, r2, c2 in self.rects()]

    def add_area(self):
        """Keeps the current block, so that the next click or drag starts another one (Ctrl + click)."""
        cur = self.sel()
        if cur not in self.areas:
            self.areas.append(cur)

    def selected_rows(self):
        """The rows that any selected block touches, as sorted (first, last) runs."""
        return _runs([(a[0], a[2]) for a in self.rects()])

    def selected_cols(self):
        return _runs([(a[1], a[3]) for a in self.rects()])

    def select(self, r1, c1, r2=None, c2=None, active=None, keep=False):
        """Selects a block; the active cell is its first cell unless `active` = (r, c) names another cell of it.  `keep`: the blocks chosen with Ctrl stay."""
        if not keep:
            self.areas = []
        r2 = r1 if r2 is None else r2
        c2 = c1 if c2 is None else c2
        r1, r2 = sorted((max(1, min(r1, E.MAXROW)), max(1, min(r2, E.MAXROW))))
        c1, c2 = sorted((max(1, min(c1, E.MAXCOL)), max(1, min(c2, E.MAXCOL))))
        self.r, self.c = active or (r1, c1)
        self.er = r2 if self.r == r1 else r1
        self.ec = c2 if self.c == c1 else c1
        self.sel_chart = None
        self._grow(self.er, self.ec)
        self.ensure_visible(self.r, self.c)
        self.viewport().update()
        self.selection_changed.emit()

    def move_to(self, r, c, extend=False, keep=False):
        """Moves the active cell (extend=False) or the other corner of the selected block (extend=True).  Moving alone drops the blocks chosen with Ctrl
        (`keep` leaves them: that is what a Ctrl + click does after it has put the old block aside)."""
        r, c = max(1, min(r, E.MAXROW)), max(1, min(c, E.MAXCOL))
        if not extend and not keep:
            self.areas = []
        if extend:
            self.er, self.ec = r, c
        else:
            self.r = self.er = r
            self.c = self.ec = c
        self.sel_chart = None
        self._grow(r, c)
        self.ensure_visible(r, c)
        self.viewport().update()
        self.selection_changed.emit()

    def active_cell(self):
        return self.r, self.c

    def _grow(self, r, c):
        mr, mc = self.wb.extent(self.sheet)
        nr, nc = max(self.nr, mr + 40, r + 20), max(self.nc, mc + 20, c + 6)
        if (nr, nc) != (self.nr, self.nc):
            self.nr, self.nc = nr, nc
            self._update_scroll()

    # ------------------------------------------------------------------ geometry and scrolling
    def _update_scroll(self):
        vw = max(10, self.viewport().width() - self.hw)
        vh = max(10, self.viewport().height() - self.hh)
        mr, mc = self.wb.extent(self.sheet) if self.wb.get_sheet(self.sheet) else (0, 0)
        self.nr, self.nc = max(self.nr, mr + 40), max(self.nc, mc + 20)
        w, h = self.cols.pos(self.nc + 1), self.rows.pos(self.nr + 1)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setRange(0, max(0, w - vw))
        hb.setPageStep(vw)
        hb.setSingleStep(36)
        vb.setRange(0, max(0, h - vh))
        vb.setPageStep(vh)
        vb.setSingleStep(DEF_H * 2)
        digits = len(str(max(1, self.rows.index_at(self.y0 + vh))))
        self.hw = max(40, QFontMetrics(self.f_head).horizontalAdvance("0" * digits) + 18)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_scroll()
        self._place_editor()
        self._place_charts()

    def _scrolled(self, _v=0):
        self.x0, self.y0 = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        self._place_editor()
        self._place_charts()
        self.viewport().update()
        if self.y0 + self.viewport().height() > self.rows.pos(self.nr) - 200 or self.x0 + self.viewport().width() > self.cols.pos(self.nc) - 200:
            self.nr, self.nc = self.nr + 40, self.nc + 8                       # the sheet goes on as you scroll
            self._update_scroll()

    def cell_rect(self, r, c):
        """The cell's rectangle in viewport coordinates."""
        return QRect(int(self.hw + self.cols.pos(c) - self.x0), int(self.hh + self.rows.pos(r) - self.y0), self.cols.size(c), self.rows.size(r))

    def block_rect(self, r1, c1, r2, c2):
        a, b = self.cell_rect(r1, c1), self.cell_rect(r2, c2)
        return QRect(a.left(), a.top(), b.right() - a.left() + 1, b.bottom() - a.top() + 1)

    def ensure_visible(self, r, c):
        vw, vh = self.viewport().width() - self.hw, self.viewport().height() - self.hh
        x, y = self.cols.pos(c), self.rows.pos(r)
        w, h = self.cols.size(c), self.rows.size(r)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        if x < self.x0:
            hb.setValue(x)
        elif x + w > self.x0 + vw:
            hb.setValue(min(x, x + w - vw))
        if y < self.y0:
            vb.setValue(y)
        elif y + h > self.y0 + vh:
            vb.setValue(min(y, y + h - vh))

    def cell_at(self, pos):
        """(row, column) under a viewport point; None over the headers."""
        if pos.x() < self.hw or pos.y() < self.hh:
            return None
        return self.rows.index_at(pos.y() - self.hh + self.y0), self.cols.index_at(pos.x() - self.hw + self.x0)

    def col_edge_at(self, x):
        """The column whose right edge is within 3 px of viewport x (for resizing), else 0."""
        c = self.cols.index_at(x - self.hw + self.x0)
        for k in (c - 1, c):
            if k >= 1 and abs(self.hw + self.cols.pos(k) + self.cols.size(k) - self.x0 - x) <= 3:
                return k
        return 0

    def row_edge_at(self, y):
        r = self.rows.index_at(y - self.hh + self.y0)
        for k in (r - 1, r):
            if k >= 1 and abs(self.hh + self.rows.pos(k) + self.rows.size(k) - self.y0 - y) <= 3:
                return k
        return 0

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        p = QPainter(self.viewport())
        try:
            self._paint(p)
        except Exception:                                # noqa: BLE001 - an error in painting must never close the program
            log_error("The grid could not be painted:\n" + traceback.format_exc())
        finally:
            p.end()

    def _paint(self, p):
        wb, sheet = self.wb, self.sheet
        s = self.sheet_obj()
        vw, vh = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, vw, vh, QColor("white"))
        r_first = self.rows.index_at(self.y0)
        r_last = min(E.MAXROW, self.rows.index_at(self.y0 + vh - self.hh) + 1)
        c_first = self.cols.index_at(self.x0)
        c_last = min(E.MAXCOL, self.cols.index_at(self.x0 + vw - self.hw) + 1)
        sr1, sc1, sr2, sc2 = self.sel()
        fm = QFontMetrics(self.f_norm)
        p.setClipRect(QRect(self.hw, self.hh, vw - self.hw, vh - self.hh))
        # backgrounds, then the lines
        for r in range(r_first, r_last + 1):
            y = self.hh + self.rows.pos(r) - self.y0
            h = self.rows.size(r)
            for c in range(c_first, c_last + 1):
                cell = s.cells.get((r, c)) if s else None
                if cell is not None and cell.st is not None and cell.st.bg:
                    x = self.hw + self.cols.pos(c) - self.x0
                    p.fillRect(x, y, self.cols.size(c), h, QColor(cell.st.bg))
        p.setPen(QPen(LINE, 1))
        for r in range(r_first, r_last + 2):
            y = self.hh + self.rows.pos(r) - self.y0 - 1
            p.drawLine(self.hw, y, vw, y)
        for c in range(c_first, c_last + 2):
            x = self.hw + self.cols.pos(c) - self.x0 - 1
            p.drawLine(x, self.hh, x, vh)
        # the text
        for r in range(r_first, r_last + 1):
            for c in range(c_first, c_last + 1):
                cell = s.cells.get((r, c)) if s else None
                if cell is None or cell.raw is None:
                    continue
                if self.edit and self.edit["sheet"] == sheet and (self.edit["r"], self.edit["c"]) == (r, c) and self.editor.isVisible():
                    continue
                self._paint_text(p, fm, r, c, cell, c_last)
        # imported blocks
        p.setPen(QPen(LINK_INK, 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for ln in (s.links if s else []):
            r0, c0 = ln["origin"]
            rr = self.block_rect(r0, c0, r0 + max(0, ln.get("rows", 0)), c0 + max(1, ln.get("cols", 1)) - 1)
            if rr.intersects(QRect(0, 0, vw, vh)):
                p.drawRect(rr.adjusted(0, 0, -1, -1))
        # the selection
        sel = self.block_rect(sr1, sc1, sr2, sc2)
        for a in self.areas:                              # blocks kept with Ctrl: shaded, with a thinner border
            ar = self.block_rect(*a)
            if ar.intersects(QRect(0, 0, vw, vh)):
                p.fillRect(ar, SEL_FILL)
                p.setPen(QPen(ACCENT, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(ar.adjusted(0, 0, -1, -1))
        if (sr1, sc1) != (sr2, sc2) or self.areas:
            p.fillRect(sel, SEL_FILL)
            act = self.cell_rect(self.r, self.c)
            p.fillRect(act.adjusted(0, 0, -1, -1), QColor("white"))
            cell = s.cells.get((self.r, self.c)) if s else None
            if cell is not None and cell.raw is not None:
                self._paint_text(p, fm, self.r, self.c, cell, c_last)
        if self.sel_chart is None:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel.adjusted(0, 0, -2, -2))
            p.setPen(QPen(QColor("white"), 1))
            p.setBrush(QBrush(ACCENT))
            p.drawRect(sel.right() - 5, sel.bottom() - 5, 6, 6)                # the fill handle
        # copied block
        if self.copied and self.copied[0] == sheet:
            pen = QPen(QColor("#2b7de9"), 1, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for rect in self.copied[1]:
                cr = self.block_rect(*rect)
                p.drawRect(cr.adjusted(1, 1, -2, -2))
        self._paint_drag(p, fm)
        # warnings
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(WARN_INK))
        for (sh, r, c), msgs in wb.warnings.items():
            if sh == sheet and r_first <= r <= r_last and c_first <= c <= c_last and msgs:
                rc = self.cell_rect(r, c)
                p.drawPolygon(QPolygonF([QPointF(rc.right() - 8, rc.top()), QPointF(rc.right(), rc.top()), QPointF(rc.right(), rc.top() + 8)]))
        p.setClipping(False)
        self._paint_headers(p, r_first, r_last, c_first, c_last, sr1, sc1, sr2, sc2)

    def _paint_drag(self, p, fm):
        """While the fill handle is dragged: a dashed outline round the cells that will be filled, with the values they will get.  While a block is dragged by its
        border: where it will land."""
        d = self._drag
        if d is None or self._last_cursor is None:
            return
        if d[0] == "fill":
            dst = self._fill_target(d[1], self._last_cursor)
            if dst is None:
                return
            src = d[1]
            whole = (min(src[0], dst[0]), min(src[1], dst[1]), max(src[2], dst[2]), max(src[3], dst[3]))
            tint = self.block_rect(*dst)
            p.fillRect(tint, QColor("white"))                           # what is there now is hidden under what will be there
            p.fillRect(tint, QColor(43, 125, 233, 22))
            p.setPen(QPen(LINE, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for rr in range(dst[0], dst[2] + 1):
                for cc in range(dst[1], dst[3] + 1):
                    p.drawRect(self.cell_rect(rr, cc).adjusted(0, 0, -1, -1))
            p.setFont(self.f_ital)
            p.setPen(QColor("#6b7a90"))
            for (r, c), (text, isnum) in self.wb.fill_preview(self.sheet, src, dst).items():
                rc = self.cell_rect(r, c)
                if rc.bottom() < self.hh or rc.top() > self.viewport().height() or rc.right() < self.hw or rc.left() > self.viewport().width():
                    continue
                flag = Qt.AlignmentFlag.AlignRight if isnum else Qt.AlignmentFlag.AlignLeft
                p.drawText(QRect(rc.left() + 4, rc.top(), rc.width() - 8, rc.height()), flag | Qt.AlignmentFlag.AlignVCenter,
                           QFontMetrics(self.f_ital).elidedText(text, Qt.TextElideMode.ElideRight, rc.width() - 8))
            p.setPen(QPen(QColor("#1f2a3c"), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.block_rect(*whole).adjusted(1, 1, -2, -2))
        elif d[0] == "move" and self._moved_to is not None and self._moved_to != tuple(d[1][:2]):
            r1, c1, r2, c2 = d[1]
            r, c = self._moved_to
            rr = self.block_rect(r, c, r + r2 - r1, c + c2 - c1)
            p.fillRect(rr, QColor(43, 125, 233, 30))
            p.setPen(QPen(ACCENT, 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rr.adjusted(1, 1, -2, -2))
            label = ("Copy to " if self._copying else "Move to ") + self._rect_name((r, c, r + r2 - r1, c + c2 - c1))
            p.setFont(self.f_norm)
            fm2 = QFontMetrics(self.f_norm)
            lw = fm2.horizontalAdvance(label) + 12
            lr = QRect(rr.left(), max(self.hh, rr.top() - 22), lw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#1f2a3c")))
            p.drawRoundedRect(lr, 3, 3)
            p.setPen(QColor("white"))
            p.drawText(lr, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_text(self, p, fm, r, c, cell, c_last):
        wb = self.wb
        st = cell.st
        v = wb.value(self.sheet, r, c)
        text = wb.display(self.sheet, r, c)
        if text == "":
            return
        rc = self.cell_rect(r, c)
        font = self.f_norm
        if st is not None:
            font = self.f_bi if st.bold and st.italic else (self.f_bold if st.bold else (self.f_ital if st.italic else self.f_norm))
        p.setFont(font)
        f2 = QFontMetrics(font)
        isnum = isinstance(v, float) and not isinstance(v, bool)
        iserr = isinstance(v, E.Err)
        color = ERR_INK if iserr else (QColor(st.fg) if st is not None and st.fg else INK)
        p.setPen(color)
        align = st.align if st is not None and st.align else ("right" if isnum else ("center" if iserr or isinstance(v, bool) else "left"))
        avail = rc.width() - 8
        tw = f2.horizontalAdvance(text)
        if isnum and tw > avail:
            for fmt_digits in (".6g", ".4g", ".3g", ".2g"):
                alt = format(v, fmt_digits)
                if cell.fmt in ("General", None) and f2.horizontalAdvance(alt) <= avail:
                    text, tw = alt, f2.horizontalAdvance(alt)
                    break
            else:
                text, tw = "#" * max(1, int(avail / max(1, f2.horizontalAdvance("#")))), avail
        box = QRect(rc.left() + 4, rc.top(), avail, rc.height())
        if not isnum and not iserr and tw > avail and align in ("left", "center"):
            x_end, k, sobj = rc.right(), c + 1, self.sheet_obj()
            while k <= c_last + 6:
                nxt = sobj.cells.get((r, k))
                if nxt is not None and nxt.raw is not None:
                    break
                x_end += self.cols.size(k)
                k += 1
                if x_end - rc.left() > tw + 12:
                    break
            box = QRect(rc.left() + 4, rc.top(), max(avail, x_end - rc.left() - 8), rc.height())
        flag = {"left": Qt.AlignmentFlag.AlignLeft, "right": Qt.AlignmentFlag.AlignRight, "center": Qt.AlignmentFlag.AlignHCenter}[align]
        p.drawText(box, flag | Qt.AlignmentFlag.AlignVCenter, text if tw <= box.width() or isnum else f2.elidedText(text, Qt.TextElideMode.ElideRight, box.width()))

    def _paint_headers(self, p, r_first, r_last, c_first, c_last, sr1, sc1, sr2, sc2):
        vw, vh = self.viewport().width(), self.viewport().height()
        p.setFont(self.f_head)
        p.fillRect(0, 0, vw, self.hh, HEAD_BG)
        p.fillRect(0, 0, self.hw, vh, HEAD_BG)
        rects = self.rects()
        p.setClipRect(QRect(self.hw, 0, vw - self.hw, self.hh))
        for c in range(c_first, c_last + 1):
            x, w = self.hw + self.cols.pos(c) - self.x0, self.cols.size(c)
            on = any(a[1] <= c <= a[3] for a in rects)
            if on:
                p.fillRect(x, 0, w, self.hh, HEAD_SEL)
            p.setPen(QPen(QColor("#c5ccd8"), 1))
            p.drawLine(x + w - 1, 0, x + w - 1, self.hh)
            p.setPen(QColor("#1a56c4") if on else HEAD_INK)
            p.drawText(QRect(x, 0, w, self.hh), Qt.AlignmentFlag.AlignCenter, E.col_letter(c))
        p.setClipRect(QRect(0, self.hh, self.hw, vh - self.hh))
        for r in range(r_first, r_last + 1):
            y, h = self.hh + self.rows.pos(r) - self.y0, self.rows.size(r)
            on = any(a[0] <= r <= a[2] for a in rects)
            if on:
                p.fillRect(0, y, self.hw, h, HEAD_SEL)
            p.setPen(QPen(QColor("#c5ccd8"), 1))
            p.drawLine(0, y + h - 1, self.hw, y + h - 1)
            p.setPen(QColor("#1a56c4") if on else HEAD_INK)
            p.drawText(QRect(0, y, self.hw - 6, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(r))
        p.setClipping(False)
        p.setPen(QPen(QColor("#c5ccd8"), 1))
        p.drawLine(0, self.hh - 1, vw, self.hh - 1)
        p.drawLine(self.hw - 1, 0, self.hw - 1, vh)
        p.setBrush(QColor("#c5ccd8"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(self.hw - 4, self.hh - 14), QPointF(self.hw - 4, self.hh - 4), QPointF(self.hw - 14, self.hh - 4)]))

    # ------------------------------------------------------------------ editing
    def begin_edit(self, text=None, enter_mode=False, focus="cell"):
        """Starts editing the active cell.  text=None: the cell's own text; enter_mode: typing started it (the arrow keys then finish the entry)."""
        if self.edit is not None:
            return
        cell = self.wb.cell(self.sheet, self.r, self.c)
        if text is None:
            text = B.edit_text(cell)
        self.edit = {"sheet": self.sheet, "r": self.r, "c": self.c}
        self.editor.enter_mode = enter_mode
        if self.bar is not None:
            self.bar.enter_mode = enter_mode
        for e in [self.editor] + ([self.bar] if self.bar is not None else []):
            e.blockSignals(True)
            e.setText(text)
            e.last_point = None
            e.blockSignals(False)
        self._place_editor()
        self.editor.show()
        w = self.editor if focus == "cell" else (self.bar or self.editor)
        w.setFocus()
        w.setCursorPosition(len(text))
        if not enter_mode and focus == "cell":
            w.deselect()
        self.edit_started.emit()
        self.edit_text.emit(text)
        self.viewport().update()

    def _editor_text(self, text):
        if self.bar is not None:
            self.bar.blockSignals(True)
            self.bar.setText(text)
            self.bar.blockSignals(False)
        self._grow_editor()
        self.edit_text.emit(text)

    def _bar_text(self, text):
        if self.edit is None:
            return
        self.editor.blockSignals(True)
        self.editor.setText(text)
        self.editor.blockSignals(False)
        self._grow_editor()
        self.edit_text.emit(text)

    def _place_editor(self):
        if self.edit is None:
            return
        on = self.edit["sheet"] == self.sheet
        self.editor.setVisible(on)
        if on:
            rc = self.cell_rect(self.edit["r"], self.edit["c"])
            self.editor.setGeometry(rc)
            self._grow_editor()

    def _grow_editor(self):
        if self.edit is None or self.edit["sheet"] != self.sheet:
            return
        rc = self.cell_rect(self.edit["r"], self.edit["c"])
        w = max(rc.width(), QFontMetrics(self.editor.font()).horizontalAdvance(self.editor.text()) + 24)
        self.editor.setGeometry(rc.left(), rc.top(), min(w, max(rc.width(), self.viewport().width() - rc.left() - 4)), rc.height())

    def edit_text_now(self):
        return self.bar.text() if self.bar is not None and self.edit is not None else self.editor.text()

    def set_edit_text(self, text):
        for e in [self.editor] + ([self.bar] if self.bar is not None else []):
            e.blockSignals(True)
            e.setText(text)
            e.blockSignals(False)
        self.edit_text.emit(text)

    def commit_edit(self, dr=0, dc=0):
        if self.edit is None:
            return True
        text = self.editor.text() if self.editor.isVisible() else (self.bar.text() if self.bar is not None else self.editor.text())
        if self.bar is not None and self.bar.hasFocus():
            text = self.bar.text()
        if text.startswith("=") and len(text) > 1:
            msg = E.check(text)
            if msg:
                self.message.emit(f"That formula cannot be read: {msg}", "bad")
                return False
        ed = self.edit
        self.edit = None
        self.editor.hide()
        if ed["sheet"] != self.sheet:
            self.set_sheet(ed["sheet"])
        self.wb.set_input(ed["sheet"], ed["r"], ed["c"], text)
        self.areas = []
        self.r = self.er = ed["r"]
        self.c = self.ec = ed["c"]
        self.edit_ended.emit()
        if dr or dc:
            self.move_to(self.r + dr, self.c + dc)
        else:
            self.selection_changed.emit()
        self.setFocus()
        self.viewport().update()
        return True

    def cancel_edit(self):
        self.finish_edit(commit=False)

    def finish_edit(self, commit):
        if self.edit is None:
            return True
        if commit:
            return self.commit_edit()
        ed = self.edit
        self.edit = None
        self.editor.hide()
        if ed["sheet"] != self.sheet:
            self.set_sheet(ed["sheet"])
        self.edit_ended.emit()
        self.selection_changed.emit()
        self.setFocus()
        self.viewport().update()
        return True

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        self.setFocus()
        right = ev.button() == Qt.MouseButton.RightButton
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        hit = self.cell_at(pos)
        if self.edit is not None and hit is not None and self.editor_for_point().can_point():
            ed = self.editor_for_point()
            self._point(hit, ed)
            self._drag = ("point", hit, ed)
            return
        if self.edit is not None and not right:
            if not self.commit_edit():
                return
        if right:
            self._context(pos, ev.globalPosition().toPoint(), hit)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if hit is not None:
            sel = self.block_rect(*self.sel())
            if QRect(sel.right() - 9, sel.bottom() - 9, 14, 14).contains(pos) and self.sel_chart is None and not ctrl:
                self._drag = ("fill", self.sel())
                self._timer.start()
                return
            if not shift and self._on_border(pos):                  # the border of the selection: drag it to move the cells (Ctrl: copy them)
                r1, c1, r2, c2 = self.sel()
                self._drag = ("move", (r1, c1, r2, c2), (hit[0] - r1, hit[1] - c1), hit)
                self._moved_to = None
                self._timer.start()
                return
            if shift:
                self.move_to(hit[0], hit[1], extend=True)
            elif ctrl:                                       # another block: the old one stays selected
                self.add_area()
                self.move_to(hit[0], hit[1], keep=True)
            else:
                self.move_to(*hit)
            self._drag = ("cells",)
            self._timer.start()
            return
        # headers
        if pos.x() < self.hw and pos.y() < self.hh:
            self.select(1, 1, self.nr, self.nc)
            return
        if pos.y() < self.hh:
            k = self.col_edge_at(pos.x())
            if k:
                self._drag = ("colsize", k, pos.x(), self.cols.size(k))
                return
            c = self.cols.index_at(pos.x() - self.hw + self.x0)
            if shift:                                        # from the active column to this one (Ctrl + Shift keeps the other blocks)
                if not ctrl:
                    self.areas = []
                self.r, self.er, self.ec = 1, self.nr, c
            else:
                if ctrl:
                    self.add_area()
                else:
                    self.areas = []
                self.r, self.c, self.er, self.ec = 1, c, self.nr, c
            self.sel_chart = None
            self._drag = ("cols", c)
            self.selection_changed.emit()
            self.viewport().update()
            return
        k = self.row_edge_at(pos.y())
        if k:
            self._drag = ("rowsize", k, pos.y(), self.rows.size(k))
            return
        r = self.rows.index_at(pos.y() - self.hh + self.y0)
        if shift:
            if not ctrl:
                self.areas = []
            self.c, self.ec, self.er = 1, self.nc, r
        else:
            if ctrl:
                self.add_area()
            else:
                self.areas = []
            self.r, self.c, self.er, self.ec = r, 1, r, self.nc
        self.sel_chart = None
        self._drag = ("rows", r)
        self.selection_changed.emit()
        self.viewport().update()

    def editor_for_point(self):
        return self.bar if self.bar is not None and self.bar.hasFocus() else self.editor

    def _point(self, hit, ed, extend=None):
        r, c = hit
        if extend:
            r1, c1 = extend
            ref = E.addr(min(r, r1), min(c, c1)) + (":" + E.addr(max(r, r1), max(c, c1)) if (r, c) != (r1, c1) else "")
        else:
            ref = E.addr(r, c)
        if self.edit and self.edit["sheet"] != self.sheet:
            ref = E.quote_sheet(self.sheet) + "!" + ref
        ed.put_reference(ref)
        ed.setFocus()
        self.edit_text.emit(ed.text())
        if ed is self.editor:
            self._bar_sync()
        else:
            self._editor_sync()
        self.viewport().update()

    def _bar_sync(self):
        if self.bar is not None:
            self.bar.blockSignals(True)
            self.bar.setText(self.editor.text())
            self.bar.blockSignals(False)

    def _editor_sync(self):
        self.editor.blockSignals(True)
        self.editor.setText(self.bar.text())
        self.editor.blockSignals(False)

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        d = self._drag
        self._last_cursor = pos
        if d is None:
            self._hover(pos)
            return
        kind = d[0]
        if kind == "point":
            hit = self.cell_at(pos)
            if hit is not None:
                self._point(hit, d[2], extend=d[1])
        elif kind == "cells":
            hit = self.cell_at(pos) or (self.rows.index_at(max(0, pos.y() - self.hh) + self.y0), self.cols.index_at(max(0, pos.x() - self.hw) + self.x0))
            if (self.er, self.ec) != hit:
                self.move_to(hit[0], hit[1], extend=True)
        elif kind == "cols":
            self.ec = self.cols.index_at(max(0, pos.x() - self.hw) + self.x0)
            self.viewport().update()
            self.selection_changed.emit()
        elif kind == "rows":
            self.er = self.rows.index_at(max(0, pos.y() - self.hh) + self.y0)
            self.viewport().update()
            self.selection_changed.emit()
        elif kind == "colsize":
            self._set_col_width(d[1], d[3] + pos.x() - d[2], live=True)
        elif kind == "rowsize":
            self._set_row_height(d[1], d[3] + pos.y() - d[2], live=True)
        elif kind == "fill":
            self.viewport().update()
        elif kind == "move":
            self._moved_to = self._move_target(d, pos)
            self._copying = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self.viewport().update()

    def _on_border(self, pos):
        """True when `pos` is on the border of the selected block (not on the fill handle): a press there drags the block."""
        if self.sel_chart is not None or self.areas or self.edit:
            return False
        r1, c1, r2, c2 = self.sel()
        if (r2 - r1 + 1) * (c2 - c1 + 1) > MOVE_LIMIT:
            return False
        sel = self.block_rect(r1, c1, r2, c2)
        if not sel.adjusted(-3, -3, 3, 3).contains(pos) or sel.adjusted(3, 3, -3, -3).contains(pos):
            return False
        return not QRect(sel.right() - 9, sel.bottom() - 9, 14, 14).contains(pos)

    def _cell_under(self, pos):
        return (self.rows.index_at(max(0, pos.y() - self.hh) + self.y0), self.cols.index_at(max(0, pos.x() - self.hw) + self.x0))

    def _move_target(self, d, pos):
        """(row, column) of the top left cell of a dragged block when the mouse is at `pos`, kept on the sheet."""
        r1, c1, r2, c2 = d[1]
        r, c = self._cell_under(pos)
        r, c = r - d[2][0], c - d[2][1]
        return max(1, min(r, E.MAXROW - (r2 - r1))), max(1, min(c, E.MAXCOL - (c2 - c1)))

    def _fill_target(self, src, pos):
        """The cells that dragging the fill handle from the block `src` to `pos` fills: (first row, first col, last row, last col), or None."""
        r1, c1, r2, c2 = src
        r, c = self._cell_under(pos)
        down, right = r - r2, c - c2
        if down <= 0 and right <= 0:
            return None
        return (r2 + 1, c1, r, c2) if down >= right else (r1, c2 + 1, r2, c)

    def _hover(self, pos):
        hit = self.cell_at(pos)
        cur = Qt.CursorShape.ArrowCursor
        if hit is None:
            if pos.y() < self.hh and pos.x() >= self.hw and self.col_edge_at(pos.x()):
                cur = Qt.CursorShape.SplitHCursor
            elif pos.x() < self.hw and pos.y() >= self.hh and self.row_edge_at(pos.y()):
                cur = Qt.CursorShape.SplitVCursor
        else:
            sel = self.block_rect(*self.sel())
            if QRect(sel.right() - 9, sel.bottom() - 9, 14, 14).contains(pos):
                cur = Qt.CursorShape.CrossCursor
            elif self._on_border(pos):
                cur = Qt.CursorShape.SizeAllCursor
        self.viewport().setCursor(cur)

    def mouseReleaseEvent(self, ev):
        d = self._drag
        self._drag = None
        self._timer.stop()
        if d is None:
            return
        if d[0] == "fill":
            self._finish_fill(d[1], ev.position().toPoint())
        elif d[0] == "move":
            self._finish_move(d, ev.position().toPoint(), bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier))
        elif d[0] in ("colsize", "rowsize"):
            self.selection_changed.emit()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position().toPoint()
        if pos.y() < self.hh and pos.x() >= self.hw:
            k = self.col_edge_at(pos.x())
            if k:
                self.autofit_column(k)
                return
        if pos.x() < self.hw and pos.y() >= self.hh:
            k = self.row_edge_at(pos.y())
            if k:
                self._set_row_height(k, DEF_H)
                return
        hit = self.cell_at(pos)
        if hit is not None and ev.button() == Qt.MouseButton.LeftButton:
            self.move_to(*hit)
            self.begin_edit(None, enter_mode=False)

    def _autoscroll(self):
        if self._drag is None or self._last_cursor is None:
            return
        pos = self._last_cursor
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        if pos.x() > self.viewport().width() - 6:
            hb.setValue(hb.value() + 24)
        elif pos.x() < self.hw + 4 and self._drag[0] in ("cells", "fill", "move"):
            hb.setValue(hb.value() - 24)
        if pos.y() > self.viewport().height() - 6:
            vb.setValue(vb.value() + 22)
        elif pos.y() < self.hh + 4 and self._drag[0] in ("cells", "fill", "move"):
            vb.setValue(vb.value() - 22)
        if self._drag[0] == "cells":
            hit = (self.rows.index_at(max(0, pos.y() - self.hh) + self.y0), self.cols.index_at(max(0, pos.x() - self.hw) + self.x0))
            if (self.er, self.ec) != hit:
                self.move_to(hit[0], hit[1], extend=True)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - ev.angleDelta().y() // 2)
            return
        super().wheelEvent(ev)

    # ------------------------------------------------------------------ sizes
    def _set_col_width(self, c, w, live=False):
        s = self.sheet_obj()
        w = max(MIN_W, int(w))
        runs = self.selected_cols()
        total = sum(b - a + 1 for a, b in runs)
        cols = [k for a, b in runs for k in range(a, b + 1)] if total > 1 and any(a <= c <= b for a, b in runs) else [c]
        for k in cols:
            if w == DEF_W:
                s.col_w.pop(k, None)
            else:
                s.col_w[k] = w
        self._load_sizes()
        self._update_scroll()
        self._place_editor()
        self._place_charts()
        self.viewport().update()
        if not live:
            self.charts_changed.emit()

    def _set_row_height(self, r, h, live=False):
        s = self.sheet_obj()
        h = max(MIN_H, int(h))
        runs = self.selected_rows()
        total = sum(b - a + 1 for a, b in runs)
        rows = [k for a, b in runs for k in range(a, b + 1)] if total > 1 and any(a <= r <= b for a, b in runs) else [r]
        for k in rows:
            if h == DEF_H:
                s.row_h.pop(k, None)
            else:
                s.row_h[k] = h
        self._load_sizes()
        self._update_scroll()
        self._place_editor()
        self._place_charts()
        self.viewport().update()

    def set_width(self, w):
        for a, b in self.selected_cols():
            for c in range(a, b + 1):
                self._set_col_width(c, w)

    def autofit_column(self, c):
        s = self.sheet_obj()
        fm = QFontMetrics(self.f_norm)
        best = MIN_W
        for (r, k), cell in s.cells.items():
            if k == c and cell.raw is not None:
                best = max(best, fm.horizontalAdvance(self.wb.display(self.sheet, r, c)) + 14)
        self._set_col_width(c, min(best, 520))

    def autofit_selection(self):
        for a, b in self.selected_cols():
            for c in range(a, b + 1):
                self.autofit_column(c)

    # ------------------------------------------------------------------ keyboard
    def keyPressEvent(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if ctrl:
            if k == Qt.Key.Key_C:
                return self.copy(False)
            if k == Qt.Key.Key_X:
                return self.copy(True)
            if k == Qt.Key.Key_V:
                return self.paste()
            if k == Qt.Key.Key_D:
                return self.fill_down()
            if k == Qt.Key.Key_R:
                return self.fill_right()
            if k == Qt.Key.Key_A:
                return self._select_used()
            if k == Qt.Key.Key_Z:
                return self.undo()
            if k == Qt.Key.Key_Y:
                return self.redo()
            if k == Qt.Key.Key_B:
                return self.command.emit("bold")
            if k == Qt.Key.Key_I:
                return self.command.emit("italic")
            if k == Qt.Key.Key_1:
                return self.command.emit("format")
            if k == Qt.Key.Key_Home:
                return self.move_to(1, 1, extend=shift)
            if k == Qt.Key.Key_End:
                mr, mc = self.wb.extent(self.sheet)
                return self.move_to(max(1, mr), max(1, mc), extend=shift)
            if k in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
                return self._jump(k, shift)
            if k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) and shift:
                return self.command.emit("insert")
            if k == Qt.Key.Key_Minus:
                return self.command.emit("delete")
            return super().keyPressEvent(ev)
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.sel_chart:
                return self.delete_chart(self.sel_chart)
            return self.clear_selection()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return self._step(-1 if shift else 1, 0)
        if k == Qt.Key.Key_Tab:
            return self._step(0, 1)
        if k == Qt.Key.Key_Backtab:
            return self._step(0, -1)
        if k == Qt.Key.Key_F2:
            return self.begin_edit(None, enter_mode=False)
        if k == Qt.Key.Key_Escape:
            if self.copied:
                self.copied = None
                self.viewport().update()
            return
        fr, fc = (self.er, self.ec) if shift else (self.r, self.c)           # arrows start from the moving corner when extending
        page = max(1, (self.viewport().height() - self.hh) // DEF_H - 1)
        if k == Qt.Key.Key_Up:
            return self.move_to(fr - 1, fc, extend=shift)
        if k == Qt.Key.Key_Down:
            return self.move_to(fr + 1, fc, extend=shift)
        if k == Qt.Key.Key_Left:
            return self.move_to(fr, fc - 1, extend=shift)
        if k == Qt.Key.Key_Right:
            return self.move_to(fr, fc + 1, extend=shift)
        if k == Qt.Key.Key_PageDown:
            return self.move_to(fr + page, fc, extend=shift)
        if k == Qt.Key.Key_PageUp:
            return self.move_to(fr - page, fc, extend=shift)
        if k == Qt.Key.Key_Home:
            return self.move_to(fr, 1, extend=shift)
        if k == Qt.Key.Key_End:
            return self.move_to(fr, self.wb.extent(self.sheet)[1] or 1, extend=shift)
        text = ev.text()
        if text and text.isprintable() and not (mods & Qt.KeyboardModifier.AltModifier):
            self.begin_edit(text, enter_mode=True)
            return
        super().keyPressEvent(ev)

    def _select_used(self):
        mr, mc = self.wb.extent(self.sheet)
        self.select(1, 1, max(1, mr), max(1, mc))

    def _step(self, dr, dc):
        """Enter / Tab with a block selected moves inside the block (and round it), like Excel; with one cell it moves one cell."""
        r1, c1, r2, c2 = self.sel()
        if (r1, c1) == (r2, c2):
            return self.move_to(self.r + dr, self.c + dc)
        r, c = self.r + dr, self.c + dc
        if r > r2:
            r, c = r1, c + 1
        if r < r1:
            r, c = r2, c - 1
        if c > c2:
            c, r = c1, r + (1 if dr else 0)
        if c < c1:
            c = c2
        if r > r2 or c > c2 or r < r1 or c < c1:
            r, c = r1, c1
        self.r, self.c = r, c                           # the block stays selected; only the active cell moves inside it
        self.ensure_visible(r, c)
        self.viewport().update()
        self.selection_changed.emit()

    def _jump(self, key, extend):
        """Ctrl + arrow: to the edge of the block of filled cells, or to the next filled cell."""
        dr = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(key, 0)
        dc = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(key, 0)
        s = self.sheet_obj()

        def filled(r, c):
            x = s.cells.get((r, c))
            return x is not None and x.raw is not None
        mr, mc = self.wb.extent(self.sheet)
        r, c = (self.er, self.ec) if extend else (self.r, self.c)
        limit_r, limit_c = (E.MAXROW, E.MAXCOL)
        steps = 0
        if filled(r, c) and filled(r + dr, c + dc):
            while 1 <= r + dr <= limit_r and 1 <= c + dc <= limit_c and filled(r + dr, c + dc):
                r, c = r + dr, c + dc
        else:
            r, c = r + dr, c + dc
            while 1 <= r <= limit_r and 1 <= c <= limit_c and not filled(r, c):
                r, c = r + dr, c + dc
                steps += 1
                if (dr > 0 and r > mr) or (dc > 0 and c > mc):
                    r, c = (limit_r if dr > 0 else r), (limit_c if dc > 0 else c)
                    break
            r, c = max(1, min(r, limit_r)), max(1, min(c, limit_c))
        if r > E.MAXROW - 1 and dr > 0:
            r = max(mr, r if r < E.MAXROW else 1)
        if c > E.MAXCOL - 1 and dc > 0:
            c = max(mc, c if c < E.MAXCOL else 1)
        self.move_to(r, c, extend=extend)

    # ------------------------------------------------------------------ the operations (also called by the ribbon)
    def undo(self):
        if self.edit is not None:
            return
        if self.wb.undo():
            self.message.emit("Undid " + (self.wb.redo_label() or "the change"), "")
            self.viewport().update()
            self.selection_changed.emit()

    def redo(self):
        if self.edit is not None:
            return
        if self.wb.redo():
            self.message.emit("Redid " + (self.wb.undo_label() or "the change"), "")
            self.viewport().update()
            self.selection_changed.emit()

    def clear_selection(self, styles=False):
        self.wb.begin("Clear")                                 # one undo step for every block
        for rect in self.rects():
            self.wb.clear(self.sheet, rect, styles=styles)
        self.wb.end()
        self.viewport().update()
        self.selection_changed.emit()

    def selection_text(self, rects=None):
        """The selected cells as tab-separated text.  Several blocks join up when they share their rows (side by side) or their columns (one under the other)."""
        rects = rects or [self.sel()]
        layout = _layout(rects)
        if layout is None:
            rects, layout = [rects[-1]], "row"
        if layout == "col":
            lines = []
            for r1, c1, r2, c2 in rects:
                for r in range(r1, min(r2, r1 + 20000) + 1):
                    lines.append("\t".join(self.wb.display(self.sheet, r, c) for c in range(c1, min(c2, c1 + 400) + 1)))
            return "\n".join(lines)
        r1, r2 = rects[0][0], rects[0][2]
        lines = []
        for r in range(r1, min(r2, r1 + 20000) + 1):
            lines.append("\t".join(self.wb.display(self.sheet, r, c) for a in rects for c in range(a[1], min(a[3], a[1] + 400) + 1)))
        return "\n".join(lines)

    def copy(self, cut=False):
        rects = self.rects()
        layout = _layout(rects)
        if len(rects) > 1:
            if cut:
                self.message.emit("Cut does not work on several blocks. Copy them instead.", "warn")
                return
            if layout is None:
                self.message.emit("Copy needs blocks that are in the same rows or in the same columns.", "warn")
                return
            rects = sorted(rects, key=(lambda a: a[1]) if layout == "row" else (lambda a: a[0]))
        md = QMimeData()
        md.setText(self.selection_text(rects))
        md.setData(MIME, json.dumps({"token": TOKEN, "sheet": self.sheet, "rect": list(rects[-1]), "rects": [list(a) for a in rects], "layout": layout or "row",
                                     "cut": cut}).encode("utf-8"))
        QGuiApplication.clipboard().setMimeData(md)
        self.copied = (self.sheet, rects, cut)
        self.viewport().update()
        name = self._rect_name(rects[0]) if len(rects) == 1 else f"{len(rects)} blocks"
        self.message.emit(("Cut " if cut else "Copied ") + name + ": choose where it goes, then Paste.", "")

    def _rect_name(self, rect):
        r1, c1, r2, c2 = rect
        return E.addr(r1, c1) if (r1, c1) == (r2, c2) else f"{E.addr(r1, c1)}:{E.addr(r2, c2)}"

    def paste(self, what="all"):
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return
        wb = self.wb
        r1, c1, r2, c2 = self.sel()
        info = None
        if md.hasFormat(MIME):
            try:
                info = json.loads(bytes(md.data(MIME)).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                info = None
        if info and info.get("token") == TOKEN and wb.get_sheet(info["sheet"]) is not None and len(info.get("rects") or []) > 1:
            blocks = [tuple(a) for a in info["rects"]]
            wb.begin("Paste")
            at_r, at_c = r1, c1
            end_r, end_c = r1, c1
            for src in blocks:
                h, w = src[2] - src[0] + 1, src[3] - src[1] + 1
                if at_r + h - 1 > E.MAXROW or at_c + w - 1 > E.MAXCOL:
                    break
                wb.copy_cells(info["sheet"], src, self.sheet, at_r, at_c, what)
                end_r, end_c = max(end_r, at_r + h - 1), max(end_c, at_c + w - 1)
                if info.get("layout") == "col":
                    at_r += h
                else:
                    at_c += w
            wb.end()
            self.select(r1, c1, end_r, end_c, active=(r1, c1))
            return
        if info and info.get("token") == TOKEN and wb.get_sheet(info["sheet"]) is not None:
            src = tuple(info["rect"])
            sh, cut = info["sheet"], bool(info["cut"])
            h, w = src[2] - src[0] + 1, src[3] - src[1] + 1
            if cut and what == "all":
                wb.begin_group("Move cells")                             # the formulas, names and charts that point at the cells follow them: one undo step
            wb.begin("Paste")
            if (h, w) == (1, 1) and (r2 > r1 or c2 > c1) and not cut:           # one cell over a block: every cell of the block gets it
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        wb.copy_cells(sh, src, self.sheet, r, c, what)
                rect = (r1, c1, r2, c2)
            else:
                rect = wb.copy_cells(sh, src, self.sheet, r1, c1, what, cut=cut and what == "all")
            wb.end()
            if cut and what == "all":
                wb.end_group()
            if cut:
                self.copied = None
                QGuiApplication.clipboard().clear()
            self.select(*rect, active=(rect[0], rect[1]))
            return
        text = md.text() if md.hasText() else ""
        if not text:
            return
        lines = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
        wb.begin("Paste")
        n = 0
        for i, line in enumerate(lines):
            for j, part in enumerate(line.split("\t")):
                if r1 + i <= E.MAXROW and c1 + j <= E.MAXCOL:
                    self._put_text(r1 + i, c1 + j, part, what)
                    n += 1
        wb.end()
        self.select(r1, c1, r1 + len(lines) - 1, c1 + max(len(x.split("\t")) for x in lines) - 1, active=(r1, c1))

    def _put_text(self, r, c, part, what):
        raw, hint = B.parse_entry(part)
        if what == "formats":
            return
        st = ...
        if hint and what == "all":
            st = B.style_of(fmt=hint)
        self.wb.set_raw(self.sheet, r, c, raw, st)

    def fill_down(self):
        self.wb.begin("Fill down")
        for r1, c1, r2, c2 in self.rects():
            if r2 > r1:
                self.wb.fill(self.sheet, (r1, c1, r1, c2), (r1 + 1, c1, r2, c2))
            elif r1 > 1:
                self.wb.fill(self.sheet, (r1 - 1, c1, r1 - 1, c2), (r1, c1, r1, c2))
        self.wb.end()
        self.viewport().update()
        self.selection_changed.emit()

    def fill_right(self):
        self.wb.begin("Fill right")
        for r1, c1, r2, c2 in self.rects():
            if c2 > c1:
                self.wb.fill(self.sheet, (r1, c1, r2, c1), (r1, c1 + 1, r2, c2))
            elif c1 > 1:
                self.wb.fill(self.sheet, (r1, c1 - 1, r2, c1 - 1), (r1, c1, r2, c1))
        self.wb.end()
        self.viewport().update()
        self.selection_changed.emit()

    def _finish_fill(self, src, pos):
        dst = self._fill_target(src, pos)
        if dst is None:
            return
        r1, c1, r2, c2 = src
        self.wb.fill(self.sheet, src, dst)
        self.select(r1, c1, max(r2, dst[2]), max(c2, dst[3]), active=(r1, c1))

    def _finish_move(self, d, pos, copy):
        """The block was dragged by its border and dropped at `pos`: move it (formulas, names and charts that point at the cells follow), or copy it with Ctrl."""
        self._moved_to = None
        src, press = d[1], d[3]
        r, c = self._move_target(d, pos)
        r1, c1, r2, c2 = src
        if (r, c) == (r1, c1):
            if self._cell_under(pos) == press:                       # a click on the border of the cell, not a drag
                self.move_to(*press)
            self.viewport().update()
            return
        h, w = r2 - r1 + 1, c2 - c1 + 1
        s = self.sheet_obj()
        clash = any((rr, cc) in s.cells and s.cells[(rr, cc)].raw is not None and not (copy is False and r1 <= rr <= r2 and c1 <= cc <= c2)
                    for rr in range(r, r + h) for cc in range(c, c + w)) if s and h * w <= MOVE_LIMIT else False
        if clash and QMessageBox.question(self, "Replace cells", "The cells you drop on already have something in them.\nReplace it?") != QMessageBox.StandardButton.Yes:
            self.viewport().update()
            return
        if copy:
            self.wb.copy_cells(self.sheet, src, self.sheet, r, c)
        else:
            self.wb.copy_cells(self.sheet, src, self.sheet, r, c, cut=True)
            self.copied = None
        self.select(r, c, r + h - 1, c + w - 1, active=(r, c))

    # ------------------------------------------------------------------ context menu
    def _context(self, pos, gpos, hit):
        s = self.sheet_obj()
        if hit is not None:
            r, c = hit
            if not any(a[0] <= r <= a[2] and a[1] <= c <= a[3] for a in self.rects()):
                self.move_to(r, c)
        elif pos.y() < self.hh and pos.x() >= self.hw:                  # a right-click on a column or row header selects it unless it already is
            c = self.cols.index_at(pos.x() - self.hw + self.x0)
            if not any(a[0] <= c <= a[1] for a in self.selected_cols()):
                self.select(1, c, self.nr, c)
        elif pos.x() < self.hw and pos.y() >= self.hh:
            r = self.rows.index_at(pos.y() - self.hh + self.y0)
            if not any(a[0] <= r <= a[1] for a in self.selected_rows()):
                self.select(r, 1, r, self.nc)
        menu = QMenu(self)
        if hit is not None:
            for text, fn in (("Cut", lambda: self.copy(True)), ("Copy", lambda: self.copy(False)), ("Paste", self.paste),
                             ("Paste special...", lambda: self.command.emit("paste_special")), (None, None),
                             ("Insert row", lambda: self.command.emit("insert_row")), ("Insert column", lambda: self.command.emit("insert_col")),
                             ("Delete row", lambda: self.command.emit("delete_row")), ("Delete column", lambda: self.command.emit("delete_col")), (None, None),
                             ("Clear contents", self.clear_selection), ("Format cells...", lambda: self.command.emit("format")), (None, None),
                             ("Insert chart from selection", lambda: self.command.emit("chart_new"))):
                if text is None:
                    menu.addSeparator()
                else:
                    menu.addAction(text, fn)
            ln = _link_at(s, *hit) if s else None
            if ln is not None:
                menu.addSeparator()
                menu.addAction("Refresh from study", lambda: self.command.emit("study_refresh"))
        elif pos.y() < self.hh:
            menu.addAction("Insert column", lambda: self.command.emit("insert_col"))
            menu.addAction("Delete column", lambda: self.command.emit("delete_col"))
            menu.addAction("Column width...", lambda: self.command.emit("col_width"))
            menu.addAction("Fit width to contents", self.autofit_selection)
        else:
            menu.addAction("Insert row", lambda: self.command.emit("insert_row"))
            menu.addAction("Delete row", lambda: self.command.emit("delete_row"))
        menu.exec(gpos)

    # ------------------------------------------------------------------ tooltips
    def viewportEvent(self, ev):
        if ev.type() == QEvent.Type.ToolTip:
            pos = ev.pos()
            hit = self.cell_at(pos)
            tip = ""
            if hit is not None:
                w = self.wb.warnings.get((self.sheet, hit[0], hit[1]))
                v = self.wb.value(self.sheet, hit[0], hit[1])
                if w:
                    tip = "\n".join(w)
                elif isinstance(v, E.Err):
                    tip = {"#DIV/0!": "Division by zero.", "#N/A": "A value is not available.", "#VALUE!": "A value is the wrong kind for this formula.",
                           "#REF!": "A cell the formula used is gone.", "#NAME?": "A function or name is not known.", "#NUM!": "A number is not valid here.",
                           "#CIRC!": "The formula uses its own result."}.get(v.code, v.code)
                else:
                    ln = _link_at(self.sheet_obj(), *hit)
                    if ln is not None:
                        tip = f"Imported from {ln.get('name', 'a study')}. Data > Refresh from study reads it again."
            if tip:
                QToolTip.showText(ev.globalPos(), tip, self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(ev)

    # ------------------------------------------------------------------ charts
    def _sync_charts(self):
        s = self.sheet_obj()
        want = {c["id"]: c for c in (s.charts if s else [])}
        for cid in list(self.frames):
            if cid not in want:
                f = self.frames.pop(cid)
                f.hide()
                f.deleteLater()
        for cid, ch in want.items():
            if cid not in self.frames:
                f = ChartFrame(self, ch)
                f.changed.connect(lambda _i: self.charts_changed.emit())
                f.edit_asked.connect(lambda i: self.command.emit("chart_edit:" + i))
                f.menu_asked.connect(self._chart_menu)
                f.picked.connect(self.pick_chart)
                self.frames[cid] = f
            self.frames[cid].place()
            self.frames[cid].show()
            self.frames[cid].raise_()
            self.frames[cid].later()
            self.frames[cid].update()
        if self.sel_chart not in self.frames:
            self.sel_chart = None

    def _place_charts(self):
        for f in self.frames.values():
            f.place()

    def refresh_charts(self):
        self._sync_charts()

    def reveal_chart(self, cid):
        """Scrolls so the chart can be seen (the side panel took some of the width)."""
        ch = next((c for c in (self.sheet_obj().charts if self.sheet_obj() else []) if c.get("id") == cid), None)
        if ch is None:
            return
        x, y = ch.get("pos", [40, 40])
        w, h = ch.get("size", sh_chart.DEFAULT_SIZE)
        vw, vh = self.viewport().width() - self.hw, self.viewport().height() - self.hh
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        if x + w > self.x0 + vw or x < self.x0:
            hb.setValue(int(max(0, min(x - 10, x + w - vw + 10))))
        if y + h > self.y0 + vh or y < self.y0:
            vb.setValue(int(max(0, min(y - 10, y + h - vh + 10))))

    def pick_chart(self, cid):
        self.sel_chart = cid
        for i, f in self.frames.items():
            f.selected = i == cid
            f.update()
        self.viewport().update()
        self.selection_changed.emit()

    def delete_chart(self, cid):
        s = self.sheet_obj()
        s.charts = [c for c in s.charts if c.get("id") != cid]
        self.sel_chart = None
        self._sync_charts()
        self.charts_changed.emit()

    def _chart_menu(self, cid, gpos):
        menu = QMenu(self)
        menu.addAction("Edit chart...", lambda: self.command.emit("chart_edit:" + cid))
        menu.addAction("Export chart...", lambda: self.command.emit("chart_export:" + cid))
        menu.addAction("Duplicate", lambda: self.command.emit("chart_copy:" + cid))
        menu.addSeparator()
        menu.addAction("Delete chart", lambda: self.delete_chart(cid))
        menu.exec(gpos)

    def add_chart(self, ch):
        """Puts a chart in the sheet (just right of the used area unless it has a place) and shows it."""
        s = self.sheet_obj()
        s.charts.append(ch)
        self._sync_charts()
        self.pick_chart(ch["id"])
        self.charts_changed.emit()

    def default_chart_pos(self, rect=None):
        mr, mc = self.wb.extent(self.sheet)
        c = (rect[3] if rect else mc) + 2
        r = rect[0] if rect else 1
        return [self.cols.pos(c), self.rows.pos(r)]


def _layout(rects):
    """How several copied blocks join up: "row" when they all have the same rows (side by side), "col" when they all have the same columns (one under the
    other); a single block is "row"; None when they do not line up."""
    if len(rects) == 1:
        return "row"
    if len({(a[0], a[2]) for a in rects}) == 1:
        return "row"
    if len({(a[1], a[3]) for a in rects}) == 1:
        return "col"
    return None


def _runs(spans):
    """[(first, last), ...] in any order -> the same spans merged where they touch or overlap, sorted."""
    out = []
    for a, b in sorted((min(x), max(x)) for x in spans):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _link_at(sheet_obj, r, c):
    for ln in sheet_obj.links:
        r0, c0 = ln["origin"]
        if r0 <= r <= r0 + ln.get("rows", 0) and c0 <= c < c0 + ln.get("cols", 0):
            return ln
    return None
