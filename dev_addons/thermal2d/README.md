# 2D Thermal (workshopping)

Heat conduction in a flat plate, as another kind of Simulation project (`.gph`, like 2D FEA / 2D CFD / 3D FEA: sketch in, regions, conditions, mesh, solve, results, probes, report, parametric study).

What it solves (everything is stored and solved in SI and kelvin; the unit system of the program decides only what is shown):
- steady and transient conduction (theta method: Crank-Nicolson or backward Euler), quadratic (T6) or linear (T3) triangles;
- conditions: fixed temperature, heat flux, heat flow, convection (h and fluid temperature), radiation to the surroundings (emissivity and surroundings temperature; Newton iteration);
- heat generation per region (W/m3), a material per region (looked up by name in a thermal library; the part's own Edit Material dialog is not changed);
- optional heat loss from the two flat faces of a plate (convection and radiation);
- results: temperature, heat flux, heat through every condition, energy balance (in - out - stored), probes, a time slider for transient runs.

Not in this version: axisymmetric, contact resistance between regions, thermal stress (temperature feeding 2D FEA), view-factor radiation, temperature-dependent properties, automatic mesh refinement.
Material values are typical room-temperature numbers taken as constant: check them against your own source. Nothing here has been compared with commercial software or tried on real Windows.

Files: `thermal_fem.py` (maths, no Qt), `thermal_units.py`, `thermal_mat.py`, `thermal_store.py` (saved tab in another unit system), `thermal_tab.py` (the tab), `thermal_study.py` (parametric studies), `thermal_ext.py` (registers the project kind).
Tests (repository root): `test_thermal_fem.py`, `test_thermal_tab.py`, `test_thermal_addon.py`.
