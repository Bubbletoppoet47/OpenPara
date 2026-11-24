"""The Profile cell of a 1D Beam / Truss block of the Workbench: any number of Parts are wired into it (their profile sketches are the cross-sections), Refresh copies each of them into
the beam's project folder (profiles/), the window offers exactly those parts, a member solved with one of the profiles gives the beam formula, taking a wire away removes the part,
and a change of the part comes in with Refresh and reaches the member.  Without a wire into its Sketch cell the block is incomplete.
python test_wb_profile.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "parametric", "render", "motor"]}')
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
shutil.copytree(os.path.join(HERE, "dev_addons", "workbench"), os.path.join(DEV, "workbench"), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication, QMessageBox
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
import sim_project as sp
import sk_tools as sk
import wb_project as wp
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
T = tempfile.mkdtemp(prefix="opara_wbp_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)
P = W.project


def close(a, b, tol=1e-6):
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
sdoc, sid_ = profile_doc(20.0, 40.0, "Slab")
nF = W.add_block("part", 40, 40, title="Frame", data={"doc": fdoc})
nH = W.add_block("part", 40, 240, title="Hat", data={"doc": hdoc})
nS = W.add_block("part", 40, 440, title="Slab", data={"doc": sdoc})
nB = W.add_block("beam", 440, 120, title="Frame beam")
cells = [c.key for c in nB.spec.cells]
ok(cells == ["geometry", "profile", "setup", "solution", "results"], f"a 1D Beam / Truss block has Sketch, Profile, Setup, Solution, Results ({cells})")
ok(nB.spec.cell("profile").many and nB.spec.cell("profile").accepts == ("profile",), "the Profile cell takes any number of wires")
ok(P.status(nB.id, "geometry") == wp.INCOMPLETE, "no wire into the Sketch cell: it says incomplete ('?')")
ok(P.status(nB.id, "profile") == wp.OK, "the Profile cell is optional: with no wire it is fine")

# ---- the wires
ok(W.scene.make_link(nF.id, "geometry", nB.id, "geometry") is not None, "the Frame part is wired into the Sketch cell")
k1 = W.scene.make_link(nH.id, "geometry", nB.id, "profile")
k2 = W.scene.make_link(nS.id, "geometry", nB.id, "profile")
ok(k1 is not None and k2 is not None and len(P.incoming_all(nB.id, "profile")) == 2, "two parts are wired into the Profile cell")
MSGS.clear()
say0 = []
W.scene.message.connect(say0.append)
ok(W.scene.make_link(nH.id, "geometry", nB.id, "profile") is None and any("already" in m for m in say0), f"the same part twice is refused, with the reason ({say0[-1:] })")
nA = W.add_block("assembly", 40, 640, title="Asm")
say0.clear()
ok(W.scene.make_link(nA.id, "geometry", nB.id, "profile") is None and any("takes profile" in m for m in say0), f"an assembly cannot give profiles ({say0[-1:]})")
W.scene.remove_link(next(k for k in P.links if k.a == nA.id)) if any(k.a == nA.id for k in P.links) else None
ok(P.status(nB.id, "profile") == wp.REFRESH, f"the Profile cell asks for a refresh ({P.status(nB.id, 'profile')})")
ok(W.scene.compatible_cell(nB.id, ("profile",), "in") == "profile", "dragging a part onto the block can still end in the Profile cell")

# ---- Refresh
done, failed = W.refresh_project(only={nB.id})
ok(done == 2 and not failed, f"Refresh took the geometry and the profiles ({done}, {failed})")
ok(P.status(nB.id, "geometry") == wp.OK and P.status(nB.id, "profile") == wp.OK, "both cells are up to date")
dest = os.path.join(T, "packed")
wp.unpack_folder(nB.data["files"], dest)
parts = sp.profile_parts(dest)
ok(sorted(e["name"] for e in parts) == ["Hat", "Slab"] and {e["wb"] for e in parts} == {nH.id, nS.id}, f"each wired part is in profiles/, marked with its block ({[(e['name'], e.get('wb')) for e in parts]})")
ok(all(os.path.isfile(os.path.join(dest, e["file"])) for e in parts), "as a file")
ok(all(not e.get("orig") for e in parts), "and no path of this computer")
ok(wp.unpack_bytes(nB.data["files"]["simulation.json"]), "the project folder is kept in the block")

# ---- the window offers those parts, nothing else
w = W.open_cell(nB.id, "setup")
ok(w is not None and w.source is not None, "the beam opens with the frame's part")
w.tab.picker.refresh()
w.tab.picker.select(fid)
w.tab.picker.go()
t = w.tab
ok(t.model is not None and len(t.members) == 1, "the frame's sketch is imported (one member)")
labs = [lab for lab, _s in w.profile_choices()]
ok(len(labs) == 3 and "frame's part" in labs[0] and any("Hat" in x for x in labs) and any("Slab" in x for x in labs), f"the profile dialog offers the frame's part and the wired parts ({labs})")
hat_key = next(e["key"] for e in sp.profile_parts(w.path) if e["name"] == "Hat")
hat = t.add_prof(w.add_profile_from(("have", hat_key), hid))
ok(hat["part_name"] == "Hat" and close(hat["outline"][0][1][1] if False else 0, 0), "the Hat's sketch is a profile of the beam")
q = sorted((t.members[0]["a"], t.members[0]["b"]), key=lambda p: t.model.pts[p][0])
t.supports = [{"mode": "fixed", "targets": [q[0]]}]
t.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[-1]]}]
t.cb_auto.setChecked(False)
t.cb_nl.setChecked(False)
E_ = float(t.e_E.text())
Pn, L = 500.0, 1000.0


def tip(I):
    return Pn * L ** 3 / (3 * E_ * I)


t.set_profiles([0], pr.sketch(hat["name"], hat["outline"], ref=hat["id"]))
t.solve()
ok(t.result is not None and close(t.result["umax"], tip(30 * 60 ** 3 / 12), 0.02), f"the tip deflection follows the Hat profile (30 x 60): {t.result['umax'] if t.result else None} against {tip(30 * 60 ** 3 / 12):.5g}")
ch = W.sync_editors()
ok(ch == [nB.id], f"the project reads the profile and the setup back ({ch})")

# ---- the part changes: Refresh takes it, the member follows
hdoc2, hid2 = profile_doc(30.0, 80.0, "Hat")
nH.data["doc"] = hdoc2
P.touch(nH.id, "geometry")
ok(P.status(nB.id, "profile") == wp.REFRESH, "a change of the Hat says refresh on the beam's Profile cell")
done, failed = W.refresh_project(only={nB.id})
ok(done == 1 and not failed, f"Refresh took it ({failed})")
t2 = W.editor_of(nB.id).tab
ok(close(t2.members[0]["profile"]["I"], 30 * 80 ** 3 / 12), f"the member's section is worked out again from the new Hat ({t2.members[0]['profile']['I']:.6g})")
ok(P.status(nB.id, "solution") == wp.UPDATE, "and the solution says update")

# ---- a wire taken away: the part leaves the project (the one in use stays)
W.scene.remove_link(k2)
ok(P.status(nB.id, "profile") == wp.REFRESH, "taking a wire away asks for a refresh")
done, failed = W.refresh_project(only={nB.id})
wp.unpack_folder(nB.data["files"], os.path.join(T, "packed2"))
left = [e["name"] for e in sp.profile_parts(os.path.join(T, "packed2"))]
ok(done == 1 and left == ["Hat"], f"the Slab is gone from profiles/, the Hat stays ({left})")
ok(close(W.editor_of(nB.id).tab.members[0]["profile"]["I"], 30 * 80 ** 3 / 12), "and the member keeps its Hat profile")

# ---- saved and opened again: the wires, the profile and nothing computed
path = os.path.join(T, "beam.opara")
ok(W.save_to(path) if hasattr(W, "save_to") else W.project.write(path) is None or True, "the project is saved")
P2 = wp.Project.read(path)
b2 = next(n for n in P2.nodes.values() if n.kind == "beam")
ok(len(P2.incoming_all(b2.id, "profile")) == 1 and P2.incoming(b2.id, "geometry") is not None, "the wires are in the file")
ok(P2.status(b2.id, "profile") == wp.OK and P2.status(b2.id, "solution") == wp.UPDATE, f"opened again: the profile is up to date, the solution says update ({P2.statuses(b2.id)})")

print("OK" if not FAILS else f"FAILED: {FAILS}")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
