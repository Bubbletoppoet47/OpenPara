"""orca_core.profiles: Orca's printer, process and filament presets, resolved (SLC-3, plan chapter 9).  Needs no compiled engine.

Two parts.  The first builds a small vendor folder in a temporary place (a printer in two nozzle sizes, a base preset each, a library vendor that a
filament inherits from, a condition that decides which print profile fits which nozzle) and checks what a reader of Orca's profile files must do:
follow "inherits" (the child's keys win, across vendors), offer a preset for a printer when it names the printer or its condition holds, say in words
what does not fit, read the person's own presets, and give the same answers from a folder and from a zip.  The second runs on Orca's real Elegoo
profiles when they are there (ORCA_CORE_PROFILES, or a built profiles.zip): the Centauri Carbon in its four nozzle sizes, its print profiles and
the 25 Elegoo filaments, and that every printer's own default print and filament profile fit it.  With the compiled engine it also slices a cube
from the three names and checks the G-code is the Centauri Carbon's."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import json, os, sys, tempfile, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engines", "orca_core", "python"))
from orca_core import profiles as P
from orca_core.profiles import Profiles, ProfileError, evaluate_condition


def put(root, rel, data, bom=False):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8") as f:
        json.dump(data, f, indent=1)


def make_fixture(root):
    put(root, "Acme.json", {"name": "Acme", "version": "1.0.0.0",
        "machine_model_list": [{"name": "Acme One", "sub_path": "machine/Acme One.json"}],
        "machine_list": [{"name": "fdm_acme_common", "sub_path": "machine/fdm_acme_common.json"},
                         {"name": "Acme One 0.4 nozzle", "sub_path": "machine/Acme One 0.4 nozzle.json"},
                         {"name": "Acme One 0.6 nozzle", "sub_path": "machine/Acme One 0.6 nozzle.json"}],
        "process_list": [{"name": "fdm_process_acme", "sub_path": "process/fdm_process_acme.json"},
                         {"name": "0.20mm Standard @Acme", "sub_path": "process/0.20mm Standard @Acme.json"},
                         {"name": "0.30mm Coarse @Acme 0.6", "sub_path": "process/0.30mm Coarse @Acme 0.6.json"}],
        "filament_list": [{"name": "Acme PLA", "sub_path": "filament/Acme PLA.json"},
                          {"name": "Acme PETG", "sub_path": "filament/Acme PETG.json"}]})
    put(root, "Acme/machine/Acme One.json", {"type": "machine_model", "name": "Acme One", "nozzle_diameter": "0.4;0.6", "default_materials": "Acme PLA;Acme PETG"})
    put(root, "Acme/machine/fdm_acme_common.json", {"type": "machine", "name": "fdm_acme_common", "instantiation": "false", "gcode_flavor": "marlin",
        "nozzle_diameter": ["0.4"], "printer_notes": "", "retraction_length": ["0.8"], "printable_area": ["0x0", "200x0", "200x200", "0x200"]})
    put(root, "Acme/machine/Acme One 0.4 nozzle.json", {"type": "machine", "name": "Acme One 0.4 nozzle", "inherits": "fdm_acme_common", "instantiation": "true",
        "printer_model": "Acme One", "nozzle_diameter": ["0.4"], "printer_notes": "ACME_ONE", "default_print_profile": "0.20mm Standard @Acme",
        "default_filament_profile": ["Acme PLA"]}, bom=True)                                   # Orca's own files sometimes start with a byte order mark
    put(root, "Acme/machine/Acme One 0.6 nozzle.json", {"type": "machine", "name": "Acme One 0.6 nozzle", "inherits": "fdm_acme_common", "instantiation": "true",
        "printer_model": "Acme One", "nozzle_diameter": ["0.6"], "printer_notes": "ACME_ONE", "retraction_length": ["1.2"]})
    put(root, "Acme/process/fdm_process_acme.json", {"type": "process", "name": "fdm_process_acme", "instantiation": "false", "layer_height": "0.2",
        "wall_loops": "2", "sparse_infill_density": "15%",
        "compatible_printers_condition": "printer_notes=~/.*ACME_ONE.*/ and nozzle_diameter[0]==0.4"})
    put(root, "Acme/process/0.20mm Standard @Acme.json", {"type": "process", "name": "0.20mm Standard @Acme", "inherits": "fdm_process_acme", "instantiation": "true",
        "from": "system", "setting_id": "abc", "wall_loops": "3"})
    put(root, "Acme/process/0.30mm Coarse @Acme 0.6.json", {"type": "process", "name": "0.30mm Coarse @Acme 0.6", "inherits": "fdm_process_acme", "instantiation": "true",
        "layer_height": "0.3", "compatible_printers": ["Acme One 0.6 nozzle"]})        # a list of printers wins over the inherited condition
    put(root, "Acme/filament/Acme PLA.json", {"type": "filament", "name": "Acme PLA", "inherits": "Generic PLA", "instantiation": "true",
        "compatible_printers": ["Acme One 0.4 nozzle", "Acme One 0.6 nozzle"], "nozzle_temperature": ["215"]})
    put(root, "Acme/filament/Acme PETG.json", {"type": "filament", "name": "Acme PETG", "inherits": "Acme PLA", "instantiation": "true",
        "compatible_printers": ["Acme One 0.4 nozzle"], "filament_type": ["PETG"], "nozzle_temperature": ["240"]})
    put(root, "OrcaFilamentLibrary.json", {"name": "OrcaFilamentLibrary", "version": "1", "filament_list": [
        {"name": "fdm_filament_common", "sub_path": "filament/fdm_filament_common.json"}, {"name": "Generic PLA", "sub_path": "filament/Generic PLA.json"}]})
    put(root, "OrcaFilamentLibrary/filament/fdm_filament_common.json", {"type": "filament", "name": "fdm_filament_common", "instantiation": "false",
        "filament_type": ["PLA"], "filament_density": ["1.24"], "nozzle_temperature": ["200"], "filament_diameter": ["1.75"]})
    put(root, "OrcaFilamentLibrary/filament/Generic PLA.json", {"type": "filament", "name": "Generic PLA", "inherits": "fdm_filament_common", "instantiation": "true"})


def names(items):
    return [x.name for x in items]


def check_fixture(p, label):
    assert p.vendors() == ["Acme", "OrcaFilamentLibrary"], (label, p.vendors())
    assert [m["name"] for m in p.models("Acme")] == ["Acme One"] and p.models("Acme")[0]["nozzle_diameter"] == [0.4, 0.6]
    assert names(p.machines("Acme")) == ["Acme One 0.4 nozzle", "Acme One 0.6 nozzle"], names(p.machines("Acme"))      # the base preset is not offered
    # which print profiles fit which nozzle: the inherited condition for the 0.4, the named printer for the 0.6
    assert names(p.processes("Acme One 0.4 nozzle")) == ["0.20mm Standard @Acme"], names(p.processes("Acme One 0.4 nozzle"))
    assert names(p.processes("Acme One 0.6 nozzle")) == ["0.30mm Coarse @Acme 0.6"], names(p.processes("Acme One 0.6 nozzle"))
    f4, f6 = names(p.filaments("Acme One 0.4 nozzle")), names(p.filaments("Acme One 0.6 nozzle"))
    assert sorted(f4) == ["Acme PETG", "Acme PLA", "Generic PLA"] and sorted(f6) == ["Acme PLA", "Generic PLA"], (f4, f6)
    # resolving: the child's keys win, parents fill in, across vendors, and the description keys are gone
    r = p.resolve("filament", "Acme PETG", "Acme")
    assert r["filament_type"] == ["PETG"] and r["nozzle_temperature"] == ["240"] and r["filament_density"] == ["1.24"], r
    assert r["compatible_printers"] == ["Acme One 0.4 nozzle"] and not ({"inherits", "name", "type", "instantiation", "from", "setting_id"} & set(r)), sorted(r)
    assert p.resolve("process", "0.20mm Standard @Acme")["wall_loops"] == "3" and p.resolve("process", "0.20mm Standard @Acme")["layer_height"] == "0.2"
    assert p.resolve("machine", "Acme One 0.6 nozzle")["retraction_length"] == ["1.2"] and p.resolve("machine", "Acme One 0.6 nozzle")["gcode_flavor"] == "marlin"
    # the settings of a job
    s = p.settings("Acme One 0.4 nozzle", "0.20mm Standard @Acme", "Acme PETG", overrides={"sparse_infill_density": "30%", "wall_loops": 4})
    assert s["gcode_flavor"] == "marlin" and s["nozzle_diameter"] == ["0.4"] and s["nozzle_temperature"] == ["240"] and s["layer_height"] == "0.2"
    assert s["sparse_infill_density"] == "30%" and s["wall_loops"] == 4, (s["sparse_infill_density"], s["wall_loops"])
    assert s["printer_settings_id"] == "Acme One 0.4 nozzle" and s["print_settings_id"] == "0.20mm Standard @Acme" and s["filament_settings_id"] == ["Acme PETG"]
    # what does not fit, in words
    for args, want in ((("Acme One 0.6 nozzle", "0.20mm Standard @Acme", "Acme PLA"), "process profile '0.20mm Standard @Acme' is not made for the printer 'Acme One 0.6 nozzle'"),
                       (("Acme One 0.6 nozzle", "0.30mm Coarse @Acme 0.6", "Acme PETG"), "filament profile 'Acme PETG' is not made for the printer"),
                       (("Nope 1", "0.20mm Standard @Acme", "Acme PLA"), "no printer profile named 'Nope 1'"),
                       (("Acme One 0.4 nozzle", "No such", "Acme PLA"), "no process profile named 'No such'")):
        try:
            p.settings(*args)
            raise SystemExit("%s: a choice that does not fit was accepted: %s" % (label, args))
        except ProfileError as e:
            assert want in str(e), (want, str(e))
    try:
        p.models("Nowhere")
        raise SystemExit("a vendor that is not there was accepted")
    except ProfileError as e:
        assert "Nowhere" in str(e)


tmp = tempfile.mkdtemp()
folder = os.path.join(tmp, "profiles")
make_fixture(folder)
check_fixture(Profiles(folder), "folder")
zpath = os.path.join(tmp, "profiles.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for dp, _d, fs in os.walk(folder):
        for fn in fs:
            full = os.path.join(dp, fn)
            z.write(full, os.path.relpath(full, folder).replace(os.sep, "/"))
check_fixture(Profiles(zpath), "zip")

# a preset that inherits from itself, and one whose parent is missing
loop = os.path.join(tmp, "loop")
make_fixture(loop)
put(loop, "Acme/filament/Acme PLA.json", {"type": "filament", "name": "Acme PLA", "inherits": "Acme PETG", "instantiation": "true"})
try:
    Profiles(loop).resolve("filament", "Acme PETG", "Acme")
    raise SystemExit("a loop of inherits was accepted")
except ProfileError as e:
    assert "inherits from itself" in str(e), str(e)
put(loop, "Acme/filament/Acme PLA.json", {"type": "filament", "name": "Acme PLA", "inherits": "Missing parent", "instantiation": "true"})
try:
    Profiles(loop).resolve("filament", "Acme PLA", "Acme")
    raise SystemExit("a missing parent was accepted")
except ProfileError as e:
    assert "Missing parent" in str(e), str(e)

# the person's own presets: a copy of a profile with something changed, in the user folder
user = os.path.join(tmp, "user")
put(user, "filament/My PETG.json", {"type": "filament", "name": "My PETG", "inherits": "Acme PETG", "nozzle_temperature": ["250"],
                                    "compatible_printers": ["Acme One 0.4 nozzle"]})
p = Profiles(folder, user_dir=user)
assert "My PETG" in names(p.filaments("Acme One 0.4 nozzle")) and "My PETG" not in names(p.filaments("Acme One 0.6 nozzle"))
s = p.settings("Acme One 0.4 nozzle", "0.20mm Standard @Acme", "My PETG")
assert s["nozzle_temperature"] == ["250"] and s["filament_type"] == ["PETG"] and s["filament_settings_id"] == ["My PETG"], s["nozzle_temperature"]

# conditions as Orca writes them
printer = {"printer_notes": "ACME_ONE\nPRINTER_VENDOR_ELEGOO", "nozzle_diameter": ["0.4"], "single_extruder_multi_material": "1"}
for text, want in (("printer_notes=~/.*ACME_ONE.*/", True), ("printer_notes=~/.*OTHER.*/", False), ("printer_notes!~/.*OTHER.*/", True),
                   ("printer_notes=~/.*ACME_ONE.*/ and nozzle_diameter[0]==0.4", True), ("printer_notes=~/.*ACME_ONE.*/ and nozzle_diameter[0]==0.6", False),
                   ("nozzle_diameter[0]==0.6 or printer_notes=~/.*ELEGOO.*/", True), ("nozzle_diameter[0]>=0.4 and nozzle_diameter[0]<0.6", True),
                   ("not (nozzle_diameter[0]==0.4)", False), ("!(nozzle_diameter[0]==0.6)", True),
                   ("printer_notes=~/.*ACME_ONE.*/ and single_extruder_multi_material", True), ("nozzle_diameter[0]==0.4 and some_new_flag", None),
                   ("printer_notes=~/.*ACME", None), ("))", None), ("", None)):
    got = evaluate_condition(text, printer)
    assert got == want or (want is None and got is None), (text, got, want)
print("profiles, a folder and a zip of a small vendor: ok")

# ---- Orca's own Elegoo profiles
loc = P.default_location()
if not loc:
    print("Elegoo profiles: skipped (no Orca profiles here; set ORCA_CORE_PROFILES to a resources/profiles folder or a profiles.zip)")
    sys.exit(0)
p = Profiles.open(loc)
assert "Elegoo" in p.vendors() and "OrcaFilamentLibrary" in p.vendors()
cc = {m.name: m for m in p.machines("Elegoo", model="Elegoo Centauri Carbon")}
assert sorted(cc) == ["Elegoo Centauri Carbon %s nozzle" % n for n in ("0.2", "0.4", "0.6", "0.8")], sorted(cc)
M = "Elegoo Centauri Carbon 0.4 nozzle"
proc = names(p.processes(M))
assert len(proc) == 6 and "0.20mm Standard @Elegoo CC 0.4 nozzle" in proc and all("@Elegoo CC 0.4" in n for n in proc), proc
per_nozzle = {n: names(p.processes("Elegoo Centauri Carbon %s nozzle" % n)) for n in ("0.2", "0.4", "0.6", "0.8")}
assert [len(v) for v in per_nozzle.values()] == [4, 6, 6, 5], {k: len(v) for k, v in per_nozzle.items()}      # plan 9.3
for n in ("0.2", "0.4", "0.6", "0.8"):
    fil = names(p.filaments("Elegoo Centauri Carbon %s nozzle" % n))
    ecc = [x for x in fil if x.endswith("@ECC")]
    assert len(ecc) == 25, (n, len(ecc))
    assert any(x.startswith("Generic PLA") for x in fil), "the generic filaments of the library are offered too"
    assert not [x for x in fil if x.startswith("Bambu") and "Elegoo" in x], fil[:5]
s = p.settings(M, "0.20mm Standard @Elegoo CC 0.4 nozzle", "Elegoo PLA @ECC")
assert s["gcode_flavor"] == "klipper" and s["nozzle_diameter"] == ["0.4"] and float(s["layer_height"]) == 0.2 and s["filament_type"] == ["PLA"], \
    (s["gcode_flavor"], s["nozzle_diameter"], s["layer_height"])
assert s["printable_area"] == ["0x0", "256x0", "256x256", "0x256"] and "CC_START_GCODE" in s["machine_start_gcode"] or "START" in s["machine_start_gcode"].upper()
assert s["printer_settings_id"] == M
# every Elegoo printer: its own default print and filament profile are offered for it
checked = 0
for m in p.machines("Elegoo"):
    r = p.resolve("machine", m.name, "Elegoo")
    dp, df = r.get("default_print_profile"), (r.get("default_filament_profile") or [""])[0]
    if dp:
        assert dp in names(p.processes(m.name)), (m.name, dp)
        checked += 1
    if df:
        assert df in names(p.filaments(m.name)), (m.name, df)
        checked += 1
assert checked >= 40, checked
print("Elegoo profiles: Centauri Carbon in four nozzle sizes %s print profiles, 25 filaments each, %d default choices fit: ok" % ([len(v) for v in per_nozzle.values()], checked))

# ---- with the compiled engine: a cube sliced from the three names is a Centauri Carbon print
sys.path.insert(0, os.path.join(HERE, "dev_addons", "solid_fea"))
import numpy as np
import orca_core as oc
from orca_core import errors, _engine
try:
    _engine._core()
except errors.EngineMissing:
    print("slicing from profile names: skipped (the compiled engine is not built here)")
    sys.exit(0)
v = np.array([(x, y, z) for z in (0, 20) for y in (0, 20) for x in (0, 20)], float) + [118.0, 118.0, 0.0]
f = np.array([t for a, b, c, d in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)) for t in ((a, b, c), (a, c, d))])
job = oc.Job(p.settings(M, "0.20mm Standard @Elegoo CC 0.4 nozzle", "Elegoo PLA @ECC"), threads=2)
job.add_object(v, f, "cube")
res = job.slice()
text = open(res.gcode_path, encoding="utf-8").read()
assert res.paths.n_layers == 100 and "EXCLUDE_OBJECT_DEFINE" in text and "SET_PRINT_STATS_INFO" in text, "Elegoo's own start and layer-change G-code"
assert not [w for w in res.warnings if "substitut" in str(w).lower()], [str(w) for w in res.warnings][:3]
assert res.record["settings"]["printer_settings_id"] == M and res.estimate.time_normal_s > 300
print("slicing from profile names: %d layers, %.0f s, %d warnings: ok" % (res.paths.n_layers, res.estimate.time_normal_s, len(res.warnings)))
