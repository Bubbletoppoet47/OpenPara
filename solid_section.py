"""
solid_section.py - the cross-section of a solid cut by a plane: area, centroid and second moments of area (the "area moment of inertia").  No Qt.

    cut(solid, plane, face=None)        -> (faces, warnings)   the flat faces the plane cuts from the solid; `face` (a flat face of the solid) is used as it is
    properties(faces, plane)            -> dict                every number below, from the exact geometry (curved edges and holes included)
    report(name, label, p, lu, lf)      -> text                the report of the window; lu = length unit name, lf = length units per mm
    outline(faces) / fill(faces)        -> 3D polylines / triangles for drawing the cut in the view

`plane` is a build123d Plane: the same planes a sketch is drawn on (Front, Top, Right, a reference plane, a face).  Its x_dir / y_dir are the section's X and Y
axes, z_dir its normal.  Everything is in mm in the model's coordinates; section coordinates are measured from the model origin projected onto the plane.

properties() keys
    area, pieces, areas        total area, number of separate flat pieces, the area of each
    c3, c                      centroid in model coordinates; (x, y) in the section axes
    Ix, Iy, Ixy                about the centroid:  Ix = integral of y^2 dA (about the section X axis), Iy = integral of x^2 dA, Ixy = integral of x*y dA
    Ix_o, Iy_o, Ixy_o          the same about the origin axes (parallel-axis theorem)
    J, J_o                     polar moment, Ix + Iy (about the centroid / about the origin)
    I1, I2, theta, axis1, axis2   principal moments (I1 the larger), the angle of the axis of I1 from the section X axis in degrees (None when I1 = I2:
                               every axis is principal) and both axes as 3D unit vectors
    rx, ry                     radii of gyration, sqrt(Ix / A) and sqrt(Iy / A)
    ext                        distance from the centroid to the farthest point of the section on the +X, -X, +Y, -Y side
    S                          section modulus Ix / (distance to the +Y side) etc.
    frame                      {"o", "u", "v", "n"} numpy vectors and {"names": (X axis, Y axis, normal) as model axes}
"""
import numpy as np
from build123d import Compound, Face, Plane
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

EPS = 1e-9


class SectionError(Exception):
    """The cut cannot be measured; the text says why."""


def _v(x):
    return np.array([x.X, x.Y, x.Z], float)


def _gp(p):
    return np.array([p.X(), p.Y(), p.Z()], float)                          # an OCC point (its coordinates are methods)


def axis_name(vec):
    """A direction as a model axis (+X, -Z ...) when it is one, else its three components."""
    a = np.asarray(vec, float)
    i = int(np.argmax(np.abs(a)))
    if abs(a[i]) > 0.99999:
        return ("+" if a[i] > 0 else "-") + "XYZ"[i]
    return "(%.2f, %.2f, %.2f)" % tuple(a)


def frame_of(plane):
    """-> {"o", "u", "v", "n", "p0"}: the section axes of the plane, the section origin (the model origin projected onto the plane) and the
    plane's own origin point."""
    p0, n = _v(plane.origin), _v(plane.z_dir)
    u, v = _v(plane.x_dir), _v(plane.y_dir)
    o = n * float(n @ p0)
    return {"o": o, "u": u, "v": v, "n": n, "p0": p0, "names": (axis_name(u), axis_name(v), axis_name(n))}


def coplanar_faces(solid, plane, tol=1e-6):
    """How many flat faces of the solid lie exactly in the plane (a cut there is ambiguous: the result may be only a part of the section)."""
    p0, n = _v(plane.origin), _v(plane.z_dir)
    k = 0
    for f in solid.faces():
        if f.geom_type.name != "PLANE":
            continue
        fn = _v(f.normal_at())
        if abs(abs(float(fn @ n)) - 1.0) < 1e-7 and abs(float((_v(f.center()) - p0) @ n)) <= tol * max(1.0, abs(float(p0 @ n))):
            k += 1
    return k


def cut(solid, plane, face=None):
    """-> (faces, warnings).  A given `face` is the section as it is (for a picked face at distance 0); otherwise the plane is cut through the solid."""
    if face is not None:
        return [face], []
    if solid is None:
        raise SectionError("There is no solid to cut.")
    bb = solid.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    size = 2.0 * diag + 10.0
    n, p0 = _v(plane.z_dir), _v(plane.origin)
    cen = np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2])
    c = cen - n * float((cen - p0) @ n)                                   # the middle of the solid, moved onto the plane
    big = Face.make_rect(size, size, plane=Plane(origin=tuple(c), x_dir=tuple(_v(plane.x_dir)), z_dir=tuple(n)))
    try:
        res = solid.intersect(big)
        faces = [f for f in res.faces() if f.area > EPS] if res is not None else []
    except Exception as e:                                                  # (a boolean that fails on awkward geometry)
        raise SectionError(f"The cut could not be made here: {e}")
    warn = []
    if faces and coplanar_faces(solid, plane):
        warn.append("The cut lies exactly in a face of the part, so the result may be only a part of the section. Move it a little, or pick the face itself.")
    return faces, warn


def _gprops(faces):
    g = GProp_GProps()
    for f in faces:
        gf = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f.wrapped, gf, 1e-8, False)
        g.Add(gf)
    return g


def properties(faces, plane):
    if not faces:
        raise SectionError("The plane does not cut the part here.")
    fr = frame_of(plane)
    g = _gprops(faces)
    A = float(g.Mass())
    if A <= EPS:
        raise SectionError("The plane does not cut the part here.")
    c3 = _gp(g.CentreOfMass())
    M = g.MatrixOfInertia()
    J3 = np.array([[M.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])              # unit surface density, about the centroid, model axes
    S3 = 0.5 * np.trace(J3) * np.eye(3) - J3                                              # integral of r r^T dA
    u, v, o = fr["u"], fr["v"], fr["o"]
    Iy = float(u @ S3 @ u)                                                                # integral of x^2 dA
    Ix = float(v @ S3 @ v)                                                                # integral of y^2 dA
    Ixy = float(u @ S3 @ v)                                                               # integral of x*y dA
    xc, yc = float(u @ (c3 - o)), float(v @ (c3 - o))
    T = np.array([[Ix, -Ixy], [-Ixy, Iy]])                                                # moment about an axis a = a^T T a
    w, vec = np.linalg.eigh(T)
    I1, I2 = float(w[1]), float(w[0])
    a1, a2 = vec[:, 1], vec[:, 0]
    theta = None
    if I1 - I2 > 1e-9 * max(I1, 1e-300):
        theta = float(np.degrees(np.arctan2(a1[1], a1[0])))
        theta = (theta + 90.0) % 180.0 - 90.0                                             # (-90, 90]
        theta = 90.0 if abs(theta + 90.0) < 1e-9 else theta
    pl = plane.to_local_coords(Compound(list(faces)))
    bb = pl.bounding_box()
    p0 = fr["p0"]
    xc0, yc0 = float(u @ (c3 - p0)), float(v @ (c3 - p0))
    ext = {"+X": float(bb.max.X - xc0), "-X": float(xc0 - bb.min.X), "+Y": float(bb.max.Y - yc0), "-Y": float(yc0 - bb.min.Y)}
    ext = {k: max(x, 0.0) for k, x in ext.items()}
    I_of = {"+X": Iy, "-X": Iy, "+Y": Ix, "-Y": Ix}                                       # bending about the Y axis stretches the X fibres
    S = {k: (I_of[k] / d if d > 1e-12 else None) for k, d in ext.items()}
    return {"area": A, "pieces": len(faces), "areas": [float(f.area) for f in faces], "c3": c3, "c": (xc, yc),
            "Ix": Ix, "Iy": Iy, "Ixy": Ixy, "Ix_o": Ix + A * yc * yc, "Iy_o": Iy + A * xc * xc, "Ixy_o": Ixy + A * xc * yc,
            "J": Ix + Iy, "J_o": Ix + Iy + A * (xc * xc + yc * yc),
            "I1": I1, "I2": I2, "theta": theta, "axis1": a1[0] * u + a1[1] * v, "axis2": a2[0] * u + a2[1] * v,
            "rx": float(np.sqrt(max(Ix, 0.0) / A)), "ry": float(np.sqrt(max(Iy, 0.0) / A)), "ext": ext, "S": S, "frame": fr}


# ------------------------------------------------------------------------------------------------------------------ drawing
def outline(faces, per_curve=48):
    """The edges of the section as 3D polylines [(N, 3) array]."""
    out = []
    for f in faces:
        for e in f.edges():
            try:
                n = 2 if e.geom_type.name == "LINE" else per_curve
                pts = [e.position_at(t) for t in np.linspace(0.0, 1.0, n)]
                out.append(np.array([[p.X, p.Y, p.Z] for p in pts]))
            except Exception:
                continue
    return out


def fill(faces, tol=0.05):
    """The section as triangles: (vertices (M, 3), triangles (K, 3))."""
    verts, tris, off = [], [], 0
    for f in faces:
        try:
            vs, ts = f.tessellate(tol)
        except Exception:
            continue
        if not vs or not ts:
            continue
        verts += [[p.X, p.Y, p.Z] for p in vs]
        tris += [[a + off, b + off, c + off] for a, b, c in ts]
        off += len(vs)
    return np.array(verts, float).reshape(-1, 3), np.array(tris, int).reshape(-1, 3)


# ------------------------------------------------------------------------------------------------------------------ the report
def _g(x, scale=1.0):
    if abs(x) <= 1e-9 * max(abs(scale), 1e-300):
        x = 0.0
    return f"{x:.8g}"


def report(name, label, p, lu, lf, warnings=()):
    """The text of the window.  lu = the length unit's name, lf = length units per mm (File > Units)."""
    L2, L3, L4 = lf ** 2, lf ** 3, lf ** 4
    fr = p["frame"]
    xn, yn, nn = fr["names"]
    A, (xc, yc) = p["area"], p["c"]
    I_scale = max(abs(p["Ix"]), abs(p["Iy"]), 1e-300)
    iscale = I_scale * L4
    g4 = lambda x: _g(x * L4, iscale)
    o = [f"Section properties of {name}", f"    Cut: {label}",
         f"    Section axes: X = model {xn}, Y = model {yn}   (the cut's normal is model {nn})"]
    if p["pieces"] > 1:
        o.append(f"    The cut has {p['pieces']} separate pieces ({' + '.join(_g(a * L2) for a in p['areas'])} square {lu}); they are measured together as one section.")
    for w in warnings:
        o.append(f"    Note: {w}")
    o += ["", f"Area = {_g(A * L2)} square {lu}", "",
          f"Centroid, in the section axes ( {lu} ), from the model origin on the cut plane:",
          f"     x = {_g(xc * lf, A ** 0.5 * lf)}      y = {_g(yc * lf, A ** 0.5 * lf)}",
          f"Centroid, in model coordinates ( {lu} ):",
          "     " + "      ".join(f"{a} = {_g(x * lf, A ** 0.5 * lf)}" for a, x in zip("XYZ", p["c3"])), "",
          f"Second moments of area, about the centroid ( {lu}^4 ):",
          f"     Ix  = {g4(p['Ix'])}      (about the section X axis: integral of y^2 dA)",
          f"     Iy  = {g4(p['Iy'])}      (about the section Y axis: integral of x^2 dA)",
          f"     Ixy = {g4(p['Ixy'])}      (integral of x*y dA; 0 for a section symmetric about X or Y)",
          f"     J   = Ix + Iy = {g4(p['J'])}      (polar)", ""]
    o += [f"Principal moments, about the centroid ( {lu}^4 ):",
          f"     I1 = {g4(p['I1'])}      I2 = {g4(p['I2'])}"]
    if p["theta"] is None:
        o.append("     Ix = Iy and Ixy = 0: every axis through the centroid is a principal axis.")
    else:
        a1, a2 = p["axis1"], p["axis2"]
        o += [f"     The I1 axis is {_g(p['theta'])} degrees from the section X axis (counter-clockwise).",
              f"     I1 axis = ( {a1[0]:.5f}, {a1[1]:.5f}, {a1[2]:.5f} )   (a direction in model coordinates)",
              f"     I2 axis = ( {a2[0]:.5f}, {a2[1]:.5f}, {a2[2]:.5f} )"]
    o += ["", f"Second moments of area, about the axes through the origin ( {lu}^4 ):",
          "     (the model origin on the cut plane; the axes are parallel to the section's X and Y)",
          f"     Ix  = {g4(p['Ix_o'])}      Iy  = {g4(p['Iy_o'])}      Ixy = {g4(p['Ixy_o'])}      J = {g4(p['J_o'])}", "",
          f"Radius of gyration ( {lu} ):      rx = {_g(p['rx'] * lf, A ** 0.5 * lf)}      ry = {_g(p['ry'] * lf, A ** 0.5 * lf)}", "",
          f"Extreme fibres, from the centroid ( {lu} ), and section moduli ( {lu}^3 ):"]
    for k in ("+Y", "-Y", "+X", "-X"):
        d, s = p["ext"][k], p["S"][k]
        side = {"+Y": f"+Y side (up, model {yn})", "-Y": "-Y side (down)", "+X": f"+X side (right, model {xn})", "-X": "-X side (left)"}[k]
        o.append(f"     {side:<28} distance = {_g(d * lf, A ** 0.5 * lf):<12} S = " + (_g(s * L3, s * L3) if s is not None else "-"))
    return "\n".join(o)
