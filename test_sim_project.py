"""Simulation project folders: the folder format, the local copy of the source (part and assembly), the tab's New project / Import /
Save / Open / Update from original, and that the project keeps working after the original is gone."""
import os, sys, json, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(HERE, "addons_src", "simulation")
if not os.path.isdir(SIM):
    SIM = os.path.join(HERE, "dev_addons", "simulation")
sys.path[:0] = [HERE, SIM]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import pm_model as pm, sk_tools as sk
import asm_model as am
import sim_project as sp
import sim_source as ss
import sim_tab

T = tempfile.mkdtemp(prefix="opara_proj_")


def make_part(path, w=40.0, h=10.0):
    d = pm.Document()
    d.params = {"W": str(w), "H": str(h)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r = sk.add_rect_corner(m, (0, 0), (w, 20))
    m.add_con("dim_h", [("ln", r["lns"][0])], value=w)
    m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    assert d.solid is not None, d.status
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())
    return d, s["id"]


# ---------------------------------------------------------------- 1. the folder format
assert sp.ext_of("fea") == ".gpf" and sp.ext_of("beam") == ".gpb" and sp.ext_of("cfd") == ".gpc"
f1 = os.path.join(T, "plate.gpf")
m = sp.create(f1, "fea")
assert os.path.isfile(os.path.join(f1, "simulation.json")) and sp.kind_of_folder(f1) == "fea" and m["source"] is None
assert sp.kind_of_folder(T) is None and sp.kind_of_folder(os.path.join(T, "nope")) is None
try:
    sp.create(f1, "cfd")
    raise SystemExit("a 2D FEA project must not be reused as a CFD project")
except sp.ProjectError:
    pass
other = os.path.join(T, "occupied")
os.makedirs(other)
open(os.path.join(other, "x.txt"), "w").write("x")
try:
    sp.create(other, "fea")
    raise SystemExit("a folder that holds other files must be refused")
except sp.ProjectError:
    pass
assert sp.default_name("fea", "plate", T).endswith("plate 2.gpf"), sp.default_name("fea", "plate", T)
assert sp.default_name("cfd", "a/b").endswith("a_b.gpc")

# ---------------------------------------------------------------- 2. the local copy of a part
orig_dir = os.path.join(T, "orig")
os.makedirs(orig_dir)
pa = os.path.join(orig_dir, "plate.gpd")
doc, sid = make_part(pa)
m, missing = sp.import_source(f1, orig_path=pa)
copy = sp.source_file(f1, m)
assert copy.endswith(os.path.join("source", "plate.gpd")) and os.path.isfile(copy) and not missing
assert m["source"]["type"] == "part" and m["source"]["name"] == "plate" and m["source"]["orig"] == os.path.abspath(pa)
src = ss.open_source(copy)
assert src.type == "part" and abs(src.doc.solid.volume - 40 * 20 * 10) < 1e-3
# the copy is independent: change and delete the original
shutil.move(orig_dir, orig_dir + "_moved")
assert not os.path.exists(pa)
assert abs(ss.open_source(copy).doc.solid.volume - 40 * 20 * 10) < 1e-3, "the copy must not need the original"
# a study can change the copy's parameters
src.set_values({"g:H": "20"})
assert abs(src.doc.solid.volume - 40 * 20 * 20) < 1e-3
assert abs(ss.open_source(copy).doc.solid.volume - 40 * 20 * 10) < 1e-3, "changing the object must not change the copy on disk"
# re-import replaces the copy
pa2 = os.path.join(T, "orig_moved", "plate.gpd")
make_part(pa2, h=30.0)
m, _ = sp.import_source(f1, orig_path=pa2)
assert abs(ss.open_source(sp.source_file(f1, m)).doc.solid.volume - 40 * 20 * 30) < 1e-3
assert not os.path.exists(os.path.join(f1, "source.new"))
try:
    sp.import_source(f1, orig_path=os.path.join(T, "none.gpd"))
    raise SystemExit("a missing original must be reported")
except sp.ProjectError:
    pass

# ---------------------------------------------------------------- 3. the local copy of an assembly (with its parts, and a sub-assembly)
ad = os.path.join(T, "asmdir")
os.makedirs(os.path.join(ad, "parts"))
make_part(os.path.join(ad, "parts", "base.gpd"), w=60.0, h=10.0)
make_part(os.path.join(ad, "parts", "lid.gpd"), w=30.0, h=5.0)
sub = am.Assembly()
sub.add_component(os.path.join("parts", "lid.gpd"), fixed=True)
open(os.path.join(ad, "sub.gpa"), "w").write(sub.to_json())
top = am.Assembly()
top.add_component(os.path.join("parts", "base.gpd"), fixed=True)
top.add_component("sub.gpa", pos=(0, 0, 10))
top.add_component(os.path.join("parts", "missing.gpd"))
open(os.path.join(ad, "top.gpa"), "w").write(top.to_json())
f2 = os.path.join(T, "asm.gpf")
sp.create(f2, "fea")
m2, miss = sp.import_source(f2, orig_path=os.path.join(ad, "top.gpa"))
assert m2["source"]["type"] == "asm" and miss == [os.path.join("parts", "missing.gpd")], miss
files = sorted(os.listdir(os.path.join(f2, "source")))
assert files == ["base.gpd", "lid.gpd", "sub.gpa", "top.gpa"], files
shutil.rmtree(ad)                                                   # the whole original is gone
asrc = ss.open_source(sp.source_file(f2, m2))
bodies = asrc.__class__ and __import__("asm_sub").bodies_of(asrc, asrc.asm)
assert len(bodies) == 2, [b[0] for b in bodies]
assert all(c["path"] and not os.path.isabs(c["path"]) and os.sep not in c["path"] for c in json.loads(open(sp.source_file(f2, m2)).read())["components"] if "missing" not in c["path"])

# ---------------------------------------------------------------- 4. the tab: New project, Import, Save, Open, Update from original
pa = os.path.join(T, "tabpart", "bracket.gpd")
os.makedirs(os.path.dirname(pa))
make_part(pa)
for kind in ("fea", "beam", "cfd"):
    w = sim_tab.SimWindow(kind)
    assert not w.b_import.isEnabled() and not w.b_refresh.isEnabled(), "nothing can be imported before the project exists"
    assert not w.project_ok() and w.source_widget() is None and [i for i, _n in w.source_items() if not str(i).startswith("__")] == []
    assert w.create_project(os.path.join(T, f"tab_{kind}"))
    assert w.path.endswith(sp.ext_of(kind)) and w.project_ok()
    assert w.import_file(pa), kind
    assert w.source is not None and w.src["type"] == "part" and w.src["name"] == "bracket"
    items = w.source_items()
    sk_id = next(i for i, n in items if i not in (sim_tab.SLICE_NEW, sim_tab.SLICE_LAST))
    w.tab.picker.refresh()
    w.tab.picker.select(sk_id)
    w.tab.picker.go()
    assert getattr(w.tab, "model", None) is not None, kind
    if kind == "fea":
        w.tab.e_h.setText("3.5")
    assert w.save() and os.path.isfile(sp.state_path(w.path))
    assert not w.is_dirty()
    folder = w.path
    shutil.rmtree(os.path.dirname(pa) + "_x", ignore_errors=True)
    os.replace(pa, pa + ".away")                                    # the original disappears
    w2 = sim_tab.SimWindow.open_project(None, folder)
    assert w2.kind == kind and w2.source is not None and w2.source.type == "part" and w2.src["name"] == "bracket"
    assert getattr(w2.tab, "model", None) is not None, "the sketch must come back from the project"
    if kind == "fea":
        assert w2.tab.e_h.text() == "3.5"
    assert abs(w2.source.doc.solid.volume - 40 * 20 * 10) < 1e-3
    # update from original: not found -> the copy is kept (the question dialog is not shown here: nothing is cleared)
    os.replace(pa + ".away", pa)
    make_part(pa, h=25.0)                                           # the original changed
    w2.tab.mesh = w2.tab.result = None
    w2.refresh()
    assert abs(w2.source.doc.solid.volume - 40 * 20 * 25) < 1e-3, "Update from original must copy the changed part"
    assert abs(ss.open_source(sp.source_file(folder)).doc.solid.volume - 40 * 20 * 25) < 1e-3
    make_part(pa)

# wrong kind
try:
    sim_tab.SimWindow.open_project(None, T)
    raise SystemExit("a folder that is no project must be refused")
except ValueError:
    pass

# a slice of the copy works without any original
w = sim_tab.SimWindow("fea")
w.create_project(os.path.join(T, "slice_fea"))
assert w.import_file(pa)
os.replace(pa, pa + ".gone")
planes = [n for n, _ in w.planes()]
assert "Top" in planes and w.bodies(), planes
w.meta["slice"] = {"plane": "Top", "offset": 5.0, "flip": False, "excluded": []}
js = w.slice_json(True)
assert js is not None and "Slice Top" in js[0], js
os.replace(pa + ".gone", pa)

# the manifest of the add-on declares the three project-folder tabs
import addons
mf = json.load(open(os.path.join(SIM, "addon.json")))
kinds = {t["kind"]: t for t in mf.get("tabs", [])}
assert set(kinds) == {"beam", "fea", "cfd"} and all(t["project_folder"]["marker"] == "simulation.json" for t in kinds.values())
assert {t["project_folder"]["format"] for t in kinds.values()} == {sp.fmt(k) for k in ("beam", "fea", "cfd")}
for t in kinds.values():
    assert callable(getattr(sim_tab, t["factory"]))

shutil.rmtree(T, ignore_errors=True)
print("OK sim project")
