"""Gear systems tab: the real program window, live read-outs, and 'Open the parts' makes separate unsaved part documents."""
import faulthandler; faulthandler.dump_traceback_later(600, exit=True)
import math
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import gears, gearsys, partgen, partgen_dialog, pm_app, gpd_app


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


def setf(field, text):
    field.w.setText(text)
    field.w.textEdited.emit(text)


def setc(field, data):
    field.w.setCurrentIndex(field.w.findData(data))


sh = gpd_app.AppShell([])
n0 = sh.tabs.count()
base = sh.new_part()
dlg = partgen_dialog.PartGenDialog(base.doc, None, base)
pg = dlg.systems
ok(dlg.tabs.count() == 2 and dlg.tabs.tabText(1) == "Gear systems", "the dialog has a Gear systems tab")
ok(pg.shell() is sh, "the page finds the program window")

# ---- train: two gears by centre distance
setf(pg.t["val2"], "60.5")
r = pg.result
ok(r is not None and abs(r["C"][0] - 60.5) < 1e-9 and r["gears"][1]["teeth"] == 40, f"read-out solved: C {r['C'][0]:.4f}, z2 {r['gears'][1]['teeth']}")
html = pg.view.toPlainText()
ok("60.5000" in html and "Turn (deg)" in html and "profile shift" in html, "read-out shows centre distance, turn angles and the shift note")
ok(pg.b3.isHidden(), "gear 3 box hidden for 2 gears")
setc(pg.t["count"], "3")
setf(pg.t["val2"], "40")
setf(pg.t["val3"], "100")
setc(pg.t["how3"], "span")
setf(pg.t["bend"], "90")
r = pg.result
ok(len(r["gears"]) == 3 and abs(sum(r["C"]) - 100) < 1e-9, f"3 gears by total span: C {r['C'][0]:.3f} + {r['C'][1]:.3f}")
setf(pg.t["val2"], "xyz")
ok("not a number" in pg.view.toPlainText() and not pg.btn_open.isEnabled(), "a bad number is reported and the button is off")
setf(pg.t["val2"], "40")

# ---- open the parts
setf(pg.t["helix"], "20")
before = sh.tabs.count()
pg.open_parts()
ok(dlg.systems_done, "dialog marks the systems as done")
ok(sh.tabs.count() == before + 3, f"three part documents opened ({sh.tabs.count() - before})")
tabs = [sh.tabs.widget(i) for i in range(before, sh.tabs.count())]
names = [sh.tabs.tabText(i) for i in range(before, sh.tabs.count())]
ok(all(n.startswith("Gear") for n in names), f"tab names {names}")
feats = [[f for f in w.doc.features if f["kind"] == "partgen"] for w in tabs]
ok(all(len(f) == 1 for f in feats), "each part has exactly one Part Generator feature")
ok([f[0]["gen"] for f in feats] == ["Helical gear"] * 3, "helical gears")
hands = [f[0]["params"]["hand"] for f in feats]
ok(hands == ["right", "left", "right"], f"hands alternate {hands}")
ok(all(w.doc.solid is not None and w.doc.solid.is_valid for w in tabs), "each part built a valid solid")
ok(all(w.is_dirty() for w in tabs), "the new parts are not saved (marked as changed)")
ok(all(not getattr(w, "path", None) for w in tabs), "no files written")
# the part reopens in the generator with the same numbers, independent of the others
f0 = feats[1][0]
dlg2 = partgen_dialog.PartGenDialog(tabs[1].doc, f0, tabs[1])
dlg2.refresh()
ok(dlg2.solid is not None and dlg2.tabs.tabBar().isHidden(), "reopened for editing, no systems tab")
ok(abs(dlg2.solid.volume - tabs[1].doc.solid.volume) < 1e-6, "reopened part gives the same solid")
dlg2.done(0)
ok(sh.tabs.count() == before + 3, "tab count unchanged by editing")

# ---- planetary
base2 = sh.new_part()
dlg = partgen_dialog.PartGenDialog(base2.doc, None, base2)
pg = dlg.systems
pg.system.setCurrentIndex(1)
pg.stack.setCurrentIndex(1)
pg.changed()
r = pg.result
ok(r["system"] == "planetary" and r["zr"] == 42, "planetary read-out: ring 42")
setc(pg.p["given"], "sun+ring")
setf(pg.p["zs"], "18")
setf(pg.p["zr"], "48")
ok(pg.result["zp"] == 15 and pg.p["zp"].w.text() == "15", "sun + ring: planet teeth worked out and shown (15)")
setf(pg.p["n"], "5")
ok(not pg.result["n_ok"] and "do not work" in pg.view.toPlainText(), "5 planets rejected with a note")
setf(pg.p["n"], "3")
ok(pg.result["n_ok"], "3 planets fine")
before = sh.tabs.count()
pg.open_parts()
ok(sh.tabs.count() == before + 3, "planetary: exactly three part documents (sun, planet, ring)")
names = [sh.tabs.tabText(i) for i in range(before, sh.tabs.count())]
ok([n.split()[0] for n in names] == ["Sun", "Planet", "Ring"], f"tab names {names}")
ring = sh.tabs.widget(before + 2)
ok(ring.doc.solid is not None and ring.doc.solid.is_valid and [f for f in ring.doc.features if f["kind"] == "partgen"][0]["gen"] == "Ring gear", "ring part is a valid Ring gear")
# the opened documents mesh (text round trip of the numbers loses nothing)
from build123d import Location
sun_d, pla_d, rin_d = (sh.tabs.widget(before + i).doc.solid for i in range(3))
rr = pg.result
worst = 0.0
for i in range(3):
    phi = math.radians(120 * i)
    P = pla_d.moved(Location((rr["C"] * math.cos(phi), rr["C"] * math.sin(phi), 0), (0, 0, 1), rr["planet_turn"][i]))
    for other in (sun_d, rin_d):
        v = P & other
        worst = max(worst, 0 if v is None else v.volume)
ok(worst < 0.5, f"parts as opened in the documents mesh: largest overlap {worst:.4f} mm3")
# preview builds
dlg = partgen_dialog.PartGenDialog(base2.doc, None, base2)
dlg.systems.preview()
ok(dlg.systems.plotter is None or len(dlg.systems.plotter.renderer.actors) > 4, "layout preview draws")
dlg.done(0)
print("\nALL OK")
os._exit(0)
