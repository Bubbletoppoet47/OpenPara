import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, math, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import settings, settings_dialog, sk_dimlines as dl, sk_tools as sk
import pm_app, pm_model as pm, sketch_edit as se

# ---- the new settings: choices and colours are checked, kept, reset
assert settings.clamp("arrow_style", "nonsense") == "open" and settings.clamp("arrow_style", "dot") == "dot"
assert settings.clamp("dim_line_style", "wavy") == "solid" and settings.clamp("ext_line_style", "dashdot") == "dashdot"
assert settings.clamp("dim_color", "#ABCDEF") == "#abcdef" and settings.clamp("dim_color", "red") == "#1a1a1a" and settings.clamp("dim_color", 5) == "#1a1a1a"
assert settings.clamp("text_pt", 99) == 30.0 and settings.clamp("arrow_pct", 0) == 0.5
settings.set_many({"arrow_style": "filled", "dim_color": "#336699", "dim_line_style": "dashed", "text_pt": 18})
settings._state.clear(); settings.load()
assert settings.get("arrow_style") == "filled" and settings.get("dim_color") == "#336699" and settings.get("text_pt") == 18.0, "kept between runs"
assert json.load(open(settings.path()))["dim_line_style"] == "dashed"
assert abs(settings.rgb("dim_color")[0] - 0x33 / 255) < 1e-9
settings.reset(); assert settings.all_values() == settings.defaults()
with settings.overriding({"text_pt": 25}):
    assert settings.get("text_pt") == 25.0
assert settings.get("text_pt") == 14.0, "an override does not leak"
print("settings ok")

# ---- line styles: pieces of a line
line = np.array([[0.0, 0.0], [100.0, 0.0]])
assert len(dl.styled(line, "solid", 1.0)) == 1
d = dl.styled(line, "dashed", 1.0)          # 4 on, 2.5 off
assert len(d) == 16 and all(abs(abs(p[1][0] - p[0][0]) - 4.0) < 1e-9 for p in d[:-1]), len(d)
assert all(abs(p[:, 1]).max() < 1e-12 for p in d), "pieces stay on the line"
dd = dl.styled(line, "dotted", 1.0); assert len(dd) == 40 and abs(dd[0][1][0] - dd[0][0][0] - 0.5) < 1e-9
da = dl.styled(line, "dashdot", 1.0)
assert abs(da[0][1][0] - da[0][0][0] - 4.0) < 1e-9 and abs(da[1][1][0] - da[1][0][0] - 0.5) < 1e-9 and abs(da[1][0][0] - 5.5) < 1e-9
# a bent polyline (an arc): the pieces follow it
arc = np.array([(10 * math.cos(t), 10 * math.sin(t)) for t in np.linspace(0, math.pi / 2, 40)])
pcs = dl.styled(arc, "dashed", 0.5)
assert len(pcs) > 3 and all(abs(np.hypot(*p.T) - 10).max() < 0.05 for p in pcs), "dashes along an arc stay on it"
print("line styles ok:", len(d), len(dd), len(da), len(pcs))

# ---- arrowhead styles
tip, inw = (5.0, 5.0), (1.0, 0.0)
assert dl.head_items("none", tip, inw, 2.0) == []
k = dict((s, dl.head_items(s, tip, inw, 2.0)) for s in settings.ARROW_STYLES if s != "none")
assert [x[0] for x in k["open"]] == ["line"] and len(k["open"][0][1]) == 3 and np.allclose(k["open"][0][1][1], tip)
assert [x[0] for x in k["closed"]] == ["line"] and len(k["closed"][0][1]) == 4 and np.allclose(k["closed"][0][1][0], k["closed"][0][1][3])
assert [x[0] for x in k["filled"]] == ["fill"] and len(k["filled"][0][1]) == 3 and np.allclose(k["filled"][0][1][0], tip)
assert [x[0] for x in k["dot"]] == ["fill"] and len(k["dot"][0][1]) == 16 and np.allclose(k["dot"][0][1].mean(axis=0), tip)
assert [x[0] for x in k["hollow_dot"]] == ["line"] and np.allclose(k["hollow_dot"][0][1][0], k["hollow_dot"][0][1][-1])
tk = k["tick"][0][1]; assert len(tk) == 2 and np.allclose(tk.mean(axis=0), tip) and abs(np.hypot(*(tk[1] - tk[0])) - 2.0) < 1e-9
assert all(x[1][:, 0].min() >= 5.0 - 1e-9 for x in (k["open"][0], k["closed"][0], k["filled"][0])), "the body of an arrowhead runs back along the line"
print("arrowheads ok")

# ---- the editor draws with the settings
w = pm_app.MainWindow(); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
w.set_tool("rect_corner"); click(-20, -10); click(20, 10); ed.reset_tool("select")
lns = list(ed.m.lns)
bottom = [l for l in lns if abs(ed.m.line_pts(l)[0][1] - ed.m.line_pts(l)[1][1]) < 1e-6 and ed.m.line_pts(l)[0][1] < 0][0]
ed.commit(lambda mm: mm.add_con("dim_h", [("ln", bottom)], value=40.0))
c = [x for x in ed.m.cons if x["type"] == "dim_h"][0]
sh = dl.shapes(ed, c); ext = dl.extent(ed.m)
base = dl.primitives(sh, ext)
assert any(it[0] == "line" for it in base) and not any(it[0] == "fill" for it in base)
n_solid = len(ed.actors)
settings.set_many({"dim_line_style": "dashed", "ext_line_style": "dotted", "arrow_style": "filled", "dim_line_px": 3.0, "ext_line_px": 0.5})
prim = dl.primitives(sh, ext)
dim_w = {round(it[2], 3) for it, kind in zip([x for x in prim if x[0] == "line"], [None] * len(prim))} if False else None
assert any(it[0] == "fill" for it in prim), "filled arrowheads"
widths = sorted({it[2] for it in prim if it[0] == "line"}); assert widths == [0.5, 3.0], widths
assert len(prim) > len(base) + 10, "dashes make many pieces"
ed.redraw(); n_dashed = len(ed.actors); print("actors solid", n_solid, "dashed", n_dashed); assert n_dashed > n_solid + 10
sel = dl.primitives(sh, ext, True); assert all(abs(it[3][0] - 1.0) < 1e-9 for it in sel[:1]) and sel[0][3] == settings.rgb("dim_sel_color")
settings.set_many({"arrow_style": "none", "text_pt": 24}); assert not [it for it in dl.primitives(sh, ext) if it[0] == "fill"]; ed.redraw()
assert dl.primitives(sh, ext) and ed.tags
r = w.plotter.devicePixelRatioF(); t0 = ed.tags[0]; sx, sy = ed.screen_of(np.array([(t0[0], t0[1])]))[0]
assert ed.pick_tag(sx + 100 * r, sy + 20 * r) == t0[2], "the click box grows with the text size"
settings.reset(); ed.redraw(); print("editor ok")
# a change of settings while the sketch is open redraws it
w.settings_changed(["arrow_style"]); settings.set_many({"ext_gap_pct": 3.0, "ext_over_pct": 6.0})
sh2 = dl.shapes(ed, c); e0 = [s for s, k in zip(sh2["segs"], sh2["kinds"]) if k == "ext"][0]
assert np.linalg.norm(e0[0] - np.array(ed.m._two_points(c["refs"])[0])) >= 0.029 * ext - 1e-9 or abs(e0[0][1] - ed.m._two_points(c["refs"])[0][1]) >= 0.029 * ext - 1e-9, "the gap setting moves the extension line"
settings.reset()

# ---- the settings window
dlg = settings_dialog.SettingsDialog()
assert dlg.sections.count() == 4 and [dlg.sections.item(i).text() for i in range(4)] == ["Curves & Surfaces", "Outlines", "Dimensions", "Picking & Snapping"]
assert dlg.pages.count() == 4
imgs = {}
for st in settings.ARROW_STYLES:
    dlg.fields["arrow_style"].set_value(st)
    assert dlg.dimprev.values["arrow_style"] == st
    img = dlg.dimprev.grab().toImage(); imgs[st] = bytes(img.constBits().asstring(img.sizeInBytes()))
    assert img.width() > 300
assert len({hash(v) for v in imgs.values()}) == len(imgs), "each arrowhead style gives a different picture"
for st in settings.LINE_STYLES:
    dlg.fields["dim_line_style"].set_value(st); dlg.dimprev.grab()
dlg.fields["dim_color"].set_value("#cc0000"); assert dlg.fields["dim_color"].btn.text() == "#cc0000"
dlg.fields["dim_color"].set_value("junk"); assert dlg.fields["dim_color"].value == "#1a1a1a"
dlg.fields["text_pt"].edit.setText("99"); dlg.fields["text_pt"].typing("99"); dlg.fields["text_pt"].finish()
assert dlg.fields["text_pt"].value == 30.0 and "allowed range" in dlg.fields["text_pt"].note.text()
assert settings.get("text_pt") == 14.0, "nothing is applied before OK"
dlg.fields["arrow_style"].set_value("dot"); dlg.fields["ext_line_style"].set_value("dashed"); dlg.apply()
assert settings.get("arrow_style") == "dot" and settings.get("ext_line_style") == "dashed" and settings.get("text_pt") == 30.0
dlg.reset_defaults(); dlg.ok(); assert settings.all_values() == settings.defaults()
# no caption under the pictures, and one short line under each input
from PyQt6.QtWidgets import QLabel
for pv in (dlg.curve, dlg.surf, dlg.line, dlg.pull, dlg.dimprev):
    assert pv.height() <= 240
assert all(len(settings_dialog.HINTS[k]) <= 80 for k in settings_dialog.HINTS), "brief explanations"
assert set(settings.SPEC) - {"hover"} <= set(settings_dialog.HINTS), "every setting has its line"
print("window ok")
print("OK")
