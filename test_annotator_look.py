import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
"""The Annotator as the redesign board draws it (ANN-1): the box labels are tabs of the class colour with the distance to one decimal, the LiDAR caption is a chip that reads on a light sky,
the frames of a set are named by their number, the status line and the bar read as on the board, "Clear & retry AI", and a project whose frames are all confirmed opens on a frame
(not on a dark empty picture area).  python test_annotator_look.py"""
import os, sys, time, tempfile, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == "tests":
    HERE = os.path.dirname(HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
TMP = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(TMP, "user")
CORE = os.path.join(HERE, "core") if os.path.isdir(os.path.join(HERE, "core")) else HERE
ADD = os.path.join(HERE, "addons") if os.path.isdir(os.path.join(HERE, "addons")) else os.path.join(HERE, "addons_src")
ANN = os.path.join(ADD, "annotator", "app")
for p in (CORE, ANN, os.path.dirname(ANN)):
    sys.path.insert(0, p)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QToolButton
app = QApplication([])
import numpy as np, cv2
from PIL import Image
import share_zip as sz, qtk, ext
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
qtk.info = qtk.warn = qtk.error = lambda *a, **k: None
import annotator_tab as at, annotator_core as ac, annotator_panel as pnl
from annotator_canvas import color_for_class


def ok(msg):
    print("ok:", msg, flush=True)


def pump(n=20, dt=0.03):
    for _ in range(n):
        app.processEvents(); time.sleep(dt)


class FakeHost:
    @contextlib.contextmanager
    def busy(self, text):
        yield


W, H = 960, 720
people = [  # (cx, foot_y, height_px, distance_m)
    [(300, 600, 330, 3.4), (700, 520, 190, 6.8)],
    [(330, 610, 340, 3.2), (690, 520, 192, 6.7), (130, 470, 120, 10.4)],
    [(360, 612, 346, 3.1), (672, 522, 196, 6.6), (140, 470, 118, 10.6)],
    [(390, 618, 352, 3.0), (655, 524, 200, 6.4)],
]
def scene(i):
    f = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        t = y / H
        f[y] = (np.array([226, 214, 196]) * (1 - t) + np.array([150, 160, 150]) * t) if y < 430 else (np.array([120, 126, 120]) * (1 - (y - 430) / 600))
    cv2.rectangle(f, (0, 300), (W, 430), (176, 170, 160), -1)
    for x in range(0, W, 120): cv2.line(f, (x, 300), (x, 430), (150, 146, 138), 2)
    for (cx, fy, h, d) in people[i]:
        w = int(h * 0.38)
        cv2.ellipse(f, (cx, fy - h + int(h * .09)), (int(h * .075), int(h * .09)), 0, 0, 360, (80, 96, 150), -1)
        cv2.rectangle(f, (cx - w // 2, fy - h + int(h * .2)), (cx + w // 2, fy - int(h * .45)), (60, 110, 90), -1)
        cv2.rectangle(f, (cx - w // 2 + 4, fy - int(h * .45)), (cx + w // 2 - 4, fy), (70, 70, 96), -1)
    return f


def make_project(name, n_done):
    vp = os.path.join(TMP, name + ".mp4")
    vw = cv2.VideoWriter(vp, cv2.VideoWriter_fourcc(*"mp4v"), 10, (W, H))
    for i in range(len(people)): vw.write(scene(i))
    vw.release()
    
    proj = os.path.join(TMP, name + ".annotator"); os.makedirs(proj)
    P = ac.Project(proj)
    P.add_class("person"); P.add_class("bag")
    res = P.import_video(vp, stride=1, session_name="20261125_184611")
    ids = sorted(res["new_ids"])
    for i, img in enumerate(ids[:len(people)]):
        boxes, picks = [], []
        dm = np.zeros((H, W), np.uint16)
        yy, xx = np.mgrid[0:H:9, 0:W:11]
        for y, x in zip(yy.ravel(), xx.ravel()):
            if 150 < y < 640: dm[y, x] = 7300 + (x % 7) * 40
        for (cx, fy, h, d) in people[i]:
            w = int(h * 0.38); x1, y1, x2, y2 = cx - w // 2 - 6, fy - h - 4, cx + w // 2 + 6, fy
            boxes.append((0, *ac.pixel_box_to_yolo(x1, y1, x2, y2, W, H)))
            sel = (yy >= y1) & (yy <= y2) & (xx >= x1 + w * .15) & (xx <= x2 - w * .15)
            for y, x in zip(yy[sel], xx[sel]): dm[y, x] = int(d * 1000 + (x % 5) * 12)
            picks.append({"distance_m": d, "u": cx, "v": fy - h // 2})
        Image.fromarray(dm).save(P.depth_path(img))
        P.manifest["images"][img]["has_depth"] = True
        if i < n_done:
            P.set_boxes(img, boxes, picks)
    P.save_manifest()
    
    return proj, ids


def window(proj):
    w = at.make_tab(proj)
    w.host = FakeHost(); w.resize(1500, 900); w.show(); pump(20)
    return w


def lum(c):
    return 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()


SESSION = "20261125_184611"

# ---- 1. a project whose frames are all confirmed opens on a frame, not on a dark empty picture area
proj, ids = make_project("done_all", 4)
w = window(proj)
assert w.panel.show_all() and w.image_list.count() == 4 and w.current_image_id == ids[0] and w.current_pil_image is not None, (w.image_list.count(), w.current_image_id)
assert w.panel.all_btn.isChecked() and not w.panel.todo_btn.isChecked() and w.canvas._qimg is not None
ok("a project whose frames are all confirmed opens with every frame listed and the first one open (the list was empty and the picture area dark)")

# ---- 2. a project with work left still opens on the work queue
proj2, ids2 = make_project("some_left", 3)
w2 = window(proj2)
assert not w2.panel.show_all() and w2.image_list.count() == 1 and w2.current_image_id == ids2[3]
w2.panel.set_show_all(True); pump(5)
assert w2.image_list.count() == 4
ok("with a frame still to do the list is the work queue (To do), and All shows every frame")

# ---- 3. the frames of a set are named by their number; over all sets by their whole id
w.set_active_session(SESSION); pump(5)
names = [w.image_list.item(i).data(pnl.ROLE_NAME) for i in range(w.image_list.count())]
assert names == ["000000", "000001", "000002", "000003"], names
w.set_active_session(None); pump(5)
names = [w.image_list.item(i).data(pnl.ROLE_NAME) for i in range(w.image_list.count())]
assert names == [i for i in ids], names
assert w.session_combo.itemText(0) == "All sets   4 / 4" and w.session_combo.itemText(1) == f"[A] {SESSION}   4 / 4", [w.session_combo.itemText(i) for i in range(2)]
ok("a set's frames are named 000000, 000001 ... (the whole id over all sets), and the set box says '20261125_184611   4 / 4'")

# ---- 4. the status line and the bar as on the board
w.set_active_session(SESSION); w.load_image(ids[1]); pump(10)
assert w.status_label.text() == f"{ids[1]}  |  3 boxes (3 with distance)  |  annotated  |  4 images in project", w.status_label.text()
assert "· 4 images" in w.bar_lbl.text() and " - 4" not in w.bar_lbl.text()
assert w.ai_status.text() == "No AI model loaded"
ok("the status line reads 'name | 3 boxes (3 with distance) | annotated | 4 images in project', the bar 'name · 4 images', the model 'No AI model loaded'")

b = w.ribbon.buttons["retry_ai"]
assert b.text().replace("\n", " ") == "Clear && retry AI", b.text()
ok("the ribbon button is 'Clear & retry AI' (&& in the text, which Qt shows as one &)")

# ---- 5. the picture: a label tab on each box, the caption on a chip
w.canvas.redraw(); pump(5)
img = w.canvas.grab().toImage()
cls_col = QColor(color_for_class(0))
iw, ih = w.current_pil_image.size
found = 0
for (cls, xc, yc, bw, bh) in w.boxes:
    x1, y1, x2, y2 = ac.yolo_box_to_pixel(xc, yc, bw, bh, iw, ih)
    cx1, cy1 = w.canvas.to_canvas(x1, y1)
    px, py = int(cx1) + 3, int(cy1) - 6
    c = img.pixelColor(px, py)
    if abs(c.red() - cls_col.red()) < 12 and abs(c.green() - cls_col.green()) < 12 and abs(c.blue() - cls_col.blue()) < 12:
        found += 1
assert found == len(w.boxes) == 3, (found, len(w.boxes))
ok("every box has a tab of its class colour on its top edge (the label is white on it)")

assert w.pick_check.isChecked() is False
w.pick_check.setChecked(True); pump(10)
img = w.canvas.grab().toImage()
off_x, off_y = w.canvas.offset
sky = img.pixelColor(int(off_x) + 300, int(off_y) + 60)
chip = img.pixelColor(int(off_x) + 16, int(off_y) + 22)
assert lum(sky) > 140 and lum(chip) < 110, (lum(sky), lum(chip))
w.pick_check.setChecked(False)
ok("the LiDAR caption sits on a dark chip, so it reads on the light sky of the picture")

# ---- 6. no picture open although the project has frames: the canvas says so
w._clear_current(); w.canvas.redraw(); pump(5)
img = w.canvas.grab().toImage()
mid = [img.pixelColor(x, img.height() // 2 - 12) for x in range(img.width() // 2 - 60, img.width() // 2 + 60, 2)]
assert any(lum(c) > 150 for c in mid), "light text on the dark canvas"
ok("with no picture open the canvas says 'No picture is open' and what to do")

w.close(); w2.close()
print("annotator look ok", flush=True)
