"""Flipping File > Units never changes what is stored (files keep mm); it only changes what is shown and how typed numbers are read."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest
app = QApplication([])
import unitctl, pm_model as pm, sk_tools as sk, gpd_app, pm_app, asm_model as am
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
tmp = tempfile.mkdtemp()
MM, IN = "Metric (mm, kg, N, s, MPa)", "US (in, lbf, psi)"
unitctl.set_units(MM, notify=False, persist=False)

d = pm.Document(); d.params = {"Width": "50.8", "Gap": "25.4", "N": "3", "Ang": "30"}; d.param_kinds = {"N": "number", "Ang": "angle"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (50.8, 25.4)); sk.solve_model(m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="Gap")); d.rebuild()
d.cfg_add_col("g:Width"); d.cfg_add_col("g:N"); d.cfg_add("Wide"); d.cfg_set_cell("Wide", "g:Width", "101.6"); d.cfg_set_cell("Wide", "g:N", "5")
pa = os.path.join(tmp, "p.gpd"); open(pa, "w").write(d.to_json())
A = am.Assembly(); A.add_component("p.gpd", fixed=True); A.add_component("p.gpd", pos=(60.0, 5.0, 25.4)); A.params = {"Clear": "12.7"}
pasm = os.path.join(tmp, "a.gpa"); open(pasm, "w").write(A.to_json())

sh = gpd_app.AppShell([pa, pasm]); QTest.qWait(30)
wp, wa = sh.tabs.widget(sh.find_tab(pa)), sh.tabs.widget(sh.find_tab(pasm))

def stored():
    return {"part": wp.doc.to_json(), "asm": wa.asm.to_json()}

def shown():
    wp.refresh_globals(); wp.cfg_panel.refresh(); wa.update_all()
    g = wp.gtab; c = wp.cfg_panel.table; ag = wa.gtab
    return {"part_width": g.item(0, 1).text(), "part_value": g.item(0, 2).text(), "part_N": g.item(2, 1).text(), "part_Ang": g.item(3, 1).text(),
            "cfg_wide": c.item(wp.doc.cfg["names"].index("Wide"), 1).text(), "cfg_N": c.item(wp.doc.cfg["names"].index("Wide"), 2).text(),
            "asm_clear": ag.item(0, 1).text(), "hdr": g.horizontalHeaderItem(1).text()}

before_store, before_show = stored(), shown()
print(before_show)
assert before_show["part_width"] == "50.8"
unitctl.set_units(IN, notify=True, persist=False); QTest.qWait(30)
after_show = shown()
print(after_show)
assert stored() == before_store, "flipping the units changed what is stored"
assert after_show["part_width"] == "2" and close(float(after_show["part_value"]), 2) and after_show["cfg_wide"] == "4" and after_show["asm_clear"] == "0.5", after_show
assert after_show["part_N"] == "3" and after_show["part_Ang"] == "30" and after_show["cfg_N"] == "5", after_show        # numbers and angles never convert
assert "(in)" in after_show["hdr"], after_show
# typing in inches stores mm
wp.gtab.item(0, 1).setText("3"); QTest.qWait(10)
assert wp.doc.params["Width"] in ("76.2", "76.2000000", "76.19999999999999") or close(float(wp.doc.params["Width"]), 76.2), wp.doc.params
# and back: the same stored numbers show as before
unitctl.set_units(MM, notify=True, persist=False); QTest.qWait(30)
assert shown()["part_width"] == "76.2"
print("OK")
