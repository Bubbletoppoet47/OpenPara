"""The PDF Editor and the Annotator as blocks of the Workbench (no wires in or out), in the real program window.

PDF Editor: the block's document is a folder; its tab opens on the PDFs and page projects in it; a PDF opened from anywhere else is copied into the folder (the original is never
changed, the same file twice is one copy, a file past the size limit opens where it is and is said), a new page project has its file in the folder from the start and keeps its PDFs as
relative paths, so the block comes back whole after the project file is closed and opened again; opening is not a change; the editor on its own is not changed by any of this.
Annotator: the block keeps a LINK to the project folder (never a copy of the dataset); a new block works in a temporary project until it is saved to a folder; the block follows the
window; a change in the dataset is a change of the cell; a folder that moved is asked for; Save the block on its own copies the folder.
python test_wb_pdf_annotator.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')      # (the annotator add-on is not installed: that would download its 1.3 GB of packages; its tab is put in below, from its own manifest)
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("workbench", "sheets", "controls", "circuits", "pdf_editor"):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
ANN = os.path.join(HERE, "addons_src", "annotator", "app")
sys.path.insert(0, ANN)
sys.path.insert(0, os.path.dirname(ANN))

T = tempfile.mkdtemp(prefix="opara_wbpa_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
SAVE = {"path": ""}
PICK = {"dir": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: PICK["dir"])
import numpy as np
import cv2
import qtk
import share_zip as sz
sz.CONFIG_PATH = os.path.join(T, "annotator_cfg.json")
json.dump({"models_prompt_done": True, "name": "Tester", "id": "tester1"}, open(sz.CONFIG_PATH, "w"))
INFO = []
for _n in ("info", "warn", "error"):
    setattr(qtk, _n, lambda parent, title, text, _n=_n: INFO.append((_n, title, text)))
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import addons
import ext
addons.startup()
addons.register_extensions(ext)
_ANN_SPEC = dict(json.load(open(os.path.join(HERE, "addons_src", "annotator", "addon.json")))["tabs"][0], aid="annotator")
_tab_kinds = addons.tab_kinds
addons.tab_kinds = lambda: {**_tab_kinds(), "annotator": _ANN_SPEC}          # the annotator's tab kind, as its manifest says, without installing the add-on

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import gpd_app
import pymupdf
import recent
import wb_nodes
import wb_project as wp
import wb_tab
import wb_tools  # noqa: F401 (registers the adapters)
import pe_reader
import pe_store
import pe_tab
import page_break_tab as pbt
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
P = W.project


def pump(n=10, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def stamp(nid):
    return P.cell(nid, "document")["stamp"]


def sha(path):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()


def make_pdf(path, pages, tag):
    d = pymupdf.open()
    for i in range(pages):
        pg = d.new_page()
        for k in range(4):
            pg.insert_text((72, 80 + 30 * k), f"{tag} page {i + 1} sentence {k + 1} is here.", fontsize=12)
    d.save(path)
    d.close()


def not_in_session(f):
    tabs, _cur = shell.session_tabs()
    return all(t["path"] != os.path.abspath(f) for t in tabs)


def not_listed(f):
    return not_in_session(f) and not any(os.path.abspath(i2["path"]) == os.path.abspath(f) for i2 in recent.items())


ok(isinstance(W, wb_tab.WorkbenchTab), "the program opened a Workbench at the start")
for kind in ("pdf", "annotator"):
    ok(wb_nodes.adapter_for(kind) is not None and kind not in wb_nodes.check_kinds(), f"{kind} has an adapter and is not listed as 'not wired in'")
    ok(wb_nodes.availability(W, kind)[0], f"the toolbox offers it ({kind}: {wb_nodes.availability(W, kind)[1] or 'ok'})")
    ok(wp.KINDS[kind].standalone == "folder" and [c.key for c in wp.KINDS[kind].cells] == ["document"], f"{kind}: one cell, saved on its own as a folder")
    ok(not [k for k in P.links if kind in (P.node(k.a).kind, P.node(k.b).kind)], f"{kind}: no wires")

# ============================================================================================================================ the PDF Editor block
print("--- PDF Editor")
EXT = os.path.join(T, "elsewhere")
os.makedirs(EXT)
one, two = os.path.join(EXT, "one.pdf"), os.path.join(EXT, "two.pdf")
make_pdf(one, 3, "First")
make_pdf(two, 2, "Second")
h_one, h_two = sha(one), sha(two)

nP = W.add_block("pdf", 60, 60, title="My PDFs")
ok(not nP.data.get("files"), "a new PDF block holds nothing yet")
ok(P.status(nP.id, "document") == wp.INCOMPLETE, f"and says incomplete ({P.status(nP.id, 'document')})")
s0 = stamp(nP.id)
w = W.open_cell(nP.id, "document")
ok(w is not None and isinstance(w, pe_tab.PdfEditorTab) and shell.tabs.indexOf(w) >= 0, "double-click opens the PDF editor in its usual tab")
ok(W.editor_of(nP.id) is w and w in shell.dependents(W), "the workbench knows it and closes it with the workbench")
f = W.node_state[nP.id]["file"]
ok(f.startswith(W.workspace) and os.path.isdir(f) and os.path.basename(f) == "My PDFs", f"its folder is in the project's workspace, named after the block ({os.path.basename(f)})")
ok(w.keep_dir == f and not w.last_files() and not w.reopen_btn.isVisible(), "the tab keeps what is open in that folder (no 'reopen what was open last time')")
ok(not_listed(f), "it is not in the recent list or the session")
ok(W.sync_editors() == [] and stamp(nP.id) == s0, "opening it is not a change")
ok(not w.is_dirty() and P.status(nP.id, "document") == wp.INCOMPLETE, "the tab is not 'unsaved' and the block is still incomplete")

# a PDF from elsewhere is copied in; the original is not touched
r1 = w.open_path(one)
ok(isinstance(r1, pe_reader.ReaderTab) and os.path.dirname(r1.path) == os.path.abspath(f) and os.path.basename(r1.path) == "one.pdf", f"a PDF opened from elsewhere is a copy in the block's folder ({r1.path if r1 else None})")
ok(sha(one) == h_one and sha(r1.path) == h_one, "the original is unchanged and the copy is the same file")
ok(w.open_path(one) is r1 and w.open_path(r1.path) is r1 and len(w.readers()) == 1 and sorted(os.listdir(f)) == ["one.pdf"], "the same file again (by either name) is the same tab, not a second copy")
ok(W.sync_editors() == [nP.id] and stamp(nP.id) == s0 + 1, "the project reads the new file back (the cell changed once)")
ok(set(nP.data["files"]) == {"one.pdf"} and P.status(nP.id, "document") == wp.OK, f"the block holds it and is ready ({sorted(nP.data['files'])}, {P.status(nP.id, 'document')})")
ok(W.sync_editors() == [], "the same state again is not a change")

# a page project: its file is in the folder from the start; its PDFs are relative paths
t = w.new_project()
ok(isinstance(t, pbt.PageBreakTab) and t.path == os.path.join(os.path.abspath(f), "Page project.oppb") and t.portable, "a new page project has its file in the block's folder from the start")
w.open_in_pages(r1.path)
ok(t.is_dirty() and len(t.project.items) == 3, f"Cut and combine from the reader put its 3 pages in it ({len(t.project.items)})")
t.import_path(two)
ok(len(t.project.items) == 5 and os.path.isfile(os.path.join(f, "two.pdf")) and sha(os.path.join(f, "two.pdf")) == h_two and sha(two) == h_two, "a PDF added to a page project from elsewhere is copied into the block too")
ok(W.sync_editors() == [nP.id], "the project reads that back (the tab is saved into the folder first)")
ok(set(nP.data["files"]) == {"one.pdf", "two.pdf", "Page project.oppb"}, f"the block holds both PDFs and the page project ({sorted(nP.data['files'])})")
saved = json.loads(nP.data["files"]["Page project.oppb"]["text"])
ok([p["source"] for p in saved["pages"]] == ["one.pdf"] * 3 + ["two.pdf"] * 2, f"the page project names its PDFs relative to itself ({sorted({p['source'] for p in saved['pages']})})")

# the limit: a file past it opens where it is, and says so
three = os.path.join(EXT, "three.pdf")
make_pdf(three, 1, "Third")
w.KEEP_LIMIT = os.path.getsize(one) + os.path.getsize(two) + 100
MSGS.clear()
r3 = w.open_path(three)
ok(isinstance(r3, pe_reader.ReaderTab) and os.path.abspath(r3.path) == os.path.abspath(three) and not os.path.exists(os.path.join(f, "three.pdf")), "a PDF that would take the block past its limit opens where it is, not copied")
ok(any("not copied into this block" in m for m in MSGS), "and the person is told")
w.close_inner(w.tabs.indexOf(r3))
w.KEEP_LIMIT = pe_tab.PdfEditorTab.KEEP_LIMIT
ok(W.sync_editors() == [] and set(nP.data["files"]) == {"one.pdf", "two.pdf", "Page project.oppb"}, "and it is not in the project")

# the editor on its own is not changed by any of this
sa = pe_store.Store()
ok(not any(W.workspace in str(p) for p in sa.get("open", [])), "what the editor remembers as 'open last time' has none of the block's files")
alone = shell.new_addon_tab("pdfeditor", three)
ok(alone is not None and alone.keep_dir is None and os.path.abspath(alone.readers()[0].path) == os.path.abspath(three), "the PDF editor on its own still opens a PDF where it is")
ok(os.listdir(EXT).count("three (2).pdf") == 0 and sorted(os.listdir(EXT)) == ["one.pdf", "three.pdf", "two.pdf"], "and copies nothing")
shell.close_tab(shell.tabs.indexOf(alone))

# the project file, closed and opened again
f1 = os.path.join(T, "pdfs.opara")
SAVE["path"] = f1
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
ok({"one.pdf", "two.pdf", "Page project.oppb"} == set(next(n for n in raw["nodes"] if n["kind"] == "pdf")["data"]["files"]), "the .opara file holds the folder")
shell.close_tab(shell.tabs.indexOf(W.editor_of(nP.id)))
ok(W.editor_of(nP.id) is None, "(the tab is closed)")
old_ws = W.workspace
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
nP = [x for x in P.nodes.values() if x.kind == "pdf"][0]
ok(P.status(nP.id, "document") == wp.OK and W.node_state == {}, "after opening the file: ok, nothing computed, no editor state left over")
s1 = stamp(nP.id)
w = W.open_cell(nP.id, "document")
f = W.node_state[nP.id]["file"]
ok(w is not None and len(w.readers()) == 2 and len(w.projects()) == 1, f"the tab opens on what was in the folder ({len(w.readers())} PDFs, {len(w.projects())} page project)")
ok(sha(os.path.join(f, "one.pdf")) == h_one and sha(os.path.join(f, "two.pdf")) == h_two, "the PDFs are byte for byte what they were")
pj = w.projects()[0]
ok(len(pj.project.items) == 5 and not pj.is_dirty(), f"the page project found its PDFs again, in the new workspace ({len(pj.project.items)} pages)")
ok(w.keep_dir == f and W.sync_editors() == [] and stamp(nP.id) == s1, "opening again is not a change")

# a second page project gets its own name; export; delete
t2 = w.new_project()
ok(os.path.basename(t2.path) == "Page project (2).oppb", f"a second page project does not overwrite the first ({os.path.basename(t2.path)})")
w.close_inner(w.tabs.indexOf(t2))
out = os.path.join(T, "out")
os.makedirs(out)
ad = wb_nodes.adapter_for("pdf")
p1, p2 = ad.export(W, nP, out), ad.export(W, nP, out)
ok(p1 != p2 and os.path.isdir(p1) and os.path.isdir(p2) and sorted(os.listdir(p1)) == ["Page project.oppb", "one.pdf", "two.pdf"], f"exporting twice makes two folders with the files ({os.path.basename(p1)}, {os.path.basename(p2)})")
ne = W.add_block("pdf", 60, 200, title="Empty PDFs")
try:
    ad.export(W, ne, out)
    refused = False
except ValueError as ex:
    refused = "nothing in it" in str(ex)
ok(refused, "an empty block cannot be exported (it says why)")
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nP.id]
sel[0].setSelected(True)
ok(W.delete_selected() == 1 and nP.id not in P.nodes and shell.tabs.indexOf(w) < 0 and nP.id not in W.node_state, "Delete removes the block, closes its tab and forgets its state")
ad2 = wb_nodes.adapter_for("pdf")
real = addons.tab_kinds
addons.tab_kinds = lambda: {k: v for k, v in real().items() if k != "pdfeditor"}
av = ad2.available(W)
ok(av[0] is False and "PDF editor" in av[1], f"a switched-off add-on is said ({av[1]})")
addons.tab_kinds = real

# ============================================================================================================================ the Annotator block
print("--- Annotator")
nA = W.add_block("annotator", 260, 60, title="My annotator")
ok(not nA.data.get("link") and P.status(nA.id, "document") == wp.INCOMPLETE, "a new Annotator block holds nothing and says incomplete")
sA = stamp(nA.id)
wa = W.open_cell(nA.id, "document")
ok(wa is not None and shell.tabs.indexOf(wa) >= 0 and W.editor_of(nA.id) is wa and wa in shell.dependents(W), "double-click opens the annotator in its usual tab")
ok(wa.temp_root is not None and wa.path is None, "on a new project in a temporary folder, as the annotator does on its own")
ok(not_listed(wa.temp_root), "which is not in the recent list or the session")
ok(W.sync_editors() == [] and stamp(nA.id) == sA and not nA.data.get("link"), "opening it is not a change, and there is no folder to link to yet")
ok(P.status(nA.id, "document") == wp.INCOMPLETE, "still incomplete")
ok(W.open_cell(nA.id, "document") is wa, "a second double-click shows the same tab")

# the person saves the project to a folder of its own (the annotator asks where): the block takes that folder
vp = os.path.join(T, "clip.mp4")
vw = cv2.VideoWriter(vp, cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
for i in range(12):
    fr = np.full((120, 160, 3), 30 + i * 5, np.uint8)
    cv2.rectangle(fr, (30 + i * 3, 30), (90 + i * 3, 90), (0, 200, 0), -1)
    vw.write(fr)
vw.release()
proj = os.path.join(T, "Birds.annotator")
SAVE["path"] = proj
ok(wa.save() is True and wa.path and os.path.abspath(wa.path) == os.path.abspath(proj) and wa.temp_root is None, "Save in the annotator gives the project its own folder")
ch = W.sync_editors()
ok(ch == [nA.id] and stamp(nA.id) == sA + 1, f"the block takes the folder (the cell changed once: {ch})")
ok(nA.data.get("link", {}).get("abs") == os.path.abspath(proj) and "files" not in nA.data, f"as a link, not a copy ({nA.data.get('link')})")
ok(P.status(nA.id, "document") == wp.OK, f"and is ready: ok ({P.status(nA.id, 'document')})")
ok(W.sync_editors() == [], "the same state again is not a change")
ad = wb_nodes.adapter_for("annotator")
ok(ad.dataset_folder(W, nA) == os.path.abspath(proj), "dataset_folder gives the project folder (where a Trainer block will get it later)")

# a change in the dataset is a change of the cell
res = wa.project.import_video(vp, 3)
wa.project.save_manifest()
ok(res and bool(wa.project.manifest["images"]), f"(the annotator imported {len(wa.project.manifest['images'])} frames)")
ch = W.sync_editors()
ok(ch == [nA.id] and stamp(nA.id) == sA + 2, f"importing pictures is a change of the cell ({ch})")
ok(W.sync_editors() == [], "and then it is quiet again")

# the project file holds the link, and no pictures
f2 = os.path.join(T, "annot.opara")
SAVE["path"] = f2
ok(W.save(True) and os.path.isfile(f2), "Save writes the project")
raw = json.load(open(f2))
dn = next(n for n in raw["nodes"] if n["kind"] == "annotator")["data"]
ok(set(dn) == {"link"} and os.path.getsize(f2) < 40000, f"the .opara file holds only the link ({sorted(dn)}, {os.path.getsize(f2)} bytes)")
shell.close_tab(shell.tabs.indexOf(wa))
ok(W.editor_of(nA.id) is None, "(the tab is closed)")
shell.tabs.setCurrentWidget(W)
W.load(f2)
P = W.project
nA = [x for x in P.nodes.values() if x.kind == "annotator"][0]
ok(P.status(nA.id, "document") == wp.OK, "after opening the file: ok")
sA = stamp(nA.id)
n_images = len(json.load(open(os.path.join(proj, "manifest.json")))["images"])
wa = W.open_cell(nA.id, "document")
ok(wa is not None and wa.temp_root is None and os.path.abspath(wa.path) == os.path.abspath(proj), "the block opens the annotator on the linked folder")
ok(len(wa.project.manifest["images"]) == n_images and n_images > 0, f"with its pictures ({n_images})")
ok(W.sync_editors() == [] and stamp(nA.id) == sA and not wa.is_dirty(), "and opening it is not a change")
ok(not_in_session(wa.path), "the tab of a block is not brought back with the session (the Workbench owns it; the folder itself is the person's and may be in Open Recent)")

# Save As in the window: the block follows the window
copy = os.path.join(T, "Birds copy.annotator")
SAVE["path"] = copy
ok(wa.save(True) is True and os.path.abspath(wa.path) == os.path.abspath(copy), "Save As in the annotator copies the project and works on the copy")
ok(W.sync_editors() == [nA.id] and nA.data["link"]["abs"] == os.path.abspath(copy), "the block follows the window to the copy")
shell.close_tab(shell.tabs.indexOf(wa))

# the folder is not where it was: the person is asked; a wrong folder is refused
moved = os.path.join(T, "moved")
os.makedirs(moved)
shutil.move(copy, os.path.join(moved, "Birds copy.annotator"))
ok(ad.dataset_folder(W, nA) is None, "(the folder is gone from its place)")
PICK["dir"] = ""
ok(W.open_cell(nA.id, "document") is None and W.editor_of(nA.id) is None, "a block whose folder is gone asks where it is; cancelling opens nothing")
PICK["dir"] = moved
ok(W.open_cell(nA.id, "document") is None and W.editor_of(nA.id) is None, "a folder that is not an annotator project is refused")
PICK["dir"] = os.path.join(moved, "Birds copy.annotator")
wa = W.open_cell(nA.id, "document")
ok(wa is not None and os.path.abspath(wa.path) == os.path.abspath(PICK["dir"]) and ad.dataset_folder(W, nA) == os.path.abspath(PICK["dir"]), "the folder that is chosen is opened and the block links to it from now on")

# save the block on its own: a copy of the folder, twice
out2 = os.path.join(T, "out2")
os.makedirs(out2)
p1, p2 = ad.export(W, nA, out2), ad.export(W, nA, out2)
ok(p1 != p2 and p1.endswith(".annotator") and os.path.isfile(os.path.join(p1, "manifest.json")) and os.path.isfile(os.path.join(p2, "manifest.json")), f"saving it on its own copies the project folder, never overwriting ({os.path.basename(p1)}, {os.path.basename(p2)})")
ok(len(json.load(open(os.path.join(p1, "manifest.json")))["images"]) == n_images, "with its pictures")
ne = W.add_block("annotator", 260, 200, title="Never saved")
try:
    ad.export(W, ne, out2)
    refused = False
except ValueError as ex:
    refused = "no saved annotator project" in str(ex)
ok(refused, "a block without a saved project cannot be saved on its own (it says why)")

# delete: the tab goes, the folder stays
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nA.id]
sel[0].setSelected(True)
keep_folder = ad.dataset_folder(W, nA)
ok(W.delete_selected() == 1 and nA.id not in P.nodes and shell.tabs.indexOf(wa) < 0 and nA.id not in W.node_state, "Delete removes the block and closes its tab")
ok(os.path.isfile(os.path.join(keep_folder, "manifest.json")), "the dataset folder is the person's: it stays")

# the packages: said, not a broken tab
import annotator_tab
real_missing = annotator_tab.missing
annotator_tab.missing = lambda required_only=False: [("cv2", "opencv-python", "video import", True)]
av = ad.available(W)
ok(av[0] is False and "opencv-python" in av[1], f"a missing package is said ({av[1]})")
annotator_tab.missing = real_missing
addons.tab_kinds = lambda: {k: v for k, v in real().items() if k != "annotator"}
av = ad.available(W)
ok(av[0] is False and "General Classification Annotator" in av[1], f"a switched-off add-on is said ({av[1]})")
addons.tab_kinds = real
ok(ad.available(W)[0], "and available again with it")

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
