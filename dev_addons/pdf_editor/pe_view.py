"""pe_view.py - the page viewer of the reader: every page of one PDF one under the other, zoom, click a sentence, drag to select, right-click.

Only the pages that are on screen are drawn (a page image is made the first time it is painted; the last few are kept), so a long book opens at once.
The viewer knows nothing about speech or saving: it asks its tab (the controller) for what a click should do.  What the tab must offer:
    tab.doc, tab.text (a pe_text.DocText), tab.edits (a pe_pdfio.Edits)
    tab.sentence_clicked(i), tab.play_requested(i), tab.highlight_selection(name), tab.remove_highlight(pno, xref), tab.copy_selection(),
    tab.toggle_play(), tab.step(d), tab.view_changed()
and, when it has them, tab.ai_clicked(word): a click on a word (the AI check shows its result for that paragraph).
"""
import bisect
from collections import OrderedDict

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QPushButton, QScrollArea, QWidget

import pe_pdfio as pio
import ui_kit

GAP, PAD = 14, 24
LOGICAL_PX_PER_PT = 96.0 / 72.0
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.4, 4.0, 1.15
MAX_IMAGES = 10
MAX_PIXELS = 40_000_000                    # no page image larger than this, however far you zoom in

READ_FILL = QColor(255, 170, 0, 85)
READ_EDGE = QColor(230, 140, 0, 200)
SEL_FILL = QColor(43, 125, 233, 80)
AI_NONE = QColor(40, 160, 130, 26)         # a paragraph the AI check looked at, where none of the tests leans AI
AI_EDGE = QColor(150, 40, 190, 230)        # the outline of the paragraph whose result is shown
PAGE_EDGE = QColor("#aab3c2")
SHADOW = QColor(40, 50, 70, 55)


class Popup(QFrame):
    """The little bar next to a selection: four highlight colours and Copy."""

    def __init__(self, view):
        super().__init__(view.sheet)
        self.setObjectName("selpop")
        self.setStyleSheet("QFrame#selpop { background:#ffffff; border:1px solid #b9c2d0; border-radius:8px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(5)
        for name, rgb in pio.COLORS.items():
            b = QPushButton("")
            b.setFixedSize(24, 24)
            b.setToolTip("Highlight " + name.lower())
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            col = pio.hex_color(rgb)
            b.setStyleSheet(f"QPushButton {{ background:{col}; border:1px solid #7b8798; border-radius:12px; }}"
                            f"QPushButton:hover {{ border:2px solid #2b7de9; }}")
            b.clicked.connect(lambda _c=False, n=name: view.tab.highlight_selection(n))
            lay.addWidget(b)
        c = QPushButton("Copy")
        c.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        c.clicked.connect(lambda _c=False: view.tab.copy_selection())
        lay.addWidget(c)
        self.adjustSize()


class Sheet(QWidget):
    """The tall widget inside the scroll area: it paints the pages that are in view and takes the mouse."""

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.view.paint(p, ev.rect())
        except Exception:                                       # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def mousePressEvent(self, ev):
        self.view.press(ev)

    def mouseMoveEvent(self, ev):
        self.view.motion(ev)

    def mouseReleaseEvent(self, ev):
        self.view.release(ev)

    def mouseDoubleClickEvent(self, ev):
        self.view.double(ev)

    def contextMenuEvent(self, ev):
        self.view.context(ev)

    def wheelEvent(self, ev):
        mods = ev.modifiers()
        dy = ev.angleDelta().y()
        if mods & Qt.KeyboardModifier.ControlModifier and dy:
            self.view.zoom_by(ZOOM_STEP if dy > 0 else 1 / ZOOM_STEP, anchor=ev.position())
            ev.accept()
        elif mods & Qt.KeyboardModifier.ShiftModifier and dy:
            bar = self.view.horizontalScrollBar()
            bar.setValue(bar.value() - (1 if dy > 0 else -1) * bar.singleStep() * 3)
            ev.accept()
        else:
            ev.ignore()                                         # the scroll area scrolls


class PdfView(QScrollArea):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.zoom = 1.0
        self.sel = None                          # (first word, last word)
        self.read_idx = None                     # the sentence marker / the sentence being spoken
        self.ai_marks = []                       # the AI check: [(page, (x0, y0, x1, y1), strength 0..1, paragraph)] - view only, never written into the PDF
        self.ai_focus = None                     # ... and the paragraph whose result is shown
        self.page_y, self.page_x, self.page_w, self.page_h = [], [], [], []
        self.total_h, self.total_w, self.content_w = 1, 1, 1
        self.images = OrderedDict()
        self.popup = None
        self._drag = None
        self._dragged = False
        self._anchor = None
        self._ignore_release = False
        self._page = 0
        self.sheet = Sheet(self)
        self.setWidget(self.sheet)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(f"QScrollArea {{ background:{ui_kit.BG}; }}")
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setSingleStep(40)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.layout_pages()

    # ------------------------------------------------------------------ geometry
    @property
    def scale(self):
        """Logical pixels per PDF point."""
        return self.zoom * LOGICAL_PX_PER_PT

    def layout_pages(self, keep_frac=None):
        """Sizes every page for the zoom and stacks them.  keep_frac: the fraction of the document that was at the top of the window."""
        s = self.scale
        self.page_w, self.page_h, self.page_y = [], [], []
        y = PAD
        doc = self.tab.doc
        for i in range(doc.page_count):
            r = doc[i].rect
            w, h = r.width * s, r.height * s
            self.page_w.append(w)
            self.page_h.append(h)
            self.page_y.append(y)
            y += h + GAP
        self.total_h = max(1, int(y - GAP + PAD))
        self.total_w = int((max(self.page_w) if self.page_w else 0) + 2 * PAD)
        self.images.clear()
        self.recenter()
        if keep_frac is not None:
            self.verticalScrollBar().setValue(int(keep_frac * self.total_h))

    def recenter(self):
        """The pages sit in the middle when the window is wider than they are."""
        cw = max(self.viewport().width(), 1)
        self.content_w = max(self.total_w, cw)
        self.page_x = [(self.content_w - w) / 2 for w in self.page_w]
        self.sheet.setFixedSize(self.content_w, self.total_h)
        self.sheet.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.size().width() != ev.oldSize().width():
            self.recenter()

    def top_fraction(self):
        return self.verticalScrollBar().value() / max(1, self.total_h)

    def set_zoom(self, z):
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if abs(z - self.zoom) < 1e-3:
            return False
        frac = self.top_fraction()
        self.zoom = z
        self._hide_popup()
        self.layout_pages(keep_frac=frac)
        self.tab.view_changed()
        return True

    def zoom_by(self, f, anchor=None):
        self.set_zoom(self.zoom * f)

    def fit_width(self):
        if not self.page_w:
            return
        avail = max(200, self.viewport().width() - 2 * PAD - 4)
        widest_pt = max(self.tab.doc[i].rect.width for i in range(self.tab.doc.page_count))
        self.set_zoom(avail / (widest_pt * LOGICAL_PX_PER_PT))

    # ------------------------------------------------------------------ where things are
    def page_at(self, y):
        return max(0, min(len(self.page_y) - 1, bisect.bisect_right(self.page_y, y) - 1)) if self.page_y else 0

    def current_page(self):
        if not self.page_y:
            return 0
        return self.page_at(self.verticalScrollBar().value() + self.viewport().height() * 0.4)

    def top_point(self):
        """(page, y in points) at the top edge of the window."""
        top = self.verticalScrollBar().value()
        pno = self.page_at(top)
        return pno, (top - self.page_y[pno]) / self.scale

    def locate(self, pos):
        """A point of the sheet -> (page, x in points, y in points)."""
        if not self.page_y:
            return None
        i = self.page_at(pos.y())
        s = self.scale
        return i, (pos.x() - self.page_x[i]) / s, (pos.y() - self.page_y[i]) / s

    def to_sheet(self, pno, r):
        s = self.scale
        px, py = self.page_x[pno], self.page_y[pno]
        return QRectF(px + r[0] * s, py + r[1] * s, (r[2] - r[0]) * s, (r[3] - r[1]) * s)

    def _scrolled(self, _v):
        p = self.current_page()
        if p != self._page:
            self._page = p
            self.tab.view_changed()

    def scroll_to(self, y):
        h = max(1, self.viewport().height())
        self.verticalScrollBar().setValue(int(max(0, min(y, self.total_h - h))))

    def scroll_to_page(self, pno):
        if self.page_y:
            self.scroll_to(self.page_y[max(0, min(pno, len(self.page_y) - 1))] - 10)

    def ensure_visible(self, idx):
        text = self.tab.text
        if not text.ready or not text.sentences:
            return
        rects = text.sentence_rects(idx)
        if not rects:
            return
        p0, r0 = rects[0]
        p1, r1 = rects[-1]
        ytop = self.page_y[p0] + r0[1] * self.scale
        ybot = self.page_y[p1] + r1[3] * self.scale
        top = self.verticalScrollBar().value()
        h = max(1, self.viewport().height())
        if ytop < top + 24 or ybot > top + h - 24:
            self.scroll_to(ytop - h * 0.25)

    # ------------------------------------------------------------------ the marker
    def set_read(self, idx, scroll=True):
        self.read_idx = idx
        self.sheet.update()
        if scroll and idx is not None:
            self.ensure_visible(idx)

    def start_sentence(self):
        """Where Play begins: the marker, else the first sentence at the top of the window."""
        text = self.tab.text
        if not text.ready or not text.sentences:
            return None
        if self.read_idx is not None and self.read_idx < len(text.sentences):
            return self.read_idx
        pno, y_pt = self.top_point()
        return text.first_sentence_from(pno, y_pt)

    # ------------------------------------------------------------------ painting
    def image(self, pno):
        img = self.images.get(pno)
        if img is not None:
            self.images.move_to_end(pno)
            return img
        pm = pio.pymupdf
        w_pt, h_pt = self.page_w[pno] / self.scale, self.page_h[pno] / self.scale
        s = self.scale * max(1.0, self.devicePixelRatioF())
        if s * s * w_pt * h_pt > MAX_PIXELS:
            s = (MAX_PIXELS / (w_pt * h_pt)) ** 0.5
        try:
            pix = self.tab.doc[pno].get_pixmap(matrix=pm.Matrix(s, s), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        except Exception:                                        # noqa: BLE001 - a page that cannot be drawn is shown blank, not as a crash
            return None
        self.images[pno] = img
        while len(self.images) > MAX_IMAGES:
            self.images.popitem(last=False)
        return img

    def refresh_pages(self, pages):
        for i in pages:
            self.images.pop(i, None)
        self.sheet.update()

    def paint(self, p, clip):
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.page_y:
            return
        first = self.page_at(clip.top())
        last = self.page_at(clip.bottom())
        for i in range(first, last + 1):
            x, y, w, h = self.page_x[i], self.page_y[i], self.page_w[i], self.page_h[i]
            if y + h < clip.top() or y > clip.bottom():
                continue
            target = QRectF(x, y, w, h)
            p.fillRect(QRectF(x + 3, y + 3, w, h), SHADOW)
            p.fillRect(target, QColor("white"))
            img = self.image(i)
            if img is not None:
                p.drawImage(target, img)
            else:
                p.setPen(QColor("#8a93a3"))
                p.drawText(target, Qt.AlignmentFlag.AlignCenter, "This page could not be drawn.")
            p.setPen(QPen(PAGE_EDGE, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(target)
        self.paint_overlays(p, first, last)

    @staticmethod
    def ai_fill(strength):
        """No test leaning AI: a faint green; the more of the tests lean AI, the deeper the purple."""
        if strength <= 0:
            return AI_NONE
        return QColor(150, 40, 190, int(40 + 95 * min(1.0, strength)))

    def paint_overlays(self, p, first, last):
        text = self.tab.text
        if not text.ready:
            return
        if self.ai_marks:
            p.setPen(Qt.PenStyle.NoPen)
            for pno, r, strength, k in self.ai_marks:
                if first <= pno <= last:
                    p.setBrush(self.ai_fill(strength))
                    p.drawRect(self.to_sheet(pno, r))
            if self.ai_focus is not None:
                p.setPen(QPen(AI_EDGE, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                for pno, r, strength, k in self.ai_marks:
                    if k == self.ai_focus and first <= pno <= last:
                        p.drawRect(self.to_sheet(pno, r).adjusted(-2, -1, 2, 1))
        if self.read_idx is not None and self.read_idx < len(text.sentences):
            p.setPen(QPen(READ_EDGE, 1))
            p.setBrush(READ_FILL)
            for pno, r in text.sentence_rects(self.read_idx):
                if first <= pno <= last:
                    q = self.to_sheet(pno, r).adjusted(-2, -1, 2, 1)
                    p.drawRoundedRect(q, 2, 2)
        if self.sel:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(SEL_FILL)
            for pno, r in text.rects_for_tokens(*self.sel):
                if first <= pno <= last:
                    p.drawRect(self.to_sheet(pno, r))

    # ------------------------------------------------------------------ the mouse
    def token_under(self, pos, max_d):
        loc = self.locate(pos)
        if not loc or not self.tab.text.ready:
            return None
        return self.tab.text.token_at(loc[0], loc[1], loc[2], max_d)

    def _hide_popup(self):
        if self.popup is not None:
            self.popup.hide()
            self.popup.deleteLater()
            self.popup = None

    def press(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        self._hide_popup()
        self._drag = ev.position()
        self._dragged = False
        self._ignore_release = False
        self._anchor = None

    def motion(self, ev):
        if self._drag is None:
            return
        pos = ev.position()
        if not self._dragged:
            if abs(pos.x() - self._drag.x()) + abs(pos.y() - self._drag.y()) < 5:
                return
            self._dragged = True
            self._anchor = self.token_under(self._drag, 40)
        if self._anchor is None:
            return
        bar = self.verticalScrollBar()
        top, h = bar.value(), self.viewport().height()
        if pos.y() < top:
            bar.setValue(bar.value() - bar.singleStep())
        elif pos.y() > top + h:
            bar.setValue(bar.value() + bar.singleStep())
        t = self.token_under(QPointF(pos.x(), max(0.0, min(pos.y(), self.total_h - 1.0))), 60)
        if t is not None:
            a, b = sorted((self._anchor, t))
            if self.sel != (a, b):
                self.sel = (a, b)
                self.sheet.update()
                self.tab.selection_changed()

    def release(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        was_drag, self._drag = self._dragged, None
        if self._ignore_release:
            return
        if was_drag:
            if self.sel:
                self.show_popup()
            return
        t = self.token_under(ev.position(), 8)
        had = self.sel is not None
        if had:
            self.sel = None
            self.tab.selection_changed()
        if t is not None:
            self.set_read(self.tab.text.tok2sent[t], scroll=False)
            self.tab.sentence_clicked(self.read_idx)
        elif had:
            self.sheet.update()
        ai = getattr(self.tab, "ai_clicked", None)
        if ai is not None:
            ai(t)

    def double(self, ev):
        self._ignore_release = True
        t = self.token_under(ev.position(), 8)
        if t is not None:
            self.clear_selection()
            self.tab.play_requested(self.tab.text.tok2sent[t])

    def context(self, ev):
        pos = QPointF(ev.pos())
        loc = self.locate(pos)
        menu = QMenu(self)
        if self.sel:
            menu.addAction("Copy text", lambda: self.tab.copy_selection())
            for name in pio.COLORS:
                menu.addAction("Highlight " + name.lower(), lambda n=name: self.tab.highlight_selection(n))
        if loc:
            t = self.tab.text.token_at(loc[0], loc[1], loc[2], 10) if self.tab.text.ready else None
            if t is not None:
                if not menu.isEmpty():
                    menu.addSeparator()
                i = self.tab.text.tok2sent[t]
                menu.addAction("Read from here", lambda: self.tab.play_requested(i))
                menu.addAction("Set reading start here", lambda: (self.set_read(i, scroll=False), self.tab.sentence_clicked(i)))
            xref = self.tab.edits.find(loc[0], loc[1], loc[2])
            if xref:
                if not menu.isEmpty():
                    menu.addSeparator()
                menu.addAction("Remove highlight", lambda: self.tab.remove_highlight(loc[0], xref))
        if not menu.isEmpty():
            menu.exec(ev.globalPos())

    # ------------------------------------------------------------------ selection
    def show_popup(self):
        self._hide_popup()
        rects = self.tab.text.rects_for_tokens(*self.sel)
        pno, r = rects[-1]
        q = self.to_sheet(pno, r)
        self.popup = Popup(self)
        x = min(q.right() + 6, self.content_w - self.popup.width() - 4)
        self.popup.move(int(max(4, x)), int(q.bottom() + 6))
        self.popup.show()

    def clear_selection(self):
        had = self.sel is not None
        self.sel = None
        self._hide_popup()
        self.sheet.update()
        if had:
            self.tab.selection_changed()

    # ------------------------------------------------------------------ keys
    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key.Key_Space:
            self.tab.toggle_play()
        elif k == Qt.Key.Key_Right:
            self.tab.step(1)
        elif k == Qt.Key.Key_Left:
            self.tab.step(-1)
        elif k == Qt.Key.Key_Escape:
            self.clear_selection()
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(ZOOM_STEP)
        elif k == Qt.Key.Key_Minus and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1 / ZOOM_STEP)
        else:
            super().keyPressEvent(ev)
