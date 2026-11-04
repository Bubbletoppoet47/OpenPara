"""towers_tab.py - the Towers tab: an Asteroids-style (white vector lines on black) tower-capture mini game. Rules are in game.py."""
import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

import game as G

OWNER_COLORS = {G.NEUTRAL: "#8a8a8a", 0: "#ffffff", 1: "#ff5a5a", 2: "#ffc23c", 3: "#d36bff"}
OWNER_NAMES = {0: "You", 1: "Red", 2: "Amber", 3: "Violet"}


class Board(QWidget):
    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setMinimumSize(640, 410)
        self.setMouseTracking(True)
        self.drag = None            # source node id while dragging
        self.cursor = (0.0, 0.0)
        self.flash = ("", 0.0)

    # ---- view transform: the world is G.W x G.H, drawn centred and scaled to fit
    def scale(self):
        return min(self.width() / G.W, self.height() / G.H)

    def to_screen(self, x, y):
        s = self.scale()
        return QPointF((self.width() - G.W * s) / 2 + x * s, (self.height() - G.H * s) / 2 + y * s)

    def to_world(self, p):
        s = self.scale()
        return ((p.x() - (self.width() - G.W * s) / 2) / s, (p.y() - (self.height() - G.H * s) / 2) / s)

    def node_at(self, wx, wy, extra=0.0):
        g = self.tab.game
        best = None
        for n in g.nodes:
            r = 24 + 3 * n.level + extra
            d = math.hypot(n.x - wx, n.y - wy)
            if d <= r and (best is None or d < best[0]):
                best = (d, n)
        return best[1] if best else None

    # ---- input
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        wx, wy = self.to_world(e.position())
        n = self.node_at(wx, wy)
        if n is not None and n.owner == G.PLAYER and self.tab.game.state == "running":
            self.drag = n.id
        else:
            self.click_path(wx, wy)
        self.cursor = (wx, wy)

    def mouseMoveEvent(self, e):
        self.cursor = self.to_world(e.position())
        if self.drag is not None:
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.drag is None:
            return
        wx, wy = self.to_world(e.position())
        t = self.node_at(wx, wy, extra=8)
        src, self.drag = self.drag, None
        if t is not None and t.id != src:
            msg = self.tab.game.toggle_path(G.PLAYER, src, t.id)
            if msg:
                self.flash = (msg, 2.0)
        self.update()

    def click_path(self, wx, wy):
        """Clicking on one of your own paths closes it."""
        g = self.tab.game
        for p in g.paths:
            if p.owner != G.PLAYER or not p.open:
                continue
            A, B = g.nodes[p.src], g.nodes[p.dst]
            dx, dy = B.x - A.x, B.y - A.y
            L2 = dx * dx + dy * dy
            t = max(0.0, min(1.0, ((wx - A.x) * dx + (wy - A.y) * dy) / L2)) if L2 else 0
            if math.hypot(A.x + dx * t - wx, A.y + dy * t - wy) < 9 and 0.12 < t < 0.88:
                p.open = False
                g.prune()
                self.update()
                return

    # ---- drawing
    def paintEvent(self, ev):
        g = self.tab.game
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#000000"))
        s = self.scale()
        p.setPen(QPen(QColor("#202020"), 1))
        tl, br = self.to_screen(0, 0), self.to_screen(G.W, G.H)
        p.drawRect(QRectF(tl, br))
        # paths: each direction is drawn a little to its own side so contested pairs show as two lines
        for pa in g.paths:
            if not pa.open:
                continue
            A, B = g.nodes[pa.src], g.nodes[pa.dst]
            dx, dy = B.x - A.x, B.y - A.y
            L = math.hypot(dx, dy) or 1
            ox, oy = -dy / L * 3, dx / L * 3
            col = QColor(OWNER_COLORS[pa.owner])
            col.setAlpha(120)
            p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
            ra, rb = 22 + 3 * A.level, 22 + 3 * B.level
            a = self.to_screen(A.x + dx / L * ra + ox, A.y + dy / L * ra + oy)
            b = self.to_screen(B.x - dx / L * rb + ox, B.y - dy / L * rb + oy)
            p.drawLine(a, b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            for k in (-0.45, 0.45):
                p.drawLine(b, QPointF(b.x() - 9 * math.cos(ang + k), b.y() - 9 * math.sin(ang + k)))
        # troops
        for (a, b), lane in g.lanes.items():
            A, B = g.nodes[a], g.nodes[b]
            dx, dy = B.x - A.x, B.y - A.y
            L = math.hypot(dx, dy) or 1
            ox, oy = -dy / L * 3, dx / L * 3
            for t in lane:
                col = QColor(OWNER_COLORS[t.owner])
                x, y = A.x + dx * t.s + ox, A.y + dy * t.s + oy
                q = self.to_screen(x, y)
                tail = self.to_screen(x - dx / L * 9, y - dy / L * 9)
                col.setAlpha(110)
                p.setPen(QPen(col, 1.2))
                p.drawLine(tail, q)
                col.setAlpha(255)
                p.setPen(QPen(col, 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawPoint(q)
        # cancel flashes
        for x, y, age in g.effects:
            c = self.to_screen(x, y)
            col = QColor("#ffffff")
            col.setAlpha(int(255 * (1 - age / 0.5)))
            p.setPen(QPen(col, 1.2))
            p.drawEllipse(c, 3 + 22 * age, 3 + 22 * age)
        # towers
        f = QFont("Courier New")
        f.setBold(True)
        f.setPixelSize(max(11, int(15 * s)))
        p.setFont(f)
        for n in g.nodes:
            col = QColor(OWNER_COLORS[n.owner])
            c = self.to_screen(n.x, n.y)
            r = (18 + 3 * n.level) * s
            p.setPen(QPen(col, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(self.rock(n, c, r))
            for k in range(1, n.level):                                  # one inner ring per level above 1
                p.setPen(QPen(col, 1))
                p.drawEllipse(c, r * (1 - 0.2 * k) * 0.82, r * (1 - 0.2 * k) * 0.82)
            if n.troops > 60:                                           # the buffer above level 4
                p.setPen(QPen(col, 1, Qt.PenStyle.DotLine))
                p.drawEllipse(c, r + 5 * s, r + 5 * s)
            p.setPen(col)
            p.drawText(QRectF(c.x() - 30, c.y() - 10, 60, 20), Qt.AlignmentFlag.AlignCenter, str(int(n.troops)))
            if n.owner != G.NEUTRAL:
                used = len(g.open_paths(n.id))
                p.setFont(QFont("Courier New", max(7, int(8 * s))))
                p.drawText(QRectF(c.x() - 30, c.y() + r + 1, 60, 14), Qt.AlignmentFlag.AlignCenter, f"L{n.level}  {used}/{n.level}")
                p.setFont(f)
        # drag preview
        if self.drag is not None:
            A = g.nodes[self.drag]
            p.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DotLine))
            p.drawLine(self.to_screen(A.x, A.y), self.to_screen(*self.cursor))
        # messages
        if g.state != "running" or self.flash[1] > 0:
            f2 = QFont("Courier New")
            f2.setPixelSize(30 if g.state != "running" else 15)
            f2.setBold(True)
            p.setFont(f2)
            p.setPen(QColor("#ffffff"))
            text = {"won": "ALL TOWERS CAPTURED", "lost": "YOUR TOWERS ARE LOST"}.get(g.state, self.flash[0])
            p.drawText(QRectF(0, 8 if g.state == "running" else self.height() / 2 - 30, self.width(), 40), Qt.AlignmentFlag.AlignCenter, text)

    def rock(self, n, c, r):
        """An irregular asteroid-like outline, fixed per tower."""
        rng = random.Random(n.id * 97 + 3)
        k = 9
        pts = []
        for i in range(k):
            a = 2 * math.pi * i / k
            rr = r * rng.uniform(0.86, 1.1)
            pts.append(QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a)))
        return QPolygonF(pts)


class TowersTab(QWidget):
    def __init__(self):
        super().__init__()
        self.host = None
        self.path = None
        self.game = G.Game(G.Config())
        self.paused = False
        self.board = Board(self)
        self.build_ui()
        self.last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.new_game()

    def build_ui(self):
        top = QHBoxLayout()

        def spin(lo, hi, val):
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setValue(val)
            return w

        self.enemies = spin(1, 3, 1)
        self.nodes = spin(6, 40, 14)
        self.level = spin(1, 4, 2)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setSpecialValueText("random")
        self.agg = QSlider(Qt.Orientation.Horizontal)
        self.agg.setRange(0, 100)
        self.agg.setValue(50)
        self.agg.setFixedWidth(110)
        self.agg_label = QLabel("50 %")
        self.agg.valueChanged.connect(lambda v: self.agg_label.setText(f"{v} %"))
        self.speed = QComboBox()
        for t, v in (("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("3x", 3.0)):
            self.speed.addItem(t, v)
        self.speed.setCurrentIndex(1)
        for label, w in (("Enemies", self.enemies), ("Towers", self.nodes), ("Start level", self.level), ("Seed", self.seed)):
            top.addWidget(QLabel(label))
            top.addWidget(w)
        top.addWidget(QLabel("AI aggression"))
        top.addWidget(self.agg)
        top.addWidget(self.agg_label)
        top.addWidget(QLabel("Speed"))
        top.addWidget(self.speed)
        self.btn_new = QPushButton("New game")
        self.btn_new.setToolTip("A new random map with these settings (seed: random) or the seed you typed")
        self.btn_new.clicked.connect(self.new_game)
        self.btn_restart = QPushButton("Restart map")
        self.btn_restart.clicked.connect(self.restart)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.toggle_pause)
        for b in (self.btn_new, self.btn_restart, self.btn_pause):
            top.addWidget(b)
        top.addStretch(1)
        self.info = QLabel("")
        self.help = QLabel("Drag from one of your towers (white) to another tower to open a path; drag again to the same tower or click the path to close it. "
                           "A tower of level N can have N paths and makes troops only through its paths (shared). Stored 20/40/60 = level 2/3/4. "
                           "Troops meeting head-on cancel. Space pauses.")
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color:#666;")
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.board, 1)
        lay.addWidget(self.info)
        lay.addWidget(self.help)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- game control
    def config(self, seed):
        return G.Config(enemies=self.enemies.value(), nodes=self.nodes.value(), aggression=self.agg.value() / 100.0, start_level=self.level.value(),
                        seed=seed or None)

    def new_game(self):
        cfg = self.config(self.seed.value())
        self.cfg = cfg
        self.game = G.Game(cfg)
        self.paused = False
        self.btn_pause.setText("Pause")
        self.update_info()
        self.board.update()

    def restart(self):
        self.game = G.Game(G.Config(enemies=self.cfg.enemies, nodes=self.cfg.nodes, aggression=self.agg.value() / 100.0,
                                    start_level=self.cfg.start_level, seed=self.cfg.seed))
        self.paused = False
        self.btn_pause.setText("Pause")
        self.update_info()

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.setText("Resume" if self.paused else "Pause")

    def tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last)
        self.last = now
        if not self.isVisible():
            return
        txt, f = self.board.flash
        if f > 0:
            self.board.flash = (txt, f - dt)
        if not self.paused:
            sp = self.speed.currentData() or 1.0
            n = max(1, int(round(sp)))
            for _ in range(n):
                self.game.step(dt * sp / n)
        self.update_info()
        self.board.update()

    def update_info(self):
        g = self.game
        parts = [f"Seed {self.cfg.seed}", f"time {int(g.time)} s"]
        for o in range(0, g.cfg.enemies + 1):
            nodes = g.owned(o)
            parts.append(f"{OWNER_NAMES[o]}: {len(nodes)} towers / {sum(int(n.troops) for n in nodes)} troops")
        self.info.setText("    ".join(parts))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.toggle_pause()
        else:
            super().keyPressEvent(e)

    def title(self):
        return "Towers"


def make_tab():
    return TowersTab()
