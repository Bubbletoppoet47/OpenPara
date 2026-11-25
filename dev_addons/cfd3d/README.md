# 3D Fluid Flow (workshopping)

Steady, laminar flow of air or water around one 3D parametric part, with the temperature of the fluid, as another kind of Simulation project (`.gpw`, next to `.gpb .gpf .gpc .gpv .gph .gpt`). It is the 3D FEA window (`solid_base.SolidBase`) with a fluid in place of the stress: the same project bar, Geometry, Mesh and Solve button, and the same way of picking faces in the 3D view. Everything is stored and solved in SI and kelvin; File > Units and File > Units > Heat transfer decide what is shown and how typed numbers are read (the pressure is shown in Pa, or in psf for the US systems).

What it does:
- the part is cut out of a box of fluid whose reach upstream, downstream and sideways you set in part sizes; the fluid comes in on one face of the box, leaves on the opposite one, the other four faces of the box are slip walls, and the fluid sticks to every face of the part;
- gmsh meshes the box with tetrahedra that are small at the part and grow away from it (the window estimates the number of nodes before you mesh and warns when the part blocks too much of the box);
- the flow is solved on linear tetrahedra with a stabilised method (SUPG + PSPG + LSIC), all of velocity and pressure at once, stepping in pseudo-time with the convection frozen at the last step until the change is below 1e-7 (the result says converged, stalled or not converged); direct solve up to 70,000 unknowns, GMRES with an incomplete LU above;
- the temperature of the fluid is solved afterwards (switch it on in Fluid and flow): inflow temperature, and on faces of the part picked in the view: Wall temperature, Wall heat flux or Adiabatic wall; a face with no condition is adiabatic;
- results: speed, pressure, temperature on the part, on a slice through the fluid and along flow lines; the force on the part split into pressure and friction, the drag coefficient, the heat of every condition, a mass balance and a heat balance, a node probe; and a verdict on the heat balance (OK under 10 %, COARSE under 35 %, CHECK above) written in plain words under the numbers.

## How good the numbers are

Read this before trusting a number. The method is first order and laminar.
- The **mass balance** and the **flow field** are the solid part: the self-check below reproduces plane Poiseuille flow (centre-line speed 1.473 against 1.5, pressure gradient 0.3 % off), the flow in a round pipe with five elements across the radius (pressure gradient 3.5 % off, wall drag 4.2 % off) and the heat taken up by a fluid between heated plates (outlet temperature 0.8 % off).
- The **heat balance, the heat of a face and the drag coefficient depend on the mesh**, and not slightly. On the test example's own mesh (2,981 nodes, elements of 2 mm at the part) the heat balance misses by 22 %; in an earlier series on the same example at element sizes 3, 2, 1.5 and 1 mm it missed by 27, 23, 19 and 15 %. The window says COARSE or CHECK and what to do (smaller elements at the part). On a well-resolved channel it closes to 0.8 %.
- The drag coefficient of a 10 mm cube in air moved from about 1.4 to about 1.8 between two meshes I tried. The self-check does **not** compare the drag of the cube with a reference value; it checks that the drag doubles when the speed doubles (Stokes flow), that the flow along +y gives the same drag as along +x, that there is no force across the flow and that the front face has the higher pressure.
- It is right for slow flows: Reynolds number up to about 100 to 150 for a blunt part. There is no turbulence model and no transient, and a wake that sheds (Reynolds above about 200) is not something it can show. The window shows the Reynolds number and the share of the box that the part blocks, and warns.
- Nothing here has been compared with commercial CFD or with a measurement, and nothing has run on real Windows: everything so far ran headless in a Linux sandbox.

Not in this version: assemblies (one part only: the window says so and the Workbench block stays incomplete), turbulence, a flow that changes with time, a moving part, buoyancy, a parametric study, patches of a face, conjugate heat transfer, and the Coupled Physics block does not take 3D fluid yet (pressure on a 3D structure, heat exchange with 3D Thermal and a structure that moves the flow are planned as the next step).

## In the Workbench

3D Fluid Flow is a block of the group Analysis Systems: wire a Part into its Geometry cell, Refresh copies the part into the analysis, double-click Setup to open the window (the flow, the box, the conditions, the mesh), Update solves. The setup is saved in the project; meshes and results are not (Update works them out again). Geometry comes only from a wire; one part per block. Save as ... on the block writes a `.gpw` project folder that opens on its own in the program.

## Testing it (and what to send back)

1. Open the **3D Fluid Flow** tab (File > New 3D Fluid Flow). Press **Load test example** (Test and diagnostics section): you choose a folder, the program builds a test project in it and opens it: a 30 by 20 by 16 mm block with a 10 mm hole through it, in air at 0.05 m/s (Reynolds number about 99), a hot top face (60 °C), a heated side face (50 W/m²) and an insulated bottom.
2. **Solve**: 14,472 tetrahedra, 2,981 nodes, 8,550 unknowns, converged in 24 steps; about 13 seconds on the 2-core sandbox I used (less on a modern desktop, I expect; I have not measured one).
3. **Run self-check**: solves six small problems with known answers and prints PASS or FAIL beside each number (31 rows: uniform flow, flow between two plates, flow in a round pipe, heat put into a flowing fluid, the iterative solver against the direct one, and a cube in air), and, once the example is solved, checks its result as well (45 rows in all). About 17 to 19 seconds here. All rows passed here; the self-check is built so that it can fail (the test suite plants a wrong constant in the solver and makes sure it is caught).
4. **Diagnostics report...**: one text page with the computer and program version, the geometry, the mesh size and quality, the setup in plain numbers, the time of every stage, the solver and its convergence, the self-check and every message the window gave (errors in full). It has **Copy to clipboard** and is also saved in the project folder as `diagnostics.txt` every time it opens.

Send the report (or the file) when something fails, is slow or looks wrong.

Files: `cfd3d_mesh.py` (the box of fluid around the part and the channel / pipe meshes of the self-check, no Qt), `cfd3d_flow.py` (the solver: flow, temperature, forces, balances, no Qt), `cfd3d_model.py` (the setup and its run, the checks before and after, no Qt), `cfd3d_view.py` (slice, flow lines, field on the part), `cfd3d_tab.py` (the window), `cfd3d_example.py` (the test example, the self-check and the report text), `cfd3d_ext.py` (registers the project kind). The report builders shared with the other 3D windows are in `dev_addons/solid_fea/solid_diag.py`.
Tests (repository root): `test_cfd3d_flow.py` (the solver on problems with known answers), `test_cfd3d_model.py`, `test_cfd3d_tab.py` (the window, the example, the self-check, the report), `test_wb_fluid3d.py` (the block in the Workbench).
