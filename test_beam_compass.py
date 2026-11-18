"""1D FEA: the X / Y compass in the bottom-left corner of the drawing (X to the right, Y up, the angle convention), always on, also in the
exported pictures; and the compass is not there before a sketch is chosen."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc, beam_tab, profiles1d


class Win:
    doc = None
    def sketch_list(self): return []
    def status(self, t): pass


def pixels(cv):
    q = cv.grab().toImage().convertToFormat(__import__("PyQt6.QtGui", fromlist=["QImage"]).QImage.Format.Format_RGBA8888)
    w, h = q.width(), q.height()
    return np.frombuffer(bytes(q.constBits().asarray(q.sizeInBytes())), np.uint8).reshape(h, q.bytesPerLine() // 4, 4)[:, :w, :3].astype(int)


def count(img, rgb, box, tol=60):
    y0, y1, x0, x1 = box
    d = np.abs(img[y0:y1, x0:x1] - np.array(rgb)).sum(axis=2)
    return int((d < tol).sum())


b = beam_tab.BeamTab(Win()); b.resize(1100, 700); b.show(); app.processEvents()
cv = b.canvas
img = pixels(cv)
H = img.shape[0]
red, green = (214, 39, 40), (44, 160, 44)
assert count(img, red, (H - 60, H, 0, 90)) == 0 and count(img, green, (H - 60, H, 0, 90)) == 0, "no compass before a sketch is chosen"

bm = sc.Model(); q = [bm.add_point(0, 0), bm.add_point(1000, 0)]; bm.add_line(q[0], q[1])
b.set_model(bm, "cantilever"); b.set_profiles([0], profiles1d.compute("rect", {"b": 20.0, "h": 40.0}))
b.supports = [{"mode": "fixed", "targets": [q[0]]}]
b.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[1]]}]
b.solve(); cv.fit(); app.processEvents()
img = pixels(cv)
H = img.shape[0]
corner = (H - 60, H, 0, 70)
nx = count(img, red, (H - 40, H - 8, 20, 70))                  # the X arrow lies along the bottom, to the right of the origin
ny = count(img, green, (H - 70, H - 20, 10, 40))               # the Y arrow rises from the origin
assert nx > 20 and ny > 20, (nx, ny)
# X points right and Y points up: the red pixels are right of the green ones, the green ones are above the red ones
ys, xs = np.nonzero(np.abs(img[H - 70:H, 0:80] - np.array(red)).sum(axis=2) < 60)
yg, xg = np.nonzero(np.abs(img[H - 70:H, 0:80] - np.array(green)).sum(axis=2) < 60)
assert xs.mean() > xg.mean() and yg.mean() < ys.mean(), "X to the right, Y up"
# it stays put when the view is panned / zoomed, and it is in an exported frame
cv.scale *= 1.7; cv.update(); app.processEvents()
img2 = pixels(cv)
assert count(img2, red, (H - 40, H - 8, 20, 70)) > 20 and count(img2, green, (H - 70, H - 20, 10, 40)) > 20
print("OK beam compass")
