# orca_core: Orca Slicer's slicing engine, cut down

This folder builds the slicing engine of [Orca Slicer](https://github.com/OrcaSlicer/OrcaSlicer) (its `libslic3r`) as a library that OpenPara
can call, without Orca's window, its CAD kernel or the libraries only they need. The plan is `planning/design/slicer/PLAN.md` (chapter 6 is
this folder); the work items are SLC-1 and SLC-2 in `planning/ISSUES.md`.

**Licence.** Orca Slicer is AGPL-3.0, and so is anything built from it (the files here, the library, the Python module made from it).
OpenPara is GPL-3.0. Whoever gets a build of this engine gets the source with it: Orca's at the pinned tag, and these files, which say exactly
what was left out and what was changed. Nothing in `engines/` is taken from Orca's repository except what `ORCA_PIN` names; their source is
fetched, not copied here.

## What is here

| File | What it is |
|---|---|
| `ORCA_PIN` | The Orca release this is built from (tag `v2.5.2`, the full commit), and the versions of Eigen, CGAL and Boost that go with it. A different Orca needs a new pin, new patches and a new test run. |
| `cuts.txt` | The files of `src/libslic3r` that are left out: the CAD kernel (`CAD/*`, STEP), the resin printer code (`SLA/*`), texture baking and painting, and the readers for formats that need heavy libraries (OBJ, glTF, FBX, SVG, DRC). Patterns, one per line, each with the reason. |
| `tools/gen_sources.py` | Reads Orca's own `src/libslic3r/CMakeLists.txt`, takes its list of files, removes the ones in `cuts.txt` and writes `sources.cmake` and `cut_report.md` (what was kept and what was cut, so a reader can check). The list is Orca's, never typed by hand, so a new pin changes it by itself. |
| `tools/prepare_orca.py` | `python tools/prepare_orca.py <Orca checkout>`: checks the checkout is the pinned commit and applies `patches/` in name order. `--check` says whether they apply, `--revert` takes them out again. |
| `patches/` | The changes to Orca's files, each small and with a message that says why. `0001` stops `Format/STEP.hpp` from including OpenCASCADE when `ORCA_CORE_SLICING_ONLY` is defined; `0002` leaves the readers that need the cut libraries out of `Model.cpp`; `0003` keeps the drain-hole geometry of `SLA/Hollowing.cpp` (z-contouring needs it) and leaves its OpenVDB half out. |
| `CMakeLists.txt` | Builds the engine with its own top-level file (not Orca's, which looks for wxWidgets, OpenCASCADE, OpenCV and OpenGL). |
| `python/orca_core/` | The Python package around the compiled engine (plan 5.1): `results.py` (the paths, moves, estimate, warnings and record, saved to and loaded from a folder), `errors.py`, `roles.py` (Orca's 20 extrusion roles), `job.py` (`Job`: objects, settings, `slice()`), `worker.py` (the engine runs in its own process; progress, cancel, time limit; a crash in the engine becomes `WorkerCrashed` and OpenPara stays open), `_engine.py` (the backend that calls the compiled engine: writes the settings, calls `_orca_core.slice`, turns what comes back and what goes wrong into this package's types and errors) and `_selftest_backend.py` (a stand-in that behaves like an engine, for the tests). Tests: `test_orca_core_results.py`, `test_orca_core_worker.py`, and with the compiled engine `test_orca_core_engine.py` (set `ORCA_CORE_BUILD_DIR`; skips itself without it). |
| `src/nanosvg_impl.cpp` | The one source file of ours in the engine: nanosvg's implementation, which Orca compiles inside a window file. |
| `tools/resolve_presets.py` | Flattens a vendor preset (follows `inherits`) into one standalone JSON; what the profile bundle (SLC-3) and the parity test use. |
| `bindings/orca_core_module.cpp` | The compiled Python module `_orca_core` (pybind11): one function, `slice(...)`, that builds the model, applies the settings, slices, writes the G-code and gives back the printed paths and moves as arrays, the estimate, the warnings and the settings used. Cancel is a file in the job folder that a thread of ours watches; progress is Orca's own status. Built with `-DORCA_CORE_PYTHON=ON -Dpybind11_DIR=$(python -m pybind11 --cmakedir)`. |
| `python/orca_core/profiles.py` | Orca's printer, process and filament presets: lists a vendor's printers, the print profiles and filaments that fit a printer (Orca's rule: names the printer, or its condition holds), follows `inherits` across vendors, reads the person's own presets, and gives the `settings` of a job from three names. A folder or a zip. No compiled engine needed. |
| `python/orca_core/resources/` | The three small tables from Orca (`info/*.json`) that the slicing code reads from its resources folder; shipped with the package. |
| `tools/build_profiles.py` | Builds the profile zip (vendors asked for + `OrcaFilamentLibrary` + `Custom`, Orca's files unchanged, `bundle.json` with the sha256 of each file; the same input gives the same zip). Elegoo: 2.1 MB. |
| `tests/slice_cube.cpp` | A test program: a cube, Orca's default print settings, sliced to G-code. |
| `tests/slice_3mf.cpp` | A test program: slices an Orca 3MF project (model and every setting) the way Orca's own command line does. |
| `tests/parity.py` | The parity test: Orca's own program and this engine on the same project, G-code compared line by line (14 cases). |

## Build (Linux, as done here)

```
git clone --branch v2.5.2 https://github.com/OrcaSlicer/OrcaSlicer orca        # the tag in ORCA_PIN
python engines/orca_core/tools/prepare_orca.py orca                            # checks the commit, applies the patches
cmake -S engines/orca_core -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DORCA_SRC=$PWD/orca -DORCA_EIGEN_DIR=<Eigen 5.0.1 source> -DORCA_CGAL_DIR=<CGAL 6.2 folder>
cmake --build build
build/orca_core_slice_cube out.gcode 20
```

Needs Boost 1.83 or newer (with its compiled libraries), TBB, zlib, libpng, expat, OpenSSL, NLopt, cereal and libnoise from the system or a
package manager, Eigen 5 and CGAL 6.2 as source folders (Eigen 3 from a Linux distribution is not what Orca v2.5.2 is built with: its own dependency is Eigen 5.0.1, and that is the one used here), and
a C++17 compiler. The compile is long (about 280 files) and uses a few GB of memory per job. On the two-core build machine used for the
first run it takes hours; the Windows runner is the intended place to build the shipped version.

## State

**SLC-1 on Linux is done**: the engine builds, links and slices, and `tests/parity.py` finds its G-code identical, line by line, to Orca Slicer 2.5.2's own program on 13 cases (Elegoo Centauri Carbon 0.4 nozzle, 0.20mm Standard, Elegoo PLA; a cube, a bridge, holes, an overhang, a 10-layer organic model, tree and normal supports, gyroid infill with 4 walls, classic walls, ironing, spiral mode, PETG), and the same in totals for fuzzy skin, which is random in Orca itself. Not compared: the settings listing at the end of the G-code, where Orca's window adds a few keys of its own (print host, plugins). The engine prints a harmless error about `nozzle_info.json` unless `set_resources_dir` is called (the binding will).

**SLC-2 on Linux is done**: `_orca_core` and `_engine.py` run a slice through the worker process and return paths, moves, estimate, warnings and record; `test_orca_core_engine.py` checks, with the real engine, that the paths' plastic volume equals what Orca's G-code extrudes (to 0.2 %), that the estimate equals Orca's own header, that progress is in order, that bad settings come back as `ConfigError` with the key, that a setting on one object changes only that object, and that a cancel stops a long slice in a fraction of a second. The paths and moves are read back from the G-code by Orca's own G-code processor, so what OpenPara analyses is what the printer would be told. Known gaps: the `object` column is 0 for every path (Orca's processor labels objects only for Bambu printers; several objects are printed, but not told apart), and `overhang`, `curve`, `z_contoured` are zero.

**SLC-3 (profiles) on Linux is done**: `profiles.py` reads Orca's vendor profiles (72 vendors in the checkout; Elegoo + the generic library in a 2.1 MB zip) and `test_orca_core_profiles.py` checks it on a small made-up vendor (folder and zip) and on the real Elegoo files: the Centauri Carbon in four nozzle sizes has 4, 6, 6 and 5 print profiles and 25 `@ECC` filaments each, every Elegoo printer's own default print and filament profile fits it, and a cube sliced from the three names (`Elegoo Centauri Carbon 0.4 nozzle`, `0.20mm Standard @Elegoo CC 0.4 nozzle`, `Elegoo PLA @ECC`) gives G-code identical to Orca's own program (7,824 lines; only the object's label differs: `cube` and not `cube.stl`).

Found while building the Workbench block: a slice with one thread never ended (Orca's G-code export waits for a second thread); `slice` now uses at least two TBB threads, and the engine test slices with one.

Not done: the Windows build (SLC-1; `.github/workflows/slicer-engine.yml` is written and started by hand, it has not been run), the settings pages and option definitions exported from Orca (SLC-6/7), and the parity cases for multi-material, painting and several objects.

Build notes from the run here: `MeshBoolean.cpp` needs about 5 GB, so on a 7 GB machine build with `ninja -j1` until it is done; a full build is a few hours on two cores. Boost is linked by file (`$<TARGET_LINKER_FILE:...>`) on purpose, see the comment in `CMakeLists.txt`.
