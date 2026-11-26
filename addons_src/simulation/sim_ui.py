"""
sim_ui.py - the shared building blocks of the left panels of 1D FEA, 2D FEA and 2D CFD.

  Section      a numbered, collapsible block: header (click to fold / unfold, one-line summary while folded, optional "?" help) + body
  icon_button  a full-width button with a sketched icon, text left-aligned (supports and loads are stacked with these)
  solve_button / solve_side_button   the Solve button (a plain grey button, like Mesh) and the Stop / Cancel button beside it; results_head puts them at the top of the Results page
  help_button  a small "?" that opens a pop-up with a long note, so the panel itself stays short
  make_panel   puts the scrolling sections and the pinned bar (Mesh / Solve ...) into one widget
  soften       gives a finished panel the soft bevel look of sim_style (make_panel does it; call it again when sections are added later)
  outlinize    turns a finished panel into the ANSYS-style column: an Outline (tree) on top and the Details of the selected item below (sim_outline); the sections become its pages

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
    b.setProperty("simrole", "help")
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
        self.head_lay = head
        self.embedded = False                 # True once the section is a page of an Outline's Details (embed)
        self.on_reveal = None
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

    def embed(self, on_reveal=None):
        """The section becomes a page of the Details of an Outline: no fold bar, no one-line summary, always open (its '?' stays).  Asking it to open (a window revealing it)
        selects its node in the outline."""
        self.embedded = True
        self.on_reveal = on_reveal
        self.toggle.hide()
        self.sum_lbl.hide()
        self.frame.show()
        if self.help is not None:
            self.head_lay.insertStretch(0, 1)

    def set_open(self, on, save=True):
        if self.embedded:
            if on and callable(self.on_reveal):
                self.on_reveal()
            return
        self.frame.setVisible(on)
        self.toggle.setText(f"{'▾' if on else '▸'}  {self.number}   {self.title}")
        self.refresh_summary()
        if save:
            remember(self.key, on)

    def is_open(self):
        return self.toggle.isChecked()

    def soften(self):
        """The soft bevel look (sim_style): a raised bar for the header, a faint tile around the open part."""
        import sim_style
        self.toggle.setStyleSheet(sim_style.SECTION_BAR)
        self.sum_lbl.setStyleSheet("color:#53647c; font-size:11px; padding-left:18px; background:transparent;")
        self.frame.setObjectName("secbody")
        self.frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.frame.setStyleSheet(sim_style.BODY)

    def refresh_summary(self):
        txt = ""
        if not self.is_open() and self.summary is not None:
            try:
                txt = self.summary() or ""
            except Exception:  # noqa: BLE001 - a summary must never break the panel
                txt = ""
        self.sum_lbl.setText(txt)
        self.sum_lbl.setVisible(bool(txt))


SOLVE_KEY = "F5"


def solve_button(text="Solve"):
    """The Solve button.  It sits at the top of the Results page and looks like the Mesh button (a plain grey button), not like a call to action."""
    b = QPushButton(text)
    b.setProperty("simrole", "solvemain")
    b.setMinimumHeight(30)
    b.setToolTip(f"Solve ({SOLVE_KEY} from any page of this window)")
    return b


def solve_side_button(text):
    """Stop / Cancel, sitting right of the Solve button: as tall as it, and as plain."""
    b = QPushButton(text)
    b.setProperty("simrole", "solveplain")
    b.setMinimumHeight(30)
    return b


def results_head(lay, *items):
    """Puts the Solve button (and what belongs to it: Stop / Cancel, the progress, the chart) at the top of a Results section: `lay` is its body, `items` are widgets or layouts,
    in the order they are shown."""
    from PyQt6.QtWidgets import QLayout
    for k, it in enumerate(items):
        if isinstance(it, QLayout):
            lay.insertLayout(k, it)
        else:
            lay.insertWidget(k, it)


def solve_row(solve, side=None):
    """The Solve button with its Stop / Cancel button on its right: -> a widget holding the row."""
    row = QWidget()
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(solve, 1)
    if side is not None:
        rl.addWidget(side)
    return row


def solve_shortcut(window, button):
    """The key that presses `button` from any page of `window` (and from its view): it does nothing while the button is off."""
    from PyQt6.QtGui import QKeySequence, QShortcut
    sh = QShortcut(QKeySequence(SOLVE_KEY), window)
    sh.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    sh.activated.connect(lambda: button.isEnabled() and button.click())
    window.solve_key = sh
    return sh


def study_slot():
    """An empty box right under the Solve button.  The window around the tab puts the 'parametric study' button of that add-on in it (when it is
    installed); while it is empty the box is hidden."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(4, 0, 4, 4)
    box.hide()
    return box


SIDE_W = 420                                         # the width every analysis window's left panel opens at (1D, 2D and 3D alike); every page fits in it


def make_panel(content, pinned_widgets, min_w=340, max_w=None):
    """`content`: the widget holding the Sections (it is scrolled).  `pinned_widgets`: widgets (or layouts) that stay visible below the scroll
    area.  Returns the panel widget for the splitter.  There is no maximum width: the user drags the divider to make the panel as wide as they like
    (it starts about `panel.default_w` wide; the width is not remembered).  A horizontal scroll bar appears if the panel is made narrower than
    its content.  `max_w` is only for a caller that really wants a cap."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        panel.setMaximumWidth(max_w if max_w else 16777215)
        panel.default_w = SIDE_W
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        panel.scroll = scroll
        soften(panel)
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
    panel.setMaximumWidth(max_w if max_w else 16777215)
    panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    panel.scroll = scroll
    panel.bar = bar
    soften(panel)
    return panel


def soften(panel):
    """Gives a panel (from make_panel) the soft bevel look of sim_style.  Safe to call again, for instance after more sections were added."""
    try:
        import sim_style
        sheet = sim_style.stylesheet()
    except Exception:  # noqa: BLE001 - a look must never break the panel
        return panel
    panel.setObjectName("simpanel")
    panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    content = panel.scroll.widget() if getattr(panel, "scroll", None) is not None else None
    if content is not None:
        content.setObjectName("simcontent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    panel.setStyleSheet(sheet)
    for s_ in panel.findChildren(Section):
        s_.soften()
    for b in panel.findChildren(QPushButton):
        if b.property("simrole") == "solve":
            b.setStyleSheet(sim_style.SOLVE)
        elif b.property("simrole") == "solveside":
            b.setStyleSheet(sim_style.SOLVE_SIDE)
    for tb in panel.findChildren(QToolButton):
        if tb.text() == "?":
            tb.setStyleSheet(sim_style.HELP)
    return panel


_PLAIN = [0]


class plain_panels:
    """`with plain_panels():` the windows made meanwhile (the hidden scratch window a study builds for every case, which nobody ever sees) get no Outline: their sections stay where
    make_panel put them.  Building the tree for each of hundreds of cases doubled the time of a study."""

    def __enter__(self):
        _PLAIN[0] += 1
        return self

    def __exit__(self, *a):
        _PLAIN[0] -= 1


def _holds_widgets(lay):
    """True when a layout holds a widget or another layout (stretches and spacers do not count)."""
    if lay is None:
        return False
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it.widget() is not None or it.layout() is not None:
            return True
    return False


def outlinize(panel, window=None, kind="sim", order=None):
    """Makes the finished panel of a window (make_panel, with all its Sections in) the ANSYS-style column: the Sections move into an Outline (a tree of them, in the order a model is
    built) with the Details of the selected one below it, and what else was in the panel stays under them, always in
    view (the Solve button is not one of these: it is at the top of the Results page).  -> the sim_outline.Outline, or None when the panel has no sections.  `window` may offer outline_items / outline_marks / outline_selected (see sim_outline).  `order`: the titles of the sections in the order the rows are wanted (a window whose rows are not the usual ones of a model: the Coupled Physics window)."""
    if _PLAIN[0]:
        return None
    scroll = getattr(panel, "scroll", None)
    content = scroll.widget() if scroll is not None else None
    if content is None:
        return None
    secs = content.findChildren(Section)
    if not secs:
        return None
    import sim_outline
    ol = sim_outline.Outline(kind)
    lay = content.layout()
    for s_ in sorted(secs, key=(lambda x: (order.index(x.title) if x.title in order else len(order), x.number)) if order else sim_outline.rank):
        if lay is not None:
            lay.removeWidget(s_)
        ol.add_section(s_)
    pl = panel.layout()
    scroll.takeWidget()
    pl.removeWidget(scroll)
    scroll.hide()
    content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    pl.insertWidget(0, ol, 1)
    if _holds_widgets(lay):
        pl.insertWidget(1, content, 0)                 # something else is in the panel (not the Solve button: that is on the Results page): it stays under the Outline
        content.show()
    else:
        content.setParent(panel)                       # nothing: no strip under the Details at all
        content.hide()
    panel.default_w = SIDE_W
    panel.outline = ol
    soften(panel)
    ol.select(next(iter(ol.keys())))
    ol.touched = False
    if window is not None:
        window.outline = ol
        ol.attach(window)
    return ol


def soften_area(widget, tabs=False):
    """The soft bevel look for an area that is not a make_panel panel (the bar and the tables of the Study tab): the style sheet of the panels, set on
    this widget and so only on what is inside it (a dialog opened from the area keeps the program's look).  `tabs`: the area holds a tab widget."""
    try:
        import sim_style
        sheet = sim_style.stylesheet() + (sim_style.TABS if tabs else "")
    except Exception:  # noqa: BLE001 - a look must never break the window
        return widget
    widget.setObjectName("simpanel")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setStyleSheet(sheet)
    return widget


def fit_side_panel(split, panel, content):
    """The panel opens SIDE_W wide in every analysis window (the same width everywhere, so moving between a 1D, 2D or 3D window does not move the
    divider); the view gets the rest.  Every page is laid out to fit in it with no sideways scroll bar.  The user can still drag the divider; the width
    is not remembered."""
    try:
        import ui_kit
        ui_kit.fit_panel(split, panel, content, lo=SIDE_W, hi=SIDE_W)
    except ImportError:                                  # a program older than this add-on: the fixed start width
        split.setSizes([SIDE_W, 1000])


def tame(combo, chars=18):
    """A drop-down with long entries does not force the panel wide (ui_kit.tame_combo); the whole text is in the list and in the tooltip."""
    try:
        import ui_kit
        return ui_kit.tame_combo(combo, chars)
    except ImportError:
        return combo


def wrapped(text):
    """A plain label that wraps instead of forcing the panel wide."""
    lb = QLabel(text)
    lb.setWordWrap(True)
    return lb
