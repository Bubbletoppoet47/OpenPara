# 3D Thermal (workshopping)

Heat conduction in a parametric part or an assembly of parts, as another kind of Simulation project (`.gpt`, next to `.gpb .gpf .gpc .gpv .gph`). It is the 3D FEA window (`solid_base.SolidBase`) with heat in place of stress: the same project bar, Geometry (part, faces, splitting a flat face into patches, the bodies of an assembly), Mesh and Solve button. Everything is stored and solved in SI and kelvin; File > Units > Heat transfer decides what is shown and how typed numbers are read.

What it solves:
- steady and transient conduction (backward Euler or Crank-Nicolson), quadratic or linear tetrahedra from gmsh;
- conditions picked on faces in the view: fixed temperature, heat flux, heat flow in watts (spread over the faces), convection (h and fluid temperature), radiation to the surroundings (emissivity and surroundings temperature, Newton iteration) and Insulated; a face with no condition is insulated;
- a material for every body of an assembly (the library 2D Thermal uses: conductivity, density, specific heat) and heat generation per body (W/m3); bodies touching each other conduct through the joint as one piece (perfect contact);
- results: temperature and heat flux on the surface, a picture slider and animation for a transient run, a node probe, the heat through every condition and a heat balance (in = out + stored) that must close, per-body numbers;
- direct solve for small meshes, conjugate gradients with an algebraic multigrid preconditioner (pyamg) above `DIRECT_LIMIT`.

Not in this version: section planes through the part (the view colours the outer surface only), heat-flow arrows / tracers, thermal stress (temperature feeding 3D FEA), conjugate heat transfer with 3D CFD, contact resistance between bodies, view-factor radiation between parts, temperature-dependent properties, automatic mesh refinement, a parametric study.
Material values are typical room-temperature numbers taken as constant. Nothing here has been compared with commercial software or tried on real Windows: everything so far ran headless.

## Testing it (and what to send back)

1. Open the **3D Thermal** tab (File > New 3D Thermal). Press **Load test example** (Test and diagnostics section): you choose a folder, the program builds a deliberately demanding project in it and opens it: an assembly of four bodies (an aluminium plate with five holes, a round copper pad that makes heat inside itself and sits over the big hole, a thin stainless-steel fin, an ABS block), a fixed temperature on a curved hole face, 25 W on the pad, convection on three different faces, radiation on a flat and on a curved face, an insulated block, and a transient run of 30 minutes. Conductivities run from 0.17 to 401 W/(m K).
2. **Solve** (about ten seconds on a modest computer; the radiation makes it factorise the matrix at every Newton step).
3. **Run self-check**: solves seven small problems whose answers are known on paper (a wall, two bodies in series, heat made inside a bar, a cube cooling in air, a plate radiating, a pipe wall with two meshes and the iterative solver against the direct one) and, when the example is loaded and solved, checks its result (heat balance, heat generated, the 25 W, nothing colder than the fluid, the hottest point never cooling, volume of the mesh, the pad being the hottest body). Each line shows PASS or FAIL with what was computed beside what was expected.
4. **Diagnostics report...**: one text page with the computer and program version, the geometry, the mesh size and quality, the setup in plain numbers, the time of every stage, the solver and its convergence, the self-check and every message the window gave (errors in full). It has **Copy to clipboard** and is also saved in the project folder as `diagnostics.txt` every time it opens. It works on your own models too: solve one, then press it.

Send the report (or the file) when something fails, is slow or looks wrong.

Files: `thermal3d_fem.py` (maths, no Qt), `thermal3d_model.py` (the setup and its run, no Qt), `thermal3d_tab.py` (the window), `thermal3d_example.py` (the test example, the self-check and the report text), `thermal3d_ext.py` (registers the project kind). The report builders shared with the 3D CFD window are in `dev_addons/solid_fea/solid_diag.py`.
Tests (repository root): `test_thermal3d_fem.py`, `test_thermal3d_model.py`, `test_thermal3d_tab.py` (the window, the example, the self-check, the report), `test_solid_diag.py`.
