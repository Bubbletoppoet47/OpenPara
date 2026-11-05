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
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

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
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.blank = QLabel("No document open.\n\nFile  >  New Part,  New Assembly  or  Open...")
        self.blank.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.blank.setStyleSheet("color:#808080; font-size:15px;")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.blank)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)
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
        fm.addSeparator()
        add(fm, "Open...", self.open_dialog, "Ctrl+O")
        add(fm, "Open Project Folder...", self.open_project_folder_dialog)          # always there: it offers the add-on that opens the folder
        add(fm, "Save", lambda: self.cur_call("save"), "Ctrl+S")
        add(fm, "Save As...", lambda: self.cur_call("save", True), "Ctrl+Shift+S")
        fm.addSeparator()
        add(fm, "Import STEP...", self.import_step)
        add(fm, "Export (STEP, STL)...", self.export_file)
        fm.addSeparator()
        add(fm, "Add-ons...", self.addons_dialog)
        add(fm, "Units...", self.units_dialog)
        add(fm, "Settings...", self.settings_dialog)
        fm.addSeparator()
        add(fm, "Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        add(fm, "Exit", self.close)
        self.add_acts = {}
        if ext.present("simulation") or ext.present("render"):               # only when a simulation / renderer add-on is installed
            am = mb.addMenu("&Add")
            if ext.present("render"):
                add(am, "New render (photorealistic pictures and videos)", lambda: self.add_render())
                am.addSeparator()
            if ext.present("simulation"):
                for kind, text in (("beam", "1D FEA (frames and trusses) - of a part"), ("fea", "2D FEA"), ("cfd", "2D CFD")):
                    self.add_acts[kind] = add(am, text, lambda k=kind: self.add_sim(k))
        em = mb.addMenu("&Edit")
        add(em, "Undo", lambda: self.cur_call("do_undo"), "Ctrl+Z")
        add(em, "Redo", lambda: self.cur_call("do_redo"), "Ctrl+Y")
        add(em, "Rebuild", self.rebuild, "Ctrl+B")
        vm = mb.addMenu("&View")
        add(vm, "Zoom to Fit", self.zoom_fit, "F")
        self.flip_act = QAction("Zoom: wheel toward you = in", self)
        self.flip_act.setCheckable(True)
        self.flip_act.setChecked(True)
        self.flip_act.toggled.connect(self.flip_changed)
        vm.addAction(self.flip_act)
        hm = mb.addMenu("&Help")
        add(hm, "Check for updates...", lambda: self.updates.check_now())
        self.auto_upd = QAction("Check for updates at start-up", self)
        self.auto_upd.setCheckable(True)
        self.auto_upd.setChecked(self.updates.auto_enabled())
        self.auto_upd.toggled.connect(lambda on: self.updates.set_auto(on))
        hm.addAction(self.auto_upd)
        add(hm, "Open the data folder", self.open_data_folder)
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
            return
        if getattr(w, "nav", None) is not None:
            self.flip_act.blockSignals(True)
            self.flip_act.setChecked(w.nav.wheel_sign == 1)
            self.flip_act.blockSignals(False)
        if hasattr(w, "refresh_parts"):
            w.refresh_parts()                     # parts may have been edited in another tab
        self.refresh_titles()

    # ------------------------------------------------------------------ documents
    def add_tab(self, w):
        i = self.tabs.addTab(w, w.title())
        self.tabs.setCurrentIndex(i)
        self.show_stack()
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
        """A Render Studio tab for the part or assembly that is on screen (or the source of the render tab that is on screen)."""
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
            QMessageBox.information(self, "Renderer", "Save the part / assembly first, so the render can be linked to it (File > Save).")
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
            QMessageBox.warning(self, "Open", f"Could not start {spec.get('label', kind)}: {ex}")
            return None
        self.tab_counts[kind] = self.tab_counts.get(kind, 0) + 1
        name = title or (os.path.basename(path.rstrip("/\\")) if path else f"{spec.get('short', spec.get('label', kind))} {self.tab_counts[kind]}")
        if not callable(getattr(w, "title", None)):              # an add-on tab need not know how the tab strip names it
            w.title = lambda w=w, name=name: os.path.basename(w.path.rstrip("/\\")) if getattr(w, "path", None) else name
        return self.add_tab(w)

    def open_project_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Project Folder", "")
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
        files, _ = QFileDialog.getOpenFileNames(self, "Open", "", self.open_filter())
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
        if path.lower().endswith(".gpr"):
            if not self.need_addon("render", "This render file (.gpr)"):
                return None
            import render_studio
            try:
                w = render_studio.RenderStudio.open_file(self, path)
            except Exception as ex:
                QMessageBox.warning(self, "Open", f"Could not open {os.path.basename(path)}: {ex}")
                return None
        elif path.lower().endswith(".gpa"):
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

    def close_tab(self, i):
        w = self.tabs.widget(i)
        if w is None:
            return False
        if not self.confirm_close(w):
            return False
        self.tabs.removeTab(i)
        if hasattr(w, "shutdown"):
            try:
                w.shutdown()
            except Exception:
                pass
        w.deleteLater()
        self.show_stack()
        return True

    def confirm_close(self, w):
        ask = getattr(w, "can_close", None)               # a tab with work running in the background asks for itself
        if callable(ask) and not ask():
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
        for i in range(self.tabs.count()):
            if not self.confirm_close(self.tabs.widget(i)):
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
        ev.accept()


def install_excepthook():
    """A Python error inside a button / menu handler would close a PyQt6 program at once; show it (and write it to gpd_error.log) instead."""
    import datetime
    import traceback

    def hook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        try:
            import paths
            with open(os.path.join(paths.user_dir(), "gpd_error.log"), "a", encoding="utf-8") as fh:
                fh.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
        except OSError:
            pass
        sys.stderr.write(text)
        try:
            box = QMessageBox(QApplication.activeWindow())
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Error")
            box.setText("Something went wrong in the last action (the program keeps running).\n"
                        "Please send me this text; it is also saved in gpd_error.log (Help > Open the data folder).")
            box.setDetailedText(text)
            box.exec()
        except Exception:
            pass
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
    QTimer.singleShot(2500, lambda: (w.offer_first_run(), w.offer_addon_updates()))          # one after the other, never two questions at once
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
