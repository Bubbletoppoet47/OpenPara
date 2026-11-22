"""pe_text.py - the words and sentences of a PDF (no window): which word is under a point, which sentence a word belongs to, where a sentence
sits on the page, and the text of a selection.  This is what lets the reader start at the sentence you click.

Words come from PyMuPDF (page.get_text("words")).  A word cut by the end of a line ("exam-" / "ple") is joined; sentences end at . ! ? unless the
word is an abbreviation (Dr.  U.S.  e.g.  a list number "1."); a short block with no closing punctuation (a heading) is a sentence of its own.

The text is read page by page in short slices (begin / step / finish) so that a long book does not freeze the window; DocText(doc) does all of it
at once for a caller that does not mind.
"""
import re
import time

ABBR = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "no", "fig",
        "vol", "pp", "ch", "cf", "inc", "co", "mt", "gen", "col", "sgt", "rev",
        "hon", "ft", "ed", "eds", "al", "approx", "dept", "est", "sec"}
_TERMINAL = re.compile(r'[.!?]["\'”’)\]]*$')
_LEAD = re.compile(r'^["\'“‘(\[]+')
_SOFT = "­"


def _starts_sentence(text):
    t = _LEAD.sub("", text)
    return bool(t) and (t[0].isupper() or t[0].isdigit())


def _is_abbr(text):
    if not _TERMINAL.search(text):
        return False
    core = re.sub(r'["\'”’)\]]+$', "", text)
    if not core.endswith("."):
        return False                                     # ends in ? or !
    w = _LEAD.sub("", core[:-1]).lower()
    if not w:
        return True
    if w in ABBR:
        return True
    if len(w) == 1 and w.isalpha():
        return True                                      # initials: J. R. R.
    if re.fullmatch(r"([a-z]\.)+[a-z]", w):
        return True                                      # U.S.  e.g.  i.e.
    if w.isdigit() and len(w) <= 2:
        return True                                      # list numbering: "1."
    return False


class Token:
    __slots__ = ("text", "parts", "block", "line")

    def __init__(self, text, parts, block, line):
        self.text, self.parts, self.block, self.line = text, parts, block, line


class DocText:
    def __init__(self, doc, build=True):
        self.doc = doc
        self.npages = doc.page_count
        self.tokens = []
        self.sentences, self.sentence_texts, self.tok2sent = [], [], []
        self.page_parts = [[] for _ in range(self.npages)]
        self.next_page = 0
        self.ready = False
        if build:
            self.step(None)

    # -- building (in slices) ---------------------------------------------
    def step(self, budget_s=0.02):
        """Reads pages for about `budget_s` seconds (all of them when None).  True when the whole document has been read."""
        if self.ready:
            return True
        t0 = time.monotonic()
        while self.next_page < self.npages:
            self._read_page(self.next_page)
            self.next_page += 1
            if budget_s is not None and time.monotonic() - t0 >= budget_s:
                break
        if self.next_page >= self.npages:
            self._finish()
        return self.ready

    def _read_page(self, pno):
        try:
            words = self.doc[pno].get_text("words")
        except Exception:                                # noqa: BLE001 - a page that cannot be read has no words, the others still do
            return
        words.sort(key=lambda w: (w[5], w[6], w[7]))
        for w in words:
            txt = w[4].replace(_SOFT, "").strip()
            if txt:
                self.tokens.append(Token(txt, [(pno, (w[0], w[1], w[2], w[3]))], (pno, w[5]), (pno, w[5], w[6])))

    def _finish(self):
        self._merge_hyphens()
        self._split_sentences()
        self.page_parts = [[] for _ in range(self.npages)]
        for ti, t in enumerate(self.tokens):
            for pno, r in t.parts:
                self.page_parts[pno].append((r[0], r[1], r[2], r[3], ti))
        self.ready = True

    def _merge_hyphens(self):
        out, i, toks = [], 0, self.tokens
        while i < len(toks):
            t = toks[i]
            if (i + 1 < len(toks) and len(t.text) > 1 and t.text.endswith("-")
                    and t.text[-2].isalpha() and toks[i + 1].line != t.line
                    and toks[i + 1].text[:1].islower()):
                n = toks[i + 1]
                out.append(Token(t.text[:-1] + n.text, t.parts + n.parts, t.block, t.line))
                i += 2
            else:
                out.append(t)
                i += 1
        self.tokens = out

    def _split_sentences(self):
        toks = self.tokens
        n = len(toks)
        spans, start = [], 0
        for i, t in enumerate(toks):
            nxt = toks[i + 1] if i + 1 < n else None
            end = False
            if _TERMINAL.search(t.text) and not _is_abbr(t.text):
                end = nxt is None or _starts_sentence(nxt.text)
            if not end and nxt is not None and nxt.block != t.block:
                # a short block with no closing punctuation is a heading / label
                if (i - start + 1) <= 15 and not re.search(r"[,;:\-]$", t.text) and _starts_sentence(nxt.text):
                    end = True
            if end:
                spans.append((start, i))
                start = i + 1
        if start < n:
            spans.append((start, n - 1))
        self.sentences = spans
        self.sentence_texts = [" ".join(toks[a].text for a in range(s, e + 1)) for s, e in spans]
        self.tok2sent = [0] * n
        for k, (s, e) in enumerate(spans):
            for i in range(s, e + 1):
                self.tok2sent[i] = k

    # -- queries ----------------------------------------------------------
    def token_at(self, pno, x, y, max_d=8.0):
        """The word nearest to the point (x, y) of page pno, when it is within max_d points; else None."""
        best, bd = None, max_d
        for x0, y0, x1, y1, ti in self.page_parts[pno]:
            dx = max(x0 - x, 0.0, x - x1)
            dy = max(y0 - y, 0.0, y - y1)
            d = (dx * dx + dy * dy) ** 0.5
            if d < bd or (d == 0.0 and best is None):
                bd, best = d, ti
                if d == 0.0:
                    break
        return best

    def rects_for_tokens(self, a, b):
        """[(page, (x0, y0, x1, y1))]: the words a..b, the words of one line merged into one rectangle."""
        out = []
        for ti in range(a, b + 1):
            for pno, (x0, y0, x1, y1) in self.tokens[ti].parts:
                if out:
                    o = out[-1]
                    if o[0] == pno:
                        h = min(o[4] - o[2], y1 - y0)
                        overlap = min(o[4], y1) - max(o[2], y0)
                        if overlap > 0.6 * h and -1 <= x0 - o[3] < 1.5 * (y1 - y0) + 4:
                            o[1] = min(o[1], x0)
                            o[2] = min(o[2], y0)
                            o[3] = max(o[3], x1)
                            o[4] = max(o[4], y1)
                            continue
                out.append([pno, x0, y0, x1, y1])
        return [(o[0], (o[1], o[2], o[3], o[4])) for o in out]

    def sentence_rects(self, k):
        s, e = self.sentences[k]
        return self.rects_for_tokens(s, e)

    def text_for_tokens(self, a, b):
        return " ".join(self.tokens[i].text for i in range(a, b + 1))

    def first_sentence_from(self, pno, y):
        """The first sentence at or after height y (points from the top) on page pno; None when the document has no text."""
        for p in range(pno, self.npages):
            for x0, y0, x1, y1, ti in self.page_parts[p]:
                if p > pno or y1 > y:
                    return self.tok2sent[ti]
        return 0 if self.sentences else None
