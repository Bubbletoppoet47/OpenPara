"""PDF editor, the tab (dev_addons/pdf_editor/pe_tab.py): one tab with a tab bar of its own for PDFs and page projects; a file that is already open comes to
the front; the program window hands the PDFs and projects that are opened from anywhere to this tab; stars and closing with unsaved highlights; Cut and
combine from the reader; what was open comes back; one voice for every PDF; PyMuPDF downloaded the first time; the manifest."""
import faulthandler
import json
import os
import shutil
import sys
import tempfile
import time

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

app = QApplication([])
import pymupdf

import page_break_tab as pbt
import pb_core as core
import pb_deps
import pe_pdfio as pio
import pe_reader
import pe_speech
import pe_tab

T = tempfile.mkdtemp(prefix="opara_pe_")


def make_pdf(path, pages, tag):
    d = pymupdf.open()
    for i in range(pages):
        p = d.new_page()
        for k in range(6):
            p.insert_text((72, 80 + 30 * k), f"{tag} page {i + 1} sentence {k + 1} is here. A second part follows.", fontsize=12)
    d.save(path)
    d.close()


one, two = os.path.join(T, "one.pdf"), os.path.join(T, "two.pdf")
make_pdf(one, 3, "First"); make_pdf(two, 2, "Second")


class Engine:
    log = []

    def __init__(self):
        self.left, self.paused = 0.0, False

    def apply(self, voice, rate, volume):
        pass

    def speak(self, text):
        Engine.log.append(text)
        self.left = 0.6

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
    def available(self):
        return True

    def list_voices(self):
        return ["Test Voice"]

    def engine(self):
        return Engine()


def until(cond, seconds=10):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if cond():
            return True
        QTest.qWait(20)
    raise SystemExit("timed out")


pe_tab.PdfEditorTab.backend = Backend()
warnings = []


def new_tab(path=None):
    t = pe_tab.make_tab(path)
    t.warn = lambda text: warnings.append(text)
    t.resize(1200, 800)
    t.show()
    app.processEvents()
    return t


# ---------------------------------------------------------------- 1. open, switch, one tab per file
t = new_tab()
assert t.stack.currentWidget() is t.empty and t.title() == "PDF editor" and t.path is None and not t.is_dirty() and t.reopen_btn.isHidden()
ra = t.open_path(one)
until(lambda: ra.text.ready)
assert isinstance(ra, pe_reader.ReaderTab) and t.stack.currentWidget() is t.tabs and t.tabs.count() == 1
assert t.path == one and t.title() == "one.pdf" and t.tabs.tabText(0) == "one.pdf"
rb = t.open_path(two)
until(lambda: rb.text.ready)
assert t.tabs.count() == 2 and t.path == two and t.tabs.currentWidget() is rb
assert t.open_path(one) is ra and t.tabs.count() == 2 and t.path == one, "a file that is open comes to the front, it is not opened twice"
assert t.adopt_path(two) and t.path == two and t.tabs.count() == 2, "a PDF opened from anywhere in the program lands here"
assert not t.adopt_path(os.path.join(T, "part.gpd")) and not t.adopt_path("notes.txt"), "files of other kinds are left to the program"
assert t.open_path(os.path.join(T, "missing.pdf")) is None and "not there" in warnings[-1]
bad = os.path.join(T, "bad.pdf"); open(bad, "w").write("not a pdf")
assert t.open_path(bad) is None and "bad.pdf" in warnings[-1] and t.tabs.count() == 2
open(os.path.join(T, "x.txt"), "w").write("x")
assert t.open_path(os.path.join(T, "x.txt")) is None and "not a PDF" in warnings[-1]

# ---------------------------------------------------------------- 2. stars, saving, closing
t.tabs.setCurrentWidget(ra)
ra.view.sel = (0, 3)
ra.highlight_selection("Yellow")
until(lambda: t.tabs.tabText(0) == "one.pdf *")
assert t.is_dirty() and t.title() == "one.pdf" and ra.is_dirty()
assert t.save() and not t.is_dirty() and pio.Edits(pio.open_pdf(one)).count() == 1
until(lambda: t.tabs.tabText(0) == "one.pdf")
ra.view.sel = (0, 5)
ra.highlight_selection("Pink")
asked = []
t.ask_save = lambda w: (asked.append(w), "cancel")[1]
assert t.close_inner(0) is False and t.tabs.count() == 2 and asked == [ra], "Cancel keeps the PDF open"
t.ask_save = lambda w: "discard"
assert t.close_inner(0) is True and t.tabs.count() == 1 and pio.Edits(pio.open_pdf(one)).count() == 1, "Discard leaves the file as it was"
ra = t.open_path(one)
until(lambda: ra.text.ready)
ra.view.sel = (0, 5)
ra.highlight_selection("Pink")
t.ask_save = lambda w: "save"
assert t.close_inner(t.tabs.indexOf(ra)) is True and pio.Edits(pio.open_pdf(one)).count() == 2, "Save writes the highlights first"
ra = t.open_path(one)
until(lambda: ra.text.ready)

# ---------------------------------------------------------------- 3. page projects: Cut and combine
n0 = t.tabs.count()
proj = t.new_project()
assert isinstance(proj, pbt.PageBreakTab) and t.tabs.count() == n0 + 1 and t.tabs.tabText(t.tabs.indexOf(proj)) == "Page project"
assert t.path is None and t.title() == "PDF editor"
ra.pages_requested.emit(ra.path)                              # "Cut and combine its pages..." in the reader
until(lambda: len(proj.project.items) == 3)
assert t.tabs.currentWidget() is proj and t.tabs.count() == n0 + 1, "added to the page project that was used last"
until(lambda: t.tabs.tabText(t.tabs.indexOf(proj)) == "Page project *")
assert t.is_dirty()
oppb = os.path.join(T, "pages.oppb")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (oppb, ""))
assert t.save(as_new=True) and os.path.isfile(oppb) and t.path == oppb and t.title() == "pages.oppb"
until(lambda: t.tabs.tabText(t.tabs.indexOf(proj)) == "pages.oppb")
assert not t.is_dirty()
assert t.open_path(oppb) is proj and t.adopt_path(oppb), "a project that is open comes to the front"
t.close_inner(t.tabs.indexOf(proj))
p2 = t.open_path(oppb)
assert isinstance(p2, pbt.PageBreakTab) and len(p2.project.items) == 3, "a .oppb file opens as a page project"
assert t.last_project is p2
ra.pages_requested.emit(two)
until(lambda: len(p2.project.items) == 5)

# ---------------------------------------------------------------- 4. one voice for every PDF
ra = t.open_path(one); rb = t.open_path(two)
until(lambda: ra.text.ready and rb.text.ready)
ra.view.set_read(2); ra.toggle_play()
until(lambda: t.hub.reading(ra))
rb.view.set_read(4); rb.toggle_play()
until(lambda: t.hub.reading(rb))
assert not t.hub.reading(ra) and t.hub.owner is rb
t.shutdown()
assert not t.hub.running, "closing the tab stops the voice"
saved = pe_tab.pe_store.Store()
assert saved.position(two)["sent"] is not None and set(saved.data["open"]) >= {one, two, oppb}, "where you were and what was open are kept"

# ---------------------------------------------------------------- 5. what was open comes back
t2 = new_tab()
assert not t2.reopen_btn.isHidden() and "file(s) from last time" in t2.reopen_btn.text() and t2.stack.currentWidget() is t2.empty
t2.reopen_btn.click()
until(lambda: t2.tabs.count() == len(saved.data["open"]))
assert {w.path for w in t2.widgets()} == set(saved.data["open"])
rr = t2.find(two)
until(lambda: rr.text.ready)
assert rr.view.read_idx == saved.position(two)["sent"], "the marker is where it was"
t2.shutdown()
t3 = new_tab(one)                                             # opened with a file (double-click, or the session of an update): only that one
until(lambda: t3.tabs.count() == 1)
assert t3.path == one and t3.tabs.count() == 1, "opened with a file: only that one"
t3.shutdown()

# ---------------------------------------------------------------- 6. the program window hands files to this tab
import gpd_app

sh = gpd_app.AppShell()
host_tab = pe_tab.make_tab()
host_tab.host = sh
sh.tabs.addTab(host_tab, "PDF editor")
w = sh.open_path(one)
assert w is host_tab and host_tab.find(one) is not None and sh.tabs.count() == 1, "File > Open of a PDF lands in the PDF editor tab"
until(lambda: host_tab.find(one).text.ready)
w = sh.open_path(two)
assert w is host_tab and sh.tabs.count() == 1 and host_tab.tabs.count() == 2
assert sh.open_path(two) is host_tab, "and an open one comes to the front"
assert sh.adopted_by_tab(os.path.join(T, "a.gpd")) is None
sh.tabs.removeTab(0)
host_tab.shutdown()

# an old Page Break folder left behind by an update that could only copy files is not loaded next to the PDF editor
import addons

old_dev = os.environ.get("OPARA_DEV_ADDONS")
fake_dev = os.path.join(T, "dev_addons")
for aid in ("page_break", "pdf_editor"):
    os.makedirs(os.path.join(fake_dev, aid))
    shutil.copy(os.path.join(HERE, "dev_addons", "pdf_editor", "addon.json"), os.path.join(fake_dev, aid, "addon.json"))
os.environ["OPARA_DEV_ADDONS"] = fake_dev
assert addons.dev_ids() == ["pdf_editor"], addons.dev_ids()
if old_dev is None:
    del os.environ["OPARA_DEV_ADDONS"]
else:
    os.environ["OPARA_DEV_ADDONS"] = old_dev

# ---------------------------------------------------------------- 7. the manifest
man = json.load(open(os.path.join(HERE, "dev_addons", "pdf_editor", "addon.json")))
t0 = man["tabs"][0]
assert man["name"] == "PDF editor" and t0["kind"] == "pdfeditor" and t0["module"] == "pe_tab" and t0["factory"] == "make_tab"
assert t0["set_host"] and ".pdf" in t0["file_types"] and ".oppb" in t0["file_types"]
# ---------------------------------------------------------------- 8. PyMuPDF missing: downloaded once, then the file that was asked for opens
# (last on purpose: a finished download makes pb_deps import PyMuPDF afresh, which a process that has used PyMuPDF already cannot take; a real start has not)
real_fitz, real_pio = core.fitz, pio.pymupdf
site = pb_deps.site_dir()
CALLS = []


def fake_installer(pins, target, progress):
    CALLS.append(list(pins))
    if progress:
        progress("Downloading pymupdf ...", None)
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "downloaded.txt"), "w").write("x")      # PyMuPDF itself is already imported by this test: load() finds that one


def offline(pins, target, progress):
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "half.txt"), "w").write("x")
    raise RuntimeError("Downloading the packages failed (needs an internet connection)")


def wait_setup(tab):
    for _ in range(600):
        app.processEvents()
        if not tab.setup_busy:
            break
        QTest.qWait(30)
    app.processEvents()


core.fitz = None
pio.pymupdf = None
pe_tab.PdfEditorTab.installer = staticmethod(offline)
tx = new_tab(one)
wait_setup(tx)
assert tx.stack.currentWidget() is tx.setup and tx.setup_retry.isVisibleTo(tx.setup) and "internet" in tx.setup_text.text()
assert not os.path.isdir(site + ".new") and tx.adopt_path(two) and tx.pending == [one, two], "files wait for PyMuPDF"
pe_tab.PdfEditorTab.installer = staticmethod(fake_installer)
tx.setup_retry.click()
wait_setup(tx)
until(lambda: tx.tabs.count() == 2)
assert core.available() and pio.pymupdf is not None and CALLS[-1] == [pb_deps.PIN] and tx.stack.currentWidget() is tx.tabs
assert [w.path for w in tx.widgets()] == [one, two], "what was asked for opens as soon as PyMuPDF is there"
tx.shutdown()
n = len(CALLS)
ty = new_tab()
assert len(CALLS) == n and ty.stack.currentWidget() is ty.empty, "a later start downloads nothing"
ty.shutdown()
core.fitz, pio.pymupdf = real_fitz, real_pio
pe_tab.PdfEditorTab.installer = None

print("OK test_pdf_editor_tab")
