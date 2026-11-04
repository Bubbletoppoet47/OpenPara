"""Files made with the old assembly-sketch link open as plain files: the numbers stay, the link and tree go."""
import json, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import legacy, pm_model as pm, asm_model as am
d = {"version": 1, "params": {"Len": "{AS_Config 1_I1} * 2"}, "kinds": {}, "features": [], "rollback": None, "counter": {},
     "gsv": {"src": "x.gpk", "configs": ["Config 1", "Big"], "vars": [], "vals": {"Config 1": {"I1": 10.0, "Pipe_Length": 3048.0}, "Big": {"I1": 20.0, "Pipe_Length": 4000.0}}},
     "cfg": {"active": "General · Config 1", "names": ["General · Config 1", "General · Big"], "cols": ["g:Pipe_Length"],
             "cells": {"General · Config 1": {"g:Pipe_Length": "{AS_@_Pipe_Length}"}, "General · Big": {"g:Pipe_Length": "{AS_@_Pipe_Length}"}},
             "tree": {"nid": 3, "groups": [{"id": "g1", "name": "General", "variants": []}],
                      "leaf": {"General · Config 1": {"g": "g1", "v": None, "aid": "a", "suffix": "Config 1"}, "General · Big": {"g": "g1", "v": None, "aid": "b", "suffix": "Big"}}}}}
doc = pm.Document.from_json(json.dumps(d))
assert doc.params["Len"] == "10 * 2", doc.params
assert doc.cfg["cells"]["General · Config 1"]["g:Pipe_Length"] == "3048", doc.cfg["cells"]
assert doc.cfg["cells"]["General · Big"]["g:Pipe_Length"] == "4000"
assert "tree" not in doc.cfg and not hasattr(doc, "gsv")
assert "gsv" not in json.loads(doc.to_json())
a = am.Assembly.from_json(json.dumps({"components": [], "params": {}, "gsv": d["gsv"], "cfg": {"active": "Default", "names": ["Default"], "cols": [], "cells": {"Default": {}}}}))
print("OK legacy")
