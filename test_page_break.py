"""Page Break (dev_addons/page_break): breaks, segments, exclusion, undo, auto-break, combining PDFs, export sizes, project file, the tab, manifest."""
import faulthandler
import json
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "page_break"), os.path.join(HERE, "shared"), HERE]
import pb_core as core
import pymupdf as fitz

T = tempfile.mkdtemp(prefix="opara_pb_")


def make_pdf(path, sizes):
    d = fitz.open()
    for i, (w, h) in enumerate(sizes):
        p = d.new_page(width=w, height=h)
        y = 40
        while y < h - 20:
            p.insert_text((30, y), f"p{i + 1} line at y={int(y)}", fontsize=12)
            y += 60
    d.save(path)
    d.close()


tall = os.path.join(T, "tall.pdf")
other = os.path.join(T, "other.pdf")
make_pdf(tall, [(612, 2000), (612, 792)])          # a very tall page and a normal one
make_pdf(other, [(400, 600)])

# ---------------------------------------------------------------- 1. the core
sc, w, h = core.display_scale(612, 792)
assert abs(sc - 760 / 612) < 1e-9 and w == 760 and h == round(792 * sc)
s2, w2, h2 = core.display_scale(612, 792, 4.0)
assert h2 <= core.HARD_MAX_PX and s2 > sc
_, w3, h3 = core.display_scale(612, 200000, 1.0)
assert h3 <= core.HARD_MAX_PX, "an absurdly tall page is capped"

pr = core.Project()
items = pr.import_pdf(tall)
assert len(items) == 2 and items[0].total == 2 and items[0].caption() == "tall.pdf - page 1 of 2"
a, b = items
assert pr.output_count() == 2, "no breaks: one output page per source page"
sc = 1.0
assert pr.break_at(a, 500, sc) == "added" and a.breaks == [500]
assert pr.break_at(a, 1200, sc) == "added" and a.breaks == [500, 1200]
assert pr.break_at(a, 504, sc) == "removed" and a.breaks == [1200], "a click within the snap distance removes"
assert pr.break_at(a, 2, sc) is None and pr.break_at(a, 1998, sc) is None, "no break at the very edge"
assert pr.break_at(a, 1200, sc) == "removed" and a.breaks == []
pr.break_at(a, 700, sc); pr.break_at(a, 1400, sc)
assert [round(s["to"] - s["from"]) for s in a.segments()] == [700, 700, 600]
assert pr.output_count() == 4
assert pr.toggle_exclude(a, 1) is True and pr.output_count() == 3
nums = [(s["out_index"]) for _it, segs in pr.numbered() for s in segs]
assert nums == [1, None, 2, 3], nums
pr.break_at(a, 100, sc)                    # a new break elsewhere keeps the excluded segment excluded
assert [s["excluded"] for s in a.segments()] == [False, False, True, False]
assert pr.undo() and a.breaks == [700, 1400] and pr.redo() and a.breaks == [100, 700, 1400]
pr.undo()
# auto break
pr.auto_break(11)                          # every 792 pt
assert a.breaks == [792, 1584] and b.breaks == [], "792 pt page: no break at its end"
for bad in (0, -3, float("nan")):
    try:
        pr.auto_break(bad); raise SystemExit("should be refused")
    except core.PageBreakError:
        pass
pr.clear_breaks()
assert a.breaks == [] and not a.excluded

# combining and ordering
pr.import_pdf(other)
assert [it.source.name for it in pr.items] == ["tall.pdf", "tall.pdf", "other.pdf"]
c = pr.items[2]
assert pr.move(c, -1) and pr.items[1] is c and not pr.move(pr.items[0], -1)
assert pr.suggested_name() == "combined.pdf"
pr.remove(pr.items[0]); pr.remove(pr.items[0])
assert pr.suggested_name() == "tall-split.pdf" and pr.items == [b]
assert pr.undo() and pr.undo() and len(pr.items) == 3 and pr.items[0] is a

# export: a tall page broken at 792 and 1584 gives three pages of those heights
pr.auto_break(11)
n = pr.export(os.path.join(T, "out.pdf"))
d = fitz.open(os.path.join(T, "out.pdf"))
heights = [round(p.rect.height) for p in d]
assert n == len(d) and heights[:3] == [792, 792, 416] and all(round(p.rect.width) in (612, 400) for p in d), heights
t1 = d[0].get_text()
assert "p1 line at y=40" in t1 and "y=820" not in t1, "the first piece holds the top of the page only"
assert "y=820" in d[1].get_text() or "y=880" in d[1].get_text(), d[1].get_text()[:80]
d.close()
# an excluded segment is left out
a2 = [it for it in pr.items if it.page_index == 0 and it.width_pt == 612][0]
pr.toggle_exclude(a2, 1)
assert pr.export(os.path.join(T, "out2.pdf")) == n - 1
for it in pr.items:
    for i in range(len(it.segments())):
        if not it.segments()[i]["excluded"]:
            pr.toggle_exclude(it, i)
try:
    pr.export(os.path.join(T, "out3.pdf")); raise SystemExit("everything excluded must be refused")
except core.PageBreakError:
    pass
try:
    core.Project().export(os.path.join(T, "x.pdf")); raise SystemExit("empty must be refused")
except core.PageBreakError:
    pass

# bad files
junk = os.path.join(T, "junk.pdf"); open(junk, "wb").write(b"not a pdf at all")
try:
    core.Project().import_pdf(junk); raise SystemExit("junk must be refused")
except core.PageBreakError as e:
    assert "open" in str(e).lower()
enc = os.path.join(T, "locked.pdf")
dd = fitz.open(); dd.new_page(); dd.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y"); dd.close()
try:
    core.Project().import_pdf(enc); raise SystemExit("a password-protected PDF must be refused")
except core.PageBreakError as e:
    assert "password" in str(e).lower()

# project file
pr2 = core.Project()
pr2.import_pdf(tall); pr2.import_pdf(other)
pr2.break_at(pr2.items[0], 700, 1.0); pr2.toggle_exclude(pr2.items[0], 1); pr2.move(pr2.items[2], -2)
js = json.loads(json.dumps(pr2.to_json(1.5, "9")))
pr3 = core.Project()
assert pr3.load_json(js) == []
assert [(it.source.name, it.page_index) for it in pr3.items] == [(it.source.name, it.page_index) for it in pr2.items]
assert [it.breaks for it in pr3.items] == [it.breaks for it in pr2.items] and [it.excluded for it in pr3.items] == [it.excluded for it in pr2.items]
js["pages"][0]["source"] = os.path.join(T, "gone.pdf")
assert core.Project().load_json(js) == [os.path.join(T, "gone.pdf")]
try:
    core.read_project(tall.replace(".pdf", ".json")); raise SystemExit
except OSError:
    pass
open(os.path.join(T, "bad.oppb"), "w").write('{"format": "something else"}')
try:
    core.read_project(os.path.join(T, "bad.oppb")); raise SystemExit("a foreign file must be refused")
except core.PageBreakError:
    pass

# ---------------------------------------------------------------- 2. the tab
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication([])
MSGS = []
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import page_break_tab as pt

tab = pt.make_tab()
tab.resize(1300, 800)
tab.show()
app.processEvents()
assert tab.views.currentWidget() is tab.empty and not tab.b_export.isEnabled() and tab.stats_lbl.text() == "Nothing to export yet."
items = tab.import_path(tall)
app.processEvents()
assert len(items) == 2 and tab.views.currentWidget() is tab.scroll and tab.is_dirty()
assert tab.stats_lbl.text().endswith("2 output page(s)") and tab.b_export.isEnabled()
assert tab.import_path(junk) == [] and MSGS and "open" in MSGS[-1].lower()
cv = tab.blocks[items[0].id].canvas
assert cv.height() == core.display_scale(612, 2000)[2] and cv.ensure_image() and cv.image.width() == cv.width()

# a real mouse click on the page: a break; click on it again: removed
sc = cv.scale
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=QPoint(100, int(700 * sc)))
assert items[0].breaks and abs(items[0].breaks[0] - 700) < 1 and tab.stats_lbl.text().endswith("3 output page(s)")
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=QPoint(300, int(700 * sc) + 3))
assert items[0].breaks == []
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=QPoint(100, int(700 * sc)))
# a click on a segment label excludes it
segs = cv.segments()
r = cv.label_rect(segs[0])
assert r is not None
QTest.mouseClick(cv, Qt.MouseButton.LeftButton, pos=r.center().toPoint())
assert items[0].breaks and len(items[0].breaks) == 1, "the label click does not add a break"
assert [s["excluded"] for s in cv.segments()] == [True, False] and "excluded" in cv.label_text(cv.segments()[0])
assert tab.stats_lbl.text().endswith("2 output page(s)")
# the pixels of an overlaid page are painted without an error
img = cv.grab().toImage()
assert img.width() == cv.width()
tab.undo(); tab.undo()
assert items[0].breaks == [] or abs(items[0].breaks[0] - 700) < 1
# auto-break from the panel
tab.auto_inches.setText("5"); assert tab.auto_break() and len(items[0].breaks) == 5
tab.auto_inches.setText("abc"); assert not tab.auto_break()
tab.auto_inches.setText("11"); assert tab.auto_break() and len(items[0].breaks) == 2
# zoom
tab.set_zoom(2.0)
assert abs(cv.scale - core.display_scale(612, 2000, 2.0)[0]) < 1e-9 and tab.zoom_lbl.text() == "200%" and cv.image is None
tab.fit_width(); tab.set_zoom(1.0)
# import more, move, remove
tab.import_path(other)
assert len(tab.project.items) == 3
tab.move_page(tab.project.items[2], -1)
order = [tab.col.itemAt(i).widget().item for i in range(tab.col.count()) if tab.col.itemAt(i).widget()]
assert order == tab.project.items, "the page list on screen follows the project order"
tab.remove_page(tab.project.items[1])
assert len(tab.blocks) == 2
# many pages: the image cache stays small
many = os.path.join(T, "many.pdf"); make_pdf(many, [(612, 792)] * 30)
tab.import_path(many)
for blk in list(tab.blocks.values()):
    blk.canvas.ensure_image()
assert len(tab.images) <= tab.MAX_CACHED_IMAGES and sum(1 for b in tab.blocks.values() if b.canvas.image is not None) <= tab.MAX_CACHED_IMAGES

# export through the tab (dialog stubbed)
tab.new(); assert not tab.project.items and tab.views.currentWidget() is tab.empty
tab.import_path(tall); tab.auto_break()
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(T, "fromtab"), ""))
n = tab.export_dialog()
assert n == 4 and len(fitz.open(os.path.join(T, "fromtab.pdf"))) == 4, n     # (3 + 1 pages)
# project save / open through the tab
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(T, "proj"), ""))
assert tab.save() and tab.path.endswith("proj.oppb") and not tab.is_dirty()
tab2 = pt.make_tab(tab.path)
assert [it.breaks for it in tab2.project.items] == [it.breaks for it in tab.project.items] and not tab2.is_dirty() and len(tab2.blocks) == 2
tab2.open_path(tall); assert len(tab2.project.items) == 4, "a PDF given to open_path is imported"
assert not tab2.open_path(os.path.join(T, "bad.oppb"))

# ---------------------------------------------------------------- 3. the manifest
man = json.load(open(os.path.join(HERE, "dev_addons", "page_break", "addon.json")))
t0 = man["tabs"][0]
assert t0["kind"] == "pagebreak" and t0["module"] == "page_break_tab" and t0["factory"] == "make_tab" and ".oppb" in t0["file_types"]
# ---------------------------------------------------------------- 4. PyMuPDF missing: downloaded once into the user folder, then everything works
import shutil
import pb_deps, pymupdf
from PyQt6.QtTest import QTest as _QT
site = pb_deps.site_dir()
assert site.startswith(UD) and not os.path.isdir(site)
CALLS = []


def fake_installer(pins, target, progress):
    CALLS.append((list(pins), target))
    if progress:
        progress("Downloading pymupdf ...", None)
    os.makedirs(target, exist_ok=True)
    shutil.copytree(os.path.dirname(pymupdf.__file__), os.path.join(target, "pymupdf"))


def offline_installer(pins, target, progress):
    CALLS.append(("offline",))
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "half-written.txt"), "w").write("x")
    raise RuntimeError("Downloading the packages failed (needs an internet connection)")


def wait(tab_, seconds=30):
    for _ in range(seconds * 20):
        app.processEvents()
        if not tab_.setup_busy:
            break
        _QT.qWait(50)
    app.processEvents()


real_fitz = core.fitz
core.fitz = None                                         # as on a computer that has no PyMuPDF
assert not core.available()
try:
    core.Project().import_pdf(tall); raise SystemExit("without PyMuPDF an import must say so")
except core.PageBreakError as e:
    assert "PyMuPDF" in str(e)

pt.PageBreakTab.installer = staticmethod(offline_installer)
tabx = pt.make_tab(os.path.join(T, "proj.oppb"))
tabx.resize(1000, 700); tabx.show()
wait(tabx)
assert tabx.views.currentWidget() is tabx.setup and tabx.setup_retry.isVisibleTo(tabx.setup) and "internet" in tabx.setup_text.text()
assert not os.path.isdir(site) and not os.path.isdir(site + ".new"), "a failed download leaves nothing half-installed"
assert tabx.import_path(tall) == [] and "PyMuPDF" in tabx.status.text(), "no import while PyMuPDF is missing"
pt.PageBreakTab.installer = staticmethod(fake_installer)
tabx.setup_retry.click()
wait(tabx)
assert core.available() and tabx.views.currentWidget() in (tabx.empty, tabx.scroll), tabx.setup_text.text()
assert CALLS[-1][0] == [pb_deps.PIN] and os.path.isdir(os.path.join(site, "pymupdf")) and site in sys.path
assert tabx.project.items, "the project file that was asked for opens as soon as PyMuPDF is there"
assert len(tabx.import_path(tall)) == 2
n_calls = len(CALLS)
tab_again = pt.make_tab()                                # a later start: nothing to download
assert len(CALLS) == n_calls and tab_again.views.currentWidget() is tab_again.empty
core.fitz = real_fitz
pt.PageBreakTab.installer = None
print("OK test_page_break")
