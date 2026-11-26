"""The Mesh page in every 2D and 3D analysis window (2D FEA, 2D Thermal, 2D CFD, 3D FEA, 3D Thermal, 3D Fluid): the Details start at the top of their area and take only the
height they need (they are not stretched over the whole Details), and "Advanced mesh options" squeezes the Outline to the selected row so that the whole page is visible without a
scroll bar; unticking it, a click on the Outline bar, or another page puts the divider back."""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "thermal3d"),
                os.path.join(HERE, "dev_addons", "cfd3d"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

import cfd3d_tab as c3
import cfd_tab
import physics_tab
import sim_outline
import sim_tab
import solid_tab
import thermal3d_tab as t3
import thermal_tab as tt


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def ok(c, msg):
    assert c, msg
    print("ok:", msg)


def settle():
    for _ in range(3):
        app.processEvents()


WINS = {"2D FEA": physics_tab.PhysicsTab(host()), "2D Thermal": tt.ThermalTab(host()), "2D CFD": cfd_tab.CFDTab(host()),
        "3D FEA": solid_tab.SolidWindow(threaded=False), "3D Thermal": t3.ThermalWindow(threaded=False), "3D Fluid": c3.FluidWindow(threaded=False)}
for name, w in WINS.items():
    w.resize(1300, 1000)
    w.show()
    settle()
    ol = w.outline
    mesh_key = next(k for k in ol.keys() if k.strip().lower() == "mesh")
    sec = ol.nodes[mesh_key]["section"]
    others = [k for k in ol.keys() if k != mesh_key]

    # advanced options off: the page starts at the top and is as tall as its content
    ol.select(mesh_key)
    settle()
    top = sec.mapTo(ol.holder, sec.rect().topLeft()).y()
    ok(top <= 12, f"{name}: the Mesh page starts at the top of the Details (y = {top})")
    ok(sec.height() <= sec.sizeHint().height() + 4, f"{name}: and takes only the height it needs ({sec.height()} of {sec.sizeHint().height()}, the Details are {ol.scroll.viewport().height()} high)")
    ok(sec.height() < ol.scroll.viewport().height() - 100, f"{name}: so there is empty space below it, not a page spread over the whole Details")
    ok(not ol.compact and ol.split.sizes()[0] >= 200, f"{name}: the Outline has its own height ({ol.split.sizes()[0]})")

    # advanced options on: the Outline shows one row, the divider is pulled up, the whole page is visible, no scroll bar
    w.cb_adv.setChecked(True)
    settle()
    ok(ol.compact and ol.split.sizes()[0] <= 60, f"{name}: ticking Advanced mesh options squeezes the Outline to one row ({ol.split.sizes()[0]} px)")
    ok(ol.bar.text().startswith("▸") and ol.tree.currentItem() is not None and ol.tree.currentItem().text(0) == mesh_key, f"{name}: its bar says so and the row shown is '{mesh_key}'")
    ok(ol.scroll.verticalScrollBar().maximum() == 0, f"{name}: the whole page is visible without a scroll bar")
    ok(w.adv_box.isVisibleTo(w) and ol.scroll.verticalScrollBar().maximum() == 0, f"{name}: the advanced options are shown")
    ok(sec.mapTo(ol.holder, sec.rect().topLeft()).y() <= 12, f"{name}: still at the top")

    # a click on the bar opens the Outline again (and keeps it open until the page or the box changes)
    ol.bar.clicked.emit()
    settle()
    ok(not ol.compact and ol.split.sizes()[0] >= 200 and ol.bar.text() == "Outline", f"{name}: a click on the bar shows the whole Outline again")
    ol.bar.clicked.emit()
    settle()
    ok(ol.compact, f"{name}: and a second click squeezes it again")

    # untick: back
    w.cb_adv.setChecked(False)
    settle()
    ok(not ol.compact and ol.split.sizes()[0] >= 200, f"{name}: unticking puts the divider back ({ol.split.sizes()[0]})")

    # tick, go to another page: back; return to the Mesh page: squeezed again
    w.cb_adv.setChecked(True)
    settle()
    ok(ol.compact, f"{name}: ticked again")
    ol.select(others[0])
    settle()
    ok(not ol.compact and ol.split.sizes()[0] >= 200, f"{name}: another page ('{others[0]}') has the whole Outline")
    sec0 = ol.nodes[others[0]]["section"]
    ok(sec0.mapTo(ol.holder, sec0.rect().topLeft()).y() <= 12, f"{name}: and starts at the top")
    ol.select(mesh_key)
    settle()
    ok(ol.compact, f"{name}: back on the Mesh page the options are still ticked: squeezed")
    w.cb_adv.setChecked(False)
    settle()

    # every page starts at the top and is not stretched
    for k in ol.keys():
        ol.select(k)
        settle()
        s_ = ol.nodes[k]["section"]
        ok(s_.mapTo(ol.holder, s_.rect().topLeft()).y() <= 12 and s_.height() <= s_.sizeHint().height() + 40, f"{name}: the page '{k}' starts at the top ({s_.height()} high)")
    w.hide()

print("OK mesh page layout in all six windows")
