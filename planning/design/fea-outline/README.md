# FEA Outline and Details

**Status:** the Outline and Details column is built since `6324847` (2026-11-24). Whether every analysis follows board 2 item for item has not been checked. No separate sign-off is recorded.

Hosted copy on Ian's Claude account (board 1 is clickable there): <https://claude.ai/artifact/9cBhrjZ9divDRnLzbwfHkP>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-fea-window.png` | 3D FEA window (click around) | A 3D analysis window, with *Mesh* selected. On the hosted board, clicking the outline changes the details and the view. |
| `2-outline-per-analysis.png` | The outline for every kind of analysis | The outline of 3D Static Structural, 3D Thermal, 2D Static Structural, 2D Thermal, 2D Fluid Flow and 1D Beam and Truss, and where today's numbered sections go. |

## What the boards decide

- **Outline above Details, in one column.** The view follows the selected item and shows only what that item is about.
- **Folders and items.** *Mesh*, *Supports*, *Loads* (*Conditions* in the thermal analyses) and *Solution* are folders. The things you insert yourself (a face sizing, a fixed support, a force) are items inside them; fixed things (Geometry, Material, Solution information, Results) are single rows.
- **One order for every analysis:** geometry, material, mesh, what acts on the model, then the solution. Only the middle changes with the physics.
- **Today's numbered sections** (1 Geometry, 2 Material and analysis, 3 Supports, 4 Loads, 5 Mesh, 6 Results) map to the outline as board 2 says; the solver choice and triggers get their own *Analysis settings* item in 1D and 2D.

## Where the build is

`6324847` (2026-11-24): the Outline and Details column in the FEA windows, the view follows the selection, lettered condition tags. Later changes to the same windows: `c0c0d8a`, `320c6f4`.

`source/` holds the board files.
