"""The program window: the start page (ways to start, recent files), File > Open Recent, the folder file windows start in, files dropped on the
window, the right-click menu and middle click on a tab, the window size that is remembered, and the error window that can be copied."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "render", "motor"]}')          # the big add-ons are not needed here (no download, no disk)
os.environ["OPARA_NO_UPDATE"] = "1"
DEV = tempfile.mkdtemp(prefix="opara_dev_"); os.environ["OPARA_DEV_ADDONS"] = DEV
d = os.path.join(DEV, "demo"); os.makedirs(d)
json.dump({"name": "Demo", "tabs": [{"kind": "demo", "label": "Demo tab", "short": "Demo", "module": "demo_tab", "factory": "make", "args": ["host", "path"],
                                      "project_folder": {"marker": "marker.txt"}}]}, open(os.path.join(d, "addon.json"), "w"))
open(os.path.join(d, "demo_tab.py"), "w").write("from PyQt6.QtWidgets import QLabel\ndef make(host, path):\n    w = QLabel('x'); w.path = path; return w\n")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPoint, QPointF, QEvent
from PyQt6.QtGui import QDropEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
ASK = []
QMessageBox.question = staticmethod(lambda *a, **k: (ASK.append(a[2]), QMessageBox.StandardButton.Yes)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: ASK.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: ASK.append(a[2]))
import addons, ext
addons.startup(); addons.register_extensions(ext)
import gpd_app, pm_model as pm, recent, start_page
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()

# ---- 1. the start page is what an empty window shows, and it offers every way to start
assert shell.stack.currentWidget() is shell.start and isinstance(shell.start, start_page.StartPage)
texts = [b.text() for b in shell.start.buttons]
assert texts[:4] == ["New Part", "New Assembly", "Open...", "Open Project Folder..."], texts
assert "New Demo tab" in texts[4:] and not shell.start.addon_head.isHidden(), "a document of an installed add-on is offered too, under its own heading"
assert shell.start.lst.isHidden() and not shell.start.empty.isHidden(), "nothing opened yet: the note, not an empty list"
assert "add-on" in shell.start.addon_lbl.text()

# ---- 2. a part that is opened or saved goes to the top of the recent list; the start page and File > Open Recent show it
work = tempfile.mkdtemp(prefix="opara_work_")
p1 = os.path.join(work, "one.gpd"); open(p1, "w", encoding="utf-8").write(pm.Document().to_json())
p2 = os.path.join(work, "two.gpd"); open(p2, "w", encoding="utf-8").write(pm.Document().to_json())
shell.open_path(p1); shell.open_path(p2)
its = recent.items()
assert [i["name"] for i in its] == ["two.gpd", "one.gpd"] and its[0]["kind"] == "Part", its
assert recent.last_folder() == work, "the next file window starts where the last file was"
seen = {}
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (seen.setdefault("open", a[2]), ([], ""))[1])
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (seen.setdefault("dir", a[2]), "")[1])
shell.open_dialog(); shell.open_project_folder_dialog()
assert seen == {"open": work, "dir": work}, seen
# a new part is listed once it has a file
w = shell.new_part(); assert len(recent.items()) == 2
p3 = os.path.join(work, "three.gpd"); w.path = p3; open(p3, "w", encoding="utf-8").write(w.doc.to_json())
shell.refresh_titles()
assert recent.items()[0]["name"] == "three.gpd" and shell.tabs.tabToolTip(shell.tabs.indexOf(w)) == p3
# a project folder of an add-on
proj = os.path.join(work, "job.demo"); os.makedirs(proj); open(os.path.join(proj, "marker.txt"), "w").write("{}")
shell.open_project_folder(proj)
assert recent.items()[0]["name"] == "job.demo" and recent.items()[0]["kind"] == "Demo tab project", recent.items()[0]
assert recent.last_folder() == work, "a project folder: the next window starts NEXT to it, not inside it"
shell.fill_recent_menu()
acts = [a.text() for a in shell.recent_menu.actions() if a.text()]
assert acts[0] == "&1  job.demo   (Demo tab project)" and "Clear the list" in acts[-1] and len(acts) == 5, acts

# ---- 3. the tab strip: right-click menu, middle click, close the others
i = shell.tabs.indexOf(w)
names = [a[0] for a in shell.tab_actions(i) if a]
assert names == ["Close", "Close the other tabs", "Close all tabs", "Save", "Copy the path", "Show in folder"], names
dict(a for a in shell.tab_actions(i) if a)["Copy the path"]()
assert QApplication.clipboard().text() == p3
n = shell.tabs.count()
bar = shell.tabs.tabBar(); c = bar.tabRect(0).center()
app.sendEvent(bar, QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(c), QPointF(bar.mapToGlobal(c)), Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
assert shell.tabs.count() == n - 1, "a middle click closes the tab"
assert shell.close_tabs(keep=w) and shell.tabs.count() == 1 and shell.tabs.widget(0) is w
assert shell.close_tabs() and shell.tabs.count() == 0 and shell.stack.currentWidget() is shell.start

# ---- 4. the start page lists them; a click opens; a file that is gone stays, greyed, and can be removed
shell.start.refresh()
lst = shell.start.lst
assert not lst.isHidden() and lst.count() == 4 and lst.item(0).text().startswith("job.demo\n"), lst.item(0).text()
os.remove(p1)
shell.start.fill_recent()
gone = [lst.item(k) for k in range(lst.count()) if lst.item(k).text().startswith("one.gpd")][0]
assert "(not found)" in gone.text()
ASK.clear(); shell.start.open_item(gone)
assert ASK and "not there right now" in ASK[0] and all(i["name"] != "one.gpd" for i in recent.items()), "asked, then removed from the list"
two = [lst.item(k) for k in range(lst.count()) if lst.item(k).text().startswith("two.gpd")][0]
shell.start.open_item(two)
assert shell.tabs.count() == 1 and recent.items()[0]["name"] == "two.gpd", "opened again: back on top"

# ---- 5. a file dropped on the window is opened
md = QMimeData(); md.setUrls([QUrl.fromLocalFile(p3)])
ev = QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
shell.dropEvent(ev); app.processEvents(); app.processEvents()
assert shell.tabs.count() == 2 and shell.cur().path == p3

# ---- 6. the window size is remembered
shell.close_tabs()
shell.resize(1111, 707); shell.save_window()
s2 = gpd_app.AppShell()
assert (s2.width(), s2.height()) == (1111, 707), (s2.width(), s2.height())
json.dump({"w": 5, "h": "x"}, open(os.path.join(UD, "window.json"), "w"))          # a broken file is ignored
assert gpd_app.AppShell().width() == 1400

# ---- 7. an error is logged, and shown as text that can be copied, with the program version on top
gpd_app.log_error("Traceback: demo error 12345")
dlg = gpd_app.ErrorDialog(shell)                                                 # Help > Show the error log
assert "demo error 12345" in dlg.text and dlg.text.startswith(gpd_app.channel.app_name()) and dlg.b_copy.isEnabled()
dlg.copy(); assert "demo error 12345" in QApplication.clipboard().text() and "Copied" in dlg.note.text()
shown = []
gpd_app.show_error_text = lambda parent, text, title="Error", head=None: shown.append((text, head))
gpd_app.install_excepthook()
try:
    raise ValueError("boom 777")
except ValueError:
    sys.excepthook(*sys.exc_info())
assert shown and "boom 777" in shown[0][0] and "Copy" in shown[0][1] and "boom 777" in gpd_app.error_log_tail()
shell.show_error_log(); assert shown[-1][0] is None
# ---- 8. the window follows the tab on screen: title bar, greyed-out menu entries, the Window menu, Save All, reopen a closed tab
s3 = gpd_app.AppShell()
A = s3.acts
assert s3.windowTitle() == gpd_app.channel.title()
off = [k for k in ("save", "save_as", "save_all", "export", "close", "close_all", "next", "prev", "reopen", "undo", "redo", "rebuild", "zoom_fit") if A[k].isEnabled()]
assert off == [], f"with no document these do nothing, so they are greyed out: {off}"
a = s3.new_part(); b = s3.new_part()
assert s3.windowTitle().startswith("Part") or " - " in s3.windowTitle(), s3.windowTitle()
assert s3.windowTitle() == f"{s3.tabs.tabText(s3.tabs.currentIndex())} - {gpd_app.channel.title()}", s3.windowTitle()
assert all(A[k].isEnabled() for k in ("save", "save_as", "save_all", "export", "close", "close_all", "next", "prev", "undo", "redo", "rebuild"))
assert not A["reopen"].isEnabled()
demo = s3.new_addon_tab("demo")                                  # a tab that cannot undo or save
assert not A["undo"].isEnabled() and not A["save"].isEnabled() and A["save_all"].isEnabled() and A["close"].isEnabled()
s3.step_tab(1); assert s3.cur() is a
s3.step_tab(-1); assert s3.cur() is demo
A["next"].trigger(); assert s3.cur() is a and A["undo"].isEnabled()
s3.fill_window_menu()
wl = [x for x in s3.window_menu.actions() if x.isCheckable()]
assert len(wl) == 3 and [x.isChecked() for x in wl] == [True, False, False] and wl[1].text().startswith("&2  "), [x.text() for x in wl]
wl[2].trigger(); assert s3.cur() is demo
s3.fill_window_menu(); assert len([x for x in s3.window_menu.actions() if x.isCheckable()]) == 3, "filled again: not doubled"
# Save All: only what has changes; a document without a file asks for its name
pa, pb = os.path.join(work, "sa.gpd"), os.path.join(work, "sb.gpd")
a.path = pa; a.saved_json = None; b.saved_json = None
assert s3.tab_dirty(a) and s3.tab_dirty(b)
QFileDialog.getSaveFileName = staticmethod(lambda *x, **k: (pb, ""))
assert s3.save_all() == 2 and os.path.isfile(pa) and os.path.isfile(pb) and not s3.tab_dirty(a) and not s3.tab_dirty(b)
assert s3.save_all() == 0 and "Nothing to save" in s3.statusBar().currentMessage()
# reopen a closed tab
s3.close_tab(s3.tabs.indexOf(a))
assert A["reopen"].isEnabled() and s3.find_tab(pa) is None
r = s3.reopen_closed()
assert r is not None and r.path == pa and s3.cur() is r and not A["reopen"].isEnabled()
assert s3.reopen_closed() is None

# ---- 9. exit: one question for several unsaved documents (Save All / Discard / Cancel)
a2 = s3.tabs.widget(s3.find_tab(pa)); b2 = s3.tabs.widget(s3.find_tab(pb))
a2.saved_json = None; b2.saved_json = None
Q = []
def answer(r):
    QMessageBox.question = staticmethod(lambda *x, **k: (Q.append((x[2], x[3] if len(x) > 3 else None)), r)[1])
answer(QMessageBox.StandardButton.Cancel)
assert s3.confirm_exit() is False and len(Q) == 1 and "2 documents have unsaved changes" in Q[0][0] and "sa.gpd" in Q[0][0] and "sb.gpd" in Q[0][0]
assert Q[0][1] == QMessageBox.StandardButton.SaveAll | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
answer(QMessageBox.StandardButton.Discard)
assert s3.confirm_exit() is True and s3.tab_dirty(a2), "discard: nothing is written"
answer(QMessageBox.StandardButton.SaveAll)
assert s3.confirm_exit() is True and not s3.tab_dirty(a2) and not s3.tab_dirty(b2)
Q.clear(); assert s3.confirm_exit() is True and Q == [], "nothing unsaved: no question"
b2.saved_json = None; answer(QMessageBox.StandardButton.Cancel)
assert s3.confirm_exit() is False and "Save changes to" in Q[-1][0], "a single unsaved document gets the usual question"
print("OK shell start page")
import shutil; shutil.rmtree(UD, ignore_errors=True); shutil.rmtree(DEV, ignore_errors=True)
os._exit(0)
