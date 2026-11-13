"""
profile_sketch.py - a member profile drawn as a sketch (no Qt).

The 1D FEA tab can take the cross-section of a member from a sketch: the sketch is the section at its true size, looked at along the member.
Up in the sketch (+y) is the direction the member bends in (the plane of the frame); Flip and Turn 90 degrees in the profile window change that.

    outline_of(model, unit)   the material of a sketch as polygons: (outline, notes).  Raises ValueError with a message for the user.
    read(doc, sid, unit)      the same for a sketch of a part, refused when the sketch could not be solved
    check_values(doc, vals)   refuses the values a parametric study gives to a part when they cannot mean anything
    sketches_of(doc)          [(sketch id, name)] of a part
    model_of(doc, sid)        the solved sketch of a part

What is material: every closed loop of lines, arcs, circles and splines bounds a region; a loop inside another is a hole, a loop inside a hole
is material again (the rule the 2D FEA tab uses, physics_geom.analyze).  Construction geometry and lines that close nothing are ignored.

An outline is plain lists, so it can be saved in the tab's state and in a study case:
    [[polygon, is_hole], ...]     polygon = [[x, y], ...]
"""
import math

import physics_geom as pg
import units


def outline_of(m, unit=None):
    """(outline, notes) of the sketch model m, with the lengths in `unit` (a unit system name; None = the sketch's own)."""
    try:
        geom = pg.analyze(m)
    except pg.GeometryError as ex:
        raise ValueError(str(ex))
    if geom["crossings"]:
        raise ValueError(f"{len(geom['crossings'])} pair(s) of lines cross without a shared point, so the outline is not clear. "
                         "Split the lines where they cross (or trim them).")
    faces = [f for f in geom["faces"] if f["included"]]
    if not faces:
        why = "The sketch has no closed outline: a profile must be drawn as a closed shape at its true thickness."
        gaps = geom.get("gaps") or []
        if gaps:
            why += " " + pg.gap_note(gaps)
        raise ValueError(why)
    lf = 1.0
    if unit and getattr(m, "unit_system", None) and units.valid(m.unit_system) and units.valid(unit):
        lf = units.length_factor(m.unit_system, unit)
    out = []
    for f in faces:
        out.append([[[float(x) * lf, float(y) * lf] for x, y in f["poly"]], False])
        for h in f["holes"]:
            out.append([[[float(x) * lf, float(y) * lf] for x, y in h["poly"]], True])
    notes = []
    if geom["pruned"]:
        notes.append(f"{len(geom['pruned'])} line(s) that close no outline were ignored")
    if len(faces) > 1:
        notes.append(f"{len(faces)} separate regions, taken together as one section")
    return out, notes


def sketches_of(doc):
    return [(f["id"], f["name"]) for f in doc.features if f["kind"] == "sketch"]


def model_of(doc, sid):
    f = doc.feature(sid)
    m = doc.models.get(sid) if f is not None else None
    if f is None or f["kind"] != "sketch" or m is None:
        raise ValueError("That sketch is not in the part any more.")
    return m


def read(doc, sid, unit=None):
    """(outline, notes, sketch name) of sketch `sid` of a part.  Raises ValueError."""
    m = model_of(doc, sid)
    rep = getattr(doc, "reports", {}).get(sid)
    if rep is not None and (getattr(rep, "conflicts", None) or not getattr(rep, "ok", True)):
        raise ValueError("The sketch cannot be solved with these dimensions (they contradict each other).")
    outline, notes = outline_of(m, unit)
    return outline, notes, doc.feature(sid)["name"]


def check_values(doc, vals, sids=()):
    """The values a parametric study is about to write into a part (the keys of Document.cfg_write): every one must be a number or an
    expression of the part's variables, and a length of one of the profile sketches `sids` must be more than 0.  The part itself takes
    anything (a text it cannot work out leaves the dimension as it was), which would run the case on the wrong section without a word.
    Raises ValueError with the reason."""
    sids = {str(x) for x in sids}
    for key, v in vals.items():
        kind, _, rest = key.partition(":")
        if kind not in ("g", "d"):
            continue
        try:
            what = doc.cfg_label(key)
        except Exception:
            what = key
        try:
            x = float(doc.num(str(v)))
        except Exception:
            raise ValueError(f"'{v}' is not a number (or an expression of the part's variables) for {what}.")
        if not math.isfinite(x):
            raise ValueError(f"'{v}' is not a finite number for {what}.")
        if kind == "d":
            fid, _, cid = rest.partition(":")
            f = doc.feature(fid)
            if fid not in sids or f is None or f["kind"] != "sketch":
                continue
            m = doc.sketch_model_raw(f)
            c = m.con_by_id(int(cid)) if cid.isdigit() else m.con_by_id(cid)
            if c and c["type"] != "dim_ang" and x <= 0:
                raise ValueError(f"{what} must be more than 0 (it is {v}).")
