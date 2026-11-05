"""
sim_source.py - the source of a simulation project, loaded from the project's own copy (source/<name>.gpd or .gpa), without any window.

The simulation tabs used to ask the open part / assembly tab for the sketches, the slice planes and the solids.  A project asks a Source,
which answers the same questions from the copy in its folder.  Because the copy is a normal part / assembly file, a parametric study can
change its parameters or configurations here (`set_values`) and rebuild.

  Part source:      .type == "part", .doc = the pm_model.Document (rebuilt)
  Assembly source:  .type == "asm",  .asm = the Assembly, and the Loader methods (part_doc, ...) of an assembly window
"""
import json
import os

import pm_model as pm


class SourceError(Exception):
    pass


class PartSource:
    type = "part"
    vis = {"planes": True, "refgeo": True}                 # every plane counts as shown in a headless source
    plane_show = {}

    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.doc = pm.Document.from_json(f.read())
            self.doc.rebuild()
        except Exception as ex:
            raise SourceError(f"The copy of the part in the project could not be read: {ex}")

    def title(self):
        return self.name

    def refresh_tree(self):
        pass

    def reload(self):
        self.load()

    # --- what a study can change
    def set_values(self, vals):
        """vals: {key: value} with the keys of Document.cfg_read ('g:<global>', 'd:<sketch id>:<constraint>', 's:<feature id>').  Rebuilds."""
        for k, v in vals.items():
            self.doc.cfg_write(k, v)
        self.doc.rebuild()

    def to_json(self):
        return self.doc.to_json()


def _loader(path):
    import assembly                                         # installs the Loader methods (abs, wire, part_doc, ...)
    import asm_model as am
    import asm_patterns
    import asm_sub
    L = asm_sub.Loader(path, None, ())
    with open(path, encoding="utf-8") as f:
        L.asm = am.Assembly.from_json(f.read())
    L.wire(L.asm)
    try:
        asm_patterns.rebuild_derived(L)
        L.asm.solve()
        asm_patterns.rebuild_derived(L)
    except am.MateError:
        pass
    return L


class AsmSource:
    type = "asm"
    vis = {"planes": True, "refgeo": True}

    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.load()

    def load(self):
        try:
            L = _loader(self.path)
        except Exception as ex:
            raise SourceError(f"The copy of the assembly in the project could not be read: {ex}")
        self.__dict__["_L"] = L
        self.asm = L.asm

    def __getattr__(self, name):                            # part_doc, solid_of, abs, wire ... come from the loader
        L = self.__dict__.get("_L")
        if L is None or name.startswith("__"):
            raise AttributeError(name)
        return getattr(L, name)

    def title(self):
        return self.name

    def refresh_tree(self):
        pass

    def reload(self):
        self.load()


def open_source(path):
    """The Source for a copy of a .gpd / .gpa."""
    if not os.path.isfile(path):
        raise SourceError(f"The copy of the source is missing from the project ({os.path.basename(path)}). Import the source again.")
    return AsmSource(path) if path.lower().endswith(".gpa") else PartSource(path)
