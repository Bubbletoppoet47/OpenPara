"""Sheets (dev_addons/sheets): the Media tab - Insert video takes an .mp4 or an .avi (an AVI is converted to an H.264 MP4, the original is not touched, with progress and
Cancel), the video is kept INSIDE the sheet file (once, byte for byte), shown as its first frame with a play button, played and paused with a click, scrubbed, looped
(a tick that is saved and undoable), moved / resized / duplicated / deleted like a picture, a big one is asked about, the panel, Export video, the .opsheet file
(save and open again, a file that lost the video bytes keeps the first frame), and the .xlsx export (the first frame and a note).

This test makes its videos with the ffmpeg that Sheets itself uses.   python test_sheets_media.py"""
import faulthandler
import os
import subprocess
import sys
import tempfile
import time

faulthandler.dump_traceback_later(280, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication([])
import sh_book as B
import sh_deps
import sh_media as M
import sh_picture as P
import sh_prefs
import sh_tab as TAB
import sh_xlsx

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


T = tempfile.mkdtemp(prefix="opara_sm_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
ASKED = []
ANSWER = [QMessageBox.StandardButton.Yes]
QMessageBox.question = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else ""), ANSWER[0])[1])
QMessageBox.warning = staticmethod(lambda *a, **k: ASKED.append(a[2] if len(a) > 2 else ""))
answers = {"open": "", "save": ""}
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (answers["open"], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (answers["save"], ""))
TAB.SheetsTab.AUTO_DOWNLOAD = False

EXE = sh_deps.ffmpeg_exe()
ok(EXE is not None, f"ffmpeg is found ({EXE})")


def make(name, args, secs=1.0, size="160x120", rate=15):
    path = os.path.join(T, name)
    r = subprocess.run([EXE, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=duration={secs}:size={size}:rate={rate}"] + args + [path],
                       capture_output=True, text=True)
    assert r.returncode == 0 and os.path.isfile(path), r.stderr
    return path


mp4 = make("good.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"])
avi = make("solidworks.avi", ["-c:v", "mpeg4"])
odd = make("odd.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv444p"], size="161x121")
mp4v = make("mpeg4_in_mp4.mp4", ["-c:v", "mpeg4"])
junk = os.path.join(T, "notavideo.mp4")
open(junk, "wb").write(b"this is just text, not a video" * 20)


def info_of(data):
    p = os.path.join(T, "probe.mp4")
    open(p, "wb").write(data)
    return M.probe(EXE, p)


# ------------------------------------------------------------------------------------------------ making a file ready
raw = open(mp4, "rb").read()
r = M.prepare(mp4)
ok(not r["converted"] and r["mp4"] == raw, "an H.264 MP4 is stored as it is, byte for byte")
img = QImage.fromData(r["poster"])
ok(not img.isNull() and (img.width(), img.height()) == (160, 120) and (r["w"], r["h"]) == (160, 120), f"its first frame is a {img.width()} x {img.height()} picture")
ok(0.8 < r["duration"] < 1.3, f"the duration is read: {r['duration']:.2f} s")
before = (os.path.getsize(avi), os.path.getmtime(avi), open(avi, "rb").read())
seen = []
r = M.prepare(avi, progress=seen.append)
i = info_of(r["mp4"])
ok(r["converted"] and r["mp4"][4:8] == b"ftyp" and i["codec"] == "h264" and i["pix"] == "yuv420p", f"an AVI becomes an H.264 MP4 (yuv420p): {i['codec']}, {i['pix']}, {len(r['mp4'])} bytes")
ok((i["w"], i["h"]) == (160, 120) and 0.8 < i["duration"] < 1.3, f"same size and length: {i['w']} x {i['h']}, {i['duration']:.2f} s")
ok(before == (os.path.getsize(avi), os.path.getmtime(avi), open(avi, "rb").read()), "the AVI file itself is not touched")
ok(seen and seen[-1] == 1.0 and all(0.0 <= x <= 1.0 for x in seen), f"progress is reported and ends at 100 %: {[round(x, 2) for x in seen][:5]} ...")
r = M.prepare(odd)
i = info_of(r["mp4"])
ok(r["converted"] and i["pix"] == "yuv420p" and i["w"] % 2 == 0 and i["h"] % 2 == 0, f"an MP4 that would not play everywhere (yuv444p, odd sides) is converted too: {i['w']} x {i['h']} {i['pix']}")
r = M.prepare(mp4v)
ok(r["converted"] and info_of(r["mp4"])["codec"] == "h264", "an MP4 that holds another codec is converted")
for why, call, words in (("a file that is not a video", lambda: M.prepare(junk), ("not a video",)),
                         ("a file that is gone", lambda: M.prepare(os.path.join(T, "gone.avi")), ("not there",))):
    try:
        call()
        ok(False, f"{why} must be refused")
    except M.MediaError as ex:
        ok(all(w in str(ex) for w in words), f"{why} is refused in words: {ex}")
try:
    M.prepare(avi, cancel=lambda: True)
    ok(False, "Cancel must stop the conversion")
except M.Cancelled:
    ok(True, "Cancel stops a conversion")
M.MAX_BYTES = 1000
try:
    M.prepare(mp4)
    ok(False, "a video over the limit must be refused")
except M.MediaError as ex:
    ok("too much" in str(ex), f"a video over the limit is refused: {str(ex)[:90]}")
M.MAX_BYTES = 250_000_000

# ------------------------------------------------------------------------------------------------ the window
sh_ok = TAB.make_tab()
t = TAB.make_tab()
t.resize(1300, 800)
t.show()
app.processEvents()
names = [t.ribbon.tabText(k) for k in range(t.ribbon.count())]
ok(names == ["Home", "Data", "Charts", "Media", "Import", "Engineering", "View"], f"the ribbon tab is called Media: {names}")
page = t.ribbon.widget(names.index("Media"))
from PyQt6.QtWidgets import QToolButton
labels = [b.text().replace("\n", " ") for b in page.findChildren(QToolButton)]
ok("Insert image" in labels and "Insert video" in labels, f"Insert image and Insert video are in it: {labels}")
ok(all(m in labels for m in ("Edit media", "Copy media", "Export media", "Delete media")), "and the buttons for the selected image or video")

# Insert video: one dialog, an AVI
answers["open"] = avi
grid = t.grid
t.video_new()
s = grid.sheet_obj()
ok(len(s.pictures) == 1 and s.pictures[0].get("video"), f"Insert video with an AVI puts a video on the sheet")
pic = s.pictures[0]
ok(pic["video"] in t.wb.images and pic["image"] in t.wb.images and pic["loop"] is False and info_of(t.wb.images[pic["video"]])["codec"] == "h264",
   "the MP4 and the first frame are stored in the workbook")
f = grid.pframes[pic["id"]]
ok(isinstance(f, M.VideoFrame) and f.bar.isVisible() or not f.bar.isHidden(), "the frame is a video frame with its bar")
ok(grid.sel_picture == pic["id"], "and it is picked")
n_bytes = len(t.wb.images[pic["video"]])

# undo / redo
t.wb.undo()
ok(not s.pictures, "undo takes the video off")
t.wb.redo()
ok(len(s.pictures) == 1 and s.pictures[0]["video"] == pic["video"], "redo puts it back (the undo steps carry only the key)")
grid.refresh_pictures()
pic = s.pictures[0]
f = grid.pframes[pic["id"]]

# playing
ok(f.player is None and not f.playing, "nothing is opened until the first click (a sheet full of videos costs nothing)")
f.toggle()
deadline = time.time() + 15
while time.time() < deadline and not (f.img is not None and f.pos_ms > 0):
    app.processEvents()
    time.sleep(0.02)
ok(f.playing and f.img is not None, f"a click plays it: the player's frames arrive ({f.img.width() if f.img is not None else None} px wide)")
ok(f.img is not None and (f.img.width(), f.img.height()) == (160, 120), "and they are the video's own size")
ok(f.pos_ms > 0 and 800 < f.dur_ms < 1300, f"the position moves ({f.pos_ms} ms of {f.dur_ms} ms)")
deadline = time.time() + 8
while time.time() < deadline and f.playing:
    app.processEvents()
    time.sleep(0.02)
ok(not f.playing and f.pos_ms >= f.dur_ms - 100, f"without Loop it stops at the end ({f.pos_ms} ms)")
f.toggle()
deadline = time.time() + 8
while time.time() < deadline and not (f.playing and 0 < f.pos_ms < f.dur_ms - 200):
    app.processEvents()
    time.sleep(0.02)
ok(f.playing and f.pos_ms < f.dur_ms - 100, f"and a click plays it again from the start ({f.pos_ms} ms)")
f.pause()
p0 = f.pos_ms
for _ in range(15):
    app.processEvents()
    time.sleep(0.02)
ok(not f.playing and abs(f.pos_ms - p0) < 150, "pause holds it")
f.scrub(500)
for _ in range(25):
    app.processEvents()
    time.sleep(0.02)
ok(abs(f.pos_ms - f.dur_ms // 2) < 200, f"the scrubber moves to the middle ({f.pos_ms} ms of {f.dur_ms} ms)")
f.scrub(0)
for _ in range(25):
    app.processEvents()
    time.sleep(0.02)
ok(f.pos_ms < 100, f"and back to the start ({f.pos_ms} ms): the first frame is shown again")

# loop
f.loop_cb.setChecked(True)
ok(grid.sheet_obj().pictures[0]["loop"] is True, "the Loop tick is saved in the picture")
t.wb.undo()
grid.refresh_pictures()
f.sync()
ok(grid.sheet_obj().pictures[0]["loop"] is False and not f.loop_cb.isChecked(), "and undoable")
t.wb.redo()
f.sync()
ok(f.loop_cb.isChecked(), "and redoable")
f.toggle()
t0 = time.time()
wrapped = False
last = 0
while time.time() - t0 < 4.0:
    app.processEvents()
    time.sleep(0.02)
    if f.pos_ms < last - 400:
        wrapped = True
    last = f.pos_ms
ok(wrapped and f.playing, "with Loop it starts again by itself when it ends and keeps playing")
f.pause()

# the mouse: a click plays and pauses, a drag moves and does not
from PyQt6.QtCore import QPoint
from PyQt6.QtTest import QTest
pic = grid.sheet_obj().pictures[0]
f = grid.pframes[pic["id"]]
f.place()
f.pause()
cx = QPoint(f.width() // 2, max(8, (f.height() - M.VideoFrame.BAR) // 2))
QTest.mouseClick(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cx)
ok(f.playing, "a click on the video plays it")
QTest.mouseClick(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cx)
ok(not f.playing, "and the next click pauses it")
x0, y0 = pic["pos"]
QTest.mousePress(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, cx)
QTest.mouseMove(f, QPoint(cx.x() + 40, cx.y() + 25))
QTest.mouseRelease(f, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(cx.x() + 40, cx.y() + 25))
pic = grid.sheet_obj().pictures[0]
ok(not f.playing and (pic["pos"][0] > x0 or pic["pos"][1] > y0), f"a drag moves it ({x0:.0f}, {y0:.0f}) -> ({pic['pos'][0]:.0f}, {pic['pos'][1]:.0f}) and does not play it")
t.wb.undo()
ok(grid.sheet_obj().pictures[0]["pos"] == [x0, y0], "and the move is one undo step")
t.wb.redo()
QTest.mouseClick(f.btn, Qt.MouseButton.LeftButton)
ok(f.playing, "the play button of the bar plays it too")
QTest.mouseClick(f.btn, Qt.MouseButton.LeftButton)
ok(not f.playing, "and pauses it")
shot = f.grab()
ok(not shot.isNull() and shot.width() == f.width(), "the frame can be drawn (first frame with the play button, bar at the bottom)")
shot.save(os.path.join(T, "frame.png"))

# move / resize like a picture; duplicate; cut is refused
pic = grid.sheet_obj().pictures[0]
c2 = grid.duplicate_picture(pic["id"])
ok(c2 is not None and c2["video"] == pic["video"] and c2["image"] == pic["image"] and c2["loop"] is True, "Duplicate copies the video (the bytes stay stored once)")
ok(len({k for k in t.wb.images}) == 2, f"two entries in the workbook for two videos: first frame and MP4 ({len(t.wb.images)})")
grid.pick_picture(pic["id"])
msgs = []
grid.message.connect(lambda m, k: msgs.append(m))
grid.copy_picture(cut=True)
ok(len(grid.sheet_obj().pictures) == 2 and any("cannot be cut" in m for m in msgs), "Ctrl+X on a video is refused: the clipboard would only keep the first frame")
grid.copy_picture(cut=False)
ok(any("first frame" in m for m in msgs), "Ctrl+C copies the first frame as a picture, and says so")
fd = grid.pframes[c2["id"]]
grid.delete_picture(c2["id"])
app.processEvents()
ok(c2["id"] not in grid.pframes and fd.player is None, "Delete takes the video away and stops its player")

# the panel
t.picture_edit(pic["id"])
pp = t.pic_panel
ok(pp is not None and pp.heading.text() == "Video" and not pp.loop.isHidden() and pp.loop.isChecked() and "Delete video" in pp.delete_btn.text(), "the panel says Video and has the Loop tick")
pp.loop.setChecked(False)
ok(grid.sheet_obj().pictures[0]["loop"] is False, "Loop in the panel is the same Loop")
pp.w.setValue(200)
ok(grid.sheet_obj().pictures[0]["size"][0] == 200, "the size can be set in the panel as for a picture")

# export the video
answers["save"] = os.path.join(T, "out.mp4")
t.picture_export(pic["id"])
ok(open(answers["save"], "rb").read() == t.wb.images[pic["video"]], "Export media saves the video as an MP4 file, byte for byte")

# the file: save, open again
path = os.path.join(T, "movies.opsheet")
t.wb.save(path)
wb2 = B.Workbook.load(path)
p2 = wb2.sheets[0].pictures[0]
ok(wb2.images[p2["video"]] == t.wb.images[pic["video"]] and wb2.images[p2["image"]] == t.wb.images[pic["image"]], f"the sheet file carries the video byte for byte ({os.path.getsize(path) / 1e3:.0f} kB file)")
ok(p2.get("loop") is False and p2["dur"] > 0.5 and p2["video"] == pic["video"], "and its Loop and length")
import json
d = json.load(open(path, encoding="utf-8"))
d["images"].pop(p2["video"])
open(os.path.join(T, "lost.opsheet"), "w", encoding="utf-8").write(json.dumps(d))
wb3 = B.Workbook.load(os.path.join(T, "lost.opsheet"))
ok(len(wb3.sheets[0].pictures) == 1 and "video" not in wb3.sheets[0].pictures[0], "a file that lost the video's bytes still has its first frame, as a picture")
t2 = TAB.make_tab()
t2.resize(1300, 800)
t2.show()
t2.open_path(path)
app.processEvents()
g2 = t2.grid
ok(isinstance(g2.pframes[p2["id"]], M.VideoFrame), "opened again, it is a video again")
f2 = g2.pframes[p2["id"]]
f2.toggle()
deadline = time.time() + 15
while time.time() < deadline and f2.img is None:
    app.processEvents()
    time.sleep(0.02)
ok(f2.img is not None, "and it plays")
f2.release()

# an Excel file
xl = os.path.join(T, "movies.xlsx")
notes = sh_xlsx.export_xlsx(t.wb, xl)
import openpyxl
x = openpyxl.load_workbook(xl)
ws = x.worksheets[0]
cm = [c.comment.text for row in ws.iter_rows() for c in row if c.comment]
ok(len(ws._images) == 1 and any("first frame" in m and "Excel cannot play" in m for m in cm), f"Excel gets the first frame as a picture and a note in its cell: {cm[:1]}")

# a big video is asked about
M.WARN_BYTES = 1000
ASKED.clear()
ANSWER[0] = QMessageBox.StandardButton.No
n = len(grid.sheet_obj().pictures)
ok(t.video_from_file(mp4) is None and len(grid.sheet_obj().pictures) == n and any("stored inside the sheet file" in a for a in ASKED), "a big video is asked about, and No adds nothing")
ANSWER[0] = QMessageBox.StandardButton.Yes
ok(t.video_from_file(mp4) is not None and len(grid.sheet_obj().pictures) == n + 1, "and Yes adds it")
M.WARN_BYTES = 50_000_000
ok(M.WARN_BYTES == 50_000_000 and M.MAX_BYTES == 250_000_000, "warning at 50 MB, nothing over 250 MB")

# no ffmpeg
real = sh_deps.ffmpeg_exe
sh_deps.ffmpeg_exe = lambda: None
n = len(grid.sheet_obj().pictures)
ok(t.video_from_file(mp4) is None and len(grid.sheet_obj().pictures) == n and "ffmpeg" in t.status.text(), "without ffmpeg it says so and adds nothing")
sh_deps.ffmpeg_exe = real

# a video that is not one
ASKED.clear()
ok(t.video_from_file(junk) is None and any("not a video" in a for a in ASKED), "a file that is not a video says so in a window and adds nothing")

# ------------------------------------------------------------------------------------------------ the same id on several sheets
# A picture's id is only its number on ITS sheet: the first picture of every sheet is "pic1".  A frame that was kept by id alone was shown for the
# "pic1" of another sheet: a video turned into a photo that does nothing, a photo showed (and played) a video that was never put on its sheet.
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QColor


def photo_data(color):
    im = QImage(120, 80, QImage.Format.Format_RGB32)
    im.fill(QColor(color))
    ba = QByteArray()
    b_ = QBuffer(ba)
    b_.open(QIODevice.OpenModeFlag.WriteOnly)
    im.save(b_, "PNG")
    return bytes(ba), im


def wait(cond, secs=8.0):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    app.processEvents()
    return bool(cond())


def centre(f):
    img = f.grab().toImage()
    return img.pixelColor(img.width() // 2, 8).name()


mp4b = make("second.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"], secs=1.2, size="128x96", rate=10)
t3 = TAB.make_tab()
t3.resize(1300, 800)
t3.show()
app.processEvents()
g3, wb3 = t3.grid, t3.wb
N1 = wb3.sheet_names()[0]
ok(t3.video_from_file(mp4) is not None, "sheet 1: a video")
wb3.add_sheet()
N2 = wb3.sheet_names()[1]
g3.set_sheet(N2)
d_, im_ = photo_data("#00aa00")
wb3.add_picture(N2, P.new_picture(wb3, N2, d_, im_, "green", (10, 10)))
g3._sync_pictures()
wb3.add_sheet()
N3 = wb3.sheet_names()[2]
g3.set_sheet(N3)
ok(t3.video_from_file(mp4b) is not None, "sheet 3: another video")
wb3.add_sheet()
N4 = wb3.sheet_names()[3]
g3.set_sheet(N4)
d_, im_ = photo_data("#aa00aa")
wb3.add_picture(N4, P.new_picture(wb3, N4, d_, im_, "purple", (10, 10)))
g3._sync_pictures()
wb3.add_sheet()
N5 = wb3.sheet_names()[4]
g3.set_sheet(N5)
d_, im_ = photo_data("#aa6600")
wb3.add_picture(N5, P.new_picture(wb3, N5, d_, im_, "orange", (10, 10)))
g3._sync_pictures()
names3 = [N1, N2, N3, N4, N5]
ok(all(wb3.get_sheet(n).pictures[0]["id"] == "pic1" for n in names3), "every one of the five sheets has its picture under the same id, pic1")
want_colour = {N2: "#00aa00", N4: "#aa00aa", N5: "#aa6600"}
bad = []
for rnd in range(2):                                              # forward, then backwards: every sheet shows its own picture, every time
    for n in (names3 if rnd == 0 else list(reversed(names3))):
        g3.set_sheet(n)
        app.processEvents()
        pic3 = wb3.get_sheet(n).pictures[0]
        f = g3.pframes.get("pic1")
        is_vid = bool(pic3.get("video"))
        if f is None or isinstance(f, M.VideoFrame) != is_vid or len(g3.pframes) != 1:
            bad.append(f"{n}: {type(f).__name__ if f is not None else None}, {len(g3.pframes)} frames")
        elif is_vid and f.kind != pic3["video"]:
            bad.append(f"{n}: a video that is not its own")
        elif not is_vid and centre(f) != want_colour[n]:
            bad.append(f"{n}: shows {centre(f)} and not {want_colour[n]}")
ok(not bad, f"each sheet shows its own picture or video, going forward and backwards ({bad})")
seen_ids = set()
for n in names3:
    g3.set_sheet(n)
    seen_ids.add(id(g3.pframes["pic1"]))
ok(len(seen_ids) >= 3, "a frame is never carried over from one sheet to the next")

# the video of sheet 1 plays ITS video, the one of sheet 3 plays its own
for n, vid_path in ((N3, mp4b), (N1, mp4)):
    g3.set_sheet(n)
    f = g3.pframes["pic1"]
    f.toggle()
    ok(wait(lambda: f.img is not None), f"{n}: the video plays and its frames arrive")
    key = wb3.get_sheet(n).pictures[0]["video"]
    ok(f.player is not None and key in f.player.source().toLocalFile(), f"{n}: and it is that sheet's own video that is playing")
    ok(abs(f.img.width() - (128 if n == N3 else 160)) <= 1, f"{n}: with its own picture size ({f.img.width()} px wide)")
    f.pause()
g3.set_sheet(N4)
f4 = g3.pframes["pic1"]
ok(type(f4).__name__ == "PictureFrame" and centre(f4) == "#aa00aa" and not hasattr(f4, "toggle"), "the purple photo is still a photo after the videos were played")

# a playing video is not interrupted by work on its own sheet
g3.set_sheet(N1)
f1 = g3.pframes["pic1"]
f1.play()
ok(wait(lambda: f1.playing and f1.img is not None), "sheet 1: playing again")
wb3.set_raw(N1, 3, 3, "hello")
wb3.add_sheet()
app.processEvents()
ok(g3.pframes.get("pic1") is f1 and f1.player is not None, "typing in a cell and adding a sheet do not take the video away (the same widget goes on)")
f1.pause()

# undo and redo of a video's removal on its own sheet
g3.delete_picture("pic1")
app.processEvents()
ok(not g3.pframes, "the video is deleted from sheet 1")
wb3.undo()
app.processEvents()
f1b = g3.pframes.get("pic1")
ok(f1b is not None and isinstance(f1b, M.VideoFrame) and f1b.kind == wb3.get_sheet(N1).pictures[0]["video"], "undo brings it back as a video that can be played")
# a sheet with a photo after one with a video: each has its own widget
g3.set_sheet(N3)
ok(isinstance(g3.pframes["pic1"], M.VideoFrame), "sheet 3 shows its video")
g3.set_sheet(N2)
ok(type(g3.pframes["pic1"]).__name__ == "PictureFrame" and centre(g3.pframes["pic1"]) == "#00aa00", "and sheet 2 its green photo")

print("FAILED:" if FAILS else "OK sheets media", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
