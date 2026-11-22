"""PDF editor, the reader tab (dev_addons/pdf_editor/pe_reader.py, pe_view.py), with a voice of its own that only records what it is told to say:
click a sentence = the marker; Play starts there; Pause goes on in the middle of the sentence and the marker does not move; Stop leaves the marker on the
sentence; scrolling does not move it; double-click reads from there; the step buttons; selecting and highlighting; Save, the switch that saves each
highlight by itself, a save that fails; where you were is remembered; a PDF with no text; the voice support that is downloaded the first time."""
import faulthandler
import os
import sys
import tempfile
import time

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pymupdf

import pe_deps
import pe_pdfio as pio
import pe_reader
import pe_speech
import pe_store

T = tempfile.mkdtemp(prefix="opara_pe_")


def make_pdf(path, pages, per_page=8):
    d = pymupdf.open()
    n = 0
    for _ in range(pages):
        p = d.new_page()
        y = 80
        for _k in range(per_page):
            n += 1
            p.insert_text((72, y), f"This is sentence number {n} of the test book. It has a second part.", fontsize=12)
            y += 30
    d.save(path)
    d.close()


book = os.path.join(T, "book.pdf")
make_pdf(book, 4)


class Engine:
    log = []

    def __init__(self, ms):
        self.ms, self.left, self.paused = ms, 0.0, False

    def apply(self, voice, rate, volume):
        pass

    def speak(self, text):
        Engine.log.append(text)
        self.left = self.ms / 1000

    def purge(self):
        self.left = 0.0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def wait(self, ms):
        time.sleep(ms / 1000)
        if not self.paused:
            self.left -= ms / 1000
        return self.left <= 0

    def close(self):
        pass


class Backend:
    ms = 700
    names = ["Test David", "Test Zira"]

    def available(self):
        return bool(self.names)

    def list_voices(self):
        return list(self.names)

    def engine(self):
        return Engine(self.ms)


def pause_ms(ms):
    t0 = time.time()
    while time.time() - t0 < ms / 1000:
        app.processEvents()
        QTest.qWait(20)


def until(cond, seconds=10):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if cond():
            return True
        QTest.qWait(20)
    raise SystemExit("timed out: " + str(cond))


def make_reader(path=book, backend=None, hub=None, store=None):
    hub = hub or pe_speech.Hub(backend or Backend())
    store = store or pe_store.Store()
    r = pe_reader.ReaderTab(path, hub, store)
    r.resize(1200, 800)
    r.show()
    until(lambda: r.text.ready)
    pause_ms(60)
    return r


def click_at(r, sentence, button=Qt.MouseButton.LeftButton):
    pno, rc = r.text.sentence_rects(sentence)[0]
    r.view.ensure_visible(sentence)
    app.processEvents()
    q = r.view.to_sheet(pno, rc).center().toPoint()
    QTest.mouseClick(r.view.sheet, button, Qt.KeyboardModifier.NoModifier, q)
    return q


r = make_reader()
v = r.view
S = r.text.sentence_texts
assert len(S) == 64 and r.banner.isHidden() and "4 page(s), 64 sentence(s)" in r.info_lbl.text(), (len(S), r.info_lbl.text())
assert r.voice_box.count() == 2 and r.voice_box.currentText() == "Test David" and r.hub.voice_name == "Test David"
assert 0.4 <= v.zoom <= 4.0 and r.zoom_lbl.text().endswith("%"), "a PDF with no saved place is fitted to the window"
assert not r.is_dirty() and r.title() == "book.pdf" and not r.b_save.isEnabled()
# the page is really drawn: white page, the marker in amber
img = v.sheet.grab().toImage()
assert img.width() == v.content_w, "the sheet is as wide as the window or the page"

# ---------------------------------------------------------------- 1. choosing where to start
assert v.start_sentence() == 0, "no marker: the first sentence at the top of the window"
v.scroll_to_page(2)
app.processEvents()
top_sentence = v.start_sentence()
assert top_sentence is not None and top_sentence >= 32 - 2, "no marker: Play begins at the top of what is on screen (page 3)"
v.scroll_to_page(0)
app.processEvents()
click_at(r, 11)
assert v.read_idx == 11 and "Sentence 12 of 64" in r.status.text(), r.status.text()
scroll_before = v.verticalScrollBar().value()
v.scroll_to_page(3)
app.processEvents()
assert v.read_idx == 11 and v.start_sentence() == 11, "scrolling does not move the marker"
QTest.mouseClick(v.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2))
assert v.read_idx == 11, "a click on the empty margin keeps the marker"
v.scroll_to_page(0)

# ---------------------------------------------------------------- 2. start, pause, resume, stop - all at the same point
Engine.log.clear()
r.toggle_play()
until(lambda: len(Engine.log) >= 1)
assert Engine.log[0] == S[11] and r.hub.reading(r) and r.b_play.text().endswith("Pause"), "Play starts at the marker: " + Engine.log[0]
until(lambda: v.read_idx == 12)
r.toggle_play()                                          # pause
assert r.hub.paused and r.b_play.text().endswith("Resume")
paused_at = v.read_idx
spoken = len(Engine.log)
v.scroll_to_page(3)                                      # looking elsewhere while it is paused
pause_ms(1200)
assert v.read_idx in (paused_at, paused_at + 1) and len(Engine.log) <= spoken + 1, "paused: nothing goes on"
held = v.read_idx
pause_ms(900)
assert v.read_idx == held, "paused: the marker stays where it is"
r.toggle_play()                                          # resume
assert not r.hub.paused
until(lambda: v.read_idx == held + 1)
r.stop_reading()
assert not r.hub.reading(r) and r.b_play.text().endswith("Play")
stopped_at = v.read_idx
assert stopped_at == held + 1, "Stop leaves the marker on the sentence that was being read"
Engine.log.clear()
v.scroll_to_page(0)
r.toggle_play()
until(lambda: len(Engine.log) >= 1)
assert Engine.log[0] == S[stopped_at], "Play after Stop starts that sentence again, wherever the window is looking: " + Engine.log[0]
r.stop_reading()

# ---------------------------------------------------------------- 3. double-click and the step buttons
Engine.log.clear()
pno, rc = r.text.sentence_rects(20)[0]
v.ensure_visible(20)
app.processEvents()
QTest.mouseDClick(v.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, v.to_sheet(pno, rc).center().toPoint())
until(lambda: len(Engine.log) >= 1)
assert Engine.log[0] == S[20] and v.read_idx == 20, "double-click reads from that sentence at once"
r.step(1)
until(lambda: Engine.log[-1] == S[21])
assert v.read_idx == 21 and r.hub.reading(r), "next sentence while reading: it goes on from there"
r.step(-2)
until(lambda: Engine.log[-1] == S[19])
r.stop_reading()
r.step(-1)
assert v.read_idx == 18 and not r.hub.reading(r), "stopped: the buttons only move the marker"
r.step(-1000); assert v.read_idx == 0
r.step(1000); assert v.read_idx == 63
v.set_read(5)
QTest.keyClick(v, Qt.Key.Key_Right)
assert v.read_idx == 6, "the arrow keys step too"
QTest.keyClick(v, Qt.Key.Key_Left); QTest.keyClick(v, Qt.Key.Key_Left)
assert v.read_idx == 4
Engine.log.clear()
QTest.keyClick(v, Qt.Key.Key_Space)
until(lambda: len(Engine.log) >= 1)
assert Engine.log[0] == S[4] and r.hub.reading(r), "Space is Play"
QTest.keyClick(v, Qt.Key.Key_Space)
assert r.hub.paused
r.stop_reading()
# the end: the voice says so
Backend.ms = 80
v.set_read(62)
r.toggle_play()
until(lambda: not r.hub.running and "Finished" in r.status.text())
Backend.ms = 700
assert r.b_play.text().endswith("Play") and r.hub.owner is None

# ---------------------------------------------------------------- 4. selecting and highlighting
r.status.say("")
pno, rc0 = r.text.sentence_rects(0)[0]
pno, rc1 = r.text.sentence_rects(1)[0]
v.scroll_to_page(0); app.processEvents()
q0 = v.to_sheet(pno, rc0).center().toPoint()
q1 = v.to_sheet(pno, rc1).center().toPoint()
assert all(not b.isEnabled() for b in r.colour_buttons), "no selection: the colour buttons wait"
QTest.mousePress(v.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q0)
QTest.mouseMove(v.sheet, QPoint(q1.x() - 10, q1.y()))
QTest.mouseMove(v.sheet, q1)
QTest.mouseRelease(v.sheet, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q1)
assert v.sel is not None and v.popup is not None and all(b.isEnabled() for b in r.colour_buttons), "a drag selects; the colours and a pop-up appear"
a, b = v.sel
assert a <= r.text.sentences[0][1] and b >= r.text.sentences[1][0], v.sel
n0 = r.edits.count()
pages = r.highlight_selection("Green")
assert pages == [0] and r.edits.count() == n0 + 1 and r.is_dirty() and r.title() == "book.pdf *" and v.sel is None and v.popup is None
assert r.b_save.isEnabled() and r.b_undo.isEnabled() and not r.b_redo.isEnabled()
assert "highlight(s)" in r.highlight_summary()
img = v.sheet.grab().toImage()
assert any(img.pixelColor(x, y).green() > img.pixelColor(x, y).red() + 40 for x in range(100, 500, 7) for y in range(40, 400, 7)), "the highlight is drawn"
assert r.undo() and r.edits.count() == n0 and not r.is_dirty(), "undo back to the saved state: not changed any more"
assert r.redo() and r.is_dirty()
assert r.save() and not r.is_dirty() and pio.Edits(pio.open_pdf(book)).count() == n0 + 1, "Save writes the highlight into the PDF"
# remove it again (the right-click menu's action)
xref = r.edits.find(0, (rc0[0] + rc0[2]) / 2, (rc0[1] + rc0[3]) / 2)
assert xref and r.remove_highlight(0, xref) and r.is_dirty() and r.edits.count() == n0
assert r.save() and pio.Edits(pio.open_pdf(book)).count() == n0
# Ctrl+Z and Ctrl+Y
assert r.undo() and r.is_dirty()
QTest.keyClick(v, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
assert r.edits.count() == n0
r.save()
# copy text
v.sel = (0, 3)
r.copy_selection()
assert QApplication.clipboard().text() == r.text.text_for_tokens(0, 3) and v.sel is None
r.highlight_selection("Pink")
assert "Drag across some text" in r.status.text(), "a colour without a selection says what to do"

# ---------------------------------------------------------------- 5. the switch: each highlight is written by itself
assert not r.auto_sw.isChecked() and not r.store.auto(r.path)
r.auto_sw.setChecked(True)
assert r.store.auto(r.path) and pe_store.Store().auto(r.path), "remembered for this PDF, in the file"
size0 = os.path.getsize(book)
v.sel = (0, 5)
r.highlight_selection("Yellow")
assert not r.is_dirty() and pio.Edits(pio.open_pdf(book)).count() == n0 + 1 and os.path.getsize(book) > size0, "on: written right after the highlight"
r.undo()
assert not r.is_dirty() and pio.Edits(pio.open_pdf(book)).count() == n0, "and right after an undo"
r.redo()
assert pio.Edits(pio.open_pdf(book)).count() == n0 + 1
r.auto_sw.setChecked(False)
assert not pe_store.Store().auto(r.path)
v.sel = (6, 9)
r.highlight_selection("Blue")
assert r.is_dirty() and pio.Edits(pio.open_pdf(book)).count() == n0 + 1, "off: it waits for Save"
r.auto_sw.setChecked(True)
assert not r.is_dirty() and pio.Edits(pio.open_pdf(book)).count() == n0 + 2, ("turning it on writes what was waiting", r.is_dirty(), pio.Edits(pio.open_pdf(book)).count(), n0, r.status.text())
r.auto_sw.setChecked(False)

# ---------------------------------------------------------------- 6. a save that fails
real_save = pio.save_in_place


def locked(doc):
    raise pio.SaveError("The file is locked or read-only (is it open in another program?).")


pio.save_in_place = locked
asked = []
r.ask_copy = lambda why: (asked.append(why), False)[1]
v.sel = (10, 12)
r.highlight_selection("Yellow")
assert r.is_dirty() and not asked
r.auto_sw.setChecked(True)
v.sel = (14, 16)
r.highlight_selection("Pink")
assert r.is_dirty() and not asked and "locked" in r.status.text() and "kept" in r.status.text(), "the automatic save never opens a window; the highlights are kept"
r.auto_sw.setChecked(False)
assert r.save() is False and len(asked) == 1 and r.is_dirty(), "Save asks about a copy, and says no"
copy = os.path.join(T, "book - highlighted.pdf")
pe_reader.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (copy, ""))
r.ask_copy = lambda why: True
assert r.save() and r.path == copy and not r.is_dirty() and os.path.isfile(copy), "a copy is made and the tab goes on with it"
assert pio.Edits(pio.open_pdf(copy)).count() == n0 + 4, pio.Edits(pio.open_pdf(copy)).count()
assert r.title() == "book - highlighted.pdf" and not r.auto_sw.isChecked() and v.read_idx is not None
pio.save_in_place = real_save
assert not r.edits.undo_stack, "the history starts again with the copy"
r.shutdown()

# ---------------------------------------------------------------- 7. where you were is remembered
r1 = make_reader(book)
r1.view.set_zoom(1.7)
click_at(r1, 40)
r1.remember()
r1.shutdown()
r2 = make_reader(book)
until(lambda: abs(r2.view.zoom - 1.7) < 1e-6 and r2.view.read_idx == 40)
assert r2.view.start_sentence() == 40 and r2.view.verticalScrollBar().value() > 0, "the zoom, the marker and the place on the page come back"
assert 'Sentence 41 of 64' in r2.status.text() or r2.status.full == "", r2.status.text()
r2.shutdown()

# ---------------------------------------------------------------- 8. one voice for every PDF
hub = pe_speech.Hub(Backend())
ra, rb = make_reader(book, hub=hub), make_reader(copy, hub=hub)
ra.view.set_read(3)
ra.toggle_play()
until(lambda: hub.reading(ra))
rb.view.set_read(5)
rb.toggle_play()
until(lambda: hub.reading(rb))
assert not hub.reading(ra) and hub.owner is rb
ra.sync()
assert ra.b_play.text().endswith("Play") and rb.b_play.text().endswith("Pause"), "starting in one PDF stops the other"
rb.shutdown()
assert not hub.running and hub.owner is None, "closing the PDF that is reading stops the voice"
ra.shutdown()

# ---------------------------------------------------------------- 9. a PDF with no text
scan = os.path.join(T, "scan.pdf")
d = pymupdf.open(); d.new_page(); d.save(scan); d.close()
rs = make_reader(scan)
assert not rs.banner.isHidden() and "no selectable text" in rs.banner_lbl.text() and rs.view.start_sentence() is None
asked_images = []
rs.images_requested.connect(lambda: asked_images.append(1))
rs.banner.findChildren(type(rs.b_save))[0].click()
assert asked_images, "the banner offers Images → PDF"
rs.toggle_play()
assert "no text" in rs.status.text() and not rs.hub.running
rs.shutdown()

# ---------------------------------------------------------------- 10. no voice yet: the support is downloaded the first time Play is pressed
Backend.names = []
hub = pe_speech.Hub(Backend())
rv = make_reader(book, hub=hub)
assert rv.voice_box.count() == 0 and not rv.voice_box.isEnabled() and not rv.voice_note.isHidden()
rv.view.set_read(7)
rv.toggle_play()                                          # not Windows: it says so and does nothing else
assert "Windows" in rv.status.text() and not hub.running
real_os = pe_reader.os


class NT:                                                 # as on Windows
    name = "nt"
    path = real_os.path


pe_reader.os = NT
CALLS = []


def fake_install(pins, target, progress):
    CALLS.append(pins)
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "x.txt"), "w").write("x")


pe_reader.ReaderTab.installer = staticmethod(fake_install)
real_ready = pe_deps.voice_ready
pe_deps.voice_ready = lambda: True
Backend.names = ["Test David"]                            # what the voices are once the support is there
Engine.log.clear()
rv.toggle_play()
until(lambda: hub.reading(rv), 15)
assert CALLS and CALLS[0] == pe_deps.VOICE_PINS and rv.voice_box.count() == 1, "downloaded, the voice is found and reading starts where it was asked"
until(lambda: len(Engine.log) >= 1)
assert Engine.log[0] == rv.text.sentence_texts[7]
rv.stop_reading()
pe_deps.voice_ready = real_ready
pe_reader.os = real_os
rv.shutdown()
print("OK test_pdf_editor_reader")
