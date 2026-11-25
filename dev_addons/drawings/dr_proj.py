"""dr_proj.py - a model (a build123d shape) seen from a direction: the 2D lines of a drawing view.

    ORIENTATIONS                         the standard views: Front, Back, Left, Right, Top, Bottom and the three axonometric ones
    view_axes(name)                      (eye, up, right): unit vectors in the model's frame; the eye is the direction FROM the model TO the viewer
    project(shape, name, hidden=True)    -> Projection
    Projection.vis / .hid                entities: {"t": "line", "a", "b"} | {"t": "circle", "c", "r"} | {"t": "arc", "c", "r", "a0", "a1"} (counter-clockwise, radians)
                                         | {"t": "poly", "pts"};  every entity also has "pts" (the polyline that is drawn) and "n" (its number in the view)
    Projection.bbox()                    (xmin, ymin, xmax, ymax) of the visible lines, in model units, the model's origin at (0, 0)
    Projection.mesh                      None, or (for the shaded styles) the triangles of the model in this view's frame: dr_shade.mesh_of

The coordinates are the view's own: x to the right, y up, in the units of the model (mm), the origin of the model at (0, 0).  A hidden line that lies exactly on a visible one is not
kept (a box seen from the top has its bottom edges behind its top edges: they are not 'hidden lines').  The model's frame is the Part window's: Z up, the Front plane looks along +Y.
"""
import math

import numpy as np

ORIENTATIONS = ("Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric", "Trimetric", "Dimetric")
ORTHO = ("Front", "Back", "Left", "Right", "Top", "Bottom")
# the axonometric views: the azimuth from the -Y axis toward +X, and the elevation above the XY plane, degrees.  Isometric: all three axes shortened alike; Dimetric: two alike
# (the 1 : 1 : 1/2 ratio); Trimetric: all three differently.
AXONO = {"Isometric": (45.0, 35.26438968), "Dimetric": (20.7048, 19.4712206), "Trimetric": (30.0, 20.0)}
_ORTHO = {"Front": ((0, -1, 0), (0, 0, 1)), "Back": ((0, 1, 0), (0, 0, 1)), "Left": ((-1, 0, 0), (0, 0, 1)), "Right": ((1, 0, 0), (0, 0, 1)),
          "Top": ((0, 0, 1), (0, 1, 0)), "Bottom": ((0, 0, -1), (0, -1, 0))}
SAMPLES = 24                                                     # points on a free-form edge
ARC_STEP = math.radians(4.0)


def view_axes(name):
    """(eye, up, right) of a standard view: unit vectors in the model's frame (eye = from the model toward the viewer; up and right are the directions of the sheet's y and x)."""
    if name in _ORTHO:
        eye, up = (np.array(v, float) for v in _ORTHO[name])
    elif name in AXONO:
        az, el = (math.radians(a) for a in AXONO[name])
        eye = np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
        up = np.array([0.0, 0.0, 1.0])
    else:
        raise ValueError(f"'{name}' is not a standard view ({', '.join(ORIENTATIONS)}).")
    eye = eye / np.linalg.norm(eye)
    up = up - eye * float(np.dot(up, eye))
    up = up / np.linalg.norm(up)
    right = np.cross(-eye, up)
    return eye, up, right / np.linalg.norm(right)


class Projection:
    def __init__(self, name, vis, hid, mesh=None):
        self.name, self.vis, self.hid, self.mesh = name, vis, hid, mesh

    def bbox(self, hidden=False):
        pts = [p for e in (self.vis + (self.hid if hidden else [])) for p in e["pts"]]
        if not pts:
            return (0.0, 0.0, 0.0, 0.0)
        a = np.array(pts)
        return (float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max()))

    def to_json(self):
        out = {"name": self.name, "vis": self.vis, "hid": self.hid}
        if self.mesh:
            out["mesh"] = self.mesh
        return out

    @classmethod
    def from_json(cls, d):
        mesh = d.get("mesh")
        try:
            import dr_shade
            if mesh is not None:
                dr_shade.decode(mesh)
        except ValueError:                                           # a damaged mesh: the view shows its lines only
            mesh = None
        return cls(d["name"], [_entity(e) for e in d.get("vis", [])], [_entity(e) for e in d.get("hid", [])], mesh)


def _entity(e):
    out = dict(e)
    for k in ("a", "b", "c"):
        if k in out:
            out[k] = tuple(out[k])
    out["pts"] = [tuple(p) for p in out["pts"]]
    return out


def _xy(v):
    return (float(v.X), float(v.Y))


def _poly(edge, n):
    ts = np.linspace(0.0, 1.0, n)
    return [_xy(p) for p in edge.positions(ts)]


def _entity_of(edge):
    """One projected build123d edge as an entity (a line, a circle, an arc or a free-form polyline)."""
    g = edge.geom_type.name
    a, b = _xy(edge.start_point()), _xy(edge.end_point())
    if g == "LINE":
        return {"t": "line", "a": a, "b": b, "pts": [a, b]}
    if g == "CIRCLE":
        c = _xy(edge.arc_center)
        r = float(edge.radius)
        closed = math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-7 * max(1.0, r)
        if closed:
            pts = [(c[0] + r * math.cos(t), c[1] + r * math.sin(t)) for t in np.linspace(0.0, 2 * math.pi, max(36, int(2 * math.pi / ARC_STEP)) + 1)]
            return {"t": "circle", "c": c, "r": r, "pts": pts}
        m = _xy(edge.position_at(0.5))
        a0 = math.atan2(a[1] - c[1], a[0] - c[0])
        am = math.atan2(m[1] - c[1], m[0] - c[0])
        a1 = math.atan2(b[1] - c[1], b[0] - c[0])
        ccw = (am - a0) % (2 * math.pi) < (a1 - a0) % (2 * math.pi)             # the midpoint lies on the counter-clockwise way from start to end
        if not ccw:
            a0, a1 = a1, a0
        sweep = (a1 - a0) % (2 * math.pi)
        n = max(4, int(math.ceil(sweep / ARC_STEP)) + 1)
        pts = [(c[0] + r * math.cos(a0 + sweep * i / (n - 1)), c[1] + r * math.sin(a0 + sweep * i / (n - 1))) for i in range(n)]
        return {"t": "arc", "c": c, "r": r, "a0": a0, "a1": a0 + sweep, "pts": pts}
    pts = _poly(edge, SAMPLES)
    arr = np.array(pts)
    span = arr.max(axis=0) - arr.min(axis=0)
    if min(span) < 1e-6 * max(1.0, max(span)):                                   # a circle seen edge-on, a flattened curve: a straight line
        i, j = int(np.argmin(arr[:, 0] + arr[:, 1] * 1e-9)), int(np.argmax(arr[:, 0] + arr[:, 1] * 1e-9))
        if span[0] < span[1]:
            i, j = int(np.argmin(arr[:, 1])), int(np.argmax(arr[:, 1]))
        a, b = pts[i], pts[j]
        return {"t": "line", "a": a, "b": b, "pts": [a, b]}
    return {"t": "poly", "pts": pts}


def _on_visible(e, vis_segs, tol):
    """True when the whole entity lies on the visible lines (every sampled point is within tol of a visible segment)."""
    pts = e["pts"]
    if len(pts) == 2:
        pts = [pts[0], ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2), pts[1]]
    idx = np.unique(np.linspace(0, len(pts) - 1, 7).astype(int))
    p = np.array([pts[i] for i in idx])
    a, b = vis_segs[:, 0, :], vis_segs[:, 1, :]
    ab = b - a
    ab2 = np.maximum((ab * ab).sum(axis=1), 1e-18)
    for q in p:
        t = np.clip(((q - a) * ab).sum(axis=1) / ab2, 0.0, 1.0)
        d = np.linalg.norm(a + ab * t[:, None] - q, axis=1)
        if d.min() > tol:
            return False
    return True


def segments(entities):
    out = []
    for e in entities:
        p = e["pts"]
        out += [(p[i], p[i + 1]) for i in range(len(p) - 1)]
    return np.array(out, float) if out else np.zeros((0, 2, 2))


def frame_of(eye, up):
    """(eye, up, right) as unit vectors, up made square to the eye."""
    eye = np.array(eye, float)
    eye = eye / np.linalg.norm(eye)
    up = np.array(up, float)
    up = up - eye * float(np.dot(up, eye))
    up = up / np.linalg.norm(up)
    right = np.cross(-eye, up)
    return eye, up, right / np.linalg.norm(right)


def project(shape, name, hidden=True, mesh=False):
    """The lines of `shape` seen as the standard view `name`.  hidden=False leaves the hidden lines out; mesh=True adds the triangles for the shaded styles."""
    eye, up, _right = view_axes(name)
    return project_axes(shape, eye, up, name, hidden, mesh)


def project_axes(shape, eye, up, name="", hidden=True, mesh=False):
    """The lines of `shape` seen from the direction `eye` (from the model toward the viewer) with `up` toward the top of the view (any pair of directions: the views that are
    projected from another view are made like this).  mesh=True: the triangles of the shape in the view's frame as well (dr_shade), for the shaded styles."""
    eye, up, right = frame_of(eye, up)
    bb = shape.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z])) or 1.0
    origin = tuple(float(x) for x in eye * (diag * 10.0 + 100.0))
    vis_e, hid_e = shape.project_to_viewport(origin, viewport_up=tuple(float(x) for x in up), look_at=(0, 0, 0))
    vis = [_entity_of(e) for e in vis_e if e.length > 1e-9]
    hid = [_entity_of(e) for e in hid_e if e.length > 1e-9] if hidden else []
    segs = segments(vis)
    if len(segs) and hid:
        tol = max(1e-4, diag * 1e-5)
        hid = [e for e in hid if not _on_visible(e, segs, tol)]
    for i, e in enumerate(vis + hid):
        e["n"] = i
    shaded = None
    if mesh:
        import dr_shade
        shaded = dr_shade.mesh_of(shape, right, up, eye)
    return Projection(name, vis, hid, shaded)
