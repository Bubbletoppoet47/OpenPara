# OpenPara design principles

The conventions the program already follows. When you are unsure how something should look or behave, start here; if this file does not answer it,
ask, then add the decision below so it is only decided once. Keep entries short and concrete.

## 1. How we work
- **Confirm first, then build.** A request ending in "please confirm" gets a plan only. "Go ahead" means build, run the full test suite, push to `dev`, and report the release number.
- **`main` is untouched** until a release is made on purpose. All work goes to `dev` (each push builds a `dev-<version>.N` pre-release; the maintainer runs the Release workflow).
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
- A project tab's top bar is short: **New project...** (makes the folder first), **Import source...** (copies a sketch, part or assembly in), **Update from original**, on the right of the bar; the kind chip, project name and Configuration sit on the left (see 7d).
- Less-used commands (Open sketch for editing, Clear sketch) live in a small menu, not on the bar. Export lives on the page it belongs to (Assembly), not on the bar.
- Heavy rebuilds are incremental: an edit rebuilds only what it touches, the rest (and its meshes) is reused; the Assembly page is built when it is opened.

- **Visualize** has the same two commands (**Import source...**, **Update from original**) but no New project step: its folder is made at the first save or render, beside the model. A model must never be hard to get in: the part or assembly on screen is shown at once (ribbon, Add menu, File > New Visualize), saved or not; a tab with nothing to show opens on a guidance page (Import part or assembly..., Open Visualize project..., or drop a file); a new model replaces the old one and keeps the settings that do not depend on the model (sun, picture, video, output). Update from original reads the open tab, else the file itself - it never opens a tab to do so.
- A command never refuses with "save first" or "open a part first" when the program can simply do the sensible thing (take the unsaved model as it is on screen; open the guidance page).

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

## 7b. The program window
- **An empty window shows the start page**, never a blank: the program's own ways to start, then the documents and commands of the installed add-ons under their own heading, and the recent files. In a narrow window the two columns stack; nothing is cut off.
- **Recent files** (`recent.py`) are noted by the window itself the first time a tab is seen with a path, so an add-on gets them for free. A path that is not there (an unplugged drive) stays in the list, greyed, and is only removed when the user says so. File windows start in the folder used last.
- **The title bar names the document on screen**; menu entries that cannot do anything right now are greyed out. Undo / Redo are greyed only when the tab cannot undo at all, never by the undo history (a stale state would swallow Ctrl+Z).
- **Window menu**: Next / Previous tab (Ctrl+Tab), Reopen closed tab (Ctrl+Shift+T), Close all, and the list of open tabs. Tabs have a right-click menu (close, close the others, save, copy the path, show in folder); a middle click closes; hovering shows the path.
- **Save All** saves only what changed. **Exit asks once** for all unsaved documents (Save All / Discard / Cancel); a single one gets the usual question.
- **Errors are text the user can copy in one click**, with the program version, mode and add-ons on top (`gpd_app.ErrorDialog`); every caught error also goes to `gpd_error.log` (Help > Show the error log). A message box that only says "could not ..." points there.
- A file or project folder dropped on the window is opened. The window size and place are remembered.

## 7c. Add-ons and the core
- **The core knows nothing about what an add-on does.** An add-on puts its own commands in the menus with `ext.add_command(place, text, fn)` from `register(ext)` (places: `file.new`, `file`, `add`, `view`, `help`); `file.new` commands are also buttons on the start page. Do not add an add-on's menu entry to `gpd_app.py`.
- **One broken add-on never stops the program** or the other add-ons: its error is kept (`addons.load_errors()`), shown once after start-up, on the start page and in File > Add-ons (Details...).
- **Tab lifetime**: a closed tab is deleted by Qt. Never keep a closed tab and reuse it (check it is alive, or forget it in `shutdown()`). A tab that cannot live without another one says so with `depends_on()`; the window closes it first. Background work is stopped in `shutdown()` (a closed tab gets no `closeEvent`), and `can_close()` asks before a run is interrupted.
- File > Add-ons says for every add-on **what it adds** (read from its manifest by `addons.adds`), its state, and its load error. Playground add-ons are used where they are: no Install / Uninstall.

## 7c-2. Reaching another computer (Remote Computer, Gimble connection)
- **Nothing happens on the other computer without its access code**, and the code is never stored there or sent: both sides prove it (SPAKE2 in `openpara_remote_helper.py`). Do not add a way in that skips it, a default code, or a "trust this network" switch. Wrong codes are counted and logged.
- **The helper is one file with no packages to install**, so it can be carried on a USB drive to a computer without a working screen. Anything it uses beyond the standard library must be optional (OpenCV / Pillow only make video lighter). It is never started or installed by OpenPara itself: the owner of the other computer does that, there.
- **What the other computer refuses is said in its own words** (`RemoteError` text is shown as it is): "switched off on that computer", "No such file", "Wrong access code." A lost connection is said once and the tab goes back to its start.
- **Destructive things ask first and say where**: deleting names the other computer and says there is no recycle bin; replacing asks. Copies go to a `.part` file and are renamed when whole; an upload is compared (SHA-256) after it arrived.
- **Pictures**: exact by default; JPEG only while a large part of the screen moves, and what stood still is sent exact once more. Keyboard and mouse go only while "Use its keyboard and mouse" is on and the picture has the focus; keys still held are released when it loses it.
- **The Gimble's own files are not ours to change**: the connection only writes `model/gimble_model.onnx|json` (the previous pair is kept in `model/previous/`) and reads `dataset/`. A model is converted in a separate process and checked against the original before anything is sent.

## 7d. One family of tabs (`ui_kit.py`)
- **Every document tab carries the icon of its kind** (`icon_set.TAB_KIND`; a manifest may name another with `"icon"`). Hues: modelling blue / teal, analysis purple, data and AI magenta, tools grey. New icons are drawn in the `icon_set` style (24 x 24 grid, the classes b / a / l / n).
- **Tab names**: a file tab shows its file name (`bracket.gpd`); a project tab shows its folder without the extension (`frame`, `Roof`); a tab without a file yet says what it is and of what (`1D FEA - bracket`, `Visualize - bracket`); a study is `Study - <project>`. The tab's tooltip says the kind and the path.
- **The bar on top is the same everywhere** (Truss, Visualize, the simulations, Study, Mesh FEA, Mesh fixing, Annotator, Trainer): a coloured chip that says what the tab is (`ui_kit.kind_chip`), then what it works on in muted text, then - on the right - its commands (`New project...`, `Import source...`, `Update from original`, drop-down buttons). A tab never has a second menu bar: inside the program its menus become drop-down buttons on the bar (`ui_kit.menu_button`).
- **One place for each command.** While the guidance page of an empty tab is up, IT has New project / Import source, and the bar does not repeat them; once there is something to work on, the bar has the project commands. A bar button and a menu item never do the same thing (Visualize: the bar's Update from original replaces the menu's "Read the part / assembly again").
- **Never `QMainWindow.setMenuWidget()` for the bar**: it deletes the window's menu bar and, with it, the menus the bar's drop-down buttons show (the buttons then do nothing). Use `ui_kit.top_bar(window, bar)`, which hides the menu bar and keeps it. Tests of a tab must let Qt delete what was scheduled (`sendPostedEvents(None, DeferredDelete)`) and click the drop-down buttons for real - a test that does not misses exactly this.
- **An empty tab says how to begin** (`ui_kit.EmptyState`): a title, one or two plain sentences, and the buttons that start the work - the first one teal. Never three empty panes, never a blank canvas.
- **Side panels are numbered, foldable sections** (`ui_kit.Section`; the simulation tabs' `sim_ui.Section` is the same look). No grey group boxes for the steps of a panel.
- **A panel opens as wide as its contents** (`ui_kit.fit_panel` / `fit_dock`): nothing is cut off and there is no sideways scroll bar at the start. It widens when its contents grow, until the user drags the divider. A long drop-down is tamed (`ui_kit.tame_combo`), three axis boxes go under their label (`uiparts.stack`), long labels wrap.
- **One teal button per panel** is the action that moves the work on (`ui_kit.primary`): Solve, Run all rows, Reduce, mesh and show, Repair, Start training, Confirm image, Export assembly. Everything else is a plain button. A Run / Solve bar that must always be reachable is pinned under the scrolling part.
- **One status line per tab** (`ui_kit.StatusLine` or the tab's own label): a long message is cut with "..." and shown whole on hover; it never widens the window.
- **3D views share one background** (`ui_kit.view_background`, the Part window's soft gradient).
- **Wording**: sentence case ("Confirm image", "Delete frame..."); three dots, never the single ellipsis character; "1 body" / "2 bodies", never "body(ies)".
- **The Add menu makes things from what is on screen**: Visualize, the simulations, Truss Generator (from a sketch of the part), Parametric study (of the simulation). An add-on registers its own entry with `ext.add_command("add", ...)`.

## 8. Known gaps (so they are not rediscovered)
- Splines: a spline END can be made tangent to a line, an arc or another spline (Tangent tool; the end point must be shared, so add Coincident too). No tangent at interior fit points, no point-on-spline constraint, no trim / fillet / offset.
- 3D FEA: no transparent animation export; results are not saved in the project.
- Colour-scale text in transparent animations is black.
- "Update from original" clears supports and loads in 1D / 2D.
- Assembly mates: exact first moves ("snaps", registry `am.SNAPS` / `@snap(type)`) put a free part straight onto a mate's closed-form answer; the numeric fit then only verifies / finishes. Concentric is the first; add a type by registering one function.
- Mate panel: nine full-width icon buttons (mate_icons.py) in the style of the FEA panel buttons; Faces / Edges / Points are icon toggles.
- Start page: no thumbnails of the recent documents, no pinning. The Add menu entries of Simulation and Visualize are still made by the core (`gpd_app.build_menus`), because add-ons of an older version would lose them; new add-ons use `ext.add_command`.
- Tab commands (right-click, Window menu) work on whole tabs only; tabs cannot be split side by side.
- Remote Computer: only the X11 path has run for real. Windows (GDI + SendInput) and Wayland (grim + uinput, US keyboard layout only) are untested; no clipboard sharing, no sound, one screen (the primary one), no picture scaling on the sending side, the Commands page is a line-by-line runner and not a terminal (no full-screen programs like nano). Ctrl+Alt+Del cannot be sent to Windows, and a helper that was not started as administrator cannot type into administrator windows or the lock screen there.
- Family look: the Part and Assembly windows keep their ribbon (no chip bar); Motor Control, Circuits, Voxel-only helpers and the 3D FEA tab were not restyled in this pass (3D FEA already uses the simulation sections). The Mesh FEA / Voxel FEA view has no empty-state overlay (the status bar says what to do). The Annotator keeps Title Case in its File menu items ("Import Video...").
