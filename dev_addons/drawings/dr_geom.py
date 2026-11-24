"""dr_geom.py - the shape of a model of a drawing: a build123d shape made from the copy of a part or an assembly that the drawing keeps.

    shape_of(kind, data)     kind "part": data = the JSON object of a .gpd file; "assembly": that of a .gpa file (every part inside it is its own copy).
                             -> the solid (a part) or the compound of the placed solids of its visible components (an assembly); GeometryError when there is nothing to show.
"""
import json
import os
import tempfile


class GeometryError(Exception):
    pass


def part_shape(data):
    import pm_model as pm
    try:
        d = pm.Document.from_json(json.dumps(data))
        d.rebuild()
    except Exception as ex:                                                  # noqa: BLE001
        raise GeometryError(f"The part could not be built: {ex}")
    if d.solid is None:
        raise GeometryError("The part has no solid yet: there is nothing to draw.")
    return d.solid


def assembly_shape(data):
    """The compound of the placed solids of the visible components (a sub-assembly gives its own bodies)."""
    import assembly                                                          # installs the Loader methods (abs, wire, part_doc ...)
    import asm_model as am
    import asm_patterns
    import asm_sub
    from build123d import Compound
    tmp = tempfile.mkdtemp(prefix="opara_dr_")
    path = os.path.join(tmp, "model.gpa")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data))
        L = asm_sub.Loader(path, None, ())
        L.asm = am.Assembly.from_json(json.dumps(data))
        L.wire(L.asm)
        try:
            asm_patterns.rebuild_derived(L)
            L.asm.solve()
            asm_patterns.rebuild_derived(L)
        except am.MateError:
            pass
        bodies = asm_sub.bodies_of(L, L.asm)
    except GeometryError:
        raise
    except Exception as ex:                                                  # noqa: BLE001
        raise GeometryError(f"The assembly could not be built: {ex}")
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:                                                    # noqa: BLE001
            pass
    solids = [s for _n, s, _m in bodies]
    if not solids:
        raise GeometryError("The assembly has no visible part with a solid: there is nothing to draw.")
    return solids[0] if len(solids) == 1 else Compound(solids)


def shape_of(kind, data):
    if kind == "part":
        return part_shape(data)
    if kind == "assembly":
        return assembly_shape(data)
    raise GeometryError(f"A drawing shows a part or an assembly, not a '{kind}'.")
