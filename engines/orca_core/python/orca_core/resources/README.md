# Resources

`info/` holds three small tables from Orca Slicer 2.5.2 (AGPL-3.0, `resources/info/`) that the slicing code reads from its resources folder:
`nozzle_info.json`, `nozzle_incompatibles.json` and `filament_info.json`. They are copied unchanged. The engine finds them through
`orca_core._engine.resources_dir()`.

The printer profiles are not kept here: they are built into a zip by `engines/orca_core/tools/build_profiles.py` and found by
`orca_core.profiles.default_location()` (the environment variable `ORCA_CORE_PROFILES`, or `profiles.zip` in this folder).
