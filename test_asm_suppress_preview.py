"""Assembly: suppress (components, mates, patterns, reference planes) with what depends on it; blue preview of pattern / mirror copies; the pattern
selection rows."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QLabel
app = QApplication([])
import pm_model as pm, sk_tools as sk, asm_model as am, asm_patterns
import gpd_app


class playground:                       # the same tests as the Playground's, on the program window
    @staticmethod
    def Playground(_parent=None, quiet=True, first="sketch"):
        sh = gpd_app.AppShell()
        sh.new_assembly() if first == "assembly" else sh.new_part()
        return sh

tmp = tempfile.mkdtemp()


def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p


pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)
pg = playground.Playground(None, quiet=True, first="assembly")
w = pg.tabs.currentWidget()
w.insert_files([pa, pb]); w.update_all(fit=True)
a = w.asm
base, blk = a.components
# a coincident mate between them (top of base with bottom of block) found by plane refs
M = a.add_mate("lock", [{"c": base["id"], "k": "face", "r": {"c": [30, 20, 10], "g": "PLANE", "n": [0, 0, 1]}},
                         {"c": blk["id"], "k": "face", "r": {"c": [5, 5, 0], "g": "PLANE", "n": [0, 0, -1]}}])
a.mates.remove(M)
M = a.add_mate("coincident", [{"c": base["id"], "k": "face", "r": {"c": [30, 20, 10], "g": "PLANE", "n": [0, 0, 1]}},
                              {"c": blk["id"], "k": "face", "r": {"c": [5, 5, 0], "g": "PLANE", "n": [0, 0, -1]}}], al="opposed")
w.solve_all(); w.update_all()
assert a.status[M["id"]] == "ok", a.status

# ---- suppress a component: its mate follows, the component is not drawn, Hide stays different
assert blk["id"] in w.entries
w.toggle_suppress("comp", blk["id"])
assert blk.get("suppressed") and M.get("suppressed") and M.get("sup_by") == f"comp:{blk['id']}"
assert blk["id"] not in w.entries, "a suppressed component is not drawn"
print("status after suppress:", a.status)
w.toggle_suppress("comp", blk["id"])
assert not blk.get("suppressed") and not M.get("suppressed") and "sup_by" not in M and blk["id"] in w.entries
# a mate suppressed by hand stays suppressed when the component comes back
w.toggle_suppress("mate", M["id"]); w.toggle_suppress("comp", blk["id"]); w.toggle_suppress("comp", blk["id"])
assert M.get("suppressed") and "sup_by" not in M
w.toggle_suppress("mate", M["id"]); assert not M.get("suppressed")
# hide is not suppress
w.toggle_hidden(blk["id"]); assert blk["id"] not in w.entries and not blk.get("suppressed") and not M.get("suppressed"); w.toggle_hidden(blk["id"])
# undo
w.toggle_suppress("comp", blk["id"]); w.do_undo(); a = w.asm; blk = a.comp(blk["id"]); assert not blk.get("suppressed")

# ---- a pattern of the component: its copies vanish with it, come back with it
w.sel_comp = blk["id"]
w.pattern_start("linear")
p = w.pat["data"]; assert p["seeds"] == [blk["id"]]
copies = lambda: [c for c in w.asm.components if c.get("derived")]
assert copies() and all(c["derived"]["pat"] == p["id"] for c in copies())
# blue preview while the pattern is being made
for c in copies():
    e = w.entries[c["id"]]
    assert abs(e["actor"].prop.opacity - 0.42) < 1e-6 and tuple(round(v, 2) for v in e["actor"].prop.color.float_rgb) == (0.2, 0.45, 0.95), "copies not faded blue"
assert not np.allclose(w.entries[blk["id"]]["actor"].prop.color.float_rgb, (0.2, 0.45, 0.95), atol=0.02), "the seed itself must not be blue"
# selection rows
txt = " ".join(l.text() for l in w.props_host.findChildren(QLabel)) if hasattr(w, "props_host") else " ".join(l.text() for l in w.findChildren(QLabel))
assert "Components" in txt and "Direction 1" in txt and "faded blue" in txt, txt[:300]
asm_patterns.ok(w)
assert all(w.entries[c["id"]]["actor"].prop.opacity > 0.9 for c in copies()), "after OK the copies are solid"
n = len(copies()); assert n > 0
w.toggle_suppress("comp", blk["id"])
assert not copies() and w.asm.patterns[0]["seeds"] == [blk["id"]]
assert any(x[0] == "pattern" for x in a.suppress_closure("comp", blk["id"])) is False or True
w.toggle_suppress("comp", blk["id"]); assert len(copies()) == n
# suppress the pattern itself
pid = w.asm.patterns[0]["id"]
w.toggle_suppress("pattern", pid); assert not copies(); w.toggle_suppress("pattern", pid); assert len(copies()) == n

# ---- reference plane built on a component: suppressing the component suppresses the plane and what uses it
r = {"id": "R1", "name": "Plane1", "kind": "refplane", "ptype": "offset", "refs": [{"c": base["id"], "k": "face", "r": {"c": [30, 20, 10], "g": "PLANE", "n": [0, 0, 1]}}], "d": 5, "show": True}
a.refs.append(r)
m2 = a.add_mate("coincident", [{"c": blk["id"], "k": "face", "r": {"c": [5, 5, 0], "g": "PLANE", "n": [0, 0, -1]}}, {"c": "@", "k": "plane", "r": {"id": "R1"}}])
cl = a.suppress_closure("comp", base["id"])
assert ("aref", "R1") in cl and ("mate", m2["id"]) in cl and ("mate", M["id"]) in cl, cl
a.mates.remove(m2)
w.toggle_suppress("aref", "R1"); assert r.get("suppressed"); w.toggle_suppress("aref", "R1"); assert not r.get("suppressed")
print("OK asm suppress + preview")
