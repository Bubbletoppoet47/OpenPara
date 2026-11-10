"""The tabs look and behave like one program: every tab carries the icon of its kind and is named by one rule; side panels open as wide as
their contents (nothing cut off); the Truss Generator, Visualize and the Parametric Study have the same bar on top (what it is on the left, its
commands on the right), say what to do while they are empty, and are reached from the Add menu of the part or simulation on screen."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
open(os.path.join(UD, "addons.json"), "w").write('{"removed": ["partgen", "annotator", "annotator_gimble", "trainer", "motor"]}')          # the big add-ons are not needed here
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import addons
addons.NOT_RELEASED = ()          # this test is about all the tabs, also Visualize, which is not in a normal OpenPara yet (see addons.NOT_RELEASED)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QFileDialog, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget
app = QApplication([])
# The offscreen test window has no real graphics card behind it: drawing a 3D model there fails now and then inside VTK (not in OpenPara).
# This test is about panels, bars and names, so the 3D views are simply not drawn.
import pyvista, pyvistaqt
pyvista.plotting.plotter.BasePlotter.render = lambda self, *a, **k: None
pyvistaqt.rwi.QVTKRenderWindowInteractor.paintEvent = lambda self, ev: None
BOX = []
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: BOX.append(a[2])))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, gpd_app, ext, ui_kit, icon_set
import sim_tab, study_tab, truss_tab, render_studio


def settle():
    """What the real program does between two clicks: pending events, and Qt deletes what was scheduled for deletion (a test that skips
    this misses anything that was destroyed by accident - the menus behind a bar's drop-down buttons, for example)."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    for _ in range(4):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


# ---------------------------------------------------------------- 1. the shared pieces
host = QWidget(); host.resize(1200, 600)
split = QSplitter(Qt.Orientation.Horizontal, host); QVBoxLayout(host).addWidget(split)
content = QWidget(); cl = QVBoxLayout(content)
wide = QPushButton("A button with a long label that must not be cut off at all"); cl.addWidget(wide)
sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(content)
view = QLabel("view")
split.addWidget(sc); split.addWidget(view)
host.show(); settle()
ui_kit.fit_panel(split, sc, content, lo=200, hi=640); settle()
assert sc.viewport().width() >= content.minimumSizeHint().width(), "the panel is as wide as its contents need"
w0 = split.sizes()[0]
wider = QPushButton("An even longer label that arrives later, after an import for example, and needs still more room"); cl.addWidget(wider); settle(); settle()
assert split.sizes()[0] > w0 and sc.viewport().width() >= content.minimumSizeHint().width(), "the panel widens when its contents grow"
split.splitterMoved.emit(300, 1)                             # the user drags the divider: from now on it stays where they put it
split.setSizes([300, 900]); settle()
w1 = split.sizes()[0]
cl.addWidget(QPushButton("x" * 140)); settle(); settle()
assert split.sizes()[0] == w1 and w1 < 320, ("a divider the user moved is left alone", split.sizes())
cb = QComboBox(); cb.addItems(["short", "A very long entry of a drop-down that would force the panel wide " * 2])
before = cb.minimumSizeHint().width(); ui_kit.tame_combo(cb, 12)
assert 0 < cb.minimumWidth() < before / 2 and cb.toolTip() == "short", "a long drop-down no longer asks for the width of its longest entry"
st = ui_kit.StatusLine(""); st.resize(60, 20); st.setText("A long message that does not fit in sixty pixels at all")
assert st.text() == "A long message that does not fit in sixty pixels at all" and st.toolTip() == st.text(), "the whole text is kept; the line shows what fits"
es = ui_kit.EmptyState("Title", "Text", [("Go", lambda: BOX.append("go")), ("Other", lambda: None)])
es.buttons[0].click(); assert BOX[-1] == "go" and len(es.buttons) == 2
for kind in ("part", "assembly", "truss", "visualize", "beam", "fea", "cfd", "study", "tet", "mesh", "annotator", "trainer"):
    assert icon_set.for_tab(kind) is not None and not icon_set.for_tab(kind).isNull(), f"no tab icon for {kind}"
assert icon_set.for_tab("something else") is None

# ---------------------------------------------------------------- a part with a sketch, open in the program
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); mm = d.models[s["id"]]
l1 = sk.add_line(mm, (0, 0), (3000, 0)); l2 = sk.add_line(mm, (3000, 0), (1500, 800)); l3 = sk.add_line(mm, (1500, 800), (0, 0))
a0, a1 = mm.lns[l1]; b0, b1 = mm.lns[l2]; c0, c1 = mm.lns[l3]
for p_, q_ in ((a1, b0), (b1, c0), (c1, a0)):
    sk.con(mm, "coincident", [("pt", p_), ("pt", q_)])
sk.solve_model(mm); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
part = os.path.join(UD, "roof.gpd"); open(part, "w").write(d.to_json())
sh = gpd_app.AppShell([part]); sh.resize(1500, 900); sh.show(); settle()
ptab = sh.cur()


def icon_of(w):
    return sh.tabs.tabIcon(sh.tabs.indexOf(w))


def menu(name):
    return next(a.menu() for a in sh.menuBar().actions() if a.text().replace("&", "") == name)


def fits(scroll_area):
    """True when the scrolled panel shows its contents whole (no sideways scrolling needed)."""
    c = scroll_area.widget()
    return scroll_area.viewport().width() >= c.minimumSizeHint().width()


assert not icon_of(ptab).isNull() and sh.tab_kind(ptab) == "part"
asm = sh.new_assembly(); assert not icon_of(asm).isNull() and sh.tab_kind(asm) == "assembly"
sh.close_tab(sh.tabs.indexOf(asm))

# ---------------------------------------------------------------- 2. Truss Generator
t = sh.new_addon_tab("truss")
assert not icon_of(t).isNull() and t.title() == "Truss"
assert t.stack.currentWidget() is t.empty and [b.text() for b in t.empty.buttons] == ["New project...", "Import source..."], "an empty truss says how to begin"
assert t.lbl_cfg.isHidden() and t.cfg.isHidden(), "no configuration box while there is nothing to choose"
bar = t.layout().itemAt(0).layout()
order = [bar.itemAt(i).widget() for i in range(bar.count()) if bar.itemAt(i).widget() is not None]
assert order.index(t.name_edit) < order.index(t.btn_new) < order.index(t.btn_import) < order.index(t.btn_refresh) < order.index(t.btn_sketch), "name left, commands right"
assert "…" not in "".join(b.text() for b in t.findChildren(QPushButton)), "three dots, as everywhere else"
assert all(b.isHidden() for b in (t.btn_new, t.btn_import, t.btn_refresh, t.btn_sketch)), "the guidance has the commands: the bar does not repeat them"
sh.close_tab(sh.tabs.indexOf(t))
# Add > Truss Generator: straight from the part on screen
acts = [a.text() for a in menu("Add").actions()]
assert any(a.startswith("Truss Generator") for a in acts), acts
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(UD, "Roof.truss"), ""))
sh.tabs.setCurrentWidget(ptab)
next(a for a in menu("Add").actions() if a.text().startswith("Truss Generator")).trigger(); settle()
t = sh.cur()
assert isinstance(t, truss_tab.TrussTab) and t.path and len(t.lines()) == 3, "the truss has the part's sketch"
assert t.stack.currentWidget() is t.pages and t.title() == "Roof" and t.lbl_sketch.text().startswith("Sketch:")
assert not t.no_member.isHidden(), "no member yet: the editor says so"
assert not any(b.isHidden() for b in (t.btn_new, t.btn_import, t.btn_refresh, t.btn_sketch)), "with a sketch the bar has the project commands"
for ln in list(t.lines()):
    t.line_toggled(ln, add_only=True)
t.mlist.setCurrentRow(0); settle()
assert t.no_member.isHidden() and t.mname.isEnabled() and len(t.p["members"]) == 3
t.say("x" * 400); assert t.msg.text() == "x" * 400 and t.msg.width() < 3000, "a long message never widens the window"
# with something that is not a part on screen the command says what is needed
BOX.clear(); n = sh.tabs.count()
next(a for a in menu("Add").actions() if a.text().startswith("Truss Generator")).trigger()
assert sh.tabs.count() == n and BOX and "part" in BOX[-1]

# ---------------------------------------------------------------- 3. Visualize
sh.tabs.setCurrentWidget(ptab)
r = sh.add_render(); settle()
assert isinstance(r, render_studio.RenderStudio) and not icon_of(r).isNull(), "a Visualize tab has its icon"
settle()
assert r.title() == "Visualize - roof" and r.top_bar.isVisible() and r.menuBar().isHidden(), "one bar instead of a second menu bar"
assert sorted(r.bar_buttons) == ["file", "guide", "import", "render", "update"]
assert r.bar_buttons["import"].text() == "Import source..." and r.bar_buttons["update"].isEnabled(), "the same two commands as the simulations and the Truss"
for key in ("file", "render"):                               # the drop-down buttons really have their menus (they were once deleted with the menu bar)
    assert r.bar_buttons[key].menu() is r.menus[key] and len([a for a in r.menus[key].actions() if a.text()]) >= 3, key
assert "Render all cameras" in [a.text() for a in r.bar_buttons["render"].menu().actions()]
assert "Read the part / assembly again" not in [a.text() for a in r.menus["file"].actions() if a.isVisible()], "the bar's Update from original does that: not twice"
from PyQt6.QtCore import QTimer
opened = {}
def close_popup():
    p_ = QApplication.activePopupWidget()
    opened["texts"] = None if p_ is None else [a.text() for a in p_.actions() if a.text()]
    if p_ is not None:
        p_.close()
QTimer.singleShot(300, close_popup)
r.bar_buttons["render"].click()                              # a click on the button really opens its menu
assert opened.get("texts") and "Render all cameras" in opened["texts"], opened
assert "roof.gpd" in r.bar_lbl.text()
assert r.a_sel in r.actions() and r.a_sel.shortcut().toString() == "F11", "the shortcuts keep working without the menu bar"
ps = r.props_dock.widget()
assert fits(ps), (ps.viewport().width(), ps.widget().minimumSizeHint().width())
assert "1 body" in r.src_lbl.text() and "(ies)" not in r.src_lbl.text()
assert r.save() and r.title() == os.path.splitext(os.path.basename(r.path))[0], "a project tab is named after its folder, without the extension"

# ---------------------------------------------------------------- 4. the simulations: one status line, panels that fit, names by the same rule
sims = {}
for kind in ("beam", "fea", "cfd"):
    sh.tabs.setCurrentWidget(ptab)
    w = sh.add_sim(kind); settle()
    assert w.title() == f"{w.label} - roof", w.title()
    assert w.stack.currentWidget() is w.empty and "Start a" in w.empty.title.text(), "no project yet: the tab says how to begin"
    assert [b.text() for b in w.empty.buttons if not b.isHidden()] == ["New project...", "Import source..."] and w.src_lbl.text() == "No project yet"
    assert w.b_new.isHidden() and w.b_import.isHidden() and w.b_refresh.isHidden(), "the guidance has the commands: the bar does not repeat them"
    assert w.create_project(os.path.join(UD, "p_" + kind)); settle()
    assert w.stack.currentWidget() is w.tab and "roof" in w.src_lbl.text(), "the part on screen was imported: the solver tab is shown"
    assert w.b_new.isHidden() and not w.b_import.isHidden() and not w.b_refresh.isHidden(), "working: the bar has Import source and Update from original"
    assert w.title() == "p_" + kind and sh.tabs.tabText(sh.tabs.indexOf(w)).startswith("p_" + kind), "the tab is renamed at once"
    w.tab.picker.refresh(); w.tab.picker.select(s["id"]); w.tab.picker.go(); settle(); settle()
    assert not icon_of(w).isNull() and sh.tab_kind(w) == kind
    assert w.status_lbl.isHidden(), "one status line per tab"
    w.say("Saved somewhere"); assert w.tab.status_lbl.text() == "Saved somewhere"
    panel = next(x for x in w.tab.findChildren(QScrollArea) if x.widget() is not None and x.widget().height() > 200)
    assert fits(panel), (kind, panel.viewport().width(), panel.widget().minimumSizeHint().width())
    sims[kind] = w
# a project folder with nothing in it yet (made from File > New ...): only the import is offered
lone = sim_tab.SimWindow("fea", shell=sh); sh.add_tab(lone)
assert lone.create_project(os.path.join(UD, "p_lone")) and lone.stack.currentWidget() is lone.empty
assert [b.text() for b in lone.empty.buttons if not b.isHidden()] == ["Import source..."] and "Import" in lone.empty.title.text()
assert lone.b_new.isHidden() and lone.b_import.isHidden() and lone.b_refresh.isHidden()
sh.close_tab(sh.tabs.indexOf(lone))
tip = sh.tabs.tabToolTip(sh.tabs.indexOf(sims["beam"]))
sh.refresh_titles()
assert sh.tabs.tabToolTip(sh.tabs.indexOf(sims["beam"])).startswith("1D FEA project\n")

# ---------------------------------------------------------------- 5. the parametric study
BOX.clear(); sh.tabs.setCurrentWidget(ptab)
study_act = next(a for a in menu("Add").actions() if a.text().startswith("Parametric study"))
study_act.trigger(); assert BOX and "simulation" in BOX[-1], "from a part it says what is needed"
sh.tabs.setCurrentWidget(sims["beam"]); study_act.trigger(); settle()
st = sh.cur()
assert isinstance(st, study_tab.StudyTab) and not icon_of(st).isNull() and st.title() == "Study - p_beam"
assert [(x.number, x.title) for x in st.sections] == [(1, "Inputs to vary"), (2, "Outputs to record"), (3, "Stop early when")]
left_scroll = st.panel.findChild(QScrollArea)
for b in (st.b_all, st.b_stop, st.b_sel, st.b_cur, st.bar):
    assert not left_scroll.isAncestorOf(b) and st.panel.isAncestorOf(b), "the Run bar is pinned under the scrolling steps"
    assert b.visibleRegion().boundingRect().height() > 0, "and in view without scrolling"
assert fits(left_scroll)
assert not st.design_hint.isHidden(), "no input ticked: the table says how it gets its columns"
pid = next(p for p in st.desc if p.startswith("beam."))
st.items[pid].setCheckState(0, Qt.CheckState.Checked); settle()
assert st.design_hint.isHidden() and st.design.columnCount() == 1
study_act.trigger(); assert sh.cur() is st, "asked again from the study itself: it is shown"
st.goto_sim(); assert sh.cur() is sims["beam"]
import shutil; shutil.rmtree(UD, ignore_errors=True)
print("OK family look")
os._exit(0)
