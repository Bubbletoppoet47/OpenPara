"""The theme and palette checker (tools/check_palette.py): the palette it builds is the icon kit's (LOOK, HUES and the tones the kit draws) and palette.json's;
a colour that is not in it is found in the strings of a .py file (not its comments), in .qss and .svg, in rgb( ) and QColor(r, g, b); a file that is not in the
baseline must be all palette, a file that is may not use an old colour more often than before; the baseline only goes down; the program passes.
python test_palette.py"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
spec = importlib.util.spec_from_file_location("check_palette", os.path.join(HERE, "tools", "check_palette.py"))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


pal = cp.palette()
T = tempfile.mkdtemp(prefix="opara_pal_")


def write(name, text):
    p = os.path.join(T, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# ---- the palette
kit = cp.kit_colours()
ok(cp.norm("#10204D") in pal and kit[cp.norm("#10204d")] == "kit ink", "the navy ink is in the palette")
ok(cp.norm("#cbd3e0") in pal and cp.norm("#ffffff") in pal, "the body grey and the paper are in the palette")
for h in ("#2f6fed", "#d6453d", "#c27a00", "#0e9488", "#7c4dcc", "#5f6b7a", "#b83280", "#2e8b57"):
    ok(h in pal, f"the hue {h} is in the palette")
ok(sum(1 for n in kit.values() if "as drawn" in n) == 32, "four tones of each of the eight hues, as the kit draws them (32)")
ok("#8793ad" in pal and "#1f3a6e" in pal and "#cfe3fb" in pal, "the Workbench and ribbon colours of palette.json are in the palette")
ok(cp.norm("#FFF") == "#ffffff" and cp.norm("#AbC") == "#aabbcc", "#rgb is read as #rrggbb")

try:                                                                           # what the kit draws is what the checker thinks it draws
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import icon_kit
except Exception:                                                              # noqa: BLE001  (no Qt here: the rest of the test does not need it)
    icon_kit = None
if icon_kit is not None:
    missing = [(k, t) for k in icon_kit.HUES for t, v in icon_kit._tone(k).items() if cp.norm(v) not in pal]
    ok(not missing, f"every tone the kit works out is in the palette {missing[:2] if missing else ''}")
    ok(all(cp.norm(v) in pal for v in icon_kit.HUES.values()) and all(cp.norm(icon_kit.LOOK[k]) in pal for k in ("ink", "body", "paper", "hi", "lo", "grey")),
       "every hue and every LOOK colour of the kit is in the palette")

# ---- finding colours
f = write("a.py", 'from PyQt6.QtGui import QColor\n'
                  'A = QColor("#d6453d")                       # on the palette (a hue of the kit)\n'
                  'B = QColor("#123456")                       # not\n'
                  '# C = "#ff00ff" a comment is not a colour\n'
                  'S = "QToolButton{color:#abc;} x{background: rgb(1, 2, 3);}"\n'
                  'Q = QColor(10, 20, 30)\n'
                  'N = "see item #631 and issue #123"\n'
                  'G = f"{x} #aabbcc {y}"\n')
found = cp.colours_in(f)
hs = [h for _n, h in found]
ok("#123456" in hs and "#aabbcc" in hs, "#rrggbb in a string and in an f-string is found")
ok("#ff00ff" not in hs, "a colour in a comment is not read")
ok("#010203" in hs and "#0a141e" in hs, "rgb( ) in a string and QColor(r, g, b) are found")
ok("#aabbcc" in hs and hs.count("#aabbcc") == 2, "#abc after a colon is read as #aabbcc")
ok("#663311" not in hs and "#112233" not in hs, "'#631' and '#123' in a sentence are not colours")
ok(cp.off_palette(f, pal) and all(h not in pal for _n, h in cp.off_palette(f, pal)), "off_palette lists only what is not in the palette")
ok("#d6453d" not in [h for _n, h in cp.off_palette(f, pal)], "a hue of the kit passes")
q = write("w.qss", "QPushButton { background: #2f6fed; border: 1px solid #ff8800; }\n")
ok([h for _n, h in cp.off_palette(q, pal)] == ["#ff8800"], "a .qss file is read as it is")
s = write("i.svg", '<svg><path fill="#10204d"/><circle fill="#00ff00"/></svg>\n')
ok([h for _n, h in cp.off_palette(s, pal)] == ["#00ff00"], "an .svg file is read as it is")
b = write("broken.py", 'x = "#ff0000"\nif (\n')
ok(any(h == "#ff0000" for _n, h in cp.colours_in(b)), "a file that does not tokenise is still read")

# ---- the nearest colour
near, name, d = cp.nearest("#2f70ee", pal)
ok(near == "#2f6fed" and d < 3, "the nearest palette colour is named: #2f70ee -> #2f6fed")

# ---- the rules: a file that is not in the baseline is strict, a file that is may not get worse
lines = []
rel_a = "a.py"
probs, slack = cp.check([rel_a], pal, {}, say=lines.append, root=T)
ok(probs == 5 and any("not in the baseline" in ln for ln in lines), f"a file that is not in the baseline: every off-palette colour is a problem ({probs}: #123456, #aabbcc twice, rgb(1, 2, 3), QColor(10, 20, 30))")
now = cp.counts(cp.off_palette(f, pal))
probs, slack = cp.check([rel_a], pal, {rel_a: now}, say=lambda *_a: None, root=T)
ok(probs == 0 and slack == 0, "a file whose old colours are in the baseline passes")
worse = {rel_a: {h: n for h, n in now.items() if h != "#123456"}}
probs, slack = cp.check([rel_a], pal, worse, say=lambda *_a: None, root=T)
ok(probs == 1, "a colour that is not in the baseline is a problem")
more = write("a.py", open(f, encoding="utf-8").read() + 'D = QColor("#123456")\n')
probs, slack = cp.check([rel_a], pal, {rel_a: now}, say=lambda *_a: None, root=T)
ok(probs == 1, "an old colour used one more time than the baseline allows is a problem")
write("a.py", 'A = QColor("#d6453d")\n')
probs, slack = cp.check([rel_a], pal, {rel_a: now}, say=lambda *_a: None, root=T)
ok(probs == 0 and slack == sum(now.values()), f"a file that got better passes and the baseline says it can go down ({slack})")

# ---- the baseline only goes down
base = {"x.py": {"#111111": 3, "#222222": 1}, "y.py": {"#333333": 2}}
new = cp.tightened(base, {"x.py": {"#111111": 1, "#999999": 5}, "z.py": {"#444444": 9}})
ok(new == {"x.py": {"#111111": 1}}, "tightened: counts go down, gone colours go, nothing is added")
bp = os.path.join(T, "baseline.json")
cp.save_baseline(base, bp)
ok(cp.load_baseline(bp) == base, "the baseline is written and read back")

# ---- the program itself
files = cp.tracked()
ok(len(files) > 100 and "icon_kit.py" not in files and not any(os.path.basename(x).startswith("test_") for x in files), f"the program files are found ({len(files)}), the kit and the tests are not among them")
lines = []
probs, slack = cp.check(files, pal, cp.load_baseline(), say=lines.append)
ok(probs == 0, "the program has no colour that is not in the palette or the baseline" + ("" if probs == 0 else "\n    " + "\n    ".join(lines[:6])))
ok(os.path.isfile(cp.PALETTE_JSON) and json.load(open(cp.PALETTE_JSON, encoding="utf-8"))["tiers"], "planning/design/theme/palette.json is there")

shutil.rmtree(T, ignore_errors=True)
print()
print("FAILURES:" if FAILS else "all passed", len(FAILS) if FAILS else "")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
