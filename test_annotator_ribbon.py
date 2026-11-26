import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""The annotator's ribbon and side panel: the buttons that have nothing to act on are greyed (no image, first / last frame, no box selected), the
Selected box tab says what the selected box is, the class list counts the boxes of the open image, the frame list shows thumbnails and notes
(To do / All), the picture says which frame it is, hover tips carry the hotkeys, the Load AI model list follows the model box, and without
OpenPara's icon kit (the annotator on its own) the same window works with text-only buttons."""
import os, sys, tempfile, time, contextlib
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
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QToolButton
app = QApplication([])
import numpy as np, cv2
import share_zip as sz, qtk, ext
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
INFO = []
for n in ("info", "warn", "error"):
    setattr(qtk, n, lambda parent, title, text, _n=n: INFO.append((_n, title, text)))
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import annotator_window as aw, annotator_tab as at, annotator_icons as aic, annotator_ribbon as rib, annotator_panel as pnl, model_library as ml
import icon_kit

FAILS = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)

def pump(n=20, dt=0.03):
    for _ in range(n):
        app.processEvents(); time.sleep(dt)

def wait_job(w):
    for _ in range(400):
        app.processEvents()
        if not w._bg_job:
            return
        time.sleep(0.05)
    raise AssertionError("background job did not finish")

class FakeHost:
    @contextlib.contextmanager
    def busy(self, text): yield

def video(name):
    p = os.path.join(TMP, name)
    vw = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(12):
        f = np.full((240, 320, 3), 30 + i * 5, np.uint8); cv2.rectangle(f, (50 + i * 3, 60), (150 + i * 3, 160), (0, 200, 0), -1); vw.write(f)
    vw.release()
    return p

ext.MENU_ITEMS.clear()
w = at.make_tab(None)
w.host = FakeHost(); w.resize(1300, 800); w.show(); pump(4)
R, P = w.ribbon, w.panel
proj = os.path.join(TMP, "Rib.annotator")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (proj, ""))
qtk.ask_files = lambda *a, **k: [video("clip.mp4")]
qtk.ask_int = lambda *a, **k: 1
w.import_video(); wait_job(w); pump(6)
w.project.add_class("rock"); w.project.add_class("bush"); w._after_class_change(""); pump(2)
ids = w.project.list_images()
ok(len(ids) == 12 and w.current_image_id == ids[0], "twelve frames imported, the first one open")

# ---- greyed buttons follow what is open
on = lambda *keys: all(R.buttons[k].isEnabled() for k in keys)
off = lambda *keys: not any(R.buttons[k].isEnabled() for k in keys)
ok(on("confirm", "next", "fit", "rotate", "delete_frame", "lidar", "retry_ai") and off("prev", "delete_box", "clear_dist"), "first frame: Previous is greyed, so are the box buttons (no box selected)")
ok(w.frame_text == "Frame 1 of 12", w.frame_text)
w.next_image(); pump(2)
ok(on("prev", "next") and w.frame_text == "Frame 2 of 12", "the middle: both arrows work, the picture says Frame 2 of 12")
w.load_image(ids[-1]); pump(2)
ok(on("prev") and off("next") and w.frame_text == "Frame 12 of 12", "the last frame: Next is greyed")
w.load_image(ids[0]); pump(2)

# ---- boxes: counts in the class list, the Selected box tab, the two box buttons
c = w.canvas
def draw(x0, y0, x1, y1):
    w.on_canvas_release(c.width() * x0, c.height() * y0, c.width() * x1, c.height() * y1)
draw(.2, .3, .4, .6); draw(.5, .3, .7, .6); pump(2)
ok(len(w.boxes) == 2 and w.class_list.item(0).data(pnl.ROLE_COUNT) == 2 and w.class_list.item(1).data(pnl.ROLE_COUNT) == 0, "the class list counts the open image's boxes per class")
ok("No box selected" in P.box_info.text() and off("delete_box"), "nothing selected yet")
w.on_canvas_release(c.width() * .3, c.height() * .45, c.width() * .3, c.height() * .45)       # a click inside the first box
ok(w.selected_box_index == 0 and "rock" in P.box_info.text() and "No distance attached" in P.box_info.text() and on("delete_box") and off("clear_dist"), "a click selects it: the tab names the box, Delete box is on, Clear distance is not")
w.box_dist[0] = {"distance_m": 3.2, "u": 10, "v": 20}; w._save_current_boxes(); pump(2)
ok("3.20 m" in P.box_info.text() and on("clear_dist"), "with a distance attached the tab shows it and Clear distance is on")
R.buttons["clear_dist"].click(); pump(2)
ok(w.box_dist[0] is None and off("clear_dist") and "No distance attached" in P.box_info.text(), "the ribbon's Clear distance clears it")
R.buttons["delete_box"].click(); pump(2)
ok(len(w.boxes) == 1 and w.selected_box_index is None and "No box selected" in P.box_info.text() and off("delete_box"), "the ribbon's Delete box removes the selected box")

# ---- the LiDAR switch: the ribbon button and the hotkey are one switch
R.buttons["lidar"].click(); pump(2)
ok(w.pick_check.isChecked() and R.buttons["lidar"].isChecked(), "LiDAR distance switches on from the ribbon")
w._toggle_pick(); pump(2)
ok(not R.buttons["lidar"].isChecked(), "and the hotkey switches the same button off")
ok(not w.canvas.grab().isNull(), "the picture paints with its labels (hint, frame number)")

# ---- hover tips carry the keys; changing a key changes the tip
ok(f"({w.hotkeys.label('fit_view')})" in R.buttons["fit"].toolTip() and f"({w.hotkeys.label('delete_box')})" in R.buttons["delete_box"].toolTip(), "tips: " + R.buttons["fit"].toolTip())
w.hotkeys.set("fit_view", "g", len(w.project.classes)); w._hotkeys_changed(); pump(2)
ok("(G)" in R.buttons["fit"].toolTip().upper(), "a new key for Fit shows in its tip: " + R.buttons["fit"].toolTip())

# ---- the frame list: states, notes, To do / All, thumbnails
w.confirm_current_as_is(); pump(2)
w.load_image(ids[3]); draw(.2, .3, .4, .6); w.confirm_current_as_is(); pump(2)
w.project.set_ai_predicted_boxes(ids[5], [(0, .5, .5, .2, .2)]); w._refresh_image_list(); pump(2)
def rows():
    return {P.image_list.item(i).data(pnl.ROLE_ID): P.image_list.item(i) for i in range(P.image_list.count())}
todo = rows()
ok(not P.show_all() and P.todo_btn.isChecked() and not P.all_btn.isChecked(), "To do is the first view")
ok(ids[0] not in todo or ids[0] == w.current_image_id, "an annotated frame drops off the To do list (the open one stays)")
ok(todo[ids[5]].data(pnl.ROLE_STATE) == "ai" and w._frame_note(ids[5]) == "AI draft" and todo[ids[5]].text().startswith("[?]"), "an AI draft is marked and says so")
ok(todo[ids[7]].data(pnl.ROLE_STATE) == "todo" and w._frame_note(ids[7]) == "", "a frame still to do says nothing")
P.all_btn.click(); pump(2)
allrows = rows()
ok(P.show_all() and P.all_btn.isChecked() and not P.todo_btn.isChecked() and len(allrows) == 12, "All lists every frame")
ok(allrows[ids[3]].data(pnl.ROLE_STATE) == "done" and allrows[ids[3]].text().startswith("[✓]") and w._frame_note(ids[3]) == "1 box", "an annotated frame: checkmark, '1 box'")
P.all_btn.click(); pump(2)
ok(P.show_all() and P.all_btn.isChecked(), "clicking All again keeps All")
P.todo_btn.click(); pump(2)
ok(not P.show_all() and len(rows()) < 12, "To do narrows the list again")
P.all_btn.click(); pump(2)
P.image_list.grab(); pump(2)
pm = P.thumbs.get(ids[2])
ok(pm is not None and not pm.isNull() and abs(pm.deviceIndependentSize().width() - pnl.THUMB_W) < 1 and len(P.thumbs.items) > 0, "thumbnails are made for the rows that are shown")
w.load_image(ids[2]); before = P.thumbs.get(ids[2]); w.rotate_current_frame(); pump(2)
ok(w.current_pil_image.size == (240, 320) and P.thumbs.get(ids[2]) is not before, "a rotated frame's thumbnail is made again from the rotated file")
w.set_active_session(next(k for k in w._session_keys if k)); pump(2)
ok("annotated" in P.set_summary.text() and "2 of 12" in P.set_summary.text() and P.set_summary.text().startswith("Set "), "the footer of the list: " + P.set_summary.text())
w.set_active_session(None); pump(2)
ok(P.set_summary.text().startswith("All sets") and "2 of 12" in P.set_summary.text(), "and for all sets: " + P.set_summary.text())
n_before = len(w.project.list_images())
R.buttons["delete_frame"].click(); pump(4)
ok(len(w.project.list_images()) == n_before - 1, "the ribbon's Delete frame deletes the open frame (asks first)")

# ---- Load AI model follows the model box
src = os.path.join(TMP, "m.pt"); open(src, "wb").write(b"x")
mdir = aw.models_dir()
os.makedirs(ml.folder_path(mdir, "assist"), exist_ok=True); os.makedirs(ml.folder_path(mdir, "scratch"), exist_ok=True)
ml.save_version(mdir, "assist", src, "n", "tester")
w._models_changed(); pump(2)
labels = [w.ai_choice.itemText(i) for i in range(w.ai_choice.count())]
menu = R.buttons["load_model"].menu()
ok(len(labels) == 2 and [a.text() for a in menu.actions()] == labels, "the Load AI model list is the model box: " + str(labels))
ok([a.isChecked() for a in menu.actions()] == [True, False], "the loaded one (none) is ticked")
picked = []
w.load_ai_model = lambda kind=None: picked.append(w.ai_choice.currentText())
menu.actions()[1].trigger(); pump(2)
ok(picked == [labels[1]] and w.ai_choice.currentText() == labels[1] and [a.isChecked() for a in R.buttons["load_model"].menu().actions()] == [False, True], "choosing from the ribbon picks the model and ticks it")
del w.load_ai_model

# ---- every drawing registers and renders; the ribbon's icons come from them
ok(all(icon_kit.has(k) for k in aic.ICONS) and all(not icon_kit.pixmap(k, 36).isNull() for k in aic.ICONS), f"all {len(aic.ICONS)} annotator icons are drawn")
ok(all(not b.icon().isNull() for b in R.buttons.values()), "every ribbon button has its icon")
ok(all(P.tabs.tabIcon(i).isNull() is False for i in range(P.tabs.count())), "the three panel tabs have icons")

# ---- on its own (no icon kit, no program look): the same window, buttons with text only
saved_kit, saved_ui = aic.icon_kit, aw.ui_kit
aic.icon_kit, aw.ui_kit = None, None
alone = at.make_tab(None); alone.show(); pump(3)
ok(all(b.icon().isNull() and b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly for b in alone.ribbon.buttons.values()) and len(alone.ribbon.buttons) == len(R.buttons), "without the icon kit every button is text only")
ok(alone.ribbon.buttons["confirm"].text() == "Confirm\nimage" and alone.bar_lbl is not None and not alone.panel.tabs.tabText(0) == "", "and the panel tabs say their names")
alone.close()
aic.icon_kit, aw.ui_kit = saved_kit, saved_ui

w.close()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED")
os._exit(1 if FAILS else 0)
