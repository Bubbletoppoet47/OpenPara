"""Evaluate > Section Properties in the part window: the button, the window, the choice of plane / reference plane / clicked face, the offset, the units, the
report, the cut drawn in the view (and the part seen through), a part that is edited or a STEP body.   python test_part_section.py"""
import faulthandler; faulthandler.dump_traceback_later(400, exit=True)
import os
import tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
import numpy as np
from PyQt6.QtWidgets import QApplication, QPushButton
app = QApplication([])
from build123d import Box, Pos
import pm_app
import pm_model as pm
import sk_tools as sk
import unitctl
import viewpick
import exchange_dialog as xd


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


def close(a, b, rel=1e-6, absol=1e-7):
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), absol)


def block_part(depth="10"):
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    mm = d.models[s["id"]]
    sk.add_rect_corner(mm, (0, 0), (40, 20))
    sk.solve_model(mm)
    d.store_sketch(s["id"])
    e = d.add(pm.new_feature("extrude", sketch=s["id"], depth=depth))
    d.rebuild()
    return d, e


def window(doc):
    w = pm_app.MainWindow()
    w.doc = doc
    w.update_all(fit=True)
    return w


def pick_face(w, solid, which):
    """A click on the chosen face of the shown solid, through the real picking code (the surface hit is replaced by that face)."""
    w.draw()
    idx = next(i for i, f in enumerate(solid.faces()) if which(f))
    cid = int(np.where(np.array(w.view_cells.cell_data["face"]) == idx)[0][0])
    orig = viewpick.pick_surface
    viewpick.pick_surface = lambda pl, x, y, tolerance=0.0005: ((0, 0, 0), w.actor_part, cid)
    try:
        w.pick_model(10, 10)
    finally:
        viewpick.pick_surface = orig
    return idx


unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
d, ext = block_part()
w = window(d)
ok(abs(d.solid.volume - 40 * 20 * 10) < 1e-6, "the test part: a 40 x 20 x 10 block, from (0, 0, 0) to (40, 20, 10)")

# ---- the button
ok("section" in w.act, "the Evaluate tab has a Section Properties button")
tabs = [w.ribbon.tabText(i) for i in range(w.ribbon.count())]
ok("Evaluate" in tabs and "Mass\nProperties".replace("\n", " ") in w.act["mass"].text().replace("\n", " "), "next to Mass Properties")
ok(w.act["section"].text().replace("\n", " ") == "Section Properties", "its label is Section Properties")
n_closed = len(w.plotter.actors)
w.act["section"].click()
dlg = w.section_dialog
ok(dlg is not None and dlg.isVisible() and dlg.windowTitle() == "Section Properties", "pressing it opens the window")
items = [dlg.plane.itemText(i) for i in range(dlg.plane.count())]
ok(items[:3] == ["Front", "Top", "Right"] and items[-1] == "Clicked face", f"it offers Front, Top, Right and the clicked face ({items})")
ok(dlg.plane.currentText() == "Top" and "Top plane" in dlg.out.toPlainText(), "with nothing selected it starts on the Top plane")
ok("exactly in a face" in dlg.out.toPlainText(), "the Top plane at 0 is the block's bottom face: the report warns about it")

# ---- a plane with an offset
dlg.offset.setValue(5.0)
t = dlg.out.toPlainText()
ok("Top plane, offset 5 mm" in t and "Area = 800 square mm" in t and "exactly in a face" not in t, "Top plane, offset 5 mm: area 800, no warning")
p = dlg.result["props"]
ok(close(p["Ix"], 40 * 20 ** 3 / 12) and close(p["Iy"], 20 * 40 ** 3 / 12) and np.allclose(p["c"], (20, 10)), "Ix = b h^3 / 12 = 26666.7, Iy = 106666.7, centroid (20, 10)")
ok(close(p["Ix_o"], p["Ix"] + 800 * 100) and close(p["Iy_o"], p["Iy"] + 800 * 400), "about the origin axes: the parallel-axis theorem (Ix_o = 106666.7, Iy_o = 426666.7)")
ok("Ix  = 26666.667" in t and "Iy  = 106666.67" in t and "Ix  = 106666.67      Iy  = 426666.67" in t, "the report prints them")
dlg.plane.setCurrentIndex(dlg.plane.findText("Front"))
ok("Offset along model -Y" in dlg.offset_label.text(), "the offset is named by the plane's normal: Front is model -Y")
dlg.offset.setValue(-10.0)                                                         # y = +10
t = dlg.out.toPlainText()
p = dlg.result["props"]
ok(p["frame"]["names"] == ("+X", "+Z", "-Y") and close(p["area"], 400) and close(p["Ix"], 40 * 10 ** 3 / 12) and close(p["Iy"], 10 * 40 ** 3 / 12) and np.allclose(p["c"], (20, 5)), "Front plane at y = 10: a 40 x 10 rectangle, section X = model X, Y = model Z")
dlg.plane.setCurrentIndex(dlg.plane.findText("Right"))
dlg.offset.setValue(20.0)
p = dlg.result["props"]
ok(p["frame"]["names"] == ("+Y", "+Z", "+X") and close(p["area"], 20 * 10) and close(p["Ix"], 20 * 10 ** 3 / 12) and np.allclose(p["c"], (10, 5)), "Right plane at x = 20: 20 (model Y) x 10 (model Z)")
dlg.offset.setValue(500.0)
ok("does not cut the part" in dlg.out.toPlainText() and dlg.result is None, "a plane far outside the part: a plain message and nothing drawn")
dlg.offset.setValue(20.0)
ok(dlg.result is not None, "back inside: measured again")

# ---- the cut is drawn, the part is seen through it
n_open = len(w.plotter.actors)
ok(n_open >= n_closed + 4, f"the view has the cut's fill, outline, axes and centroid ({n_open - n_closed} more actors)")
ok(w.part_opacity() <= 0.35 + 1e-9, "the part is drawn see-through while the window is open")
dlg.hide()
ok(abs(w.part_opacity() - 1.0) < 1e-9 and len(w.plotter.actors) == n_closed, "hidden: the cut is gone from the view and the part is solid again")
w.act["section"].click()
dlg = w.section_dialog
ok(dlg.isVisible() and len([x for x in w.findChildren(type(dlg)) if x.isVisible()]) == 1, "pressing the button again leaves one window")

# ---- a reference plane
w.sel_plane = "Top"
w.command("refplane")
rf = w.doc.feature(w.sel)
rf["d"] = "7"
w.update_all()
w.pm_ok()
w.act["section"].click()
dlg = w.section_dialog
ok(rf["name"] in [dlg.plane.itemText(i) for i in range(dlg.plane.count())], f"a reference plane of the part is offered ({rf['name']})")
dlg.plane.setCurrentIndex(dlg.plane.findText(rf["name"]))
p = dlg.result["props"]
ok("reference plane" in dlg.out.toPlainText() and close(p["area"], 800) and np.allclose(p["c3"], (20, 10, 7)), "cut with it: the section at z = 7")

# ---- a clicked face
top_idx = pick_face(w, w.shown_solid(), lambda f: f.geom_type.name == "PLANE" and abs(f.center().Z - 10) < 1e-6)
ok(dlg.plane.currentText() == "Clicked face" and dlg.off_mm == 0.0, "clicking a flat face switches the window to that face, at distance 0")
t = dlg.out.toPlainText()
p = dlg.result["props"]
ok("the clicked face itself" in t and close(p["area"], 800) and np.allclose(p["c3"], (20, 10, 10)) and "exactly in a face" not in t, "the face itself is measured: 40 x 20 at z = 10, no warning")
ok(p["frame"]["names"][2] == "+Z", "its normal is the outward one, model +Z")
ok(dlg.offset_label.text() == "Distance into the part", "the offset now reads 'Distance into the part'")
dlg.offset.setValue(4.0)
p = dlg.result["props"]
ok("into the part from the clicked face" in dlg.out.toPlainText() and np.allclose(p["c3"], (20, 10, 6)) and close(p["area"], 800), "4 mm into the part from that face: the section at z = 6")
dlg.offset.setValue(0.0)
side = pick_face(w, w.shown_solid(), lambda f: f.geom_type.name == "PLANE" and abs(f.center().X - 40) < 1e-6)
p = dlg.result["props"]
ok(dlg.off_mm == 0.0 and close(p["area"], 20 * 10) and p["frame"]["names"][2] == "+X" and np.allclose(p["c3"], (40, 10, 5)), "another face (the end at x = 40): 20 x 10, normal model +X")
ok(close(p["Ix"], 20 * 10 ** 3 / 12) or close(p["Ix"], 10 * 20 ** 3 / 12), "its moments are those of a 20 x 10 rectangle")
# a curved face is refused, the last result stays
res = dlg.result
w.sel_face = {"ref": None, "index": 0}
w.section_face_clicked()
ok("curved" in dlg.hint.text() and dlg.result is res, "a curved face: a message in red, the last result is kept")
# a click on nothing changes nothing
orig = viewpick.pick_surface
viewpick.pick_surface = lambda pl, x, y, tolerance=0.0005: None
try:
    w.pick_model(10, 10)
finally:
    viewpick.pick_surface = orig
ok(dlg.result is res, "a click on empty space leaves the result alone")
# opening the window with a face already selected measures that face
dlg.close()
w.sel_face = {"ref": w.doc.face_ref(w.shown_solid().faces()[top_idx]), "index": top_idx}
w.section_open()
dlg = w.section_dialog
ok(dlg.plane.currentText() == "Clicked face" and np.allclose(dlg.result["props"]["c3"], (20, 10, 10)), "with a flat face already selected, the window opens on that face")

# ---- the part is edited while the window is open
dlg.plane.setCurrentIndex(dlg.plane.findText("Front"))
dlg.offset.setValue(-10.0)
ok(close(dlg.result["props"]["area"], 400), "Front plane at y = 10 of the 10 mm tall block: 400 mm^2")
ext2 = w.doc.feature(ext["id"])
ext2["depth"] = "20"
w.update_all()
w.draw()
ok(close(dlg.result["props"]["area"], 800) and dlg.solid is w.shown_solid(), "the extrude is made 20 mm: the window measures the new part (800 mm^2)")

# ---- units follow File > Units
dlg.plane.setCurrentIndex(dlg.plane.findText("Top"))
dlg.offset.setValue(5.0)
unitctl.set_units("US (in, lbf, psi)", notify=False, persist=False)
w.units_changed()
t = dlg.out.toPlainText()
ok("in^4" in t and f"Area = {800 / 25.4 ** 2:.8g} square in" in t and f"Ix  = {40 * 20 ** 3 / 12 / 25.4 ** 4:.8g}" in t, "in inches: the area and the moments are converted")
ok(abs(dlg.offset.value() - 5.0 / 25.4) < 1e-4 and dlg.offset.suffix().strip() == "in", "the offset box shows 0.1969 in (still 5 mm)")
dlg.offset.setValue(0.5)
ok(close(dlg.off_mm, 12.7) and "offset 0.5 in" in dlg.out.toPlainText(), "0.5 in typed: the cut is 12.7 mm up")
unitctl.set_units("Metric (mm, kg, N, s, MPa)", notify=False, persist=False)
w.units_changed()

# ---- copy
from PyQt6.QtGui import QGuiApplication
next(b for b in dlg.findChildren(QPushButton) if b.text() == "Copy to Clipboard").click()
ok(QGuiApplication.clipboard().text() == dlg.out.toPlainText() and "Section properties of" in dlg.out.toPlainText(), "Copy to Clipboard copies the report")

# ---- Measure was on: the window turns it off (a face click must reach Section Properties)
dlg.close()
w.measure_toggle()
ok(w.measuring, "(Measure is on)")
w.section_open()
ok(not w.measuring and w.section_dialog.isVisible(), "opening Section Properties turns Measure off")
w.section_dialog.close()

# ---- no solid yet
empty = pm_app.MainWindow()
empty.doc = pm.Document()
empty.update_all()
empty.section_open()
ok(empty.section_dialog is None and "solid" in empty.statusBar().currentMessage().lower(), "a part with no solid: 'Make a solid first', no window")

# ---- a STEP body measures like any other solid
beam = (Pos(0, 45, 0) * Box(100, 10, 200) + Pos(0, -45, 0) * Box(100, 10, 200) + Box(8, 80, 200))
wb = window(xd.import_doc("beam", beam, "beam.step"))
wb.section_open()
bd = wb.section_dialog
bd.plane.setCurrentIndex(bd.plane.findText("Top"))
bd.offset.setValue(40.0)
Ix = 100 * 100 ** 3 / 12 - 92 * 80 ** 3 / 12
ok(close(bd.result["props"]["Ix"], Ix) and close(bd.result["props"]["area"], 2640), f"an imported I-beam: Ix = {Ix:.0f} mm^4, A = 2640 mm^2 (textbook)")
pick_face(wb, wb.shown_solid(), lambda f: f.geom_type.name == "PLANE" and abs(f.center().Z - 100) < 1e-6)
ok(bd.plane.currentText() == "Clicked face" and close(bd.result["props"]["Ix"], Ix) and "exactly in a face" not in bd.out.toPlainText(), "clicking the beam's end face gives the same section")
bd.close()
ok(abs(wb.part_opacity() - 1.0) < 1e-9, "closed: solid again")

print("test_part_section OK")
