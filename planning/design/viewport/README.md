# 3D view: look, hover and the geometry selector

**Status:** asked for by Ian on 2026-11-27 and confirmed by him the same day ("Yes, go for it"). Built as VW-1 to VW-4 (see `../../ISSUES.md`). There are no boards for this one: Ian's reference was screenshots of another CAD program's window, which are not filed here. What was agreed is written below.

## What Ian asked for

1. **A neutral colour.** Parts and assemblies were drawn in colours (an assembly cycled through six: blue-grey, tan, green, purple, yellow, teal; a part window used one blue-grey). Modern parametric programs use one neutral grey with ordinary lighting. Ian chose **60 % grey**.
2. **Hover shows an outline, a click fills.** The cursor over a face draws an outline along its edges (the holes included); an edge or a point lights up itself; a click fills the face solid. Ian chose **orange** for the outline and **blue** for the fill.
3. **A soft shadow on the floor under the part**, as in the reference pictures. On by default.
4. **Every one of these is a setting** that can be turned off or recoloured (File > Settings > 3D View).
5. **A geometry selector**, as in Ansys: **General, Point, Edge, Face, Body**. The chosen kind gets a wider pick distance, so a corner or an edge is easy to hit without the other kinds getting in the way. Beside the **Show** button in the part and assembly windows, and in the 3D simulation windows. In the simulation windows **Body** chooses a whole part (its material and mesh size), and points and edges can carry supports, loads and heat.

## Settings (File > Settings > 3D View, and Picking & Snapping)

| Setting | Key | Default |
|---|---|---|
| Highlight what is under the cursor | `hover` | on |
| Shadow under the part | `shadow` | on |
| Part colour | `part_color` | `#999999` (60 % grey) |
| Hover outline colour | `hover_color` | `#ff7300` (the selected-dimension orange) |
| Selected face colour | `select_color` | `#00b4ff` |
| Point pick distance (Point selected) | `pick_point_px` | 14 px |
| Edge pick distance (Edge selected) | `pick_edge_px` | 10 px |
| 3D pick distance (General) | `pick3d_px` | 4 px (as before) |

A colour set on one part (Display tab) or on one component of an assembly still wins over `part_color`.

## How the selector behaves

- **General** (the default) is what the windows did before: a point close to the cursor wins over an edge, an edge over a face.
- **Point, Edge, Face** pick only that kind, with the wider distance for points and edges. A click that is not on that kind picks nothing.
- **Body** picks the whole part (or component). Hover outlines the whole body; a click selects it.
- **Tools** that need geometry of more than one kind (Measure, Fillet and Chamfer, the Mate and Reference geometry tools) put the bar back to General when they start. The bar can still be changed while the tool is open, except in a sketch, where the sketch editor does its own picking and the bar is greyed.
- In the assembly's normal mode a click still selects a component. The hover outline is drawn there only for Body, Face, Edge or Point; with General nothing is outlined, because a click would not pick a face.
- The old Faces / Edges / Points toggles in the Mate panel are replaced by this bar, so there is one place.

## The shadow

A soft contact shadow is drawn on a floor under the lowest point of the model (Z up): the model's shape is flattened onto the floor along a light that comes from above and a little from the front left, blurred, and drawn as a transparent picture. It is made again when the model changes, not on every turn of the view, and it is hidden when the view looks from below the floor. It is a picture, not a real-time shadow, so it costs almost nothing while rotating. Models with more than a set number of triangles use a coarser picture.

## Not changed

The render studio's materials, the drawings, the Workbench canvas and the simulation result colours are not part of this. Ian's own colours on parts stay.

## Where the build is

`view3d.py` (settings colours, the hover outline, the shadow, the selector bar and the pick rules), `pm_app.py`, `assembly.py`, `dev_addons/solid_fea/solid_view.py` and `solid_base.py`, `settings.py`, `settings_dialog.py`, `icon_shapes.py` (five icons). Tests: `test_view3d.py` and the ones named in the Done entries.
