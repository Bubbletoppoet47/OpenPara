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
  Measure and Mass Properties and the slice plane offset.
  Systems: Metric (mm, kg, N, s, MPa) [default], (cm, ... N/cm2), (m, ... Pa), (m, kN, kPa), (mm, kN, kN/mm2),
           US (in, lbf, psi), (in, kip, ksi), (ft, lbf, psf), (ft, kip, ksf).
  Speed is a separate choice (m/s, km/h, mph, ft/s, mm/s, in/s), so a wind speed can be in mph with metric lengths.
  Your files are not changed: geometry is always stored in millimetres, so switching units only changes what is shown and how
  typed numbers are read.
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
  A part tab shows Part Features / Sketch / Evaluate. An assembly tab shows Assembly Features / Evaluate. Add-ons (File > Add-ons) can add buttons and tabs.
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

=== Add-ons (File > Add-ons) ===
The core of OpenPara is Sketch/Part and Assembly.  Everything else is an add-on that you install when you need it (it is downloaded from
the GitHub release of your version; once installed it works offline):
* Part Generator - gears and other parts from a few parameters (Part Features > Part Generator).  A part that uses it keeps its data
  without the add-on and says that it needs it; install the add-on and it rebuilds.
* Truss Generator - the members of a truss from the lines of a sketch (File > New Truss Generator, or File > Open Project Folder).
Uninstalling an add-on never touches your files.
