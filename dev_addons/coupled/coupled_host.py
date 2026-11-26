"""coupled_host.py - what the Coupled Physics window is made of besides the coupling itself: the STRIP of buttons at the top of its left column (Fluid, Thermal, Structural, Coupled, Viz; each
with a mark top right), and the HOSTING of the analyses: the side panel (with its Outline and Details) and the model view of a Fluid, Thermal or Structural window are taken out of that
window and shown inside the Coupled window, one analysis at a time.  The analysis window itself stays alive and hidden: the engine keeps driving it (its own mesh, its own Solve, its own
result) exactly as before; only where its two panes are shown has changed.

Hosting moves widgets, it does not copy them: whatever the analysis window does with its panes (selecting an Outline row, repainting the view) keeps working.  Four small things go with the move:
the status messages of the analysis (they were written in the status line of its own tab) are sent to the status line of the Coupled window; the F5 key (Solve of that analysis) is bound to
the panes where they are now; the width helper of the panel is told its splitter is empty; and the analysis window becomes a hidden child of the Coupled window (so that a dialog it opens has a
window to stand over).

This was tried in a headless Qt (the same Qt, no real screen): the panes of the 2D windows move, draw, and keep their Outline working.  Nothing was seen on Windows, and the 3D views (OpenGL)
were never drawn at all here: a 3D window's panes are moved before it was ever shown, which is the safest moment, but that is a reason to look at it on a real screen, not a result."""
from PyQt6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QSplitter, QWidget

import sim_outline
import sim_ui

ROLES = (("fluid", "Fluid"), ("thermal", "Thermal"), ("structural", "Structural"), ("coupled", "Coupled"), ("viz", "Viz"))
MEMBER_ROLES = ("fluid", "thermal", "structural")
NAMES = dict(ROLES)
TEAL, INK, MUTED, EDGE, BAR = "#1f7a84", "#374151", "#4a5563", "#c5ced9", "#e4ebf2"
STRIP_H = 56
HOSTED_KINDS = ("thermal", "fea", "cfd")                           # the kinds of analysis window whose panes can be hosted (the 3D windows are added by hosting_kinds())
TIPS = {"fluid": "The fluid flow analysis: its own Outline, its own model view", "thermal": "The heat analysis: its own Outline, its own model view",
        "structural": "The stress analysis: its own Outline, its own model view", "coupled": "Solving the analyses together: the coupling, the options, Solve and the report",
        "viz": "The picture of the last coupled solve"}
MARK_TIPS = {"ok": "", "update": "", "incomplete": ""}

# the line pictures of the strip (18 x 18, stroke 1.5, round caps and joins, no fill)
ICON_BODY = {
    "fluid": "".join(f'<path d="M1.5 {y}c2-2 3 2 5 0s3 2 5 0 3 2 4 0"/>' for y in (5.5, 9.5, 13.5)),
    "thermal": '<path d="M7.2 10.8V4a1.8 1.8 0 013.6 0v6.8a3.2 3.2 0 11-3.6 0z"/><path d="M9 7.5v5"/>',
    "structural": '<path d="M2.5 3v12"/><path d="M2.5 5.5c5 0 8 2 13 7"/>',
    "coupled": '<circle cx="6.5" cy="9" r="4"/><circle cx="11.5" cy="9" r="4"/>',
    "viz": '<path d="M1.5 9S4.5 4 9 4s7.5 5 7.5 5-3 5-7.5 5S1.5 9 1.5 9z"/><circle cx="9" cy="9" r="2.2"/>',
}
_PM = {}


def role_svg(role, colour=INK):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18" fill="none" stroke="{colour}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICON_BODY[role]}</svg>')


def role_pixmap(role, px=18, colour=INK, dpr=2.0):
    """The picture of a role as a pixmap (drawn from the svg text above; kept)."""
    key = (role, px, colour, dpr)
    pm = _PM.get(key)
    if pm is None:
        r = QSvgRenderer(QByteArray(role_svg(role, colour).encode()))
        pm = QPixmap(int(px * dpr), int(px * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, px, px))
        p.end()
        _PM[key] = pm
    return pm


class StripButton(QAbstractButton):
    """One button of the strip: the picture above its name, a mark top right; the chosen one is white with a teal edge (thicker below)."""

    def __init__(self, role, text, parent=None):
        super().__init__(parent)
        self.role = role
        self.setText(text)
        self.setCheckable(True)
        self.mark = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(STRIP_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(TIPS.get(role, ""))
        self.base_tip = TIPS.get(role, "")

    def sizeHint(self):
        return QSize(72, STRIP_H)

    def set_mark(self, kind, tip=""):
        if kind != self.mark or tip != getattr(self, "mark_tip", ""):
            self.mark, self.mark_tip = kind, tip
            self.setToolTip(self.base_tip + (("\n" + tip) if tip else ""))
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        sel = self.isChecked()
        p.setBrush(QColor("#ffffff" if sel else BAR))
        p.setPen(QPen(QColor(TEAL if sel else EDGE), 1))
        p.drawRoundedRect(r, 6, 6)
        if sel:
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(r, 6, 6)
            p.setClipPath(clip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TEAL))
            p.drawRect(QRectF(r.left(), r.bottom() - 2.5, r.width(), 3.5))
            p.restore()
        p.drawPixmap(QPointF(self.width() / 2 - 9, 9), role_pixmap(self.role))
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setBold(sel)
        p.setFont(f)
        p.setPen(QColor("#1f2933"))
        p.drawText(QRectF(0, 31, self.width(), 20), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), self.text())
        if self.mark in sim_outline.MARK_COLOURS:
            p.drawPixmap(self.width() - 14 - 4, 3, sim_outline.mark_icon(self.mark).pixmap(14, 14))
        p.end()


class RoleStrip(QWidget):
    """The five buttons: Fluid, Thermal, Structural, Coupled, Viz.  A member button is shown only while that analysis is wired in; Coupled and Viz always."""
    picked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 6)
        lay.setSpacing(4)
        self.buttons = {}
        for role, name in ROLES:
            b = StripButton(role, name)
            b.clicked.connect(lambda _=False, r=role: self.picked.emit(r))
            lay.addWidget(b)
            self.buttons[role] = b
        self.set_roles([r for r, _n in ROLES if r not in MEMBER_ROLES])
        self.select("coupled")

    def set_roles(self, roles):
        for r, b in self.buttons.items():
            b.setVisible(r in roles)

    def roles(self):
        """The roles shown now, in the order of the strip."""
        return [r for r, _n in ROLES if not self.buttons[r].isHidden()]

    def select(self, role):
        if role not in self.buttons or self.buttons[role].isHidden():
            return False
        for r, b in self.buttons.items():
            b.setChecked(r == role)
        return True

    def current(self):
        return next((r for r, b in self.buttons.items() if b.isChecked()), None)

    def button(self, role):
        return self.buttons.get(role)

    def set_mark(self, role, kind, tip=""):
        b = self.buttons.get(role)
        if b is not None:
            b.set_mark(kind, tip)

    def marks(self):
        return {r: b.mark for r, b in self.buttons.items() if not b.isHidden()}


# ---------------------------------------------------------------------------------------------------------------------------- hosting
class Relay(QLabel):
    """Takes the place of the status label of a hosted analysis: whatever the analysis writes there is sent on (the text, and the tooltip it may add)."""

    def __init__(self, sink, parent=None):
        super().__init__(parent)
        self.sink = sink
        self.hide()

    def setText(self, text):
        super().setText(text)
        try:
            self.sink(text)
        except RuntimeError:                                       # the Coupled window is being closed
            pass


def panes_of(win):
    """(side panel, view) of an analysis window: the two panes of its splitter (a 2D window holds a solver tab that holds the splitter; a 3D window holds it itself).  The panes are not moved."""
    holder = getattr(win, "tab", None) or win
    sp = [c for c in holder.children() if isinstance(c, QSplitter)]
    if len(sp) != 1 or sp[0].count() < 2:
        raise ValueError(f"the window of an analysis ({type(win).__name__}) has no side panel and view to show")
    s = sp[0]
    panel, view = s.widget(0), s.widget(1)
    return panel, view


def hosting_kinds():
    """The kinds of analysis window that are hosted (see HOSTED_KINDS)."""
    return HOSTED_KINDS


def can_host(kind):
    return kind in hosting_kinds()


class Hosted:
    """An analysis window shown inside the Coupled window: its panes, and what was taken from it."""

    def __init__(self, role, win):
        self.role, self.win = role, win
        self.panel, self.view = panes_of(win)
        self.outline = getattr(self.panel, "outline", None)
        self.relays = []

    def setup_mark(self):
        """'ok' when the Outline of the analysis has nothing incomplete before its results (the Workbench knows better: it asks the Setup cell), else 'incomplete'."""
        ol = self.outline
        if ol is None:
            return "ok"
        for key, mark in ol.marks.items():
            if key.strip().lower() in ("results", "solver"):
                continue
            if mark == "incomplete":
                return "incomplete"
        return "ok"


def route_status(win, sink):
    """The status labels of a 2D analysis (its window's and its solver tab's) become relays: what it says goes to `sink(text)`.  -> the relays."""
    out = []
    for obj in (win, getattr(win, "tab", None)):
        if obj is None or not isinstance(getattr(obj, "status_lbl", None), QLabel):
            continue
        if getattr(win, "tab", None) is None:
            continue                                               # (a 3D window keeps its own status line: it stays in its view)
        rl = Relay(sink, win)
        obj.status_lbl = rl
        out.append(rl)
    return out


def rebind_solve(h):
    """F5 solves the analysis from either of its panes where they are now (the key was bound to the solver tab they have left)."""
    t = getattr(h.win, "tab", None) or h.win
    b = getattr(t, "b_solve", None)
    if b is None:
        return
    for wdg in (h.panel, h.view):
        sim_ui.solve_shortcut(wdg, b)


def fix_fitter(h):
    """The panel's width helper keeps asking the splitter the panel left: it is guarded in ui_kit.fit_panel; the panel is as wide as the column of the Coupled window gives it."""
    f = getattr(h.panel, "fitter", None)
    if f is not None:
        f.user = True                                              # (never widen it again by itself)


class Ticker:
    """A timer that runs while a widget is shown (the marks of the strip are looked at a few times a second, only while the window is on screen)."""

    def __init__(self, widget, fn, ms=1000):
        self.t = QTimer(widget)
        self.t.setInterval(ms)
        self.t.timeout.connect(fn)

    def start(self):
        self.t.start()

    def stop(self):
        self.t.stop()
