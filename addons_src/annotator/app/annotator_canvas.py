"""annotator_canvas.py - the picture area of the annotator (Qt).

Draws the photo (zoomed / panned), the boxes, the LiDAR dots and the pick hover, and turns mouse gestures into calls on the window
(`app`): press-drag-release draws a box or selects, double / right click deletes, wheel zooms, middle drag pans. All the geometry
(fit, zoom, pan, clamping) is the same arithmetic the Tk version used, so boxes land on exactly the same pixels.
"""
import math

import numpy as np
from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import annotator_core as ac

CANVAS_BG = "#1e1e1e"
DEPTH_NEAR_M, DEPTH_FAR_M = 0.5, 6.0     # colour scale of the LiDAR depth overlay
ZOOM_MAX = 8.0                           # scroll-wheel zoom limit (1 = whole image)
ZOOM_STEP = 1.25                         # one wheel notch
PICK_RADIUS_PX = 40                      # how far (screen px) from the cursor a LiDAR point can be picked
BOX_COLORS = ["#e74c3c", "#2ecc71", "#3498db", "#f1c40f", "#9b59b6", "#1abc9c", "#e67e22", "#95a5a6", "#fd79a8", "#00b894"]


def color_for_class(class_id):
    return BOX_COLORS[class_id % len(BOX_COLORS)]


def pil_to_qimage(im):
    im = im.convert("RGB")
    arr = np.ascontiguousarray(np.asarray(im))
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class ImageCanvas(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMouseTracking(True)
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.draw_start = None            # (x, y) while a left press is down
        self.draw_now = None
        self.pan_last = None
        self.hover = None                 # (kind, data) of the pick hover, or None
        self._qimg = None                 # (QImage, x, y) of the drawn picture part
        self.scale = 1.0
        self.offset = (0, 0)

    # ------------------------------------------------------------------ geometry (same as the Tk version)
    def fit_geometry(self):
        a = self.app
        cw, ch = max(self.width(), 1), max(self.height(), 1)
        iw, ih = a.current_pil_image.size
        fit = min(cw / iw, ch / ih)
        scale = fit * a.zoom
        disp_w, disp_h = iw * scale, ih * scale
        vcx, vcy = a.view_center if (a.zoom > 1 and a.view_center) else (iw / 2, ih / 2)
        off_x, off_y = cw / 2 - vcx * scale, ch / 2 - vcy * scale
        off_x = (cw - disp_w) / 2 if disp_w <= cw else min(0, max(cw - disp_w, off_x))
        off_y = (ch - disp_h) / 2 if disp_h <= ch else min(0, max(ch - disp_h, off_y))
        return scale, (off_x, off_y), (disp_w, disp_h)

    def to_image_px(self, cx, cy):
        scale, (ox, oy), _ = self.fit_geometry()
        return (cx - ox) / scale, (cy - oy) / scale

    def to_canvas(self, ix, iy):
        scale, (ox, oy), _ = self.fit_geometry()
        return ix * scale + ox, iy * scale + oy

    # ------------------------------------------------------------------ drawing
    def overlay_depth(self, resized, scale, origin=(0, 0)):
        """LiDAR returns painted onto the already-resized display image (red near, blue far, near ones on top)."""
        pts = self.app.current_depth_points()
        if pts is None or len(pts[0]) == 0:
            return resized
        u, v, z = pts
        arr = np.array(resized)
        h, w = arr.shape[:2]
        order = np.argsort(-z)
        cols = ac.depth_colors(z[order], DEPTH_NEAR_M, DEPTH_FAR_M)
        x = np.round((u[order] - origin[0]) * scale).astype(int)
        y = np.round((v[order] - origin[1]) * scale).astype(int)
        r = 1 if scale < 1.6 else (2 if scale < 4 else 3)
        for dy in range(-r + 1, r + 1):
            for dx in range(-r + 1, r + 1):
                arr[np.clip(y + dy, 0, h - 1), np.clip(x + dx, 0, w - 1)] = cols
        return Image.fromarray(arr)

    def prepare(self):
        """(Re)makes the picture part that is on screen; called before every paint of a new view."""
        a = self.app
        self._qimg = None
        if a.current_pil_image is None:
            return
        scale, (off_x, off_y), (disp_w, disp_h) = self.fit_geometry()
        self.scale, self.offset = scale, (off_x, off_y)
        a.scale, a.offset = scale, (off_x, off_y)
        cw, ch = max(self.width(), 1), max(self.height(), 1)
        iw, ih = a.current_pil_image.size
        x0 = int(max(0, math.floor(-off_x / scale)))
        y0 = int(max(0, math.floor(-off_y / scale)))
        x1 = int(min(iw, math.ceil((cw - off_x) / scale)))
        y1 = int(min(ih, math.ceil((ch - off_y) / scale)))
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        if a.zoom <= 1:
            resized = a.current_pil_image.resize((max(int(disp_w), 1), max(int(disp_h), 1)))
            x0 = y0 = 0
        else:
            crop = a.current_pil_image.crop((x0, y0, x1, y1))
            resized = crop.resize((max(int(round((x1 - x0) * scale)), 1), max(int(round((y1 - y0) * scale)), 1)))
        if a.pick_check.isChecked():
            resized = self.overlay_depth(resized, scale, (x0, y0))
        self._qimg = (pil_to_qimage(resized), off_x + x0 * scale, off_y + y0 * scale)

    def redraw(self):
        self.prepare()
        self.update()

    def resizeEvent(self, e):
        self.redraw()
        self.place_empty()

    # ---- what the canvas shows while the project has no images: what to do first, with the buttons to do it
    def build_empty(self):
        from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout
        box = QWidget(self)
        box.setStyleSheet("QLabel { color:#d7dce6; } QLabel#h { color:#ffffff; font-size:15px; font-weight:600; }"
                          "QPushButton { background:#2d333d; color:#e8ecf2; border:1px solid #4a5361; border-radius:5px; padding:6px 14px; }"
                          "QPushButton:hover { background:#3a4250; border-color:#7f8ea3; }"
                          "QPushButton#go { background:#0e7f86; border:none; font-weight:600; color:white; } QPushButton#go:hover { background:#12949c; }")
        lay = QVBoxLayout(box)
        lay.setSpacing(8)
        h = QLabel("No images yet")
        h.setObjectName("h")
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(h)
        t = QLabel("An annotator project is a folder of pictures with their boxes. Bring pictures in from a video, or from a dataset zip "
                   "someone handed you. The File menu has the other ways (a Gimble session, models, a tablet).")
        t.setWordWrap(True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setFixedWidth(430)
        lay.addWidget(t)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_buttons = []
        for i, (text, fn) in enumerate((("Import video...", self.app.import_video), ("Import dataset zip...", self.app.import_zip))):
            b = QPushButton(text)
            if i == 0:
                b.setObjectName("go")
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
            self.empty_buttons.append(b)
        lay.addLayout(row)
        box.hide()
        return box

    def place_empty(self):
        e = getattr(self, "empty", None)
        if e is not None:
            e.adjustSize()
            e.move(max(0, (self.width() - e.width()) // 2), max(0, (self.height() - e.height()) // 2))

    def update_empty(self):
        """Shown only while the project holds no image at all (not while a set merely has nothing left to annotate)."""
        if getattr(self, "empty", None) is None:
            self.empty = self.build_empty()
        try:
            none = not self.app.project.list_images()
        except Exception:
            none = False
        if none != self.empty.isVisible() or none:
            self.place_empty()
            self.empty.setVisible(none)

    def paintEvent(self, e):
        a = self.app
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CANVAS_BG))
        if a.current_pil_image is None or self._qimg is None:
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        img, ix, iy = self._qimg
        p.drawImage(QPointF(ix, iy), img)
        off_x, off_y = self.offset
        small = QFont(self.font())
        small.setPointSize(9)
        small.setBold(True)
        p.setFont(small)
        if a.pick_check.isChecked():
            pts = a.current_depth_points()
            note = (f"LiDAR depth: {len(pts[0])} points, {DEPTH_NEAR_M:g} m (red) to {DEPTH_FAR_M:g} m (blue)"
                    if pts is not None else "No LiDAR depth for this image")
            p.setPen(QColor("#ffffff"))
            p.drawText(QPointF(off_x + 8, off_y + 20), note)
        pending = a.project.is_ai_pending(a.current_image_id)
        img_w, img_h = a.current_pil_image.size
        for i, (cls, xc, yc, w, h) in enumerate(a.boxes):
            x1, y1, x2, y2 = ac.yolo_box_to_pixel(xc, yc, w, h, img_w, img_h)
            cx1, cy1 = self.to_canvas(x1, y1)
            cx2, cy2 = self.to_canvas(x2, y2)
            color = QColor(color_for_class(cls))
            pen = QPen(color, 3 if i == a.selected_box_index else 2)
            if pending:
                pen.setStyle(Qt.PenStyle.CustomDashLine)
                pen.setDashPattern([3, 1.5])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(QPointF(cx1, cy1), QPointF(cx2, cy2)).normalized())
            label = a.project.classes[cls] if cls < len(a.project.classes) else f"class {cls}"
            if pending:
                label += " (AI)"
            pk = a.box_dist[i] if i < len(a.box_dist) else None
            if pk:
                label += f"  {pk['distance_m']:.2f} m"
            p.setPen(color)
            p.drawText(QPointF(cx1 + 4, cy1 - 2), label)
            if pk:
                mx, my = self.to_canvas(pk['u'], pk['v'])
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(mx, my), 6, 6)
                p.setPen(QPen(color, 1))
                p.setBrush(QBrush(color))
                p.drawEllipse(QPointF(mx, my), 3, 3)
        if self.draw_start is not None and self.draw_now is not None:
            pen = QPen(QColor(color_for_class(a.current_class_id)), 2)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([2, 1])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(QPointF(*self.draw_start), QPointF(*self.draw_now)).normalized())
        if self.hover is not None:
            self.paint_hover(p)
        p.end()

    def paint_hover(self, p):
        kind, data = self.hover
        if kind == "label":
            x, y, text, color = data
            self.hover_label(p, x, y, text, color)
        else:
            px, py, text = data
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(px, py), 8, 8)
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.drawLine(QPointF(px - 12, py), QPointF(px + 12, py))
            p.drawLine(QPointF(px, py - 12), QPointF(px, py + 12))
            self.hover_label(p, px + 14, py - 26, text, "#ffffff")

    def hover_label(self, p, x, y, text, color):
        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        r = p.fontMetrics().boundingRect(text)
        rect = QRectF(x - 3, y - 2, r.width() + 6, r.height() + 4)
        p.fillRect(rect, QColor("#000000"))
        p.setPen(QColor(color))
        p.drawText(QPointF(x, y + r.height() - p.fontMetrics().descent()), text)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        a = self.app
        x, y = e.position().x(), e.position().y()
        b = e.button()
        if b == Qt.MouseButton.LeftButton:
            if a.current_pil_image is not None:
                self.draw_start, self.draw_now = (x, y), (x, y)
        elif b == Qt.MouseButton.MiddleButton:
            self.pan_last = (x, y)
        elif b == Qt.MouseButton.RightButton:
            a.on_canvas_right_click(x, y)

    def mouseMoveEvent(self, e):
        a = self.app
        x, y = e.position().x(), e.position().y()
        if self.pan_last is not None:
            a.on_pan_drag(x - self.pan_last[0], y - self.pan_last[1])
            self.pan_last = (x, y)
            return
        if self.draw_start is not None:
            self.draw_now = (x, y)
            self.update()
            return
        a.on_canvas_motion(x, y)

    def mouseReleaseEvent(self, e):
        a = self.app
        x, y = e.position().x(), e.position().y()
        if e.button() == Qt.MouseButton.MiddleButton:
            self.pan_last = None
        elif e.button() == Qt.MouseButton.LeftButton and self.draw_start is not None:
            x0, y0 = self.draw_start
            self.draw_start = self.draw_now = None
            a.on_canvas_release(x0, y0, x, y)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.app.on_canvas_double_click(e.position().x(), e.position().y())

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.app.zoom_at(e.position().x(), e.position().y(), 1 if d > 0 else -1)

    def leaveEvent(self, e):
        self.hover = None
        self.update()
