"""
remote_tab.py - the Remote Computer tab: see the screen of another computer, use its keyboard and mouse, copy files to and from it and run
commands there.  The other computer runs openpara_remote_helper.py (File > "Get the helper" saves it) and has an access code; nothing is
reachable without that code.

Playground only for now (see addons.NOT_RELEASED).  Tested here against an X11 desktop; the Windows and Wayland parts of the helper are
written but have not run on real machines yet.
"""
import os
import shutil
import threading
import time
import zlib

import numpy as np
from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPainter
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
                             QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import remote_link as RL
import ui_kit

KEY_NAMES = {Qt.Key.Key_Return: "Return", Qt.Key.Key_Enter: "Return", Qt.Key.Key_Escape: "Escape", Qt.Key.Key_Backspace: "BackSpace",
             Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab", Qt.Key.Key_Delete: "Delete", Qt.Key.Key_Insert: "Insert",
             Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End", Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown",
             Qt.Key.Key_Left: "Left", Qt.Key.Key_Up: "Up", Qt.Key.Key_Right: "Right", Qt.Key.Key_Down: "Down", Qt.Key.Key_Shift: "Shift",
             Qt.Key.Key_Control: "Control", Qt.Key.Key_Alt: "Alt", Qt.Key.Key_Meta: "Meta", Qt.Key.Key_CapsLock: "CapsLock",
             Qt.Key.Key_Menu: "Menu", Qt.Key.Key_Print: "Print", Qt.Key.Key_Pause: "Pause", Qt.Key.Key_ScrollLock: "ScrollLock",
             Qt.Key.Key_NumLock: "NumLock", Qt.Key.Key_Space: " "}
for _i in range(12):
    KEY_NAMES[Qt.Key(Qt.Key.Key_F1.value + _i)] = f"F{_i + 1}"
BUTTONS = {Qt.MouseButton.LeftButton: 1, Qt.MouseButton.RightButton: 2, Qt.MouseButton.MiddleButton: 3}

HELPER_README = """OpenPara Remote helper
======================

Put  openpara_remote_helper.py  on the computer you want to reach from OpenPara (a Raspberry Pi, a laptop whose screen is broken ...).
It needs Python 3.8 or newer and nothing else.

First time (you need to see that computer's screen once, or a second screen plugged in):

  1. Double-click  "Set up (Raspberry Pi, Linux).desktop"  or  "Set up (Windows).bat"  in this folder (choose Execute / Run if asked),
     or open a terminal in this folder and run:
         python3 openpara_remote_helper.py --install
     It shows an ACCESS CODE - write it down. It also makes the helper start with every login.
     (Windows: use  python  instead of  python3.  If Windows asks whether Python may be reached on private networks, answer Allow.)
  2. Restart that computer (or log out and in). From then on the helper runs by itself.
  3. In OpenPara: File > New Remote Computer, Search this network, pick the computer and type the access code.
     If the search finds nothing, use Add by address: the helper says its address when it starts (and with --check); use the first one.

Both computers have to be on the same network: your home Wi-Fi, or a hotspot both are joined to.

Good to know
  * Anyone with the access code can see and use that computer fully. Keep it to yourself; only use it on a network you trust.
  * A new code:            python3 openpara_remote_helper.py --new-code
  * Stop starting it:      python3 openpara_remote_helper.py --uninstall
  * Ask before each use:   python3 openpara_remote_helper.py --ask       (not for a computer nobody sits at)
  * Switch a part off:     --no-input  --no-files  --no-commands  --no-screen
  * What works there:      python3 openpara_remote_helper.py --check     (screen, keyboard and mouse)
  * Every connection is written to connections.log in its settings folder ( --status shows where).
  * Raspberry Pi OS with the Wayland desktop: the screen needs 'grim' (it is there on Raspberry Pi OS), keyboard and mouse need the
    permission that --install sets up (restart once). If the picture stays black, switch the desktop to X11:
    sudo raspi-config > Advanced Options > Wayland > X11.
"""


EMPTY_TITLE = "See and use another computer from here"
EMPTY_TEXT = ("The other computer runs a small helper program and has an access code. Put the helper on it (Get the helper), start it there "
              "once, then search this network and connect with the code. Both computers must be on the same Wi-Fi or hotspot.")


class Poster(QObject):
    """Runs a function in the window's own thread: worker threads hand their results over with post(fn)."""
    sig = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.sig.connect(lambda fn: fn())

    def post(self, fn):
        try:
            self.sig.emit(fn)
        except RuntimeError:                 # the window is gone (a worker that was still running when its tab closed)
            pass


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class ScreenView(QWidget):
    """The picture of the other screen, scaled to fit, and what turns this PC's keyboard and mouse into events for the other one."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.lock = threading.Lock()
        self.fb = None                       # numpy (h, w, 4) BGRX, the other screen as we know it
        self.target = QRectF()
        self.pending = []                    # input events not sent yet
        self.down = {}                       # Qt key -> the key name sent for it
        self.wheel_acc = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.flush_timer = QTimer(self)
        self.flush_timer.timeout.connect(self.flush)
        self.flush_timer.start(16)

    # ---- the picture (called from the frame thread)
    def apply_frame(self, h, payload):
        w, hh, fmt = int(h["w"]), int(h["h"]), h["fmt"]
        with self.lock:
            if self.fb is None or self.fb.shape[:2] != (hh, w):
                self.fb = np.zeros((hh, w, 4), np.uint8)
                self.fb[:, :, 3] = 255
            off = 0
            for x, y, rw, rh, enc, n in h["rects"]:
                blob = payload[off:off + n]
                off += n
                if enc == "z":
                    a = np.frombuffer(zlib.decompress(blob), np.uint8).reshape(rh, rw, len(fmt))
                    self.fb[y:y + rh, x:x + rw, :3] = a[:, :, 2::-1] if fmt == "rgb" else a[:, :, :3]
                else:
                    qi = QImage.fromData(blob, "JPG").convertToFormat(QImage.Format.Format_RGB32)
                    bits = qi.constBits()
                    bits.setsize(qi.sizeInBytes())
                    a = np.frombuffer(bits, np.uint8).reshape(qi.height(), qi.bytesPerLine() // 4, 4)
                    self.fb[y:y + rh, x:x + rw, :3] = a[:rh, :rw, :3]
        return len(h["rects"])

    def clear(self):
        with self.lock:
            self.fb = None
        self.update()

    def screen_size(self):
        with self.lock:
            return (self.fb.shape[1], self.fb.shape[0]) if self.fb is not None else None

    def snapshot(self):
        with self.lock:
            if self.fb is None:
                return None
            hh, w = self.fb.shape[:2]
            return QImage(self.fb.tobytes(), w, hh, w * 4, QImage.Format.Format_RGB32).copy()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        with self.lock:
            if self.fb is None:
                return
            hh, w = self.fb.shape[:2]
            s = min(self.width() / w, self.height() / hh)
            tw, th = w * s, hh * s
            self.target = QRectF((self.width() - tw) / 2, (self.height() - th) / 2, tw, th)
            img = QImage(self.fb.data, w, hh, w * 4, QImage.Format.Format_RGB32)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
            p.drawImage(self.target, img)
        if self.hasFocus() and self.tab.controlling():
            p.setPen(Qt.GlobalColor.green)
            p.drawRect(self.target.adjusted(0, 0, -1, -1))

    # ---- keyboard and mouse
    def to_screen(self, pos):
        size = self.screen_size()
        if size is None or self.target.width() < 1:
            return None
        w, hh = size
        x = (pos.x() - self.target.x()) / self.target.width() * w
        y = (pos.y() - self.target.y()) / self.target.height() * hh
        return min(max(x, 0), w - 1), min(max(y, 0), hh - 1)

    def queue(self, ev):
        if not self.tab.controlling():
            return
        if ev["t"] == "move" and self.pending and self.pending[-1]["t"] == "move":
            self.pending[-1] = ev
        else:
            self.pending.append(ev)

    def flush(self):
        if not self.pending:
            return
        events, self.pending = self.pending, []
        link = self.tab.link
        if link is not None and not link.closed:
            try:
                link.input(events)
            except RL.RemoteError:
                pass

    def mouseMoveEvent(self, ev):
        xy = self.to_screen(ev.position())
        if xy:
            self.queue({"t": "move", "x": round(xy[0], 1), "y": round(xy[1], 1)})

    def mousePressEvent(self, ev):
        self.setFocus()
        self.mouseMoveEvent(ev)
        if ev.button() in BUTTONS:
            self.queue({"t": "btn", "b": BUTTONS[ev.button()], "down": True})

    def mouseReleaseEvent(self, ev):
        self.mouseMoveEvent(ev)
        if ev.button() in BUTTONS:
            self.queue({"t": "btn", "b": BUTTONS[ev.button()], "down": False})

    def wheelEvent(self, ev):
        self.wheel_acc += ev.angleDelta().y() / 120.0
        steps = int(self.wheel_acc)
        if steps:
            self.wheel_acc -= steps
            self.queue({"t": "wheel", "dy": steps})
        dx = int(ev.angleDelta().x() / 120.0)
        if dx:
            self.queue({"t": "wheel", "dx": dx})
        ev.accept()

    def key_name(self, ev):
        k = ev.key()
        try:
            name = KEY_NAMES.get(Qt.Key(k))
        except ValueError:
            name = None
        if name:
            return name
        mods = ev.modifiers()
        plain = not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier))
        text = ev.text()
        if plain and len(text) == 1 and text.isprintable():
            return text
        if 0x20 < k <= 0x7e:
            return chr(k).lower()
        return None

    def event(self, ev):
        t = ev.type()
        if t == ev.Type.ShortcutOverride and self.tab.controlling():
            ev.accept()                                  # Ctrl+S, Ctrl+W ... go to the other computer while its screen has the keyboard
            return True
        if t == ev.Type.KeyPress and ev.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.tab.controlling():
            self.keyPressEvent(ev)
            return True
        return super().event(ev)

    def focusNextPrevChild(self, _next):
        return not self.tab.controlling() and super().focusNextPrevChild(_next)

    def keyPressEvent(self, ev):
        if not self.tab.controlling():
            return super().keyPressEvent(ev)
        if ev.isAutoRepeat():
            name = self.down.get(ev.key())
            if name and self.tab.repeat_keys:              # only Windows does not repeat a held key by itself
                self.queue({"t": "key", "key": name, "down": True})
            return
        name = self.key_name(ev)
        if name:
            self.down[ev.key()] = name
            self.queue({"t": "key", "key": name, "down": True})
        elif len(ev.text()) > 1:
            self.queue({"t": "text", "s": ev.text()})

    def keyReleaseEvent(self, ev):
        if ev.isAutoRepeat():
            return
        name = self.down.pop(ev.key(), None)
        if name:
            self.queue({"t": "key", "key": name, "down": False})

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.update()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self.down:
            self.down.clear()
            self.pending.append({"t": "release"})
        self.update()


class CodeDialog(QDialog):
    def __init__(self, parent, name, note=""):
        super().__init__(parent)
        self.setWindowTitle("Access code")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"The access code of {name}:"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("ABCD-EFGH-JKMN")
        self.edit.setMinimumWidth(260)
        lay.addWidget(self.edit)
        self.keep = QCheckBox("Remember the code on this PC")
        self.keep.setToolTip("Saved as it is in your OpenPara settings folder, so anyone using this Windows account could read it.")
        lay.addWidget(self.keep)
        lay.addWidget(ui_kit.note(note or "The helper showed it the first time it was started there.  python3 openpara_remote_helper.py --new-code  "
                                  "makes a new one."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class RemoteTab(QWidget):
    def __init__(self, host=None):
        super().__init__()
        self.host = host
        self.path = None
        self.link = None
        self.poster = Poster()
        self.found = []                     # computers the last search found
        self.repeat_keys = False
        self.job = None                     # {"stop": bool} of the copy that is running
        self.cmd_id = None
        self.cwd = None                     # the folder commands run in, on the other computer
        self.rdir = ""                      # the folder the Files page shows
        self.history, self.hist_i = [], 0
        self.frames = 0
        self.connecting = False
        self.updating = 0                   # > 0 while the other computer's helper is being replaced: tries left to connect again
        self.was_updating = False
        self.current = None
        self.parent_dir = None
        self.screen_on = False              # the Screen page is the one being looked at (read by the frame thread)
        self.fast = True
        self._build()
        self.refresh_list()
        self.update_ui()

    # ============================================================================ tab protocol
    def title(self):
        return f"Remote: {self.link.label()}" if self.connected() else "Remote Computer"

    def is_dirty(self):
        return False

    def can_close(self):
        if self.job is not None:
            r = QMessageBox.question(self, "Remote Computer", "A copy is still running. Stop it and close?")
            if r != QMessageBox.StandardButton.Yes:
                return False
        return True

    def shutdown(self):
        if self.job is not None:
            self.job["stop"] = True
        self.disconnect_now()

    def connected(self):
        return self.link is not None and not self.link.closed

    def controlling(self):
        return self.connected() and self.ctl_box.isChecked() and bool(self.link.info.get("input", {}).get("ok"))

    # ============================================================================ layout
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)
        head = QLabel("Computers")
        head.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        ll.addWidget(head)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self.update_ui)
        self.list.itemDoubleClicked.connect(lambda _i: self.connect_selected())
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.search_btn = QPushButton("Search this network")
        self.search_btn.clicked.connect(self.search)
        self.add_btn = QPushButton("Add by address...")
        self.add_btn.clicked.connect(self.add_by_address)
        row.addWidget(self.search_btn)
        row.addWidget(self.add_btn)
        ll.addLayout(row)
        row = QHBoxLayout()
        self.connect_btn = ui_kit.primary(QPushButton("Connect"))
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.connect_btn, 1)
        row.addWidget(self.remove_btn)
        ll.addLayout(row)
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setTextFormat(Qt.TextFormat.RichText)
        ll.addWidget(self.info_lbl)
        self.ctl_box = QCheckBox("Use its keyboard and mouse")
        self.ctl_box.setChecked(True)
        self.ctl_box.setToolTip("Off: you only watch. On: click the picture, then what you type and click goes to the other computer.")
        self.ctl_box.toggled.connect(lambda _c: (self.update_ui(), self.view.update()))
        ll.addWidget(self.ctl_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Picture:"))
        self.quality = QComboBox()
        self.quality.addItem("Fast (lighter, for video)", "fast")
        self.quality.addItem("Sharp (exact, for text)", "sharp")
        self.quality.setToolTip("Fast sends moving pictures as JPEG when the other computer can make them (OpenCV or Pillow installed there).")
        self.quality.currentIndexChanged.connect(lambda _i: setattr(self, "fast", self.quality.currentData() == "fast"))
        row.addWidget(self.quality, 1)
        ll.addLayout(row)
        self.update_btn = QPushButton("Update its helper")
        self.update_btn.setToolTip("The helper on that computer is older than this OpenPara's. This sends the new one over and starts it "
                                   "there; the connection comes back after a few seconds. The access code stays the same.")
        self.update_btn.clicked.connect(self.update_helper)
        self.update_btn.hide()
        ll.addWidget(self.update_btn)
        self.helper_btn = QPushButton("Get the helper...")
        self.helper_btn.setToolTip("Saves the helper program and its instructions to a folder or USB drive, for the other computer.")
        self.helper_btn.clicked.connect(self.save_helper)
        ll.addWidget(self.helper_btn)
        split.addWidget(left)

        self.stack = QStackedWidget()
        self.empty = ui_kit.EmptyState(EMPTY_TITLE, EMPTY_TEXT, [("Search this network", self.search), ("Get the helper...", self.save_helper)])
        self.stack.addWidget(self.empty)
        self.pages = QTabWidget()
        self.pages.currentChanged.connect(self.on_page)
        self.stack.addWidget(self.pages)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 900])

        # ---- Screen
        sp = QWidget()
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        self.type_btn = QPushButton("Type the clipboard")
        self.type_btn.setToolTip("Types the text you copied on this PC into the other computer (a password, a long command).")
        self.type_btn.clicked.connect(self.type_clipboard)
        self.shot_btn = QPushButton("Save picture...")
        self.shot_btn.clicked.connect(self.save_picture)
        self.screen_msg = QLabel("")
        self.screen_msg.setStyleSheet(f"color:{ui_kit.MUTED};")
        bar.addWidget(self.type_btn)
        bar.addWidget(self.shot_btn)
        bar.addWidget(self.screen_msg, 1)
        sl.addLayout(bar)
        self.view = ScreenView(self)
        sl.addWidget(self.view, 1)
        self.pages.addTab(sp, "Screen")

        # ---- Files
        fp = QWidget()
        fl = QVBoxLayout(fp)
        row = QHBoxLayout()
        self.up_btn = QPushButton("Up")
        self.up_btn.clicked.connect(self.go_up)
        self.home_btn = QPushButton("Home")
        self.home_btn.clicked.connect(lambda: self.browse("~"))
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(lambda: self.browse(self.path_edit.text()))
        self.reload_btn = QPushButton("Refresh")
        self.reload_btn.clicked.connect(lambda: self.browse(self.rdir))
        for wdg in (self.up_btn, self.home_btn):
            row.addWidget(wdg)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.reload_btn)
        fl.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Size", "Changed"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 420)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemSelectionChanged.connect(self.update_ui)
        fl.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.get_btn = ui_kit.primary(QPushButton("Copy to this PC..."))
        self.get_btn.clicked.connect(self.download_selected)
        self.put_btn = QPushButton("Send files...")
        self.put_btn.clicked.connect(self.upload_files)
        self.putdir_btn = QPushButton("Send a folder...")
        self.putdir_btn.clicked.connect(self.upload_folder)
        self.mkdir_btn = QPushButton("New folder")
        self.mkdir_btn.clicked.connect(self.new_folder)
        self.ren_btn = QPushButton("Rename")
        self.ren_btn.clicked.connect(self.rename_selected)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.delete_selected)
        for wdg in (self.get_btn, self.put_btn, self.putdir_btn, self.mkdir_btn, self.ren_btn, self.del_btn):
            row.addWidget(wdg)
        row.addStretch(1)
        fl.addLayout(row)
        row = QHBoxLayout()
        self.job_lbl = QLabel("")
        self.job_bar = QProgressBar()
        self.job_bar.setRange(0, 1000)
        self.job_stop = QPushButton("Stop")
        self.job_stop.clicked.connect(self.stop_job)
        row.addWidget(self.job_lbl, 1)
        row.addWidget(self.job_bar, 1)
        row.addWidget(self.job_stop)
        self.job_row = QWidget()
        self.job_row.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.job_row)
        self.pages.addTab(fp, "Files")

        # ---- Commands
        cp = QWidget()
        cl = QVBoxLayout(cp)
        self.cwd_lbl = QLabel("")
        self.cwd_lbl.setStyleSheet(f"color:{ui_kit.MUTED};")
        cl.addWidget(self.cwd_lbl)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(6000)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.out.setFont(f)
        cl.addWidget(self.out, 1)
        row = QHBoxLayout()
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setFont(f)
        self.cmd_edit.setPlaceholderText("A command for the other computer, then Enter   (cd <folder> changes the folder)")
        self.cmd_edit.returnPressed.connect(self.run_command)
        self.cmd_edit.installEventFilter(self)
        self.run_btn = ui_kit.primary(QPushButton("Run"))
        self.run_btn.clicked.connect(self.run_command)
        self.kill_btn = QPushButton("Stop")
        self.kill_btn.clicked.connect(self.stop_command)
        row.addWidget(self.cmd_edit, 1)
        row.addWidget(self.run_btn)
        row.addWidget(self.kill_btn)
        cl.addLayout(row)
        self.detach_box = QCheckBox("Start it on that screen and leave it running (a program with a window)")
        cl.addWidget(self.detach_box)
        self.pages.addTab(cp, "Commands")

        self.status = ui_kit.StatusLine("")
        ll.addWidget(self.status)

    def eventFilter(self, obj, ev):
        if obj is self.cmd_edit and ev.type() == ev.Type.KeyPress and ev.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self.history:
            self.hist_i = min(max(self.hist_i + (-1 if ev.key() == Qt.Key.Key_Up else 1), 0), len(self.history))
            self.cmd_edit.setText(self.history[self.hist_i] if self.hist_i < len(self.history) else "")
            return True
        return super().eventFilter(obj, ev)

    def say(self, text, level=""):
        self.status.say(text, level)

    def retitle(self):
        fn = getattr(self.host, "refresh_titles", None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def update_ui(self):
        on = self.connected()
        busy = self.connecting
        self.connect_btn.setText("Disconnect" if on else ("Connecting..." if busy else "Connect"))
        self.connect_btn.setEnabled(on or (not busy and self.list.currentItem() is not None))
        self.remove_btn.setEnabled(not on and self.list.currentItem() is not None)
        self.search_btn.setEnabled(not on and not busy)
        self.add_btn.setEnabled(not on and not busy)
        self.list.setEnabled(not on and not busy)
        self.stack.setCurrentWidget(self.pages if on else self.empty)
        if on:
            info = self.link.info
            files, cmds = bool(info.get("files")), bool(info.get("commands"))
            sel = self.tree.selectedItems()
            idle = self.job is None
            for b in (self.put_btn, self.putdir_btn, self.mkdir_btn):
                b.setEnabled(files and idle)
            self.get_btn.setEnabled(files and idle and bool(sel))
            self.ren_btn.setEnabled(files and idle and len(sel) == 1)
            self.del_btn.setEnabled(files and idle and bool(sel))
            self.job_row.setVisible(not idle)
            running = self.cmd_id is not None
            self.run_btn.setEnabled(cmds)
            self.run_btn.setText("Send" if running else "Run")
            self.kill_btn.setEnabled(running)
            self.type_btn.setEnabled(self.controlling())
            self.ctl_box.setEnabled(bool(info.get("input", {}).get("ok")))
        else:
            self.ctl_box.setEnabled(True)

    # ============================================================================ the list of computers
    def refresh_list(self):
        key = self.selected_key()
        self.list.clear()
        saved = RL.load_computers()
        seen = set()
        for c in saved:
            it = QListWidgetItem(f"{c.get('name') or c['host']}   ({c['host']})")
            it.setData(Qt.ItemDataRole.UserRole, dict(c, saved=True))
            self.list.addItem(it)
            seen.add((c["host"], int(c.get("port", RL.PORT))))
        for c in self.found:
            if (c["host"], c["port"]) in seen:
                continue
            it = QListWidgetItem(f"{c['name']}   ({c['host']})   - found")
            it.setData(Qt.ItemDataRole.UserRole, dict(c, saved=False))
            self.list.addItem(it)
        for i in range(self.list.count()):
            d = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            if (d["host"], int(d.get("port", RL.PORT))) == key:
                self.list.setCurrentRow(i)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def selected(self):
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def selected_key(self):
        d = self.selected()
        return (d["host"], int(d.get("port", RL.PORT))) if d else None

    def search(self):
        self.say("Searching this network ...")
        self.search_btn.setEnabled(False)

        def work():
            found = RL.discover(1.8)
            self.poster.post(lambda: self.search_done(found))
        threading.Thread(target=work, daemon=True).start()

    def search_done(self, found):
        self.found = found
        self.refresh_list()
        self.update_ui()
        n = len(found)
        self.say(f"Found {n} computer{'s' if n != 1 else ''} with the helper running." if n else
                 "No helper answered. Is it running on the other computer, and are both on the same Wi-Fi or hotspot? "
                 "Some networks block searching: use Add by address.", "" if n else "warn")

    def add_by_address(self):
        text, ok = QInputDialog.getText(self, "Add a computer", "Its address or name on the network\n(for example 192.168.1.42 or raspberrypi.local):")
        text = text.strip()
        if not ok or not text:
            return
        host, port = text, RL.PORT
        if text.count(":") == 1 and text.rsplit(":", 1)[1].isdigit():
            host, port = text.rsplit(":", 1)[0], int(text.rsplit(":", 1)[1])
        RL.remember(host, host, port)
        self.refresh_list()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole)["host"] == host:
                self.list.setCurrentRow(i)
        self.update_ui()

    def remove_selected(self):
        d = self.selected()
        if not d:
            return
        if d.get("saved"):
            RL.forget(d["host"], d.get("port", RL.PORT))
        else:
            self.found = [c for c in self.found if (c["host"], c["port"]) != (d["host"], d["port"])]
        self.refresh_list()
        self.update_ui()

    # ============================================================================ connecting
    def toggle_connect(self):
        if self.connected():
            self.disconnect_now()
            self.say("Disconnected.")
        else:
            self.connect_selected()

    def connect_selected(self, code=None, keep=False, note=""):
        d = self.selected()
        if not d or self.connected() or self.connecting:
            return
        if code is None:
            code = d.get("code")
        if not code:
            dlg = CodeDialog(self, d.get("name") or d["host"], note)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.edit.text().strip():
                return
            code, keep = dlg.edit.text().strip(), dlg.keep.isChecked()
        self.start_connect(d, code, keep)

    def start_connect(self, d, code, keep=False):
        self.connecting = True
        self.say(f"Connecting to {d.get('name') or d['host']} ...")
        self.empty.set_text(EMPTY_TITLE, EMPTY_TEXT)
        self.update_ui()
        link = RL.Link(d["host"], d.get("port", RL.PORT), code)

        def work():
            try:
                link.connect()
                self.poster.post(lambda: self.connect_done(link, d, code, keep, None))
            except RL.RemoteError as e:
                self.poster.post(lambda e=e: self.connect_done(None, d, code, keep, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def connect_done(self, link, d, code, keep, err):
        self.connecting = False
        if err and self.updating:                          # the new helper is not up yet: try again shortly
            self.update_ui()
            self.say("Waiting for the helper there to start again ...")
            QTimer.singleShot(2500, self.reconnect_after_update)
            return
        was_updating, self.was_updating = self.was_updating, False
        if err:
            self.update_ui()
            self.say(err, "bad")
            if "does not answer" in err or "did not get through" in err:      # the whole reason, where there is room to read it
                self.empty.set_text(f"Could not connect to {d.get('name') or d['host']}", err)
            if "access code" in err.lower() and "many" not in err.lower():
                if d.get("code"):                           # a remembered code that no longer works is dropped
                    RL.remember(d.get("name") or d["host"], d["host"], d.get("port", RL.PORT))
                    self.refresh_list()
                self.connect_selected(note="That code was not accepted. Type it again (letters and digits; dashes and spaces do not matter).")
            return
        self.link = link
        link.on_closed = lambda why: self.poster.post(lambda: self.link_closed(link, why))
        link.on_notice = lambda text: self.poster.post(lambda: self.say(text, "warn"))
        info = link.info
        RL.remember(info.get("name") or d.get("name") or d["host"], d["host"], d.get("port", RL.PORT), code if (keep or d.get("code")) else None)
        self.refresh_list()
        self.current = (dict(d), code, bool(keep or d.get("code")))       # for connecting again by itself after its helper was updated
        self.update_btn.setVisible(link.helper_outdated())
        self.repeat_keys = info.get("platform") == "win32"
        self.cwd = info.get("home")
        self.rdir = info.get("home") or ""
        self.out.clear()
        self.show_info()
        self.update_ui()
        self.retitle()
        if was_updating:
            self.updating = 0
            self.say(f"Connected to {link.label()} again; its helper is now version {info.get('helper')}.", "good")
        else:
            self.say(f"Connected to {link.label()}.", "good")
        self.view.clear()
        self.frames = 0
        threading.Thread(target=self.frame_loop, args=(link,), daemon=True).start()
        if info.get("files"):
            self.browse(self.rdir)
        self.cwd_lbl.setText(f"Folder there: {self.cwd}")
        self.pages.setCurrentIndex(0 if info.get("screen", {}).get("ok") else 1)
        self.view.setFocus()

    def show_info(self):
        i = self.link.info
        lines = [f"<b>{i.get('name', '')}</b>", f"{i.get('system', '')} {i.get('release', '')} ({i.get('machine', '')}), user {i.get('user', '')}"]
        sc, ip = i.get("screen", {}), i.get("input", {})
        lines.append(f"Screen {sc.get('w')} x {sc.get('h')}" if sc.get("ok") else f"<span style='color:{ui_kit.WARN}'>Screen: {sc.get('why', 'not available')}</span>")
        if not ip.get("ok"):
            lines.append(f"<span style='color:{ui_kit.WARN}'>Keyboard and mouse: {ip.get('why', 'not available')}</span>")
        off = [w for w, k in (("files", "files"), ("commands", "commands")) if not i.get(k)]
        if off:
            lines.append(f"<span style='color:{ui_kit.WARN}'>Switched off there: {', '.join(off)}</span>")
        self.info_lbl.setText("<br>".join(lines))
        self.screen_msg.setText("" if sc.get("ok") else sc.get("why", ""))

    def disconnect_now(self):
        link, self.link = self.link, None
        if link is not None:
            link.on_closed = None
            link.close()
        self.cmd_id = None
        self.updating, self.was_updating = 0, False
        self.update_btn.hide()
        self.info_lbl.setText("")
        self.update_ui()
        self.retitle()

    def link_closed(self, link, why):
        if link is not self.link:
            return
        self.link = None
        self.cmd_id = None
        self.info_lbl.setText("")
        self.update_btn.hide()
        self.update_ui()
        self.retitle()
        if self.updating:
            self.say("The helper there is starting again ...")
            QTimer.singleShot(3000, self.reconnect_after_update)
        else:
            self.say(why, "bad")

    # ============================================================================ a newer helper for the other computer
    def update_helper(self):
        if not self.connected() or self.updating or self.job is not None:
            return
        r = QMessageBox.question(self, "Update its helper",
                                 f"Send this OpenPara's helper (version {RL.H.HELPER_VERSION}) to {self.link.label()} in place of the one "
                                 f"running there (version {self.link.info.get('helper')}), and start it again?\n\nThe connection ends "
                                 "for a few seconds and comes back by itself. The access code stays the same.")
        if r != QMessageBox.StandardButton.Yes:
            return
        link = self.link
        self.updating, self.was_updating = 5, True         # tries to connect again
        self.say("Sending the new helper ...")

        def work():
            try:
                link.update_helper()
            except RL.RemoteError as e:
                self.poster.post(lambda e=e: self.update_failed(str(e)))
        threading.Thread(target=work, daemon=True).start()

    def update_failed(self, err):
        self.updating, self.was_updating = 0, False
        self.say(err, "bad")

    def reconnect_after_update(self):
        if not self.updating or self.connected() or self.connecting or not self.current:
            return
        self.updating -= 1
        d, code, keep = self.current
        self.start_connect(d, code, keep)

    # ============================================================================ the screen
    def on_page(self, _i=None):
        self.screen_on = self.pages.currentIndex() == 0 and self.isVisible()
        if self.pages.currentIndex() == 0:
            self.view.setFocus()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.screen_on = self.pages.currentIndex() == 0

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.screen_on = False

    def frame_loop(self, link):
        """Keeps asking for what changed on the other screen while the Screen page is shown."""
        if not link.info.get("screen", {}).get("ok"):
            return
        full = True
        while not link.closed and link is self.link:
            if not self.screen_on:
                time.sleep(0.2)
                full = True
                continue
            try:
                h, payload = link.frame(full=full, lossy=self.fast, wait=0.5)
                full = False
                if self.view.apply_frame(h, payload):
                    self.frames += 1
                    self.poster.post(self.view.update)
            except RL.LinkClosed:
                return
            except RL.RemoteError as e:
                self.poster.post(lambda e=e: self.screen_msg.setText(str(e)))
                time.sleep(2.0)
                full = True
            except Exception as e:  # noqa: BLE001  (a frame we could not read must not end the picture)
                self.poster.post(lambda e=e: self.screen_msg.setText(f"A picture could not be shown ({type(e).__name__})."))
                time.sleep(1.0)
                full = True

    def type_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            self.say("There is no text on the clipboard.", "warn")
            return
        if len(text) > 4000:
            self.say("That is more than 4000 characters; send it as a file instead.", "warn")
            return
        try:
            self.link.input([{"t": "text", "s": text}])
            self.say(f"Typed {len(text)} characters there.")
        except RL.RemoteError as e:
            self.say(str(e), "bad")
        self.view.setFocus()

    def save_picture(self):
        img = self.view.snapshot()
        if img is None:
            self.say("There is no picture yet.", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save picture", f"{self.link.label()} screen.png", "PNG picture (*.png)")
        if path:
            img.save(path if path.lower().endswith(".png") else path + ".png")
            self.say(f"Saved {os.path.basename(path)}.")

    # ============================================================================ files
    def call(self, fn, *a, **k):
        """A quick request to the other computer; a problem is shown in the status line and gives None."""
        try:
            return fn(*a, **k)
        except RL.RemoteError as e:
            self.say(str(e), "bad")
            return None

    def browse(self, path):
        if not self.connected():
            return
        r = self.call(self.link.ls, path)
        if r is None:
            return
        self.rdir, self.parent_dir = r["path"], r.get("parent")
        self.path_edit.setText(self.rdir)
        self.up_btn.setEnabled(self.parent_dir is not None)
        self.tree.clear()
        for name, is_dir, size, mtime in r["entries"]:
            it = QTreeWidgetItem([name, "folder" if is_dir else human_size(size),
                                  time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else ""])
            it.setData(0, Qt.ItemDataRole.UserRole, (name, bool(is_dir), size))
            if is_dir:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            self.tree.addTopLevelItem(it)
        self.update_ui()

    def go_up(self):
        if self.parent_dir is not None:
            self.browse(self.parent_dir)

    def open_item(self, it, _col=0):
        name, is_dir, _size = it.data(0, Qt.ItemDataRole.UserRole)
        if is_dir:
            self.browse(self.link.join(self.rdir, name) if self.rdir else name)

    def picked(self):
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]

    def start_job(self, label, work, done_text):
        """work(progress, stop) runs in the background; progress(done, total, name)."""
        if self.job is not None:
            return
        job = self.job = {"stop": False}
        self.job_lbl.setText(label)
        self.job_bar.setValue(0)
        self.update_ui()
        last = [0.0]

        def progress(done, total, name=""):
            if time.time() - last[0] > 0.1 or done >= total:
                last[0] = time.time()
                self.poster.post(lambda: (self.job_bar.setValue(int(1000 * done / max(total, 1))),
                                          self.job_lbl.setText(f"{label}  {human_size(done)} of {human_size(total)}  {name}")))

        def run():
            err, res = None, None
            try:
                res = work(progress, lambda: job["stop"])
            except RL.Stopped:
                err = "Stopped."
            except RL.RemoteError as e:
                err = str(e)
            except OSError as e:
                err = f"{e.strerror or e}" + (f": {e.filename}" if e.filename else "")
            self.poster.post(lambda: self.job_done(job, err, done_text(res) if err is None else None))
        threading.Thread(target=run, daemon=True).start()

    def job_done(self, job, err, text):
        if self.job is job:
            self.job = None
        self.update_ui()
        self.say(err or text, "bad" if err and err != "Stopped." else ("warn" if err else "good"))
        if self.connected():
            self.browse(self.rdir)

    def stop_job(self):
        if self.job is not None:
            self.job["stop"] = True
            self.job_lbl.setText("Stopping ...")

    def download_selected(self):
        items = self.picked()
        if not items:
            return
        dest = QFileDialog.getExistingDirectory(self, "Copy to this folder on this PC")
        if not dest:
            return
        clash = [n for n, _d, _s in items if os.path.exists(os.path.join(dest, n))]
        if clash and QMessageBox.question(self, "Copy to this PC", f"{', '.join(clash[:5])}{' ...' if len(clash) > 5 else ''} "
                                          f"{'is' if len(clash) == 1 else 'are'} already in that folder. Replace? (In a folder, files of the same "
                                          "size are kept.)") != QMessageBox.StandardButton.Yes:
            return
        link, rdir = self.link, self.rdir

        def work(progress, stop):
            n = 0
            for name, is_dir, _size in items:
                src = link.join(rdir, name)
                if is_dir:
                    c, _s = link.download_tree(src, os.path.join(dest, name), progress, stop)
                    n += c
                else:
                    link.download(src, os.path.join(dest, name), lambda d, t, nm=name: progress(d, t, nm), stop)
                    n += 1
            return n
        self.start_job("Copying to this PC", work, lambda n: f"Copied {n} file{'s' if n != 1 else ''} to {dest}.")

    def upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Send these files to the other computer")
        if files:
            self.send_paths(files)

    def upload_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Send this folder to the other computer")
        if d:
            self.send_paths([d])

    def send_paths(self, paths):
        there = {it.data(0, Qt.ItemDataRole.UserRole)[0] for it in (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))}
        clash = [os.path.basename(p.rstrip("/\\")) for p in paths if os.path.basename(p.rstrip("/\\")) in there]
        if clash and QMessageBox.question(self, "Send", f"{', '.join(clash[:5])}{' ...' if len(clash) > 5 else ''} "
                                          f"{'is' if len(clash) == 1 else 'are'} already in that folder there. Replace?") != QMessageBox.StandardButton.Yes:
            return
        link, rdir = self.link, self.rdir

        def work(progress, stop):
            n = 0
            for p in paths:
                name = os.path.basename(p.rstrip("/\\"))
                if os.path.isdir(p):
                    n += link.upload_tree(p, link.join(rdir, name), progress, stop)
                else:
                    link.upload(p, link.join(rdir, name), lambda d, t, nm=name: progress(d, t, nm), stop)
                    n += 1
            return n
        self.start_job("Sending", work, lambda n: f"Sent {n} file{'s' if n != 1 else ''} to {rdir}.")

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "New folder", "Name of the new folder there:")
        if ok and name.strip():
            try:
                self.link.mkdir(self.link.join(self.rdir, name.strip()))
            except RL.RemoteError as e:
                self.say(str(e), "bad")
                return
            self.browse(self.rdir)

    def rename_selected(self):
        items = self.picked()
        if len(items) != 1:
            return
        old = items[0][0]
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip() and new.strip() != old:
            try:
                self.link.rename(self.link.join(self.rdir, old), self.link.join(self.rdir, new.strip()))
            except RL.RemoteError as e:
                self.say(str(e), "bad")
            self.browse(self.rdir)

    def delete_selected(self):
        items = self.picked()
        if not items:
            return
        names = ", ".join(n for n, _d, _s in items[:6]) + (" ..." if len(items) > 6 else "")
        folders = sum(1 for _n, d, _s in items if d)
        r = QMessageBox.question(self, "Delete on the other computer",
                                 f"Delete {names} on {self.link.label()}?\n\n" + (f"{folders} of them {'is a folder' if folders == 1 else 'are folders'}: "
                                 "everything inside goes too. " if folders else "") + "This cannot be undone (there is no recycle bin).")
        if r != QMessageBox.StandardButton.Yes:
            return
        for name, is_dir, _s in items:
            try:
                self.link.delete(self.link.join(self.rdir, name), recursive=is_dir)
            except RL.RemoteError as e:
                self.say(str(e), "bad")
                break
        else:
            self.say(f"Deleted {len(items)} item{'s' if len(items) != 1 else ''}.")
        self.browse(self.rdir)

    # ============================================================================ commands
    def append_out(self, text):
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)
        self.out.insertPlainText(text)
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)

    def run_command(self):
        text = self.cmd_edit.text()
        if not self.connected():
            return
        if self.cmd_id is not None:                          # a command is running: the line goes to it
            try:
                self.link.write_in(self.cmd_id, text + "\n")
                self.append_out(text + "\n")
            except RL.RemoteError as e:
                self.say(str(e), "bad")
            self.cmd_edit.clear()
            return
        cmd = text.strip()
        if not cmd:
            return
        self.history.append(cmd)
        self.hist_i = len(self.history)
        self.cmd_edit.clear()
        self.append_out(f"\n> {cmd}\n")
        link = self.link
        win = link.info.get("platform") == "win32"
        if cmd == "cd" or cmd.startswith("cd "):
            target = cmd[2:].strip().strip('"') or link.info.get("home", "")
            code, out = self.call(link.run, (f'cd /d "{target}" && cd' if win else f'cd "{target}" && pwd'), self.cwd, 20) or (1, "")
            if code == 0 and out.strip():
                self.cwd = out.strip().splitlines()[-1]
                self.cwd_lbl.setText(f"Folder there: {self.cwd}")
            else:
                self.append_out(out or "That folder could not be opened.\n")
            return
        if self.detach_box.isChecked():
            try:
                pid = link.launch(cmd, self.cwd)
                self.append_out(f"Started (process {pid}); it keeps running there.\n")
            except RL.RemoteError as e:
                self.append_out(f"{e}\n")
            return
        try:
            self.cmd_id = link.spawn(cmd, self.cwd, on_out=lambda t: self.poster.post(lambda: self.append_out(t)),
                                     on_done=lambda code, stopped: self.poster.post(lambda: self.command_done(code, stopped)))
        except RL.RemoteError as e:
            self.append_out(f"{e}\n")
        self.update_ui()

    def command_done(self, code, stopped):
        self.cmd_id = None
        if stopped:
            self.append_out("[stopped]\n")
        elif code not in (0, None):
            self.append_out(f"[ended with code {code}]\n")
        self.update_ui()

    def stop_command(self):
        if self.cmd_id is not None and self.connected():
            try:
                self.link.kill(self.cmd_id)
            except RL.RemoteError:
                pass

    # ============================================================================ the helper file
    def save_helper(self):
        r = QMessageBox.information(
            self, "Get the helper",
            "The other computer needs one small file, openpara_remote_helper.py, and Python 3.8 or newer.\n\n"
            "Choose a folder or a USB drive next. OpenPara saves the helper and a read-me with the steps there; carry it to the other "
            "computer and follow the read-me (it takes a minute, and you need to see that computer's screen that one time).\n\n"
            "Whoever knows its access code can see and use that computer fully, so only do this with computers of your own.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Ok:
            return
        dest = QFileDialog.getExistingDirectory(self, "Save the helper to this folder")
        if not dest:
            return
        out = save_helper_to(dest)
        if out:
            self.say(f"Saved the helper and its read-me to {out}.", "good")
        else:
            self.say("The helper could not be saved there (is the drive writable?).", "bad")


SETUP_DESKTOP = """[Desktop Entry]
Type=Application
Name=Set up the OpenPara Remote helper
Comment=Installs the helper on this computer and shows its access code
Exec=bash -c 'S=$(find /media /mnt /run/media "$HOME" -maxdepth 6 -name openpara_remote_helper.py 2>/dev/null | head -n1); if [ -n "$S" ]; then python3 "$S" --install; else echo "openpara_remote_helper.py was not found on any drive."; fi; echo; read -p "Write the access code down, then press Enter to close. " x'
Icon=preferences-desktop-remote-desktop
Terminal=true
Categories=Utility;
"""
SETUP_BAT = ("@echo off\r\ncd /d \"%~dp0\"\r\nwhere python >nul 2>nul && (python openpara_remote_helper.py --install) || (py -3 openpara_remote_helper.py --install)\r\n"
             "echo.\r\necho Write the access code down. If nothing was shown above, install Python from python.org first.\r\npause\r\n")


def save_helper_to(dest):
    """Writes the helper, its read-me and a double-click set-up for Linux and for Windows into <dest>/OpenPara Remote helper/; returns that
    folder, or None."""
    out = os.path.join(dest, "OpenPara Remote helper")
    try:
        os.makedirs(out, exist_ok=True)
        shutil.copyfile(RL.helper_path(), os.path.join(out, "openpara_remote_helper.py"))
        for name, text in (("READ ME.txt", HELPER_README), ("Set up (Raspberry Pi, Linux).desktop", SETUP_DESKTOP)):
            with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        with open(os.path.join(out, "Set up (Windows).bat"), "w", encoding="ascii", newline="") as f:
            f.write(SETUP_BAT)
    except OSError:
        return None
    return out


def make_tab(host=None):
    return RemoteTab(host)
