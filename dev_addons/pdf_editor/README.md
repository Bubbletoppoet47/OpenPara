# PDF editor (playground add-on)

One tab, **PDF editor**, for working with PDFs: read them aloud from any sentence, highlight them, check them for signs of AI-written text
(experimental), cut long pages into normal-sized pages and combine pages from several PDFs, and turn photos or scans of text into a PDF with real text.  It is the merge of two of Ian's programs: **Read Aloud** (a Tkinter reader)
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
* **Voices**: two kinds, in one list.  **Natural voices** (Kokoro, `pe_kokoro.py`): the 28 English voices - American women (11), American men (9),
  British women (4), British men (4) - each shown with the grade the model's own voice table gives it (**A best ... F**), grouped, best first in each
  group (`Heart · A`, `Bella · A-`, ...).  The default is Heart.  They are made on this computer (no internet after the download) and work on any
  system.  The **Windows (SAPI) voices** (`pywin32`) stay at the bottom of the list as a fallback.  `pe_speech.py` keeps speech behind a small backend
  interface (`voice_entries()`, `needs(voice)`, `engine()`), `MixedBackend` puts the two kinds together.
  The first time a natural voice is played, OpenPara **asks** and then downloads about 160 MB once (see Downloads); *Stop* ends that download and
  keeps nothing half done.  Pause goes on at the exact sample where it stopped; the next two sentences are made while one is spoken; the speed
  slider (-5 ... +10) is Kokoro's speed 0.7 ... 1.6.  pywin32 (about 10 MB) is downloaded the first time a Windows voice is played; on other systems
  the Windows voices are not offered.  The chosen voice and speed are remembered.
* **Highlights**: drag across text, pick a colour (yellow, green, pink, blue) or use the pop-up that appears next to the selection (it also has *Copy*);
  right-click a highlight to remove it.  They are real PDF highlight annotations, so Edge and Acrobat show them too.  Undo/Redo (Ctrl+Z / Ctrl+Y).
  A highlight marks the PDF as changed (`*` in the tab title); **Save** (Ctrl+S) writes them into the file, **Save a copy...** writes a new file.
  The pill switch *Save highlights into this PDF by themselves* (off by default, remembered per PDF) writes right after each highlight, removal,
  undo and redo.  It is separate from the AutoSave of the OpenPara window.  If a save fails (the file is locked, protected ...) the highlights stay,
  the status line says why, the next highlight tries again, and *Save a copy...* is offered; the automatic save never opens a dialog.
  Closing a PDF with unsaved highlights asks Save / Discard / Cancel.
* **AI check** (section 3; `pe_aipanel.py`, `pe_aicheck.py`, `pe_aidet.py`, `pe_aipacks.py`) - **experimental, a hint and not proof**: a banner in the section
  says so and it must stay there.  Three tests run side by side over every paragraph of the whole PDF, alone, in any group or all together (*Check this PDF* runs
  the ticked ones, *Run all tests* ticks all three).  The answer is a **count of tests**, never a percentage and never a verdict: each paragraph is shaded by
  "k of m tests lean AI" (purple, deeper the more tests lean AI; faint green = checked and no test leans AI; no shading = too short or not text), and the
  section says how many tests lean AI over the whole PDF (a test leans AI overall when more than half of the words it judged lean AI) with a line per test.
  Click a paragraph to see each test's own number; *Next / Previous flagged* walks through the paragraphs where at least one test leans AI; *Save the numbers...*
  writes every paragraph's raw numbers to a .csv; *Clear* removes it all.  It is view only: nothing is written into the PDF and nothing is saved with it.
  * *Trained classifier* (light, ~130 MB): `onnx-community/tmr-ai-text-detector-ONNX`, a RoBERTa-base model trained on the RAID benchmark (MIT).
  * *Binoculars* (light, ~1 GB): Hans et al. 2024, with Qwen2.5-0.5B and its Instruct version (`onnx-community/Qwen2.5-0.5B[-Instruct]`, 8-bit files) as
    observer and performer; a LOW score leans AI.  The authors' Falcon-7B pair does not fit an 8 GB laptop.
  * *Fast-DetectGPT (7B)* (heavy, ~5 GB, off by default): Bao et al. 2024, the analytic form with one model in both roles, here Mistral-7B-Instruct-v0.3 as 4-bit
    ONNX (`EmbeddedLLM/mistral-7b-instruct-v0.3-onnx-cpu-int4-rtn-block-32-acc-level-4`, a third party's conversion); a HIGH score leans AI.  It needs about 5.6 GB of
    free memory: when less is free the window **asks** before running it, and it takes many minutes on a long PDF; Stop gives up the calculation at once.
  A paragraph is one text block of the PDF (blocks that stop mid-sentence are joined, page numbers and running heads of four words or fewer are left out); a
  paragraph of 80 words or more is judged on its own (cut at sentence ends above 250 words), shorter ones in a row are joined until they reach 160 words, and
  what is still under 80 words is left out and said so.  A PDF with no such stretch is "too short to judge"; under 250 words a warning says the tests are even
  less reliable.  Models and packages are **downloaded the first time, after asking** (sizes shown, Stop keeps what came and the next try goes on from there).
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

Downloaded packages go to `<user folder>/packages/<name>` (`pdfeditor_voice`, `pdfeditor_ocr`, `pdfeditor_natural`, `pdfeditor_aicheck`, `pagebreak` for PyMuPDF) and are
appended to the search path, so a package the program bundles still wins.  onnxruntime is shared: the text reader and the natural voices each leave
it out of their download when the program (or the other pack) already has it.  The natural voices' model files (the 92 MB int8 model and the 28 MB
voices file) go to `<user folder>/pdf_editor_models/kokoro`; each is downloaded to a `.part` file, checked for size and SHA-256, and only then
renamed, so a broken or stopped download never looks like a good one.  Only one download runs at a time (`pe_deps.exclusive`).  The first download
is about 40 MB of packages + 92 MB + 28 MB = roughly 160 MB on disk (the whole voices file is kept).  The full 310 MB model is a possible later option.  The Playground installer already bundles PyMuPDF (`requirements-playground.txt`); an install
updated in place without a new bundle downloads it once (`pb_deps.py`).  The AI check needs `tokenizers` (a few MB, installed on its own with `--no-deps`) and onnxruntime
(only when the program, the text reader or the natural voices do not already have it); its **model files** go to `<user folder>/pdf_editor_models/ai_check/<pack>` and are
fetched straight from huggingface.co (`pe_aipacks.py`): a HEAD request gives the size and (for big files) the SHA-256 the Hub states, the file is written to `.part`
(kept when the connection ends or Stop is pressed, and gone on from with a Range request), checked, and renamed; a file that may sit under more than one name is
tried under each; a test whose model cannot be had is reported and the others still run.  PyMuPDF is AGPL-licensed, so check the licence before a public release.  kokoro-onnx is MIT, the Kokoro model Apache-2.0; its phonemiser
(espeak-ng, via the `espeakng-loader` wheel) is GPL-3.0 and is downloaded, not bundled.

## What has been tried and what has not

Tested on Linux, offscreen: the sentence model, highlights, saving (including a repeated save to the same file), undo/redo, the marker/play/pause/stop
behaviour with a fake voice, the inner tabs, the host hook, the download steps with a fake downloader and a fake `pip`, the Images dialog with a fake
text reader, and once for real: downloading RapidOCR/onnxruntime into a scratch folder and reading a picture.  The natural voices: the voice table,
clause cutting, the engine (with a fake model and a fake sound card driven block by block: exact pause/resume, sentences made ahead, stopping, a failing
model), the downloads (fake fetch: sizes, hashes, stop, offline, one at a time) and the picker are tested; once for real, the 92 MB model was
downloaded and run on a slow 2-core Linux machine (speech made at roughly 0.7x real time; first sound after about 0.9 s; on that machine there were
short pauses while the first two clauses of a read were still being made) - with a fake sound card, so **nothing was heard**.
`OPARA_REAL_KOKORO=<folder with site/ and models/> python test_pdf_editor_natural.py` repeats the real-model check.
**Not tried on Windows**: the sound output (sounddevice/PortAudio), loading espeak-ng and the model there, how fast the voices are made on a real
computer (speech made slower than it is spoken shows as pauses), the SAPI voices through the downloaded pywin32 (DLL and search-path handling), the OCR
packages on Windows, saving into a PDF that Edge or Acrobat has open.

**The AI check**: tested on Linux, offscreen, with **stand-in models** (tiny next-word tables built as real ONNX files, run by the real onnxruntime and tokenizers) and
a local server that imitates the Hub: the downloads (hashes, a damaged file, a cut connection, ranges, Stop and going on, a name that is not there, a small disk,
another download running); the Binoculars and Fast-DetectGPT arithmetic against a plain float64 re-working (and the Fast-DetectGPT mean and variance against
sampling); the input feed for different ONNX layouts; the paragraphs from PDFs of known structure; the runner (cache, Stop, failures); the counting; and the
window (panel, questions asked first, shading drawn and checked pixel by pixel, clicks, next/previous, .csv, Clear, closing the tab while it runs).  26 deliberate
breakages of the code were each caught by these tests.
**Not tried, and the reason to treat every result as a hint:** no real model was ever run (Hugging Face could not be reached when this was written, so the file names
and sizes of the model repositories were taken from their pages and are tried under alternatives), so **how well any test tells human from AI writing is not known**,
**the lines each test draws are starting guesses** (`pe_aidet.THRESHOLDS`: classifier 0.5, Binoculars 0.90, Fast-DetectGPT 1.0) that were found in the papers for other,
full-size models and were not checked on these 8-bit and 4-bit files, how long the real models take (the 7B model on a laptop CPU may need minutes per page),
which output class of the classifier is "AI" (read from the model's own labels; guessed and said so when they are unnamed), the tokenizer details of the real files,
and Windows.  To set the lines properly: run the check on PDFs whose author is known, *Save the numbers...*, and look at where the two groups separate.
Made for English text.  Open Pangram's detector is not used (non-commercial licence).

A MuPDF quirk to know about (`pe_pdfio.save_in_place`): a highlight added *after* an incremental save of the same open document is left out by the next
incremental save.  The document is therefore opened again after each in-place save.

## Files

`pe_tab.py` the tab and its inner tabs · `pe_reader.py` one PDF · `pe_view.py` the page view · `pe_text.py` words, sentences, positions ·
`pe_pdfio.py` highlights, undo, saving · `pe_speech.py` voices (Speaker, Hub, mixed backend) · `pe_kokoro.py` the natural voices · `pe_store.py` what is remembered · `pe_deps.py` / `pb_deps.py` downloads ·
`pe_aidet.py` paragraphs and the three AI tests · `pe_aicheck.py` the runner and the counting · `pe_aipacks.py` the AI models' downloads · `pe_aipanel.py` the AI check section of the reader ·
`pe_ocr.py`, `pe_images.py` Images → PDF · `page_break_tab.py`, `pb_core.py` page projects.
Tests: `test_pdf_editor_core.py`, `test_pdf_editor_reader.py`, `test_pdf_editor_tab.py`, `test_pdf_editor_images.py`, `test_pdf_editor_natural.py`, `test_pdf_editor_aicheck.py`,
`test_page_break.py`.
