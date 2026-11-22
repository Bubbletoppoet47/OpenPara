"""pe_pdfio.py - highlights stored inside the PDF itself, with undo and redo (no window, so it is tested without one).

A highlight is a real PDF highlight annotation, so it shows in Edge and Acrobat too.  Edits is the list of what was done to one open PDF:
add (one annotation per page that the selection touches), remove, undo, redo.  Nothing is written to the file until save_in_place() is called;
`dirty` says whether what is in memory differs from what was last written.
"""
import os

import pb_deps

pymupdf = pb_deps.load()                          # PyMuPDF; None until the editor has downloaded it (reload() looks again)

COLORS = {
    "Yellow": (1.0, 0.92, 0.23),
    "Green": (0.55, 0.90, 0.45),
    "Pink": (1.0, 0.55, 0.75),
    "Blue": (0.50, 0.80, 1.00),
}


def reload():
    global pymupdf
    pymupdf = pb_deps.load()
    return pymupdf is not None


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb)


class SaveError(Exception):
    """The file cannot be updated in place; the message says why."""


def can_save_in_place(doc):
    try:
        return bool(doc.can_save_incrementally())
    except Exception:                             # noqa: BLE001
        return False


def save_in_place(doc):
    """Appends the changes to the original file and returns the document opened again.  Raises SaveError (with a sentence for the person) when that
    is not possible: a PDF that is encrypted or was repaired when it was opened cannot be added to, and a file that another program holds open cannot
    be written.

    The document is opened again because of how MuPDF saves: a highlight that is added AFTER an incremental save of the same open document is never
    written by the next one (the first save is fine, the second silently leaves it out).  A document opened afresh does not have the problem."""
    if not can_save_in_place(doc):
        raise SaveError("This PDF cannot be updated in place (it is protected, or it was repaired when it was opened).")
    path = doc.name
    try:
        doc.saveIncr()
    except Exception as e:                        # noqa: BLE001 - the library's messages vary; what matters is that nothing was written
        raise SaveError(_plain(e)) from e
    try:
        new = pymupdf.open(path)
    except Exception as e:                        # noqa: BLE001
        raise SaveError("The highlights were saved, but the file could not be opened again: " + _plain(e)) from e
    try:
        doc.close()
    except Exception:                             # noqa: BLE001
        pass
    return new


def save_copy(doc, path):
    """Writes the whole PDF, with its highlights, to a new file."""
    try:
        doc.save(path, garbage=0)
    except Exception as e:                        # noqa: BLE001
        raise SaveError(_plain(e)) from e


def _plain(e):
    t = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    if "Permission" in t or "denied" in t or "being used" in t:
        return "The file is locked or read-only (is it open in another program?)."
    return t


def _quads_rects(vertices):
    """The rectangles of a highlight annotation (its corner points come four to a rectangle)."""
    out = []
    v = vertices or []
    for k in range(0, len(v), 4):
        pts = v[k:k + 4]
        if len(pts) < 4:
            continue
        out.append((min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)))
    return out


class Edits:
    """The highlights of one open PDF and their history."""

    def __init__(self, doc):
        self.doc = doc
        self.undo_stack, self.redo_stack = [], []
        self.saved_at = 0                          # len(undo_stack) when the file was last written; -1 when no state of the history is the saved one
        self.xref_of, self.id_of, self.next_id = {}, {}, 1      # a highlight keeps its id when it is put back (its xref then changes)

    # -- state
    @property
    def dirty(self):
        return len(self.undo_stack) != self.saved_at

    def mark_saved(self):
        self.saved_at = len(self.undo_stack)

    def save(self):
        """Writes the changes into the file (save_in_place); the document is replaced by the one that was opened again, which is returned."""
        self.doc = save_in_place(self.doc)
        self.mark_saved()
        return self.doc

    def reset(self, doc=None):
        if doc is not None:
            self.doc = doc
        self.undo_stack, self.redo_stack, self.saved_at = [], [], 0
        self.xref_of, self.id_of = {}, {}

    # -- one annotation
    def _add_item(self, item):
        page = self.doc[item["pno"]]               # keep a reference: the annotation is bound to its page
        annot = page.add_highlight_annot(quads=[pymupdf.Rect(r) for r in item["rects"]])
        annot.set_colors(stroke=item["rgb"])
        annot.update()
        self.xref_of[item["id"]] = annot.xref
        self.id_of[annot.xref] = item["id"]

    def _del_item(self, item):
        xref = self.xref_of.pop(item["id"], None)
        self.id_of.pop(xref, None)
        page = self.doc[item["pno"]]
        for annot in page.annots():
            if annot.xref == xref:
                page.delete_annot(annot)
                return True
        return False

    def _new_id(self):
        self.next_id += 1
        return self.next_id - 1

    def _apply(self, op, forward):
        add = (op["kind"] == "add") == forward
        for item in op["items"]:
            (self._add_item if add else self._del_item)(item)
        return sorted({i["pno"] for i in op["items"]})

    def _push(self, op):
        if self.saved_at > len(self.undo_stack):    # the saved state lies in a future that is being thrown away
            self.saved_at = -1
        self.undo_stack.append(op)
        self.redo_stack.clear()

    # -- the edits
    def add(self, rects_by_page, rgb):
        """rects_by_page: [(page_no, (x0, y0, x1, y1))].  One annotation per page.  Returns the pages that changed."""
        by = {}
        for pno, r in rects_by_page:
            by.setdefault(pno, []).append(tuple(r))
        op = {"kind": "add", "items": [{"id": self._new_id(), "pno": p, "rects": rs, "rgb": tuple(rgb)} for p, rs in sorted(by.items())]}
        if not op["items"]:
            return []
        pages = self._apply(op, True)
        self._push(op)
        return pages

    def find(self, pno, x, y):
        """The xref of the highlight under the point (x, y) of page pno, else None."""
        page = self.doc[pno]
        pt = pymupdf.Point(x, y)
        for annot in page.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]):
            for r in _quads_rects(annot.vertices):
                if pt in pymupdf.Rect(r):
                    return annot.xref
        return None

    def remove(self, pno, xref):
        """Takes one highlight away (undo puts it back).  True when it was there."""
        page = self.doc[pno]
        for annot in page.annots():
            if annot.xref == xref:
                rects = _quads_rects(annot.vertices)
                rgb = (annot.colors or {}).get("stroke") or COLORS["Yellow"]
                hid = self.id_of.get(xref)
                if hid is None:                                  # a highlight that was already in the file
                    hid = self._new_id()
                    self.xref_of[hid], self.id_of[xref] = xref, hid
                item = {"id": hid, "pno": pno, "rects": rects, "rgb": tuple(rgb)}
                self._del_item(item)
                self._push({"kind": "remove", "items": [item]})
                return True
        return False

    def undo(self):
        """-> the pages that changed, or None when there is nothing to undo."""
        if not self.undo_stack:
            return None
        op = self.undo_stack.pop()
        pages = self._apply(op, False)
        self.redo_stack.append(op)
        return pages

    def redo(self):
        if not self.redo_stack:
            return None
        op = self.redo_stack.pop()
        pages = self._apply(op, True)
        self.undo_stack.append(op)
        return pages

    def count(self, pno=None):
        """How many highlights the PDF has (on page pno, or in all)."""
        pages = [pno] if pno is not None else range(self.doc.page_count)
        return sum(len(list(self.doc[p].annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]))) for p in pages)


def open_pdf(path, password_for=None):
    """Opens a PDF.  A protected one asks password_for(path) -> str or None.  Raises ValueError with a sentence for the person."""
    if pymupdf is None:
        raise ValueError("PyMuPDF is not available yet.")
    if not os.path.isfile(path):
        raise ValueError("That file is not there.")
    try:
        doc = pymupdf.open(path)
    except Exception as e:                        # noqa: BLE001
        raise ValueError(f"It is not a PDF that can be opened ({_plain(e)}).") from e
    if doc.needs_pass:
        pw = password_for(path) if password_for else None
        if not pw or not doc.authenticate(pw):
            doc.close()
            raise ValueError("The password was not accepted." if pw else "This PDF is protected by a password.")
    return doc
