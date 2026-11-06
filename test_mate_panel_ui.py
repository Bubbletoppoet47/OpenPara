"""The Mate panel: nine icon buttons for the types (the picked one pressed), three pick toggles, picking a type switches the mate."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QPushButton, QRadioButton
app = QApplication([])
import pm_model as pm, sk_tools as sk, gpd_app, assembly
tmp = tempfile.mkdtemp()
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (10, 10)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
pb = os.path.join(tmp, "block.gpd"); open(pb, "w").write(d.to_json())
sh = gpd_app.AppShell([pb]); w = sh.new_assembly(); w.insert_files([pb])
w.mate_start(); w.show_mate_panel()
btns = {b.text().strip(): b for b in w.props.findChildren(QPushButton)}
for name in assembly.MATE_NAMES.values():
    assert name in btns and not btns[name].icon().isNull() and btns[name].isCheckable(), name
for name in ("Faces", "Edges", "Points"):
    assert name in btns and btns[name].isCheckable() and not btns[name].icon().isNull(), name
assert not w.props.findChildren(QRadioButton), "no radio buttons any more"
btns["Concentric"].setChecked(True); app.processEvents()
assert w.mate_type == "concentric"
btns = {b.text().strip(): b for b in w.props.findChildren(QPushButton)}
assert btns["Concentric"].isChecked() and not btns["Parallel"].isChecked()
btns["Edges"].setChecked(False); assert w.pick_filter["edge"] is False and w.pick_filter["face"] is True
print("PASS"); os._exit(0)
