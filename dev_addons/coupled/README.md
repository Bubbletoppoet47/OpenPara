# Coupled Physics (workshopping)

A heat analysis and a stress analysis of the same geometry, solved together: the heat problem first, its temperature field handed to the stress problem, then the stress problem with that temperature as a load of its own. Both 2D or both 3D. It is a block of the Workbench (`.gpx` project folder: `simulation.json` + `state.sim`), not a separate way of setting problems up.

## How it works

1. In the Workbench, wire a **Part or Assembly** block into a 2D or 3D **Thermal** block and into a 2D or 3D **Static Structural** block (the same dimension, the same geometry block), set each up in its own window as usual: the heat conditions; the supports and the material of the stress analysis, with its **thermal expansion coefficient** (1/K) and **reference temperature** (°C). The stress analysis needs supports but **no mechanical load**: the temperature is its load. A stress analysis may also have loads; they act together with the temperature.
2. Add a **Coupled Physics** block (Analysis Systems in the toolbox) and wire the Setup cell of the thermal block and the Setup cell of the structural block into its **Physics** cell. Refresh checks that there is one of each, the same dimension and the same geometry block, and says in plain words what is wrong when there is not.
3. **Update** (or Solve in the Coupled Physics window): the heat analysis is solved, every node of the stress mesh takes the temperature at its place in the heat mesh (the two analyses keep their own meshes; the temperature is **interpolated**, never extrapolated), and the stress analysis is solved with the thermal strain `eps0 = alpha (T - Tref)` of every element.
4. The window shows the temperature range and average, the largest displacement and von Mises stress, what was handed over (points, direct copy or interpolation, the range on both meshes) and four checks:
   - **Nothing extrapolated** (stops the result): no stress-mesh node lies outside the heat mesh;
   - **Every point found** (stops the result);
   - **Average temperature kept**: the average of the stress mesh differs from the average of the heat mesh by less than the tolerance (2 % of the temperature range by default; a box in the window);
   - **Stress solve used the field** (stops the result): the stress analysis reports the temperatures it was given.
   The temperature and stress pictures are in the Results pages of the two analyses; they hold this solve.

## Thermal expansion in the analyses (also usable without Coupled Physics)

- A material has an expansion coefficient `alpha` (1/K) and the analysis a reference temperature (°C, the temperature at which the body is free of thermal stress). The library materials carry typical values (steel 12e-6, aluminium 23e-6, ...); the 2D and 3D Static Structural windows show both numbers in their Material section.
- 2D (plane stress, plane strain, axisymmetric) and 3D (tetrahedra and hex-dominant) take a temperature field as a load. Not in the nonlinear 2D solver (with the linear solver also ticked, the linear result is shown with a WARNING line; with the nonlinear solver alone the solve is refused) and not with the adaptive-mesh loops (2D and 3D refuse and say so): the temperature is never left out silently.

## Known answers

- Free bar, one end 100 °C and the other 20 °C, `alpha` 12e-6, reference 20 °C: mean temperature 60 °C, the far end grows `alpha (Tmean - Tref) L` = 0.048 mm for L = 100 mm, and the stress stays small.
- The same bar held at both ends: the stress along it is `-E alpha (Tmean - Tref)` (about -96 MPa for steel), and it moves `alpha (Tmax - Tmin) L / 8` = 0.012 mm at most.

## Testing it (and what to send back)

1. In the Workbench press **Load Example Project**. It now holds **Bar heating** (3D Thermal), **Bar growth** (3D Static Structural: three symmetry planes, no load) and **Bar thermal stress** (Coupled Physics of the two) next to the other blocks, and a known answer of 0.048 mm for the far end of the bar.
2. **Update Project** solves everything, the coupled block included. Open **Bar thermal stress** (double-click its Results cell): the checks list shows PASS or FAIL for each check and for the known answer, with what was found beside what was expected.
3. **Self-check** (in the window): solves problems with known answers on stand-in analyses (a linear temperature handed from one mesh to another, 2D and 3D, exact; no value outside the range of the heat problem; the average kept) and then tries the checks the wrong way round: a stress solve that is not given the field, a heat problem of 3D with a stress problem of 2D, a stress mesh far from the heat mesh. Each must be caught; each line shows PASS or FAIL. A self-check that cannot fail is worth nothing: `test_coupled_tab.py` breaks the hand-over on purpose and requires FAIL.
4. **Diagnostics report**: the members, the options, the last solve (times, transfers, checks, the known answer), the self-check, what the two analyses said last and what this window said (errors in full). It is saved as `diagnostics.txt` in the project folder every time it opens. Send it when something fails, is slow or looks wrong.

## Not in this version (said plainly)

- **Setups stay in the windows of the two analyses.** The Coupled Physics window drives them; there is no single window with tabs for heat and stress, and the Solve of a wired analysis is not locked (solving it alone is still possible).
- **One way only**: heat to stress. The stress does not change the temperature. A transient heat analysis is used at its final state.
- Parametric Study and Optimization of the Coupled Physics block: not yet (a study of one of the two analyses works as before).
- Pressure and heat-exchange transfers with fluid flow, structure moving the flow (next versions).
- The temperature and stress pictures are in the two analyses' windows; the combined result shows numbers and tables.
- A stress analysis of a 3D body reproduces a uniform temperature stress closely; on the quadratic hex-dominant mesh a fixed end face shows a local end effect (its median stress is right, its maximum is not). The gradient is exact at the level of one element.
- No standalone uniform-temperature load (use the heat analysis with a fixed temperature on every face). `alpha` is in 1/K and the reference temperature in °C only; the Edit Material dialog for parts does not edit `alpha` (the Material section of the analysis does).
- The known-answer row is for 3D bodies; a 2D problem says so instead of showing PASS.
- Nothing here has been compared with commercial software or tried on real Windows: everything so far ran headless.

Files: `coupled_engine.py` (the hand-over and the loop, no Qt), `coupled_members.py` (what the real 2D and 3D windows give to the loop), `coupled_check.py` (the self-check, no Qt), `coupled_tab.py` (the window), `coupled_ext.py` (registers the project kind). The Workbench block is `dev_addons/workbench/wb_coupled.py`.
Tests (repository root): `test_coupled_engine.py`, `test_coupled_members.py`, `test_coupled_tab.py`, `test_wb_coupled.py`, `test_wb_example.py`, `test_thermal_strain2d.py`, `test_thermal_strain3d.py`, `test_material_expansion.py`.
