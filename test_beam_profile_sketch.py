"""1D FEA profile sketches: the section of a drawn outline against the closed forms, the copies of profile parts in the project folder,
the tab (add / use / update / remove / save / reopen / units), the Profile window, and parametric studies that change a profile sketch
(of the frame's part and of another part)."""
import os, sys, math, json, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
PAR = os.path.join(HERE, "addons_src", "parametric")
sys.path[:0] = [HERE, SIM, PAR, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, sketcher_core as sc, ext, units
import profiles1d as pr, profile_sketch as ps, physics_store as pstore
import beam_dialogs as bd
import sim_tab, sim_project as sp
import study_core as core, study_ext

T = tempfile.mkdtemp(prefix="opara_prof_")
close = lambda a, b, tol=1e-6: abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)
def hgt(prof):
    """The height of the outline of a profile sketch (an unanchored sketch may move when it is solved again)."""
    ys = [y for poly, _hole in prof["outline"] for _x, y in poly]
    return max(ys) - min(ys)

# ---------------------------------------------------------------- 1. the section of a drawn outline
m = sc.Model()
sk.add_rect_corner(m, (0, 0), (50, 100)); sk.add_rect_corner(m, (5, 5), (45, 95))            # a box, wall 5
ol, notes = ps.outline_of(m)
box, ref = pr.sketch("box", ol), pr.compute("rtube", {"b": 50, "h": 100, "t": 5})
assert close(box["A"], ref["A"]) and close(box["I"], ref["I"]) and close(box["c_top"], 50) and close(box["c_bottom"], 50), (box["A"], box["I"])
assert box["shape"] == "sketch" and box["dims"] == {} and abs(box["skew"]) < 1e-9 and notes == [] and "As" not in box
assert pr.shear_area(box) is None, "a drawn section has no shear area unless one is given"
turned, ref_w = pr.sketch("box", ol, weak=True), pr.compute("rtube", {"b": 50, "h": 100, "t": 5}, weak=True)
assert close(turned["I"], ref_w["I"]) and close(turned["c_top"], 25) and "turned" in turned["label"]
assert json.loads(json.dumps(box)) == box, "a sketch profile is plain data (it is saved in the project and in study cases)"

m = sc.Model()                                                   # a pipe: two circles
c = m.add_point(0, 0); m.add_circle(c, 30.0); m.add_circle(c, 26.0)
pipe, ref = pr.sketch("pipe", ps.outline_of(m)[0]), pr.compute("pipe", {"d": 60, "t": 4})
assert close(pipe["A"], ref["A"], 2e-3) and close(pipe["I"], ref["I"], 2e-3), (pipe["A"], ref["A"], pipe["I"], ref["I"])

m = sc.Model()                                                   # a T: flange on top, drawn as one outline
pts = [(-4, 0), (4, 0), (4, 92), (50, 92), (50, 100), (-50, 100), (-50, 92), (-4, 92)]
ids = [m.add_point(x, y) for x, y in pts]
for i in range(len(ids)):
    m.add_line(ids[i], ids[(i + 1) % len(ids)])
tee, ref = pr.sketch("tee", ps.outline_of(m)[0]), pr.compute("tee", {"bf": 100, "h": 100, "tf": 8, "tw": 8})
assert close(tee["A"], ref["A"]) and close(tee["I"], ref["I"]) and close(tee["c_top"], ref["c_top"]) and tee["c_top"] < tee["c_bottom"]
flipped = pr.sketch("tee", ps.outline_of(m)[0], flip=True)
assert close(flipped["c_top"], tee["c_bottom"]) and close(flipped["c_bottom"], tee["c_top"]) and close(flipped["I"], tee["I"])
two = pr.sketch("tee", ps.outline_of(m)[0], copies={"nx": 2}, As=500.0)
assert close(two["A"], 2 * tee["A"]) and close(two["I"], 2 * tee["I"]) and close(two["As"], 1000.0) and two["As_one"] == 500.0 and "skew" not in two
assert close(pr.shear_area(two), 1000.0)
again = pr.relink(two, ps.outline_of(m)[0], "renamed")
assert again["label"].startswith("renamed") and close(again["I"], two["I"]) and again["copies"] == two["copies"] and again["As_one"] == 500.0
big = pr.scale(tee, 0.1)
assert close(big["A"], tee["A"] * 0.01) and close(big["I"], tee["I"] * 1e-4) and close(pr.relink(big, big["outline"])["I"], big["I"])
assert len(pr.drawing(two)) == 2 and len(pr.drawing(tee)) == 1

m = sc.Model()                                                   # an angle: not symmetric about the frame plane -> the note
pts = [(0, 0), (60, 0), (60, 6), (6, 6), (6, 90), (0, 90)]
ids = [m.add_point(x, y) for x, y in pts]
for i in range(len(ids)):
    m.add_line(ids[i], ids[(i + 1) % len(ids)])
ang = pr.sketch("angle", ps.outline_of(m)[0])
assert abs(ang["skew"]) > pr.SKEW_NOTE and close(ang["I"], pr.compute("angle", {"b": 60, "h": 90, "t": 6})["I"])

m = sc.Model()                                                   # a rounded slot section (arcs): the strips of the nonlinear solver stay few
a, b_, c1, c2 = m.add_point(0, -20), m.add_point(0, 20), m.add_point(60, -20), m.add_point(60, 20)
ca, cb = m.add_point(0, 0), m.add_point(60, 0)
m.add_line(a, c1); m.add_line(b_, c2); m.add_arc(ca, b_, a); m.add_arc(cb, c1, c2)
slot = pr.sketch("slot", ps.outline_of(m)[0])
A_slot = 60 * 40 + math.pi * 20 ** 2
I_slot = 60 * 40 ** 3 / 12 + math.pi * 20 ** 4 / 4
assert close(slot["A"], A_slot, 2e-3) and close(slot["I"], I_slot, 2e-3), (slot["A"], A_slot, slot["I"], I_slot)
y, dA = pr.fibres(slot)
assert len(y) <= 4 * 60 + 2 and close(float(dA.sum()), slot["A"]) and close(float((dA * y * y).sum()), slot["I"], 5e-3), len(y)

m = sc.Model()                                                   # an open shape, and lines that cross: refused with the reason
ids = [m.add_point(x, y) for x, y in ((0, 0), (10, 0), (10, 10))]
m.add_line(ids[0], ids[1]); m.add_line(ids[1], ids[2])
for bad in (m,):
    try:
        ps.outline_of(bad); raise SystemExit("an open outline must be refused")
    except ValueError as ex:
        assert "closed" in str(ex), ex
m = sc.Model()
sk.add_rect_corner(m, (0, 0), (10, 10))
p1, p2 = m.add_point(-5, 5), m.add_point(15, 5); m.add_line(p1, p2)
try:
    ps.outline_of(m); raise SystemExit("crossing lines must be refused")
except ValueError as ex:
    assert "cross" in str(ex), ex
m = sc.Model(); sk.add_rect_corner(m, (0, 0), (25.4, 50.8))                              # units: the outline arrives in the tab's unit
inch = next(n for n in units.names() if "in" in n.lower() and units.length_factor(m.unit_system, n) != 1.0) if hasattr(units, "names") else None
if inch:
    f = units.length_factor(m.unit_system, inch)
    assert close(pr.sketch("r", ps.outline_of(m, inch)[0])["A"], 25.4 * 50.8 * f * f)
print("section maths ok")

# ---------------------------------------------------------------- 2. the parts: a frame with a profile sketch of its own, and a separate profile part
def rect_sketch(d, w, h, name):
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
    r = sk.add_rect_corner(mm, (0, 0), (w, h))
    mm.add_con("dim_h", [("ln", r["lns"][0])], value=w); mm.add_con("dim_v", [("ln", r["lns"][1])], value=h)
    sk.solve_model(mm); d.store_sketch(s["id"])
    s["name"] = name
    return s["id"]

def make_frame(path, h=40.0):
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
    a, b = mm.add_point(0, 0), mm.add_point(1000, 0); l = mm.add_line(a, b)
    mm.add_con("dim_h", [("ln", l)], value=1000.0)
    sk.solve_model(mm); d.store_sketch(s["id"])
    s["name"] = "Frame"
    sec = rect_sketch(d, 20.0, h, "Own section")
    d.rebuild()
    open(path, "w").write(d.to_json())
    return s["id"], sec

def make_profile_part(path, h=60.0):
    d = pm.Document()
    sec = rect_sketch(d, 30.0, h, "Hat")
    other = rect_sketch(d, 5.0, 5.0, "Not a profile")
    d.rebuild()
    open(path, "w").write(d.to_json())
    return sec, other

os.makedirs(os.path.join(T, "orig"))
frame_gpd, hat_gpd = os.path.join(T, "orig", "frame.gpd"), os.path.join(T, "orig", "hat.gpd")
fid, own_sid = make_frame(frame_gpd)
hat_sid, other_sid = make_profile_part(hat_gpd)

# ---------------------------------------------------------------- 3. the project folder: copies of profile parts
proj = os.path.join(T, "p1.gpb")
sp.create(proj, "beam")
assert sp.profile_parts(proj) == [] and sp.profile_file(proj, "hat.gpd") is None
mf, e = sp.import_profile_part(proj, orig_path=hat_gpd)
assert e["key"] == "hat.gpd" and e["file"] == "profiles/hat.gpd" and os.path.isfile(sp.profile_file(proj, "hat.gpd")) and e["name"] == "hat"
mf, e2 = sp.import_profile_part(proj, orig_path=hat_gpd)
assert e2["key"] == "hat.gpd" and len(sp.profile_parts(proj)) == 1, "the same original is replaced, not copied twice"
os.makedirs(os.path.join(T, "other"))
shutil.copyfile(hat_gpd, os.path.join(T, "other", "hat.gpd"))
mf, e3 = sp.import_profile_part(proj, orig_path=os.path.join(T, "other", "hat.gpd"))
assert e3["key"] == "hat_2.gpd" and len(sp.profile_parts(proj)) == 2, "another part of the same name gets its own copy"
sp.import_source(proj, orig_path=frame_gpd)
assert len(sp.profile_parts(proj)) == 2 and os.path.isfile(sp.profile_file(proj, "hat.gpd")), "importing a source keeps the profile parts"
sp.remove_profile_part(proj, "hat_2.gpd")
assert [x["key"] for x in sp.profile_parts(proj)] == ["hat.gpd"] and not os.path.exists(os.path.join(proj, "profiles", "hat_2.gpd"))
for bad in (os.path.join(T, "nope.gpd"),):
    try:
        sp.import_profile_part(proj, orig_path=bad); raise SystemExit("a missing part must be refused")
    except sp.ProjectError:
        pass
open(os.path.join(T, "asm.gpa"), "w").write(json.dumps({"components": []}))
try:
    sp.import_profile_part(proj, orig_path=os.path.join(T, "asm.gpa")); raise SystemExit("an assembly must be refused")
except sp.ProjectError:
    pass

# ---------------------------------------------------------------- 4. the tab: add, use, solve
w = sim_tab.SimWindow("beam")
assert w.create_project(os.path.join(T, "cant")) and w.import_file(frame_gpd)
w.tab.picker.refresh(); w.tab.picker.select(fid); w.tab.picker.go()
t = w.tab
assert t.model is not None and len(t.members) == 1 and t.profs == [] and t.prof_list.count() == 0
labels = [lab for lab, _s in w.profile_choices()]
assert len(labels) == 1 and "frame's part" in labels[0], labels
doc = w.profile_spec_doc((sim_tab.MAIN_PART,))
assert [n for _i, n in ps.sketches_of(doc)] == ["Frame", "Own section"]
own = t.add_prof(w.add_profile_from((sim_tab.MAIN_PART,), own_sid))
assert own["part"] == "main" and own["name"] == "Own section" and own["id"] == 1 and t.prof_list.count() == 1 and "not used yet" in t.prof_list.item(0).text()
assert not os.path.isdir(os.path.join(w.path, "profiles")), "a sketch of the frame's own part needs no second copy"
hat = t.add_prof(w.add_profile_from(("file", hat_gpd), hat_sid))
assert hat["part"] == "hat.gpd" and hat["part_name"] == "hat" and os.path.isfile(os.path.join(w.path, "profiles", "hat.gpd")) and hat["id"] == 2
assert t.add_prof(w.add_profile_from(("have", "hat.gpd"), hat_sid)) is hat and len(t.profs) == 2, "the same sketch is not added twice"
assert any("hat" in lab and "already in the project" in lab for lab, _s in w.profile_choices())
try:
    w.add_profile_from(("have", "hat.gpd"), "no-such-sketch"); raise SystemExit("a sketch that is not there must be refused")
except ValueError:
    pass

q = sorted((t.members[0]["a"], t.members[0]["b"]), key=lambda p: t.model.pts[p][0])
t.supports = [{"mode": "fixed", "targets": [q[0]]}]
t.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[-1]]}]
t.cb_auto.setChecked(False)
t.cb_nl.setChecked(False)
E_ = float(t.e_E.text()); P, L = 500.0, 1000.0
def tip(I):
    return P * L ** 3 / (3 * E_ * I)
def solved():
    t.solve()
    assert t.result is not None, t.res_lbl.text()
    return t.result["umax"]
t.set_profiles([0], pr.sketch(own["name"], own["outline"], ref=own["id"]))
assert t.members[0]["profile"]["label"] == "Own section" and "1 member" in t.prof_list.item(0).text()
assert close(t.members[0]["profile"]["I"], 20 * 40 ** 3 / 12) and close(solved(), tip(20 * 40 ** 3 / 12), 0.02)
t.set_profiles([0], pr.sketch(hat["name"], hat["outline"], ref=hat["id"]))
assert close(t.members[0]["profile"]["I"], 30 * 60 ** 3 / 12) and close(solved(), tip(30 * 60 ** 3 / 12), 0.02)

# the nonlinear solver takes the drawn outline as fibres: at this small load it agrees with the linear one
u_lin = t.result["umax"]
t.cb_lin.setChecked(False); t.cb_nl.setChecked(True)
u_nl = solved()
assert close(u_nl, u_lin, 0.01), (u_nl, u_lin)
t.cb_lin.setChecked(True); t.cb_nl.setChecked(False)

# the Profile window offers the profile sketches, with flip / turn / copies and the optional shear area
dlg = bd.ProfileDialog(t, 0)
assert dlg.shape.currentData() == f"sketch:{hat['id']}" and dlg.shape.findData(f"sketch:{own['id']}") >= 0
assert close(dlg.profile["I"], 30 * 60 ** 3 / 12) and dlg.cb_weak.isEnabled() and dlg.cb_weak.text() == "Turn 90 degrees" and "shear area" in dlg.info.text()
dlg.cb_weak.setChecked(True)
assert close(dlg.profile["I"], 60 * 30 ** 3 / 12) and dlg.profile["weak"]
dlg.cb_weak.setChecked(False)
dlg.edits["As"].setText("900")
assert close(dlg.profile["As"], 900.0) and "shear area" not in dlg.info.text()
dlg.edits["As"].setText("x")
assert dlg.profile is None and not dlg.bb.button(dlg.bb.StandardButton.Ok).isEnabled()
dlg.edits["As"].setText("")
dlg.cp_nx.setValue(2)
assert close(dlg.profile["I"], 2 * 30 * 60 ** 3 / 12) and len(dlg.preview.polys) == 2
dlg.cp_nx.setValue(1)
dlg.shape.setCurrentIndex(dlg.shape.findData(f"sketch:{own['id']}"))
assert close(dlg.profile["I"], 20 * 40 ** 3 / 12) and dlg.profile["ref"] == own["id"]
dlg.shape.setCurrentIndex(dlg.shape.findData("rect"))
assert dlg.profile["shape"] == "rect" and dlg.cb_weak.text() == "Bend about the weak axis" and "As" not in dlg.edits
dlg.reject()
# the window that adds one: the frame's part first, its sketches without the frame sketch
old_exec = QDialog.exec
QDialog.exec = lambda self: 1
got = w.pick_profile_sketch()
QDialog.exec = old_exec
assert got is not None and got["part"] == "main" and got["sid"] == own_sid and got["sketch"] == "Own section", got

# ---------------------------------------------------------------- 5. save, reopen, the original gone
assert w.is_dirty() and w.save() and not w.is_dirty()
folder = w.path
os.replace(hat_gpd, hat_gpd + ".away")
w2 = sim_tab.SimWindow.open_project(None, folder)
t2 = w2.tab
assert [p["name"] for p in t2.profs] == ["Own section", "Hat"] and t2.prof_seq == 2 and t2.prof_list.count() == 2
assert t2.members[0]["profile"]["shape"] == "sketch" and t2.members[0]["profile"]["ref"] == 2 and close(t2.members[0]["profile"]["I"], 30 * 60 ** 3 / 12)
notes = w2.update_profile_parts()
assert len(notes) == 1 and "not found" in notes[0] and os.path.isfile(os.path.join(folder, "profiles", "hat.gpd")), notes
assert t2.refresh_profs() == [] and close(t2.members[0]["profile"]["I"], 30 * 60 ** 3 / 12), "the copy in the project still works"
os.replace(hat_gpd + ".away", hat_gpd)

# ---------------------------------------------------------------- 6. the originals change: Update, and Update from original
make_profile_part(hat_gpd, h=80.0)
t2.update_profile_sketches()
assert close(t2.members[0]["profile"]["I"], 30 * 80 ** 3 / 12), "Update copies the profile part again and the member follows"
assert close(hgt(t2.prof_by_id(1)), 40.0), "the frame's own section is unchanged"
make_frame(frame_gpd, h=50.0)
make_profile_part(hat_gpd, h=70.0)
t2.result = None
w2.refresh()
assert close(t2.members[0]["profile"]["I"], 30 * 70 ** 3 / 12), "Update from original takes the profile parts too"
t2.set_profiles([0], pr.sketch("Own section", t2.prof_by_id(1)["outline"], ref=1))
assert close(t2.members[0]["profile"]["I"], 20 * 50 ** 3 / 12), "and the profile sketch of the frame's own part"
# a profile sketch that no longer closes: the earlier outline stays, and the tab says so
d_bad = pm.Document.from_json(open(hat_gpd).read()); d_bad.rebuild()
mm = d_bad.models[hat_sid]
gone = next(iter(mm.lns))
mm.constr.add(("ln", gone)) if isinstance(mm.constr, set) else mm.constr.append(("ln", gone))
d_bad.store_sketch(hat_sid)
open(hat_gpd, "w").write(d_bad.to_json())
t2.set_profiles([0], pr.sketch("Hat", t2.prof_by_id(2)["outline"], ref=2))
t2.update_profile_sketches()
assert t2.prof_by_id(2)["error"] and "closed" in t2.prof_by_id(2)["error"] and close(t2.members[0]["profile"]["I"], 30 * 70 ** 3 / 12)
assert t2.prof_problems() and "earlier outline" in t2.info.text()
make_profile_part(hat_gpd, h=60.0)
t2.update_profile_sketches()
assert t2.prof_by_id(2)["error"] is None and not t2.prof_problems() and close(t2.members[0]["profile"]["I"], 30 * 60 ** 3 / 12)
make_frame(frame_gpd, h=40.0)
t2.result = None
w2.refresh()

# units: the outlines are lengths
st = t2.export_state()
other = next(n for n in units.names() if units.length_factor(t2.unit_name(), n) != 1.0)
f = units.length_factor(t2.unit_name(), other)
st2 = pstore.convert_beam_state(st, t2.unit_name(), other, True)
assert close(hgt(st2["profs"][1]), 60.0 * f) and close(st2["members"][0]["profile"]["I"], 30 * 60 ** 3 / 12 * f ** 4)
assert close(hgt(st["profs"][1]), 60.0), "the state that was converted is not changed itself"
print("tab ok")

# ---------------------------------------------------------------- 7. parametric studies
w2.save()
t2.supports = [{"mode": "fixed", "targets": [q[0]]}]
t2.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[-1]]}]
t2.cb_nl.setChecked(False)
t2.set_profiles([0], pr.sketch("Hat", t2.prof_by_id(2)["outline"], ref=2))
ad = t2.study_adapter()
assert ad.ready() is None
ps_ = {d["id"]: d for d in ad.params()}
prof_ids = [i for i in ps_ if i.startswith("beam.prof.")]
assert len(prof_ids) == 2 and all(i.startswith("beam.prof.hat.gpd.d:" + str(hat_sid)) for i in prof_ids), prof_ids
assert all(ps_[i]["group"].startswith("Profile sketch dimensions") and ps_[i]["label"].startswith("hat: ") for i in prof_ids)
assert not [i for i in ps_ if i.startswith("beam.mem")], "a sketched profile has no dimensions of its own: they are in its sketch"
hat_h = next(i for i in prof_ids if float(ps_[i]["now"]) == 60.0)
ctx = {}
def run(values, state=None):
    spc = ad.prepare(values, ctx, state)
    assert spc["error"] is None, spc["error"]
    c = spc["run"](lambda *a, **k: None, lambda: False)
    assert c["status"] == "ok", c
    return c
before = (repr(t2.members), repr(t2.profs), repr(t2.loads))
c0, c1 = run({}), run({hat_h: "120"})
u0, u1 = (ad.case_outputs(c, ["beam.umax"])["beam.umax"] for c in (c0, c1))
assert close(u0, tip(30 * 60 ** 3 / 12), 0.02) and close(u1 / u0, 1 / 8, 0.01), (u0, u1)
assert "profs" not in c0 and close(hgt(c1["profs"][1]), 120.0) and len(ctx["profile_outlines"]) == 1
run({hat_h: "120"})
assert len(ctx["profile_outlines"]) == 1, "the changed part is loaded once per set of values"
assert (repr(t2.members), repr(t2.profs), repr(t2.loads)) == before and os.path.getsize(os.path.join(folder, "profiles", "hat.gpd")) > 0, "a case changes nothing on the tab or in the project"
assert close(pr.sketch("x", ps.read(w2.profile_source("hat.gpd", True).doc, hat_sid)[0])["I"], 30 * 60 ** 3 / 12), "the copy in the project is not changed"
for val, word in (("abc", "not a number"), ("0", "more than 0"), ("-5", "more than 0")):
    bad = ad.prepare({hat_h: val}, ctx)
    assert bad["error"] and word in bad["error"] and bad["run"] is None, (val, bad)
# the frame's own part: its dimensions change the frame AND its profile sketch (geometry_state)
t2.set_profiles([0], pr.sketch("Own section", t2.prof_by_id(1)["outline"], ref=1))
ad = t2.study_adapter()
own_h = next(key for key, lab, now in w2.source.doc.cfg_candidates() if key.startswith(f"d:{own_sid}:") and float(now) == 40.0)
frame_L = next(key for key, lab, now in w2.source.doc.cfg_candidates() if key.startswith(f"d:{fid}:") and float(now) == 1000.0)
import sim_source
g0 = run({})
g1 = run({}, ad.geometry_state(sim_source.open_source(sp.source_file(folder)), {own_h: "80"}))
g2 = run({}, ad.geometry_state(sim_source.open_source(sp.source_file(folder)), {frame_L: "2000"}))
v0, v1, v2 = (ad.case_outputs(c, ["beam.umax"])["beam.umax"] for c in (g0, g1, g2))
assert close(v0, tip(20 * 40 ** 3 / 12), 0.02) and close(v1 / v0, 1 / 8, 0.01) and close(v2 / v0, 8, 0.01), (v0, v1, v2)
# a profile sketch that is out of date fails the case with the reason instead of running on the old outline
t2.prof_by_id(1)["error"] = "The sketch has no closed outline."
bad = t2.study_adapter().prepare({}, {})
assert bad["error"] and "Own section" in bad["error"] and "Update" in bad["error"], bad
t2.prof_by_id(1)["error"] = None

# the study tab end to end: both kinds of profile input side by side, show a case, back to the own inputs
ext.HOOKS.clear(); study_ext.register(ext)
w2.save()
tab = study_ext.open_study(w2, threaded=False)
d = tab.desc
geo_own = core.GEO + own_h
assert geo_own in d and d[geo_own]["label"].endswith("@Own section") and hat_h in d, [k for k in d if "geo" in k or "prof" in k]
from PyQt6.QtCore import Qt
t2.set_profiles([0], pr.sketch("Hat", t2.prof_by_id(2)["outline"], ref=2))
tab.refresh_params()
for pid in (tab.items[hat_h],):
    pid.setCheckState(0, Qt.CheckState.Checked)
assert tab.cols() == [hat_h] and tab.fill_grid({hat_h: "60, 120"})
tab.data.out_checked = ["beam.status", "beam.umax", "beam.sigma"]
tab.fill_outputs()
assert tab.run_all()
assert [c["status"] for c in tab.data.cases] == ["ok", "ok"], [(c["status"], c.get("error")) for c in tab.data.cases]
uu = [c["outputs"]["beam.umax"] for c in tab.data.cases]
ss_ = [c["outputs"]["beam.sigma"] for c in tab.data.cases]
assert close(uu[1] / uu[0], 1 / 8, 0.01) and close(ss_[1] / ss_[0], 1 / 4, 0.01), (uu, ss_)
assert close(t2.members[0]["profile"]["I"], 30 * 60 ** 3 / 12), "the live tab is untouched by the run"
assert tab.show_case(1)
assert close(t2.members[0]["profile"]["I"], 30 * 120 ** 3 / 12) and t2.result is not None, "the shown case brings its profile sketch"
tab.back_to_own()
assert close(t2.members[0]["profile"]["I"], 30 * 60 ** 3 / 12)
# reopened from the project: the case still shows its profile
tab.save()
assert w2.save()
study_ext.forget(tab) if hasattr(study_ext, "forget") else None
w3 = sim_tab.SimWindow.open_project(None, folder)
tab3 = study_ext.open_study(w3, threaded=False)
assert len(tab3.data.cases) == 2 and tab3.show_case(1) and close(w3.tab.members[0]["profile"]["I"], 30 * 120 ** 3 / 12)

# ---------------------------------------------------------------- 8. remove
t = w3.tab
tab3.back_to_own()
t.prof_list.setCurrentRow(1)
t.remove_profile_sketch()
assert [p["name"] for p in t.profs] == ["Own section"] and t.members[0]["profile"] is None
assert not os.path.exists(os.path.join(folder, "profiles", "hat.gpd")) and sp.profile_parts(folder) == [], "its part leaves the project with it"
assert not [i for i in {x["id"] for x in t.study_adapter().params()} if i.startswith("beam.prof.")]
t.prof_list.setCurrentRow(0)
t.remove_profile_sketch()
assert t.profs == [] and t.prof_list.count() == 0

# ---------------------------------------------------------------- 9. a part that is open in a tab: its live state is what is copied
class FakeTab:
    def __init__(self, path):
        self.path = path
        self.doc = pm.Document.from_json(open(path).read()); self.doc.rebuild()
    def title(self):
        return os.path.basename(self.path)
class FakeTabs:
    def __init__(self, tabs): self.t = tabs
    def count(self): return len(self.t)
    def widget(self, i): return self.t[i]
class FakeShell:
    def __init__(self, tabs): self.tabs = FakeTabs(tabs)
    def find_tab(self, path):
        return next((i for i, x in enumerate(self.tabs.t) if os.path.normcase(x.path) == os.path.normcase(path)), None)
    def refresh_titles(self): pass
make_profile_part(hat_gpd, h=60.0)
ft = FakeTab(hat_gpd)
hkey = next(k for k, lab, now in ft.doc.cfg_candidates() if k.startswith(f"d:{hat_sid}:") and float(now) == 60.0)
ft.doc.cfg_write(hkey, 90.0); ft.doc.rebuild()                       # an edit that is not saved to the file
w5 = sim_tab.SimWindow("beam", shell=FakeShell([ft]))
assert w5.create_project(os.path.join(T, "live")) and w5.import_file(frame_gpd)
w5.tab.picker.refresh(); w5.tab.picker.select(fid); w5.tab.picker.go()
ch = w5.profile_choices()
assert [sp_[0] for _l, sp_ in ch] == ["main", "tab"] and "open part tab" in ch[1][0], ch
live = w5.tab.add_prof(w5.add_profile_from(ch[1][1], hat_sid))
assert close(hgt(live), 90.0) and live["part"] == "hat.gpd", "the open tab's state is copied, unsaved edits included"
assert close(hgt({"outline": ps.read(sim_source.PartSource(hat_gpd).doc, hat_sid)[0]}), 60.0), "the file itself still has the saved size"
ft.doc.cfg_write(hkey, 100.0); ft.doc.rebuild()
w5.tab.update_profile_sketches()
assert close(hgt(w5.tab.prof_by_id(live["id"])), 100.0), "Update takes the open tab again"
print("ok")
sys.stdout.flush()
os._exit(0)            # skip PyQt's clean-up at exit: it can crash deleting the widgets this script still holds (as in the other UI tests)
