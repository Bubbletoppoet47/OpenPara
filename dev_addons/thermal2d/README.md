# 2D Thermal (workshopping)

Heat conduction in a flat plate, as another kind of Simulation project (`.gph`, like 2D FEA / 2D CFD / 3D FEA: sketch in, regions, conditions, mesh, solve, results, probes, report, parametric study).

What it solves (everything is stored and solved in SI and kelvin; the unit system of the program decides only what is shown):
- steady and transient conduction (theta method: Crank-Nicolson or backward Euler), quadratic (T6) or linear (T3) triangles;
- conditions: fixed temperature, heat flux, heat flow, convection (h and fluid temperature), radiation to the surroundings (emissivity and surroundings temperature; Newton iteration), and Insulated (no heat through the edge: an adiabatic wall or a line of symmetry; the same maths as a heat flux of zero, drawn as a hatch outside the edge). An edge with no condition at all is insulated too; a note under the conditions table counts those edges;
- a material for every region, all assigned in Material and analysis: a table of the regions with their material, and the box of the selected region to choose from the thermal library or type k, density and specific heat ("(custom values)"); "Use for all regions" copies one region's material to the others. Regions whose part has no thermal values carry the default material and are marked "choose a material" until you pick one. The part's own Edit Material dialog is not changed. Projects saved before this keep their results: the old single material is copied into the regions that had none;
- heat generation per region (W/m3, in Geometry next to the region list, where regions are also switched in or out of the model);
- optional heat loss from the two flat faces of a plate (convection and radiation);
- results: temperature, heat flux, heat through every condition, energy balance (in - out - stored), probes, a time slider for transient runs;
- heat flow (Results > Heat flow): moving tracer particles made and drawn like the tracers of the 2D CFD (700 particles, white trails and dark dots, the same pacing and lifetimes), carried along the heat flux; they start again at the edges where heat enters the body. Or arrows on a grid. Works for a steady result and for every picture of a transient run (also while Animate plays). Display only: the speed shows the flux compared with the strong flux of the picture, it is not a real speed. The exported animation file does not contain the tracers. Animate itself needs a transient run; a steady result says so and points to Heat flow.

Not in this version: axisymmetric, contact resistance between regions, thermal stress (temperature feeding 2D FEA), view-factor radiation, temperature-dependent properties, automatic mesh refinement.
Material values are typical room-temperature numbers taken as constant: check them against your own source. Nothing here has been compared with commercial software or tried on real Windows.

Files: `thermal_fem.py` (maths, no Qt), `thermal_units.py`, `thermal_mat.py`, `thermal_store.py` (saved tab in another unit system), `thermal_tab.py` (the tab), `thermal_flow.py` (tracers and arrows, no Qt), `thermal_study.py` (parametric studies), `thermal_ext.py` (registers the project kind).
Tests (repository root): `test_thermal_fem.py`, `test_thermal_tab.py`, `test_thermal_regions.py` (materials per region, Insulated), `test_thermal_flow.py` (heat flow), `test_thermal_addon.py`.
