"""Degrees of freedom do not depend on the size of the sketch: an angle on a 7.6 m roof counts as much as a length (the user's roof sketch:
fully defined; the pitch angle used to be reported redundant and the pillar tops free)."""
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, copy
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import asm_sketch as ak, sk_tools as sk
here = os.path.dirname(os.path.abspath(__file__))
doc, asm, parts = ak.load(os.path.join(here, "test_data", "big_pitch_sketch.gpk")); doc.rebuild()
f = ak.sketch_feature(doc); m = doc.models[f["id"]]; rep = doc.reports[f["id"]]
pitch = next(c for c in m.cons if c.get("name") == "Pitch_Angle")
print("dof", rep.dof, "free", len(rep.free_pts), "redundant", rep.redundant)
assert rep.dof == 0 and not rep.free_pts and not rep.conflicts
assert pitch["id"] not in rep.redundant
# without the pitch the roof can tilt: one more degree of freedom
mm = copy.deepcopy(m); mm.cons = [c for c in mm.cons if c["id"] != pitch["id"]]
r2 = sk.solve_model(mm); assert r2.dof == 1 and r2.free_pts, r2.dof
print("OK dof scale")
