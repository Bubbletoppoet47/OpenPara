"""The Configurations panel with nested configurations: order, tree, renames, sever, new variant.  python test_cfg_panel.py"""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, tempfile
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication(sys.argv)
import pm_app, pm_model as pm, cfg_tree, gsv, sk_tools as sk

w = pm_app.MainWindow()
w.doc = pm.Document(); d = w.doc
d.params = {"A": "1"}; d.cfg_add_col("g:A")
sk_ = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[sk_["id"]]
sk.add_rect_corner(m, (0, 0), (20, 20)); sk.solve_model(m); d.store_sketch(sk_["id"])
ex = d.add(pm.new_feature("extrude", sketch=sk_["id"], depth="10")); d.rebuild()
d.gsv_set("s.gpk", ["Small", "Big"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}, "Big": {"W": 2.0}}, ids=["a", "b"])
d.gsv_bind("g:A", "W"); d.cfg_add("Mine")
w.update_all(); p = w.cfg_panel; p.refresh()
assert p.order == ["Default · Small", "Default · Big", "Mine"], p.order            # groups first, regular below, children in the sketch's order
root = p.tree.topLevelItem(0)
assert root.childCount() == 2 and "Default" in root.child(0).text(0) and root.child(0).childCount() == 2, [root.child(i).text(0) for i in range(root.childCount())]
# rename the group from the table: the suffix is kept
t = p.table; t.item(0, 0).setText("Short pipe · Small"); assert p.order[:2] == ["Short pipe · Small", "Short pipe · Big"], p.order
# renaming the suffix is refused
msgs = []; w.say = lambda s_, *a, **k: msgs.append(s_)
p.refresh(); p.table.item(0, 0).setText("Short pipe · Huge"); assert any("assembly sketch configuration" in x for x in msgs), msgs
# a feature that no variant has -> prompt -> new variant, original unchanged
QInputDialog.getText = staticmethod(lambda *a, **k: ("No extrude", True))
p.refresh(); w.cfg_panel.set_value("Short pipe · Small", "s:" + ex["id"], True)
assert "Short pipe · No extrude · Small" in d.cfg["names"] and d.cfg["active"] == "Short pipe · No extrude · Small", (d.cfg["names"], d.cfg["active"])
assert not d.cfg["cells"]["Short pipe · Small"].get("s:" + ex["id"])
# the same state again switches to the existing variant (no prompt)
asked = []; QInputDialog.getText = staticmethod(lambda *a, **k: asked.append(1) or ("x", True))
d.cfg_apply("Short pipe · Big"); w.update_all()
w.toggle_suppress(ex["id"]); assert d.cfg["active"] == "Short pipe · No extrude · Big" and not asked, (d.cfg["active"], asked)
# sever
p.refresh(); p.sever("Short pipe · Big"); assert any("(unlinked)" in n for n in d.cfg["names"])
p.refresh(); assert p.order[-2:] == ["Mine", "Short pipe · Big (unlinked)"] or "Short pipe · Big (unlinked)" in p.order[-3:], p.order
print("config panel nested OK")
