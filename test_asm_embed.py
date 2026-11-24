"""Assemblies whose components live INSIDE the file (asm_embed.py, assembly.py embed mode): inserting a part makes a copy in the assembly (the part file is not touched and later changes
to it do not reach the assembly); the same part inserted twice stays one part with two instances; the assembly saves as ONE self-contained file that opens on another computer (the part
files are gone) and keeps mates, configurations and positions; a component's configurations work; Edit Component changes only the assembly's copy and the assembly sees the edit;
an old assembly file with paths is read as copies; a missing part file stays a reference and is said; an assembly inserted into another is copied with its own parts; nothing changes for an
assembly that does not use embed mode (it still writes exactly what it wrote before).   python test_asm_embed.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import asm_embed
import asm_model as am
import asm_sub
import gpd_app
import pm_model as pm
import sk_tools as sk

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


T = tempfile.mkdtemp(prefix="opara_embed_")


def make_part(name, rect, depth, cfg=None):
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1])
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    if cfg:
        d.cfg_add_col("g:H")
        d.cfg_add("Tall")
        d.cfg_set_cell("Tall", "g:H", str(cfg))
    p = os.path.join(T, name)
    open(p, "w").write(d.to_json())
    return p


def height(w, c):
    return w.solid_of(c).bounding_box().size.Z


pa = make_part("base.gpd", ((0, 0), (60, 40)), 10)
pb = make_part("block.gpd", ((0, 0), (10, 10)), 10, cfg=30)
sh = gpd_app.AppShell([])

# ------------------------------------------------------------------------------------------------------------------------------------ the model
a = am.Assembly()
ok(a.parts == {} and "parts" not in json.loads(a.to_json()), "an assembly with no embedded component writes no 'parts' (the file is what it always was)")
obj = json.loads(open(pa).read())
v1 = a.embed_part("base", "part", obj)
v2 = a.embed_part("base", "part", json.loads(json.dumps(obj)))
ok(v1 == "embedded:P1/base.gpd" and v1 == v2 and len(a.parts) == 1, f"the same content under the same name is stored once ({v1})")
obj2 = json.loads(json.dumps(obj))
obj2["params"]["H"] = "99"
v3 = a.embed_part("base", "part", obj2)
ok(v3 == "embedded:P2/base.gpd" and len(a.parts) == 2, "a different content under the same name is a second copy")
ok(am.is_embedded(v1) and not am.is_embedded("a/b.gpd") and am.embed_key(v3) == "P2", "is_embedded / embed_key")
c = a.add_component(v1)
ok(c["base"] == "base" and c["path"] == v1, "the component's name comes from the copy's name")
js = json.loads(a.to_json())
ok(sorted(js["parts"]) == ["P1"], "only the copies a component uses are written")
b = am.Assembly.from_json(a.to_json())
ok(b.parts["P1"]["doc"] == obj and b.components[0]["path"] == v1, "and read back")

# ------------------------------------------------------------------------------------------------------------------------------------ inserting in embed mode
w = sh.new_assembly()
w.embed = True
w.insert_files([pa, pb, pb])
A = w.asm
c0, c1, c2 = A.components
ok(all(am.is_embedded(c["path"]) for c in A.components), f"in embed mode every component is a copy ({[c['path'] for c in A.components]})")
ok(len(A.parts) == 2 and c1["path"] == c2["path"], "the part inserted twice is stored once: two instances of one part")
ok(abs(height(w, c0) - 10) < 1e-6 and abs(height(w, c1) - 10) < 1e-6, "the copies build like the files")
ok(c0["fixed"] and not c1["fixed"], "the first component is fixed")
ok(w.part_doc(c1) is not None and w.part_doc(c1).solid is not None, "part_doc finds the solid")
ok(A.part_cfgs_fn(c1) == ["Default", "Tall"], f"the part's configurations are known ({A.part_cfgs_fn(c1)})")
c1["config"] = "Tall"
w.doc_memo.clear()
ok(abs(height(w, c1) - 30) < 1e-6, "a component can use a configuration of its copy")
c1["config"] = None
w.doc_memo.clear()
# changing the original file later does not reach the assembly
open(pa, "w").write(json.dumps({**obj, "params": {"H": "77"}}))
w.refresh_parts()
ok(abs(height(w, c0) - 10) < 1e-6, "a later change of the part file does not reach the assembly")
open(pa, "w").write(json.dumps(obj))
# mates and saving as one file
faces = lambda c: (max([f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().Z),
                   min([f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().Z))
R = lambda c, f: {"c": c["id"], "k": "face", "r": am.face_ref(f)}
w.mate_start()
w.add_mate_ref(R(c0, faces(c0)[0]), {"cid": c0["id"], "kind": "face", "idx": 0, "label": "F"})
w.add_mate_ref(R(c1, faces(c1)[1]), {"cid": c1["id"], "kind": "face", "idx": 0, "label": "F"})
w.mate_ok()
A = w.asm
c0, c1, c2 = A.components[:3]
ok(len(A.mates) == 1, "a mate between two copies works")
z1 = float(c1["pos"][2])
ok(abs(z1 - 10.0) < 1e-3, f"the block sits on the base (z = {z1:.3f})")
ap = os.path.join(T, "asm.gpa")
w.path = ap
ok(w.save() is True and os.path.isfile(ap), "Save writes the assembly")
saved = json.load(open(ap))
ok(sorted(saved["parts"]) == ["P1", "P2"] and all(am.is_embedded(c["path"]) for c in saved["components"]), "the file holds the parts inside it")
ok(saved["components"][0]["path"].startswith("embedded:") and "\\" not in saved["components"][0]["path"], "and their paths are not turned into file paths")
ok(not w.is_dirty(), "saved: not dirty")
# the file works when the part files are gone, in another folder
other = os.path.join(T, "elsewhere")
os.makedirs(other)
moved = os.path.join(other, "moved.gpa")
shutil.copy(ap, moved)
os.remove(pa)
os.remove(pb)
sh2 = gpd_app.AppShell([moved])
w2 = sh2.cur()
ok(hasattr(w2, "asm") and len(w2.asm.components) == 3, "the assembly opens with its part files gone and in another folder (a plain window, no embed mode)")
d2 = w2.asm.components
ok(abs(height(w2, d2[0]) - 10) < 1e-6 and w2.part_doc(d2[1]).solid is not None, "its parts are all there")
ok(abs(float(d2[1]["pos"][2]) - z1) < 1e-3 and len(w2.asm.mates) == 1, "with the mate and the position")
ok(not w2.is_dirty(), "just opened: not dirty")
w2.asm.comp(d2[1]["id"])["config"] = "Tall"
w2.doc_memo.clear()
ok(abs(height(w2, d2[1]) - 30) < 1e-6, "configurations of an embedded part work after reopening")
# undo / redo with embedded parts
w.delete_component(c2["id"])
ok(len(w.asm.components) == 2, "a component deleted")
w.do_undo()
ok(len(w.asm.components) == 3 and all(am.is_embedded(c["path"]) for c in w.asm.components) and abs(height(w, w.asm.components[2]) - 10) < 1e-6, "undo brings it back with its copy")
w.do_redo()
ok(len(w.asm.components) == 2, "redo")
w.do_undo()
# a derived (pattern) copy resolves through its source
d = w.duplicate_component(w.asm.components[1]["id"])
ok(d is not None and am.is_embedded(w.asm.comp(d)["path"]) and abs(height(w, w.asm.comp(d)) - 10) < 1e-6, "Duplicate keeps the copy and builds")

# ------------------------------------------------------------------------------------------------------------------------------------ Edit Component
pa2 = make_part("base2.gpd", ((0, 0), (60, 40)), 10)
w3 = sh.new_assembly()
w3.embed = True
w3.insert_files([pa2])
c = w3.asm.components[0]
w3.sel_comp = c["id"]
tab = w3.edit_component()
ok(tab is not None and getattr(tab, "no_session", False) and w3.embed_edit, "Edit Component on a copy opens it in a tab of its own (not in the session)")
ok(tab.title() == f"{c['name']} (in the assembly)", f"the tab says it is the copy in the assembly ({tab.title()})")
ok(sh.dependents(w3) == [tab], "and it belongs to the assembly's tab")
tab.doc.params["H"] = "25"
tab.doc.rebuild()
w3.doc_memo.clear()
ok(abs(height(w3, c) - 25) < 1e-6, "the assembly sees the edit at once (it reads the tab's Document)")
ok(w3.is_dirty(), "and is dirty")
ok(w3.asm.parts["P1"]["doc"]["params"]["H"] == "25", "the copy inside the assembly holds the edit")
ok(json.load(open(pa2))["params"]["H"] == "10", "the part's own file was not touched")
n_tabs = sh.tabs.count()
again = w3.edit_component()
ok(again is tab and sh.tabs.count() == n_tabs, "Edit Component again shows the same tab")
# closing the editing tab keeps the edit (the file in the temporary folder is the last saved state: closing with 'discard' keeps what the assembly had)
ap3 = os.path.join(T, "asm3.gpa")
w3.path = ap3
w3.save()
ok(json.load(open(ap3))["parts"]["P1"]["doc"]["params"]["H"] == "25", "Save writes the edited copy")
sh.close_tab(sh.tabs.indexOf(w3))
ok(sh.tabs.indexOf(tab) < 0, "closing the assembly closes its editing tab")
ok(w3.embed_dir is None or not os.path.exists(w3.embed_dir), "and its temporary folder is removed")

# ------------------------------------------------------------------------------------------------------------------------------------ an old file with paths
pa3 = make_part("legacy_base.gpd", ((0, 0), (60, 40)), 10)
pb3 = make_part("legacy_block.gpd", ((0, 0), (10, 10)), 10)
lg = am.Assembly()
lg.add_component(os.path.basename(pa3), fixed=True)
lg.add_component(os.path.basename(pb3))
lg.add_component("not_there.gpd")
lp = os.path.join(T, "legacy.gpa")
open(lp, "w").write(lg.to_json())
w4 = sh.new_assembly()
w4.embed = True
MSGS.clear()
w4.open_file(lp)
cs = w4.asm.components
ok(am.is_embedded(cs[0]["path"]) and am.is_embedded(cs[1]["path"]) and not am.is_embedded(cs[2]["path"]), "an old assembly is read with copies of the parts it found (embed mode)")
ok("not_there.gpd" in " ".join(MSGS) or any("not_there" in s for s in [w4.statusBar().currentMessage()]), "and a part file that is missing stays a reference, and is said")
ok(abs(height(w4, cs[0]) - 10) < 1e-6, "the copies build")
ok(os.path.isfile(pa3) and open(lp).read() == lg.to_json(), "the old files were not touched")
w5 = sh.new_assembly()
w5.open_file(lp)
ok(not any(am.is_embedded(c["path"]) for c in w5.asm.components), "without embed mode an old assembly is read as it always was (paths)")
ok("parts" not in json.loads(w5.asm.to_json()), "and written as it always was")
# insert in the old way
w6 = sh.new_assembly()
w6.insert_files([pa3])
ok(not am.is_embedded(w6.asm.components[0]["path"]), "without embed mode inserting a part makes a path reference, as before")

# ------------------------------------------------------------------------------------------------------------------------------------ an assembly inside an assembly
sub = sh.new_assembly()
sub.embed = True
sub.insert_files([pa3, pb3])
sp = os.path.join(T, "sub.gpa")
sub.path = sp
sub.save()
top = sh.new_assembly()
top.embed = True
top.insert_files([sp, pa3])
cc = top.asm.components
ok(cc[0]["path"].endswith(".gpa") and am.is_embedded(cc[0]["path"]) and top.asm.parts[am.embed_key(cc[0]["path"])]["kind"] == "assembly", "an assembly file inserted in embed mode is copied in with its own parts")
inner = top.asm.parts[am.embed_key(cc[0]["path"])]["asm"]
ok(all(am.is_embedded(c["path"]) for c in inner["components"]) and sorted(inner["parts"]) == ["P1", "P2"], "the nested copy holds its own parts")
d0 = top.part_doc(cc[0])
ok(d0 is not None and d0.solid is not None and getattr(d0, "is_sub", False), "the nested assembly builds as one rigid component")
os.remove(pa3)
os.remove(pb3)
os.remove(sp)
tp = os.path.join(T, "top.gpa")
top.path = tp
top.save()
t2 = sh.new_assembly()
t2.open_file(tp)
ok(t2.part_doc(t2.asm.components[0]) is not None and t2.part_doc(t2.asm.components[0]).solid is not None, "it still builds when every file it was made from is gone")

# an assembly in a file that contains the assembly itself cannot be copied in forever
loop_a = os.path.join(T, "loop_a.gpa")
loop_b = os.path.join(T, "loop_b.gpa")
la, lb = am.Assembly(), am.Assembly()
la.add_component("loop_b.gpa")
lb.add_component("loop_a.gpa")
open(loop_a, "w").write(la.to_json())
open(loop_b, "w").write(lb.to_json())
try:
    asm_embed.self_contained_text(loop_a)
    text, warns = asm_embed.self_contained_text(loop_a)
    ok(any("contains itself" in x for x in warns), f"a loop of assemblies is found and said ({warns[:1]})")
except Exception as ex:                                                              # noqa: BLE001
    ok(False, f"a loop raised {ex}")
try:
    asm_embed.embed_file(am.Assembly(), os.path.join(T, "nope.gpd"))
    ok(False, "a missing file raises")
except asm_embed.EmbedError as ex:
    ok("could not be read" in str(ex), f"a file that cannot be read is an error with the name ({ex})")
open(os.path.join(T, "junk.gpd"), "w").write("not json")
try:
    asm_embed.embed_file(am.Assembly(), os.path.join(T, "junk.gpd"))
    ok(False, "a file that is not a part raises")
except asm_embed.EmbedError as ex:
    ok("not a part file" in str(ex), f"a file that is not a part is refused ({ex})")
# a component given as a dict (a part of a Workbench project)
w7 = sh.new_assembly()
w7.embed = True
w7.insert_files([{"name": "Lid", "kind": "part", "text": json.dumps(obj)}])
ok(len(w7.asm.components) == 1 and w7.asm.components[0]["path"] == "embedded:P1/Lid.gpd" and w7.asm.components[0]["base"] == "Lid", "a part handed over as text becomes a copy named after it")
ok(w7.asm.components[0]["name"] == "Lid<1>", "its component is called Lid<1>")
w8 = sh.new_assembly()
w8.insert_files([{"name": "Lid", "kind": "part", "text": json.dumps(obj)}])
ok(am.is_embedded(w8.asm.components[0]["path"]), "text handed over is always embedded (even outside embed mode)")
hook_calls = []
w8.insert_hook = lambda win: hook_calls.append(win) or True
w8.insert_dialog()
ok(hook_calls == [w8], "the insert dialog gives way to the hook (the Workbench offers its parts there)")

# ------------------------------------------------------------------------------------------------------------------------------------ the other way: an embedded assembly as plain files
fa = make_part("fa.gpd", ((0, 0), (60, 40)), 10)             # (the parts of the tests above were deleted on purpose)
fb = make_part("fb.gpd", ((0, 0), (10, 10)), 10)
inner = am.Assembly()
inner.add_component(inner.embed_part("block", "part", json.loads(open(fb).read())), fixed=True)
outer = am.Assembly()
outer.add_component(outer.embed_part("base", "part", json.loads(open(fa).read())), fixed=True)
outer.add_component(outer.embed_part("inner", "assembly", json.loads(inner.to_json())), pos=(100, 0, 0), fixed=True)
outer.add_component("somewhere/else.gpd", fixed=True)
FL = os.path.join(T, "flat")
fpath = asm_embed.flatten_to_files(json.loads(outer.to_json()), FL, "frame")
ok(os.path.basename(fpath) == "frame.gpa" and sorted(os.listdir(FL)) == ["base.gpd", "block.gpd", "frame.gpa", "inner.gpa"], f"every part and sub-assembly is a file ({sorted(os.listdir(FL))})")
fobj = json.load(open(fpath))
ok([c["path"] for c in fobj["components"]] == ["base.gpd", "inner.gpa", "somewhere/else.gpd"], f"the components point at those files; a reference stays a reference ({[c['path'] for c in fobj['components']]})")
ok("parts" not in fobj and "parts" not in json.load(open(os.path.join(FL, "inner.gpa"))), "and nothing is embedded any more")
ok([c["path"] for c in json.load(open(os.path.join(FL, "inner.gpa")))["components"]] == ["block.gpd"], "the sub-assembly points at its own part file")
import assembly
wf = assembly.AssemblyWindow(None, shell=None)
wf.open_file(fpath)
ok(abs(height(wf, wf.asm.components[0]) - 10) < 1e-6 and wf.solid_of(wf.asm.components[1]) is not None, "the files build as an assembly (the missing reference is just missing)")
FL2 = os.path.join(T, "flat2")
asm_embed.flatten_to_files(json.loads(outer.to_json()), FL2, "frame")
asm_embed.flatten_to_files(json.loads(outer.to_json()), FL2, "frame")
ok(sorted(os.listdir(FL2)).count("frame.gpa") == 1 and "frame_2.gpa" in os.listdir(FL2) and "base_2.gpd" in os.listdir(FL2), f"nothing is overwritten: a second time gets other names ({sorted(os.listdir(FL2))})")
twin = am.Assembly()
twin.add_component(twin.embed_part("same", "part", json.loads(open(fa).read())), fixed=True)
twin.add_component(twin.embed_part("same", "part", json.loads(open(fb).read())), fixed=True)
FL3 = os.path.join(T, "flat3")
tp = asm_embed.flatten_to_files(json.loads(twin.to_json()), FL3, "twin")
ok(sorted(os.listdir(FL3)) == ["same.gpd", "same_2.gpd", "twin.gpa"] and [c["path"] for c in json.load(open(tp))["components"]] == ["same.gpd", "same_2.gpd"], "two different parts with one name get two files")
broken = json.loads(outer.to_json())
broken["parts"].pop(am.embed_key(outer.components[0]["path"]))
try:
    asm_embed.flatten_to_files(broken, os.path.join(T, "flat4"), "x")
    ok(False, "a missing copy raises")
except asm_embed.EmbedError as ex:
    ok("missing" in str(ex) and "base<1>" in str(ex), f"a copy that is missing from the assembly is said, with the component ({ex})")
tp2 = asm_embed.flatten_to_files(json.loads(am.Assembly().to_json()), os.path.join(T, "flat5"), "a/b:c")
ok(os.path.basename(tp2) == "a_b_c.gpa", f"the name is a good file name ({os.path.basename(tp2)})")

shutil.rmtree(T, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
