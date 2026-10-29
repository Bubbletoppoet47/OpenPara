import os; os.environ["QT_QPA_PLATFORM"]="offscreen"
import numpy as np, tempfile
from PyQt6.QtWidgets import QApplication
app=QApplication([])
import beam1d, beam_canvas, result_style, beam_tab, physics_tab, cfd_tab, meshdraw, sim_tab
# 1D station values for the standard results, cantilever with a tip load
L,P,E,I=100.0,1000.0,200000.0,1000.0
r=beam1d.solve({1:(0,0),2:(L,L)},[beam1d._member(1,1,2)],{1:(True,True,True)},{2:(0.0,-P,0.0)})
cv=beam_canvas.BeamCanvas.__new__(beam_canvas.BeamCanvas)
for mode in ("umag","ux","uy","vm","sx","sy","fos"):
    lo,hi,arr=beam_canvas.BeamCanvas.station_values(cv,r,mode)
    v=arr[1]; print(mode, round(lo,5), round(hi,5), len(v))
    assert np.all(np.isfinite(v)) or mode=="fos"
# magnitude consistency: |u|^2 = ux^2+uy^2 ; vm = |sigma| ; sx+sy = sigma sign-consistent
_,_,a_x=beam_canvas.BeamCanvas.station_values(cv,r,"ux"); _,_,a_y=beam_canvas.BeamCanvas.station_values(cv,r,"uy"); _,_,a_m=beam_canvas.BeamCanvas.station_values(cv,r,"umag")
assert np.allclose(np.hypot(a_x[1],a_y[1]),a_m[1])
_,_,s_x=beam_canvas.BeamCanvas.station_values(cv,r,"sx"); _,_,s_y=beam_canvas.BeamCanvas.station_values(cv,r,"sy"); _,_,s_v=beam_canvas.BeamCanvas.station_values(cv,r,"vm")
assert np.allclose(np.abs(s_x[1]+s_y[1]),s_v[1])
print("1D station values OK")
# colour schemes
for n in result_style.CMAPS:
    result_style.set_current(n)
    c=result_style.colours(np.linspace(0,1,5)); assert c.shape==(5,3) and c.min()>=0 and c.max()<=255
    print(n, c[0].tolist(), c[-1].tolist())
result_style.set_current("jet")
# the tabs share one choice
class H:
    doc=None
    class m: unit_system="Metric (mm, kg, N, s, MPa)"
    _restoring=False
    def status(self,t): pass
    def sketch_list(self): return []
    def sketch_json(self,s): return None
h=H(); ta=physics_tab.PhysicsTab(h); tb=beam_tab.BeamTab(h); tc=cfd_tab.CFDTab(h)
ta.cmap_combo.setCurrentText("viridis")
assert tb.cmap_combo.currentText()=="viridis" and tc.cmap_combo.currentText()=="viridis" and result_style.current()=="viridis"
tb.cmap_combo.setCurrentText("turbo"); assert ta.cmap_combo.currentText()=="turbo"
names2d=[n for n,_,_ in physics_tab.FIELDS][:6]; names1d=[t for t,k in beam_tab.VIEWS if k in ("umag","ux","uy","vm","sx","sy")]
print(names2d, names1d); assert names2d==names1d
result_style.set_current("jet")
os.remove(result_style._settings_path()) if os.path.exists(result_style._settings_path()) else None
print("RESULTS OK")
