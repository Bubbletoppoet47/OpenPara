"""pe_aicheck.py - running the AI-text tests over the paragraphs of a PDF, counting how many lean AI, and the words that say so (no window).

    Runner   goes through the chosen tests one after the other (only one model is in memory at a time), each over every paragraph it has no result for yet,
             so a run that was stopped, or a second run with another test added, goes on instead of starting again.  The result for a paragraph is a
             Verdict (pe_aidet), False when the paragraph is too short for that test once tokenized, or None when not yet judged.
    tally    per paragraph: "k of m tests lean AI"; per test: the share of the judged words that lean AI; and how many tests lean AI over the whole PDF
             (a test leans AI over the whole PDF when more than half of the words it judged lean AI).  No percentage is put together from the tests and
             there is no verdict - a count of tests is what is said.
"""
import csv
import time

import pe_aidet
from pe_aipacks import Cancelled

BANNER = ("Experimental. This is a hint, not proof: every test is wrong on some human writing and on some AI writing, and where each one draws its line is a "
          "starting guess that has not been checked against texts of known authorship. Made for English. Do not conclude that someone used AI from this alone.")


# ---------------------------------------------------------------------------------------------------------------------- running
def _duration(seconds):
    s = int(seconds + 0.5)
    if s < 45:
        return "less than a minute"
    m = (s + 30) // 60
    if m < 60:
        return f"about {m} minute{'s' if m != 1 else ''}"
    h, m = divmod(m, 60)
    return f"about {h} h {m:02d} min"


class Runner:
    """results: {test id: [None | False | Verdict] per window} and errors: {test id: sentence}, both filled in place (the caller keeps them between runs).
    progress(text, fraction 0..1) is called from the thread that calls go()."""

    def __init__(self, layout, results, errors, test_ids, make=None, progress=None):
        import threading
        self.layout, self.results, self.errors, self.test_ids = layout, results, errors, list(test_ids)
        self.make = make or (lambda tid: pe_aidet.CLASSES[tid]())
        self.progress = progress or (lambda text, frac=None: None)
        self.cancel = threading.Event()
        self.active = None
        self.stopped = False

    def stop(self):
        """From any thread: stop after the paragraph in hand - or at once, the model is told to give up its calculation."""
        self.cancel.set()
        t = self.active
        if t is not None:
            t.stop()

    def go(self):
        n = len(self.test_ids)
        for i, tid in enumerate(self.test_ids):
            if self.cancel.is_set():
                break
            self._one(tid, i, n)
        self.stopped = self.cancel.is_set()

    def _one(self, tid, i, n):
        wins = self.layout.windows
        res = self.results.setdefault(tid, [None] * len(wins))
        self.errors.pop(tid, None)
        todo = [k for k in range(len(wins)) if res[k] is None]
        if not todo:
            return
        test = self.make(tid)
        name = getattr(test, "name", tid)
        self.active = test
        try:
            self.progress(f"{name}: getting ready ...", i / n)
            test.load(lambda text: self.progress(text, i / n))
            t0, done = time.monotonic(), 0
            for k in todo:
                if self.cancel.is_set():
                    return
                try:
                    res[k] = test.judge(wins[k].text)
                except pe_aidet.Unjudgeable:
                    res[k] = False
                done += 1
                left = len(todo) - done
                eta = f" - {_duration((time.monotonic() - t0) / done * left)} left" if done >= 2 and left else ""
                self.progress(f"{name}: paragraph {done} of {len(todo)}{eta}", (i + done / len(todo)) / n)
        except Cancelled:
            return
        except Exception as e:                         # noqa: BLE001 - a test that cannot run is reported, the others still run
            if not self.cancel.is_set():               # (a stopped calculation raises too; that is not an error)
                msg = str(e).strip() or type(e).__name__
                self.errors[tid] = "ran out of memory" if isinstance(e, MemoryError) else msg
        finally:
            self.active = None
            try:
                test.close()
            except Exception:                          # noqa: BLE001
                pass


# ---------------------------------------------------------------------------------------------------------------------- counting
class Tally:
    def __init__(self, layout, results, test_ids):
        wins = layout.windows
        self.test_ids = [t for t in test_ids if any(isinstance(v, pe_aidet.Verdict) for v in results.get(t, ()))]
        self.per_window = []                           # (tests leaning AI, tests with a result)
        for k in range(len(wins)):
            vs = [results[t][k] for t in self.test_ids]
            vs = [v for v in vs if isinstance(v, pe_aidet.Verdict)]
            self.per_window.append((sum(1 for v in vs if v.ai), len(vs)))
        self.per_test = {}
        for t in self.test_ids:
            jw = aw = jn = an = 0
            for k, v in enumerate(results[t]):
                if isinstance(v, pe_aidet.Verdict):
                    jn += 1
                    jw += wins[k].words
                    if v.ai:
                        an += 1
                        aw += wins[k].words
            self.per_test[t] = {"windows": jn, "ai_windows": an, "words": jw, "ai_words": aw, "lean": aw * 2 > jw}
        self.leaning = sum(1 for t in self.test_ids if self.per_test[t]["lean"])

    @property
    def tests_run(self):
        return len(self.test_ids)


def count_text(k, m, tail=""):
    """'2 of 3 tests lean AI' (tail: words to put after, e.g. ' over the whole PDF')"""
    if m == 0:
        return "no result"
    return f"{k} of {m} test{'s' if m != 1 else ''} {'leans' if m == 1 else 'lean'} AI{tail}"


def window_text(tally, k):
    return count_text(*tally.per_window[k])


def overall_text(tally):
    if not tally.tests_run:
        return ""
    return count_text(tally.leaning, tally.tests_run, " over the whole PDF")


def test_line(test_cls, tally, tid):
    s = tally.per_test[tid]
    nm = test_cls.name
    share = s["ai_words"] / s["words"] if s["words"] else 0.0
    return (f"{nm}: {s['ai_windows']} of {s['windows']} paragraphs lean AI ({share:.0%} of the words) - "
            + ("leans AI overall" if s["lean"] else "does not lean AI overall"))


def window_details(layout, results, k, test_ids):
    """[(test id, sentence, leans AI or None)] for window k, in the order of test_ids."""
    out = []
    for t in test_ids:
        v = results.get(t, [None] * len(layout.windows))[k]
        nm = pe_aidet.CLASSES[t].name
        if isinstance(v, pe_aidet.Verdict):
            out.append((t, f"{nm}: {'leans AI' if v.ai else 'does not lean AI'} - {v.detail}", v.ai))
        elif v is False:
            out.append((t, f"{nm}: too short to judge", None))
        else:
            out.append((t, f"{nm}: not run", None))
    return out


def warnings(layout):
    """Sentences about what the tests could not use.  An empty list when all is as it should be."""
    out = []
    if layout.total_words == 0:
        out.append("This PDF has no text that can be read, so there is nothing to check. If it is a scan (a picture of pages), its text has to be recognized first.")
        return out
    if not layout.windows:
        out.append(f"Too short to judge: this PDF has {layout.total_words} words and none of its paragraphs is long enough ({pe_aidet.MIN_WORDS} words are the least "
                   "the tests can work with).")
        return out
    if layout.judged_words < pe_aidet.SHORT_TOTAL:
        out.append(f"This is short ({layout.judged_words} words are long enough to check): the tests are even less reliable on a short text.")
    if layout.skipped_words:
        out.append(f"{layout.skipped_words} words in very short paragraphs (headings, captions, short list items) were left out.")
    return out


def write_csv(path, layout, results, test_ids):
    """One row per paragraph with the raw number of every test: so that where a test draws its line can be checked against texts of known authorship."""
    ids = [t for t in test_ids if t in results]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        head = ["paragraph", "page", "words", "starts with"]
        for t in ids:
            head += [f"{t} value", f"{t} leans AI"]
        head.append("tests leaning AI")
        w.writerow(head)
        tally = Tally(layout, results, ids)
        for k, win in enumerate(layout.windows):
            row = [k + 1, win.page, win.words, " ".join(win.text.split()[:8])]
            for t in ids:
                v = results[t][k]
                row += [f"{v.value:.4f}", "yes" if v.ai else "no"] if isinstance(v, pe_aidet.Verdict) else ["", ""]
            ai, m = tally.per_window[k]
            row.append(f"{ai} of {m}" if m else "")
            w.writerow(row)
