"""PDF editor, the natural voices (pe_kokoro.py, the natural part of pe_deps.py, the mixed backend of pe_speech.py and the voice picker of pe_reader.py).
The voice model itself is replaced by a fake that returns known samples and the sound card by a fake stream that a test drives block by block, so what
is tested is everything around them: the ranked voice table, how a sentence is cut into clauses, that pausing and resuming give back exactly the samples
that were made, the next sentences being made ahead, a failure being said, the download (sizes, hashes, a stop, another download running), and the
picker in the window (groups, grades, default voice, asking before downloading).  With OPARA_REAL_KOKORO=<folder with site/ and models/> the real model is
tried as well (that is how it was tried once on Linux; it cannot be heard here)."""
import faulthandler
import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time

faulthandler.dump_traceback_later(240, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "pdf_editor"), os.path.join(HERE, "shared"), HERE]
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import pe_deps
import pe_kokoro
import pe_pdfio as pio
import pe_reader
import pe_speech
import pe_store
import pe_tab

T = tempfile.mkdtemp(prefix="opara_nat_")
pymupdf = pio.pymupdf


def until(cond, seconds=10, ui=False):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if ui:
            app.processEvents()
        if cond():
            return True
        QTest.qWait(15) if ui else time.sleep(0.01)
    raise SystemExit("timed out: " + str(cond))


# ---------------------------------------------------------------- 1. the voices: 28, grouped, ranked, graded
V = pe_kokoro.VOICES
assert len(V) == 28 and len({v.id for v in V}) == 28 and pe_kokoro.IDS == {v.id for v in V}
groups = []
for v in V:
    if not groups or groups[-1][0] != v.group:
        groups.append([v.group, 0])
    groups[-1][1] += 1
assert groups == [["American women", 11], ["American men", 9], ["British women", 4], ["British men", 4]], groups
for g, _n in groups:
    ranks = [pe_kokoro.grade_rank(v.grade) for v in V if v.group == g]
    assert ranks == sorted(ranks), "best grade first within " + g
first = V[0]
assert (first.id, first.label, first.grade, first.kind) == ("af_heart", "Heart  ·  A", "A", "natural") and pe_kokoro.DEFAULT_VOICE == "af_heart"
by = {v.id: v for v in V}
assert by["af_bella"].grade == "A-" and by["bf_emma"].grade == "B-" and by["am_adam"].grade == "F+" and by["bm_george"].grade == "C" and by["am_santa"].grade == "D-"
assert all(v.label.endswith(v.grade) for v in V) and all(v.id.startswith(("af_", "am_", "bf_", "bm_")) for v in V), "English voices only"
assert [v.id for v in V if v.group == "American men"][:3] == ["am_fenrir", "am_michael", "am_puck"], "equal grades are in name order"
assert pe_kokoro.grade_rank("A") < pe_kokoro.grade_rank("A-") < pe_kokoro.grade_rank("B+") < pe_kokoro.grade_rank("F") < pe_kokoro.grade_rank("?")
assert pe_kokoro.speed_for(0) == 1.0 and pe_kokoro.speed_for(10) == 1.6 and pe_kokoro.speed_for(-5) == 0.7 and pe_kokoro.speed_for(99) == 2.0 and pe_kokoro.speed_for(-99) == 0.5
assert pe_kokoro.lang_for("af_heart") == "en-us" and pe_kokoro.lang_for("bm_george") == "en-gb"

# ---------------------------------------------------------------- 2. a sentence cut into clauses
txt = ("It was a quiet morning in the small town, and the road, which usually carried a few farm trucks before dawn, "
       "was empty until the first bus passed; nobody saw it go - not even the old man at the window, who had 1,000 things to do.")
ch = pe_kokoro.chunks(txt)
words = [w for c in ch for w in c.split()]
assert [w for w in words if w not in ("-",)] == [w for w in txt.split() if w not in ("-",)], "no word lost, none moved"
assert len(ch) >= 3 and len(ch[0]) <= 110 and all(len(c) <= 260 for c in ch), [len(c) for c in ch]
assert len(ch[0]) < max(len(c) for c in ch), "the first piece is a short one, so that the sound starts early"
assert any("1,000" in c for c in ch), "a number with a comma is not cut"
assert pe_kokoro.chunks("Short one.") == ["Short one."] and pe_kokoro.chunks("") == [] and pe_kokoro.chunks("   ") == []
long_run = "word " * 120
pieces = pe_kokoro.chunks(long_run.strip())
assert all(len(p) <= 260 for p in pieces) and " ".join(pieces).split() == long_run.split(), "a text without punctuation is cut on spaces"
assert pe_kokoro.clean("a­b  c d\n e") == "ab c d e"


# ---------------------------------------------------------------- 3. the engine, with a fake model and a fake sound card
class FakeModel:
    def __init__(self, delay=0.0):
        self.calls, self.returned, self.delay, self.fail = [], [], delay, None
        self.next = 1000

    def create(self, text, voice=None, speed=1.0, lang=None):
        self.calls.append((voice, speed, lang, text))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError(self.fail)
        n = 30 * len(text)
        a = (np.arange(self.next, self.next + n, dtype=np.float32) + 1) / 1e5          # every sample different, all above zero
        self.next += n
        self.returned.append(a)
        return a, 24000


class FakeStream:
    def __init__(self, samplerate, channels, dtype, callback):
        self.rate, self.channels, self.dtype, self.cb = samplerate, channels, dtype, callback
        self.started = self.stopped = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeSD:
    streams = []
    broken = False

    @classmethod
    def OutputStream(cls, **kw):
        if cls.broken:
            raise OSError("no output device")
        s = FakeStream(**kw)
        cls.streams.append(s)
        return s


pe_kokoro.set_sounddevice(FakeSD)


def pull(eng, frames=480):
    out = np.zeros((frames, 1), dtype=np.float32)
    eng._cb(out, frames, None, None)
    return out[:, 0].copy()


def play_out(eng, expected_len=None, pause_at=None, pause_blocks=0, limit=20000):
    """Drives the sound callback until the sentence is said; returns what came out (paused blocks left out) and the block in which the last sample went."""
    got, n, said = [], 0, 0
    for i in range(limit):
        if pause_at is not None and i == pause_at:
            pos0, q0 = eng.pos, len(eng.q)
            eng.pause()
            for _ in range(pause_blocks):
                assert not pull(eng).any() and eng.pos == pos0 and len(eng.q) == q0, "paused: silence, and nothing of the sound is used up"
            eng.resume()
        b = pull(eng)
        got.append(b)
        if expected_len is not None and not said and sum(int((x != 0).sum()) for x in got) >= expected_len:
            said = i
            assert not eng.finished.is_set(), "not 'said' while the last samples are still on their way out"
        if eng.finished.is_set():
            return np.concatenate(got), said
    raise SystemExit("the sentence never ended")


m = FakeModel()
pe_kokoro.set_model(m)
eng = pe_kokoro.NaturalEngine()
st = FakeSD.streams[-1]
assert st.started and st.rate == 24000 and st.channels == 1 and st.dtype == "float32" and eng.finished.is_set()
SENT = ("The quick brown fox, which was very tired after the long night, jumped over the lazy dog; then it slept all afternoon "
        "in the warm sun by the old stone wall.")
eng.apply("af_heart", 0, 100)
eng.speak(SENT)
assert not eng.finished.is_set()
until(lambda: eng.got >= eng.total)
exp = np.concatenate(m.returned)
assert len(m.returned) == len(pe_kokoro.chunks(pe_kokoro.clean(SENT))) >= 2 and all(c[:3] == ("af_heart", 1.0, "en-us") for c in m.calls)
out, said = play_out(eng, len(exp), pause_at=3, pause_blocks=6)
assert np.array_equal(out[out != 0], exp), "paused and resumed: exactly the samples that were made, in order, none lost, none twice"
assert eng.wait(5) is True, "wait says the sentence has been said"

# a slow model: gaps of silence while it is made, and every sample still comes out once, in order
m2 = FakeModel(delay=0.04)
pe_kokoro.set_model(m2)
eng.apply("af_heart", 0, 100)
eng.speak(SENT)
got = []
t0 = time.time()
while not eng.finished.is_set() and time.time() - t0 < 10:
    got.append(pull(eng))
    time.sleep(0.002)
out = np.concatenate(got)
assert eng.finished.is_set() and np.array_equal(out[out != 0], np.concatenate(m2.returned)), "slow making: silence, never a repeated or lost sample"

# the next sentences are made ahead and used
m3 = FakeModel()
pe_kokoro.set_model(m3)
S2, S3, S4 = "Second sentence, with a comma in it.", "Third one is a bit longer than the second one, so it has two parts.", "Fourth."
eng.apply("af_heart", 0, 100)
eng.speak(SENT)
eng.prefetch([S2, S3])
until(lambda: len(m3.returned) >= len(pe_kokoro.chunks(SENT)) + len(pe_kokoro.chunks(S2)) + len(pe_kokoro.chunks(S3)))
n = len(m3.calls)
play_out(eng)
eng.speak(S2)
until(lambda: eng.got >= eng.total)
assert len(m3.calls) == n, "a sentence that was made ahead is not made again"
eng.prefetch([S3, S4])
until(lambda: any(c[3] == S4 for c in m3.calls))
assert sum(1 for c in m3.calls if c[3] == S3) == 1 and sum(1 for c in m3.calls if c[3] == S4) == 1
play_out(eng)

# another voice or speed: what was made for the old one is not used
eng.apply("af_heart", 0, 100)
eng.prefetch([S2])
time.sleep(0.15)
before = len(m3.calls)
eng.apply("bm_george", 5, 100)
eng.speak(S2)
until(lambda: eng.got >= eng.total)
last = [c for c in m3.calls[before:] if c[3] == S2]
assert last and last[-1][:3] == ("bm_george", 1.3, "en-gb"), (last, m3.calls[before:])
play_out(eng)
eng.apply("nonsense", 0, 100)
assert eng.voice == "af_heart", "an unknown voice falls back to the default one"

# volume
m4 = FakeModel()
pe_kokoro.set_model(m4)
eng.apply("af_heart", 0, 50)
eng.speak(S2)
until(lambda: eng.got >= eng.total)
out, _ = play_out(eng)
assert np.array_equal(out[out != 0], np.concatenate(m4.returned) * 0.5)
eng.apply("af_heart", 0, 100)

# stop: nothing more comes out, what a slow model still delivers is thrown away
m5 = FakeModel(delay=0.15)
pe_kokoro.set_model(m5)
eng.speak(SENT)
eng.purge()
assert eng.finished.is_set() and not eng.q and not pull(eng).any()
time.sleep(0.6)
assert not eng.q and not pull(eng).any(), "a sentence that was stopped does not come back"
eng.speak(S4)                                                # and the engine is usable again
until(lambda: eng.got >= eng.total)
out, _ = play_out(eng)
assert out[out != 0].size == len(m5.returned[-1])

# a failure of the model is said, once, and the next sentence is tried again
m6 = FakeModel()
m6.fail = "model exploded"
pe_kokoro.set_model(m6)
eng.speak(S2)
until(lambda: eng.finished.is_set())
try:
    eng.wait(10)
    raise SystemExit("a failed sentence must raise")
except RuntimeError as e:
    assert "could not make this sentence" in str(e) and "model exploded" in str(e)
m6.fail = None
eng.speak(S2)
until(lambda: eng.got >= eng.total)
assert eng.err is None and eng.wait(1) is False
play_out(eng)

# no sound card
FakeSD.broken = True
try:
    pe_kokoro.NaturalEngine()
    raise SystemExit("a missing sound device must raise")
except RuntimeError as e:
    assert "sound could not be started" in str(e) and "no output device" in str(e)
FakeSD.broken = False
eng.close()
assert st.stopped and st.closed

# the sound system's thread asks for sound many times a second while sentences start, stop and arrive: nothing may raise, nothing stale may be heard
mR = FakeModel(delay=0.0004)
pe_kokoro.set_model(mR)
er = pe_kokoro.NaturalEngine()
errs, quit_ = [], threading.Event()
orig_fill = er._fill


def spy(o, f):
    try:
        orig_fill(o, f)
    except Exception as ex:                                   # noqa: BLE001
        errs.append(ex)
        raise


er._fill = spy
beats = [0]


def hammer():
    out = np.zeros((480, 1), dtype=np.float32)
    while not quit_.is_set():
        er._cb(out, 480, None, None)
        beats[0] += 1


ht = threading.Thread(target=hammer, daemon=True)
ht.start()
er.apply("af_heart", 0, 100)
for k in range(300):
    er.speak(SENT if k % 3 else S2)
    if k % 2:
        er.purge()
    if k % 7 == 0:
        er.pause()
        er.resume()
time.sleep(0.5)
quit_.set()
ht.join(5)
assert not errs and beats[0] > 100, (errs[:1], beats[0])
er.purge()
until(lambda: er.pool._work_queue.qsize() == 0)
time.sleep(0.15)
n0 = len(mR.calls)
er.speak(S2)
until(lambda: er.got >= er.total)
out, _ = play_out(er)
assert np.array_equal(out[out != 0], np.concatenate(mR.returned[n0:])), "after all that, a sentence is heard exactly as it was made - nothing of the stopped ones"
er.close()

# the backend: refuses to start while nothing is downloaded
real_ready = pe_deps.natural_ready
pe_deps.natural_ready = lambda: False
pe_kokoro.set_model(None)
kb = pe_kokoro.KokoroBackend()
assert kb.has("af_heart") and not kb.has("Microsoft David") and not kb.ready() and len(kb.voice_entries()) == 28
try:
    kb.engine()
    raise SystemExit("an engine without the download must raise")
except RuntimeError as e:
    assert "not downloaded" in str(e)
pe_deps.natural_ready = real_ready
pe_kokoro.set_model(FakeModel())
e2 = pe_kokoro.KokoroBackend().engine()
e2.close()


# ---------------------------------------------------------------- 4. the mixed backend: natural first, Windows after, what each needs
class FakeEngine:
    def __init__(self, kind):
        self.kind, self.log, self.closed = kind, [], False

    def apply(self, voice, rate, volume):
        self.log.append(("apply", voice, rate))

    def speak(self, text):
        self.log.append(("speak", text))

    def purge(self):
        self.log.append(("purge",))

    def pause(self):
        self.log.append(("pause",))

    def resume(self):
        self.log.append(("resume",))

    def wait(self, ms):
        return True

    def close(self):
        self.closed = True


class FakeNatEngine(FakeEngine):
    def prefetch(self, texts):
        self.log.append(("prefetch", list(texts)))


class FakeNat:
    def __init__(self):
        self.made, self.warmed = [], 0

    def voice_entries(self):
        return list(pe_kokoro.VOICES)

    def has(self, v):
        return v in pe_kokoro.IDS

    def ready(self):
        return pe_deps.natural_ready()

    def engine(self):
        self.made.append(FakeNatEngine("natural"))
        return self.made[-1]

    def warm(self):
        if self.ready():                                      # (like the real one: the model is only loaded when it is there)
            self.warmed += 1


class FakeWin:
    names, avail = [], False

    def __init__(self):
        self.made = []

    def list_voices(self):
        return list(self.names)

    def available(self):
        return self.avail

    def engine(self):
        self.made.append(FakeEngine("windows"))
        return self.made[-1]


class NT:
    name = "nt"


real_pe_speech_os = pe_speech.os
nat, win = FakeNat(), FakeWin()
FakeWin.names, FakeWin.avail = [], False
mb = pe_speech.MixedBackend(nat, win)
ent = mb.voice_entries()
assert len(ent) == 28 and all(e.kind == "natural" for e in ent), "no Windows voices on this system: the natural ones only"
assert mb.needs("Test David") == "notwindows" and mb.needs("windows:setup") == "notwindows"
pe_speech.os = NT
ent = mb.voice_entries()
assert len(ent) == 29 and ent[-1] == pe_speech.Voice("windows:setup", "Windows voices (a small download first)", "Windows voices", "", "setup")
assert mb.needs("windows:setup") == "windows" and mb.needs("anything") == "windows"
FakeWin.names, FakeWin.avail = ["Test David", "Test Zira"], True
ent = mb.voice_entries()
assert [e.id for e in ent[-2:]] == ["Test David", "Test Zira"] and all(e.group == "Windows voices" and e.kind == "windows" for e in ent[-2:]) and len(ent) == 30
assert mb.needs("Test David") is None
pe_deps.natural_ready = lambda: False
assert mb.needs("af_heart") == "natural" and mb.needs("bm_daniel") == "natural"
pe_deps.natural_ready = lambda: True
assert mb.needs("af_heart") is None and mb.list_voices()[0] == "af_heart"
mb.warm()
assert nat.warmed == 1
me = mb.engine()
me.apply("af_heart", 2, 100)
me.speak("hello")
me.prefetch(["a", "b"])
me.pause()
me.resume()
me.purge()
assert len(nat.made) == 1 and not win.made and nat.made[0].log == [("apply", "af_heart", 2), ("speak", "hello"), ("prefetch", ["a", "b"]), ("pause",), ("resume",), ("purge",)]
me.apply("Test David", 2, 100)
me.speak("hi")
me.prefetch(["x"])                                           # the Windows engine has no prefetch: nothing happens
me.apply("bm_lewis", 1, 100)
me.speak("again")
assert len(nat.made) == 1 and len(win.made) == 1 and win.made[0].log == [("apply", "Test David", 2), ("speak", "hi")], "each kind of engine is made once, when first needed"
me.close()
assert nat.made[0].closed and win.made[0].closed
pe_deps.natural_ready = real_ready

h = pe_speech.Hub()                                          # what the window really uses
assert [v.id for v in h.voice_entries()][:2] == ["af_heart", "af_bella"] and len(h.voices()) == 29 and h.voices()[-1] == "windows:setup"
pe_speech.os = real_pe_speech_os
h = pe_speech.Hub()
assert len(h.voice_entries()) == 28 and h.voices()[0] == "af_heart"
pe_deps.natural_ready = lambda: False
assert h.needs("af_heart") == "natural"
h.voice_name = "bm_george"
assert h.needs() == "natural"
pe_deps.natural_ready = real_ready
old = pe_speech.Hub(type("Old", (), {"list_voices": lambda s: ["A", "B"], "engine": lambda s: None})())
assert [v.label for v in old.voice_entries()] == ["A", "B"] and old.needs("A") is None, "a backend that knows only names still works"

# ---------------------------------------------------------------- 5. the download: what is fetched, what is checked, what a failure leaves
MODELS = os.path.join(T, "models")
os.makedirs(MODELS)
real_dir, real_files, real_pk, real_fetch = pe_deps.models_dir, pe_deps.MODEL_FILES, pe_deps.natural_packages_ready, pe_deps._fetch
BODY = {"m.onnx": b"model bytes " * 50, "v.bin": b"voices bytes " * 20}
pe_deps.models_dir = lambda: MODELS
pe_deps.MODEL_FILES = [{"name": n, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "what": "the " + n} for n, b in BODY.items()]
PKG = {"ready": False}
pe_deps.natural_packages_ready = lambda deep=False: PKG["ready"]
assert not pe_deps.models_ready() and not pe_deps.natural_ready()

calls = {"pip": [], "fetch": []}


def pip_inst(pins, target, progress):
    calls["pip"].append(list(pins))
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "kokoro_onnx.py"), "w").write("X = 1\n")
    PKG["ready"] = True


def good_fetch(url, dest, progress, what):
    calls["fetch"].append(url)
    body = BODY[url.rsplit("/", 1)[1]]
    with open(dest, "wb") as f:
        f.write(body[:len(body) // 2])
        if progress:
            progress("Downloading " + what + ": half", 0.5)
        f.write(body[len(body) // 2:])


msgs = []
pe_deps.install_natural(lambda t, f=None: msgs.append(t), pip_inst, good_fetch)
assert calls["pip"] == [pe_deps.NATURAL_PINS] and [u.rsplit("/", 1)[1] for u in calls["fetch"]] == ["m.onnx", "v.bin"]
assert all(u.startswith(pe_deps.MODEL_BASE) for u in calls["fetch"]) and pe_deps.models_ready() and pe_deps.natural_ready()
assert sorted(os.listdir(MODELS)) == ["m.onnx", "v.bin"], "no side files are left"
assert any("half" in x for x in msgs)
pe_deps.install_natural(None, pip_inst, good_fetch)
assert len(calls["pip"]) == 1 and len(calls["fetch"]) == 2, "what is there is not downloaded again"
os.remove(os.path.join(MODELS, "v.bin"))
pe_deps.install_natural(None, pip_inst, good_fetch)
assert len(calls["fetch"]) == 3 and calls["fetch"][-1].endswith("v.bin") and pe_deps.models_ready(), "only the missing file"
for n in os.listdir(MODELS):
    os.remove(os.path.join(MODELS, n))


def damaged(kind):
    def f(url, dest, progress, what):
        body = BODY[url.rsplit("/", 1)[1]]
        with open(dest, "wb") as fh:
            fh.write(body[:-3] if kind == "short" else bytes(reversed(body)))
    return f


for kind in ("short", "other"):
    try:
        pe_deps.install_natural(None, pip_inst, damaged(kind))
        raise SystemExit("a damaged download must raise")
    except RuntimeError as e:
        assert "damaged" in str(e) and "Try again" in str(e), str(e)
    assert os.listdir(MODELS) == [], "a damaged file is not kept, nor its side file"


def offline(url, dest, progress, what):
    with open(dest, "wb") as fh:
        fh.write(b"abc")
    raise OSError("no internet")


try:
    pe_deps.install_natural(None, pip_inst, offline)
    raise SystemExit("an offline download must raise")
except RuntimeError as e:
    assert "internet connection" in str(e) and "no internet" in str(e)
assert os.listdir(MODELS) == []

# the packages: a failed package download stops before any model file is asked for
PKG["ready"] = False
calls["fetch"].clear()


def bad_pip(pins, target, progress):
    raise RuntimeError("Downloading the packages failed (needs an internet connection)")


try:
    pe_deps.install_natural(None, bad_pip, good_fetch)
    raise SystemExit("a failed package download must raise")
except RuntimeError as e:
    assert "packages failed" in str(e)
assert not calls["fetch"], "the big files are not fetched when the packages could not be had"

# one download at a time
hold, started = threading.Event(), threading.Event()
res = []


def slow_fetch(url, dest, progress, what):
    started.set()
    hold.wait(10)
    good_fetch(url, dest, progress, what)


PKG["ready"] = True
th = threading.Thread(target=lambda: res.append(pe_deps.install_natural(None, pip_inst, slow_fetch)), daemon=True)
th.start()
assert started.wait(5) and pe_deps.busy()
try:
    pe_deps.install_natural(None, pip_inst, good_fetch)
    raise SystemExit("a second download must be refused")
except RuntimeError as e:
    assert "already running" in str(e)
try:
    pe_deps.install_ocr(None, pip_inst)
    raise SystemExit("the text reader's download is refused too")
except RuntimeError as e:
    assert "already running" in str(e)
hold.set()
th.join(10)
assert not pe_deps.busy() and pe_deps.models_ready()
for n in os.listdir(MODELS):
    os.remove(os.path.join(MODELS, n))

# the packages of the natural pack: what the program (or the text reader) already has is not downloaded again
if os.name == "posix":
    import stat
    import paths
    fake_pip = os.path.join(T, "fakepip.py")
    open(fake_pip, "w").write("""import os, sys, zipfile
a = sys.argv
dest = a[a.index("--dest") + 1]
assert "--no-deps" not in a and "--only-binary=:all:" in a
for name, mod in (("kokoro_onnx", "kokoro_onnx"), ("numpy", "numpy_copy"), ("onnxruntime", "ort_copy"), ("sounddevice", "sounddevice"), ("phonemizer", "phonemizer")):
    with zipfile.ZipFile(os.path.join(dest, name + "-1.0-py3-none-any.whl"), "w") as z:
        z.writestr(mod + "/__init__.py", "X = 1\\n")
        z.writestr(name + "-1.0.dist-info/METADATA", "Name: x\\nVersion: 1.0\\n")
        z.writestr(name + "-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\n")
        z.writestr(name + "-1.0.dist-info/RECORD", "")
""")
    runner = os.path.join(T, "fakepy.sh")
    open(runner, "w").write('#!/bin/sh\nshift 2\nexec %s %s "$@"\n' % (sys.executable, fake_pip))
    os.chmod(runner, os.stat(runner).st_mode | stat.S_IEXEC)
    real_exe = paths.python_exe
    paths.python_exe = lambda: runner
    target = os.path.join(UD, "nat_target")
    pe_deps.natural_installer(pe_deps.NATURAL_PINS, target, lambda t, f=None: None)
    got = set(os.listdir(target))
    assert {"kokoro_onnx", "sounddevice", "phonemizer"} <= got, got
    assert "numpy_copy" not in got, "numpy comes with the program: " + str(got)
    paths.python_exe = real_exe

pe_deps.models_dir, pe_deps.MODEL_FILES, pe_deps.natural_packages_ready = real_dir, real_files, real_pk
mf = pe_deps.MODEL_FILES
assert [f["name"] for f in mf] == ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"] and mf[0]["bytes"] == 92361271 and mf[1]["bytes"] == 28214398
assert all(len(f["sha256"]) == 64 for f in mf) and pe_deps.MODEL_BASE.startswith("https://github.com/thewh1teagle/kokoro-onnx/releases/download/")
assert pe_deps.model_path("x").endswith(os.path.join("pdf_editor_models", "kokoro", "x")) and pe_deps.NATURAL_MB == 160

# ---------------------------------------------------------------- 6. the picker in the window
book = os.path.join(T, "book.pdf")
d = pymupdf.open()
n = 0
for _p in range(3):
    pg = d.new_page()
    y = 72
    for _i in range(8):
        n += 1
        pg.insert_text((72, y), f"This is sentence number {n} of the test book. It has a second part.", fontsize=12)
        y += 30
d.save(book)
d.close()


class Eng:
    log = []

    def __init__(self):
        self.left, self.paused = 0.0, False

    def apply(self, voice, rate, volume):
        pass

    def speak(self, text):
        Eng.log.append(text)
        self.left = 0.7

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


class UiNat(FakeNat):
    def engine(self):
        return Eng()


class UiWin(FakeWin):
    def engine(self):
        return Eng()


def make_reader(hub, store=None):
    store = store or pe_store.Store()
    r = pe_reader.ReaderTab(book, hub, store)
    r.resize(1200, 800)
    r.show()
    until(lambda: r.text.ready, ui=True)
    r.ask_natural_download = lambda mb: (ASKED.append(mb), ANSWER["yes"])[1]
    return r


ASKED, ANSWER = [], {"yes": False}
MODELS2 = os.path.join(T, "models2")
os.makedirs(MODELS2)
pe_deps.models_dir = lambda: MODELS2
pe_deps.MODEL_FILES = [{"name": n, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "what": "the " + n} for n, b in BODY.items()]
PKG["ready"] = True
pe_deps.natural_packages_ready = lambda deep=False: PKG["ready"]
UiWin.names, UiWin.avail = ["Test David", "Test Zira"], True
pe_speech.os = NT
pe_reader.os = type("NTR", (), {"name": "nt", "path": os.path})

nat, win = UiNat(), UiWin()
hub = pe_speech.Hub(pe_speech.MixedBackend(nat, win))
r = make_reader(hub)
box, model = r.voice_box, r.voice_model
texts = [box.itemText(i) for i in range(box.count())]
assert box.count() == 28 + 4 + 1 + 2, box.count()
assert texts[:4] == ["American women", "Heart  ·  A", "Bella  ·  A-", "Nicole  ·  B-"], texts[:4]
heads = [i for i in range(box.count()) if box.itemData(i) is None]
assert [texts[i] for i in heads] == ["American women", "American men", "British women", "British men", "Windows voices"]
assert all(not (model.item(i).flags() & Qt.ItemFlag.ItemIsEnabled) for i in heads), "a group heading is shown, never chosen"
assert texts[-3:] == ["Windows voices", "Test David", "Test Zira"], "the Windows voices are at the bottom"
assert box.currentData() == "af_heart" and box.currentText() == "Heart  ·  A" and hub.voice_name == "af_heart", "Heart is the voice when nothing was chosen"
assert r.voice_summary() == "Heart  ·  A"
assert nat.warmed == 0, "nothing is loaded before it is downloaded"
assert "downloaded the first time" in r.voice_note.text() and "160 MB" in r.voice_note.text() and "A is the best" in r.voice_note.text() and not r.voice_note.isHidden()

# a download is asked for, and refused
r.view.set_read(2)
r.toggle_play()
assert ASKED == [160] and not hub.running and not pe_deps.models_ready()
assert "Nothing was downloaded" in r.status.text() and "Windows voice" in r.status.text()
assert not r.setup_busy and not r.b_stop.isEnabled()

# ... and accepted: the model files and the packages come (fakes), then reading starts at the sentence that was asked for
ANSWER["yes"] = True
FETCHED = []


def fetch_ok(url, dest, progress, what):
    FETCHED.append(url)
    body = BODY[url.rsplit("/", 1)[1]]
    progress("Downloading " + what + ": 1 MB", 0.1)
    with open(dest, "wb") as f:
        f.write(body)


r.natural_fetch = fetch_ok
r.natural_installer = pip_inst
Eng.log.clear()
r.toggle_play()
assert r.setup_busy and r.b_stop.isEnabled(), "while it downloads Stop is there"
until(lambda: hub.reading(r), 15, ui=True)
assert len(ASKED) == 2 and [u.rsplit("/", 1)[1] for u in FETCHED] == ["m.onnx", "v.bin"] and pe_deps.models_ready() and not r.setup_busy
until(lambda: len(Eng.log) >= 1, ui=True)
assert Eng.log[0] == r.text.sentence_texts[2] and "downloaded the first time" not in r.voice_note.text()
assert "A is the best" in r.voice_note.text() and nat.warmed >= 1, "the model is loaded in the background once it can be"
r.stop_reading()
assert not hub.running

# a voice that is already downloaded: no question
ASKED.clear()
r.toggle_play()
until(lambda: hub.reading(r), ui=True)
assert not ASKED
r.stop_reading()

# choosing another voice: remembered, shared, and the note follows
r.select_voice("bm_george")
assert hub.voice_name == "bm_george" and r.store.get("voice") == "bm_george" and r.voice_summary() == "George  ·  C"
r.select_voice("Test David")
assert hub.voice_name == "Test David" and r.store.get("voice") == "Test David" and r.voice_note.isHidden(), "a Windows voice needs no note"
Eng.log.clear()
r.view.set_read(4)
r.toggle_play()
until(lambda: hub.reading(r), ui=True)
until(lambda: len(Eng.log) >= 1, ui=True)
assert Eng.log[0] == r.text.sentence_texts[4]

# changing to a natural voice that is not there (the files were removed) while reading: reading stops and says why
for n_ in os.listdir(MODELS2):
    os.remove(os.path.join(MODELS2, n_))
assert hub.running
r.select_voice("af_nicole")
assert not hub.running and "downloaded first" in r.status.text() and not r.b_stop.isEnabled()

# a stop during the download, and nothing half downloaded is kept
begun = threading.Event()


def slow(url, dest, progress, what):
    with open(dest, "wb") as f:
        f.write(b"partial")
    begun.set()
    for _ in range(1000):
        progress("Downloading " + what + ": 5 MB", 0.2)
        time.sleep(0.01)


r.natural_fetch = slow
r.toggle_play()
assert r.setup_busy
until(begun.is_set, ui=True)
r.stop_reading()
until(lambda: not r.setup_busy, 10, ui=True)
assert "stopped" in r.status.text() and not hub.running and os.listdir(MODELS2) == [] and not pe_deps.busy()

# another download is running: it is said, and nothing is asked
ASKED.clear()
with pe_deps.exclusive():
    r.toggle_play()
assert "already running" in r.status.text() and not ASKED and not r.setup_busy

# a download that fails says what went wrong, and reading does not start
r.natural_fetch = offline
r.toggle_play()
until(lambda: not r.setup_busy, 10, ui=True)
assert "could not be downloaded" in r.status.text() and "no internet" in r.status.text() and not hub.running and os.listdir(MODELS2) == []

# the tab does not ask when the support is switched off (as in a test of something else)
r.AUTO_SETUP = False
ASKED.clear()
r.toggle_play()
assert not ASKED and "not downloaded" in r.status.text()
r.AUTO_SETUP = True
r.shutdown()

# the Windows voices that are not there yet: a stand-in entry in the list, replaced by the real ones after the download
UiWin.names, UiWin.avail = [], False
nat2, win2 = UiNat(), UiWin()
hub2 = pe_speech.Hub(pe_speech.MixedBackend(nat2, win2))
r2 = make_reader(hub2)
assert r2.voice_box.count() == 28 + 4 + 1 + 1 and r2.voice_box.itemText(r2.voice_box.count() - 1) == "Windows voices (a small download first)"
r2.select_voice("windows:setup")
assert "Windows voices" in r2.voice_note.text() and hub2.needs() == "windows"
CALLS = []


def win_install(pins, target, progress):
    CALLS.append(list(pins))
    os.makedirs(target, exist_ok=True)
    open(os.path.join(target, "x.txt"), "w").write("x")
    UiWin.names, UiWin.avail = ["Test David"], True


real_vr = pe_deps.voice_ready
pe_deps.voice_ready = lambda: True
pe_reader.ReaderTab.installer = staticmethod(win_install)
Eng.log.clear()
r2.view.set_read(6)
r2.toggle_play()
until(lambda: hub2.reading(r2), 15, ui=True)
assert CALLS == [pe_deps.VOICE_PINS] and r2.voice_box.currentData() == "Test David" and hub2.voice_name == "Test David", "the first Windows voice takes the stand-in's place"
until(lambda: len(Eng.log) >= 1, ui=True)
assert Eng.log[0] == r2.text.sentence_texts[6]
r2.stop_reading()
pe_deps.voice_ready = real_vr
pe_reader.ReaderTab.installer = None
r2.shutdown()

# not Windows: a Windows voice cannot be used, and says so; the natural ones are not touched by that
pe_speech.os = real_pe_speech_os
pe_reader.os = os
UiWin.names, UiWin.avail = ["Test David"], True
hub3 = pe_speech.Hub(pe_speech.MixedBackend(UiNat(), UiWin()))
r3 = make_reader(hub3)
r3.select_voice("Test David")
r3.view.set_read(1)
r3.toggle_play()
assert "needs Windows" in r3.status.text() and not hub3.running
r3.shutdown()

# a stored voice from last time comes back; one that no longer exists gives way to Heart
st = pe_store.Store()
st.set("voice", "am_michael")
r4 = make_reader(pe_speech.Hub(pe_speech.MixedBackend(UiNat(), UiWin())), st)
assert r4.voice_box.currentData() == "am_michael" and r4.voice_box.currentText() == "Michael  ·  C+"
r4.shutdown()
st.set("voice", "Voice That Is Gone")
r5 = make_reader(pe_speech.Hub(pe_speech.MixedBackend(UiNat(), UiWin())), st)
assert r5.voice_box.currentData() == "af_heart"
r5.shutdown()

# the speed of last time (the tab gives it to the voice when it opens)
ss = pe_store.Store()
ss.set("rate", 4)
ss.flush()
pe_tab.PdfEditorTab.backend = pe_speech.MixedBackend(UiNat(), UiWin())
tab = pe_tab.make_tab()
assert tab.hub.rate == 4, "the speed is remembered"
tab.shutdown()
pe_tab.PdfEditorTab.backend = None

pe_deps.models_dir, pe_deps.MODEL_FILES, pe_deps.natural_packages_ready = real_dir, real_files, real_pk

# ---------------------------------------------------------------- 7. the real model, when a folder with it is given (not part of the normal run)
real = os.environ.get("OPARA_REAL_KOKORO")
if real and os.path.isdir(real):
    sys.path.insert(0, os.path.join(real, "site"))             # (before the stand-in package that the download test above unpacked)
    sys.modules.pop("kokoro_onnx", None)
    from kokoro_onnx import Kokoro
    pe_kokoro.set_model(Kokoro(os.path.join(real, "models", mf[0]["name"]), os.path.join(real, "models", mf[1]["name"])))
    a = pe_kokoro.synth("af_heart", 1.0, "Hello there, how are you today?")
    b = pe_kokoro.synth("bm_george", 1.0, "Hello there, how are you today?")
    c = pe_kokoro.synth("af_heart", 1.5, "Hello there, how are you today?")
    assert a.dtype == np.float32 and 1.0 < len(a) / 24000 < 6 and abs(a).max() > 0.05 and not np.array_equal(a[:2000], b[:2000]), (len(a), abs(a).max())
    assert 0.5 < len(c) / len(a) < 0.85, "a higher speed is a shorter sentence"
    eng = pe_kokoro.NaturalEngine()
    eng.apply("bf_emma", 0, 100)
    eng.speak("The real voice says this sentence, and then it stops.")
    got = []
    t0 = time.time()
    while not eng.finished.is_set() and time.time() - t0 < 60:
        got.append(pull(eng))
        time.sleep(0.01)
    out = np.concatenate(got)
    assert eng.finished.is_set() and (out != 0).sum() > 24000, "real speech came out of the engine"
    eng.close()
    print("real model: ok")

shutil.rmtree(T, ignore_errors=True)
shutil.rmtree(UD, ignore_errors=True)
print("OK test_pdf_editor_natural")
