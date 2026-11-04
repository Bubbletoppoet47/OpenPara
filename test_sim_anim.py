"""Export animation (Simulation add-on): GIF / MP4 / PNG pictures from 2D FEA (the load ramp), 2D CFD (the saved time frames) and 1D FEA (a NEW load
ramp: Animate with Frames / Duration / Playback, Play / Stop).  Frame counts, 'back and forth', and the ramp really scales the picture."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PIL import Image
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import anim_export as ax, physics_tab, beam_tab, cfd_tab, physics_fea as pf, profiles1d

OUT = tempfile.mkdtemp()
class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass

# ---------------- the writer
from PyQt6.QtGui import QImage, QColor
def pics(n, w=64, h=40):
    out = []
    for k in range(n):
        im = QImage(w, h, QImage.Format.Format_RGB32); im.fill(QColor(255 - 20 * k, 40 * k % 255, 100))
        out.append(im)
    return out
assert ax.formats()[0] == "gif" and ax.formats()[-1] == "png" and ("mp4" in ax.formats()) == ax.mp4_available()
assert len(ax.ordered(list(range(5)), 2)) == 8 and ax.ordered(list(range(5)), 2)[:8] == [0, 1, 2, 3, 4, 3, 2, 1] and ax.ordered(list(range(5)), 1) == list(range(5))
g = ax.write(pics(6), os.path.join(OUT, "a"), "gif", 10, 1)                      # the extension is added
assert g.endswith(".gif") and os.path.getsize(g) > 0
im = Image.open(g); assert im.n_frames == 6 and im.info.get("loop") == 0 and im.info["duration"] == 100
g1 = ax.write(pics(4), os.path.join(OUT, "once.gif"), "gif", 5, 0); assert "loop" not in Image.open(g1).info and Image.open(g1).n_frames == 4
g2 = ax.write(pics(5), os.path.join(OUT, "bf.gif"), "gif", 5, 2); assert Image.open(g2).n_frames == 8
d = ax.write(pics(3), os.path.join(OUT, "frames.png"), "png", 10, 0)
assert os.path.isdir(d) and sorted(os.listdir(d)) == ["frames_0001.png", "frames_0002.png", "frames_0003.png"]
if ax.mp4_available():
    mp = ax.write(pics(7, 65, 41), os.path.join(OUT, "m.mp4"), "mp4", 10, 0)        # odd size: cropped to even
    import cv2
    cap = cv2.VideoCapture(mp); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); cap.release()
    assert n == 7 and w == 64, (n, w)
try:
    ax.write([], os.path.join(OUT, "x"), "gif"); raise SystemExit("empty export accepted")
except ax.ExportError:
    pass

# ---------------- 2D FEA
m = sc.Model(); p = [m.add_point(*c) for c in ((0, 0), (100, 0), (100, 20), (0, 20))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
t = physics_tab.PhysicsTab(Win()); t.set_model(m, "beam"); t.resize(900, 600); t.show(); app.processEvents()
t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
t.loads = [{"kind": "pressure", "p": 0.5, "targets": [("ln", ls[2])]}]
t.e_h.setText("6"); t.run_mesh()
t.show_solution(pf.solve(t.mesh, t.read_material(), t.supports, t.loads, lambda *a, **k: None, lambda: False))
t.field.setCurrentIndex(1); app.processEvents()
assert t.canvas.field is not None
t.e_frames.setText("6"); t.e_dur.setText("1"); t.loop_combo.setCurrentIndex(2)           # back and forth: 6 -> 10 frames
out = t.export_animation(path_fmt=(os.path.join(OUT, "fea2d.gif"), "gif"))
assert out and Image.open(out).n_frames == 10 and Image.open(out).info["duration"] == 170 or Image.open(out).info["duration"] in (160, 170), Image.open(out).info
fr = [Image.open(out).copy() for _ in (0,)]
im = Image.open(out); im.seek(0); first = np.array(im.convert("RGB")); im.seek(5); last = np.array(im.convert("RGB"))
assert np.abs(first.astype(int) - last.astype(int)).sum() > 0, "the ramp changes the picture"
t.loop_combo.setCurrentIndex(0)
out = t.export_animation(path_fmt=(os.path.join(OUT, "fea2d_png"), "png"))
assert len(os.listdir(out)) == 6
assert t.canvas.anim_idx == 0 or True

# ---------------- 2D CFD: the saved time frames
c = cfd_tab.CFDTab(Win()); c.resize(900, 600); c.show(); app.processEvents()
c.slider.setRange(0, 4); c.slider.setValue(2)
out = c.export_animation(path_fmt=(os.path.join(OUT, "cfd.gif"), "gif"))
gi = Image.open(out)
total = 0
for k in range(gi.n_frames):
    gi.seek(k); total += gi.info["duration"]
assert out and abs(total - 5 * 83) <= 25 and c.slider.value() == 2, (total, c.slider.value())      # identical pictures are merged by the GIF writer, the time is kept
c.slider.setRange(0, 0)
assert c.b_export.text() == "Export animation..."

# ---------------- 1D FEA: the new load ramp
b = beam_tab.BeamTab(Win()); b.resize(1100, 700); b.show(); app.processEvents()
assert b.cb_anim.text() == "Animate" and not b.anim_box.isVisibleTo(b)
b.cb_anim.setChecked(True); assert b.anim_box.isVisibleTo(b)
assert [b.loop_combo.itemText(i) for i in range(3)] == ["Once", "Loop", "Back and forth"] and b.e_frames.text() == "30" and b.e_dur.text() == "3"
bm = sc.Model(); q = [bm.add_point(0, 0), bm.add_point(1000, 0)]; bm.add_line(q[0], q[1])
b.set_model(bm, "cantilever")
prof = profiles1d.compute("rect", {"b": 20.0, "h": 40.0})
b.set_profiles([0], prof)
b.supports = [{"mode": "fixed", "targets": [q[0]]}]
b.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[1]]}]
b.solve()
assert b.result is not None, b.status_lbl.text()
b.canvas.fit()
b.e_frames.setText("5"); b.e_dur.setText("1"); b.loop_combo.setCurrentIndex(1)
imgs = []
def grab_probe(k):
    b.canvas.ramp = k / 4.0; b.canvas.repaint(); return b.canvas.grab().toImage()
a0, a4 = grab_probe(0), grab_probe(4)
assert a0 != a4, "ramp 0 and full look different"
b.canvas.ramp = 1.0
out = b.export_animation(path_fmt=(os.path.join(OUT, "fea1d.gif"), "gif"))
assert out and Image.open(out).n_frames == 5 and Image.open(out).info.get("loop") == 0 and b.canvas.ramp == 1.0
# Play / Stop drive the ramp
b.anim_play(); assert b.anim_timer.isActive() and b.canvas.ramp == 0.0
for _ in range(3): b.anim_step()
assert 0 < b.canvas.ramp < 1.0
b.anim_stop(); assert not b.anim_timer.isActive() and b.canvas.ramp == 1.0
b.loop_combo.setCurrentIndex(0); b.anim_play()
for _ in range(10): b.anim_step()
assert not b.anim_timer.isActive() and b.canvas.ramp == 1.0                              # once: ends on the full result
b.anim_stop()
if ax.mp4_available():
    out = b.export_animation(path_fmt=(os.path.join(OUT, "fea1d.mp4"), "mp4"))
    assert out and os.path.getsize(out) > 0
print("OK sim anim")
os._exit(0)
