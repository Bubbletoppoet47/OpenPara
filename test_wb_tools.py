"""The tool blocks of the Workbench (Sheets, Systems and Controls, Circuits, the Truss Generator) in the real program window: a block opens the tool in its usual tab, opening is not a change,
an edit is read back into the project (the cell goes from 'incomplete' to ok, and changes again with the next edit), the project file holds the document (a file, or for the Truss
Generator a folder), the temporary files never reach the recent list or the session, and closing / deleting / renaming / exporting / a switched-off add-on work.
python test_wb_tools.py"""
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
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("workbench", "sheets", "controls", "circuits"):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
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


import gpd_app
import recent
import wb_nodes
import wb_project as wp
import wb_tab
import wb_tools
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbt_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
P = W.project


def stamp(nid):
    return P.cell(nid, "document")["stamp"]


def sheets_edit(w):
    w.wb.set_input(w.wb.sheet_names()[0], 2, 2, "42")


def sheets_read(w):
    return w.wb.value(w.wb.sheet_names()[0], 2, 2)


def controls_edit(w):
    w.sections[0].load_example(1)


def controls_read(w):
    return (w.sections[0].num.text(), w.sections[0].den.text())


def circuits_edit(w):
    w.scene.add_part("BAT", 0, 0)
    w.edited()


def circuits_read(w):
    return sorted(p.kind for p in w.scene.parts())


def truss_edit(w):
    w.name_edit.setText("Roof truss")
    w.rename_project()


def truss_read(w):
    return w.p["name"]


CASES = {
    "sheets": (".opsheet", sheets_edit, sheets_read, 42.0, False),
    "controls": (".opctl", controls_edit, controls_read, ("2s+3", "s^2+3s+2"), False),
    "circuits": (".opcirc", circuits_edit, circuits_read, ["BAT"], False),
    "truss": (".truss", truss_edit, truss_read, "Roof truss", True),
}

ok(isinstance(W, wb_tab.WorkbenchTab), "the program opened a Workbench at the start")
for kind in CASES:
    ok(wb_nodes.adapter_for(kind) is not None, f"{kind} has an adapter")
    ok(kind not in wb_nodes.check_kinds(), f"and is not listed as 'not wired in' ({kind})")
    ok(wb_nodes.availability(W, kind)[0], f"the toolbox offers it ({kind})")
ok(wb_nodes.adapter_for("truss").folder and not wb_nodes.adapter_for("sheets").folder, "only the Truss Generator's document is a folder")

NODES = {}
for i, (kind, (ext_, edit, read, want, is_folder)) in enumerate(CASES.items()):
    print(f"--- {kind}")
    n = W.add_block(kind, 60 + 200 * i, 60, title=f"My {kind}")
    NODES[kind] = n
    slot = "files" if is_folder else "file"
    ok(not n.data.get(slot), f"a new block holds nothing yet ({kind})")
    ok(P.status(n.id, "document") == wp.INCOMPLETE, f"and says incomplete ({P.status(n.id, 'document')})")
    s0 = stamp(n.id)
    w = W.open_cell(n.id, "document")
    ok(w is not None and shell.tabs.indexOf(w) >= 0, f"double-click opens the usual {kind} tab")
    ok(W.editor_of(n.id) is w and w in shell.dependents(W), "the workbench knows it, and the program closes it with the workbench")
    f = W.node_state[n.id]["file"]
    ok(f.startswith(W.workspace) and os.path.basename(f) == f"My {kind}{ext_}", f"its document is in the project's workspace, named after the block ({os.path.basename(f)})")
    ok(os.path.isdir(f) if is_folder else os.path.isfile(f), "and exists there (a new one is saved at once)")
    ok(not any(os.path.abspath(i2["path"]) == os.path.abspath(f) for i2 in recent.items()), "it is not in the recent list")
    tabs, cur = shell.session_tabs()
    ok(all(t["path"] != os.path.abspath(f) for t in tabs), "nor in the session")
    ok(W.open_cell(n.id, "document") is w, "a second double-click shows the same tab")
    ok(W.sync_editors() == [] and stamp(n.id) == s0, "opening it is not a change")
    ok(not w.is_dirty(), "and the tab is not 'unsaved'")
    ok(P.status(n.id, "document") == wp.INCOMPLETE, "still incomplete: nothing was made in it")

    edit(w)
    ok(w.is_dirty(), "after an edit it is unsaved")
    ch = W.sync_editors()
    ok(ch == [n.id], f"the project reads the edit back ({ch})")
    ok(bool(n.data.get(slot)), "the block holds the document")
    ok(stamp(n.id) == s0 + 1, "its cell changed")
    ok(P.status(n.id, "document") == wp.OK, f"and is ready: ok ({P.status(n.id, 'document')})")
    ok(not w.is_dirty(), "reading it back saved it in the workspace")
    ok(W.sync_editors() == [], "the same state again is not a change")

# the blocks do not change each other: every one was changed once
ok(all(stamp(n.id) == 1 for n in NODES.values()), f"each block changed once, on its own ({[stamp(n.id) for n in NODES.values()]})")

# ------------------------------------------------------------------------------------------------------------------------------ the project file
f1 = os.path.join(T, "tools.opara")
import PyQt6.QtWidgets as qw
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "Save writes the project")
raw = json.load(open(f1))
byk = {n["kind"]: n for n in raw["nodes"]}
for kind, (ext_, edit, read, want, is_folder) in CASES.items():
    d = byk[kind]["data"]
    ok(bool(d.get("files" if is_folder else "file")), f"the .opara file holds the {kind} document inside it")
ok(set(byk["truss"]["data"]["files"]) >= {"project.json"}, f"the Truss Generator's folder has its project.json ({sorted(byk['truss']['data']['files'])})")
ok(not P.is_dirty(), "saved: not changed")

# close all the editors and read it again from the saved project
for kind, n in NODES.items():
    w = W.editor_of(n.id)
    ok(shell.close_tab(shell.tabs.indexOf(w)), f"the {kind} tab closes")
    ok(W.editor_of(n.id) is None, "the workbench no longer has an editor for it")
ok(all(os.path.abspath(p) not in [os.path.abspath(x["path"]) for x in recent.items()] for p in shell.closed), "none of them is in Window > Reopen closed tab or recent")

# the same workbench loads the file again
shell.tabs.setCurrentWidget(W)
W.load(f1)
P = W.project
ok(P.path == f1 and not P.is_dirty() and W.node_state == {}, "a project that was just opened is not changed, and no editor state is left over")
for kind, (ext_, edit, read, want, is_folder) in CASES.items():
    n = [x for x in P.nodes.values() if x.kind == kind][0]
    ok(P.status(n.id, "document") == wp.OK, f"{kind}: ok after opening the file (nothing computed)")
    s0 = stamp(n.id)
    w = W.open_cell(n.id, "document")
    ok(w is not None and read(w) == want, f"{kind}: the document comes back as it was ({read(w) if w is not None else None})")
    ok(not w.is_dirty() and W.sync_editors() == [] and stamp(n.id) == s0, f"{kind}: and opening it is still not a change")
    NODES[kind] = n

# a second edit is a second change
n = NODES["circuits"]
w = W.editor_of(n.id)
s1 = stamp(n.id)
w.scene.add_part("R", 100, 0)
w.edited()
ok(W.sync_editors() == [n.id] and stamp(n.id) == s1 + 1, "a second edit is read back again (the stamp moves on)")
ok(circuits_read(W.editor_of(n.id)) == ["BAT", "R"], "with both parts")

# ------------------------------------------------------------------------------------------------------------------------------ rename, export, delete
P.rename_node(n.id, "Divider")
ok(P.node(n.id).title == "Divider", "(renamed)")
old_file = W.node_state[n.id]["file"]
shell.close_tab(shell.tabs.indexOf(W.editor_of(n.id)))
w = W.open_cell(n.id, "document")
ok(not os.path.exists(old_file), "the document under the old name is gone from the workspace")
ok(os.path.basename(W.node_state[n.id]["file"]) == "Divider.opcirc", f"after a rename the file follows the name ({os.path.basename(W.node_state[n.id]['file'])})")
ok(circuits_read(w) == ["BAT", "R"], "with its content")

out = os.path.join(T, "out")
os.makedirs(out)
for kind, nn in NODES.items():
    ext_, _e, read, want, is_folder = CASES[kind]
    ad = wb_nodes.adapter_for(kind)
    p1 = ad.export(W, nn, out)
    p2 = ad.export(W, nn, out)
    ok(p1 != p2 and os.path.exists(p1) and os.path.exists(p2) and p1.endswith(ext_) and p2.endswith(ext_), f"{kind}: exporting twice makes two documents, never overwrites ({os.path.basename(p1)}, {os.path.basename(p2)})")
    ok(os.path.isdir(p1) == is_folder, f"{kind}: {'a folder' if is_folder else 'a file'}")
# the exported documents open on their own in the program
for kind, nn in NODES.items():
    ext_, _e, read, want, is_folder = CASES[kind]
    p1 = wb_nodes.adapter_for(kind).export(W, nn, out)
    w2 = shell.new_addon_tab(kind, p1)
    exp = ["BAT", "R"] if kind == "circuits" else want
    ok(w2 is not None and read(w2) == exp, f"{kind}: the exported document opens in its tool by itself ({read(w2) if w2 is not None else None})")
    if w2 is not None:
        shell.close_tab(shell.tabs.indexOf(w2))

# a document is opened from the block's content, never mixed with what an earlier open left in the workspace (here: no reading back happened, so the block is the truth)
nt = NODES["truss"]
tf = W.node_state[nt.id]["file"]
shell.close_tab(shell.tabs.indexOf(W.editor_of(nt.id)))
W.sync_editors()
open(os.path.join(tf, "stray.txt"), "w").write("left over")
W.node_state[nt.id].pop("base")
wt = W.open_cell(nt.id, "document")
ok(not os.path.exists(os.path.join(tf, "stray.txt")) and truss_read(wt) == "Roof truss", "a stray file in the workspace is not part of the document that is opened again")
ok(W.sync_editors() == [] and "stray.txt" not in nt.data["files"], "and it never gets into the project")

# an empty block refuses to export
ne = W.add_block("sheets", 60, 300, title="Empty")
try:
    wb_nodes.adapter_for("sheets").export(W, ne, out)
    refused = False
except ValueError as ex:
    refused = "nothing in it" in str(ex)
ok(refused, "an empty block cannot be exported (it says why)")

# delete: the tab goes
nd = NODES["sheets"]
wd = W.editor_of(nd.id)
ok(wd is not None, "(the sheets tab is open)")
W.scene.clearSelection()
sel = [it for it in W.scene.items() if hasattr(it, "nid") and it.nid == nd.id]
ok(bool(sel), "(the block is on the schematic)")
sel[0].setSelected(True)
wd.wb.set_input(wd.wb.sheet_names()[0], 3, 3, "7")
ok(wd.is_dirty(), "(the sheet has unsaved changes)")
ok(W.delete_selected() == 1, "Delete removes the block")
ok(nd.id not in P.nodes and shell.tabs.indexOf(wd) < 0 and nd.id not in W.node_state, "and closes its tab without asking about it, and forgets its state")

# a tool whose add-on is switched off
ad = wb_nodes.adapter_for("controls")
real = addons.tab_kinds
addons.tab_kinds = lambda: {k: v for k, v in real().items() if k != "controls"}
av = ad.available(W)
ok(av[0] is False and "Systems and Controls" in av[1], f"a missing add-on is said ({av[1]})")
addons.tab_kinds = real
ok(ad.available(W)[0], "and available again with it")

print()
print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
