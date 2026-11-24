"""What the 3D windows keep for a diagnostics report: the event log and the job log of solid_base.SolidBase, and the text builders of solid_diag (no physics here:
a bare window with the base's defaults).   python test_solid_diag.py"""
import faulthandler
faulthandler.dump_traceback_later(170, exit=True)
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm
import sk_tools as sk
import solid_base
import solid_diag as sd
import solid_fem as fem
import solid_progress

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


class Bare(solid_base.SolidBase):
    kind = "solid"
    label = "Bare window"

    def show_field(self, mesh_only=False):
        pass


T = tempfile.mkdtemp(prefix="opara_solid_diag_")
w = Bare(threaded=False)

# ------------------------------------------------------------------------------------------------------------------- the event log
ok(w.events == [] and w.job_log == [], "a new window has said nothing and run nothing")
w.say("first")
w.status("second")
w.say("")
ok([e[2] for e in w.events] == ["first", "second"] and all(e[1] == "say" for e in w.events), "say() and status() keep their text; an empty text is not kept")
ok(w.status_lbl.text() == "", "the status line shows the latest text, even an empty one")
ok(all(isinstance(e[0], float) and abs(e[0] - time.time()) < 60 for e in w.events), "each entry has the clock time it was said")
w.job_note("Meshing 10%")
w.job_note("Meshing 10%")
w.job_note("Meshing 20%")
ok([e[2] for e in w.events].count("Meshing 10%") == 1 and [e[2] for e in w.events][-2:] == ["Meshing 10%", "Meshing 20%"] and w.events[-1][1] == "note", "a job's note is kept once while it repeats")
ok(w.status_lbl.text() == "Meshing 20%", "and still goes to the status line")
for i in range(solid_base.EVENT_LIMIT + 50):
    w.log_event("say", f"m{i}")
ok(len(w.events) == solid_base.EVENT_LIMIT and w.events[-1][2] == f"m{solid_base.EVENT_LIMIT + 49}" and w.events[0][2] == "m50", "only the last EVENT_LIMIT messages are kept")
w.log_event("error", None)
ok(w.events[-1][2] == f"m{solid_base.EVENT_LIMIT + 49}", "None is not kept")

# ------------------------------------------------------------------------------------------------------------------- the job log
w.events.clear()


def work(progress, cancel):
    fem._stage(progress, "assemble", 1000.0)
    time.sleep(0.02)
    fem._stage(progress, "factor", 5e6)
    return 42


got = []
ok(w.run_job(work, got.append, "Testing", [("assemble", 1000.0), ("factor", 5e6)]) is True and got == [42], "a job runs and hands over its result")
ok(len(w.job_log) == 1 and w.job_log[0]["title"] == "Testing" and w.job_log[0]["ok"] is True and w.job_log[0]["seconds"] >= 0.02, "one entry: title, ok, seconds")
ok(w.last_tracker is not None, "the tracker of the last job is kept")
st = w.job_log[0]["stages"]
ok([s_[0] for s_ in st] == ["assemble", "factor"] and st[0][1] == 1000.0 and st[1][1] == 5e6 and all(s_[2] >= 0.0 for s_ in st), f"with its stages and their sizes: {st}")


def bad(progress, cancel):
    raise fem.FemError("the matrix is singular")


ok(w.run_job(bad, got.append, "Failing job", None) is True, "a job that fails is still handled")
ok(w.job_log[-1]["title"] == "Failing job" and w.job_log[-1]["ok"] is False, "and logged as failed")
ok(w.events[-1][1] == "error" and "singular" in w.events[-1][2], "its message is an error entry")


def crash(progress, cancel):
    raise ZeroDivisionError("division by zero")


w.run_job(crash, got.append, "Crashing job", None)
ok(w.job_log[-1]["title"] == "Crashing job" and w.job_log[-1]["ok"] is False and w.events[-1][1] == "error" and "Traceback" in w.events[-1][2] and "ZeroDivisionError" in w.events[-1][2],
   "an unexpected exception is logged with its whole traceback")
ok(w.status_lbl.text().endswith("division by zero"), "while the status line has its last line only")
for i in range(solid_base.JOB_LIMIT + 5):
    w.run_job(work, lambda r: None, f"job {i}", None)
ok(len(w.job_log) == solid_base.JOB_LIMIT and w.job_log[-1]["title"] == f"job {solid_base.JOB_LIMIT + 4}", "only the last JOB_LIMIT jobs are kept")

# a threaded window logs the same
wt = Bare(threaded=True)
wt.prog = solid_progress.make_row()                 # (a window with a Results section has it; the bare one has none)
res = []
wt.run_job(work, res.append, "Threaded", None)
t0 = time.time()
while wt.job is not None and wt.job.isRunning() and time.time() - t0 < 30:
    app.processEvents()
    time.sleep(0.01)
for _ in range(50):
    app.processEvents()
    time.sleep(0.01)
ok(res == [42] and [j["title"] for j in wt.job_log] == ["Threaded"] and wt.job_log[0]["ok"] and len(wt.job_log[0]["stages"]) == 2, f"a threaded job is logged with its stages: {wt.job_log}")
wt.close()

# ------------------------------------------------------------------------------------------------------------------- the builders
L = sd.program_lines("TITLE LINE")
ok(L[0] == "TITLE LINE" and any(x.startswith("python ") for x in L) and any(x.startswith("packages: ") for x in L) and any(x.startswith("processor: ") for x in L), "the program lines: title, python, processor, packages")
ok(any("numpy" in x and "scipy" in x and "gmsh" in x and "PyQt6" in x for x in L), "the packages include the numerical ones and Qt")
tot, av = sd.memory_bytes()
ok((tot is None) == (av is None) and (tot is None or tot >= av > 0), f"memory: total {sd.gb(tot)}, free {sd.gb(av)}")
ok(sd.gb(None) == "unknown" and sd.gb(2 ** 31) == "2.0 GB", "memory is printed in GB, or 'unknown'")
ok(sd._version_of("a_package_that_does_not_exist").startswith("NOT AVAILABLE"), "a missing package is a line saying so, not an error")
ok(sd.geometry_lines(w) == ["Nothing imported yet."], "no part: 'Nothing imported yet.'")
ok(sd.mesh_lines(None) == ["No mesh yet."], "no mesh: 'No mesh yet.'")
ok(sd.jobs_lines([]) == ["No job has run in this window yet."] and sd.events_lines([]) == ["Nothing was said."], "nothing run, nothing said")

d = pm.Document()
d.params = {}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
d.rebuild()
m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (100, 10))
sk.solve_model(m)
d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10"))
d.rebuild()
part = os.path.join(T, "bar.gpd")
open(part, "w").write(d.to_json())
ok(w.create_project(os.path.join(T, "bar")) and w.import_file(part), "a project with a bar")
G = sd.geometry_lines(w)
ok(any("size 100 x 10 x 10 mm" in x for x in G) and any("volume 10000" in x for x in G), f"geometry: size and volume: {G[2]}")
ok(any(x.startswith("faces 6") and "vertices 8" in x for x in G) and any("plane 6" in x for x in G), "geometry: faces and their kinds")
ok(any(w.path in x for x in G), "geometry: the project folder")
w.run_mesh()
M = sd.mesh_lines(w.mesh_q, 4.0, {"order": 2, "face_sizes": [1, 2], "type": "tets"})
ok(M[0].endswith("quadratic elements, element size asked for 4 mm") and "tetrahedra" in M[0], f"mesh: counts and size: {M[0]}")
ok(any(x.startswith("mesh options:") and "order=2" in x and "face_sizes" not in x for x in M) and any("sizes on single faces: 2" in x for x in M), "mesh: options (the long lists only counted)")
ok(any(x.startswith("edge length mm:") for x in M) and any("radius ratio" in x for x in M) and any("inverted elements 0" in x for x in M), "mesh: edge lengths, radius ratio, inverted elements")
q = dict(w.mesh_q)
q.pop("quality", None)
ok(any("radius ratio" in x for x in sd.mesh_lines(q)), "the quality is measured when the mesh does not carry it")

J = sd.jobs_lines([{"title": "Solve", "ok": True, "seconds": 2.5, "stages": [("assemble", 100.0, 0.1)] + [("factor", 2e6, s_) for s_ in (0.2, 0.9, 0.4, 0.5)]},
                   {"title": "Mesh", "ok": False, "seconds": 0.2, "stages": []}, {"title": "Twice", "ok": True, "seconds": 1.0, "stages": [("solve", 10.0, 0.3), ("solve", 30.0, 0.1)]}])
ok(J[0] == "Solve: finished in 2.50 s" and "Mesh: FAILED or cancelled in 0.20 s" in J, "jobs: title, finished or failed, time")
ok(sum(1 for x in J if "stage factor" in x) == 1 and any("4 times" in x and "total 2.000 s" in x and "mean 0.500 s" in x and "longest 0.900 s" in x for x in J), "a stage repeated 4 times is one line: count, total, mean, longest")
ok(sum(1 for x in J if "stage solve" in x) == 1 and any("2 times" in x and "total 0.400 s" in x and "mean 0.200 s" in x and "longest 0.300 s" in x and " last " in x for x in J), "a stage that ran twice (with two sizes) is one line too: 'last' size")
ok(sum(1 for x in J if "stage assemble" in x) == 1 and not any("assemble" in x and "times" in x for x in J), "a stage that ran once is a plain line")

E = sd.events_lines([(0.0, "say", "hello"), (1.0, "error", "Traceback (most recent call last):\n  File x\nValueError: bad")])
ok(E[0].endswith("SAY   hello") and E[1].endswith("ERROR Traceback (most recent call last):") and E[2].strip() == "File x" and E[3].strip() == "ValueError: bad", "events: one line per message, an error's lines indented under it")
many = [(0.0, "say", f"m{i}") for i in range(300)]
ok(len(sd.events_lines(many)) == 200 and sd.events_lines(many)[-1].endswith("m299"), "events: the last 200")
ok(sd.section("A", ["x", "y"]) == ["", "== A ==", "x", "y"], "a section is a blank line, a heading and its lines")

# ------------------------------------------------------------------------------------------------------------------- the file
p = sd.write_report(T, "line one")
ok(p == os.path.join(T, "diagnostics.txt") and open(p, encoding="utf-8").read() == "line one\n", "the report is written into the folder, ending in a newline")
p = sd.write_report(T, "naïve ΔT °C\n")
ok(open(p, encoding="utf-8").read() == "naïve ΔT °C\n", "any text (degree signs, Greek letters) is written in UTF-8, one newline at the end")
ok(not os.path.exists(p + ".tmp"), "no temporary file is left")
ok(sd.write_report(None, "x") is None and sd.write_report("", "x") is None and sd.write_report(os.path.join(T, "missing"), "x") is None, "no folder (or a missing one): None")
w.close()

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("OK solid diag")
