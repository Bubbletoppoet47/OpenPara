"""The Constraint Lab dev add-on, loaded the real way (development add-on folder): File > New Constraint Lab gives OpenPara's own assembly window on the
Current mate engine; the Engine buttons move the assembly onto the lab's Experimental engine and back (poses and mates stay, new / undone / opened
assemblies follow the choice, lab_adopt() runs); the Mate Matrix module and its window work and an unchanged copy of the engine scores the same."""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
os.symlink(os.path.join(HERE, "dev_addons", "constraint_lab"), os.path.join(DEV, "constraint_lab"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
import addons
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, ext, assembly

addons.startup(); addons.register_extensions(ext); addons.activate()
assert "constraint_lab" in addons.dev_ids() and addons.is_dev("constraint_lab") and addons.is_active("constraint_lab")
spec = addons.tab_kinds().get("constraint_lab")
assert spec is not None and spec["label"] == "Constraint Lab" and "constraint_lab" in addons.known()
import lab_engine, lab_matrix, lab_tab
assert lab_engine.MateError is am.MateError, "the window catches am.MateError: the copy must raise that class"
assert lab_engine.Assembly is not am.Assembly and lab_engine.TYPES == am.TYPES


def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(UD, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)

# ---- the tab opens from File > New and is the real assembly window on the Current engine
sh = gpd_app.AppShell([pa])
labels = [a.text() for a in sh.menuBar().actions()[0].menu().actions()]
assert "New Constraint Lab" in labels, labels
w = sh.new_addon_tab("constraint_lab")
assert isinstance(w, lab_tab.LabWindow) and isinstance(w, assembly.AssemblyWindow) and w.kind == "constraint_lab"
assert sh.tabs.tabText(sh.tabs.count() - 1).startswith("Constraint Lab"), sh.tabs.tabText(sh.tabs.count() - 1)
assert type(w.asm) is am.Assembly and w.engine_name == "Current"
assert w.act["tool_eng_cur"].isChecked() and not w.act["tool_eng_exp"].isChecked() and "Current" in w.engine_label.text()
assert w.ribbon.tabText(w.ribbon.count() - 1) == "Constraint Lab" and "lab_matrix" in w.act
assert sh.tab_kind(w) == "assembly", "it is an assembly tab for the shell: Save / Open / mates all work as in the real one"

# ---- mate two parts on the Current engine, exactly as the assembly window does
w.insert_files([pa, pb, pb]); A = w.asm
c0, c1, c2 = A.components
def R(c, f): return {"c": c["id"], "k": "face", "r": am.face_ref(f)}
def face(c, which):
    pl = [f for f in w.solid_of(c).faces() if f.geom_type.name == "PLANE"]
    return max(pl, key=lambda f: f.center().Z) if which == "top" else min(pl, key=lambda f: f.center().Z)
def mate_faces(a, fa, b, fb, ty=None):
    w.mate_start()
    w.add_mate_ref(R(a, face(a, fa)), {"cid": a["id"], "kind": "face", "idx": 0, "label": "Face"})
    w.add_mate_ref(R(b, face(b, fb)), {"cid": b["id"], "kind": "face", "idx": 0, "label": "Face"})
    if ty:
        w.set_mate_type(ty)
    w.mate_ok()
mate_faces(c0, "top", c1, "bot")
assert len(A.mates) == 1 and abs(c1["pos"][2] - 10) < 1e-3, (A.mates, c1["pos"])
assert type(w.asm) is am.Assembly

# ---- switch to the Experimental engine: same assembly, new class, poses and mates stay
w.set_engine("Experimental")
assert w.asm is A and type(A) is lab_engine.Assembly and w.engine_name == "Experimental"
assert len(A.mates) == 1 and abs(c1["pos"][2] - 10) < 1e-3
assert w.act["tool_eng_exp"].isChecked() and not w.act["tool_eng_cur"].isChecked() and "Experimental" in w.engine_label.text()
mate_faces(c0, "top", c2, "bot")                                        # a mate made, previewed and solved by the Experimental engine
assert len(w.asm.mates) == 2 and abs(w.asm.components[2]["pos"][2] - 10) < 1e-3
assert type(w.asm) is lab_engine.Assembly
# undo / redo rebuild the assembly from json: they must come back on the chosen engine
w.do_undo(); assert type(w.asm) is lab_engine.Assembly and len(w.asm.mates) == 1
w.do_redo(); assert type(w.asm) is lab_engine.Assembly and len(w.asm.mates) == 2
# save / open and New follow it too
p = os.path.join(UD, "lab.gpa")
import fileio; fileio.write_text(p, w.asm.to_json()); w.path = p
w.open_file(p); assert type(w.asm) is lab_engine.Assembly and len(w.asm.mates) == 2
w.new_doc(); assert type(w.asm) is lab_engine.Assembly and not w.asm.components
w.open_file(p)
# the engine may need attributes the other engine's __init__ did not make: lab_adopt() is called after the swap
lab_engine.Assembly.lab_adopt = lambda self: setattr(self, "adopted", True)
w.set_engine("Current"); assert type(w.asm) is am.Assembly and len(w.asm.mates) == 2 and not hasattr(w.asm, "adopted")
w.set_engine("Experimental"); assert w.asm.adopted is True
del lab_engine.Assembly.lab_adopt
w.set_engine("Current")
assert w.asm.solve() and abs(w.asm.components[1]["pos"][2] - 10) < 1e-3

# ---- the Mate Matrix module
kinds, mates = ["plane", "point", "axis"], ["coincident", "parallel"]
r = lab_matrix.run(am, mates=mates, kinds=kinds, n_starts=2)
assert len(r["cells"]) == len(kinds) ** 2 * len(mates) and all(len(v) == 2 for v in r["cells"].values()) and not r["cancelled"]
assert set(sum(r["cells"].values(), [])) <= set(lab_matrix.OUTCOMES)
assert r["cells"][("plane", "plane", "coincident")] == ["ok", "ok"], r["cells"][("plane", "plane", "coincident")]
assert r["cells"][("point", "plane", "parallel")] == ["ERR", "ERR"] and any("cannot mate" in m for s in r["msgs"].values() for m in s)
r2 = lab_matrix.run(lab_engine, mates=mates, kinds=kinds, n_starts=2)
assert lab_matrix.diff_text({"Current": r, "Experimental": r}).startswith("The engines give the same")
assert all(v2.count("ok") >= r["cells"][k].count("ok") for k, v2 in r2["cells"].items()), "the Experimental engine is never worse than the Current one on a pick pair"
txt = lab_matrix.report({"Current": r, "Experimental": r2})
assert "coincident" in txt and "Current" in txt and "Experimental" in txt and "Where the engines differ" in txt
assert "Quick run: only the first 2 of 10 start poses" in txt
t = lab_matrix.totals(r, "coincident"); assert t["ok"] > 0 and 0 < t["score"] <= 1
dist = lab_matrix.run(am, mates=["distance", "angle"], kinds=["plane", "point"], n_starts=2)
assert dist["cells"][("plane", "plane", "distance")] == ["ok", "ok"] and dist["cells"][("plane", "plane", "angle")] == ["ok", "ok"], "distance / angle get a real target, so they are not 'noop'"
assert set(dist["cells"][("point", "point", "angle")]) <= set(lab_matrix.OUTCOMES)        # a point has no direction: ERR or EXC today, whatever a fixed engine says
stopped = lab_matrix.run(am, mates=["coincident"], kinds=kinds, n_starts=1, progress=lambda d, n: d >= 2)
assert stopped["cancelled"] and len(stopped["cells"]) == 2
assert "stopped early" in lab_matrix.report({"Current": stopped})

# ---- the Mate Matrix window
w.matrix_open(); d = w.matrix_win
assert d is not None and d.windowTitle() == "Mate Matrix"
d.which.setCurrentIndex(0); d.quick.setChecked(True)
d.run()
assert not d.running and d.run_b.isEnabled() and not d.stop_b.isEnabled()
assert list(d.results) == ["Current"] and "coincident" in d.text.toPlainText() and "Current" in d.text.toPlainText(), d.text.toPlainText()[:300]
assert d.bar.value() == 1000 and "Several mates together" in d.text.toPlainText() and "pin in hole" in d.text.toPlainText()
d.close(); assert d.stop is True
assert w.matrix_win is d

print("OK constraint lab")
os._exit(0)
