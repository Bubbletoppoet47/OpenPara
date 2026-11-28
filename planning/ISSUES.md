# OpenPara: issues and changes, by add-on

This is the running list of what is **open** (to fix or finish) and what is **done**, for each add-on and part of the program. It lives in the repository so that
every chat and every build sees the same list.

**Where this file is not shipped:** `planning/` is not copied into the installer, and a push that changes only files in it does not start a build.

## How it works

- Every item has an ID: the area's letters and a number (`TRN-3`). IDs are never reused. Write them in commit messages (`Fixes TRN-3`).
- **Open** items say what is wrong or missing, who reported it and when, and **how we will know it is fixed** (a test, or something to look at on a screenshot).
- **Limit** is an item we know about and have chosen not to fix yet; it is not a bug.
- When an item is fixed it moves from *Open* to *Done* in the **same commit** as the fix, with that commit's short hash (add it right after the commit).
- *Done* also records changes that were not reported as issues, so that each area's list says what changed and when. Newest first.
- The history of one add-on is also in git: `git log --oneline -- dev_addons/coupled`.
- Design choices and mock-ups are in `planning/design/` (start with its `README.md`), and an item can point to them.
- Dates are the day it was reported or done (Phoenix time).

Areas: ANN Annotator, TRN Trainer, WB Workbench, DRW Drawings, VIS Visualize, CPL Coupled Physics, VW 3D view (look and selection), SLC Slicer, PA printed-part analysis, GEN whole program and tests.

---

## ANN: Annotator

### Open

- **ANN-2** The Analyse tab is still in the Annotator. Model testing now has its own block in the Workbench (`d37321a`), but the Analyse tab stays until the tester does everything Analyse did. *Fixed when:* Ian confirms the Model testing block covers it, and then the tab is removed from the Annotator and its test is moved.

### Done

- 2026-11-26 `8b39da8` ANN-1: the Annotator compared with the redesign board and changed, built locally, **not pushed, waiting for Ian to look**. Found: a project whose frames were all confirmed opened with an empty list and a dark picture area with nothing in it (probably what the screenshot showed); it now opens with every frame listed and the first one open, and a picture area with no picture says so. Changed to match the board: the box labels are tabs of the class colour with the distance to one decimal, the LiDAR caption is a chip (it was white text on a light sky), 4,840 with a thousands separator, the frames of a set are named by their number (000001), the set box reads `20261125_184611   3 / 4`, the status line reads `name | 3 boxes (3 with distance) | annotated | 4 images in project`, the bar `Lab walk · 4 images`, `No AI model loaded`, `Clear & retry AI`. Left as it is, for Ian to say: the list opens on To do (the board shows All pressed); the picture area is `#1e1e1e` (the board's is a bluer `#20262f`, and the palette has no dark grey near either); the LiDAR dots are smaller than the board's. Test: `test_annotator_look.py`. Ian's own screenshot was not available to compare, only the board.

---

## TRN: Trainer

### Open


### Done

- 2026-11-26 `6dcdb6a`, `404d675` TRN-1 and TRN-2: the Trainer window to boards 2 and 3 and the PDF's options, built locally, **not pushed, waiting for Ian to look**. Four pages (Data, Model, Train, Setup) in place of five; the kind (Detector, Detector + distance, Distance: classic, Distance: network) is four ribbon buttons; the Model page has the layers table (+ layer, - layer, neurons typed in, the parameters of each layer: 4 x 32 with batch norm = 3,681 as on the board), the neurons per layer as bars, and each option of the PDF by itself (loss, optimiser, learning rate, momentum, weight decay, activation, initialisation, target, epochs, stop early, batch size, batch norm; a recipe is a preset of them and only what differs is kept in the project), and the tuning of the five classic regressors. The Train page has seeds, learning rates (the recipe's, the specification's grid, your own), the number of runs, the list of runs with a progress bar, the run now, three live charts (error, gradient norm of the first and last hidden layer, saturated and dead units) drawn from `live.json` while the job trains, and Stop that first finishes the run that is going. Differences from the boards, for Ian to say: (1) a small list *Models made here* (right-click: export, remove) stays on the Train page, the boards moved models to Trained models; (2) Start and Stop are in the ribbon of both the Model and the Train page; (3) the *Shape* read-out says `32 x 4` or `64 - 32 - 16` where the board says `8 : 1`, which I could not read; (4) five rows the PDF asks for are not on the board (momentum, activation, initialisation, target, batch size); (5) the log is a tab beside the live charts, the finished runs' charts a third. Tests: `test_nn_live.py`, `test_trainer_model_qt.py`, and the Trainer, np_net and chart tests follow the new window.
- 2026-11-26 `612d624` A Charts tab for the runs of the distance network.
- 2026-11-26 `8cc6d65` Two distance-only model types in the window: formula and regressors, neural network.
- 2026-11-26 `7c8b3cc` A job that trains the distance network on any rung of the ladder.
- 2026-11-26 `4a4952e` A hand-written NumPy network for the distance ladder.
- 2026-11-26 `2094ed2` Distance-only models (formula, log-linear, k-NN, boosting, Gaussian process) with a shared scoring harness.
- 2026-11-26 `88ab86b` The Trainer window in the Annotator's layout; models exported and imported; a block of the Workbench.

---

## WB: Workbench

### Open

*(nothing open)*

### Done

- 2026-11-26 `5df8128` (local, not pushed) **WB-1** A STEP (`.step`, `.stp`) or STL file dropped on the Workbench, or taken by Import, becomes a block. STEP with several solids asks each time: one Assembly block, one Part block per solid, or one Part block with all the solids. An STL is a mesh body (a closed surface, repaired first; the triangles are kept, and the solid with a flat face for every triangle is made from them, with no limit). It wires into an analysis and a drawing. *Not done:* wiring into a Visualize node (it takes no wire until VIS-1); making the solid of a large mesh is slow (about 20 s for 32 000 triangles), and the mesh is not meshed straight from its triangles by the analyses (they use the solid). *Test:* `test_wb_step_stl.py`.
- 2026-11-26 `d0aab72` A Trainer block's Setup cell asks for what its model type needs.
- 2026-11-26 `a25d364` Model testing takes distance-only models, with boxes from a detector, and compares runs.
- 2026-11-26 `684ccda` Distance-only models live inside the `.opara` and in the Trained models list.
- 2026-11-26 `d37321a` A Model testing block (the Annotator's Analyse tab as a block of its own).
- 2026-11-26 `b03f554` A Trained models block: one list of every model.
- 2026-11-26 `01570a9` The Annotator's Dataset and Distances wired into a Trainer block.

---

## DRW: Drawings

### Open

*(nothing open)*

### Done

- 2026-11-26 `5592b67` (local, not pushed) **DRW-1** and **DRW-2** Every view has **Turn left 90°** / **Turn right 90°** (ribbon and the view's details): the picture turns on the sheet like a sheet of paper, the orientation label stays, four presses give the original back, left and right cancel, the dimensions, marks, balloons and note leaders of the view turn with it, only that view turns, the turn is kept in the file and in undo. A projected view is a model view of its own once it is put down (own orientation, scale, style, position, turn; nothing else moves with it); a model that changes still draws every view again; an old drawing opens with its projected views free, where they were. *Tests:* `test_dr_turn.py` (new), `test_dr_model.py`, `test_dr_annot.py`, `test_dr_tab.py`, `test_dr_view_panels.py`. *Mine:* choosing an orientation (or the one the view already has) puts the view upright again; a view projected from an Isometric view is called *Custom*.

---

## VIS: Visualize

### Open

- **VIS-1** Every result window has its own Animate and Export animation; Ian wants a Visualize node to do the exporting. Reported by Ian, 2026-11-26. *Decided with Ian, 2026-11-26:*
  1. **One input.** A Visualize node has one input and cannot take several. Coupled Physics is how two results are shown together: its result goes into the one input.
  2. **Two modes, by what comes in.** A part, geometry or assembly: it works like today's render studio (looks, lights, floor, environment, cameras). A simulation result: it draws the part the way the simulation windows draw it now (in a vacuum, no lights, no environment), with rotation as below.
  3. **It keeps its own copy of the result, inside the `.opara`** (the size limit of the project file is already raised). On opening a project it does not update itself. To change what it shows: run the simulation again, then Update the Visualize node.
  4. **It takes what is on screen in the simulation window.** If the window is set to Displacement when the node is updated, the node can animate and export displacement only; it cannot switch to another field. To see another field: set the window to it, then Update the node.
  5. **Preview stays, export moves.** The simulation windows keep the basic view and the Animate preview. Exporting pictures and animations (GIF, WebP, MP4 ...) moves to the Visualize node, which gets that one job and makes the simulation windows simpler.
  6. **Rotation, in the way SolidWorks does it.** The person sets how long the animation runs and how many rotations it has (none gives a still picture or a fixed view, in a view they choose), and the axis of rotation (X, Y, Z or a direction they enter). The rotation runs on the same timeline as the result animation. Ian said this may change later.
  7. **Transient runs.** The node keeps every frame the simulation window holds, with no new cap, and shows what the frames add to the size of the project file.
  8. It works for 1D, 2D and 3D results and for Coupled Physics.
  9. **Style.** The node follows the program's theme and palette (GEN-4).
  *Designs:* drawn 2026-11-26, five boards in `design/visualize/` (Workbench block, result window, render studio, Export, what moves out of the simulation windows). Waiting for Ian to approve; four questions for him are in its README. Nothing is built.
  *What the code is today:* The Visualize add-on (`addons_src/render/`) is a picture-and-video studio for a part or assembly working on its own copy of the model in a `.gpv` folder, with no idea of a result field. In the Workbench `visualize` is a one-cell block (a document, no inputs). Animate and Export animation are in `beam_tab`, `physics_tab` (2D FEA), `cfd_tab`, `thermal_tab` (2D heat), `solid_tab` (3D FEA), `thermal3d_tab`, and Save animation in `coupled_viz`; they share `addons_src/simulation/anim_export.py` (WebP, APNG, GIF, MP4, PNG pictures). A result window draws a frame from the result and the chosen field (`field_values(ramp)` in 3D FEA), so what the node must keep is the field on screen, the shape it is drawn on and the frames of a ramp or a transient run. *Fixed when:* the designs are drawn and approved (they go in `planning/design/`), and then it is built in steps, each with its own item.
### Done

*(nothing recorded yet)*

---

## CPL: Coupled Physics

### Open

- **CPL-1** *(limit)* The air and tracers of a 3D flow are not drawn in the Viz tab; the picture says so when the block has a 3D flow.
- **CPL-2** *(limit)* 3D analyses are not shown inside the Coupled Physics window; they keep their own tabs.
- **CPL-3** *(limit)* The heat-flux tracers of a 3D part are bent with a displacement blended from the nearest points of the surface, not a solved displacement of the inside. It is for the picture only. The part is drawn faded while the tracers are on.
- **CPL-4** The Viz tab has only been tried in a headless Qt. Nothing of it (the 2D heat picture, the 3D picture, the tracers) has been seen on a real screen or on Windows. Design: `design/combined-physics/`. *Fixed when:* Ian has looked at the Viz tab of the example project on his computer and said what is off.

### Done

- 2026-11-26 `228a685` (local, not pushed) **CPL-5** The Viz tab no longer turns the part by itself: the box, `turn_on`, `camera_at` and `turn_at` are gone, and the camera is the same for every frame of the animation, of a saved animation and of a saved picture (the view the person set). Tests: `test_coupled_viz3d.py`, `test_coupled_viz3d_core.py`. Full rotations and a picked view come with the Visualize node (VIS-1).
- 2026-11-26 `970764c` Viz: heat-flux tracers for a 2D heat and stress solve with no flow (before it was not drawn), and inside a 3D part. Tests: `test_coupled_viz_heat.py`, `test_coupled_viz3d_tracers.py`.
- 2026-11 `e9a58d7` Viz draws a 3D heat and stress solve (software z-buffer, no OpenGL).

---

## VW: 3D view (look and selection)

Design: `planning/design/viewport/README.md`. Asked for by Ian, 2026-11-27.

### Open

*(nothing open)*

### Done

- 2026-11-27 `93808e9` **VW-4** Supports, loads and heat on picked edges and points in Structural and Thermal 3D. Structural: fixed or prescribed displacement on faces, edges and points; a force on faces **or** edges (shared by area or by length) or on points (shared equally); pressure on faces only. Thermal: temperature on faces, edges and points; heat on faces **or** edges **or** points. A condition on an edge goes to the mesh nodes along it (corner nodes on the curve plus the mid-edge nodes between them, weights L/6, 4L/6, L/6 for the quadratic mesh and L/2 for the linear one); if the mesh has no nodes along the edge, or only along part of it, the window says so and does not approximate. One edge or point alone leaves the part free to move, and the solve says so. CFD keeps Face and Body. The edge and point marks are drawn over the part; projects from before open as they were. Tested in `test_view3d_sim.py` with solves (equilibrium; a cantilever held on four edges, 0.2157 mm against 0.2000 mm from beam theory; heat balance closes; a held node is exact). Design: `design/viewport/README.md`.
- 2026-11-27 `93808e9` **VW-3** The Structural, Thermal 3D and CFD 3D windows have the General / Point / Edge / Face / Body bar beside Show. A click replaces the selection, Ctrl or Shift adds; Body picks a whole part (all its faces take the selected colour and its rows are selected in the material and element-size tables; a body cannot carry a support or a condition). CFD has General, Face and Body (Point and Edge greyed with the reason). Tested in `test_view3d_sim.py`.
- 2026-11-27 `93808e9` **VW-2** A General / Point / Edge / Face / Body selector beside Show in the part and assembly windows. Each kind has its own pick distance (Settings: Point 14 px, Edge 10 px, General 4 px as before); Body picks a whole part or component and its hover outlines the whole body. The Faces / Edges / Points toggles of the Mate panel are replaced by the bar. Tools that pick several kinds take the bar back from Body to General. Tested in `test_view3d.py`, `test_mate_panel_ui.py`, `test_lab_highlight.py`.
- 2026-11-27 `93808e9` **VW-1** One neutral 60 % grey (#999999) in place of the colours (an assembly's six in rotation), an orange (#ff7300) outline under the cursor in the part window and the assembly (the assembly's fill-on-hover is gone), a blue (#00b4ff) fill on the selected face, and a soft shadow on the floor under the part. All of it is in File > Settings > 3D View (hover and shadow on by default, three colours); a colour set on a part or component still wins. New file `view3d.py`; lighting a little brighter. The shadow is a picture (not drawn above about 900 000 triangles, and not in the simulation windows). The three colours are registered in `design/theme/palette.json`. Tested in `test_view3d.py`, `test_asm_baked_outlines.py`.

---

## SLC: Slicer (Orca Slicer's engine inside OpenPara)

Design: `planning/design/slicer/` (the plan, `OpenPara_Slicer_Integration_Plan.pdf`, Draft 1, 2026-11-28). Asked for by Ian, 2026-11-27; he said on 2026-11-28 to go on from the plan into the build and push to `dev`. The add-on stays in `NOT_RELEASED` until SLC-12. Sizes and what each item needs are in chapter 12 of the plan.

### Open

- **SLC-0** Window boards: pictures of the plate, the generated settings pages, the object list and the preview, for Ian to approve. *Fixed when:* Ian has approved or changed them. Nothing waits for it except SLC-6.
- **SLC-1** Engine build: the cut list as patch files, a build file for the cut-down engine, built on Linux and then on a Windows runner; a cube sliced from a C++ test program. The gate for everything else. *Fixed when:* the engine links and slices on both systems and the first parity comparison (one cube, one preset) matches Orca's own. *Now (2026-11-28):* **Linux done.** Pinned to Orca Slicer v2.5.2; three patches; the engine links and slices; `tests/parity.py` finds the G-code line-for-line identical to Orca's own program on 13 cases and equal in totals on fuzzy skin (random in Orca itself). **Left:** the Windows build (workflow `slicer-engine.yml`, to be run once from the Actions page, `workflow_dispatch` only) and more parity cases (several objects, multi-material, painting). Not closed until the Windows build links.
- **SLC-2** The module `orca_core`: bindings (a whole job, a staged session), result tables (`paths`, `moves`, `estimate`), the worker process, progress, cancel, errors. *Python side done 2026-11-28 (result tables, errors, `Job`, the worker process with progress, cancel, time limit and crash detection; tested with a stand-in backend); the bindings to Orca's code are not.* *Fixed when:* parity tests T1 and T2 pass on the 12 test models on both systems, and T8 (crash safety) and T9 (cancel and progress) pass.
- **SLC-3** Profiles: Orca's bundle loaded through the engine's own loader; option definitions and the settings layout exported; the Elegoo bundle selectable. *Linux done 2026-11-28: `orca_core.profiles` (Orca's vendor files, folder or zip; `inherits` across vendors; Orca's compatibility rule incl. conditions; user presets; `settings(machine, process, filament, overrides)`), `tools/build_profiles.py` (Elegoo + library + Custom = 2.1 MB), `test_orca_core_profiles.py`; a cube sliced from the three Elegoo names is identical to Orca's own G-code. Not done: the option definitions and settings layout exported for the window (SLC-6/7).* *Fixed when:* T3 and T4 pass and `Profiles.open().settings("Elegoo Centauri Carbon 0.4 nozzle", ...)` works.
- **SLC-4** The add-on `addons_src/slicer`, in `NOT_RELEASED`: the catalog entry; the download of the engine wheel and the profile assets with sha256. *Skeleton done 2026-11-28 (manifest, catalog entry, `slicer_engine.py`, tests); the download is not, it needs SLC-2's wheel.* *Fixed when:* it installs in the Playground build and imports the module on a clean Windows machine.
- **SLC-5** The Workbench block: the `slicer` kind and its adapter, the wires, staleness, saving and reopening, the `toolpaths` kind. *Fixed when:* the block tests of plan 7.6 pass and Part, Slicer, Update gives a result in the block.
- **SLC-6** The window, first version: plate, one or more objects, the three preset boxes, generated settings pages, Slice, Preview, Export G-code. *Fixed when:* workflow steps 1, 2 and 5 to 8 of plan 8.2 can be done and a Part sliced for the Centauri Carbon prints.
- **SLC-7** The enable and disable rules lifted out of Orca's GUI code. *Fixed when:* changing a setting enables, disables and updates others as in Orca, on 50 recorded cases.
- **SLC-8** Thumbnails, user presets, Import from Orca. *Fixed when:* the Centauri Carbon shows a picture and a changed preset is saved and reloaded.
- **SLC-9** Object list: modifiers, per-object and per-part settings. *Fixed when:* step 3 of plan 8.2 can be done.
- **SLC-10** Painting: support enforcer and blocker, seam; then fuzzy skin and multi-material. *Fixed when:* step 4 of plan 8.2 can be done for supports and seams.
- **SLC-11** Arrange, auto-orient, several plates, calibration pages. *Fixed when:* each works as in Orca.
- **SLC-12** Release: `slicer` out of `NOT_RELEASED`, a user guide, about page and notices, licence reading confirmed. *Fixed when:* a normal OpenPara offers the add-on and Ian has printed with it.

### Done

- 2026-11-28 **SLC-2 (bindings, Linux)**: `engines/orca_core/bindings/orca_core_module.cpp` (`_orca_core.slice`), `python/orca_core/_engine.py`, `test_orca_core_engine.py`, `tests/slice_3mf.cpp` with `--settings`, `tests/parity.py` now runs every case twice (project settings and preset files, all identical). Paths and moves come from Orca's G-code processor, so they are what the printer is told; path volume equals the G-code's extrusion to 0.2 %. **Gaps, to be done:** the `object` column is 0 for every path (the processor labels objects for Bambu printers only; `gcode_id` does not line up with the final file after Orca inserts lines), `overhang`, `curve` and `z_contoured` are zero, no wheel or Windows build yet.
- 2026-11-28 **SLC-2 (Python side)**: `engines/orca_core/python/orca_core/`: `Paths` (the plan's columns; `layer_slice`, `object_slice`, `role_slice`, lengths and volumes), `Moves`, `Estimate`, `SliceWarning`, `Result` (saved to and loaded from a folder), the typed errors (`ConfigError`, `SliceError`, `SliceTimeout`, `Cancelled`, `WorkerCrashed`, `EngineMissing`), `Job.add_object` (refuses a mesh with no triangles, a NaN or an index that points nowhere, in words), and `worker.py`: the engine runs in its own process; the caller polls its progress, cancels softly (a flag the engine checks) and then hard (the process is ended after a grace time), has a time limit, and a crash (an exit without a word, or a real read at address 0) comes back as `WorkerCrashed` with the exit code and the last progress line, not as a closed OpenPara. `test_orca_core_results.py`, `test_orca_core_worker.py` (a stand-in backend: the compiled engine is not needed; T8 and T9 are checked in this form, not yet with the real engine). **Not done:** the bindings (`_orca_core`), `orca_core._engine`, the hook that records the print order, progress from the real `Print`, the real cancel flag.
- 2026-11-28 **SLC-4 (skeleton)** (8ed05d8): `addons_src/slicer/` with `addon.json` and `slicer_engine.py` (finds the engine module `orca_core` and says in words why it cannot slice when it is missing); `slicer` is in `addons.NOT_RELEASED` and `CATALOG`, the add-on tests and the Playground and release workflows know it. No menu, tab or block yet. `test_slicer_engine.py`. `test_addons.py`, `test_release_files.py` and `test_release_set.py` fail on `dev` before and after this (GEN-2); in a copy with the Trainer's version set to the program's they all pass with the new add-on.
- 2026-11-28 **SLC-1 (started)** (8ed05d8): `engines/orca_core/` (`ORCA_PIN`, `cuts.txt`, `tools/gen_sources.py`, `tools/prepare_orca.py`, `CMakeLists.txt`, `patches/0001`, `0002`, `tests/slice_cube.cpp`). **Finding that changes the plan's chapter 6:** cutting the CAD kernel is not "one deleted include line and one guarded function" as drafts 1 wrote it. `Format/STEP.hpp` has to be guarded (patch 0001), `Model.cpp` has to leave out its STEP, textured-mesh, OBJ, glTF, FBX, SVG and DRC readers (patch 0002), and `Format/OBJ.*`, `TexturePainting.*`, `ObjColorUtils.*`, `Format/AssimpImport.*`, `Format/DRC.*`, `Format/svg.*` go too. Eigen has to be 5.0.1 (Ubuntu has 3.4; the GitHub mirror is the source because GitLab is blocked here) and CGAL 6.2. To be written into the plan's revision log when SLC-1 closes.
- 2026-11-28 **Plan written** (Stage 1): `planning/design/slicer/`, 55 pages. Not yet read by Ian.

---

## PA: Printed-part analysis (toolpaths into anisotropic strength)

Design: `planning/design/slicer/`, chapter 10. Accuracy is unknown until PA-5; the plan makes no promise of it. PA-1 and PA-2 do not need the slicer.

### Open

- **PA-7** The mapping's modelling choices, to be checked on real prints (PA-5): the rule of mixtures for sparse infill (it is an upper bound: a lattice that bends is softer, so `phi_power` above 1), no in-plane direction for steep roads (bridges, contoured layers count as plastic only), the smoothing distance, and thermal expansion that does not depend on direction. *Fixed when:* each is either confirmed by the coupon tests or replaced, in the validation report. (Raised 2026-11-28.)
- **PA-6** Typing the constants and axes of an `ortho` material in the 3D FEA tab (the solver takes them from the part's setup already, PA-2). Adaptive meshing and direction-dependent thermal expansion with an `ortho` material are refused, not supported. *Fixed when:* a person can set an orthotropic material in the window and the project saves and reopens it. (Found while doing PA-2, 2026-11-28.)
- **PA-3** The fabric grid and mapping from toolpaths, with a "Print data" cell. *Mapping and its tests done 2026-11-28 on paths made by the tests (see Done); not done: the "Print data" cell, and A5 and A6 on the real paths of a sliced cube, which need the compiled engine.* *Fixed when:* A5 and A6 pass and a sliced cube gives a sensible field in the view. Needs SLC-2.
- **PA-4** Bond quality, the failure index, result views, printed-material entries in the library. *Fixed when:* the index and its direction show in Results and the project saves and reopens. Needs a working slicer.
- **PA-5** Coupon tests R1 to R3, calibration of the constants, a written validation report. *Fixed when:* the report states the error, whatever it is. Needs a working slicer and a printer.

### Done

- 2026-11-28 **PA-3 (mapping)**: `dev_addons/solid_fea/print_fabric.py`: `Fabric.from_paths` puts the plastic volume and the direction of every piece of a printed path into small cells (z is the top of the road, as Orca writes it; supports, skirt, brim and prime tower are left out), `element_stiffness` gives every element of a mesh its (6, 6) stiffness (in `g["D21"]`, the form the solver takes): plastic and directions are smoothed (a Gaussian) and divided by the smoothed mesh volume, so the surface of the part does not thin the plastic; the stiffness is `phi**p` times the volume-weighted average of the road stiffness turned to each road's angle, which is exact for any mix of angles because a turned matrix has only five terms (1, cos2t, sin2t, cos4t, sin4t) and so only five sums per cell are stored. `p` (default 1: rule of mixtures) and the smoothing distance are parameters, not results: the real rule is for PA-5 to calibrate. The setup takes a `"printed"` material (`fabric` file or object, `constants`, `transform`, `sigma`, `sigma_z`, `phi_power`) in `solid_model.py`; refused in words: missing or unreadable print data, bad constants or transform, print data that does not cover the part (more than 25 % of the elements with no plastic around them), together with `ortho`, in the adaptive loop, in an assembly. Tests: `test_print_fabric.py` (the harmonic basis at angles it was not fitted at; A5: 45/-45 infill gives equal in-plane eigenvalues and phi = the density to 0.001, and the surface does not thin it; A6: a wall gives one eigenvalue of 1.000 along the wall; roads along x or y give the material's matrix or its swap; phi to the power p; a transform) and `test_solid_printed_model.py` (a real part through setup, mesh and solve: a bar pulled along x stretches by F L / (A E_x) within 6 % for roads along x, along y and for half the plastic). **The paths in these tests are made by the tests, not by the slicer.**
- 2026-11-28 **PA-1, PA-2** (8ed05d8): `dev_addons/solid_fea` takes a different stiffness matrix for each element group (`g["D"]`, one 6x6 matrix or one per element, or `g["D21"]`, the 21 numbers of each, float32) and the solver uses it everywhere the isotropic one was used (assembly, stresses, thermal load); `fem.orthotropic_matrix`, `stress_rotation`, `rotate_D`, `pack_D`, `unpack_D`; the setup takes an `"ortho"` material (E1, E2, E3, G12, G23, G13, nu12, nu23, nu13 and the directions of the axes, checked before the solve) in `solid_model.py`. Decision for PA-1: the production solver for this is `solid_fea`; `fea3d` is not touched. Tests: `test_solid_ortho.py` (A1 to A4 and A7: tets and bricks, a cantilever against Timoshenko beam theory (2.389 against 2.400 mm), an exact layered patch test (error 4.5e-17), a million matrices in 84 MB and 0.9 s) and `test_solid_ortho_model.py` (a real part through setup, mesh and solve: the strong direction along x, y or z within 6 %, equal moduli give the isotropic answer, refusals). An isotropic project gives bit-identical K, stresses, energy and thermal loads to before, and the 20 existing `test_solid_*` tests pass. A5, A6 and R1 to R3 wait for PA-3 and PA-5.


---

## GEN: whole program and tests

### Open

- **GEN-1** `test_dimstyle.py` and `test_family_look.py` fail on `dev`. They were already failing before the Viz work; the cause has not been looked into. *Fixed when:* both pass on a clean checkout.
- **GEN-2** `test_release_files.py` and `test_release_set.py` fail on `dev` (found 2026-11-26, and they fail the same on a clean checkout). The first stops at `addons_src/trainer/addon.json`, whose version is not the program's version in `version.py` (0.8.6); the second says the released add-ons of the program folder (simulation, parametric) are not put in place. Not looked into further; it may be the tests that are out of date and not the release. *Fixed when:* both pass, or each is changed to say what is now true.
- **GEN-3** Hold the next push of program code until Ian has confirmed the Annotator and Trainer layout. Asked by Ian, 2026-11-26: he thought the layout had not been pushed and might be out of date. Checked the same day: it was pushed. The Annotator ribbon (`b828756`, `85513fc`) and the Trainer window (`88ab86b`) are on `origin/dev`, in Playground builds `dev-0.8.6.139` to `dev-0.8.6.155`; nothing of the Annotator or Trainer is on `main`. A push that changes only `planning/` does not build, so this list and the designs can go up without waiting. *Fixed when:* Ian has said the layout is as he wants it, or has listed what to change (ANN-1, TRN-2), and has said to go on.
- **GEN-5** *(limit)* The program's screens use many near-duplicate colours that are not in the palette: five reds for an error (`#B00020`, `#C00000`, `#B3261E`, `#C0392B`, `#D62828`), several blues for a selection and a link, pure greys for text. About 500 colours, 1,230 uses in 105 files, are kept in `tools/palette_baseline.json`. Found 2026-11-26 while writing the palette (GEN-4). *Fixed when:* one set of status colours (error, warning, done) is chosen from the palette, the others are replaced file by file, and the baseline is tightened (`python tools/check_palette.py --tighten`).

### Done

- 2026-11-26 `5797a28` GEN-4: the theme and palette: `planning/design/theme/` (the palette and a swatch sheet), `tools/check_palette.py` (checks a file, the changed files or the whole program against the palette and a baseline that only shrinks), `test_palette.py`; the checker is a step of "Filing a new design".
- 2026-11-26 `007710d` The approved designs are filed in `planning/design/`: a picture of every board, a note on what each decides, the specs.
- 2026-11-26 `344d096` This list (`planning/ISSUES.md`); a push that changes only `planning/` does not build.
