# 2D Static Structural: material per region, Supports and Loads pages, Mesh page

**Status:** built since `320c6f4` (2026-11-25). No separate sign-off is recorded.

Hosted copy, interactive, on Ian's Claude account: <https://claude.ai/artifact/D89DGotNpfvGbGZ8arK2mT>

## Boards

| Picture | Board title | What it shows |
|---|---|---|
| `1-material-per-region.png` | Material and analysis: a material per region | A plate with two regions, each with its own material. |
| `2-supports-and-loads.png` | Supports and Loads: separate pages | The old Supports page next to the proposed Supports and Loads pages. |
| `3-mesh-page.png` | Mesh: details from the top, Advanced fully visible | The old Mesh page next to the proposed page with Advanced off and on. |

On boards 2 and 3 the left column is a screenshot of the window before the change ("real window").

## What the boards decide

- **Every region is tinted and named in the view.** Click a region to select its row; select a row to see it in the view (the selected region's outline is teal).
- **A material for each region.** Regions that touch along an edge are fully bonded: the mesh shares its nodes there.
- **Supports and Loads are separate pages.** Each starts at the top and lists only its own conditions, with a table (*Supports on this model*, *Loads on this model*) and *Edit selected* and *Remove selected* under it.
- **Details start at the top.** Ticking *Advanced mesh options* pulls the divider up so the whole page shows, with no scrolling.

## Where the build is

`320c6f4` (2026-11-25): the Mesh page fits in every 2D and 3D window, a material per region, regions tinted and named, separate Supports and Loads pages.

`source/` holds the board files and the two screenshots (`source/_blob/`, referred to as `/_blob/<id>` in the HTML).
