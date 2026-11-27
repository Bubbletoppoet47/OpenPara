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

*(nothing recorded yet)*

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

- **DRW-1** A model view cannot be turned in steps of 90°. Reported by Ian, 2026-11-26. He wants, for example, to choose Isometric and then turn that view 90° and keep turning it round. Today a model view takes one of nine fixed orientations (`P.ORIENTATIONS`: Front, Back, Left, Right, Top, Bottom, Isometric, Trimetric, Dimetric) set in the View properties box (`v_orient`, `dr_panels.py`; `Drawing.set_orient`, `dr_model.py`), and a projected view follows its parent. *Not decided yet (asked of Ian):* turn about the model's vertical axis, so Isometric shows each of its four corners in turn, or turn the picture in its own plane like a sheet of paper; and whether the turn also applies to the Front, Right and other views. *Fixed when:* a view has a control that turns it 90° each press, four presses give the view back as it was, the projected views that hang from it follow, and a test covers it.

### Done

*(nothing recorded yet)*

---

## VIS: Visualize

### Open

- **VIS-1** Every result window has its own Animate and Export animation; Ian wants Visualize to be the one place for it. Reported by Ian, 2026-11-26. What he asked for: Visualize becomes a node of the Workbench that takes results on its inputs (from the 1D, 2D and 3D analyses and from Coupled Physics); he opens it and animates and exports with all its settings; in 3D it allows full rotations, or picking a view; Coupled Physics results also go through it. *What the code is today:* (1) The Visualize add-on (`addons_src/render/`) is a picture-and-video studio for a part or assembly (looks, lights, floor, cameras with keyframes, a video); it works on its own copy of the model in a `.gpv` folder and has no idea of a result field (stress, temperature, flow). (2) In the Workbench `visualize` is a one-cell block (a document, no inputs). (3) Animate and Export animation are in each result window: `beam_tab`, `physics_tab` (2D FEA), `cfd_tab`, `thermal_tab` (2D heat), `solid_tab` (3D FEA), `thermal3d_tab`, and Save animation in `coupled_viz`; they share `addons_src/simulation/anim_export.py` (WebP, APNG, GIF, MP4, PNG pictures). (4) Results are not saved in a `.opara` file; they stay in the analysis window and every solution cell says "update" when a project is opened. So the node has to read a result from a window that is open and solved, or results have to be kept somewhere. *Not decided yet (asked of Ian):* see the questions in the chat; the answers go here. *Fixed when:* a design is approved and filed in `planning/design/`, and then it is built in steps, each with its own item.

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
