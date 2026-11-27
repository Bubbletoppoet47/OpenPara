"""annotator_ribbon.py - the ribbon on top of the annotator window: tabs of big buttons, as in the Part window.

`Ribbon` is a QTabWidget (the tabs below the buttons, like the Part window's). A page is a row of buttons (`button(...)`) and dividers
("|"); every button is a QToolButton with an icon above its text (annotator_icons: on its own, without the icon kit, the text alone).
Nothing here knows what a button does: the window hands each one its function.

A page can also hold small blocks of fields (`field_block`: a label and a box on each line, and a line of small text under them), a column of
check boxes (`check_column`) and any other widget (`widget(key, w)`); buttons given the same `group` are one set of which only one is pressed.
"""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (QButtonGroup, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QTabWidget, QToolButton, QVBoxLayout, QWidget)

import annotator_icons as icons

HEIGHT = 104                       # the Part window's ribbon: 78 of buttons and the tab strip under them
ICON_PX = 36
BUTTON_QSS = ("QToolButton{font-size:11px; padding:2px;} QToolButton:disabled{color:#a0a0a0;}"
              " QToolButton:checked{background:#cfe3fb; border:1px solid #6aa0e0;}")
BOLD_QSS = " QToolButton{font-weight:600;}"


def button(key, icon, text, tip="", fn=None, checkable=False, menu=None, bold=False, group=None):
    """The description of one ribbon button (the Ribbon makes it): `fn` runs on a click, `menu` is a QMenu that opens instead,
    `checkable` makes it a switch (connect to its toggled signal); buttons with the same `group` (any name) are a set of which one is pressed."""
    return {"key": key, "icon": icon, "text": text, "tip": tip or text.replace("\n", " "), "fn": fn, "checkable": checkable or bool(group), "menu": menu, "bold": bold, "group": group}


def widget(key, w):
    """A page item that is a widget of the window's own (a block of fields, a column of check boxes ...): the Ribbon puts it in the row and returns it under `key`."""
    return {"key": key, "widget": w}


def field_block(rows, caption=None, label_px=84):
    """A block of fields for a page: `rows` = [(label, widget)], a label and a box on each line, then `caption` (a line of small text, returned too) under them.
    -> (the block, its caption label or None)."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(4, 4, 4, 0)
    v.setSpacing(2)
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setVerticalSpacing(3)
    form.setHorizontalSpacing(8)
    for text, w in rows:
        lab = QLabel(text)
        lab.setMinimumWidth(label_px)
        form.addRow(lab, w)
    v.addLayout(form)
    cap = None
    if caption is not None:
        cap = QLabel(caption)
        cap.setStyleSheet("font-size:11px;")
        v.addWidget(cap)
    v.addStretch(1)
    return box, cap


def readout(text="", width=96):
    """A read-only box for a number the window works out (it is shown, not typed)."""
    e = QLineEdit(text)
    e.setReadOnly(True)
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    e.setFixedWidth(width)
    e.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return e


def check_column(checks):
    """A column of check boxes for a page: `checks` = [QCheckBox]."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(6, 4, 6, 0)
    v.setSpacing(3)
    for c in checks:
        v.addWidget(c)
    v.addStretch(1)
    return box


def make_button(spec):
    b = QToolButton()
    b.setText(spec["text"])
    ic = icons.icon(spec["icon"], ICON_PX) if spec.get("icon") else None
    if ic is not None:
        b.setIcon(ic)
        b.setIconSize(QSize(ICON_PX, ICON_PX))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    else:
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    b.setToolTip(spec["tip"])
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)             # a click must not take the keyboard from the picture (its hotkeys)
    b.setMinimumSize(66, 70)
    b.setStyleSheet(BUTTON_QSS + (BOLD_QSS if spec.get("bold") else ""))
    if spec.get("menu") is not None:
        b.setMenu(spec["menu"])
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    elif spec.get("checkable"):
        b.setCheckable(True)
    elif spec.get("fn") is not None:
        b.clicked.connect(lambda _c=False, f=spec["fn"]: f())
    else:
        b.setEnabled(False)
    return b


class Ribbon(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(HEIGHT)
        self.setDocumentMode(True)
        self.setTabPosition(QTabWidget.TabPosition.South)
        self.buttons = {}                 # key -> QToolButton, over all pages
        self.page_index = {}              # page name -> tab index

    def add_page(self, name, items):
        """A tab named `name` with these buttons / "|" dividers; returns the buttons made, by key."""
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(2)
        made = {}
        groups = {}
        for it in items:
            if it == "|":
                f = QFrame()
                f.setFrameShape(QFrame.Shape.VLine)
                f.setFrameShadow(QFrame.Shadow.Sunken)
                lay.addWidget(f)
                continue
            if it.get("widget") is not None:
                lay.addWidget(it["widget"])
                made[it["key"]] = it["widget"]
                continue
            b = make_button(it)
            lay.addWidget(b)
            made[it["key"]] = b
            if it.get("group"):
                g = groups.get(it["group"])
                if g is None:
                    g = groups[it["group"]] = QButtonGroup(page)
                    g.setExclusive(True)
                g.addButton(b)
        lay.addStretch(1)
        sc = QScrollArea()
        sc.setWidget(page)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_index[name] = self.addTab(sc, name)
        self.buttons.update(made)
        return made

    def show_page(self, name):
        if name in self.page_index:
            self.setCurrentIndex(self.page_index[name])


def two_lines(text):
    """'Import Gimble session' -> 'Import Gimble\\nsession': a label under an icon wraps to two short lines."""
    text = text.strip()
    if "\n" in text or len(text) <= 11 or " " not in text:
        return text
    words = text.split(" ")
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])
