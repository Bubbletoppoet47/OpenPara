"""Part window: Suppress also suppresses the features that cannot be built without it; Unsuppress brings back exactly those; saved and undoable."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk

w = pm_app.MainWindow(); d = w.doc
V0 = d.solid.volume


def sketch(plane, build):
    m = sk.new_model(); build(m)
    f = d.add(pm.new_feature("sketch", plane=plane, model=m.to_json())); d.rebuild(); return f


s1 = sketch({"base": "Top"}, lambda m: sk.add_rect_corner(m, (10, 5), (20, 15)))
boss = d.add(pm.new_feature("extrude", sketch=s1["id"], depth="30", end1="blind", merge=True)); d.rebuild()
s2 = sketch({"base": "Top"}, lambda m: sk.add_rect_corner(m, (-25, -15), (-20, -10)))
other = d.add(pm.new_feature("extrude", sketch=s2["id"], depth="30", end1="blind", merge=True)); d.rebuild()      # independent of the first boss
mir = d.add(pm.new_feature("mirror", features=[boss["id"]], source="features", plane={"base": "Right"})); d.rebuild()
names = lambda ids: [d.feature(i)["name"] for i in ids]
assert all(d.status[f["id"]] == "ok" for f in d.features), d.status
Vall = d.solid.volume

# the closure: the boss's sketch, the boss and the mirror of it follow; the independent boss does not
cl = d.suppress_closure(s1["id"]); assert set(cl) == {boss["id"], mir["id"]}, names(cl)
cl = d.suppress_closure(boss["id"]); assert cl == [mir["id"]], names(cl)
assert d.suppress_closure(mir["id"]) == [] and d.suppress_closure(other["id"]) == []
assert d.suppress_closure(s1["id"]) and not any(d.feature(i)["name"] == other["name"] for i in d.suppress_closure(s1["id"]))

# menu action: Suppress boss -> mirror is suppressed with it
w.toggle_suppress(boss["id"])
assert boss["suppressed"] and mir["suppressed"] and mir.get("sup_by") == boss["id"] and not other["suppressed"]
assert d.status[boss["id"]] == "suppressed" and d.status[mir["id"]] == "suppressed" and d.status[other["id"]] == "ok"
assert all(d.status[f["id"]] in ("ok", "suppressed") for f in d.features)                         # nothing fails: nothing is left in error
assert d.solid.volume < Vall
# the tree says so
w.refresh_tree()
tags = {w.tree.topLevelItem(0).child(i).text(0) for i in range(w.tree.topLevelItem(0).childCount())}
assert any(t.startswith(mir["name"]) and f"suppressed with {boss['name']}" in t for t in tags), tags
# reload keeps it
d2 = pm.Document.from_json(d.to_json()); d2.rebuild()
assert d2.feature(mir["id"])["suppressed"] and d2.feature(mir["id"])["sup_by"] == boss["id"]
# Unsuppress brings back exactly the follower
mir2 = d.feature(mir["id"]); w.toggle_suppress(boss["id"])
assert not boss["suppressed"] and not mir["suppressed"] and "sup_by" not in mir and abs(d.solid.volume - Vall) < 1e-6
# one the user suppressed himself stays suppressed
w.toggle_suppress(mir["id"]); assert mir["suppressed"] and "sup_by" not in mir
w.toggle_suppress(boss["id"]); w.toggle_suppress(boss["id"])
assert mir["suppressed"], "a feature suppressed by hand must stay suppressed when the one before it comes back"
w.toggle_suppress(mir["id"]); assert not mir["suppressed"]
# undo restores everything in one step
w.toggle_suppress(boss["id"]); w.do_undo(); d = w.doc
assert not d.feature(boss["id"])["suppressed"] and not d.feature(mir["id"])["suppressed"], "undo should bring both back"
# an already-broken feature is not blamed on the suppress
print("OK part suppress")
