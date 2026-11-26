"""Model testing with a DISTANCE-ONLY model: the "Boxes from" slot, the made-up session of the Analyse tab's example, a real .opdm file (the formula, with the constant worked out by hand),
a detector that is a made-up one (the real one needs torch), the trust question for a model that holds a pickle, and the runs side by side (the table, the chart numbers, the CSV).
python test_wb_testing_boxes.py"""
import atexit
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import os
import shutil
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "simulation", "parametric", "render", "motor"]}')      # (the add-ons are not installed: that would download their packages; their tab kinds are put in below, from their own manifests)
os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = tempfile.mkdtemp(prefix="opara_dev_")
for n in ("workbench",):
    shutil.copytree(os.path.join(HERE, "dev_addons", n), os.path.join(DEV, n), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
sys.path.insert(0, HERE)
ANN = os.path.join(HERE, "addons_src", "annotator", "app")
TRN = os.path.join(HERE, "addons_src", "trainer")
sys.path.insert(0, ANN)
sys.path.insert(0, os.path.dirname(ANN))
sys.path.insert(0, TRN)

T = tempfile.mkdtemp(prefix="opara_wbtr_")
atexit.register(shutil.rmtree, UD, True)
atexit.register(shutil.rmtree, DEV, True)
atexit.register(shutil.rmtree, T, True)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
MSGS = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
SAVE = {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
ASK = {"name": ("", False)}
QInputDialog.getText = staticmethod(lambda *a, **k: ASK["name"])
import numpy as np
import cv2
import qtk
import share_zip as sz
sz.CONFIG_PATH = os.path.join(T, "annotator_cfg.json")
json.dump({"models_prompt_done": True, "name": "Tester", "id": "tester1"}, open(sz.CONFIG_PATH, "w"))
for _n in ("info", "warn", "error"):
    setattr(qtk, _n, lambda parent, title, text, _n=_n: None)
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import addons
import ext
addons.startup()
addons.register_extensions(ext)
_ANN_SPEC = dict(json.load(open(os.path.join(HERE, "addons_src", "annotator", "addon.json")))["tabs"][0], aid="annotator")
_TR_SPEC = dict(json.load(open(os.path.join(TRN, "addon.json")))["tabs"][0], aid="trainer")
_tab_kinds = addons.tab_kinds
addons.tab_kinds = lambda: {**_tab_kinds(), "annotator": _ANN_SPEC, "trainer": _TR_SPEC}

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


import annotator_core as ac
import model_library as ml
FAKE = os.path.join(T, "fake_train.py")
open(FAKE, "w").write(f'''import os, sys, time
sys.path.insert(0, {TRN!r})
import job_common as jc
job = jc.load_job()
print("fake training", job["classes"], job["counts"], flush=True)
for e in range(2):
    print("epoch", e, flush=True); time.sleep(0.1)
best = os.path.join(job["run_dir"], "best.pt"); open(best, "wb").write(b"weights" * 40)
sys.exit(jc.finish(job, best, {{"epoch": 1, "total_epochs": 2, "map50": 0.6, "map50_95": 0.4}}))
''')
ext.add_model_trainer("fake", label="Fake model", script=FAKE, sizes=("n", "s"), default_size="n")
import gpd_app
import trainer_core as tc
import trainer_tab as tt
import wb_nodes
import wb_project as wp
import wb_tab
import wb_tools  # noqa: F401 (registers the adapters)
import wb_models
import wb_trainer
import wb_models_block
import wb_models_tab
import wb_testing
import wb_testing_tab
import annotator_analysis as aa
tt.TrainerTab.check_env = lambda self: None                  # (looking for Pythons runs programs: not here)
app = QApplication([])
shell = gpd_app.AppShell()
shell.show()
for fn in ext.hooks("shell.start"):
    fn(shell)
W = shell.tabs.widget(0)
P = W.project


def pump(n=10, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def stamp(nid, key="document"):
    return P.cell(nid, key)["stamp"]


def st(nid, key):
    return P.status(nid, key)





INFO = []
for _n in ("info", "warn", "error"):
    setattr(qtk, _n, lambda parent, title, text, _n=_n: INFO.append((_n, title, text)))


def model_file(name, size=3000):
    p = os.path.join(T, name)
    open(p, "wb").write(os.urandom(size))
    return p


def wait_run(w):
    for _ in range(400):
        app.processEvents()
        if not w.analyse.running:
            pump(3)
            return
        time.sleep(0.05)
    raise AssertionError("the analysis did not finish")


def fake_predict(label):
    return aa.demo_predictor, True

import dist_data as dd
import dist_models as dm
import wb_testing_boxes as tb
import wb_testing_compare as tcmp
from PyQt6.QtCore import QPointF

ASKED = []
S = 640
SESS = aa.make_demo_session(os.path.join(T, "sessions", "20261125_184611"))
session = aa.open_session(SESS)
FRAMES = len(session)


def pinhole(k, names=("person",), path=None):
    """The formula with its constant set (k metres x pixels): d = k / height of the box in the letterboxed picture."""
    m = dm.make("pinhole", S, len(names), list(names))
    m.k = [float(x) for x in (k if isinstance(k, (list, tuple)) else [k] * len(names))]
    m.k_all = float(np.mean(m.k))
    if path:
        m.save(path, scores={"dist_median_err": 0.06})
    return m


# ============================================================================================================================ the pieces
print("--- the boxes of a detector, the distance of a model")
m840 = pinhole(840.0)
slot = lambda s: aa.DEMO_SLOTS[s]                                      # noqa: E731
got = m840.predict_m_orig(np.array([slot("A"), slot("B"), slot("C")], float), aa.DEMO_W, aa.DEMO_H)
ok(np.allclose(got, [840 / 280, 840 / 200, 840 / 120]), f"the formula, by hand: boxes 140, 100 and 60 pixels high in a 320 x 240 picture (280, 200, 120 letterboxed): {np.round(got, 3).tolist()} m")
det = tb.DetectorBoxes(aa.demo_predictor)
comp = tb.DistanceOnBoxes(det, m840)
f0 = comp(session.frames[0].image)
ok([(c, conf) for c, conf, *_r in f0] == [("person", 0.93), ("person", 0.91)] and [tuple(r[2:6]) for r in f0] == [slot("A"), slot("B")], "the boxes, classes and confidences are the detector's")
ok(abs(f0[0][6] - 3.0) < 1e-9 and abs(f0[1][6] - 4.2) < 1e-9, f"the distances are the model's, not the detector's ({[round(r[6], 3) for r in f0]}; the detector said 3.0 and 6.2)")
ok(comp(session.frames[3].image) == [] and comp(session.frames[4].image)[0][6] is not None, "a picture without boxes gives none; a box the detector gave no distance for gets the model's")
for fr in session.frames:
    comp(fr.image)
ok(det.calls == FRAMES, f"the detector ran once per picture ({det.calls} of {FRAMES}), however often they were asked for")
comp2 = tb.DistanceOnBoxes(det, pinhole(700.0))
for fr in session.frames:
    comp2(fr.image)
ok(det.calls == FRAMES, "and a second distance model on the same boxes does not run it again")

two = pinhole([840.0, 420.0], ("person", "chair"))
mix = tb.DistanceOnBoxes(tb.DetectorBoxes(lambda p: [("chair", 0.9, *slot("A"), None), ("dog", 0.9, *slot("B"), None), ("person", 0.9, *slot("A"), 9.9)]), two)
r = mix(session.frames[0].image)
ok(abs(r[0][6] - 1.5) < 1e-9 and r[1][6] is None and abs(r[2][6] - 3.0) < 1e-9, f"with two classes the class name picks the constant, and a class the model was not trained on has no distance ({[None if x[6] is None else round(x[6], 2) for x in r]})")
ok(tb.class_numbers(two, ["person", "dog", "chair"]) == [0, None, 1] and tb.class_numbers(m840, ["anything"]) == [0], "(class numbers)")

print("--- the numbers of a run")
an = aa.run(session, comp, model="formula k=840")
st0 = aa.Settings(0.85, 0.10, "closest")
s0 = tb.summarise(an, st0)
ok((s0["boxes"], s0["judged"], s0["passed"], s0["no_lidar"], s0["no_distance"]) == (6, 5, 3, 1, 0), f"worked out by hand: 6 boxes, 5 judged, 3 pass, one has no LiDAR ({[s0[k] for k in ('boxes', 'judged', 'passed', 'no_lidar', 'no_distance')]})")
ok(abs(s0["pass_pct"] - 60.0) < 1e-9 and abs(s0["median_off_pct"] - 0.0) < 1e-9 and abs(s0["mean_abs_m"] - 0.72) < 1e-9, f"60 % pass, median off {s0['median_off_pct']:.1f} %, mean {s0['mean_abs_m']:.2f} m")
ok([(b[1], b[2]) for b in s0["bands"] if b[1]] == [(3, 3), (2, 0)], f"by distance: three at 2-4 m all pass, two at 6-8 m none ({[(b[0], b[1], b[2]) for b in s0['bands'] if b[1]]})")
s1 = tb.summarise(an, aa.Settings(0.85, 0.50, "closest"))
ok(s1["passed"] == 5 and s1["pass_pct"] == 100.0, "a wider tolerance passes the 43 % miss")
empty = tb.summarise(aa.Analysis(session), st0)
ok(empty["pass_pct"] is None and not tb.usable_for(empty), "a run with nothing in it says nothing")
csvp = tb.write_comparison(os.path.join(T, "cmp.csv"), [("a", s0), ("b", s1)], st0)
rows_csv = open(csvp).read().splitlines()
ok(rows_csv[3].split(",") == tb.COLUMNS and rows_csv[4].startswith("a,6,6,5,3,60.0") and any(l.startswith("a,2-4 m,3,3,100.0") for l in rows_csv), f"the comparison CSV: settings, one row per model, one row per model and band ({rows_csv[4]})")

print("--- a model that holds a pickle")
rng = np.random.default_rng(3)
n = 200
d = np.exp(rng.uniform(np.log(2.5), np.log(20.0), n))
h = 420.0 * 1.7 / d
cx = rng.uniform(100, 540, n)
y2 = 300 + 420 * 1.2 / d
xyxy = np.stack([cx - 0.2 * h, y2 - h, cx + 0.2 * h, y2], 1)
bx = dd.Boxes(dd.geometry(xyxy, S), np.zeros(n, int), d * np.exp(rng.normal(0, 0.05, n)), xyxy, [f"gim_rec{k % 6:02d}_{k:06d}" for k in range(n)], 1, ["person"], S)
boost = dm.make("boosting", S, 1, ["person"], seed=0).fit(bx, folds=3, learning_rates=(0.1,), depths=(2,), max_iter=30)
bp = boost.save(os.path.join(T, "boost.opdm"), scores={"dist_median_err": 0.07})
fp = pinhole(840.0, path=os.path.join(T, "pin840.opdm"))
ok(tb.needs_trust(bp) and not tb.needs_trust(os.path.join(T, "pin840.opdm")) and not tb.needs_trust(os.path.join(T, "nothing.opdm")), "the gradient boosting file is known to hold a pickle (read without opening it); the formula's file does not")
try:
    tb.load_model(bp)
    ok(False, "an untrusted pickle must not be opened")
except dm.UntrustedModel:
    ok(True, "it is not opened unless it is trusted")
ok(tb.load_model(bp, True).family == "boosting" and tb.load_model(os.path.join(T, "pin840.opdm")).family == "pinhole", "and is when it is")

# ============================================================================================================================ in the window
print("--- the window")
nM = W.add_block("model_test", 780, 60, title="Distance check")
w = W.open_cell(nM.id, "models")
A = w.analyse
det_pt = model_file("Detector.pt", 2500)
w.take_paths([det_pt, os.path.join(T, "pin840.opdm"), bp])
pinhole(700.0, path=os.path.join(T, "pin700.opdm"))
w.take_paths([os.path.join(T, "pin700.opdm")])
labels = [A.panel.model_combo.itemText(i) for i in range(A.panel.model_combo.count())]
dist_labels = [lab for lab in labels if lab.endswith("(distance only)")]
ok(len(labels) == 4 and len(dist_labels) == 3 and w._det_labels == ["Detector"], f"the list has the detector and three distance-only models ({labels})")
ok("3 distance only" in w.bar_lbl.text() and [w.bf_combo.itemText(i) for i in range(w.bf_combo.count())] == ["Detector"] and w._bf == "Detector", f"'Boxes from' offers only what finds boxes ({w.bar_lbl.text()})")
A.panel.model_combo.setCurrentText("Detector")
pump(3)
ok(not w.bf_combo.isEnabled() and "its own boxes" in w.bf_note.text(), "a model that finds its own boxes does not use the slot")
l840 = next(lab for lab in dist_labels if lab.startswith("pin840"))
l700 = next(lab for lab in dist_labels if lab.startswith("pin700"))
lbo = next(lab for lab in dist_labels if lab.startswith("boost"))
A.panel.model_combo.setCurrentText(l840)
pump(3)
ok(w.bf_combo.isEnabled() and "distances only" in w.bf_note.text(), f"a distance-only model does ({w.bf_note.text()[:60]})")
ok(w._ai_entries.get(l840)["kind"] == "distance" and w._ai_entries.get(l840)["path"].endswith(".opdm"), "its file is written out when asked for")

w.make_detector = lambda label: aa.demo_predictor                       # (the real detector needs torch; this one is the Analyse tab's made-up one)
A.open_session(SESS)
wait_run(w)
A.run()
wait_run(w)
ok(A.analysis is not None and A.analysis.analysed == FRAMES and A.analysis.finished, f"Run analysis runs the distance model on the boxes of the detector ({A.analysis.analysed} frames)")
sw = tb.summarise(A.analysis, A.settings)
ok((A.settings.conf, A.settings.tol) == (0.85, 0.10) and (sw["judged"], sw["passed"]) == (5, 3), f"the numbers are those worked out by hand ({sw['judged']} judged, {sw['passed']} pass at conf {A.settings.conf})")
ok((l840, "Detector") in w.kept and w.kept[(l840, "Detector")]["name"] == f"{l840} (boxes: Detector)", "the run is kept under the model and the detector")
ok(w._detectors["Detector"].calls == FRAMES, "the detector ran once over the session")
ok(not w.models_buttons["compare"].isChecked(), "one run is nothing to compare: the pane stays closed")

print("--- the trust question")
ASKED.clear()
A.panel.model_combo.setCurrentText(lbo)
QMessageBox.question = staticmethod(lambda *a, **k: ASKED.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.No)
INFO.clear()
A.run()
wait_run(w)
ok(len(ASKED) == 1 and "pickle" in ASKED[0] and lbo.replace(" (distance only)", "") in ASKED[0], f"a model that holds a pickle is asked about first ({ASKED[0][:70] if ASKED else ''})")
ok(any("was not opened" in t[2] for t in INFO) and (lbo, "Detector") not in w.kept and not w._trusted, "answering No: nothing is opened, nothing is run, and nothing is kept")
QMessageBox.question = staticmethod(lambda *a, **k: ASKED.append(a[2] if len(a) > 2 else "") or QMessageBox.StandardButton.Yes)
ASKED.clear()
A.run()
wait_run(w)
ok(len(ASKED) == 1 and (lbo, "Detector") in w.kept and len(w._trusted) == 1, f"Yes: it runs, and is remembered for as long as the window is open ({len(ASKED)} question)")
A.run()
wait_run(w)
ok(len(ASKED) == 1, "and is not asked again")
ok(w.models_buttons["compare"].isChecked() and w.compare.isVisibleTo(w), "two runs: the pane opens by itself")

print("--- side by side")
w._poll()
tbl = w.compare.table
ok(tbl.rowCount() == 2, f"a row for each run ({tbl.rowCount()})")
names = [tbl.item(i, 0).text() for i in range(tbl.rowCount())]
ok(names[0].startswith("pin840") and "(boxes: Detector)" in names[0] and names[1].startswith("boost"), f"in the order they were made ({names})")
ok(tbl.item(0, 1).text() == "5" and tbl.item(0, 2).text() == "60 %" and tbl.item(0, 3).text() == "0.0 %" and tbl.item(0, 4).text() == "0.72 m", f"the first row is the hand-worked one ({[tbl.item(0, c).text() for c in range(5)]})")
A.panel.model_combo.setCurrentText(l700)
A.run()
wait_run(w)
w._poll()
ok(tbl.rowCount() == 3 and tbl.item(2, 2).text() == "0 %", f"a third run joins it: a formula that is 17 % short fails every box at 10 % ({tbl.item(2, 2).text()})")
ok([s["slot"] for s in w.compare.chart.series] == [0, 1, 2] and len(set(tcmp.SHAPES[:3])) == 3, "each run has its own colour and shape on the chart")
pts = {s["name"].split(" (distance")[0]: s["points"] for s in w.compare.chart.series}
k840 = next(k for k in pts if k.startswith("pin840"))
ok(pts[k840] == [(1, 100.0, 3, 3), (3, 0.0, 2, 0)], f"the chart's points are the pass share by distance band ({pts[k840]})")
tip = w.compare.chart.text_at(QPointF(*w.compare.chart._xy(1, 100.0)))
ok("3 of 3 pass" in tip and "only a few boxes" in tip, f"hovering a marker says what is behind it ({tip.splitlines()[-2] if tip else ''})")
A.panel.tol_spin.setValue(50)
pump(3)
w._poll()
vals = [tbl.item(i, 2).text() for i in range(3)]
ok(vals[0] == "100 %" and tbl.horizontalHeaderItem(2).text() == "Pass (±50 %)", f"the tolerance on the left changes the table at once ({vals}, {tbl.horizontalHeaderItem(2).text()})")
A.panel.tol_spin.setValue(10)
pump(3)
w._poll()

print("--- the other models, the CSV, the settings")
before = set(w.kept)
w.say("")
w.run_others()
ok(w.status.text().startswith("Every distance-only model"), f"all three have been run: nothing is left to run ({w.status.text()})")
del w.kept[(l700, "Detector")]
w.run_others()
for _ in range(400):
    app.processEvents()
    if not A.running and not w._queue:
        break
    time.sleep(0.05)
pump(3)
ok(set(w.kept) == before and w.kept[(l700, "Detector")]["an"].finished and w._detectors["Detector"].calls == FRAMES, "Run the other distance models runs the one that was missing, on the same boxes (the detector did not run again)")
SAVE["path"] = os.path.join(T, "comparison.csv")
out = w.export_comparison()
txt = open(out).read()
ok(out == SAVE["path"] and txt.count("(boxes: Detector)") >= 3 and "2-4 m" in txt, "Export CSV writes the comparison")
W.sync_editors()
ok(nM.data["settings"].get("boxes_from") == "Detector", f"the project keeps the detector that was chosen ({nM.data['settings'].get('boxes_from')})")
A.panel.core_check.setChecked(True)
wait_run(w)
w._poll()
notes = [it["note"] for it in w.compare_items()]
ok(sum(1 for t in notes if "run again" in t) == 2 and sum(1 for t in notes if not t) == 1, f"the LiDAR read another way: the run that was re-read stays, the others say to run again ({notes})")
A.panel.core_check.setChecked(False)
wait_run(w)
A.example()
wait_run(w)
ok([it["name"] for it in w.compare_items()] == ["Made-up model (example)"], f"another session: the pane has only what was run on it (the example runs its own model), none of the runs made on the first one ({[it['name'] for it in w.compare_items()]})")
ok(any(w.bf_combo.itemText(i) == "Made-up model (example)" for i in range(w.bf_combo.count())), "and the example's made-up model can give boxes")
A.panel.model_combo.setCurrentText(l840)
w.bf_combo.setCurrentText("Made-up model (example)")
A.run()
wait_run(w)
mine = [it for it in w.compare_items() if it["name"].startswith("pin840")]
ok(A.analysis.finished and len(mine) == 1 and mine[0]["summary"]["frames"] == FRAMES and "boxes: Made-up model (example)" in mine[0]["name"], "a distance model on the example's own boxes runs")

print()
print("all passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
