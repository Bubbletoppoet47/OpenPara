"""
gpd_app.py - the program window: File / Edit / View menus and one tab per open document (parts and assemblies).

Run:  python gpd_app.py [file.gpd | file.gpa ...]
"""
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QStackedWidget, QTabWidget

import pm_app
import pm_model as pm


class AppShell(QMainWindow):
    def __init__(self, files=None):
        super().__init__()
        self.setWindowTitle("Gen Parametric Designer")
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
        self.build_menus()
        opened = False
        for f in files or []:
            if os.path.exists(f):
                self.open_path(f)
                opened = True
        self.show_stack()
        self.timer = QTimer(self)                     # a star after the tab name while a document has unsaved changes
        self.timer.timeout.connect(self.refresh_titles)
        self.timer.start(1500)

    def show_stack(self):
        self.stack.setCurrentWidget(self.tabs if self.tabs.count() else self.blank)

    # ------------------------------------------------------------------ menus
    def build_menus(self):
        mb = self.menuBar()

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
        fm.addSeparator()
        add(fm, "Open...", self.open_dialog, "Ctrl+O")
        add(fm, "Save", lambda: self.cur_call("save"), "Ctrl+S")
        add(fm, "Save As...", lambda: self.cur_call("save", True), "Ctrl+Shift+S")
        fm.addSeparator()
        add(fm, "Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        add(fm, "Exit", self.close)
        am = mb.addMenu("&Add")
        add(am, "New render (photorealistic pictures and videos)", lambda: self.add_render())
        am.addSeparator()
        self.add_acts = {}
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

    def add_sim(self, kind):
        """A 1D FEA / 2D FEA / 2D CFD container for the part or assembly that is on screen."""
        import sim_tab
        src = self.cur()
        if isinstance(src, sim_tab.SimWindow):                # from a simulation: another one for the same part / assembly
            src = src.source_widget()
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
        import render_studio
        src = self.cur()
        if isinstance(src, render_studio.RenderStudio):
            src = src.source_widget()
        elif hasattr(src, "source_widget") and not hasattr(src, "doc") and not hasattr(src, "asm"):
            src = src.source_widget()                              # a simulation tab
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

    def new_part(self, demo=False):
        w = pm_app.MainWindow()
        if not demo:
            w.doc = pm.Document()
            w.update_all(fit=True)
            w.saved_json = w.doc.to_json()
        return self.add_tab(w)

    def new_assembly(self):
        import assembly
        return self.add_tab(assembly.AssemblyWindow(shell=self))

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", "", "Parts, assemblies, simulations and renders (*.gpd *.gpa *.gps *.gpr);;Part (*.gpd);;Assembly (*.gpa);;Simulation (*.gps);;Render (*.gpr)")
        for f in files:
            self.open_path(f)

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
        if path.lower().endswith(".gps"):
            import sim_tab
            try:
                w = sim_tab.SimWindow.open_file(self, path)
            except Exception as ex:
                QMessageBox.warning(self, "Open", f"Could not open {os.path.basename(path)}: {ex}")
                return None
        elif path.lower().endswith(".gpr"):
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
        ev.accept()


def install_excepthook():
    """A Python error inside a button / menu handler would close a PyQt6 program at once; show it (and write it to gpd_error.log) instead."""
    import datetime
    import traceback

    def hook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpd_error.log"), "a", encoding="utf-8") as fh:
                fh.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
        except OSError:
            pass
        sys.stderr.write(text)
        try:
            box = QMessageBox(QApplication.activeWindow())
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Error")
            box.setText("Something went wrong in the last action (the program keeps running).\n"
                        "Please send me this text; it is also saved in gpd_error.log next to the program.")
            box.setDetailedText(text)
            box.exec()
        except Exception:
            pass
    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    install_excepthook()
    pm_app.apply_theme(app)
    w = AppShell(sys.argv[1:])
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
