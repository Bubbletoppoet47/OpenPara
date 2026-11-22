"""pe_images.py - the Images -> PDF window: photos or scans of text in, a PDF with real text out (and it opens as a tab of the PDF editor).

Put the pictures in order (photo2 comes before photo10), say where the PDF goes, press Make the PDF.  The first time, the text reader (RapidOCR, roughly
100 MB) is downloaded after asking.  Reading the pictures runs in a thread; the PDF itself is written on the window's thread afterwards, because the
PDF library must not be used from two threads at once while the editor is showing PDFs.  Nothing leaves the computer except that one download.
"""
import os
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
                             QVBoxLayout)

import pe_deps
import pe_ocr
import ui_kit


class Signals(QObject):
    progress = pyqtSignal(int, int, str)               # done, total, text
    finished = pyqtSignal(object, str)                 # per-image paragraphs (None when it did not finish), a sentence for the person


class ImagesDialog(QDialog):
    installer = None                                   # a test can put its own downloader here
    closing = False                                    # Stop was pressed: the window closes as soon as the work has ended

    def __init__(self, shell=None):
        super().__init__(shell)
        self.shell = shell
        self.setWindowTitle("Images → PDF")
        self.setMinimumWidth(560)
        self.busy = False
        self.cancel = threading.Event()
        self.result_path = None
        self.out_edited = False
        self.sig = Signals()
        self.sig.progress.connect(self.on_progress)
        self.sig.finished.connect(self.on_finished)

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(ui_kit.note("Makes a PDF with real text from photos or scans of text, so it can be read aloud and highlighted like any other PDF. "
                                  "The pictures are read on this computer."))

        # 1 pictures
        s1 = ui_kit.Section("pdfeditor_images", 1, "Pictures", True)
        lay.addWidget(s1)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        self.b_add = QPushButton("Add pictures...")
        self.b_up = QPushButton("Move up")
        self.b_down = QPushButton("Move down")
        self.b_remove = QPushButton("Remove")
        self.b_clear = QPushButton("Remove all")
        for b in (self.b_add, self.b_up, self.b_down, self.b_remove, self.b_clear):
            col.addWidget(b)
        col.addStretch(1)
        row.addLayout(col)
        s1.body.addLayout(row)
        s1.body.addWidget(ui_kit.note("In the order they should be read. Pictures of one text, page after page, join into one flowing text."))
        self.b_add.clicked.connect(lambda _c=False: self.add_dialog())
        self.b_up.clicked.connect(lambda _c=False: self.move(-1))
        self.b_down.clicked.connect(lambda _c=False: self.move(1))
        self.b_remove.clicked.connect(lambda _c=False: self.remove_selected())
        self.b_clear.clicked.connect(lambda _c=False: self.clear())
        self.list.itemSelectionChanged.connect(self.refresh)

        # 2 save as
        s2 = ui_kit.Section("pdfeditor_images", 2, "Save the PDF as", True)
        lay.addWidget(s2)
        r2 = QHBoxLayout()
        self.out = QLineEdit()
        self.out.setPlaceholderText("Where to save the PDF")
        self.out.textEdited.connect(self.out_typed)
        self.b_browse = QPushButton("Browse...")
        self.b_browse.clicked.connect(lambda _c=False: self.browse())
        r2.addWidget(self.out, 1)
        r2.addWidget(self.b_browse)
        s2.body.addLayout(r2)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = ui_kit.StatusLine("")
        lay.addWidget(self.status)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.b_close = QPushButton("Close")
        self.b_close.clicked.connect(lambda _c=False: self.reject())
        self.b_go = ui_kit.primary(QPushButton("Make the PDF"))
        self.b_go.clicked.connect(lambda _c=False: self.go())
        bottom.addWidget(self.b_close)
        bottom.addWidget(self.b_go)
        lay.addLayout(bottom)
        self.refresh()

    # ------------------------------------------------------------------ the list
    def paths(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def add_paths(self, paths):
        have = {os.path.normcase(p) for p in self.paths()}
        new = [p for p in sorted(paths, key=pe_ocr.natural_key) if os.path.normcase(p) not in have]
        for p in new:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.list.addItem(item)
        if new and not self.out_edited:
            self.out.setText(self.default_out())
        self.refresh()
        return len(new)

    def add_dialog(self):
        exts = pe_ocr.image_exts()
        flt = "Pictures (%s);;All files (*)" % " ".join("*" + e for e in exts)
        start = os.path.dirname(self.paths()[-1]) if self.paths() else (self.shell.store.get("last_dir", "") if self.shell is not None else "")
        files, _ = QFileDialog.getOpenFileNames(self, "Add pictures", start, flt)
        self.add_paths(files)

    def move(self, step):
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=step > 0)
        for r in rows:
            to = r + step
            if 0 <= to < self.list.count():
                self.list.insertItem(to, self.list.takeItem(r))
                self.list.item(to).setSelected(True)
        self.out_default_refresh()
        self.refresh()

    def remove_selected(self):
        for r in sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=True):
            self.list.takeItem(r)
        self.out_default_refresh()
        self.refresh()

    def clear(self):
        self.list.clear()
        self.out_default_refresh()
        self.refresh()

    # ------------------------------------------------------------------ where the PDF goes
    def default_out(self):
        ps = self.paths()
        if not ps:
            return ""
        base = os.path.splitext(os.path.basename(ps[0]))[0]
        return os.path.join(os.path.dirname(ps[0]), base + " - text.pdf")

    def out_typed(self, _text):
        self.out_edited = True

    def out_default_refresh(self):
        if not self.out_edited:
            self.out.setText(self.default_out())

    def browse(self):
        start = self.out.text() or self.default_out()
        p, _ = QFileDialog.getSaveFileName(self, "Save the PDF as", start, "PDF files (*.pdf)")
        if p:
            if not p.lower().endswith(".pdf"):
                p += ".pdf"
            self.out.setText(p)
            self.out_edited = True

    # ------------------------------------------------------------------ state
    def refresh(self):
        n = self.list.count()
        sel = bool(self.list.selectedItems())
        idle = not self.busy
        self.b_add.setEnabled(idle)
        self.b_up.setEnabled(idle and sel)
        self.b_down.setEnabled(idle and sel)
        self.b_remove.setEnabled(idle and sel)
        self.b_clear.setEnabled(idle and n > 0)
        self.out.setEnabled(idle)
        self.b_browse.setEnabled(idle)
        self.b_go.setEnabled(idle and n > 0)
        self.b_go.setText("Make the PDF")
        self.b_close.setText("Stop" if self.busy else "Close")

    # ------------------------------------------------------------------ asking
    def ask_download(self, mb):
        r = QMessageBox.question(self, "Images → PDF", f"Reading text from pictures needs a text reader (roughly {mb} MB), downloaded once from the internet.\n\n"
                                 "Download it now?")
        return r == QMessageBox.StandardButton.Yes

    def ask_overwrite(self, path):
        r = QMessageBox.question(self, "Images → PDF", f"{os.path.basename(path)} already exists.\n\nReplace it?")
        return r == QMessageBox.StandardButton.Yes

    def warn(self, text):
        QMessageBox.warning(self, "Images → PDF", text)

    # ------------------------------------------------------------------ running
    def go(self):
        if self.busy or not self.paths():
            return
        out = os.path.abspath(self.out.text().strip()) if self.out.text().strip() else ""
        if not out:
            self.status.say("Choose where to save the PDF.", "warn")
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
            self.out.setText(out)
        if not os.path.isdir(os.path.dirname(out)):
            self.status.say("The folder to save in does not exist.", "warn")
            return
        if self.shell is not None and hasattr(self.shell, "find") and self.shell.find(out) is not None:
            self.status.say(f"{os.path.basename(out)} is open in the editor. Choose another name.", "warn")
            return
        if os.path.exists(out) and not self.ask_overwrite(out):
            return
        self.target = out
        self.cancel.clear()
        self.busy = True
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.refresh()
        if pe_deps.ocr_ready():
            self.start_reading()
        elif self.ask_download(pe_deps.OCR_MB):
            self.start_download()
        else:
            self.stopped("Nothing was made: the text reader was not downloaded.")

    def start_download(self):
        self.status.say("Downloading the text reader (once). This needs an internet connection ...")

        def work():
            try:
                pe_deps.install_ocr(lambda text, frac=None: self.sig.progress.emit(0, 0, text), self.installer)
                ok = ""
            except BaseException as e:                 # noqa: BLE001 - shown to the person, never raised in a thread
                ok = str(e).strip()[-500:] or "The download failed."
            self.sig.finished.emit(None, "download:" + ok)
        threading.Thread(target=work, daemon=True).start()

    def start_reading(self):
        paths = self.paths()
        self.bar.setRange(0, len(paths))
        self.bar.setValue(0)
        self.status.say("Loading the text reader (a few seconds the first time) ...")

        def work():
            per, msg = [], ""
            try:
                pe_ocr.get_engine()
                for i, p in enumerate(paths):
                    if self.cancel.is_set():
                        self.sig.finished.emit(None, "stopped")
                        return
                    self.sig.progress.emit(i, len(paths), f"Reading {os.path.basename(p)} ({i + 1} of {len(paths)}) ...")
                    per.append(pe_ocr.read_paragraphs(p))
            except ValueError as e:                    # a picture that cannot be opened: said plainly, nothing is made
                self.sig.finished.emit(None, "error:" + str(e))
                return
            except BaseException as e:                 # noqa: BLE001
                self.sig.finished.emit(None, "error:The text reader stopped (%s)." % (str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__))
                return
            self.sig.finished.emit(per, msg)
        threading.Thread(target=work, daemon=True).start()

    def on_progress(self, done, total, text):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.status.say(text)

    def on_finished(self, per, message):
        if message.startswith("download:"):
            err = message[len("download:"):]
            if err:
                self.stopped("The text reader could not be downloaded. " + err, "bad")
            elif self.cancel.is_set():
                self.stopped("Stopped.")
            else:
                self.start_reading()
            return
        if per is None:
            if message == "stopped":
                self.stopped("Stopped. Nothing was made.")
            else:
                self.stopped(message[len("error:"):] if message.startswith("error:") else message, "bad")
            return
        if self.cancel.is_set():
            self.stopped("Stopped. Nothing was made.")
            return
        if not any(per):
            self.stopped("No text could be read in these pictures. Sharper, straighter, well-lit photos read best.", "warn")
            return
        self.status.say("Building the PDF ...")
        self.bar.setRange(0, 0)
        try:
            out, nparas, nwords = pe_ocr.make_pdf(per, self.target)
        except ValueError as e:
            self.stopped(str(e), "bad")
            return
        self.busy = False
        self.bar.setVisible(False)
        self.result_path = out
        self.status.say(f"Made {os.path.basename(out)}: {nwords} words in {nparas} paragraphs.", "good")
        self.refresh()
        self.finish(out)

    def stopped(self, text, level=""):
        self.busy = False
        self.bar.setVisible(False)
        self.status.say(text, level)
        self.refresh()
        if self.closing:
            self.reject()

    def finish(self, out):
        """The PDF is made: it opens as a tab of the editor and this window closes."""
        if self.shell is not None and hasattr(self.shell, "open_path"):
            self.shell.open_path(out)
        self.accept()

    def reject(self):
        if self.busy:                                  # Stop: the reading ends after the picture it is on, then the window closes
            self.cancel.set()
            self.closing = True
            self.status.say("Stopping ...")
            return
        super().reject()
