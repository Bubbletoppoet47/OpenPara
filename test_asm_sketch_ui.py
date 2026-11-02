import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, pm_app, asm_sketch as ak, asm_sketch_win as aw
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
tmp = tempfile.mkdtemp()

def make_part(name):
    d = pm.Document(); d.params = {"Width": "10"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, (0, 0), (20, 20)); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="Width")); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa, pb = make_part("plateA.gpd"), make_part("plateB.gpd")

sh = gpd_app.AppShell([pa, pb])
wa, wb = sh.tabs.widget(0), sh.tabs.widget(1)
sw = sh.new_asm_sketch(); QTest.qWait(50)
assert isinstance(sw, aw.AsmSketchWindow) and sw.KIND == "asmsketch"
assert [sh.tabs.tabText(i) for i in range(sh.tabs.count())][-1].startswith("Assembly Sketch")
print("sketch window editing:", sw.ed.active if sw.ed is not None else None, "tabs:", [sw.left.tabText(i) or sw.left.tabToolTip(i) for i in range(sw.left.count())])
# a symbol W with two configurations in the sketch
f = ak.sketch_feature(sw.doc); m = sw.doc.models[f["id"]]
m.add_param("W", 50.0); sk.solve_model(m)
m.set_configs(["Small", "Big"], "Small"); m.params["W"]["vals"] = [30.0, 90.0]; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all()
spath = os.path.join(tmp, "frame.gpk")
sw.path = spath; assert sw.save()
assert os.path.isfile(spath)
assert sw.var_table.rowCount() == 1 and sw.var_table.item(0, 0).text() == "W" and sw.var_table.columnCount() == 4, (sw.var_table.rowCount(), sw.var_table.columnCount())

# link plate A's Width and plate B's Width to W (the dialog, driven without exec)
for w, path in ((wa, pa), (wb, pb)):
    dlg = aw._LinkDialog(w)
    assert dlg.combo.count() >= 1 and any(p == os.path.normpath(spath) for p, _w in dlg.open_tabs), dlg.open_tabs
    dlg.combo.setCurrentIndex(dlg.combo.findData(os.path.normpath(spath)))
    assert "g:Width" in dlg.combos, list(dlg.combos)
    dlg.combos["g:Width"].setCurrentText("W")
    dlg.apply()
    assert w.doc.link_of("g:Width")["var"] == "W" and w.doc.cfg["names"] == ["Default", "Small", "Big"], w.doc.cfg
    assert w.doc.cfg["cells"]["Big"]["g:Width"] == "90.0"
assert sorted(os.path.basename(p) for p in sw.parts) == ["plateA.gpd", "plateB.gpd"], sw.parts
# config panel: the cell is driven (not editable) and the column header names the variable
wa.cfg_panel.refresh(); t = wa.cfg_panel.table
hdr = t.horizontalHeaderItem(1).text(); print("header:", hdr); assert "⇐ W" in hdr
row_big = wa.doc.cfg["names"].index("Big")
from PyQt6.QtCore import Qt
assert not (t.item(row_big, 1).flags() & Qt.ItemFlag.ItemIsEditable)
row_def = wa.doc.cfg["names"].index("Default"); assert t.item(row_def, 1).flags() & Qt.ItemFlag.ItemIsEditable

# a change in the sketch reaches the OPEN parts live
wa.doc.cfg_apply("Big"); wa.update_all()
assert close(float(wa.doc.values["Width"]), 90) and close(wa.doc.solid.volume, 20 * 20 * 90)
m = sw.doc.models[f["id"]]; m.params["W"]["vals"][1] = 120.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all()
QTest.qWait(700)
assert close(float(wa.doc.values["Width"]), 120) and close(wa.doc.solid.volume, 20 * 20 * 120), (wa.doc.values, wa.doc.solid.volume)
assert close(float(wb.doc.cfg["cells"]["Big"]["g:Width"]), 120)
# the sketch does not follow the part: changing a part global leaves the sketch alone
before = ak.dumps(sw.doc, [])
wa.doc.params["Width"] = "55"; wa.update_all(); assert ak.dumps(sw.doc, []) == before

wa.save(); wb.save()                                                    # links live in the part file: saving keeps them
# close plate B, change the sketch, "Update parts now" writes B's file; opening B later shows the new numbers
ib = sh.find_tab(pb); sh.tabs.removeTab(ib); wb.deleteLater()
sw.save()
m = sw.doc.models[f["id"]]; m.params["W"]["vals"][0] = 44.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.update_all(); QTest.qWait(500)
sw.push_now(write_closed=True); print(sw.vars_status.text())
assert pm.Document.from_json(open(pb).read()).cfg["cells"]["Small"]["g:Width"] == "44.0"
sw.save()
# a stale part file opened later pulls from the saved sketch on its own
m = sw.doc.models[f["id"]]; m.params["W"]["vals"][0] = 47.0; sk.solve_model(m); sw.doc.store_sketch(f["id"]); sw.save()
w2 = pm_app.MainWindow(pa); assert w2.doc.cfg["cells"]["Small"]["g:Width"] == "47.0", w2.doc.cfg["cells"]
# relative links on save, absolute again in memory; moving the pair of files keeps working
w2.save(); txt = open(pa).read(); assert '"src": "frame.gpk"' in txt, txt[-600:]
# reopen the sketch file in a window: parts and variables come back
sw2 = aw.AsmSketchWindow(spath, shell=sh); assert len(sw2.parts) == 2 and sw2.var_table.rowCount() == 1
# unlink
w2.cfg_panel.refresh(); w2.cfg_panel.table.setCurrentCell(0, 1); w2.cfg_panel.unlink_column(); assert not w2.doc.links
print("OK")
