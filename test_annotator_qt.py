import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
"""The annotator: a new project has no classes (so no AI-assist boxes); the File menu is short; the project is a folder with its dataset inside
(saved the first time something is imported); datasets travel as zips that merge; models come from the GitHub folder; windows show the
'Opening ...' card; add-ons add menu items."""
import os, sys, tempfile, time, zipfile, json, shutil, contextlib
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
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])
import numpy as np, cv2
import share_zip as sz, qtk, ext
sz.CONFIG_PATH = os.path.join(TMP, "cfg.json")
INFO = []
for n in ("info", "warn", "error"):
    setattr(qtk, n, lambda parent, title, text, _n=n: INFO.append((_n, title, text)))
qtk.yesno = lambda *a, **k: True
qtk.ask_string = lambda *a, **k: "Tester"
import annotator_window as aw, annotator_dialogs as dlg, annotator_tab as at, annotator_core as ac, dataset_zip as dz, model_library as ml


def pump(n=40, dt=0.05):
    for _ in range(n):
        app.processEvents(); time.sleep(dt)

def wait_job(w):
    for _ in range(400):
        app.processEvents()
        if not w._bg_job:
            return
        time.sleep(0.05)
    raise AssertionError("background job did not finish")

def video(name, shift=0):
    p = os.path.join(TMP, name)
    vw = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(12):
        f = np.full((240, 320, 3), 30 + i * 5 + shift, np.uint8); cv2.rectangle(f, (50 + i * 3, 60), (150 + i * 3, 160), (0, 200, 0), -1); vw.write(f)
    vw.release()
    return p

class FakeHost:
    def __init__(self): self.cards = []
    @contextlib.contextmanager
    def busy(self, text):
        self.cards.append(text); yield

# ---- 1. a new project: no classes, no AI-assist boxes, one AI choice, short menus
ext.MENU_ITEMS.clear()
w = at.make_tab(None)
w.host = FakeHost(); w.resize(1200, 800); w.show(); pump(4)
assert w.temp_root and w.path is None and w.title() == "Annotator" and not w.is_dirty()
assert w.project.classes == [] and w.ai_box.count() == 0 and w.class_list.count() == 0
assert [w.ai_choice.itemText(i) for i in range(w.ai_choice.count())] == ["No AI model"]
menus = {m.title().replace("&", ""): [a.text() for a in m.actions() if a.text()] for m in w.menuBar().findChildren(type(w.file_menu))}
file_items = [a.text() for a in w.file_menu.actions() if a.text()]
assert file_items == ["Import Video...", "Export dataset as zip...", "Import dataset zip...", "Download models from GitHub...", "Open in browser (tablet)..."], file_items
edit_items = [a.text() for a in w.edit_menu.actions() if a.text()]
assert edit_items == ["Classes...", "Hotkeys...", "My name...", "AI confidence..."], edit_items
for gone in ("Insert Assist Model", "Insert Scratch Model", "Publish to shared folder", "Import data to edit...", "Shared folder location...", "Models folder location...", "Dataset location...", "Import Gimble Session..."):
    assert gone not in file_items
# a box cannot be drawn without a class
INFO.clear()

# ---- 2. the project is a folder with its dataset inside: importing a video asks to save it first
vp = video("clip.mp4")
proj = os.path.join(TMP, "MyProj.annotator")
SAVE = {"path": proj}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
temp_dir = w.temp_root
qtk.ask_files = lambda *a, **k: [vp]
qtk.ask_int = lambda *a, **k: 1
SAVE["path"] = ""
w.import_video(); assert w.temp_root == temp_dir and not w.project.manifest["images"], "cancelled save: nothing imported"
SAVE["path"] = proj
w.import_video(); wait_job(w); pump(4)
assert w.temp_root is None and w.path == proj and os.path.isdir(proj) and not os.path.exists(temp_dir), (w.temp_root, w.path)
assert w.project.root == proj and w.title() == "MyProj" and len(w.project.manifest["images"]) == 12
assert os.path.isfile(os.path.join(proj, "manifest.json")) and json.load(open(os.path.join(proj, "manifest.json")))["format"] == "openpara-annotator"
assert os.listdir(os.path.join(proj, "images")), "the dataset is inside the project folder"

# ---- 3. classes are made by the user; AI assist gets one box per class
qtk.ask_string = lambda *a, **k: "rock"
w.manage_classes(); cd = w._dialogs["classes"]; cd.do_add()
qtk.ask_string = lambda *a, **k: "bush"; cd.do_add(); pump(4)
assert w.project.classes == ["rock", "bush"] and w.ai_box.count() == 2 and w.class_list.count() == 2
assert "classes" in [k for k in w._dialogs] and any("classes" in c for c in w.host.cards), w.host.cards     # the 'Opening ...' card

# ---- 4. annotate some frames, export a zip
ids = sorted(w.project.manifest["images"])
for i in ids[:6]:
    w.load_image(i); c = w.canvas
    w.on_canvas_release(c.width() / 2 - 60, c.height() / 2 - 40, c.width() / 2 + 60, c.height() / 2 + 40)
    w.confirm_current_as_is() if not w.project.is_annotated(i) else None
annotated = [i for i in ids if w.project.is_annotated(i)]
assert len(annotated) == 6, len(annotated)
zp = os.path.join(TMP, "share.zip")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (zp, ""))
w.export_zip(); wait_job(w)
assert os.path.isfile(zp) and any("Exported 6" in t for _n, _t, t in INFO), INFO
names = zipfile.ZipFile(zp).namelist()
assert "index.json" in names and sum(1 for n in names if n.startswith("images/")) == 6 and not any("dist" in n for n in names)
idx = json.loads(zipfile.ZipFile(zp).read("index.json")); assert idx["classes"] == ["rock", "bush"] and len(idx["images"]) == 6

# ---- 5. a second person's project merges the zip: classes by name, nothing twice
w2 = at.make_tab(None); w2.host = FakeHost(); w2.show(); pump(2)
qtk.ask_string = lambda *a, **k: "Other"
sz.CONFIG_PATH = os.path.join(TMP, "cfg2.json"); w2.cfg = {}; w2.me = None
proj2 = os.path.join(TMP, "Other.annotator"); SAVE["path"] = proj2
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (zp, ""))
w2.import_zip(); wait_job(w2); pump(6)
assert w2.temp_root is None and w2.path == proj2
assert w2.project.classes == ["rock", "bush"], w2.project.classes
n_img = len(w2.project.manifest["images"]); assert n_img == 6, n_img
assert any("Import complete" == t and "6 new" in x for _n, t, x in INFO), INFO[-3:]
# importing it again adds nothing
INFO.clear(); w2.import_zip(); wait_job(w2); pump(4)
assert len(w2.project.manifest["images"]) == 6 and any("Nothing new" in x or "0 new" in x or "identical" in x for _n, _t, x in INFO), INFO

# ---- 6. only YOU changed an image: kept silently.  Both changed it: your choice
iid = next(iter(w2.project.manifest["images"]))
w2.access_people = {info.get("owner_id") for info in w2.project.manifest["images"].values()}
w2.load_image(iid)
w2.boxes = [(1, 0.5, 0.5, 0.2, 0.2)]; w2.box_dist = [None]; w2._save_current_boxes()
INFO.clear(); w2.import_zip(); wait_job(w2); pump(4)            # the zip is the old version: mine changed, theirs did not
assert [b[0] for b in w2.project.get_boxes(iid)] == [1], w2.project.get_boxes(iid)
from PyQt6.QtWidgets import QMessageBox
asked = []
def fake_exec(self):
    asked.append(self.text()); self._pick = next(b for b in self.buttons() if b.text() == "Take the zip's")
QMessageBox.exec = fake_exec
QMessageBox.clickedButton = lambda self: self._pick
assert not asked, "a change only on my side is not a conflict"
# now the first person edits the same image differently and exports again
uid = w2.project.manifest["images"][iid]["uid"]
src_id = next(i for i, info in w.project.manifest["images"].items() if info.get("uid") == uid)
w.load_image(src_id); w.boxes = [(0, 0.3, 0.3, 0.1, 0.1)]; w.box_dist = [None]; w._save_current_boxes()
zp2 = os.path.join(TMP, "share2.zip")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (zp2, ""))
w.export_zip(); wait_job(w)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (zp2, ""))
INFO.clear(); w2.import_zip(); wait_job(w2); pump(4)
assert asked and "annotated differently" in asked[0], asked
assert any("replaced by the zip" in x for _n, _t, x in INFO), INFO
assert [b[0] for b in w2.project.get_boxes(iid)] == [0], w2.project.get_boxes(iid)

# ---- 7. models: the downloaded ones (GitHub folder) fill the AI box; nothing is built in
src = os.path.join(TMP, "m.pt"); open(src, "wb").write(b"x")
mdir = aw.models_dir()
os.makedirs(ml.folder_path(mdir, "assist"), exist_ok=True); os.makedirs(ml.folder_path(mdir, "scratch"), exist_ok=True)
ml.save_version(mdir, "assist", src, "n", "tester")
w2._models_changed()
labels = [w2.ai_choice.itemText(i) for i in range(w2.ai_choice.count())]
assert labels[0] == "No AI model" and any("Assist" in l for l in labels) and "Original helper model" not in labels, labels
assert mdir.startswith(os.environ["OPARA_USER_DIR"])

# ---- 8. add-ons put items in the File menu
ext.add_menu_item("annotator.file", "Import Gimble Session...", lambda win: INFO.append(("hook", win.title(), "")))
w3 = at.make_tab(proj2); w3.show()
acts = [a for a in w3.file_menu.actions() if a.text() == "Import Gimble Session..."]
assert len(acts) == 1
acts[0].trigger(); assert INFO[-1][0] == "hook"
assert w3.path == proj2 and w3.title() == "Other"

# ---- 9. an unsaved project that is closed is gone; one with content asks (is_dirty)
w4 = at.make_tab(None); tmp4 = w4.temp_root
w4.project.add_class("x"); assert w4.is_dirty()
w4.close(); assert not os.path.exists(tmp4)
print("OK annotator")
os._exit(0)
