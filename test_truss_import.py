"""Truss: import a sketch from any open part tab; the truss is saved to its .truss folder first; importing again replaces the sketch and
clears the members; Clear sketch starts over; editing / refreshing needs a saved truss."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(); os.environ["OPARA_NO_UPDATE"] = "1"
os.environ["OPARA_DEV_ADDONS"] = os.path.join(HERE, "addons_src")
sys.path.insert(0, HERE)
import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QInputDialog
INFO = []
ANS = {"q": QMessageBox.StandardButton.Yes}
QMessageBox.warning = staticmethod(lambda *a, **k: INFO.append(a[2]))
QMessageBox.information = staticmethod(lambda *a, **k: INFO.append(a[2]))
QMessageBox.question = staticmethod(lambda *a, **k: ANS["q"])
TMP = tempfile.mkdtemp()
SAVE = {"path": os.path.join(TMP, "T.truss")}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (SAVE["path"], ""))
PICK = {"want": "Tab:"}
SEEN = {}
def fake_item(parent, title, label, items, cur=0, editable=False):
    SEEN["items"] = list(items)
    for it in items:
        if it.startswith(PICK["want"]):
            return it, True
    return items[0], True
QInputDialog.getItem = staticmethod(fake_item)


def build_doc():
    import pm_model as pm, sk_tools as sk
    d = pm.Document(); d.params = {"Span": "3000"}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    l1 = sk.add_line(m, (0, 0), (3000, 0)); l2 = sk.add_line(m, (3000, 0), (1500, 800)); l3 = sk.add_line(m, (1500, 800), (0, 0))
    a0, a1 = m.lns[l1]; b0, b1 = m.lns[l2]; c0, c1 = m.lns[l3]
    sk.con(m, "coincident", [("pt", a1), ("pt", b0)]); sk.con(m, "coincident", [("pt", b1), ("pt", c0)]); sk.con(m, "coincident", [("pt", c1), ("pt", a0)])
    sk.con(m, "coincident", [("pt", a0), ("pt", 0)]); sk.con(m, "horizontal", [("ln", l1)]); sk.con(m, "dim_len", [("ln", l1)], value=3000.0, expr="Span", name="SpanDim")
    sk.solve_model(m); d.store_sketch(s["id"]); d.cfg_add_col("g:Span"); d.cfg_add("Wide"); d.cfg_set_cell("Wide", "g:Span", "4000"); d.cfg_apply("Default")
    return d


def inspect(shell, out):
    import truss_core as tc
    d = build_doc()
    shell.new_part()                                          # a part with no sketch: never offered
    shell.new_part()
    shell.tabs.widget(shell.tabs.count() - 1).doc = d         # a part tab with a sketch (unsaved)
    got = shell.open_sketches()
    assert len(got) == 1 and len(got[0]["sketches"]) == 1 and got[0]["doc"], got
    t = shell.new_addon_tab("truss")
    # the top bar: New project / Import source / Update from original / Sketch menu, Project and Configuration; no Export here (it is on the Assembly page)
    bar_texts = [t.btn_new.text(), t.btn_import.text(), t.btn_refresh.text(), t.btn_sketch.text()]
    assert bar_texts == ["New project...", "Import source...", "Update from original", "Sketch ▾"], bar_texts
    assert [a.text() for a in t.btn_sketch.menu().actions()] == ["Open sketch for editing", "Clear sketch"]
    assert not hasattr(t, "btn_export") and not hasattr(t, "btn_open")
    # New project... makes the folder first (cancel does nothing), an empty truss with no sketch
    SAVE["path"] = ""
    t.new_project(); assert not t.path
    SAVE["path"] = os.path.join(TMP, "Fresh.truss")
    t.new_project()
    assert t.path and os.path.isfile(os.path.join(t.path, "project.json")) and t.p["name"] == "Fresh" and not t.p["members"] and t.lbl_sketch.text() == "No sketch yet"
    t.path, t.p = None, tc.new_project("Truss"); t.name_edit.setText("Truss"); t.refresh_all()
    SAVE["path"] = os.path.join(TMP, "T.truss")

    # unsaved truss: editing and refreshing ask to save first, nothing is written
    n = len(INFO)
    t.open_sketch_for_editing(); t.refresh_from_sketch()
    assert not t.path

    # import: asks for the .truss folder (cancel = nothing happens)
    SAVE["path"] = ""
    t.import_menu()
    assert not t.p.get("sketch") and not t.path
    SAVE["path"] = os.path.join(TMP, "T.truss")
    t.import_menu()
    assert any("Tab:" in x for x in SEEN["items"]) and SEEN["items"][-1].startswith("A part file"), SEEN
    assert t.path and os.path.isfile(os.path.join(t.path, tc.SKETCH_FILE)), t.path
    assert t.cfg.count() == 2 and len(t.lines()) == 3 and t.lbl_sketch.text().startswith("Sketch:")
    # the truss now edits and refreshes from its own folder
    t.refresh_from_sketch()
    assert "Sketch refreshed" in t.msg.text(), t.msg.text()

    # members, then a second import: declined keeps everything, accepted clears the members and replaces the sketch
    line = sorted(t.lines())[0]
    tc.add_member(t.p, line); t.refresh_all()
    assert len(t.p["members"]) == 1
    ANS["q"] = QMessageBox.StandardButton.No
    t.import_menu()
    assert len(t.p["members"]) == 1
    ANS["q"] = QMessageBox.StandardButton.Yes
    d2 = build_doc(); d2.cfg_add("Extra")
    shell.tabs.widget(shell.tabs.count() - 2).doc = d2
    t.import_menu()
    assert t.p["members"] == [] and t.cfg.count() == 3 and "Extra" in [t.cfg.itemText(i) for i in range(t.cfg.count())]
    assert tc.load(t.path)["members"] == []
    assert "Extra" in tc.SketchSource(tc.load(t.path)["sketch"]["doc"], tc.load(t.path)["sketch"]["sid"]).configs()

    # Clear sketch: declined keeps it, accepted removes sketch.gpd and the members
    tc.add_member(t.p, sorted(t.lines())[0])
    ANS["q"] = QMessageBox.StandardButton.No
    t.clear_sketch(); assert t.p["sketch"] and len(t.p["members"]) == 1
    ANS["q"] = QMessageBox.StandardButton.Yes
    t.clear_sketch()
    assert t.p["sketch"] is None and t.p["members"] == [] and t.lbl_sketch.text() == "No sketch yet"
    assert not os.path.exists(os.path.join(t.path, tc.SKETCH_FILE)) and tc.load(t.path)["sketch"] is None
    # and a fresh start: import again into the same truss folder
    t.import_menu()
    assert t.p["sketch"] and os.path.isfile(os.path.join(t.path, tc.SKETCH_FILE)) and not t.dirty
    out["ok"] = True



import addons, ext
addons.startup(); addons.register_extensions(ext)
import gpd_app
app = QApplication([])
shell = type("Shell", (*ext.SHELL_MIXINS, gpd_app.AppShell), {})()
out = {}
inspect(shell, out)
assert out.get("ok")
print("OK truss import")
os._exit(0)
