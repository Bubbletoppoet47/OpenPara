"""
render_scene.py - from a part / assembly file to a render scene (no Qt windows here; used by render_studio.py).

  load_bodies(path)            [(name, solid, material name)] of a part (.gpd) or an assembly (.gpa; only the parts that are visible in it)
  default_appearance(mat)      colour / roughness / metallic for a material name
  mesh_of(solid)               (vertices, normals, triangles): per face, so edges stay sharp and curved faces are smooth
  new_project(bodies, source)  the starting render project (cameras, sun, floor, ...)
  scene_for_render(proj, bodies, folder)   the scene dict that render_core.py reads (meshes written to folder as .npz), model turned so
                                           that the chosen "up" axis is Z
"""
import json
import math
import os

import numpy as np

# ---------------------------------------------------------------------------------------------- appearance
# (keyword in the material name) -> colour (0..1), roughness, metallic.  The first match wins.
LOOKS = [
    ("stainless", (0.72, 0.73, 0.75), 0.30, 1.0),
    ("aluminum", (0.80, 0.81, 0.82), 0.32, 1.0),
    ("titanium", (0.62, 0.62, 0.64), 0.35, 1.0),
    ("brass", (0.80, 0.65, 0.28), 0.28, 1.0),
    ("copper", (0.80, 0.45, 0.30), 0.28, 1.0),
    ("magnesium", (0.74, 0.75, 0.76), 0.40, 1.0),
    ("nickel", (0.62, 0.64, 0.66), 0.33, 1.0),
    ("cast iron", (0.36, 0.37, 0.39), 0.55, 0.9),
    ("steel", (0.60, 0.62, 0.65), 0.36, 1.0),
    ("abs", (0.85, 0.85, 0.82), 0.45, 0.0),
    ("nylon", (0.93, 0.92, 0.86), 0.50, 0.0),
    ("wood", (0.66, 0.48, 0.30), 0.70, 0.0),
    ("water", (0.55, 0.75, 0.95), 0.05, 0.0),
]
DEFAULT_LOOK = ((0.70, 0.72, 0.75), 0.45, 0.0)


def default_appearance(material_name):
    n = (material_name or "").lower()
    for key, col, rough, met in LOOKS:
        if key in n:
            return {"color": list(col), "roughness": rough, "metallic": met}
    col, rough, met = DEFAULT_LOOK
    return {"color": list(col), "roughness": rough, "metallic": met}


# ---------------------------------------------------------------------------------------------- bodies
def bodies_from_widget(w):
    """[(name, solid, material name)] of an open part or assembly tab (what is on screen, saved or not)."""
    if hasattr(w, "asm"):
        import asm_sub
        return [(n, sd, (m or {}).get("name", "")) for n, sd, m in asm_sub.bodies_of(w, w.asm)]
    doc = w.doc
    if getattr(doc, "solid", None) is None:
        return []
    nm = os.path.splitext(os.path.basename(w.path))[0] if getattr(w, "path", None) else "Part"
    return [(nm, doc.solid, (doc.material or {}).get("name", ""))]


def load_bodies(path):
    """[(name, solid, material name)] of the file.  Needs a QApplication (the assembly is opened without showing it)."""
    low = path.lower()
    if low.endswith(".gpa"):
        import assembly
        import asm_sub
        w = assembly.AssemblyWindow(path, shell=None)
        try:
            out = [(n, s, (m or {}).get("name", "")) for n, s, m in asm_sub.bodies_of(w, w.asm)]
        finally:
            w.deleteLater()
        return out
    import pm_model as pm
    with open(path, "r", encoding="utf-8") as fh:
        doc = pm.Document.from_json(fh.read())
    doc.rebuild()
    if doc.solid is None:
        return []
    return [(os.path.splitext(os.path.basename(path))[0], doc.solid, doc.material.get("name", ""))]


def mesh_of(solid, tol=None):
    """(v, n, f): vertices Nx3, unit normals Nx3, triangles Mx3.  Each face is meshed on its own so the edges between faces stay sharp;
    flat faces get their plane normal, curved faces smooth normals from their own triangles."""
    bb = solid.bounding_box()
    diag = math.sqrt(bb.size.X ** 2 + bb.size.Y ** 2 + bb.size.Z ** 2) or 1.0
    tol = tol or max(diag * 0.0006, 0.005)
    V, N, F = [], [], []
    base = 0
    for face in solid.faces():
        try:
            verts, tris = face.tessellate(tol, 0.15)
        except Exception:
            continue
        if not len(tris):
            continue
        v = np.array([[p.X, p.Y, p.Z] for p in verts], float)
        t = np.array(tris, int)
        fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])          # triangle normals (length = 2 x area)
        try:
            c = face.center()
            out = face.normal_at(c)
            out = np.array([out.X, out.Y, out.Z], float)
        except Exception:
            out = fn.sum(0)
        if face.geom_type.name == "PLANE":
            n = np.tile(out / (np.linalg.norm(out) or 1.0), (len(v), 1))
            flip = (fn @ out) < 0
        else:
            n = np.zeros_like(v)
            for k in range(3):
                np.add.at(n, t[:, k], fn)
            nl = np.linalg.norm(n, axis=1, keepdims=True)
            n = n / np.where(nl > 1e-12, nl, 1.0)
            # point the vertex normals out of the solid: compare with the surface normal at a sample vertex
            try:
                p0 = verts[len(verts) // 2]
                ref = face.normal_at(p0)
                ref = np.array([ref.X, ref.Y, ref.Z], float)
                if float(n[len(v) // 2] @ ref) < 0:
                    n = -n
            except Exception:
                pass
            flip = np.einsum("ij,ij->i", fn, n[t].sum(1)) < 0
        t = np.where(flip[:, None], t[:, ::-1], t)
        V.append(v)
        N.append(n)
        F.append(t + base)
        base += len(v)
    if not V:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.concatenate(V), np.concatenate(N), np.concatenate(F)


# ---------------------------------------------------------------------------------------------- the project
UP_AXES = {"+Z": 2, "-Z": 2, "+Y": 1, "-Y": 1, "+X": 0, "-X": 0}


def up_vector(name):
    v = np.zeros(3)
    v[UP_AXES[name]] = 1.0 if name[0] == "+" else -1.0
    return v


def rotation_to_z(name):
    """3x3 rotation that turns the chosen up axis into +Z."""
    def rx(a):
        c, s = math.cos(a), math.sin(a)
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)

    def ry(a):
        c, s = math.cos(a), math.sin(a)
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)
    return {"+Z": np.eye(3), "-Z": rx(math.pi), "+Y": rx(math.pi / 2), "-Y": rx(-math.pi / 2), "+X": ry(-math.pi / 2), "-X": ry(math.pi / 2)}[name]


def bounds_of(meshes):
    lo, hi = np.full(3, 1e30), np.full(3, -1e30)
    for v, _n, _f in meshes:
        if len(v):
            lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    if not np.all(np.isfinite(lo)) or lo[0] > hi[0]:
        lo, hi = np.full(3, -50.0), np.full(3, 50.0)
    return lo, hi


def view_camera(lo, hi, direction, fov=35.0, name="Camera", up="+Z"):
    """A camera looking at the middle of the model from `direction` (given as if the up axis were Z: X right, -Y towards the viewer)."""
    R = rotation_to_z(up)
    direction = R.T @ np.array(direction, float)                 # into model coordinates
    cen = 0.5 * (lo + hi)
    diag = float(np.linalg.norm(hi - lo))
    d = np.array(direction, float)
    d /= np.linalg.norm(d)
    dist = 0.62 * diag / math.tan(math.radians(fov) / 2) + 0.2 * diag
    return {"name": name, "origin": [float(x) for x in cen + d * dist], "target": [float(x) for x in cen],
            "up": [float(x) for x in up_vector(up)], "fov": fov}


PRESET_VIEWS = {"Iso": (1.0, -1.2, 0.8), "Front": (0.0, -1.0, 0.0), "Back": (0.0, 1.0, 0.0), "Right": (1.0, 0.0, 0.0), "Left": (-1.0, 0.0, 0.0),
                "Top": (0.0, -0.001, 1.0)}


def new_project(bodies, meshes, source=""):
    lo, hi = bounds_of(meshes)
    diag = float(np.linalg.norm(hi - lo))
    cen = 0.5 * (lo + hi)
    iso = view_camera(lo, hi, PRESET_VIEWS["Iso"], name="Iso")
    return {
        "version": 1, "source": source, "up": "+Z",
        "appearance": {n: default_appearance(m) for n, _s, m in bodies},
        "cameras": [iso, view_camera(lo, hi, PRESET_VIEWS["Front"], name="Front")],
        "sun": {"on": True, "shadows": True, "date": "2026-06-21", "time": "16:00", "tz": -7.0, "lat": 33.45, "lon": -112.07, "north": 0.0,
                "turbidity": 3.0, "intensity": 1.0},
        "ambient": 0.0,
        "spot": {"on": False, "pos": [float(cen[0] + diag), float(cen[1] - diag), float(hi[2] + diag)], "target": [float(x) for x in cen],
                 "power": 50.0, "cone": 35.0, "color": [1.0, 1.0, 1.0]},
        "floor": {"on": True, "z": float(lo[2]), "color": [0.62, 0.62, 0.62], "roughness": 0.8},
        "render": {"width": 1280, "height": 720, "spp": 128, "exposure": 0.5, "max_depth": 8, "background": "sky", "bg_color": [1.0, 1.0, 1.0],
                   "denoise": False, "fireflies": True},
        "output": {"folder": "", "name": "render"},
        "anim": {"curved": True, "ease": False, "seconds": 10.0, "fps": 30},
    }


def save_project(proj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(proj, fh, indent=1)


def load_project(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------------------------- the scene for render_core
def scene_for_render(proj, bodies, meshes, folder, overrides=None):
    """Turns the model so that the chosen up axis is Z (the sun and the sky need Z up), writes the meshes, returns the scene dict."""
    os.makedirs(folder, exist_ok=True)
    R = rotation_to_z(proj.get("up", "+Z"))
    up = up_vector(proj.get("up", "+Z"))
    pt = lambda p: [float(x) for x in R @ np.array(p, float)]
    sc = {"bodies": [], "cameras": []}
    for i, ((name, _s, _m), (v, n, f)) in enumerate(zip(bodies, meshes)):
        if not len(v):
            continue
        p = os.path.join(folder, f"body{i}.npz")
        np.savez(p, v=(v @ R.T).astype(np.float32), n=(n @ R.T).astype(np.float32), f=f.astype(np.int32))
        ap = proj["appearance"].get(name) or default_appearance("")
        sc["bodies"].append({"name": name, "mesh": p, "color": ap["color"], "roughness": ap["roughness"], "metallic": ap["metallic"]})
    for c in proj["cameras"]:
        sc["cameras"].append({"name": c["name"], "origin": pt(c["origin"]), "target": pt(c["target"]), "up": pt(c.get("up", [0, 0, 1])), "fov": c["fov"]})
    sc["sun"] = dict(proj["sun"])
    sc["ambient"] = proj.get("ambient", 0.0)
    sp = dict(proj["spot"])
    sp["pos"], sp["target"] = pt(sp["pos"]), pt(sp["target"])
    sc["spot"] = sp
    fl = dict(proj["floor"])
    fl["z"] = float(fl["z"]) * (1.0 if proj.get("up", "+Z")[0] == "+" else -1.0) if proj.get("up", "+Z")[1] != "Z" or True else fl["z"]
    # the floor height is measured along the chosen up axis (in model coordinates): after the turn it is the new Z of that plane
    fl["z"] = float(np.dot(R @ (up * float(proj["floor"]["z"])), [0, 0, 1]))
    sc["floor"] = fl
    sc["render"] = dict(proj["render"])
    if overrides:
        sc["render"].update(overrides)
    return sc


# ---------------------------------------------------------------------------------------------- the camera path of a video
def _catmull(P, s):
    """Point at parameter s (0 .. len(P)-1) of the uniform Catmull-Rom curve through the points P (passes through every point; the ends are
    continued by mirroring so they have no kink).  P is K x D."""
    P = np.asarray(P, float)
    K = len(P)
    if K == 1:
        return P[0]
    i = int(min(max(math.floor(s), 0), K - 2))
    t = s - i
    p1, p2 = P[i], P[i + 1]
    p0 = P[i - 1] if i > 0 else 2 * P[0] - P[1]
    p3 = P[i + 2] if i + 2 < K else 2 * P[K - 1] - P[K - 2]
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def _linear(P, s):
    P = np.asarray(P, float)
    K = len(P)
    i = int(min(max(math.floor(s), 0), K - 2))
    t = s - i
    return P[i] * (1 - t) + P[i + 1] * t


def path_cameras(cams, n_frames, curved=True, ease=False, name="frame"):
    """The cameras of a video: `cams` = the checked cameras in their order (>= 2).  Position, the point looked at and the field of view
    move along a smooth curve through them (Curved; with 3 cameras it passes exactly through the middle one) or along straight pieces
    (Straight).  Constant speed along the path (Ease: starts and stops gently).  Returns n_frames camera dicts."""
    if len(cams) < 2:
        raise ValueError("Tick at least two cameras for the animation.")
    O = np.array([c["origin"] for c in cams], float)
    T = np.array([c["target"] for c in cams], float)
    F = np.array([[c["fov"]] for c in cams], float)
    up = np.array(cams[0].get("up", [0, 0, 1]), float)
    K = len(cams)
    f = _catmull if (curved and K > 2) else _linear
    dense = np.linspace(0, K - 1, 2000)
    po = np.array([f(O, s) for s in dense])
    pt = np.array([f(T, s) for s in dense])
    length = np.linalg.norm(np.diff(po, axis=0), axis=1) + 1e-3 * np.linalg.norm(np.diff(pt, axis=0), axis=1)
    if length.sum() < 1e-9:
        length = np.ones(len(dense) - 1)                      # a path that only changes the field of view: constant in parameter
    arc = np.concatenate([[0], np.cumsum(length)])
    arc /= arc[-1]
    out = []
    for i in range(n_frames):
        u = i / max(1, n_frames - 1)
        if ease:
            u = u * u * (3 - 2 * u)
        s = float(np.interp(u, arc, dense))
        out.append({"name": f"{name}_{i:05d}", "origin": [float(x) for x in f(O, s)], "target": [float(x) for x in f(T, s)],
                    "up": [float(x) for x in up], "fov": float(max(2.0, min(150.0, f(F, s)[0])))})
    return out


def path_polyline(cams, curved=True, n=120):
    """Points (n x 3) of the camera position path, for drawing it in the 3D view."""
    O = np.array([c["origin"] for c in cams], float)
    K = len(O)
    f = _catmull if (curved and K > 2) else _linear
    return np.array([f(O, s) for s in np.linspace(0, K - 1, n)])


# ---------------------------------------------------------------------------------------------- settings files (text)
SETTINGS_KIND = "gpd-render-settings"
CAMERAS_KIND = "gpd-render-cameras"
GENERAL_KEYS = ("sun", "ambient", "spot", "floor", "render", "anim")


def export_settings(proj):
    """The general settings as a dict (sun, sky, spot, floor, picture and quality, animation).  No bodies' looks and no cameras: those are
    different for every model (cameras have their own file)."""
    d = {k: copy_json(proj[k]) for k in GENERAL_KEYS if k in proj}
    d["kind"] = SETTINGS_KIND
    d["version"] = 1
    return d


def import_settings(proj, d):
    if d.get("kind") != SETTINGS_KIND:
        raise ValueError("this is not a Render Studio settings file")
    for k in GENERAL_KEYS:
        if k in d and isinstance(d[k], dict):
            proj[k] = {**proj.get(k, {}), **copy_json(d[k])}
        elif k in d:
            proj[k] = d[k]


def export_cameras(proj):
    return {"kind": CAMERAS_KIND, "version": 1, "cameras": copy_json(proj["cameras"])}


def import_cameras(d):
    if d.get("kind") != CAMERAS_KIND:
        raise ValueError("this is not a Render Studio cameras file")
    return copy_json(d["cameras"])


def copy_json(x):
    return json.loads(json.dumps(x))
