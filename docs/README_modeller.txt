PARAMETRIC MODELLER PROTOTYPE (SolidWorks-style workflow)
Run: double-click run_modeller.bat  (installs build123d, pyvista, pyvistaqt, PyQt6 the first time).

Workflow
  1. Click a plane in the tree (or in the view), or a flat face of the part, then press "Sketch". The view turns to face the plane.
  2. Draw in the 3D view with the Sketch ribbon: Line (chains; Esc or double-click ends), Rectangle, Circle, Select (Delete removes).
     The whole part stays visible behind the sketch. Alt+left drag orbits, middle drag pans, wheel zooms; "Normal To" turns back to the
     plane. Clicks snap to the origin and to existing end points / corners / centres. Closed loops of lines make a profile.
     Exact numbers are still editable (as expressions) in the Properties panel. "Exit Sketch" (or Esc with Select) leaves the sketch;
     double-click a sketch in the tree to edit it again.
  3. Press "Extruded Boss" or "Extruded Cut"; set depth / through all / reverse / mid plane in Properties.
  4. "Fillet" / "Chamfer": press, then click edges in the view (click again to remove); set the size.
  5. Globals (right panel): name = expression (e.g. HoleD = Width/4). Change one and the whole part rebuilds.
  6. Tree right-click: Roll back to here / Roll forward / Suppress / Delete. A failing feature turns red; later ones are "not built".
  Ctrl+Z / Ctrl+Y undo and redo, Ctrl+S saves a .gpd file (JSON).

Files
  pm_model.py   the document: feature tree, rebuild, expressions, stable face/edge references (no UI)
  pm_app.py     the window
  viewpick.py   picking helper copied from the sketcher project
  sketch_edit.py   sketching in the 3D view: plane maths, tools, snapping, the drawing layer
  test_model.py, test_app.py, test_sketch.py   self-checks (python test_model.py)

Face and edge references are stored as position + direction and re-matched on every rebuild (not as "Face7"), so edits upstream
usually keep downstream sketches and fillets attached. They can still land on the wrong face after big changes.
Next: sketch constraints and Smart Dimension (the solver), snapping / Convert Entities to the part's edges, arcs, then revolve, patterns, assemblies.


SKETCH TOOLS AND CONSTRAINTS (new)
----------------------------------
The sketch now runs on the real constraint solver from the sketcher (sketcher_core.py): every sketch is a set of points, lines, circles,
arcs, relations and dimensions.  Document globals (Equations tab) can be used in dimensions, e.g. type  Length/2  in a dimension.

Ribbon > Sketch (drop-down groups: the button repeats the last choice, the arrow opens the list):
  Line / Centerline / Midpoint Line
  Rectangle: Corner, Center, 3 Point Corner, 3 Point Center, Parallelogram
  Circle / Perimeter Circle        Arc: Centerpoint (move round the centre to pick the direction), Tangent, 3 Point
  Slot: Straight, Centerpoint Straight, Centerpoint Arc, 3 Point Arc        Polygon (asks the number of sides)        Point
  Sketch Fillet (asks the radius, click the corner)    Trim Entities (click the piece to remove)
  Offset Entities / Mirror Entities / Sketch Pattern (Linear, Circular) / Move Entities / Convert Entities   (select first, then press)
  Add Relation: Horizontal, Vertical, Parallel, Perpendicular, Collinear, Coincident, Concentric, Tangent, Equal, Fix, Midpoint
  Dimension: Horizontal, Vertical, Length, Radius, Diameter, Angle -> click the entities, type a number, a symbol or an equation.
  (Select entities first and then pick a relation/dimension and it is applied at once.)  Double-click a dimension label to edit it.
Drawing snaps to existing points (shapes join) and onto lines/circles (a coincident relation is added).  Lines that are nearly horizontal or
vertical get that relation.  Drag a point in Select mode and the solver moves the rest.  Colours: blue = has freedom, green = fully
defined, red = conflicting relations, orange = selected, grey = construction.  Properties shows the degrees of freedom, a dimension
table (edit values/equations) and the list of relations (delete one).

Not done / not tested in the real window: Spline, Ellipse, Text (left out on purpose); Offset has no live preview; Convert Entities
copies the part's edges that lie in the sketch plane (sketch on a face of the part).  The headless tests drive the tools through
simulated clicks; the on-screen drawing (VTK second layer, dimension labels) has not been seen by the author.


SELECTING EDGES AND FACES, EXTRUDE / CUT OPTIONS (new)
-------------------------------------------------------
Selecting in the 3D view (no feature open): click close to an edge to pick the edge, in the middle of a face to pick the face.  Shift-click
adds edges, clicking a picked edge again removes it.  Then press Fillet or Chamfer: the picked edges are used at once.
While sketching the same clicks work (a click on empty sketch space with the Select tool picks part geometry): pick edges or a face, then
Convert Entities copies them into the sketch (projected on the sketch plane, fixed where they are, joined to existing points).  With
nothing picked it converts the part edges that lie in the sketch plane.  Drawing also snaps to corners of the part (position only).
Boss-Extrude / Cut-Extrude panel: contours (tick regions of a sketch), end condition (Blind, Mid Plane, Through All, Up To Face),
Reverse, Direction 2, Draft (angle, outward), Thin feature (wall inside / outside / both), Merge result (boss), Flip side to cut.
A cut chooses once the direction that removes material and says so if it does not touch the part.
Not done: Up To Next, hover highlight of edges, thin features with open profiles, linking converted geometry to the part.


NAVIGATION, VIEW CUBE, RIGHT-CLICK (new)
----------------------------------------
Middle button drag = rotate, Ctrl + middle drag = pan, Shift + middle drag = zoom.  Wheel: rolling toward you zooms in (toward the cursor);
the toolbar item "Zoom: wheel toward you = in" reverses it (remembered).  The left button only selects / sketches, it never turns the view.
View cube (top right): click a face / edge / corner to snap to that view, the arrows turn the view by 90 degrees, the house = isometric.
Axes: Z up; Front looks along +Y, Top looks down.  Right click: sketch = Make construction / Normal geometry, Delete, Edit dimension, Normal To,
Exit Sketch (the entity under the cursor is selected first); part = Fillet / Chamfer / Sketch on this face.  Sketch > Construction does
the same for the selection.  The origin is drawn as a magenta dot and can be picked for relations and dimensions (e.g. Horizontal
dimension from the origin to a corner).  Box selection was left out on purpose.
Icons are drawn in the program (icons.py), light theme in pm_app.py (THEME).


SHOW / HIDE, FILLET PREVIEW (new)
---------------------------------
"Show" (right, under the ribbon): Planes, Origin, Sketches, Sketch dimensions, Part edges.  Each sketch, plane and the origin also has a
checkbox in the tree.  A sketch is hidden automatically once a feature (Extrude, Cut) uses it; tick it to show it again.  A selected or
open sketch is always shown.  While Fillet / Chamfer is open the view shows the rounded result; the edges to pick are drawn thin on top.
Speed: anti-aliasing is FXAA now (was supersampling), edges and sketches are drawn as one object each instead of one per line.

REVOLVE, PATTERN, MIRROR
  Revolved Boss/Base and Revolved Cut: pick the sketch, an axis (a centerline of the sketch is used automatically,
  otherwise the sketch's vertical axis; any line of the sketch can be chosen) and an angle (360 = full turn).
  The profile must not cross the axis.
  Linear Pattern / Circular Pattern (drop-down on the same button): tick the features to repeat (extrudes, cuts, revolves)
  or repeat the whole body. Linear: direction X/Y/Z or a selected edge, copies, spacing, optional second direction.
  Circular: axis X/Y/Z or a selected edge, copies, angle (360 = evenly around). Copies that miss the part are simply merged/cut where they touch.
  Mirror: tick features (or the whole body); mirror about the Front/Top/Right plane or a flat face you selected.
  Not built: Shell, Draft, Hole Wizard, Sweep, Loft, reference geometry.

SKETCH VISIBILITY
  View > Show > Sketches off hides every sketch. With it on, each sketch's checkbox in the feature tree decides whether it is drawn
  (selecting a sketch does not show it). The sketch you are editing is always drawn.

CONFIGURATIONS: FEATURE VALUES AND NAMED DIMENSIONS
  Add Column lists, besides globals and Suppress, the numbers of each feature (Depth, Depth2, Draft, Wall, Angle, Radius / Distance,
  Copies, Spacing, Offset ...). A feature with nothing to size (for example a Through All cut) has only its Suppress column.
  Sketch dimensions can be renamed: double-click the name in the sketch's dimension table. A name is unique in the part (not a global,
  a function name, or another named dimension). A named dimension is listed by its name in Add Column, and can be used in formulas of
  features and of later sketches (e.g. Depth = FlangeWidth/4). A dimension driven by a symbol shows the symbol's number in the table.

UNITS  (File > Units)
  One unit system for the whole program: sketch dimensions, feature boxes, globals, assemblies (positions, mates, pattern spacing),
  Measure and Mass Properties, the slice plane offset, the Renderer, and the 1D FEA / 2D FEA / 2D CFD tabs.
  Systems: Metric (mm, kg, N, s, MPa) [default], (cm, ... N/cm2), (m, ... Pa), (m, kN, kPa), (mm, kN, kN/mm2),
           US (in, lbf, psi), (in, kip, ksi), (ft, lbf, psf), (ft, kip, ksf).
  Speed is a separate choice (m/s, km/h, mph, ft/s, mm/s, in/s), so a wind speed can be in mph with metric lengths.
  Your files are not changed: geometry is always stored in millimetres, so switching units only changes what is shown and how
  typed numbers are read. A simulation (.gps) is converted to the new units (its mesh/result is converted in place when possible
  and cleared otherwise); a .gps saved in other units is converted when opened.
  Typing: a plain number in a length box is in the current unit. You can also type a unit:  3 in,  25 mm,  2 ft + 10 cm.
  Formulas: a number added or subtracted (W/2 + 3), alone (40) or inside min/max/abs/round is a length; a number that multiplies or
  divides (2*W, W/3) is just a factor. In the Globals table every global has a Type: length (default), number or angle - number and
  angle are never converted (use them for counts, ratios and degrees).
  The choice is remembered between sessions (units.json in the data folder).

EVALUATE TAB
  Mass Properties: pick a material (or type a density), units follow File > Units (mm and cm show grams, m kilograms, in and ft pounds). Shows mass, volume, surface area,
  center of mass, principal axes and moments, and the moment of inertia at the center of mass and at the origin
  (positive tensor notation). The material is saved in the .gpd file. Copy to Clipboard copies the text.
  Measure: press it, then click points (vertices), edges or faces. One item gives its coordinates / length (and radius of circles) / area.
  Two items give distances: tick Minimum, Maximum and Center to center as you like, XYZ adds the dX dY dZ split. Lengths are shown in the program's unit (File > Units).
  The measured line is drawn in orange. Maximum distance is found from points sampled along the shapes.

ASSEMBLIES AND TABS  (start with:  python gpd_app.py   or   python pm_app.py)
  The window has File / Edit / View menus and one tab per document (tabs at the bottom). File > New Part, New Assembly, Open (.gpd parts,
  .gpa assemblies), Save, Save As, Close Tab. A star after the tab name means unsaved changes.
  A part tab shows Part Features / Sketch / Evaluate / Simulation. An assembly tab shows Assembly Features / Evaluate / Simulation.
  The assembly file (.gpa) is readable JSON: links to the part files (relative paths), each component's position and rotation, its fixed flag,
  and the mates and patterns. It does not copy the geometry, so editing a part updates every assembly that uses it
  (Edit Component opens the part in a tab; switching back to the assembly refreshes it).
  Insert Components: choose .gpd files. The first is fixed (f); the others float (-). Right-click a component: Fix/Float, Edit, Hide, Delete.
  Move / Rotate Component: drag with the left button. A component with mates slides only where the mates allow it.
  Mate: click two items (face, edge, point - or a component's Front/Top/Right plane or Origin in the tree), pick the type, press OK.
    Types: Coincident, Parallel, Perpendicular, Tangent (flat face / cylinder / sphere / straight edge against a curved face),
    Concentric, Lock, Distance, Angle, Symmetric (pick two items, then the mirror plane). "Flip" switches aligned / opposite or the side.
    The tree shows (-) for components that can still move, mates in red when they cannot all be satisfied.
  Linear / Circular Component Pattern and Mirror Components: click the components to repeat, set the options, press OK. Copies are
  derived (shown "(pattern)" / "(mirror)", not mated). Mirror makes a flipped copy of the same part (exact for symmetric parts).
  Assembly Mass Properties: uses each part's own density.

LEFT PANEL TABS, CONFIGURATIONS, DISPLAY
  Four icon tabs: Part tree (Assembly tree in an assembly) / Properties / Configurations / Display. Equations is now an item in the tree:
  double-click "Equations" to open the table of global variables.
  Configurations: a configuration is a named row of values in the configuration table. Add Column puts items in the table; Add Configuration
  makes a row; double-click a configuration in the tree (or right-click > Activate) to switch to it. Editing a cell edits that configuration.
    Part columns: a global's equation, one sketch dimension (D1@Sketch1, a number or an equation), or $SUPPRESS@feature (tick = suppressed).
    Assembly columns: Configuration@component (which configuration of that part the component uses), $SUPPRESS@component,
    $SUPPRESS@mate, Value@mate (distance / angle mates), and pattern numbers (copies, spacing, angle).
  Configurations are saved inside the .gpd / .gpa file together with the active one. The tables are internal (no Excel link yet).
  Display: color (click the swatch, right-click resets), transparency slider and Shown checkbox for each component; a part has its own
  color / transparency (used when it is drawn alone, and in assemblies unless the component sets its own).

=== Starting, saving, reference geometry, the small tree ===
* The program opens with no document: File > New Part / New Assembly / Open.  Closing a tab or the program asks Save / Don't Save / Cancel
  for every document with unsaved changes (a star after the tab name marks them).
* Reference geometry (Part Features > Reference Geometry; in assemblies on the Assembly Features tab): a Plane or an Axis.
  - Pick the references (faces, edges, points, planes, axes) in the view or in the small tree; click a pick again to remove it.
  - Plane types: Offset distance, At angle, Parallel at point, Perpendicular, Mid plane, Through 3 points, Coincident.
    Axis types: One line/edge/axis, Two planes, Two points, Cylindrical face, Point and face/plane.
    The type follows what you pick until you choose one yourself.  Not included: planes tangent to a curved surface, planes from curves.
  - In a part a reference plane can be sketched on (select it, press Sketch) and mirrored about.  Double-click a plane/axis in the tree
    (or right-click > Edit references) to change its references.  The tree checkbox shows/hides it; the Show menu has "Reference geometry".
  - Sketching is for parts only.  An assembly has no sketches; its reference planes/axes are built from components and the assembly
    planes, they move with the components, and they can be mated to, mirrored about or patterned around.
* An assembly has its own Origin and Front / Top / Right planes (tree + Show menu + a checkbox for each) which can be mated to.
  A component's own reference planes/axes appear under it in the tree and can be picked for mates.
* The small tree (top left of the 3D view, "Tree" button): a see-through copy of the big tree.  While a command asks for picks (mate,
  reference plane/axis, mirror, pattern) a click on an item adds it; otherwise a click selects it in the big tree.
* Mates: tick/untick = suppress, double-click or right-click > Edit Mate, right-click > Delete Mate (Ctrl+Z undoes).

=== Assemblies inside assemblies ===
* Insert Components accepts .gpa files too.  A sub-assembly is RIGID: it moves as one body (fix / float / mate its faces, edges, points and planes
  like a part).  Its internal mates are solved from its own file and cannot be changed from the parent; the tree lists the parts inside it.
* Edit Component opens the .gpa in its tab (the parent follows its live state).  Sub-assemblies can be patterned / mirrored like parts.
* The parent's Configurations table can switch which configuration of the sub-assembly is used (Configuration@<name> column).
* An assembly cannot contain itself, directly or through others (refused with a message).  Mass properties of the parent include
  everything inside, each part with its own density.  A sub-assembly is drawn in one colour (the Display tab colour of the component).

=== Material of a part ===
* The tree entry "Material <name>" (double-click, or right-click > Edit Material...) opens the library: pick one or type your own values
  (density, E, Poisson's ratio, yield and ultimate strength).  "Save to library" keeps your own materials (gpd_materials.json next to the
  program); the built-in ones are typical textbook values - check them against your source.  The density feeds the mass properties too.

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
