"""pb_core.py - the maths and the file work of Page Break, with no window: pages from one or more PDFs, break lines across them, segments,
what is excluded, and the export of every included segment as one combined PDF.

A page's breaks are y positions in PDF points measured from the top of the page.  Between two neighbouring breaks (and the page edges) lies a
segment; a segment is one output page unless it is excluded.  Excluded segments are remembered by their (from, to) so that they stay excluded
while other breaks are added or removed.  Needs PyMuPDF (pip install pymupdf).
"""
import json
import math
import os

import pb_deps

fitz = pb_deps.load()                 # PyMuPDF, or None: the tab then downloads it (pb_deps.install) and calls reload()

FORMAT = "openpara-pagebreak"
BASE_WIDTH_PX = 760        # the width of a page at 100 %
BASE_MAX_HEIGHT_PX = 8000
MAX_SCALE = 3.0
HARD_MAX_PX = 20000        # no page image taller than this, however far you zoom in
MAX_AREA_PX = 90_000_000   # nor larger than this many pixels in all
SNAP_PX = 8                # how near (in screen pixels) a click must be to an existing break to remove it
EDGE_PT = 4                # no break closer than this to the top or bottom edge
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.25, 4.0, 1.15


class PageBreakError(Exception):
    """Something the user can fix (a file that is not a PDF, a password, nothing to export); the message says what."""


def available():
    return fitz is not None


def reload():
    """Looks for PyMuPDF again (after pb_deps.install); True when it is there."""
    global fitz
    fitz = pb_deps.load()
    return fitz is not None


def need_fitz():
    if fitz is None:
        raise PageBreakError("Page Break is still getting PyMuPDF (it downloads it once; this needs an internet connection). Wait for the set-up to finish, or press Try again.")


def display_scale(width_pt, height_pt, zoom=1.0):
    """Pixels per point for a page at `zoom`, and the image size: (scale, width_px, height_px)."""
    base = min(BASE_WIDTH_PX / width_pt, BASE_MAX_HEIGHT_PX / height_pt, MAX_SCALE)
    if base <= 0:
        base = 0.2
    s = base * zoom
    if s * height_pt > HARD_MAX_PX:
        s = HARD_MAX_PX / height_pt
    if s * s * width_pt * height_pt > MAX_AREA_PX:
        s = math.sqrt(MAX_AREA_PX / (width_pt * height_pt))
    return s, max(1, round(width_pt * s)), max(1, round(height_pt * s))


def _key(frm, to):
    return (round(frm, 2), round(to, 2))


class Source:
    """One opened PDF file; its pages are PageItems."""

    def __init__(self, path, doc):
        self.path, self.doc = path, doc

    @property
    def name(self):
        return os.path.basename(self.path)


class PageItem:
    def __init__(self, uid, source, page_index, total, width_pt, height_pt):
        self.id = uid
        self.source = source
        self.page_index = page_index
        self.total = total                  # pages in that PDF (for the caption)
        self.width_pt, self.height_pt = width_pt, height_pt
        self.breaks = []                    # y in points from the top, sorted
        self.excluded = set()               # {(from, to)} rounded

    def caption(self):
        txt = f"{self.source.name} - page {self.page_index + 1}"
        return txt + (f" of {self.total}" if self.total > 1 else "")

    def size_text(self):
        return f"{self.width_pt / 72:.2f} x {self.height_pt / 72:.2f} in"

    def bounds(self):
        return [0.0] + self.breaks + [self.height_pt]

    def segments(self):
        """[{"from", "to", "excluded", "out_index": None}] top to bottom (out_index is filled in by Project.numbered())."""
        b = self.bounds()
        return [{"from": b[i], "to": b[i + 1], "excluded": _key(b[i], b[i + 1]) in self.excluded, "out_index": None} for i in range(len(b) - 1)]


class Project:
    """The working set: pages in the order they will be exported, plus undo."""

    def __init__(self):
        self.items = []
        self.sources = []
        self._next_id = 1
        self.undo_stack = []
        self.redo_stack = []

    # ------------------------------------------------------------------ pages
    def import_pdf(self, path):
        """Appends every page of the PDF; returns the new PageItems.  PageBreakError says why a file cannot be used."""
        need_fitz()
        try:
            doc = fitz.open(path)
        except Exception as e:                                  # noqa: BLE001 - PyMuPDF raises several kinds
            raise PageBreakError(f"Couldn't open that PDF:\n{e}") from e
        if getattr(doc, "needs_pass", False):
            doc.close()
            raise PageBreakError("That PDF is password protected. Remove the password first, then import it.")
        self.push_undo()
        src = Source(path, doc)
        self.sources.append(src)
        new = []
        for i in range(len(doc)):
            r = doc[i].rect
            if r.width <= 0 or r.height <= 0:
                continue
            it = PageItem(self._next_id, src, i, len(doc), r.width, r.height)
            self._next_id += 1
            self.items.append(it)
            new.append(it)
        if not new:
            self.sources.remove(src)
            doc.close()
            self.undo_stack.pop()
            raise PageBreakError("That PDF has no pages.")
        return new

    def clear(self):
        for s in self.sources:
            try:
                s.doc.close()
            except Exception:                                   # noqa: BLE001
                pass
        self.items, self.sources = [], []
        self.undo_stack, self.redo_stack = [], []

    def remove(self, item):
        if item in self.items:
            self.push_undo()
            self.items.remove(item)

    def move(self, item, direction):
        i = self.items.index(item)
        j = i + direction
        if 0 <= j < len(self.items):
            self.push_undo()
            self.items[i], self.items[j] = self.items[j], self.items[i]
            return True
        return False

    # ------------------------------------------------------------------ breaks
    def break_at(self, item, y_px, scale):
        """A click at y_px on the page image: removes the break within SNAP_PX of it, else adds one there.  Returns "removed", "added" or None."""
        near, dist = -1, float("inf")
        for i, b in enumerate(item.breaks):
            d = abs(b * scale - y_px)
            if d < dist:
                near, dist = i, d
        if near >= 0 and dist <= SNAP_PX:
            self.push_undo()
            item.breaks.pop(near)
            return "removed"
        pt = y_px / scale
        if EDGE_PT < pt < item.height_pt - EDGE_PT:
            self.push_undo()
            item.breaks.append(pt)
            item.breaks.sort()
            return "added"
        return None

    def toggle_exclude(self, item, index):
        segs = item.segments()
        if not 0 <= index < len(segs):
            return None
        self.push_undo()
        k = _key(segs[index]["from"], segs[index]["to"])
        if k in item.excluded:
            item.excluded.discard(k)
            return False
        item.excluded.add(k)
        return True

    def auto_break(self, inches):
        """A break every `inches` on every page (replacing the breaks that were there)."""
        if not inches or inches <= 0 or not math.isfinite(inches):
            raise PageBreakError("Enter a number of inches greater than 0.")
        step = inches * 72
        self.push_undo()
        for it in self.items:
            it.breaks, y = [], step
            while y < it.height_pt - EDGE_PT:
                it.breaks.append(y)
                y += step

    def clear_breaks(self):
        if any(it.breaks or it.excluded for it in self.items):
            self.push_undo()
        for it in self.items:
            it.breaks, it.excluded = [], set()

    # ------------------------------------------------------------------ numbering
    def numbered(self):
        """[(item, segments)] in export order; every included segment has its out_index (1, 2, 3 ...)."""
        n, out = 0, []
        for it in self.items:
            segs = it.segments()
            for s in segs:
                if not s["excluded"] and s["to"] - s["from"] >= 1:
                    n += 1
                    s["out_index"] = n
            out.append((it, segs))
        return out

    def output_count(self):
        return sum(1 for _, segs in self.numbered() for s in segs if s["out_index"])

    # ------------------------------------------------------------------ undo
    def _snapshot(self):
        return [(it, list(it.breaks), set(it.excluded)) for it in self.items]

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-100]
        self.redo_stack = []

    def _restore(self, snap):
        self.items = [it for it, _b, _e in snap]
        for it, b, e in snap:
            it.breaks, it.excluded = list(b), set(e)

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())
        return True

    # ------------------------------------------------------------------ export
    def build_output(self):
        """The combined PDF as an open PyMuPDF document, and its page count."""
        need_fitz()
        out = fitz.open()
        n = 0
        for it, segs in self.numbered():
            for s in segs:
                if not s["out_index"]:
                    continue
                h = s["to"] - s["from"]
                page = out.new_page(width=it.width_pt, height=h)
                page.show_pdf_page(page.rect, it.source.doc, it.page_index, clip=fitz.Rect(0, s["from"], it.width_pt, s["to"]))
                n += 1
        return out, n

    def suggested_name(self):
        names = list(dict.fromkeys(it.source.name for it in self.items))
        if len(names) == 1:
            return f"{os.path.splitext(names[0])[0]}-split.pdf"
        return "combined.pdf"

    def suggested_dir(self):
        return (os.path.dirname(self.items[0].source.path) if self.items else "") or "."

    def export(self, path):
        """Writes the combined PDF; returns the number of pages.  PageBreakError when nothing would be written or the file cannot be saved."""
        if not self.items:
            raise PageBreakError("Import a PDF first.")
        out, n = self.build_output()
        try:
            if not n:
                raise PageBreakError("Nothing to export: every segment is excluded.")
            try:
                out.save(path)
            except Exception as e:                              # noqa: BLE001
                raise PageBreakError(f"Couldn't save the file:\n{e}") from e
        finally:
            out.close()
        return n

    # ------------------------------------------------------------------ the project file (.oppb)
    def to_json(self, zoom=1.0, auto_inches="11"):
        return {"format": FORMAT, "version": 1, "zoom": zoom, "auto_inches": auto_inches,
                "pages": [{"source": it.source.path, "page": it.page_index, "breaks": [round(b, 3) for b in it.breaks],
                           "excluded": [list(k) for k in sorted(it.excluded)]} for it in self.items]}

    def load_json(self, d):
        """Reopens the PDFs a project file names.  Returns the list of files that could not be opened (their pages are left out)."""
        self.clear()
        missing, opened = [], {}
        for p in d.get("pages", []):
            path = p.get("source", "")
            if path in missing:
                continue
            if path not in opened:
                if not os.path.isfile(path):
                    missing.append(path)
                    continue
                try:
                    opened[path] = self.import_pdf(path)
                except PageBreakError:
                    missing.append(path)
                    continue
        self.undo_stack, self.redo_stack = [], []
        by_page = {(it.source.path, it.page_index): it for items in opened.values() for it in items}
        ordered = []
        for p in d.get("pages", []):
            it = by_page.pop((p.get("source", ""), p.get("page", -1)), None)
            if it is None:
                continue
            it.breaks = sorted(float(b) for b in p.get("breaks", []) if EDGE_PT < float(b) < it.height_pt - EDGE_PT)
            it.excluded = {_key(float(a), float(b)) for a, b in p.get("excluded", [])}
            ordered.append(it)
        self.items = ordered           # pages the file did not list are dropped (the user had removed them)
        return missing


def read_project(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        raise PageBreakError("That is not a Page Break project file.")
    return d
