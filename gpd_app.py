"""
gpd_app.py - the program window: File / Edit / View menus and one tab per open document (parts and assemblies).

Run:  python gpd_app.py [file.gpd | file.gpa ...]
"""
import os
import sys
import contextlib

import channel

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QStackedWidget,
                             QTabWidget, QVBoxLayout, QWidget)

SPLASH = None
APP = None               # kept alive here: if the QApplication were dropped, Qt would delete the card with it


def _step(text, frac):
    if SPLASH is not None:
        SPLASH.step(text, frac)


def _early():
    """Started as the program: make the window system and the start-up card FIRST, so the card is on the screen while the slow imports
    below (geometry kernel, 3D view) run.  Importing this module from a test or another script does none of this."""
    global SPLASH, APP
    if sys.platform == "win32":                      # own taskbar icon / grouping instead of python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenPara.Playground" if channel.is_playground() else "OpenPara.CAD")
        except Exception:
            pass
    app = APP = QApplication.instance() or QApplication(sys.argv)
    try:
        import splash
        SPLASH = splash.show(app)
    except Exception:
        import traceback
        print("splash: not available:\n" + traceback.format_exc(), file=sys.stderr)
        SPLASH = None


if __name__ == "__main__":
    _early()

_step("Loading add-ons...", 0.08)
import addons
addons.startup()          # puts the shipped add-ons in place (or upgrades them) and makes the installed ones importable
import ext
addons.register_extensions(ext)          # the Part window and the Assembly window learn which add-ons are there

_step("Loading geometry kernel...", 0.2)
import pm_app
_step("Loading settings and units...", 0.8)
import settings
import unitctl
import pm_model as pm


class AppShell(QMainWindow):
    _project_hint_busy = False                       # True while "install the add-on, then open the folder" runs, so it is asked only once
    def __init__(self, files=None):
        super().__init__()
        self.tab_counts = {}
        self.setWindowTitle(channel.title())
        self.resize(1400, 860)
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        from PyQt6.QtCore import QSize
        self.tabs.setIconSize(QSize(16, 16))
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        import start_page
        self.acts = {}                                # the menu entries that are greyed out when they do not apply (see update_window)
        self.closed = []                              # paths of the tabs closed in this session, newest last (Window > Reopen closed tab)
        self._recent_seen = set()                     # paths noted in the recent list during this session (see note_recent)
        self.blank = self.start = start_page.StartPage(self)          # shown while no document is open: ways to start, recent files
        self.stack = QStackedWidget()
        self.stack.addWidget(self.blank)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)
        self.setAcceptDrops(True)                     # a file or a project folder dropped on the window is opened
        bar = self.tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self.tab_menu)
        bar.installEventFilter(self)                  # a middle click on a tab closes it
        self.restore_window()
        self.add_gl_anchor()
        self._busy_depth = 0
        self._busy_veil = None
        import update_ui
        self.updates = update_ui.UpdateController(self)
        ext.installer = lambda aid, parent: self.need_addon(aid, "This")
        self.build_menus()
        import autosave
        self.autosave = autosave.AutoSave(self)           # the AutoSave switch at the top
        unitctl.on_change(self.units_changed)
        settings.on_change(self.settings_changed)
        opened = False
        for f in files or []:
            if os.path.exists(f):
                self.open_path(f)
                opened = True
        self.show_stack()
        self.timer = QTimer(self)                     # a star after the tab name while a document has unsaved changes
        self.timer.timeout.connect(self.refresh_titles)
        self.timer.start(1500)

    def add_gl_anchor(self):
        """The first 3D tab used to make the whole window close and open again: Qt re-creates a window that is already on screen the first time
        a GPU-drawn widget is added to it.  A tiny GPU widget (kept outside the visible area) is added BEFORE the window is first shown, so the
        window is made the right way from the start and the first tab just opens in it."""
        self.gl_anchor = None
        try:
            from PyQt6.QtOpenGLWidgets import QOpenGLWidget
            a = QOpenGLWidget(self)
            a.setFixedSize(2, 2)
            a.move(-4, -4)                                         # outside the window: never seen, but part of it
            a.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.gl_anchor = a
        except Exception:
            pass

    @contextlib.contextmanager
    def busy(self, text):
        """A small card over a dimmed window while something slow is built ("Opening a new part...").  Nested uses show one card."""
        self._busy_depth += 1
        first = self._busy_depth == 1
        if first:
            self.show_busy(text)
        try:
            yield
        finally:
            self._busy_depth -= 1
            if first:
                self.hide_busy()

    def show_busy(self, text):
        try:
            veil = QWidget(self)
            veil.setStyleSheet("background: rgba(0, 0, 0, 90);")
            veil.setGeometry(self.rect())
            lay = QVBoxLayout(veil)
            lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card = QLabel(text + "\n\nJust a second...")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setStyleSheet("background: #2b2f36; color: #f0f0f0; border: 1px solid #5a6270; border-radius: 8px; padding: 22px 34px; font-size: 14px;")
            lay.addWidget(card)
            veil.show()
            veil.raise_()
            self._busy_veil = veil
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()                        # paint the card before the slow work starts
        except Exception:
            self._busy_veil = None

    def hide_busy(self):
        v, self._busy_veil = self._busy_veil, None
        if v is not None:
            QApplication.restoreOverrideCursor()
            v.hide()
            v.deleteLater()

    def show_stack(self):
        self.stack.setCurrentWidget(self.tabs if self.tabs.count() else self.blank)

    # ------------------------------------------------------------------ the window itself: size, drops, the tab strip
    WINDOW_FILE = "window.json"

    def restore_window(self):
        """The size and place the window had when it was last closed (only when it still fits a screen that is connected)."""
        import json
        import paths
        try:
            with open(os.path.join(paths.user_dir(), self.WINDOW_FILE), encoding="utf-8") as f:
                d = json.load(f)
            w, h, x, y = int(d["w"]), int(d["h"]), int(d["x"]), int(d["y"])
        except (OSError, ValueError, KeyError, TypeError):
            return
        if not (400 <= w <= 20000 and 300 <= h <= 20000):
            return
        self.resize(w, h)
        from PyQt6.QtCore import QRect
        frame = QRect(x, y, w, h)
        if any(s.availableGeometry().intersected(frame).width() > 200 and s.availableGeometry().intersected(frame).height() > 150
               for s in QApplication.screens()):
            self.move(x, y)
        if d.get("max"):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def save_window(self):
        import json
        import paths
        try:
            g = self.normalGeometry() if self.isMaximized() else self.geometry()
            with open(os.path.join(paths.user_dir(), self.WINDOW_FILE), "w", encoding="utf-8") as f:
                json.dump({"w": g.width(), "h": g.height(), "x": g.x(), "y": g.y(), "max": bool(self.isMaximized())}, f)
        except OSError:
            pass

    @staticmethod
    def dropped_paths(mime):
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()] if mime.hasUrls() else []

    def dragEnterEvent(self, ev):
        if self.dropped_paths(ev.mimeData()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths_ = self.dropped_paths(ev.mimeData())
        if paths_:
            ev.acceptProposedAction()
            QTimer.singleShot(0, lambda: [self.open_path(p) for p in paths_ if os.path.exists(p)])     # after the drop is over (a question may be asked)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.tabs.tabBar() and ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.MiddleButton:
            i = obj.tabAt(ev.position().toPoint())
            if i >= 0:
                self.close_tab(i)
                return True
        return super().eventFilter(obj, ev)

    def tab_actions(self, i):
        """[(text, fn)] of the right-click menu of tab i (None = a separator)."""
        w = self.tabs.widget(i)
        if w is None:
            return []
        out = [("Close", lambda: self.close_tab(self.tabs.indexOf(w))),
               ("Close the other tabs", lambda: self.close_tabs(keep=w)),
               ("Close all tabs", lambda: self.close_tabs())]
        if self.saveable(w):
            out += [None, ("Save", lambda: self.save_widget(w))]
        p = getattr(w, "path", None)
        if isinstance(p, str) and p:
            import start_page
            out += [None, ("Copy the path", lambda: QApplication.clipboard().setText(os.path.abspath(p))),
                    ("Show in folder", lambda: start_page.show_in_folder(p))]
        return out

    def tab_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        bar = self.tabs.tabBar()
        i = bar.tabAt(pos)
        if i < 0:
            return
        m = QMenu(self)
        for it in self.tab_actions(i):
            if it is None:
                m.addSeparator()
            else:
                m.addAction(it[0], it[1])
        m.exec(bar.mapToGlobal(pos))

    def close_tabs(self, keep=None):
        """Closes every tab (but `keep`), asking about unsaved changes; stops at the first Cancel.  True when all were closed."""
        for w in [self.tabs.widget(i) for i in range(self.tabs.count())]:
            i = self.tabs.indexOf(w)
            if w is keep or i < 0:                     # (a tab that belonged to another one is already gone)
                continue
            if keep is not None and keep in self.dependents(w):
                continue                                  # the tab that is kept needs this one
            if not self.close_tab(i):
                return False
        return True

    # ------------------------------------------------------------------ menus
    def build_menus(self):
        mb = self.menuBar()
        mb.clear()

        def add(menu, text, fn, key=None):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _c=False, f=fn: f())
            menu.addAction(a)
            return a
        fm = mb.addMenu("&File")
        add(fm, "New Part", lambda: self.new_part(), "Ctrl+N")
        add(fm, "New Assembly", self.new_assembly, "Ctrl+Shift+N")
        kinds = addons.tab_kinds()
        for kind, spec in kinds.items():
            add(fm, "New " + spec.get("label", kind), lambda k=kind: self.new_addon_tab(k))
        self.addon_commands(fm, "file.new", add)                                     # what add-ons put with the New entries
        fm.addSeparator()
        add(fm, "Open...", self.open_dialog, "Ctrl+O")
        add(fm, "Open Project Folder...", self.open_project_folder_dialog)          # always there: it offers the add-on that opens the folder
        self.recent_menu = fm.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        self.acts["save"] = add(fm, "Save", lambda: self.cur_call("save"), "Ctrl+S")
        self.acts["save_as"] = add(fm, "Save As...", lambda: self.cur_call("save", True), "Ctrl+Shift+S")
        self.acts["save_all"] = add(fm, "Save All", self.save_all, "Ctrl+Alt+S")
        fm.addSeparator()
        add(fm, "Import STEP...", self.import_step)
        self.acts["export"] = add(fm, "Export (STEP, STL)...", self.export_file)
        self.addon_commands(fm, "file", add)
        fm.addSeparator()
        add(fm, "Add-ons...", self.addons_dialog)
        add(fm, "Units...", self.units_dialog)
        add(fm, "Settings...", self.settings_dialog)
        fm.addSeparator()
        self.acts["close"] = add(fm, "Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        add(fm, "Exit", self.close)
        self.add_acts = {}
        if ext.present("simulation") or ext.present("render") or ext.commands("add"):          # only when an add-on has something to add
            am = mb.addMenu("&Add")
            if ext.present("render"):
                add(am, "Visualize: Preview / Render (lit view, pictures and videos)", lambda: self.add_render())
                am.addSeparator()
            if ext.present("simulation"):
                for kind, text in (("beam", "1D FEA (frames and trusses) - of a part"), ("fea", "2D FEA"), ("cfd", "2D CFD")):
                    self.add_acts[kind] = add(am, text, lambda k=kind: self.add_sim(k))
            if ext.commands("add") and am.actions():
                am.addSeparator()
            self.addon_commands(am, "add", add)
        em = mb.addMenu("&Edit")
        self.acts["undo"] = add(em, "Undo", lambda: self.cur_call("do_undo"), "Ctrl+Z")
        self.acts["redo"] = add(em, "Redo", lambda: self.cur_call("do_redo"), "Ctrl+Y")
        self.acts["rebuild"] = add(em, "Rebuild", self.rebuild, "Ctrl+B")
        vm = mb.addMenu("&View")
        self.acts["zoom_fit"] = add(vm, "Zoom to Fit", self.zoom_fit, "F")
        self.flip_act = QAction("Zoom: wheel toward you = in", self)
        self.flip_act.setCheckable(True)
        self.flip_act.setChecked(True)
        self.flip_act.toggled.connect(self.flip_changed)
        vm.addAction(self.flip_act)
        self.addon_commands(vm, "view", add)
        wm = self.window_menu = mb.addMenu("&Window")
        self.acts["next"] = add(wm, "Next tab", lambda: self.step_tab(1), "Ctrl+Tab")
        self.acts["prev"] = add(wm, "Previous tab", lambda: self.step_tab(-1), "Ctrl+Shift+Tab")
        self.acts["reopen"] = add(wm, "Reopen closed tab", self.reopen_closed, "Ctrl+Shift+T")
        self.acts["close_all"] = add(wm, "Close all tabs", lambda: self.close_tabs())
        self.window_sep = wm.addSeparator()               # below it: the open tabs, filled when the menu opens
        wm.aboutToShow.connect(self.fill_window_menu)
        hm = mb.addMenu("&Help")
        add(hm, "Check for updates...", lambda: self.updates.check_now())
        self.auto_upd = QAction("Check for updates at start-up", self)
        self.auto_upd.setCheckable(True)
        self.auto_upd.setChecked(self.updates.auto_enabled())
        self.auto_upd.toggled.connect(lambda on: self.updates.set_auto(on))
        hm.addAction(self.auto_upd)
        add(hm, "Open the data folder", self.open_data_folder)
        add(hm, "Show the error log...", self.show_error_log)
        self.addon_commands(hm, "help", add)
        if channel.is_playground():
            hm.addSeparator()
            grp = QActionGroup(self)
            for m, label in (("testing", "Playground mode: Testing (exactly the next release)"), ("full", "Playground mode: Full dev (all experimental add-ons)")):
                a = QAction(label, self)
                a.setCheckable(True)
                a.setChecked(channel.mode() == m)
                a.setActionGroup(grp)
                a.triggered.connect(lambda _c=False, m=m: self.set_playground_mode(m))
                hm.addAction(a)
        hm.addSeparator()
        add(hm, "About " + channel.app_name(), lambda: self.updates.about())
        self.update_window()

    # ------------------------------------------------------------------ the window follows the tab on screen
    def update_window(self):
        """The title bar names the document on screen, and the menu entries that cannot do anything right now are greyed out.  (Undo and Redo
        only look at whether the tab can undo at all: greying them by the undo history could swallow a Ctrl+Z pressed right after an edit.)"""
        w = self.cur() if self.tabs.count() else None
        i = self.tabs.currentIndex()
        title = channel.title()
        if w is not None and i >= 0:
            title = f"{self.tabs.tabText(i)} - {title}"
        if self.windowTitle() != title:
            self.setWindowTitle(title)
        n = self.tabs.count()
        can = {"save": callable(getattr(w, "save", None)), "save_as": callable(getattr(w, "save", None)), "save_all": any(self.saveable(self.tabs.widget(k)) for k in range(n)),
               "export": w is not None, "close": n > 0, "close_all": n > 0, "next": n > 1, "prev": n > 1, "reopen": bool(self.closed),
               "undo": callable(getattr(w, "do_undo", None)), "redo": callable(getattr(w, "do_redo", None)),
               "rebuild": w is not None and (hasattr(w, "refresh_parts") or hasattr(w, "update_all")),
               "zoom_fit": w is not None and getattr(w, "plotter", None) is not None}
        for name, a in self.acts.items():
            try:
                if name in can and a.isEnabled() != bool(can[name]):
                    a.setEnabled(bool(can[name]))
            except RuntimeError:
                pass                                      # (an entry of a menu that was rebuilt)

    def step_tab(self, d):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def reopen_closed(self):
        """Opens the file / project folder of the tab that was closed last (and is not open again already)."""
        while self.closed:
            p = self.closed.pop()
            if os.path.exists(p) and self.find_tab(p) is None:
                w = self.open_path(p)
                self.update_window()
                return w
        self.update_window()
        return None

    def fill_window_menu(self):
        """The open tabs under the separator of the Window menu: a click shows one; the one on screen is ticked."""
        m = self.window_menu
        acts = m.actions()
        for a in acts[acts.index(self.window_sep) + 1:]:
            m.removeAction(a)
        for i in range(self.tabs.count()):
            t = self.tabs.tabText(i).replace("&", "&&")
            a = m.addAction((f"&{i + 1}  " if i < 9 else "") + t)
            a.setCheckable(True)
            a.setChecked(i == self.tabs.currentIndex())
            w = self.tabs.widget(i)
            a.triggered.connect(lambda _c=False, w=w: self.tabs.setCurrentWidget(w))
        self.window_sep.setVisible(self.tabs.count() > 0)

    def save_all(self):
        """Saves every document that has unsaved changes (one without a file yet is shown and asks for its name).  Returns how many were saved."""
        done = 0
        for w in [self.tabs.widget(i) for i in range(self.tabs.count())]:
            if not self.saveable(w) or not self.tab_dirty(w):
                continue
            if not getattr(w, "path", None):
                self.tabs.setCurrentWidget(w)             # the name window is about the document that is on screen
            if not self.save_widget(w):
                break                                     # cancelled or failed: stop here, nothing else is touched
            done += 1
        self.refresh_titles()
        self.statusBar().showMessage(f"Saved {done} document{'s' if done != 1 else ''}." if done else "Nothing to save.", 6000)
        return done

    def addon_commands(self, menu, place, add):
        """The commands add-ons registered for this place of the menus (ext.add_command).  A command gets the program window; an error in it is
        shown like any other, it never takes the window down."""
        for c in ext.commands(place):
            a = add(menu, c["text"], lambda c=c: c["fn"](self), c.get("key"))
            if c.get("tip"):
                a.setStatusTip(c["tip"])

    def start_actions(self):
        """What the start page offers: [{"text", "fn", "tip", "group"}] - the program's own ways to start, then (group "addon") the documents
        and commands of the installed add-ons, the same things as the top of the File menu."""
        out = [{"text": "New Part", "fn": lambda: self.new_part(), "tip": "A part: sketches, extrudes, revolves ...  (Ctrl+N)"},
               {"text": "New Assembly", "fn": self.new_assembly, "tip": "Parts put together with mates  (Ctrl+Shift+N)"},
               {"text": "Open...", "fn": self.open_dialog, "tip": "A part, an assembly or a file of an add-on  (Ctrl+O)"},
               {"text": "Open Project Folder...", "fn": self.open_project_folder_dialog, "tip": "A simulation, Visualize, annotator ... project"}]
        for kind, spec in addons.tab_kinds().items():
            out.append({"text": "New " + spec.get("label", kind), "fn": lambda k=kind: self.new_addon_tab(k), "group": "addon",
                        "tip": addons.info(spec["aid"])["name"] + " add-on"})
        for c in ext.commands("file.new"):
            out.append({"text": c["text"], "fn": lambda c=c: c["fn"](self), "tip": c.get("tip"), "group": "addon"})
        return out

    # ------------------------------------------------------------------ recent files
    def tab_kind(self, w):
        """The kind of a tab: "part", "assembly", or the kind its add-on gave it (its manifest "kind", or the tab's own  kind  attribute)."""
        if isinstance(w, pm_app.MainWindow):
            return "part"
        if hasattr(w, "asm"):
            return "assembly"
        k = getattr(w, "kind", None)
        if isinstance(k, str) and k:
            return k
        try:                                              # a tab the add-on opened itself: the kind of its add-on's (first) document
            aid = addons.owner_of_module(type(w).__module__)
            return next((kind for kind, spec in addons.tab_kinds().items() if spec.get("aid") == aid), "")
        except Exception:
            return ""

    def tab_icon(self, w):
        """The small icon of a tab (icon_set): the one its add-on names (the tab's  tab_icon  or the manifest's "icon"), else by kind."""
        try:
            import icon_set
            kind = self.tab_kind(w)
            spec = addons.tab_kinds().get(kind) or {}
            return icon_set.for_tab(kind, getattr(w, "tab_icon", None) or spec.get("icon"))
        except Exception:
            return None

    def kind_label(self, w):
        """What a tab is, in a word or two, for the recent list: Part, Assembly, or the label of the add-on's document (+ "project" for a folder)."""
        if isinstance(w, pm_app.MainWindow):
            return "Part"
        if hasattr(w, "asm"):
            return "Assembly"
        spec = addons.tab_kinds().get(getattr(w, "kind", None))
        if spec is None:                                  # a tab its add-on opened itself (Visualize of a part): the add-on's (first) document
            try:
                aid = addons.owner_of_module(type(w).__module__)
                spec = next((sp for sp in addons.tab_kinds().values() if sp.get("aid") == aid), None)
            except Exception:
                spec = None
        label = spec.get("label", "") if spec else ""
        p = getattr(w, "path", None)
        return (label + " project").strip() if isinstance(p, str) and os.path.isdir(p) else label

    def note_recent(self, w):
        """A tab that has a file or a project folder goes to the top of the recent list the first time it is seen with that path (so a new
        document appears when it is first saved, and a project made by an add-on needs nothing from the add-on)."""
        p = getattr(w, "path", None)
        if not isinstance(p, str) or not p:
            return
        try:
            key = os.path.normcase(os.path.abspath(p))
            if key in self._recent_seen or not os.path.exists(p):
                return
            import recent
            self._recent_seen.add(key)
            recent.add(p, self.kind_label(w))
            recent.set_last_folder(p)
        except Exception:
            pass                                          # never worth an error

    def open_recent(self, path):
        import recent
        if not os.path.exists(path):
            r = QMessageBox.question(self, "Open Recent", f"{path}\n\nis not there right now (moved, renamed, or on a drive that is not connected).\n\n"
                                     "Remove it from the list?")
            if r == QMessageBox.StandardButton.Yes:
                recent.remove(path)
            return None
        w = self.open_path(path)
        if w is not None:
            self._recent_seen.discard(os.path.normcase(os.path.abspath(path)))          # opened again: back to the top of the list
            self.note_recent(w)
        return w

    def fill_recent_menu(self):
        import recent
        m = self.recent_menu
        m.clear()
        its = recent.items()
        for k, it in enumerate(its):
            a = m.addAction((f"&{k + 1}  " if k < 9 else "") + it["name"].replace("&", "&&") + (f"   ({it['kind']})" if it["kind"] else "")
                            + ("   - not found" if it["missing"] else ""))
            a.setToolTip(it["path"])
            a.setStatusTip(it["path"])
            a.triggered.connect(lambda _c=False, p=it["path"]: self.open_recent(p))
        if not its:
            a = m.addAction("Nothing opened yet")
            a.setEnabled(False)
        else:
            m.addSeparator()
            m.addAction("Clear the list", lambda: (recent.clear(), self.start.fill_recent()))

    def show_error_log(self):
        show_error_text(self, None)

    def report_addon_errors(self):
        """After the start: say once which add-ons could not be loaded (they are off for this session; everything else works)."""
        errs = addons.load_errors()
        if errs:
            names = ", ".join(addons.info(a)["name"] for a in errs)
            show_error_text(self, "\n\n".join(f"=== {addons.info(a)['name']} ({a}) ===\n{t}" for a, t in errs.items()), title="Add-ons",
                            head=f"These add-ons could not be loaded and are switched off for now: {names}.\nEverything else works. "
                                 "Updating or reinstalling them in File > Add-ons usually fixes it.")

    def settings_dialog(self):
        import settings_dialog
        settings_dialog.SettingsDialog(self).exec()

    def settings_changed(self, keys):
        """File > Settings was applied: every open document redraws with the new values."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "settings_changed"):
                try:
                    w.settings_changed(keys)
                except Exception:
                    import traceback
                    traceback.print_exc()

    def units_dialog(self):
        import units_dialog
        d = units_dialog.UnitsDialog(self)
        if d.exec():
            sysname, speed = d.choice()
            unitctl.set_units(sysname, speed)              # tells units_changed() below

    def units_changed(self, old_s, new_s, old_v, new_v):
        """The program's units were changed: every open document shows / converts to the new ones."""
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "units_changed"):
                try:
                    w.units_changed(old_s, new_s, old_v, new_v)
                except Exception:
                    import traceback
                    traceback.print_exc()
        self.statusBar().showMessage(f"Units: {new_s}   speed: {new_v}", 8000)

    def open_data_folder(self):
        import paths
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(paths.user_dir()))

    def cur(self):
        return self.tabs.currentWidget()

    def cur_call(self, name, *args):
        w = self.cur()
        if w is not None and hasattr(w, name):
            return getattr(w, name)(*args)

    def rebuild(self):
        w = self.cur()
        if w is None:
            return
        if hasattr(w, "refresh_parts"):
            w.refresh_parts()
        else:
            w.update_all()

    def zoom_fit(self):
        w = self.cur()
        if w is not None and w.plotter is not None:
            w.plotter.reset_camera()
            w.plotter.render()

    def flip_changed(self, on):
        w = self.cur()
        if w is not None and getattr(w, "nav", None) is not None:
            w.nav.flip_zoom(not on)

    @staticmethod
    def saveable(w):
        """Parts, assemblies and add-on documents that have a file of their own to save."""
        return w is not None and callable(getattr(w, "save", None)) and callable(getattr(w, "is_dirty", None))

    def tab_dirty(self, w):
        try:
            return bool(w.is_dirty())
        except Exception:
            return False

    def save_widget(self, w, as_new=False):
        """Save one tab (asks for a name when it has none).  True when it was saved."""
        try:
            ok = w.save(as_new) if as_new else w.save()
        except Exception as ex:
            QMessageBox.warning(self, "Save", f"Could not save: {ex}")
            return False
        self.refresh_titles()
        return ok is not False

    def has_docs(self):
        return self.tabs.count() > 0

    def tab_changed(self, _i):
        w = self.cur()
        if w is None:
            self.update_window()
            return
        if getattr(w, "nav", None) is not None:
            self.flip_act.blockSignals(True)
            self.flip_act.setChecked(w.nav.wheel_sign == 1)
            self.flip_act.blockSignals(False)
        if hasattr(w, "refresh_parts"):
            w.refresh_parts()                     # parts may have been edited in another tab
        self.refresh_titles()
        self.update_window()

    # ------------------------------------------------------------------ documents
    def add_tab(self, w):
        i = self.tabs.addTab(w, w.title())
        ic = self.tab_icon(w)
        if ic is not None:
            self.tabs.setTabIcon(i, ic)                   # what kind of document the tab is, at a glance
        self.tabs.setCurrentIndex(i)
        self.show_stack()
        self.note_recent(w)
        return w

    def need_addon(self, aid, what):
        """True when the add-on is installed; otherwise offer to install it (downloaded from GitHub)."""
        if addons.is_active(aid):
            return True
        info = addons.info(aid)
        if aid not in addons.known():
            QMessageBox.information(self, "Add-on", f"{what} needs '{aid}', which is not part of this version of OpenPara.")
            return False
        if QMessageBox.question(self, "Add-on needed", f"{what} needs the add-on '{info['name']}'.\n\nDownload and install it now? "
                                "(It is fetched from GitHub, so this needs an internet connection.)") != QMessageBox.StandardButton.Yes:
            return False
        import addons_dialog
        if not addons_dialog.install_with_progress(self, aid):
            return False
        self.addons_changed()
        return True

    def addon_tabs(self, aid):
        """Indexes of the open tabs whose class comes from the add-on."""
        return [i for i in range(self.tabs.count()) if addons.owner_of_module(type(self.tabs.widget(i)).__module__) == aid]

    def close_addon_tabs(self, aid):
        """Close the tabs of an add-on (asks about unsaved changes); False when the user cancelled."""
        for i in reversed(self.addon_tabs(aid)):
            if not self.close_tab(i):
                return False
        return True

    def offer_addon_updates(self):
        """At start: add-ons you installed that are older than this program (it was just updated) are offered an update, with their packages.
        'Not now' is remembered for this version of the program; File > Add-ons > Update still works."""
        if os.environ.get("OPARA_NO_UPDATE") or addons.update_prompt_declined():
            return
        old = addons.outdated()
        if not old:
            return
        names = ", ".join(addons.info(a)["name"] for a in old)
        r = QMessageBox.question(self, "Add-ons need an update",
                                 f"OpenPara was updated. These add-ons are for the previous version: {names}.\n\nUpdate them now? This downloads what they need from "
                                 "GitHub (an add-on with AI support can be a few hundred MB, so it may take a few minutes) and needs an internet connection. "
                                 "Your own files are not touched.\n\nIf you choose No, they keep working as they are and you can update them later in File > Add-ons.")
        if r != QMessageBox.StandardButton.Yes:
            addons.set_update_prompt_declined()
            return
        import addons_dialog
        for a in old:
            if not addons_dialog.install_with_progress(self, a):
                break
        self.addons_changed()

    def restart_program(self):
        """Closes the window (open documents are asked about first) and starts the program again."""
        import subprocess
        import updater
        lay = updater.installed_layout()
        self.close()
        if not self.isVisible():
            subprocess.Popen(updater.restart_command(), cwd=lay[0] if lay else os.getcwd())
            QApplication.quit()

    def set_playground_mode(self, m):
        if m == channel.mode():
            return
        channel.set_mode(m)
        what = "Testing: exactly what the next release would be" if m == "testing" else "Full dev: everything, including the experimental add-ons"
        r = QMessageBox.question(self, "Playground mode", f"Mode set to {what}.\n\nRestart now to use it? (open documents are asked about first)")
        if r == QMessageBox.StandardButton.Yes:
            self.restart_program()

    def offer_first_run(self):
        """First start of a Playground: offer to bring over the OpenPara settings and to install the add-ons OpenPara offers, so it behaves like OpenPara.
        Asked once; the add-ons can always be installed later in File > Add-ons."""
        import playground
        if os.environ.get("OPARA_NO_UPDATE") or not playground.first_run_pending():
            return
        playground.mark_first_run_done()                      # asked once, whatever the answers
        copied = []
        names = playground.copyable_settings()
        if names:
            r = QMessageBox.question(self, "Welcome to the Playground",
                                     "This is a separate copy of OpenPara for trying the next version, with its own settings.\n\nCopy your settings and material "
                                     f"library from OpenPara so it feels the same? ({len(names)} file(s); OpenPara's own files are not changed.)")
            if r == QMessageBox.StandardButton.Yes:
                copied = playground.copy_settings()
        todo = playground.addons_to_offer()
        installed = False
        if todo:
            lst = ", ".join(addons.info(a)["name"] for a in todo)
            r = QMessageBox.question(self, "Add-ons",
                                     f"OpenPara offers these add-ons: {lst}.\n\nInstall them here too, so the Playground can do the same things? This downloads them "
                                     "from GitHub (the Annotator brings the AI packages and is a few hundred MB, so it may take a few minutes) and needs an internet "
                                     "connection.\n\nIf you choose No, you can install them later in File > Add-ons.")
            if r == QMessageBox.StandardButton.Yes:
                import addons_dialog
                for a in todo:
                    if not addons_dialog.install_with_progress(self, a):
                        break
                    installed = True
                self.addons_changed()
        if copied:
            r = QMessageBox.question(self, "Settings copied", "Restart now so the copied settings are used?")
            if r == QMessageBox.StandardButton.Yes:
                self.restart_program()

    def addons_changed(self):
        """Menus and buttons that depend on an add-on follow it: the core is told again which add-ons are there, the menus are rebuilt."""
        addons.register_extensions(ext)
        self.build_menus()
        self.start.refresh()                              # the start page offers what the installed add-ons offer
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "update_all") and hasattr(w, "refresh_tree"):
                try:
                    w.refresh_tree()
                except Exception:
                    pass

    def addons_dialog(self):
        import addons_dialog
        addons_dialog.AddonsDialog(self).exec()

    def add_sim(self, kind):
        """A 1D FEA / 2D FEA / 2D CFD container for the part or assembly that is on screen."""
        if not self.need_addon("simulation", "A simulation"):
            return None
        import sim_tab
        src = self.cur()
        if isinstance(src, sim_tab.SimWindow):                # from a simulation: another new one, offering the same original when it is open
            p = src.src.get("path")
            i = self.find_tab(p) if p else None
            src = self.tabs.widget(i) if i is not None else None
            if src is None:
                return self.add_tab(sim_tab.SimWindow(kind, shell=self))
        is_asm = src is not None and hasattr(src, "asm")
        is_part = isinstance(src, pm_app.MainWindow)
        if not (is_asm or is_part):
            QMessageBox.information(self, "Add", "Open a part or an assembly first: a simulation works on its sketch or on a slice of it.")
            return None
        if kind == "beam" and is_asm:
            QMessageBox.information(self, "Add", "1D FEA works on a sketch of a part. An assembly can only be used for 2D, through a slice.")
            return None
        return self.add_tab(sim_tab.SimWindow(kind, shell=self, src_tab=src))

    def add_render(self):
        """A Visualize tab for the part or assembly that is on screen (or the model of the Visualize tab that is on screen)."""
        if not self.need_addon("render", "A render"):
            return None
        import render_studio
        src = self.cur()
        if isinstance(src, render_studio.RenderStudio):
            src = src.source_widget()
        is_asm = src is not None and hasattr(src, "asm")
        is_part = isinstance(src, pm_app.MainWindow)
        if not (is_asm or is_part):
            QMessageBox.information(self, "Renderer", "Open a part or an assembly first: a render shows the one that is on screen.")
            return None
        if not getattr(src, "path", None):
            QMessageBox.information(self, "Renderer", "Save the part / assembly first (File > Save): the Visualize project is named after it and gets its own copy.")
            return None
        try:
            w = render_studio.RenderStudio(shell=self, src_widget=src)
        except Exception as ex:
            QMessageBox.warning(self, "Renderer", f"Could not start the renderer window: {ex}")
            return None
        return self.add_tab(w)

    def new_addon_tab(self, kind, path=None, title=None):
        """A document tab of an add-on (File > New <label>, or opening one of its files / project folders).  The add-on's manifest says how:
        module + factory (or class), the arguments to give it (host, path, quiet, threaded), and whether the tab needs w.host."""
        spec = addons.tab_kinds().get(kind)
        if spec is None:
            return None
        import importlib
        ctx = {"host": self, "path": path, "quiet": False, "threaded": True}
        with self.busy("Opening " + (os.path.basename(path.rstrip("/\\")) if path else "a new " + spec.get("short", spec.get("label", kind)))):
            return self._new_addon_tab(spec, kind, path, title, ctx, importlib)

    def _new_addon_tab(self, spec, kind, path, title, ctx, importlib):
        try:
            mod = importlib.import_module(spec["module"])
            if spec.get("factory"):
                w = getattr(mod, spec["factory"])(*[ctx[k] for k in spec.get("args", [])])
            else:
                w = getattr(mod, spec["class"])(*[ctx[k] for k in spec.get("args", [])], **{k: ctx[k] for k in spec.get("kwargs", [])})
            if spec.get("set_host"):
                w.host = self
            w.kind = kind
        except Exception as ex:
            import traceback
            log_error(f"Could not start {spec.get('label', kind)} (add-on {spec.get('aid', '?')}):\n{traceback.format_exc()}")
            QMessageBox.warning(self, "Open", f"Could not start {spec.get('label', kind)}: {ex}\n\nThe details are in Help > Show the error log.")
            return None
        self.tab_counts[kind] = self.tab_counts.get(kind, 0) + 1
        name = title or (os.path.basename(path.rstrip("/\\")) if path else f"{spec.get('short', spec.get('label', kind))} {self.tab_counts[kind]}")
        if not callable(getattr(w, "title", None)):              # an add-on tab need not know how the tab strip names it
            w.title = lambda w=w, name=name: os.path.basename(w.path.rstrip("/\\")) if getattr(w, "path", None) else name
        return self.add_tab(w)

    def open_project_folder_dialog(self):
        import recent
        folder = QFileDialog.getExistingDirectory(self, "Open Project Folder", recent.last_folder())
        if folder:
            self.open_project_folder(folder)

    def open_project_folder(self, folder):
        """Open a project folder in the tab of the add-on that handles it (found from the marker file in it); None, with a message, when none does."""
        import json
        folder = os.path.abspath(folder.rstrip("/\\") or folder)
        for kind, spec in addons.tab_kinds().items():
            pf = spec.get("project_folder")
            mk = os.path.join(folder, (pf or {}).get("marker", "project.json"))
            if not pf or not os.path.isfile(mk):
                continue
            try:
                fmt = json.load(open(mk, encoding="utf-8")).get("format")
            except Exception:
                fmt = None
            if pf.get("format") in (None, fmt):                # a spec without a format is recognised by its marker file alone
                i = self.find_tab(folder)
                if i is not None:
                    self.tabs.setCurrentIndex(i)
                    return self.tabs.widget(i)
                return self.new_addon_tab(kind, folder)
        aid = addons.project_hint(folder)
        if aid and not self._project_hint_busy:
            name = addons.info(aid)["name"]
            r = QMessageBox.question(self, "Open Project Folder",
                                     f"{os.path.basename(folder)} looks like a project of the '{name}' add-on, which is not installed.\n\nInstall it now? This "
                                     "downloads it from GitHub and needs an internet connection.")
            if r == QMessageBox.StandardButton.Yes:
                import addons_dialog
                if addons_dialog.install_with_progress(self, aid):
                    self.addons_changed()
                    self._project_hint_busy = True
                    try:
                        return self.open_project_folder(folder)
                    finally:
                        self._project_hint_busy = False
            return None
        QMessageBox.information(self, "Open Project Folder", f"{os.path.basename(folder)} is not a project that an installed add-on can open.")
        return None

    def new_part(self, demo=False):
        with self.busy("Opening a new part"):
            w = pm_app.MainWindow()
            if not demo:
                w.doc = pm.Document()
                w.update_all(fit=True)
                w.saved_json = w.doc.to_json()
            return self.add_tab(w)

    def new_assembly(self):
        import assembly
        with self.busy("Opening a new assembly"):
            return self.add_tab(assembly.AssemblyWindow(shell=self))

    def import_step(self):
        import exchange_dialog
        exchange_dialog.run_import(self)

    def export_file(self):
        import exchange_dialog
        exchange_dialog.run_export(self, self.tabs.currentWidget())

    def open_filter(self):
        """The file-type filter of File > Open: parts, assemblies, what the active add-ons open themselves, and the files of add-ons the program
        opens through them (.gpr render files; simulation projects are folders, opened with File > Open Project Folder) whenever that add-on is available (installed, or one click away)."""
        extra = sorted({t for sp in addons.tab_kinds().values() for t in sp.get("file_types", [])})
        own = [(ext, label) for ext, (aid, label) in addons.OPENABLE.items() if aid in addons.known() and ext not in extra]
        every = ["*.gpd", "*.gpa"] + ["*" + t for t in extra] + ["*" + e for e, _ in own]
        parts = ["All supported files (" + " ".join(every) + ")", "Part (*.gpd)", "Assembly (*.gpa)"]
        parts += [f"{label} (*{ext})" for ext, label in own]
        return ";;".join(parts)

    def open_dialog(self):
        import recent
        files, _ = QFileDialog.getOpenFileNames(self, "Open", recent.last_folder(), self.open_filter())
        for f in files:
            self.open_path(f)

    def open_sketches(self):
        """The open part tabs that have a sketch, for any add-on that imports one:
        [{"title": tab name, "tab": widget, "doc": the part's JSON text, "sketches": [(feature id, sketch name), ...]}]."""
        out = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            d = getattr(w, "doc", None)
            feats = getattr(d, "features", None)
            if not feats or not callable(getattr(d, "to_json", None)):
                continue
            sk = [(f["id"], f["name"]) for f in feats if f["kind"] == "sketch"]
            if sk:
                t = self.tabs.tabText(i)
                out.append({"title": t[:-2] if t.endswith(" *") else t, "tab": w, "doc": d.to_json(), "sketches": sk})
        return out

    def find_tab(self, path):
        norm = os.path.normcase(os.path.abspath(path))
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if getattr(w, "path", None) and os.path.normcase(os.path.abspath(w.path)) == norm:
                return i
        return None

    def open_path(self, path):
        i = self.find_tab(path)
        if i is not None:
            self.tabs.setCurrentIndex(i)
            return self.tabs.widget(i)
        with self.busy("Opening " + os.path.basename(path)):
            return self._open_path(path)

    def _open_path(self, path):
        spec = next((sp for sp in addons.tab_kinds().values() if path.lower().endswith(tuple(sp.get("file_types", [])) or ("\0",))), None)
        if spec is not None:
            return self.new_addon_tab(next(k for k, v in addons.tab_kinds().items() if v is spec or v == spec), path)
        if os.path.isdir(path):
            return self.open_project_folder(path)
        if path.lower().endswith(".gpa"):
            import assembly
            w = assembly.AssemblyWindow(path, shell=self)
        else:
            w = pm_app.MainWindow(path)
        return self.add_tab(w)

    def open_part(self, path):
        """Edit Component: show the part in its tab (opening it when needed)."""
        return self.open_path(path)

    def part_doc(self, path):
        """The live Document of a part that is open in a tab (so an assembly sees edits at once), else None."""
        i = self.find_tab(path)
        if i is None:
            return None
        w = self.tabs.widget(i)
        return getattr(w, "doc", None) if isinstance(w, pm_app.MainWindow) else None

    def refresh_titles(self):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            try:
                t = w.title() + (" *" if w.is_dirty() else "")
            except Exception:
                t = w.title()
            if self.tabs.tabText(i) != t:
                self.tabs.setTabText(i, t)
            p = getattr(w, "path", None)
            if isinstance(p, str) and p:                  # hovering a tab says what it is and where its file is
                tip = (self.kind_label(w) + "\n" if self.kind_label(w) else "") + p
                if self.tabs.tabToolTip(i) != tip:
                    self.tabs.setTabToolTip(i, tip)
            self.note_recent(w)                           # a document saved under a (new) name, a project folder just made
        self.update_window()

    def close_tab(self, i):
        w = self.tabs.widget(i)
        if w is None:
            return False
        for d in self.dependents(w):                     # e.g. the parametric study of a simulation: it cannot live without its simulation tab
            if not self.close_tab(self.tabs.indexOf(d)):
                return False
        i = self.tabs.indexOf(w)
        if not self.confirm_close(w):
            return False
        p = getattr(w, "path", None)
        if isinstance(p, str) and p and os.path.exists(p):
            self.closed.append(p)                         # Window > Reopen closed tab
            del self.closed[:-20]
        self.tabs.removeTab(i)
        if hasattr(w, "shutdown"):
            try:
                w.shutdown()
            except Exception:
                pass
        w.deleteLater()
        self.show_stack()
        self.update_window()
        return True

    def confirm_exit(self):
        """Before the program closes: tabs with work running are asked first; then ONE question for all the documents with unsaved changes
        (Save All / Discard / Cancel) instead of one question per document.  A single unsaved document gets the usual question."""
        tabs = [self.tabs.widget(i) for i in range(self.tabs.count())]
        for w in tabs:
            ask = getattr(w, "can_close", None)
            if callable(ask) and not ask():
                return False
        dirty = [w for w in tabs if self.tab_dirty(w)]
        if len(dirty) == 1:
            return self.confirm_close(dirty[0], asked=True)
        if len(dirty) > 1:
            names = "\n".join("   " + w.title() for w in dirty[:12]) + (f"\n   ... and {len(dirty) - 12} more" if len(dirty) > 12 else "")
            r = QMessageBox.question(self, "Exit", f"{len(dirty)} documents have unsaved changes:\n\n{names}\n\nSave them before closing?",
                                     QMessageBox.StandardButton.SaveAll | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.SaveAll:
                for w in dirty:
                    if not getattr(w, "path", None):
                        self.tabs.setCurrentWidget(w)
                    if not self.save_widget(w):
                        return False                      # a save that was cancelled or failed keeps the program open
        return True

    def is_open(self, w):
        """True when `w` is one of the open tabs.  Safe for a tab that was closed (Qt deletes it; touching a deleted tab raises): add-ons use
        this before they reuse a tab they remembered."""
        try:
            return w is not None and self.tabs.indexOf(w) >= 0
        except RuntimeError:
            return False

    def dependents(self, w):
        """The open tabs that say they belong to tab `w` (a tab of an add-on may offer  depends_on() -> the tab it cannot live without)."""
        out = []
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            fn = getattr(t, "depends_on", None)
            try:
                if t is not w and callable(fn) and fn() is w:
                    out.append(t)
            except Exception:
                pass
        return out

    def confirm_close(self, w, asked=False):
        ask = getattr(w, "can_close", None)               # a tab with work running in the background asks for itself
        if not asked and callable(ask) and not ask():
            return False
        try:
            dirty = w.is_dirty()
        except Exception:
            dirty = False
        if not dirty:
            return True
        r = QMessageBox.question(self, "Close", f"Save changes to {w.title()}?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return bool(w.save())
        return True

    def closeEvent(self, ev):
        if not self.confirm_exit():
            ev.ignore()
            return
        for i in range(self.tabs.count()):
            if hasattr(self.tabs.widget(i), "shutdown"):
                try:
                    self.tabs.widget(i).shutdown()
                except Exception:
                    pass
        for i in range(self.tabs.count()):
            self.tabs.widget(i).saved_json = getattr(self.tabs.widget(i), "saved_json", None)
        unitctl.off_change(self.units_changed)
        self.save_window()
        ev.accept()


ERROR_LOG = "gpd_error.log"


def log_error(text):
    """Appends an error text to gpd_error.log in the data folder (Help > Show the error log)."""
    import datetime
    try:
        import paths
        with open(os.path.join(paths.user_dir(), ERROR_LOG), "a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
    except OSError:
        pass


def error_log_tail(max_chars=60000):
    """The newest part of gpd_error.log ("" when there is none)."""
    try:
        import paths
        with open(os.path.join(paths.user_dir(), ERROR_LOG), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    if len(text) > max_chars:
        text = text[-max_chars:]
        text = "(older entries left out)\n" + text[text.find("\n--- ") + 1:] if "\n--- " in text else text
    return text


def program_info():
    """One line that says which program this is (it goes on top of a copied error, so a report always carries the version)."""
    try:
        import platform
        import version
        on = [a for a in addons.known() if addons.is_active(a)]
        return (f"{channel.app_name()} {version.__version__}" + (f" ({channel.mode()} mode)" if channel.is_playground() else "")
                + f" - Python {platform.python_version()} on {platform.system()} {platform.release()} - add-ons: {', '.join(on) or 'none'}")
    except Exception:
        return channel.app_name()


class ErrorDialog(QDialog):
    """An error (or the error log) as text that can be read, selected and copied in one click, with the program version on top."""
    def __init__(self, parent=None, text=None, title="Error", head=None):
        super().__init__(parent)
        self.setWindowTitle(title if text is not None else "Error log")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        if text is None:
            text = error_log_tail()
            head = head or ("Errors the program caught, newest at the bottom (gpd_error.log in the data folder)." if text
                            else "No errors have been logged.")
        self.head = QLabel(head or "")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.text = program_info() + "\n\n" + text if text else ""
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 11px;")
        self.view.setPlainText(self.text)
        self.view.moveCursor(self.view.textCursor().MoveOperation.End)
        self.view.setVisible(bool(self.text))
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.b_copy = QPushButton("Copy")
        self.b_copy.setEnabled(bool(self.text))
        self.b_copy.clicked.connect(self.copy)
        row.addWidget(self.b_copy)
        self.b_folder = QPushButton("Open the data folder")
        self.b_folder.clicked.connect(self.open_folder)
        row.addWidget(self.b_folder)
        self.note = QLabel("")
        self.note.setStyleSheet("color:#2e7d32;")
        row.addWidget(self.note)
        row.addStretch(1)
        self.b_close = QPushButton("Close")
        self.b_close.setDefault(True)
        self.b_close.clicked.connect(self.accept)
        row.addWidget(self.b_close)
        lay.addLayout(row)

    def copy(self):
        QApplication.clipboard().setText(self.text)
        self.note.setText("Copied - paste it into your message.")

    def open_folder(self):
        import paths
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(paths.user_dir()))


def show_error_text(parent, text, title="Error", head=None):
    """Shows an error text (None: the error log) in the copyable window.  Tests replace this function."""
    dlg = ErrorDialog(parent, text, title, head)
    dlg.exec()
    return dlg


def install_excepthook():
    """A Python error inside a button / menu handler would close a PyQt6 program at once; show it (and write it to gpd_error.log) instead."""
    import traceback

    showing = [False]

    def hook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        log_error(text)
        sys.stderr.write(text)
        if showing[0]:                                    # an error while the error window is open (a redraw that keeps failing): logged, not stacked
            return
        showing[0] = True
        try:
            show_error_text(QApplication.activeWindow(), text, head="Something went wrong in the last action (the program keeps running).\n"
                            "Press Copy and send me the text; it is also kept in Help > Show the error log.")
        except Exception:
            pass
        finally:
            showing[0] = False
    sys.excepthook = hook


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OpenPara.ico")
    if os.path.exists(ico):
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(ico))
    install_excepthook()
    pm_app.apply_theme(app)
    _step("Opening the window...", 0.92)
    shell = type("Shell", (*ext.SHELL_MIXINS, AppShell), {}) if ext.SHELL_MIXINS else AppShell     # add-ons may give the window helpers their tabs use
    w = shell(sys.argv[1:])
    w.show()
    if SPLASH is not None:
        SPLASH.finish(w)                              # the card goes away when the window is up
    w.updates.check_later()
    QTimer.singleShot(2500, lambda: (w.report_addon_errors(), w.offer_first_run(), w.offer_addon_updates()))          # one after the other, never two questions at once
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
