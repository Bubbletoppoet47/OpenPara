"""Section properties of a sketched cross-section, and the profile-properties file (.profprops).

The sketch is a cross-section drawn at its true size (sheet thickness included).  The areas are taken from the closed regions
the user ticks (holes are subtracted).  Everything is in the sketch's own length unit; the values "per unit width" divide by the
width of the profile (one rib pitch, say).

The file is plain text, "key = value" lines.  The FEA tab reads it to idealise a ribbed panel as a thin strip:
  strip thickness h = sqrt(12 I / A)           (A, I per unit width)
  stiffness ratio rho = A / h                   (E_eff = rho E, so the strip has the same EA and EI)
  stress factor  k = 2 c / (rho h)              (real extreme-fibre stress = k x strip stress; c = the farther extreme fibre)
"""
import math

FORMAT = 1
EXT = ".profprops"


def _poly_sums(poly):
    """Signed sums over one polygon: area, first and second moments about the origin."""
    A = Sx = Sy = Ixx = Iyy = Ixy = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A += cr
        Sx += (x0 + x1) * cr
        Sy += (y0 + y1) * cr
        Ixx += (y0 * y0 + y0 * y1 + y1 * y1) * cr
        Iyy += (x0 * x0 + x0 * x1 + x1 * x1) * cr
        Ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cr
    return A / 2.0, Sx / 6.0, Sy / 6.0, Ixx / 12.0, Iyy / 12.0, Ixy / 24.0


def properties(faces):
    """faces: the face dicts of physics_geom.analyze ("poly" counter-clockwise, "holes" each with a clockwise "poly").
    -> dict of area, centroid, Ixx / Iyy / Ixy about the centroid, the extreme-fibre distances and section moduli, bbox width."""
    ymin, ymax, xmin, xmax = math.inf, -math.inf, math.inf, -math.inf
    # clear implementation: outer polygons count positive, hole polygons negative, whatever their stored orientation
    A = Mx = My = Ixx0 = Iyy0 = Ixy0 = 0.0
    for f in faces:
        for k, poly in enumerate([f["poly"]] + [h["poly"] for h in f.get("holes", [])]):
            a, sx, sy, ixx, iyy, ixy = _poly_sums(poly)
            want = 1.0 if k == 0 else -1.0
            sg = want * (1.0 if a >= 0 else -1.0)      # flip a polygon that is stored the other way round
            A += sg * a
            Mx += sg * sx
            My += sg * sy
            Ixx0 += sg * ixx
            Iyy0 += sg * iyy
            Ixy0 += sg * ixy
        for x, y in f["poly"]:
            ymin, ymax, xmin, xmax = min(ymin, y), max(ymax, y), min(xmin, x), max(xmax, x)
    if A <= 0:
        raise ValueError("The selected regions have no area.")
    xc, yc = Mx / A, My / A
    Ixx = Ixx0 - A * yc * yc
    Iyy = Iyy0 - A * xc * xc
    Ixy = Ixy0 - A * xc * yc
    c_top, c_bot = ymax - yc, yc - ymin
    return {"area": A, "xc": xc, "yc": yc, "Ixx": Ixx, "Iyy": Iyy, "Ixy": Ixy, "c_top": c_top, "c_bottom": c_bot,
            "S_top": Ixx / c_top if c_top > 0 else math.inf, "S_bottom": Ixx / c_bot if c_bot > 0 else math.inf,
            "width_bbox": xmax - xmin, "height": ymax - ymin, "ymin": ymin, "ymax": ymax}


def per_width(props, width):
    if not width > 0:
        raise ValueError("The width must be positive.")
    return {"A_w": props["area"] / width, "I_w": props["Ixx"] / width, "S_top_w": props["S_top"] / width,
            "S_bottom_w": props["S_bottom"] / width}


def strip(A_w, I_w, c_top, c_bottom):
    """-> dict h, rho, c (the farther fibre), k.  Raises ValueError for a section that cannot be idealised."""
    if not (A_w > 0 and I_w > 0):
        raise ValueError("The profile needs a positive area and moment of inertia per width.")
    h = math.sqrt(12.0 * I_w / A_w)
    rho = A_w / h
    c = max(c_top, c_bottom)
    return {"h": h, "rho": rho, "c": c, "k": 2.0 * c / (rho * h)}


def write(path, name, units_name, length_unit, props, width):
    pw = per_width(props, width)
    st = strip(pw["A_w"], pw["I_w"], props["c_top"], props["c_bottom"])
    lines = [
        "Sketcher profile properties",
        f"format = {FORMAT}",
        f"name = {name}",
        f"units = {units_name}",
        f"length_unit = {length_unit}",
        "# values of the selected cross-section, about its centroid (horizontal axis = x)",
        f"width = {width:.12g}",
        f"area = {props['area']:.12g}",
        f"centroid_y = {props['yc']:.12g}",
        f"Ixx = {props['Ixx']:.12g}",
        f"c_top = {props['c_top']:.12g}",
        f"c_bottom = {props['c_bottom']:.12g}",
        f"S_top = {props['S_top']:.12g}",
        f"S_bottom = {props['S_bottom']:.12g}",
        "# per unit width (the numbers the FEA tab uses)",
        f"area_per_width = {pw['A_w']:.12g}",
        f"I_per_width = {pw['I_w']:.12g}",
        f"S_top_per_width = {pw['S_top_w']:.12g}",
        f"S_bottom_per_width = {pw['S_bottom_w']:.12g}",
        "# bending up (+y): top fibre in tension, bottom in compression.  Bending down (-y): the other way round.",
        "# The FEA tab scales the stress with the fibre farther from the centroid (the smaller section modulus) in both directions.",
        f"strip_thickness = {st['h']:.12g}",
        f"stiffness_ratio = {st['rho']:.12g}",
        f"stress_factor = {st['k']:.12g}",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return "\n".join(lines)


def read(path):
    """-> dict with name, units, A_w, I_w, c_top, c_bottom (lengths in the file's unit system).  Raises ValueError."""
    d = {}
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    lines = [ln.strip() for ln in text.splitlines()]
    if not lines or not lines[0].lower().startswith("sketcher profile properties"):
        raise ValueError("This is not a Sketcher profile properties file.")
    for ln in lines[1:]:
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        d[k.strip()] = v.strip()
    try:
        out = {"name": d.get("name", ""), "units": d["units"], "A_w": float(d["area_per_width"]), "I_w": float(d["I_per_width"]),
               "c_top": float(d["c_top"]), "c_bottom": float(d["c_bottom"])}
    except (KeyError, ValueError):
        raise ValueError("The file is missing area_per_width, I_per_width, c_top, c_bottom or units, or they are not numbers.")
    if int(float(d.get("format", 1))) > FORMAT:
        raise ValueError("This file was written by a newer version of the program.")
    strip(out["A_w"], out["I_w"], out["c_top"], out["c_bottom"])
    for key, src in (("area", "area"), ("Ixx", "Ixx"), ("width", "width")):          # the totals of the section as drawn (the 1D FEA tab uses them)
        try:
            out[key] = float(d[src])
        except (KeyError, ValueError):
            pass
    return out
