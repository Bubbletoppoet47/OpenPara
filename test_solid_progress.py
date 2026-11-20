"""The progress bar of the 3D FEA window (dev_addons/solid_fea/solid_progress.py): the time model and the tracker (with a fake clock), the stage reports of a real
mesh and solve (direct and iterative), Cancel, what the computer learns from a solve, and the bar in the window during a real threaded solve."""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile, time, json, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
import pm_model as pm, sk_tools as sk
import solid_progress as spg, solid_fem as fem, solid_model as sm, solid_tab


def ok(cond, msg=""):
    assert cond, msg
    print("ok:", msg)


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t
    def add(self, s): self.t += s


def tracker(clock, path=None):
    return spg.Tracker(history=spg.History(path=path or os.path.join(tempfile.mkdtemp(prefix="opara_hist_"), "solid_timing.json")), clock=clock)


# ---- 1. the time model against what was measured (Linux VM, solves of a 100x20x20 bar and an 80x50x30 block; seconds of the direct solve)
measured = [(9927, (100, 20, 20), 0.38), (25464, (100, 20, 20), 6.18), (60339, (100, 20, 20), 32.57),
            (15507, (80, 50, 30), 3.67), (31965, (80, 50, 30), 16.44), (63900, (80, 50, 30), 83.05)]
fixed, c0 = spg.STAGES["factor"]
for n, ext, t in measured:
    pred = fixed + c0 * spg.factor_cost(n, ext)
    ok(0.5 < pred / t < 2.0, f"the default estimate for {n:,} unknowns of a {ext[0]}x{ext[1]}x{ext[2]} part is {pred:.1f} s (measured {t} s)")
ok(spg.factor_cost(60000, (80, 50, 30)) > 1.5 * spg.factor_cost(60000, (200, 20, 20)), "a fat block costs more to factor than a long bar with as many unknowns")
ok(spg.factor_cost(6000) > 0 and spg.factor_cost(6000, (0, 0, 0)) > 0 and spg.factor_cost(0, (1, 1, 1)) > 0, "degenerate sizes do not break the cost")
ok(spg.DIRECT_LIMIT == fem.DIRECT_LIMIT, "the bar and the solver agree on where the direct solver stops")
ok(spg.fmt_time(0.4) == "0 s" and spg.fmt_time(75) == "1 min 15 s" and spg.fmt_time(3700) == "1 h 01 min" and spg.fmt_time(3.44, fine=True) == "3.4 s", "times are written plainly")
ok(spg.fmt_left(2) == "a few seconds" and spg.fmt_left(12) == "about 12 s" and spg.fmt_left(47) == "about 45 s" and spg.fmt_left(150) == "about 2.5 min" and spg.fmt_left(900) == "about 15 min",
   "the time left is rounded")

# ---- 2. one job through a fake clock: mesh 1 s, assemble 2 s, factor (estimated 30 s, takes 30 s), stress 1 s
ck = Clock(); t = tracker(ck)
size_f = (30.0 - fixed) / c0                                   # the factor stage is predicted to take exactly 30 s
t.expect([("mesh", 5000), ("assemble", 5000), ("factor", size_f), ("stress", 5000)])
f0, text0, _ = t.snapshot()
ok(f0 == 0.0 and text0.startswith("Starting"), "before the first stage: 0 % and 'Starting'")
seen = [f0]
def look(): f, tx, d = t.snapshot(); seen.append(f); return f, tx, d
t("meshing"); t.stage("mesh", 5000); ck.add(1.0); look()
t("assembling"); t.stage("assemble", 5000)
ref_asm = spg.STAGES["assemble"][0] + spg.STAGES["assemble"][1] * 5000       # the assembly takes just what the table says: this computer is as fast as the table
for i in range(1, 5):
    t.part(i / 4); ck.add(ref_asm / 4); look()
t("solving 15,000 unknowns"); t.stage("factor", size_f)
for _ in range(29):
    ck.add(1.0); f, tx, d = look()
ok(0.5 < f < spg.CEILING, f"near the end of the factor stage the bar is high but not full ({f:.3f})")
ok("Solving 15,000 unknowns" in tx and "(estimate)" in tx and "left" in tx, "the line says what is running, how long, and that the time left is an estimate: " + tx)
ck.add(1.0); look()                                            # the stage is exactly as long as estimated
ck.add(30.0); f, tx, d = look()                                # ... and now it overruns by 30 s
ok(f < spg.CEILING and "taking longer than estimated" in tx and d["over"] and d["left"] is None, "an overrun: the bar creeps, does not claim to be done, and says so: " + tx)
ck.add(60.0); f2, tx, d = look()
ok(f < f2 < spg.CEILING, f"a longer overrun still moves, still below the ceiling ({f:.3f} -> {f2:.3f})")
t("stresses"); t.stage("stress", 5000); ck.add(0.2); look()
t.finish(True)
f, tx, d = t.snapshot()
ok(f == 1.0 and tx.startswith("Done in") and d["left"] == 0, "finished: 100 % and 'Done in ...': " + tx)
ok(all(b >= a for a, b in zip(seen, seen[1:])), "the bar never goes back")
ok(max(seen) < 1.0, "and it never showed 100 % before the end")

# ---- 3. a stage that measures its own progress (the iterative solver) takes over from the estimate
ck = Clock(); t = tracker(ck)
t.expect([("ilu", 1e6), ("cg", 2e5), ("stress", 1e4)])
t.stage("ilu", 1e6); ck.add(20.0); t.stage("cg", 2e5)
t.part(0.5); ck.add(50.0)
f, tx, d = t.snapshot()
ok(abs(d["left"] - 50.0 - spg.STAGES["stress"][0] - spg.STAGES["stress"][1] * 1e4) < 2.0, f"half way after 50 s: about 50 s are left (plus the stresses): {d['left']:.1f}")
t.part(0.3)                                                    # a smaller fraction is ignored: progress does not run backwards
ck.add(0.0); ok(t.snapshot()[0] >= f, "a smaller report does not move the bar back")

# ---- 4. learning: a solve that took twice the estimate teaches the next one
path = os.path.join(tempfile.mkdtemp(prefix="opara_hist_"), "solid_timing.json")
ck = Clock(); t = tracker(ck, path)
size = 2.0e8
t.stage("factor", size); ck.add(2 * (fixed + c0 * size)); t.stage("stress", 100); t.finish(True)
ok(os.path.exists(path) and json.load(open(path))["c"]["factor"], "a finished solve is written to solid_timing.json")
t2 = tracker(Clock(), path)
t2.stage("factor", size)
want = 2 * (fixed + c0 * size)
ok(abs(t2.cur["pred"] - want) / want < 0.05, f"the next estimate has learned the speed of this computer: {t2.cur['pred']:.1f} s (took {want:.1f} s)")
bad = os.path.join(tempfile.mkdtemp(prefix="opara_hist_"), "solid_timing.json"); open(bad, "w").write("not json{")
ok(spg.History(path=bad).data == {}, "a damaged history file is ignored")
t3 = tracker(Clock(), os.path.join(tempfile.mkdtemp(prefix="opara_hist_"), "solid_timing.json"))
t3.stage("factor", size); t3.finish(False)
ok(not os.path.exists(t3.history.path), "a job that failed or was cancelled teaches nothing")
t3 = tracker(Clock(), os.path.join(tempfile.mkdtemp(prefix="opara_hist_"), "solid_timing.json")); ck3 = t3.clock
t3.stage("factor", size); ck3.add(0.1); t3.stage("stress", 10); t3.finish(True)
ok(t3.history.c("factor") is None, "a stage shorter than a quarter of a second says nothing about the speed")

# ---- 5. the speed of the assembly stage is the yardstick when there is no history yet
ck = Clock(); t = tracker(ck)
t.stage("assemble", 10000); ck.add(2.0 * (spg.STAGES["assemble"][0] + spg.STAGES["assemble"][1] * 10000)); t.stage("factor", 1e8)
ok(1.9 < t.speed < 2.1, f"this computer assembled twice as slowly as the table: speed {t.speed:.2f}")
ok(abs(t.cur["pred"] - (fixed + 2.0 * c0 * 1e8)) < 0.5, "so the first estimate of the factorisation is doubled too")

# ---- 6. cancelling
ck = Clock(); t = tracker(ck); t.stage("factor", 1e8); t.cancelling = True
ok("Cancelling" in t.snapshot()[1], "after Cancel the line says that it stops when the step that is running ends")

# ---- 8. the plan from the size of the model
g = {"volume": 40000.0, "bbox": [[0, 0, 0], [100, 20, 20]]}
p = spg.plan_for(g, {"h": 3.5})
ok([k for k, _ in p] == ["mesh", "assemble", "factor", "stress"], "mesh, assemble, factor, stress: " + str([k for k, _ in p]))
est_el = dict(p)["assemble"]
ok(abs(est_el - 5109) / 5109 < 0.25, f"the element count is estimated from volume and size: {est_el:.0f} (real mesh: 5109)")
ok([k for k, _ in spg.plan_for(g, {"h": 3.5}, mesh={"nodes": np.zeros((8693, 3)), "conn": np.zeros((5109, 10))})] == ["assemble", "factor", "stress"], "a cached mesh is not planned again")
ok([k for k, _ in spg.plan_for(g, {"h": 3.5}, solving=False)] == ["mesh"], "a mesh-only job has the mesh only")
ok([k for k, _ in spg.plan_for(g, {"h": 1.0})] == ["mesh", "assemble", "ilu", "cg", "stress"], "a model above the direct limit is planned as iterative")
ok(spg.plan_for(None, None) is not None and spg.plan_for({}, {}) is not None, "no data does not break the plan")

# ---- 9. the real thing: a bar, meshed and solved with a Tracker as `progress`
T = tempfile.mkdtemp(prefix="opara_solid_")
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (100, 10)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bar_p")) and w.import_file(part)
g = w.geom
face = lambda n: next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99)
w.select_faces([face([-1, 0, 0])]); w.add_support("fixed"); w.select_faces([face([1, 0, 0])]); w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.set_size("6"); w.inputs_changed(); w.read_inputs()
r = sm.resolve(g, w.setup)


class Rec(spg.Tracker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.events = []; self.parts = {}
    def stage(self, key, size=0.0):
        self.events.append((key, size)); self.parts[key] = []; super().stage(key, size)
    def part(self, f):
        if self.events: self.parts[self.events[-1][0]].append(f)
        super().part(f)


def run_with(tr, cache):
    return sm.run(g, r, cache, lambda: False, tr)
tr = Rec(history=spg.History(path=os.path.join(T, "t1.json")))
tr.expect(spg.plan_for(g, dict(r, h=r["h"] or sm.auto_h(g))))
cache = {}
res = run_with(tr, cache); tr.finish(True)
ok([k for k, _ in tr.events] == ["mesh", "assemble", "factor", "stress"], "a solve reports mesh, assemble, factor, stress: " + str([k for k, _ in tr.events]))
ok(all(sz > 0 for _k, sz in tr.events), "each with a size")
pa = tr.parts["assemble"]
ok(len(pa) >= 1 and all(b >= a for a, b in zip(pa, pa[1:])) and abs(pa[-1] - 1.0) < 1e-9, f"the assembly reports its progress up to 100 % ({len(pa)} reports)")
tr2 = Rec(history=spg.History(path=os.path.join(T, "t2.json")))
res2 = run_with(tr2, cache); tr2.finish(True)
ok([k for k, _ in tr2.events] == ["assemble", "factor", "stress"], "with the mesh cached there is no mesh stage")
ok(abs(res["umax"] - res2["umax"]) < 1e-12 and abs(res["umax"] - 0.005) / 0.005 < 0.02, "and the answer is the same and right")
res3 = sm.run(g, r, cache, lambda: False, lambda t: None)
ok(abs(res3["umax"] - res["umax"]) < 1e-12, "a plain function as `progress` still works (parametric studies)")

# ---- 10. the iterative solver: stages, real progress, the same answer, and Cancel inside it
old = fem.DIRECT_LIMIT
fem.DIRECT_LIMIT = 300
try:
    tr = Rec(history=spg.History(path=os.path.join(T, "t3.json")))
    res4 = run_with(tr, cache); tr.finish(True)
    ok([k for k, _ in tr.events] == ["assemble", "ilu", "cg", "stress"], "iterative: " + str([k for k, _ in tr.events]))
    pc = tr.parts["cg"]
    ok(len(pc) >= 1 and all(b >= a - 1e-12 for a, b in zip(pc, pc[1:])) and 0 <= min(pc) and max(pc) <= 1.0, f"the CG reports how far the residual has fallen ({len(pc)} reports, last {pc[-1] if pc else None})")
    ok(abs(res4["umax"] - res["umax"]) / res["umax"] < 1e-4, "the iterative answer agrees with the direct one")
    n_cancel = [0]
    def cancel_late():
        return n_cancel.__setitem__(0, n_cancel[0] + 1) or n_cancel[0] > 5
    got = None
    try:
        sm.run(g, r, cache, cancel_late, lambda t: None)
    except fem.Cancelled:
        got = True
    ok(got, "Cancel is noticed between iterations of the iterative solver")
finally:
    fem.DIRECT_LIMIT = old

# ---- 11. the bar in the window, during a real threaded solve
w2 = solid_tab.SolidWindow(threaded=True)
assert w2.create_project(os.path.join(T, "bar_q")) and w2.import_file(part)
g2 = w2.geom
face2 = lambda n: next(f["id"] for f in g2["faces"] if np.dot(f["normal"], n) > 0.99)
w2.select_faces([face2([-1, 0, 0])]); w2.add_support("fixed"); w2.select_faces([face2([1, 0, 0])]); w2.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w2.resize(1400, 900); w2.show(); app.processEvents()
ok(not w2.prog.isVisible(), "no bar while nothing runs")
w2.set_size("2.2"); w2.inputs_changed()                     # about 5 000 elements: a couple of seconds
vals, texts, vis = [], [], []
assert w2.run_solve()
t_start = time.time()
ok(w2.job is not None and w2.prog.isVisible() and not w2.b_solve.isEnabled() and w2.b_cancel.isEnabled(), "Solve pressed: the bar is shown under the button, Solve is off, Cancel is on")
while w2.job is not None and time.time() - t_start < 200:
    app.processEvents(); time.sleep(0.03)
    vals.append(w2.prog.bar.value()); texts.append(w2.prog.lbl.text()); vis.append(w2.prog.isVisible())
took = time.time() - t_start
ok(w2.result is not None and w2.job is None, f"the solve finished in {took:.1f} s")
ok(all(b >= a for a, b in zip(vals, vals[1:])) and max(vals) <= 1000, "the bar only moved forward")
ok(all(vis[:-1]) if len(vis) > 1 else True, "and was shown all the time")
ok(len(set(vals)) >= 3, f"and it moved ({len(set(vals))} different positions)")
ok(w2.prog.bar.value() == 1000 and w2.prog.lbl.text().startswith("Done in"), "at the end: full, 'Done in ...': " + w2.prog.lbl.text())
ok(any("so far" in x for x in texts), "while it ran the line said how long it had been going")
hist = json.load(open(os.path.join(UD, "solid_timing.json")))["c"]
ok("factor" in hist, "the solve was written to the timing history: " + ", ".join(sorted(hist)))
w2.prog.HIDE_MS = 50
w2.prog.hide()
# a second solve: the estimate made at the start is now about right
w2.set_size("2.2"); w2.inputs_changed()
w2.cache.clear()
tr_seen = []
assert w2.run_solve()
trk = w2.job.tracker
first = trk.snapshot()
t_start = time.time()
est0 = None
while w2.job is not None and time.time() - t_start < 200:
    app.processEvents(); time.sleep(0.03)
    fr, tx, dd = trk.snapshot()
    if est0 is None and dd["left"] and fr > 0.0 and time.time() - t_start > 0.5:
        est0 = dd["left"] + (time.time() - t_start)
took2 = time.time() - t_start
ok(est0 is None or 0.4 < est0 / took2 < 2.5, f"the estimate made half a second into the second solve ({est0}) is close to what it took ({took2:.1f} s)")

# ---- 12. Cancel
w2.set_size("2.0"); w2.inputs_changed(); w2.cache.clear()
assert w2.run_solve()
n_hist = len(json.load(open(os.path.join(UD, "solid_timing.json")))["c"].get("factor", []))
w2.cancel()
ok("Cancelling" in w2.prog.lbl.text(), "Cancel: the line says that it stops when the step that is running ends")
t_start = time.time()
while w2.job is not None and time.time() - t_start < 200:
    app.processEvents(); time.sleep(0.03)
ok(w2.job is None and not w2.prog.isVisible(), "a cancelled job hides the bar")
ok("Cancelled" in w2.status_lbl.text(), "and the status line says Cancelled: " + w2.status_lbl.text())
ok(len(json.load(open(os.path.join(UD, "solid_timing.json")))["c"].get("factor", [])) == n_hist, "and teaches nothing")
ok(w2.b_solve.isEnabled() and not w2.b_cancel.isEnabled(), "the buttons are back")

# ---- 13. a mesh-only job has the bar too
w2.set_size("3"); w2.inputs_changed(); w2.cache.clear()
assert w2.run_mesh()
ok(w2.prog.isVisible(), "Mesh: the bar is shown")
t_start = time.time()
while w2.job is not None and time.time() - t_start < 100:
    app.processEvents(); time.sleep(0.03)
ok(w2.mesh_q is not None and w2.prog.bar.value() == 1000, "and it ends full")
print("OK solid progress")
os._exit(0)
