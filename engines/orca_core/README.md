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
| `patches/` | The changes to Orca's files, each small and with a message that says why. `0001` stops `Format/STEP.hpp` from including OpenCASCADE when `ORCA_CORE_SLICING_ONLY` is defined; `0002` leaves the readers that need the cut libraries out of `Model.cpp`. |
| `CMakeLists.txt` | Builds the engine with its own top-level file (not Orca's, which looks for wxWidgets, OpenCASCADE, OpenCV and OpenGL). |
| `tests/slice_cube.cpp` | A test program: a cube, Orca's default print settings, sliced to G-code. The first thing that has to work (SLC-1). |

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

SLC-1 is under way. What has been checked: the list of files, the two patches (they apply to the pinned tree and `Model.cpp` and the other
files compile), and the CMake configure. What has not: the link, the first slice, the comparison with Orca's own output, and the Windows build.
This file is updated when each of those is done.
