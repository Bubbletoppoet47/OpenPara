"""
start_page.py - what the program window shows while no document is open: the ways to start, and what was opened lately.

Left: one button per way to start (New Part, New Assembly, the documents the installed add-ons offer, the commands add-ons put with
"file.new", Open, Open Project Folder).  Right: the recent files and project folders (recent.py); a click opens one, a right-click offers
"Show in folder" and "Remove from list".  At the bottom: how many add-ons are installed, a button to File > Add-ons, and a line when an
add-on could not be loaded.  The page reads everything from the program window (shell.start_actions()) each time it is shown, so it
follows the add-ons that are installed or removed.
"""
import os

from PyQt6.QtCore import QRect, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics
from PyQt6.QtWidgets import (QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QStyle,
                             QStyledItemDelegate, QVBoxLayout, QWidget)

import addons
import channel
import recent

STYLE = """
#startPage { background: #f3f5f9; }
#startTitle { font-size: 24px; font-weight: 600; color: #1f2a3c; }
#startSub { color: #6a7790; font-size: 12px; }
#startHead { color: #4a5872; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QPushButton#startBtn { text-align: left; padding: 9px 14px; font-size: 13px; background: #ffffff; border: 1px solid #d5dbe6; border-radius: 6px; }
QPushButton#startBtn:hover { background: #e6efff; border-color: #2b7de9; }
QPushButton#startSmall { text-align: left; padding: 6px 10px; font-size: 12px; background: #ffffff; border: 1px solid #d5dbe6; border-radius: 5px; }
QPushButton#startSmall:hover { background: #e6efff; border-color: #2b7de9; }
QPushButton#startLink { border: 0; background: transparent; color: #1a56c4; padding: 2px 4px; text-align: left; }
QPushButton#startLink:hover { text-decoration: underline; background: transparent; }
#startRecent { font-size: 12px; }
#startNote { color: #808a9c; }
#startWarn { color: #b00020; }
"""


def show_in_folder(path):
    """Opens the folder that holds `path` in the file manager (the project folder's parent, so the folder itself is seen)."""
    p = os.path.abspath(str(path).rstrip("/\\"))
    d = os.path.dirname(p)
    if os.path.isdir(d):
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))


NAME_ROLE, LINE2_ROLE, MISSING_ROLE = Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 2, Qt.ItemDataRole.UserRole + 3


class RecentDelegate(QStyledItemDelegate):
    """One recent file: its name (bold) and under it what it is and where (grey, the middle of a long path is left out so both ends are read)."""
    PAD, GAP = 10, 3

    def fonts(self, option):
        f1 = QFont(option.font)
        f1.setPixelSize(13)
        f1.setWeight(QFont.Weight.DemiBold)
        f2 = QFont(option.font)
        f2.setPixelSize(11)
        return f1, f2

    def sizeHint(self, option, index):
        f1, f2 = self.fonts(option)
        return QSize(120, QFontMetrics(f1).height() + QFontMetrics(f2).height() + 2 * self.PAD - 4 + self.GAP)

    def paint(self, p, option, index):
        f1, f2 = self.fonts(option)
        r = option.rect
        hot = bool(option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected))
        p.save()
        p.fillRect(r, QColor("#e6efff") if hot else QColor("#ffffff"))
        p.setPen(QColor("#edf0f6"))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        missing = bool(index.data(MISSING_ROLE))
        w = r.width() - 2 * self.PAD
        m1, m2 = QFontMetrics(f1), QFontMetrics(f2)
        y = r.top() + self.PAD - 2
        p.setFont(f1)
        p.setPen(QColor("#9aa3b2") if missing else QColor("#1f2a3c"))
        p.drawText(QRect(r.left() + self.PAD, y, w, m1.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   m1.elidedText(index.data(NAME_ROLE) or "", Qt.TextElideMode.ElideMiddle, w))
        p.setFont(f2)
        p.setPen(QColor("#9aa3b2") if missing else QColor("#6a7790"))
        p.drawText(QRect(r.left() + self.PAD, y + m1.height() + self.GAP, w, m2.height()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   m2.elidedText(index.data(LINE2_ROLE) or "", Qt.TextElideMode.ElideMiddle, w))
        p.restore()


class StartPage(QWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.setObjectName("startPage")
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()                                  # a small window scrolls the page instead of cutting it off
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        page = QWidget()
        page.setObjectName("startPage")
        scroll.setWidget(page)
        row = QHBoxLayout(page)
        row.addStretch(1)
        mid = QVBoxLayout()
        mid.setContentsMargins(24, 28, 24, 20)
        mid.setSpacing(6)
        row.addLayout(mid, 8)
        row.addStretch(1)

        self.title = QLabel(channel.app_name())
        self.title.setObjectName("startTitle")
        mid.addWidget(self.title)
        self.sub = QLabel("")
        self.sub.setObjectName("startSub")
        mid.addWidget(self.sub)
        mid.addSpacing(18)

        cols = self.cols = QBoxLayout(QBoxLayout.Direction.LeftToRight)       # side by side; one above the other in a narrow window
        cols.setSpacing(36)
        mid.addLayout(cols, 1)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        h = QLabel("START")
        h.setObjectName("startHead")
        h.setFixedHeight(24)
        left.addWidget(h)
        self.btn_box = QVBoxLayout()
        self.btn_box.setSpacing(6)
        left.addLayout(self.btn_box)
        left.addSpacing(14)
        self.addon_head = QLabel("FROM YOUR ADD-ONS")
        self.addon_head.setObjectName("startHead")
        left.addWidget(self.addon_head)
        self.addon_grid = QGridLayout()                         # the documents and commands of the add-ons: compact, two columns when there are many
        self.addon_grid.setSpacing(5)
        left.addLayout(self.addon_grid)
        left.addStretch(1)
        self.left = QWidget()
        self.left.setLayout(left)
        cols.addWidget(self.left, 0)

        right = QVBoxLayout()
        right.setSpacing(6)
        head = QHBoxLayout()
        h = QLabel("RECENT")
        h.setObjectName("startHead")
        h.setFixedHeight(24)
        head.addWidget(h)
        head.addStretch(1)
        self.b_clear = QPushButton("Clear list")
        self.b_clear.setObjectName("startLink")
        self.b_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_clear.clicked.connect(self.clear_recent)
        head.addWidget(self.b_clear)
        right.addLayout(head)
        self.lst = QListWidget()
        self.lst.setObjectName("startRecent")
        self.lst.setItemDelegate(RecentDelegate(self.lst))
        self.lst.setMouseTracking(True)
        self.lst.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lst.setMinimumHeight(200)
        self.lst.setMinimumWidth(260)
        self.lst.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lst.itemClicked.connect(self.open_item)
        self.lst.itemActivated.connect(self.open_item)
        self.lst.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lst.customContextMenuRequested.connect(self.recent_menu)
        right.addWidget(self.lst, 1)
        self.empty = QLabel("Nothing yet. The parts, assemblies and projects you open are listed here.\nYou can also drop a file or a project folder "
                            "anywhere on this window.")
        self.empty.setObjectName("startNote")
        self.empty.setWordWrap(True)
        right.addWidget(self.empty)
        cols.addLayout(right, 1)

        mid.addSpacing(10)
        foot = QHBoxLayout()
        self.addon_lbl = QLabel("")
        self.addon_lbl.setObjectName("startNote")
        foot.addWidget(self.addon_lbl)
        self.b_addons = QPushButton("Add-ons...")
        self.b_addons.setObjectName("startLink")
        self.b_addons.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_addons.clicked.connect(lambda: self.shell.addons_dialog())
        foot.addWidget(self.b_addons)
        foot.addStretch(1)
        mid.addLayout(foot)
        self.warn = QLabel("")
        self.warn.setObjectName("startWarn")
        self.warn.setWordWrap(True)
        self.warn.hide()
        mid.addWidget(self.warn)
        self.buttons = []
        self.left_w = 270
        self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refresh()

    # ------------------------------------------------------------------ contents
    def refresh(self):
        try:
            import version
            self.sub.setText(f"Version {version.__version__}")
        except Exception:
            self.sub.setText("")
        for lay in (self.btn_box, self.addon_grid):
            while lay.count():
                it = lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
        self.buttons = []
        acts = self.shell.start_actions()
        extra = [a for a in acts if a.get("group") == "addon"]
        two = len(extra) > 5
        for act in acts:
            b = QPushButton(act["text"])
            small = act.get("group") == "addon"
            b.setObjectName("startSmall" if small else "startBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if act.get("tip"):
                b.setToolTip(act["tip"])
            b.clicked.connect(lambda _c=False, f=act["fn"]: f())
            if small:
                k = extra.index(act)
                self.addon_grid.addWidget(b, k // 2 if two else k, k % 2 if two else 0)
            else:
                self.btn_box.addWidget(b)
            self.buttons.append(b)
        self.addon_head.setVisible(bool(extra))
        self.left_w = 400 if two else 270
        self.arrange()
        self.fill_recent()
        n = sum(1 for a in addons.known() if addons.is_active(a))
        self.addon_lbl.setText(f"{n} add-on{'s' if n != 1 else ''} installed." if n else "No add-ons installed.")
        errs = addons.load_errors()
        if errs:
            self.warn.setText("Could not be loaded (see File > Add-ons for the details): " + ", ".join(addons.info(a)["name"] for a in errs) + ".")
        self.warn.setVisible(bool(errs))

    NARROW = 780                                                # below this window width the two columns are stacked

    def arrange(self):
        """Start and Recent side by side, or - in a narrow window - Start above Recent at the full width, so nothing is cut off."""
        narrow = self.width() < self.NARROW
        self.cols.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self.cols.setSpacing(18 if narrow else 36)
        if narrow:
            self.left.setMinimumWidth(0)
            self.left.setMaximumWidth(16777215)
        else:
            self.left.setFixedWidth(self.left_w)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.arrange()

    def fill_recent(self):
        self.lst.clear()
        its = recent.items()
        for it in its:
            where = it["folder"] or it["path"]
            line2 = (it["kind"] + "  -  " if it["kind"] else "") + where + ("   (not found)" if it["missing"] else "")
            item = QListWidgetItem(it["name"] + "\n" + line2)              # (the text is for screen readers and tests; the delegate draws the two lines)
            item.setData(Qt.ItemDataRole.UserRole, it["path"])
            item.setData(NAME_ROLE, it["name"])
            item.setData(LINE2_ROLE, line2)
            item.setData(MISSING_ROLE, it["missing"])
            item.setToolTip(it["path"] + ("\nNot found right now (a drive that is not connected?). It stays in the list." if it["missing"] else ""))
            self.lst.addItem(item)
        self.lst.setVisible(bool(its))
        self.b_clear.setVisible(bool(its))
        self.empty.setVisible(not its)

    # ------------------------------------------------------------------ actions
    def open_item(self, item):
        self.shell.open_recent(item.data(Qt.ItemDataRole.UserRole))
        self.fill_recent()

    def recent_menu(self, pos):
        item = self.lst.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("Open", lambda: self.open_item(item))
        m.addAction("Show in folder", lambda: show_in_folder(path))
        m.addAction("Remove from list", lambda: (recent.remove(path), self.fill_recent()))
        m.exec(self.lst.mapToGlobal(pos))

    def clear_recent(self):
        recent.clear()
        self.fill_recent()
