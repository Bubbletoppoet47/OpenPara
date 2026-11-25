"""
sim_style.py - the look of the left panels of 1D FEA, 2D FEA, 3D FEA and 2D CFD: a soft "bevel".

  Raised parts (buttons, section bars, table headers, the "?" buttons) have a one pixel white top-left edge, a grey-blue bottom-right edge,
  rounded corners of 3 px and a very light top-to-bottom gradient.  Inputs, lists and tables are sunken and white.  The open part of a section
  sits on a faint tile with a hairline border.  Selection is the pale blue of the rest of the program.  (SOLVE, the teal call-to-action button, is now only the Run button of the Study tab: the Solve button of an analysis is a plain button on its Results page.)

Only the panel gets this look (sim_ui.soften(panel) sets the style sheet on it); nothing else in the program changes.

  stylesheet()     the style sheet of a panel (a string)
  SECTION_BAR, SECTION_BAR_HOT, BODY, SOLVE, SOLVE_SIDE, HELP, TABS      style sheets of single parts, used by sim_ui
  images()         {name: path} of the small pictures the style sheet needs (check mark, radio dot, arrows); drawn once into the user folder,
                   in 1x and @2x sizes; {} when they cannot be written (the panel then keeps the default check boxes)
"""
import os

COLORS = {"face": "#eef1f6", "tile": "#f7f8fb", "ink": "#1f2a3c", "head": "#16324f", "field": "#ffffff", "hi": "#ffffff", "edge": "#a8b1c3",
          "edge_l": "#c9d0dd", "sel": "#cfe0fb", "seltxt": "#12223f", "teal": "#0e7f86", "muted": "#53647c"}
FACE, TILE, INK, HEAD, FIELD, HI = (COLORS[k] for k in ("face", "tile", "ink", "head", "field", "hi"))
EDGE, EDGE_L, SEL, SELTXT, TEAL = (COLORS[k] for k in ("edge", "edge_l", "sel", "seltxt", "teal"))
VERSION = 1                      # change when a picture changes (they are cached in the user folder)

_images = None


def grad(a, b):
    return f"qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {a}, stop:1 {b})"


RAISED = f"background:{grad('#fbfcfe', '#e3e8f0')}; border:1px solid; border-color:{HI} {EDGE} {EDGE} {HI}; border-radius:3px;"
RAISED_HOT = f"background:{grad('#ffffff', '#dbe8fa')}; border:1px solid; border-color:{HI} #8fb0e0 #8fb0e0 {HI}; border-radius:3px;"
PRESSED = f"background:#d9dfe9; border:1px solid; border-color:{EDGE} {HI} {HI} {EDGE}; border-radius:3px;"
SUNKEN = f"background:{FIELD}; border:1px solid; border-color:{EDGE} {EDGE_L} {EDGE_L} {EDGE}; border-radius:3px;"

SECTION_BAR = (f"QPushButton {{ {RAISED} color:{HEAD}; text-align:left; padding:1px 8px 1px 6px; font-weight:bold; }}"
               f"QPushButton:hover {{ {RAISED_HOT} }}")
BODY = (f"QWidget#secbody {{ background:{TILE}; border:1px solid #d9dfe9; border-radius:4px; padding:3px; }}"
        "QWidget#secbody QLabel, QWidget#secbody QCheckBox, QWidget#secbody QRadioButton { background:transparent; }")
HELP = (f"QToolButton {{ background:{grad('#ffffff', '#eef1f6')}; border:1px solid #9aa7b8; border-radius:10px; color:{HEAD}; font-weight:bold; }}"
        "QToolButton:hover { background:#dbe8fa; } QToolButton:pressed { background:#d0d9e6; }")
SOLVE = (f"QPushButton {{ background:{grad('#17949b', TEAL)}; color:white; font-size:15px; font-weight:bold; margin:6px 4px; min-height:28px; border:1px solid; "
         "border-color:#5fc3c8 #0a5f64 #0a5f64 #5fc3c8; border-radius:5px; }"
         f"QPushButton:hover {{ background:{grad('#1ea4ab', '#12949c')}; }}"
         "QPushButton:pressed { background:#0c7078; border-color:#0a5f64 #5fc3c8 #5fc3c8 #0a5f64; }"
         "QPushButton:disabled { background:#cfd6df; color:#eef2f4; border:1px solid #bcc5d0; }")

# Stop / Cancel beside the Solve button: the same height as its face (the panel's own button look, only taller)
SOLVE_SIDE = "QPushButton { margin:6px 4px 6px 0px; min-height:28px; }"

# Tab bars with the soft look (the Study tab has one under its design-point table); added to stylesheet() for areas that hold tab widgets
TABS = (f"QTabBar::tab {{ background:{grad('#fbfcfe', '#e3e8f0')}; border:1px solid {EDGE_L}; border-bottom:none; padding:4px 14px; margin-right:2px; "
        f"border-top-left-radius:4px; border-top-right-radius:4px; color:{INK}; }}"
        f"QTabBar::tab:selected {{ background:{TILE}; font-weight:bold; color:{HEAD}; }}"
        f"QTabWidget::pane {{ border:1px solid #d9dfe9; border-radius:4px; background:{TILE}; top:-1px; }}")


def _draw(path, w, h, ratio, fn):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter
    im = QImage(int(w * ratio), int(h * ratio), QImage.Format.Format_ARGB32)
    im.fill(QColor(0, 0, 0, 0))
    p = QPainter(im)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(ratio, ratio)
    fn(p)
    p.end()
    return im.save(path)


def _box(on):
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QColor, QPen, QPolygonF

    def fn(p):
        p.setPen(QPen(QColor("#8b95a8"), 1))
        p.setBrush(QColor(FIELD))
        p.drawRoundedRect(QRectF(0.5, 0.5, 12, 12), 2.5, 2.5)
        p.setPen(QPen(QColor("#d3d9e4"), 1))                                  # a hint of inner shadow, top and left
        p.drawLine(QPointF(2, 1.5), QPointF(11, 1.5))
        p.drawLine(QPointF(1.5, 2), QPointF(1.5, 11))
        if on:
            pen = QPen(QColor(TEAL), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(3.2, 6.8), QPointF(5.6, 9.2), QPointF(9.8, 3.8)]))
    return fn


def _radio(on):
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QPen

    def fn(p):
        p.setPen(QPen(QColor("#8b95a8"), 1))
        p.setBrush(QColor(FIELD))
        p.drawEllipse(QRectF(0.5, 0.5, 12, 12))
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TEAL))
            p.drawEllipse(QRectF(3.5, 3.5, 6, 6))
    return fn


def _chevron(down):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QColor, QPen, QPolygonF

    def fn(p):
        pen = QPen(QColor(HEAD), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        pts = [QPointF(1.2, 1.2), QPointF(3.5, 3.4), QPointF(5.8, 1.2)] if down else [QPointF(1.2, 3.4), QPointF(3.5, 1.2), QPointF(5.8, 3.4)]
        p.drawPolyline(QPolygonF(pts))
    return fn


SHAPES = {"check_off": (13, 13, _box(False)), "check_on": (13, 13, _box(True)), "radio_off": (13, 13, _radio(False)),
          "radio_on": (13, 13, _radio(True)), "down": (7, 5, _chevron(True)), "up": (7, 5, _chevron(False))}


def images():
    """{name: path of the 1x picture}; the @2x picture sits next to it (Qt picks it on a high-resolution screen).  {} when it cannot be drawn."""
    global _images
    if _images is not None:
        return _images
    out = {}
    try:
        import paths
        d = os.path.join(paths.user_dir(), "sim_style", f"v{VERSION}")
        os.makedirs(d, exist_ok=True)
        for name, (w, h, fn) in SHAPES.items():
            p1, p2 = os.path.join(d, name + ".png"), os.path.join(d, name + "@2x.png")
            if not os.path.isfile(p1) and not _draw(p1, w, h, 1, fn):
                raise OSError(p1)
            if not os.path.isfile(p2) and not _draw(p2, w, h, 2, fn):
                raise OSError(p2)
            out[name] = p1.replace("\\", "/")
    except Exception:  # noqa: BLE001 - no pictures: the panel simply keeps the default check boxes and arrows
        out = {}
    _images = out
    return out


def stylesheet():
    im = images()

    def img(sel, name, extra=""):
        return f"{sel} {{ image:url({im[name]}); {extra} }}\n" if name in im else ""
    s = f"""
QWidget {{ background:transparent; }}
QWidget#simpanel, QWidget#simcontent {{ background:{FACE}; }}
QLabel {{ color:{INK}; background:transparent; }}
QCheckBox, QRadioButton {{ color:{INK}; spacing:6px; background:transparent; }}
QPushButton {{ {RAISED} color:{INK}; padding:2px 12px; min-height:19px; }}
QPushButton:hover {{ {RAISED_HOT} }}
QPushButton:pressed {{ {PRESSED} padding:3px 11px 1px 13px; }}
QPushButton:checked {{ {PRESSED} }}
QPushButton:disabled {{ color:#9aa4b5; background:#f1f3f7; border-color:#dfe4ec; }}
QToolButton {{ color:{INK}; }}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{ {SUNKEN} color:{INK}; padding:0 4px; min-height:20px; selection-background-color:{SEL}; selection-color:{SELTXT}; }}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{ border-color:#5b8fe0 {EDGE_L} {EDGE_L} #5b8fe0; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {{ background:#f1f3f7; color:#9aa4b5; }}
QComboBox {{ padding-right:20px; }}
QComboBox::drop-down {{ subcontrol-origin:border; subcontrol-position:right center; width:18px; border:none; border-left:1px solid {EDGE_L}; background:transparent; }}
QComboBox QAbstractItemView {{ background:white; border:1px solid {EDGE}; selection-background-color:{SEL}; selection-color:{SELTXT}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:16px; border:none; border-left:1px solid {EDGE_L}; background:transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:16px; border:none; border-left:1px solid {EDGE_L}; background:transparent; }}
QListWidget, QTreeWidget, QTableWidget, QTextEdit, QPlainTextEdit, QTextBrowser {{ {SUNKEN} color:{INK}; alternate-background-color:#f6f8fb; gridline-color:#e3e8f0; selection-background-color:{SEL}; selection-color:{SELTXT}; }}
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {{ background:{SEL}; color:{SELTXT}; }}
QHeaderView::section {{ background:{grad('#f9fafd', '#e6ebf3')}; color:#3d4a62; border:none; border-right:1px solid #d3dae6; border-bottom:1px solid {EDGE}; padding:3px 6px; min-height:18px; }}
QTableCornerButton::section {{ background:{grad('#f9fafd', '#e6ebf3')}; border:none; border-bottom:1px solid {EDGE}; }}
QGroupBox {{ border:1px solid #d3dae6; border-radius:4px; margin-top:9px; padding-top:8px; background:transparent; color:{INK}; }}
QGroupBox::title {{ subcontrol-origin:margin; left:9px; padding:0 4px; color:{HEAD}; }}
QProgressBar {{ {SUNKEN} text-align:center; color:{INK}; min-height:16px; }}
QProgressBar::chunk {{ background:{TEAL}; border-radius:2px; }}
QSlider::groove:horizontal {{ height:4px; background:#cfd6e3; border-radius:2px; }}
QSlider::handle:horizontal {{ width:12px; margin:-5px 0; {RAISED} border-radius:6px; }}
QScrollBar:vertical {{ width:10px; background:transparent; margin:0; border:none; }}
QScrollBar::handle:vertical {{ background:#c3cde0; border-radius:4px; min-height:24px; margin:1px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ height:10px; background:transparent; margin:0; border:none; }}
QScrollBar::handle:horizontal {{ background:#c3cde0; border-radius:4px; min-width:24px; margin:1px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
QScrollArea {{ background:{FACE}; border:none; }}
"""
    s += "QCheckBox::indicator { width:13px; height:13px; }\n"
    flat = "border:none; background:transparent; border-radius:0;"             # the program's own check box style has a blue frame: not under our picture
    s += img("QCheckBox::indicator:unchecked", "check_off", flat) + img("QCheckBox::indicator:checked", "check_on", flat)
    s += "QRadioButton::indicator { width:13px; height:13px; }\n"
    s += img("QRadioButton::indicator:unchecked", "radio_off", flat) + img("QRadioButton::indicator:checked", "radio_on", flat)
    s += "QAbstractItemView::indicator { width:13px; height:13px; }\n"
    s += img("QAbstractItemView::indicator:unchecked", "check_off", flat) + img("QAbstractItemView::indicator:checked", "check_on", flat)
    s += img("QComboBox::down-arrow", "down", "width:7px; height:5px;")
    s += img("QSpinBox::up-arrow, QDoubleSpinBox::up-arrow", "up", "width:7px; height:5px;")
    s += img("QSpinBox::down-arrow, QDoubleSpinBox::down-arrow", "down", "width:7px; height:5px;")
    return s
