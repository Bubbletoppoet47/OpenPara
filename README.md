<p align="center"><img src="assets/openpara-logo.svg" width="140" alt="OpenPara logo"></p>

# OpenPara

An open-source parametric CAD modeller written in Python (working title: *Gen Parametric Designer*).

- Parametric parts: sketches with a constraint solver, extrude / cut / revolve / sweep / loft (boss and cut; sweeps can twist), fillet / chamfer, configurations, STEP and STL export of parts and assemblies, and STEP import (File > Import STEP... / Export...; an imported body is the first feature of a new part, and a STEP with several solids can open as one assembly)
- Sketches can use geometry of other sketches (ribbon: Other Sketch): a point, a line, or the point where a sweep path pierces the sketch plane, so a profile can be tied to its path with normal relations and follows it when the path changes
- Assemblies with mates, sub-assemblies and their own Globals (positions, mate values and pattern spacing take formulas)
- One program-wide unit system (File > Units: mm, cm, m, in, ft, N, kN, kip, ... and a separate speed unit)

The core is **Sketch/Part and Assembly** (with STEP / STL exchange, units, settings, materials and AutoSave). Everything else is an **add-on** (File > Add-ons..., or the question that appears when you use one), downloaded from the GitHub release of your version:

- **Part Generator**: spur, helical, herringbone and internal ring gears with true involute teeth; a Gear systems tab sizes a train of up to three gears from centre distances or ratios, or a planetary sun / planet / ring set, and opens each gear as its own part.
- **Truss Generator**: builds the members of a truss from the lines of a sketch (profile, longest length, angled end cuts) and writes a cut list.

Parts that use the Part Generator keep their data without the add-on and say that they need it. Uninstalling an add-on never touches your files or your material library. Installing needs an internet connection; once installed an add-on works offline. Simulation and the renderer are not part of this version; they are being reworked and will return as add-ons.

Built on [build123d](https://github.com/gumyr/build123d) (OpenCascade), PyQt6, pyvista / VTK.

## Install (Windows)

1. Go to the [Releases](https://github.com/Bubbletoppoet47/OpenPara/releases) page and download `OpenPara-Setup-<version>.exe`.
2. Run it. It installs OpenPara for your user (no administrator rights), with its own Python and all packages inside, and adds a Start-menu entry.
3. Start **OpenPara** from the Start menu.

OpenPara looks for updates at start-up (Help > Check for updates...) and installs them for you. Your own data (error log, material library, settings)
is kept in `%LOCALAPPDATA%\OpenPara` (Help > Open the data folder) and is never touched by an update.

## Run from source


Windows: double-click `run_modeller.bat` (installs the packages the first time), or

    pip install -r requirements.txt
    python gpd_app.py

## Guides

- `docs/README_modeller.txt` - how the modeller works

## Tests

Each `test_*.py` runs on its own, for example `QT_QPA_PLATFORM=offscreen python test_links.py`.

## Status

Early and in active development. Not everything is tested on every machine (for example CUDA rendering and the OptiX denoiser).

## License

GNU General Public License v3.0 - see `LICENSE`.

## For the maintainer: making a release

1. Raise `__version__` in `version.py` (and `RUNTIME` only when the Python or the packages change).
2. Commit, then tag: `git tag v<version> && git push origin v<version>`.
3. The workflow `.github/workflows/release.yml` builds the Windows folder on GitHub, makes `OpenPara-Setup-<version>.exe` and
   `OpenPara-app-<version>.zip` (the small update zip) and publishes them as a release.
