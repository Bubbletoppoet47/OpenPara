=== Simulations: 1D FEA, 2D FEA, 2D CFD (menu Add) ===
* Add > 1D FEA / 2D FEA / 2D CFD opens a simulation tab for the part or assembly that is on screen (from another simulation tab it uses the
  same source).  File > Save saves it as a .gps file (settings, mesh and results zipped); File > Open reopens it.
* The simulation works on a COPY of a 2D sketch.  In the left panel choose what to import and press Import:
  - a part:      one of its sketches, or "Slice with a plane..." (the 1D FEA takes sketches only: its frames / trusses are the sketch lines);
  - an assembly: only "Slice with a plane...": choose a plane (Front / Top / Right or a reference plane), an offset in mm, flip, and which parts to cut.
    Touching parts are BONDED (one connected body).  Regions are named after their part; holes (no material) are switched off.
* "Slice with a plane..." opens a window with a small 3D view of the model.  Only the planes that are SHOWN in the part / assembly window
  are drawn and listed (hidden planes and reference planes stay out).  Click a plane or a flat face of the model (or pick the plane from the
  list); set the Offset in mm (- / + buttons with their own step, or type it; Reverse swaps the sign), and see the cut (red outlines on an
  orange plane with its arrow) before pressing Slice.  A clicked face is remembered as a fixed plane (it does not follow later model changes).
* The slice's 2D axes are the ones a sketch on that plane would have.
* Linked files: when you save a simulation it is listed under "Simulations" in the project tree of its part / assembly (save the part /
  assembly to keep the list).  Double-click one to open it (nothing opens by itself when the part opens); right-click > remove from the list
  (the file stays).  Saving the part / assembly also saves its open simulations that have changes.  The simulations stay separate .gps files.
* Results are the same in 1D and 2D FEA: Displacement magnitude / X / Y, von Mises stress, Normal stress X / Y (then the 1D force, shear and
  moment diagrams as extras).  One "Colours" choice (turbo, jet, viridis, plasma, coolwarm, rainbow, gray) is shared by 1D FEA, 2D FEA and
  2D CFD and is remembered (gpd_settings.json).  Installing matplotlib (pip install matplotlib) gives the exact matplotlib maps; without it
  close approximations are used.
* "Refresh from source" (top of the tab) takes the sketch / slice again as it is now (clears supports, loads, mesh and result).
* Materials: the part's material (tree > Material) fills E, Poisson's ratio and the strengths by itself; you can still type other values.
  In an assembly slice every region uses the material of its part (2D FEA only; each element's factor of safety uses its own strengths;
  the nonlinear solver is not used with several materials).  A part with no elastic values (e.g. water) leaves the boxes for you to fill.
* The solvers, supports, loads, meshing, probes, CFD and 1D tools are those of the earlier program.  Needs the gmsh and scipy packages
  (run_modeller.bat installs them the first time).
* Not done: contact between parts (only bonded), 1D FEA from a slice, linking a CFD result into an FEA tab across simulation tabs,
  the Parameterization tab, heat transfer.


RENDERER (new)
--------------
Ribbon > Renderer > New render opens a Render Studio tab for the part or assembly that is on screen (it must be saved once).  It uses the
live model, so unsaved edits are rendered too.  Same window as run_render_studio.bat; the full guide is README_render.txt.
- Save the render (File > Save render project, or save the part / assembly): it becomes <model>_render.gpr next to the model and is
  listed in the feature tree under "Renders (n)"; double-click it to open it again.  Saving the part also saves its open renders.
- File > Read the part / assembly again: picks up changes to the model; looks, lights and cameras stay.
- Looks: colour, roughness, metallic per body.  Sun from date, time and place, spot light, floor (with the up axis), several cameras.
- General settings (sun, spot, floor, picture and quality, animation) can be exported / imported as text files, cameras separately.
  Looks of single bodies are not part of the settings file on purpose.
- Quality goes up to Ultra 4096 / 8192 / Maximum 16384 samples; Denoise is a checkbox (needs an NVIDIA GPU; without it the picture is just
  not denoised).  Pictures and videos render in a separate program, so a problem there never closes the modeller; Stop is graceful.
- Video: tick the cameras that belong to the video, order them with the arrows, choose Curved or Straight path (3 cameras = start,
  middle, end; the path passes through the middle one), seconds and fps.  Output is an MP4 only.
Not tested by me: the real 3D window, CUDA rendering and the OptiX denoiser (no NVIDIA card in my workspace).


VERSION 0.2.3
Box selection in a sketch: with the Select tool, press on empty space and drag.  Dragging left to right selects what lies completely
inside the box; right to left selects everything the box touches (dimension labels inside the box too).  Shift or Ctrl adds to the
selection.  A click without a drag still clears the selection and picks the part's edge / face under it.  Dragging a point or a
line still moves it; Alt+drag orbits.

Every modelling number takes a global or a formula.
 - Sketch tools: the Offset distance, Linear / Circular pattern step and centre, Move X / Y and the Fillet radius accept a number,
   a global (Width), a formula (Width/2 + 3) or a length with a unit (2 in).  A linked Offset keeps the formula, so changing the global
   moves the offset.  Fillet, Move and the patterns create plain geometry once (their result is the value at that moment).
 - Assemblies have their own Globals (the equations tab of the assembly window).  Component position / rotation, the Distance / Angle of
   a mate (while adding and when editing it) and the Spacing / Angle / Instances of a pattern accept those names or formulas.  The
   formula stays stored in the file, so changing a global moves the assembly.  Typing a plain number again removes the formula.


VERSION 0.2.4
Sketch > Select now has a drop-down (like Line or Rectangle): Select and Box Select.
 - Select: click to pick, Shift / Ctrl adds, drag a point or line to move it, drag on empty space for a selection box.
 - Box Select: every left drag is a selection box, even when it starts on top of a line or point (nothing is moved).  A click still picks
   one entity.  Left to right (blue box) selects what is completely inside; right to left (green box) selects everything the box touches.
The box is drawn inside the 3D view, and the status line says how many items it selected - or that it found nothing and which direction to
drag.  The ribbon tab "Renderer" is now "Render".


VERSION 0.2.5
The OpenPara logo / program icon was redrawn with a margin, so the whole logo (the P, both dimension arrows) shows at every size and when
Windows crops it to a circle or a rounded tile.  The logo files are in assets/ (SVG) and OpenPara.ico / docs/icon.png.


VERSION 0.2.6
The selection box now also selects points (sketch points, line ends, circle centres), not only lines, arcs and circles.  The origin is left out.


VERSION 0.2.7
Suggestion lists.  Every box where a number or a formula is typed in a part shows an Excel-style list under it: the globals with their current
values (in the current unit), the named dimensions, the open sketch's own symbols and the functions (min, max, sqrt, sin ...).  It opens while
you type a name, when you click into an empty box, and with the Down key; Enter / Tab / a click puts the name in place of the word typed.
Where: feature boxes, the Globals equation column, the sketch dimension table and the dimension / rename dialogs, the sketch tool dialogs
(offset, fillet, patterns, move) and the cells of the part's Configurations table.  (Assembly boxes do not have the list yet.)

Sketch patterns.  Circular Sketch Pattern no longer repeats Horizontal / Vertical relations on the turned copies (they could not hold); the other
relations (parallel, perpendicular, equal, tangent, concentric, coincident, collinear, midpoint) are repeated.  Mirror Entities repeats
Horizontal / Vertical only when the mirror line is itself horizontal or vertical.  Linear pattern and Move are unchanged.


VERSION 0.2.8
Rename tree items.  Select an item in the feature tree (part) or the assembly tree and press F2, or right-click > Rename.
 - Part: features, sketches, reference planes and axes.  Assembly: components, mates, patterns and the assembly's reference items.
 - Names must be unique in their group and not empty; a rename can be undone.  The Configurations table headers show the new name.
 - Globals: edit the Name cell of the Equations table to rename a global.  Every formula that used it (other globals, feature values, sketch
   dimensions and symbols, Configurations cells) and its Configurations column follow.  Only whole words are replaced (renaming W leaves
   Width alone).  Renaming a sketch dimension does the same for the later formulas that used its name.

Update prompt.  The program looks for a newer version every time it starts (Help > Check for updates at start-up switches this off) and asks
"Update now?".  Help > Check for updates still works by hand.  A failed automatic check only writes a note in the status bar.


VERSION 0.2.9
Dimensions in a sketch.
 - Drag a dimension's label with the Select tool: it moves to where you drop it (only the label; the drawing does not change).  The position is
   saved with the sketch.  Right-click > Reset label position puts it back.  A click anywhere on the label's text selects it (not only on a
   small spot).
 - An angle's label can be dragged across the corner to the opposite sector (the same angle, so the dimension stays valid) and the arc follows.
 - New angle dimensions: when the two lines cross, a small dialog asks which angle you mean - the acute one (less than 90 degrees) or the obtuse
   one - and lights the chosen sector in the sketch.  The side your cursor was on is suggested.  Perpendicular lines are not asked.  Right-click
   an angle > Change which angle... switches it to the neighbouring sector later (the drawing does not move; the value becomes that sector's).
 - Delete a dimension: select its label in the sketch and press Delete, right-click > Delete, or select its row in the Dimensions table and press
   Delete / the button.  The lines stay.  If a formula elsewhere uses the dimension's name you are asked first.  Its Configurations column goes
   with it.
 - The Dimensions and Relations tables look and work alike (spreadsheet style, whole-row selection, Shift / Ctrl for several, a Delete button).
   Selecting a row lights the label and the lines / points it concerns in the sketch; selecting a label in the sketch selects its row.

VERSION 0.3.0
File > Settings (new).  Typed values, applied to every part and assembly (kept in your data folder, not inside files).  Reset to defaults,
Apply and OK buttons.  Each drawing setting has a small picture beside it that redraws as you type:
 - Curve accuracy (edges): the most a drawn line may stray from the true curve.  Shown on a 90 degree bend with the straight pieces drawn over
   the true curve.  Edges are now cut into as many pieces as that needs (before: always 24).
 - Surface accuracy (shading): how finely round surfaces are shaded; shown as the facets of a circle cut across.  The finest values warn that
   big assemblies get slow.
 - Outline thickness (pixels) and Outline pull toward viewer (pixels; a sketch of why the outline is brought forward).  Defaults are thinner and
   pull less than before, so thin faces are no longer covered.
 - Picking: the 3D pick distance, the sketch snap / pick distances and the dimension label click area, and a switch for the hover highlight.
Assemblies.
 - Mates, reference geometry and patterns: tick boxes Faces / Edges / Points choose what a click may pick.  The zone around an edge or corner
   is now measured in screen pixels (default 4; before at least 0.4 mm whatever the zoom), so the narrow cut face of a thin pipe can be picked.
 - The face, edge or point under the cursor lights up while you pick (can be switched off in Settings).

VERSION 0.3.1
Sketch dimensions are now drawn like a drawing.
 - Length (horizontal / vertical / length): two extension lines from the measured points, a dimension line with an arrowhead at each, and the label on
   that line.  Dragging the label moves the dimension line (how far out it is) and slides the text along it.  The lines are worked out from the
   geometry each time, so they always join what is measured.  A new dimension starts a little outside the drawing.
 - Radius / diameter: a line from the circle (through the centre for a diameter) with arrowheads on the circle, running out to the label.
 - Angle: an arc between the two lines with arrowheads, and extension lines when the lines stop short of it.  The label slides along the arc but
   can only stay between the two lines (inside the acute or obtuse angle that was chosen); dragging it farther out or in changes the arc's radius.
   Dragging it across the corner still switches to the opposite sector (the same angle).
 - Each configuration keeps its own label positions.  A new configuration starts as a copy of the one it was made from; moving a label while
   another configuration is active changes only that configuration.  Files from before open with every label where it was.
Configurations > Add Column: a "shows" drop-down (All / Globals / Sketch dimensions / Feature values / Suppress switches; for assemblies Components /
 Suppress switches / Mate values / Patterns) and, for sketch dimensions and feature values, a second one to pick one sketch or feature.
Assemblies: the 3D pick distance is now measured on the screen in pixels (the edges and corners are projected to the view), so it means the same
 number of pixels at any zoom or angle.  Before, it was converted to a distance in the model and could be wider than set when zoomed in.

VERSION 0.3.2
File > Settings is now in sections (list on the left): Curves & Surfaces, Outlines, Dimensions, Picking & Snapping.  The text under the pictures is
gone; each input has one short line under it.
Dimensions (new section), with a picture of a length, a diameter and an angle dimension that redraws as you change a value:
 - Dimension line: thickness and style (Solid, Dashed, Dotted, Dash-dot).
 - Extension lines: thickness, style, the gap from the part and how far they pass the dimension line (% of the sketch size).
 - Arrowheads: size (% of the sketch size) and style (Open arrow, Filled arrow, Closed arrow, Solid dot, Empty dot, Tick, None).
 - Label text size, the colour of dimensions and the colour of a selected dimension.
 Dashes and dots are drawn as short pieces whose length follows the sketch size.  The settings apply to every sketch (they are not saved in files).
