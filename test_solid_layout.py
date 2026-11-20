"""3D FEA window: numbered sections like 2D FEA, material list, global units in inputs and results, grey mesh before Solve, click probe;
and the shared results formatter (sim_report)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk
import sim_report as R, solid_tab, unitctl, units

# --- the formatter
assert R.num(1234.5678) == "1234.6" and R.num(0.000012345) == "1.2345e-5" and R.num(None) == "n/a" and R.num(0) == "0"
h = R.summary(2.5, None, [("Largest displacement", "0.01", "mm")])
assert "Summary" in h and "n/a" in h and "mm" in h
assert "Converged" in R.refine_block([{"pass": 1, "n": 10, "umax": 1.0, "vmax": 2.0, "change": None}, {"pass": 2, "n": 20, "umax": 1.01, "vmax": 2.0, "change": 0.01}],
                                      "stopped", True, "mm", "MPa")
assert "CHECK" in R.solver_block("direct", 1e-3, False, "x")

# --- a bar and its 3D window
T = tempfile.mkdtemp(prefix="opara_sl_")
d = pm.Document(); d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bar_l")) and w.import_file(part)

# sections 1..6, in the order of 1D FEA (Probe is part of Results), with the Solve button before the results
nums = [s_.number for s_ in w.sections]
assert nums == sorted(nums) == [1, 2, 3, 4, 5, 6], nums
titles = [s_.title for s_ in w.sections]
assert titles == ["Geometry", "Material and analysis", "Supports", "Loads", "Mesh", "Results"], titles

# material list
assert w.mat_combo.count() > 2 and w.mat_combo.itemData(0) is None
names = [w.mat_combo.itemData(i) for i in range(w.mat_combo.count())]
alu = next(n for n in names if n and "alumin" in n.lower())
w.mat_combo.setCurrentIndex(names.index(alu)); w.material_picked()
assert 60000 < w.setup["material"]["E"] < 80000, w.setup["material"]

def face(n):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)
w.select_faces([face([-1, 0, 0])]); w.add_support("fixed")
w.select_faces([face([1, 0, 0])]); w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.set_size("6"); w.inputs_changed()
assert w.run_mesh()
if w.view.plotter is not None:
    assert w.view.mesh_actor is not None and w.view.result_actor is None, "meshed only: plain grey surface, no result colours"
assert w.run_solve()
t = w.res_lbl.text()
for word in ("Summary", "Largest von Mises stress", "Largest displacement", "Mesh", "Solver check", "OK"):
    assert word in t, word
assert "MPa" in t and "mm" in t

# global units: US customary; the labels, fields and results follow
n0 = w.result["vm_max"]
unitctl.set_units("in-lb-psi" if units.valid("in-lb-psi") else next(n for n in units.SYSTEMS if units.get(n)["L"] == "in"), persist=False)
L = units.get(unitctl.system())["L"]
assert L == "in" and "(in" in w.h_label.text() and units.get(unitctl.system())["S"] in w.mat_labels["E"].text()
assert units.get(unitctl.system())["S"] in w.res_lbl.text() and "in" in w.res_lbl.text()
w.read_inputs(); assert abs(w.setup["h"] - 6) < 1e-6, "typed values keep their meaning across a unit change"
w.e_probe.setText(f"{100 / 25.4}, {5 / 25.4}, {5 / 25.4}")
i, dist, un, vm = w.probe_node()
assert dist < 6 and "Probe" in w.probe_lbl.text() and "Displacement" in w.probe_lbl.text() and "Stress" in w.probe_lbl.text()
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)

# click probe
p = w.result["nodes"][i] + w.scale_value() * w.result["u"][i]          # a click lands on the deformed shape that is on screen
assert w.scale_value() > 0, "the deformation scale starts at auto"
assert w.probe_at(tuple(p)) is not None and w.last_probe["i"] == i
# the side panel has no maximum width (drag the divider), and loads / supports are full-width icon buttons like 2D FEA
assert w.panel.maximumWidth() >= 16000 and w.panel.minimumWidth() <= 400
from PyQt6.QtWidgets import QPushButton
texts = [b_.text().strip() for b_ in w.findChildren(QPushButton)]
for want in ("Force on face(s)...", "Pressure on face(s)...", "Force at vertex...", "Gravity...", "Fixed", "One direction (normal)", "Bearing (hole face)"):
    assert want in texts, want
assert "Bolt / pin hole" not in texts, "screws and bolts are gone from the 3D FEA"

# ---- the Results block is laid out like the one of 1D FEA: result box (displacement magnitude first), Colours, deformed shape, scale, Animate; Probe is inside it
from PyQt6.QtWidgets import QCheckBox
res_sec = next(x for x in w.sections if x.title == "Results")
assert not any(x.title == "Probe" for x in w.sections)
for wid in (w.cb_field, w.cmap_combo, w.cb_def, w.e_scale, w.cb_edges, w.cb_anim, w.b_probe, w.e_probe, w.probe_lbl, w.res_lbl):
    assert res_sec.isAncestorOf(wid), wid
assert [w.cb_field.itemData(i) for i in range(w.cb_field.count())] == ["umag", "ux", "uy", "uz", "vm", "fos"] and w.cb_field.currentData() == "umag"
assert w.cb_field.itemText(0).startswith("Displacement magnitude (") and "MPa" in w.cb_field.itemText(4)
assert w.e_scale.text() == "" and w.e_scale.placeholderText() == "auto" and w.cb_def.isChecked() and not w.cb_edges.isChecked()
assert not w.anim_box.isVisibleTo(w) and w.cb_anim.text() == "Animate"
w.cb_anim.setChecked(True); assert w.anim_box.isVisibleTo(w)
assert [w.loop_combo.itemText(i) for i in range(3)] == ["Once", "Loop", "Back and forth"] and w.e_frames.text() == "30" and w.e_dur.text() == "3"
assert w.cmap_combo.currentText() in __import__("result_style").CMAPS

# the colour legend: always the range of the full result; an animation scales the values but not the legend
r = w.result
vals, leg = w.field_values()
assert np.allclose(vals, r["un"]) and leg["lo"] == float(r["un"].min()) and leg["hi"] == float(r["un"].max()) and leg["title"].startswith("Displacement magnitude  [mm]")
half, leg2 = w.field_values(0.5)
assert np.allclose(half, 0.5 * r["un"]) and leg2["lo"] == leg["lo"] and leg2["hi"] == leg["hi"] and leg2["labels"] == leg["labels"]
w.cb_field.setCurrentIndex(w.cb_field.findData("uz"))
vz, legz = w.field_values()
assert np.allclose(vz, r["u"][:, 2]) and "Displacement Z" in legz["title"]
w.cb_field.setCurrentIndex(w.cb_field.findData("vm"))
vv, legv = w.field_values()
assert legv["title"].startswith("von Mises stress  [MPa]") and np.isclose(legv["hi"], r["vm_node"].max()) and len(legv["labels"]) == 3
w.cb_field.setCurrentIndex(w.cb_field.findData("fos"))
vf, legf = w.field_values()
assert legf["flip"] and (legf["lo"], legf["hi"]) == (0.5, 3.0) and np.allclose(vf, w.result["material"]["sy"] / np.maximum(r["vm_node"], 1e-12))
vf0, _ = w.field_values(0.0)
assert (vf0 > 1e6).all() or vf0.max() <= 100, "no load: a very high safety factor (clipped)"
w.cb_field.setCurrentIndex(0)

# the deformation scale: blank / auto = about a tenth of the part; a typed number is used as typed; the deformed shape box turns it off
auto = w.scale_value()
assert abs(auto * r["umax"] - 0.1 * w.geom["diag"]) < 1e-9
w.e_scale.setText("auto"); assert w.scale_value() == auto
w.e_scale.setText("25"); assert w.scale_value() == 25.0
w.e_scale.setText("0"); assert w.scale_value() == 0.0
w.e_scale.setText(""); w.cb_def.setChecked(False); assert w.scale_value() == 0.0
w.cb_def.setChecked(True); assert w.scale_value() == auto

# the picture (when the 3D view is there): the legend, the axes triad, a ramp that moves the points and the colours
if w.view.plotter is not None:
    assert w.view.axes_on, "the X / Y / Z triad is in the view"
    assert w.view.legend_spec is not None and w.view.legend_spec["title"].startswith("Displacement magnitude")
    pts1 = np.array(w.view.res["ds"].points)
    w.apply_ramp(0.5)
    pts_half = np.array(w.view.res["ds"].points)
    w.apply_ramp(1.0)
    assert np.allclose(np.array(w.view.res["ds"].points), pts1) and not np.allclose(pts_half, pts1)
    w.view.res["ds"]                                                           # the same surface is reused: no rebuild per frame
    w.cb_field.setCurrentIndex(w.cb_field.findData("vm")); assert w.view.legend_spec["title"].startswith("von Mises stress")
    w.cb_field.setCurrentIndex(0)
    w.view.set_legend(None); assert w.view.legend is None
    w.show_field(); assert w.view.legend_spec is not None

# the animation: Play ramps 0 -> 1 (Once stops at the end), Stop shows the full result
w.e_frames.setText("4"); w.e_dur.setText("0.1"); w.loop_combo.setCurrentIndex(0)
seen = []
w.apply_ramp = lambda ramp, f=w.apply_ramp: (seen.append(round(ramp, 4)), f(ramp))
w.anim_play()
assert w.anim_timer.isActive() and seen == [0.0]
for _ in range(4):
    w.anim_step()
assert not w.anim_timer.isActive() and seen[-1] == 1.0 and [round(x, 2) for x in seen[:4]] == [0.0, 0.33, 0.67, 1.0], seen
w.loop_combo.setCurrentIndex(2); seen.clear(); w.anim_play()
for _ in range(6):
    w.anim_step()
assert w.anim_timer.isActive() and seen[:7] == [0.0, 0.3333, 0.6667, 1.0, 0.6667, 0.3333, 0.0], seen
w.anim_stop(); assert not w.anim_timer.isActive() and seen[-1] == 1.0
w.invalidate(); assert not w.anim_timer.isActive() and "Solve" in w.res_lbl.text() and not w.b_play.isEnabled() and not w.b_anim.isEnabled(), "an edit stops the animation and asks for a new solve"
assert w.run_solve() and w.b_play.isEnabled() and w.b_anim.isEnabled()

# the export: the same formats as 1D FEA, with the frames from the Frames box and Playback (back and forth = forward then back without the end twice)
import anim_export as ax
from PIL import Image
OUTD = tempfile.mkdtemp(prefix="opara_sl_out_")
w.e_frames.setText("5"); w.loop_combo.setCurrentIndex(1)
g = w.export_animation(path_fmt=(os.path.join(OUTD, "a.gif"), "gif"))
assert g and Image.open(g).n_frames == 5 and Image.open(g).info.get("loop") == 0
w.loop_combo.setCurrentIndex(2)
g = w.export_animation(path_fmt=(os.path.join(OUTD, "b.gif"), "gif"))
assert g and Image.open(g).n_frames == 8, "back and forth: 5 + 3"
pw = w.export_animation(path_fmt=(os.path.join(OUTD, "c.webp"), "webp"))
assert pw and Image.open(pw).n_frames == 8 and Image.open(pw).convert("RGBA").getpixel((2, 2))[3] == 0, "a transparent background"
pf = w.export_animation(path_fmt=(os.path.join(OUTD, "d_png"), "png"))
assert pf and len(os.listdir(pf)) == 8
first, last = Image.open(os.path.join(pf, sorted(os.listdir(pf))[0])), Image.open(os.path.join(pf, sorted(os.listdir(pf))[4]))
import numpy as _np
assert _np.abs(_np.asarray(first.convert("RGB"), int) - _np.asarray(last.convert("RGB"), int)).mean() > 0.5, "the frames differ: the ramp reaches the picture"
if w.view.plotter is not None:
    assert w.export_animation(path_fmt=(os.path.join(OUTD, "e.mp4"), "mp4")) is not None or not ax.mp4_available()
assert w.export_animation(path_fmt=os.path.join(OUTD, "old.gif"), frames=3) and Image.open(os.path.join(OUTD, "old.gif")).n_frames in (3, 4)
w.invalidate(); assert w.export_animation(path_fmt=(os.path.join(OUTD, "none.gif"), "gif")) is None
print("OK solid layout")
