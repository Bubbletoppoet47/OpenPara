"""PDF editor, Images -> PDF (pe_ocr.py, pe_images.py, the OCR part of pe_deps.py).  The text reader itself (RapidOCR) is replaced by a fake that answers by
the size of the picture, so what is tested is everything around it: lines to paragraphs, joining across pictures, the PDF that is written, the download
of the packages (what is skipped, what is unpacked, what a failure says), and the window: order, names, asking, stopping, errors, opening the result."""
import faulthandler
import os
import shutil
import stat
import sys
import tempfile
import time
import zipfile

faulthandler.dump_traceback_later(150, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
from PIL import Image
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pe_deps
import pe_images
import pe_ocr
import pe_pdfio as pio
import pe_tab

T = tempfile.mkdtemp(prefix="opara_img_")
pymupdf = pio.pymupdf


def until(cond, seconds=15):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if cond():
            return True
        QTest.qWait(20)
    raise SystemExit("timed out")


# ---------------------------------------------------------------- 1. lines -> paragraphs
R = pe_ocr.Row


def lines(*specs):
    """(text, x0, y0, x1) with 20 px high lines."""
    return [R(t, x0, y0, x1, y0 + 20) for t, x0, y0, x1 in specs]


# boxes on one baseline become one line, in reading order
rows = pe_ocr.merge_boxes_into_rows([R("world", 120, 100, 170, 120), R("hello", 20, 101, 100, 121), R("next line", 20, 140, 170, 160)])
assert [r.text for r in rows] == ["hello world", "next line"]

# a paragraph: lines close together join; a gap starts a new one; a hyphen at the end of a line is repaired
paras = pe_ocr.rows_to_paragraphs(lines(("The cat sat on the", 20, 0, 300), ("mat and then wan-", 20, 24, 300), ("dered off.", 20, 48, 120),
                                        ("A new idea starts here", 20, 110, 300), ("and goes on.", 20, 134, 200)))
assert paras == ["The cat sat on the mat and then wandered off.", "A new idea starts here and goes on."], paras
# an indented first line after a finished sentence starts a paragraph even without a gap
paras = pe_ocr.rows_to_paragraphs(lines(("First paragraph runs across the whole width.", 20, 0, 400), ("    Indented second one", 70, 24, 300)))
assert len(paras) == 2, paras
# a short last line that ends a sentence ends the paragraph
paras = pe_ocr.rows_to_paragraphs(lines(("A long line of text that fills the width fully", 20, 0, 400), ("then a short end.", 20, 24, 120),
                                        ("Another paragraph begins", 20, 48, 400)))
assert paras == ["A long line of text that fills the width fully then a short end.", "Another paragraph begins"], paras
assert pe_ocr.rows_to_paragraphs([]) == []

# a paragraph cut by the edge of one photo goes on in the next; a finished one does not
assert pe_ocr.merge_across([["Intro.", "It was cut at the"], ["end of the page.", "Next."]]) == ["Intro.", "It was cut at the end of the page.", "Next."]
assert pe_ocr.merge_across([["Finished."], ["lower case start."]]) == ["Finished.", "lower case start."]
assert pe_ocr.merge_across([[], ["a"], []]) == ["a"]

assert sorted(["photo10.png", "photo2.png", "photo1.png"], key=pe_ocr.natural_key) == ["photo1.png", "photo2.png", "photo10.png"]
assert ".png" in pe_ocr.image_exts() and ".jpg" in pe_ocr.image_exts()

# ---------------------------------------------------------------- 2. the fake reader and real picture files
SCRIPT = {300: ["Chapter one begins with a quiet morning.", "The town was still asleep and the road was", "empty until the first bus passed."],
          400: ["The second picture holds a second page.", "It has two lines."]}
CALLS = []


class Result:
    def __init__(self, texts):
        self.txts = tuple(texts)
        self.boxes = [[[20, 20 + 40 * i], [600, 20 + 40 * i], [600, 50 + 40 * i], [20, 50 + 40 * i]] for i in range(len(texts))]


class FakeEngine:
    delay = 0.0

    def __call__(self, arr):
        CALLS.append(arr.shape)
        time.sleep(self.delay)
        w = arr.shape[1]
        if w not in SCRIPT:
            return Result([]) if w != 999 else None
        return Result(SCRIPT[w])


def make_image(name, width, exif_rotate=False):
    p = os.path.join(T, name)
    Image.new("RGB", (width, 200), "white").save(p)
    return p


pe_ocr.set_engine(FakeEngine())
i1, i2, i10 = make_image("page1.png", 300), make_image("page2.png", 400), make_image("page10.png", 300)
blank = make_image("blank.png", 500)
none_img = make_image("none.png", 999)
rows = pe_ocr.ocr_rows(i1)
assert len(rows) == 3 and rows[0].text.startswith("Chapter one") and rows[0].h == 30
assert pe_ocr.read_paragraphs(i1)[0].startswith("Chapter one begins"), "the picture is turned into paragraphs"
assert pe_ocr.read_paragraphs(blank) == [] and pe_ocr.read_paragraphs(none_img) == [], "no text -> nothing, not an error"
junk = os.path.join(T, "junk.png"); open(junk, "w").write("this is not a picture")
try:
    pe_ocr.read_paragraphs(junk)
    raise SystemExit("a file that is not a picture must be refused")
except ValueError as e:
    assert "junk.png" in str(e) and "could not be opened" in str(e)
big = os.path.join(T, "big.png"); Image.new("RGB", (6400, 300), "white").save(big)
assert pe_ocr.load_image(big).shape[1] == 3200, "huge pictures are shrunk before they are read"

# ---------------------------------------------------------------- 3. the PDF
per = [pe_ocr.read_paragraphs(i1), pe_ocr.read_paragraphs(i2)]
out = os.path.join(T, "made.pdf")
res = pe_ocr.make_pdf(per, out)
assert res[0] == out and res[1] >= 2 and res[2] > 15
d = pymupdf.open(out)
text = d[0].get_text()
assert "Chapter one begins" in text and "second picture" in text and d.metadata["title"] == "made", (text, d.metadata)
d.close()
assert not [f for f in os.listdir(T) if f.endswith(".making.pdf")], "no side file is left behind"
pe_ocr.make_pdf(per, out)                                                       # replacing an existing PDF works
real_replace = os.replace
os.replace = lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "denied"))
try:
    pe_ocr.make_pdf(per, out)
    raise SystemExit("a locked file must be said plainly")
except ValueError as e:
    assert "cannot be replaced" in str(e)
finally:
    os.replace = real_replace
assert not [f for f in os.listdir(T) if f.endswith(".making.pdf")]
many = [["Paragraph number %d has a few words in it so that it takes room." % k for k in range(80)]]
pe_ocr.make_pdf(many, os.path.join(T, "long.pdf"))
assert pymupdf.open(os.path.join(T, "long.pdf")).page_count >= 2, "a long text runs over onto more pages"

# ---------------------------------------------------------------- 4. the download: what is unpacked, what is left out, what a failure says
if os.name == "posix":
    import paths

    fake_pip = os.path.join(T, "fakepip.py")
    open(fake_pip, "w").write("""import os, sys, zipfile
a = sys.argv
dest = a[a.index("--dest") + 1]
assert "--no-deps" not in a, "the text reader needs what its packages need"
assert "--only-binary=:all:" in a
if os.environ.get("FAKE_PIP_FAIL"):
    print("ERROR: no internet"); sys.exit(1)
for name, mod in (("tinyocr", "tinyocr"), ("numpy", "numpy_copy"), ("pillow", "pil_copy"), ("opencv_python_headless", "cv_copy")):
    with zipfile.ZipFile(os.path.join(dest, name + "-1.0-py3-none-any.whl"), "w") as z:
        z.writestr(mod + "/__init__.py", "X = 1\\n")
        z.writestr(name + "-1.0.dist-info/METADATA", "Name: x\\nVersion: 1.0\\n")
        z.writestr(name + "-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\n")
        z.writestr(name + "-1.0.dist-info/RECORD", "")
""")
    runner = os.path.join(T, "fakepy.sh")
    open(runner, "w").write('#!/bin/sh\nshift 2\nexec %s %s "$@"\n' % (sys.executable, fake_pip))      # "python -m pip download ..." -> fakepip.py download ...
    os.chmod(runner, os.stat(runner).st_mode | stat.S_IEXEC)
    # the runner is called as  runner -m pip download --dest D ...  ->  shift 2 drops "-m pip"
    real_exe = paths.python_exe
    paths.python_exe = lambda: runner
    msgs = []
    target = os.path.join(UD, "ocr_target")
    pe_deps.ocr_installer(["tinyocr"], target, lambda t, f=None: msgs.append(t))
    got = set(os.listdir(target))
    assert "tinyocr" in got and "cv_copy" in got, got
    assert "numpy_copy" not in got and "pil_copy" not in got, "what the program has already (numpy, pillow) is not downloaded again: " + str(got)
    assert any("Downloading" in m for m in msgs) and any("Unpacking" in m for m in msgs)
    os.environ["FAKE_PIP_FAIL"] = "1"
    try:
        pe_deps.ocr_installer(["tinyocr"], os.path.join(UD, "ocr_target2"), None)
        raise SystemExit("a failed download must raise")
    except RuntimeError as e:
        assert "internet connection" in str(e) and "no internet" in str(e)
    del os.environ["FAKE_PIP_FAIL"]
    paths.python_exe = real_exe

# ---------------------------------------------------------------- 5. the window
pe_tab.PdfEditorTab.backend = type("B", (), {"available": lambda s: True, "list_voices": lambda s: [], "engine": lambda s: None})()
shell = pe_tab.make_tab()
shell.warn = lambda t: None
shell.resize(1100, 700)
shell.show()
app.processEvents()
READY = {"on": True}
pe_deps.ocr_ready = lambda: READY["on"]
asked = []


def dialog():
    d = pe_images.ImagesDialog(shell)
    d.ask_download = lambda mb: (asked.append(("download", mb)), True)[1]
    d.ask_overwrite = lambda p: (asked.append(("overwrite", p)), True)[1]
    d.show()
    app.processEvents()
    return d


d = dialog()
assert not d.b_go.isEnabled() and d.b_close.text() == "Close" and d.out.text() == ""
assert d.add_paths([i10, i1, i2]) == 3 and [os.path.basename(p) for p in d.paths()] == ["page1.png", "page2.png", "page10.png"], "natural order, not 1, 10, 2"
assert d.add_paths([i1]) == 0 and d.list.count() == 3, "a picture is not added twice"
assert d.out.text() == os.path.join(T, "page1 - text.pdf") and d.b_go.isEnabled()
d.list.item(2).setSelected(True)
d.move(-1)
assert [os.path.basename(p) for p in d.paths()] == ["page1.png", "page10.png", "page2.png"]
d.list.clearSelection(); d.list.item(0).setSelected(True)
d.remove_selected()
assert [os.path.basename(p) for p in d.paths()] == ["page10.png", "page2.png"] and d.out.text() == os.path.join(T, "page10 - text.pdf"), "the name follows the first picture"
d.out.setText(os.path.join(T, "mine.pdf")); d.out.textEdited.emit("x")
d.clear()
assert d.list.count() == 0 and d.out.text() == os.path.join(T, "mine.pdf") and not d.b_go.isEnabled(), "a name the person typed stays"

# a normal run: two pictures in order -> one PDF that opens as a tab of the editor
d.add_paths([i2, i1])
d.out.setText(os.path.join(T, "book"))
d.go()
until(lambda: d.result_path is not None)
book = os.path.join(T, "book.pdf")
assert d.result_path == book and os.path.isfile(book) and d.result() == 1, "the PDF is made, '.pdf' added, the window closes"
doc = pymupdf.open(book)
txt = doc[0].get_text()
assert txt.index("Chapter one") < txt.index("second picture"), "in the order of the list: page1 before page2 (naturally sorted)"
doc.close()
assert shell.find(book) is not None and shell.path == book, "the result opens as a PDF tab of the editor"
assert asked == [], "nothing to ask when the reader is there and the file is new"

# asks before replacing; refuses a PDF that is open in the editor
d = dialog()
d.add_paths([i1]); d.out.setText(book); d.out.textEdited.emit("x")
d.go()
assert d.busy is False and "open in the editor" in d.status.text() and not d.result_path
shell.close_inner(shell.tabs.indexOf(shell.find(book)))
d.go()
until(lambda: d.result_path is not None)
assert asked == [("overwrite", book)], asked
asked.clear()

# no name, missing folder
d = dialog()
d.add_paths([i1]); d.out.setText(""); d.out.textEdited.emit("x")
d.go()
assert "Choose where" in d.status.text()
d.out.setText(os.path.join(T, "nope", "x.pdf")); d.go()
assert "does not exist" in d.status.text() and not d.busy

# pictures with no text, and a picture that cannot be opened: nothing is made, the window stays, the words are plain
d.out.setText(os.path.join(T, "empty.pdf")); d.clear(); d.add_paths([blank, none_img]); d.out.setText(os.path.join(T, "empty.pdf"))
d.go()
until(lambda: not d.busy)
assert "No text could be read" in d.status.text() and not os.path.exists(os.path.join(T, "empty.pdf")) and d.isVisible() and d.b_go.isEnabled()
d.clear(); d.add_paths([i1, junk]); d.out.setText(os.path.join(T, "bad.pdf"))
d.go()
until(lambda: not d.busy)
assert "junk.png" in d.status.text() and not os.path.exists(os.path.join(T, "bad.pdf")) and d.isVisible()

# Stop: the reading ends after the picture it is on; nothing is made; the window closes
slow = FakeEngine(); slow.delay = 0.4
pe_ocr.set_engine(slow)
d.clear(); d.add_paths([i1, i2, i10, i2]); d.out.setText(os.path.join(T, "stopped.pdf"))
d.go()
until(lambda: "Reading" in d.status.text())
assert d.busy and d.b_close.text() == "Stop" and not d.b_go.isEnabled() and not d.b_add.isEnabled()
d.reject()
assert d.isVisible() and "Stopping" in d.status.text()
until(lambda: not d.isVisible())
assert not os.path.exists(os.path.join(T, "stopped.pdf")) and not d.busy
pe_ocr.set_engine(FakeEngine())

# the first time: the reader is downloaded after asking
READY["on"] = False
d = dialog()
d.add_paths([i1]); d.out.setText(os.path.join(T, "first.pdf")); d.out.textEdited.emit("x")
asked.clear()
d.ask_download = lambda mb: (asked.append(("download", mb)), False)[1]
d.go()
assert asked == [("download", pe_deps.OCR_MB)] and not d.busy and "not downloaded" in d.status.text() and not os.path.exists(os.path.join(T, "first.pdf")), "declined: nothing happens"
INSTALLS = []


def good_installer(pins, target, progress):
    INSTALLS.append(list(pins))
    if progress:
        progress("Downloading the text reader ...", None)
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "x.txt"), "w").write("x")
    READY["on"] = True


d.ask_download = lambda mb: True
pe_images.ImagesDialog.installer = staticmethod(good_installer)
d.go()
until(lambda: d.result_path is not None)
assert INSTALLS == [pe_deps.OCR_PINS] and os.path.isfile(os.path.join(T, "first.pdf")), "downloaded, then the pictures were read, then the PDF made"
assert os.path.isdir(pe_deps.site_dir(pe_deps.OCR)), "into the folder of the text reader under the user folder"

# no internet: said plainly, nothing is half-installed
READY["on"] = False
shutil_target = pe_deps.site_dir(pe_deps.OCR)
shutil.rmtree(shutil_target, ignore_errors=True)


def offline(pins, target, progress):
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "half.txt"), "w").write("x")
    raise RuntimeError("Downloading the packages failed (needs an internet connection)")


pe_images.ImagesDialog.installer = staticmethod(offline)
d = dialog()
d.add_paths([i1]); d.out.setText(os.path.join(T, "off.pdf")); d.out.textEdited.emit("x")
d.go()
until(lambda: not d.busy)
assert "could not be downloaded" in d.status.text() and "internet" in d.status.text() and not os.path.exists(os.path.join(T, "off.pdf"))
assert not os.path.exists(shutil_target + ".new") and not os.path.exists(shutil_target), "a failed download leaves nothing behind"

# the editor's own entry: the menu and welcome page buttons open this window with the editor as its owner
opened = []
pe_tab.PdfEditorTab.images_dialog = lambda self: opened.append(pe_images.ImagesDialog(self))
shell.images_dialog()
assert opened and opened[0].shell is shell
shell.shutdown()
print("OK test_pdf_editor_images")
