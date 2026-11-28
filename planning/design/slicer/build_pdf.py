"""
build_pdf.py - makes OpenPara_Slicer_Integration_Plan.pdf from PLAN.md and the pictures in figures/.

    python build_pdf.py            (run from anywhere; it works on the folder this file is in)

PLAN.md is the document.  Change it, add a line to the revision log at its end, run this, and commit both.
The pictures in figures/ are made from the .mmd files next to them with the Mermaid command-line tool:
    mmdc -c figures/mmd_config.json -i figures/<name>.mmd -o figures/<name>.png -s 2 -b white -w 1500

What it needs: markdown-it-py and Playwright with Chromium (pip install markdown-it-py playwright).
Fonts: the body is Lora (assets/fonts) and the tables and headings are Sofia Sans (docs/assets/fonts), both in this repository, so the
result looks the same on every machine.

The page numbers in the contents list are read back from the bookmarks of a first run of the PDF and filled in on a second run.
"""
import html
import os
import re
import sys

from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "PLAN.md")
OUT = os.path.join(HERE, "OpenPara_Slicer_Integration_Plan.pdf")
TMP = os.path.join(HERE, "_plan_build.html")

CSS = r"""
@font-face { font-family: "Lora"; src: url("../../../assets/fonts/Lora-Variable.ttf"); font-weight: 400 700; font-style: normal; }
@font-face { font-family: "Lora"; src: url("../../../assets/fonts/Lora-Italic-Variable.ttf"); font-weight: 400 700; font-style: italic; }
@font-face { font-family: "Sofia"; src: url("../../../docs/assets/fonts/sofia-sans.woff2"); font-weight: 1 1000; font-style: normal; }
@page { size: Letter; margin: 0.8in 0.75in 0.85in 0.75in; }
:root { --ink: #1f2a44; --muted: #5b6783; --line: #c9d1e0; --band: #eef2f9; --accent: #2f6fed; --warn: #fff4dc; }
* { box-sizing: border-box; }
html { color: var(--ink); background: #fff; }
body { font-family: "Lora", Georgia, serif; font-size: 10pt; line-height: 1.5; margin: 0; hyphens: manual; }
h1, h2, h3, th, .toc, figcaption, .cover-kicker { font-family: "Sofia", "DejaVu Sans", Arial, sans-serif; }
h1 { font-size: 22pt; line-height: 1.15; font-weight: 800; margin: 0 0 10pt; padding-bottom: 6pt; border-bottom: 2.5px solid var(--accent); break-after: avoid; }
h1.chapter { break-before: page; }
h1.appendix-first { break-before: page; }
h1.appendix { margin-top: 26pt; font-size: 17pt; }
h2 { font-size: 13.5pt; line-height: 1.25; font-weight: 750; margin: 18pt 0 5pt; break-after: avoid; }
h3 { font-size: 11pt; font-weight: 700; margin: 12pt 0 3pt; break-after: avoid; }
p { margin: 0 0 7pt; orphans: 3; widows: 3; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin: 0 0 3pt; }
hr { display: none; }
a { color: var(--accent); text-decoration: none; }
strong { font-weight: 700; }
code { font-family: "DejaVu Sans Mono", Menlo, Consolas, monospace; font-size: 0.86em; background: var(--band); padding: 0.5pt 3pt; border-radius: 2px; overflow-wrap: break-word; }
pre { font-family: "DejaVu Sans Mono", Menlo, Consolas, monospace; font-size: 7.9pt; line-height: 1.4; background: var(--band); border-left: 3px solid var(--line); padding: 7pt 9pt; margin: 6pt 0 10pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
table { border-collapse: collapse; width: 100%; margin: 7pt 0 12pt; font-family: "Sofia", "DejaVu Sans", Arial, sans-serif; font-size: 8.7pt; line-height: 1.35; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { text-align: left; background: var(--band); border-bottom: 1.4px solid var(--muted); font-weight: 700; padding: 4pt 6pt; vertical-align: bottom; }
td { border-bottom: 0.6px solid var(--line); padding: 3.6pt 6pt; vertical-align: top; overflow-wrap: break-word; }
td.nw, th.nw { white-space: nowrap; }
td code, th code { font-size: 0.9em; }
figure { margin: 8pt 0 12pt; padding: 0; break-inside: avoid; text-align: center; }
figure img { max-width: 100%; max-height: 4.7in; border: 0.6px solid var(--line); }
figcaption { font-size: 8.4pt; color: var(--muted); margin-top: 3pt; }
em { font-style: italic; }
/* cover */
.cover { padding-top: 0.5in; }
.cover h1 { font-size: 31pt; line-height: 1.1; border-bottom: 3px solid var(--accent); padding-bottom: 12pt; margin-bottom: 14pt; }
.cover table { font-size: 9.4pt; }
.cover td:first-child { width: 1.1in; font-weight: 700; color: var(--muted); }
/* contents */
.toc-page { break-before: page; break-after: page; }
.toc-page h1 { font-size: 20pt; }
.toc { font-size: 8.9pt; line-height: 1.25; }
.toc .row { display: flex; align-items: baseline; gap: 6pt; margin: 0; }
.toc .row a { color: var(--ink); }
.toc .row .dots { flex: 1; border-bottom: 1px dotted var(--line); transform: translateY(-2.5pt); }
.toc .row .pg { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 14pt; text-align: right; }
.toc .l1 { font-weight: 750; margin-top: 4.5pt; font-size: 9.4pt; }
.toc .l2 { padding-left: 14pt; color: var(--ink); }
"""


def slug(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:70] or "x"


def plain(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def render(md_text):
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    return md.render(md_text)


def nowrap_cells(h):
    """Short cells (an ID, a number, a yes/no) are never broken across lines."""
    def cell(m):
        tag, inner = m.group(1), m.group(2)
        if len(plain(inner)) <= 13 and "<br" not in inner:
            return f'<{tag} class="nw">{inner}</{tag}>'
        return m.group(0)
    return re.sub(r"<(td|th)>(.*?)</\1>", cell, h, flags=re.S)


def figures(h):
    """<p><img alt=...></p> -> <figure> with a caption from the alt text."""
    def fig(m):
        return f'<figure>{m.group(1)}<figcaption>{html.escape(html.unescape(m.group(2)))}</figcaption></figure>'
    return re.sub(r'<p>(<img src="[^"]+" alt="([^"]*)"[^>]*>)</p>', fig, h)


def build_html(pages):
    text = open(SRC, encoding="utf-8").read()
    head, sep, body = text.partition("\n---\n")
    cover_html = nowrap_cells(figures(render(head)))
    cover_html = re.sub(r"<h1>", "<h1>", cover_html, count=1)
    body_html = nowrap_cells(figures(render(body)))
    heads = []

    def add_id(m):
        lvl, inner = int(m.group(1)), m.group(2)
        t = plain(inner)
        i = slug(t)
        n = sum(1 for x in heads if x[2] == i)
        if n:
            i = f"{i}-{n + 1}"
        heads.append((lvl, t, i))
        cls = ""
        if lvl == 1:
            if re.match(r"\d+\.", t):
                cls = ' class="chapter"'
            elif t.startswith("Appendix A"):
                cls = ' class="appendix appendix-first"'
            else:
                cls = ' class="appendix"'
        return f'<h{lvl}{cls} id="{i}">{inner}</h{lvl}>'

    body_html = re.sub(r"<h([1-3])>(.*?)</h\1>", add_id, body_html, flags=re.S)
    rows = []
    for lvl, t, i in heads:
        if lvl > 2:
            continue
        pg = pages.get(t, "")
        rows.append(f'<div class="row l{lvl}"><a href="#{i}">{html.escape(t)}</a><span class="dots"></span><span class="pg">{pg}</span></div>')
    toc = f'<section class="toc-page"><h1>Contents</h1><div class="toc">{"".join(rows)}</div></section>'
    title = plain(re.search(r"<h1>(.*?)</h1>", cover_html, re.S).group(1))
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>{CSS}</style></head>'
           f'<body><section class="cover">{cover_html}</section>{toc}<main>{body_html}</main></body></html>')
    return doc, heads, text


def draft_of(text):
    m = re.search(r"\*\*(Draft \d+)\*\*", text)
    return m.group(1) if m else ""


def make_pdf(doc, footer_left):
    with open(TMP, "w", encoding="utf-8") as f:
        f.write(doc)
    footer = ('<div style="font-size:7.6px;font-family:Arial,Helvetica,sans-serif;color:#5b6783;width:100%;padding:0 0.75in;'
              'display:flex;justify-content:space-between;"><span>' + html.escape(footer_left) +
              '</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto("file://" + TMP)
        pg.wait_for_load_state("networkidle")
        pg.evaluate("document.fonts.ready")
        kw = dict(path=OUT, prefer_css_page_size=True, print_background=True, display_header_footer=True,
                  header_template="<span></span>", footer_template=footer)
        try:
            pg.pdf(outline=True, tagged=True, **kw)
        except TypeError:
            pg.pdf(**kw)
        b.close()


def pages_from_outline():
    """{heading text: page number} read from the bookmarks of the PDF."""
    from pypdf import PdfReader
    r = PdfReader(OUT)
    out = {}

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                try:
                    out.setdefault(plain(it.title), r.get_destination_page_number(it) + 1)
                except Exception:
                    pass
    walk(r.outline)
    return out, len(r.pages)


def main():
    doc, heads, text = build_html({})
    footer_left = "Slicer in OpenPara: integration plan" + (" - " + draft_of(text) if draft_of(text) else "")
    make_pdf(doc, footer_left)
    pages, n = pages_from_outline()
    doc2, _, _ = build_html(pages)
    make_pdf(doc2, footer_left)
    pages2, n2 = pages_from_outline()
    if pages2 != pages or n2 != n:                      # the numbers in the list changed the layout: one more run settles it
        doc3, _, _ = build_html(pages2)
        make_pdf(doc3, footer_left)
        pages2, n2 = pages_from_outline()
    missing = [t for lvl, t, i in heads if lvl <= 2 and t not in pages2]
    os.remove(TMP)
    print(f"{OUT}: {n2} pages, {len(heads)} headings, {len(missing)} without a page number")
    for t in missing:
        print("  no bookmark for:", t)


if __name__ == "__main__":
    sys.exit(main())
