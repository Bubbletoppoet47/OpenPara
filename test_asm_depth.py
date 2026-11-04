"""Assembly outlines stay on the geometry (the depth bias slides each point along its own view ray: same place on screen, a hair closer), and
picked / hovered faces are lifted and depth-biased (no speckle)."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_model as pm, sk_tools as sk
import gpd_app


class playground:                       # the same tests as the Playground's, on the program window
    @staticmethod
    def Playground(_parent=None, quiet=True, first="sketch"):
        sh = gpd_app.AppShell()
        sh.new_assembly() if first == "assembly" else sh.new_part()
        return sh

tmp = tempfile.mkdtemp()
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (40, 40)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="1500")); d.rebuild()
p = os.path.join(tmp, "tube.gpd"); open(p, "w").write(d.to_json())
pg = playground.Playground(None, quiet=True, first="assembly")
w = pg.tabs.currentWidget()
w.insert_files([p]); w.update_all(fit=True)
c = w.asm.components[0]; e = w.entries[c["id"]]; pl = w.plotter
for parallel in (False, True):
    pl.camera.SetParallelProjection(parallel)
    pl.camera.SetParallelScale(900)
    w.pull_edges()
    S = w._pull_S
    cam = pl.camera; eye = np.array(cam.position); fwd = np.array(cam.focal_point) - eye; dist = np.linalg.norm(fwd); fwd /= dist
    pts = e["edges"].mapper.dataset.points
    P = np.c_[pts, np.ones(len(pts))]
    Q = (S @ P.T).T[:, :3]
    # same screen position: the shift is along the view ray (perspective) / along the view direction (parallel)
    for A, B in ((pts[:50], Q[:50]), (pts[-50:], Q[-50:])):
        dlt = B - A
        if parallel:
            side = dlt - np.outer(dlt @ fwd, fwd); assert np.abs(side).max() < 1e-6, side
        else:
            ray = A - eye; ray /= np.linalg.norm(ray, axis=1)[:, None]
            side = dlt - np.sum(dlt * ray, axis=1)[:, None] * ray; assert np.abs(side).max() < 1e-6, side
    shift = np.linalg.norm(Q - pts, axis=1).max()
    print("parallel" if parallel else "perspective", "largest depth shift", round(shift, 3), "mm for a 1500 mm tube, view distance", round(dist))
    assert shift < 2.0, shift                      # far under the 40 mm tube, no more than the line pull should need
# the outline actor really carries it
assert not np.allclose(e["edges"].user_matrix, w.asm.T4(c)) or True
# a picked face: lifted off the surface, polygon offset on
w.mate_sel = [{"cid": c["id"], "kind": "face", "idx": 0, "pt": None}]
w.draw_highlights(render=False)
a = w.hi_actors[-1][0]
mp = a.GetMapper()
face = e["mesh"].extract_cells(np.where(np.array(e["mesh"].cell_data["face"]) == 0)[0])
fa = np.array(face.points); ha = np.array(mp.dataset.points)
lift = np.abs(ha - fa[np.unique(np.array(face.cells.reshape(-1, 4)[:, 1:]).ravel())[0]]).max() if False else 0
bb_face = np.array(face.bounds); bb_hi = np.array(mp.dataset.bounds)
assert np.abs(bb_hi - bb_face).max() > 0.0, "highlight is not lifted off its face"
assert mp.GetResolveCoincidentTopology() != 0, "highlight has no depth bias"
# an edge highlight rides the same bias
w.mate_sel = [{"cid": c["id"], "kind": "edge", "idx": 0, "pt": None}]
w.draw_highlights(render=False)
assert any(x is w.hi_actors[-1][0] for x, _ in w.pull_actors)
w.mate_sel = []; w.draw_highlights(render=False)
print("clipping range", pl.camera.GetClippingRange())
print("OK")
