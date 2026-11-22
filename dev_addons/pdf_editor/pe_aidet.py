"""pe_aidet.py - the paragraphs of a PDF and the three tests that look at them for signs of AI-written text (no window; pe_aicheck.py runs them, pe_reader.py shows them).

No test here is proof.  Each one measures a different thing about how predictable a stretch of text is, and each is wrong on some human text and on some AI text;
that is why several run side by side and the answer is how many of them lean AI, never a percentage and never a verdict.

    classifier   a RoBERTa-base model that was trained on human and AI text (the RAID benchmark) and says which one a stretch looks like.   (light, ~130 MB)
    binoculars   two small language models (Qwen2.5-0.5B and its Instruct version) are asked how surprised each is by the text and how much they disagree
                 about it; Hans et al. 2024, "Spotting LLMs with Binoculars".  AI text is unsurprising to both: a LOW score.             (light, ~1 GB)
    fastdetect   one big language model (Mistral-7B-Instruct, 4-bit) is asked whether the words are more likely than the words it would have picked
                 itself; Bao et al. 2024, "Fast-DetectGPT" (the analytic form, one model for both roles).  A HIGH score is AI.            (heavy, ~5 GB)

The thresholds below are STARTING GUESSES.  The ones in the papers were found for other models (full-size, not 4-bit or 8-bit) and could not be tried on the models used
here when this was written, so where each test puts its line is not known to be right.  The raw numbers are shown (and can be saved) so that they can be checked
against texts whose author is known, and the line moved.

Everything runs on onnxruntime + tokenizers (pe_deps AI pack) - no PyTorch.  The models are ONNX files from pe_aipacks.  The ONNX files of different exports ask for
different inputs (position ids, empty key/value caches, ...), so the feed is built from what the session says it wants rather than from one assumed layout.
"""
import bisect
import json
import math
import os
import re
import sys
import threading
from collections import namedtuple

import pe_aipacks
import pe_deps
from pe_aipacks import Cancelled
from pe_text import _LEAD, _TERMINAL

MIN_WORDS = 80          # a stretch of text shorter than this is not judged (the tests are unreliable on it)
TARGET_WORDS = 160      # a long paragraph is cut at a sentence end once it has this many words
CAP_WORDS = 250         # ... and a piece is never longer than this, except that a rest of less than MIN_WORDS is joined to the piece before it
MAX_TOKENS = 512        # what a model is given at most
MIN_TOKENS = 12         # fewer tokens than this after tokenizing: the text cannot be judged
SHORT_TOTAL = 250       # a document with fewer judged words than this gets a warning on top of the usual one
CHUNK = 32              # positions whose probabilities are worked out at a time (a 150,000-word vocabulary makes one position 600 KB)

THRESHOLDS = {"classifier": 0.5, "binoculars": 0.90, "fastdetect": 1.0}     # STARTING GUESSES, see above

Verdict = namedtuple("Verdict", "value ai detail")


class Unjudgeable(ValueError):
    """This stretch of text is too short once it is cut into the model's tokens; it gets no result from this test."""


# ---------------------------------------------------------------------------------------------------------------------- the computer
def memory():
    """(total, available) bytes of memory, each None when it cannot be told."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return float(vm.total), float(vm.available)
    except Exception:                                  # noqa: BLE001
        pass
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                            ("aext", ctypes.c_ulonglong)]
            st = _Status()
            st.length = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return float(st.total), float(st.avail)
        else:
            total = avail = None
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total = float(line.split()[1]) * 1024.0
                    elif line.startswith("MemAvailable:"):
                        avail = float(line.split()[1]) * 1024.0
            return total, avail
    except Exception:                                  # noqa: BLE001
        pass
    return None, None


def _np():
    pe_deps.add_all_to_path()
    import numpy
    return numpy


# ---------------------------------------------------------------------------------------------------------------------- paragraphs -> windows
class Window:
    """A stretch of the document that is judged as a whole: one paragraph, a long paragraph cut at a sentence end, or short paragraphs in a row."""
    __slots__ = ("runs", "text", "words", "page")

    def __init__(self, runs, text, words, page=0):
        self.runs, self.text, self.words, self.page = runs, text, words, page          # page: the number (from 1) of the page it starts on

    @property
    def first(self):
        return self.runs[0][0]

    @property
    def last(self):
        return self.runs[-1][1]


class Layout:
    """The windows of one document, and how many words were left out because they were too short."""

    def __init__(self, windows, skipped_words, total_words):
        self.windows, self.skipped_words, self.total_words = windows, skipped_words, total_words
        runs = sorted((a, b, k) for k, w in enumerate(windows) for a, b in w.runs)
        self._runs = runs
        self._keys = [r[0] for r in runs]

    @property
    def judged_words(self):
        return sum(w.words for w in self.windows)

    def window_at(self, tok):
        """The index of the window that holds token `tok`, or None."""
        i = bisect.bisect_right(self._keys, tok) - 1
        if i >= 0 and self._runs[i][0] <= tok <= self._runs[i][1]:
            return self._runs[i][2]
        return None


def _isword(text):
    return any(c.isalpha() for c in text)


def _runs_of(idxs):
    runs = []
    for i in idxs:
        if runs and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [tuple(r) for r in runs]


def _blocks(tokens):
    out, i, n = [], 0, len(tokens)
    while i < n:
        j, blk = i, tokens[i].block
        while j + 1 < n and tokens[j + 1].block == blk:
            j += 1
        out.append((i, j))
        i = j + 1
    return out


def _continues(tokens, last, first):
    """The block that begins at token `first` goes on with the sentence the block that ends at `last` left open."""
    t = tokens[last].text
    if _TERMINAL.search(t):
        return False
    return _LEAD.sub("", tokens[first].text)[:1].islower() or t[-1:] in ",;:-"


def build_layout(doc):
    """doc: a pe_text.DocText that has been read (tokens, sentences, tok2sent).  Page numbers and running heads (a block of four words or fewer that does not end
    in a full stop) are left out; blocks that stop in the middle of a sentence are joined to the next; a paragraph of MIN_WORDS or more is judged on its own
    (cut at sentence ends when it is longer than CAP_WORDS); shorter paragraphs in a row are judged together once they add up to MIN_WORDS."""
    tokens = doc.tokens
    isword = [_isword(t.text) for t in tokens]
    total = sum(isword)
    paras = []                                         # [runs, words]
    for a, b in _blocks(tokens):
        if b - a + 1 <= 4 and not _TERMINAL.search(tokens[b].text):
            continue
        w = sum(isword[a:b + 1])
        if paras and _continues(tokens, paras[-1][0][-1][1], a):
            paras[-1][0].append((a, b))
            paras[-1][1] += w
        else:
            paras.append([[(a, b)], w])
    windows, skipped, pend = [], 0, []

    def text_of(runs):
        return " ".join(tokens[i].text for a, b in runs for i in range(a, b + 1))

    def make(runs, w):
        return Window(runs, text_of(runs), w, tokens[runs[0][0]].parts[0][0] + 1)

    def flush():
        nonlocal pend, skipped
        if pend:
            w = sum(p[1] for p in pend)
            if w >= MIN_WORDS:
                runs = [r for p in pend for r in p[0]]
                windows.append(make(runs, w))
            else:
                skipped += w
        pend = []

    for runs, w in paras:
        if w >= MIN_WORDS:
            flush()
            if w <= CAP_WORDS:
                windows.append(make(runs, w))
                continue
            pieces, cur, cw = [], [], 0
            for a, b in runs:
                for i in range(a, b + 1):
                    cur.append(i)
                    cw += isword[i]
                    if (cw >= TARGET_WORDS and doc.sentences[doc.tok2sent[i]][1] == i) or cw >= CAP_WORDS:
                        pieces.append((cur, cw))
                        cur, cw = [], 0
            if cur:
                if cw >= MIN_WORDS or not pieces:
                    pieces.append((cur, cw))
                else:
                    pieces[-1] = (pieces[-1][0] + cur, pieces[-1][1] + cw)
            for idxs, cw in pieces:
                r = _runs_of(idxs)
                windows.append(make(r, cw))
        else:
            pend.append([runs, w])
            if sum(p[1] for p in pend) >= TARGET_WORDS:
                flush()
    flush()
    return Layout(windows, skipped, total)


# ---------------------------------------------------------------------------------------------------------------------- the arithmetic
def _log_softmax(x):
    np = _np()
    x = x.astype(np.float32, copy=False)
    z = x - x.max(axis=-1, keepdims=True)
    return z - np.log(np.exp(z).sum(axis=-1, keepdims=True))


def binoculars_score(observer_logits, performer_logits, ids):
    """(score, log-perplexity, log-cross-perplexity).  Row t of both logits predicts token ids[t+1].  As in the authors' code (github.com/ahans1/Binoculars):
    the perplexity is the performer's, the cross-perplexity is the average over positions of -sum_v softmax(observer)_v * log_softmax(performer)_v,
    and the score is the first divided by the second."""
    np = _np()
    n = len(ids) - 1
    if n < 1:
        raise Unjudgeable("too few tokens")
    if observer_logits.shape[-1] != performer_logits.shape[-1]:
        raise RuntimeError("the two models do not share a vocabulary")
    labels = np.asarray(ids[1:])
    nll = xent = 0.0
    for s in range(0, n, CHUNK):
        e = min(n, s + CHUNK)
        lq = _log_softmax(performer_logits[s:e])
        p = np.exp(_log_softmax(observer_logits[s:e]))
        xent += float(-(p * lq).sum(dtype=np.float64))
        nll += float(-lq[np.arange(e - s), labels[s:e]].astype(np.float64).sum())
    ppl, x = nll / n, xent / n
    if not (math.isfinite(ppl) and math.isfinite(x) and x > 0):
        raise RuntimeError("the model gave numbers that cannot be used")
    return ppl / x, ppl, x


def fastdetect_score(logits, ids):
    """The analytic Fast-DetectGPT criterion with one model as both the sampling and the scoring model:
    (log-likelihood of the text - its expectation) / its standard deviation, summed over positions.  High = more like what the model itself would write."""
    np = _np()
    n = len(ids) - 1
    if n < 1:
        raise Unjudgeable("too few tokens")
    labels = np.asarray(ids[1:])
    ll = mean_ref = var = 0.0
    for s in range(0, n, CHUNK):
        e = min(n, s + CHUNK)
        lp = _log_softmax(logits[s:e])
        p = np.exp(lp)
        ll += float(lp[np.arange(e - s), labels[s:e]].astype(np.float64).sum())
        m = (p * lp).sum(axis=-1, dtype=np.float64)
        mean_ref += float(m.sum())
        var += float(((p * lp * lp).sum(axis=-1, dtype=np.float64) - m * m).sum())
    if not (math.isfinite(ll) and math.isfinite(mean_ref) and math.isfinite(var)):
        raise RuntimeError("the model gave numbers that cannot be used")
    if var <= 0:
        return 0.0
    return (ll - mean_ref) / math.sqrt(var)


# ---------------------------------------------------------------------------------------------------------------------- an ONNX model
_DTYPES = {"tensor(int64)": "int64", "tensor(int32)": "int32", "tensor(float)": "float32", "tensor(float16)": "float16", "tensor(double)": "float64",
           "tensor(bool)": "bool"}


def build_feed(session, ids):
    """What `session` asks for, for one sequence of token ids: ids, an all-ones mask, positions, token types, and an empty key/value cache for each 'past_*' input."""
    np = _np()
    n = len(ids)
    feed = {}
    for inp in session.get_inputs():
        nm = inp.name
        dt = np.dtype(_DTYPES.get(inp.type, "int64"))
        if nm == "input_ids":
            feed[nm] = np.asarray(ids, dtype=dt)[None, :]
        elif nm == "attention_mask":
            feed[nm] = np.ones((1, n), dtype=dt)
        elif nm == "position_ids":
            feed[nm] = np.arange(n, dtype=dt)[None, :]
        elif nm == "token_type_ids":
            feed[nm] = np.zeros((1, n), dtype=dt)
        elif nm == "use_cache_branch":
            feed[nm] = np.zeros((1,), dtype=dt)
        elif "past" in nm:
            shape = []
            for d in inp.shape:
                if isinstance(d, int):
                    shape.append(d)
                else:
                    low = str(d).lower()
                    shape.append(0 if "past" in low else (n if "sequence" in low else 1))
            feed[nm] = np.zeros(shape, dtype=dt)
        else:
            raise RuntimeError(f"this model file asks for an input that is not known here ({nm})")
    return feed


class Model:
    """One ONNX model with its tokenizer: ids = encode(text); run(ids) -> the logits."""

    def __init__(self, pid, heavy=False):
        pe_deps.add_all_to_path()
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = pe_aipacks.pack_dir(pid)
        so = ort.SessionOptions()
        so.log_severity_level = 3
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        if heavy:
            so.enable_cpu_mem_arena = False
            so.enable_mem_pattern = False
        self.pid = pid
        self.sess = ort.InferenceSession(os.path.join(d, "model.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        self.tok.enable_truncation(max_length=MAX_TOKENS)
        self.ro = ort.RunOptions()
        outs = [o.name for o in self.sess.get_outputs()]
        self.out = "logits" if "logits" in outs else outs[0]

    def encode(self, text):
        return _np().asarray(self.tok.encode(text).ids, dtype="int64")

    def vocab(self):
        return self.tok.get_vocab_size()

    def run(self, ids):
        out = self.sess.run([self.out], build_feed(self.sess, ids), self.ro)[0]
        return out[0] if out.ndim == 3 and out.shape[0] == 1 else out

    def logits(self, ids):
        """(len(ids), vocabulary) - what a language model says about the next token at each position."""
        out = self.run(ids)
        if out.ndim != 2 or out.shape[0] != len(ids):
            raise RuntimeError("this model file only gives the scores for the last word, not for every word of the text")
        return out

    def stop(self):
        try:
            self.ro.terminate = True
        except Exception:                              # noqa: BLE001
            pass


# ---------------------------------------------------------------------------------------------------------------------- the tests
class Test:
    id = ""
    name = ""
    blurb = ""
    heavy = False
    packs = ()
    ram_mb = 0                                         # what the test needs free, on top of the program, when it runs
    lean_text = ""                                     # how the number reads

    def __init__(self):
        self.models = []

    # -- what the person is told before anything is downloaded
    @classmethod
    def missing_mb(cls):
        return pe_aipacks.total_mb(cls.packs)

    @classmethod
    def ready(cls):
        return all(pe_aipacks.pack_ready(p) for p in cls.packs) and pe_deps.ai_ready()

    @classmethod
    def threshold(cls):
        return THRESHOLDS[cls.id]

    # -- running
    def load(self, say=None):
        raise NotImplementedError

    def judge(self, text):
        raise NotImplementedError

    def stop(self):
        for m in self.models:
            m.stop()

    def close(self):
        self.models = []


def _softmax(v):
    m = max(v)
    e = [math.exp(x - m) for x in v]
    s = sum(e)
    return [x / s for x in e]


_AI_WORDS = {"ai", "machine", "generated", "fake", "chatgpt", "gpt", "llm", "synthetic", "bot", "artificial"}


def ai_label_index(config):
    """(index of the 'AI' class, guessed) from a model's config.json."""
    labels = (config or {}).get("id2label") or {}
    for k, v in labels.items():
        w = set(re.findall(r"[a-z]+", str(v).lower()))
        if w & _AI_WORDS and "human" not in w:
            return int(k), False
    return 1, True


class ClassifierTest(Test):
    id = "classifier"
    name = "Trained classifier"
    blurb = "a model that was trained on human and AI text and says which one the paragraph looks like"
    packs = ("classifier",)
    ram_mb = 600
    lean_text = "score from 0 (human) to 1 (AI); leans AI from {t:g}"

    def load(self, say=None):
        if say:
            say("Loading the classifier ...")
        with open(pe_aipacks.file_path("classifier", "config.json"), encoding="utf-8") as f:
            self.ai_index, self.guessed = ai_label_index(json.load(f))
        m = Model("classifier")
        self.models = [m]

    def judge(self, text):
        m = self.models[0]
        ids = m.encode(text)
        if len(ids) < MIN_TOKENS:
            raise Unjudgeable("too few tokens")
        out = [float(x) for x in m.run(ids).reshape(-1)]
        if len(out) < 2 or not all(math.isfinite(x) for x in out):
            raise RuntimeError("the classifier gave numbers that cannot be used")
        p = _softmax(out)[min(self.ai_index, len(out) - 1)]
        thr = self.threshold()
        return Verdict(p, p >= thr, f"score {p:.2f} ({'AI' if p >= thr else 'human'} side of {thr:g})" + (" - which class is AI was guessed" if self.guessed else ""))


class BinocularsTest(Test):
    id = "binoculars"
    name = "Binoculars"
    blurb = "two small language models compare how surprised they are by the paragraph; AI text surprises both less"
    packs = ("qwen05", "qwen05i")
    ram_mb = 2200
    lean_text = "score; leans AI below {t:g} (lower = less surprising)"

    def load(self, say=None):
        if say:
            say("Loading the two small language models ...")
        a = Model("qwen05")
        b = Model("qwen05i")
        self.models = [a, b]
        probe = "The quick brown fox jumps over the lazy dog, 12 times."
        if a.vocab() != b.vocab() or list(a.encode(probe)) != list(b.encode(probe)):
            raise RuntimeError("the two models do not use the same word pieces, so they cannot be compared")

    def judge(self, text):
        obs, perf = self.models
        ids = obs.encode(text)
        if len(ids) < MIN_TOKENS:
            raise Unjudgeable("too few tokens")
        score, ppl, x = binoculars_score(obs.logits(ids), perf.logits(ids), ids)
        thr = self.threshold()
        return Verdict(score, score < thr, f"score {score:.3f} ({'AI' if score < thr else 'human'} side of {thr:g}; surprise {ppl:.2f}, disagreement {x:.2f})")


class FastDetectTest(Test):
    id = "fastdetect"
    name = "Fast-DetectGPT (7B)"
    blurb = "a 7-billion-parameter model checks whether the words are the ones it would have chosen itself"
    heavy = True
    packs = ("mistral7",)
    ram_mb = 5600
    lean_text = "score; leans AI from {t:g} (higher = more like the model's own choices)"

    def load(self, say=None):
        if say:
            say("Loading the 7-billion-parameter model (this takes a while) ...")
        self.models = [Model("mistral7", heavy=True)]

    def judge(self, text):
        m = self.models[0]
        ids = m.encode(text)
        if len(ids) < MIN_TOKENS:
            raise Unjudgeable("too few tokens")
        d = fastdetect_score(m.logits(ids), ids)
        thr = self.threshold()
        return Verdict(d, d >= thr, f"score {d:.2f} ({'AI' if d >= thr else 'human'} side of {thr:g})")


CLASSES = {c.id: c for c in (ClassifierTest, BinocularsTest, FastDetectTest)}
ORDER = ["classifier", "binoculars", "fastdetect"]
