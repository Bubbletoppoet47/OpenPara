"""Visualize (Render Studio): panel layout, Previs <-> Preview, camera view sync, video scrub bar, Preview lights, render-mode mapping."""
import os, tempfile
_ud = os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()     # a fresh copy of the add-on from addons_src (the others are left out: no downloads)
open(os.path.join(_ud, "addons.json"), "w").write('{"removed": ["partgen", "truss", "annotator", "annotator_gimble", "trainer", "simulation"]}')
import addons; addons.startup()   # the render module lives in an add-on
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import pm_model as pm, sk_tools as sk, gpd_app, render_studio as st
tmp = tempfile.mkdtemp()
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (60, 20)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="40")); d.rebuild()
pa = os.path.join(tmp, "plate.gpd"); open(pa, "w").write(d.to_json())
w = st.RenderStudio(); w.open_any(pa)
assert w.proj and len(w.bodies) == 1 and w.pl is not None
# ---- panel: numbered sections in order, the three big buttons
heads = [s_.head.text() for s_ in (w.s_scene, w.s_app, w.s_sun, w.s_spot, w.s_floor, w.s_cam, w.s_prev, w.s_out)]
for i, h in enumerate(heads, 1):
    assert f" {i} " in h, heads
assert [b.text() for b in (w.b_previs, w.b_preview, w.b_render)] == ["Previs", "Preview", "Render"]
assert not w.s_sun.head.isChecked() and not w.s_spot.head.isChecked() and not w.s_floor.head.isChecked(), "folded by default"
w.s_sun.refresh_summary(); assert w.s_sun.sum_lbl.text().startswith("Sun"), w.s_sun.sum_lbl.text()
assert [w.o_what.itemText(i) for i in range(w.o_what.count())][:3] == ["Selected camera", "All cameras", "Video (MP4)"]
assert w.b_stop.parent() is not None and w.run_btns == [w.b_render]
# ---- Previs <-> Preview toggling
assert w.mode == "previs" and w.b_previs.isChecked() and not w.b_preview.isChecked()
w.b_preview.click(); assert w.mode == "preview" and w.b_preview.isChecked() and not w.b_previs.isChecked()
w.b_previs.click(); assert w.mode == "previs" and w.b_previs.isChecked() and not w.b_preview.isChecked()
w.b_previs.click(); assert w.b_previs.isChecked(), "clicking the current mode keeps it"
# ---- camera view: panel combo and view-bar combo are one thing
w.cam_add_preset(); w.cam_add_preset()
n = len(w.proj["cameras"]); assert n >= 3 and w.vw_cam.count() == n + 1 and w.pv_cam.count() == n
assert w.view_cam == -1 and w.vw_cam.currentIndex() == 0 and w.rb_env.isChecked()
for mode in ("previs", "preview"):
    w.set_mode(mode)
    w.vw_cam.setCurrentIndex(2); w.vw_cam.activated.emit(2)            # second camera, from the view bar
    assert w.view_cam == 1 and w.pv_cam.currentIndex() == 1 and w.rb_cam.isChecked() and w.cur_cam == 1, (mode, w.view_cam)
    w.pv_cam.setCurrentIndex(0); w.pv_cam.activated.emit(0)            # first camera, from the panel
    assert w.view_cam == 0 and w.vw_cam.currentIndex() == 1
    pos = [round(x, 3) for x in w.pl.camera.position]
    assert pos == [round(x, 3) for x in w.proj["cameras"][0]["origin"]], pos
    w.rb_env.setChecked(True); assert w.view_cam == -1 and w.vw_cam.currentIndex() == 0
# ---- picture frame shown only when looking through a camera
w.set_view(0); w.pv_frame.setChecked(True); assert w.overlay.isVisibleTo(w.overlay.parent())
w.pv_frame.setChecked(False); assert not w.overlay.isVisibleTo(w.overlay.parent())
w.pv_frame.setChecked(True); w.set_view(-1); assert not w.overlay.isVisibleTo(w.overlay.parent())
# ---- scrub bar: hidden with fewer than 2 ticked cameras
w.show()
assert not w.has_track() and not w.scrub_bar.isVisibleTo(w)
for i in range(3):
    w.proj["cameras"][i]["anim"] = True
w.fill_cameras(); w.mark(); w.update_scrub_info()
assert w.has_track() and w.scrub_bar.isVisibleTo(w)
w.an_sec.setValue(8); w.an_fps.setValue(25)
w.sc_slider.setValue(500); assert w.pv_slider.value() == 500 and w.sc_time.text() == "4.0 s / 8.0 s" == w.pv_time.text(), w.sc_time.text()
mid = [round(x, 2) for x in w.pl.camera.position]
w.pv_slider.setValue(0); assert w.sc_slider.value() == 0
p0 = [round(x, 2) for x in w.pl.camera.position]
assert p0 != mid and p0 == [round(x, 2) for x in w.proj["cameras"][0]["origin"]], (p0, mid)
w.pv_slider.setValue(1000)
assert [round(x, 2) for x in w.pl.camera.position] == [round(x, 2) for x in w.proj["cameras"][2]["origin"]]
w.set_mode("preview"); w.pv_slider.setValue(300); assert w.view_cam == -2 and w.mode == "preview"
w.play_toggle(); assert w.play_timer.isActive(); w.play_toggle(); assert not w.play_timer.isActive()
# keyframe markers: first and last camera at the ends, in order; step and jump
ks = w.sc_slider.marks; assert len(ks) == 3 and ks[0] == 0.0 and ks[-1] == 1.0 and ks == sorted(ks), ks
w.scrub_to(0.0); w.step_key(1); assert abs(w.scrub_t - ks[1]) < 1e-9
w.step_key(1); assert abs(w.scrub_t - 1.0) < 1e-9; w.step_key(-1); assert abs(w.scrub_t - ks[1]) < 1e-9
w.sc_slider.jumped(2); assert w.scrub_t == 1.0
w.scrub_to(0.5); w.play_toggle(-1); assert w.play_timer.isActive() and w.play_dir == -1; w.play_step(); assert w.scrub_t < 0.5
w.play_toggle(-1); assert not w.play_timer.isActive()
# ---- layout: panel on the left, nothing at the bottom
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget
docks = w.findChildren(QDockWidget); assert len(docks) == 1 and w.dockWidgetArea(docks[0]) == Qt.DockWidgetArea.LeftDockWidgetArea, docks
assert not w.log.isVisibleTo(w) and w.b_stop.parent() is not None and w.bar.parent() is not None
w.log_btn.setChecked(True); assert w.log.isVisibleTo(w); w.log_btn.setChecked(False)
# ---- Preview draws (lit, helpers hidden) at all qualities; Previs keeps its helpers
w.set_view(-1); w.fl_on.setChecked(True); w.sun_shadows.setChecked(True)
def actors(): return len(w.pl.renderer.actors)
w.set_mode("previs"); na = actors()
for q in range(3):
    w.pv_qual.setCurrentIndex(q); w.set_mode("preview"); w.draw_scene()
    assert actors() < na, (q, actors(), na)       # no camera glyphs / labels / path / sun arrow
    assert len(w.pl.renderer.lights) >= 3, len(w.pl.renderer.lights)
w.set_mode("previs"); assert actors() == na
# ---- What-to-render mapping
calls = []
w.start_render = lambda mode: calls.append(mode)
for i, want in enumerate(("selected", "all", "video", "preview", "video_preview")):
    w.o_what.setCurrentIndex(i); w.b_render.click(); assert calls[-1] == want, (i, calls)
# ---- saved as a project folder with its own copy; reopened keeps the camera ticks and the video path
del w.start_render
fd = os.path.join(tmp, "t.gpv")
st.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (fd, ""))
assert w.save_project() and os.path.isfile(os.path.join(fd, "visualize.json")) and os.path.isfile(os.path.join(fd, "source", "plate.gpd"))
os.remove(pa)
w2 = st.RenderStudio(); w2.open_any(fd)
assert [c.get("anim") for c in w2.proj["cameras"]][:3] == [True] * 3 and w2.proj["anim"]["seconds"] == 8 and len(w2.bodies) == 1
w.shutdown(); w2.shutdown()
print("visualize studio OK")
