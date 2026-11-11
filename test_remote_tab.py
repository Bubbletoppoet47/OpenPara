"""Remote Computer tab (Playground only): registered as an add-on that a normal OpenPara does not offer; connect with the access code (asked
for, remembered on request, a wrong one asked again); the other screen is shown and kept up to date; this PC's mouse and keyboard become
events there - only while 'Use its keyboard and mouse' is on; files both ways with progress; commands; a lost connection is said in words;
the helper and its read-me can be saved for the other computer."""
import os, sys, tempfile, time, shutil
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor", "gimble_link"]}')
os.environ["OPRH_CONFIG_DIR"] = tempfile.mkdtemp(prefix="opara_rh_")
import addons
assert "remote" in addons.NOT_RELEASED and "remote" not in addons.known(), "a normal OpenPara does not know it"
addons.NOT_RELEASED = ()          # from here on: as in the Playground's Full dev mode
addons.startup()
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QInputDialog, QDialog
app = QApplication([])
ASK = []
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Yes)[1])
QMessageBox.information = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Ok)[1])
import remote_tab as RT, remote_link as RL, openpara_remote_helper as H
import numpy as np

assert addons.status("remote") == "installed" and addons.tab_kinds()["remote"]["label"] == "Remote Computer"
assert addons.info("remote")["name"] == "Remote Computer"
import icon_set; assert icon_set.TAB_KIND["remote"] in icon_set.ICONS if hasattr(icon_set, "ICONS") else True


def wait(cond, secs=8.0, what=""):
    t = time.time()
    while time.time() - t < secs:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise SystemExit(f"timed out: {what}")


class FakeScreen:
    name = "fake"
    def __init__(self, w=320, h=200):
        self.w, self.h = w, h
        self.buf = bytearray(os.urandom(64) * (w * h * 4 // 64))
    def grab(self):
        return self.w, self.h, 4, "bgrx", bytes(self.buf)
    def paint(self, x, y, w, h, bgrx):
        for r in range(y, y + h):
            self.buf[(r * self.w + x) * 4:(r * self.w + x + w) * 4] = bytes(bgrx) * w


class FakeInput(H._Keys):
    name = "fake"
    shift_code = "SHIFT"
    def __init__(self):
        super().__init__(); self.log = []
    def move(self, x, y, w, h): self.log.append(("move", round(x), round(y)))
    def button(self, b, down): self.log.append(("btn", b, down))
    def wheel(self, dy, dx=0): self.log.append(("wheel", dy, dx))
    def lookup(self, key):
        if key in H.KEYSYMS or key == " ": return key, None
        return (key.lower(), key.isupper()) if len(key) == 1 else None
    def raw_key(self, code, down): self.log.append(("key", code, down))
    def flush(self): pass


cfg = H.set_code({"name": "Bench Pi"}, "ABCD-EFGH-JKMN")
hp = H.Helper(cfg, port=0, bind="127.0.0.1", discovery=False)
hp.screen, hp.inp = FakeScreen(), FakeInput()
hp.jpeg = None                                     # exact pictures, so they can be compared
hp.start()

w = RT.make_tab()
w.resize(1100, 700); w.show(); app.processEvents()
assert w.title() == "Remote Computer" and not w.is_dirty() and w.can_close()
assert w.stack.currentWidget() is w.empty and "access code" in w.empty.text.text() and [b.text() for b in w.empty.buttons] == ["Search this network", "Get the helper..."]
assert w.list.count() == 0 and not w.connect_btn.isEnabled(), "nothing to connect to yet"

# ---- add a computer by address; the code is asked for, a wrong one is said and asked again, 'remember' keeps it
QInputDialog.getText = staticmethod(lambda *a, **k: (f"127.0.0.1:{hp.port}", True))
w.add_by_address()
assert w.list.count() == 1 and w.connect_btn.isEnabled() and RL.load_computers()[0]["port"] == hp.port
codes = [("WRONG-CODE-1234", False), ("abcd efgh jkmn", True)]
notes = []
def fake_exec(self):
    notes.append(self.findChildren(RT.QLabel)[-1].text())
    if not codes:
        return QDialog.DialogCode.Rejected
    code, keep = codes.pop(0)
    self.edit.setText(code); self.keep.setChecked(keep)
    return QDialog.DialogCode.Accepted
RT.CodeDialog.exec = fake_exec
w.connect_selected()
assert w.connecting and w.connect_btn.text() == "Connecting..." and not w.connect_btn.isEnabled()
wait(w.connected, what="connect after a wrong code")
assert len(notes) == 2 and "not accepted" in notes[1], notes
assert w.title() == "Remote: Bench Pi" and w.stack.currentWidget() is w.pages and w.connect_btn.text() == "Disconnect"
assert "Bench Pi" in w.info_lbl.text() and "320 x 200" in w.info_lbl.text() and "Connected to Bench Pi" in w.status.text()
saved = RL.load_computers()[0]
assert saved["name"] == "Bench Pi" and saved["code"] == "abcd efgh jkmn", saved
assert not w.search_btn.isEnabled() and not w.list.isEnabled(), "the list is not changed while connected"

# ---- the picture: the whole screen first, then what changes there
def same():
    fb = w.view.fb
    return fb is not None and fb.shape == (200, 320, 4) and bytes(fb[:, :, :3].tobytes()) == bytes(np.frombuffer(bytes(hp.screen.buf), np.uint8).reshape(200, 320, 4)[:, :, :3].tobytes())
wait(same, what="first picture")
hp.screen.paint(100, 50, 40, 40, (10, 200, 30, 0))
wait(same, what="changed picture")
assert w.frames >= 2 and w.view.snapshot().width() == 320
assert tuple(w.view.snapshot().pixelColor(110, 60).getRgb()[:3]) == (30, 200, 10), "blue-green-red there is red-green-blue here"

# ---- mouse and keyboard
v = w.view
v.repaint(); app.processEvents()
t = v.target
assert abs(t.width() / t.height() - 320 / 200) < 0.01, "the picture keeps its shape"
def at(sx, sy):
    return QPoint(int(t.x() + (sx + 0.5) * t.width() / 320), int(t.y() + (sy + 0.5) * t.height() / 200))
log = hp.inp.log
def settle():
    v.flush(); w.link.request("ping")
QTest.mouseClick(v, Qt.MouseButton.LeftButton, pos=at(160, 100)); settle()
assert log[-3:] == [("btn", 1, True), ("move", 160, 100), ("btn", 1, False)] or (("btn", 1, True) in log and ("btn", 1, False) in log and ("move", 160, 100) in log), log
del log[:]
QTest.mouseClick(v, Qt.MouseButton.RightButton, pos=at(10, 190)); settle()
assert ("move", 10, 190) in log and ("btn", 2, True) in log and ("btn", 2, False) in log, log
del log[:]
QTest.mouseMove(v, QPoint(2, 2)); settle()                          # outside the picture: the edge of the screen there
assert log and log[-1][0] == "move" and 0 <= log[-1][1] < 320 and 0 <= log[-1][2] < 200
del log[:]
v.setFocus(); app.processEvents()
def key(k, text="", mods=Qt.KeyboardModifier.NoModifier, down=True, up=True):          # as a real keyboard sends them (the text follows Shift)
    if down:
        app.sendEvent(v, QKeyEvent(QEvent.Type.KeyPress, k, mods, text))
    if up:
        app.sendEvent(v, QKeyEvent(QEvent.Type.KeyRelease, k, mods, text))
QTest.keyClick(v, Qt.Key.Key_A)
key(Qt.Key.Key_Shift, down=True, up=False); key(Qt.Key.Key_B, "B", Qt.KeyboardModifier.ShiftModifier); key(Qt.Key.Key_Shift, down=False)
QTest.keyClick(v, Qt.Key.Key_Return); QTest.keyClick(v, Qt.Key.Key_Tab); QTest.keyClick(v, Qt.Key.Key_F5); QTest.keyClick(v, Qt.Key.Key_Space); settle()
assert log == [("key", "a", True), ("key", "a", False), ("key", "Shift", True), ("key", "b", True), ("key", "b", False), ("key", "Shift", False),
               ("key", "Return", True), ("key", "Return", False), ("key", "Tab", True), ("key", "Tab", False), ("key", "F5", True), ("key", "F5", False),
               ("key", " ", True), ("key", " ", False)], log
del log[:]
key(Qt.Key.Key_Question, "?"); settle()                                # a character that needs Shift there although Shift is not held here
assert log == [("key", "?", True), ("key", "?", False)], log
assert app.focusWidget() is v, "Tab went to the other computer, not to the next button here"
del log[:]
key(Qt.Key.Key_Control, down=True, up=False); key(Qt.Key.Key_S, "\x13", Qt.KeyboardModifier.ControlModifier); key(Qt.Key.Key_Control, down=False); settle()
assert log == [("key", "Control", True), ("key", "s", True), ("key", "s", False), ("key", "Control", False)], log
ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
app.sendEvent(v, ev); assert ev.isAccepted(), "Ctrl+S is not taken by OpenPara's own Save while the other screen has the keyboard"
del log[:]
QTest.keyPress(v, Qt.Key.Key_Shift); settle(); assert log == [("key", "Shift", True)]
w.cmd_edit.setFocus(); app.processEvents(); settle()
assert ("key", "Shift", False) in log, "leaving the picture lets go of the keys that were held"
del log[:]
app.clipboard().setText("pass word")
w.type_clipboard(); w.link.request("ping")
assert [e for e in log if e[2]] == [("key", c, True) for c in "pass word"] and "Typed 9 characters" in w.status.text()
del log[:]
w.ctl_box.setChecked(False)                                           # watching only
QTest.mouseClick(v, Qt.MouseButton.LeftButton, pos=at(5, 5)); QTest.keyClick(v, Qt.Key.Key_A); settle()
assert log == [] and not w.type_btn.isEnabled() and not w.controlling()
w.ctl_box.setChecked(True)

# ---- files
D = tempfile.mkdtemp(prefix="opara_rt_")
os.makedirs(os.path.join(D, "there", "sub")); open(os.path.join(D, "there", "note.txt"), "w").write("hello")
open(os.path.join(D, "there", "sub", "deep.bin"), "wb").write(os.urandom(50000))
w.pages.setCurrentIndex(1)
w.browse(os.path.join(D, "there"))
names = [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]
assert names == ["sub", "note.txt"] and w.path_edit.text() == os.path.join(D, "there") and w.tree.topLevelItem(0).text(1) == "folder"
assert w.tree.topLevelItem(1).text(1) == "5 B" and not w.get_btn.isEnabled(), "nothing picked yet"
w.open_item(w.tree.topLevelItem(0)); assert w.rdir == os.path.join(D, "there", "sub") and w.tree.topLevelItem(0).text(0) == "deep.bin"
w.go_up(); assert w.rdir == os.path.join(D, "there")
local = os.path.join(D, "mine.dat"); open(local, "wb").write(os.urandom(300000))
w.send_paths([local])
assert w.job is not None and not w.job_row.isHidden() and not w.put_btn.isEnabled()
wait(lambda: w.job is None, what="send")
assert open(os.path.join(D, "there", "mine.dat"), "rb").read() == open(local, "rb").read() and "Sent 1 file" in w.status.text()
assert "mine.dat" in [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())] and w.job_row.isHidden()
n = len(ASK); w.send_paths([local]); assert len(ASK) == n + 1 and "already in that folder there" in ASK[-1]; wait(lambda: w.job is None)
os.makedirs(os.path.join(D, "here"))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: os.path.join(D, "here"))
w.tree.clearSelection()
for i in range(w.tree.topLevelItemCount()):
    if w.tree.topLevelItem(i).text(0) in ("sub", "note.txt"):
        w.tree.topLevelItem(i).setSelected(True)
assert w.get_btn.isEnabled()
w.download_selected(); wait(lambda: w.job is None, what="copy to this PC")
assert open(os.path.join(D, "here", "note.txt")).read() == "hello" and os.path.getsize(os.path.join(D, "here", "sub", "deep.bin")) == 50000
assert "Copied 2 files" in w.status.text(), w.status.text()
QInputDialog.getText = staticmethod(lambda *a, **k: ("made here", True)); w.new_folder(); assert os.path.isdir(os.path.join(D, "there", "made here"))
w.tree.clearSelection(); [w.tree.topLevelItem(i).setSelected(True) for i in range(w.tree.topLevelItemCount()) if w.tree.topLevelItem(i).text(0) == "note.txt"]
QInputDialog.getText = staticmethod(lambda *a, **k: ("renamed.txt", True)); w.rename_selected(); assert os.path.exists(os.path.join(D, "there", "renamed.txt"))
w.tree.clearSelection(); [w.tree.topLevelItem(i).setSelected(True) for i in range(w.tree.topLevelItemCount()) if w.tree.topLevelItem(i).text(0) in ("sub", "renamed.txt")]
n = len(ASK); w.delete_selected()
assert len(ASK) == n + 1 and "cannot be undone" in ASK[-1] and "1 of them is a folder" in ASK[-1] and "Bench Pi" in ASK[-1]
assert sorted(os.listdir(os.path.join(D, "there"))) == ["made here", "mine.dat"] and "Deleted 2 items" in w.status.text()
w.browse(os.path.join(D, "nowhere")); assert "No such file" in w.status.text() and w.rdir == os.path.join(D, "there"), "a folder that is not there is said, the list stays"

# ---- commands
w.pages.setCurrentIndex(2)
py = sys.executable
w.cmd_edit.setText(f'"{py}" -c "print(6*7)"'); w.run_command()
wait(lambda: w.cmd_id is None and "42" in w.out.toPlainText(), what="command")
assert w.out.toPlainText().count("> ") == 1 and w.run_btn.text() == "Run" and not w.kill_btn.isEnabled()
w.cmd_edit.setText(f"cd {os.path.join(D, 'there')}"); w.run_command()
assert w.cwd == os.path.join(D, "there") and w.cwd in w.cwd_lbl.text()
w.cmd_edit.setText(f'"{py}" -c "import os; print(os.path.basename(os.getcwd()))"'); w.run_command()
wait(lambda: w.cmd_id is None and w.out.toPlainText().rstrip().endswith("there"), what="command in the new folder")
w.cmd_edit.setText(f'"{py}" -c "import time; time.sleep(60)"'); w.run_command()
wait(lambda: w.cmd_id is not None); assert w.run_btn.text() == "Send" and w.kill_btn.isEnabled()
w.stop_command(); wait(lambda: w.cmd_id is None, what="stop a command"); assert "[stopped]" in w.out.toPlainText()
w.cmd_edit.setText(f'"{py}" -c "import sys; sys.exit(4)"'); w.run_command(); wait(lambda: "[ended with code 4]" in w.out.toPlainText())
assert w.history[-1].endswith('sys.exit(4)"') and len(w.history) == 5
QTest.keyClick(w.cmd_edit, Qt.Key.Key_Up); assert w.cmd_edit.text() == w.history[-1]; QTest.keyClick(w.cmd_edit, Qt.Key.Key_Down); assert w.cmd_edit.text() == ""

# ---- the helper for the other computer
out = RT.save_helper_to(D)
assert sorted(os.listdir(out)) == ["READ ME.txt", "Set up (Raspberry Pi, Linux).desktop", "Set up (Windows).bat", "openpara_remote_helper.py"]
assert os.path.basename(out) == "OpenPara Remote helper"
desk = open(os.path.join(out, "Set up (Raspberry Pi, Linux).desktop")).read(); bat = open(os.path.join(out, "Set up (Windows).bat"), newline="").read()
assert "openpara_remote_helper.py" in desk and "--install" in desk and "Terminal=true" in desk and "\r" not in desk
assert "--install" in bat and "pause" in bat and bat.count("\r\n") >= 5
assert open(os.path.join(out, "openpara_remote_helper.py"), encoding="utf-8").read() == open(H.__file__, encoding="utf-8").read()
rd = open(os.path.join(out, "READ ME.txt"), encoding="utf-8").read()
for words in ("--install", "ACCESS CODE", "same network", "--new-code", "--uninstall", "New Remote Computer", "Set up (Windows).bat", "--check"):
    assert words in rd, words
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: os.path.join(D, "usb")); os.makedirs(os.path.join(D, "usb"))
w.save_helper(); assert os.path.isfile(os.path.join(D, "usb", "OpenPara Remote helper", "openpara_remote_helper.py")) and "Saved the helper" in w.status.text()
assert "only do this with computers of your own" in ASK[-1]

# ---- the other computer goes away: said in words, back to the start; connecting again uses the remembered code without asking
w.pages.setCurrentIndex(0)
hp.stop()
wait(lambda: w.link is None, what="lost connection")
assert "was lost" in w.status.text() and w.stack.currentWidget() is w.empty and w.title() == "Remote Computer" and w.connect_btn.text() == "Connect"
w.connect_selected(); wait(lambda: not w.connecting)
assert not w.connected() and "does not answer" in w.status.text() and "helper running" in w.status.text(), w.status.text()
assert w.empty.title.text() == "Could not connect to Bench Pi" and "no helper is listening" in w.empty.text.text(), "the whole reason is where it can be read"
hp = H.Helper(cfg, port=hp.port, bind="127.0.0.1", discovery=False); hp.screen, hp.inp, hp.jpeg = FakeScreen(), FakeInput(), None; hp.start()
n = len(notes); w.connect_selected(); wait(w.connected, what="reconnect"); assert len(notes) == n, "the remembered code was used"
assert w.empty.title.text() == RT.EMPTY_TITLE, "the earlier problem is not shown any more"
wait(same, what="picture after reconnect")

# ---- an older helper on the other computer: offered an update, sent over, started again there, and the tab connects again by itself
import subprocess, socket as _socket
assert w.update_btn.isHidden(), "the helper there is the current one: nothing to update"
w.toggle_connect()
OLD = os.path.join(D, "old_helper"); os.makedirs(OLD)
old_src = open(H.__file__, encoding="utf-8").read().replace(f'HELPER_VERSION = "{H.HELPER_VERSION}"', 'HELPER_VERSION = "0.9"')
assert 'HELPER_VERSION = "0.9"' in old_src
open(os.path.join(OLD, "openpara_remote_helper.py"), "w", encoding="utf-8").write(old_src)
k = _socket.socket(); k.bind(("127.0.0.1", 0)); free_port = k.getsockname()[1]; k.close()
env = dict(os.environ, OPRH_CONFIG_DIR=os.path.join(D, "old_cfg"))
subprocess.run([sys.executable, os.path.join(OLD, "openpara_remote_helper.py"), "--code", "OLDCODE12345", "--name", "Old laptop", "--port", str(free_port), "--status"],
               env=env, capture_output=True)
proc = subprocess.Popen([sys.executable, os.path.join(OLD, "openpara_remote_helper.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    RL.remember("Old laptop", "127.0.0.1", free_port, "OLDCODE12345"); w.refresh_list()
    for i in range(w.list.count()):
        if w.list.item(i).data(Qt.ItemDataRole.UserRole)["port"] == free_port:
            w.list.setCurrentRow(i)
    for _ in range(40):                                   # until that program listens
        try:
            _socket.create_connection(("127.0.0.1", free_port), timeout=0.5).close(); break
        except OSError:
            time.sleep(0.25)
    w.connect_selected(); wait(w.connected, what="connect to the old helper")
    assert w.link.info["helper"] == "0.9" and w.link.helper_outdated() and not w.update_btn.isHidden()
    n = len(ASK); w.update_helper()
    assert len(ASK) == n + 1 and "version 0.9" in ASK[-1] and H.HELPER_VERSION in ASK[-1] and "access code stays the same" in ASK[-1]
    wait(lambda: w.link is None, 20, "the old helper ends")
    assert "starting again" in w.status.text()
    wait(lambda: w.connected() and not w.updating, 40, "connected again after the update")
    assert w.link.info["helper"] == H.HELPER_VERSION and w.update_btn.isHidden() and f"its helper is now version {H.HELPER_VERSION}" in w.status.text()
    assert open(os.path.join(OLD, "openpara_remote_helper.py"), encoding="utf-8").read() == open(H.__file__, encoding="utf-8").read()
    assert RL.load_computers()[0].get("code") == "OLDCODE12345", "the remembered code is kept"
    pid = w.link.info["pid"]; assert pid != proc.pid
    w.toggle_connect()
finally:
    proc.kill()
    try:
        os.kill(pid, 15)
    except (NameError, OSError):
        pass
w.remove_selected()
assert w.list.count() == 1 and "Bench Pi" in w.list.item(0).text()
w.list.setCurrentRow(0); w.connect_selected(); wait(w.connected, what="back to the first computer")

# ---- Disconnect; closing the tab ends the connection
w.toggle_connect(); assert not w.connected() and w.status.text() == "Disconnected." and w.list.isEnabled()
w.connect_selected(); wait(w.connected)
link = w.link
assert w.can_close(); w.shutdown(); assert link.closed and w.link is None
w.remove_selected(); assert RL.load_computers() == [] and w.list.count() == 0

# ---- in the program window: File > New Remote Computer opens the tab (only where the add-on is offered)
import gpd_app
sh = gpd_app.AppShell([])
fm = next(a.menu() for a in sh.menuBar().actions() if a.text().replace("&", "") == "File")
assert "New Remote Computer" in [a.text() for a in fm.actions()]
tab = sh.new_addon_tab("remote")
assert isinstance(tab, RT.RemoteTab) and tab.host is sh and sh.tabs.tabText(sh.tabs.indexOf(tab)).startswith("Remote")
hp.stop()
for d in (_ud, D, os.environ["OPRH_CONFIG_DIR"]):
    shutil.rmtree(d, ignore_errors=True)
print("OK remote tab", flush=True)
os._exit(0)
