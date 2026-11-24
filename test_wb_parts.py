"""The Part and Assembly blocks of the Workbench in the real program window (the add-on loaded like the Playground does): a block opens its editor in a tab, opening is not a change,
an edit is read back into the project (and makes the cells that use it say so), the project file holds the parts, a project part is inserted into an assembly as a COPY (and the two
never change each other), closing / deleting / renaming / saving on its own work, and the temporary files of the editors never reach the recent list or the session.
python test_wb_parts.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
shutil.copytree(os.path.join(HERE, "dev_addons", "workbench"), os.path.join(DEV, "workbench"), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import asm_model as am
import assembly
import gpd_app
import pm_app
import pm_model as pm
import recent
import sk_tools as sk
import wb_nodes
import wb_parts
import wb_project as wp
import wb_tab
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbp_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)


def add_box(doc, rect, depth):
    """A box in a Document (the same steps as the part window's sketch + extrude)."""
    doc.params = {"H": str(depth)}
    s = doc.add(pm.new_feature("sketch", plane={"base": "Top"}))
    doc.rebuild()
    m = doc.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1])
    sk.solve_model(m)
    doc.store_sketch(s["id"])
    doc.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    doc.rebuild()


def box_json(rect, depth):
    d = pm.Document()
    add_box(d, rect, depth)
    return json.loads(d.to_json())


def stamp(p, nid, key="geometry"):
    return p.cell(nid, key)["stamp"]


ok(isinstance(W, wb_tab.WorkbenchTab), "the program opened a Workbench at the start")
ok(wb_nodes.adapter_for("part") is not None and wb_nodes.adapter_for("assembly") is not None, "Part and Assembly have adapters")
ok("part" not in wb_nodes.check_kinds() and "assembly" not in wb_nodes.check_kinds(), "and are no longer listed as 'not wired in'")
ok(wb_nodes.availability(W, "part")[0] and wb_nodes.availability(W, "assembly")[0], "the toolbox offers them")

# ------------------------------------------------------------------------------------------------------------------------------------ a Part block
nP = W.add_block("part", 60, 60, title="Base")
P = W.project
ok(isinstance(nP.data.get("doc"), dict) and not nP.data["doc"].get("features"), "a new Part block holds an empty part")
ok(P.status(nP.id, "geometry") == wp.INCOMPLETE, f"and says incomplete: it has no solid ({P.status(nP.id, 'geometry')})")
s0 = stamp(P, nP.id)
ed = W.open_cell(nP.id, "geometry")
ok(isinstance(ed, pm_app.MainWindow) and shell.tabs.indexOf(ed) >= 0, "double-click opens the part in the usual part window, in a tab")
ok(shell.tabs.tabText(shell.tabs.indexOf(ed)).startswith(f"{nP.label} Base"), f"named after the block ({shell.tabs.tabText(shell.tabs.indexOf(ed))})")
ok(W.editor_of(nP.id) is ed and shell.dependents(W) == [ed], "the workbench knows it, and the program closes it with the workbench")
fp = W.node_state[nP.id]["file"]
ok(os.path.isfile(fp) and fp.startswith(W.workspace) and fp.endswith("Base.gpd"), f"its file is in the project's workspace ({os.path.basename(fp)})")
ok(not any(os.path.abspath(i["path"]) == os.path.abspath(fp) for i in recent.items()), "it is not in the recent list")
tabs, cur = shell.session_tabs()
ok(all(t["path"] != os.path.abspath(fp) for t in tabs), "nor in the session")
ok(W.open_cell(nP.id, "geometry") is ed, "a second double-click shows the same tab")
ok(W.sync_editors() == [] and stamp(P, nP.id) == s0, "opening it is not a change: nothing is stale")
ok(not ed.is_dirty(), "and the part tab is not 'unsaved'")

add_box(ed.doc, ((0, 0), (60, 40)), 10)
ed.update_all()
ok(ed.is_dirty(), "after an edit in the part window it is unsaved")
ch = W.sync_editors()
ok(ch == [nP.id], f"the project reads the edit back ({ch})")
ok(len(nP.data["doc"]["features"]) == 2, "the block holds the new part")
ok(stamp(P, nP.id) == s0 + 1, "its cell changed (the cells that use it will say so)")
ok(P.status(nP.id, "geometry") == wp.OK, f"it has a solid now: ok ({P.status(nP.id, 'geometry')})")
ok(not ed.is_dirty(), "reading it back is saving it in the workspace: the tab is not 'unsaved' any more")
ok(W.sync_editors() == [], "the same state again is not a change")
ok(P.is_dirty(), "the project is changed")

# the file
f1 = os.path.join(T, "demo.opara")
import PyQt6.QtWidgets as qw
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
ok(raw["format"] == "openpara-project" and any(n["kind"] == "part" and n["data"]["doc"]["features"] for n in raw["nodes"]), "the .opara file holds the part inside it")
ok(not P.is_dirty(), "saved: not changed")

# closing the editor with a saved edit: read back from the workspace file
ed.doc.params["H"] = "25"
ed.update_all()
s_before = stamp(P, nP.id)
ok(ed.save(), "(the part window saves into the workspace)")
ok(shell.close_tab(shell.tabs.indexOf(ed)), "the editor tab closes")
ok(W.editor_of(nP.id) is None, "the workbench no longer has an editor for it")
ok(nP.data["doc"]["params"]["H"] == "25" and stamp(P, nP.id) == s_before + 1, "an edit that was saved before the tab was closed is read back (once: the program does it when the workbench is shown again)")
ok(W.sync_editors() == [], "and a second reading finds nothing new")
ok(P.status(nP.id, "geometry") == wp.OK, "and the block is ready")
ok(all(not os.path.abspath(p) == os.path.abspath(fp) for p in shell.closed), "the tab is not in Window > Reopen closed tab (its file is a temporary one)")

# reopened from the block's content
ed2 = W.open_cell(nP.id, "geometry")
ok(ed2 is not ed and ed2.doc.params["H"] == "25" and ed2.doc.solid is not None, "reopening shows the block's content (the edit, built)")
ok(W.sync_editors() == [], "and again opening is not a change")
H25 = json.loads(json.dumps(nP.data["doc"]))

# renaming the block moves its file
P.rename_node(nP.id, "Plate")
ok(P.node(nP.id).title == "Plate", "(renamed)")
shell.close_tab(shell.tabs.indexOf(ed2))
ed3 = W.open_cell(nP.id, "geometry")
ok(os.path.basename(W.node_state[nP.id]["file"]) == "Plate.gpd" and not os.path.exists(fp), "after a rename the file follows the name")
ok(ed3.doc.params["H"] == "25", "with the content")

# ------------------------------------------------------------------------------------------------------------------------------------ an Assembly block
nS = W.add_block("assembly", 360, 60, title="Frame")
ok(isinstance(nS.data.get("asm"), dict) and P.status(nS.id, "geometry") == wp.INCOMPLETE, "a new Assembly block is empty and incomplete")
sw = W.open_cell(nS.id, "geometry")
ok(isinstance(sw, assembly.AssemblyWindow) and sw.embed and shell.tabs.indexOf(sw) >= 0, "double-click opens the usual assembly window in embed mode")
ok(W.editor_of(nS.id) is sw and sw.no_session and sw.depends_on() is W, "it belongs to the workbench")
ok(W.sync_editors() == [], "opening it is not a change")

# Insert Component offers the project's parts
asked = {}


def pick(tab, items, parent=None):
    asked["items"] = items
    return "project", [i for i in items if i["name"] == "Plate"]


wb_parts.choose_sources = pick
sw.insert_dialog()
ok([i["name"] for i in asked["items"]] == ["Plate"] and asked["items"][0]["kind"] == "part", f"the chooser lists the project's parts ({[i['name'] for i in asked['items']]})")
ok(len(sw.asm.components) == 1, "the part was inserted")
c0 = sw.asm.components[0]
ok(am.is_embedded(c0["path"]), f"as a copy inside the assembly ({c0['path']})")
ok(sw.solid_of(c0) is not None and abs(sw.solid_of(c0).bounding_box().size.Z - 25) < 1e-6, "which builds (height 25: the part as it is now)")
ok(sw.asm.parts[am.embed_key(c0["path"])]["doc"]["params"]["H"] == "25", "the copy holds the part's data")
ch = W.sync_editors()
ok(ch == [nS.id], f"the project takes the assembly ({ch})")
ok(nS.data["asm"]["parts"], "its data holds the parts inside it")
ok(P.status(nS.id, "geometry") == wp.OK, "and the block is ready (a component with a solid)")

# no link: the part changes, the assembly's copy does not
ed3.doc.params["H"] = "40"
ed3.update_all()
W.sync_editors()
ok(nP.data["doc"]["params"]["H"] == "40", "the part block has the new height")
ok(sw.asm.parts[am.embed_key(sw.asm.components[0]["path"])]["doc"]["params"]["H"] == "25", "the copy in the assembly keeps the old one")
ok(nS.data["asm"]["parts"][am.embed_key(c0["path"])]["doc"]["params"]["H"] == "25", "and so does the assembly block")
# the other way round: Edit Component changes only the copy
sw.sel_comp = c0["id"]
etab = sw.edit_component()
ok(etab is not None and shell.tabs.indexOf(etab) >= 0, "Edit Component opens the copy in a tab")
ok(etab.no_session and etab.depends_on() is sw, "which belongs to the assembly's tab")
tmpf = etab.path
ok(not any(os.path.abspath(i["path"]) == os.path.abspath(tmpf) for i in recent.items()), "and is not in the recent list")
etab.doc.params["H"] = "5"
etab.update_all()
sw.doc_memo.clear()
ok(abs(sw.solid_of(sw.asm.components[0]).bounding_box().size.Z - 5) < 1e-6, "the assembly sees the edit at once")
ch = W.sync_editors()
ok(ch == [nS.id] and nS.data["asm"]["parts"][am.embed_key(c0["path"])]["doc"]["params"]["H"] == "5", "the project takes it")
ok(nP.data["doc"]["params"]["H"] == "40", "the Part block is untouched by it")

# cancelling the chooser inserts nothing; with no part in the project the file dialog is what opens
wb_parts.choose_sources = lambda tab, items, parent=None: (None, None)
n_before = len(sw.asm.components)
ok(wb_parts.choose_and_insert(W, nS, sw) is True and len(sw.asm.components) == n_before, "Cancel in the chooser inserts nothing (and the file dialog does not open)")
wb_parts.choose_sources = lambda tab, items, parent=None: ("browse", None)
ok(wb_parts.choose_and_insert(W, nS, sw) is False, "'Browse for a file...' lets the file dialog open")
W2 = shell.new_addon_tab("workbench", None)
nS2 = W2.add_block("assembly", 40, 40)
sw2 = W2.open_cell(nS2.id, "geometry")
CALLS = []
wb_parts.choose_sources = lambda tab, items, parent=None: (CALLS.append(items), ("project", []))[1]
ok(wb_parts.choose_and_insert(W2, nS2, sw2) is False and not CALLS, "with no part in the project the file dialog opens at once (the chooser is not shown)")
shell.close_tab(shell.tabs.indexOf(W2))

# an assembly whose only component has no solid is not ready
nE = W.add_block("part", 60, 220, title="Empty")
nS4 = W.add_block("assembly", 360, 220, title="Hollow")
sw4 = W.open_cell(nS4.id, "geometry")
wb_parts.choose_sources = lambda tab, items, parent=None: ("project", [i for i in items if i["name"] == "Empty"])
sw4.insert_dialog()
ok(len(sw4.asm.components) == 1 and sw4.solid_of(sw4.asm.components[0]) is None, "(an assembly with one component that has no solid)")
W.sync_editors()
ok(P.status(nS4.id, "geometry") == wp.INCOMPLETE, f"it is incomplete, not ready ({P.status(nS4.id, 'geometry')})")
ok(P.status(nS.id, "geometry") == wp.OK, "while the one with a solid is ok")

# ------------------------------------------------------------------------------------------------------------------------------------ the file keeps both, nothing external
f2 = os.path.join(T, "frame.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f2, ""))
ok(W.save(True), "the project is saved with both blocks")
raw = json.load(open(f2))
ok(len(raw["nodes"]) == 4 and all(n["data"] for n in raw["nodes"]), "four blocks with their data")
ok(str(T) not in open(f2).read(), "no path of a file on this computer is in it")
shell.close_tab(shell.tabs.indexOf(W))
ok(shell.tabs.count() == 0 or all(not isinstance(shell.tabs.widget(i), (pm_app.MainWindow, assembly.AssemblyWindow)) for i in range(shell.tabs.count())), "closing the workbench closed its editors")

# reopened in a new tab: nothing computed, nothing opened; the assembly works with no part file anywhere
W3 = shell.open_path(f2)
ok(isinstance(W3, wb_tab.WorkbenchTab) and len(W3.project.nodes) == 4, "the project opens in a Workbench tab")
ok(shell.tabs.count() == 1, "with no editor opened")
p3 = W3.project
nS3 = [n for n in p3.nodes.values() if n.kind == "assembly" and n.title == "Frame"][0]
nP3 = [n for n in p3.nodes.values() if n.kind == "part" and n.title == "Plate"][0]
ok(p3.status(nS3.id, "geometry") in (wp.OK, wp.INCOMPLETE), f"the cells have a status without opening anything ({p3.status(nS3.id, 'geometry')})")
sw3 = W3.open_cell(nS3.id, "geometry")
ok(len(sw3.asm.components) == 1 and abs(sw3.solid_of(sw3.asm.components[0]).bounding_box().size.Z - 5) < 1e-6, "the assembly opens and builds from what the project file holds (with the edited copy)")
ok(W3.sync_editors() == [], "opening it from a file is not a change either")
pw3 = W3.open_cell(nP3.id, "geometry")
ok(pw3.doc.params["H"] == "40" and pw3.doc.solid is not None, "the part opens too")
ok(W3.sync_editors() == [], "and not a change")

# ------------------------------------------------------------------------------------------------------------------------------------ saving a block on its own
out = os.path.join(T, "out")
os.makedirs(out)
pp = W3.export_node(nP3.id, out)
ok(pp and pp.endswith(".gpd") and os.path.isfile(pp), f"the part is saved on its own as a .gpd ({os.path.basename(pp or '')})")
d = pm.Document.from_json(open(pp).read())
d.rebuild()
ok(d.solid is not None and d.params["H"] == "40", "which opens in the program as any part")
ap = W3.export_node(nS3.id, out)
ok(ap and ap.endswith(".gpa") and os.path.isfile(ap), "the assembly is saved on its own as a .gpa")
ok(json.load(open(ap))["parts"], "with its parts inside")
pp2 = W3.export_node(nP3.id, out)
ok(pp2 != pp and os.path.isfile(pp) and os.path.isfile(pp2), f"saving again never overwrites ({os.path.basename(pp2)})")
w_plain = assembly.AssemblyWindow(ap, shell=None)
ok(len(w_plain.asm.components) == 1 and w_plain.solid_of(w_plain.asm.components[0]) is not None, "the saved assembly opens and builds in the ordinary assembly window")

# a block with nothing in it cannot be saved on its own, and says why
nEmpty = W3.add_block("part", 500, 500, title="Nothing")
nEmpty.data.pop("doc")
MSGS.clear()
ok(W3.export_node(nEmpty.id, out) is None and MSGS and "nothing to save" in MSGS[-1], f"an empty block is refused with the reason ({MSGS[-1:]})")
W3.scene.remove_nodes([nEmpty.id])

# loading another project into a tab forgets what the adapters knew about the old one (the ids n1, n2 ... mean other blocks there)
W5 = shell.new_addon_tab("workbench", None)
n5 = W5.add_block("part", 20, 20)
W5.open_cell(n5.id, "geometry")
ok(n5.id in W5.node_state and W5.editor_of(n5.id) is not None, "(a block with an editor and a state)")
W5.load(f2)
ok(W5.node_state == {} and not W5.editors, "loading a project into the tab closes the editors and forgets the old states")
shell.close_tab(shell.tabs.indexOf(W5))

# ------------------------------------------------------------------------------------------------------------------------------------ deleting a block with its editor open
nid = nP3.id
W3.scene.clearSelection()
sel = [it for it in W3.scene.items() if hasattr(it, "nid") and it.nid == nid]
ok(bool(sel), "(the block is on the schematic)")
sel[0].setSelected(True)
pw3.doc.params["H"] = "99"
pw3.update_all()
ok(pw3.is_dirty(), "(the part editor has unsaved changes)")
ok(W3.delete_selected() == 1, "Delete removes the block")
ok(nid not in p3.nodes and shell.tabs.indexOf(pw3) < 0, "and closes its editor without asking about it (the block is gone)")
ok(nid not in W3.node_state, "and forgets it")

# closing the workbench cleans up
ws = W3.workspace
shell.close_tab(shell.tabs.indexOf(W3))
ok(not os.path.exists(ws), "closing the workbench removes its workspace folder")

# a block made with content says at once whether it is ready; a part that stops building is incomplete, not a crash
W4 = shell.new_addon_tab("workbench", None)
nB = W4.add_block("part", 20, 20, data={"doc": box_json(((0, 0), (10, 10)), 7)})
ok(W4.project.status(nB.id, "geometry") == wp.OK, f"a block made with a part that builds is ok at once ({W4.project.status(nB.id, 'geometry')})")
nBad = W4.add_block("part", 220, 20, data={"doc": {**box_json(((0, 0), (10, 10)), 7), "features": []}})
ok(W4.project.status(nBad.id, "geometry") == wp.INCOMPLETE, "a block made with a part that has no solid is incomplete")
nAs = W4.add_block("assembly", 420, 20, data={"asm": {"components": []}})
ok(W4.project.status(nAs.id, "geometry") == wp.INCOMPLETE, "an assembly with no component is incomplete")
e4 = W4.open_cell(nB.id, "geometry")
ok(e4.doc.solid is not None and W4.sync_editors() == [], "the part opens, built, and that is not a change")
e4.doc.features[1]["sketch"] = "nope"
e4.doc.rebuild()
ok(e4.doc.solid is None, "(the part no longer builds)")
ch = W4.sync_editors()
ok(ch == [nB.id] and W4.project.status(nB.id, "geometry") == wp.INCOMPLETE, f"the block says incomplete ({W4.project.status(nB.id, 'geometry')})")
shell.close_tab(shell.tabs.indexOf(W4))

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
