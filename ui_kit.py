"""
ui_kit.py - small building blocks every window of the program and of its add-ons can share, so they look and behave like one program.

    fit_panel(split, panel, content)      a side panel opens as wide as its contents need - nothing cut off, no sideways scroll bar
    fit_dock(window, dock, content)       the same for a dock panel;   tame_combo(combo)  a long drop-down that does not force the panel wide
    EmptyState(title, text, actions)      what a view shows while there is nothing in it yet: what this is for, and the buttons to begin
    Section(kind, n, title)               a numbered, foldable block of a side panel (the look of the simulation panels), fold remembered
    top_bar(window, bar)                  the bar on top of a QMainWindow-based tab (its menu bar is hidden, never deleted)
    StatusLine()                          one quiet line for "what just happened" at the bottom of a tab
    kind_chip(text)                       a small coloured label that says what kind of document this is
    primary(button) / quiet(button)       the two button weights: the one action that moves the work on, and everything else
    note(text)                            a grey, wrapping note under a control

Colours are the ones of the program's theme (pm_app.THEME); nothing here knows about any add-on.
"""
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QToolBar, QToolTip, QVBoxLayout, QWidget

INK = "#1f2a3c"
MUTED = "#6a7790"
FAINT = "#9aa3b2"
LINE = "#d5dbe6"
BG = "#f3f5f9"
ACCENT = "#2b7de9"
ACCENT_DARK = "#1a56c4"
TEAL = "#0e7f86"
WARN = "#a05000"
BAD = "#b00020"
GOOD = "#2e7d32"

PRIMARY_QSS = (f"QPushButton {{ background:{TEAL}; color:white; font-weight:600; border:none; border-radius:6px; padding:7px 16px; }}"
               "QPushButton:hover { background:#12949c; } QPushButton:pressed { background:#0b6a70; }"
               "QPushButton:disabled { background:#b9c4cc; color:#eef2f4; }")


def primary(b):
    """The one button of a panel that moves the work on (Solve, Run, Start training): teal, bold."""
    b.setStyleSheet(PRIMARY_QSS)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def note(text, color=MUTED):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet(f"color:{color}; font-size:11px;")
    return lb


def kind_chip(text, color="#7c4dcc"):
    """A small rounded label ("1D FEA", "Study") in the colour of that family of documents."""
    lb = QLabel(text)
    lb.setStyleSheet(f"background:{color}; color:white; font-weight:600; font-size:11px; border-radius:9px; padding:2px 9px;")
    lb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lb


def content_width(content):
    """The width a scrolled panel needs so that its contents are shown whole, with room for the vertical scroll bar."""
    try:
        content.ensurePolished()
        if content.layout() is not None:
            content.layout().activate()
        w = max(content.minimumSizeHint().width(), content.layout().minimumSize().width() if content.layout() is not None else 0)
    except RuntimeError:
        return 0
    bar = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent) if QApplication.instance() else 16
    return w + bar + 6


class _Fitter(QObject):
    """Keeps a side panel at least as wide as its contents need.  It sets the width when the tab is built and widens the panel when the
    contents grow later (a longer label after an import, a section that is unfolded) - but never after the user dragged the divider, and it
    never makes the panel narrower: what the user sized stays."""
    def __init__(self, content, lo, hi, get_w, set_w, moved_signal=None):
        super().__init__(content)
        self.content, self.lo, self.hi, self.get_w, self.set_w = content, lo, hi, get_w, set_w
        self.user = False
        self.busy = False
        if moved_signal is not None:
            moved_signal.connect(self.dragged)
        content.installEventFilter(self)

    def dragged(self, *_a):
        if not self.busy:
            self.user = True

    def want(self):
        return max(self.lo, min(self.hi, content_width(self.content)))

    def apply(self, grow_only=False):
        if self.busy:
            return
        self.busy = True
        try:
            w = self.want()
            if not grow_only or (not self.user and w > self.get_w() + 1):
                self.set_w(w)
        except RuntimeError:
            pass                                              # the tab was closed before the first layout
        finally:
            self.busy = False

    def eventFilter(self, obj, ev):
        if obj is self.content and ev.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, lambda: self.apply(grow_only=True))
        return False


def fit_panel(split, panel, content, lo=340, hi=640, index=0):
    """Makes the side panel `panel` (pane `index` of the splitter) as wide as `content` needs, between `lo` and `hi` pixels; the rest of the
    splitter gets what is left.  Set when the tab is built, again when it is first laid out (fonts and styles are known then), and widened
    when the contents grow - until the user drags the divider, which then stays where they put it.  The width is not remembered."""
    def get_w():
        return split.sizes()[index]

    def set_w(want):
        sizes = split.sizes()
        n = split.count()
        others = [i for i in range(n) if i != index]
        total = sum(sizes)
        new = [0] * n
        new[index] = want
        if total <= 0:                                        # not laid out yet: the panel gets its width, the view gets the rest
            for i in others:
                new[i] = 1000
        else:
            rest = max(200, total - want)
            had = sum(sizes[i] for i in others)
            for i in others:
                new[i] = int(rest * sizes[i] / had) if had > 0 else rest // max(1, len(others))
        split.setSizes(new)
        panel.fitted_w = want
    f = _Fitter(content, lo, hi, get_w, set_w, split.splitterMoved)
    panel.fitter = f
    f.apply()
    QTimer.singleShot(0, f.apply)
    return panel


def fit_dock(window, dock, content, lo=340, hi=640):
    """The same for a panel that is a dock of a QMainWindow (the Visualize properties): as wide as its contents need."""
    def set_w(want):
        dock.setMinimumWidth(min(want, lo))
        window.resizeDocks([dock], [want], Qt.Orientation.Horizontal)
        dock.fitted_w = want
    f = _Fitter(content, lo, hi, lambda: dock.width(), set_w)
    dock.fitter = f
    f.apply()
    QTimer.singleShot(0, f.apply)
    return dock


def tame_combo(combo, chars=16):
    """A drop-down with long entries no longer forces its panel wide: it asks for room for `chars` characters, shows the whole text in the
    list that drops down, and the whole current text as a tooltip."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setMinimumWidth(combo.sizeHint().width())          # (Qt keeps the old, wide minimum otherwise: a layout would still give it the full width)
    try:
        combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 28)
    except Exception:
        pass
    combo.currentTextChanged.connect(lambda t, c=combo: c.setToolTip(t))
    combo.setToolTip(combo.currentText())
    return combo


class EmptyState(QWidget):
    """What a view shows while there is nothing in it: a title, one or two plain sentences, and the buttons that begin the work.
    actions: [(text, fn)] - the first one is the main action."""
    def __init__(self, title, text="", actions=(), parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"font-size:15px; font-weight:600; color:{INK};")
        lay.addWidget(self.title)
        self.text = QLabel(text)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setFixedWidth(460)                          # a wrapping label needs its width said, or the centred layout makes it a narrow column
        self.text.setStyleSheet(f"color:{MUTED};")
        self.text.setVisible(bool(text))
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.buttons = []
        for i, (label, fn) in enumerate(actions):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, f=fn: f())
            if i == 0:
                primary(b)
            row.addWidget(b)
            self.buttons.append(b)
        if actions:
            lay.addSpacing(6)
            lay.addLayout(row)

    def set_text(self, title=None, text=None):
        if title is not None:
            self.title.setText(title)
        if text is not None:
            self.text.setText(text)
            self.text.setVisible(bool(text))


class StatusLine(QLabel):
    """One line at the bottom of a tab for what just happened.  say(text) shows it; say(text, "warn" / "bad" / "good") colours it."""
    COLORS = {"": MUTED, "warn": WARN, "bad": BAD, "good": GOOD}

    def __init__(self, text=""):
        super().__init__(text)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setMinimumWidth(40)                              # a long message never widens the window: it is cut with "..." and shown whole on hover
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.full = text
        self.say(text)

    def say(self, text, level=""):
        self.full = text or ""
        self.setStyleSheet(f"color:{self.COLORS.get(level, MUTED)}; padding:2px 6px;")
        self.setToolTip(self.full)
        self.elide()

    def setText(self, text):                                  # used like a plain label: the whole text is kept, the line shows what fits
        self.say(text)

    def text(self):
        return self.full

    def elide(self):
        fm = self.fontMetrics()
        QLabel.setText(self, fm.elidedText(self.full.replace("\n", "  "), Qt.TextElideMode.ElideRight, max(40, self.width() - 12)))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.elide()


# ---------------------------------------------------------------- numbered, foldable sections of a side panel
PANEL_STATE = "panels.json"
_panel_state = None


def _panels():
    global _panel_state
    if _panel_state is None:
        _panel_state = {}
        try:
            import json
            import os
            import paths
            with open(os.path.join(paths.user_dir(), PANEL_STATE), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                _panel_state = d
        except (OSError, ValueError, ImportError):
            pass
    return _panel_state


def _remember_panel(key, value):
    st = _panels()
    st[key] = bool(value)
    try:
        import json
        import os
        import paths
        with open(os.path.join(paths.user_dir(), PANEL_STATE), "w", encoding="utf-8") as f:
            json.dump(st, f)
    except (OSError, ImportError):
        pass


class Section(QWidget):
    """A numbered block of a side panel, the same as in the simulation tabs: a heading that folds the block away (the fold is remembered),
    a one-line summary while it is folded, an optional "?" with a longer note.  Put the widgets into  .body  (a QVBoxLayout).
    kind: a name for the panel it belongs to (the key under which the fold is remembered)."""
    HEAD_QSS = ("QPushButton { text-align:left; border:none; border-bottom:1px solid #cfd6e0; padding:3px 2px; font-weight:bold; color:#16324f; }"
                "QPushButton:hover { background:#eef4f7; }")

    def __init__(self, kind, number, title, open_=True, help_text=None, summary=None):
        super().__init__()
        self.key = f"{kind}/{title}"
        self.title, self.number, self.summary = title, number, summary
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
        self.toggle.setStyleSheet(self.HEAD_QSS)
        head.addWidget(self.toggle, 1)
        self.help = None
        if help_text:
            self.help = QPushButton("?")
            self.help.setFixedSize(20, 20)
            self.help.setCursor(Qt.CursorShape.PointingHandCursor)
            self.help.setToolTip(help_text)
            self.help.setStyleSheet("QPushButton { border:1px solid #9aa9bb; border-radius:10px; color:#3d5a80; font-weight:bold; background:#ffffff; padding:0; }"
                                    "QPushButton:hover { background:#e6efff; }")
            self.help.clicked.connect(lambda: QToolTip.showText(self.help.mapToGlobal(self.help.rect().bottomLeft()), help_text, self.help))
            head.addWidget(self.help)
        outer.addLayout(head)
        self.sum_lbl = QLabel("")
        self.sum_lbl.setStyleSheet("color:#53647c; font-size:11px; padding-left:18px;")
        self.sum_lbl.setWordWrap(True)
        outer.addWidget(self.sum_lbl)
        self.frame = QWidget()
        self.body = QVBoxLayout(self.frame)
        self.body.setContentsMargins(6, 4, 4, 6)
        outer.addWidget(self.frame)
        self.toggle.toggled.connect(self.set_open)
        self.toggle.setChecked(bool(_panels().get(self.key, open_)))
        self.set_open(self.toggle.isChecked(), save=False)

    def set_open(self, on, save=True):
        self.frame.setVisible(on)
        num = f"{self.number}   " if self.number not in (None, "") else ""
        self.toggle.setText(f"{'▾' if on else '▸'}  {num}{self.title}")
        self.refresh_summary()
        if save:
            _remember_panel(self.key, on)

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


VIEW_BG = ("#f7f9fc", "#cfd9ea")                             # the 3D views of the program: bottom and top of the soft gradient


def view_background(plotter):
    """The background every 3D view of the program has (the Part and Assembly windows' soft gradient)."""
    try:
        plotter.set_background(VIEW_BG[0], top=VIEW_BG[1])
    except Exception:
        pass


BUTTON_QSS = ("QToolButton { background:#ffffff; border:1px solid #c8d0de; border-radius:5px; padding:4px 12px; }"
              "QToolButton:hover { background:#e6efff; border-color:#2b7de9; } QToolButton::menu-indicator { image:none; }")


def menu_button(tool_button):
    """A drop-down tool button that looks like the push buttons next to it (and shows one arrow, not two)."""
    tool_button.setStyleSheet(BUTTON_QSS)
    return tool_button


def top_bar(window, bar):
    """Puts `bar` (the chip + commands strip) at the top of a QMainWindow-based tab and hides the window's own menu bar.
    The menu bar is only hidden, never replaced: QMainWindow.setMenuWidget() would delete it, and with it the menus that the bar's drop-down
    buttons show.  Returns the (fixed) tool bar that holds the bar."""
    window.menuBar().hide()
    tb = QToolBar(window)
    tb.setObjectName("topbar")
    tb.setMovable(False)
    tb.setFloatable(False)
    tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
    tb.toggleViewAction().setEnabled(False)                   # it cannot be switched off from a right-click list
    tb.setStyleSheet("QToolBar#topbar { border:0; padding:0; spacing:0; background:transparent; }")
    bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    tb.addWidget(bar)
    window.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
    window.top_bar = tb
    return tb


def hline():
    ln = QFrame()
    ln.setFrameShape(QFrame.Shape.HLine)
    ln.setStyleSheet(f"color:{LINE};")
    return ln
