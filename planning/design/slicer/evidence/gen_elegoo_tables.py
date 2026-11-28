"""gen_elegoo_tables.py <orca-checkout> - prints markdown tables of the Elegoo Centauri Carbon presets as shipped in Orca's resources/profiles/Elegoo
(inheritance resolved the way a preset bundle does it: the child's keys win over its parent's).  Used for the appendix of PLAN.md; run again when the Orca checkout moves."""
import glob, json, os, sys
root = os.path.join(sys.argv[1] if len(sys.argv) > 1 else ".", "resources", "profiles", "Elegoo")
idx = {}
for dp, _, fs in os.walk(root):
    for f in fs:
        if f.endswith(".json"):
            idx[f[:-5]] = os.path.join(dp, f)

def resolve(name):
    chain = []
    while name and name in idx:
        d = json.load(open(idx[name], encoding="utf-8")); chain.append(d); name = d.get("inherits")
    out = {}
    for d in reversed(chain):
        out.update(d)
    return out, len(chain)

def first(v):
    return (v[0] if v else "") if isinstance(v, list) else v

print("### Filament presets for the Centauri Carbon (`filament/ECC`)\n")
print("| Preset | Type | Density (g/cm3) | Nozzle (C) | Hot plate (C) | Textured plate (C) | Max flow (mm3/s) | Pressure advance |")
print("|---|---|---|---|---|---|---|---|")
for p in sorted(glob.glob(os.path.join(root, "filament", "ECC", "*.json"))):
    d, _ = resolve(os.path.basename(p)[:-5])
    print("| %s | %s | %s | %s | %s | %s | %s | %s |" % (d["name"], first(d.get("filament_type")), first(d.get("filament_density")), first(d.get("nozzle_temperature")),
          first(d.get("hot_plate_temp")), first(d.get("textured_plate_temp")), first(d.get("filament_max_volumetric_speed")), first(d.get("pressure_advance"))))
print("\n### Process presets for the Centauri Carbon with the 0.4 nozzle (`process/ECC`)\n")
print("| Preset | Layer height (mm) | Walls | Infill | Infill pattern | Top / bottom layers | Outer wall speed (mm/s) | Infill speed (mm/s) |")
print("|---|---|---|---|---|---|---|---|")
for p in sorted(glob.glob(os.path.join(root, "process", "ECC", "*CC 0.4 nozzle.json"))):
    d, _ = resolve(os.path.basename(p)[:-5])
    print("| %s | %s | %s | %s | %s | %s / %s | %s | %s |" % (d["name"], d.get("layer_height"), d.get("wall_loops"), d.get("sparse_infill_density"), d.get("sparse_infill_pattern"),
          d.get("top_shell_layers"), d.get("bottom_shell_layers"), d.get("outer_wall_speed"), d.get("sparse_infill_speed")))
