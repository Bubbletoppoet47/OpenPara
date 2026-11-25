"""Thermal expansion data of the materials: the coefficient alpha (per kelvin) and the reference temperature (the temperature at which the material is free of
thermal stress).  The library of the simulations (physics_materials / materials.json), the library of the parts (mat_lib), the Add a material dialog, the 2D and the
3D structural material panels.  An old file (written before these existed) still loads: the built-in materials get their typical value, the materials of the user
none; nothing is stored for a material that has no alpha."""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication([])
import numpy as np
import physics_materials as pm
import mat_lib
import sim_matdlg
import pm_model as pmod, sk_tools as sk
import physics_tab, solid_tab
import physics_fea as pf

warn = []
QMessageBox.warning = staticmethod(lambda *a, **k: warn.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)

# ---------------------------------------------------------------------------------------------------------------- the library of the simulations
lib = pm.load()
by = {m["name"]: m for m in lib}
assert len(lib) == len(pm.DEFAULTS) and all(m.get("alpha") is not None and m["Tref_K"] == 293.15 for m in lib), "every built-in material has a typical alpha"
assert abs(by["Structural steel (A36)"]["alpha"] - 11.7e-6) < 1e-12 and abs(by["Aluminium 6061-T6"]["alpha"] - 23.6e-6) < 1e-12
assert abs(by["Stainless steel 304"]["alpha"] - 17.3e-6) < 1e-12 and abs(by["Titanium Ti-6Al-4V"]["alpha"] - 8.6e-6) < 1e-12
assert all(3e-6 < m["alpha"] < 4e-5 for m in lib), "metals expand by 5e-6 .. 3e-5 per kelvin"
print("ok   the built-in materials carry typical expansion coefficients")

# a file from before: no alpha anywhere (a built-in name, and a material of the user)
old = {"materials": [{"name": "Aluminium 6061-T6", "E_MPa": 68900, "nu": 0.33, "Sy_MPa": 276, "Su_MPa": 310},
                     {"name": "My foam", "E_MPa": 12.0, "nu": 0.1, "Sy_MPa": 0.5, "Su_MPa": 0.6}]}
with open(pm.library_path(), "w", encoding="utf-8") as fh:
    json.dump(old, fh)
lib = pm.load()
assert [m["name"] for m in lib] == ["Aluminium 6061-T6", "My foam"]
assert abs(lib[0]["alpha"] - 23.6e-6) < 1e-12 and lib[0]["Tref_K"] == 293.15, "a built-in name gets its typical alpha from an old file"
assert "alpha" not in lib[1] and "Tref_K" not in lib[1], "a material of the user with none keeps none"
pm.save(lib)
raw = json.load(open(pm.library_path()))["materials"]
assert "alpha" in raw[0] and "alpha" not in raw[1], "nothing is written for a material that has none"
lib2 = pm.load()
assert lib2 == lib, "round trip"
mine = lib + [{"name": "Hot alloy", "E_MPa": 1.0e5, "nu": 0.3, "Sy_MPa": 100.0, "Su_MPa": 200.0, "alpha": 2.0e-5, "Tref_K": 300.0}]
pm.save(mine)
h = next(m for m in pm.load() if m["name"] == "Hot alloy")
assert h["alpha"] == 2.0e-5 and h["Tref_K"] == 300.0, "alpha and the reference temperature are kept"
os.remove(pm.library_path())
print("ok   an old materials.json still loads; alpha and the reference temperature are saved and read back; none is written for a material without")

# ---------------------------------------------------------------------------------------------------------------- the library of the parts
assert mat_lib.find("Aluminum 6061")["alpha"] == 23.6e-6 and mat_lib.find("Water").get("alpha") is None and mat_lib.find("Wood (pine)").get("alpha") is None
assert mat_lib.expansion({"name": "Copper"}) == (16.5e-6, 293.15), "by the name"
assert mat_lib.expansion({"name": "Whatever", "alpha": 1e-5}) == (1e-5, 293.15), "its own value"
assert mat_lib.expansion({"name": "Copper", "alpha": 1e-5, "Tref_K": 300.0}) == (1e-5, 300.0), "its own value wins over the library"
assert mat_lib.expansion({"name": "Water", "density": 1000}) is None and mat_lib.expansion(None) is None and mat_lib.expansion({"name": "Nobody"}) is None
assert mat_lib.material_dict(mat_lib.find("Brass"))["alpha"] == 20.0e-6
mat_lib.save_user([{"name": "Mine", "density": 1000.0, "E_MPa": 1.0, "nu": 0.3, "Sy_MPa": 1.0, "Su_MPa": 2.0, "alpha": 3e-5, "Tref_K": 280.0},
                   {"name": "Plain", "density": 900.0, "E_MPa": 2.0, "nu": 0.3, "Sy_MPa": 1.0, "Su_MPa": 2.0}])
um = {m["name"]: m for m in mat_lib.user_materials()}
assert um["Mine"]["alpha"] == 3e-5 and um["Mine"]["Tref_K"] == 280.0 and "alpha" not in um["Plain"], um
assert mat_lib.expansion(mat_lib.find("Mine")) == (3e-5, 280.0)
print("ok   the part materials carry alpha (library, own, none), and a user's material keeps its own")

# ---------------------------------------------------------------------------------------------------------------- the Add a material dialog
orig_exec = QDialog.exec
FILL = {}
def fake_exec(self):
    f = self.fields
    f["name"].setText(FILL.get("name", "Dlg alloy")); f["E"].setText("70000"); f["nu"].setText("0.33"); f["sy"].setText("200"); f["su"].setText("300")
    f["unit"].setCurrentText("MPa"); f["alpha"].setText(FILL.get("alpha", "")); f["tref"].setText(FILL.get("tref", ""))
    return QDialog.DialogCode.Accepted.value
QDialog.exec = fake_exec
pm.save([m for m in pm.load()])


class Parent:
    pass


from PyQt6.QtWidgets import QWidget
par = QWidget()
FILL.update(name="A1", alpha="2.3e-5", tref="25")
assert sim_matdlg.add_material(par, pm.load(), "MPa", {}) == "A1"
a1 = next(m for m in pm.load() if m["name"] == "A1")
assert a1["alpha"] == 2.3e-5 and abs(a1["Tref_K"] - 298.15) < 1e-9, a1
FILL.update(name="A2", alpha="", tref="")
assert sim_matdlg.add_material(par, pm.load(), "MPa", {}) == "A2"
a2 = next(m for m in pm.load() if m["name"] == "A2")
assert "alpha" not in a2 and "Tref_K" not in a2, a2
FILL.update(name="A3", alpha="2.3e-5", tref="")
assert sim_matdlg.add_material(par, pm.load(), "MPa", {}) == "A3"
assert abs(next(m for m in pm.load() if m["name"] == "A3")["Tref_K"] - 293.15) < 1e-9, "no reference temperature typed: 20 degC"
for bad_alpha, word in (("abc", "numbers"), ("5", "per kelvin"), ("0", "per kelvin")):
    FILL.update(name="A4", alpha=bad_alpha, tref="")
    n = len(pm.load())
    assert sim_matdlg.add_material(par, pm.load(), "MPa", {}) is None and word in warn[-1] and len(pm.load()) == n, (bad_alpha, warn[-1])
QDialog.exec = orig_exec
print("ok   the Add a material dialog stores alpha and the reference temperature (degC typed, kelvin kept), accepts none, refuses nonsense in words")
os.remove(pm.library_path())

# ---------------------------------------------------------------------------------------------------------------- the 2D structural panel
class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


t2 = physics_tab.PhysicsTab(Win())
m = t2.read_material()
assert abs(m["alpha"] - 11.7e-6) < 1e-12 and abs(m["Tref"] - 293.15) < 1e-9, "the default material (A36) has its alpha in the boxes"
assert t2.e_alpha.text() == "1.17e-05" and t2.e_tref.text() == "20"
i = t2.mat_combo.findData("Aluminium 6061-T6")
t2.mat_combo.setCurrentIndex(i); t2.material_picked()
m = t2.read_material()
assert abs(m["alpha"] - 23.6e-6) < 1e-12 and t2.e_alpha.text() == "2.36e-05"
t2.e_alpha.setText("2.4e-5"); t2.e_alpha.textEdited.emit("2.4e-5")
assert t2.mat_combo.currentData() is None, "typing a value makes the material custom"
assert abs(t2.read_material()["alpha"] - 2.4e-5) < 1e-12
t2.e_tref.setText("-10"); assert abs(t2.read_material()["Tref"] - 263.15) < 1e-9
t2.e_alpha.setText(""); assert t2.read_material()["alpha"] is None, "empty = none"
for txt in ("1", "-1", "abc"):
    t2.e_alpha.setText(txt)
    try:
        t2.read_material(); assert False, txt
    except pf.ModelError as ex:
        assert "expansion" in str(ex), str(ex)
t2.e_alpha.setText("1.2e-5"); t2.e_tref.setText("")
assert abs(t2.read_material()["Tref"] - 293.15) < 1e-9, "no reference temperature typed: 20 degC"
import physics_store as pstore
assert "e_alpha" in t2.INPUTS and "e_tref" in t2.INPUTS, "saved with the project"
got = pstore.get_inputs(t2, t2.INPUTS)
assert got["e_alpha"] == "1.2e-5" and got["e_tref"] == "", got
t2.e_alpha.setText(""); t2.e_tref.setText("20")
pstore.set_inputs(t2, got)
assert t2.e_alpha.text() == "1.2e-5", "read back from the file"
t2.region_mats = {1: {"E_MPa": 70000.0, "nu": 0.33, "Sy_MPa": 100.0, "Su_MPa": 200.0, "alpha": 2.0e-5, "Tref_K": 300.0}, 2: {"E_MPa": 1e5, "nu": 0.3}}
rm = t2.region_mats_in_units()
assert rm[1]["alpha"] == 2.0e-5 and rm[1]["Tref"] == 300.0 and rm[2]["alpha"] is None, rm
print("ok   2D structural panel: boxes, library pick, custom, validation, saved with the project, region materials carry alpha")

# ---------------------------------------------------------------------------------------------------------------- the 3D structural panel
T = tempfile.mkdtemp()
d = pmod.Document(); d.params = {"T": "10"}
s = d.add(pmod.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m_ = d.models[s["id"]]
r = sk.add_rect_corner(m_, (0, 0), (100, 10))
m_.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m_.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m_); d.store_sketch(s["id"])
d.add(pmod.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w3 = solid_tab.SolidWindow(threaded=False)
assert w3.create_project(os.path.join(T, "a")) and w3.import_file(part)
import solid_model as sm3
assert "alpha" not in sm3.default_setup()["material"], "a bare setup has no expansion coefficient"
assert abs(w3.read_inputs()["material"]["alpha"] - 12.0e-6) < 1e-12 and w3.e_alpha.text() == "1.2e-05", "the part came with its material (generic steel): its alpha is in the box"
w3.mat_combo.setCurrentIndex(w3.mat_combo.findData("Aluminium 6061-T6")); w3.material_picked()
mt = w3.setup["material"]
assert abs(mt["alpha"] - 23.6e-6) < 1e-12 and abs(mt["Tref"] - 293.15) < 1e-9 and w3.e_alpha.text() == "2.36e-05" and w3.e_tref.text() == "20", (mt, w3.e_alpha.text())
w3.e_alpha.setText("1.5e-5"); w3.e_tref.setText("30"); w3.inputs_changed()
mt = w3.setup["material"]
assert mt["alpha"] == 1.5e-5 and abs(mt["Tref"] - 303.15) < 1e-9
w3.e_alpha.setText("7"); w3.e_tref.setText("30")
try:
    w3.read_inputs(); assert False
except ValueError as ex:
    assert "per kelvin" in str(ex), str(ex)
w3.e_alpha.setText(""); w3.inputs_changed()
assert "alpha" not in w3.setup["material"] and "Tref" not in w3.setup["material"], "empty = none"
# the part material of an assembly body
import solid_asm
bm = solid_asm.body_material({"name": "Aluminum 6061", "density": 2700.0, "E_MPa": 68900.0, "nu": 0.33})
assert bm["alpha"] == 23.6e-6 and bm["Tref"] == 293.15, bm
assert "alpha" not in solid_asm.body_material({"name": "Water", "density": 1000.0}) and "alpha" not in solid_asm.body_material(None)
w3.use_source_material({"name": "Copper", "density": 8960.0, "E_MPa": 117000.0, "nu": 0.34, "Sy_MPa": 70.0, "Su_MPa": 220.0})
assert abs(w3.setup["material"]["alpha"] - 16.5e-6) < 1e-12, "the material of the part in the file gives its alpha"
print("ok   3D structural panel: boxes, library pick, custom, validation, empty = none, the material of the part, the bodies of an assembly")
print("OK")
