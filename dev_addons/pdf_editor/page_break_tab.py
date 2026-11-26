"""page_break_tab.py - the Page Break tab: cut long PDF pages into normal-sized pages and combine pages of several PDFs into one file.

Left: numbered sections (Pages, Breaks, Export) with the Export button pinned underneath.  Right: every imported page as an image.  Click a page to
drop a break line, click a break line to remove it, click a segment's label to leave that segment out of the export.  Project files: .oppb (JSON;
it keeps the list of PDFs, their breaks and what is excluded - the PDFs themselves stay where they are).
"""
import json
import os
import threading
from collections import OrderedDict

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen
from PyQt6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                             QStackedWidget, QVBoxLayout, QWidget)

import pb_core as core
import pb_deps
import ui_kit

PDF_FILTER = "PDF files (*.pdf);;All files (*)"
PROJECT_FILTER = "Page Break project (*.oppb);;All files (*)"
CHIP = "#c8402f"

BREAK = QColor("#d9480f")
BAND_ODD = QColor(43, 125, 233, 34)
BAND_EXCLUDED = QColor(120, 128, 140, 120)
LABEL_BG = QColor(255, 255, 255, 225)
LABEL_INK = QColor("#1f2a3c")
LABEL_OFF = QColor("#8a93a3")


# ------------------------------------------------------------------------------------------------------------- one page
class PageCanvas(QWidget):
    """The picture of one source page with its breaks and segment labels drawn over it.  The image is rendered the first time the widget is
    painted (a long document does not render pages nobody has scrolled to)."""

    def __init__(self, tab, item):
        super().__init__()
        self.tab, self.item = tab, item
        self.image = None
        self.scale = 1.0
        self.hover_y = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.resize_for_zoom()

    # ------------------------------------------------------------------ size and image
    def resize_for_zoom(self):
        self.scale, w, h = core.display_scale(self.item.width_pt, self.item.height_pt, self.tab.zoom)
        self.image = None
        self.tab.forget_image(self)
        self.setFixedSize(w, h)
        self.update()

    def ensure_image(self):
        if self.image is not None:
            self.tab.touch_image(self)
            return True
        try:
            page = self.item.source.doc[self.item.page_index]
            m = core.fitz.Matrix(self.scale, self.scale)
            pix = page.get_pixmap(matrix=m, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        except Exception:                                       # noqa: BLE001 - a page that cannot be drawn is shown blank, not as a crash
            return False
        self.image = img
        self.tab.touch_image(self)
        return True

    def drop_image(self):
        self.image = None

    # ------------------------------------------------------------------ geometry of the overlay (also used for clicks)
    def segments(self):
        for it, segs in self.tab.project.numbered():
            if it is self.item:
                return segs
        return []

    def label_text(self, seg):
        inches = (seg["to"] - seg["from"]) / 72
        if seg["excluded"]:
            return f"☒  excluded · {inches:.2f} in"
        return f"☐  Page {seg['out_index']} · {inches:.2f} in"

    def label_rect(self, seg):
        """Where the label of a segment sits (a rounded box centred in the segment), or None when the segment is too short to hold one."""
        top, bot = seg["from"] * self.scale, seg["to"] * self.scale
        f = QFont(self.font())
        f.setPixelSize(12)
        fm = QFontMetricsF(f)
        w, h = fm.horizontalAdvance(self.label_text(seg)) + 16, 22.0
        if bot - top < h + 2:
            return None
        cx, cy = self.width() / 2, (top + bot) / 2
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def hit_label(self, pos):
        for i, seg in enumerate(self.segments()):
            r = self.label_rect(seg)
            if r is not None and r.contains(QPointF(pos)):
                return i
        return None

    def near_break(self, y_px):
        return any(abs(b * self.scale - y_px) <= core.SNAP_PX for b in self.item.breaks)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        i = self.hit_label(pos)
        if i is not None:
            self.tab.exclude_segment(self.item, i)
            return
        self.tab.click_page(self.item, pos.y(), self.scale)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        self.hover_y = pos.y()
        over_label = self.hit_label(pos) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if over_label else Qt.CursorShape.CrossCursor)
        if over_label:
            self.hover_y = None
        self.update()

    def leaveEvent(self, ev):
        self.hover_y = None
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            self.draw(p)
        except Exception:                                       # noqa: BLE001 - an error escaping a paint event would close the whole program
            pass
        finally:
            p.end()

    def draw(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        if self.ensure_image():
            p.drawImage(0, 0, self.image)
        else:
            p.setPen(QColor("#8a93a3"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "This page could not be drawn.")
        segs = self.segments()
        w = self.width()
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        for i, seg in enumerate(segs):
            top, bot = seg["from"] * self.scale, seg["to"] * self.scale
            if seg["excluded"]:
                p.fillRect(QRectF(0, top, w, bot - top), BAND_EXCLUDED)
            elif i % 2 == 0:
                p.fillRect(QRectF(0, top, w, bot - top), BAND_ODD)
        pen = QPen(BREAK, 2, Qt.PenStyle.DashLine)
        for b in self.item.breaks:
            y = b * self.scale
            p.setPen(pen)
            p.drawLine(QPointF(0, y), QPointF(w, y))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(BREAK)
            p.drawEllipse(QPointF(8, y), 5, 5)
        if self.hover_y is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            if self.near_break(self.hover_y):                   # a click here removes that break
                p.setPen(QPen(QColor(217, 72, 15, 90), 8))
                y = min(self.item.breaks, key=lambda b: abs(b * self.scale - self.hover_y)) * self.scale
                p.drawLine(QPointF(0, y), QPointF(w, y))
            elif core.EDGE_PT * self.scale < self.hover_y < self.height() - core.EDGE_PT * self.scale:
                p.setPen(QPen(QColor(217, 72, 15, 130), 1, Qt.PenStyle.DotLine))
                p.drawLine(QPointF(0, self.hover_y), QPointF(w, self.hover_y))
        for seg in segs:
            r = self.label_rect(seg)
            if r is None:
                continue
            p.setPen(QPen(QColor("#b9c2d0"), 1))
            p.setBrush(LABEL_BG)
            p.drawRoundedRect(r, 6, 6)
            p.setPen(LABEL_OFF if seg["excluded"] else LABEL_INK)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.label_text(seg))


class PageBlock(QWidget):
    """A page with its caption line: the file and page, the size, move up / down and remove."""

    def __init__(self, tab, item):
        super().__init__()
        self.item = item
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 22)
        lay.setSpacing(4)
        head = QHBoxLayout()
        cap = QLabel(item.caption())
        cap.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        head.addWidget(cap)
        dims = QLabel(item.size_text())
        dims.setStyleSheet(f"color:{ui_kit.FAINT};")
        head.addWidget(dims)
        head.addStretch(1)
        for text, tip, fn in (("▲", "Move this page up", lambda: tab.move_page(item, -1)),
                              ("▼", "Move this page down", lambda: tab.move_page(item, 1)),
                              ("Remove", "Take this page out of the export", lambda: tab.remove_page(item))):
            b = QPushButton(text)
            b.setToolTip(tip)
            if len(text) == 1:
                b.setFixedWidth(30)
            b.clicked.connect(lambda _c=False, f=fn: f())
            head.addWidget(b)
        lay.addLayout(head)
        self.canvas = PageCanvas(tab, item)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(self.canvas)
        wrap.addStretch(1)
        lay.addLayout(wrap)


class SetupSignals(QObject):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)


# ------------------------------------------------------------------------------------------------------------- the tab
class PageBreakTab(QWidget):
    MAX_CACHED_IMAGES = 14
    AUTO_SETUP = True                          # download PyMuPDF by itself when it is missing (a test turns this off)
    installer = None                           # a test can put its own downloader here (see pb_deps.install)

    def __init__(self, path=None, portable=False):
        super().__init__()
        self.path = None                       # the .oppb project file, when there is one
        self.portable = portable               # in a Workbench block: the PDFs next to the project file are written as relative paths
        self.keep = None                       # in a Workbench block: a PDF that is imported from elsewhere is copied into the block first (PdfEditorTab.keep)
        self.host = None
        self.dirty = False
        self.zoom = 1.0
        self.project = core.Project()
        self.blocks = {}                       # item id -> PageBlock
        self.images = OrderedDict()            # canvases that hold a rendered image, least recently used first

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.build_bar())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.build_panel())
        self.views = QStackedWidget()
        self.empty = ui_kit.EmptyState(
            "Cut and combine PDF pages",
            "Import a PDF, click anywhere on a page to drop a break, and import more files any time to build a bigger one.",
            [("Import PDF...", self.import_dialog)])
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(f"QScrollArea {{ background:{ui_kit.BG}; }}")
        self.inner = QWidget()
        self.inner.setStyleSheet(f"background:{ui_kit.BG};")
        self.col = QVBoxLayout(self.inner)
        self.col.setContentsMargins(18, 14, 18, 14)
        self.col.setSpacing(0)
        self.col.addStretch(1)
        self.scroll.setWidget(self.inner)
        self.setup = self.build_setup_page()
        self.setup_sig = SetupSignals()
        self.setup_sig.progress.connect(self.setup_text.setText)
        self.setup_sig.done.connect(self.setup_finished)
        self.setup_busy = False
        self.pending_path = None
        self.views.addWidget(self.empty)
        self.views.addWidget(self.scroll)
        self.views.addWidget(self.setup)
        split.addWidget(self.views)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 1000])
        lay.addWidget(split, 1)

        self.status = ui_kit.StatusLine("")
        lay.addWidget(self.status)
        self.refresh()
        if not core.available():
            self.pending_path = path
            self.dirty = False
            self.show_setup("Getting ready ...")
            if self.AUTO_SETUP:
                QTimer.singleShot(0, self.start_setup)
            else:
                self.show_setup("PyMuPDF is needed.", failed=True)
            return
        if path and os.path.isfile(path):
            self.open_path(path)
        self.dirty = False

    # ------------------------------------------------------------------ getting PyMuPDF (once, the first time)
    def build_setup_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)
        t = QLabel("Setting up Page Break")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"font-size:15px; font-weight:600; color:{ui_kit.INK};")
        lay.addWidget(t)
        self.setup_text = QLabel("")
        self.setup_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setup_text.setWordWrap(True)
        self.setup_text.setFixedWidth(480)
        self.setup_text.setStyleSheet(f"color:{ui_kit.MUTED};")
        lay.addWidget(self.setup_text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setup_retry = ui_kit.primary(QPushButton("Try again"))
        self.setup_retry.clicked.connect(lambda _c=False: self.start_setup())
        lay.addWidget(self.setup_retry, 0, Qt.AlignmentFlag.AlignHCenter)
        return w

    def show_setup(self, text, failed=False):
        self.views.setCurrentWidget(self.setup)
        self.setup_text.setText(text)
        self.setup_retry.setVisible(failed)
        self.status.say("")

    def start_setup(self):
        """Downloads PyMuPDF in a thread (the window stays alive); setup_finished() runs when it is done."""
        if self.setup_busy or core.available():
            return
        self.setup_busy = True
        self.show_setup("Downloading PyMuPDF, the library that reads and writes PDFs (about 20 MB, once). This needs an internet connection.")

        def work():
            try:
                pb_deps.install(lambda text, frac=None: self.setup_sig.progress.emit(text), self.installer)
                self.setup_sig.done.emit(True, "")
            except BaseException as e:                         # noqa: BLE001 - whatever went wrong is shown to the person, never raised in a thread
                self.setup_sig.done.emit(False, str(e))
        self.setup_thread = threading.Thread(target=work, daemon=True)
        self.setup_thread.start()

    def setup_finished(self, ok, message):
        self.setup_busy = False
        if ok and core.reload():
            self.views.setCurrentWidget(self.empty)
            self.refresh_numbers()
            self.status.say("PyMuPDF is ready.", "good")
            path, self.pending_path = self.pending_path, None
            if path and os.path.isfile(path):
                self.open_path(path)
            return
        self.show_setup("PyMuPDF could not be downloaded.\n\n" + (message.strip()[-600:] or "Check the internet connection and try again."), failed=True)

    # ------------------------------------------------------------------ building the window
    def build_bar(self):
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.addWidget(ui_kit.kind_chip("PDF", CHIP))
        self.title_lbl = QLabel("Page Break")
        self.title_lbl.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        h.addWidget(self.title_lbl)
        h.addSpacing(12)
        for text, tip, fn in (("New", "Remove every page and start over", self.new),
                              ("Import PDF...", "Add the pages of a PDF to the end", self.import_dialog),
                              ("Open project", "Open a .oppb Page Break project", self.open_dialog),
                              ("Save", "Save the project (Ctrl+S)", self.save),
                              ("Save as", "", self.save_as)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, f=fn: f())
            h.addWidget(b)
        h.addStretch(1)
        h.addWidget(QLabel("Zoom"))
        self.b_out = QPushButton("−")
        self.b_in = QPushButton("+")
        self.b_fit = QPushButton("Fit width")
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setMinimumWidth(44)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for b in (self.b_out, self.b_in):
            b.setFixedWidth(30)
        self.b_out.clicked.connect(lambda _c=False: self.set_zoom(self.zoom / core.ZOOM_STEP))
        self.b_in.clicked.connect(lambda _c=False: self.set_zoom(self.zoom * core.ZOOM_STEP))
        self.b_fit.clicked.connect(lambda _c=False: self.fit_width())
        for w in (self.b_out, self.zoom_lbl, self.b_in, self.b_fit):
            h.addWidget(w)
        return bar

    def build_panel(self):
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(6, 6, 6, 6)
        cl.setSpacing(4)
        self.sections = []

        def sec(n, title, summary=None, help_text=None):
            s = ui_kit.Section("pagebreak", n, title, True, help_text, summary)
            self.sections.append(s)
            cl.addWidget(s)
            return s.body

        # 1 pages
        v = sec(1, "Pages", summary=lambda: self.pages_lbl.text())
        self.pages_lbl = QLabel("")
        self.pages_lbl.setWordWrap(True)
        v.addWidget(self.pages_lbl)
        b = QPushButton("Import PDF...")
        b.clicked.connect(lambda _c=False: self.import_dialog())
        v.addWidget(b)
        v.addWidget(ui_kit.note("Every import adds its pages to the end of the list. Use the arrows on a page to change the order, and Remove to leave a page out."))

        # 2 breaks
        v = sec(2, "Breaks", summary=lambda: self.stats_lbl.text())
        v.addWidget(ui_kit.note("Click a page to drop a break line. Click a line again to remove it. Click a segment's label to leave that segment out."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Auto-break every"))
        self.auto_inches = QLineEdit("11")
        self.auto_inches.setFixedWidth(56)
        row.addWidget(self.auto_inches)
        row.addWidget(QLabel("in"))
        b = QPushButton("Apply")
        b.setToolTip("Replaces the breaks of every page")
        b.clicked.connect(lambda _c=False: self.auto_break())
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.b_undo = QPushButton("Undo")
        self.b_redo = QPushButton("Redo")
        b = QPushButton("Clear all breaks")
        self.b_undo.clicked.connect(lambda _c=False: self.undo())
        self.b_redo.clicked.connect(lambda _c=False: self.redo())
        b.clicked.connect(lambda _c=False: self.clear_breaks())
        for w in (self.b_undo, self.b_redo, b):
            row.addWidget(w)
        v.addLayout(row)

        # 3 export
        v = sec(3, "Export", summary=lambda: self.stats_lbl.text())
        self.stats_lbl = QLabel("")
        self.stats_lbl.setWordWrap(True)
        v.addWidget(self.stats_lbl)
        v.addWidget(ui_kit.note("One combined PDF with every included segment, in the order the pages are listed. The save box opens in the folder of the first PDF."))
        cl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(col)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(scroll, 1)
        pin = QFrame()
        pin.setObjectName("pinned")
        pin.setStyleSheet("QFrame#pinned { border-top:1px solid #cfd6e0; background:#f6f8fa; }")
        pb = QHBoxLayout(pin)
        pb.setContentsMargins(8, 8, 8, 8)
        self.b_export = ui_kit.primary(QPushButton("Export split PDF"))
        self.b_export.clicked.connect(lambda _c=False: self.export_dialog())
        pb.addWidget(self.b_export, 1)
        pl.addWidget(pin)
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(520)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return panel

    # ------------------------------------------------------------------ the image cache (a long PDF does not keep every page in memory)
    def touch_image(self, canvas):
        self.images.pop(canvas, None)
        self.images[canvas] = True
        while len(self.images) > self.MAX_CACHED_IMAGES:
            old, _ = self.images.popitem(last=False)
            if old is not canvas:
                old.drop_image()

    def forget_image(self, canvas):
        self.images.pop(canvas, None)

    # ------------------------------------------------------------------ showing the project
    def refresh(self):
        """Rebuilds the list of pages (after an import, move, remove, undo ...) and every number."""
        keep = {i: b for i, b in self.blocks.items()}
        ids = [it.id for it in self.project.items]
        for i, b in keep.items():
            if i not in ids:
                self.col.removeWidget(b)
                b.deleteLater()
                del self.blocks[i]
        for it in self.project.items:
            if it.id not in self.blocks:
                self.blocks[it.id] = PageBlock(self, it)
        while self.col.count():                                # lay the blocks out in project order, the stretch last (the widgets stay alive)
            self.col.takeAt(0)
        for it in self.project.items:
            self.col.addWidget(self.blocks[it.id])
        self.col.addStretch(1)
        self.refresh_numbers()

    def refresh_numbers(self):
        n_pages, n_out = len(self.project.items), self.project.output_count()
        if core.available():
            self.views.setCurrentWidget(self.scroll if n_pages else self.empty)
        files = len({s.path for s in (it.source for it in self.project.items)})
        self.pages_lbl.setText(f"{n_pages} page(s) from {files} file(s)" if n_pages else "No pages yet.")
        self.stats_lbl.setText(f"{n_pages} source page(s)  →  {n_out} output page(s)" if n_pages else "Nothing to export yet.")
        self.b_export.setEnabled(n_out > 0)
        self.b_undo.setEnabled(bool(self.project.undo_stack))
        self.b_redo.setEnabled(bool(self.project.redo_stack))
        for s in self.sections:
            s.refresh_summary()
        for b in self.blocks.values():
            b.canvas.update()
        name = os.path.basename(self.path) if self.path else "Page Break"
        self.title_lbl.setText(name + (" *" if self.dirty else ""))

    def edited(self):
        self.dirty = True
        self.refresh_numbers()

    # ------------------------------------------------------------------ actions (each returns something a test can check)
    def import_path(self, path):
        if not core.available():
            self.status.say("Page Break is still getting PyMuPDF. Wait for the set-up to finish.", "warn")
            return []
        if self.keep is not None:
            path = self.keep(path)
        try:
            items = self.project.import_pdf(path)
        except core.PageBreakError as e:
            self.status.say(str(e), "bad")
            QMessageBox.warning(self, "Page Break", str(e))
            return []
        self.dirty = True
        self.refresh()
        self.status.say(f"Imported {len(items)} page(s) from {os.path.basename(path)}.", "good")
        return items

    def import_dialog(self):
        if not core.available():
            self.status.say("Page Break is still getting PyMuPDF. Wait for the set-up to finish.", "warn")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose a PDF", "", PDF_FILTER)
        for p in paths:
            self.import_path(p)

    def click_page(self, item, y_px, scale):
        r = self.project.break_at(item, y_px, scale)
        if r:
            self.edited()
        return r

    def exclude_segment(self, item, index):
        r = self.project.toggle_exclude(item, index)
        if r is not None:
            self.edited()
        return r

    def move_page(self, item, direction):
        if self.project.move(item, direction):
            self.dirty = True
            self.refresh()
            return True
        return False

    def remove_page(self, item):
        self.project.remove(item)
        self.dirty = True
        self.refresh()

    def auto_break(self):
        try:
            inches = float(self.auto_inches.text().strip())
            self.project.auto_break(inches)
        except ValueError:
            self.status.say("Enter a valid number of inches.", "warn")
            return False
        except core.PageBreakError as e:
            self.status.say(str(e), "warn")
            return False
        self.edited()
        return True

    def clear_breaks(self):
        self.project.clear_breaks()
        self.edited()

    def undo(self):
        if self.project.undo():
            self.dirty = True
            self.refresh()
            return True
        return False

    def redo(self):
        if self.project.redo():
            self.dirty = True
            self.refresh()
            return True
        return False

    def new(self):
        if self.project.items and QMessageBox.question(
                self, "Page Break", "Remove all imported pages and start over?") != QMessageBox.StandardButton.Yes:
            return False
        self.project.clear()
        self.images.clear()
        self.path, self.dirty = None, False
        self.refresh()
        self.status.say("")
        return True

    # ------------------------------------------------------------------ zoom
    def set_zoom(self, z):
        self.zoom = max(core.ZOOM_MIN, min(core.ZOOM_MAX, z))
        self.zoom_lbl.setText(f"{round(self.zoom * 100)}%")
        for b in self.blocks.values():
            b.canvas.resize_for_zoom()

    def fit_width(self):
        w = self.scroll.viewport().width() - 40
        self.set_zoom(w / core.BASE_WIDTH_PX if w > 120 else 1.0)

    # ------------------------------------------------------------------ export
    def export_dialog(self):
        if not self.project.items:
            return None
        if not self.project.output_count():
            self.status.say("Nothing to export: every segment is excluded.", "warn")
            return None
        p, _ = QFileDialog.getSaveFileName(self, "Save PDF", os.path.join(self.project.suggested_dir(), self.project.suggested_name()), PDF_FILTER)
        if not p:
            return None
        return self.export_to(p)

    def export_to(self, path):
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            n = self.project.export(path)
        except core.PageBreakError as e:
            self.status.say(str(e), "bad")
            QMessageBox.warning(self, "Page Break", str(e))
            return None
        self.status.say(f"Saved {n} page(s) to {path}", "good")
        return n

    # ------------------------------------------------------------------ project files
    def title(self):
        return os.path.basename(self.path) if self.path else "Page Break"

    def is_dirty(self):
        return self.dirty

    def portable_base(self):
        """In a Workbench block (the tab was made so) the folder of the project file: the PDFs next to it are kept as relative paths, so the block can move."""
        return os.path.dirname(os.path.abspath(self.path)) if self.portable and self.path else None

    def to_json(self):
        return self.project.to_json(self.zoom, self.auto_inches.text(), self.portable_base())

    def open_path(self, path):
        if not core.available():
            self.pending_path = path                            # opened as soon as PyMuPDF is there
            self.status.say("Page Break is still getting PyMuPDF; the file opens when it is ready.", "warn")
            return False
        if path.lower().endswith(".pdf"):                       # a PDF dropped on the tab: just import it
            return bool(self.import_path(path))
        try:
            d = core.read_project(path)
            self.images.clear()
            self.blocks_clear()
            before, self.path = self.path, path                 # (portable_base needs it)
            try:
                missing = self.project.load_json(d, self.portable_base())
            except BaseException:
                self.path = before
                raise
        except (OSError, ValueError, core.PageBreakError) as e:
            self.status.say(f"Couldn't open that file: {e}", "bad")
            return False
        self.auto_inches.setText(str(d.get("auto_inches", "11")))
        self.path, self.dirty = path, False
        self.refresh()
        self.set_zoom(float(d.get("zoom", 1.0) or 1.0))
        if missing:
            self.status.say("These PDFs were not found, so their pages are left out: " + "; ".join(missing), "warn")
        else:
            self.status.say(f"Opened {path}", "good")
        return True

    def blocks_clear(self):
        while self.col.count():
            self.col.takeAt(0)
        for b in self.blocks.values():
            b.deleteLater()
        self.blocks = {}

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open", "", PROJECT_FILTER)
        if p:
            self.open_path(p)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            import fileio
            fileio.write_text(self.path, json.dumps(self.to_json(), indent=1))
        except OSError as e:
            self.status.say(f"Couldn't save: {e}", "bad")
            return False
        self.dirty = False
        self.refresh_numbers()
        self.status.say(f"Saved {self.path}", "good")
        return True

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save", self.path or "pages.oppb", PROJECT_FILTER)
        if not p:
            return False
        if not p.lower().endswith(".oppb"):
            p += ".oppb"
        self.path = p
        return self.save()

    def keyPressEvent(self, ev):
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and ev.key() == Qt.Key.Key_S:
            self.save()
        elif ctrl and ev.key() == Qt.Key.Key_Z:
            self.undo()
        elif ctrl and ev.key() == Qt.Key.Key_Y:
            self.redo()
        else:
            super().keyPressEvent(ev)


def make_tab(path=None):
    return PageBreakTab(path)
