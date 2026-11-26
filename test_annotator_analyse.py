import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""The annotator's Analyse tab: open a recorded Gimble session, run a model over it, and see how its distance holds up against the LiDAR.
The model is a made-up one (the real one needs torch); the session is made up too, with answers worked out by hand: of the four boxes the model
gives a distance for and the LiDAR has returns in (at 85 % confidence), the closest point passes 3, the median 2, the average 0.
Covers: the tab and its buttons, opening a session (a dataset folder asks which), running with progress and Stop, the settings (confidence,
tolerance, judging method, middle of the box) re-judging at once, scrubbing (arrows, strip, filters, boxes list), the detail card, the exports
(CSV, report, frame picture), a model with no distance, a model that fails, and the adapter that turns the annotator's model objects into
what the analysis reads."""
import os, sys, tempfile, time, contextlib, csv, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
ANN = os.path.join(HERE, "addons", "annotator", "app")
if not os.path.isdir(ANN):
    ANN = os.path.join(HERE, "addons_src", "annotator", "app")
for p in (CORE, ANN, os.path.dirname(ANN)):
    sys.path.insert(0, p)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QInputDialog
app = QApplication([])
from PIL import Image
import share_zip as sz, qtk, ext
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
INFO = []
for n in ("info", "warn", "error"):
    setattr(qtk, n, lambda parent, title, text, _n=n: None if title == "Download models" else INFO.append((_n, title, text)))     # (the first-run offer to fetch models has no network here)
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import annotator_tab as at, annotator_analysis as aa, annotator_analyse as ana, annotator_icons as aic

FAILS = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)

def pump(n=20, dt=0.03):
    for _ in range(n):
        app.processEvents(); time.sleep(dt)

def wait_run(A):
    for _ in range(400):
        app.processEvents()
        if not A.running:
            pump(3)
            return
        time.sleep(0.05)
    raise AssertionError("the analysis did not finish")

class FakeHost:
    @contextlib.contextmanager
    def busy(self, text): yield

ext.MENU_ITEMS.clear()
w = at.make_tab(None)
w.host = FakeHost(); w.resize(1300, 800); w.show(); pump(4)
R, A = w.ribbon, w.analyse
P = A.panel
def show_tab(i):
    P.tabs.setCurrentIndex(i); pump(3)
on = lambda *keys: all(A.rb[k].isEnabled() for k in keys)
off = lambda *keys: not any(A.rb[k].isEnabled() for k in keys)

# ---- the tab, and what it swaps
tabs = [R.tabText(i) for i in range(R.count())]
ok(tabs == ["Annotate", "Data", "Models", "Analyse", "Setup"], f"the ribbon has an Analyse tab between Models and Setup: {tabs}")
ok(w.stack.currentIndex() == 0 and not w._mode_analyse and w.shortcuts and all(s.isEnabled() for s in w.shortcuts), "the annotating view is shown first, its hotkeys awake")
R.show_page("Analyse"); pump(3)
ok(w.stack.currentIndex() == 1 and w._mode_analyse and all(not s.isEnabled() for s in w.shortcuts), "the Analyse tab shows its own panel and picture, and the annotating hotkeys sleep")
w._bind_hotkeys()
ok(all(not s.isEnabled() for s in w.shortcuts), "a key changed while it is shown does not wake them")
ok(w.status_label.text() == "Analyse: no session open", w.status_label.text())
ok(on("open", "run", "example", "selfcheck") and off("stop", "save_img", "csv", "report", "dots_box", "dots_all"), "nothing open: Run, Open, Example and Self-check can be pressed, the rest is greyed")
icons_ok = all(not A.rb[k].icon().isNull() for k in A.rb) and all(not A.panel.tabs.tabIcon(i).isNull() for i in range(3))
ok(icons_ok and all(len(A.rb[k].toolTip()) > 14 for k in A.rb), "every button has an icon and a hover tip, and the panel tabs have icons")

# ---- opening a session
sess_dir = aa.make_demo_session(os.path.join(TMP, "dataset", "20261125_184611"))
aa.make_demo_session(os.path.join(TMP, "dataset", "20261125_100000"))
qtk.ask_dir = lambda *a, **k: None
A.run()
ok(not A.running and A.session is None and not INFO, "Run with nothing open asks for a folder; cancelling it does nothing")
A.open_session(os.path.join(TMP, "nothing_here"))
ok(INFO and INFO[-1][0] == "error" and "Not a recorded session" in INFO[-1][1], f"a folder that is no session says so: {INFO[-1:]}")
INFO.clear()
picked = []
def choose(parent, title, label, names, cur, edit):
    picked.append(list(names)); return names[0], True
QInputDialog.getItem = staticmethod(choose)
ok(A.open_session(os.path.join(TMP, "dataset")) and A.session.name == "20261125_100000" and picked == [["20261125_100000", "20261125_184611"]], "a dataset folder with two sessions asks which; the one picked opens")
QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
ok(not A.open_session(os.path.join(TMP, "dataset")) and A.session.name == "20261125_100000", "cancelling that question keeps what was open")
ok(A.open_session(sess_dir) and A.session.name == "20261125_184611" and len(A.session) == 6, "a session folder opens on its own")
qtk.ask_dir = lambda *a, **k: sess_dir
ok(A.open_session() and w.cfg.get("analyse_dir") == os.path.join(TMP, "dataset"), "a folder picked in the dialog is remembered for the next time: " + str(w.cfg.get("analyse_dir")))
qtk.ask_dir = lambda *a, **k: None
ok(A.panel.folder_label.text() == "20261125_184611" and A.panel.folder_label.toolTip() == sess_dir and on("save_img", "dots_box", "dots_all") and off("csv", "report"), "the panel names it; pictures can be saved, results cannot be exported yet")
ok(A.frame_image(0) is not None and A.view.where.text() == "Frame 1 of 6" and "not analysed" in A.view.summary.text(), "the first photo is on show before any run: " + A.view.summary.text())
A.run()
ok(not A.running and INFO and INFO[-1][1] == "Pick a model", f"no model in the list: Run says so ({INFO[-1:]})")
INFO.clear()
show_tab(2); ok(P.frame_list.count() == 6, "the Frames tab lists the photos even before a run"); show_tab(0)

# ---- the model list follows the annotator's
gone_pt = os.path.join(TMP, "gone.pt")
w._inserted["Trained: foo"] = {"label": "Trained: foo", "path": gone_pt, "kind": "scratch"}          # a model of the annotator's list (kept when the list is rebuilt)
w._refresh_ai_choices([]); pump(2)
labels = [A.panel.model_combo.itemText(i) for i in range(A.panel.model_combo.count())]
ok(labels == ["Trained: foo"], f"the Analyse model list is the annotator's models without 'No AI model': {labels}")

# ---- a model that is not there / cannot be loaded here: an error, and the tab is usable again
A.predictor_for = A._default_predictor
A.panel.model_combo.setCurrentText("Trained: foo"); A.run(); wait_run(A)
ok(INFO and INFO[-1][1] == "Analysis failed" and "not there" in INFO[-1][2] and not A.running and on("run", "open"), f"a model that is gone: {INFO[-1:]}")
INFO.clear()
fake_pt = os.path.join(TMP, "foo.pt"); open(fake_pt, "wb").write(b"not a model")
w._inserted["Trained: foo"]["path"] = fake_pt; w._refresh_ai_choices([]); pump(2)
A.run(); wait_run(A)
ok(INFO and INFO[-1][1] == "Analysis failed" and not A.running and A.analysis.analysed == 0, f"a file that is no model: an error, nothing analysed ({INFO[-1][2][:60]})")
INFO.clear()

# ---- the example: made-up session, made-up model, run
A.example(); wait_run(A)
ok(A.session.name == "example_session" and A.analysis is not None and A.analysis.finished and A.analysis.analysed == 6 and not INFO, "the example opens its session and runs the whole of it")
ok(A.panel.model_combo.currentText() == ana.DEMO_LABEL and "gives a distance" in A.panel.model_note.text(), A.panel.model_note.text())
ev = A.ev
ok(ev.boxes == 6 and ev.counts["closest"] == [3, 1] and ev.counts["median"] == [2, 2] and ev.counts["average"] == [0, 4], f"the numbers worked out by hand: {ev.counts}")
vals = {m: P.rows[m].value.text() for m in aa.METHODS}
ok(vals == {"closest": "75%", "median": "50%", "average": "0%"}, f"the Results tab shows them: {vals}")
ok("1 box " in P.nolidar.text() and "No predicted distance: 1 box" in P.nolidar.text(), "no LiDAR / no distance are counted apart: " + P.nolidar.text().replace("\n", " | "))
bands = [(lab.text(), val.text()) for (wd, lab, bar, val) in P.band_rows if not wd.isHidden()]
ok(bands == [("2-4 m", "50% (2)"), ("6-8 m", "100% (2)")], f"by distance: {bands}")
ok(P.rows["closest"].sub.text().endswith("(colours the boxes)") and "RESULTS" in P.results_head.text() and "6 BOXES" in P.results_head.text(), P.results_head.text())
ok(on("save_img", "csv", "report", "run", "open", "example", "selfcheck") and off("stop"), "after a run the exports are on")
ok(w.status_label.text().startswith("Session example_session  |  6 frames  |  6 analysed"), w.status_label.text())

# ---- scrubbing
ok(A.cur == 0 and A.sel == 0 and "2 boxes: 2 pass, 0 fail, 0 no result" in A.view.summary.text(), "frame 1: " + A.view.summary.text())
card = A.view.canvas.card
ok(not card.isHidden() and "3.00 m" in card.value_labels["pred"].text() and "off by 0%" in card.value_labels["closest"].text() and "off by 50%" in card.value_labels["average"].text(), "the card of the selected box: " + card.value_labels["average"].text())
ok("Box 1 of 2" in card.head.text() and "100 LiDAR points" in card.points.text(), card.head.text() + " / " + card.points.text())
A.goto(1); pump(2)
ok("1 fail" in A.view.summary.text() and "1 no result" in A.view.summary.text(), "frame 2: " + A.view.summary.text())
A.select_box(1)
ok("no LiDAR" in card.value_labels["closest"].text() and "5.00 m" in card.value_labels["pred"].text(), "a box with no LiDAR says so: " + card.value_labels["closest"].text())
A.goto(3); pump(2)
ok(card.isHidden() and "0 boxes" in A.view.summary.text(), "a frame without boxes: no card, " + A.view.summary.text())
A.goto(0)
A.set_filter("fail"); show_tab(2)
ok(A.cur == 1 and A.panel.frame_list.count() == 1 and A.view.chips["fail"].isChecked() and not A.view.chips["all"].isChecked(), "the With a fail filter moves to the frame that has one and lists only it")
A.goto(1); A.step(1); A.step(-1)
ok(A.cur == 1 and not A.view.next_btn.isEnabled() and not A.view.prev_btn.isEnabled(), "arrows stay within the filtered frames")
A.set_filter("nolidar")
ok(A.cur == 1 and A.panel.frame_list.count() == 1, "the No LiDAR filter finds the same frame here")
A.set_filter("all"); ok(P.frame_list.count() == 6 and P.frame_list.currentRow() == 1, "All frames lists them all again, the open one marked"); show_tab(0)
A.jump(True); ok(A.cur == 5, "End goes to the last frame"); A.jump(False); ok(A.cur == 0, "Home to the first")
A.step(1); A.step(1); ok(A.cur == 2, "the Next button steps on")
A.view.canvas.setFocus(); QTest.keyClick(A.view.canvas, Qt.Key.Key_Left); pump(2)
ok(A.cur == 1, "the left arrow key goes back one frame (cur %d)" % A.cur)
strip = A.view.strip
QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=QPoint(int(strip.width() * 4.5 / 6), 10)); pump(2)
ok(A.cur == 4, "a click on the strip goes to that frame")
A.goto(0); A.view.canvas.repaint(); pump(2)
rect, cvw = A.view.canvas._rect, A.view.canvas
bx = [d for _i, d, _s in ana.kept_boxes(A.analysis, 0, A.settings)][1].box          # the second box of frame 1
pt = QPoint(int(rect.left() + (bx[0] + bx[2]) / 2 / 320 * rect.width()), int(rect.top() + (bx[1] + bx[3]) / 2 / 240 * rect.height()))
QTest.mouseClick(cvw, Qt.MouseButton.LeftButton, pos=pt); pump(2)
ok(A.sel == 1 and "Box 2 of 2" in card.head.text(), "a click on a box selects it")
A.step_box(1); ok(A.sel == 0, "the down arrow goes round to the next box"); A.step_box(-1); ok(A.sel == 1, "and up goes back")

# ---- the boxes list jumps to its box
tb = P.table
show_tab(1)
ok(tb.rowCount() == 6 and [tb.item(0, c).text() for c in range(6)] == ["1", "person", "0.93", "3.00 m", "3.00 m", "✓ pass"] and tb.horizontalHeaderItem(4).text() == "Closest", "the Boxes tab: six rows, the first " + str([tb.item(0, c).text() for c in range(6)]))
ok(tb.item(3, 5).text() == "no LiDAR" and tb.item(5, 5).text() == "no distance", "rows say no LiDAR / no distance: " + tb.item(3, 5).text() + ", " + tb.item(5, 5).text())
A.goto(0, 1); pump(2)
ok(tb.currentRow() == 1, "the row of the box on show is the selected one")
P._box_clicked(4, 0); pump(2)
ok(A.cur == 2 and A.sel == 1 and tb.currentRow() == 4, "a click on a row of the list goes to that frame and box")

# ---- the settings judge again at once
P.conf_slider.setValue(75); pump(8)
ok(A.ev.boxes == 7 and A.ev.counts["closest"] == [4, 1] and A.ev.counts["median"] == [3, 2] and P.conf_label.text() == "75%" and tb.rowCount() == 7, f"85 % -> 75 % adds the 80 % box: {A.ev.counts}")
P.conf_slider.setValue(85); pump(8)
P.tol_spin.setValue(30); A.set_method("median"); pump(8)
ok(A.ev.counts["median"] == [4, 0] and A.ev.counts["closest"] == [4, 0] and P.rows["median"].sub.text().endswith("(colours the boxes)"), f"a wider tolerance passes the 25 % miss: {A.ev.counts}")
show_tab(0); QTest.mouseClick(P.rows["average"], Qt.MouseButton.LeftButton); pump(4)
ok(A.settings.method == "average" and P.rows["average"].sub.text().endswith("(colours the boxes)") and A.ev.state[0] == "fail", "a click on a method row makes it the one that judges the boxes")
P.tol_spin.setValue(10); A.set_method("closest"); pump(8)
ok(A.ev.counts["closest"] == [3, 1], "back to the first settings, the first numbers")

# ---- the dots
ok(A.dots == "box" and A.rb["dots_box"].isChecked() and not A.rb["dots_all"].isChecked(), "dots in boxes is the default")
A.rb["dots_all"].setChecked(True)
ok(A.dots == "all" and not A.rb["dots_box"].isChecked() and not A.view.canvas.grab().isNull(), "All dots switches the other off, and the picture paints")
A.rb["dots_all"].setChecked(False)
ok(A.rb["dots_all"].isChecked() and A.dots == "all", "one of the two is always on")
A.rb["dots_box"].setChecked(True)
ok(A.dots == "box" and not A.rb["dots_all"].isChecked(), "and back")

# ---- the middle of the box: the same run, read again
P.core_check.setChecked(True); wait_run(A)
r2 = [r for r in aa.rows(A.analysis, aa.Settings()) if r["median_m"] is not None]
ok(A.analysis.region == "core" and A.region == "core" and r2 and all(r["median_m"] == r["average_m"] for r in r2), "the middle 60 % has only the object in it: median and average agree")
P.core_check.setChecked(False); wait_run(A)
ok(A.analysis.region == "box" and A.ev.counts["average"] == [0, 4] and not P.progress.isVisible(), "and the whole box again")

# ---- exports
cp = A.export_csv(os.path.join(TMP, "out.csv"))
with open(cp, newline="", encoding="utf-8") as f:
    rd = csv.DictReader(f); rows = list(rd)
ok(rd.fieldnames == aa.CSV_FIELDS and len(rows) == 6 and rows[0]["class"] == "person" and rows[0]["predicted_m"] == "3.0" and rows[3]["closest_result"] == "no LiDAR", "CSV: one row per box, the columns of the engine")
hp = A.export_report(os.path.join(TMP, "out.html"))
page = open(hp, encoding="utf-8").read()
ok("Model check - example_session" in page and "Closest point (judges the boxes)" in page and page.count("data:image/png;base64") == 3 and 'src="http' not in page, f"report: settings, results and {page.count('data:image/png;base64')} frame pictures, all in one file")
ip = A.save_frame_image(os.path.join(TMP, "frame.png"))
with Image.open(ip) as im:
    ok(im.width == 1280 and im.height > 960, f"the frame picture: the photo with its boxes and a line per box under it ({im.size})")
ok(A.render_frame(1, 640).width() == 640, "a picture can be made of any frame, at any width")
fails, passes = A.report_frames()
ok(fails == [1] and passes == [0, 2], f"the report shows the miss and the passing frames: {fails} {passes}")

# ---- Stop keeps what was done
state = {"n": 0}
def stopper(path):
    state["n"] += 1
    if state["n"] == 3:
        A.stop()
    return aa.demo_predictor(path)
A.predictor_for = lambda label: (stopper, True)
A.run(); wait_run(A)
ok(A.analysis.analysed == 3 and not A.analysis.finished and not A.running, f"Stop after the third frame keeps three ({A.analysis.analysed})")
ok("3 OF 6 FRAMES SO FAR" in P.results_head.text() and on("csv", "report") and A.ev.state[3] is None, P.results_head.text())
A.goto(4); pump(2)
ok("not analysed" in A.view.summary.text() and card.isHidden(), "a frame not reached says so")
INFO.clear()

# ---- a model that fails halfway
def broken(label):
    raise RuntimeError("model broke")
A.predictor_for = broken
A.run(); wait_run(A)
ok(INFO and INFO[-1] == ("error", "Analysis failed", "model broke") and not A.running and on("run", "open"), f"a failing model: {INFO[-1:]}")
INFO.clear()

# ---- a model with no distance: boxes are seen, none is judged
def no_distance(path):
    return [(c, conf, x1, y1, x2, y2, None) for (c, conf, x1, y1, x2, y2, _d) in aa.demo_predictor(path)]
A.predictor_for = lambda label: (no_distance, False)
A.run(); wait_run(A)
ok(A.ev.boxes == 6 and A.ev.no_distance == 6 and A.ev.counts["closest"] == [0, 0] and P.rows["closest"].value.text() == "-" and "no distance" in P.model_note.text(), "no distance: " + P.model_note.text())
show_tab(1)
ok(tb.item(0, 5).text() == "no distance", "and the Boxes list says no distance"); show_tab(0)

# ---- the adapter between the annotator's model objects and the analysis
class FakeGimble:
    class_names = ["person", "box"]
    def predict_detections(self, path, conf_threshold=0.25):
        assert conf_threshold == aa.FLOOR
        return [(0, .5, .5, .25, .5, .9, 3.5), (1, .25, .25, .1, .2, .3, 2.0)]
class FakeHelper:
    def predict_boxes(self, path, conf_threshold=0.25):
        return [(1, .5, .5, .5, .5)]
img = os.path.join(sess_dir, "images", "000000.jpg")
g = aa.AssistPredictor(FakeGimble())
out = g(img)
ok(g.has_distance and out[0] == ("person", 0.9, 120.0, 60.0, 200.0, 180.0, 3.5) and out[1][0] == "box" and out[1][6] == 2.0, f"a model with distances: classes by name, boxes in pixels: {out[0]}")
h = aa.AssistPredictor(FakeHelper())
ok(not h.has_distance and h(img) == [("class 1", 1.0, 80.0, 60.0, 240.0, 180.0, None)], f"a model without: no distance, no confidence ({h(img)})")

# ---- Self-check button
A.selfcheck(); pump(2)
ok(INFO and INFO[-1][0] == "info" and "17 of 17 checks passed" in INFO[-1][2] and "FAIL" not in INFO[-1][2], "Self-check: " + INFO[-1][2].split("\n")[0])
INFO.clear()

# ---- back to annotating: its status line and hotkeys are back
R.show_page("Annotate"); pump(3)
ok(w.stack.currentIndex() == 0 and not w._mode_analyse and all(s.isEnabled() for s in w.shortcuts) and w.status_label.text().startswith("Project:"), "the Annotate tab brings back its picture, status line and hotkeys: " + w.status_label.text()[:40])
w._update_status()
R.show_page("Analyse"); pump(2)
ok(w.status_label.text().startswith("Session example_session"), "the annotator's own status updates do not overwrite the Analyse line")
R.show_page("Annotate")

# ---- without the icon kit the panel tabs say their names
saved = aic.icon
aic.icon = lambda *a, **k: None
plain = ana.AnalysePanel(A)
ok([plain.tabs.tabText(i) for i in range(3)] == ["Results", "Boxes", "Frames"], "no icon kit: the panel tabs have names")
aic.icon = saved
plain.deleteLater()

# ---- the made-up session is made once and goes when the window does
demo = A.demo_dir
A.example(); wait_run(A)
ok(A.demo_dir == demo and os.path.isdir(demo) and A.session.folder == os.path.join(demo, "example_session"), "Try the example again opens the same made-up session")
w.close(); pump(2)
ok(not os.path.exists(demo), "closing the window removes it")
shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
os._exit(1 if FAILS else 0)
