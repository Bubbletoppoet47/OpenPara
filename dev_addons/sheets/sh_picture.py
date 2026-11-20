"""
sh_picture.py - pictures on a sheet: a screenshot pasted with Ctrl+V, or a PNG / JPEG file from Insert image.

    read_file(path) / read_image(qimage, name)   -> (bytes to keep, QImage, name): what a picture file or the clipboard gave, ready for the workbook
    new_picture(wb, sheet, data, image, name, pos, room)   the picture's entry for sheet.pictures (the bytes go into wb.images once)
    PictureFrame(grid, picture)                  the picture floating over the cells: drag it to move, the corner to resize, double-click for the panel
    PicturePanel()                               the panel on the right of the grid: width, height, keep proportions, scale, back to the original size
    export(wb, picture, path)                    saves the picture as a file ("" or the reason it could not be saved)

A picture is {id, image (a key of Workbook.images), pos [x, y] (pixels from the top-left of the sheet, like charts), size [w, h] (as shown), orig [w, h] (as it
came: the "original size"), keep (proportions locked), name}.  The bytes are kept once in the workbook, so undo steps and copied sheets only carry the key.
"""
import os

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QImageIOHandler, QImageReader, QPainter, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

import sh_icons
import ui_kit

MAX_SIDE = 4000                    # a picture with more pixels than this on its longer side is made smaller when it is brought in
MAX_BYTES = 40_000_000             # ... and one that is still bigger than this is refused
MIN_SIZE, MAX_SIZE = 8, 10000      # as shown on the sheet, in pixels
FILE_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)"
ACCENT = QColor("#2b7de9")


class PictureError(Exception):
    """A picture that cannot be brought in; the text says why, in words for the person."""


# ------------------------------------------------------------------------------------------------------------------ bringing a picture in
def _encode(image, fmt, quality=-1):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buf, fmt, quality)
    buf.close()
    if not ok:
        raise PictureError("The picture could not be stored.")
    return bytes(ba.data())


def kind_of(data):
    """'png', 'jpeg' or 'other' from the first bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    return "other"


def suffix_of(data):
    return {"png": ".png", "jpeg": ".jpg"}.get(kind_of(data), ".png")


def _finish(image, source, fmt):
    """The bytes to keep for `image`: the file's own bytes when it is a PNG or a JPEG that needs nothing done to it (so a photo does not grow), else a PNG."""
    scaled = False
    if max(image.width(), image.height()) > MAX_SIDE:
        image = image.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        scaled = True
    if source is not None and not scaled and fmt in ("png", "jpeg", "jpg"):
        data = bytes(source)
    elif fmt in ("jpeg", "jpg"):
        data = _encode(image, "JPEG", 90)
    else:
        data = _encode(image, "PNG")
    if len(data) > MAX_BYTES:
        raise PictureError(f"This picture is too big ({len(data) / 1e6:.0f} MB; the limit is {MAX_BYTES // 1_000_000} MB).")
    return data, image


def read_bytes(raw, name=""):
    """The bytes of a picture file -> (bytes to keep, QImage, name)."""
    ba = QByteArray(raw)
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    rd = QImageReader(buf)
    rd.setAutoTransform(True)                                   # (a phone's JPEG says it is to be turned: the bytes are then stored turned)
    fmt = bytes(rd.format()).decode("ascii", "ignore").lower()
    untouched = rd.transformation() == QImageIOHandler.Transformation.TransformationNone
    image = rd.read()
    if image.isNull():
        raise PictureError("This is not a picture Sheets can read (PNG, JPG, BMP, GIF and WebP work).")
    data, image = _finish(image, raw if untouched else None, fmt)
    return data, image, name


def read_file(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES * 2 + 1)
    except OSError as ex:
        raise PictureError(f"The file could not be read: {ex.strerror or ex}")
    if len(raw) > MAX_BYTES * 2:
        raise PictureError("This file is too big to be a picture for a sheet.")
    return read_bytes(raw, os.path.splitext(os.path.basename(path))[0])


def read_image(image, name=""):
    """A QImage from the clipboard -> (bytes to keep, QImage, name); it is stored as a PNG."""
    if image is None or image.isNull():
        raise PictureError("There is no picture on the clipboard.")
    data, image = _finish(image, None, "png")
    return data, image, name


def clipboard_image(md=None):
    """The picture on the clipboard as (bytes, QImage, name), or None when there is none (an image file that was copied in a file manager counts)."""
    cb = QGuiApplication.clipboard()
    md = md if md is not None else cb.mimeData()
    if md is None:
        return None
    if md.hasImage():
        img = cb.image() if md is cb.mimeData() else md.imageData()
        if isinstance(img, QPixmap):
            img = img.toImage()
        if isinstance(img, QImage) and not img.isNull():
            return read_image(img, "Picture")
    if md.hasUrls():
        for u in md.urls():
            p = u.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp") and os.path.isfile(p):
                return read_file(p)
    return None


def has_clipboard_image(md=None):
    md = md if md is not None else QGuiApplication.clipboard().mimeData()
    if md is None:
        return False
    if md.hasImage():
        return True
    return md.hasUrls() and any(os.path.splitext(u.toLocalFile())[1].lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp") for u in md.urls())


def new_picture(wb, sheet, data, image, name, pos, room=None):
    """The entry for sheet.pictures.  It is shown at its natural size (a screenshot of a high-density screen at the size it had on that screen), made
    smaller to fit `room` = (width, height) when it would not fit."""
    ratio = image.devicePixelRatio() or 1.0
    ow, oh = max(1.0, image.width() / ratio), max(1.0, image.height() / ratio)
    w, h = ow, oh
    if room:
        k = min(1.0, max(40.0, room[0]) / w, max(40.0, room[1]) / h)
        w, h = w * k, h * k
    return {"id": wb.new_picture_id(sheet), "image": wb.add_image(data), "pos": [float(pos[0]), float(pos[1])],
            "size": [float(max(MIN_SIZE, round(w))), float(max(MIN_SIZE, round(h)))], "orig": [float(round(ow)), float(round(oh))], "keep": True, "name": name or "Picture"}


def qimage_of(wb, pic):
    img = QImage.fromData(wb.images.get(pic["image"], b""))
    return img


def export(wb, pic, path):
    """Saves the picture's own pixels to `path` (PNG, JPG or BMP by the name).  Returns "" or what went wrong."""
    data = wb.images.get(pic["image"])
    if not data:
        return "The picture's data is missing."
    ext = os.path.splitext(path)[1].lower()
    try:
        if (ext == ".png" and kind_of(data) == "png") or (ext in (".jpg", ".jpeg") and kind_of(data) == "jpeg"):
            with open(path, "wb") as fh:
                fh.write(data)
            return ""
        img = qimage_of(wb, pic)
        if img.isNull():
            return "The picture could not be read."
        if not img.save(path):
            return f"{os.path.basename(path)} could not be saved."
        return ""
    except OSError as ex:
        return f"{os.path.basename(path)} could not be saved: {ex.strerror or ex}"


# ------------------------------------------------------------------------------------------------------------------ the picture on the grid
class PictureFrame(QWidget):
    """A picture floating over the cells: drag it to move, drag the corner to resize, double-click for the panel, right-click for more."""
    CORNER = 16
    changed = pyqtSignal(str)                 # picture id: moved or resized (one undo step was made)
    edit_asked = pyqtSignal(str)
    menu_asked = pyqtSignal(str, QPoint)
    picked = pyqtSignal(str)

    def __init__(self, grid, pic):
        super().__init__(grid.viewport())
        self.grid, self.pid = grid, pic["id"]
        self.selected = False
        self._drag = None
        self._key = None
        self._pix = None
        self._scaled = None
        self.setMouseTracking(True)
        self.load(pic)
        self.show()

    def pic(self):
        return self.grid.wb.picture(self.grid.sheet, self.pid)

    def load(self, pic):
        if pic["image"] != self._key:
            pm = QPixmap()
            pm.loadFromData(self.grid.wb.images.get(pic["image"], b""))
            self._pix, self._key, self._scaled = pm, pic["image"], None

    def place(self):
        p = self.pic()
        if p is None:
            return
        self.load(p)
        g = self.grid
        w, h = max(1, int(p["size"][0])), max(1, int(p["size"][1]))
        gx, gy = int(g.hw + p["pos"][0] - g.x0), int(g.hh + p["pos"][1] - g.y0)
        self.setGeometry(gx, gy, w, h)
        left, top = max(0, g.hw - gx), max(0, g.hh - gy)               # the part that is under the row and column headers is not drawn
        if left >= w or top >= h:
            self.hide()
            return
        if left or top:
            self.setMask(QRegion(QRect(left, top, w - left, h - top)))
        else:
            self.clearMask()
        self.show()

    def _in_corner(self, pos):
        return pos.x() > self.width() - self.CORNER and pos.y() > self.height() - self.CORNER

    def draw_picture(self, p, r):
        """The picture itself, filling `r`."""
        if self._pix is None or self._pix.isNull():
            p.fillRect(r, QColor("#f4f6fa"))
            p.setPen(QColor("#b00020"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "This picture\ncould not be read.")
            return
        dpr = self.devicePixelRatioF()
        size = QSize(max(1, round(r.width() * dpr)), max(1, round(r.height() * dpr)))
        if self._drag is not None and self._drag[0] == "size":     # (while the corner is dragged: quick; smooth again when it is let go)
            p.drawPixmap(r, self._pix)
        else:
            if self._scaled is None or self._scaled.size() != size:
                self._scaled = self._pix.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self._scaled.setDevicePixelRatio(dpr)
            p.drawPixmap(0, 0, self._scaled)

    def draw_selection(self, p, r):
        """The frame and the corner handle of a picked picture."""
        if self.selected:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r.adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor("white"), 1))
            p.setBrush(ACCENT)
            p.drawRect(QRect(r.width() - 11, r.height() - 11, 9, 9))

    def paintEvent(self, ev):
        p = QPainter(self)
        r = self.rect()
        self.draw_picture(p, r)
        self.draw_selection(p, r)
        p.end()

    def release(self):
        """The frame is going away (a video stops its player here)."""

    def mousePressEvent(self, ev):
        self.picked.emit(self.pid)
        if ev.button() == Qt.MouseButton.RightButton:
            self.menu_asked.emit(self.pid, ev.globalPosition().toPoint())
            return
        p = self.pic()
        if p is None or ev.button() != Qt.MouseButton.LeftButton:
            return
        kind = "size" if self._in_corner(ev.position().toPoint()) else "move"
        self._drag = (kind, ev.globalPosition().toPoint(), list(p["pos"]), list(p["size"]), self.grid.wb.picture_state(self.grid.sheet, self.pid))

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._in_corner(pos) else Qt.CursorShape.SizeAllCursor)
            return
        p = self.pic()
        if p is None:
            return
        kind, start, opos, osize, _before = self._drag
        d = ev.globalPosition().toPoint() - start
        if kind == "move":
            p["pos"] = [max(0.0, opos[0] + d.x()), max(0.0, opos[1] + d.y())]
        else:
            w, h = osize[0] + d.x(), osize[1] + d.y()
            if p.get("keep", True) and osize[0] > 0 and osize[1] > 0:           # proportions kept: the corner drags the picture by whichever way it was pulled more
                k = max(w / osize[0], h / osize[1])
                k = min(min(MAX_SIZE / osize[0], MAX_SIZE / osize[1]), max(max(MIN_SIZE / osize[0], MIN_SIZE / osize[1]), k))
                w, h = osize[0] * k, osize[1] * k
            w, h = min(MAX_SIZE, max(MIN_SIZE, w)), min(MAX_SIZE, max(MIN_SIZE, h))
            p["size"] = [float(round(w)), float(round(h))]
        self.place()
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            kind, before = self._drag[0], self._drag[4]
            self._drag = None
            made = self.grid.wb.record_picture("Move picture" if kind == "move" else "Resize picture", self.grid.sheet, self.pid, before)
            self.update()
            if made:
                self.changed.emit(self.pid)

    def mouseDoubleClickEvent(self, ev):
        self.edit_asked.emit(self.pid)


# ------------------------------------------------------------------------------------------------------------------ the panel
def _spin(lo, hi, value, step, decimals=0, suffix=""):
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


class PicturePanel(QWidget):
    """What the panel on the right shows for a picture: its size.  Resizing is all there is (width, height, keep proportions, scale, original size)."""
    changed = pyqtSignal(str)                  # picture id: its size was changed
    closed = pyqtSignal()
    export_asked = pyqtSignal(str)
    delete_asked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wb = None
        self.grid = None
        self.picture = None
        self.sheet = ""
        self._loading = False
        self.setMinimumWidth(300)
        self.setObjectName("picturepanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.heading = QLabel("Image")
        self.heading.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        head.addWidget(self.heading, 1)
        b_exp = QToolButton()
        b_exp.setText("Export…")
        b_exp.setToolTip("Save the image as a file")
        b_exp.clicked.connect(lambda _c=False: self.picture and self.export_asked.emit(self.picture["id"]))
        b_x = QToolButton()
        sh_icons.decorate(b_x, "s_remove")
        b_x.setToolTip("Close the panel")
        b_x.clicked.connect(lambda _c=False: self.close_panel())
        head.addWidget(b_exp)
        head.addWidget(b_x)
        lay.addLayout(head)
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
        lay.addWidget(self.name_lbl)
        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        self.w = _spin(MIN_SIZE, MAX_SIZE, 100, 10, 0, " px")
        self.h = _spin(MIN_SIZE, MAX_SIZE, 100, 10, 0, " px")
        self.keep = QCheckBox("Keep proportions")
        self.scale = _spin(1, 1000, 100, 5, 0, " %")
        self.w.setToolTip("How wide the image is on the sheet")
        self.h.setToolTip("How tall the image is on the sheet")
        self.scale.setToolTip("The size as a percentage of the original size")
        form.addRow("Width", self.w)
        form.addRow("Height", self.h)
        form.addRow("", self.keep)
        form.addRow("Scale", self.scale)
        self.loop = QCheckBox("Loop (start again when it ends)")
        self.loop.setToolTip("Play the video again and again; saved with the sheet")
        form.addRow("", self.loop)
        lay.addLayout(form)
        self.orig_lbl = QLabel("")
        self.orig_lbl.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
        row = QHBoxLayout()
        self.reset = QPushButton("Original size")
        self.reset.setToolTip("Back to the size the image came in")
        row.addWidget(self.reset)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.orig_lbl)
        lay.addStretch(1)
        self.delete_btn = QPushButton("Delete image")
        self.delete_btn.clicked.connect(lambda _c=False: self.picture and self.delete_asked.emit(self.picture["id"]))
        lay.addWidget(self.delete_btn)
        self.w.valueChanged.connect(lambda _v: self.edited("w"))
        self.h.valueChanged.connect(lambda _v: self.edited("h"))
        self.scale.valueChanged.connect(lambda _v: self.edited("s"))
        self.keep.toggled.connect(self.keep_toggled)
        self.loop.toggled.connect(self.loop_toggled)
        self.reset.clicked.connect(lambda _c=False: self.to_original())

    def set_context(self, wb, grid):
        self.wb, self.grid = wb, grid

    def open_picture(self, pic, sheet):
        self.picture, self.sheet = pic, sheet
        self.load()

    def close_panel(self):
        self.picture = None
        self.hide()
        self.closed.emit()

    def is_open_for(self, pid):
        return self.picture is not None and self.picture.get("id") == pid and not self.isHidden()

    def load(self):
        pic = self.picture
        if pic is None:
            return
        self._loading = True
        video = bool(pic.get("video"))
        self.heading.setText("Video" if video else "Image")
        self.delete_btn.setText("Delete video" if video else "Delete image")
        self.loop.setVisible(video)
        self.loop.setChecked(bool(pic.get("loop")))
        self.name_lbl.setText((pic.get("name") or "") + (f"  ({int(pic.get('dur') or 0) // 60}:{int(pic.get('dur') or 0) % 60:02d})" if video and pic.get("dur") else ""))
        self.w.setValue(pic["size"][0])
        self.h.setValue(pic["size"][1])
        self.keep.setChecked(bool(pic.get("keep", True)))
        self.scale.setValue(self.percent(pic))
        self.orig_lbl.setText(f"Original size: {pic['orig'][0]:.0f} × {pic['orig'][1]:.0f} px")
        self._loading = False

    @staticmethod
    def percent(pic):
        return max(1.0, min(1000.0, round(100.0 * pic["size"][0] / max(1.0, pic["orig"][0]))))

    def apply(self, label, **fields):
        """Sets what changed (one undo step), then tells the sheet."""
        pic = self.picture
        if pic is None or self.wb is None:
            return
        before = self.wb.picture_state(self.sheet, pic["id"])
        live = self.wb.picture(self.sheet, pic["id"])
        if live is None:
            return
        live.update(fields)
        self.wb.record_picture(label, self.sheet, pic["id"], before)
        self.picture = live
        self.load()
        self.changed.emit(live["id"])

    def edited(self, which):
        pic = self.picture
        if self._loading or pic is None:
            return
        w, h = float(pic["size"][0]), float(pic["size"][1])
        if which == "w":
            w = self.w.value()
            h = w * h / max(1.0, pic["size"][0]) if self.keep.isChecked() else self.h.value()
        elif which == "h":
            h = self.h.value()
            w = h * w / max(1.0, pic["size"][1]) if self.keep.isChecked() else self.w.value()
        else:
            k = self.scale.value() / 100.0
            w, h = pic["orig"][0] * k, pic["orig"][1] * k
        w, h = min(MAX_SIZE, max(MIN_SIZE, round(w))), min(MAX_SIZE, max(MIN_SIZE, round(h)))
        self.apply("Resize picture", size=[float(w), float(h)])

    def loop_toggled(self, on):
        if self._loading or self.picture is None or not self.picture.get("video"):
            return
        self.apply("Video loop", loop=bool(on))

    def keep_toggled(self, on):
        if self._loading or self.picture is None:
            return
        self.apply("Picture proportions", keep=bool(on))

    def to_original(self):
        pic = self.picture
        if pic is not None:
            self.apply("Original picture size", size=[float(pic["orig"][0]), float(pic["orig"][1])])
