"""dr_shade.py - the shaded display styles of a drawing view (Shaded With Edges, Shaded): the surface of the model seen from the view's direction, lit like a part on a drawing table.

    mesh_of(shape, right, up, eye)      the triangles of a build123d shape in the view's frame (x to the right, y up, z toward the viewer) with the normal of the surface at every corner
                                        (model units, mm).  Smooth inside a face, a crease between faces.  The mesh is kept as text, so that it goes into the file as it is and a copy
                                        of the document (undo) costs nothing:  {"n": corners, "m": triangles, "v": base64 of float32 [n, 6] (x, y, z, nx, ny, nz), "t": base64 of int32 [m, 3]}
    encode(V, T) / decode(mesh)         arrays <-> that text (decode gives float64 [n, 6] and int64 [m, 3])
    bbox(mesh)                          (xmin, ymin, xmax, ymax) of the triangles
    render(mesh, px, ss=2)              -> Shaded: the picture of the mesh with `px` pixels to every mm of the model (a z-buffer, so what is nearer hides what is behind it whatever the order
                                        of the triangles); ss x ss samples to a pixel give clean edges.  Plain numpy: no Qt, no build123d, nothing to install.
    Shaded                              .rgba (H x W x 4, uint8, grey with an alpha: 0 where there is no surface), .x0 / .y1 (the left and the top of the picture in the view's frame),
                                        .px (pixels to the mm: smaller than asked when the picture would have been too big)
    brightness(n) / grey(i)             the light: from the upper left, in front, with some light everywhere (a grey between 70 and 245, so that the black lines of a drawing show on it)
"""
import base64
import math

import numpy as np

AMBIENT = 0.30
LIGHT = np.array([-0.35, 0.5, 0.8]) / math.sqrt(0.35 ** 2 + 0.5 ** 2 + 0.8 ** 2)          # toward the light, in the view's frame
GREY_DARK, GREY_LIGHT = 70.0, 245.0
MAX_SAMPLES = 9_000_000                            # the most samples (pixels x ss x ss) of one picture
BUDGET = 900_000                                   # candidate samples looked at together
NORMAL_FALLBACK_TOL = 1e-9


def brightness(n):
    """0..1 for a unit normal (in the view's frame): some light everywhere, the most where the surface faces the light."""
    n = np.asarray(n, float)
    return AMBIENT + (1.0 - AMBIENT) * np.maximum(0.0, n @ LIGHT)


def grey(i):
    return GREY_DARK + (GREY_LIGHT - GREY_DARK) * np.asarray(i, float)


class Shaded:
    def __init__(self, rgba, x0, y1, px):
        self.rgba, self.x0, self.y1, self.px = rgba, float(x0), float(y1), float(px)

    @property
    def width(self):
        return self.rgba.shape[1]

    @property
    def height(self):
        return self.rgba.shape[0]


# ---------------------------------------------------------------------------------------------------------------------------- the mesh
def mesh_of(shape, right, up, eye, tol=None, angular=0.1):
    """The triangles of `shape` in the frame of a view (see the module's doc)."""
    from OCP.BRep import BRep_Tool
    from OCP.StdPrs import StdPrs_ToolTriangulatedShape
    from OCP.TopLoc import TopLoc_Location
    R = np.array([right, up, eye], float)                                    # model -> view
    bb = shape.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z])) or 1.0
    tol = max(diag * 1e-4, 0.005) if tol is None else tol
    shape.mesh(tol, angular)
    verts, tris, base = [], [], 0
    for f in shape.faces():
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(f.wrapped, loc)
        if poly is None or poly.NbNodes() == 0 or poly.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        n = poly.NbNodes()
        pts = np.array([[q.X(), q.Y(), q.Z()] for q in (poly.Node(i).Transformed(trsf) for i in range(1, n + 1))])
        reverse = f.wrapped.Orientation().name.endswith("REVERSED")
        tr = np.array([(t.Value(1) - 1, t.Value(3) - 1, t.Value(2) - 1) if reverse else (t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1) for t in poly.Triangles()], dtype=np.int64)
        nrm = _surface_normals(f, poly, trsf, n)
        gn = _vertex_normals(pts, tr)                                         # from the triangles: they are the way round that the winding says (outward)
        if nrm is None:
            nrm = gn
        elif float(np.sum(nrm * gn)) < 0.0:                                   # the surface's own normals look the other way: the face is turned round
            nrm = -nrm
        verts.append(np.hstack([pts @ R.T, nrm @ R.T]))
        tris.append(tr + base)
        base += n
    if not verts:
        return None
    return encode(np.vstack(verts), np.vstack(tris))


def encode(V, T):
    V = np.ascontiguousarray(V, np.float32).reshape(-1, 6)
    T = np.ascontiguousarray(T, np.int32).reshape(-1, 3)
    return {"n": int(len(V)), "m": int(len(T)), "v": base64.b64encode(V.tobytes()).decode("ascii"), "t": base64.b64encode(T.tobytes()).decode("ascii")}


def decode(mesh):
    """(V float64 [n, 6], T int64 [m, 3]) of a mesh; ValueError when it is not one (a damaged file)."""
    try:
        n, m = int(mesh["n"]), int(mesh["m"])
        V = np.frombuffer(base64.b64decode(mesh["v"]), np.float32).reshape(n, 6).astype(np.float64)
        T = np.frombuffer(base64.b64decode(mesh["t"]), np.int32).reshape(m, 3).astype(np.int64)
    except (KeyError, TypeError, ValueError, AttributeError) as ex:
        raise ValueError(f"not a mesh: {ex}")
    if m and (T.min() < 0 or T.max() >= n):
        raise ValueError("not a mesh: a triangle has a corner that is not there")
    return V, T


def _surface_normals(face, poly, trsf, n):
    """The normal of the surface at every node of a face's triangulation (OCC's own, exact on a cylinder or a sphere); None when it cannot be had."""
    try:
        from OCP.StdPrs import StdPrs_ToolTriangulatedShape
        StdPrs_ToolTriangulatedShape.ComputeNormals_s(face.wrapped, poly)
        out = np.array([[d.X(), d.Y(), d.Z()] for d in (poly.Normal(i).Transformed(trsf) for i in range(1, n + 1))])
    except Exception:                                                         # noqa: BLE001
        return None
    ln = np.linalg.norm(out, axis=1)
    if not np.all(np.isfinite(out)) or float(ln.min()) < 0.5:
        return None
    return out / ln[:, None]


def _vertex_normals(pts, tr):
    """The normals of the corners from the triangles around them (area weighted)."""
    a, b, c = pts[tr[:, 0]], pts[tr[:, 1]], pts[tr[:, 2]]
    fn = np.cross(b - a, c - a)
    out = np.zeros_like(pts)
    for k in range(3):
        np.add.at(out, tr[:, k], fn)
    ln = np.linalg.norm(out, axis=1)
    ln[ln < NORMAL_FALLBACK_TOL] = 1.0
    return out / ln[:, None]


def bbox(mesh):
    v = decode(mesh)[0]
    if not len(v):
        return (0.0, 0.0, 0.0, 0.0)
    return (float(v[:, 0].min()), float(v[:, 1].min()), float(v[:, 0].max()), float(v[:, 1].max()))


# ---------------------------------------------------------------------------------------------------------------------------- the picture
def render(mesh, px, ss=2):
    """The picture of a mesh (see the module's doc); None when there is nothing to see."""
    V, T = decode(mesh)
    if not len(V) or not len(T):
        return None
    x0, y0, x1, y1 = (float(V[:, 0].min()), float(V[:, 1].min()), float(V[:, 0].max()), float(V[:, 1].max()))
    px = float(px)
    ss = max(1, int(ss))
    while True:
        W = int(math.ceil((x1 - x0) * px)) + 2
        H = int(math.ceil((y1 - y0) * px)) + 2
        if W * H * ss * ss <= MAX_SAMPLES or (px < 1e-3 and ss == 1):
            break
        if ss > 1:
            ss = 1
        else:
            px *= 0.8
    Ws, Hs = W * ss, H * ss
    f = px * ss
    SX = (V[:, 0] - x0) * f + ss                                              # a margin of one pixel round the picture
    SY = (y1 - V[:, 1]) * f + ss
    Z = V[:, 2]
    ia, ib, ic = T[:, 0], T[:, 1], T[:, 2]
    ax, ay, bx, by, cx, cy = SX[ia], SY[ia], SX[ib], SY[ib], SX[ic], SY[ic]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    # the way the triangle faces in the view's frame (z of the cross product), from the true coordinates
    e1, e2 = V[ib, :2] - V[ia, :2], V[ic, :2] - V[ia, :2]
    facing = np.where(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0] >= 0.0, 1.0, -1.0)
    xmin = np.maximum(np.floor(np.minimum(np.minimum(ax, bx), cx) - 0.5), 0).astype(np.int64)
    xmax = np.minimum(np.ceil(np.maximum(np.maximum(ax, bx), cx) + 0.5), Ws - 1).astype(np.int64)
    ymin = np.maximum(np.floor(np.minimum(np.minimum(ay, by), cy) - 0.5), 0).astype(np.int64)
    ymax = np.minimum(np.ceil(np.maximum(np.maximum(ay, by), cy) + 0.5), Hs - 1).astype(np.int64)
    keep = (np.abs(area) > 1e-12) & (xmax >= xmin) & (ymax >= ymin)
    idx = np.nonzero(keep)[0]
    zbuf = np.full(Hs * Ws, -np.inf, np.float32)
    col = np.zeros(Hs * Ws, np.float32)
    if len(idx):
        bw, bh = xmax - xmin + 1, ymax - ymin + 1
        idx = idx[np.argsort((bw * bh)[idx], kind="stable")]
        ctx = (SX, SY, Z, V[:, 3:6], T, area, facing, xmin, ymin, Ws, Hs, zbuf, col)
        i = 0
        while i < len(idx):
            j, cw, ch = i + 1, int(bw[idx[i]]), int(bh[idx[i]])
            if cw * ch > BUDGET:                                              # one large triangle: in bands of rows
                t = int(idx[i])
                rows = max(1, BUDGET // cw)
                for r0 in range(0, ch, rows):
                    _chunk(ctx, np.array([t]), int(ymin[t]) + r0, cw, min(rows, ch - r0))
                i += 1
                continue
            while j < len(idx):
                nw, nh = max(cw, int(bw[idx[j]])), max(ch, int(bh[idx[j]]))
                if (j + 1 - i) * nw * nh > BUDGET:
                    break
                cw, ch, j = nw, nh, j + 1
            _chunk(ctx, idx[i:j], None, cw, ch)
            i = j
    cov = np.isfinite(zbuf).astype(np.float32).reshape(H, ss, W, ss).sum(axis=(1, 3))
    gsum = (col.reshape(Hs, Ws) * np.isfinite(zbuf).reshape(Hs, Ws)).reshape(H, ss, W, ss).sum(axis=(1, 3))
    alpha = cov / float(ss * ss)
    g = np.where(cov > 0, gsum / np.maximum(cov, 1.0), 0.0)
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = np.clip(np.rint(g), 0, 255).astype(np.uint8)
    rgba[..., 3] = np.clip(np.rint(alpha * 255.0), 0, 255).astype(np.uint8)
    # the picture's pixel (0, 0) is one pixel left of and above (x0, y1)
    return Shaded(rgba, x0 - 1.0 / px, y1 + 1.0 / px, px)


def _chunk(ctx, tri, row0, bw, bh):
    """The samples of some triangles (the rows row0.. of their boxes when row0 is given), the nearest one kept in the z-buffer."""
    SX, SY, Z, N, T, area, facing, xmin, ymin, Ws, Hs, zbuf, col = ctx
    a, b, c = T[tri, 0], T[tri, 1], T[tri, 2]
    gx = xmin[tri][:, None, None] + np.arange(bw)[None, None, :]
    gy = (ymin[tri] if row0 is None else np.full(len(tri), row0))[:, None, None] + np.arange(bh)[None, :, None]
    qx, qy = gx + 0.5, gy + 0.5
    ax, ay, bx, by, cx, cy = (v[:, None, None] for v in (SX[a], SY[a], SX[b], SY[b], SX[c], SY[c]))
    ar = area[tri][:, None, None]
    w0 = ((bx - qx) * (cy - qy) - (by - qy) * (cx - qx)) / ar
    w1 = ((cx - qx) * (ay - qy) - (cy - qy) * (ax - qx)) / ar
    w2 = 1.0 - w0 - w1
    eps = 1e-9
    inside = (w0 >= -eps) & (w1 >= -eps) & (w2 >= -eps) & (gx < Ws) & (gy < Hs)
    k, r, s = np.nonzero(inside)
    if not len(k):
        return
    f0, f1, f2 = w0[k, r, s], w1[k, r, s], w2[k, r, s]
    t = tri[k]
    z = f0 * Z[a[k]] + f1 * Z[b[k]] + f2 * Z[c[k]]
    pix = gy[k, r, 0] * Ws + gx[k, 0, s]
    order = np.lexsort((z, pix))                                             # by sample, nearest last
    pix, z, f0, f1, f2, t, ak, bk, ck = pix[order], z[order], f0[order], f1[order], f2[order], t[order], a[k][order], b[k][order], c[k][order]
    last = np.r_[pix[1:] != pix[:-1], True]
    pix, z, f0, f1, f2, t, ak, bk, ck = pix[last], z[last], f0[last], f1[last], f2[last], t[last], ak[last], bk[last], ck[last]
    win = z > zbuf[pix]
    if not np.any(win):
        return
    pix, z, f0, f1, f2, t, ak, bk, ck = pix[win], z[win], f0[win], f1[win], f2[win], t[win], ak[win], bk[win], ck[win]
    n = f0[:, None] * N[ak] + f1[:, None] * N[bk] + f2[:, None] * N[ck]
    ln = np.linalg.norm(n, axis=1)
    ln[ln < 1e-12] = 1.0
    n = n / ln[:, None] * facing[t][:, None]                                  # a triangle that faces away and is still seen (an open shell): lit from the side it is seen from
    zbuf[pix] = z
    col[pix] = grey(brightness(n))
