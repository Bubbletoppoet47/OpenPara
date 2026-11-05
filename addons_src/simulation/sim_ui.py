"""
sim_ui.py - the shared building blocks of the left panels of 1D FEA, 2D FEA and 2D CFD.

  Section      a numbered, collapsible block: header (click to fold / unfold, one-line summary while folded, optional "?" help) + body
  icon_button  a full-width button with a sketched icon, text left-aligned (supports and loads are stacked with these)
  help_button  a small "?" that opens a pop-up with a long note, so the panel itself stays short
  make_panel   puts the scrolling sections and the pinned bar (Mesh / Solve ...) into one widget

Whether a section is folded is remembered between runs (sim_panels.json in the user folder).
"""
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

import paths
import sim_icons

STATE_FILE = "sim_panels.json"
_state = None


def _load():
    global _state
    if _state is None:
        try:
            with open(os.path.join(paths.user_dir(), STATE_FILE), encoding="utf-8") as f:
                _state = json.load(f)
            if not isinstance(_state, dict):
                _state = {}
        except (OSError, ValueError):
            _state = {}
    return _state


def remembered(key, default):
    v = _load().get(key, default)
    return bool(v)


def remember(key, value):
    st = _load()
    st[key] = bool(value)
    try:
        with open(os.path.join(paths.user_dir(), STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(st, f)
    except OSError:
        pass


class HelpPopup(QFrame):
    """A small pop-up frame with a wrapped text; it closes on any click outside it."""

    def __init__(self, text, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet("QFrame { background:#fffdf5; border:1px solid #bfae6a; } QLabel { border:none; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setMinimumWidth(280)
        lb.setMaximumWidth(340)
        lb.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(lb)


def help_button(text):
    b = QToolButton()
    b.setText("?")
    b.setToolTip("What is this?")
    b.setFixedSize(20, 20)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet("QToolButton { border:1px solid #9aa7b8; border-radius:10px; color:#53647c; background:white; font-weight:bold; } "
                    "QToolButton:hover { background:#e6f3f4; }")

    def show():
        b._popup = HelpPopup(text, b)
        b._popup.move(QCursor.pos())
        b._popup.show()
    b.clicked.connect(show)
    b.help_text = text
    return b


def icon_button(text, icon_name=None, tip=None, checkable=False):
    b = QPushButton("  " + text)
    if icon_name:
        b.setIcon(sim_icons.icon(icon_name))
        from PyQt6.QtCore import QSize
        b.setIconSize(QSize(22, 22))
    b.setStyleSheet("QPushButton { text-align:left; padding:4px 8px; }")
    b.setMinimumHeight(30)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.setCheckable(checkable)
    if tip:
        b.setToolTip(tip)
    return b


class Section(QWidget):
    """A numbered block of the panel.  Put its widgets into `.body` (a QVBoxLayout).  `summary` (a callable returning text) is shown on the
    header line while the block is folded."""

    def __init__(self, kind, number, title, open_=True, help_text=None, summary=None):
        super().__init__()
        self.key = f"{kind}/{title}"
        self.title = title
        self.number = number
        self.summary = summary
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setFlat(True)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle.setMinimumHeight(26)
        self.toggle.setStyleSheet("QPushButton { text-align:left; border:none; border-bottom:1px solid #cfd6e0; padding:3px 2px; font-weight:bold; "
                                  "color:#16324f; } QPushButton:hover { background:#eef4f7; }")
        head.addWidget(self.toggle, 1)
        self.help = None
        if help_text:
            self.help = help_button(help_text)
            head.addWidget(self.help)
        outer.addLayout(head)
        self.sum_lbl = QLabel("")
        self.sum_lbl.setStyleSheet("color:#53647c; font-size:11px; padding-left:18px;")
        self.sum_lbl.setWordWrap(True)
        outer.addWidget(self.sum_lbl)
        self.frame = QWidget()
        self.body = QVBoxLayout(self.frame)
        self.body.setContentsMargins(4, 4, 2, 4)
        outer.addWidget(self.frame)
        self.toggle.toggled.connect(self.set_open)
        self.toggle.setChecked(remembered(self.key, open_))
        self.set_open(self.toggle.isChecked(), save=False)

    def set_open(self, on, save=True):
        self.frame.setVisible(on)
        self.toggle.setText(f"{'▾' if on else '▸'}  {self.number}   {self.title}")
        self.refresh_summary()
        if save:
            remember(self.key, on)

    def is_open(self):
        return self.toggle.isChecked()

    def refresh_summary(self):
        txt = ""
        if not self.is_open() and self.summary is not None:
            try:
                txt = self.summary() or ""
            except Exception:  # noqa: BLE001 - a summary must never break the panel
                txt = ""
        self.sum_lbl.setText(txt)
        self.sum_lbl.setVisible(bool(txt))


def solve_button(text="Solve"):
    """The one big full-width Solve button that sits between the setup sections and the Results."""
    b = QPushButton(text)
    b.setMinimumHeight(46)
    b.setStyleSheet("QPushButton { background:#0e7f86; color:white; font-size:15px; font-weight:bold; border:none; border-radius:8px; margin:6px 4px; }"
                    "QPushButton:hover { background:#12949c; } QPushButton:disabled { background:#b9c4cc; color:#eef2f4; }")
    return b


def study_slot():
    """An empty box right under the Solve button.  The window around the tab puts the 'parametric study' button of that add-on in it (when it is
    installed); while it is empty the box is hidden."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(4, 0, 4, 4)
    box.hide()
    return box


def make_panel(content, pinned_widgets, min_w=340, max_w=400):
    """`content`: the widget holding the Sections (it is scrolled).  `pinned_widgets`: widgets (or layouts) that stay visible below the scroll
    area.  Returns the panel widget for the splitter."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    panel = QWidget()
    pl = QVBoxLayout(panel)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(0)
    pl.addWidget(scroll, 1)
    panel.bar = None
    if not pinned_widgets:
        panel.setMinimumWidth(min_w)
        panel.setMaximumWidth(max_w)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        panel.scroll = scroll
        return panel
    bar = QFrame()
    bar.setFrameShape(QFrame.Shape.NoFrame)
    bar.setStyleSheet("QFrame#pinned { border-top:1px solid #cfd6e0; background:#f6f8fa; }")
    bar.setObjectName("pinned")
    bl = QHBoxLayout(bar)
    bl.setContentsMargins(6, 6, 6, 6)
    for w in pinned_widgets:
        bl.addWidget(w, 1)
    pl.addWidget(bar)
    panel.setMinimumWidth(min_w)
    panel.setMaximumWidth(max_w)
    panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    panel.scroll = scroll
    panel.bar = bar
    return panel
