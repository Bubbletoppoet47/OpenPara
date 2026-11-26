"""annotator_panel.py - the side panel of the annotator window: the class list on top, then three icon tabs
(Frames: the working set and its images with thumbnails; Selected box: what the selected box is; AI assist: the model and the classes it labels).

The panel only shows things and reports clicks to the window (`win`, an AnnotatorWindow); what a click does is the window's business.
"""
from collections import OrderedDict

from PIL import Image, ImageOps
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QStyle, QStyledItemDelegate, QTabWidget, QVBoxLayout,
                             QWidget)

import annotator_canvas as cv
import annotator_icons as icons

INK, MUTED, LINE, BORDER = "#1f2a3c", "#5a6577", "#e3e3e3", "#ababab"
SELECT_BG, SELECT_LINE = "#e6f0fc", "#006ec8"
THUMB_W, THUMB_H = 44, 33
ROW_H = 40
ROLE_COUNT, ROLE_COLOR = Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 2     # a class row: how many boxes of it the open image has, its colour
ROLE_ID, ROLE_STATE = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 3            # a frame row: its id, "done" / "ai" / "todo"
GLYPHS = {"done": ("✓", "#2e7d32"), "ai": ("?", "#a05000"), "todo": ("○", MUTED)}


def load_thumb(path, w=THUMB_W, h=THUMB_H):
    """A small picture of a photo, cropped to fill w x h (drawn at twice the pixels, so it stays sharp), or None when it can't be read."""
    try:
        with Image.open(path) as im:
            im.draft("RGB", (w * 4, h * 4))                         # a JPEG is decoded at a fraction of its size: fast
            im = ImageOps.fit(im.convert("RGB"), (w * 2, h * 2))
        pm = QPixmap.fromImage(cv.pil_to_qimage(im))
        pm.setDevicePixelRatio(2)
        return pm
    except Exception:  # noqa: BLE001  (an unreadable file just has no thumbnail)
        return None


class ThumbCache:
    """The thumbnails shown so far (loaded when a row first comes into view, the oldest forgotten beyond `limit`)."""

    def __init__(self, path_of, limit=600):
        self.path_of, self.limit, self.items = path_of, limit, OrderedDict()

    def get(self, img_id):
        if img_id in self.items:
            self.items.move_to_end(img_id)
            return self.items[img_id]
        try:
            pm = load_thumb(self.path_of(img_id))
        except Exception:  # noqa: BLE001
            pm = None
        self.items[img_id] = pm
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return pm

    def forget(self, img_id):
        self.items.pop(img_id, None)

    def clear(self):
        self.items.clear()


class ClassDelegate(QStyledItemDelegate):
    """A class row: its colour, "[key] name", and at the right how many boxes of it the open image has."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 26)

    def paint(self, p, option, index):
        p.save()
        r = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, QColor("#dbe9fb"))
        colour = index.data(ROLE_COLOR)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(colour) if colour else QColor("#999999"))
        p.drawRoundedRect(QRect(r.left() + 10, r.center().y() - 6, 12, 12), 2, 2)
        p.setPen(QColor(INK))
        p.drawText(QRect(r.left() + 30, r.top(), r.width() - 70, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, index.data(Qt.ItemDataRole.DisplayRole) or "")
        n = index.data(ROLE_COUNT)
        if n:
            p.setPen(QColor(MUTED))
            p.drawText(QRect(r.left(), r.top(), r.width() - 10, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(n))
        p.restore()


class FrameDelegate(QStyledItemDelegate):
    """A frame row: its state mark, a thumbnail, its id, and a short note at the right ("2 boxes", "AI draft")."""

    def __init__(self, thumbs, info_fn, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        self.info_fn = info_fn              # id -> the note at the right (asked only for rows that are on screen)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p, option, index):
        p.save()
        r = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.fillRect(r, QColor(SELECT_BG))
            p.fillRect(QRect(r.left(), r.bottom() - 1, r.width(), 2), QColor(SELECT_LINE))
        glyph, colour = GLYPHS.get(index.data(ROLE_STATE) or "todo", GLYPHS["todo"])
        p.setPen(QColor(colour))
        p.drawText(QRect(r.left() + 8, r.top(), 16, r.height()), Qt.AlignmentFlag.AlignCenter, glyph)
        img_id = index.data(ROLE_ID) or ""
        tx = r.left() + 30
        pm = self.thumbs.get(img_id)
        ty = r.top() + (r.height() - THUMB_H) // 2
        if pm is not None:
            p.drawPixmap(tx, ty, pm)
        else:
            p.fillRect(QRect(tx, ty, THUMB_W, THUMB_H), QColor("#d8dde6"))
        p.setPen(QColor("#c9c9c9"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRect(tx, ty, THUMB_W - 1, THUMB_H - 1))
        info = self.info_fn(img_id) or ""
        right_w = p.fontMetrics().horizontalAdvance(info) + 10 if info else 0
        p.setPen(QColor(INK))
        p.drawText(QRect(tx + THUMB_W + 8, r.top(), max(10, r.width() - (tx - r.left()) - THUMB_W - 16 - right_w), r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, p.fontMetrics().elidedText(img_id, Qt.TextElideMode.ElideMiddle, max(10, r.width() - (tx - r.left()) - THUMB_W - 16 - right_w)))
        if info:
            p.setPen(QColor(MUTED))
            p.drawText(QRect(r.left(), r.top(), r.width() - 8, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, info)
        p.restore()


def _heading(text):
    lab = QLabel(text.upper())
    lab.setStyleSheet("color:#4a5872; font-size:11px; font-weight:600; letter-spacing:1px;")
    return lab


def _note(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color:#6a7790; font-size:11px;")
    return lab


SEG_QSS = ("QPushButton{border:1px solid #bdbdbd; background:#ffffff; color:#1f2a3c; padding:4px 0; border-radius:0;}"
           "QPushButton:checked{border-color:#1a56c4; background:#e6f0fc; color:#1a56c4; font-weight:600;}"
           "QPushButton#left{border-top-left-radius:3px; border-bottom-left-radius:3px;}"
           "QPushButton#right{border-top-right-radius:3px; border-bottom-right-radius:3px; border-left:0;}"
           "QPushButton#right:checked{border-left:1px solid #1a56c4;}")


class AnnotatorPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._show_all = False
        self.thumbs = ThumbCache(lambda i: win.project.image_path(i))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._classes_block())
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(26, 26))
        self._add_tab(self._frames_page(), "ann_tab_frames", "Frames")
        self._add_tab(self._box_page(), "ann_tab_box", "Selected box")
        self._add_tab(self._ai_page(), "ann_tab_ai", "AI assist")
        lay.addWidget(self.tabs, 1)
        self.setMinimumWidth(270)

    def _add_tab(self, page, icon_key, name):
        ic = icons.icon(icon_key, 26)
        i = self.tabs.addTab(page, ic if ic is not None else QIcon(), "" if ic is not None else name)
        self.tabs.setTabToolTip(i, name)

    # ---- the class list, always in view
    def _classes_block(self):
        box = QFrame()
        box.setObjectName("classes")
        box.setStyleSheet(f"QFrame#classes{{background:#ffffff; border:1px solid {BORDER};}}")
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 8, 0, 6)
        v.setSpacing(4)
        h = _heading("Classes")
        h.setContentsMargins(10, 0, 10, 0)
        v.addWidget(h)
        self.class_list = QListWidget()
        self.class_list.setFrameShape(QFrame.Shape.NoFrame)
        self.class_list.setItemDelegate(ClassDelegate(self.class_list))
        self.class_list.setToolTip("Press a class key [ ] to pick it. A selected box is relabeled too.")
        self.class_list.currentRowChanged.connect(self.win._on_class_select)
        v.addWidget(self.class_list)
        self.class_hint = _note("No classes yet.")
        self.class_hint.setContentsMargins(10, 0, 10, 0)
        v.addWidget(self.class_hint)
        b = QPushButton("Edit classes…")
        b.setFlat(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("QPushButton{border:0; background:transparent; color:#1a56c4; text-align:left; padding:2px 10px;} QPushButton:hover{text-decoration:underline;}")
        b.clicked.connect(lambda _c=False: self.win.manage_classes())
        v.addWidget(b)
        self.edit_classes_button = b
        return box

    def fit_class_list(self, n):
        """As tall as its classes (up to six rows, then it scrolls); with none, a line saying so."""
        self.class_list.setVisible(n > 0)
        self.class_hint.setVisible(n == 0)
        self.class_list.setFixedHeight(max(1, min(n, 6)) * 26 + 2)

    # ---- tab 1: the working set and its frames
    def _frames_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(10, 8, 10, 8)
        tl.setSpacing(6)
        tl.addWidget(_note("Working set"))
        self.session_combo = QComboBox()
        self.session_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.session_combo.setMinimumContentsLength(14)
        self.session_combo.setToolTip("[A] = every frame of the set is annotated.")
        self.session_combo.activated.connect(self.win._on_session_pick)
        tl.addWidget(self.session_combo)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.todo_btn, self.all_btn = QPushButton("To do"), QPushButton("All")
        self.todo_btn.setObjectName("left")
        self.all_btn.setObjectName("right")
        for b in (self.todo_btn, self.all_btn):
            b.setCheckable(True)
            b.setStyleSheet(SEG_QSS)
            seg.addWidget(b, 1)
        self.todo_btn.setChecked(True)
        self.todo_btn.setToolTip("Only the images still to annotate ([?] = AI draft, not yet confirmed).")
        self.all_btn.setToolTip("Every image, to review and fix annotated ones too.")
        self.todo_btn.clicked.connect(lambda _c=False: self.set_show_all(False))
        self.all_btn.clicked.connect(lambda _c=False: self.set_show_all(True))
        tl.addLayout(seg)
        v.addWidget(top)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{LINE};")
        v.addWidget(line)
        self.image_list = QListWidget()
        self.image_list.setFrameShape(QFrame.Shape.NoFrame)
        self.image_list.setItemDelegate(FrameDelegate(self.thumbs, self.win._frame_note, self.image_list))
        self.image_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.image_list.setUniformItemSizes(True)
        self.image_list.currentRowChanged.connect(self.win._on_image_select)
        v.addWidget(self.image_list, 1)
        self.set_summary = QLabel("")
        self.set_summary.setStyleSheet(f"color:{MUTED}; font-size:11px; padding:7px 10px; border-top:1px solid {LINE};")
        v.addWidget(self.set_summary)
        return page

    def show_all(self):
        """True: every frame is listed; False: only the ones still to annotate (and the open one)."""
        return self._show_all

    def set_show_all(self, on, notify=True):
        on = bool(on)
        changed = on != self._show_all
        self._show_all = on
        self.todo_btn.setChecked(not on)
        self.all_btn.setChecked(on)
        if notify and changed:
            self.win._refresh_image_list()

    # ---- tab 2: the selected box
    def _box_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        self.box_info = QLabel("")
        self.box_info.setWordWrap(True)
        self.box_info.setTextFormat(Qt.TextFormat.RichText)
        self.box_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.box_info)
        v.addWidget(_note("Drag: new box. Click: select. Double- or right-click: delete."))
        v.addWidget(_note("LiDAR distance (ribbon): hover a box, click a dot to attach its distance, right-click to clear."))
        v.addStretch(1)
        return page

    # ---- tab 3: the AI model and the classes it labels
    def _ai_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        v.addWidget(_note("Model"))
        self.ai_choice = QComboBox()
        self.ai_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.ai_choice.setMinimumContentsLength(14)
        self.ai_choice.activated.connect(lambda _i: self.win.load_ai_model())
        v.addWidget(self.ai_choice)
        v.addSpacing(6)
        v.addWidget(_heading("Pre-label these classes"))
        v.addWidget(_note("Check classes for live predictions on this photo. Confirmed images are never touched."))
        self.ai_box = QVBoxLayout()
        v.addLayout(self.ai_box)
        v.addStretch(1)
        return page
