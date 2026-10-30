import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk, assembly, asm_model as am
w = pm_app.MainWindow(); d = w.doc
# --- a part: sketch (with a dimension using a global), extrude (depth formula), pattern, configuration columns
d.params.update({"W": "40", "Width": "99", "Depth": "W/2", "Gap": "W + 5"})
s = d.add(pm.new_feature("sketch", plane={"base": "Front"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (10, 10)); sk.solve_model(m)
ln = next(iter(m.lns)); m.add_con("dim_len", [("ln", ln)], value=10.0, expr="W*0.5"); sk.solve_model(m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="Depth+W")); d.rebuild()
d.cfg_add_col("g:W"); d.cfg_add_col("g:Depth"); d.cfg_add_col(f"f:{e['id']}:depth")
d.cfg["cells"]["Default"]["g:W"] = "40"; d.cfg["cells"]["Default"]["g:Depth"] = "W/2"; d.cfg["cells"]["Default"][f"f:{e['id']}:depth"] = "W+3"
# rename W -> Wide : whole word only (Width is untouched)
d.rename_global("W", "Wide")
assert "W" not in d.params and d.params["Wide"] == "40" and d.params["Width"] == "99", d.params
assert d.params["Depth"] == "Wide/2" and d.params["Gap"] == "Wide + 5"
assert e["depth"] == "Depth+Wide", e["depth"]
assert "g:Wide" in d.cfg["cols"] and "g:W" not in d.cfg["cols"]
row = d.cfg["cells"]["Default"]; assert row["g:Wide"] == "40" and row["g:Depth"] == "Wide/2" and row[f"f:{e['id']}:depth"] == "Wide+3", row
m2 = d.sketch_model_raw(d.feature(s["id"])); assert any(c.get("expr") == "Wide*0.5" for c in m2.cons), [c.get("expr") for c in m2.cons]
d.rebuild(); assert d.status[e["id"]] == "ok", d.status; assert abs(d.values["Wide"] - 40) < 1e-9 and d.solid is not None
assert d.cfg_label("g:Wide") == "Wide"
# refused renames
for bad in ("Width", "1x", "sin", "", "has space"):
    try: d.rename_global("Wide", bad); raise SystemExit(f"accepted {bad!r}")
    except pm.ModelError: pass
assert "Wide" in d.params
# feature rename: unique, config header follows
d.rename_feature(e["id"], "Base Boss"); assert e["name"] == "Base Boss"
assert "Base Boss" in d.cfg_label(f"f:{e['id']}:depth"), d.cfg_label(f"f:{e['id']}:depth")
for bad in ("", "Front", s["name"], s["name"].upper()):
    try: d.rename_feature(e["id"], bad); raise SystemExit(f"accepted {bad!r}")
    except pm.ModelError: pass
# through the window: Globals table edit renames, undo restores
w.doc = d; w.update_all()
t = w.gtab; r = [i for i in range(t.rowCount()) if t.item(i, 0).text() == "Wide"][0]
t.item(r, 0).setText("Span")
assert "Span" in d.params and "Wide" not in d.params and d.params["Depth"] == "Span/2", d.params
w.do_undo(); assert "Wide" in w.doc.params and w.doc.params["Depth"] == "Wide/2", w.doc.params
w.rename_feature(e["id"], "Boss A"); assert w.doc.feature(e["id"])["name"] == "Boss A"
# a named dimension: later formulas that used it follow
d = w.doc; sid = s["id"]; mm = d.sketch_model_raw(d.feature(sid)); dim = next(c for c in mm.cons if c["type"] == "dim_len")
d.rename_dimension(sid, dim["id"], "Len1"); e2 = d.feature(e["id"]); e2["depth"] = "Len1*2"
d.rename_dimension(sid, dim["id"], "Len2"); assert d.feature(e["id"])["depth"] == "Len2*2", d.feature(e["id"])["depth"]
# --- an assembly
aw = assembly.AssemblyWindow(); a = aw.asm
c1 = a.add_component("/x/a.gpd"); c2 = a.add_component("/x/b.gpd")
mt = a.add_mate("distance", [{"c": c1["id"], "k": "x"}, {"c": c2["id"], "k": "y"}], value=1.0)
a.patterns.append({"id": "P1", "type": "linear", "name": "Pat1", "seeds": [c1["id"]], "s1": 3.0, "n1": 2})
a.cfg_add_col(f"x:{c1['id']}"); a.cfg_add_col(f"v:{mt['id']}")
assert "a<1>" in a.cfg_label(f"x:{c1['id']}")
aw.rename_item("comp", c1["id"], "Base plate"); assert c1["name"] == "Base plate"
assert "Base plate" in a.cfg_label(f"x:{c1['id']}")
aw.rename_item("mate", mt["id"], "Gap mate"); assert a.cfg_label(f"v:{mt['id']}").endswith("Gap mate") and mt["name"] == "Gap mate"
aw.rename_item("pattern", "P1", "Ring"); assert a.patterns[0]["name"] == "Ring"
msgs = []; aw.say = lambda t, *x, **k: msgs.append(t)
aw.rename_item("comp", c2["id"], "base plate"); assert c2["name"] != "base plate" and any("already used" in m for m in msgs), msgs
aw.rename_item("comp", c2["id"], "  "); assert c2["name"] != "  "
b = am.Assembly.from_json(a.to_json()); assert b.comp(c1["id"])["name"] == "Base plate" and b.mate(mt["id"])["name"] == "Gap mate"
aw.update_all()
print("RENAME OK")
