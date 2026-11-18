"""
sh_ribbon.py - the ribbon's buttons at a size the person sets.

    RibbonButton(glyph, text, icon_pt, text_pt)    a tool button that draws its glyph and its label in two sizes (the glyph is a text character, so any size is sharp)
    RibbonSizeDialog                               the two number boxes: ribbon icon size (pt) and ribbon text size (pt), applied as they change
    page_height(buttons, caption_pt)               how tall the ribbon has to be for the buttons it holds
"""
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPalette
from PyQt6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QStyle, QStyleOptionToolButton, QStylePainter, QToolButton,
                             QVBoxLayout)

import sh_prefs
import ui_kit


class RibbonButton(QToolButton):
    PAD = 4

    def __init__(self, glyph, text, icon_pt=20, text_pt=10, parent=None):
        super().__init__(parent)
        self.glyph, self.label = glyph, text
        self.setText(f"{glyph}\n{text}")                 # (what a screen reader and the tests read; the painting below ignores it)
        self.fg, self.fl = QFont(self.font()), QFont(self.font())
        self.set_sizes(icon_pt, text_pt)

    def set_sizes(self, icon_pt, text_pt):
        self.fg = QFont(self.font())
        self.fg.setPointSizeF(float(icon_pt))
        self.fl = QFont(self.font())
        self.fl.setPointSizeF(float(text_pt))
        hint = self.sizeHint()
        self.setMinimumSize(hint)
        self.updateGeometry()
        self.update()

    def _lines(self):
        return self.label.split("\n")

    def sizeHint(self):
        fg, fl = QFontMetrics(self.fg), QFontMetrics(self.fl)
        lines = self._lines()
        w = max([fg.horizontalAdvance(self.glyph)] + [fl.horizontalAdvance(x) for x in lines]) + 2 * self.PAD + 8
        h = fg.height() + fl.height() * len(lines) + 2 * self.PAD
        return QSize(max(w, 44), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, ev):
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        p.setPen(self.palette().color(group, QPalette.ColorRole.ButtonText))
        w = self.width()
        gh = QFontMetrics(self.fg).height()
        lh = QFontMetrics(self.fl).height()
        p.setFont(self.fg)
        p.drawText(QRect(0, self.PAD, w, gh), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.glyph)
        p.setFont(self.fl)
        y = self.PAD + gh
        for line in self._lines():
            p.drawText(QRect(0, y, w, lh), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, line)
            y += lh
        p.end()


def page_height(buttons, caption_pt):
    """The height the ribbon's pages need: the tallest button, the caption under it and some room."""
    tallest = max([b.sizeHint().height() for b in buttons] or [60])
    cap = QFontMetrics(_font(caption_pt)).height()
    return tallest + cap + 22


def _font(pt):
    f = QFont()
    f.setPointSizeF(float(pt))
    return f


class RibbonSizeDialog(QDialog):
    """Ribbon icon size and text size.  The ribbon follows each change at once and the numbers are kept in Sheets' own settings file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ribbon size")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.icon = QSpinBox()
        self.text = QSpinBox()
        for box, key, suffix in ((self.icon, "ribbon_icon", " pt"), (self.text, "ribbon_text", " pt")):
            lo, hi = sh_prefs.LIMITS[key]
            box.setRange(lo, hi)
            box.setSuffix(suffix)
            box.setValue(int(sh_prefs.get(key)))
            box.setKeyboardTracking(False)
        form.addRow("Icon size", self.icon)
        form.addRow("Text size", self.text)
        lay.addLayout(form)
        lb = QLabel(f"Icons {sh_prefs.LIMITS['ribbon_icon'][0]}-{sh_prefs.LIMITS['ribbon_icon'][1]} pt, text {sh_prefs.LIMITS['ribbon_text'][0]}-{sh_prefs.LIMITS['ribbon_text'][1]} pt.")
        lb.setStyleSheet(f"color:{ui_kit.MUTED}; font-size:11px;")
        lay.addWidget(lb)
        row = QHBoxLayout()
        b_reset = QPushButton("Reset")
        b_close = QPushButton("Close")
        ui_kit.primary(b_close)
        row.addWidget(b_reset)
        row.addStretch(1)
        row.addWidget(b_close)
        lay.addLayout(row)
        self.icon.valueChanged.connect(lambda v: sh_prefs.set_many({"ribbon_icon": v}))
        self.text.valueChanged.connect(lambda v: sh_prefs.set_many({"ribbon_text": v}))
        b_reset.clicked.connect(lambda _c=False: self.reset())
        b_close.clicked.connect(lambda _c=False: self.accept())

    def reset(self):
        sh_prefs.set_many({"ribbon_icon": sh_prefs.DEFAULTS["ribbon_icon"], "ribbon_text": sh_prefs.DEFAULTS["ribbon_text"]})
        self.icon.setValue(int(sh_prefs.get("ribbon_icon")))
        self.text.setValue(int(sh_prefs.get("ribbon_text")))
