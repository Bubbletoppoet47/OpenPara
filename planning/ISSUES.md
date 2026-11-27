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

Areas: ANN Annotator, TRN Trainer, WB Workbench, DRW Drawings, VIS Visualize, CPL Coupled Physics, GEN whole program and tests.

---

## ANN: Annotator

### Open

- **ANN-1** The Annotator does not look like the approved redesign. Reported by Ian, 2026-11-26, with a screenshot of his Windows install (Annotate, Data, Models, Analyse, Setup tabs; the picture area was dark with no image shown). Design: `design/annotator/`. *Where it is:* the ribbon layout is on `origin/dev` (`b828756`, `85513fc`) and in the Playground builds from `dev-0.8.6.139`; it is not on `main`. So the layout was pushed; what is open is that its details differ from the board. *Fixed when:* we have compared the screenshot with the redesign board, listed the differences, and each is changed.
- **ANN-2** The Analyse tab is still in the Annotator. Model testing now has its own block in the Workbench (`d37321a`), but the Analyse tab stays until the tester does everything Analyse did. *Fixed when:* Ian confirms the Model testing block covers it, and then the tab is removed from the Annotator and its test is moved.

### Done

*(nothing recorded yet)*

---

## TRN: Trainer

### Open

- **TRN-1** The Trainer does not show the more basic neural-network options from the Distance-Model Comparison PDF. Reported by Ian, 2026-11-26, from a screenshot of the Trainer (Data tab, Windows install). Not yet checked: the code for the distance-only model types has been in the repository since 2026-11-26 (`2094ed2` to `8cc6d65`: formula, log-linear, k-NN, boosting, Gaussian process, and the hand-written NumPy network ladder), so either his installed build is older than that, the Model tab does not show them the way the mock-up does, or the PDF asks for options that are not built. Spec: `design/spec/Distance_Model_Comparison_Handoff.pdf`; boards: `design/trainer/`. *Fixed when:* we go through the PDF and the Model tab together, list what is missing, and each option shows in the Model tab on a screenshot from his install.
- **TRN-2** The Trainer does not look like the approved Trainer mock-ups. Reported by Ian, 2026-11-26, with a screenshot (tabs Data, Model, Models, Train, Setup; the Data tab with distortions; Models trained in this project on the right). Mock-ups: `design/trainer/`. *Where it is:* the window is on `origin/dev` (`88ab86b`) and in the Playground builds from `dev-0.8.6.144`; it is not on `main`. *Read from the code, not yet seen on a screen:* the ribbon has five pages (Data, Model, Models, Train, Setup) and the boards have four (Data, Model, Train, Setup); the Models page (export, import, remove a model) is what the boards moved to the Trained models block; the Model page has one button (Continue from a file) where the boards' ribbon chooses the kind of model. *Fixed when:* the differences from the mock-up are listed and each is changed.

### Done

- 2026-11-26 `612d624` A Charts tab for the runs of the distance network.
- 2026-11-26 `8cc6d65` Two distance-only model types in the window: formula and regressors, neural network.
- 2026-11-26 `7c8b3cc` A job that trains the distance network on any rung of the ladder.
- 2026-11-26 `4a4952e` A hand-written NumPy network for the distance ladder.
- 2026-11-26 `2094ed2` Distance-only models (formula, log-linear, k-NN, boosting, Gaussian process) with a shared scoring harness.
- 2026-11-26 `88ab86b` The Trainer window in the Annotator's layout; models exported and imported; a block of the Workbench.

---

## WB: Workbench

### Open

- **WB-1** STEP and STL files cannot be dropped into the Workbench. Reported by Ian, 2026-11-26 22:25: he wants to drag a complete STEP file, or an STL file, from the file explorer onto the Workbench and be able to work with it. Today a drop is read by `wb_import.what_is` and takes only `.gpd`, `.gpa`, `.opara`, an analysis folder and the files of the tools; anything else says "not a kind of file the workbench can import". *What exists:* the Part window already reads STEP (File > Import STEP, `exchange.read_step`, `exchange_dialog.run_import`: one solid becomes a part; a file of several solids asks for a part or an assembly) and the body is kept inside the part. STL is written (`export_stl`) but nothing reads one into a part; `shared/solid.faceted_solid` makes a solid with one flat face per triangle (exact, but slow for a large mesh), and `shared/solid.tet_mesh` can fill a surface mesh with tetrahedra. *Not decided yet (asked of Ian):* what a STEP file of several solids becomes (an Assembly block, one Part block per solid, or ask each time), what an STL becomes (a Part block with a solid made from the triangles, or a mesh body that can be meshed and analysed but not edited with features), and how large the STL files are (a few thousand triangles, or hundreds of thousands). *Fixed when:* a `.step`, `.stp` and `.stl` file dropped on the Workbench becomes a block, it can be wired into an analysis, a drawing or a Visualize node, and a test drops a small file of each.

### Done

- 2026-11-26 `d0aab72` A Trainer block's Setup cell asks for what its model type needs.
- 2026-11-26 `a25d364` Model testing takes distance-only models, with boxes from a detector, and compares runs.
- 2026-11-26 `684ccda` Distance-only models live inside the `.opara` and in the Trained models list.
- 2026-11-26 `d37321a` A Model testing block (the Annotator's Analyse tab as a block of its own).
- 2026-11-26 `b03f554` A Trained models block: one list of every model.
- 2026-11-26 `01570a9` The Annotator's Dataset and Distances wired into a Trainer block.

---

## DRW: Drawings

### Open

- **DRW-1** A model view cannot be turned in its own plane. Reported by Ian, 2026-11-26. *Decided with Ian, 2026-11-26 22:25:* the view offers **Turn left 90°** and **Turn right 90°**, and it acts like a piece of paper being turned: the orientation (what is looked at: Isometric, Front ...) does not change, only how the picture sits on the sheet, and it can be pressed again and again. Today a model view takes one of nine fixed orientations (`P.ORIENTATIONS`) set in the View properties box (`v_orient`, `dr_panels.py`; `Drawing.set_orient`, `dr_model.py`) and has no turn of its own; a projected view follows its parent. *Not decided yet (asked of Ian):* whether the views projected from a turned view turn with it so they stay lined up (the default I will take unless he says otherwise), and whether dimensions and notes fixed to the view turn with it. *Fixed when:* a model view has the two buttons, four presses one way give the view back as it was, a left and a right press cancel, the projected views and what is fixed to the view follow, the turn is kept in the drawing file, and a test covers it.

### Done

*(nothing recorded yet)*

---

## VIS: Visualize

### Open

- **VIS-1** Every result window has its own Animate and Export animation; Ian wants a Visualize node to do the exporting. Reported by Ian, 2026-11-26. *Decided with Ian, 2026-11-26 22:25:*
  1. **One input.** A Visualize node has one input and cannot take several. Coupled Physics is how two results are shown together: its result goes into the one input.
  2. **It keeps its own copy of the result, inside the `.opara`** (the size limit of the project file is already raised). On opening a project it does not update itself. To change what it shows: run the simulation again, then Update the Visualize node so it takes the new result.
  3. **It takes what is on screen in the simulation window.** If the window is set to Displacement when the node is updated, the node can animate and export displacement only; it does not hold the whole result and cannot switch to another field. To see another field: set the window to it, then Update the node.
  4. **The simulation windows keep a basic view** to preview the result. Exporting pictures and animations moves out of them to the Visualize node, which gets that one job. This also makes the simulation windows simpler.
  5. In 3D the node allows full rotations, or a picked view (the Combined Physics auto-turn, CPL-5, goes away; its job is here).
  6. It works for 1D, 2D and 3D results and for Coupled Physics.
  *What the code is today:* The Visualize add-on (`addons_src/render/`) is a picture-and-video studio for a part or assembly (looks, lights, floor, cameras with keyframes, a video) working on its own copy of the model in a `.gpv` folder, with no idea of a result field. In the Workbench `visualize` is a one-cell block (a document, no inputs). Animate and Export animation are in `beam_tab`, `physics_tab` (2D FEA), `cfd_tab`, `thermal_tab` (2D heat), `solid_tab` (3D FEA), `thermal3d_tab`, and Save animation in `coupled_viz`; they share `addons_src/simulation/anim_export.py` (WebP, APNG, GIF, MP4, PNG pictures). A result window draws a frame from the result and the chosen field (`field_values(ramp)` in 3D FEA), so what the node must keep is the field on screen, the shape it is drawn on and the frames of a ramp or a transient run.
  *Not decided yet (asked of Ian):* whether the Animate play button (a preview) stays in the simulation windows while only the export moves; how many frames a transient run may keep in the node (the biggest data); whether the existing render studio (looks, lights, floor, video) is part of this node or stays a separate tool for a part. *Fixed when:* the designs are drawn and approved (they go in `planning/design/`), and then it is built in steps, each with its own item.

### Done

*(nothing recorded yet)*

---

## CPL: Coupled Physics

### Open

- **CPL-1** *(limit)* The air and tracers of a 3D flow are not drawn in the Viz tab; the picture says so when the block has a 3D flow.
- **CPL-2** *(limit)* 3D analyses are not shown inside the Coupled Physics window; they keep their own tabs.
- **CPL-3** *(limit)* The heat-flux tracers of a 3D part are bent with a displacement blended from the nearest points of the surface, not a solved displacement of the inside. It is for the picture only. The part is drawn faded while the tracers are on.
- **CPL-4** The Viz tab has only been tried in a headless Qt. Nothing of it (the 2D heat picture, the 3D picture, the tracers) has been seen on a real screen or on Windows. Design: `design/combined-physics/`. *Fixed when:* Ian has looked at the Viz tab of the example project on his computer and said what is off.

- **CPL-5** The Viz tab turns the part by itself in the second half of an animation. Reported by Ian, 2026-11-26: he does not like it and wants the animation to stay in the view that is set. It is the box "Turn the part in the second half of the animation" (ticked by default; `turn_on`, `camera_at`, `V3.turn_at` in `coupled_viz.py`). *Fixed when:* the camera is the same for every frame of an animation and of a saved animation unless the person changes the view; a test checks it. (Full rotations and a picked view are wanted in the Visualize node: VIS-1.)

### Done

- 2026-11-26 `970764c` Viz: heat-flux tracers for a 2D heat and stress solve with no flow (before it was not drawn), and inside a 3D part. Tests: `test_coupled_viz_heat.py`, `test_coupled_viz3d_tracers.py`.
- 2026-11 `e9a58d7` Viz draws a 3D heat and stress solve (software z-buffer, no OpenGL).

---

## GEN: whole program and tests

### Open

- **GEN-1** `test_dimstyle.py` and `test_family_look.py` fail on `dev`. They were already failing before the Viz work; the cause has not been looked into. *Fixed when:* both pass on a clean checkout.
- **GEN-2** `test_release_files.py` and `test_release_set.py` fail on `dev` (found 2026-11-26, and they fail the same on a clean checkout). The first stops at `addons_src/trainer/addon.json`, whose version is not the program's version in `version.py` (0.8.6); the second says the released add-ons of the program folder (simulation, parametric) are not put in place. Not looked into further; it may be the tests that are out of date and not the release. *Fixed when:* both pass, or each is changed to say what is now true.

- **GEN-3** Hold the next push of program code until Ian has confirmed the Annotator and Trainer layout. Asked by Ian, 2026-11-26: he thought the layout had not been pushed and might be out of date. Checked the same day: it was pushed. The Annotator ribbon (`b828756`, `85513fc`) and the Trainer window (`88ab86b`) are on `origin/dev`, in Playground builds `dev-0.8.6.139` to `dev-0.8.6.155`; nothing of the Annotator or Trainer is on `main`. A push that changes only `planning/` does not build, so this list and the designs can go up without waiting. *Fixed when:* Ian has said the layout is as he wants it, or has listed what to change (ANN-1, TRN-2), and has said to go on.

### Done

- 2026-11-26 `007710d` The approved designs are filed in `planning/design/`: a picture of every board, a note on what each decides, the specs.
- 2026-11-26 `344d096` This list (`planning/ISSUES.md`); a push that changes only `planning/` does not build.
