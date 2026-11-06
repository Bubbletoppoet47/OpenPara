# OpenPara design principles

The conventions the program already follows. When you are unsure how something should look or behave, start here; if this file does not answer it,
ask, then add the decision below so it is only decided once. Keep entries short and concrete.

## 1. How we work
- **Confirm first, then build.** A request ending in "please confirm" gets a plan only. "Go ahead" means build, run the full test suite, push to `dev`, and report the release number.
- **`main` is untouched** until a release is made on purpose. All work goes to `dev` (each push builds a `dev-0.8.5.N` pre-release; the maintainer runs the Release workflow).
- **Parity rule.** A feature added to one simulation tab (1D FEA, 2D FEA, 3D FEA, CFD) is checked against the others. If it makes sense there, it is built there too, and looks the same.
- **Every change has a test**, and the full suite passes before pushing. Tests draw things and assert on pixels or values, not only that nothing crashed.
- **Say what is missing.** Limitations are listed in the report, not hidden.

## 2. Side panels (1D FEA, 2D FEA, 3D FEA, CFD)
- The left panel is a stack of **numbered, collapsible sections**; the fold state is remembered.
- **Mesh / Solve are pinned** under the scrolling part so they are always reachable. No horizontal squeeze: the panel scrolls sideways when needed; there is no maximum width.
- **No hotkeys** in the simulation panels (letters do nothing). Mouse and menus only.
- **Supports and loads are icon buttons**, stacked, with the same icons in every tab (`sim_icons`).
- Inputs use the **global unit system**; values are shown in it and converted on entry.
- The note text under a control is short, plain, and says what the control does, not how it is coded.

## 2b. Project bars (Truss Generator, simulation tabs)
- A project tab's top bar is short: **New project…** (makes the folder first), **Import source…** (copies a sketch, part or assembly in), **Update from original**. Project name and Configuration sit beside them.
- Less-used commands (Open sketch for editing, Clear sketch) live in a small menu, not on the bar. Export lives on the page it belongs to (Assembly), not on the bar.
- Heavy rebuilds are incremental: an edit rebuilds only what it touches, the rest (and its meshes) is reused; the Assembly page is built when it is opened.

## 3. Results
- Result text comes from the **one shared formatter** (`sim_report`), so 1D, 2D and 3D read the same: heading, chips, key/value tables, summary, solver block.
- Numbers are shown to **5 significant figures**; units always follow the global system.
- **Colour scales** are drawn by the shared routine (`legend_draw`): measured first, never cut off, long titles wrap with the unit kept, shrink in small windows. Never position a legend with fixed pixel offsets.
- The colour scale is fixed to the final result during an animation.

## 4. Animations and exports
- The **Animate box is the same everywhere**: Duration (s), Playback (Once / Loop / Back and forth), Play, Stop, then **Export animation...**. Frames are a field where the user can choose them (2D, 1D); in CFD they are the saved time steps and the box shows the count.
- Export formats: transparent animated **WebP** (default), animated **PNG**, **GIF**, **MP4** (when available), or a folder of PNGs.
- **Transparent means only what is drawn is kept**: frames are drawn on white and on black and the alpha is computed from the two.
- The exported clip uses the same Duration and Playback as the on-screen preview.

## 5. Tables and the Parametric Studies add-on
- Tables are plain grids: first column is the parameter name, one column per value, editable cells.
- **Fill range** supports linear and log spacing; filling that would replace existing rows asks for **confirmation** first.
- A study never silently overwrites results; the user chooses what to keep.

## 6. Sketching
- The context menu on a plane says just **Sketch**.
- Exactly one ribbon tool button is lit at a time (plain buttons and drop-downs alike).
- Mates are solved in the order they were made. If they all agree they are solved together; if not, one at a time: earlier mates are trusted and stay exact, a mate that cannot be met is left out and reported ("conflicts with the mates before it"), and a mate being added or edited counts as the newest. No mate type is special.
- Assembly mates can use the assembly's own planes and origin, even with a single component.
- Tools finish with **Enter, Esc or a double-click**; Esc never throws away finished work.
- Everything drawn stays editable: points can be dragged, including a spline's fit points.
- Curves that need no solver equations (splines) are still ordinary sketch geometry: they take part in regions, extrudes, 2D FEA and the .skt file.

## 7. Wording and appearance
- The wheel zoom strength is a setting (File > Settings > Navigation); every view that zooms with the wheel reads it. The start-up card never stays on top of other windows.
- Button and menu labels are short and sentence case ("Export animation...", "Play", "Stop").
- Anything that can be cut off, clipped or overlap in a narrow window is a bug: measure text, wrap or elide, and test at several widths.
- Prefer one shared helper over three copies. If two tabs draw the same thing, it lives in one module.

## 8. Known gaps (so they are not rediscovered)
- Splines: a spline END can be made tangent to a line, an arc or another spline (Tangent tool; the end point must be shared, so add Coincident too). No tangent at interior fit points, no point-on-spline constraint, no trim / fillet / offset.
- 3D FEA: no transparent animation export; results are not saved in the project.
- Colour-scale text in transparent animations is black.
- "Update from original" clears supports and loads in 1D / 2D.
- Assembly mates: exact first moves ("snaps", registry `am.SNAPS` / `@snap(type)`) put a free part straight onto a mate's closed-form answer; the numeric fit then only verifies / finishes. Concentric is the first; add a type by registering one function.
- Mate panel: nine full-width icon buttons (mate_icons.py) in the style of the FEA panel buttons; Faces / Edges / Points are icon toggles.
