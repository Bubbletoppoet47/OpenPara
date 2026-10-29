import os
os.environ["QT_QPA_PLATFORM"]="offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app=QApplication([])
import pm_app
w=pm_app.MainWindow(); d=w.doc
w.command("fillet")
solid=w.shown_solid()
e=[e for e in solid.edges() if e.geom_type.name=="LINE"][0]
p=np.array(tuple(e.position_at(0.5)))+np.array([0.3,0.3,0.0])
try:
    from viewpick import world_per_pixel; print("wpp",world_per_pixel(w.plotter))
except Exception as ex: print("wpp fail",ex)
found=w.nearest_edge(solid,p); print("nearest:", found is not None)
print("click on empty:", end=" "); w.on_click(5,5); print("ok")
