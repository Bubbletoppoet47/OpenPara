import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, asm_model as am, asm_sketch as ak, asm_sketch_win as aw, gsv
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
tmp = tempfile.mkdtemp()
warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: warned.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Ok)

def make_part(name):
    d = pm.Document(); d.params = {"Width": "10"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (20, 20)); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="Width")); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa, pb, pc = make_part("plateA.gpd"), make_part("plateB.gpd"), make_part("loose.gpd")
A = am.Assembly(); A.add_component("plateA.gpd", fixed=True); A.add_component("plateB.gpd", pos=(30, 0, 0)); A.params = {"Gap": "5"}
pasm = os.path.join(tmp, "frame.gpa"); open(pasm, "w").write(A.to_json())

sh = gpd_app.AppShell([pa, pb, pasm])
wa, wb = sh.tabs.widget(sh.find_tab(pa)), sh.tabs.widget(sh.find_tab(pb)); wasm = sh.tabs.widget(sh.find_tab(pasm))
sw = sh.new_asm_sketch(); QTest.qWait(50)
assert isinstance(sw, aw.AsmSketchWindow)
f = ak.sketch_feature(sw.doc); m = sw.doc.models[f["id"]]
m.add_param("W", 50.0); m.add_param("Hole", 8.0); sk.solve_model(m)
m.set_configs(["Small", "Big"], "Small"); m.params["W"]["vals"] = [30.0, 90.0]; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all()
# linking needs a saved sketch and an assembly first
assert not sw.add_part(pa) and warned, warned
spath = os.path.join(tmp, "frame.gpk"); sw.path = spath; assert sw.save()
assert not sw.add_part(pa)                                              # still no assembly
# the Variables table: Export checkbox per variable, nothing exported yet
t = sw.var_table; assert t.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable and [t.horizontalHeaderItem(i).text() for i in range(4)] == ["Export", "Variable", "Kind", "Role"]
rows = {t.item(r, 1).text(): r for r in range(t.rowCount())}; assert set(rows) == {"W", "Hole"}
t.item(rows["W"], 0).setCheckState(Qt.CheckState.Checked); QTest.qWait(10)
assert sw.doc.export == ["W"] and ak.payload(sw.doc)[2]["Big"] == {"W": 90.0}
# the assembly, then parts (open ones follow live; the loose one is not a component: linked with a note)
assert sw.link_one(pasm); sw.assembly = pasm
assert wasm.asm.gsv and wasm.asm.gsv["src"] == "frame.gpk" and {"Small", "Big"} <= set(wasm.asm.cfg["names"]), wasm.asm.cfg["names"]
assert sw.add_part(pa) and sw.add_part(pb) and sw.add_part(pc)
assert "not a component" in sw.vars_status.text(), sw.vars_status.text()
assert sorted(os.path.basename(p) for p in sw.parts) == ["loose.gpd", "plateA.gpd", "plateB.gpd"]
assert wa.doc.gsv["src"] == "frame.gpk" and wa.doc.cfg["names"] == ["Default", "Small", "Big"], wa.doc.cfg["names"]
assert pm.Document.from_json(open(pc).read()).gsv is not None            # a closed part got the link written into its file
# the read-only table in the part and assembly
wa.gsv_panel.refresh(); gt = wa.gsv_panel.table
names = [gt.item(r, 0).text() for r in range(gt.rowCount())]; print(names)
assert names == ["AS-Small-W", "AS-Big-W"] and gt.item(0, 3).text() == "driving" and not (gt.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)
wasm.gsv_panel.refresh(); assert wasm.gsv_panel.table.rowCount() == 2
# bind Width to W: each sketch-driven configuration follows its own number
wa.doc.gsv_bind("g:Width", "W"); wa.doc.cfg_apply("Big"); wa.update_all()
assert close(float(wa.doc.values["Width"]), 90) and close(wa.doc.solid.volume, 20 * 20 * 90), wa.doc.values
assert wa.doc.cfg["cells"]["Default"]["g:Width"] == "10"
# the cell in the configuration table is shown highlighted and keeps its text
wa.cfg_panel.refresh(); ct = wa.cfg_panel.table; rb = wa.doc.cfg["names"].index("Big"); assert "{AS-@-W}" in ct.item(rb, 1).text(), ct.item(rb, 1).text()
# a sketch change reaches the open parts and assembly live
m = sw.doc.models[f["id"]]; m.params["W"]["vals"][1] = 120.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all(); QTest.qWait(700)
assert close(float(wa.doc.values["Width"]), 120) and close(wa.doc.solid.volume, 20 * 20 * 120), wa.doc.values
assert close(wasm.asm.gsv["vals"]["Big"]["W"], 120)
# a NEW sketch configuration creates configurations in the parts and the assembly
m = sw.doc.models[f["id"]]; m.set_configs(m.configs + ["Huge"], m.configs[m.active]); m.params["W"]["vals"][-1] = 300.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all(); QTest.qWait(700)
assert "Huge" in wa.doc.cfg["names"] and "Huge" in wasm.asm.cfg["names"] and wa.doc.cfg["cells"]["Huge"]["g:Width"] == "{AS-@-W}", wa.doc.cfg["names"]
wa.doc.cfg_apply("Huge"); wa.update_all(); assert close(wa.doc.solid.volume, 20 * 20 * 300)
# the part is linked to ONE sketch: a second sketch is refused
sw3 = sh.new_asm_sketch(); QTest.qWait(30); s3 = os.path.join(tmp, "other.gpk"); sw3.path = s3; sw3.save(); sw3.assembly = pasm
warned.clear(); assert not sw3.link_one(pa) and warned, warned
# close B, change the sketch, write to closed files; B pulls on its own when opened too
wa.save(); wb.save(); wasm.save()
ib = sh.find_tab(pb); sh.tabs.removeTab(ib); wb.deleteLater()
sw.save(); m = sw.doc.models[f["id"]]; m.params["W"]["vals"][0] = 44.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all(); QTest.qWait(500)
sw.push_now(write_closed=True); print(sw.vars_status.text())
assert pm.Document.from_json(open(pb).read()).gsv["vals"]["Small"]["W"] == 44.0
# a stale file (not re-saved) still follows the sketch when opened: the part, and the part an assembly draws
sw.save(); m = sw.doc.models[f["id"]]; m.params["W"]["vals"][0] = 47.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.save()
w2 = pm_app.MainWindow(pb); assert w2.doc.gsv["vals"]["Small"]["W"] == 47.0, w2.doc.gsv
import assembly
aw2 = assembly.AssemblyWindow(pasm, shell=None); assert aw2.asm.gsv["vals"]["Small"]["W"] == 47.0
# saving keeps the sketch location relative
w2.save(); assert '"src": "frame.gpk"' in open(pb).read()
# reopen the sketch: assembly, parts, export flags come back
sw2 = aw.AsmSketchWindow(spath, shell=sh); assert sw2.assembly == os.path.normpath(pasm) and len(sw2.parts) == 3 and sw2.doc.export == ["W"]
# remove a part: its link goes, its configurations stay
sw2.part_list.setCurrentRow(sw2.parts.index(os.path.normpath(pc))); sw2.remove_part()
assert pm.Document.from_json(open(pc).read()).gsv is None and len(sw2.parts) == 2
print("OK")
