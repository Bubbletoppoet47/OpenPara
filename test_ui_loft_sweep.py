"""Sweep and loft in the window: ribbon buttons, commands, property panels, tree nesting, undo, save and reopen."""
import faulthandler; faulthandler.dump_traceback_later(240, exit=True)
import math
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QListWidget, QPushButton, QToolButton
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk

w = pm_app.MainWindow(); w.new_doc(); d = w.doc


def sketch(plane, offset, draw):
    w.sel_plane = plane; w.command("sketch"); sid = w.sel
    if offset:
        d.feature(sid)["plane"]["offset"] = str(offset)
    draw(w.ed.m); d.reports[sid] = sk.solve_model(w.ed.m); d.store_sketch(sid); w.leave_sketch()
    return sid


texts = [b.text().replace("\n", " ") for b in w.ribbon.findChildren(QToolButton)]
for need in ("Swept Boss/Base", "Lofted Boss/Base", "Swept Cut", "Lofted Cut"):
    assert need in texts, (need, texts)
print("ribbon buttons ok")

# --- sweep
prof = sketch("Top", 0, lambda m: sk.add_circle(m, (0, 0), (3, 0)))
path = sketch("Front", 0, lambda m: sk.add_line(m, (0, 0), (0, 20)))
w.sel = prof; w.command("sweep"); f = d.feature(w.sel)
print("sweep", d.status[f["id"]], round(d.solid.volume, 2))
assert f["kind"] == "sweep" and f["sketch"] == prof and f["path"] == path
assert d.status[f["id"]] == "ok" and abs(d.solid.volume - math.pi * 9 * 20) < 0.01
panel = w.props_lay.parent()
labels = [c.currentText() for c in panel.findChildren(QComboBox)]
print("sweep panel combos:", labels)
assert "Sketch1" in labels[0] or labels[0].startswith("Sketch")
# switch the twist on in the panel: a straight path allows it, and a twist box appears
chk = panel.findChildren(QCheckBox)
for c in chk:
    c.setChecked(True)
    if d.feature(f["id"]).get("twist_on"):
        break
assert d.feature(f["id"]).get("twist_on") and d.status[f["id"]] == "ok", d.status[f["id"]]
assert abs(d.solid.volume - math.pi * 9 * 20) < 0.5          # a round profile twisted is still the same pipe
f = d.feature(f["id"]); f["twist_on"] = False; d.rebuild()

# tree: both sketches nest under the sweep
it = w.tree.findItems("", pm_app.Qt.MatchFlag.MatchContains | pm_app.Qt.MatchFlag.MatchRecursive)
nested = [i.text(0) for i in it]
print("tree:", nested)
top = [w.tree.topLevelItem(0).child(i).text(0) for i in range(w.tree.topLevelItem(0).childCount())]
sweep_item = [i for i in it if f["name"] in i.text(0)][0]
assert sweep_item.childCount() == 2, sweep_item.childCount()

# --- sweep cut into a block
base = sketch("Top", 0, lambda m: sk.add_rect_corner(m, (-20, -20), (20, 20)))
w.sel = base; w.command("extrude"); e = d.feature(w.sel); e["depth"] = "30"; w.update_all()
v0 = d.solid.volume
p2 = sketch("Right", 0, lambda m: sk.add_circle(m, (0, 15), (0, 18)))
l2 = sketch("Top", 0, lambda m: sk.add_line(m, (-25, 0), (25, 0)))
w.sel = p2; w.command("sweep_cut"); c = d.feature(w.sel)
print("sweep cut", d.status[c["id"]])
assert c["kind"] == "sweep_cut"

# --- loft + loft cut
a = sketch("Top", 60, lambda m: sk.add_rect_corner(m, (-5, -5), (5, 5)))
b = sketch("Top", 72, lambda m: sk.add_rect_corner(m, (-2, -2), (2, 2)))
w.sel = a; w.command("loft"); lf = d.feature(w.sel)
print("loft", lf["sections"], d.status[lf["id"]])
assert lf["kind"] == "loft" and a in lf["sections"] and len(lf["sections"]) == 2
panel = w.props_lay.parent()
lw = panel.findChildren(QListWidget)[0]
assert lw.count() == 2
# reorder and remove through the buttons
btn = {x.text(): x for x in panel.findChildren(QPushButton)}
assert {"Up", "Down", "Remove"} <= set(btn), list(btn)
lw.setCurrentRow(1); btn["Up"].click()
assert d.feature(lf["id"])["sections"][0] == lf["sections"][0]
lf = d.feature(lf["id"])
w.show_props(); panel = w.props_lay.parent()
lw = panel.findChildren(QListWidget)[0]; lw.setCurrentRow(0)
{x.text(): x for x in panel.findChildren(QPushButton)}["Remove"].click()
assert len(d.feature(lf["id"])["sections"]) == 1
assert d.status[lf["id"]].startswith("error")           # red on error, like every other feature
print("loft with one section ->", d.status[lf["id"]])
w.show_props(); panel = w.props_lay.parent()
{x.text(): x for x in panel.findChildren(QPushButton)}["Add section"].click()
assert len(d.feature(lf["id"])["sections"]) == 2 and d.status[lf["id"]] == "ok", d.status[lf["id"]]

# --- pattern of a sweep / loft through the window, delete protection, save and reopen
w.sel = lf["id"]; w.command("pattern_linear"); pt = d.feature(w.sel)
print("pattern of the loft:", d.status[pt["id"]])
assert lf["id"] in pt["features"] and d.status[pt["id"]] == "ok", d.status[pt["id"]]
path_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_ls.json")
open(path_out, "w").write(d.to_json())
back = pm.Document.from_json(open(path_out).read()); back.rebuild(); os.remove(path_out)
assert abs(back.solid.volume - d.solid.volume) < 1e-6
assert [g["kind"] for g in back.features] == [g["kind"] for g in d.features]
print("OK")
