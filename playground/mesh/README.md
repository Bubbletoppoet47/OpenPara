# Mesh playground (organic STL work)

A standalone test bench, not part of the installer and not wired into OpenPara. It exists to find out what works on real-world
organic meshes before anything is integrated. Run everything from this folder or the repository root.

| file | what it does |
|---|---|
| `shapes.py` | Test shapes (blob, torus, bone, noisy scan, box bar) and seven kinds of damage (unmerged corners, holes, flipped triangles, spikes, fins, zero-area/duplicate triangles, loose fragments). `corpus()` returns 13 meshes. |
| `repair.py` | `diagnose` (open edges, non-manifold edges, flipped triangles, degenerate/duplicate triangles, shells, volume, worst triangle) and `repair` (merge points, collapse slivers, remove fins, orient, drop loose shells, flatten spikes, fill holes) with a before/after report. |
| `remesh.py` | `refine` (split edges where the target size is smaller; shape unchanged), `coarsen` (size-gated quadric edge collapse), `remesh` (both), `reduce` (global quadric decimation), `subdivide`, `deviation`. Zones: sphere, box, distance from a point or line, curvature. |
| `solid.py` | `faceted_solid` (OCC solid, one planar face per triangle), `tet_mesh` (gmsh tetrahedra whose boundary is the mesh's own triangles), `tet_quality`. |
| `section.py` | `cut` a mesh with a plane, then `fea` / `cfd` on the cut using the program's own `physics_fea` and `physics_cfd`. |
| `mesh_play.py` | Command line: `corpus`, `repair`, `remesh`, `reduce`, `solid`, `fea`, `cfd`. |
| `test_mesh_play.py` | 48 checks, about 2-3 minutes. Includes a cantilever FEA against beam theory. |

## What the tests show

* All 13 corpus meshes end as one closed, consistently oriented shell. Volume comes back to the clean shape within 0.2 % for
  everything except holes (filled flat, so a little volume is lost: about 0.5 % for three 12 mm holes in a 90 mm blob).
* Refining inside a zone raises the facet count there only, and does not change the shape at all (new points sit on existing triangles).
  Coarsening to a 4 mm target keeps 95 % of the surface within about 0.6 % of the model size.
* Faceted solids are exact (volume equal to the mesh volume, valid in OCC). They take about 4 s per 4 000 triangles.
* The mid-plane cut of a 100 x 10 x 10 mm bar, cantilevered and loaded with 1000 N, gives a tip deflection of 2.012 mm against 2.000 mm
  from beam theory (0.6 % apart).

## Limits to know about

* **Self-intersections are not repaired.** Tetrahedralisation of a noisy scan that cuts through itself first fails; the code then retries
  on a lightly smoothed copy and says so in the result. Detecting and fixing intersections properly is still open.
* **Hole filling is a flat fan to the loop's centre.** It closes the mesh but does not follow the curvature. Holes larger than a quarter of
  the model size are left open and reported.
* **Spike removal** only flattens single points that stand clear of a flat ring of neighbours. Broader bumps or noise are not touched.
* **Coarsening quality**: triangle shape (minimum angle) drops in heavily coarsened or locally refined regions; there is no edge flipping or
  smoothing pass yet. Slivers already in the input are kept by refine.
* **Faceted solids** are huge for large meshes (limit 30 000 triangles). There is no NURBS surface fitting.
* **The FEA / CFD are 2D idealisations of a cut**, not 3D analyses. The FEA is plane stress/strain with a thickness; the CFD is laminar
  flow past the outline. Both use the program's solvers unchanged. CFD at 9 000 triangles takes about 30 s per 50 steps.
* Nothing here has been used on a real scanned STL yet, only on generated shapes. Real scans will have harder damage than this corpus.
* Zones are given by coordinates in code; picking them with the mouse is for the integration step.
