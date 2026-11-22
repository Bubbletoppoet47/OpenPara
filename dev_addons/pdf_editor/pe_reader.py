"""pe_reader.py - one PDF in the reader: read it aloud from the sentence you choose, highlight it, save the highlights into the file.

Left: numbered sections (Read aloud, Highlights, This PDF) with Play / Pause pinned underneath.  Right: the pages (pe_view.PdfView).
The window of the PDF editor holds one of these for every PDF that is open (pe_tab.py) and one voice (pe_speech.Hub) that they share.

Where it reads from:  click a sentence = the marker; Play starts at the marker (or at the top of the window when there is none); double-click or right-click
"Read from here" starts at once.  Pause goes on in the middle of the sentence; Stop leaves the marker on the sentence that was being read, so Play starts
that sentence again.  The marker does not move when you scroll.

Highlights are written into the PDF with Save (Ctrl+S) or, when the switch of this PDF is on, right after each one.
"""
import os

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                             QSlider, QSplitter, QVBoxLayout, QWidget)

import pe_deps
import pe_pdfio as pio
import pe_speech
import pe_store
import pe_text
import pe_view
import ui_kit

try:
    from autosave import Switch                  # the pill switch of OpenPara's own AutoSave: the same look
except Exception:                                # noqa: BLE001 - outside the program (a test of a single file) a check box does the same
    from PyQt6.QtWidgets import QCheckBox as Switch

PDF_FILTER = "PDF files (*.pdf);;All files (*)"
CHIP = "#c8402f"


class Signals(QObject):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)


class ReaderTab(QWidget):
    changed = pyqtSignal()                       # the title (a star) or the buttons changed
    pages_requested = pyqtSignal(str)            # "Cut and combine this PDF"
    images_requested = pyqtSignal()
    AUTO_SETUP = True                            # download the voice support by itself when it is missing (a test turns this off)
    installer = None                             # a test can put its own downloader here

    def __init__(self, path, hub, store, password_for=None):
        super().__init__()
        self.path = os.path.abspath(path)
        self.hub, self.store = hub, store
        self.host = None
        self.doc = pio.open_pdf(self.path, password_for)       # raises ValueError with a sentence for the person
        self.edits = pio.Edits(self.doc)
        self.text = pe_text.DocText(self.doc, build=False)
        self.placed = False
        self.setup_busy = False
        self.sig = Signals()
        self.sig.progress.connect(lambda t: self.status.say(t))
        self.sig.done.connect(self.voice_setup_done)
        self.pump_timer = QTimer(self)
        self.pump_timer.setInterval(40)
        self.pump_timer.timeout.connect(self.pump)
        self.build_timer = QTimer(self)
        self.build_timer.setInterval(0)
        self.build_timer.timeout.connect(self.build_step)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.build_bar())
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self.build_panel())
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.banner = self.build_banner()
        rl.addWidget(self.banner)
        self.view = pe_view.PdfView(self)
        rl.addWidget(self.view, 1)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 1000])
        lay.addWidget(split, 1)
        self.status = ui_kit.StatusLine("")
        lay.addWidget(self.status)

        self.refresh_voices()
        self.sync()
        self.status.say("Reading the text of this PDF ...")
        self.build_timer.start()

    # ------------------------------------------------------------------ building the window
    def build_bar(self):
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.addWidget(ui_kit.kind_chip("PDF", CHIP))
        self.title_lbl = QLabel("")
        self.title_lbl.setStyleSheet(f"font-weight:600; color:{ui_kit.INK};")
        h.addWidget(self.title_lbl)
        h.addSpacing(12)
        self.b_save = QPushButton("Save")
        self.b_save.setToolTip("Write the highlights into this PDF (Ctrl+S)")
        self.b_save.clicked.connect(lambda _c=False: self.save())
        self.b_copy = QPushButton("Save a copy...")
        self.b_copy.setToolTip("Write the PDF, with its highlights, to a new file and go on with that one")
        self.b_copy.clicked.connect(lambda _c=False: self.save_copy())
        h.addWidget(self.b_save)
        h.addWidget(self.b_copy)
        h.addStretch(1)
        h.addWidget(QLabel("Zoom"))
        self.b_out, self.b_in, self.b_fit = QPushButton("−"), QPushButton("+"), QPushButton("Fit width")
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setMinimumWidth(44)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for b in (self.b_out, self.b_in):
            b.setFixedWidth(30)
        self.b_out.clicked.connect(lambda _c=False: self.view.zoom_by(1 / pe_view.ZOOM_STEP))
        self.b_in.clicked.connect(lambda _c=False: self.view.zoom_by(pe_view.ZOOM_STEP))
        self.b_fit.clicked.connect(lambda _c=False: self.view.fit_width())
        for w in (self.b_out, self.zoom_lbl, self.b_in, self.b_fit):
            h.addWidget(w)
        return bar

    def build_banner(self):
        f = QFrame()
        f.setObjectName("banner")
        f.setStyleSheet("QFrame#banner { background:#fff6e0; border-bottom:1px solid #e8d29a; }")
        h = QHBoxLayout(f)
        h.setContentsMargins(10, 6, 10, 6)
        self.banner_lbl = QLabel("This PDF has no selectable text (it is probably a scan), so there is nothing to read aloud. "
                                 "Images → PDF can read the words in the page pictures and make a PDF with real text.")
        self.banner_lbl.setWordWrap(True)
        self.banner_lbl.setStyleSheet("color:#6b4d00;")
        h.addWidget(self.banner_lbl, 1)
        b = QPushButton("Images → PDF...")
        b.clicked.connect(lambda _c=False: self.images_requested.emit())
        h.addWidget(b)
        f.setVisible(False)
        return f

    def build_panel(self):
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(6, 6, 6, 6)
        cl.setSpacing(4)
        self.sections = []

        def sec(n, title, summary=None, help_text=None):
            s = ui_kit.Section("pdfeditor", n, title, True, help_text, summary)
            self.sections.append(s)
            cl.addWidget(s)
            return s.body

        # 1 read aloud
        v = sec(1, "Read aloud", summary=lambda: self.voice_summary())
        v.addWidget(ui_kit.note("Click a sentence to choose where to start, then press Play. Double-click a sentence to read from it at once. "
                                "Pause goes on in the middle of the sentence."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Voice"))
        self.voice_box = QComboBox()
        ui_kit.tame_combo(self.voice_box, 26)
        self.voice_box.currentTextChanged.connect(self.voice_changed)
        row.addWidget(self.voice_box, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Speed"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(pe_speech.RATE_MIN, pe_speech.RATE_MAX)
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed.valueChanged.connect(self.speed_changed)
        row.addWidget(self.speed, 1)
        self.speed_lbl = QLabel("")
        self.speed_lbl.setMinimumWidth(52)
        row.addWidget(self.speed_lbl)
        v.addLayout(row)
        self.voice_note = ui_kit.note("")
        self.voice_note.setWordWrap(True)
        v.addWidget(self.voice_note)

        # 2 highlights
        v = sec(2, "Highlights", summary=lambda: self.highlight_summary())
        v.addWidget(ui_kit.note("Drag across some text, then pick a colour. Right-click a highlight to remove it. Highlights are part of the PDF, "
                                "so Edge and Acrobat show them too."))
        row = QHBoxLayout()
        self.colour_buttons = []
        for name, rgb in pio.COLORS.items():
            b = QPushButton("")
            b.setFixedSize(28, 28)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip("Highlight the selected text " + name.lower())
            col_hex = pio.hex_color(rgb)
            r8, g8, b8 = (int(round(c * 255)) for c in rgb)
            b.setStyleSheet(f"QPushButton {{ background:{col_hex}; border:1px solid #7b8798; border-radius:14px; }}"
                            f"QPushButton:disabled {{ background:rgba({r8},{g8},{b8},90); border:1px solid #c9d0db; }}"
                            f"QPushButton:hover:enabled {{ border:2px solid #2b7de9; }}")
            b.clicked.connect(lambda _c=False, n=name: self.highlight_selection(n))
            row.addWidget(b)
            self.colour_buttons.append(b)
        row.addStretch(1)
        self.b_undo, self.b_redo = QPushButton("Undo"), QPushButton("Redo")
        self.b_undo.clicked.connect(lambda _c=False: self.undo())
        self.b_redo.clicked.connect(lambda _c=False: self.redo())
        for b in (self.b_undo, self.b_redo):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        self.auto_sw = Switch()
        self.auto_sw.setChecked(self.store.auto(self.path))
        self.auto_sw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.auto_sw.toggled.connect(self.auto_toggled)
        row.addWidget(self.auto_sw)
        lbl = QLabel("Save highlights into this PDF by themselves")
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)
        v.addLayout(row)
        v.addWidget(ui_kit.note("On: each highlight (and each undo) is written into the file right after you make it. Off: it waits for Save."))

        # 3 this PDF
        v = sec(3, "This PDF", summary=lambda: self.info_lbl.text())
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        v.addWidget(self.info_lbl)
        b = QPushButton("Cut and combine its pages...")
        b.setToolTip("Open this PDF in a page project, to cut its pages and combine them with others")
        b.clicked.connect(lambda _c=False: self.request_pages())
        v.addWidget(b)
        cl.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(col)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(scroll, 1)
        pin = QFrame()
        pin.setObjectName("pinned")
        pin.setStyleSheet("QFrame#pinned { border-top:1px solid #cfd6e0; background:#f6f8fa; }")
        pb = QHBoxLayout(pin)
        pb.setContentsMargins(8, 8, 8, 8)
        self.b_prev, self.b_next, self.b_stop = QPushButton("⏮"), QPushButton("⏭"), QPushButton("⏹")
        self.b_play = ui_kit.primary(QPushButton("▶  Play"))
        self.b_prev.setToolTip("The sentence before (Left arrow)")
        self.b_next.setToolTip("The next sentence (Right arrow)")
        self.b_stop.setToolTip("Stop reading; the marker stays on the sentence")
        self.b_play.setToolTip("Play / Pause (Space)")
        self.b_prev.clicked.connect(lambda _c=False: self.step(-1))
        self.b_next.clicked.connect(lambda _c=False: self.step(1))
        self.b_stop.clicked.connect(lambda _c=False: self.stop_reading())
        self.b_play.clicked.connect(lambda _c=False: self.toggle_play())
        for b in (self.b_prev, self.b_next, self.b_stop, self.b_play):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)             # Space and the arrows stay with the pages
        for b in (self.b_prev, self.b_next, self.b_stop):
            b.setFixedWidth(38)
        pb.addWidget(self.b_prev)
        pb.addWidget(self.b_play, 1)
        pb.addWidget(self.b_next)
        pb.addWidget(self.b_stop)
        pl.addWidget(pin)
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(520)
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return panel

    # ------------------------------------------------------------------ reading the text, placing the view
    def build_step(self):
        """Reads a slice of the text; the window stays alive while a long book is read."""
        done = self.text.step(0.015)
        if done:
            self.build_timer.stop()
            self.text_ready()
        else:
            self.status.say(f"Reading the text of this PDF ... {round(100 * self.text.next_page / max(1, self.text.npages))} %")

    def finish_text(self):
        """Reads whatever is left of the text now (Play pressed early, or a test)."""
        if not self.text.ready:
            self.build_timer.stop()
            self.text.step(None)
            self.text_ready()

    def text_ready(self):
        saved = self.store.position(self.path)
        if saved and saved.get("sent") is not None and 0 <= saved["sent"] < len(self.text.sentences):
            self.view.set_read(saved["sent"], scroll=False)
        self.banner.setVisible(not self.text.tokens)
        n = len(self.text.sentences)
        self.info_lbl.setText(f"{self.doc.page_count} page(s), {n} sentence(s)." if n else f"{self.doc.page_count} page(s). No selectable text.")
        self.status.say("")
        self.update_status()
        self.sync()
        for s in self.sections:
            s.refresh_summary()
        if self.placed:
            self.place_saved()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self.placed:
            self.placed = True
            QTimer.singleShot(0, self.place_initial)
        self.refresh_voices()

    def place_initial(self):
        """The first time the PDF is on screen: where you left it, or fitted to the window."""
        saved = self.store.position(self.path)
        if saved:
            self.view.set_zoom(saved.get("zoom", 1.0))
        else:
            self.view.fit_width()
        self.zoom_lbl.setText(f"{round(self.view.zoom * 100)}%")
        if self.text.ready:
            self.place_saved()
        else:
            QTimer.singleShot(0, self.place_saved)

    def place_saved(self):
        saved = self.store.position(self.path)
        if not saved:
            return
        if self.view.read_idx is not None and self.text.ready:
            self.view.ensure_visible(self.view.read_idx)
        elif saved.get("page"):
            self.view.scroll_to_page(saved["page"])

    def remember(self, flush=True):
        self.store.set_position(self.path, self.view.read_idx, self.view.zoom, self.view.current_page())
        if flush:
            self.store.flush()

    # ------------------------------------------------------------------ what the viewer asks for
    def view_changed(self):
        self.zoom_lbl.setText(f"{round(self.view.zoom * 100)}%")
        self.update_status()

    def selection_changed(self):
        on = self.view.sel is not None
        for b in self.colour_buttons:
            b.setEnabled(on)

    def sentence_clicked(self, idx):
        if not self.hub.reading(self):
            self.update_status()
        self.remember(flush=False)

    def play_requested(self, idx):
        self.play_from(idx)

    # ------------------------------------------------------------------ voices
    def voice_summary(self):
        return (self.voice_box.currentText() or "no voice") if self.voice_box.count() else "no voice yet"

    def refresh_voices(self):
        voices = self.hub.voices()
        cur = self.hub.voice_name
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        self.voice_box.addItems(voices)
        if voices:
            if cur not in voices:
                cur = (self.store.get("voice") if self.store.get("voice") in voices else voices[0])
                self.hub.voice_name = cur
            self.voice_box.setCurrentText(cur)
        self.voice_box.setEnabled(bool(voices))
        self.voice_box.blockSignals(False)
        self.speed.blockSignals(True)
        self.speed.setValue(self.hub.rate)
        self.speed.blockSignals(False)
        self.speed_lbl.setText(self.speed_text(self.hub.rate))
        if voices:
            self.voice_note.setText("")
            self.voice_note.setVisible(False)
        else:
            self.voice_note.setVisible(True)
            self.voice_note.setText("No Windows voice is ready. Press Play: the first time, OpenPara downloads the small package that lets it use them "
                                    f"(about {pe_deps.VOICE_MB} MB, once). This needs Windows and an internet connection." if os.name == "nt" else
                                    "Reading aloud uses the Windows voices, so it needs Windows.")

    @staticmethod
    def speed_text(v):
        return f"{v:+d}" if v else "normal"

    def voice_changed(self, name):
        if name:
            self.hub.voice_name = name
            self.store.set("voice", name)

    def speed_changed(self, v):
        self.hub.rate = v
        self.speed_lbl.setText(self.speed_text(self.hub.rate))
        self.store.set("rate", self.hub.rate)

    # voice support (pywin32), downloaded the first time
    def need_voices(self, idx):
        if os.name != "nt":
            self.status.say("Reading aloud uses the Windows voices, so it needs Windows.", "warn")
            return
        if self.setup_busy:
            return
        if not self.AUTO_SETUP:
            self.status.say("The voice support is missing.", "warn")
            return
        import threading
        self.setup_busy = True
        self.pending_idx = idx
        self.status.say(f"Getting the voice support (about {pe_deps.VOICE_MB} MB, once). This needs an internet connection ...")

        def work():
            try:
                pe_deps.install_voice(lambda text, frac=None: self.sig.progress.emit(text), self.installer)
                self.sig.done.emit(True, "")
            except BaseException as e:                           # noqa: BLE001 - shown to the person, never raised in a thread
                self.sig.done.emit(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def voice_setup_done(self, ok, message):
        self.setup_busy = False
        self.hub.forget_voices()
        self.refresh_voices()
        if ok and self.hub.voices():
            self.status.say("The voices are ready.", "good")
            idx, self.pending_idx = getattr(self, "pending_idx", None), None
            if idx is not None:
                self.play_from(idx)
        else:
            self.status.say("The voice support could not be set up: " + (message.strip().splitlines()[-1] if message.strip() else "no voice was found."), "bad")

    # ------------------------------------------------------------------ reading aloud
    def toggle_play(self):
        if self.hub.reading(self):
            if self.hub.paused:
                self.hub.resume()
            else:
                self.hub.pause()
                self.remember()
            self.sync()
            return
        self.finish_text()
        idx = self.view.start_sentence()
        if idx is None:
            self.status.say("There is no text to read in this PDF.", "warn")
            return
        self.play_from(idx)

    def play_from(self, idx):
        self.finish_text()
        if not self.text.sentences:
            return
        if not self.hub.voices():
            self.need_voices(idx)
            return
        idx = max(0, min(idx, len(self.text.sentences) - 1))
        self.hub.start(self, self.text.sentence_texts, idx)
        self.view.set_read(idx)
        self.pump_timer.start()
        self.sync()
        self.update_status()

    def stop_reading(self):
        if self.hub.owner is self:
            self.hub.stop()
        self.pump_timer.stop()
        self.sync()
        self.update_status()
        self.remember()

    def step(self, d):
        if not self.text.ready or not self.text.sentences:
            return
        base = self.view.read_idx if self.view.read_idx is not None else (self.view.start_sentence() or 0)
        new = max(0, min(len(self.text.sentences) - 1, base + d))
        if self.hub.reading(self):
            self.play_from(new)
        else:
            self.view.set_read(new)
            self.sentence_clicked(new)

    def pump(self):
        """What the voice reported (called by a timer while this PDF is reading)."""
        for kind, val in self.hub.poll():
            if self.hub.owner is not self:
                continue
            if kind == "sentence":
                self.view.set_read(val)
                self.update_status()
            elif kind == "done":
                if val:
                    self.status.say("Finished reading.", "good")
                self.hub.owner = None
                self.remember()
            elif kind == "error":
                self.status.say("Speech problem: " + str(val), "bad")
        if self.hub.owner is not self or not self.hub.running:
            self.pump_timer.stop()
            self.sync()

    def sync(self):
        reading = self.hub.reading(self)
        has_text = (not self.text.ready) or bool(self.text.sentences)
        self.b_play.setEnabled(has_text)
        self.b_prev.setEnabled(self.text.ready and bool(self.text.sentences))
        self.b_next.setEnabled(self.text.ready and bool(self.text.sentences))
        self.b_stop.setEnabled(reading)
        self.b_play.setText(("▶  Resume" if self.hub.paused else "⏸  Pause") if reading else "▶  Play")
        self.b_undo.setEnabled(bool(self.edits.undo_stack))
        self.b_redo.setEnabled(bool(self.edits.redo_stack))
        self.selection_changed()
        self.b_save.setEnabled(self.edits.dirty)
        self.title_lbl.setText(self.title())
        self.changed.emit()

    def update_status(self):
        if self.status.full and not self.status.full.startswith(("Page ", "Reading the text")):
            return                                               # a message (saved, a problem) stays until the next thing happens
        parts = [f"Page {self.view.current_page() + 1} of {self.doc.page_count}"]
        v = self.view
        if self.text.ready and v.read_idx is not None and v.read_idx < len(self.text.sentences):
            snip = self.text.sentence_texts[v.read_idx]
            parts.append(f"Sentence {v.read_idx + 1} of {len(self.text.sentences)}")
            parts.append("“" + (snip[:60] + "…" if len(snip) > 60 else snip) + "”")
        self.status.say("   ·   ".join(parts))

    # ------------------------------------------------------------------ highlights
    def highlight_selection(self, name):
        if not self.view.sel:
            self.status.say("Drag across some text first, then pick a highlight colour.", "warn")
            return []
        rects = self.text.rects_for_tokens(*self.view.sel)
        pages = self.edits.add(rects, pio.COLORS[name])
        self.view.sel = None
        self.view._hide_popup()
        self.view.refresh_pages(pages)
        self.after_edit()
        return pages

    def remove_highlight(self, pno, xref):
        if self.edits.remove(pno, xref):
            self.view.refresh_pages([pno])
            self.after_edit()
            return True
        return False

    def undo(self):
        pages = self.edits.undo()
        if pages is None:
            return False
        self.view.refresh_pages(pages)
        self.after_edit()
        return True

    def redo(self):
        pages = self.edits.redo()
        if pages is None:
            return False
        self.view.refresh_pages(pages)
        self.after_edit()
        return True

    def copy_selection(self):
        if self.view.sel:
            QApplication.clipboard().setText(self.text.text_for_tokens(*self.view.sel))
        self.view.clear_selection()

    def after_edit(self):
        """A highlight was added, removed, undone or redone: update the buttons and, when this PDF saves by itself, write the file now."""
        self.status.say("")
        if self.auto_sw.isChecked():
            self.write(interactive=False)
        self.sync()
        self.update_status()

    def highlight_summary(self):
        try:
            n = self.edits.count()
        except Exception:                                        # noqa: BLE001
            n = 0
        return f"{n} highlight(s)" + (" - saved automatically" if self.auto_sw.isChecked() else "")

    # ------------------------------------------------------------------ saving
    def auto_toggled(self, on):
        self.store.set_auto(self.path, on)
        self.store.flush()
        if on and self.edits.dirty:
            self.write(interactive=False)                        # what is waiting goes into the file now
        self.sync()
        for s in self.sections:
            s.refresh_summary()

    def is_dirty(self):
        return self.edits.dirty

    def title(self):
        return os.path.basename(self.path) + (" *" if self.edits.dirty else "")

    def ask_copy(self, why):
        """The highlights could not be written into the file: offer a copy.  True = the person wants one."""
        return QMessageBox.question(self, "PDF editor", f"The highlights could not be saved into the original file:\n{why}\n\n"
                                    "Save a copy of the PDF (with your highlights) instead?") == QMessageBox.StandardButton.Yes

    def write(self, interactive=True):
        """Writes the highlights into the PDF.  True when the file is up to date.  interactive=False (the automatic save) never opens a window."""
        if not self.edits.dirty:
            return True
        try:
            self.doc = self.edits.save()
            self.text.doc = self.doc                             # (the document was opened again, see pe_pdfio.save_in_place)
        except pio.SaveError as ex:
            self.status.say("The highlights could not be saved into the file: " + str(ex) +
                            ("" if interactive else "  They are kept; Save tries again, or use Save a copy."), "bad")
            if interactive and self.ask_copy(str(ex)):
                return self.save_copy()
            return False
        self.status.say("Saved " + self.path, "good")
        self.sync()
        return True

    def save(self, as_new=False):
        if as_new:
            return self.save_copy()
        return self.write(interactive=True)

    def save_copy(self):
        start = os.path.splitext(self.path)[0] + " - highlighted.pdf"
        p, _ = QFileDialog.getSaveFileName(self, "Save a copy", start, PDF_FILTER)
        if not p:
            return False
        return self.copy_to(p)

    def copy_to(self, new):
        """Writes the PDF with its highlights to `new` and goes on with that file (the original is left as it was on disk)."""
        if not new.lower().endswith(".pdf"):
            new += ".pdf"
        try:
            pio.save_copy(self.doc, new)
            doc = pio.open_pdf(new)
        except (pio.SaveError, ValueError) as ex:
            self.status.say("Could not save the copy: " + str(ex), "bad")
            return False
        old = self.doc
        self.doc = doc
        self.text.doc = doc
        self.edits.reset(doc)
        self.view.images.clear()
        self.remember()
        self.path = os.path.abspath(new)
        self.auto_sw.blockSignals(True)
        self.auto_sw.setChecked(self.store.auto(self.path))
        self.auto_sw.blockSignals(False)
        try:
            old.close()
        except Exception:                                        # noqa: BLE001
            pass
        self.view.sheet.update()
        self.status.say("Saved a copy: " + self.path, "good")
        self.sync()
        return True

    def request_pages(self):
        if self.edits.dirty:
            self.write(interactive=False)
        self.pages_requested.emit(self.path)

    def shutdown(self):
        """The tab is closing: stop the voice, remember where you were, let go of the file."""
        self.build_timer.stop()
        if self.hub.owner is self:
            self.hub.stop()
        self.pump_timer.stop()
        try:
            self.remember()
        except Exception:                                        # noqa: BLE001
            pass
        try:
            self.doc.close()
        except Exception:                                        # noqa: BLE001
            pass

    def keyPressEvent(self, ev):
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if ctrl and ev.key() == Qt.Key.Key_S:
            self.save()
        elif ctrl and ev.key() == Qt.Key.Key_Z:
            self.undo()
        elif ctrl and ev.key() == Qt.Key.Key_Y:
            self.redo()
        else:
            super().keyPressEvent(ev)
