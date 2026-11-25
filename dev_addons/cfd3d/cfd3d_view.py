"""cfd3d_view.py - the 3D view of the 3D Fluid Flow window: the solid_view.SolidView of the 3D FEA (the part, its faces, picking, the legend, the axes) with what
a flow needs on top of it:

  * the surface of the part coloured by the field on show (pressure, temperature ...) - or plain grey where the field is zero there (the speed: the fluid sticks)
  * a slice through the fluid (a plane, along one axis, at a position) coloured by the same field
  * flow lines: the paths of fluid particles from seeds upstream of the part, coloured by the same field
  * the box of the fluid domain as a wire frame

Everything is drawn with the one colour scale and legend of the field (result_style), like the other result views.
"""
import numpy as np

import result_style
import solid_view as sv

pv = sv.pv


def box_segments(lo, hi):
    """The 12 edges of the box lo..hi as [(p0, p1)]."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    c = [np.array([x, y, z]) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
    return [(tuple(c[a]), tuple(c[b])) for a, b in pairs]


def seed_grid(lo, hi, axis, sign, n, along=0.06, cross_lo=None, cross_hi=None, margin=0.15):
    """Seed points of the flow lines: about n of them on a plane across the flow, a little way into the domain from the inlet, spread over the cross-section
    cross_lo..cross_hi (the part's, by default the domain's), widened by `margin`.  `axis` 0..2 and `sign` +1 / -1: the way the fluid flows."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    cl = np.asarray(lo if cross_lo is None else cross_lo, float)
    ch = np.asarray(hi if cross_hi is None else cross_hi, float)
    keep = [i for i in range(3) if i != axis]
    k = max(2, int(round(np.sqrt(max(int(n), 4)))))
    a0 = lo[axis] + along * (hi[axis] - lo[axis]) if sign > 0 else hi[axis] - along * (hi[axis] - lo[axis])
    g = []
    for i in keep:
        w = (ch[i] - cl[i]) * (0.5 + margin)
        c = 0.5 * (ch[i] + cl[i])
        g.append(np.linspace(max(c - w, lo[i] + 1e-6 * (hi[i] - lo[i])), min(c + w, hi[i] - 1e-6 * (hi[i] - lo[i])), k))
    P = np.zeros((k * k, 3))
    A, B = np.meshgrid(g[0], g[1], indexing="ij")
    P[:, keep[0]] = A.ravel()
    P[:, keep[1]] = B.ravel()
    P[:, axis] = a0
    return P


class FluidView(sv.SolidView):
    def __init__(self, parent):
        self.scene = {}                            # name -> actor: "slice", "lines"
        self.info = {}                             # what the last show_fluid drew: {"slice_points", "stream_points", "stream_lines", "part_triangles"}
        super().__init__(parent)

    def clear_result(self):
        if self.scene and self.plotter is not None:
            for a in self.scene.values():
                try:
                    self.plotter.remove_actor(a)
                except Exception:                                    # noqa: BLE001
                    pass
        self.scene = {}
        self.info = {}
        super().clear_result()

    def apply_focus(self):
        super().apply_focus()
        try:
            on = self.focus in (None, "results")
            for a in self.scene.values():
                a.SetVisibility(on)
        except Exception:                                            # noqa: BLE001 - a view that cannot draw must not break the window
            pass

    @staticmethod
    def _colours(values, lo, hi, flip=False):
        v = np.asarray(values, float)
        span = hi - lo
        t = (v - lo) / span if span > 0 else np.zeros_like(v)
        if flip:
            t = 1.0 - t
        return result_style.ramp(np.nan_to_num(t, nan=0.0)).round().astype(np.uint8)

    def show_fluid(self, nodes, tets, u, values, lo, hi, part_tris, colour_part=True, slice_spec=None, lines=None, legend=None, flip=False):
        """Draws the result.  `values`: the field at every node (display units) between lo and hi; `part_tris`: the triangles of the mesh on the part;
        `colour_part`: False draws the part plain grey (a field that is zero on a wall); `slice_spec` = (axis 0..2, position along it in mesh units) or None;
        `lines` = {"seeds": (n, 3), "max_length": mesh units} or None.  -> True when there is a view."""
        if self.plotter is None:
            return False
        self.clear_result()
        nodes = np.asarray(nodes, float)
        values = np.asarray(values, float)
        grey = np.array(sv.GREY) * 255.0
        n_part = 0
        if len(part_tris):
            used, inv = np.unique(np.asarray(part_tris).ravel(), return_inverse=True)
            poly = pv.PolyData(nodes[used], np.hstack([np.full((len(part_tris), 1), 3), inv.reshape(-1, 3)]).ravel())
            poly.point_data["rgb"] = self._colours(values[used], lo, hi, flip) if colour_part else np.tile(grey, (len(used), 1)).astype(np.uint8)
            self.result_actor = self.plotter.add_mesh(poly, scalars="rgb", rgb=True, show_edges=False, reset_camera=False, show_scalar_bar=False)
            n_part = len(part_tris)
            if self.actor is not None:
                self.actor.SetVisibility(False)
        info = {"part_triangles": n_part, "slice_points": 0, "stream_points": 0, "stream_lines": 0}
        if slice_spec is not None or lines is not None:
            grid = pv.UnstructuredGrid(sv._cells(tets), np.full(len(tets), pv.CellType.TETRA, np.uint8), nodes)
            grid.point_data["v"] = values
            grid.point_data["u"] = np.asarray(u, float)
            if slice_spec is not None:
                ax, pos = int(slice_spec[0]), float(slice_spec[1])
                nrm = np.zeros(3)
                nrm[ax] = 1.0
                org = 0.5 * (nodes.min(axis=0) + nodes.max(axis=0))
                org[ax] = pos
                sl = grid.slice(normal=nrm, origin=org)
                if sl.n_points:
                    sl.point_data["rgb"] = self._colours(sl.point_data["v"], lo, hi, flip)
                    self.scene["slice"] = self.plotter.add_mesh(sl, scalars="rgb", rgb=True, show_edges=False, reset_camera=False, show_scalar_bar=False)
                    info["slice_points"] = int(sl.n_points)
            if lines is not None:
                st = None
                try:
                    st = grid.streamlines_from_source(pv.PolyData(np.asarray(lines["seeds"], float)), vectors="u", integration_direction="forward",
                                                      max_length=float(lines["max_length"]), max_steps=6000, terminal_speed=1e-12, compute_vorticity=False)
                except Exception:                                    # noqa: BLE001 - an older pyvista or a seed outside the mesh: no flow lines, the rest is drawn
                    st = None
                if st is not None and st.n_points:
                    st.point_data["rgb"] = self._colours(st.point_data["v"], lo, hi, flip)
                    self.scene["lines"] = self.plotter.add_mesh(st, scalars="rgb", rgb=True, line_width=2, reset_camera=False, show_scalar_bar=False)
                    info["stream_points"] = int(st.n_points)
                    info["stream_lines"] = int(st.n_lines) if hasattr(st, "n_lines") else 0
        self.info = info
        self.set_legend(legend)
        self.apply_focus()
        return True
