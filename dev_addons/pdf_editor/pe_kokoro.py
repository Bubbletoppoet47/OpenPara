"""pe_kokoro.py - the natural voices: Kokoro, an 82-million-parameter speech model that runs on this computer (kokoro-onnx on onnxruntime).

The 28 English voices (American and British, women and men) with the grade Kokoro's own voice table gives each one (A best ... F), in the order to show
them: groups, best first.  The model and its packages are downloaded the first time (pe_deps.install_natural); every voice is only a small profile in the
one voices file, so no voice costs more than another.

NaturalEngine is what the speaker thread uses (the interface of pe_speech: apply / speak / purge / pause / resume / wait, plus prefetch):
  * a sentence is cut into clauses and made one clause at a time, so the first sound comes after the first clause, not after the whole sentence;
  * the next sentences are made while this one is played, so there is no gap between sentences (when the computer can make speech faster than it is
    spoken; if it cannot, the pause is the time it still needs);
  * the sound goes out through a sound stream the engine owns (sounddevice), and pausing silences that stream: the voice goes on at the exact sample
    where it stopped.  Stop empties it.
Nothing here needs Qt.  The model and the sound card are looked up late, so a test puts a fake model (set_model) and a fake sounddevice (set_sounddevice).
"""
import os
import re
import threading
from collections import deque
from concurrent.futures import CancelledError, ThreadPoolExecutor

import pe_deps
from pe_speech import Voice

RATE_HZ = 24000
DEFAULT_VOICE = "af_heart"
GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F+", "F"]

# (id, name, Kokoro's grade) - from the voice table of the model's own page
_TABLE = [
    ("American women", [("af_heart", "Heart", "A"), ("af_bella", "Bella", "A-"), ("af_nicole", "Nicole", "B-"), ("af_aoede", "Aoede", "C+"),
                        ("af_kore", "Kore", "C+"), ("af_sarah", "Sarah", "C+"), ("af_alloy", "Alloy", "C"), ("af_nova", "Nova", "C"),
                        ("af_sky", "Sky", "C-"), ("af_jessica", "Jessica", "D"), ("af_river", "River", "D")]),
    ("American men", [("am_fenrir", "Fenrir", "C+"), ("am_michael", "Michael", "C+"), ("am_puck", "Puck", "C+"), ("am_echo", "Echo", "D"),
                      ("am_eric", "Eric", "D"), ("am_liam", "Liam", "D"), ("am_onyx", "Onyx", "D"), ("am_santa", "Santa", "D-"),
                      ("am_adam", "Adam", "F+")]),
    ("British women", [("bf_emma", "Emma", "B-"), ("bf_isabella", "Isabella", "C"), ("bf_alice", "Alice", "D"), ("bf_lily", "Lily", "D")]),
    ("British men", [("bm_fable", "Fable", "C"), ("bm_george", "George", "C"), ("bm_lewis", "Lewis", "D+"), ("bm_daniel", "Daniel", "D")]),
]


def grade_rank(g):
    return GRADES.index(g) if g in GRADES else len(GRADES)


def build_voices():
    """The voices in the order to show them: group by group, best grade first (equal grades by name)."""
    out = []
    for group, rows in _TABLE:
        for vid, name, grade in sorted(rows, key=lambda r: (grade_rank(r[2]), r[1])):
            out.append(Voice(vid, f"{name}  ·  {grade}", group, grade, "natural"))
    return out


VOICES = build_voices()
IDS = {v.id for v in VOICES}


def speed_for(rate):
    """The speed slider (-5 .. +10, 0 = normal) -> Kokoro's speed (1.0 = normal)."""
    return max(0.5, min(2.0, round(1.0 + 0.06 * float(rate), 3)))


def lang_for(voice):
    return "en-gb" if voice.startswith("b") else "en-us"


# ---------------------------------------------------------------------------------------------------------------------- text
_CLAUSE = re.compile(r"(?<=[,;:])\s+|\s+[—–]\s+|\s+-{1,2}\s+")


def clean(text):
    return re.sub(r"\s+", " ", text.replace("­", "").replace(" ", " ")).strip()


def chunks(text, first=70, rest=170, hard=260, first_hard=110, grow=1.4):
    """A sentence cut into clauses to be made (and played) one after the other: the first chunk is short, so that the sound starts early, and each one
    may be about 1.4 times as long as the one before (a chunk is made while the one before it plays, so it must not take longer to make than that
    one takes to say).  The words stay in order and nothing is dropped."""
    text = text.strip()
    if len(text) <= first + 10:
        return [text] if text else []
    pieces = []
    for p in _CLAUSE.split(text):
        p = p.strip()
        while len(p) > (first_hard if not pieces else hard):           # a clause with no punctuation that is too long: cut on a space
            limit = first_hard if not pieces else hard
            cut = p.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)
    out, cur = [], ""
    for p in pieces:
        goal = min(rest, first * grow ** len(out))
        if cur and len(cur) + 1 + len(p) > goal:
            out.append(cur)
            cur = p
        else:
            cur = (cur + " " + p) if cur else p
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------------------------------------------------- the model
_model = None
_model_lock = threading.Lock()
_synth_lock = threading.Lock()                         # the phonemiser (espeak-ng) keeps global state: one text at a time
_sd = None


def set_model(m):
    """A test puts its own model here: m.create(text, voice=, speed=, lang=) -> (samples, sample_rate)."""
    global _model
    _model = m


def set_sounddevice(sd):
    global _sd
    _sd = sd


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            pe_deps.add_all_to_path()
            from kokoro_onnx import Kokoro
            _model = Kokoro(pe_deps.model_path(pe_deps.MODEL_FILES[0]["name"]), pe_deps.model_path(pe_deps.MODEL_FILES[1]["name"]))
        return _model


def get_sounddevice():
    global _sd
    if _sd is None:
        pe_deps.add_all_to_path()
        import sounddevice
        _sd = sounddevice
    return _sd


def synth(voice, speed, text):
    """One clause -> its samples (float32, 24 kHz)."""
    m = get_model()
    with _synth_lock:
        samples, _sr = m.create(text, voice=voice, speed=speed, lang=lang_for(voice))
    return samples


_warming = False


def warm():
    """Loads the model in the background, so that the first Play does not wait for it."""
    global _warming
    if _warming or _model is not None:
        return
    _warming = True

    def work():
        global _warming
        try:
            get_model()
        except Exception:                              # noqa: BLE001 - the real error is reported when someone speaks
            pass
        finally:
            _warming = False
    threading.Thread(target=work, daemon=True).start()


def plain(e):
    t = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return t[:200]


# ---------------------------------------------------------------------------------------------------------------------- the engine
class NaturalEngine:
    def __init__(self):
        pe_deps.add_all_to_path()
        import numpy
        self.np = numpy
        self.sd = get_sounddevice()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pe-natural")      # one clause at a time, in order
        self.voice, self.speed, self.volume = DEFAULT_VOICE, 1.0, 1.0
        self.jobs = {}                                 # (voice, speed, text) -> its clauses' futures, for sentences made ahead
        self.cur_futs = []
        self.gen = 0                                   # a new sentence (or a stop) makes what an older one still delivers worthless
        self.q = deque()                               # samples ready to be played
        self.cur, self.pos = None, 0
        self.paused = False
        self.finished = threading.Event()
        self.finished.set()
        self.total = self.got = 0
        self.all_queued = True
        self.tail = 0
        self.err = None
        self.stream = None
        self.lock = threading.Lock()                   # the sound system's thread (_cb) and the others (speak, purge, a clause made) never change the same things at once
        try:
            self.stream = self.sd.OutputStream(samplerate=RATE_HZ, channels=1, dtype="float32", callback=self._cb)
            self.stream.start()
        except Exception as e:                         # noqa: BLE001
            self.pool.shutdown(wait=False)
            raise RuntimeError(f"The sound could not be started ({plain(e)}). Is a speaker or headphones connected, and not in use by another program?") from e

    # -- what the speaker thread calls
    def apply(self, voice, rate, volume):
        self.voice = voice if voice in IDS else DEFAULT_VOICE
        self.speed = speed_for(rate)
        self.volume = max(0.0, min(1.0, float(volume) / 100.0))

    def _key(self, text):
        return (self.voice, self.speed, text)

    def _submit(self, text):
        return [self.pool.submit(synth, self.voice, self.speed, c) for c in chunks(clean(text))]

    def prefetch(self, texts):
        want = {}
        for t in texts:
            want.setdefault(self._key(t), t)
        for k in list(self.jobs):
            if k not in want:
                for f in self.jobs.pop(k):
                    f.cancel()
        for k, t in want.items():
            if k not in self.jobs:
                self.jobs[k] = self._submit(t)

    def speak(self, text):
        futs = self.jobs.pop(self._key(text), None)
        for k in [k for k in self.jobs if k[0] != self.voice or k[1] != self.speed]:      # made for another voice or speed: no longer wanted
            for f in self.jobs.pop(k):
                f.cancel()
        if futs is None:
            futs = self._submit(text)
        with self.lock:
            self.gen += 1
            gen = self.gen
            older, self.cur_futs = self.cur_futs, futs
            self.q.clear()
            self.cur, self.pos = None, 0
            self.total, self.got, self.err = len(futs), 0, None
            self.all_queued = not futs
            self.tail = 2
            self.finished.clear()
        for f in older:                                # what was still being made for the sentence before is no longer wanted
            if f not in futs:
                f.cancel()
        for f in futs:
            f.add_done_callback(lambda fut, g=gen: self._chunk(fut, g))

    def _chunk(self, fut, gen):
        """A clause is made (called in the making thread, in order)."""
        try:
            samples = self.np.asarray(fut.result(), dtype=self.np.float32) * self.volume
        except CancelledError:
            return
        except Exception as e:                         # noqa: BLE001
            samples, err = None, e
        with self.lock:
            if gen != self.gen:                        # a newer sentence (or a stop) came meanwhile: this is worth nothing
                return
            if samples is None:
                self.err = err
                self.finished.set()
                return
            self.q.append(samples)
            self.got += 1
            if self.got >= self.total:
                self.all_queued = True

    def wait(self, ms):
        """True when the sentence has been said (or could not be)."""
        done = self.finished.wait(ms / 1000.0)
        if self.err is not None:
            raise RuntimeError("The voice could not make this sentence (" + plain(self.err) + ").")
        return done

    def pause(self):
        self.paused = True                             # the stream goes on, silent: nothing of the audio is consumed

    def resume(self):
        self.paused = False

    def purge(self):
        with self.lock:
            self.gen += 1
            futs = list(self.cur_futs)
            self.q.clear()
            self.cur, self.pos = None, 0
            self.paused = False
            self.all_queued = True
            self.finished.set()
        for f in futs:
            f.cancel()

    def close(self):
        self.purge()
        for futs in self.jobs.values():
            for f in futs:
                f.cancel()
        self.jobs.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:                          # noqa: BLE001
                pass
            self.stream = None

    # -- the sound stream (called by the sound system, many times a second)
    def _cb(self, outdata, frames, tm, status):
        try:
            with self.lock:
                self._fill(outdata, frames)
        except Exception:                              # noqa: BLE001 - a callback that raises stops the whole stream: silence instead
            outdata.fill(0)

    def _fill(self, outdata, frames):
        if self.paused:
            outdata.fill(0)
            return
        out = outdata[:, 0]
        n = 0
        while n < frames:
            if self.cur is None or self.pos >= len(self.cur):
                try:
                    self.cur = self.q.popleft()
                    self.pos = 0
                except IndexError:
                    self.cur = None
                    break
                continue
            take = min(frames - n, len(self.cur) - self.pos)
            out[n:n + take] = self.cur[self.pos:self.pos + take]
            self.pos += take
            n += take
        if n < frames:
            out[n:] = 0
        if self.cur is None and not self.q and self.all_queued and not self.finished.is_set():
            self.tail -= 1                             # the last samples are still in the sound card: let them play out before saying "said"
            if self.tail <= 0:
                self.finished.set()


class KokoroBackend:
    """The natural voices, for pe_speech.MixedBackend."""

    def voice_entries(self):
        return list(VOICES)

    def has(self, voice):
        return voice in IDS

    def ready(self):
        return pe_deps.natural_ready()

    def engine(self):
        if not pe_deps.natural_ready() and _model is None:
            raise RuntimeError("The natural voices are not downloaded yet.")
        return NaturalEngine()

    def warm(self):
        if _model is None and pe_deps.natural_ready():
            warm()
