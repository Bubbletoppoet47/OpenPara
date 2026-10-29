import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, sys, time, tempfile
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"/tmp/claude-0/-home-claude/185fe3ec-3984-59f4-ac61-89b69f00ea6d/scratchpad/gpd")
sys.path.insert(0,os.getcwd())
from PyQt6.QtWidgets import QApplication, QMessageBox
app=QApplication([])
QMessageBox.question=staticmethod(lambda *a,**k: QMessageBox.StandardButton.Yes)
QMessageBox.warning=staticmethod(lambda *a,**k: print("WARN",a[2:]))
import render_studio as st
w=st.RenderStudio()
w.open_any("/tmp/rs_samples/asm.gpa")
assert w.proj and len(w.bodies)==2 and len(w.proj["cameras"])==2
print("bodies", [b[0] for b in w.bodies], "pl", w.pl is not None)
# edit things through the controls
w.sun_time.setTime(w.sun_time.time().addSecs(3600)); w.sun_shadows.setChecked(True)
w.fl_on.setChecked(True); w.floor_bottom()
w.o_size.setCurrentIndex(2); w.o_qual.setCurrentIndex(0)   # 800x600, draft
w.o_w.setEnabled(True); w.o_w.setValue(480); w.o_h.setValue(300)
assert w.proj["render"]["width"]==480 and w.proj["render"]["spp"]==32, w.proj["render"]
w.cam_add_view(); w.cam_add_preset()
print("cameras", [c["name"] for c in w.proj["cameras"]])
w.cam_list.setCurrentRow(2); w.cam_look(); w.cam_update()
w.reset_body("plate<1>","Aluminum 6061"); 
cb,rough,met,rv,mv=w.app_ctrl["block<1>"]; rough.setValue(20); met.setValue(100)
assert abs(w.proj["appearance"]["block<1>"]["roughness"]-0.2)<1e-9
w.up_combo.setCurrentText("+Y"); assert w.proj["up"]=="+Y"
w.up_combo.setCurrentText("+Z")
out=tempfile.mkdtemp(); w.proj["output"]["folder"]=out; w.o_prefix.setEditText("asm")
# preview then all
def wait():
    t=time.time()
    while w.busy and time.time()-t<200: app.processEvents(); time.sleep(0.05)
    for _ in range(10): app.processEvents()
w.start_render("preview"); wait(); print("preview files", w.files.count(), w.log.toPlainText().splitlines()[-1])
w.start_render("all"); wait()
print(sorted(os.listdir(out))); assert len(os.listdir(out))==len(w.proj["cameras"]), os.listdir(out)
# save / reopen project
pp=os.path.join(out,"t.gpr"); w.proj_path=pp; assert w.save_project()
w2=st.RenderStudio(); w2.open_any(pp)
assert [c["name"] for c in w2.proj["cameras"]]==[c["name"] for c in w.proj["cameras"]] and w2.proj["appearance"]["block<1>"]["metallic"]==1.0

# ---- settings / cameras as text
import json
QF=st.QFileDialog
sp=os.path.join(out,"settings.json"); cp=os.path.join(out,"cams.json")
QF.getSaveFileName=staticmethod(lambda *a,**k:(sp,""))
w.sun_lat.setValue(40.0); w.o_den.setChecked(True); w.o_qual.setCurrentIndex(len(st.QUALITY)-1)
w.export_settings(); d=json.load(open(sp)); assert d["kind"]=="gpd-render-settings" and "cameras" not in d and "appearance" not in d, d.keys()
assert d["render"]["spp"]==16384 and d["render"]["denoise"] is True and d["sun"]["lat"]==40.0
QF.getSaveFileName=staticmethod(lambda *a,**k:(cp,"")); w.export_cameras(); assert json.load(open(cp))["kind"]=="gpd-render-cameras"
# a different model takes them over
w3=st.RenderStudio(); w3.open_any("/tmp/rs_samples/plate.gpd")
QF.getOpenFileName=staticmethod(lambda *a,**k:(sp,""))
w3.import_settings(); assert w3.proj["sun"]["lat"]==40.0 and w3.proj["render"]["spp"]==16384 and w3.o_den.isChecked()
QF.getOpenFileName=staticmethod(lambda *a,**k:(cp,""))
class Box(st.QMessageBox):
    def exec(self): self._b=[b for b in self.buttons() if b.text().startswith("Replace")][0]; self.setProperty("x",1); return 0
    def clickedButton(self): return self._b
st.QMessageBox=Box
w3.import_cameras(); assert [c["name"] for c in w3.proj["cameras"]]==[c["name"] for c in w.proj["cameras"]]
st.QMessageBox=QMessageBox
# ---- video: three cameras ticked, curved path
w.sun_lat.setValue(33.45); w.o_den.setChecked(False); w.o_qual.setCurrentIndex(0)
w.cam_add_preset(); w.cam_add_preset(); w.preset.setCurrentText("Right"); w.cam_add_preset()
for i in range(w.cam_list.count()):
    if i>=w.cam_list.count()-3: w.cam_list.item(i).setCheckState(st.Qt.CheckState.Checked)
assert sum(1 for c in w.proj["cameras"] if c.get("anim"))==3
w.an_sec.setValue(1.0); w.an_fps.setValue(6); w.o_w.setValue(240); w.o_h.setValue(160); w.o_spp.setValue(8)
print(w.an_info.text())
w.start_render("video"); wait()
mp4=[f for f in os.listdir(out) if f.endswith(".mp4")]; print("video files", mp4, w.log.toPlainText().splitlines()[-3:])
assert mp4 and os.path.getsize(os.path.join(out,mp4[0]))>1000 and not [d for d in os.listdir(out) if d.startswith("_frames")]
# stop: graceful, keeps frames, then resume
w.an_sec.setValue(4.0)
w.start_render("video")
t0=time.time()
while time.time()-t0<60 and w.log.toPlainText().count("saved")<3: app.processEvents(); time.sleep(0.05)
w.stop_render(); wait()
fr=[d for d in os.listdir(out) if d.startswith("_frames")]; print("after stop:", fr, len(os.listdir(os.path.join(out,fr[0]))) if fr else None)
assert fr
w.start_render("video"); wait()
assert not [d for d in os.listdir(out) if d.startswith("_frames")] and os.path.exists(os.path.join(out,mp4[0]))
print("log tail:", w.log.toPlainText().splitlines()[-2:])
print("STUDIO OK")
