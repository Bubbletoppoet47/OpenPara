# 3D view: look, hover and the geometry selector

**Status:** asked for by Ian on 2026-11-27 and confirmed by him the same day ("Yes, go for it"). **Built** the same day as VW-1 to VW-4 (see `../../ISSUES.md`); pushed to `dev`, not yet looked at by Ian in a running window. There are no boards for this one: Ian's reference was screenshots of another CAD program's window, which are not filed here. What was agreed is written below.

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
- **Tools** that pick geometry of more than one kind. In the part window Measure starts with the bar on General (and Fillet and Chamfer always pick by General, whatever the bar says). In the assembly the tools (Mate, Reference geometry, Pattern, Mirror plane, Axis pick, Measure) take the bar back from Body to General, because a whole body means nothing to them; Point, Edge and Face stay as chosen. In a sketch the sketch editor does its own picking and the bar is greyed.
- In the assembly's normal mode a click still selects a component. The hover outline is drawn there only for Body, Face, Edge or Point; with General nothing is outlined, because a click would not pick a face.
- The old Faces / Edges / Points toggles in the Mate panel are replaced by this bar, so there is one place. (The assembly already had a Show button; the bar sits beside it, as in the part window.)

## The shadow

A soft contact shadow is drawn on a floor under the lowest point of the model (Z up): the model's shape is flattened onto the floor along a light that comes from above and a little from the front left, blurred, and drawn as a transparent picture. It is made again when the model changes, not on every turn of the view, and it is hidden when the view looks from below the floor. It is a picture, not a real-time shadow, so it costs almost nothing while rotating. Models with more than a set number of triangles use a coarser picture.

## The 3D simulation windows (VW-3, VW-4)

The Structural, Thermal 3D and CFD 3D windows have the same bar, beside the Show button, with the same pick distances. What each window takes on what is picked:

- **Structural.** Support (fixed or a prescribed displacement) on faces, edges or points. Force on faces **or** edges (shared by area, or by length), or on one or more points (shared equally). Pressure on faces only.
- **Thermal 3D.** Temperature on faces, edges or points. Heat (power) on faces **or** edges **or** points. Flux, convection, radiation and insulation on faces only.
- **CFD 3D.** The bar has General, Face and Body; Point and Edge are greyed and their tip says why (an inlet, an outlet and a wall are faces). General picks a face; Body picks a part.

How selecting works in all three:

- **Selecting.** A plain click replaces the whole selection (faces, edges, points or a body); Ctrl or Shift adds to it or takes from it. Selected faces are filled with the selected colour; selected edges and points are drawn in the hover colour, thick, over the part.
- **Body** chooses a part: all its faces take the selected colour and its row is selected in the tables of the material and of the element size. A body cannot carry a support or a condition, and the status line says so ("a whole part is for its material and element size").
- **Edges and points are on the geometry.** A condition on an edge is applied to the mesh nodes that lie along that edge: the corner nodes on it, and the mid-edge nodes between consecutive corner nodes. The loads are shared by length (quadratic: L/6, 4L/6, L/6 per piece; linear: L/2), a point condition goes to the corner node at the vertex. Closed edges (a circle) work. The mid-edge nodes of the quadratic mesh are straight midpoints, so on a curved edge only the corner nodes lie on the curve: the window uses the corner chain and finds the mid nodes between them.
- **When the mesh has no nodes there**, the window says so and does not approximate: "this mesh has no nodes along that edge ... Use a face ..." when none lie on it, and "does not follow all of edge N (its nodes cover X % of it)" when only part of it is covered. A hexdominant mesh gives this on many edges, and Thermal does not take a hexdominant mesh at all.
- **One edge or one point alone cannot hold a part.** The solve reports that the part is free to move or turn; add a second support.
- **Marks.** Edges and points that carry a condition are drawn over the part in the colour of that condition's tag (the part window's outline focus "Conditions" shows them). The selected-face blue (#00b4ff) is near the Support tag blue; both colours are settings or tags that can be changed.
- **Assemblies** keep their per-body soft colours in the simulation windows (so the parts can be told apart where the material or mesh differs), and there is **no floor shadow** in these windows. The part colour setting colours a single-part simulation window.
- Data: a support or load keeps `"faces"` (always, possibly empty) and may add `"edges"` and `"points"` (each as a signature that is matched again after a re-import, `solid_geom.edge_sig` / `match_edge`). Old projects open as they were.

## Not changed

The render studio's materials, the drawings, the Workbench canvas and the simulation result colours are not part of this. Ian's own colours on parts stay.

## Limits

- The shadow is a picture (flattened, blurred), made again when the model changes; models above about 900 000 triangles get none. It is not drawn in the simulation windows.
- The lighting is a little brighter than before so that the grey reads as grey.
- CFD 3D keeps Face and Body: an inlet, an outlet and a wall are faces.
- A condition on an edge or a point needs mesh nodes there (above). Point and edge conditions for CFD are not part of this.
- The new colours are registered in `planning/design/theme/palette.json` (tier "viewport"): #999999, #ff7300, #00b4ff.

## Where the build is

`view3d.py` (settings colours, the hover outline, the shadow, the selector bar and the pick rules), `pm_app.py`, `assembly.py`, `asm_refs.py`, `settings.py`, `settings_dialog.py`, `icon_shapes.py` (five icons); the simulation windows in `dev_addons/solid_fea/` (`solid_view.py` picking, hover and marks; `solid_base.py` the bar, selection and marks; `solid_geom.py` edges and the edge chain; `solid_model.py` resolving edge and point conditions; `solid_tab.py` Structural), `dev_addons/thermal3d/` (`thermal3d_model.py`, `thermal3d_fem.py`, `thermal3d_tab.py`) and `dev_addons/cfd3d/` (`cfd3d_tab.py`, `cfd3d_view.py`).

Tests: `test_view3d.py` (look, settings, shadow, hover, selector, picks in the part and assembly windows), `test_view3d_sim.py` (edges and chains on tet, linear and hexdominant meshes, the bar in the three windows, picks, clicks, edge and point supports, loads and heat with solves: equilibrium, a cantilever held on four edges, heat balance, the missing-node messages, CFD faces and body, assembly Body), and the changed `test_solid_hooks.py`, `test_asm_baked_outlines.py`, `test_lab_highlight.py`, `test_mate_panel_ui.py`.
