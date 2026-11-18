"""The icon kit (icon_kit.py, icon_shapes.py): every drawing renders at the sizes the program uses, every ribbon label, mate type, load type, tab kind and
Sheets button has a drawing, the look is one palette, and the simulation add-on still draws its icons when the core is older and has no kit."""
import faulthandler
import importlib
import os
import re
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import icon_kit
import icon_set
import icon_shapes
import icons
import mate_icons
import sh_icons

KEYS = icon_kit.keys()
assert len(KEYS) == len(set(KEYS)) and len(KEYS) >= 160, len(KEYS)

# ---- every drawing: well formed, and it draws something at every size the program uses
ROLES = {"b", "p", "a", "l", "n", "d", "k", "th"}
ELEM = re.compile(r'<(path|circle|ellipse|rect) class="(\w+)"([^>]*?)\s*/>')
INK = QColor(icon_kit.LOOK["ink"]).rgb() & 0xFFFFFF
for k in KEYS:
    inner, hue = icon_kit._SHAPES[k]
    assert hue in icon_kit.HUES, (k, hue)
    found = ELEM.findall(inner)
    assert found, k
    assert len(found) == inner.count("<"), (k, "an element the kit cannot read")
    assert {r for _t, r, _a in found} <= ROLES, (k, {r for _t, r, _a in found} - ROLES)
    for size in (16, 24, 40):
        for ratio in (1, 2):
            img = icon_kit.image(k, size, ratio)
            assert img.width() == size * ratio and img.height() == size * ratio, (k, size, ratio)
            solid = sum(1 for y in range(img.height()) for x in range(img.width()) if img.pixelColor(x, y).alpha() > 0)
            assert solid >= 0.04 * img.width() * img.height(), (k, size, ratio, "nearly blank", solid)
    img = icon_kit.image(k, 40, 2)
    if {r for _t, r, _a in found} - {"n", "th"}:                                 # (a drawing of accent lines only has no navy)
        assert any((img.pixel(x, y) & 0xFFFFFF) == INK and img.pixelColor(x, y).alpha() == 255 for y in range(80) for x in range(80)), (k, "no navy ink")

# ---- the QIcon: sharp at the sizes of the tree (16), panel buttons (20-24), tabs (26) and the ribbon (36, 40); a screen with 2x pixels gets 2x pixmaps
ic = icon_kit.qicon("fillet", 40)
assert ic is not None and not ic.isNull()
sizes = {(s.width(), s.height()) for s in ic.availableSizes()}
for px in (16, 20, 22, 24, 26, 36, 40):
    assert (px, px) in sizes and (2 * px, 2 * px) in sizes, px
assert icon_kit.qicon("no_such_icon") is None and not icon_kit.has("no_such_icon")
off = icon_kit.pixmap("fillet", 24, 2, enabled=False).toImage()
on = icon_kit.pixmap("fillet", 24, 2).toImage()
assert off != on and any(off.pixelColor(x, y).alpha() > 0 for y in range(48) for x in range(48)), "the greyed icon"

# ---- the one palette: changing it in LOOK changes the icon
before = icon_kit.image("fillet", 24, 2)
saved = dict(icon_kit.LOOK)
try:
    icon_kit.LOOK["body"] = "#ff00ff"
    icon_kit._cache.clear()
    assert icon_kit.image("fillet", 24, 2) != before
finally:
    icon_kit.LOOK.update(saved)
    icon_kit._cache.clear()
assert icon_kit.image("fillet", 24, 2) == before

# ---- a drawing cannot be registered twice with different pictures
try:
    icon_kit.register({"fillet": ('<path class="b" d="M1 1h2v2z"/>', "feat")})
    raise AssertionError("a second drawing of the same name was accepted")
except ValueError:
    pass
icon_kit.register({"fillet": icon_kit._SHAPES["fillet"]})                      # (the same drawing again is fine)

# ---- every ribbon label of the part / assembly windows (and the menu entries) has a drawing
LABELS = ["Sketch", "Exit Sketch", "Exit Sketch (Esc)", "Normal To", "Select", "Line", "Centerline", "Rectangle", "Circle", "Arc", "Spline", "Slot", "Polygon", "Point",
          "Sketch Fillet", "Trim", "Trim Entities", "Offset", "Offset Entities", "Mirror Entities", "Sketch Pattern", "Linear Pattern", "Move Entities", "Construction",
          "Convert Entities", "Add Relation", "Add Relations", "Dimension", "Extruded Boss/Base", "Revolved Boss/Base", "Swept Boss/Base", "Lofted Boss/Base",
          "Extruded Cut", "Revolved Cut", "Swept Cut", "Lofted Cut", "Reference Geometry", "Fillet", "Chamfer", "Shell", "Mirror", "Part Generator", "Wrap", "Boundary Boss/Base",
          "Boundary Cut", "Rib", "Draft", "Intersect", "Mass Properties", "Measure", "Insert Components", "Edit Component", "Mate", "Linear Component Pattern",
          "Mirror Components", "Tab Tree", "Tab Properties", "Tab Configurations", "Tab Equations", "Tab Display", "1D FEA\n(frames)", "1D FEA", "2D FEA", "2D CFD",
          "New Render", "Preview / Render"]
for lab in LABELS:
    assert icons.icon(lab) is not None and not icons.icon(lab).isNull(), lab
    k = icons.key_of(lab) or icon_set.LABELS.get(lab.lower().replace("\n", " "))
    assert k and icon_kit.has(k), (lab, k)
assert icons.icon("not a button") is None

# ---- every tab kind, tree feature and tree glyph has one
for kind in icon_set.TAB_KIND:
    assert icon_set.for_tab(kind) is not None, kind
for kind in icon_set.FEATURE:
    assert icon_set.for_feature(kind) is not None, kind
for g, k in icon_set.GLYPH.items():
    assert icon_kit.has(k), (g, k)
for k in icon_set.LABELS.values():
    assert icon_kit.has(k), k

# ---- mate types and load types
import asm_model as am
assert set(am.TYPES) <= set(mate_icons.NAMES)
for n in mate_icons.NAMES:
    assert icon_kit.has("m_" + n) and not mate_icons.icon(n).isNull() and not mate_icons.pixmap(n, 24).isNull(), n
assert {k[2:] for k in KEYS if k.startswith("m_")} == set(mate_icons.NAMES)
import sim_icons
assert icon_kit.keys() and {k[2:] for k in KEYS if k.startswith("l_")} == set(sim_icons.NAMES)
for n in sim_icons.NAMES:
    assert not sim_icons.icon(n).isNull() and sim_icons.pixmap(n, 48).width() > 0, n

# ---- an older core (no icon kit): the simulation add-on draws its own icons as before
saved_mod = sys.modules.get("icon_kit")
try:
    sys.modules["icon_kit"] = None                                              # (an import of it now fails, like on a core that has none)
    old = importlib.reload(sim_icons)
    assert old.icon_kit is None
    for n in old.NAMES:
        pm = old.pixmap(n, 48)
        assert not pm.isNull() and any(pm.toImage().pixelColor(x, y).alpha() > 0 for x in range(0, 48, 2) for y in range(0, 48, 2)), n
        assert not old.icon(n).isNull(), n
finally:
    sys.modules["icon_kit"] = saved_mod
    importlib.reload(sim_icons)
assert sim_icons.icon_kit is not None

# ---- Sheets: its drawings come with the add-on, share the renderer, and every ribbon button and panel button has one
S = icon_kit.keys()
SHEET_KEYS = [k for k in S if k.startswith("s_")]
assert len(SHEET_KEYS) >= 40 and all(k in sh_icons.SHEETS for k in SHEET_KEYS)
assert not any(k.startswith("s_") for k in icon_shapes.CORE), "Sheets keeps its own drawings"
import sh_tab
t = sh_tab.make_tab()
assert t.ribbon_buttons
for b in t.ribbon_buttons:
    assert icon_kit.has(b.icon_key), (b.label, b.icon_key)
    assert not b.grab().isNull()
assert len({b.icon_key for b in t.ribbon_buttons}) >= 38, "most buttons have a drawing of their own"
for key in ("s_pick_range", "s_remove", "s_more"):
    assert icon_kit.has(key) and not sh_icons.icon(key, 16).isNull(), key
assert not sh_icons.pixmap("s_new", 24, 1).isNull()
src = "".join(open(os.path.join(HERE, "dev_addons", "sheets", f), encoding="utf-8").read() for f in ("sh_tab.py", "sh_panel.py", "sh_dialogs.py", "sh_ribbon.py"))
for ch in "▢▤▣▧⎘✂⧉▩⊕⊖⤓⤒⌫↶↷⇩⟳▥▦☰⊞⊟⇉◔✎⇪✕ƒ☷⋯":
    assert ch not in src.replace("✕ puts", ""), ("a text glyph is left in the Sheets code", ch)

print("OK test_icon_kit")
