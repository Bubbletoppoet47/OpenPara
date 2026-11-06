"""Core runs without the optional add-ons (Part Generator, Simulation, Renderer, Truss) and keeps their data; with them it works as before."""
import os as _o, sys as _s
_s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "addons_src", "partgen"))
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import addons, ext
addons.startup()                                         # the add-ons that sit in the program folder are put in place
addons.register_extensions(ext)
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import pm_model as pm
import pm_app, assembly


def tabs(w):
    return [w.ribbon.tabText(i) for i in range(w.ribbon.count())]


def build_doc():
    d = pm.Document()
    sk = d.add(pm.new_feature("sketch", plane="Top"))
    pg = d.add(pm.new_feature("partgen", gen="Spur gear", params={}, place={"plane": "Top"}))
    return d, sk, pg


# ---- with every add-on there
import partgen
kind = next(iter(partgen.PART_TYPES))
assert ext.present("partgen") and ext.feature("partgen") is not None
w = pm_app.MainWindow()
assert "Part Features" in tabs(w) and "Visualize" in tabs(w), tabs(w)
d = pm.Document()
f = d.add(pm.new_feature("partgen", gen=kind, params={}, place={"plane": "Top"}))
d.rebuild()
print("with add-on:", f.get("name"), d.status.get(f["id"]), d.solid is not None)
assert d.solid is not None and not str(d.status.get(f["id"])).startswith("error"), d.status
saved = d.to_json()

# ---- every optional add-on removed
for aid in ("partgen", "truss", "simulation", "render"):
    addons.uninstall(aid)
addons.register_extensions(ext)
assert not ext.present("partgen") and not ext.present("simulation") and not ext.present("render") and ext.feature("partgen") is None
w2 = pm_app.MainWindow()
t = tabs(w2)
assert "Simulation" not in t and "Visualize" not in t and "Part Features" in t, t
a2 = assembly.AssemblyWindow()
t = tabs(a2)
assert "Simulation" not in t and "Visualize" not in t, t
d2 = pm.Document.from_json(saved)
d2.rebuild()
fid = next(x["id"] for x in d2.features if x["kind"] == "partgen")
assert str(d2.status[fid]).startswith("error") and "Part Generator" in d2.status[fid], d2.status
import json
again = json.loads(d2.to_json())
assert [x for x in again["features"] if x["kind"] == "partgen"] == [x for x in json.loads(saved)["features"] if x["kind"] == "partgen"], "the generated part's data must survive"
# the property panel and the button answer instead of crashing
from PyQt6.QtWidgets import QFormLayout, QMessageBox
asked = []
ext.installer = lambda aid, parent: asked.append(aid)
w2.doc = d2
form = QFormLayout()
w2.partgen_panel(form, d2.feature(fid))
w2.partgen_dialog(None)
assert asked == ["partgen"], asked
w2.update_all()
print("OK addon_ext: core runs without add-ons and keeps their data")
