# Page Break (playground add-on)

Cut long PDF pages (a saved web page, a long printout) into normal-sized pages, and combine pages from several PDFs into one file.
Tab: **Page Break**; project files: `.oppb` (JSON: the list of PDFs, their breaks, what is excluded and the page order; the PDFs stay where they are).
Needs PyMuPDF (`pymupdf` in `requirements-playground.txt`; it is AGPL-licensed, so check the licence before a public release).
An install that was updated in place does not have it (updates replace program files, not the bundled packages): the tab then downloads PyMuPDF
once into `<user folder>/packages/pagebreak` (`pb_deps.py`, needs internet), shows the progress, and retries on request if the download fails.

* **Import PDF...** adds every page of a PDF to the end of the list (import more files any time).
* **Click a page** to drop a break line; click the line again to remove it. The shaded bands are the output pages, each labelled `Page N · height`.
* **Click a segment's label** to leave that segment out of the export (click again to include it).
* **Auto-break every N in** puts a break every N inches on every page (replacing the ones there). **Undo / Redo** (Ctrl+Z / Ctrl+Y), **Clear all breaks**.
* **Arrows / Remove** on a page change the order or leave the page out. **Zoom** (+ / - / Fit width) for more precise breaks.
* **Export split PDF** writes one combined PDF of every included segment, in list order; the save box opens in the folder of the first PDF.

The maths and file work are in `pb_core.py` (no window); the tab is `page_break_tab.py`. Tests: `test_page_break.py`.
Origin: the standalone `page_break.py` (Tkinter) by Ian; this is a PyQt6 port of it.
