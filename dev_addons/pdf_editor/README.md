# PDF editor (playground add-on)

One tab, **PDF editor**, for working with PDFs: read them aloud from any sentence, highlight them, cut long pages into normal-sized pages and combine pages
from several PDFs, and turn photos or scans of text into a PDF with real text.  It is the merge of two of Ian's programs: **Read Aloud** (a Tkinter reader)
and the earlier **Page Break** add-on.  The add-on's folder is `pdf_editor`; an old `page_break` folder left behind by an update is ignored
(`addons.RETIRED`).

## How it is put together

The tab has a tab bar of its own.  Each inner tab is a **PDF** (the reader) or a **page project** (`.oppb`, the unchanged Page Break tab); the inner tab
decides what the left panel shows.  Any PDF opened from elsewhere in OpenPara (File > Open, drag and drop) lands as an inner tab of the same
editor tab (the host hook `AppShell.adopted_by_tab` asks each tab whether it takes the file).  A file that is already open comes to the front.
What is open, where you were in each PDF, the voice and its speed are remembered in `<user folder>/pdf_editor.json`; an empty new editor tab offers
"Reopen ..." for what was open last time.  The look is OpenPara's (`ui_kit`: numbered sections, notes, status line, empty state); pages stay white.

### Reader (a PDF tab)

* **Where reading starts**: click a sentence to put the marker there; **Play** starts at the marker (with no marker, at the first sentence at the top
  of the window).  Double-click a sentence, or right-click > *Read from here*, starts at once.  **Pause** goes on in the middle of the same sentence;
  **Stop** leaves the marker on the sentence that was being read, so Play starts that sentence again.  Scrolling never moves the marker.
  **⏮ / ⏭** and the left/right arrow keys step by sentence (reading restarts there when it is reading).  One voice at a time across all open PDFs.
  The marker is remembered per PDF.
* **Voices**: the Windows (SAPI) voices, through `pywin32`.  `pe_speech.py` keeps speech behind a small backend interface (`list_voices()`,
  `engine()`), so a better engine can be added without touching the reader.  pywin32 (about 10 MB) is **downloaded the first time Play is pressed**
  (`pe_deps.install_voice`); on other systems the reader works but says it needs Windows to speak.
* **Highlights**: drag across text, pick a colour (yellow, green, pink, blue) or use the pop-up that appears next to the selection (it also has *Copy*);
  right-click a highlight to remove it.  They are real PDF highlight annotations, so Edge and Acrobat show them too.  Undo/Redo (Ctrl+Z / Ctrl+Y).
  A highlight marks the PDF as changed (`*` in the tab title); **Save** (Ctrl+S) writes them into the file, **Save a copy...** writes a new file.
  The pill switch *Save highlights into this PDF by themselves* (off by default, remembered per PDF) writes right after each highlight, removal,
  undo and redo.  It is separate from the AutoSave of the OpenPara window.  If a save fails (the file is locked, protected ...) the highlights stay,
  the status line says why, the next highlight tries again, and *Save a copy...* is offered; the automatic save never opens a dialog.
  Closing a PDF with unsaved highlights asks Save / Discard / Cancel.
* A PDF without text (a scan) shows a banner that offers **Images → PDF**.
* **Cut and combine its pages...** sends the PDF to the page project you used last (or a new one).

### Page projects (the Page Break tab, `page_break_tab.py`, `pb_core.py`)

Cut long PDF pages (a saved web page, a long printout) into normal-sized pages and combine pages of several PDFs into one file.  Project files `.oppb`
are JSON (the list of PDFs, their breaks, what is excluded and the page order; the PDFs stay where they are).  Click a page to drop a break, click the
line again to remove it; click a segment's label to leave it out; *Auto-break every N in*; Undo/Redo; arrows / Remove reorder or leave out pages;
*Export split PDF* writes one combined PDF.

### Images → PDF (`pe_images.py`, `pe_ocr.py`)

Menu **+ Open > Images → PDF...** (also on the empty page and in the no-text banner).  Add the pictures (kept in natural order: photo2 before photo10),
choose where the PDF goes, press *Make the PDF*.  OCR is RapidOCR on onnxruntime (ported from Read Aloud's `ocr_to_pdf.py`): lines are merged into
paragraphs, a paragraph cut by the edge of one photo continues on the next, and a letter-size PDF with real text is written.  The result opens as a tab.
The text reader (roughly 100 MB, models included) is **downloaded the first time, after asking** (`pe_deps.install_ocr`: `pip download` with its
requirements, leaving out what the program already has - numpy, pillow, shapely).  Reading runs in a thread; the PDF is written on the window's thread.
iPhone `.heic` photos open only if `pillow_heif` happens to be installed.

## Downloads and the packages folder

Downloaded packages go to `<user folder>/packages/<name>` (`pdfeditor_voice`, `pdfeditor_ocr`, `pagebreak` for PyMuPDF) and are appended to the search
path, so a package the program bundles still wins.  The Playground installer already bundles PyMuPDF (`requirements-playground.txt`); an install
updated in place without a new bundle downloads it once (`pb_deps.py`).  PyMuPDF is AGPL-licensed, so check the licence before a public release.

## What has been tried and what has not

Tested on Linux, offscreen: the sentence model, highlights, saving (including a repeated save to the same file), undo/redo, the marker/play/pause/stop
behaviour with a fake voice, the inner tabs, the host hook, the download steps with a fake downloader and a fake `pip`, the Images dialog with a fake
text reader, and once for real: downloading RapidOCR/onnxruntime into a scratch folder and reading a picture.  **Not tried on Windows**: the SAPI voices
through the downloaded pywin32 (DLL and search-path handling), the OCR packages on Windows, saving into a PDF that Edge or Acrobat has open.

A MuPDF quirk to know about (`pe_pdfio.save_in_place`): a highlight added *after* an incremental save of the same open document is left out by the next
incremental save.  The document is therefore opened again after each in-place save.

## Files

`pe_tab.py` the tab and its inner tabs · `pe_reader.py` one PDF · `pe_view.py` the page view · `pe_text.py` words, sentences, positions ·
`pe_pdfio.py` highlights, undo, saving · `pe_speech.py` voices · `pe_store.py` what is remembered · `pe_deps.py` / `pb_deps.py` downloads ·
`pe_ocr.py`, `pe_images.py` Images → PDF · `page_break_tab.py`, `pb_core.py` page projects.
Tests: `test_pdf_editor_core.py`, `test_pdf_editor_reader.py`, `test_pdf_editor_tab.py`, `test_pdf_editor_images.py`, `test_page_break.py`.
