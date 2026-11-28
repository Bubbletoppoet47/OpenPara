# Evidence for the slicer plan

What was run, so that someone can check the plan's claims. Everything here was run on 2026-11-28 in a scratch folder outside the repository, on a machine with 2 cores and 7 GB, Linux, `g++ 13`.

| File | What it is |
|---|---|
| `compile_probe.log` | The result of compiling the heaviest files of Orca's `libslic3r` one at a time (`-O1`): return code, seconds, peak memory, errors. **Compile only: nothing was linked or run.** |
| `compile_probe_plain.py`, `compile_probe_stepcut.py`, `compile_probe_cgal.py`, `probe_all.sh` | The scripts that made the log. They are kept **as they were run**, so they contain absolute paths of the scratch folder (where Orca's source, Ubuntu's Boost/Eigen/TBB headers and CGAL 6.2.1 were) and need those edited before they run anywhere else |
| `libslic3r_version.h` | A stand-in for the header Orca's CMake generates |
| `gen_elegoo_tables.py` | Reads Orca's profile files for the Elegoo Centauri Carbon (inheritance resolved, the child winning) and prints the tables of Appendix C of the plan |
| `elegoo_tables.md` | Its output |

Orca's commit was `1044ef4407d7` (2.6.0-dev). `Print.cpp` and `GCode.cpp` compiled once their include of the STEP header was deleted in a copy. `Model.cpp` **failed** (10 errors, the STEP type is missing); the plan's chapter 6.3 says it needs a guard around `Model::read_from_step` and its declaration, and that guard has **not** been tried.

Orca's source is AGPL-3.0 and is not kept here.
