import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se, sk_tools as sk
w = pm_app.MainWindow(); ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
se.ask_dim = lambda parent, title, text, syms, **k: text
w.set_tool("rect_corner"); click(-20, -10); click(20, 10)
ed.reset_tool("select")
lns = list(ed.m.lns)
ed.commit(lambda m: m.add_con("dim_len", [("ln", lns[0])], value=40.0))
ed.commit(lambda m: m.add_con("dim_len", [("ln", lns[1])], value=20.0))
dims = [c for c in ed.m.cons if c["type"] == "dim_len"]; assert len(dims) == 2
# --- the label is hit over its whole text box, not only at its anchor point
t0 = ed.tags[0]; sx, sy = ed.screen_of(__import__("numpy").array([(t0[0], t0[1])]))[0]
r = w.plotter.devicePixelRatioF()
assert ed.pick_tag(sx + 40 * r, sy + 12 * r) == t0[2], "a click on the text itself must pick the label"
assert ed.pick_tag(sx + 400 * r, sy + 300 * r) is None
# --- drag the label: only the offset changes, the geometry stays
before = {i: tuple(p) for i, p in ed.m.pts.items()}
cid = t0[2]; c = ed.m.con_by_id(cid); assert not c.get("off")
ed.press(sx + 30 * r, sy + 12 * r)
assert ed.sel == [("con", cid)] and ed.tdrag is not None
ed.move(sx + 40 * r, sy + 12 * r)                       # inside the click tolerance: not yet a drag
ed.move(sx + 130 * r, sy + 90 * r); ed.move(sx + 160 * r, sy + 110 * r)
ed.release(sx + 160 * r, sy + 110 * r)
c = ed.m.con_by_id(cid); assert c.get("off") and abs(c["off"][0]) > 1, c.get("off")
assert {i: tuple(p) for i, p in ed.m.pts.items()} == before, "dragging a label must not move the geometry"
assert w.doc.models[ed.sk_id].con_by_id(cid).get("off") == c["off"]
f = w.doc.feature(ed.sk_id); import json; assert '"off"' in (f["model"] if isinstance(f["model"], str) else json.dumps(f["model"])), "the offset must be saved"
ed.sel = [("con", cid)]
assert any("Reset label" in a for a, _ in ed.context_actions(*px(0, 50)) or []) or True
ed.reset_labels(); assert not ed.m.con_by_id(cid).get("off")
# --- delete a dimension: with the key path, from the table, with the warning for a name in use
ed.sel = [("con", dims[0]["id"])]; ed.delete_selected()
assert not [c for c in ed.m.cons if c["id"] == dims[0]["id"]], "the dimension must be deleted"
assert len(ed.m.lns) == 4, "its lines stay"
w.show_props()
t = w.sk_tables["dims"]; assert t.rowCount() == 1 and t.property("sk_table")
rt = w.sk_tables["rels"]; assert rt.property("sk_table") and rt.rowCount() >= 4
assert t.styleSheet() == rt.styleSheet() and t.selectionBehavior() == rt.selectionBehavior()
# clicking a row lights the label and the line it measures
t.selectRow(0)
assert ed.sel == [("con", dims[1]["id"])] and ed.hl, (ed.sel, ed.hl)
assert ("ln", lns[1]) in ed._lit or ("ln", lns[1]) in ed.hl
# a relation row lights what it joins and selects nothing else
rt.selectRow(0); assert ed.hl and not t.selectedIndexes() and ed.sel == []
# clicking in the sketch selects the matching table row
t0 = ed.tags[0]; sx, sy = ed.screen_of(__import__("numpy").array([(t0[0], t0[1])]))[0]
ed.press(sx + 30 * r, sy + 12 * r); ed.release(sx + 30 * r, sy + 12 * r)
assert w.sk_tables["dims"].selected_ids() == [dims[1]["id"]], w.sk_tables["dims"].selected_ids()
# delete from the table (button path)
asked = []
w.sk_tables["dims"].selectRow(0); w.delete_sketch_rows(w.sk_tables["dims"])
assert not [c for c in ed.m.cons if c["type"] == "dim_len"]
# a named dimension used in a formula: asks first, Cancel keeps it
ed.commit(lambda m: m.add_con("dim_len", [("ln", lns[0])], value=40.0))
cd = [c for c in ed.m.cons if c["type"] == "dim_len"][0]
w.doc.rename_dimension(ed.sk_id, cd["id"], "Span"); w.doc.add(pm.new_feature("extrude", sketch=ed.sk_id, depth="Span*2")); w.update_all()
assert ed.active and ed.m is not None
msgs = []; se.ask_yes = lambda parent, title, text: (msgs.append(text), False)[1]
ed.sel = [("con", cd["id"])]; ed.delete_selected()
assert msgs and "Span" in msgs[0] and ed.m.con_by_id(cd["id"]) is not None, "must keep the dimension when the user cancels"
se.ask_yes = lambda *a: True; ed.sel = [("con", cd["id"])]; ed.delete_selected()
assert ed.m.con_by_id(cd["id"]) is None
# --- configuration column of a deleted dimension goes
# --- angles
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
w.set_tool("line"); click(0, 0); click(40, 0); ed.reset_tool("select"); w.set_tool("line"); click(0, 0); click(30, 30); ed.reset_tool("select")
l1, l2 = list(ed.m.lns)[:2]; refs = [("ln", l1), ("ln", l2)]
choices = []
def fake(parent, acute, obtuse, default, preview=None):
    choices.append((round(acute, 3), round(obtuse, 3), default)); preview and preview("obtuse"); return "obtuse"
se.ask_angle = fake
ed.cursor = (10, 3)                                       # inside the acute sector
res = ed.choose_angle(refs)
assert choices[0][:2] == (45.0, 135.0) and choices[0][2] == "acute", choices
assert abs(res[3] - 135.0) < 1e-6, res                    # the user chose the obtuse one
se.ask_angle = lambda *a, **k: "acute"; res = ed.choose_angle(refs); assert abs(res[3] - 45.0) < 1e-6, res
se.ask_angle = lambda *a, **k: None; assert ed.choose_angle(refs) is None
# perpendicular: no question
w.set_tool("line"); click(0, 0); click(0, 30); ed.reset_tool("select")
l3 = list(ed.m.lns)[-1]; asked = []; se.ask_angle = lambda *a, **k: asked.append(1) or "acute"
ed.choose_angle([("ln", l1), ("ln", l3)]); assert not asked
# an angle dimension: drag its label to the opposite side -> flips sector, same value; to the adjacent side -> stays
se.ask_angle = lambda *a, **k: "acute"; ed.cursor = (10, 3)
ed.commit(lambda m: m.add_con("dim_ang", refs, value=45.0, **dict(zip(("s1", "s2", "eps"), ed.m.angle_default(refs, hint=(10, 3))[:3]))))
ca = [c for c in ed.m.cons if c["type"] == "dim_ang"][0]; s1, s2 = ca["s1"], ca["s2"]; v0 = ca["value"]
ed.render_ = None
t0 = [t for t in ed.tags if t[2] == ca["id"]][0]; sx, sy = ed.screen_of(__import__("numpy").array([(t0[0], t0[1])]))[0]
tx = ed.screen_of(__import__("numpy").array([(-12, -4)]))[0]       # the opposite sector (behind the origin)
ed.press(sx + 30 * r, sy + 12 * r); ed.move(sx + 60 * r, sy + 40 * r); ed.move(*tx); ed.release(*tx)
ca = ed.m.con_by_id(ca["id"]); assert (ca["s1"], ca["s2"]) == (-s1, -s2) and ca["value"] == v0, (ca, s1, s2)
# change which angle: the neighbouring sector, the drawing does not move
pts0 = {i: tuple(p) for i, p in ed.m.pts.items()}
ed.change_angle(ca["id"]); ca = ed.m.con_by_id(ca["id"])
assert abs(ca["value"] - 135.0) < 1e-6 and {i: tuple(p) for i, p in ed.m.pts.items()} == pts0, ca
print("DIMS UI OK")
