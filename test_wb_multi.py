"""One Parametric Study block with any number of wires into its Parameters cell: the dimensions of Parts (they flow through every analysis that works on that Part, as its geometry or
as one of its profiles) and the Setup of any number of analyses (their own inputs; the outputs of every one of them are recorded).  Two 1D beams on one frame, one with a profile part,
are studied together: the inputs are grouped per block, a case sets every ticked value and runs both beams, the study is kept in the study block (and comes back with the saved project),
a study needs one analysis at least, taking a wire away removes its inputs and outputs.   python test_wb_multi.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(560, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for name in ("workbench", "solid_fea", "thermal3d", "thermal2d"):
    shutil.copytree(os.path.join(HERE, "dev_addons", name), os.path.join(DEV, name), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
import PyQt6.QtWidgets as qw
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import addons
import ext
addons.startup()
addons.register_extensions(ext)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import gpd_app
import pm_model as pm
import profiles1d as pr
import sk_tools as sk
import study_core
import study_tab
import wb_multi
import wb_project as wp
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbm_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
P = W.project


def close(a, b, tol=0.02):
    return abs(a - b) <= tol * max(1.0, abs(b))


def rect_sketch(d, w, h, name):
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    mm = d.models[s["id"]]
    r = sk.add_rect_corner(mm, (0, 0), (w, h))
    mm.add_con("dim_h", [("ln", r["lns"][0])], value=w)
    mm.add_con("dim_v", [("ln", r["lns"][1])], value=h)
    sk.solve_model(mm)
    d.store_sketch(s["id"])
    s["name"] = name
    return s["id"]


def frame_doc():
    d = pm.Document()
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    mm = d.models[s["id"]]
    a, b = mm.add_point(0, 0), mm.add_point(1000, 0)
    ln = mm.add_line(a, b)
    mm.add_con("dim_h", [("ln", ln)], value=1000.0)
    sk.solve_model(mm)
    d.store_sketch(s["id"])
    s["name"] = "Frame"
    d.rebuild()
    return json.loads(d.to_json()), s["id"]


def profile_doc(w, h, name):
    d = pm.Document()
    sid = rect_sketch(d, w, h, name)
    d.rebuild()
    return json.loads(d.to_json()), sid


fdoc, fid = frame_doc()
hdoc, hid = profile_doc(30.0, 60.0, "Hat")
nF = W.add_block("part", 40, 40, title="Frame", data={"doc": fdoc})
nH = W.add_block("part", 40, 260, title="Hat", data={"doc": hdoc})
nB1 = W.add_block("beam", 440, 40, title="Hat beam")
nB2 = W.add_block("beam", 440, 300, title="Plain beam")
nS = W.add_block("study", 860, 140, title="Beam study")

# ---- the cell takes any number of wires
c = wp.spec_of("study").cell("setup")
ok(c.many and c.accepts == ("analysis", "dimensions") and c.needs_any == ("analysis",), "Parameters takes any number of wires: analyses and the dimensions of parts")
ok("dimensions" in wp.spec_of("part").cell("geometry").provides, "a Part gives its dimensions")
ok(P.status(nS.id, "setup") == wp.INCOMPLETE, "a study with no wire is incomplete")
MSGS.clear(); W.line.setText("")
ok(W.open_cell(nS.id, "results") is None and "Wire the Setup cell of an analysis" in W.line.text(), f"and says what to wire ({W.line.text()[:60]})")
ok(W.scene.make_link(nF.id, "geometry", nS.id, "setup") is not None, "a Part can be wired in")
ok(P.status(nS.id, "setup") == wp.INCOMPLETE and "Setup cell of an analysis" in P.why_incomplete(nS.id, "setup"),
   f"a Part alone is still incomplete: it needs an analysis ({P.why_incomplete(nS.id, 'setup')})")

# ---- the two beams
W.scene.make_link(nF.id, "geometry", nB1.id, "geometry")
W.scene.make_link(nF.id, "geometry", nB2.id, "geometry")
W.scene.make_link(nH.id, "geometry", nB1.id, "profile")
done, failed = W.refresh_project(only={nB1.id, nB2.id})
ok(done >= 3 and not failed, f"the beams took the frame and the profile ({done}, {failed})")


def setup_beam(node, force, profile):
    w = W.open_cell(node.id, "setup")
    w.tab.picker.refresh()
    w.tab.picker.select(fid)
    w.tab.picker.go()
    t = w.tab
    q = sorted((t.members[0]["a"], t.members[0]["b"]), key=lambda p: t.model.pts[p][0])
    t.supports = [{"mode": "fixed", "targets": [q[0]]}]
    t.loads = [{"kind": "force", "fx": 0.0, "fy": -force, "targets": [q[-1]]}]
    t.cb_auto.setChecked(False)
    t.cb_nl.setChecked(False)
    if profile == "hat":
        key = next(e["key"] for e in __import__("sim_project").profile_parts(w.path) if e["name"] == "Hat")
        hat = t.add_prof(w.add_profile_from(("have", key), hid))
        t.set_profiles([0], pr.sketch(hat["name"], hat["outline"], ref=hat["id"]))
    else:
        t.set_profiles([0], pr.compute("rect", {"b": 20.0, "h": 40.0}))
    w.tab.changed()
    return w


w1 = setup_beam(nB1, 500.0, "hat")
w2 = setup_beam(nB2, 250.0, "rect")
E_ = float(w1.tab.e_E.text())
W.sync_editors()
ok(P.status(nB1.id, "setup") == wp.OK and P.status(nB2.id, "setup") == wp.OK, "both beams have their setup")

def tip(P_, L, I):
    return P_ * L ** 3 / (3 * E_ * I)

I_hat, I_rect = 30 * 60 ** 3 / 12, 20 * 40 ** 3 / 12

# ---- wire everything in
ok(W.scene.make_link(nB1.id, "setup", nS.id, "setup") is not None and W.scene.make_link(nB2.id, "setup", nS.id, "setup") is not None, "two analyses are wired in")
ok(W.scene.make_link(nH.id, "geometry", nS.id, "setup") is not None, "and a second part")
ok(len(P.incoming_all(nS.id, "setup")) == 4, "four wires into one cell")
ok(P.status(nS.id, "setup") == wp.REFRESH, f"Parameters says refresh ({P.status(nS.id, 'setup')})")
done, failed = W.refresh_project(only={nS.id})
ok(not failed and P.status(nS.id, "setup") == wp.OK, f"Refresh took them ({failed})")
st = W.open_cell(nS.id, "results")
ok(isinstance(st, study_tab.StudyTab) and W.editor_of(nS.id) is st, "double-click opens the study window of the block")
ok(isinstance(st.sw, wb_multi.StudyHost) and st.path_ == st.sw.path and st.sw.path.endswith(".study"), f"it works on the block's own folder ({st.path_})")
ok(W.editor_of(nB1.id) is w1 and W.editor_of(nB2.id) is w2, "the analyses stay open as their own tabs")
ids = list(st.desc)
print("      inputs:", ids[:40])
groups = []
for d in st.desc.values():
    if d["group"] not in groups:
        groups.append(d["group"])
print("      groups:", groups)
print("      outputs:", [o["id"] for o in st.outs][:30])
ok(all("/" in i for i in ids), "every input carries the letter of its block")
ok(any(g.startswith(f"{nF.label} Frame") for g in groups) and any(g.startswith(f"{nH.label} Hat") for g in groups), "the parts have their own groups")
ok(any(g.startswith(f"{nB1.label} Hat beam") for g in groups) and any(g.startswith(f"{nB2.label} Plain beam") for g in groups), "so have the beams")
ok(not any("Profile sketch dimensions" in g for g in groups), "the profile part's dimensions are the Hat's, not repeated under the beam")
ok(not any("Part dimensions" in g for g in groups), "and so are the frame's")
ok({o["id"].split("/")[0] for o in st.outs} == {nB1.label, nB2.label}, "the outputs come from both beams")

# ---- the table: the frame's length, the hat's depth and the second beam's force
L_, H_, F2_ = "A/d:F1:1", "B/d:F1:6", f"{nB2.label}/beam.load0.fy"
U1, U2 = f"{nB1.label}/beam.umax", f"{nB2.label}/beam.umax"
ok(st.desc[L_]["now"] == "1000.0" and st.desc[H_]["now"] == "60.0" and float(st.desc[F2_]["now"]) == -250.0, "the inputs show their values now")
for pid in (L_, H_, F2_):
    st.items[pid].setCheckState(0, Qt.CheckState.Checked)
rows = [{L_: "1000", H_: "60", F2_: "-250"}, {L_: "800", H_: "60", F2_: "-250"}, {L_: "1000", H_: "80", F2_: "-250"}, {L_: "1000", H_: "60", F2_: "-500"}]
st.data.rows = [dict(r) for r in rows]
st.rebuild_design()
st.data.out_checked = [U1, U2]
st.fill_outputs()
st.mark()
s_set = {n.id: P.cell(n.id, "setup")["stamp"] for n in (nB1, nB2)}
ch = W.sync_editors()
ok(nS.id in ch and P.status(nS.id, "solution") == wp.UPDATE, f"a study set up differently says update ({P.status(nS.id, 'solution')})")
ok("study/study.json" in nS.data["files"] and not any(k.startswith("study/") for n in (nB1, nB2) for k in n.data["files"]), "the block holds the study, the analyses do not")
ok(all(P.cell(n.id, "setup")["stamp"] == s_set[n.id] for n in (nB1, nB2)) and P.status(nS.id, "setup") == wp.OK, "and a study is not a change of the analyses")

done, failed = W.update_project(only={nS.id})
ok(done == 1 and not failed and P.status(nS.id, "solution") == wp.OK, f"Update ran the study ({done}, {failed})")
cs = st.data.cases
ok(len(cs) == 4 and all(c["status"] == "ok" for c in cs), f"four cases, all ok ({[c['status'] for c in cs]})")
r1, r2, r3, r4 = [(c["outputs"][U1], c["outputs"][U2]) for c in cs]
print("      outputs:", r1, r2, r3, r4)
ok(close(r1[0], tip(500, 1000, I_hat)) and close(r1[1], tip(250, 1000, I_rect)), "case 1: both beams as they are")
ok(close(r2[0], tip(500, 800, I_hat)) and close(r2[1], tip(250, 800, I_rect)), "case 2: the frame's length reaches BOTH beams")
ok(close(r3[0], tip(500, 1000, 30 * 80 ** 3 / 12)) and close(r3[1], r1[1], 1e-6), "case 3: the hat's depth reaches the beam that uses the hat, and only that one")
ok(close(r4[1], 2 * r1[1]) and close(r4[0], r1[0], 1e-6), "case 4: the second beam's force changes the second beam only")
ok(any("early" not in c for c in cs) and all(set(c["outputs"]) == {U1, U2} for c in cs), "both beams' outputs are in every row")
hdr = [lab for _k, lab in st.data.run_meta["outputs"]]
ok(len(hdr) == 2 and hdr[0].startswith(nB1.label + ":") and hdr[1].startswith(nB2.label + ":"), f"the columns say which analysis they come from ({hdr})")
ok(st.data.run_meta["params"][0][1].startswith("A:"), "and so do the inputs")
ok(all(P.status(nS.id, k) == wp.OK for k in ("setup", "solution", "results")), f"every cell of the study is ok ({P.statuses(nS.id)})")
ok("study/study.json" in nS.data["files"] and not any("/cases/" in k for k in nS.data["files"]), "the project holds the table and the outputs, not the full case results")
ok(W.update_project(only={nS.id})[0] == 0, "a second Update has nothing to do")
ok(close(w1.tab.result["umax"] if w1.tab.result else tip(500, 1000, I_hat), tip(500, 1000, I_hat)), "(the beams' own windows were not changed by the run)")

# ---- a part changes: the study says so, and runs again with it
hdoc2, _hid2 = profile_doc(30.0, 70.0, "Hat")
nH.data["doc"] = hdoc2
P.touch(nH.id, "geometry")
ok(P.status(nS.id, "setup") == wp.REFRESH and P.status(nS.id, "solution") == wp.UPDATE, f"the Hat changed: the study says refresh and update ({P.statuses(nS.id)})")
done, failed = W.update_project(only={nB1.id, nS.id})
ok(not failed and P.status(nS.id, "solution") == wp.OK, f"Update Project brings both up to date ({failed})")
st = W.editor_of(nS.id)
ok(st is not None and not any(W.editor_of(n.id) is None for n in (nB1, nB2)), "(the window of the study was opened again behind the others: refreshing the beam's profile closed it)")
ok(st.desc[H_]["now"] == "70.0", f"the input shows the Hat's new depth ({st.desc[H_]['now']})")
ok(len(st.data.cases) == 4 and close(st.data.cases[2]["outputs"][U1], tip(500, 1000, 30 * 80 ** 3 / 12)), "and the table and the outputs of the saved study are still there")

# ---- saved and opened again
f1 = os.path.join(T, "beams.opara")
qw.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f1, ""))
ok(W.save(True) and os.path.isfile(f1), "the project is saved")
raw = open(f1, encoding="utf-8").read()
ok("study/study.json" in raw and "/cases/" not in raw and T not in raw, "the file holds the study's table, no case files, no path of this computer")
shell.close_tab(shell.tabs.indexOf(W))
ok(not any(isinstance(shell.tabs.widget(i), study_tab.StudyTab) for i in range(shell.tabs.count())), "closing the workbench closed the study tab too")
W3 = shell.open_path(f1)
p3 = W3.project
nS3 = next(n for n in p3.nodes.values() if n.kind == "study")
ok(len(p3.incoming_all(nS3.id, "setup")) == 4 and shell.tabs.count() == 1, "four wires come back; no editor is open")
ok(p3.statuses(nS3.id)["setup"] == wp.OK and p3.statuses(nS3.id)["solution"] == wp.UPDATE, f"the Parameters are ok, the Study says update ({p3.statuses(nS3.id)})")
st3 = W3.open_cell(nS3.id, "results")
ok(isinstance(st3, study_tab.StudyTab) and len(st3.data.rows) == 4 and len(st3.data.cases) == 4, f"the study opens with its table and its outputs ({len(st3.data.rows)}, {len(st3.data.cases)})")
ok(sorted(st3.data.checked) == sorted([L_, H_, F2_]) and sorted(st3.data.out_checked) == sorted([U1, U2]), "the ticked inputs and outputs are as they were")
ok({W3.editor_of(n.id) is not None for n in p3.nodes.values() if n.kind == "beam"} == {True}, "the beams were opened behind it")
done, failed = W3.update_project(only={nS3.id})
ok(not failed and len(st3.data.cases) == 4 and all(c["status"] == "ok" for c in st3.data.cases), f"Update runs it again from the saved project ({failed})")
ok(close(st3.data.cases[1]["outputs"][U2], tip(250, 800, I_rect)), "with the same answers")

# ---- a wire taken away: its inputs and outputs go
b2 = next(n for n in p3.nodes.values() if n.title == "Plain beam")
b2k = next(k for k in p3.links if k.a == b2.id and k.b == nS3.id)
W3.scene.remove_link(b2k)
ok(p3.status(nS3.id, "setup") == wp.REFRESH, "taking a wire away asks for a refresh")
done, failed = W3.refresh_project(only={nS3.id})
st3.refresh_params()
ok(not any(i.startswith(b2.label + "/") for i in st3.desc) and not any(o["id"].startswith(b2.label + "/") for o in st3.outs), "the second beam's inputs and outputs are gone from the window")
ok(not st3.running() and st3.adapter.ready() is None, "and the study is still ready (one analysis is enough)")
b1 = next(n for n in p3.nodes.values() if n.title == "Hat beam")
W3.scene.clearSelection()
W3.scene.items_by_id[b1.id].setSelected(True)
W3.delete_selected()
ok(b1.id not in p3.nodes and W3.editor_of(nS3.id) is None and not any(isinstance(shell.tabs.widget(i), study_tab.StudyTab) for i in range(shell.tabs.count())), "removing the last analysis closes the study's tab")
ok(p3.status(nS3.id, "setup") == wp.INCOMPLETE, "and the study has no analysis any more: incomplete")

print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for f_ in FAILS:
    print("  -", f_)
sys.stdout.flush()
os._exit(1 if FAILS else 0)
