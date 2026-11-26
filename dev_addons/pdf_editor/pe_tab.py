"""pe_tab.py - the PDF editor tab: one OpenPara tab with a tab bar of its own, so that several PDFs (and page projects) can be open and you can go
between them.

    a PDF               the reader (pe_reader.ReaderTab): read it aloud from any sentence, highlight it, save the highlights into the file
    a page project      Page Break (page_break_tab.PageBreakTab, a .oppb file): cut long pages into normal ones and combine pages of several PDFs
    Images -> PDF       a window (pe_images.py) that reads the words in pictures of text and makes a PDF with real text; the PDF opens as a tab

One voice (pe_speech.Hub) is shared by every PDF: starting to read in one stops the other.  What was open, where you were reading and the voice are kept
in <user folder>/pdf_editor.json (pe_store.py).  PyMuPDF is downloaded the first time (pb_deps.py), the voice support when you first press Play
(pe_deps.py).

What the program window expects of a tab (see gpd_app.py): path, title(), is_dirty(), save(), shutdown(); adopt_path(path) lets a PDF or a project
that is opened from anywhere in the program land in this tab as a new inner tab instead of opening a second PDF editor.
"""
import os
import shutil
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStackedWidget, QTabWidget,
                             QToolButton, QVBoxLayout, QWidget)

import page_break_tab as pbt
import pb_core as core
import pb_deps
import pe_pdfio as pio
import pe_reader
import pe_speech
import pe_store
import ui_kit

PDF_EXT, PROJECT_EXT = ".pdf", ".oppb"
PDF_FILTER = "PDF files (*.pdf);;All files (*)"
PROJECT_FILTER = "Page Break project (*.oppb);;All files (*)"


class SetupSignals(QObject):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)


class PdfEditorTab(QWidget):
    AUTO_SETUP = True                          # download PyMuPDF by itself when it is missing (a test turns this off)
    installer = None                           # a test can put its own downloader here (see pb_deps.install)
    backend = None                             # a test can put its own voice here (see pe_speech)
    KEEP_LIMIT = 150 << 20                     # in a Workbench block: the PDFs it keeps come to at most this many bytes (the project file holds them)
    keep_dir = None                            # set by a Workbench block (attach_block_folder): the folder that holds what is open in this tab

    def __init__(self, path=None):
        super().__init__()
        self.host = None
        self.kind = None
        self.store = pe_store.Store()
        self.hub = pe_speech.Hub(self.backend)
        try:
            self.hub.rate = int(self.store.get("rate", 1))           # the speed of last time
        except (TypeError, ValueError):
            pass
        self.pending = []                      # paths to open as soon as PyMuPDF is there
        self.setup_busy = False
        self.last_project = None               # the page project that "Cut and combine" adds to
        self._labels = {}
        self.kept = {}                         # in a block: {key of a file picked from elsewhere: its copy in the block's folder}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        self.empty = ui_kit.EmptyState("PDF editor", "", [])
        self.build_empty()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_inner)
        self.tabs.currentChanged.connect(self.current_changed)
        self.tabs.setCornerWidget(self.build_plus(), Qt.Corner.TopRightCorner)
        self.setup = self.build_setup_page()
        self.setup_sig = SetupSignals()
        self.setup_sig.progress.connect(self.setup_text.setText)
        self.setup_sig.done.connect(self.setup_finished)
        for w in (self.empty, self.tabs, self.setup):
            self.stack.addWidget(w)

        self.timer = QTimer(self)               # the stars after the names of the inner tabs (a page project has no signal for it)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh_titles)
        self.timer.start()

        self.show_stack()
        if not core.available():
            self.pending = [path] if path else []
            self.show_setup("Getting ready ...")
            if self.AUTO_SETUP:
                QTimer.singleShot(0, self.start_setup)
            else:
                self.show_setup("PyMuPDF is needed.", failed=True)
            return
        self.startup(path)

    # ------------------------------------------------------------------ the empty page and the + button
    def build_empty(self):
        self.empty.set_text("PDF editor", "Open a PDF to read it aloud from any sentence and highlight it, cut and combine the pages of PDFs, "
                                          "or turn pictures of text into a PDF with real text.")
        lay = self.empty.layout()
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for i, (text, fn) in enumerate((("Open PDF...", self.open_dialog), ("Images → PDF...", self.images_dialog),
                                        ("New page project", self.new_project), ("Open page project...", self.open_project_dialog))):
            b = QPushButton(text)
            if i == 0:
                ui_kit.primary(b)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        lay.addSpacing(6)
        lay.addLayout(row)
        self.reopen_btn = QPushButton("")
        self.reopen_btn.clicked.connect(lambda _c=False: self.reopen_last())
        self.reopen_btn.setVisible(False)
        lay.addWidget(self.reopen_btn, 0, Qt.AlignmentFlag.AlignHCenter)

    def build_plus(self):
        b = QToolButton()
        b.setText("+  Open")
        b.setToolTip("Open a PDF, make a PDF from pictures of text, or start a page project")
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(b)
        for text, fn in (("Open PDF...", self.open_dialog), ("Images → PDF...", self.images_dialog), (None, None),
                         ("New page project", self.new_project), ("Open page project...", self.open_project_dialog)):
            if text is None:
                m.addSeparator()
            else:
                m.addAction(text, fn)
        b.setMenu(m)
        return ui_kit.menu_button(b)

    def last_files(self):
        if self.keep_dir:                                        # (what was open last time was open on its own, not in this block)
            return []
        return [p for p in self.store.get("open", []) if isinstance(p, str) and os.path.isfile(p)]

    def refresh_reopen(self):
        files = self.last_files()
        self.reopen_btn.setVisible(bool(files))
        if files:
            self.reopen_btn.setText(f"Reopen the {len(files)} file(s) from last time" if len(files) > 1 else "Reopen " + os.path.basename(files[0]))

    def reopen_last(self):
        for p in self.last_files():
            self.open_path(p)

    # ------------------------------------------------------------------ PyMuPDF, downloaded once
    def build_setup_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)
        t = QLabel("Setting up the PDF editor")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"font-size:15px; font-weight:600; color:{ui_kit.INK};")
        lay.addWidget(t)
        self.setup_text = QLabel("")
        self.setup_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setup_text.setWordWrap(True)
        self.setup_text.setFixedWidth(480)
        self.setup_text.setStyleSheet(f"color:{ui_kit.MUTED};")
        lay.addWidget(self.setup_text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setup_retry = ui_kit.primary(QPushButton("Try again"))
        self.setup_retry.clicked.connect(lambda _c=False: self.start_setup())
        lay.addWidget(self.setup_retry, 0, Qt.AlignmentFlag.AlignHCenter)
        return w

    def show_setup(self, text, failed=False):
        self.stack.setCurrentWidget(self.setup)
        self.setup_text.setText(text)
        self.setup_retry.setVisible(failed)

    def start_setup(self):
        if self.setup_busy or core.available():
            return
        self.setup_busy = True
        self.show_setup("Downloading PyMuPDF, the library that reads and writes PDFs (about 20 MB, once). This needs an internet connection.")

        def work():
            try:
                pb_deps.install(lambda text, frac=None: self.setup_sig.progress.emit(text), self.installer)
                self.setup_sig.done.emit(True, "")
            except BaseException as e:                         # noqa: BLE001 - shown to the person, never raised in a thread
                self.setup_sig.done.emit(False, str(e))
        self.setup_thread = threading.Thread(target=work, daemon=True)
        self.setup_thread.start()

    def setup_finished(self, ok, message):
        self.setup_busy = False
        if ok and core.reload():
            pio.reload()
            pend, self.pending = self.pending, []
            self.startup(pend[0] if pend else None, extra=pend[1:])
            return
        self.show_setup("PyMuPDF could not be downloaded.\n\n" + (message.strip()[-600:] or "Check the internet connection and try again."), failed=True)

    def startup(self, path, extra=()):
        """PyMuPDF is there: open what was asked for.  Without a file, the empty page offers to reopen what was open last time."""
        self.show_stack()
        for p in ([path] if path else []) + list(extra):
            self.open_path(p)
        self.refresh_reopen()

    # ------------------------------------------------------------------ the inner tabs
    def show_stack(self):
        if not core.available():                                 # the set-up page stays until PyMuPDF is there
            return
        if self.tabs.count():
            self.stack.setCurrentWidget(self.tabs)
        else:
            self.refresh_reopen()
            self.stack.setCurrentWidget(self.empty)

    def widgets(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def readers(self):
        return [w for w in self.widgets() if isinstance(w, pe_reader.ReaderTab)]

    def projects(self):
        return [w for w in self.widgets() if isinstance(w, pbt.PageBreakTab)]

    def active(self):
        return self.tabs.currentWidget()

    def find(self, path):
        k = pe_store.key(path)
        for w in self.widgets():
            if getattr(w, "path", None) and pe_store.key(w.path) == k:
                return w
        return None

    def label(self, w):
        if isinstance(w, pe_reader.ReaderTab):
            return w.title()
        name = os.path.basename(w.path) if getattr(w, "path", None) else "Page project"
        return name + (" *" if w.is_dirty() else "")

    def add_inner(self, w):
        i = self.tabs.addTab(w, self.label(w))
        self.tabs.setTabToolTip(i, getattr(w, "path", None) or "A page project that is not saved yet")
        self.tabs.setCurrentIndex(i)
        self._labels[w] = self.label(w)
        self.remember_open()
        self.show_stack()
        return w

    def refresh_titles(self):
        changed = False
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            text = self.label(w)
            if self._labels.get(w) != text:
                self._labels[w] = text
                self.tabs.setTabText(i, text)
                self.tabs.setTabToolTip(i, getattr(w, "path", None) or "A page project that is not saved yet")
                changed = True
        if changed:
            self.set_host_titles()

    def set_host_titles(self):
        h = self.host
        fn = getattr(h, "refresh_titles", None)
        if callable(fn) and self.window() is not None and self.isVisible():
            try:
                fn()
            except Exception:                                    # noqa: BLE001 - the star of the outer tab is a convenience
                pass

    def current_changed(self, _i):
        w = self.active()
        if isinstance(w, pbt.PageBreakTab):
            self.last_project = w
        self.remember_open()
        if self.host is not None and hasattr(self.host, "save_session"):
            try:
                self.host.save_session()
            except Exception:                                    # noqa: BLE001
                pass

    def remember_open(self):
        if self.keep_dir:                                        # a block's files live in the project's temporary folder: never in "open last time"
            return
        self.store.set("open", [w.path for w in self.widgets() if getattr(w, "path", None)])
        self.store.flush()

    # ------------------------------------------------------------------ opening
    def adopt_path(self, path):
        """The program window offers a file it is about to open: True when this tab took it (as an inner tab)."""
        if not (isinstance(path, str) and path.lower().endswith((PDF_EXT, PROJECT_EXT))):
            return False
        if not core.available():
            self.pending.append(path)
            return True
        return self.open_path(path) is not None

    def open_path(self, path):
        """Opens a PDF (a reader tab) or a .oppb project (a page project tab); one that is already open is brought to the front.  -> the tab, or None.
        In a Workbench block a file from anywhere else is copied into the block's folder first (see keep) and the copy is opened."""
        if not core.available():
            self.pending.append(path)
            return None
        path = self.kept.get(pe_store.key(path), path)           # a file that was copied into the block before: its copy
        w = self.find(path)
        if w is not None:
            self.tabs.setCurrentWidget(w)
            return w
        if not os.path.isfile(path):
            self.warn(f"{os.path.basename(path)} is not there any more.")
            return None
        low = path.lower()
        if not low.endswith((PROJECT_EXT, PDF_EXT)):
            self.warn(f"{os.path.basename(path)} is not a PDF or a page project.")
            return None
        path = self.keep(path)
        if path.lower().endswith(PROJECT_EXT):
            return self.open_project(path)
        return self.open_pdf(path)

    # ------------------------------------------------------------------ in a block of the Workbench: everything open is kept in the block's folder
    def attach_block_folder(self, folder):
        """A Workbench block opened this tab on its folder: the PDFs and page projects in it open as tabs, and from now on a file that is opened from anywhere
        else is copied into the folder (the project file holds the folder, never a link to a file somewhere else)."""
        os.makedirs(folder, exist_ok=True)
        self.keep_dir = folder
        self.reopen_btn.setVisible(False)
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith((PDF_EXT, PROJECT_EXT)) and os.path.isfile(os.path.join(folder, fn)):
                self.open_path(os.path.join(folder, fn))
        self.show_stack()

    @staticmethod
    def free_name(folder, name):
        """folder/name, or folder/stem (2).ext ... when that exists: a file in the folder is never overwritten."""
        stem, ext = os.path.splitext(name)
        p, i = os.path.join(folder, name), 2
        while os.path.exists(p):
            p = os.path.join(folder, f"{stem} ({i}).{ext.lstrip('.')}" if ext else f"{stem} ({i})")
            i += 1
        return p

    def kept_bytes(self):
        folder = self.keep_dir
        return sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))

    def keep(self, path):
        """-> the path to open: in a block, a copy in the block's folder (the original is never changed); a file that is already in the folder, a file that would take
        the block past KEEP_LIMIT (it opens where it is and is not part of the project: said), and any file outside a block are opened as they are."""
        if not self.keep_dir:
            return path
        folder = os.path.abspath(self.keep_dir)
        src = os.path.abspath(path)
        if pe_store.key(os.path.dirname(src)) == pe_store.key(folder):
            return path
        had = self.kept.get(pe_store.key(src))
        if had and os.path.isfile(had):                          # the same file again: its copy, not a second one
            return had
        try:
            size = os.path.getsize(src)
            if self.kept_bytes() + size > self.KEEP_LIMIT:
                self.warn(f"{os.path.basename(src)} is not copied into this block: the PDFs of a block come to at most {self.KEEP_LIMIT >> 20} MB, because the project file holds them.\n\n"
                          "It opens where it is and is not part of the project.")
                return path
            os.makedirs(folder, exist_ok=True)
            dst = self.free_name(folder, os.path.basename(src))
            shutil.copy2(src, dst)
        except OSError as e:
            self.warn(f"{os.path.basename(src)} could not be copied into this block ({e}). It opens where it is and is not part of the project.")
            return path
        self.kept[pe_store.key(src)] = dst
        return dst

    def ask_password(self, path):
        pw, ok = QInputDialog.getText(self, "PDF editor", f"{os.path.basename(path)} is protected by a password.\nPassword:", QLineEdit.EchoMode.Password)
        return pw if ok else None

    def warn(self, text):
        QMessageBox.warning(self, "PDF editor", text)

    def open_pdf(self, path):
        try:
            r = pe_reader.ReaderTab(path, self.hub, self.store, self.ask_password)
        except ValueError as e:
            self.warn(f"Could not open {os.path.basename(path)}:\n{e}")
            return None
        r.host = self.host
        r.changed.connect(self.refresh_titles)
        r.pages_requested.connect(self.open_in_pages)
        r.images_requested.connect(self.images_dialog)
        self.store.set("last_dir", os.path.dirname(os.path.abspath(path)))
        return self.add_inner(r)

    def open_project(self, path=None):
        t = pbt.PageBreakTab(path, portable=bool(self.keep_dir))
        t.host = self.host
        if self.keep_dir:
            t.keep = self.keep
        if path is None and self.keep_dir:                       # in a block a new page project has its file in the block's folder from the start (no question where)
            os.makedirs(self.keep_dir, exist_ok=True)
            t.path = self.free_name(os.path.abspath(self.keep_dir), "Page project" + PROJECT_EXT)
        self.last_project = t
        return self.add_inner(t)

    def new_project(self):
        return self.open_project(None)

    def open_in_pages(self, path):
        """Cut and combine a PDF of the reader: it is added to a page project (the one you used last, else a new one)."""
        t = self.last_project if self.last_project is not None and self.tabs.indexOf(self.last_project) >= 0 else None
        if t is None:
            t = self.new_project()
        self.tabs.setCurrentWidget(t)
        t.import_path(path)
        return t

    def open_dialog(self):
        start = self.store.get("last_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PDF", start, PDF_FILTER)
        for p in paths:
            self.open_path(p)

    def open_project_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open page project", self.store.get("last_dir", ""), PROJECT_FILTER)
        if p:
            self.open_path(p)

    def images_dialog(self):
        import pe_images
        d = pe_images.ImagesDialog(self)
        d.exec()
        return d

    # ------------------------------------------------------------------ closing
    def ask_save(self, w):
        """The tab has changes that are not saved: 'save' / 'discard' / 'cancel'."""
        r = QMessageBox.question(self, "Close", f"Save changes to {self.label(w).rstrip(' *')}?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        return {QMessageBox.StandardButton.Save: "save", QMessageBox.StandardButton.Discard: "discard"}.get(r, "cancel")

    def close_inner(self, i):
        w = self.tabs.widget(i)
        if w is None:
            return False
        if w.is_dirty():
            what = self.ask_save(w)
            if what == "cancel":
                return False
            if what == "save" and not self.save_one(w):
                return False
        self.tabs.removeTab(i)
        if self.last_project is w:
            self.last_project = None
        self._labels.pop(w, None)
        if hasattr(w, "shutdown"):
            try:
                w.shutdown()
            except Exception:                                    # noqa: BLE001
                pass
        w.deleteLater()
        self.remember_open()
        self.show_stack()
        return True

    def shutdown(self):
        """The program closes the tab: every PDF stops its voice and remembers where you were."""
        self.timer.stop()
        self.hub.stop()
        for w in self.widgets():
            if hasattr(w, "shutdown"):
                try:
                    w.shutdown()
                except Exception:                                # noqa: BLE001
                    pass
        self.store.flush()

    # ------------------------------------------------------------------ what the program window asks of a tab
    @property
    def path(self):
        w = self.active() if hasattr(self, "tabs") else None
        return getattr(w, "path", None)

    def title(self):
        w = self.active()
        return os.path.basename(w.path) if w is not None and getattr(w, "path", None) else "PDF editor"

    def is_dirty(self):
        return any(w.is_dirty() for w in self.widgets())

    def save_one(self, w):
        if isinstance(w, pbt.PageBreakTab) and not w.path:
            return bool(w.save_as()) if w is self.active() else True       # a project that was never saved is asked for only when it is on screen
        return w.save() is not False

    def save(self, as_new=False):
        """Save: every PDF and project that has changes.  as_new: the one on screen under a new name (a PDF: a copy)."""
        w = self.active()
        if as_new:
            if w is None:
                return False
            return bool(w.save_as()) if isinstance(w, pbt.PageBreakTab) else bool(w.save(True))
        ok = True
        for x in self.widgets():
            if x.is_dirty():
                ok = self.save_one(x) and ok
        self.refresh_titles()
        return ok


def make_tab(path=None):
    return PdfEditorTab(path)
