"""pe_ocr.py - pictures of text -> the words in them -> a PDF with real, selectable text (so it can be read aloud and highlighted).

Ported from Read Aloud's ocr_to_pdf.py.  The steps, each usable without a window:
    read_paragraphs(path)         one picture -> its paragraphs (OCR boxes -> lines -> paragraphs)
    make_pdf(per_image, out)      the paragraphs of all pictures -> one PDF (a paragraph cut by the edge of one photo continues on the next)

The text reader is RapidOCR on onnxruntime; both are downloaded the first time (pe_deps.install_ocr) and imported only here, when a picture is read.
read_paragraphs does not touch PyMuPDF, so it can run in a thread while the editor shows PDFs; make_pdf does, so it runs on the window's own thread.
"""
import html
import logging
import os
import re
import statistics

import pe_deps
import pe_pdfio as pio

_engine = None
_END = re.compile(r'[.!?]["\'”’)\]]*$')

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def heic_ok():
    """iPhone .heic photos open only when pillow_heif happens to be installed (nothing here downloads it)."""
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        return True
    except Exception:                                  # noqa: BLE001
        return False


def image_exts():
    return IMAGE_EXTS + ((".heic", ".heif") if heic_ok() else ())


def natural_key(path):
    """photo2 before photo10."""
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


# ---------------------------------------------------------------------------------------------------------------------- the engine
def set_engine(engine):
    """A test puts its own engine here: engine(array) -> an object with .boxes and .txts."""
    global _engine
    _engine = engine


def get_engine():
    global _engine
    if _engine is None:
        pe_deps.add_to_path(pe_deps.OCR)
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        from rapidocr import RapidOCR
        _engine = RapidOCR()
    return _engine


class Row:
    """One visual line of text (OCR boxes on the same baseline merged)."""

    def __init__(self, text, x0, y0, x1, y1):
        self.text, self.x0, self.y0, self.x1, self.y1 = text, x0, y0, x1, y1

    @property
    def h(self):
        return max(1.0, self.y1 - self.y0)


def load_image(path, max_side=3200):
    """The picture as a BGR array for the engine; turned upright by its camera data, shrunk when it is huge."""
    import numpy as np
    from PIL import Image, ImageOps
    img = Image.open(path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    return np.array(img)[:, :, ::-1]


def ocr_rows(path, max_side=3200):
    import numpy as np
    res = get_engine()(load_image(path, max_side))
    if res is None or getattr(res, "boxes", None) is None or getattr(res, "txts", None) is None:
        return []
    boxes = []
    for box, txt in zip(res.boxes, res.txts):
        txt = (txt or "").strip()
        if not txt:
            continue
        b = np.array(box)
        boxes.append(Row(txt, float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 0].max()), float(b[:, 1].max())))
    return merge_boxes_into_rows(boxes)


def merge_boxes_into_rows(boxes):
    boxes = sorted(boxes, key=lambda r: (r.y0 + r.y1) / 2)
    rows = []                                          # each: list of boxes
    for b in boxes:
        placed = False
        if rows:
            cur = rows[-1]
            cy0 = min(r.y0 for r in cur)
            cy1 = max(r.y1 for r in cur)
            overlap = min(cy1, b.y1) - max(cy0, b.y0)
            if overlap > 0.5 * min(cy1 - cy0, b.h):
                cur.append(b)
                placed = True
        if not placed:
            rows.append([b])
    out = []
    for cur in rows:
        cur.sort(key=lambda r: r.x0)
        out.append(Row(" ".join(r.text for r in cur), min(r.x0 for r in cur), min(r.y0 for r in cur), max(r.x1 for r in cur), max(r.y1 for r in cur)))
    out.sort(key=lambda r: r.y0)
    return out


def _join(a, b):
    """Join two lines of one paragraph, repairing end-of-line hyphenation."""
    if len(a) > 1 and a.endswith("-") and a[-2].isalpha() and b[:1].islower():
        return a[:-1] + b
    return a + " " + b


def rows_to_paragraphs(rows):
    if not rows:
        return []
    h = statistics.median(r.h for r in rows)
    xs = sorted(r.x0 for r in rows)
    margin = xs[len(xs) // 4]
    right = max(r.x1 for r in rows)
    width = max(1.0, right - margin)
    paras = [rows[0].text]
    for prev, cur in zip(rows, rows[1:]):
        gap = cur.y0 - prev.y1
        new = False
        if gap > 0.85 * h:
            new = True
        elif cur.x0 - margin > 1.0 * h and _END.search(prev.text):
            new = True                                 # indented first line
        elif (prev.x1 - margin) < 0.6 * width and _END.search(prev.text):
            new = True                                 # short last line of a paragraph
        if new:
            paras.append(cur.text)
        else:
            paras[-1] = _join(paras[-1], cur.text)
    return [re.sub(r"\s+", " ", p).strip() for p in paras if p.strip()]


def read_paragraphs(path):
    """One picture -> its paragraphs.  Raises ValueError with a sentence for the person when the picture cannot be opened."""
    try:
        rows = ocr_rows(path)
    except (OSError, ValueError) as e:
        raise ValueError(f"{os.path.basename(path)} could not be opened as a picture ({e}).") from e
    return rows_to_paragraphs(rows)


def merge_across(per_image):
    """A paragraph cut by the edge of one photo continues on the next."""
    out = []
    for paras in per_image:
        paras = list(paras)
        if out and paras and not _END.search(out[-1]) and paras[0][:1].islower():
            out[-1] = _join(out[-1], paras.pop(0))
        out.extend(paras)
    return out


# ---------------------------------------------------------------------------------------------------------------------- the PDF
def build_pdf(paragraphs, out_path, title=None, font_pt=12):
    """A letter-size PDF with one text paragraph per paragraph, one inch of margin."""
    pymupdf = pio.pymupdf
    css = "body { font-family: serif; font-size: %spt; line-height: 1.45; } p { margin: 0 0 %spt 0; }" % (font_pt, round(font_pt * 0.9, 1))
    body = "".join("<p>%s</p>" % html.escape(p) for p in paragraphs) or "<p>(No text was found in the images.)</p>"
    story = pymupdf.Story(html=body, user_css=css)
    mediabox = pymupdf.paper_rect("letter")
    where = mediabox + (72, 72, -72, -72)
    writer = pymupdf.DocumentWriter(out_path)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    if title:
        doc = pymupdf.open(out_path)
        doc.set_metadata({"title": title})
        doc.saveIncr()
        doc.close()


def make_pdf(per_image, out_path):
    """per_image: the paragraphs of each picture, in order.  Writes the PDF (to a side file first, so a file that cannot be replaced is told plainly
    and a failure never leaves half a PDF) -> (out_path, number of paragraphs, number of words)."""
    paras = merge_across(per_image)
    folder = os.path.dirname(os.path.abspath(out_path))
    tmp = os.path.join(folder, "." + os.path.basename(out_path) + ".making.pdf")
    try:
        build_pdf(paras, tmp, title=os.path.splitext(os.path.basename(out_path))[0])
        os.replace(tmp, out_path)
    except PermissionError as e:
        raise ValueError(f"{os.path.basename(out_path)} cannot be replaced (is it open in another program?).") from e
    except Exception as e:                             # noqa: BLE001 - OSError, or whatever the PDF library raises: the person gets one plain sentence
        raise ValueError(f"The PDF could not be written ({getattr(e, 'strerror', None) or e}).") from e
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return out_path, len(paras), sum(len(p.split()) for p in paras)
