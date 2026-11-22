"""PDF editor, the parts with no window (dev_addons/pdf_editor): the words and sentences of a PDF (pe_text), highlights with undo / redo and saving
(pe_pdfio), what is remembered between runs (pe_store), the voice thread and the shared voice (pe_speech) and the package downloads (pe_deps)."""
import faulthandler
import json
import os
import sys
import tempfile
import threading
import time

faulthandler.dump_traceback_later(120, exit=True)
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
import pymupdf

import pe_deps
import pe_pdfio as pio
import pe_speech
import pe_store
import pe_text as tx

T = tempfile.mkdtemp(prefix="opara_pe_")


def make_pdf(path, pages):
    """pages: [[line, line ...]]"""
    d = pymupdf.open()
    for lines in pages:
        p = d.new_page()
        y = 80
        for ln in lines:
            p.insert_text((72, y), ln, fontsize=12)
            y += 18
        y += 0
    d.save(path)
    d.close()


# ---------------------------------------------------------------- 1. words and sentences
text_pdf = os.path.join(T, "text.pdf")
make_pdf(text_pdf, [["Dr. Smith went to the U.S. in 1999. He liked it! Was it good? Yes, it was a great ex-",
                     "ample of travel. Fig. 3 shows 1. the plan.", "", "", "", "A Heading", "", "", "", "The body starts here. It goes on."],
                    ["Second page begins. It ends here."]])
doc = pio.open_pdf(text_pdf)
dt = tx.DocText(doc)
S = dt.sentence_texts
assert S[0] == "Dr. Smith went to the U.S. in 1999." and S[1] == "He liked it!" and S[2] == "Was it good?", S
assert S[3] == "Yes, it was a great example of travel.", "a word cut at the end of a line is joined: " + S[3]
assert S[4] == "Fig. 3 shows 1. the plan.", "Fig. and a list number do not end a sentence"
assert "A Heading" in S, "a short block with no full stop is a sentence of its own: " + str(S)
assert S[-2:] == ["Second page begins.", "It ends here."]
assert dt.ready and dt.tok2sent[0] == 0 and dt.tok2sent[-1] == len(S) - 1
pno, r = dt.sentence_rects(1)[0]
cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
ti = dt.token_at(pno, cx, cy)
assert ti is not None and dt.tok2sent[ti] == 1, "the word under a point belongs to its sentence"
assert dt.token_at(pno, 5, 5, 8.0) is None and dt.token_at(pno, 5, 5, 400.0) is not None
assert dt.first_sentence_from(0, 0) == 0 and dt.first_sentence_from(1, 0) == len(S) - 2
assert dt.first_sentence_from(0, 10000) == len(S) - 2, "past the end of a page the next page's first sentence"
assert dt.text_for_tokens(*dt.sentences[2]) == "Was it good?"
rects = dt.rects_for_tokens(*dt.sentences[3])
assert len(rects) == 2 and rects[0][0] == 0, "a sentence on two lines gives two rectangles"
# the slices give the same as all at once
slow = tx.DocText(doc, build=False)
n = 0
while not slow.step(0.0):
    n += 1
assert slow.sentence_texts == dt.sentence_texts and n >= 1, "page by page"
empty_pdf = os.path.join(T, "empty.pdf")
make_pdf(empty_pdf, [[]])
e = tx.DocText(pio.open_pdf(empty_pdf))
assert not e.tokens and not e.sentences and e.first_sentence_from(0, 0) is None, "a scan has no text"

# ---------------------------------------------------------------- 2. highlights, undo / redo, saving
hl_pdf = os.path.join(T, "hl.pdf")
make_pdf(hl_pdf, [["One sentence here. Another sentence there.", "A third line follows."]])
doc = pio.open_pdf(hl_pdf)
dt = tx.DocText(doc)
ed = pio.Edits(doc)
assert not ed.dirty and ed.count() == 0 and ed.undo() is None and ed.redo() is None
rects = dt.rects_for_tokens(*dt.sentences[0])
assert ed.add(rects, pio.COLORS["Yellow"]) == [0] and ed.dirty and ed.count() == 1
p0, r0 = rects[0]
xref = ed.find(0, (r0[0] + r0[2]) / 2, (r0[1] + r0[3]) / 2)
assert xref and ed.find(0, 400, 700) is None
assert ed.add([], pio.COLORS["Pink"]) == [] and ed.count() == 1
doc = ed.save()
assert not ed.dirty and ed.doc is doc and ed.count() == 1
assert ed.remove(0, xref) and ed.count() == 0 and ed.dirty and not ed.remove(0, xref)
assert ed.undo() == [0] and ed.count() == 1, "undo of a remove puts the highlight back"
assert abs(doc[0].annots().__next__().colors["stroke"][0] - 1.0) < 1e-6, "with its colour"
assert not ed.dirty, "back at the saved state"
assert ed.redo() == [0] and ed.count() == 0 and ed.dirty
assert ed.undo() == [0] and ed.undo() == [0] and ed.count() == 0 and ed.dirty, "two undos go back past the saved state"
assert ed.redo() == [0] and ed.count() == 1
ed.add(dt.rects_for_tokens(*dt.sentences[1]), pio.COLORS["Blue"])
assert ed.count() == 2 and not ed.redo_stack
assert ed.undo() == [0] and ed.redo() == [0] and ed.count() == 2
# several saves in a row on the same open PDF: a highlight added after a save must reach the file (MuPDF alone loses it: see pe_pdfio.save_in_place)
def on_disk():
    d = pio.open_pdf(hl_pdf)
    n = pio.Edits(d).count()
    d.close()
    return n


doc = ed.save()
assert ed.count() == 2 and on_disk() == 2 and not ed.dirty
ed.add(dt.rects_for_tokens(*dt.sentences[1]), pio.COLORS["Green"])
ed.save()
assert on_disk() == 3
ed.undo(); ed.save()
assert on_disk() == 2
ed.redo(); ed.save()
assert on_disk() == 3 and not ed.dirty
# the saved state lies in a future that a new edit throws away: it is then never "clean" again until saved
ed.undo(); ed.save(); ed.undo()
assert ed.dirty
ed.add(dt.rects_for_tokens(*dt.sentences[0]), pio.COLORS["Pink"])
assert ed.dirty, "the same depth as when it was saved, but not the same content"
ed.save()
assert on_disk() == 2 and not ed.dirty
back = ed.doc
assert back.name == hl_pdf

copy = os.path.join(T, "copy.pdf")
ed3 = pio.Edits(back)
ed3.add(dt.rects_for_tokens(*dt.sentences[1]), pio.COLORS["Yellow"])
pio.save_copy(back, copy)
assert pio.Edits(pio.open_pdf(copy)).count() == pio.Edits(back).count(), "a copy has the highlights"
try:
    pio.save_copy(back, hl_pdf); raise SystemExit("a copy cannot overwrite the open file")
except pio.SaveError:
    pass
# a protected PDF: asks for the password; cannot be added to in place
prot = os.path.join(T, "prot.pdf")
d = pymupdf.open(); d.new_page().insert_text((72, 100), "Secret words here.", fontsize=12)
d.save(prot, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw"); d.close()
try:
    pio.open_pdf(prot); raise SystemExit("a protected PDF needs its password")
except ValueError as ex:
    assert "password" in str(ex)
try:
    pio.open_pdf(prot, lambda p: "wrong"); raise SystemExit("wrong password")
except ValueError as ex:
    assert "not accepted" in str(ex)
pd = pio.open_pdf(prot, lambda p: "pw")
assert tx.DocText(pd).sentence_texts == ["Secret words here."]
try:
    pio.open_pdf(os.path.join(T, "nope.pdf")); raise SystemExit
except ValueError:
    pass
junk = os.path.join(T, "junk.pdf"); open(junk, "w").write("this is not a pdf")
try:
    pio.open_pdf(junk); raise SystemExit("not a PDF")
except ValueError:
    pass

# ---------------------------------------------------------------- 3. what is remembered
st = pe_store.Store()
assert st.position("a.pdf") is None and not st.auto("a.pdf") and st.get("rate", 1) == 1 and st.get("open") == []
st.set_position(os.path.join(T, "A.pdf"), 7, 1.25, 3)
st.set_auto(os.path.join(T, "A.pdf"), True)
st.set("voice", "Zira"); st.set("open", ["x.pdf"])
st.flush()
st2 = pe_store.Store()
assert st2.position(os.path.join(T, "A.pdf")) == {"sent": 7, "zoom": 1.25, "page": 3} and st2.auto(os.path.join(T, "A.pdf")) and st2.get("voice") == "Zira"
st2.set_auto(os.path.join(T, "A.pdf"), False)
assert not st2.auto(os.path.join(T, "A.pdf"))
for i in range(80):
    st2.set_position(f"/p/{i}.pdf", i, 1.0, 0)
st2.flush()
st3 = pe_store.Store()
assert len(st3.data["positions"]) == pe_store.MAX_POSITIONS and st3.position("/p/79.pdf") and not st3.position("/p/0.pdf"), "the oldest are dropped"
open(st3.file, "w").write("{ not json")
assert pe_store.Store().position("/p/79.pdf") is None, "a damaged file gives the defaults"
open(st3.file, "w").write(json.dumps({"positions": [], "open": "x", "auto": 3}))
s4 = pe_store.Store()
assert s4.data["positions"] == {} and s4.data["open"] == [] and s4.data["auto"] == {}, "wrong kinds of value are ignored"


# ---------------------------------------------------------------- 4. the voice thread
class Engine:
    def __init__(self, log, ms=120):
        self.log, self.ms, self.left, self.paused, self.closed = log, ms, 0.0, False, False

    def apply(self, voice, rate, volume):
        self.log.append(("apply", voice, rate))

    def speak(self, text):
        self.log.append(("speak", text))
        self.left = self.ms / 1000

    def purge(self):
        self.log.append(("purge",))
        self.left = 0.0

    def pause(self):
        self.log.append(("pause",))
        self.paused = True

    def resume(self):
        self.log.append(("resume",))
        self.paused = False

    def wait(self, ms):
        time.sleep(ms / 1000)
        if not self.paused:
            self.left -= ms / 1000
        return self.left <= 0

    def close(self):
        self.closed = True


class Backend:
    def __init__(self, ms=120, fail=False):
        self.log, self.ms, self.fail = [], ms, fail

    def available(self):
        return True

    def list_voices(self):
        return ["Voice A", "Voice B"]

    def engine(self):
        if self.fail:
            raise RuntimeError("no speech here")
        return Engine(self.log, self.ms)


def settle(hub, cond, seconds=8):
    t0, got = time.time(), []
    while time.time() - t0 < seconds:
        got += hub.poll()
        if cond(got):
            return got
        time.sleep(0.02)
    raise SystemExit("timed out waiting: " + str(got))


sentences = ["One.", "", "Two.", "Three.", "Four."]
be = Backend()
hub = pe_speech.Hub(be)
assert hub.voices() == ["Voice A", "Voice B"] and hub.rate == 1
hub.rate = 99; assert hub.rate == pe_speech.RATE_MAX
hub.rate = -99; assert hub.rate == pe_speech.RATE_MIN
hub.rate = 2; hub.voice_name = "Voice B"
owner = object()
hub.start(owner, sentences, 2)                                   # from the third entry on
assert hub.reading(owner)
got = settle(hub, lambda g: ("done", True) in g)
assert [v for k, v in got if k == "sentence"] == [2, 3, 4], got
assert [x[1] for x in be.log if x[0] == "speak"] == ["Two.", "Three.", "Four."], "starts where it is told and ends at the end"
assert ("apply", "Voice B", 2) in be.log
assert not hub.running

# pause is exact: the sentence that is being said is held, nothing else is started; resume goes on
be = Backend(ms=500)
hub = pe_speech.Hub(be)
hub.start(owner, sentences, 0)
settle(hub, lambda g: ("sentence", 0) in g)
hub.pause()
time.sleep(0.4)
assert hub.paused and ("pause",) in be.log
n_spoken = len([x for x in be.log if x[0] == "speak"])
time.sleep(0.8)
assert len([x for x in be.log if x[0] == "speak"]) == n_spoken and hub.poll() == [], "paused: no new sentence, no event"
hub.resume()
assert not hub.paused
got = settle(hub, lambda g: ("sentence", 2) in g)
assert ("resume",) in be.log
# stop: the voice is purged, the thread ends, nothing more is reported
hub.stop()
assert not hub.running and hub.owner is None and ("purge",) in be.log
time.sleep(0.2)
assert hub.poll() == []

# a second start (another PDF) stops the first and what the first still put into the queue is thrown away
be = Backend(ms=300)
hub = pe_speech.Hub(be)
a, b = object(), object()
hub.start(a, ["A1.", "A2.", "A3."], 0)
settle(hub, lambda g: ("sentence", 0) in g)
hub.start(b, ["B1.", "B2."], 0)
assert hub.owner is b and not hub.reading(a)
got = settle(hub, lambda g: ("done", True) in g)
assert [v for k, v in got if k == "sentence"] == [0, 1], "only the second run's sentences: " + str(got)

# a problem is reported and the thread still ends
hub = pe_speech.Hub(Backend(fail=True))
hub.start(owner, ["x."], 0)
got = settle(hub, lambda g: any(k == "done" for k, _ in g))
assert ("error", "no speech here") in got and ("done", False) in got

# the real backend says plainly that it is not there when it is not
sb = pe_speech.SapiBackend()
if sys.platform != "win32":
    assert not sb.available() and sb.list_voices() == []
    try:
        sb.engine(); raise SystemExit("no engine without Windows")
    except RuntimeError as ex:
        assert "Windows" in str(ex)

# ---------------------------------------------------------------- 5. downloads
site = pe_deps.site_dir(pe_deps.VOICE)
assert site.startswith(UD) and site.endswith(os.path.join("packages", "pdfeditor_voice"))
CALLS = []


def fake(pins, target, progress):
    CALLS.append((list(pins), target))
    os.makedirs(os.path.join(target, "win32"), exist_ok=True)
    open(os.path.join(target, "marker.txt"), "w").write("x")


def broken(pins, target, progress):
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "half.txt"), "w").write("x")
    raise RuntimeError("Downloading the packages failed (needs an internet connection)")


try:
    pe_deps.install(["somepkg"], "pdfeditor_test", None, broken); raise SystemExit("a failed download is an error")
except RuntimeError as ex:
    assert "internet" in str(ex)
assert not os.path.isdir(pe_deps.site_dir("pdfeditor_test")) and not os.path.isdir(pe_deps.site_dir("pdfeditor_test") + ".new"), "nothing half-installed is left"
pe_deps.install(["somepkg"], "pdfeditor_test", None, fake, check=lambda: True)
assert CALLS[-1][0] == ["somepkg"] and os.path.isfile(os.path.join(pe_deps.site_dir("pdfeditor_test"), "marker.txt"))
d = pe_deps.site_dir("pdfeditor_test")
assert d in sys.path and os.path.join(d, "win32") in sys.path, "the folder (and win32 inside it) are on the search path"
try:
    pe_deps.install(["somepkg"], "pdfeditor_test2", None, fake, check=lambda: False); raise SystemExit("downloaded but unusable")
except RuntimeError as ex:
    assert "could not be loaded" in str(ex)
assert pe_deps.VOICE_PINS and pe_deps.VOICE_PINS[0].startswith("pywin32")
print("OK test_pdf_editor_core")
